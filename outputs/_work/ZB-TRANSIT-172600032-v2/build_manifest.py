"""Build the QA manifest from the reviewed screen-row transcription."""
import json
import os
from pathlib import Path

from solver import load_rows

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
source = json.loads((HERE / "source.json").read_text())
results = json.loads((HERE / "recompute.json").read_text())
trial = json.loads((HERE / "blind_trials.json").read_text())
baseline, alternative = results["baseline"], results["alternative"]

# Inner row extents at the first and last data lines, as seen in the native crops.
screens = {
    "A": ([697, 1232, 719, 1233], [675, 2242, 730, 2244], [650, 1070, 795, 1350]),
    "B": ([1477, 1240, 703, 1240], [1468, 2252, 716, 2248], [1439, 1070, 786, 1350]),
    "C": ([2242, 1248, 706, 1246], [2240, 2260, 730, 2258], [2215, 1070, 790, 1360]),
    "D": ([3008, 1251, 699, 1248], [3028, 2266, 728, 2262], [2983, 1070, 807, 1360]),
}

objects = []
for row in load_rows():
    first, last, _ = screens[row.screen]
    fraction = (row.row_number - 1) / 30
    x, left_y, width, right_y = [
        round(a + (b - a) * fraction) for a, b in zip(first, last)
    ]
    category = "带 Help" if row.help else "合格空 Help" if len(row.gate) > 1 else "无合格 Gate"
    objects.append({
        "id": row.flight,
        "bbox": [x, min(left_y, right_y) - 12, width, 24 + abs(left_y - right_y)],
        "category": category,
    })

rois = [{"id": screen, "bbox": coords[2], "human_readable": True}
        for screen, coords in screens.items()]
rois += [
    {"id": "B-help", "bbox": [1460, 1320, 730, 78], "human_readable": True},
    {"id": "B-gate", "bbox": [1460, 1745, 737, 65], "human_readable": True},
    {"id": "D-gate", "bbox": [3010, 1925, 755, 62], "human_readable": True},
    {"id": "C-heathrow", "bbox": [2235, 1450, 735, 148], "human_readable": True},
]
points = [
    {"xy": [1887, 1372], "label": "B 屏 T3 位于 UA9791 的 Zurich 行。正上方 DL9235 的 Help 格为空。"},
    {"xy": [2157, 1770], "label": "B 屏 DL9351 的 Gate 为 C11。它不进入候选对，但计入拥挤费。"},
    {"xy": [3704, 1957], "label": "D 屏 CI9225 也用 C11。与 B 屏的记录共同决定这行的拥挤费。"},
]

nodes = [
    *({"id": f"read_{screen}", "kind": "visual", "roi_id": screen} for screen in screens),
    *({"id": key, "kind": kind} for key, kind in [
        ("pair_edges", "state"), ("gate_counts", "aggregate"), ("help_filter", "state"),
        ("time_and_letter_costs", "parameter"), ("full_plans", "state"),
        ("apply_congestion", "optimize"), ("recount_after_removal", "state"),
        *((f"q{i}", "output") for i in range(1, 6)),
    ]),
]
edges = [(f"read_{screen}", node) for screen in screens
         for node in ["pair_edges", "gate_counts", "help_filter", "time_and_letter_costs"]]
edges += [
    ("pair_edges", "q1"), ("pair_edges", "full_plans"), ("help_filter", "full_plans"),
    ("full_plans", "q2"), ("full_plans", "q3"), ("time_and_letter_costs", "q3"),
    ("gate_counts", "apply_congestion"), ("full_plans", "apply_congestion"),
    ("time_and_letter_costs", "apply_congestion"), ("apply_congestion", "q4"),
    ("apply_congestion", "recount_after_removal"), ("gate_counts", "recount_after_removal"),
    ("full_plans", "recount_after_removal"), ("recount_after_removal", "q5"),
]
item = {
    "id": HERE.name,
    "image": os.path.relpath(ROOT / source["file"], HERE),
    "require_real": True,
    "min_native_short_px": 1080,
    "source": {
        "kind": "real_photo",
        "url": source["source_page"],
        "license_url": source["license"]["LicenseUrl"],
        "authorization": "verified",
        "scene_id": "commons:172600032:schiphol-departures-2025-08-13",
        "attribution": "Sebleouf, CC BY-SA 4.0",
        "native_resolution": [4032, 3024],
        "ingest_transform": source["modifications"],
        "license_evidence": "source_page.html",
        "dedup_evidence": "qa_notes.md",
    },
    "annotation_provenance": "人工逐行抄录，行框见本目录构建脚本",
    "objects": objects,
    "critical_rois": rois,
    "platform_points": points,
    "ocr": {"han_bboxes": [], "reviewed": True, "evidence": "qa_notes.md"},
    "human_checks": dict.fromkeys([
        "source_fidelity", "annotation_correct", "critical_evidence_visible",
        "no_answer_leakage", "counting_rules_clear",
    ], True),
    "human_checks_evidence": "qa_notes.md",
    "task": {
        "uses_distance": False,
        "measurements": [],
        "measurement_review": "无连续像素距离或阈值，时间取整分钟。见 qa_notes.md。",
        "bypass_review": "passed",
        "bypass_evidence": "qa_notes.md",
        "dependencies": [
            {"roi_id": screen, "parameter": "同一行的目的地、时间、Help、Gate、航班号",
             "output": "q1–q5"} for screen in screens
        ] + [
            {"roi_id": "B-help", "parameter": "T3 对应 UA9791", "output": "q2–q5"},
            {"roi_id": "B-gate", "parameter": "DL9351 使用 C11", "output": "q4–q5"},
            {"roi_id": "D-gate", "parameter": "CI9225 使用 C11", "output": "q4–q5"},
            {"roi_id": "C-heathrow", "parameter": "两个同目的地同时间但不同 Gate 的航班行",
             "output": "q1、q2、q5"},
        ],
        "counterfactuals": [
            {"field": "q2", "baseline": baseline["q2"], "alternative": alternative["q2"],
             "verified": True, "evidence": "recompute.json"},
            {"field": "q4_cost", "baseline": baseline["q4"]["cost"],
             "alternative": alternative["q4"]["cost"], "verified": True, "evidence": "recompute.json"},
            {"field": "q4_cost_without_C11_collision", "baseline": baseline["q4"]["cost"],
             "alternative": results["alternative_gate"]["q4"]["cost"],
             "verified": True, "evidence": "recompute.json"},
        ],
        "reasoning_graph": {"nodes": nodes, "edges": edges},
    },
    "evaluation": {
        "tools_enabled": True,
        "frozen_version": HERE.name,
        "counts": trial["counts"],
        "trajectory": "blind_trials.json",
        "gt_review": "recompute.json",
        "failure_attribution": "三轮均全部字段正确",
    },
}
(HERE / "manifest.json").write_text(json.dumps({"items": [item]}, ensure_ascii=False, indent=2) + "\n")
