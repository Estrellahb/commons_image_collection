from io import BytesIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw

import img_server
from collect_wellcome import (
    WELLCOME_CATALOGUE_API,
    WELLCOME_IIIF_PRES_BASE,
    normalize_license,
    run_collection,
)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "collection_schema.sql"


def _make_plate_jpeg(width: int = 1200, height: int = 900, dense: bool = True) -> bytes:
    im = Image.new("RGB", (width, height), (245, 240, 228))
    draw = ImageDraw.Draw(im)
    if dense:
        for i in range(40, width - 40, 32):
            draw.line((i, 50, i, height - 50), fill=(25, 22, 20), width=4)
        for j in range(50, height - 50, 32):
            draw.line((40, j, width - 40, j), fill=(25, 22, 20), width=4)
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


class _FakeResp:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload

    @property
    def content(self) -> bytes:
        return self._payload


class _FakeSession:
    def __init__(self, routes: dict[str, _FakeResp]):
        self.routes = routes
        self.headers: dict[str, str] = {}

    def get(self, url: str, params=None, timeout=20):
        if params and "query" in params:
            key = f"{url}?query={params['query']}"
            return self.routes.get(key, _FakeResp({"results": []}))
        return self.routes.get(url, _FakeResp(b"", status_code=404))


class WellcomeCollectionTests(unittest.TestCase):
    def test_license_normalization_rejects_nc_and_inc(self):
        self.assertEqual(
            normalize_license("http://creativecommons.org/publicdomain/mark/1.0/")[0],
            "pdm",
        )
        self.assertEqual(
            normalize_license({"id": "cc-by", "url": "https://creativecommons.org/licenses/by/4.0/"})[0],
            "cc-by",
        )
        self.assertEqual(
            normalize_license("https://creativecommons.org/licenses/by-nc/4.0/"),
            ("", ""),
        )
        self.assertEqual(
            normalize_license("http://rightsstatements.org/vocab/InC/1.0/"),
            ("", ""),
        )

    def test_run_collection_filters_blank_and_nc_and_registers_db(self):
        dense_thumb = _make_plate_jpeg(400, 300, dense=True)
        blank_thumb = _make_plate_jpeg(400, 300, dense=False)
        dense_full = _make_plate_jpeg(1600, 1200, dense=True)

        svc_good_1 = "https://iiif.wellcomecollection.org/image/V0001001"
        svc_bad_nc = "https://iiif.wellcomecollection.org/image/V0001002"
        svc_atlas_blank = "https://iiif.wellcomecollection.org/image/b900_0001.jp2"
        svc_atlas_plate = "https://iiif.wellcomecollection.org/image/b900_0002.jp2"
        svc_cat_plate = "https://iiif.wellcomecollection.org/image/V0002001"

        routes = {
            f"{WELLCOME_IIIF_PRES_BASE}/b100": _FakeResp(
                {
                    "label": "Botanical classification; 227 figures",
                    "license": "http://creativecommons.org/publicdomain/mark/1.0/",
                    "sequences": [
                        {
                            "canvases": [
                                {"images": [{"resource": {"service": {"@id": svc_good_1}}}]},
                            ]
                        }
                    ],
                }
            ),
            f"{WELLCOME_IIIF_PRES_BASE}/b101": _FakeResp(
                {
                    "label": "Restricted anatomy",
                    "license": "https://creativecommons.org/licenses/by-nc/4.0/",
                    "sequences": [
                        {
                            "canvases": [
                                {"images": [{"resource": {"service": {"@id": svc_bad_nc}}}]},
                            ]
                        }
                    ],
                }
            ),
            f"{WELLCOME_IIIF_PRES_BASE}/b900": _FakeResp(
                {
                    "label": "Essays on the Microscope",
                    "license": "http://creativecommons.org/publicdomain/mark/1.0/",
                    "sequences": [
                        {
                            "canvases": [
                                {"images": [{"resource": {"service": {"@id": svc_atlas_blank}}}]},
                                {"images": [{"resource": {"service": {"@id": svc_atlas_plate}}}]},
                            ]
                        }
                    ],
                }
            ),
            f"{WELLCOME_CATALOGUE_API}?query=astronomy": _FakeResp(
                {
                    "results": [
                        {
                            "id": "cat001",
                            "title": "Astronomy: celestial star map diagram",
                            "items": [
                                {
                                    "locations": [
                                        {
                                            "locationType": {"id": "iiif-image"},
                                            "license": {"id": "cc-by", "url": "https://creativecommons.org/licenses/by/4.0/"},
                                            "url": f"{svc_cat_plate}/info.json",
                                        }
                                    ]
                                }
                            ],
                        },
                        {
                            "id": "cat002",
                            "title": "Portrait of an unknown gentleman",
                            "items": [],
                        },
                    ]
                }
            ),
            f"{svc_good_1}/full/!400,400/0/default.jpg": _FakeResp(dense_thumb),
            f"{svc_good_1}/full/!2048,2048/0/default.jpg": _FakeResp(dense_full),
            f"{svc_atlas_blank}/full/!400,400/0/default.jpg": _FakeResp(blank_thumb),
            f"{svc_atlas_plate}/full/!400,400/0/default.jpg": _FakeResp(dense_thumb),
            f"{svc_atlas_plate}/full/!2048,2048/0/default.jpg": _FakeResp(dense_full),
            f"{svc_cat_plate}/full/!400,400/0/default.jpg": _FakeResp(dense_thumb),
            f"{svc_cat_plate}/full/!2048,2048/0/default.jpg": _FakeResp(dense_full),
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "test.sqlite"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            out_dir = root / "img" / "科学图像" / "Wellcome_IIIF"

            saved, inserted, updated = run_collection(
                output_dir=out_dir,
                db_path=db_path,
                target_count=5,
                standalone_specs=[
                    {"mid": "b100", "domain": "botany_grid", "max_canvases": 1},
                    {"mid": "b101", "domain": "anatomy_chart", "max_canvases": 1},
                ],
                atlas_specs=[{"mid": "b900", "domain": "microscopy", "limit": 2, "min_idx": 0, "scan_limit": 5}],
                catalogue_queries=[("astronomy", "astronomy")],
                session=_FakeSession(routes),
            )

            self.assertEqual(saved, 3)
            self.assertEqual(inserted, 3)
            self.assertEqual(updated, 0)

            jpgs = sorted((out_dir / "JPG").glob("*.jpg"))
            self.assertEqual([p.name for p in jpgs], [
                "wellcome-b100-p001.jpg",
                "wellcome-b900-p002.jpg",
                "wellcome-cat001.jpg",
            ])

            manifest_lines = (out_dir / "元数据" / "plates_manifest.jsonl").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(manifest_lines), 3)
            items = [json.loads(line) for line in manifest_lines]
            self.assertEqual(items[0]["annotations"]["difficulty"], "hard")
            self.assertEqual(items[2]["license"], "cc-by")

            store = img_server.ClaimStore(db_path, root / "img")
            claims = store.get_claims_by_relpaths(
                [
                    "科学图像/Wellcome_IIIF/JPG/wellcome-b100-p001.jpg",
                    "科学图像/Wellcome_IIIF/JPG/wellcome-b900-p002.jpg",
                    "科学图像/Wellcome_IIIF/JPG/wellcome-cat001.jpg",
                ]
            )
            self.assertEqual(len(claims), 3)
            self.assertTrue(all(v["registered"] and v["registry_source"] == "img_claims" for v in claims.values()))

            with sqlite3.connect(db_path) as conn:
                q_count = conn.execute("SELECT COUNT(*) FROM collection_queue").fetchone()[0]
            self.assertEqual(q_count, 0)


if __name__ == "__main__":
    unittest.main()
