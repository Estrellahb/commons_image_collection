import json
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[2]
page_path = root / 'authoring_ZB-0230-v1' / 'author_record.html'
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/home/wujacket218/.cache/ms-playwright/chromium-1255/chrome-linux64/chrome', headless=True, args=['--no-sandbox'])
    context = browser.new_context(viewport={'width': 1280, 'height': 1000})
    page = context.new_page()
    page.goto(page_path.as_uri())
    page.wait_for_load_state('load')
    check = page.evaluate('''() => ({images: [...document.images].map(i=>({loaded:i.complete&&i.naturalWidth===1200, width:i.naturalWidth, height:i.naturalHeight})), points:[...document.querySelectorAll('.point')].map(p=>{let r=p.getBoundingClientRect(), i=p.parentElement.querySelector('img').getBoundingClientRect(); return [(r.x+r.width/2-i.x)/i.width*1200,(r.y+r.height/2-i.y)/i.height*1600]}), columns:getComputedStyle(document.querySelector('.images')).gridTemplateColumns})''')
    page.screenshot(path=str(Path(__file__).parent/'preview_desktop.png'),full_page=True)
    for button in page.locator('[data-copy]').all():
        target=button.get_attribute('data-copy')
        expected=page.locator('#'+target).inner_text()
        button.click()
        actual=page.evaluate('navigator.clipboard.readText()')
        assert actual == expected, target
    page.set_viewport_size({'width':390,'height':900})
    check['mobile_columns']=page.evaluate("getComputedStyle(document.querySelector('.images')).gridTemplateColumns")
    page.screenshot(path=str(Path(__file__).parent/'preview_mobile.png'),full_page=True)
    assert all(i['loaded'] for i in check['images'])
    for actual, expected in zip(check['points'],[(100,767),(513,635),(460,1020)]):
        assert all(abs(a-b)<0.1 for a,b in zip(actual,expected)), (actual,expected)
    check['copy_fields']=5
    (Path(__file__).parent/'html_check.json').write_text(json.dumps(check,ensure_ascii=False,indent=2))
    print(json.dumps(check,ensure_ascii=False))
    browser.close()
