"""Build the offline Chinese authoring form with the original image embedded."""
import base64
import html
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEST = ROOT / 'outputs' / ('authoring_' + HERE.name)


def read(name):
    return json.loads((HERE / name).read_text())


def escape(value):
    return html.escape(str(value), quote=True)


def button(target):
    return f'<button type="button" data-copy="{target}">复制</button>'


def table(headers, rows):
    head = ''.join('<th scope="col">' + escape(h) + '</th>' for h in headers)
    body = ''.join('<tr>' + ''.join('<td>' + escape(cell) + '</td>' for cell in row) + '</tr>' for row in rows)
    return '<div class="table-wrap"><table><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table></div>'


def section(target, title, plain, rich=None):
    if rich is None:
        rich = ''.join('<p class="plain">' + escape(p) + '</p>' for p in plain.split('\n\n'))
    return (f'<section><header><h2>{escape(title)}</h2>{button(target)}</header>'
            f'<textarea hidden readonly id="{target}">{escape(plain)}</textarea>{rich}</section>')


facts = read('facts.json')
source = read('source.json')
results = read('recompute.json')
qa = read('qa_report/report.json')['items'][0]
trials = read('blind_trials.json')
answer = results['baseline']['answer']
assert qa['decision'] == 'authoring_candidate'
assert len(trials['trials']) == 3 and all(t['valid'] for t in trials['trials'])
prompt = (HERE / 'prompt.txt').read_text().strip()
response = '\n'.join(f'{number} {json.dumps(value, ensure_ascii=False, separators=(",", ","))}'
                     for number, value in zip('①②③④⑤⑥', answer))
thinking = (
    '答题者须区分A5的零星前翅残斑与相邻标本的成片青绿色主斑，并区分C4的奶油色后翅斑与相邻标本的橙红色后翅斑。'
    'A5的F改变A—B可连边及单路线恰有一件F=0的约束。C4的H决定八件H和恰为7的可行条件，也决定工况1采用4b加价的路线。'
    'A5若误读为F=1，双路线数864变为1296，工况1最优代价和14变为13且规范代表改变。C4若误读为H=1，双路线可行集变为空。'
    '四列的斑纹、胸部位置和逐列编号共同提供输入，计算规则由本题规定。'
)
fact_rows = [(o['id'], f"({o['xy'][0]}, {o['xy'][1]})", o['F'], o['H'], o['evidence']) for o in facts['objects']]
recognition_intro = (
    '图中第2—5列分别为A—D，保留150<y<1130的胸部中心后，件数为5、6、5、6。'
    'F=0对象为A5、B4、C4、D1、D6，H=0对象为C4。'
    'A5的浅色鳞片仅余微小点状斑；B4有小乳黄点及暗淡零散鳞片。'
    'C4躯干斜向左下，左右前后翅应沿该躯干追溯。其H=0，依统一口径记F=0。C5的乳黄色上部下方仍有明确成片绿色主斑。'
    'D1与D6前翅为纯白短斑，D2—D5有青绿色斑群。手写种名、针和反光均按公开口径处理。'
)
recognition = recognition_intro + '\n\n逐对象事实表，胸部坐标为原生像素约数\n' + '\n'.join(
    ' | '.join(map(str, row)) for row in [('对象', '胸部中心', 'F', 'H', '图证'), *fact_rows])
excluded_rows = [(o['id'], str(o.get('xy', '整列')), o['why']) for o in facts['excluded']]
recognition += '\n\n窗口外与其他排除项\n' + '\n'.join(' | '.join(map(str, row)) for row in excluded_rows)
recognition_rich = ('<p>' + escape(recognition_intro) + '</p><h3>逐对象事实表</h3>' +
                    table(['对象', '胸部中心约数 / px', 'F', 'H', '图证'], fact_rows) +
                    '<h3>窗口外与其他排除项</h3>' + table(['对象', '中心约数 / px', '排除依据'], excluded_rows))
route_groups = Counter()
lookup = {(o['column'], o['rank']): o for o in facts['objects']}
for route in results['baseline']['routes']:
    zero = [col for col, rank in zip('ABCD', route) if lookup[(col, rank)]['F'] == 0]
    route_groups[zero[0]] += 1
reasoning = (
    '先逐列按胸部中心排序，先读取H，对H=0对象统一记F=0，其余按前翅读取F。相邻列逐对检查编号差≤2及F和≥1，得到三段边数20、20、20。'
    '在5×6×5×6个四元组中检查三条边、F和等于3、H和至少3，得到138条合法路线。'
    f'按唯一F=0所在列A—D分组，路线数依次为{route_groups["A"]}、{route_groups["B"]}、{route_groups["C"]}、{route_groups["D"]}。'
    '其中H和为3的44条，H和为4的94条。\n\n'
    '对两条不同合法路线组成的无序对，按A列编号排序，逐列检查P编号均严格小于Q，并检查八件H和等于7。'
    '严格逐列小于同时确保八件不复用，每份方案由规范P、Q唯一表示，共864份。'
    '因C4是唯一H=0对象，每份双路线方案恰含C4；其所在路线H和为3，另一条为4。\n\n'
    '工况0在全部864份方案上依次最小化(max(gP,gQ),gP+gQ)，最小值为(1,1)，有2份并列。'
    '两份方案为((1,1,1,1),(3,3,4,4))与((3,3,4,4),(5,5,5,5))。'
    '按拼接向量字典序选前一份，代价为0、1。\n\n'
    '工况1对含C4的路线加4b，对另一条加3(6-d)，在同一864份方案中得到最优(12,14)，唯一方案为'
    'P=(2,2,4,4)、Q=(4,5,5,6)。P的g0=4，加8得到12；Q的g0=2，加0得到2。'
    '规范代表为(2,2,4,4,4,5,5,6)。\n\n'
    'solver.py从单路线无序对筛选。verify_solver.py从每列两个编号的无序组合出发，构造各列严格递增的两条路线，'
    '独立得到相同计数、全部最优值、并列数和代表向量。'
)
scoring = (
    '逐字段判分共25项。①为四列各3项共12项，②为三段边数共3项，③④各1项，⑤⑥各有较大代价、代价和、并列数、完整代表向量4项。'
    '向量按整体精确判分，顺序为P的a,b,c,d再接Q的a,b,c,d。整数数值等价写法可归一化，允许常见中英文括号与分隔符。'
    '①的列顺序和②的段顺序固定，代表方案先按公开规则规范化。所有数值精确，无浮点容差。整题25项全部正确才计整题正确。'
)
counts = trials['evaluation']['counts']
trial_rows = [(t['id'], '有效', f"{t['correct_fields']}/25", '整题正确' if t['whole_correct'] else '存在错答',
               '、'.join(t['wrong_fields']) or '空') for t in trials['trials']]
trial_summary = (
    f'冻结版本ZB-0244-v3，3个独立新上下文子代理各试答一次，均只获公开题面与干净原图，工具开放。'
    f'有效试答3次，整题正确{counts["correct"]}次、完整错答{counts["incorrect"]}次，'
    f'超时{counts["timeout"]}次、工具故障{counts["infra_error"]}次、残缺答案{counts["partial"]}次。'
    '逐字段结果见下表。'
)
summary = (
    '本地图片质检最终decision为authoring_candidate，blockers和review均为空。22个人工对象框，3种F/H组合，'
    '6个关键ROI，原生短边1333px。近色候选12对、框重叠候选2对已逐对对照原生ROI核实归属，关键主斑可读。'
    '拉丁字母及数字标签经两次人工复核，汉字覆盖0，图面未见人脸及遮挡题证的水印。\n\n'
    '纵坐标纳入窗口的保守margin=20px，error_bound=5px，R=4。'
    '编号顺序在该定位误差内稳定。路线代价采用离散编号的题设公式。\n\n'
    '正确读法的双路线方案数864。易混读法一将A5的F改成1，A—B边数20→21，单路线138→145，'
    '双路线864→1296，工况1最优(12,14)→(12,13)，规范代表改为(2,2,4,4,5,5,5,6)。'
    '易混读法二将C4的H改成1，八件H和恰为7的约束得到0份可行方案。'
    '两条独立枚举路径对正确输入与两种替换均已核对一致。\n\n' + trial_summary + '\n\n' + trials['difficulty_decision'] + '\n\n'
    '去图或只读题面后缺少F/H及成员编号。单列裁图缺少其他列输入。四列整体裁图可保留全部图证，允许一次读图后编程。'
    '照片与来源页未给出本题新增约束的边数、路线或优化结果。\n\n'
    '官方原文件2000×1333，2261472字节，已逐字节核验。作者Haslemere Educational Museum，CC BY-SA 4.0，'
    '官方页有VRTS许可确认。去重覆盖当前数据库、来源台账、项目可见作者包和技能例题。'
    '外部难题300完整排除清单未随工作区提供。旧ZB-0244-v1备注为已释放临停稿，本版从公开原图重建。\n\n'
    '旧版ZB-0244-v2的三次有效盲答中2次全对、1次因C4暗灰绿残斑定义分歧而错答，另有1次超时。新版新增H=0时统一F=0的口径，使用全新上下文重做三次试答。\n\n'
    '已在离线浏览器检查宽屏与窄屏图像排列、3个标记的缩放位置、原图字节一致性及逐项复制纯文本结果。'
)
metadata = [
    ('question_id', '题号', HERE.name), ('title', '题名', '蝴蝶标本柜的双路线观察规划'),
    ('question_types', '题型', '计数聚合链；复杂指令遵循'),
    ('image_major', '图片大类', '真实照片'), ('image_minor', '图片小类', '小众专业实物／珠宝·矿物·标本／昆虫标本柜'),
    ('difficulty', '难度', trials['difficulty_label']), ('native_size', '原图尺寸', '2000×1333像素；JPEG；2261472字节'),
    ('source', '来源', source['source_page']), ('artist', '作者', 'Haslemere Educational Museum，Haslemere，Surrey，2019年12月'),
    ('license', '许可', 'CC BY-SA 4.0；https://creativecommons.org/licenses/by-sa/4.0/；官方VRTS ticket 2019120710000652'),
    ('modifications', '原文件与覆盖层', '照片从官方原文件下载并逐字节保留。右侧3个编号为HTML覆盖层，标记覆盖层按CC BY-SA 4.0提供。'),
]
meta_rows = ''.join('<tr><th scope="row">' + escape(label) + '</th><td>' + escape(value) +
                    f'<textarea id="{target}" readonly hidden>{escape(value)}</textarea></td><td>' +
                    button(target) + '</td></tr>' for target, label, value in metadata)
data_uri = 'data:image/jpeg;base64,' + base64.b64encode((DEST / facts['image']).read_bytes()).decode()
markers = ''.join(f'<span class="point" style="left:{p["xy"][0] / 20:.8f}%;top:{p["xy"][1] / 13.33:.8f}%" '
                  f'title="{escape(p["label"])}" aria-label="证据点{i}">{i}</span>'
                  for i, p in enumerate(facts['platform_points'], 1))
point_rows = [(i, f"({p['xy'][0]}, {p['xy'][1]})", p['label'])
              for i, p in enumerate(facts['platform_points'], 1)]
point_text = '\n'.join(' | '.join(map(str, row)) for row in point_rows)
image_compare = (
    '<section><header><h2>原图与打点对照</h2>' + button('platform_points') + '</header>'
    '<div class="images"><figure><figcaption>原图</figcaption><div class="image-frame">'
    f'<img src="{data_uri}" width="2000" height="1333" alt="干净原图，蝴蝶标本柜"></div></figure>'
    '<figure><figcaption>打点图</figcaption><div class="image-frame">'
    f'<img src="{data_uri}" width="2000" height="1333" alt="同一张原图，叠加三个作者证据标记">{markers}</div></figure></div>'
    '<p>坐标以原图左上角为原点，单位为像素。编号点为作者关键证据点。</p>' +
    table(['编号', '原图坐标 (x, y)', '证据说明'], point_rows) +
    '<textarea hidden readonly id="platform_points">' + escape(point_text) + '</textarea></section>'
)
font_css = ''
font_path = HERE / 'cjk_subset.woff2'
if font_path.exists():
    encoded = base64.b64encode(font_path.read_bytes()).decode()
    font_css = f'@font-face{{font-family:RecordSC;src:url(data:font/woff2;base64,{encoded}) format("woff2");font-display:swap}}'
css = '''
:root{color-scheme:light;font-family:RecordSC,system-ui,sans-serif;color:#20342e;background:#eff3ef;font-size:16px;line-height:1.7}
*{box-sizing:border-box}body{margin:0}main{max-width:1540px;margin:auto;padding:28px 24px 70px}
h1{font-size:30px;line-height:1.4;margin:0 0 22px}h2{font-size:22px;margin:0}h3{font-size:18px}
section{background:white;border:1px solid #cbd5cd;border-radius:10px;padding:24px;margin:20px 0}
header{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:18px}
button{font:inherit;font-size:14px;white-space:nowrap;cursor:pointer;border:1px solid #9eada4;background:#edf5ed;color:#1b4b39;border-radius:5px;padding:4px 14px}
button:focus-visible{outline:3px solid #d5a829}p{margin:12px 0}.plain{white-space:pre-wrap;overflow-wrap:anywhere}
.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:15px}td,th{padding:9px 12px;border:1px solid #d6ded8;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#f0f5ef;font-weight:600}
.images{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:20px}figure{margin:0;min-width:0}figcaption{font-weight:600;margin-bottom:8px}
.image-frame{position:relative;width:100%;line-height:0}.image-frame img{display:block;width:100%;height:auto}
.point{position:absolute;transform:translate(-50%,-50%);width:22px;height:22px;border-radius:50%;display:grid;place-items:center;background:#a32514;color:white;border:2px solid white;box-shadow:0 0 0 1px #482115;font:bold 12px/1 sans-serif}
a{color:#1e5b46;overflow-wrap:anywhere}footer{font-size:13px;color:#4f6258}.status{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:#163f2e;color:white;padding:8px 18px;border-radius:6px;z-index:10}.status:empty{display:none}
@media(max-width:700px){main{padding:18px 10px 45px}h1{font-size:25px}section{padding:16px 12px}.images{grid-template-columns:minmax(0,1fr);gap:20px}td,th{padding:8px}header{gap:8px}h2{font-size:19px}}
@media print{button,.status{display:none}section{break-inside:avoid;border-radius:0}main{padding:0}}
'''
script = '''
document.querySelectorAll('[data-copy]').forEach(button=>button.addEventListener('click',async()=>{
 const text=document.getElementById(button.dataset.copy).value;
 const fallback=()=>{const area=document.createElement('textarea');area.value=text;area.style.position='fixed';area.style.left='-10000px';document.body.appendChild(area);area.select();const ok=document.execCommand('copy');area.remove();if(!ok)throw new Error('copy');};
 try{if(navigator.clipboard&&navigator.clipboard.writeText){try{await navigator.clipboard.writeText(text);}catch(error){fallback();}}else{fallback();}
 document.getElementById('copy-status').textContent='已复制纯文本';}
 catch(error){document.getElementById('copy-status').textContent='复制失败，请使用浏览器选择文字复制';}
}));
'''
body = ('<h1>ZB-0244-v3 · 蝴蝶标本柜的双路线观察规划</h1>'
        '<section><header><h2>基本信息</h2></header><div class="table-wrap"><table><tbody>' + meta_rows + '</tbody></table></div>'
        '<p><a href="' + escape(source['source_page']) + '">Wikimedia Commons官方文件页</a> · '
        '<a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0许可原文</a></p></section>' + image_compare +
        section('prompt', '题目（prompt）', prompt) + section('thinking', '出题思路（thinking）', thinking) +
        section('cot_image_understanding', '图像识别（cot_image_understanding）', recognition, recognition_rich) +
        section('cot_reasoning', '题目推理（cot_reasoning）', reasoning) +
        section('response', '标准答案（response）', response,
                '<p class="plain">' + escape(response) + '</p><h3>逐字段判分口径</h3><p>' + escape(scoring) + '</p>') +
        section('qa_summary', '质检与复算摘要', summary,
                ''.join('<p>' + escape(p) + '</p>' for p in summary.split('\n\n')) +
                table(['轮次', '有效性', '正确字段', '整题结果', '关键错答字段'], trial_rows)) +
        '<footer>原图署名 Haslemere Educational Museum · CC BY-SA 4.0。原图像素与文件保持官方发布版本。'
        '公开题面版本ZB-0244-v3。作者记录包含标准答案。</footer>')
license_path = HERE / 'font_license.txt'
license_note = '\n<!--\n' + license_path.read_text().replace('--', '—') + '\n-->\n' if license_path.exists() else ''
page = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>ZB-0244-v3 中文作者填报页</title><style>' + font_css + css + '</style></head><body><main>' + body +
        '</main><div id="copy-status" class="status" role="status" aria-live="polite"></div><script>' + script +
        '</script>' + license_note + '</body></html>')
(DEST / 'author_record.html').write_text(page)
(HERE / 'author_record_fields.json').write_text(json.dumps({
    'prompt': prompt, 'thinking': thinking, 'cot_image_understanding': recognition,
    'cot_reasoning': reasoning, 'response': response, 'qa_summary': summary, 'scoring': scoring,
}, ensure_ascii=False, indent=2))
print(DEST / 'author_record.html')
