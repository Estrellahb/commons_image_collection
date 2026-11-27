"""Render the self-contained platform form from the frozen inputs and reviewed results."""
import html
import json
import shutil
from collections import defaultdict
from pathlib import Path

from solver import load_rows

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEST = ROOT / "outputs" / f"authoring_{HERE.name}"


def read_json(path):
    return json.loads((HERE / path).read_text())


def esc(value):
    return html.escape(str(value), quote=True)


def table(headers, rows):
    head = "".join(f"<th scope='col'>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{esc(v)}</td>" for v in row) + "</tr>" for row in rows)
    return f"<div class='table'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def button(field):
    return f"<button type='button' data-copy='{field}'>复制</button>"


def field(field_id, title, plain, rich=None):
    paragraphs = "".join(f"<p>{esc(p)}</p>" for p in plain.strip().split("\n\n"))
    return (
        f"<section><header><h2>{title} <small>{field_id}</small></h2>{button(field_id)}</header>"
        f"<textarea id='{field_id}' hidden readonly>{esc(plain.strip())}</textarea>"
        f"{rich if rich is not None else paragraphs}</section>"
    )


source = read_json("source.json")
photo = ROOT / source["file"]
results = read_json("recompute.json")
baseline = results["baseline"]
alternative = results["alternative"]
facts = load_rows()
manifest = read_json("manifest.json")["items"][0]
qa = read_json("qa_report/report.json")["items"][0]
blind = read_json("blind_trials.json")
assert qa["decision"] == "authoring_candidate"
assert blind["counts"]["correct"] == len(blind["trials"]) == 3

by_flight = {r.flight: r for r in facts}
candidate_flights = {r["flight"] for ps in baseline["candidate_pairs"].values()
                     for pair in ps for r in pair}
used_gates = {by_flight[f].gate for f in candidate_flights}
gate_rows = defaultdict(list)
for row in facts:
    gate_rows[row.gate].append(f"{row.screen} {row.flight}")
repeated_gates = [(gate, len(gate_rows[gate]), "、".join(gate_rows[gate]))
                  for gate in sorted(used_gates) if len(gate_rows[gate]) > 1]
object_facts = [
    (r.screen, r.row_number, r.time, r.destination, r.flight, r.help or "空", r.gate or "空")
    for r in facts if r.flight in candidate_flights
]

image_intro = (
    "A–D 是从左到右的四块屏，屏内数据行从上往下编号，每屏 31 行。"
    "C 屏第 2 行 FR421、D 屏第 2 行 EJU7843 和第 15 行 EZY2180 的 Gate 为 H。"
    "C 屏第 20 行 AA6902 的 Gate 空白。这四行排除。B 屏 EZY2162 的 H1 合格，但没有合格的跨屏 Manchester 对手。"
    "C 屏第 8、11 行均显示 10:20 London Heathrow，分别是 BA429/D16 与 CZ7603/D25，各自都能与 D 屏 BA431/D18 配对。"
    "B 屏第 4 行 DL9235 的 Help 为空，下一行 UA9791 才带 T3。"
)
facts_headers = ("屏", "行", "计划时间", "目的地", "航班号", "Help", "Gate")
gate_headers = ("Gate", "行数", "屏与航班号")
image_plain = image_intro + "\n\n所有进入候选对的航班行\n" + "\n".join(
    " | ".join(map(str, values)) for values in [facts_headers, *object_facts]
) + "\n\n候选用到的重复 Gate 及照片中全部同口航班行\n" + "\n".join(
    " | ".join(map(str, values)) for values in [gate_headers, *repeated_gates]
) + "\n其余候选用到的 Gate 在全图只出现一次。"
image_rich = (
    f"<p>{esc(image_intro)}</p><h3>所有进入候选对的航班行</h3>{table(facts_headers, object_facts)}"
    f"<h3>候选用到的重复 Gate</h3>{table(gate_headers, repeated_gates)}"
    "<p>其余候选用到的 Gate 在全图只出现一次。</p>"
)

pair_facts = []
for screen_pair, pairs in baseline["candidate_pairs"].items():
    for a, b in pairs:
        pair_facts.append((screen_pair, a["destination"], a["flight"] + " / " + b["flight"],
                           sum(bool(r["help"]) for r in (a, b))))
pair_headers = ("跨屏", "目的地", "航班配对", "带 Help 行数")
removal_reasons = {
    "CI9225": "原最优方案失效。Heathrow 的 CZ7603 组合与 Stockholm 组合并列。",
    "CI9291": "C5 少一行，复用 C5 的 Stockholm 组合降至 135 点。",
    "CI9293": "原最优方案失效。Heathrow 的 CZ7603 组合与 Stockholm 组合并列。",
    "DL9351": "C11 少一行，原最优方案少付 25 点。",
    "DL9427": "全部含 Zurich 的完整方案失效，Madrid / Warsaw 组合以 175 点取胜。",
    "EI603": "D18 少一行，Heathrow 的 CZ7603 组合降至 135 点。",
    "UA9791": "全部含 Zurich 的完整方案失效，Madrid / Warsaw 组合以 175 点取胜。",
    "VY8379": "B17 少一行，复用 B17 的 Stockholm 组合降至 135 点。",
}
removals = [(f, cost, removal_reasons[f])
            for f, cost in baseline["q5"]["minimum_after_removal"].items()]
removal_headers = ("撤下航班", "新最低成本（点）", "复算依据")
reason_paragraphs = [
    "用完整目的地名在六个跨屏组合中配对。AB、AC、AD、BC、BD、CD 分别有 2、5、6、1、4、4 对。",
    "依次取 AB×CD、AC×BD、AD×BC。三个乘积有 8、20、6 种，两对目的地在这些乘积中均不同。按四行恰有一个 Help 筛成 4、10、3 种。每个方案在唯一的屏幕分组下枚举一次。",
    "常规成本最低方案由 Zurich 和 Stockholm 组成，时间差为 5 与 5 分钟，共 10 点。它有两次字母切换，C5 和 B17 各多一行，拥挤成本为 10 + 2×50 + 2×25 = 160 点。",
    "拥挤工况最优方案由 Zurich 和 Paris de Gaulle 组成。两对时间差为 5 与 60 分钟，只有 Zurich 发生字母切换。四行的 Gate 为 D82、B35、C15、C11，只有 C11 另有一行，故成本为 65 + 50 + 25 = 140 点。两工况均唯一最优。枚举时仍先保留全部同分最优方案，再按 A、B、C、D 航班号元组取字典序首项。",
    "依次撤下 124 个航班行。每次删除包含该行的完整方案，再用剩余行重算所有方案的 Gate 重数。以下八种使最低成本变化。",
]
reason_plain = reason_paragraphs[0] + "\n\n" + "\n".join(
    " | ".join(map(str, values)) for values in [pair_headers, *pair_facts]
) + "\n\n" + "\n\n".join(reason_paragraphs[1:]) + "\n" + "\n".join(
    " | ".join(map(str, values)) for values in [removal_headers, *removals]
)
reason_rich = (f"<p>{esc(reason_paragraphs[0])}</p>{table(pair_headers, pair_facts)}"
               + "".join(f"<p>{esc(p)}</p>" for p in reason_paragraphs[1:])
               + table(removal_headers, removals))

answer = (
    "1. 2，5，6，1，4，4\n"
    "2. 4，10，3\n"
    "3. 10 点，1 个，DL9427、UA9791、DL9184、SK556\n"
    "4. 140 点，1 个，DL9427、UA9791、CI9293、CI9225\n"
    "5. 8 种\n" + "\n".join(f"{f} → {cost} 点" for f, cost, _ in removals)
)
answer_html = (
    f"<pre>{esc(answer)}</pre><h3>逐字段判分口径</h3>"
    + table(("项", "口径"), [
        ("1", "六个候选对数逐个比较，按 AB、AC、AD、BC、BD、CD。"),
        ("2", "三个完整方案数逐个比较，按 AB/CD、AC/BD、AD/BC。"),
        ("3、4", "成本点、最优方案数、四个有序航班号各自比较。航班号保留前导零。"),
        ("5", "分别核对情形数及有序撤下清单中的各航班号和新成本。完整清单须无缺漏、额外项或重复。"),
    ]) + "<p>整数和成本的容差均为 0。标点、分隔空格及等值数值写法可规范化。整题正确须全部字段匹配。</p>"
)
thinking = (
    "同一时刻的 B 屏 Frankfurt 和 Zurich 只隔一行。T3 的横行归属决定 AB 的 Zurich 对能否作为唯一的 Help 来源，"
    "也决定 BD 的 Frankfurt 对是否因有两个 Help 而失去资格。错绑会改变完整方案数、两种最低成本和撤下一行的敏感情形。"
    "\n\n"
    "图中两处 C11 属于不同航班。B 屏 Split 的 DL9351 无跨屏同名候选，仍与 D 屏 CI9225 构成同口占用。"
    "若遗漏这个对应，拥挤最低成本少 25 点。C 屏两条 Heathrow 行同目的地同时间，须用航班号和 D16、D25 保留为两个实体。"
)

metadata = [
    ("题号", HERE.name), ("题名", "四屏航班配对与登机口拥挤"),
    ("题型", "复杂指令遵循"), ("辅助题型", "计数聚合链、抗干扰文本读取"),
    ("难度", "中等"), ("图片大类", "实拍文字载体照"),
    ("图片小类", "交通枢纽 · 机场出发航班电子屏"),
    ("素材类型", "真实照片"), ("原图尺寸", "4032 × 3024 像素"),
    ("原图文件", photo.name), ("来源", source["source_page"]),
    ("作者", "Sebleouf"), ("许可", "CC BY-SA 4.0"),
    ("许可链接", source["license"]["LicenseUrl"]),
    ("处理记录", "采集入库时曾重编码 JPEG 并处理 EXIF，未缩放。交付文件逐字节复制库内原图。"),
]
info_rows = []
for i, (label, value) in enumerate(metadata):
    field_id = f"meta-{i}"
    visible = f"<a href='{esc(value)}'>{esc(value)}</a>" if value.startswith("https://") else esc(value)
    info_rows.append(f"<tr><th scope='row'>{label}</th><td>{visible}<textarea id='{field_id}' hidden readonly>{esc(value)}</textarea></td><td>{button(field_id)}</td></tr>")
info = "<section><h2>基本信息</h2><div class='table'><table>" + "".join(info_rows) + "</table></div></section>"

marks = []
point_rows = []
for i, point in enumerate(manifest["platform_points"], 1):
    x, y = point["xy"]
    point_rows.append((i, f"({x}, {y})", point["label"]))
    marks.append(f"<span class='point' data-x='{x}' data-y='{y}' title='{esc(point['label'])}' style='left:{x / 4032:.10%};top:{y / 3024:.10%}'>{i}</span>")
point_text = "\n".join(f"{n}. {xy}  {desc}" for n, xy, desc in point_rows)
img = f"<img src='{esc(photo.name)}' width='4032' height='3024' alt='四块并排的机场出发航班屏'>"
comparison = (
    f"<section><header><h2>原图与打点对照</h2>{button('platform_points')}</header>"
    f"<textarea id='platform_points' hidden readonly>{esc(point_text)}</textarea>"
    f"<div class='images'><figure><div class='image-frame'>{img}</div><figcaption>干净原图</figcaption></figure>"
    f"<figure><div class='image-frame'>{img}{''.join(marks)}</div><figcaption>打点图</figcaption></figure></div>"
    "<p>坐标使用原图像素，以左上角为原点，x 向右，y 向下。</p>"
    + table(("编号", "原图坐标 (x, y)", "证据说明"), point_rows) + "</section>"
)

qa_html = (
    "<section><h2>质检与复算摘要</h2>"
    f"<p>离线质检判定为 <code>{qa['decision']}</code>。124 个航班行全部核对，8 个关键区域可在原生像素下读取。"
    "逐行框无重叠候选。84 对近色异类行共享相似底色，按横行、字段列及字符区分。汉字覆盖 0%，"
    "无可辨识人脸及遮挡图证的水印。题目使用离散读数，连续测距阈值与误差比不适用。</p>"
    "<p>只读题面或单屏裁图无法恢复跨屏配对及完整登机口重数。题目允许查看含四屏的裁图并编程求解。"
    "场景去重覆盖本地已登记条目与现有题包，工作区未提供单独的全项目排除表。</p>"
    + table(("读法", "完整方案数", "常规最低（点）", "拥挤最低（点）", "撤下情形数"), [
        ("正确读法", "4 / 10 / 3", 10, 140, 8),
        ("把 B 屏 T3 上移一行", "0 / 5 / 3", 125, 175, 4),
        ("把 B 屏 DL9351 的 C11 误读为 C1", "4 / 10 / 3", 10, 115,
         results["alternative_gate"]["q5"]["count"]),
    ])
    + "<p>冻结版的 3 次独立盲答均完整且整题全对，关键错答字段为零，超时、故障和残缺均为零。"
    "第一版 3 次全对后加入 Gate 重数及撤下行后的动态重算。新版仍为 3 次全对，登记为中等难度。</p></section>"
)

prompt = (HERE / "prompt.txt").read_text()
page = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>四屏航班配对与登机口拥挤 · ZeroBench 作者记录</title>
<style>
:root { color-scheme: light; font: 16px/1.65 system-ui, "Noto Sans CJK SC", sans-serif; color: #17242d; background: #eef2f4; }
* { box-sizing: border-box; }
body { margin: 0; }
main { max-width: 1280px; margin: auto; padding: 24px clamp(12px, 3vw, 40px) 48px; }
h1 { margin: 0 0 20px; font-size: clamp(24px, 3vw, 38px); line-height: 1.25; }
h2 { font-size: 21px; margin: 0 0 8px; }
h3 { font-size: 17px; margin: 16px 0 6px; }
small { color: #486374; font-size: 0.67em; font-weight: 500; overflow-wrap: anywhere; }
section { background: #fff; border: 1px solid #d6e2e8; border-radius: 12px; padding: clamp(14px, 2.5vw, 26px); margin-bottom: 18px; }
section header { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
p { margin: 8px 0; }
a { color: #175473; overflow-wrap: anywhere; }
button { background: #e7f2f9; color: #153f57; border: 1px solid #a9c7d9; border-radius: 6px; cursor: pointer; font: inherit; font-size: 14px; padding: 3px 10px; white-space: nowrap; }
button:focus-visible, a:focus-visible { outline: 2px solid #175473; outline-offset: 2px; }
.table { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
th, td { border-bottom: 1px solid #dfe8ed; padding: 6px 9px; text-align: left; vertical-align: top; }
th { background: #f3f7f9; white-space: nowrap; }
.images { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 10px 0; }
figure { margin: 0; }
figcaption { margin-top: 5px; text-align: center; }
.image-frame { position: relative; }
.image-frame img { display: block; width: 100%; height: auto; }
.point { position: absolute; display: grid; place-items: center; width: 19px; height: 19px; transform: translate(-50%, -50%); border-radius: 50%; background: #a12608; color: #fff; border: 1px solid #fff; font: bold 11px system-ui, sans-serif; box-shadow: 0 0 0 1px #22150d; }
pre { font: inherit; white-space: pre-wrap; overflow-wrap: anywhere; }
.copy-fallback { position: fixed; left: 10px; bottom: 10px; width: 250px; min-height: 80px; opacity: 0; }
.copy-fallback.manual { opacity: 1; }
@media (max-width: 700px) { .images { grid-template-columns: 1fr; } }
</style>
</head>
<body><main>
<h1>四屏航班配对与登机口拥挤</h1>
""" + info + comparison + field("prompt", "题目", prompt) + field(
    "thinking", "出题思路", thinking
) + field("cot_image_understanding", "图像识别", image_plain, image_rich) + field(
    "cot_reasoning", "题目推理", reason_plain, reason_rich
) + field("response", "标准答案", answer, answer_html) + qa_html + """
</main>
<script>
document.querySelectorAll("[data-copy]").forEach(button => {
  button.addEventListener("click", async () => {
    const plain = document.getElementById(button.dataset.copy).value;
    try {
      await navigator.clipboard.writeText(plain);
      button.textContent = "已复制";
    } catch (_) {
      const box = document.createElement("textarea");
      box.className = "copy-fallback";
      box.value = plain;
      box.readOnly = true;
      box.setAttribute("aria-label", "待复制纯文本");
      document.body.append(box);
      box.select();
      if (document.execCommand("copy")) {
        box.remove();
        button.focus();
        button.textContent = "已复制";
      } else {
        box.classList.add("manual");
        box.addEventListener("blur", () => box.remove(), {once: true});
        button.textContent = "按 Ctrl/Cmd+C 复制";
        return;
      }
    }
    setTimeout(() => { button.textContent = "复制"; }, 1400);
  });
});
</script>
</body></html>
"""

DEST.mkdir(exist_ok=True)
shutil.copyfile(photo, DEST / photo.name)
(DEST / "author_record.html").write_text(page, encoding="utf-8")
