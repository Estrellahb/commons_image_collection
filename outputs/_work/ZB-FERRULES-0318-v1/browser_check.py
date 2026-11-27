"""离线打开作者HTML，检查同图、缩放坐标与每一个复制按钮。"""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
HTML = ROOT.parents[1] / "authoring_ZB-FERRULES-0318-v1" / "author_record.html"

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, env={**os.environ,
        "LD_LIBRARY_PATH": "/tmp/zerobench-browser.XXBG5o/libs/usr/lib/x86_64-linux-gnu"})
    page = browser.new_page(viewport={"width": 1440, "height": 1080})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    # 捕获真正复制路径传入的纯文本，逐按钮与可见字段比较。
    page.add_init_script("""
    window.copies=[];
    Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copies.push(text)}}});
    document.execCommand=command=>{
      if(command==='copy'){window.copies.push(document.activeElement.value);return true;}
      return false;
    };
    """)
    page.goto(HTML.as_uri(), wait_until="load")
    page.evaluate("document.fonts.ready")
    page.wait_for_function("Array.from(document.images).every(i=>i.complete&&i.naturalWidth===4409)")
    assert page.locator("#prompt-text").inner_text() == (ROOT / "prompt.txt").read_text().strip()
    image_check = page.evaluate("""() => {
      const a=document.getElementById('clean-image'), b=document.getElementById('marked-image');
      return {sameSource:a.src===b.src, sizes:[a.naturalWidth,a.naturalHeight,b.naturalWidth,b.naturalHeight]};
    }""")
    assert image_check["sameSource"] and image_check["sizes"] == [4409, 3185, 4409, 3185]
    copy_checks = []
    for button in page.locator("button[data-copy]").all():
        key = button.get_attribute("data-copy")
        expected = page.locator("#" + key).text_content()
        button.click()
        page.wait_for_function("window.copies.length > 0")
        copied = page.evaluate("window.copies.pop()")
        assert copied == expected, key
        copy_checks.append({"field": key, "plain_text_equal": True, "characters": len(copied)})
    geometry = {}
    for label, viewport in [("wide", {"width": 1440, "height": 1080}),
                             ("narrow", {"width": 390, "height": 844})]:
        page.set_viewport_size(viewport)
        page.locator("#comparison").scroll_into_view_if_needed()
        result = page.evaluate("""() => {
          const images=[...document.querySelectorAll('.frame img')].map(i=>i.getBoundingClientRect().toJSON());
          const frame=document.querySelectorAll('.frame')[1].getBoundingClientRect();
          const points=[...document.querySelectorAll('.point')].map(p=>{
            const r=p.getBoundingClientRect();return [(r.x+r.width/2-frame.x)/frame.width,
              (r.y+r.height/2-frame.y)/frame.height];
          });
          return {images,points,overflow:document.documentElement.scrollWidth>innerWidth};
        }""")
        for actual, expected in zip(result["points"], [(2460 / 4409, 1870 / 3185),
                                                       (3010 / 4409, 2235 / 3185),
                                                       (3500 / 4409, 2200 / 3185)]):
            assert all(abs(a - b) < 0.001 for a, b in zip(actual, expected))
        first, second = result["images"]
        assert abs(first["width"] - second["width"]) < 0.1
        if label == "wide":
            assert abs(first["y"] - second["y"]) < 1
            assert second["x"] > first["x"]
        else:
            assert second["y"] > first["y"] + first["height"]
            assert not result["overflow"]
        geometry[label] = result
        page.locator("#comparison").screenshot(path=str(ROOT / ("preview_" + label + ".png")))
    assert not errors, errors
    (ROOT / "browser_checks.json").write_text(json.dumps({"offline_file_open": True,
        "images": image_check, "copy_buttons": copy_checks, "geometry": geometry,
        "javascript_errors": errors, "clipboard_test": "intercepted clipboard API and execCommand text"},
        ensure_ascii=False, indent=2))
    browser.close()
    print("Offline image, marker alignment, responsive layout and all copy buttons passed")
