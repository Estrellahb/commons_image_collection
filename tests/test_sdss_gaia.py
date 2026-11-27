"""Unit tests for collect_sdss_gaia.py."""

from contextlib import closing
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock

from PIL import Image, ImageDraw

import collect_sdss_gaia
import img_server


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "collection_schema.sql"


def make_starfield_jpeg() -> bytes:
    img = Image.new("RGB", (1024, 1024), (2, 2, 4))
    draw = ImageDraw.Draw(img)
    for x in range(64, 960, 48):
        for y in range(64, 960, 48):
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=(210, 190, 150))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


class SDSSGaiaTests(unittest.TestCase):
    def test_sky_to_pixel_and_angular_separation_center_and_offsets(self):
        px, py = collect_sdss_gaia.sky_to_pixel(197.8730, -1.3410, 197.8730, -1.3410)
        self.assertAlmostEqual(px, 511.5, places=4)
        self.assertAlmostEqual(py, 511.5, places=4)
        # Moving East (+RA) moves left (-x); moving North (+Dec) moves up (-y).
        px_e, py_n = collect_sdss_gaia.sky_to_pixel(
            197.8730 + 3.9612 / 3600.0, -1.3410 + 3.9612 / 3600.0, 197.8730, -1.3410
        )
        self.assertLess(px_e, 505.0)
        self.assertLess(py_n, 505.0)
        sep = collect_sdss_gaia.angular_separation_arcsec(10.0, 0.0, 10.0 + 1.0 / 3600.0, 0.0)
        self.assertAlmostEqual(sep, 1.0, places=4)

    def test_collect_sdss_gaia_downloads_and_registers_claims_without_network(self):
        star_jpeg = make_starfield_jpeg()
        # Generate 90 synthetic SDSS objects including close pairs < 5 arcsec.
        sdss_rows = []
        gaia_csv_lines = ["source_id,ra,dec,phot_g_mean_mag,bp_rp,pmra,pmdec"]
        ra0, dec0 = 197.8730, -1.3410
        for idx in range(90):
            dx_arcsec = ((idx % 10) - 4.5) * 20.0
            dy_arcsec = ((idx // 10) - 4.5) * 20.0
            if idx % 15 == 1:
                dx_arcsec = (((idx - 1) % 10) - 4.5) * 20.0 + 2.5
                dy_arcsec = (((idx - 1) // 10) - 4.5) * 20.0 + 1.0
            ra = ra0 + dx_arcsec / 3600.0
            dec = dec0 + dy_arcsec / 3600.0
            obj_type = 6 if idx % 2 == 0 else 3
            sdss_rows.append({
                "objID": 1237600000000000000 + idx,
                "ra": ra,
                "dec": dec,
                "u": 20.0,
                "g": 18.5,
                "r": 17.6,
                "i": 17.2,
                "z": 17.0,
                "type": obj_type,
            })
            if obj_type == 6:
                gaia_csv_lines.append(f"{1000 + idx},{ra},{dec},18.0,1.1,12.0,3.0")

        def fake_get(url, params=None, timeout=20):
            resp = Mock()
            resp.raise_for_status = Mock()
            if "ImgCutout" in url:
                resp.content = star_jpeg
                resp.url = url
            else:
                resp.json = Mock(return_value=[{"Rows": sdss_rows}])
            return resp

        def fake_post(url, data=None, timeout=25):
            resp = Mock()
            resp.raise_for_status = Mock()
            resp.text = "\n".join(gaia_csv_lines)
            return resp

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "采集数据.sqlite"
            with closing(sqlite3.connect(db_path)) as db:
                db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

            mock_session = Mock()
            mock_session.get.side_effect = fake_get
            mock_session.post.side_effect = fake_post
            mock_session.headers = {}
            cm = Mock()
            cm.__enter__ = Mock(return_value=mock_session)
            cm.__exit__ = Mock(return_value=False)

            with unittest.mock.patch("collect_sdss_gaia.requests.Session", return_value=cm):
                summary = collect_sdss_gaia.collect_sdss_gaia(
                    root=root,
                    db_path=db_path,
                    targets=[("Abell_Test", "galaxy_cluster", ra0, dec0)],
                )

            self.assertEqual(summary["saved"], 1)
            self.assertEqual(summary["difficulty_counts"]["hard"], 1)
            self.assertEqual(summary["db_inserted"], 1)

            jpg_path = root / "img" / "科学图像" / "SDSS_Gaia" / "JPG" / "Abell_Test.jpg"
            self.assertTrue(jpg_path.is_file())
            self.assertNotEqual(img_server.make_thumbnail(jpg_path), img_server.THUMB_PLACEHOLDER)

            store = img_server.ClaimStore(db_path, root / "img")
            rel = "科学图像/SDSS_Gaia/JPG/Abell_Test.jpg"
            claim = store.get_claims_by_relpaths([rel])[rel]
            self.assertEqual(claim["difficulty"], "hard")
            self.assertIn("domain_decoding", claim["question_types"])
            manifest_line = json.loads(
                (root / "img" / "科学图像" / "SDSS_Gaia" / "元数据" / "catalog_manifest.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            self.assertEqual(manifest_line["catalog_stats"]["sdss_close_pairs_lt5arcsec"], 6)


if __name__ == "__main__":
    unittest.main()
