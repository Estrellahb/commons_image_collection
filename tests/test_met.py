"""Unit tests for collect_met.py."""

from contextlib import closing
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import collect_met
import img_server


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "collection_schema.sql"


def make_png_bytes(width: int = 2400, height: int = 1600) -> bytes:
    img = Image.new("RGBA", (width, height), (120, 80, 40, 255))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class MetCollectionTests(unittest.TestCase):
    def test_collect_met_scans_converts_and_registers_cc0_only(self):
        csv_lines = [
            "Object Number,Is Highlight,Is Timeline Work,Is Public Domain,Object ID,Gallery Number,Department,AccessionYear,Object Name,Title",
            "1.1,True,False,True,101,100,The American Wing,1900,Sampler,Embroidered Sampler",
            "1.2,False,False,False,102,100,The American Wing,1900,Sampler,Private Sampler",
            "1.3,False,False,True,103,100,Islamic Art,1900,Textile,Should Not Match Tile",
            "1.4,True,False,True,104,100,Islamic Art,1900,Tile panel,Geometric Tile Panel",
        ]
        sample_png = make_png_bytes()

        def fake_get(url, stream=False, timeout=15):
            resp = Mock()
            resp.raise_for_status = Mock()
            resp.status_code = 200
            if "MetObjects.csv" in url:
                resp.iter_lines = Mock(return_value=iter(csv_lines))
                resp.close = Mock()
            elif url.endswith("/101"):
                resp.json = Mock(return_value={
                    "objectID": 101, "isPublicDomain": True, "primaryImage": "https://images.met/101.png",
                    "objectName": "Sampler", "title": "Embroidered Sampler", "department": "The American Wing",
                })
            elif url.endswith("/104"):
                resp.json = Mock(return_value={
                    "objectID": 104, "isPublicDomain": True, "primaryImage": "https://images.met/104.png",
                    "objectName": "Tile panel", "title": "Geometric Tile Panel", "department": "Islamic Art",
                })
            else:
                resp.content = sample_png
            return resp

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "采集数据.sqlite"
            with closing(sqlite3.connect(db_path)) as db:
                db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

            mock_session = Mock()
            mock_session.get.side_effect = fake_get
            mock_session.headers = {}
            cm = Mock()
            cm.__enter__ = Mock(return_value=mock_session)
            cm.__exit__ = Mock(return_value=False)

            with patch("collect_met.requests.Session", return_value=cm), patch("collect_met.time.sleep"):
                summary = collect_met.collect_met(root=root, db_path=db_path, target_count=10, per_bucket=2)

            self.assertEqual(summary["saved"], 2)
            self.assertEqual(summary["db_inserted"], 2)
            self.assertEqual(summary["difficulty_counts"]["hard"], 2)

            jpg101 = root / "img" / "小众专业实物" / "Met_CC0" / "JPG" / "met-101.jpg"
            self.assertTrue(jpg101.is_file())
            with Image.open(jpg101) as im:
                self.assertEqual((im.format, im.mode), ("JPEG", "RGB"))
                self.assertLessEqual(max(im.size), 2048)

            store = img_server.ClaimStore(db_path, root / "img")
            rel = "小众专业实物/Met_CC0/JPG/met-101.jpg"
            claim = store.get_claims_by_relpaths([rel])[rel]
            self.assertTrue(claim["registered"])
            self.assertEqual(claim["registry_source"], "img_claims")
            self.assertIn("robust_ocr", claim["question_types"])
            manifest = (root / "img" / "小众专业实物" / "Met_CC0" / "元数据" / "objects_manifest.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(manifest), 2)
            self.assertEqual(json.loads(manifest[0])["object_id"], 101)


if __name__ == "__main__":
    unittest.main()
