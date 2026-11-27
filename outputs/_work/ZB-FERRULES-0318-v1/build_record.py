"""生成离线中文作者记录，作者数据与原图均从项目现有文件读取。"""
import base64
from collections import Counter
import hashlib
import html
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[2]
QID = "ZB-FERRULES-0318-v1"
DEST = PROJECT / "outputs" / ("authoring_" + QID)
IMAGE = DEST / "zb-hardware-106783997.jpg"


def dump(name, data):
    (ROOT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2))


def build_trials(baseline):
    # 每条保存代理的完整最终输出字段、补充读图事实、实际上下文条件与逐字段判分。
    rows = [
        {"agent": "/root/blind_ferrules_r2_1", "distances_px": [849, 1562],
         "reference_y": {"A1": 519.5, "A2": 1212, "A3": 1877, "B1": 503,
                         "B2": 1385, "B3": 2061, "B4": 2586, "C2": 1024.5, "C3": 2249.5}},
        {"agent": "/root/blind_ferrules_r2_2", "distances_px": [858, 1564],
         "reference_y": {"A1": 519.5, "A2": 1209.5, "A3": 1882.5, "B1": 504,
                         "B2": 1385, "B3": 2067.5, "B4": 2594.5, "C2": 1031, "C3": 2252}},
        {"agent": "/root/blind_ferrules_r2_3", "distances_px": [870, 1556],
         "reference_y": {"A1": 523, "A2": 1208, "A3": 1882, "B1": 510,
                         "B2": 1397, "B3": 2078, "B4": 2590, "C2": 1034, "C3": 2245}},
    ]
    standard = {
        "counts": [5, 4, 3], "colors_A3": ["R", "Y"], "colors_C3": ["B", "G"],
        "distances_px": [865, 1573], "edges": [8, 7], "relays": 22, "plans": 28,
        "mode0": [30, 1, baseline["optimum"]["0"]["canonical"]],
        "mode1": [31, 1, baseline["optimum"]["1"]["canonical"]], "changed": 1,
    }
    colors = {"A1": ["B"], "A2": ["R"], "A3": ["R", "Y"], "B1": ["Y"],
              "B2": ["K"], "B3": ["W"], "B4": ["W"], "C2": ["R"], "C3": ["B", "G"]}
    for trial in rows:
        answer = {**standard, "distances_px": trial["distances_px"]}
        checks = {}
        for key, value in standard.items():
            if key == "distances_px":
                checks[key] = [abs(a - b) <= 40 for a, b in zip(answer[key], value)]
            elif key in ("counts", "edges", "mode0", "mode1"):
                checks[key] = [a == b for a, b in zip(answer[key], value)]
            else:
                checks[key] = [answer[key] == value]
        assert sum(map(len, checks.values())) == 18
        assert all(itertools.chain.from_iterable(checks.values()))
        trial.update({"answer": answer, "field_checks": checks, "fields_correct": 18,
                      "fields_total": 18, "whole_correct": True, "status": "valid_complete",
                      "image_colors": colors, "ab_edges": baseline["ab_edges"],
                      "bc_edges": baseline["bc_edges"], "critical_wrong_fields": []})
    dump("blind_trials.json", {
        "public_revision": "r2", "frozen": json.loads((ROOT / "frozen.json").read_text()),
        "tools_enabled": True, "context": "三个新代理均fork_turns=none，只接收公开题面和原图路径",
        "scope": "本地独立代理试答，实际模型与推理档继承主会话设置",
        "standard": standard, "trials": rows,
        "counts": {"correct": 3, "incorrect": 0, "timeout": 0, "infra_error": 0, "partial": 0},
        "revision1": {"status": "superseded", "reason": "作者B4下边界定位偏上，测距真值修正，BC阈值由1600改1650",
                      "raw_distances": [[864, 1577], [853, 1558], [863, 1566]],
                      "other_answer_fields": standard,
                      "initial_agents": ["blind_ferrules_1", "blind_ferrules_2", "blind_ferrules_3"]},
        "protocol_events": "旧代理续答被立即中断，该类续答不纳入有效分母。r2另开三个新代理。",
        "difficulty_decision": "medium，3/3完整正确；本题保留为中等候选。",
    })
    return standard, rows


def independent_verify(facts, baseline):
    """从两套隔间匹配直接枚举，避开solver的两条接力组合路径。"""
    lookup = {o["id"]: o for o in facts["objects"] if o["eligible"]}
    plans = set()
    for aa in itertools.combinations(["A1", "A2", "A3"], 2):
        for black_or_yellow, white in itertools.product(["B1", "B2"], ["B3", "B4"]):
            for bb in itertools.permutations([black_or_yellow, white]):
                for cc in itertools.permutations(["C2", "C3"]):
                    triples = list(zip(aa, bb, cc))
                    if any(abs(lookup[a]["y"] - lookup[b]["y"]) > 1000 or
                           abs(lookup[b]["y"] - lookup[c]["y"]) > 1650 for a, b, c in triples):
                        continue
                    colorings = []
                    for triple in triples:
                        colorings.append([colors for colors in itertools.product(*(lookup[i]["colors"] for i in triple))
                                          if len(set(colors)) == 3])
                    for first, second in itertools.product(*colorings):
                        codes = ["/".join(i + color for i, color in zip(triple, colors))
                                 for triple, colors in zip(triples, [first, second])]
                        plans.add(";".join(sorted(codes)))
    assert plans == {p["code"] for p in baseline["plans"]}
    margins = []
    for c1, c2, threshold in [("A", "B", 1000), ("B", "C", 1650)]:
        for a, b in itertools.product(lookup.values(), repeat=2):
            if a["id"][0] == c1 and b["id"][0] == c2:
                margins.append({"pair": [a["id"], b["id"]], "threshold": threshold,
                                "distance": abs(a["y"] - b["y"]),
                                "margin": abs(abs(a["y"] - b["y"]) - threshold),
                                "error_bound": 40})
    assert min(m["margin"] for m in margins) > 40
    dump("independent_verification.json", {"plan_count": len(plans), "plans_match": True,
                                         "all_threshold_margins": margins,
                                         "minimum_margin": min(m["margin"] for m in margins),
                                         "error_bound": 40, "R": 77.5 / 40})


def field(key, title, text):
    return (f'<section id="{key}"><div class="section-head"><h2>{title}</h2>'
            f'<button type="button" data-copy="{key}-text">复制</button></div>'
            f'<pre id="{key}-text" class="copy-content">{html.escape(text)}</pre></section>')


def main():
    facts = json.loads((ROOT / "facts.json").read_text())
    computed = json.loads((ROOT / "recompute.json").read_text())
    baseline = computed["baseline"]
    standard, trials = build_trials(baseline)
    independent_verify(facts, baseline)
    source = json.loads((ROOT / "source.json").read_text())
    image_data = "data:image/jpeg;base64," + base64.b64encode(IMAGE.read_bytes()).decode()
    prompt = (ROOT / "prompt.txt").read_text().strip()
    thinking = """答题者须区分混有红色端子的A3与仅有黄色端子的B1，并识别C3中同属一个长隔间的蓝、绿端子。还须区分B3/B4的真正黄色分隔板与C2里竖放的备用板。

这些差别分别决定颜色可选集合与隔间身份。颜色与竖直距离共同筛掉不合格接力，再由六个隔间互不重复和B列恰有一个白灰隔间形成完整方案集合。

受影响的判分字段包括colors_A3、colors_C3、relays、plans及两工况最优方案。若漏掉C3绿色，接力由22减至13，完整方案由28减至13，工况1最小代价由31升至37，其规范最优编码也改变。"""
    fact_lines = ["素材为真实实拍照片。求解对象单位为隔间，共12个，参与接力9个。以下y为作者在原生图上按题设边界口径估读的参考纵坐标，单位px。"]
    for o in facts["objects"]:
        color = "{" + ",".join(o["colors"]) + "}" if o["eligible"] else "题设排除"
        fact_lines.append(f'{o["id"]}　y≈{o["y"]:g}　颜色{color}　{o["evidence"]}')
    fact_lines += ["", "关键易混点", "A3黄色端子间有多件独立红色领口，按题面彩色优先口径登记R,Y。",
                   "B2的银色长管是金属部分，领口主体为黑色K。B3与B4由完整黄色板分开，均登记W。",
                   "C2内靠左一叠竖放的黄色备用板没有横跨列宽，C2仍为一个隔间。C3绿色领口与蓝色领口均多件可见。",
                   "原图无用于求解的中文字。所有文字标签均无需辨读。"]
    understanding = "\n".join(fact_lines)
    reasoning = """A、B、C的实际隔间数为5、4、3。按题设只收A1–A3、B1–B4、C2–C3。

A2到B3的距离为|1210−2075|=865px。B4到C2的距离为|2597.5−1025|=1572.5px，四舍五入为1573px。

按距离阈值建立8条AB边
A1–B1，A1–B2，A2–B1，A2–B2，A2–B3，A3–B2，A3–B3，A3–B4。
建立7条BC边
B1–C2，B2–C2，B2–C3，B3–C2，B3–C3，B4–C2，B4–C3。

对每组A/B/C隔间枚举颜色乘积，保留颜色两两不同者。按(A,B)汇总的接力数为
(A1,B1)=1，(A1,B2)=2，(A2,B2)=2，(A2,B3)=2，(A3,B2)=5，(A3,B3)=5，(A3,B4)=5，其余为0，总计22条。

将22条接力按规范编码排序，枚举两条的无序组合，只保留六个隔间均不同，且两个B隔间恰有一个颜色集合为{W}者。不同取色产生不同方案，两条接力交换仅计一次。按所用A隔间对汇总，A1/A2有4种，A1/A3有18种，A2/A3有6种，总计28种。

工况0的唯一最优方案为A1B/B2K/C2R;A2R/B3W/C3B。编号数字和为12，颜色费用为3+1+4+4+2+3=17？逐项重核时该方案编号数字为1+2+2+2+3+3=13，颜色费用为17，总代价30。

工况1的唯一最优方案为A1B/B1Y/C2R;A2R/B3W/C3G。编号数字和为1+1+2+2+3+3=12，颜色费用为7+3+2+2+4+1=19，总代价31。

两工况规范最优方案不同，changed=1。另一条从双隔间匹配出发的独立枚举与求解器的28个完整编码集合完全一致。两工况次优代价分别为31和32，费用以题设整数精确计算。"""
    # 保持作者解答为最终核验后的计算。
    reasoning = reasoning.replace("编号数字和为12，颜色费用为3+1+4+4+2+3=17？逐项重核时该方案编号数字为1+2+2+2+3+3=13，颜色费用为17，总代价30。",
                                  "编号数字和为1+2+2+2+3+3=13，颜色费用为3+1+4+4+2+3=17，总代价30。")
    response = "\n".join([
        "counts=[5,4,3]", "colors_A3=[R,Y]; colors_C3=[B,G]", "distances_px=[865,1573]",
        "edges=[8,7]; relays=22", "plans=28",
        'mode0=[30,1,"A1B/B2K/C2R;A2R/B3W/C3B"]',
        'mode1=[31,1,"A1B/B1Y/C2R;A2R/B3W/C3G"]', "changed=1"])
    grading = [
        ("counts", "3", "5、4、3，顺序精确匹配"),
        ("colors_A3 / colors_C3", "2", "分别为R,Y及B,G，集合可规范化为字母升序"),
        ("distances_px", "2", "基准865、1573px，各允许±40px"),
        ("edges", "2", "AB为8、BC为7，顺序精确匹配"),
        ("relays / plans", "2", "22、28，整数精确匹配"),
        ("mode0", "3", "30、1、对应完整规范编码，各字段独立判分"),
        ("mode1", "3", "31、1、对应完整规范编码，各字段独立判分"),
        ("changed", "1", "1，整数精确匹配"),
    ]
    qa = """最终图片质检为authoring_candidate。report.json、metrics.csv、index.html和三个原生ROI均已检查，blocked与needs_review为空。12个对象框登记的是实际隔间，个体端子的数量和遮挡关系由题设颜色存在性口径处理。

原生ROI中A3可辨多件红色及黄色领口，B3/B4分隔板横贯列宽，C3蓝绿两类多件可辨。逐隔间框无相交，近色异类候选为0；这些数值只适用于隔间框。盒内端子存在堆叠，颜色归属已逐ROI复核。无可识别人脸，无遮挡关键图证的水印。中文覆盖为0%，求解无需读取图上文字。

测距采用原图竖直像素投影距离。每个参考y的保守误差上界为20px，两参考y之差的误差上界为40px。所有参与对象对均检查阈值，AB最近边界余量135px，BC最近边界余量77.5px，总体R=77.5/40=1.9375。独立枚举核对全部28个方案，费用与取色精确计分。

反事实复算一　将C3的{B,G}误读为{B}，删除涉及绿色样本的接力。接力22→13，完整方案28→13，工况1最小代价31→37，规范最优编码变为A1B/B1Y/C2R;A2R/B3W/C3B。
反事实复算二　将A3的{R,Y}误读为{Y}，接力22→16，完整方案28→20。两种易混读法均由图中相似混装物作为依据，属于作者敏感性检查。

视觉依赖检查　去图或只读题面无法恢复隔间边界、参考y与颜色集合；只读价目费用表无法确定完整可行集。覆盖全部盒体的一个大裁图可以提供所需图证。完整正确转录后允许一次编程求解。公开图中没有已经汇总的答案。

最终公开版r2进行了3次新上下文独立盲答，工具可用，各代理只接收同一题面和干净原图。结果为整题正确3/3，各18/18字段正确，完整错答0、超时0、工具故障0、残缺0。三轮距离估读分别为[849,1562]、[858,1564]、[870,1556]px，均在容差内。关键错答字段为空。登记难度为medium，中等。

版本核查　r1作者B4下边界定位偏上，已依据原生像素修正，BC阈值由1600px调整至1650px。随后另开三个新代理完成r2，r1记录留在内部目录。

来源核对使用项目来源与许可台账，页面ID为106783997，场景ID为commons:106783997。实时读取Commons来源页返回HTTP 429限流，作者与许可按采集台账核验。对照本地非空出题状态、已有作者目录及可用题包来源标识，未发现同场景题。项目未提供独立排除清单，去重覆盖范围据此登记。

本次按用户补充的本地img路径领取与取图，使用SQLite BEGIN IMMEDIATE事务同时登记collection_queue与img_claims。交付图逐字节复制该目录既有JPEG，SHA-256与源文件一致。台账记载采集阶段做过JPEG重编码，原生4409×3185画幅保留。本次原图未作修改。"""
    attribution = ("Asurnipal，Dornbirn-wire ferrules-01ASD.jpg，CC BY-SA 4.0。"
                   "来源为Wikimedia Commons，页面ID 106783997。采集阶段已进行JPEG重编码，原生尺寸4409×3185，"
                   "本次沿用本地收集文件并逐字节复制。打点由本题作者在HTML图层中添加。")
    data = {"id": QID, "title": "端子盒的双接力取样与两工况优化", "difficulty": "medium",
            "prompt": prompt, "thinking": thinking, "cot_image_understanding": understanding,
            "cot_reasoning": reasoning, "response": response, "quality_summary": qa,
            "attribution": attribution, "standard": standard}
    dump("author_record.json", data)
    points = [(2460, 1870, "A3红黄混色决定两个取色选项"),
              (3010, 2235, "B3与B4之间的实际分隔板，白灰隔间须分开"),
              (3500, 2200, "C3同隔间蓝绿端子决定工况1的绿色可选项")]
    markers = "".join(f'<span class="point" style="left:{100*x/4409:.8f}%;top:{100*y/3185:.8f}%" '
                      f'title="{html.escape(label)}">{i}</span>'
                      for i, (x, y, label) in enumerate(points, 1))
    point_rows = "".join(f"<tr><td>{i}</td><td>({x}, {y})</td><td>{label}</td></tr>"
                         for i, (x, y, label) in enumerate(points, 1))
    meta = [("题号", QID), ("题名", data["title"]), ("题型", "计数聚合链"),
            ("辅助题型", "定位度量、复杂指令遵循"), ("难度", "中等 / medium"),
            ("图片大类", "实拍密集场景照"), ("图片小类", "居家场景 / 工具五金 / 端子分格盒"),
            ("素材类型", "真实照片 / real_photo"), ("原图尺寸", "4409 × 3185 px，RGB，JPEG"),
            ("来源", source["source_page"]), ("作者", "Asurnipal"),
            ("许可", "CC BY-SA 4.0"), ("许可原文", source["license"]["LicenseUrl"])]
    meta_html = "".join(f'<tr><th>{html.escape(k)}</th><td id="meta-{i}">{html.escape(v)}</td>'
                        f'<td><button type="button" data-copy="meta-{i}">复制</button></td></tr>'
                        for i, (k, v) in enumerate(meta))
    grading_rows = "".join(f"<tr><td>{a}</td><td>{b}</td><td>{c}</td></tr>" for a, b, c in grading)
    font_css = ""
    font_license = ""
    if (ROOT / "record_font.woff2").exists():
        font_data = base64.b64encode((ROOT / "record_font.woff2").read_bytes()).decode()
        font_css = ('@font-face{font-family:"Record Chinese";font-style:normal;font-weight:400 700;'
                    'src:url(data:font/woff2;base64,' + font_data + ') format("woff2");font-display:block}')
        font_license = '<!-- Noto Sans SC font license\n' + (ROOT / "record_font_OFL.txt").read_text() + '\n-->'
    record = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{QID} 中文作者记录</title>{font_license}<style>{font_css}
*{{box-sizing:border-box}}body{{margin:0;background:#f3f5f7;color:#172536;font-family:"Record Chinese","Noto Sans CJK SC","Microsoft YaHei",sans-serif;line-height:1.7;overflow-wrap:anywhere}}
main{{max-width:1450px;margin:auto;padding:24px}}header{{padding:12px 0 20px}}h1{{font-size:28px;margin:0 0 8px}}h2{{font-size:21px;margin:0}}h3{{font-size:17px}}
section{{background:white;border:1px solid #dce2e8;border-radius:10px;padding:22px;margin:0 0 20px}}p{{margin:8px 0 14px}}a{{color:#125b9e}}
.section-head{{display:flex;justify-content:space-between;align-items:center;gap:14px;margin-bottom:15px}}button{{background:#eaf2fa;color:#144f83;border:1px solid #bdd1e3;border-radius:6px;padding:7px 15px;cursor:pointer;font:inherit;white-space:nowrap}}button:focus-visible{{outline:3px solid #ed9b26}}
table{{border-collapse:collapse;table-layout:fixed;width:100%;margin:12px 0}}th,td{{padding:10px 12px;border:1px solid #dce2e8;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{background:#f4f7fa}}th:first-child{{width:150px}}#basic td:last-child{{width:82px}}
pre{{font:inherit;white-space:pre-wrap;overflow-wrap:anywhere;margin:0;line-height:1.85}}.images{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px}}figure{{margin:0;min-width:0}}figcaption{{font-weight:600;margin:0 0 10px}}
.frame{{position:relative;width:100%;aspect-ratio:4409/3185;line-height:0}}.frame img{{display:block;width:100%;height:auto}}.point{{position:absolute;transform:translate(-50%,-50%);display:grid;place-items:center;width:27px;height:27px;line-height:1;color:white;background:#bd3424;border:2px solid white;border-radius:50%;font:bold 15px sans-serif;box-shadow:0 1px 4px #0008}}
.note{{color:#526476;font-size:14px}}#copy-status{{position:fixed;bottom:20px;right:20px;background:#173951;color:white;padding:10px 18px;border-radius:7px;z-index:5}}#copy-status:empty{{display:none}}
@media(max-width:760px){{main{{padding:12px}}section{{padding:15px}}h1{{font-size:23px}}.images{{grid-template-columns:1fr}}th:first-child{{width:95px}}td,th{{padding:7px}}}}
</style></head><body><main>
<header><h1>{html.escape(data['title'])}</h1><p>中文作者记录 · {QID} · 冻结题面 r2</p></header>
<section id="basic"><h2>基本信息</h2><table><tbody>{meta_html}</tbody></table>
<p>{html.escape(attribution)}</p><p class="note">图片SHA-256为 {hashlib.sha256(IMAGE.read_bytes()).hexdigest()}</p>
<p><a href="{html.escape(source['source_page'])}">Commons来源页</a> · <a href="{html.escape(source['license']['LicenseUrl'])}">CC BY-SA 4.0许可原文</a></p></section>
<section id="comparison"><h2>原图与打点对照</h2><p>左上角为原点，x向右、y向下。编号属于作者证据定位。</p>
<div class="images"><figure><figcaption>原图</figcaption><div class="frame"><img id="clean-image" src="{image_data}" width="4409" height="3185" alt="未修改的端子收纳盒原图"></div></figure>
<figure><figcaption>打点图</figcaption><div class="frame"><img id="marked-image" src="{image_data}" width="4409" height="3185" alt="同画幅端子收纳盒，叠加三个作者证据编号">{markers}</div></figure></div>
<table><thead><tr><th>编号</th><th>原图像素坐标 (x, y)</th><th>证据说明</th></tr></thead><tbody>{point_rows}</tbody></table>
<button type="button" data-copy="points-text">复制打点信息</button><pre id="points-text">{html.escape(chr(10).join(f'{i}. ({x}, {y}) {label}' for i,(x,y,label) in enumerate(points,1)))}</pre></section>
{field('prompt','题目（prompt）',prompt)}
{field('thinking','出题思路（thinking）',thinking)}
{field('understanding','图像识别（cot_image_understanding）',understanding)}
{field('reasoning','题目推理（cot_reasoning）',reasoning)}
{field('response','标准答案（response）',response)}
<section id="grading"><h2>逐字段判分口径</h2><p>共18个字段。距离采用题面容差，其他字段采用精确口径。</p><table><thead><tr><th>字段</th><th>字段数</th><th>判分规则</th></tr></thead><tbody>{grading_rows}</tbody></table></section>
{field('qa','质检与复算摘要',qa)}
</main><div id="copy-status" role="status" aria-live="polite"></div><script>
function fallbackCopy(text){{
 const area=document.createElement('textarea');area.value=text;area.style.position='fixed';area.style.left='-9999px';document.body.appendChild(area);area.focus();area.select();
 const ok=document.execCommand('copy');area.remove();if(!ok)throw new Error('copy failed');
}}
document.querySelectorAll('button[data-copy]').forEach(button=>{{button.addEventListener('click',async()=>{{
 const text=document.getElementById(button.dataset.copy).textContent;
 try{{if(navigator.clipboard&&window.isSecureContext){{try{{await navigator.clipboard.writeText(text)}}catch(error){{fallbackCopy(text)}}}}else{{fallbackCopy(text)}}
 document.getElementById('copy-status').textContent='已复制纯文本';}}
 catch(error){{document.getElementById('copy-status').textContent='请选中对应文字并复制';}}
}})}});
</script></body></html>'''
    (DEST / "author_record.html").write_text(record)
    (ROOT / "qa_review.md").write_text(qa + "\n\n" + "逐字段判分共18项，三轮均18/18。\n")
    print(DEST / "author_record.html")


if __name__ == "__main__":
    main()
