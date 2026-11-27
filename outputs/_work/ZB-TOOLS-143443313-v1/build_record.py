"""生成 ZB-TOOLS-143443313-v1 离线中文作者记录与干净原图双文件交付包。"""
from __future__ import annotations

import base64
import hashlib
import html
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[2]
QID = "ZB-TOOLS-143443313-v1"
DEST = PROJECT / "outputs" / ("authoring_" + QID)
IMAGE_NAME = "zb-hardware-143443313.jpg"
SOURCE_IMAGE = PROJECT / "img" / "居家场景" / "工具五金" / IMAGE_NAME
WORK_IMAGE = ROOT / "public" / "image.jpg"
DEST_IMAGE = DEST / IMAGE_NAME
EXPECTED_SHA256 = "bbb114d54700f206dd885f821d49b4f4f3d9e76d491cae7cd87c26c116c2d4ed"


def field_section(key: str, title: str, text: str) -> str:
    return (
        f'<section id="{key}"><div class="section-head"><h2>{title}</h2>'
        f'<button type="button" data-copy="{key}-text">复制</button></div>'
        f'<pre id="{key}-text" class="copy-content">{html.escape(text)}</pre></section>'
    )


def main() -> None:
    src_img = SOURCE_IMAGE if SOURCE_IMAGE.is_file() else WORK_IMAGE
    img_bytes = src_img.read_bytes()
    img_sha = hashlib.sha256(img_bytes).hexdigest()
    assert img_sha == EXPECTED_SHA256, f"Unexpected image SHA-256: {img_sha}"
    if WORK_IMAGE.is_file():
        assert hashlib.sha256(WORK_IMAGE.read_bytes()).hexdigest() == img_sha

    DEST.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_img, DEST_IMAGE)
    DEST_IMAGE.chmod(0o644)
    assert hashlib.sha256(DEST_IMAGE.read_bytes()).hexdigest() == img_sha

    record_json = json.loads((ROOT / "author" / "author_record.json").read_text(encoding="utf-8"))
    source_json = json.loads((ROOT / "author" / "source.json").read_text(encoding="utf-8"))
    recompute = json.loads((ROOT / "recompute.json").read_text(encoding="utf-8"))

    entry = next(e for e in source_json["entries"] if e.get("file", "").endswith(IMAGE_NAME))
    source_page = entry["source_page"]
    license_url = entry["license"]["LicenseUrl"]
    license_name = entry["license"]["LicenseShortName"]
    artist = entry["license"]["Artist"]

    prompt = record_json["prompt"].strip()
    thinking = record_json["thinking"].strip()
    understanding = record_json["cot_image_understanding"].strip()
    reasoning = record_json["cot_reasoning"].strip()
    response = record_json["response"].strip()
    assert response == recompute["baseline"]["response"]

    qa_summary = "\n".join([
        "最终图片质检为 authoring_candidate，report.json、metrics.csv、index.html 与 9 张原生 ROI 均已检查，blocked 与 needs_review 为空。",
        "对象框共 32 个（30 个入槽批头及 L/R 两个实物端点区域），近色异类候选 27 对、投影重叠候选 3 对已逐对沿着杆身和槽位复核并保留。",
        "全部距离取原图 4032 × 3024 px 水平投影：LA 最近余量 127.5 px（R=4.25），AB 最近余量 85.0 px（R=4.25），BC 最近余量 60.5 px（R=3.025），CR 最近余量 132 px（R=4.40），全局最小 R=3.025 > 1。",
        "solver.py 与 author/verify.py 两条独立求解路径对 baseline 与 2 组反事实的全部 15 个答案字段完全一致：",
        "  • 正确读法：tickets=83，pairs=1692，M=(3,5)，N=(2,2)，联合最优=(3,6,3,010610,040509)。",
        "  • 反事实一（C06 误按白点星标纳入）：CR 5→6，BC 29→36，tickets 83→105，pairs 1692→2858，联合最优变为 (1,2,1,030806,040509)。",
        "  • 反事实二（B01 黄色环误读为杆身红色反光）：AB 25→23，tickets 83→81，pairs 1692→1588。",
        "  • 门限消融：去掉 L–A 门限后 pairs 1692→3282；去掉 C–R 门限后 pairs 1692→3056。",
        "去重核查：来源页 143443313（队列 id=107）与同场景白底加尺派生版 145653915（队列 id=316）共用 authored_ref 并标记 316 为 discarded 防重；外部难题300清单未随项目提供。",
        "difficulty_status = not_evaluated（登记候选题型 counting / complex_instruction / localization_measurement / robust_ocr，模型直调评测尚未执行）。",
    ])

    attribution = (
        f"{artist}，Miniature bit set with wrench for carrying on belt.jpg，{license_name}。"
        f"来源为 Wikimedia Commons，页面 ID 143443313。采集阶段应用了 EXIF 朝向并做 JPEG 重编码，"
        f"保留 4032 × 3024 原生画幅，本次逐字节复制本地采集文件。打点由本题作者在 HTML 图层中添加。"
    )

    points = [(int(p["xy"][0]), int(p["xy"][1]), p["label"]) for p in record_json["platform_points"]]
    markers = "".join(
        f'<span class="point" style="left:{100 * x / 4032:.8f}%;top:{100 * y / 3024:.8f}%" '
        f'title="{html.escape(label)}">{i}</span>'
        for i, (x, y, label) in enumerate(points, 1)
    )
    point_rows = "".join(
        f"<tr><td>{i}</td><td>({x}, {y})</td><td>{html.escape(label)}</td></tr>"
        for i, (x, y, label) in enumerate(points, 1)
    )
    points_text = "\n".join(f"{i}. ({x}, {y}) {label}" for i, (x, y, label) in enumerate(points, 1))

    meta = [
        ("题号", QID),
        ("题名", record_json["title"]),
        ("题型", "计数聚合链"),
        ("辅助题型", "复杂指令遵循、定位度量、抗干扰文本读取"),
        ("难度", "困难 / hard"),
        ("图片大类", "实拍密集场景照"),
        ("图片小类", "居家场景 / 工具五金"),
        ("素材类型", "真实照片 / real_photo"),
        ("原图尺寸", "4032 × 3024 px，RGB，JPEG"),
        ("来源", source_page),
        ("作者", artist),
        ("许可", license_name),
        ("许可原文", license_url),
    ]
    meta_html = "".join(
        f'<tr><th>{html.escape(k)}</th><td id="meta-{i}">{html.escape(v)}</td>'
        f'<td><button type="button" data-copy="meta-{i}">复制</button></td></tr>'
        for i, (k, v) in enumerate(meta)
    )

    grading_rows = "".join(
        f'<tr><td>{html.escape(str(f["field"]))}</td><td>{html.escape(str(f["expected"]))}</td>'
        f'<td>{html.escape(str(f["unit"]))}</td><td>{html.escape(str(f["comparison"]))}</td></tr>'
        for f in record_json["answer_fields"]
    )

    image_data = "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode("ascii")

    record_html = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{QID} 中文作者记录</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f5f7;color:#172536;font-family:"Noto Sans CJK SC","PingFang SC","Hiragino Sans GB","Microsoft YaHei",system-ui,sans-serif;line-height:1.7;overflow-wrap:anywhere}}
main{{max-width:1450px;margin:auto;padding:24px}}header{{padding:12px 0 20px}}h1{{font-size:28px;margin:0 0 8px}}h2{{font-size:21px;margin:0}}
section{{background:white;border:1px solid #dce2e8;border-radius:10px;padding:22px;margin:0 0 20px}}p{{margin:8px 0 14px}}a{{color:#125b9e}}
.section-head{{display:flex;justify-content:space-between;align-items:center;gap:14px;margin-bottom:15px}}button{{background:#eaf2fa;color:#144f83;border:1px solid #bdd1e3;border-radius:6px;padding:7px 15px;cursor:pointer;font:inherit;white-space:nowrap}}button:focus-visible{{outline:3px solid #ed9b26}}
table{{border-collapse:collapse;table-layout:fixed;width:100%;margin:12px 0}}th,td{{padding:10px 12px;border:1px solid #dce2e8;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{background:#f4f7fa}}th:first-child{{width:150px}}#basic td:last-child{{width:82px}}
pre{{font:inherit;white-space:pre-wrap;overflow-wrap:anywhere;margin:0;line-height:1.85}}.images{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px}}figure{{margin:0;min-width:0}}figcaption{{font-weight:600;margin:0 0 10px}}
.frame{{position:relative;width:100%;aspect-ratio:4032/3024;line-height:0}}.frame img{{display:block;width:100%;height:auto}}.point{{position:absolute;transform:translate(-50%,-50%);display:grid;place-items:center;width:27px;height:27px;line-height:1;color:white;background:#bd3424;border:2px solid white;border-radius:50%;font:bold 15px sans-serif;box-shadow:0 1px 4px #0008}}
.note{{color:#526476;font-size:14px}}#copy-status{{position:fixed;bottom:20px;right:20px;background:#173951;color:white;padding:10px 18px;border-radius:7px;z-index:5}}#copy-status:empty{{display:none}}
@media(max-width:760px){{main{{padding:12px}}section{{padding:15px}}h1{{font-size:23px}}.images{{grid-template-columns:1fr}}th:first-child{{width:95px}}td,th{{padding:7px}}}}
</style></head><body><main>
<header><h1>{html.escape(record_json["title"])}</h1><p>中文作者记录 · {QID} · 冻结题面 v1</p></header>
<section id="basic"><h2>基本信息</h2><table><tbody>{meta_html}</tbody></table>
<p>{html.escape(attribution)}</p><p class="note">图片 SHA-256 为 {img_sha}</p>
<p><a href="{html.escape(source_page)}">Commons 来源页</a> · <a href="{html.escape(license_url)}">{html.escape(license_name)} 许可原文</a></p></section>
<section id="comparison"><h2>原图与打点对照</h2><p>左上角为原点，x 向右、y 向下。编号属于作者关键图证定位。</p>
<div class="images"><figure><figcaption>原图</figcaption><div class="frame"><img id="clean-image" src="{image_data}" width="4032" height="3024" alt="未修改的红色工具批头盒原图"></div></figure>
<figure><figcaption>打点图</figcaption><div class="frame"><img id="marked-image" src="{image_data}" width="4032" height="3024" alt="同画幅红色工具批头盒，叠加三个作者证据编号">{markers}</div></figure></div>
<table><thead><tr><th>编号</th><th>原图像素坐标 (x, y)</th><th>证据说明</th></tr></thead><tbody>{point_rows}</tbody></table>
<button type="button" data-copy="points-text">复制打点信息</button><pre id="points-text">{html.escape(points_text)}</pre></section>
{field_section("prompt", "题目（prompt）", prompt)}
{field_section("thinking", "出题思路（thinking）", thinking)}
{field_section("understanding", "图像识别（cot_image_understanding）", understanding)}
{field_section("reasoning", "题目推理（cot_reasoning）", reasoning)}
{field_section("response", "标准答案（response）", response)}
<section id="grading"><h2>逐字段判分口径</h2><p>共 15 个字段。边数、计数、偏差采用精确数值比较（等值小数可接受），6 位取件单编码保留前导零精确字符串比较。</p><table><thead><tr><th>字段</th><th>标准值</th><th>单位</th><th>判分规则</th></tr></thead><tbody>{grading_rows}</tbody></table></section>
{field_section("qa", "质检与复算摘要", qa_summary)}
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

    out_html = DEST / "author_record.html"
    out_html.write_text(record_html, encoding="utf-8")
    print(f"Wrote {out_html} ({out_html.stat().st_size} bytes) and {DEST_IMAGE} ({DEST_IMAGE.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
