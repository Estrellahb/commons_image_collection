"""离线浏览器确认两张图、响应式点位和真实剪贴板内容。"""
import base64
import hashlib
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

work = Path(__file__).resolve().parent
manifest = json.loads((work / "manifest.json").read_text())["items"][0]
folder = work.parent.parent / f"authoring_{manifest['id']}"
html_path = folder / "author_record.html"
source_path = (work / manifest["image"]).resolve()
image = source_path.read_bytes()
assert {p.name for p in folder.iterdir()} == {html_path.name, source_path.name}
assert (folder / source_path.name).read_bytes() == image
frozen_hashes = [line.split()[0] for line in (work / "frozen.sha256").read_text().splitlines()]
assert frozen_hashes == [hashlib.sha256(b).hexdigest() for b in ((work / "prompt.txt").read_bytes(), image)]

result = {"checks": []}
with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    context = browser.new_context(offline=True)
    context.grant_permissions(["clipboard-read", "clipboard-write"])
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    for width in (1320, 390):
        page.set_viewport_size({"width": width, "height": 1200})
        page.goto(html_path.as_uri(), wait_until="load")
        assert page.evaluate("location.protocol") == "file:"
        assert page.evaluate("async () => (await document.fonts.load('16px PageChinese', '香料摊')).every(font => font.status === 'loaded')")
        assert page.evaluate("document.fonts.check('16px PageChinese', '原图与打点对照')")
        pictures = page.locator(".image-pair img")
        assert pictures.count() == 2
        sources = []
        for pic in pictures.all():
            assert pic.evaluate("i => i.complete && i.naturalWidth===1650 && i.naturalHeight===2320")
            sources.append(pic.get_attribute("src"))
        assert sources[0] == sources[1]
        assert base64.b64decode(sources[0].split(",", 1)[1]) == image
        original = pictures.nth(0).bounding_box()
        marked = pictures.nth(1).bounding_box()
        assert abs(original["width"] - marked["width"]) < 1
        assert abs(original["height"] - marked["height"]) < 1
        if width == 1320:
            assert abs(original["y"] - marked["y"]) < 1 and original["x"] < marked["x"]
        else:
            assert abs(original["x"] - marked["x"]) < 1 and original["y"] < marked["y"]
        for locator, point in zip(page.locator(".marker").all(), manifest["platform_points"], strict=True):
            actual = locator.bounding_box()
            x, y = point["xy"]
            assert abs(actual["x"] + actual["width"] / 2 - (marked["x"] + marked["width"] * x / 1650)) < 1
            assert abs(actual["y"] + actual["height"] / 2 - (marked["y"] + marked["height"] * y / 2320)) < 1

        assert page.locator("#prompt").inner_text() == (work / "prompt.txt").read_text().strip()
        buttons = page.locator("button[data-copy]").all()
        for button in buttons:
            key = button.get_attribute("data-copy")
            button.click()
            page.wait_for_function("document.activeElement.textContent === '已复制'")
            expected = page.locator(f"#{key}").inner_text()
            actual = page.evaluate("navigator.clipboard.readText()")
            assert actual == expected, (key, expected, actual)
        assert not page_errors, page_errors
        page.locator(".image-pair").screenshot(path=work / f"record_images_{width}.png")
        result["checks"].append({"viewport": width, "images": 2, "marker_count": 3,
                                 "copy_fields": len(buttons), "clipboard": "actual_clipboard_plain_text"})
    page.goto((work / "qa_report/index.html").as_uri(), wait_until="load")
    assert page.locator("body").inner_text().count("authoring_candidate") >= 1
    result["qa_index_opened"] = True
    result["embedded_Chinese_font_loaded"] = True
    result["browser_version"] = browser.version
    result["sha256"] = frozen_hashes[1]
(work / "record_check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(result, ensure_ascii=False))
