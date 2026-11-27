"""Download curated high-density SDSS DR18 cutouts paired with SDSS & Gaia DR3 catalogs."""

import argparse
import csv
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image
import requests

import image_tags
from local_registry import atomic_write_bytes, register_local_claims


ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "采集数据.sqlite"
DEFAULT_IMG_DIR = ROOT / "img"
SDSS_SUBDIR = Path("科学图像") / "SDSS_Gaia"
SDSS_CUTOUT_URL = "https://skyserver.sdss.org/dr18/SkyServerWS/ImgCutout/getjpeg"
SDSS_SQL_URL = "https://skyserver.sdss.org/dr18/SkyServerWS/SearchTools/SqlSearch"
GAIA_TAP_URL = "https://gaia.ari.uni-heidelberg.de/tap/sync"
SDSS_POLICY_URL = "https://www.sdss.org/collaboration/image-use-policy/"
SDSS_LICENSE = "CC BY"
GAIA_LICENSE = "CC BY 4.0 IGO"
NATIVE_SCALE_ARCSEC_PX = 0.39612
DEFAULT_WIDTH = 1024
DEFAULT_HEIGHT = 1024
MAX_IMAGE_BYTES = 5_000_000

# Verified dense astronomical targets inside SDSS DR18 coverage.
TARGETS: list[tuple[str, str, float, float]] = [
    # Rich Abell galaxy clusters
    ("Abell_1689", "galaxy_cluster", 197.8730, -1.3410),
    ("Abell_1656_Coma", "galaxy_cluster", 194.9531, 27.9807),
    ("Abell_2199", "galaxy_cluster", 247.1593, 39.5513),
    ("Abell_2029", "galaxy_cluster", 227.7338, 5.7448),
    ("Abell_2142", "galaxy_cluster", 239.5833, 27.2334),
    ("Abell_1795", "galaxy_cluster", 207.2188, 26.5929),
    ("Abell_85", "galaxy_cluster", 10.4603, -9.3031),
    ("Abell_1367_Leo", "galaxy_cluster", 176.1229, 19.8392),
    ("Abell_2065", "galaxy_cluster", 230.6216, 27.7076),
    ("Abell_2255", "galaxy_cluster", 258.1200, 64.0630),
    ("Abell_2670", "galaxy_cluster", 358.5570, -10.4190),
    ("Abell_1991", "galaxy_cluster", 223.6312, 18.6423),
    ("Abell_1413", "galaxy_cluster", 178.8250, 23.4049),
    ("Abell_611", "galaxy_cluster", 120.2367, 36.0566),
    ("Abell_963", "galaxy_cluster", 154.2651, 39.0470),
    ("Abell_1763", "galaxy_cluster", 203.8257, 41.0012),
    ("Abell_2261", "galaxy_cluster", 260.6133, 32.1326),
    ("Abell_2390", "galaxy_cluster", 328.4034, 17.6955),
    ("Abell_370", "galaxy_cluster", 39.9696, -1.5767),
    ("Abell_1185", "galaxy_cluster", 167.6900, 28.6780),
    ("Abell_1213", "galaxy_cluster", 169.1125, 29.2536),
    ("Abell_1314", "galaxy_cluster", 173.7042, 49.0778),
    ("Abell_1775", "galaxy_cluster", 205.4750, 26.3700),
    ("Abell_1800", "galaxy_cluster", 207.3500, 28.1000),
    ("Abell_2052", "galaxy_cluster", 229.1854, 7.0217),
    ("Abell_2063", "galaxy_cluster", 230.7720, 8.6090),
    ("Abell_2151_Hercules", "galaxy_cluster", 241.1492, 17.7217),
    ("Abell_2197", "galaxy_cluster", 246.9200, 40.9200),
    ("Abell_2256", "galaxy_cluster", 255.9500, 78.6400),
    ("Abell_2634", "galaxy_cluster", 354.6224, 27.0313),
    # Compact & interacting galaxy groups
    ("HCG_92_Stephan", "compact_group", 338.9900, 33.9658),
    ("HCG_79_Seyfert", "compact_group", 239.8021, 20.7536),
    ("HCG_31", "compact_group", 75.4050, -4.2581),
    ("HCG_44", "compact_group", 154.5042, 21.8258),
    ("HCG_56", "compact_group", 173.1750, 52.9467),
    ("HCG_68", "compact_group", 208.3958, 40.3517),
    ("Markarian_Chain", "galaxy_group", 186.6337, 13.0083),
    # Globular clusters & outskirts (offset ~6.5-7 arcmin on bright clusters to resolve individual stars)
    ("M3_outskirts_E", "globular_outskirts", 205.5484 + 0.115, 28.3773),
    ("M5_outskirts_N", "globular_outskirts", 229.6384, 2.0810 + 0.110),
    ("M13_outskirts_E", "globular_outskirts", 250.4235 + 0.125, 36.4613),
    ("M15_outskirts_N", "globular_outskirts", 322.4930, 12.1670 + 0.105),
    ("M53_outskirts_N", "globular_outskirts", 198.2302, 18.1682 + 0.095),
    ("M92_outskirts_E", "globular_outskirts", 259.2808 + 0.120, 43.1359),
    ("NGC_2419", "globular_cluster", 114.5354, 38.8819),
    ("NGC_5466", "globular_cluster", 211.3637, 28.5344),
    ("NGC_4147", "globular_cluster", 182.5263, 18.5426),
    ("Palomar_3", "globular_cluster", 151.3801, 0.0717),
    ("Palomar_5", "globular_cluster", 229.0192, -0.1119),
    # Open star clusters
    ("M67_NGC2682", "open_cluster", 132.8250, 11.8000),
    ("NGC_2420", "open_cluster", 114.6025, 21.5733),
    ("NGC_6791", "open_cluster", 290.2208, 37.7717),
    ("NGC_2158", "open_cluster", 91.8542, 24.0958),
]


def sky_to_pixel(
    ra: float,
    dec: float,
    ra0: float,
    dec0: float,
    scale_arcsec_px: float = NATIVE_SCALE_ARCSEC_PX,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> tuple[float, float]:
    """Project ICRS (ra, dec) in degrees to top-left pixel coordinates in SDSS North-up cutouts."""
    cos_dec0 = max(1e-6, math.cos(math.radians(dec0)))
    # Wrap RA difference into [-180, 180] for fields near RA=0/360.
    dra_deg = ((ra - ra0 + 180.0) % 360.0) - 180.0
    dra_arcsec = dra_deg * cos_dec0 * 3600.0
    ddec_arcsec = (dec - dec0) * 3600.0
    px = (width - 1) / 2.0 - dra_arcsec / scale_arcsec_px
    py = (height - 1) / 2.0 - ddec_arcsec / scale_arcsec_px
    return px, py


def angular_separation_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Compute spherical angular separation in arcseconds via haversine."""
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    sd = math.sin((d2 - d1) / 2.0)
    sr = math.sin((r2 - r1) / 2.0)
    a = min(1.0, sd * sd + math.cos(d1) * math.cos(d2) * sr * sr)
    return math.degrees(2.0 * math.asin(math.sqrt(a))) * 3600.0


def count_close_pairs(objects: list[dict], max_arcsec: float = 5.0, min_arcsec: float = 0.5) -> int:
    """Count distinct pairs separated by (min_arcsec, max_arcsec] within the field."""
    if len(objects) < 2:
        return 0
    ordered = sorted(objects, key=lambda o: o["dec"])
    max_deg = max_arcsec / 3600.0 + 1e-6
    pairs = 0
    for i, a in enumerate(ordered):
        for j in range(i + 1, len(ordered)):
            b = ordered[j]
            if b["dec"] - a["dec"] > max_deg:
                break
            sep = angular_separation_arcsec(a["ra"], a["dec"], b["ra"], b["dec"])
            if min_arcsec < sep <= max_arcsec:
                pairs += 1
    return pairs


def evaluate_cutout_pixels(image_bytes: bytes) -> dict:
    """Decode cutout JPEG, verify clean full coverage, and return image quality metrics."""
    with Image.open(BytesIO(image_bytes)) as img:
        if img.format != "JPEG":
            raise ValueError(f"意外格式 {img.format}")
        rgb = img.convert("RGB")
        arr = np.asarray(rgb)
        buf = BytesIO()
        # Strip non-pixel metadata and keep crisp high-quality JPEG.
        rgb.save(buf, format="JPEG", quality=93, subsampling=0)
        clean_bytes = buf.getvalue()
        width, height = rgb.size

    lum = arr.mean(axis=2)
    fg_frac = float((lum > 18).mean())
    sat_frac = float((lum > 245).mean())
    zero_frac = float((lum == 0).mean())
    passed = (
        len(clean_bytes) <= MAX_IMAGE_BYTES
        and fg_frac > 0.01
        and sat_frac < 0.03
        and zero_frac < 0.05
    )
    return {
        "passed": passed,
        "width": width,
        "height": height,
        "clean_bytes": clean_bytes,
        "fg_pct": round(fg_frac * 100.0, 2),
        "sat_pct": round(sat_frac * 100.0, 3),
        "zero_pct": round(zero_frac * 100.0, 2),
    }


def query_sdss_catalog(
    session: requests.Session,
    ra0: float,
    dec0: float,
    scale_arcsec_px: float = NATIVE_SCALE_ARCSEC_PX,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> list[dict]:
    """Query SDSS DR18 PhotoPrimary sources inside the cutout FOV."""
    cos_dec = max(0.1, math.cos(math.radians(dec0)))
    half_dec_deg = (height * scale_arcsec_px / 2.0) / 3600.0
    half_ra_deg = (width * scale_arcsec_px / 2.0) / (3600.0 * cos_dec)
    ra_min = (ra0 - half_ra_deg) % 360.0
    ra_max = (ra0 + half_ra_deg) % 360.0
    ra_clause = (
        f"(ra >= {ra_min:.6f} OR ra <= {ra_max:.6f})"
        if ra_min > ra_max
        else f"ra BETWEEN {ra_min:.6f} AND {ra_max:.6f}"
    )
    query = (
        "SELECT TOP 1500 objID, ra, dec, u, g, r, i, z, type "
        "FROM PhotoPrimary "
        f"WHERE {ra_clause} "
        f"AND dec BETWEEN {dec0 - half_dec_deg:.6f} AND {dec0 + half_dec_deg:.6f} "
        "AND r BETWEEN 5.0 AND 21.5"
    )
    resp = session.get(SDSS_SQL_URL, params={"cmd": query, "format": "json"}, timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    raw_rows = payload[0].get("Rows", []) if payload else []
    objects: list[dict] = []
    for row in raw_rows:
        px, py = sky_to_pixel(row["ra"], row["dec"], ra0, dec0, scale_arcsec_px, width, height)
        if not (0.0 <= px < width and 0.0 <= py < height):
            continue
        r_mag = float(row["r"])
        g_mag = float(row["g"])
        objects.append({
            "objID": str(row["objID"]),
            "ra": round(float(row["ra"]), 6),
            "dec": round(float(row["dec"]), 6),
            "px": round(px, 2),
            "py": round(py, 2),
            "g": round(g_mag, 3),
            "r": round(r_mag, 3),
            "i": round(float(row["i"]), 3),
            "g_minus_r": round(g_mag - r_mag, 3) if g_mag > 0 and r_mag > 0 else None,
            "sdss_type": int(row["type"]),
            "kind": "star" if int(row["type"]) == 6 else "galaxy" if int(row["type"]) == 3 else "other",
        })
    objects.sort(key=lambda o: o["r"])
    return objects


def query_gaia_catalog(
    session: requests.Session,
    ra0: float,
    dec0: float,
    scale_arcsec_px: float = NATIVE_SCALE_ARCSEC_PX,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> list[dict]:
    """Query Gaia DR3 sources inside the cutout FOV via ARI Heidelberg TAP."""
    radius_deg = math.hypot(width, height) * scale_arcsec_px / 2.0 / 3600.0
    adql = (
        "SELECT TOP 1500 source_id, ra, dec, phot_g_mean_mag, bp_rp, pmra, pmdec "
        "FROM gaiadr3.gaia_source "
        f"WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra0:.6f}, {dec0:.6f}, {radius_deg:.6f})) = 1"
    )
    resp = session.post(
        GAIA_TAP_URL,
        data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": adql},
        timeout=20,
    )
    resp.raise_for_status()
    reader = csv.DictReader(resp.text.splitlines())
    sources: list[dict] = []
    for row in reader:
        if not row.get("ra") or not row.get("dec"):
            continue
        ra = float(row["ra"])
        dec = float(row["dec"])
        px, py = sky_to_pixel(ra, dec, ra0, dec0, scale_arcsec_px, width, height)
        if not (0.0 <= px < width and 0.0 <= py < height):
            continue
        pmra = float(row["pmra"]) if row.get("pmra") else 0.0
        pmdec = float(row["pmdec"]) if row.get("pmdec") else 0.0
        g_mag = float(row["phot_g_mean_mag"]) if row.get("phot_g_mean_mag") else None
        bp_rp = float(row["bp_rp"]) if row.get("bp_rp") else None
        sources.append({
            "source_id": row["source_id"],
            "ra": round(ra, 6),
            "dec": round(dec, 6),
            "px": round(px, 2),
            "py": round(py, 2),
            "g_mag": round(g_mag, 3) if g_mag is not None else None,
            "bp_rp": round(bp_rp, 3) if bp_rp is not None else None,
            "pm_total_mas_yr": round(math.hypot(pmra, pmdec), 2),
        })
    sources.sort(key=lambda g: g["g_mag"] if g["g_mag"] is not None else 99.0)
    return sources


def summarize_catalogs(sdss_objs: list[dict], gaia_objs: list[dict]) -> dict:
    """Compute density, class breakdown, and close angular-pair counts across both catalogs."""
    stars = sum(1 for o in sdss_objs if o["kind"] == "star")
    galaxies = sum(1 for o in sdss_objs if o["kind"] == "galaxy")
    bright = sum(1 for o in sdss_objs if o["r"] < 19.5)
    sdss_pairs = count_close_pairs(sdss_objs, max_arcsec=5.0)
    gaia_pairs = count_close_pairs(gaia_objs, max_arcsec=5.0)
    gaia_high_pm = sum(1 for g in gaia_objs if g["pm_total_mas_yr"] >= 10.0)
    return {
        "sdss_r_lt21_5": len(sdss_objs),
        "sdss_r_lt19_5": bright,
        "sdss_stars": stars,
        "sdss_galaxies": galaxies,
        "sdss_close_pairs_lt5arcsec": sdss_pairs,
        "gaia_dr3_count": len(gaia_objs),
        "gaia_high_pm_count": gaia_high_pm,
        "gaia_close_pairs_lt5arcsec": gaia_pairs,
    }


def classify_sdss_item(name: str, kind: str, stats: dict) -> dict[str, str]:
    """Build canonical image_tags annotations for a verified SDSS+Gaia astronomical field."""
    total = max(stats["sdss_r_lt21_5"], stats["gaia_dr3_count"])
    stars = stats["sdss_stars"]
    galaxies = stats["sdss_galaxies"]
    close_pairs = max(stats["sdss_close_pairs_lt5arcsec"], stats["gaia_close_pairs_lt5arcsec"])
    multi_class = stars >= 5 and galaxies >= 5

    q_types = ["counting", "localization_measurement"]
    if multi_class or kind in ("galaxy_cluster", "compact_group", "galaxy_group"):
        q_types.append("domain_decoding")

    d_tags = ["high_similarity", "small_target"]
    if total >= 80:
        d_tags.append("high_density")
    if close_pairs >= 3:
        d_tags.append("occlusion_overlap")
    if total >= 60 and (close_pairs >= 3 or (galaxies >= 10 and stars >= 10)):
        d_tags.append("multi_hop_visual")

    if total >= 80 and (close_pairs >= 4 or (galaxies >= 15 and stars >= 10)):
        difficulty = "hard"
        tier = "P1/P2困难候选"
    elif total >= 30:
        difficulty = "medium"
        tier = "P2中等候选"
    else:
        difficulty = "easy"
        tier = "稀疏天区候选"

    norm_q = ",".join(image_tags.normalize_codes(q_types, image_tags.QUESTION_TYPES, "question_types"))
    norm_d = ",".join(image_tags.normalize_codes(d_tags, image_tags.DIFFICULTY_TAGS, "difficulty_tags"))

    return {
        "question_types": norm_q,
        "difficulty": difficulty,
        "difficulty_tags": norm_d,
        "authored_status": "",
        "authored_ref": "",
        "tag_notes": (
            f"{tier}。SDSS DR18+Gaia DR3[{kind} | {name}] | FOV 6.76'×6.76'(0.39612\"/px) | "
            f"SDSS(r<21.5)={stats['sdss_r_lt21_5']}（恒星{stars}/星系{galaxies}），Gaia DR3={stats['gaia_dr3_count']}，"
            f"近邻对(<5\")={close_pairs} | 许可 {SDSS_LICENSE} (Sloan Digital Sky Survey)。"
            "可考衍射芒恒星与弥散星系辨析、g-r色差筛选、混叠源区分及WCS角距计算。"
        ),
    }


def collect_sdss_gaia(
    *,
    root: Path = ROOT,
    img_dir: Path | None = None,
    db_path: Path | None = None,
    targets: list[tuple[str, str, float, float]] | None = None,
    limit: int = 0,
    skip_db: bool = False,
    force_tags: bool = False,
) -> dict:
    """Download curated SDSS cutouts, query SDSS+Gaia catalogs, save JPGs and register in SQLite."""
    resolved_img_dir = (img_dir or (root / "img")).resolve()
    resolved_db = (db_path or (root / "采集数据.sqlite")).resolve()
    base_dir = resolved_img_dir / SDSS_SUBDIR
    jpg_dir = base_dir / "JPG"
    meta_dir = base_dir / "元数据"
    jpg_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    selected = list(targets or TARGETS)
    if limit > 0:
        selected = selected[:limit]

    records: list[dict] = []
    skipped: list[dict] = []

    with requests.Session() as session:
        session.headers.update({"User-Agent": "ZeroBenchCommonsCollector/1.0 (SDSS-Gaia-Pipeline)"})
        for name, kind, ra0, dec0 in selected:
            out_path = jpg_dir / f"{name}.jpg"
            try:
                cutout_params = {
                    "ra": ra0,
                    "dec": dec0,
                    "scale": NATIVE_SCALE_ARCSEC_PX,
                    "width": DEFAULT_WIDTH,
                    "height": DEFAULT_HEIGHT,
                }
                r = session.get(SDSS_CUTOUT_URL, params=cutout_params, timeout=20)
                r.raise_for_status()
                qc = evaluate_cutout_pixels(r.content)
                if not qc["passed"]:
                    qc_info = {k: v for k, v in qc.items() if k != "clean_bytes"}
                    skipped.append({"name": name, "reason": f"coverage/saturation check failed: {qc_info}"})
                    continue

                sdss_objs = query_sdss_catalog(session, ra0, dec0)
                try:
                    gaia_objs = query_gaia_catalog(session, ra0, dec0)
                except requests.RequestException:
                    gaia_objs = []

                stats = summarize_catalogs(sdss_objs, gaia_objs)
                if max(stats["sdss_r_lt21_5"], stats["gaia_dr3_count"]) < 15:
                    skipped.append({"name": name, "reason": f"too sparse: {stats}"})
                    continue

                atomic_write_bytes(out_path, qc["clean_bytes"])
                sha256 = hashlib.sha256(qc["clean_bytes"]).hexdigest()
                annotations = classify_sdss_item(name, kind, stats)
                img_relpath = out_path.relative_to(resolved_img_dir).as_posix()
                file_relpath = out_path.relative_to(root).as_posix() if out_path.is_relative_to(root) else img_relpath

                records.append({
                    "dataset": "SDSS_DR18+Gaia_DR3",
                    "name": name,
                    "field_kind": kind,
                    "center_ra": ra0,
                    "center_dec": dec0,
                    "scale_arcsec_px": NATIVE_SCALE_ARCSEC_PX,
                    "fov_arcmin": round(DEFAULT_WIDTH * NATIVE_SCALE_ARCSEC_PX / 60.0, 2),
                    "file": file_relpath,
                    "img_relpath": img_relpath,
                    "source_url": r.url,
                    "width": qc["width"],
                    "height": qc["height"],
                    "bytes": len(qc["clean_bytes"]),
                    "sha256": sha256,
                    "pixel_qc": {k: v for k, v in qc.items() if k != "clean_bytes"},
                    "catalog_stats": stats,
                    "top_sdss_objects": sdss_objs[:40],
                    "top_gaia_sources": gaia_objs[:40],
                    "license": {
                        "ImageLicense": SDSS_LICENSE,
                        "ImageAttribution": "Sloan Digital Sky Survey (SDSS)",
                        "ImagePolicyUrl": SDSS_POLICY_URL,
                        "GaiaCatalogLicense": GAIA_LICENSE,
                    },
                    "annotations": annotations,
                })
                print(
                    f"[OK] {name}: diff={annotations['difficulty']} sdss={stats['sdss_r_lt21_5']} "
                    f"gaia={stats['gaia_dr3_count']} pairs={stats['sdss_close_pairs_lt5arcsec']}",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(0.1)
            except Exception as exc:
                print(f"[SKIP] {name}: {exc}", file=sys.stderr, flush=True)
                skipped.append({"name": name, "reason": str(exc)})

    if records:
        license_note = (
            "SDSS DR18 Optical Cutouts + Gaia DR3 Astrometric Cross-Match\n"
            f"SDSS Image Use Policy ({SDSS_LICENSE}): {SDSS_POLICY_URL}\n"
            "Credit: Sloan Digital Sky Survey (www.sdss.org)\n"
            f"SDSS Cutout Service: {SDSS_CUTOUT_URL}\n"
            f"SDSS SQL Search: {SDSS_SQL_URL}\n"
            f"Gaia DR3 TAP ({GAIA_LICENSE}): {GAIA_TAP_URL}\n"
        )
        atomic_write_bytes(meta_dir / "来源与许可.txt", license_note.encode("utf-8"))
        manifest_text = "\n".join(json.dumps(rec, ensure_ascii=False) for rec in records) + "\n"
        atomic_write_bytes(meta_dir / "catalog_manifest.jsonl", manifest_text.encode("utf-8"))

    inserted = updated = 0
    if records and not skip_db:
        inserted, updated = register_local_claims(resolved_db, records, force_tags=force_tags)

    diff_counts = {"hard": 0, "medium": 0, "easy": 0}
    for rec in records:
        diff = rec["annotations"]["difficulty"]
        if diff in diff_counts:
            diff_counts[diff] += 1

    return {
        "saved": len(records),
        "skipped": skipped,
        "difficulty_counts": diff_counts,
        "db_inserted": inserted,
        "db_updated": updated,
        "out_dir": str(jpg_dir),
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
        sys.stderr.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(
        description="下载高密度 SDSS DR18 CC-BY 天文观测图并关联 Gaia DR3 星表登记入库。"
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--img-dir", type=Path, default=None)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=0, help="限制下载前 N 个天区（0 表示全部）")
    parser.add_argument("--skip-db", action="store_true")
    parser.add_argument("--force-tags", action="store_true")
    args = parser.parse_args(argv)

    summary = collect_sdss_gaia(
        root=args.root.resolve(),
        img_dir=args.img_dir,
        db_path=args.db,
        limit=args.limit,
        skip_db=args.skip_db,
        force_tags=args.force_tags,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
