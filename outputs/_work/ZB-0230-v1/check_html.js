const { chromium } = require('/home/wujacket218/.cache/uv/archive-v0/uhMVNp8DpEJRPwnR/playwright/driver/package');
const fs = require('fs');
(async () => {
 const browser = await chromium.launch({executablePath:'/home/wujacket218/.cache/ms-playwright/chromium_headless_shell-1255/chrome-headless-shell-linux64/chrome-headless-shell',args:['--no-sandbox']});
 const context = await browser.newContext({viewport:{width:1280,height:1000}});
 await context.grantPermissions(["clipboard-read", "clipboard-write"], {origin:"http://127.0.0.1:8765"});
 const page = await context.newPage();
 await page.goto('http://127.0.0.1:8765/outputs/authoring_ZB-0230-v1/author_record.html');
 const result = await page.evaluate(() => ({images:[...document.images].map(i=>({loaded:i.complete&&i.naturalWidth===1200,width:i.naturalWidth,height:i.naturalHeight})),points:[...document.querySelectorAll('.point')].map(p=>{const r=p.getBoundingClientRect(),i=p.parentElement.querySelector('img').getBoundingClientRect();return [(r.x+r.width/2-i.x)/i.width*1200,(r.y+r.height/2-i.y)/i.height*1600]}),columns:getComputedStyle(document.querySelector('.images')).gridTemplateColumns}));
 await page.screenshot({path:'outputs/_work/ZB-0230-v1/preview_desktop.png',fullPage:true});
 for (const button of await page.locator('[data-copy]').all()) {const id=await button.getAttribute('data-copy'); const expected=await page.locator('#'+id).textContent(); await button.click(); const copied=await page.evaluate(()=>navigator.clipboard.readText()); if(copied!==expected) throw new Error('copy mismatch '+id);}
 await page.setViewportSize({width:390,height:900}); result.mobile_columns=await page.evaluate(()=>getComputedStyle(document.querySelector('.images')).gridTemplateColumns); await page.screenshot({path:'outputs/_work/ZB-0230-v1/preview_mobile.png',fullPage:true});
 if(!result.images.every(x=>x.loaded)) throw Error('image failed');
 for (const [i,expected] of [[100,767],[513,635],[460,1020]].entries()) if(result.points[i].some((v,j)=>Math.abs(v-expected[j])>0.1)) throw Error('marker mismatch');
 result.copy_fields=6; fs.writeFileSync('outputs/_work/ZB-0230-v1/html_check.json',JSON.stringify(result,null,2)); console.log(JSON.stringify(result)); await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
