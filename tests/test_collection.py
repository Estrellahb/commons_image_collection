import csv
from contextlib import closing
from io import BytesIO
from pathlib import Path
import random
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from PIL import Image, ImageOps

from download_images import DEFAULT_DB, MAX_PNG_BYTES, Commons, Rejected, StopBatch, collect_one, encode_jpg, encode_png, load_records, read_queue, write_index

SOURCE = "https://commons.wikimedia.org/wiki/File:Example.jpg"
MEDIA = "https://upload.wikimedia.org/wikipedia/commons/1/12/Example.jpg"
CATEGORY = "居家场景/工具五金"
NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "d": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"}


def example():
    with Image.new("RGB", (96, 48), "#225969") as image:
        image.putpixel((8, 16), (255, 255, 0))
        exif = image.getexif()
        exif[274] = 6
        data = BytesIO()
        image.save(data, "JPEG", exif=exif, quality=93)
    data.seek(0)
    return data


def fake_commons(license_name="CC BY 4.0"):
    source = example()
    service = Mock()
    service.file_info.return_value = (1234, "File:Example.jpg", {
        "size": len(source.getvalue()), "width": 96, "height": 48, "mime": "image/jpeg", "url": MEDIA,
        "extmetadata": {
            "LicenseShortName": {"value": license_name},
            "Artist": {"value": '<a href="/wiki/User:Example">Example Artist</a>'},
            "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/4.0/"},
        },
    })
    service.fetch.side_effect = lambda *_: example()
    return service


class CollectionTests(unittest.TestCase):
    def test_queue_reads_the_project_database(self):
        items = read_queue(DEFAULT_DB)
        self.assertGreaterEqual(len(items), 4)
        self.assertIn("公共场景/市场摊位", {category for _, _, category in items})
        with closing(sqlite3.connect(DEFAULT_DB)) as db:
            text = db.execute(
                "SELECT keyword FROM search_keywords WHERE category = ? AND is_exploratory = 0",
                (CATEGORY,),
            ).fetchall()
        self.assertIn(("wrenches tool wall",), text)

    def test_sqlite_queue_preserves_id_order_and_validates_links_and_categories(self):
        schema = DEFAULT_DB.with_name("collection_schema.sql").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "queue.sqlite"
            second = "https://commons.wikimedia.org/wiki/File:Example%2C_Detail.png"
            with closing(sqlite3.connect(path)) as db:
                db.executescript(schema)
                with db:
                    db.executemany(
                        "INSERT INTO collection_queue (id, file_url, category) VALUES (?, ?, ?)",
                        [(3, SOURCE, CATEGORY), (2, second, "公共场景/市场摊位")],
                    )
                self.assertEqual(db.execute(
                    "SELECT authored_status, authored_ref FROM collection_queue ORDER BY id"
                ).fetchall(), [("", ""), ("", "")])
                self.assertEqual(read_queue(path), [
                    (second, "File:Example,_Detail.png", "公共场景/市场摊位"),
                    (SOURCE, "File:Example.jpg", CATEGORY),
                ])
                with db:
                    db.execute("UPDATE collection_queue SET category = ? WHERE id = 3", ("../../other",))
                with self.assertRaisesRegex(ValueError, r"collection_queue\.id=3.*未知图片种类"):
                    read_queue(path)
                with db:
                    db.execute("UPDATE collection_queue SET category = ?, file_url = ? WHERE id = 3",
                               (CATEGORY, "https://example.org/wiki/File:Not-Commons.png"))
                with self.assertRaisesRegex(ValueError, r"collection_queue\.id=3.*Commons"):
                    read_queue(path)

    def test_queue_still_accepts_an_explicit_csv(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "test.csv"
            with path.open("w", encoding="utf-8", newline="") as f:
                csv.writer(f).writerows([["文件页", "图片种类"], [SOURCE, CATEGORY]])
            self.assertEqual(read_queue(path), [(SOURCE, "File:Example.jpg", CATEGORY)])

    def test_exif_oriented_jpeg_remains_identical_after_encoding(self):
        dimensions, result, resized = encode_png(example(), MAX_PNG_BYTES)
        self.assertFalse(resized)
        with Image.open(example()) as original, Image.open(BytesIO(result)) as saved:
            self.assertEqual((saved.format, dimensions), ("PNG", (48, 96)))
            self.assertEqual(saved.tobytes(), ImageOps.exif_transpose(original).tobytes())
            self.assertFalse(saved.getexif())

    def test_transparent_pixels_and_opaque_alpha_are_preserved(self):
        for alpha in (0, 255):
            with self.subTest(alpha=alpha):
                with Image.new("RGBA", (16, 16), (17, 67, 87, alpha)) as source:
                    output = BytesIO()
                    source.save(output, "PNG")
                    _, data, resized = encode_png(output, MAX_PNG_BYTES)
                    self.assertFalse(resized)
                    with Image.open(BytesIO(data)) as decoded:
                        self.assertEqual(decoded.format, "PNG")
                        self.assertEqual(decoded.tobytes(), source.tobytes())

    def test_jpg_resizes_proportionally_when_needed(self):
        with Image.effect_noise((3000, 2100), 45) as source:
            data = BytesIO()
            source.save(data, "PNG")
        size, full, resized = encode_jpg(data, MAX_PNG_BYTES)
        self.assertEqual(size, (3000, 2100))
        self.assertFalse(resized)
        limit = int(len(full) * 0.8)
        self.assertEqual(encode_jpg(data, limit, allow_resize=False)[0], size)
        dimensions, payload, resized = encode_jpg(data, limit)
        self.assertTrue(resized)
        self.assertLessEqual(len(payload), limit)
        self.assertAlmostEqual(dimensions[1], dimensions[0] * 0.7, delta=1)
        with Image.open(BytesIO(payload)) as decoded:
            self.assertEqual((decoded.format, decoded.size), ("JPEG", dimensions))

    def test_jpg_retries_when_optimized_encoder_fails(self):
        source = example()
        original_save = Image.Image.save

        def save_with_encoder_failure(image, output, **options):
            if options.get("optimize"):
                output.write(b"partial output")
                raise OSError("broken data stream when writing image file")
            return original_save(image, output, **options)

        with patch.object(Image.Image, "save", save_with_encoder_failure):
            dimensions, payload, resized = encode_jpg(source, MAX_PNG_BYTES)
        self.assertFalse(resized)
        with Image.open(BytesIO(payload)) as decoded:
            self.assertEqual((decoded.format, decoded.size), ("JPEG", dimensions))
            decoded.load()

    def test_jpg_with_transparency_uses_png(self):
        with tempfile.TemporaryDirectory() as d, Image.new("RGBA", (16, 16), (17, 67, 87, 16)) as original:
            data = BytesIO()
            original.save(data, "PNG")
            service = fake_commons()
            service.file_info.return_value[2].update(mime="image/png", width=16, height=16, size=data.tell())
            service.fetch.side_effect = lambda *_: data
            root = Path(d)
            record, _ = collect_one(root, service, (SOURCE, "File:Example.jpg", CATEGORY), {}, MAX_PNG_BYTES,
                                    output_format="jpg")
            self.assertTrue(record["file"].endswith(".png"))
            with Image.open(root / record["file"]) as saved:
                self.assertEqual(saved.tobytes(), original.tobytes())

    def test_saves_with_category_and_size_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            service = fake_commons()
            item = (SOURCE, "File:Example.jpg", CATEGORY)
            with self.assertRaisesRegex(Rejected, "超过 .* MB；未保存"):
                collect_one(root, service, item, {}, 1)
            self.assertFalse(list(root.rglob("*.png")))
            with patch("download_images.encode_png", return_value=((96, 48), bytes(MAX_PNG_BYTES + 1), True)):
                with self.assertRaisesRegex(Rejected, "超过 5 MB"):
                    collect_one(root, service, item, {}, MAX_PNG_BYTES + 1)
            record, _ = collect_one(root, service, item, {}, MAX_PNG_BYTES)
            self.assertEqual(record["file"], "img/居家场景/工具五金/zb-hardware-1234.png")
            self.assertEqual(record["limit_bytes"], 5_000_000)
            self.assertEqual(record["license"]["Artist"], "Example Artist")
            self.assertEqual([p.suffix for p in (root / "img").rglob("*") if p.is_file()], [".png"])
            state = load_records(root)
            self.assertEqual(collect_one(root, service, item, state, MAX_PNG_BYTES)[1], "已存在")
            with self.assertRaisesRegex(Rejected, "已归类"):
                collect_one(root, service, (SOURCE, "File:Example.jpg", "公共场景/市场摊位"), state, MAX_PNG_BYTES)
            self.assertEqual(service.fetch.call_count, 3)

    def test_oversize_png_is_resized_with_aspect_ratio_and_alpha(self):
        with Image.effect_noise((2700, 1800), 35).convert("RGB") as source:
            source.putpixel((50, 50), (0, 0, 0))
            data = BytesIO()
            source.save(data, "PNG", transparency=(0, 0, 0))
            full_size = data.tell()
        limit = int(full_size * 0.80)
        dimensions, payload, resized = encode_png(data, limit)
        self.assertTrue(resized)
        self.assertLessEqual(len(payload), limit)
        with Image.open(BytesIO(payload)) as saved:
            self.assertEqual((saved.format, saved.mode, saved.size), ("PNG", "RGBA", dimensions))
            self.assertGreaterEqual(dimensions[0], 2048)
            self.assertLess(dimensions[0], 2700)
            self.assertLessEqual(abs(dimensions[1] - dimensions[0] * 2 / 3), 1)
            self.assertLess(saved.getextrema()[3][0], 255)

    def test_soft_target_keeps_small_image_at_original_resolution(self):
        dimensions, payload, resized = encode_png(example(), MAX_PNG_BYTES, preferred=1)
        self.assertEqual(dimensions, (48, 96))
        self.assertFalse(resized)
        self.assertGreater(len(payload), 1)

    def test_png_shrinks_below_2048_when_needed_to_meet_hard_limit(self):
        data = BytesIO()
        with Image.frombytes("RGB", (2100, 1800), random.Random(0).randbytes(2100 * 1800 * 3)) as source:
            source.save(data, "PNG")
        dimensions, payload, resized = encode_png(data, MAX_PNG_BYTES)
        self.assertTrue(resized)
        self.assertLess(max(dimensions), 2048)
        self.assertLessEqual(len(payload), 5_000_000)
        self.assertAlmostEqual(dimensions[1], dimensions[0] * 1800 / 2100, delta=1)

    def test_recompression_uses_source_and_only_installs_smaller_result(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            service = fake_commons()
            item = (SOURCE, "File:Example.jpg", CATEGORY)
            records = {}
            record, _ = collect_one(root, service, item, records, MAX_PNG_BYTES)
            old_path = Path("images", *Path(record["file"]).parts[1:])
            file = root / old_path
            file.parent.mkdir(parents=True)
            (root / record["file"]).rename(file)
            record["file"] = old_path.as_posix()
            old = b"a" * 5_000_001
            file.write_bytes(old)
            with patch("download_images.encode_png", return_value=((96, 48), old, False)):
                with self.assertRaisesRegex(Rejected, "超过 5 MB"):
                    collect_one(root, service, item, records, MAX_PNG_BYTES, recompress=True)
            self.assertEqual(file.stat().st_size, len(old))
            record, state = collect_one(root, service, item, records, MAX_PNG_BYTES, recompress=True)
            self.assertEqual(state, "已重新压缩")
            self.assertEqual(record["preferred_bytes"], 5_000_000)
            self.assertLessEqual(file.stat().st_size, 5_000_000)
            self.assertEqual(load_records(root)[1234]["bytes"], file.stat().st_size)

    def test_non_approved_license_is_rejected_before_download(self):
        service = fake_commons("CC BY-NC 4.0")
        with tempfile.TemporaryDirectory() as d, self.assertRaisesRegex(Rejected, "许可需要人工确认"):
            collect_one(Path(d), service, (SOURCE, "File:Example.jpg", CATEGORY), {}, MAX_PNG_BYTES)
        service.fetch.assert_not_called()

    def test_api_token_not_sent_to_media_and_no_redirects(self):
        session = Mock()
        session.get.return_value.status_code = 200
        client = Commons(session, "collector@example.org", "dummy-token", "http://127.0.0.1:1277")
        with patch("download_images.time.sleep"):
            client.get("https://commons.wikimedia.org/w/api.php")
            client.get(MEDIA, media=True)
        api_call, media_call = session.get.call_args_list
        self.assertEqual(api_call.kwargs["headers"]["Authorization"], "Bearer dummy-token")
        self.assertNotIn("Authorization", media_call.kwargs["headers"])
        self.assertFalse(media_call.kwargs["allow_redirects"])
        self.assertEqual(api_call.kwargs["proxies"], media_call.kwargs["proxies"])
        self.assertEqual(media_call.kwargs["proxies"], {"https": "http://127.0.0.1:1277"})

    def test_long_retry_after_stops_without_retrying(self):
        session = Mock()
        session.get.return_value.status_code = 429
        session.get.return_value.headers = {"Retry-After": "120"}
        with self.assertRaisesRegex(StopBatch, "HTTP 429"):
            Commons(session, "collector@example.org", "").get(MEDIA, media=True)
        self.assertEqual(session.get.call_count, 1)

    def test_xlsx_has_two_columns_image_and_matching_category(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            records = {}
            item = (SOURCE, "File:Example.jpg", CATEGORY)
            record, _ = collect_one(
                root, fake_commons(), item, records, MAX_PNG_BYTES
            )
            service = fake_commons()
            self.assertEqual(collect_one(root, service, item, records, MAX_PNG_BYTES, output_format="jpg")[0], record)
            service.fetch.assert_not_called()
            _, title, info = service.file_info.return_value
            service.file_info.return_value = (2345, title, info)
            jpg, _ = collect_one(root, service, item, records, MAX_PNG_BYTES, output_format="jpg")
            self.assertTrue(jpg["file"].endswith(".jpg"))
            self.assertIn("Lossy JPEG", jpg["modifications"])
            with Image.open(root / jpg["file"]) as photo:
                self.assertEqual((photo.format, photo.size), ("JPEG", (48, 96)))
                self.assertFalse(photo.getexif())
            self.assertEqual(collect_one(root, service, item, load_records(root), MAX_PNG_BYTES)[0], jpg)
            service.fetch.assert_called_once()
            self.assertEqual(write_index(root, records), 2)
            xlsx = root / "图片分类.xlsx"
            self.assertFalse(list(root.glob("*.inspect.ndjson")))
            with ZipFile(xlsx) as z:
                sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
                self.assertEqual(
                    [c.attrib["r"] for c in sheet.findall(".//x:c", NS)],
                    ["A1", "B1", "A2", "B2", "A3", "B3"],
                )
                strings = ET.fromstring(z.read("xl/sharedStrings.xml"))
                shared = ["".join(s.itertext()) for s in strings.findall("x:si", NS)]
                values = []
                for cell in sheet.findall(".//x:c", NS):
                    if cell.get("t") == "s":
                        values.append(shared[int(cell.findtext("x:v", namespaces=NS))])
                    elif cell.get("t") == "inlineStr":
                        values.append("".join(t.text for t in cell.findall(".//x:t", NS)))
                    else:
                        values.append(cell.findtext("x:v", namespaces=NS))
                self.assertEqual(values, ["图片", "图片种类", Path(record["file"]).name, CATEGORY,
                                          Path(jpg["file"]).name, CATEGORY])
                drawing = ET.fromstring(z.read("xl/drawings/drawing1.xml"))
                self.assertEqual(drawing.find(".//d:from/d:col", NS).text, "0")
                self.assertEqual(drawing.find(".//d:from/d:row", NS).text, "1")
                self.assertEqual([row.text for row in drawing.findall(".//d:from/d:row", NS)], ["1", "2"])


if __name__ == "__main__":
    unittest.main()
