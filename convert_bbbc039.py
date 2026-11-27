"""Convert BBBC039 16-bit grayscale TIFF micrographs to 8-bit PNGs and register them in SQLite."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

import image_tags
from local_registry import atomic_write_bytes, register_local_claims


ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "采集数据.sqlite"
DEFAULT_IMG_DIR = ROOT / "img"
BBBC_SUBDIR = Path("科学图像") / "BBBC039"
MAX_PNG_BYTES = 5_000_000
MIN_NUCLEUS_AREA = 20
DATASET_URL = "https://bbbc.broadinstitute.org/BBBC039"
IMAGES_URL = "https://data.broadinstitute.org/bbbc/BBBC039/images.zip"
MASKS_URL = "https://data.broadinstitute.org/bbbc/BBBC039/masks.zip"
LICENSE_NAME = "CC0 1.0"
LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"


def load_bbbc039_metadata(meta_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Load official split assignments and BBBC022 plate IDs indexed by file stem."""
    splits: dict[str, str] = {}
    for split_name in ("training", "validation", "test"):
        split_file = meta_dir / f"{split_name}.txt"
        if split_file.is_file():
            for line in split_file.read_text(encoding="utf-8").splitlines():
                name = line.strip()
                if name:
                    splits[Path(name).stem] = split_name

    plates: dict[str, str] = {}
    plates_file = meta_dir / "filenames_and_plates.csv"
    if plates_file.is_file():
        # filenames_and_plates.csv uses classic CR line endings; splitlines handles CR/LF/CRLF.
        for line in plates_file.read_text(encoding="utf-8").splitlines():
            row = line.strip()
            if not row or "," not in row:
                continue
            fname, plate = row.split(",", 1)
            plates[Path(fname.strip()).stem] = plate.strip()
    return splits, plates


def connected_component_areas(mask_bool: np.ndarray) -> list[int]:
    """Return 8-connected foreground component pixel areas for a 2D boolean mask."""
    if not mask_bool.any():
        return []
    height, width = mask_bool.shape
    padded = np.zeros((height + 2, width + 2), dtype=np.uint8)
    padded[1:-1, 1:-1] = mask_bool
    indices = np.flatnonzero(padded).tolist()
    flat = padded.ravel().tolist()
    stride = width + 2
    offsets = (
        -stride - 1, -stride, -stride + 1,
        -1, 1,
        stride - 1, stride, stride + 1,
    )
    areas: list[int] = []
    for start in indices:
        if not flat[start]:
            continue
        flat[start] = 0
        stack = [start]
        area = 0
        while stack:
            cur = stack.pop()
            area += 1
            for offset in offsets:
                nb = cur + offset
                if flat[nb]:
                    flat[nb] = 0
                    stack.append(nb)
        areas.append(area)
    return areas


def compute_intensity_window(arr: np.ndarray) -> tuple[float, float]:
    """Compute an artifact-resistant linear intensity window [lo, hi] for 16-bit micrographs."""
    p05, p990, p998 = np.percentile(arr, [0.5, 99.0, 99.8])
    lo = float(p05)
    # Cap upper bound relative to p99.0 when bright dust/scratch artifacts saturate p99.8.
    hi_cand = min(float(p998), float(p990) * 1.5) if p990 > lo + 400.0 else float(p998)
    # Enforce minimum span so blank/empty wells remain dark instead of amplifying sensor noise.
    hi = max(hi_cand, lo + 300.0)
    return lo, hi


def convert_tiff_array_to_uint8(arr: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Linearly stretch a 16-bit micrograph array into 8-bit uint8 using robust percentiles."""
    arr_f = np.asarray(arr, dtype=np.float64)
    lo, hi = compute_intensity_window(arr_f)
    scaled = np.clip((arr_f - lo) / (hi - lo), 0.0, 1.0)
    u8 = np.round(scaled * 255.0).astype(np.uint8)
    return u8, lo, hi


def analyze_mask(mask_path: Path) -> dict[str, float | int]:
    """Extract nuclei count, binary cluster count, touching delta, and foreground fraction."""
    with Image.open(mask_path) as mask_img:
        arr = np.asarray(mask_img)
    labels = arr[:, :, 0] if arr.ndim == 3 else arr
    max_label = int(labels.max())
    inst_areas: list[int] = []
    for label_val in range(1, max_label + 1):
        inst_areas.extend(connected_component_areas(labels == label_val))
    valid_inst = [area for area in inst_areas if area >= MIN_NUCLEUS_AREA]
    tiny_count = len(inst_areas) - len(valid_inst)

    fg_mask = labels > 0
    cluster_areas = [
        area for area in connected_component_areas(fg_mask) if area >= MIN_NUCLEUS_AREA
    ]
    nuclei_count = len(valid_inst)
    binary_clusters = len(cluster_areas)
    touching_delta = max(0, nuclei_count - binary_clusters)
    foreground_pct = float(100.0 * fg_mask.mean())
    return {
        "nuclei_count": nuclei_count,
        "tiny_fragment_count": tiny_count,
        "binary_cluster_count": binary_clusters,
        "touching_delta": touching_delta,
        "foreground_pct": round(foreground_pct, 2),
        "max_mask_label": max_label,
    }


def classify_bbbc039_item(
    *,
    split: str,
    plate: str,
    stats: dict[str, float | int],
    lo: float,
    hi: float,
    cluttered_bg: bool,
) -> dict[str, str]:
    """Build canonical annotation fields matching image_tags.py and ZeroBench criteria."""
    nuclei = int(stats["nuclei_count"])
    clusters = int(stats["binary_cluster_count"])
    delta = int(stats["touching_delta"])
    fg_pct = float(stats["foreground_pct"])
    split_tag = split or "unknown"
    plate_tag = f" / plate={plate}" if plate else ""

    if nuclei == 0:
        return {
            "question_types": "",
            "difficulty": "",
            "difficulty_tags": "",
            "authored_status": "discarded",
            "authored_ref": "",
            "tag_notes": (
                f"BBBC039[{split_tag}{plate_tag}] | 空白视野（掩膜前景 0%，核数 0），"
                f"不适合出题已标记淘汰。16位TIFF线性拉伸[{lo:.0f},{hi:.0f}]转8位PNG，许可 {LICENSE_NAME}。"
            ),
        }

    q_types = ["counting", "localization_measurement"]
    if delta >= 15:
        q_types.append("topology_tracking")

    d_tags = ["high_similarity", "small_target"]
    if nuclei >= 80:
        d_tags.append("high_density")
    if delta >= 10:
        d_tags.append("occlusion_overlap")
    if nuclei >= 80 and delta >= 10:
        d_tags.append("multi_hop_visual")
    if cluttered_bg:
        d_tags.append("cluttered_bg")

    if nuclei >= 100 and delta >= 15:
        difficulty = "hard"
        tier_note = "P1困难候选"
    elif nuclei >= 40:
        difficulty = "medium"
        tier_note = "P1中等候选"
    else:
        difficulty = "easy"
        tier_note = "稀疏视野基础候选"

    norm_q = ",".join(image_tags.normalize_codes(q_types, image_tags.QUESTION_TYPES, "question_types"))
    norm_d = ",".join(image_tags.normalize_codes(d_tags, image_tags.DIFFICULTY_TAGS, "difficulty_tags"))

    return {
        "question_types": norm_q,
        "difficulty": difficulty,
        "difficulty_tags": norm_d,
        "authored_status": "",
        "authored_ref": "",
        "tag_notes": (
            f"{tier_note}。BBBC039[{split_tag}{plate_tag}] | 核数={nuclei} / 二值连通团={clusters}"
            f"（粘连拆分差={delta}）| 前景占比={fg_pct:.1f}% | 16位TIFF线性拉伸[{lo:.0f},{hi:.0f}]→8位PNG"
            f" | 许可 {LICENSE_NAME}。可辨认粘连核边界后按形态/灰度/邻域约束求解完整计数或互斥配对；"
            "官方掩膜按4色标签区分邻接实例，不可直接二值连通域计数。"
        ),
    }


def process_bbbc039(
    *,
    root: Path = ROOT,
    img_dir: Path | None = None,
    db_path: Path | None = None,
    dry_run: bool = False,
    skip_db: bool = False,
    force_tags: bool = False,
) -> dict:
    """Convert all BBBC039 16-bit TIFFs to 8-bit PNGs, write manifest, and register in SQLite."""
    resolved_img_dir = (img_dir or (root / "img")).resolve()
    resolved_db = (db_path or (root / "采集数据.sqlite")).resolve()
    bbbc_dir = resolved_img_dir / BBBC_SUBDIR
    src_dir = bbbc_dir / "原图"
    mask_dir = bbbc_dir / "掩膜"
    meta_dir = bbbc_dir / "元数据"
    out_dir = bbbc_dir / "PNG"

    if not src_dir.is_dir():
        raise FileNotFoundError(f"找不到 BBBC039 原图目录：{src_dir}")

    tif_paths = sorted(src_dir.glob("*.tif"))
    if not tif_paths:
        raise ValueError(f"目录中没有 .tif 文件：{src_dir}")

    splits, plates = load_bbbc039_metadata(meta_dir)
    records: list[dict] = []

    for tif_path in tif_paths:
        stem = tif_path.stem
        mask_path = mask_dir / f"{stem}.png"
        if not mask_path.is_file():
            raise FileNotFoundError(f"找不到匹配的掩膜文件：{mask_path}")

        with Image.open(tif_path) as tif_img:
            src_mode = tif_img.mode
            src_size = tif_img.size
            arr = np.asarray(tif_img)

        u8, lo, hi = convert_tiff_array_to_uint8(arr)
        stats = analyze_mask(mask_path)

        with Image.open(mask_path) as mask_img:
            mask_arr = np.asarray(mask_img)
        fg_mask = (mask_arr[:, :, 0] if mask_arr.ndim == 3 else mask_arr) > 0
        cluttered_bg = False
        if fg_mask.any() and (~fg_mask).any():
            bg_p95_u8 = 255.0 * (float(np.percentile(arr[~fg_mask], 95)) - lo) / (hi - lo)
            cluttered_bg = bg_p95_u8 > 50.0

        split = splits.get(stem, "")
        plate = plates.get(stem, "")
        annotations = classify_bbbc039_item(
            split=split,
            plate=plate,
            stats=stats,
            lo=lo,
            hi=hi,
            cluttered_bg=cluttered_bg,
        )

        out_path = out_dir / f"{stem}.png"
        img_relpath = out_path.relative_to(resolved_img_dir).as_posix()
        file_relpath = out_path.relative_to(root).as_posix() if out_path.is_relative_to(root) else img_relpath

        png_bytes_len = 0
        sha256 = ""
        if not dry_run:
            from io import BytesIO

            buf = BytesIO()
            Image.fromarray(u8).save(buf, format="PNG", optimize=True)
            payload = buf.getvalue()
            if len(payload) > MAX_PNG_BYTES:
                raise ValueError(f"{out_path.name} 转换后体积 {len(payload)} 字节超过 5 MB 上限")
            atomic_write_bytes(out_path, payload)
            png_bytes_len = len(payload)
            sha256 = hashlib.sha256(payload).hexdigest()

        records.append({
            "dataset": "BBBC039v1",
            "stem": stem,
            "split": split,
            "plate": plate,
            "source_tif": tif_path.relative_to(root).as_posix() if tif_path.is_relative_to(root) else str(tif_path),
            "mask_png": mask_path.relative_to(root).as_posix() if mask_path.is_relative_to(root) else str(mask_path),
            "file": file_relpath,
            "img_relpath": img_relpath,
            "source_mode": src_mode,
            "source_width": src_size[0],
            "source_height": src_size[1],
            "width": int(u8.shape[1]),
            "height": int(u8.shape[0]),
            "bytes": png_bytes_len,
            "sha256": sha256,
            "intensity_window": [round(lo, 2), round(hi, 2)],
            "cluttered_bg_detected": cluttered_bg,
            "mask_stats": stats,
            "license": {
                "LicenseShortName": LICENSE_NAME,
                "LicenseUrl": LICENSE_URL,
                "DatasetUrl": DATASET_URL,
                "SourceImagesUrl": IMAGES_URL,
                "SourceMasksUrl": MASKS_URL,
                "Attribution": "BBBC039v1 (Caicedo et al. 2018), Broad Bioimage Benchmark Collection",
            },
            "modifications": (
                f"Converted 16-bit grayscale TIFF ({src_mode}) to 8-bit grayscale PNG (mode L) "
                f"via linear intensity window [{lo:.2f}, {hi:.2f}] clipped to [0, 255]."
            ),
            "annotations": annotations,
        })

    if not dry_run:
        manifest_path = meta_dir / "conversion_manifest.jsonl"
        manifest_text = "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n"
        atomic_write_bytes(manifest_path, manifest_text.encode("utf-8"))

    inserted = updated = 0
    if not dry_run and not skip_db:
        inserted, updated = register_local_claims(resolved_db, records, force_tags=force_tags)

    diff_counts = {"hard": 0, "medium": 0, "easy": 0, "discarded": 0}
    for rec in records:
        ann = rec["annotations"]
        if ann["authored_status"] == "discarded":
            diff_counts["discarded"] += 1
        elif ann["difficulty"] in diff_counts:
            diff_counts[ann["difficulty"]] += 1

    return {
        "total": len(records),
        "difficulty_counts": diff_counts,
        "db_inserted": inserted,
        "db_updated": updated,
        "out_dir": str(out_dir),
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
        sys.stderr.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(
        description="将 BBBC039 的 16 位灰度 .tif 原图线性拉伸转换为 8 位 .png 并登记到数据库。"
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="项目根目录")
    parser.add_argument("--img-dir", type=Path, default=None, help="图片目录（默认 <root>/img）")
    parser.add_argument("--db", type=Path, default=None, help="SQLite 数据库路径（默认 <root>/采集数据.sqlite）")
    parser.add_argument("--dry-run", action="store_true", help="只统计与校验，不写入 PNG 和数据库")
    parser.add_argument("--skip-db", action="store_true", help="只转换 PNG 与生成清单，不写入数据库")
    parser.add_argument("--force-tags", action="store_true", help="覆盖已存在记录的标签与备注（保留 claimed_by 与 authored_ref）")
    args = parser.parse_args(argv)

    summary = process_bbbc039(
        root=args.root.resolve(),
        img_dir=args.img_dir,
        db_path=args.db,
        dry_run=args.dry_run,
        skip_db=args.skip_db,
        force_tags=args.force_tags,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
