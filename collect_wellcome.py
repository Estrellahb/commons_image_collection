#!/usr/bin/env python3
"""Download & register curated Wellcome Collection IIIF v2 scientific plates."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from io import BytesIO
import json
from pathlib import Path
import re
import time
from typing import Any

import numpy as np
from PIL import Image
import requests

from local_registry import atomic_write_bytes, register_local_claims


DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "img" / "科学图像" / "Wellcome_IIIF"
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "采集数据.sqlite"

WELLCOME_CATALOGUE_API = "https://api.wellcomecollection.org/catalogue/v2/works"
WELLCOME_IIIF_PRES_BASE = "https://iiif.wellcomecollection.org/presentation/v2"

MAX_IMAGE_BYTES = 3_000_000
MAX_IMAGE_SIDE = 2048
MIN_IMAGE_DIM = 700
DEFAULT_TARGET_COUNT = 36

ALLOWED_LICENSE_IDS = {"pdm", "cc0", "cc-by", "cc-by-sa"}

# Curated standalone workType=k / short IIIF Presentation v2 manifests verified for
# scientific plates, charts, astronomy diagrams, anatomical/acupuncture figures, etc.
CURATED_STANDALONE_MANIFESTS: list[dict[str, Any]] = [
    {"mid": "b11846173", "domain": "botany_grid", "max_canvases": 1},
    {"mid": "b12039895", "domain": "astronomy", "max_canvases": 1},
    {"mid": "b14650046", "domain": "astronomy", "max_canvases": 1},
    {"mid": "b14650058", "domain": "astronomy", "max_canvases": 1},
    {"mid": "b12042018", "domain": "astronomy", "max_canvases": 1},
    {"mid": "b14982523", "domain": "astronomy", "max_canvases": 1},
    {"mid": "b15833203", "domain": "anatomy_chart", "max_canvases": 1},
    {"mid": "b15676614", "domain": "anatomy_chart", "max_canvases": 1},
    {"mid": "b11985136", "domain": "anatomy_chart", "max_canvases": 1},
    {"mid": "b15791932", "domain": "zoology", "max_canvases": 1},
]

# Multi-canvas copperplate scientific atlases scored by thumbnail ink density.
CURATED_ATLAS_MANIFESTS: list[dict[str, Any]] = [
    {"mid": "b30456605", "domain": "microscopy", "limit": 8, "min_idx": 5, "scan_limit": 50},
    {"mid": "b29292396", "domain": "osteology", "limit": 5, "min_idx": 5, "scan_limit": 50},
    {"mid": "b33521724", "domain": "neuroanatomy", "limit": 5, "min_idx": 10, "scan_limit": 55},
    {"mid": "b2492460x", "domain": "botany_plate", "limit": 4, "min_idx": 5, "scan_limit": 45},
    {"mid": "b30448724", "domain": "natural_history", "limit": 4, "min_idx": 5, "scan_limit": 45},
]

# Catalogue v2 fallback/expansion queries for rich scientific plates & diagrams.
CATALOGUE_QUERIES: list[tuple[str, str]] = [
    ("microscope", "microscopy"),
    ("astronomy", "astronomy"),
    ("skeleton", "osteology"),
    ("entomology", "zoology"),
    ("botanical", "botany_plate"),
    ("anatomy", "anatomy_chart"),
]

SCIENTIFIC_TITLE_ALLOW = re.compile(
    r"\b("
    r"microscope|microscop|cell|anatomy|anatomical|skeleton|bones?|nerves?|vascular|"
    r"astronomy|planet|solar|star\s*map|constellation|eclipse|longitude|latitude|"
    r"botanic(?:al)?|plant|flora|herbarium|plan|diagram|chart|map|plate|figures?|"
    r"insect|butterfly|beetle|fish(?:es)?|shell|crustacea|reptile|spider|mollusc|"
    r"opti(?:cs|cal)|apparatus|instrument|cranium|muscle|heart|acupuncture"
    r")\b",
    re.IGNORECASE,
)

TITLE_EXCLUDE = re.compile(
    r"\b(portrait|caricature|cartoon|satire|satirical|building\s+facade|interior\s+of\s+the)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PlateCandidate:
    """Normalized Wellcome IIIF plate candidate prior to full download."""

    item_id: str
    manifest_id: str
    canvas_index: int
    domain: str
    title: str
    license_id: str
    license_url: str
    service_url: str
    source_url: str
    ink_ratio: float
    dark_core_ratio: float


def normalize_license(raw_license: Any) -> tuple[str, str]:
    """Normalize a Wellcome Catalogue or IIIF v2 license value to (code, url).

    Rejects NC / ND / in-copyright / unknown values with ("", "").
    """
    if isinstance(raw_license, dict):
        lic_id = str(raw_license.get("id") or "").strip().lower()
        lic_url = str(raw_license.get("url") or "").strip()
        if lic_id in ALLOWED_LICENSE_IDS:
            return lic_id, lic_url
        raw_str = lic_url or lic_id
    else:
        raw_str = str(raw_license or "").strip()

    low = raw_str.lower()
    if not low:
        return "", ""
    if any(bad in low for bad in ("/by-nc", "/by-nd", "inc/", "rightsstatements.org/vocab/inc", "in-copyright")):
        return "", ""
    if "publicdomain/mark" in low or low == "pdm":
        return "pdm", raw_str if raw_str.startswith("http") else "https://creativecommons.org/publicdomain/mark/1.0/"
    if "publicdomain/zero" in low or low == "cc0":
        return "cc0", raw_str if raw_str.startswith("http") else "https://creativecommons.org/publicdomain/zero/1.0/"
    if re.search(r"/licenses/by-sa(?:/|$)", low) or low == "cc-by-sa":
        return "cc-by-sa", raw_str
    if re.search(r"/licenses/by(?:/|$)", low) or low == "cc-by":
        return "cc-by", raw_str
    return "", ""


def compute_ink_metrics(img_bytes: bytes) -> tuple[int, int, float, float]:
    """Return (width, height, ink_ratio, dark_core_ratio) from thumbnail bytes."""
    with Image.open(BytesIO(img_bytes)) as im:
        gray = np.asarray(im.convert("L"), dtype=np.uint8)
    h, w = gray.shape
    ink = float(np.mean(gray < 170))
    # Exclude margins so border toning or scanner frames do not count as plate ink.
    y0, y1 = int(h * 0.12), int(h * 0.88)
    x0, x1 = int(w * 0.12), int(w * 0.88)
    core = gray[y0:y1, x0:x1] if y1 > y0 and x1 > x0 else gray
    dark_core = float(np.mean(core < 140))
    return w, h, round(ink, 4), round(dark_core, 4)


def extract_manifest_canvases(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract (canvas_index, label, service_url, license) dicts from IIIF v2 JSON."""
    seqs = manifest.get("sequences") or []
    if not seqs:
        return []
    manifest_license = manifest.get("license") or ""
    canvases = seqs[0].get("canvases") or []
    out: list[dict[str, Any]] = []
    for idx, canvas in enumerate(canvases):
        images = canvas.get("images") or []
        if not images:
            continue
        res = images[0].get("resource") or {}
        svc = res.get("service") or {}
        if isinstance(svc, list):
            svc = svc[0] if svc else {}
        svc_url = str(svc.get("@id") or svc.get("id") or "").rstrip("/")
        if not svc_url:
            continue
        raw_lic = canvas.get("license") or manifest_license
        out.append(
            {
                "canvas_index": idx,
                "label": str(canvas.get("label") or ""),
                "service_url": svc_url,
                "raw_license": raw_lic,
                "width": int(canvas.get("width") or 0),
                "height": int(canvas.get("height") or 0),
            }
        )
    return out


def fetch_json(session: requests.Session, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fetch JSON with polite retry on transient errors/429s."""
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            resp = session.get(url, params=params, timeout=25)
            if resp.status_code in (429, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_err = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"Failed JSON GET {url}: {last_err}")


def fetch_image_bytes(session: requests.Session, service_url: str, size_spec: str) -> bytes:
    """Download an IIIF Image API derivative with fallback size syntax."""
    candidates = [f"{service_url}/full/{size_spec}/0/default.jpg"]
    if size_spec != "full":
        candidates.append(f"{service_url}/full/max/0/default.jpg")
    last_err: Exception | None = None
    for url in candidates:
        for attempt in range(3):
            try:
                resp = session.get(url, timeout=35)
                if resp.status_code in (429, 502, 503, 504):
                    time.sleep(1.2 * (attempt + 1))
                    continue
                if resp.status_code == 400 and url != candidates[-1]:
                    break
                resp.raise_for_status()
                return resp.content
            except requests.RequestException as exc:
                last_err = exc
                time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"Failed IIIF image fetch {service_url} ({size_spec}): {last_err}")


def encode_plate_jpeg(
    raw_bytes: bytes,
    max_side: int = MAX_IMAGE_SIDE,
    max_bytes: int = MAX_IMAGE_BYTES,
) -> tuple[bytes, int, int]:
    """Normalize downloaded bytes to RGB JPEG within max_side and max_bytes."""
    with Image.open(BytesIO(raw_bytes)) as im:
        rgb = im.convert("RGB")
        if max(rgb.size) > max_side:
            rgb.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

        for scale in (1.0, 0.85, 0.72):
            cur = rgb
            if scale < 1.0:
                cur = rgb.resize(
                    (max(1, int(rgb.width * scale)), max(1, int(rgb.height * scale))),
                    Image.Resampling.LANCZOS,
                )
            for quality in (90, 84, 78, 70):
                buf = BytesIO()
                cur.save(buf, format="JPEG", quality=quality, optimize=True)
                data = buf.getvalue()
                if len(data) <= max_bytes:
                    return data, cur.width, cur.height
        raise ValueError(f"Could not fit image within {max_bytes} bytes")


def assign_wellcome_annotations(candidate: PlateCandidate, width: int, height: int) -> dict[str, str]:
    """Assign image_tags-compliant metadata for a Wellcome scientific plate."""
    title_low = candidate.title.lower()
    domain = candidate.domain

    if domain == "astronomy" or any(k in title_low for k in ("astron", "planet", "star", "longitude", "latitude")):
        q_types = "localization_measurement,spatial_transform,domain_decoding,complex_instruction"
        d_tags = "small_target,cross_region_alignment,multi_hop_visual"
        diff = "hard"
    elif domain in ("osteology", "neuroanatomy", "anatomy_chart") or any(
        k in title_low for k in ("bone", "nerve", "acupuncture", "phrenolog", "anatomy", "skeleton")
    ):
        q_types = "topology_tracking,localization_measurement,domain_decoding,robust_ocr"
        d_tags = "branching_paths,high_density,small_target,multi_hop_visual"
        diff = "hard"
    elif domain in ("botany_grid", "microscopy") or "227 figures" in title_low or candidate.dark_core_ratio >= 0.08:
        q_types = "counting,localization_measurement,domain_decoding,robust_ocr"
        d_tags = "high_density,small_target,high_similarity,multi_hop_visual"
        diff = "hard"
    else:
        q_types = "localization_measurement,domain_decoding,robust_ocr"
        d_tags = "small_target,cluttered_bg,multi_hop_visual"
        diff = "hard" if min(width, height) >= 1200 and candidate.ink_ratio >= 0.10 else "medium"

    notes = (
        f"Wellcome IIIF v2 ({candidate.license_id.upper()}), domain={domain}, "
        f"ink={candidate.ink_ratio:.3f}, dark_core={candidate.dark_core_ratio:.3f}; "
        f"title={candidate.title[:90]}"
    )
    return {
        "question_types": q_types,
        "difficulty": diff,
        "difficulty_tags": d_tags,
        "tag_notes": notes,
        "authored_status": "",
        "authored_ref": "",
    }


def collect_standalone_candidates(
    session: requests.Session,
    specs: list[dict[str, Any]],
) -> list[PlateCandidate]:
    """Collect verified standalone Wellcome IIIF v2 works."""
    results: list[PlateCandidate] = []
    seen_services: set[str] = set()
    for spec in specs:
        mid = spec["mid"]
        try:
            manifest = fetch_json(session, f"{WELLCOME_IIIF_PRES_BASE}/{mid}")
        except Exception as exc:
            print(f"[SKIP] standalone manifest {mid}: {exc}")
            continue
        title = str(manifest.get("label") or mid)
        canvases = extract_manifest_canvases(manifest)
        taken = 0
        for c in canvases:
            if taken >= int(spec.get("max_canvases", 1)):
                break
            lic_id, lic_url = normalize_license(c["raw_license"])
            svc = c["service_url"]
            if not lic_id or svc in seen_services:
                continue
            try:
                thumb = fetch_image_bytes(session, svc, "!400,400")
                _, _, ink, dark_core = compute_ink_metrics(thumb)
            except Exception as exc:
                print(f"[SKIP] thumb {mid} p{c['canvas_index']}: {exc}")
                continue
            if ink < 0.04:
                continue
            seen_services.add(svc)
            idx = c["canvas_index"] + 1
            results.append(
                PlateCandidate(
                    item_id=f"wellcome-{mid}-p{idx:03d}",
                    manifest_id=mid,
                    canvas_index=idx,
                    domain=spec["domain"],
                    title=title,
                    license_id=lic_id,
                    license_url=lic_url,
                    service_url=svc,
                    source_url=f"https://wellcomecollection.org/works?query={mid}",
                    ink_ratio=ink,
                    dark_core_ratio=dark_core,
                )
            )
            taken += 1
        time.sleep(0.1)
    return results


def collect_atlas_candidates(
    session: requests.Session,
    specs: list[dict[str, Any]],
    seen_services: set[str],
) -> list[PlateCandidate]:
    """Score multi-canvas scientific atlases and return dense copperplate engravings."""
    results: list[PlateCandidate] = []
    for spec in specs:
        mid = spec["mid"]
        try:
            manifest = fetch_json(session, f"{WELLCOME_IIIF_PRES_BASE}/{mid}")
        except Exception as exc:
            print(f"[SKIP] atlas manifest {mid}: {exc}")
            continue
        title = str(manifest.get("label") or mid)
        canvases = extract_manifest_canvases(manifest)
        min_idx = int(spec.get("min_idx", 4))
        scan_limit = int(spec.get("scan_limit", 50))
        scored: list[PlateCandidate] = []
        for c in canvases[min_idx : min_idx + scan_limit]:
            svc = c["service_url"]
            if svc in seen_services:
                continue
            lic_id, lic_url = normalize_license(c["raw_license"])
            if not lic_id:
                continue
            try:
                thumb = fetch_image_bytes(session, svc, "!400,400")
                _, _, ink, dark_core = compute_ink_metrics(thumb)
            except Exception:
                continue
            # Engraved plates carry heavy line-art core density compared to blank versos.
            if ink < 0.11 or dark_core < 0.07:
                continue
            idx = c["canvas_index"] + 1
            scored.append(
                PlateCandidate(
                    item_id=f"wellcome-{mid}-p{idx:03d}",
                    manifest_id=mid,
                    canvas_index=idx,
                    domain=spec["domain"],
                    title=title,
                    license_id=lic_id,
                    license_url=lic_url,
                    service_url=svc,
                    source_url=f"{WELLCOME_IIIF_PRES_BASE}/{mid}",
                    ink_ratio=ink,
                    dark_core_ratio=dark_core,
                )
            )
        scored.sort(key=lambda x: (x.dark_core_ratio, x.ink_ratio), reverse=True)
        for cand in scored[: int(spec.get("limit", 5))]:
            seen_services.add(cand.service_url)
            results.append(cand)
    return results


def collect_catalogue_candidates(
    session: requests.Session,
    queries: list[tuple[str, str]],
    seen_services: set[str],
    needed: int,
) -> list[PlateCandidate]:
    """Query Wellcome Catalogue v2 for additional standalone scientific plates."""
    if needed <= 0:
        return []
    results: list[PlateCandidate] = []
    seen_works: set[str] = set()
    for query, domain in queries:
        if len(results) >= needed:
            break
        try:
            payload = fetch_json(
                session,
                WELLCOME_CATALOGUE_API,
                params={
                    "query": query,
                    "workType": "k",
                    "items.locations.locationType": "iiif-image",
                    "include": "items",
                    "pageSize": 25,
                },
            )
        except Exception as exc:
            print(f"[SKIP] catalogue query {query!r}: {exc}")
            continue
        for work in payload.get("results") or []:
            if len(results) >= needed:
                break
            wid = str(work.get("id") or "").strip()
            title = str(work.get("title") or "").strip()
            if not wid or wid in seen_works:
                continue
            if TITLE_EXCLUDE.search(title) or not SCIENTIFIC_TITLE_ALLOW.search(title):
                continue
            for item in work.get("items") or []:
                picked = False
                for loc in item.get("locations") or []:
                    if (loc.get("locationType") or {}).get("id") != "iiif-image":
                        continue
                    lic_id, lic_url = normalize_license(loc.get("license"))
                    svc = str(loc.get("url") or "").removesuffix("/info.json").rstrip("/")
                    if not lic_id or not svc or svc in seen_services:
                        continue
                    try:
                        thumb = fetch_image_bytes(session, svc, "!400,400")
                        _, _, ink, dark_core = compute_ink_metrics(thumb)
                    except Exception:
                        continue
                    if ink < 0.05:
                        continue
                    seen_works.add(wid)
                    seen_services.add(svc)
                    results.append(
                        PlateCandidate(
                            item_id=f"wellcome-{wid}",
                            manifest_id=wid,
                            canvas_index=1,
                            domain=domain,
                            title=title,
                            license_id=lic_id,
                            license_url=lic_url,
                            service_url=svc,
                            source_url=f"https://wellcomecollection.org/works/{wid}",
                            ink_ratio=ink,
                            dark_core_ratio=dark_core,
                        )
                    )
                    picked = True
                    break
                if picked:
                    break
        time.sleep(0.1)
    return results


def write_attribution(meta_dir: Path, saved_count: int) -> None:
    """Write human-readable Wellcome IIIF v2 license and source attribution."""
    text = (
        "Wellcome Collection IIIF v2 公版/开放许可科学图版与博物插图数据集\n"
        f"精选数量: {saved_count}\n"
        "API 入口: https://api.wellcomecollection.org/catalogue/v2/works 与 "
        "https://iiif.wellcomecollection.org/presentation/v2/{manifest_id}\n"
        "许可范围: 仅收录逐条核验为 Public Domain Mark 1.0 (pdm)、CC0 1.0 (cc0)、"
        "CC BY (cc-by) 或 CC BY-SA (cc-by-sa) 的条目（严格过滤 NC/ND/InC）。\n"
        "用途说明: 显微铜版图鉴、天文星图与经纬图解、解剖/骨骼/神经图谱、植物细胞与标本插图；"
        "所有 JPG 已统一限制在 2048px 与 3 MB 以内。\n"
    )
    atomic_write_bytes(meta_dir / "来源与许可.txt", text.encode("utf-8"))


def run_collection(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    db_path: Path = DEFAULT_DB_PATH,
    target_count: int = DEFAULT_TARGET_COUNT,
    standalone_specs: list[dict[str, Any]] | None = None,
    atlas_specs: list[dict[str, Any]] | None = None,
    catalogue_queries: list[tuple[str, str]] | None = None,
    session: requests.Session | None = None,
    force_tags: bool = False,
) -> tuple[int, int, int]:
    """Collect Wellcome IIIF plates, convert to JPG, write manifest, and register DB claims."""
    jpg_dir = output_dir / "JPG"
    meta_dir = output_dir / "元数据"
    jpg_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    http = session or requests.Session()
    http.headers.setdefault("User-Agent", "ZeroBenchCommonsCollector/1.0 (+https://wellcomecollection.org)")

    s_specs = CURATED_STANDALONE_MANIFESTS if standalone_specs is None else standalone_specs
    a_specs = CURATED_ATLAS_MANIFESTS if atlas_specs is None else atlas_specs
    c_queries = CATALOGUE_QUERIES if catalogue_queries is None else catalogue_queries

    candidates = collect_standalone_candidates(http, s_specs)
    seen_services = {c.service_url for c in candidates}
    if len(candidates) < target_count:
        candidates.extend(collect_atlas_candidates(http, a_specs, seen_services))
    if len(candidates) < target_count:
        candidates.extend(
            collect_catalogue_candidates(
                http,
                c_queries,
                seen_services,
                needed=max(0, target_count - len(candidates) + 6),
            )
        )

    img_root = output_dir.parent.parent
    manifest_records: list[dict[str, Any]] = []
    registry_records: list[dict[str, Any]] = []

    for cand in candidates:
        if len(manifest_records) >= target_count:
            break
        try:
            raw = fetch_image_bytes(http, cand.service_url, f"!{MAX_IMAGE_SIDE},{MAX_IMAGE_SIDE}")
            jpg_bytes, width, height = encode_plate_jpeg(raw)
        except Exception as exc:
            print(f"[SKIP] download {cand.item_id}: {exc}")
            continue

        if min(width, height) < MIN_IMAGE_DIM:
            print(f"[SKIP] {cand.item_id} too small: {width}x{height}")
            continue

        filename = f"{cand.item_id}.jpg"
        out_path = jpg_dir / filename
        atomic_write_bytes(out_path, jpg_bytes)
        try:
            img_relpath = out_path.relative_to(img_root).as_posix()
        except ValueError:
            img_relpath = f"科学图像/{output_dir.name}/JPG/{filename}"

        annotations = assign_wellcome_annotations(cand, width, height)
        rec = {
            "item_id": cand.item_id,
            "manifest_id": cand.manifest_id,
            "canvas_index": cand.canvas_index,
            "domain": cand.domain,
            "title": cand.title,
            "license": cand.license_id,
            "license_url": cand.license_url,
            "iiif_service": cand.service_url,
            "source_url": cand.source_url,
            "width": width,
            "height": height,
            "file_size_bytes": len(jpg_bytes),
            "ink_ratio": cand.ink_ratio,
            "dark_core_ratio": cand.dark_core_ratio,
            "img_relpath": img_relpath,
            "annotations": annotations,
        }
        manifest_records.append(rec)
        registry_records.append(rec)
        print(
            f"[OK] {cand.item_id} ({cand.domain}, {cand.license_id}): "
            f"{width}x{height} {len(jpg_bytes) // 1024}KB diff={annotations['difficulty']}"
        )
        time.sleep(0.1)

    manifest_lines = "\n".join(json.dumps(r, ensure_ascii=False) for r in manifest_records)
    if manifest_lines:
        manifest_lines += "\n"
    atomic_write_bytes(meta_dir / "plates_manifest.jsonl", manifest_lines.encode("utf-8"))
    write_attribution(meta_dir, len(manifest_records))

    inserted, updated = register_local_claims(db_path, registry_records, force_tags=force_tags)
    return len(manifest_records), inserted, updated


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect and register Wellcome IIIF v2 scientific plates.")
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    p.add_argument("--target-count", type=int, default=DEFAULT_TARGET_COUNT)
    p.add_argument("--force-tags", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    count, inserted, updated = run_collection(
        output_dir=args.output_dir,
        db_path=args.db_path,
        target_count=args.target_count,
        force_tags=args.force_tags,
    )
    print(f"Summary: saved={count} db_inserted={inserted} db_updated={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
