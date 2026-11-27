import json
from pathlib import Path

root = Path(__file__).resolve().parent


def read(name):
    return json.loads((root / f"{name}.json").read_text())


facts, source, recompute, trials = map(read, ("facts", "source", "recompute", "blind_trials"))
base = recompute["baseline"]
wrong_name = recompute["alternatives"]["same_color_as_same_name"]["result"]
wrong_lid = recompute["alternatives"]["occluded_lid_as_visible"]["result"]
points = [
    {"xy": [1247, 718], "label": "上排第 5 罐正面的 CURCUMA，与下排左端同名。"},
    {"xy": [325, 1519], "label": "下排第 1 罐正面的 CURCUMA，沿罐口上溯到本罐锥尖。"},
    {"xy": [1135, 1690], "label": "白牌遮在右后方灰褐块罐的盖顶前，牌缘不可用作盖缘坐标。"},
]
rois = {
    "upper_tips": [142, 25, 1225, 230],
    "upper_names": [145, 560, 1235, 291],
    "lower_tips": [145, 851, 1225, 170],
    "lower_names": [144, 1290, 1225, 365],
    "rear_lids": [65, 1605, 1310, 523],
    "front_lids": [190, 1922, 1330, 398],
    "blocked_lid": [1030, 1575, 345, 353],
}
categories = {obj["id"]: obj["name"] for group in ("upper", "lower") for obj in facts[group]}
categories.update({obj["id"]: obj["type"] for obj in facts["references"]})
categories.update({obj["id"]: obj["category"] for obj in facts["excluded"]})
objects = [
    {"id": obj["id"], "bbox": obj["bbox"], "category": categories[obj["id"]]}
    for group in ("upper", "lower", "references", "excluded")
    for obj in facts[group]
]
outputs = ["same_name", "counts", "optima", "representative_edges"]
nodes = [{"id": key, "kind": "visual", "roi_id": key} for key in rois]
nodes += [
    {"id": key, "kind": kind}
    for key, kind in (
        ("name_match", "parameter"), ("edge_geometry", "measure"),
        ("lid_eligibility", "parameter"), ("five_permutations", "state"),
        ("window", "state"), ("scores", "optimize"),
    )
]
nodes += [{"id": key, "kind": "output"} for key in outputs]
edges = [
    ("upper_names", "name_match"), ("lower_names", "name_match"),
    ("upper_tips", "edge_geometry"), ("lower_tips", "edge_geometry"),
    ("rear_lids", "lid_eligibility"), ("front_lids", "lid_eligibility"), ("blocked_lid", "lid_eligibility"),
    ("name_match", "same_name"), ("name_match", "five_permutations"),
    ("edge_geometry", "five_permutations"), ("edge_geometry", "window"),
    ("five_permutations", "window"), ("lid_eligibility", "window"),
    ("window", "counts"), ("window", "scores"), ("lid_eligibility", "scores"),
    ("scores", "optima"), ("scores", "representative_edges"), ("window", "representative_edges"),
]
item = {
    "id": trials["version"],
    "image": facts["image"],
    "require_real": True,
    "source": {
        "kind": source["kind"], "scene_id": source["scene_id"], "authorization": "verified",
        "url": source["source_page"], "license_url": source["license"]["LicenseUrl"],
        "author": source["license"]["Artist"], "license": source["license"]["LicenseShortName"],
        "native_size": facts["size"], "evidence": "source.json, source_page.html",
    },
    "annotation_provenance": "author_manual_native_pixels",
    "objects": objects,
    "critical_rois": [{"id": key, "bbox": bbox, "human_readable": True} for key, bbox in rois.items()],
    "platform_points": points,
    "ocr": {"han_bboxes": [], "reviewed": True, "notes": "原生图全幅巡查未见汉字。题证品名为拉丁字母，部分末字随弧面变暗。下方阿拉伯文与法文吊牌只用于实体遮挡定位。"},
    "human_checks": {
        "source_fidelity": True, "annotation_correct": True, "critical_evidence_visible": True,
        "no_answer_leakage": True, "counting_rules_clear": True, "privacy_faces": True,
        "watermark_no_obstruction": True,
    },
    "task": {
        "uses_distance": True,
        "dependencies": [
            {"roi_id": "upper_names", "parameter": "上排品名", "output": "同名边、方案总数"},
            {"roi_id": "lower_names", "parameter": "下排品名", "output": "同名边、方案总数"},
            {"roi_id": "upper_tips", "parameter": "上排锥尖 x", "output": "档位、代表方案码"},
            {"roi_id": "lower_tips", "parameter": "下排锥尖 x", "output": "档位、代表方案码"},
            {"roi_id": "rear_lids", "parameter": "后方参照盖顶及料型", "output": "各参照方案数、最低分"},
            {"roi_id": "front_lids", "parameter": "前方参照盖顶及料型", "output": "各参照方案数"},
            {"roi_id": "blocked_lid", "parameter": "排除盖顶受阻的灰褐罐", "output": "参照编号和总数"},
        ],
        "measurements": [
            {"id": "bands", "margin": base["min_band_margin"][0], "error_bound": 24,
             "unit": "px", "error_method": "两个锥尖横坐标各取 ±12 px 上界", "evidence": "facts.json, recompute.json, qa_review.md"},
            {"id": "window", "margin": base["min_window_margin"][0], "error_bound": 24,
             "unit": "px", "error_method": "两锥尖中点经误差取平均仍至多 ±12 px，盖顶至多 ±12 px", "evidence": "facts.json, recompute.json, qa_review.md"},
        ],
        "counterfactuals": [
            {"field": "完整方案数", "baseline": base["total"], "alternative": wrong_name["total"],
             "verified": True, "evidence": "recompute.json#same_color_as_same_name"},
            {"field": "A 代表方案", "baseline": base["optimum"]["A"]["representative"],
             "alternative": wrong_name["optimum"]["A"]["representative"],
             "verified": True, "evidence": "recompute.json#same_color_as_same_name"},
            {"field": "按参照编号的完整方案数", "baseline": base["by_reference"],
             "alternative": wrong_lid["by_reference"], "verified": True,
             "evidence": "recompute.json#occluded_lid_as_visible"},
        ],
        "bypass_review": "passed",
        "reasoning_graph": {"nodes": nodes, "edges": edges},
    },
    "evaluation": {
        "tools_enabled": True, "frozen_version": trials["version"], "counts": trials["counts"],
        "trajectory": "blind_trials.json", "gt_review": "recompute.json, grade_blind.py",
        "failure_attribution": "三次独立试答均全部正确。",
    },
}
(root / "manifest.json").write_text(json.dumps({"items": [item]}, ensure_ascii=False, indent=2) + "\n")
