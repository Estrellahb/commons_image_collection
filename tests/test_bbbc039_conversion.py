"""Unit and integration tests for convert_bbbc039.py."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import numpy as np
from PIL import Image

import convert_bbbc039
import img_server


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "collection_schema.sql"


def make_synthetic_bbbc039(root: Path, *, include_empty: bool = True) -> None:
    bbbc_dir = root / "img" / "科学图像" / "BBBC039"
    src_dir = bbbc_dir / "原图"
    mask_dir = bbbc_dir / "掩膜"
    meta_dir = bbbc_dir / "元数据"
    for folder in (src_dir, mask_dir, meta_dir):
        folder.mkdir(parents=True, exist_ok=True)

    # 1) Normal dense sample with two touching nuclei (mask values 1 and 2) and a 4095 artifact pixel.
    tif_arr = np.full((64, 64), 140, dtype=np.uint16)
    mask_arr = np.zeros((64, 64, 4), dtype=np.uint8)
    mask_arr[:, :, 3] = 255
    tif_arr[10:25, 10:25] = 950
    mask_arr[10:25, 10:25, 0] = 1
    tif_arr[10:25, 25:40] = 1020
    mask_arr[10:25, 25:40, 0] = 2
    tif_arr[0, 0] = 4095  # Bright hot pixel / scratch artifact

    stem_dense = "IXMtest_SAMPLE_DENSE"
    Image.fromarray(tif_arr).save(src_dir / f"{stem_dense}.tif")
    Image.fromarray(mask_arr).save(mask_dir / f"{stem_dense}.png")

    stems = [stem_dense]
    if include_empty:
        stem_empty = "IXMtest_SAMPLE_EMPTY"
        empty_tif = np.full((64, 64), 135, dtype=np.uint16)
        empty_tif[20:30, 20:30] = 155
        empty_mask = np.zeros((64, 64, 4), dtype=np.uint8)
        empty_mask[:, :, 3] = 255
        Image.fromarray(empty_tif).save(src_dir / f"{stem_empty}.tif")
        Image.fromarray(empty_mask).save(mask_dir / f"{stem_empty}.png")
        stems.append(stem_empty)

    (meta_dir / "training.txt").write_text(f"{stem_dense}.png\n", encoding="utf-8")
    (meta_dir / "validation.txt").write_text(
        f"{stems[1]}.png\n" if include_empty else "", encoding="utf-8"
    )
    (meta_dir / "test.txt").write_text("", encoding="utf-8")
    # Replicate classic CR line endings used by upstream filenames_and_plates.csv
    (meta_dir / "filenames_and_plates.csv").write_bytes(
        "\r".join(f"{s}.png,20630" for s in stems).encode("utf-8")
    )


class BBBC039ConversionTests(unittest.TestCase):
    def test_converts_16bit_tiff_and_registers_img_claims_without_clobbering_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_synthetic_bbbc039(root)
            db_path = root / "采集数据.sqlite"
            with closing(sqlite3.connect(db_path)) as db:
                db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

            summary = convert_bbbc039.process_bbbc039(root=root, db_path=db_path)
            self.assertEqual(summary["total"], 2)
            self.assertEqual(summary["db_inserted"], 2)
            self.assertEqual(summary["difficulty_counts"]["discarded"], 1)

            png_dir = root / "img" / "科学图像" / "BBBC039" / "PNG"
            dense_png = png_dir / "IXMtest_SAMPLE_DENSE.png"
            empty_png = png_dir / "IXMtest_SAMPLE_EMPTY.png"
            self.assertTrue(dense_png.is_file())
            self.assertTrue(empty_png.is_file())

            with Image.open(dense_png) as img:
                self.assertEqual((img.format, img.mode, img.size), ("PNG", "L", (64, 64)))
                arr = np.asarray(img)
                # Nuclei must be bright & legible despite the 4095 artifact pixel, while background stays 0.
                self.assertGreater(int(arr[15, 15]), 180)
                self.assertEqual(int(arr[50, 50]), 0)

            with Image.open(empty_png) as empty_img:
                # Blank well should stay dark rather than amplifying sensor noise to 255.
                self.assertLess(int(np.asarray(empty_img).max()), 30)

            # Verify img_server thumbnail and ClaimStore work seamlessly on converted PNGs.
            thumb = img_server.make_thumbnail(dense_png)
            self.assertNotEqual(thumb, img_server.THUMB_PLACEHOLDER)

            store = img_server.ClaimStore(db_path, root / "img")
            dense_rel = "科学图像/BBBC039/PNG/IXMtest_SAMPLE_DENSE.png"
            empty_rel = "科学图像/BBBC039/PNG/IXMtest_SAMPLE_EMPTY.png"
            claims = store.get_claims_by_relpaths([dense_rel, empty_rel])
            self.assertEqual(claims[dense_rel]["difficulty"], "easy")
            self.assertEqual(claims[dense_rel]["question_types"], ["counting", "localization_measurement"])
            self.assertEqual(claims[empty_rel]["authored_status"], "discarded")

            # Claiming then re-running conversion must preserve existing claimed_by and authored_ref.
            store.claim_item(claimer="alice", relpath=dense_rel)
            store.update_tags([({"relpath": dense_rel}, {"authored_status": "draft", "authored_ref": "ZB-BBBC-1"})])
            rerun = convert_bbbc039.process_bbbc039(root=root, db_path=db_path)
            self.assertEqual((rerun["db_inserted"], rerun["db_updated"]), (0, 2))
            after = store.get_claims_by_relpaths([dense_rel])[dense_rel]
            self.assertEqual(after["claimed_by"], "alice")
            self.assertEqual((after["authored_status"], after["authored_ref"]), ("draft", "ZB-BBBC-1"))

            manifest_lines = (
                root / "img" / "科学图像" / "BBBC039" / "元数据" / "conversion_manifest.jsonl"
            ).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(manifest_lines), 2)
            first = json.loads(manifest_lines[0])
            self.assertEqual(first["mask_stats"]["nuclei_count"], 2)
            self.assertEqual(first["mask_stats"]["binary_cluster_count"], 1)
            self.assertEqual(first["mask_stats"]["touching_delta"], 1)
            self.assertEqual(first["plate"], "20630")


if __name__ == "__main__":
    unittest.main()
