"""Open the offline form and QA report in Chromium, then test geometry and copying."""
import hashlib
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DELIVERY = ROOT / "outputs" / f"authoring_{HERE.name}"
IMAGE = "zb-transit-172600032.jpg"

assert set(x.name for x in DELIVERY.iterdir()) == {"author_record.html", IMAGE}
sha = hashlib.sha256((DELIVERY / IMAGE).read_bytes()).hexdigest()
assert sha == (HERE / "frozen.sha256").read_text().splitlines()[1].split()[0]
report = json.loads((HERE / "qa_report/report.json").read_text())["items"][0]
assert report["decision"] == "authoring_candidate" and not report["review"] and not report["blockers"]

def check_geometry(page, width):
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto((DELIVERY / "author_record.html").as_uri(), wait_until="load")
    images = page.locator(".image-frame img")
    assert images.count() == 2
    assert images.evaluate_all("(nodes) => nodes.every(i => i.complete && i.naturalWidth === 4032 && i.naturalHeight === 3024 && i.src === nodes[0].src)")
    first, second = [images.nth(i).bounding_box() for i in range(2)]
    assert abs(first["width"] - second["width"]) < 0.1
    if width > 700:
        assert abs(first["y"] - second["y"]) < 1
        assert second["x"] > first["x"] + first["width"]
    else:
        assert abs(first["x"] - second["x"]) < 1
        assert second["y"] > first["y"] + first["height"]
    markers = page.locator(".point")
    assert markers.count() == 3 and not page.locator("figure").first.locator(".point").count()
    for i, p in enumerate(report["platform_points"]):
        marker = markers.nth(i)
        actual = marker.bounding_box()
        x, y = p["xy"]
        assert marker.text_content() == str(i + 1)
        assert abs(actual["x"] + actual["width"] / 2 - (second["x"] + x / 4032 * second["width"])) < .2
        assert abs(actual["y"] + actual["height"] / 2 - (second["y"] + y / 3024 * second["height"])) < .2
    page.locator(".images").screenshot(path=HERE / f"offline_preview_{width}.png")


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    context = browser.new_context(offline=True)
    page = context.new_page()
    errors = []
    remote = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: remote.append(request.url) if request.url.startswith(("http:", "https:")) else None)
    for width in [1280, 430]:
        check_geometry(page, width)

    # Inspect actual clipboard contents on click. Capture the plain-text fallback
    # separately in a browser that simulates Clipboard API rejection.
    assert context.grant_permissions(["clipboard-read", "clipboard-write"]) is None
    page.set_viewport_size({"width": 1280, "height": 1000})
    page.reload(wait_until="load")
    assert page.locator("#prompt").input_value() == (HERE / "prompt.txt").read_text().strip()
    buttons = page.locator("[data-copy]")
    for button in buttons.all():
        target = button.get_attribute("data-copy")
        expected = page.locator("#" + target).input_value()
        assert expected
        button.click()
        assert page.evaluate("navigator.clipboard.readText()") == expected, target
    page.evaluate("""() => {
        Object.defineProperty(navigator.clipboard, "writeText", {
            value: async () => { throw new Error("restricted clipboard"); }
        });
        document.addEventListener("copy", event => {
            window.fallbackSelection = document.activeElement.value;
        });
    }""")
    page.locator("[data-copy=prompt]").click()
    assert page.evaluate("window.fallbackSelection") == (HERE / "prompt.txt").read_text().strip()
    assert page.evaluate("navigator.clipboard.readText()") == (HERE / "prompt.txt").read_text().strip()
    page.goto((HERE / "qa_report/index.html").as_uri(), wait_until="load")
    assert "authoring_candidate" in page.title() or "authoring_candidate" in page.locator("h2").first.text_content()
    assert page.locator("article img").evaluate("(img) => img.complete && img.naturalWidth > 0")
    assert not errors and not remote, (errors, remote)
    browser.close()
print("离线 Chromium 核验通过，宽屏和窄屏均正确，全部复制字段与回退复制通过。" )
