from pathlib import Path
import html

root = Path(__file__).parent
prompt = (root/'prompt.txt').read_text().strip()
fields = {
'题目（prompt）': prompt,
'出题思路（thinking）': '必须区分前排多色混合胡椒与右侧纯红胡椒，并追踪茶牌尖脚与前方料格的关系。颜色判断决定互异约束及茶终点禁色，进而改变可行路线数、代价与不复用路线对；图中黄色牌面跨在后排颗粒前，不能以牌面遮挡位置认定料堆归属。',
'图像识别（cot_image_understanding）': '三排对象按左至右列号登记：A1 橙、A2 黄、A3 绿；B1 绿、B2 红、B3 黄；C1 杂、C2 白、C3 红。C1 可见红、白与深色颗粒混合，C2 为浅白颗粒，C3 为红色颗粒。前方 ORANGE TEA 牌尖插在第二列茶料，LOVE TEA 牌尖插在第三列茶料。牌面覆盖后排胡椒，牌尖和透明横隔板确定茶料归属。',
'题目推理（cot_reasoning）': '按 A、B、C、D 四个列号逐个枚举，先筛邻列差，再筛前三色互异及终点禁色。合法四元组为 1112、1122、1123、1212、1222、2123、3212、3222、3323，共 9 条，其中 D2 为 6 条，D3 为 3 条。工况甲最优 3323，基础代价 3+2+6+2=13，D3 加 0。工况乙最优 1112，基础代价 4+3+1+1=9，D2 加 0。两者终点不同。两路线各排均不重格的无序对共 5 对，基础代价和依次为 22、27、27、26、26，最小 22 仅一对，成员为 1112 与 3323。路线对交换顺序只计一次。',
'标准答案（response）': '① A：橙、黄、绿；B：绿、红、黄；C：杂、白、红。\n② 9；6；3。\n③ 13；1；(3,3,2,3)。\n④ 9；1；(1,1,1,2)。\n⑤ 1。\n⑥ 5；22；1。'
}
sections=[]
for i,(name,value) in enumerate(fields.items()):
 sections.append(f'<section><div class="sectionhead"><h2>{html.escape(name)}</h2><button type="button" data-copy="field{i}">复制</button></div><div class="copytext" id="field{i}">{html.escape(value)}</div></section>')
source='https://commons.wikimedia.org/wiki/File:Spice_Bazaar_18283738.jpg'
doc='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>ZB-0230-v1 作者记录</title><style>
*{box-sizing:border-box}body{font-family:system-ui,"Noto Sans CJK SC",sans-serif;color:#202a2d;background:#f3f5f2;margin:0;line-height:1.7}main{max-width:1250px;margin:auto;padding:28px}h1{font-size:2rem;margin:0}h2{font-size:1.35rem;margin:0}section{background:white;border:1px solid #d9e0dc;border-radius:12px;padding:22px;margin:20px 0}.sectionhead{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px}button{border:0;background:#1b6458;color:white;padding:9px 16px;border-radius:7px;cursor:pointer;font-size:1rem}button:focus-visible{outline:3px solid #d29431}.copytext{white-space:pre-wrap}table{width:100%;border-collapse:collapse}th,td{text-align:left;border-bottom:1px solid #dce3de;padding:9px;vertical-align:top}th{width:22%}.images{display:grid;grid-template-columns:1fr 1fr;gap:18px}.frame{position:relative;line-height:0}.frame img{width:100%;height:auto;display:block}.point{position:absolute;transform:translate(-50%,-50%);background:#ae251b;color:white;border:2px solid white;border-radius:50%;width:27px;height:27px;display:grid;place-items:center;font-size:14px;font-weight:bold;line-height:1;box-shadow:0 1px 5px #333}.caption{line-height:1.5;margin:8px 0}a{color:#165d52}#status{min-height:1.5em;color:#165d52}@media(max-width:700px){main{padding:12px}.images{grid-template-columns:1fr}section{padding:16px}th{width:34%}}
</style></head><body><main><header><h1>ZB-0230-v1 · 香料柜的跨层路线</h1><p>视觉联合推理 · 作者填报记录</p></header><section><div class="sectionhead"><h2>基本信息</h2><button type="button" data-copy="basic">复制</button></div><table><tr><th>题号与题名</th><td>ZB-0230-v1｜香料柜的跨层路线</td></tr><tr><th>题型与难度</th><td>计数聚合链｜中等</td></tr><tr><th>图片大类与小类</th><td>实拍密集场景照｜公共场景 / 市场摊位</td></tr><tr><th>原图尺寸与素材</th><td>1200 × 1600 像素｜真实照片｜官方原始 JPEG</td></tr><tr><th>来源与作者</th><td>Wikimedia Commons，Jon Eben Field (jefield) · <a href="SOURCE">来源文件页</a></td></tr><tr><th>许可</th><td>CC BY 2.0 · <a href="https://creativecommons.org/licenses/by/2.0/">许可原文</a> · 原图未修改</td></tr></table><div id="basic" hidden>题号：ZB-0230-v1
题名：香料柜的跨层路线
题型：计数聚合链
难度：中等
图片大类：实拍密集场景照
图片小类：公共场景 / 市场摊位
原图尺寸：1200 × 1600 像素
素材类型：真实照片
来源：https://commons.wikimedia.org/wiki/File:Spice_Bazaar_18283738.jpg
作者：Jon Eben Field (jefield)
许可：CC BY 2.0，https://creativecommons.org/licenses/by/2.0/
原图未修改</div></section><section><h2>原图与打点对照</h2><div class="images"><div><p class="caption">原图</p><div class="frame"><img src="Spice_Bazaar_18283738.jpg" alt="香料柜台原图"></div></div><div><p class="caption">打点图</p><div class="frame"><img src="Spice_Bazaar_18283738.jpg" alt="香料柜台关键证据打点图"><span class="point" style="left:8.333333%;top:47.9375%">1</span><span class="point" style="left:42.75%;top:39.6875%">2</span><span class="point" style="left:38.333333%;top:63.75%">3</span></div></div></div><ol><li>（100，767）左侧混色圆粒胡椒。</li><li>（513，635）白胡椒牌及其后方白色颗粒。</li><li>（460，1020）ORANGE TEA 牌及指向前方茶料的尖脚。</li></ol><p>坐标以原图左上角为原点，单位为像素。</p></section>SECTIONS<section><h2>逐字段判分口径</h2><p>① 三排颜色及顺序均精确；② 总数及两个终点数分别判分；③④ 各自的代价、数量、四元组逐项判分；⑤ 精确判位；⑥ 路线对数、最小和、并列数逐项判分。整数无容差，代价无单位。</p></section><section><h2>质检与复算摘要</h2><ul><li>本地指标报告为 authoring_candidate，blocked 和 needs_review 均为空。11 个人工样本框中近色异类与重叠候选均为 0，已按原生 ROI 复核色块、层位、牌尖与可读性。</li><li>正确读法有 9 条合法路线、5 对互不复用路线；将 C1 混色误归为红色后，分别变为 7 条和 1 对，工况乙最小代价由 9 变为 13。易混读法是作者反事实。</li><li>修订版三次独立有效盲答均整题正确，全部字段与标准答案一致。前版三次亦全对，增加了互不复用路线对约束。此记录反映本地试答，难度登记为中等。</li><li>图片无汉字、可识别人脸或遮挡题证的水印。列号差为离散规则，无测距阈值。去图与单排裁图不能恢复完整输入，覆盖全部证据的大裁图可以解题。</li></ul></section><p id="status" role="status" aria-live="polite"></p></main><script>
document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {const text=document.getElementById(button.dataset.copy).textContent; const status=document.getElementById('status'); try {if(navigator.clipboard && window.isSecureContext){await navigator.clipboard.writeText(text)}else{const el=document.createElement('textarea');el.value=text;el.style.position='fixed';el.style.left='-9999px';document.body.appendChild(el);el.select();const ok=document.execCommand('copy');el.remove();if(!ok) throw new Error('copy failed')} button.textContent='已复制';status.textContent='已复制纯文本';setTimeout(()=>button.textContent='复制',1800)}catch(e){status.textContent='复制失败，请选中正文手动复制。'}}));
</script></body></html>'''.replace('SOURCE',source).replace('SECTIONS',''.join(sections))
Path('outputs/authoring_ZB-0230-v1/author_record.html').write_text(doc,encoding='utf-8')
