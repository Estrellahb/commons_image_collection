"""Collect high-density CC0 public domain objects from The Metropolitan Museum of Art."""

import argparse
import csv
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re
import sys
import time

from PIL import Image, ImageOps
import requests

import image_tags
from local_registry import atomic_write_bytes, register_local_claims


ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "采集数据.sqlite"
DEFAULT_IMG_DIR = ROOT / "img"
MET_SUBDIR = Path("小众专业实物") / "Met_CC0"
MET_CSV_URL = "https://media.githubusercontent.com/media/metmuseum/openaccess/master/MetObjects.csv"
MET_OBJECT_API = "https://collectionapi.metmuseum.org/public/collection/v1/objects/{object_id}"
MET_OPENACCESS_POLICY = "https://www.metmuseum.org/about-the-met/policies-and-documents/open-access"
MAX_EDGE_PX = 2048
MAX_BYTES = 3_000_000
MIN_SHORT_EDGE_PX = 600

# Word-boundary regexes per bucket to select visually dense, multi-part, or calibrated objects.
BUCKET_PATTERNS: list[tuple[str, re.Pattern[str], str | None]] = [
    ("sampler", re.compile(r"\bsampler\b", re.I), None),
    ("quilt", re.compile(r"\b(?:patchwork )?quilt\b|\bcoverlet\b", re.I), None),
    ("tiles", re.compile(r"\b(?:wall panel )?tiles?\b|\bmosaic\b|\btile panel\b", re.I), None),
    ("astrolabe_sundial", re.compile(r"\bastrolabe\b|\bsundial\b|\barmillary\b|\bquadrant\b", re.I), None),
    ("pocket_watch", re.compile(r"\bpocket watch\b|\brepeater watch\b|\bclock\b", re.I), None),
    ("instrument", re.compile(r"\bharpsichord\b|\bspinet\b|\bvirginal\b", re.I), None),
    ("game", re.compile(r"\bchess(?:board| set)?\b|\bbackgammon\b", re.I), None),
    ("beads_medal", re.compile(r"\bmedallion\b|\brosary\b|\bcoin\b|\bbuttons\b", re.I), None),
]


def scan_met_openaccess_ids(
    session: requests.Session, *, per_bucket: int = 8, max_rows: int = 750_000
) -> list[dict]:
    """Stream MetObjects.csv to collect diverse Public Domain object IDs without saving the 341MB CSV."""
    buckets: dict[str, list[dict]] = {name: [] for name, _, _ in BUCKET_PATTERNS}
    resp = session.get(MET_CSV_URL, stream=True, timeout=30)
    resp.raise_for_status()
    try:
        line_iter = resp.iter_lines(decode_unicode=True)
        header = next(line_iter)
        cols = [col.lstrip("\ufeff") for col in next(csv.reader([header]))]
        for row_idx, raw_line in enumerate(line_iter, start=1):
            if row_idx > max_rows:
                break
            try:
                vals = next(csv.reader([raw_line]))
            except csv.Error:
                continue
            if len(vals) < len(cols):
                continue
            row = dict(zip(cols, vals))
            if row.get("Is Public Domain") != "True":
                continue
            obj_name = row.get("Object Name", "")
            dept = row.get("Department", "")
            for bucket, pattern, req_dept in BUCKET_PATTERNS:
                if len(buckets[bucket]) >= per_bucket:
                    continue
                if req_dept and dept != req_dept:
                    continue
                if pattern.search(obj_name):
                    buckets[bucket].append({
                        "object_id": int(row["Object ID"]),
                        "bucket": bucket,
                        "department": dept,
                        "object_name": obj_name,
                        "title": row.get("Title", ""),
                    })
            if all(len(items) >= per_bucket for items in buckets.values()):
                break
    finally:
        resp.close()
    selected: list[dict] = []
    for bucket, _, _ in BUCKET_PATTERNS:
        selected.extend(buckets[bucket])
    return selected


def encode_met_jpeg(raw_bytes: bytes, *, max_edge: int = MAX_EDGE_PX, max_bytes: int = MAX_BYTES) -> dict:
    """Decode Met image, normalize orientation/RGB, cap dimensions, and fit within byte limit."""
    with Image.open(BytesIO(raw_bytes)) as src:
        orig_size = src.size
        if min(orig_size) < MIN_SHORT_EDGE_PX:
            raise ValueError(f"分辨率过低 {orig_size}")
        oriented = ImageOps.exif_transpose(src)
        if oriented.mode != "RGB":
            if oriented.has_transparency_data:
                rgba = oriented.convert("RGBA")
                canvas = Image.new("RGB", rgba.size, (245, 245, 245))
                canvas.paste(rgba, mask=rgba.getchannel("A"))
                rgb = canvas
            else:
                rgb = oriented.convert("RGB")
        else:
            rgb = oriented.copy()

    edge = max(rgb.size)
    if edge > max_edge:
        scale = max_edge / edge
        dims = (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale)))
        rgb = rgb.resize(dims, Image.Resampling.LANCZOS, reducing_gap=3)

    while True:
        buf = BytesIO()
        rgb.save(buf, format="JPEG", quality=92, subsampling=0, optimize=True)
        payload = buf.getvalue()
        if len(payload) <= max_bytes or max(rgb.size) <= 600:
            break
        factor = min(0.9, 0.96 * math.sqrt(max_bytes / len(payload)))
        dims = (max(1, round(rgb.width * factor)), max(1, round(rgb.height * factor)))
        rgb = rgb.resize(dims, Image.Resampling.LANCZOS, reducing_gap=3)

    if len(payload) > max_bytes:
        raise ValueError(f"压缩后仍超过 {max_bytes} 字节: {len(payload)}")

    return {
        "payload": payload,
        "source_width": orig_size[0],
        "source_height": orig_size[1],
        "width": rgb.width,
        "height": rgb.height,
        "bytes": len(payload),
    }


def classify_met_item(meta: dict) -> dict[str, str]:
    """Assign ZeroBench candidate tags and difficulty notes by object category."""
    bucket = meta["bucket"]
    obj_name = meta.get("object_name") or bucket
    title = meta.get("title") or obj_name
    dept = meta.get("department") or ""

    mapping = {
        "sampler": (
            ["counting", "robust_ocr", "spatial_transform"],
            ["high_density", "small_target", "high_similarity"],
            "hard",
            "P1/P2候选。绣品纹样/字母行列密集，适合按字母/花纹规则筛选计数或局部例外核对。",
        ),
        "quilt": (
            ["counting", "spatial_transform", "complex_instruction"],
            ["high_density", "high_similarity", "multi_hop_visual"],
            "hard",
            "P1/P2候选。几何拼布纹样重复且常含局部配色/朝向例外，适合规则遵循与方案计数。",
        ),
        "tiles": (
            ["counting", "spatial_transform", "topology_tracking"],
            ["high_density", "high_similarity", "cross_region_alignment"],
            "hard",
            "P1/P2候选。瓷砖/马赛克面板含连续几何边界与拼合对应，适合跨区配对与破损/异色计数。",
        ),
        "astrolabe_sundial": (
            ["localization_measurement", "domain_decoding", "robust_ocr"],
            ["small_target", "multi_hop_visual", "high_density"],
            "hard",
            "P1精密仪器候选。星盘/日晷含刻度盘、游标与多环读数对应，适合多步读数与条件计算。",
        ),
        "pocket_watch": (
            ["localization_measurement", "domain_decoding", "robust_ocr"],
            ["small_target", "high_similarity", "multi_hop_visual"],
            "medium",
            "P1仪器表盘候选。钟表指针/副盘/罗马数字或齿轮结构清晰，适合多刻度读取与校时计算。",
        ),
        "instrument": (
            ["counting", "localization_measurement"],
            ["high_density", "high_similarity", "small_target"],
            "medium",
            "P2专业器物候选。羽管键琴/古钢琴键列及装饰结构重复密集，适合键位计数与状态筛选。",
        ),
        "game": (
            ["game_puzzle", "counting", "localization_measurement"],
            ["high_density", "high_similarity", "cross_region_alignment"],
            "hard",
            "P1/P2盘面实物候选。实拍棋盘/双陆棋盘与棋子摆放可还原盘面状态并附加几何/计数约束。",
        ),
        "beads_medal": (
            ["counting", "localization_measurement"],
            ["high_density", "high_similarity", "small_target"],
            "medium",
            "P2器物序列候选。串珠/徽章序列适合物件分类计数、串序对称性与局部例外定位。",
        ),
    }
    q_list, d_list, diff, rationale = mapping.get(
        bucket,
        (["counting"], ["high_similarity"], "medium", "馆藏实物图，适合对象计数与属性辨析。"),
    )
    norm_q = ",".join(image_tags.normalize_codes(q_list, image_tags.QUESTION_TYPES, "question_types"))
    norm_d = ",".join(image_tags.normalize_codes(d_list, image_tags.DIFFICULTY_TAGS, "difficulty_tags"))

    return {
        "question_types": norm_q,
        "difficulty": diff,
        "difficulty_tags": norm_d,
        "authored_status": "",
        "authored_ref": "",
        "tag_notes": (
            f"Met CC0[{bucket} | ID={meta['object_id']}] {title} ({obj_name}, {dept}) | "
            f"原图 {meta['source_width']}×{meta['source_height']}→保存 {meta['width']}×{meta['height']} | "
            f"许可 CC0 1.0。{rationale}"
        ),
    }


def collect_met(
    *,
    root: Path = ROOT,
    img_dir: Path | None = None,
    db_path: Path | None = None,
    target_count: int = 36,
    per_bucket: int = 7,
    skip_db: bool = False,
    force_tags: bool = False,
) -> dict:
    """Download curated CC0 objects from The Met, convert/compress to JPEG, and register in SQLite."""
    resolved_img_dir = (img_dir or (root / "img")).resolve()
    resolved_db = (db_path or (root / "采集数据.sqlite")).resolve()
    base_dir = resolved_img_dir / MET_SUBDIR
    jpg_dir = base_dir / "JPG"
    meta_dir = base_dir / "元数据"
    jpg_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    skipped: list[dict] = []

    with requests.Session() as session:
        session.headers.update({"User-Agent": "ZeroBenchCommonsCollector/1.0 (Met-CC0-Pipeline)"})
        candidates = scan_met_openaccess_ids(session, per_bucket=per_bucket)
        for cand in candidates:
            if len(records) >= target_count:
                break
            oid = cand["object_id"]
            try:
                time.sleep(0.25)
                obj_resp = session.get(MET_OBJECT_API.format(object_id=oid), timeout=15)
                if obj_resp.status_code == 429:
                    time.sleep(2.0)
                    obj_resp = session.get(MET_OBJECT_API.format(object_id=oid), timeout=15)
                obj_resp.raise_for_status()
                obj = obj_resp.json()
                if not obj.get("isPublicDomain") or not obj.get("primaryImage"):
                    skipped.append({"object_id": oid, "reason": "not public domain or missing primaryImage"})
                    continue

                img_resp = session.get(obj["primaryImage"], timeout=30)
                img_resp.raise_for_status()
                enc = encode_met_jpeg(img_resp.content)

                out_path = jpg_dir / f"met-{oid}.jpg"
                atomic_write_bytes(out_path, enc["payload"])
                sha256 = hashlib.sha256(enc["payload"]).hexdigest()
                img_relpath = out_path.relative_to(resolved_img_dir).as_posix()
                file_relpath = out_path.relative_to(root).as_posix() if out_path.is_relative_to(root) else img_relpath

                item_meta = {
                    "dataset": "MetMuseum_OpenAccess",
                    "object_id": oid,
                    "bucket": cand["bucket"],
                    "department": obj.get("department", cand["department"]),
                    "object_name": obj.get("objectName", cand["object_name"]),
                    "title": obj.get("title", cand["title"]),
                    "culture": obj.get("culture", ""),
                    "object_date": obj.get("objectDate", ""),
                    "medium": obj.get("medium", ""),
                    "dimensions": obj.get("dimensions", ""),
                    "credit_line": obj.get("creditLine", ""),
                    "object_url": obj.get("objectURL", f"https://www.metmuseum.org/art/collection/search/{oid}"),
                    "source_url": obj["primaryImage"],
                    "file": file_relpath,
                    "img_relpath": img_relpath,
                    "source_width": enc["source_width"],
                    "source_height": enc["source_height"],
                    "width": enc["width"],
                    "height": enc["height"],
                    "bytes": enc["bytes"],
                    "sha256": sha256,
                    "license": {
                        "LicenseShortName": "CC0 1.0",
                        "LicenseUrl": "https://creativecommons.org/publicdomain/zero/1.0/",
                        "PolicyUrl": MET_OPENACCESS_POLICY,
                    },
                }
                item_meta["annotations"] = classify_met_item(item_meta)
                records.append(item_meta)
                print(
                    f"[OK] met-{oid} ({cand['bucket']}): {enc['width']}x{enc['height']} "
                    f"{enc['bytes']//1024}KB diff={item_meta['annotations']['difficulty']}",
                    file=sys.stderr,
                    flush=True,
                )
            except Exception as exc:
                skipped.append({"object_id": oid, "reason": str(exc)})

    if records:
        license_note = (
            "The Metropolitan Museum of Art Open Access Collection (CC0 1.0)\n"
            f"Policy: {MET_OPENACCESS_POLICY}\n"
            "API: https://collectionapi.metmuseum.org/public/collection/v1/objects\n"
            "All saved items verified isPublicDomain=true via object API.\n"
        )
        atomic_write_bytes(meta_dir / "来源与许可.txt", license_note.encode("utf-8"))
        manifest_text = "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n"
        atomic_write_bytes(meta_dir / "objects_manifest.jsonl", manifest_text.encode("utf-8"))

    inserted = updated = 0
    if records and not skip_db:
        inserted, updated = register_local_claims(resolved_db, records, force_tags=force_tags)

    diff_counts = {"hard": 0, "medium": 0, "easy": 0}
    for r in records:
        d = r["annotations"]["difficulty"]
        if d in diff_counts:
            diff_counts[d] += 1

    return {
        "saved": len(records),
        "skipped_count": len(skipped),
        "difficulty_counts": diff_counts,
        "db_inserted": inserted,
        "db_updated": updated,
        "out_dir": str(jpg_dir),
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
        sys.stderr.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description="采集 Met Museum CC0 高密度文物/仪器/纹样并入库。")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--img-dir", type=Path, default=None)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--target-count", type=int, default=36)
    parser.add_argument("--per-bucket", type=int, default=7)
    parser.add_argument("--skip-db", action="store_true")
    parser.add_argument("--force-tags", action="store_true")
    args = parser.parse_args(argv)
    summary = collect_met(
        root=args.root.resolve(),
        img_dir=args.img_dir,
        db_path=args.db,
        target_count=args.target_count,
        per_bucket=args.per_bucket,
        skip_db=args.skip_db,
        force_tags=args.force_tags,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
