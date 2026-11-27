"""用复算答案核对三份盲答。保留原始末答与用于逐字段比较的规范值。"""
import json
import re
from pathlib import Path

work = Path(__file__).resolve().parent
base = json.loads((work / "recompute.json").read_text())["baseline"]
a, b = (base["optimum"][key] for key in ("A", "B"))
expected = {
    "same_name": base["same_name"],
    "by_reference": base["by_reference"],
    "total": base["total"],
    "A_score": a["score"], "A_count": a["count"], "A_code": a["representative"],
    "B_score": b["score"], "B_count": b["count"], "B_code": b["representative"],
    "A_edge": a["window_edge"], "B_edge": b["window_edge"],
}

attempts = [
    {
        "agent": "blind_0235_v2_a",
        "final": "1. 4-2、5-1\n2. 5、7、6、5、0，共 23\n3. 20，2，13425/2\n4. 14，2，14523/2\n5. A：2-3，B：2-4\n\n同名品为 GINGEMBRE 和 CURCUMA。上排锥尖横坐标约为 300、541、765、1003、1233，下排约为 282、570、799、1025、1239。\n\n五只参照的盖缘最高点横坐标约为 505、743、953、1087、1318，内容依次为半透明白色大块、灰褐色不规则大块、灰褐色不规则大块、粉紫色花苞、黄绿色细碎颗粒。最右后排灰褐块罐的盖顶被白色吊牌挡住。左端深色长块及前排其他混色碎料均不符合表列类别。",
        "initial_reference_x": [501, 734, 954, 1082, 1315],
        "additional_check": "报告跨目测范围的 720 组点位复算末答一致。",
    },
    {
        "agent": "blind_0235_v2_b",
        "final": "1. 4-2、5-1\n2. 5、7、6、5、0，合计 23\n3. 20，2，13425/2\n4. 14，2，14523/2\n5. A 2-3，B 2-4\n\n上排锥尖横坐标约为 299、541、765、1002、1232，下排约为 279、570、796、1025、1238。参照盖顶横坐标约为 507、742、947、1081、1306，依次对应半透明白块、两罐灰褐块、粉紫花苞和黄绿碎粒。右侧另一罐灰褐块的盖顶被白牌挡住。白块左侧的深色粗块遮住了其后盖缘的最高处。",
    },
    {
        "agent": "blind_0235_v2_c",
        "final": "1. 4-2，5-1\n2. 5，7，6，5，0；总计 23\n3. 20，2，13425/2\n4. 14，2，14523/2\n5. A 2-3，B 2-4\n\n上排锥尖的横坐标约为 303、540、768、1004、1231，下排约为 281、569、799、1026、1239。同名罐分别是 GINGEMBRE 和 CURCUMA。\n\n参照盖顶从左至右约在 505、738、950、1085、1312 像素，依次为半透明白色大块、灰褐色不规则大块、灰褐色不规则大块、粉紫花苞和黄绿色细碎颗粒。白牌挡住了第三罐灰褐色大块后方的盖顶。",
    },
]

counts = dict(correct=0, incorrect=0, timeout=0, infra_error=0, partial=0)
for attempt in attempts:
    row1, row2, row3, row4, row5 = attempt["final"].splitlines()[:5]
    names = [[int(i), int(j)] for i, j in re.findall(r"(\d)-(\d)", row1)]
    ref_counts = list(map(int, re.findall(r"\d+", row2)[1:]))
    costs = [re.fullmatch(r"[34]\. (\d+)，(\d+)，(\d+/\d+)", row).groups() for row in (row3, row4)]
    window = [[int(i), int(j)] for i, j in re.findall(r"(\d)-(\d)", row5)]
    normalized = {
        "same_name": names, "by_reference": ref_counts[:-1], "total": ref_counts[-1],
        "A_score": int(costs[0][0]), "A_count": int(costs[0][1]), "A_code": costs[0][2],
        "B_score": int(costs[1][0]), "B_count": int(costs[1][1]), "B_code": costs[1][2],
        "A_edge": window[0], "B_edge": window[1],
    }
    judges = {key: normalized[key] == value for key, value in expected.items()}
    attempt.update(normalized=normalized, field_matches=judges)
    counts["correct" if all(judges.values()) else "incorrect"] += 1
result = {
    "version":"ZB-0235-v2", "tools_enabled":True, "counts":counts,
    "inputs":["prompt.txt","冻结摘要所列原图"], "setup":"三个空历史子代理，每个单独试答一次。仅提供公开题面及同一个原图副本，可自由裁图、放大与编程。",
    "expected":expected, "attempts":attempts,
    "finding":"三份独立末答都覆盖全部 11 个逻辑字段，均正确。无关键错答字段。定位估计小差异没有改变判档、可行集或代表解，难度登记为中等。",
}
(work / "blind_trials.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
