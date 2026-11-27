"""Check the delivered offline form in an existing local Chromium installation."""
import base64
import hashlib
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEST = ROOT / 'outputs' / ('authoring_' + HERE.name)
facts = json.loads((HERE / 'facts.json').read_text())
source = json.loads((HERE / 'source.json').read_text())
qa = json.loads((HERE / 'qa_report/report.json').read_text())['items'][0]
assert {p.name for p in DEST.iterdir()} == {'author_record.html', facts['image']}
original_bytes = (DEST / facts['image']).read_bytes()
assert original_bytes == (HERE / 'original.jpg').read_bytes()
assert hashlib.sha256(original_bytes).hexdigest() == source['sha256']
assert qa['decision'] == 'authoring_candidate' and not qa['blockers'] and not qa['review']

environment = dict(os.environ)
environment['LD_LIBRARY_PATH'] = '/tmp/zerobench-browser.XXBG5o/libs/usr/lib/x86_64-linux-gnu'
verification = {'viewports': [], 'copy_fields': [], 'network_requests': [], 'page_errors': []}
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(env=environment)
    context = browser.new_context(offline=True)
    context.grant_permissions(['clipboard-read', 'clipboard-write'])
    page = context.new_page()
    page.on('pageerror', lambda error: verification['page_errors'].append(str(error)))
    page.on('request', lambda request: verification['network_requests'].append(request.url)
            if request.url.startswith(('http:', 'https:')) else None)
    for width in [1440, 430]:
        page.set_viewport_size({'width': width, 'height': 1000})
        page.goto((DEST / 'author_record.html').as_uri(), wait_until='load')
        page.evaluate('document.fonts.ready')
        images = page.locator('.image-frame img')
        assert images.count() == 2
        assert images.evaluate_all('(images)=>images.every(i=>i.complete&&i.naturalWidth===2000&&i.naturalHeight===1333&&i.src===images[0].src)')
        embedded = images.first.get_attribute('src')
        assert base64.b64decode(embedded.split(',', 1)[1]) == original_bytes
        first, second = [images.nth(i).bounding_box() for i in (0, 1)]
        assert abs(first['width'] - second['width']) < .1
        if width > 700:
            assert abs(first['y'] - second['y']) < 1
            assert second['x'] > first['x'] + first['width']
        else:
            assert abs(first['x'] - second['x']) < 1
            assert second['y'] > first['y'] + first['height']
        assert page.locator('figure').first.locator('.point').count() == 0
        assert page.locator('.point').count() == 3
        for i, point in enumerate(facts['platform_points']):
            marker = page.locator('.point').nth(i)
            box = marker.bounding_box()
            x, y = point['xy']
            assert marker.text_content() == str(i + 1)
            assert abs(box['x'] + box['width'] / 2 - second['x'] - x / 2000 * second['width']) < .2
            assert abs(box['y'] + box['height'] / 2 - second['y'] - y / 1333 * second['height']) < .2
        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        page.locator('.images').screenshot(path=HERE / f'offline_preview_{width}.png')
        page.screenshot(path=HERE / f'page_top_{width}.png')
        verification['viewports'].append({'width': width, 'same_embedded_original': True,
                                          'marker_geometry': 'passed', 'layout': 'passed'})

    page.set_viewport_size({'width': 1440, 'height': 1000})
    page.reload(wait_until='load')
    assert page.locator('#prompt').input_value() == (HERE / 'prompt.txt').read_text().strip()
    for button in page.locator('[data-copy]').all():
        field = button.get_attribute('data-copy')
        expected = page.locator('#' + field).input_value()
        assert expected
        button.click()
        page.wait_for_function('document.getElementById("copy-status").textContent==="已复制纯文本"')
        assert page.evaluate('navigator.clipboard.readText()') == expected, field
        verification['copy_fields'].append(field)
    page.evaluate('''() => {
        Object.defineProperty(navigator.clipboard,'writeText',{value:async()=>{throw new Error('test fallback')}});
        document.addEventListener('copy',()=>{window.fallbackCopied=document.activeElement.value});
    }''')
    page.locator('[data-copy="prompt"]').click()
    assert page.evaluate('window.fallbackCopied') == (HERE / 'prompt.txt').read_text().strip()
    assert page.evaluate('navigator.clipboard.readText()') == (HERE / 'prompt.txt').read_text().strip()
    verification['fallback_copy'] = 'passed'
    page.goto((HERE / 'qa_report/index.html').as_uri(), wait_until='load')
    assert 'authoring_candidate' in page.locator('h2').first.inner_text()
    assert page.locator('article img').evaluate('(image)=>image.complete&&image.naturalWidth>0')
    page.screenshot(path=HERE / 'qa_report_browser.png')
    assert not verification['page_errors'] and not verification['network_requests']
    browser.close()

(HERE / 'html_verification.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2))
print('离线宽窄屏、原图字节、三点坐标、全部纯文本复制及回退复制核验通过。')
