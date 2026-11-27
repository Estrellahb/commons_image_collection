import base64
import json
from html import escape
from pathlib import Path
from shutil import copyfile

work = Path(__file__).resolve().parent
manifest = json.loads((work / "manifest.json").read_text())["items"][0]
report = json.loads((work / "qa_report/report.json").read_text())["items"][0]
facts = json.loads((work / "facts.json").read_text())
analysis = json.loads((work / "recompute.json").read_text())
solution = analysis["baseline"]
source = manifest["source"]
points = manifest["platform_points"]
version = manifest["id"]
output = work.parent.parent / f"authoring_{version}"
output.mkdir(exist_ok=True)
image = (work / manifest["image"]).resolve()
image_url = "data:image/jpeg;base64," + base64.b64encode(image.read_bytes()).decode("ascii")
copyfile(image, output / image.name)


def text_block(value):
    return "".join(f"<p>{escape(part)}</p>" for part in value.strip().split("\n\n"))


def field(key, title, content, extra=""):
    return f"""<section aria-labelledby="{key}-head">
    <div class="section-head"><h2 id="{key}-head">{title} <span>{key}</span></h2>
    <button type="button" data-copy="{key}">复制</button></div>
    <div class="copy-value" id="{key}">{content}</div>{extra}
    </section>"""


def table(headers, rows):
    head = "".join(f'<th scope="col">{escape(str(col))}</th>' for col in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(col))}</td>" for col in row) + "</tr>"
        for row in rows
    )
    return f'<div class="table-scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def edge_text(pair):
    return "-".join(map(str, pair))


def ref_counts(values):
    return "、".join(map(str, values))


title = "香料摊的跨排配对"
license_link = escape(source["license_url"], quote=True)
source_link = escape(source["url"], quote=True)
metadata = [
    ("number", "题号", version),
    ("name", "题名", title),
    ("type", "题型", "计数聚合链（counting）"),
    ("level", "难度", "中等（medium）"),
    ("category", "图片大类与小类", "实拍密集场景照／市场摊位（公共场景）"),
    ("image-size", "原图尺寸", "1650 × 2320 像素"),
    ("source", "来源", f'<a href="{source_link}">{source_link}</a>'),
    ("photographer", "作者", "High Contrast"),
    ("license", "许可", f'CC BY 3.0 德国版 · <a href="{license_link}">{license_link}</a>'),
    ("attribution", "完整署名", "《Spices for sale in the Morocco》，High Contrast，Wikimedia Commons，CC BY 3.0 德国版。"
     f'<br>来源 <a href="{source_link}">{source_link}</a><br>许可 <a href="{license_link}">{license_link}</a>'
     "<br>沿用项目入库 JPEG。入库时曾重新编码并应用 EXIF 方向，保留原生画幅与分辨率。本题直接复制入库文件。"),
]
metadata_html = "".join(
    f'<tr><th scope="row">{label}</th><td id="{key}">{value}</td><td><button type="button" data-copy="{key}" aria-label="复制{label}">复制</button></td></tr>'
    for key, label, value in metadata
)
point_table = table(
    ["编号", "原图像素坐标 (x, y)", "证据"],
    [(i, tuple(point["xy"]), point["label"]) for i, point in enumerate(points, 1)],
)
markers = "".join(
    f'<span class="marker" style="--x:{point["xy"][0] / 16.5:.9f}%;--y:{point["xy"][1] / 23.2:.9f}%">{i}</span>'
    for i, point in enumerate(points, 1)
)

prompt = (work / "prompt.txt").read_text().strip()
thinking = """银罐的粉色和列位提供了两个直观的误配线索。上排左端和下排左端的粉堆都偏黄，但跨排同名的 CURCUMA 是上排最右和下排最左。GINGEMBRE 也跨列。罐名决定同名边身份、超远边资格以及窗口阶段是否纳入该边。

白牌下方另有一罐灰褐大块。它和左邻两只灰褐罐的内容形态相近，但牌挡住盖峰，影响参照可用集合及其编号。正确关联每只罐的自有盖顶后，才能将异名边的中点与参照比较，并从同一只参照的料形取两工况分值。关键判分字段是按参照的方案数、方案总数、并列数与代表码。"""
def silver_rows():
    for group, label in (("upper", "上排"), ("lower", "下排")):
        for i, obj in enumerate(facts[group], 1):
            yield label, i, obj["name"], obj["xy"][0]


reading = (
    text_block("按照片画面的横向顺序，从每只银罐的罐口追到其粉锥尖。下表给出图上品名和原生横坐标估读，单位为像素。")
    + table(["所在层板", "编号", "品名", "锥尖 x"], silver_rows())
    + text_block("上排第 4 罐可辨 GINGEMBR 词段，和下排第 2 罐对应。上排第 5 与下排第 1 罐读作 CURCUMA。上排左端是 CORIANDRE。")
    + table(["参照", "盖峰 x（px）", "内容物"], [(i, row["xy"][0], row["label"]) for i, row in enumerate(facts["references"], 1)])
    + text_block("左端深色大块、前缘卷片和暗红褐果荚、左下混色大杂碎及右下截入的纤维条均不符合表列形态。右后方白牌下还能看见一罐灰褐大块，所需的盖峰被牌遮盖。排除以后，石块类只占参照 2、3。")
)
bands = ("近", "中", "远", "超远")
matrix = table(
    ["上排＼下排", "1", "2", "3", "4", "5"],
    [(i, *[f"{bands[b]}（{d}）" for b, d in zip(b_row, d_row)])
     for i, (b_row, d_row) in enumerate(zip(solution["band_matrix"], solution["distance_matrix"]), 1)],
)
reasoning = (
    text_block("把两排锥尖的横坐标两两相减并取绝对值，得到下列档位矩阵，括号中是作者量值（px）。同名边为 4-2 和 5-1。")
    + matrix
    + text_block("""枚举 5! = 120 个下排编号排列。过滤掉异名超远边、同名边条数不为 1 或近边多于 2 的码，保留 13 个。对每个码逐只试配参照，统计离参照盖顶 x 不超过 117 px 的异名边。恰一条入窗且为中或远时，把该五码与参照编号计为一个方案。五只参照分别得到 5、7、6、5、0 个，共 23 个。

工况 A 的最低分出现在 13425/2 和 13425/3。前者的档位依次为近、中、中、远、近，两对逆序加 4，档位加 12，灰褐块参照加 4，合为 20。参照 2 的盖峰 x 为 744，异名边 2-3 中点为 671.5，入窗且为中边。两码的五位部分相同，选择编号较小的参照 2。

工况 B 的最低分出现在 14523/2 和 34125/2。代表方案 14523/2 有四对逆序、四条远边和一条近边，加上灰褐参照得 8 + 4 + 2 = 14 分。边 2-4 的中点 x 为 784，与盖顶横差 40 px，是唯一入窗的异名边。五码 14523 的字典序较小。""")
)
a, b = (solution["optimum"][key] for key in ("A", "B"))
response = (
    "1. " + "、".join(map(edge_text, solution["same_name"])) + "\n"
    + f"2. {ref_counts(solution['by_reference'])}，合计 {solution['total']}\n"
    + f"3. {a['score']}，{a['count']}，{a['representative']}\n"
    + f"4. {b['score']}，{b['count']}，{b['representative']}\n"
    + f"5. A {edge_text(a['window_edge'])}，B {edge_text(b['window_edge'])}"
)
rubric = '<h3>逐字段判分</h3>' + table(
    ["行", "逐项比较"],
    [
        ("1", "同名边列表须完整，保持上排编号升序，每对保留上排→下排方向。"),
        ("2", "按参照顺序比对五个整数，最后比对合计。保留第 5 只参照的 0。"),
        ("3", "依次比对 A 的整数最低分、并列完整方案数、五码/参照编号。"),
        ("4", "依次比对 B 的整数最低分、并列完整方案数、五码/参照编号。"),
        ("5", "按 A、B 顺序比对两条边，各保留上排→下排方向。"),
    ],
) + "<p>数字、边、分值和方案码容差为 0。中英文标点、空格、行号和单位标签可规范化。整题须全部字段一致。</p>"
comparisons = [
    ("正确读法", solution),
    ("将 5-1 错换成 1-1", analysis["alternatives"]["same_color_as_same_name"]["result"]),
    ("以白牌邻近的 x=1135 充作盖顶", analysis["alternatives"]["occluded_lid_as_visible"]["result"]),
]
comparison_rows = [
    (label, ref_counts(s["by_reference"]), s["total"],
     f"{s['optimum']['A']['representative']}（{s['optimum']['A']['count']} 并列）",
     f"{s['optimum']['B']['representative']}（{s['optimum']['B']['count']} 并列）")
    for label, s in comparisons
]
summary = (
    text_block(f"""本地图片指标质检结论为 {report['decision']}，阻断和待复核均为 0。逐张查阅 7 张原生 ROI，逐对复核 6 对近色候选和 12 对框重叠。品名为拉丁字母，汉字覆盖为 0%。画面未见可识别人脸或遮挡图证的水印。去掉上半部无法恢复同名和档位，去掉下半部无法恢复参照资格与窗口，题面和来源信息都没有提供这些事实。

每处锥尖、盖顶横坐标按 ±12 px 复核。距离档界的最小 margin 为 59 px，error_bound 为 24 px，R≈2.46。窗口最小 margin 为 27 px，error_bound 为 24 px，R=1.125。两项均以原图水平投影像素为单位。以误差上界联合扰动时，所有有效比较的结论均保持。

盲答分别使用空历史子代理三次，开放放大、裁图和计算，仅给冻结题面与干净原图。首版 3/3 整题正确。加入独立的下部参照图证后重新试答，定稿版 3/3 整题正确，11 个字段全部匹配。未出现超时、故障、残缺或可归因错答。按本地表现归为中等。""")
    + table(["复算读法", "按参照计数", "总数", "A 代表方案", "B 代表方案"], comparison_rows)
    + text_block("第一种误配同时改动同名集合、超远资格和窗口排除对象，两工况最低分仍为 20、14，但并列数和代表码均变。第二种误配把受遮挡对象纳入参照，表中是指定假坐标下的示例复算。")
)
font = base64.b64encode((work / "record_font.woff2").read_bytes()).decode("ascii")
font_license = (work / "record_font_OFL.txt").read_text()
css = f"@font-face{{font-family:PageChinese;src:url(data:font/woff2;base64,{font}) format('woff2');font-weight:400 700;font-display:swap}}" + """
:root{color-scheme:light;--ink:#182820;--muted:#4d6257;--line:#cddbd1;--accent:#1a634c;--paper:#f2f6f2;--surface:#fff}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.65 "PageChinese","Noto Sans CJK SC","PingFang SC","Microsoft YaHei",sans-serif}
main{width:min(1160px,100% - 48px);margin:0 auto;padding:40px 0 48px}
header{padding:8px 0 20px;border-bottom:3px solid var(--accent);margin-bottom:22px}
h1,h2,h3{line-height:1.28;margin:0;font-weight:700} h1{font-size:clamp(1.8rem,4vw,2.5rem)} h2{font-size:1.3rem} h3{font-size:1.05rem;margin-top:1.1em}
h2 span{font:normal .84rem ui-monospace,monospace;color:var(--muted);overflow-wrap:anywhere}
header p{margin:8px 0 0;color:var(--muted)}
section{margin:16px 0;padding:22px 24px;background:var(--surface);border:1px solid var(--line);border-radius:12px}
.section-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px}
button{font:inherit;font-size:.875rem;min-width:4.5rem;padding:4px 10px;border:1px solid #639780;border-radius:6px;color:var(--accent);background:#f0f7f2;cursor:pointer}
button:hover{background:#dcece1} :focus-visible{outline:2px solid #087658;outline-offset:3px}
p{margin:.65em 0}
a{color:var(--accent);overflow-wrap:anywhere}
table{border-collapse:collapse;width:100%;text-align:left;font-size:.92rem} td,th{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
thead th{background:#eaf2ec;color:#254232} th[scope=row]{min-width:7.6em} .metadata td:last-child{width:1%;white-space:nowrap}
.table-scroll{overflow:auto;margin:.65em 0}
.image-pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin:18px 0}
figure{margin:0} figcaption{color:var(--muted);margin-bottom:6px} .frame{position:relative;isolation:isolate}
.frame img{display:block;width:100%;height:auto} .marker{position:absolute;left:var(--x);top:var(--y);transform:translate(-50%,-50%);display:grid;place-items:center;width:1.65rem;height:1.65rem;border:2px solid white;background:#9b241b;color:white;border-radius:50%;font-weight:700;box-shadow:0 1px 4px #161616a8}
pre{font:inherit;white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f7f3;padding:16px;border:1px solid var(--line);border-radius:8px;margin:0}
#response{font-variant-numeric:tabular-nums}
#copy-status{position:fixed;bottom:1rem;right:1rem;background:#173a2d;color:white;padding:.45em .8em;border-radius:6px}
#copy-status:empty{display:none}
.clipboard-buffer{position:fixed;inset:0 auto auto -10000px}
@media(max-width:690px){main{width:calc(100% - 24px);padding:18px 0} section{padding:14px} .image-pair{grid-template-columns:minmax(0,1fr)} th[scope=row]{min-width:0} td,th{padding:7px 5px} .metadata button{min-width:3rem;padding-inline:5px}}
"""
script = """
document.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-copy]");
  if (!button) return;
  const status = document.getElementById("copy-status");
  const field = document.getElementById(button.dataset.copy);
  const plainText = field.innerText;
  try {
    try {
      await navigator.clipboard.writeText(plainText);
    } catch {
      const input = document.createElement("textarea");
      input.value = plainText;
      input.className = "clipboard-buffer";
      document.body.append(input);
      input.select();
      const copied = document.execCommand("copy");
      input.remove();
      button.focus();
      if (!copied) throw new Error("clipboard");
    }
    button.textContent = "已复制";
    status.textContent = "已复制纯文本";
  } catch {
    status.textContent = "剪贴板不可用，请选中字段文本复制";
  }
  clearTimeout(button.reset);
  button.reset = setTimeout(() => {
    button.textContent = "复制";
    status.textContent = "";
  }, 1500);
});
"""
image_common = f'src="{image_url}" width="1650" height="2320"'
html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · {version}</title>
<style>{css}</style>
<!-- Noto Sans SC webfont subset
{font_license.replace("--", "—")}
-->
</head>
<body>
<main>
<header><h1>{title}</h1><p>ZeroBench 平台填报 · {version}</p></header>
<section aria-labelledby="meta-head">
<h2 id="meta-head">基本信息</h2>
<div class="table-scroll"><table class="metadata"><tbody>{metadata_html}</tbody></table></div>
</section>
<section aria-labelledby="image-head">
<h2 id="image-head">原图与打点对照</h2>
<div class="image-pair">
<figure><figcaption>原图</figcaption><div class="frame"><img {image_common} alt="香料摊原图"></div></figure>
<figure><figcaption>打点图</figcaption><div class="frame"><img {image_common} alt="香料摊标注底图">{markers}</div></figure>
</div>
<p>坐标以原图左上角为原点，x 向右，y 向下。</p>
{point_table}
</section>
{field("prompt", "题目", f"<pre>{escape(prompt)}</pre>")}
{field("thinking", "出题思路", text_block(thinking))}
{field("cot_image_understanding", "图像识别", reading)}
{field("cot_reasoning", "题目推理", reasoning)}
{field("response", "标准答案", f"<pre>{escape(response)}</pre>", rubric)}
<section aria-labelledby="qa-head"><h2 id="qa-head">质检与复算摘要</h2>{summary}</section>
</main>
<div id="copy-status" role="status" aria-live="polite"></div>
<script>{script}</script>
</body>
</html>
"""
(output / "author_record.html").write_text(html, encoding="utf-8")
