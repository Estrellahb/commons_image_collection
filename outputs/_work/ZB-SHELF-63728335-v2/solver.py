#!/usr/bin/env python3
"""Independent solver & counterfactual recomputation for ZB-SHELF-63728335-v2 (hardened v2).

Image: img/公共场景/超市货架/zb-shelf-63728335.jpg (4032x3024, CC BY-SA 4.0, unresized)
Upgrades over v1: removes all layout/trap spoon-feeding, adds dual price reading (Kr Pr/Stk + floor Pr/kg),
visible green keyhole icons on B1/B2 (catching the upside-down bottom-right icon on B2), and visible
upturned peel-tabs on A3 (Can #1 and Can #5).
"""
import itertools
import json
import random
from pathlib import Path

IMAGE_SIZE = (4032, 3024)

BASE_BAYS = [
    {"id": "A1", "group": "A", "brand": "Stabburet",  "N": 2, "E": 0, "p10": 150, "kg": 135, "K": 0, "tab": 0, "has_tag": 0, "cx": 525,  "cy": 1030, "bbox": [120, 860, 810, 340]},
    {"id": "A2", "group": "A", "brand": "KING OSCAR", "N": 4, "E": 2, "p10": 122, "kg": 122, "K": 0, "tab": 0, "has_tag": 1, "cx": 1255, "cy": 850,  "bbox": [830, 410, 850, 850]},
    {"id": "A3", "group": "A", "brand": "KING OSCAR", "N": 6, "E": 1, "p10": 139, "kg": 126, "K": 0, "tab": 2, "has_tag": 1, "cx": 1915, "cy": 790,  "bbox": [1610, 350, 610, 880]},
    {"id": "A4", "group": "A", "brand": "Stabburet",  "N": 4, "E": 3, "p10": 139, "kg": 126, "K": 0, "tab": 0, "has_tag": 1, "cx": 3426, "cy": 860,  "bbox": [2820, 440, 1212, 850]},
    {"id": "B1", "group": "B", "brand": "Stabburet",  "N": 4, "E": 2, "p10": 150, "kg": 135, "K": 2, "tab": 0, "has_tag": 0, "cx": 1025, "cy": 1930, "bbox": [590, 1620, 870, 620]},
    {"id": "B2", "group": "B", "brand": "Stabburet",  "N": 6, "E": 2, "p10": 169, "kg": 153, "K": 3, "tab": 0, "has_tag": 1, "cx": 1810, "cy": 1940, "bbox": [1380, 1520, 860, 860]},
    {"id": "B3", "group": "B", "brand": "Stabburet",  "N": 6, "E": 4, "p10": 197, "kg": 115, "K": 0, "tab": 0, "has_tag": 1, "cx": 2970, "cy": 2040, "bbox": [2220, 1460, 1500, 1080]},
]

D_NEAR = 720.0
D_MAX = 2050.0
WALK_NEAR = 15
WALK_MID = 45
W_PEN = 6
K_CREDIT = 18
TAB_PEN = 8
M_CUT = 8


def solve(bays_list):
    D = {b["id"]: dict(b) for b in bays_list}
    for b in D.values():
        b["G"] = b["N"] - b["E"]

    A = [D[b["id"]] for b in bays_list if b["group"] == "A"]
    B = [D[b["id"]] for b in bays_list if b["group"] == "B"]

    sum_N = sum(b["N"] for b in D.values())
    sum_E = sum(b["E"] for b in D.values())
    sum_K = D["B1"]["K"] + D["B2"]["K"]
    tab_A3 = D["A3"]["tab"]
    sum_P10 = sum(b["p10"] for b in D.values() if b["has_tag"] == 1)
    sum_KG = sum(b["kg"] for b in D.values() if b["has_tag"] == 1)

    edges = []
    all_dx = []
    for a in A:
        for b in B:
            dx = abs(a["cx"] - b["cx"])
            e_sum = a["E"] + b["E"]
            all_dx.append({"edge": f"{a['id']}-{b['id']}", "dx": dx, "e_sum": e_sum, "g_a": a["G"], "g_b": b["G"]})
            if dx <= D_MAX and e_sum >= 3 and a["G"] >= 1 and b["G"] >= 1:
                near = dx <= D_NEAR
                edges.append({
                    "a": a["id"],
                    "b": b["id"],
                    "dx": dx,
                    "near": near,
                    "walk": WALK_NEAR if near else WALK_MID,
                    "e_sum": e_sum,
                })

    plans = []
    for e1, e2 in itertools.combinations(edges, 2):
        if e1["a"] == e2["a"] or e1["b"] == e2["b"]:
            continue
        if int(e1["a"][1:]) > int(e2["a"][1:]):
            e1, e2 = e2, e1
        a1, b1, a2, b2 = D[e1["a"]], D[e1["b"]], D[e2["a"]], D[e2["b"]]
        k_cnt = (a1["brand"] == "KING OSCAR") + (a2["brand"] == "KING OSCAR")
        if k_cnt < 1:
            continue
        e_tot = a1["E"] + a2["E"] + b1["E"] + b2["E"]
        fam = "M" if e_tot >= M_CUT else "N"
        walk = e1["walk"] + e2["walk"]
        c0 = (a1["p10"] + a2["p10"] + b1["p10"] + b2["p10"]) + walk
        c1 = (
            (a1["kg"] + a2["kg"] + b1["kg"] + b2["kg"])
            + walk
            + W_PEN * (sum_E - e_tot)
            - K_CREDIT * (b1["K"] + b2["K"])
            + TAB_PEN * (a1["tab"] + a2["tab"])
        )
        code = f"{e1['a']}-{e1['b']};{e2['a']}-{e2['b']}"
        plans.append({"family": fam, "c0": c0, "c1": c1, "code": code, "e_tot": e_tot})

    def summarize(fam):
        sub = [p for p in plans if p["family"] == fam]
        if not sub:
            return {"count": 0, "min_c0": None, "ties_c0": 0, "best_c0": [], "min_c1": None, "ties_c1": 0, "best_c1": []}
        m0 = min(p["c0"] for p in sub)
        b0 = sorted(p["code"] for p in sub if p["c0"] == m0)
        m1 = min(p["c1"] for p in sub)
        b1 = sorted(p["code"] for p in sub if p["c1"] == m1)
        return {
            "count": len(sub),
            "min_c0": m0,
            "ties_c0": len(b0),
            "best_c0": b0,
            "min_c1": m1,
            "ties_c1": len(b1),
            "best_c1": b1,
        }

    M = summarize("M")
    N = summarize("N")

    def winner(m_val, n_val):
        if m_val is None and n_val is None:
            return "NONE"
        if n_val is None or (m_val is not None and m_val < n_val):
            return "M"
        if m_val is None or n_val < m_val:
            return "N"
        return "TIE"

    w0 = winner(M["min_c0"], N["min_c0"])
    w1 = winner(M["min_c1"], N["min_c1"])
    reversal = int(w0 in ("M", "N") and w1 in ("M", "N") and w0 != w1)
    w1_rep = (M["best_c1"][0] if w1 == "M" else N["best_c1"][0]) if w1 in ("M", "N") else "NONE"

    margin_near = min(abs(d["dx"] - D_NEAR) for d in all_dx)
    margin_max = min(abs(d["dx"] - D_MAX) for d in all_dx)
    closest_near = min(all_dx, key=lambda d: abs(d["dx"] - D_NEAR))
    closest_max = min(all_dx, key=lambda d: abs(d["dx"] - D_MAX))

    fields = {
        "q1_sum_N": sum_N,
        "q1_sum_E": sum_E,
        "q1_sum_K": sum_K,
        "q1_tab_A3": tab_A3,
        "q1_sum_P10": sum_P10,
        "q1_sum_KG": sum_KG,
        "q2_edges": len(edges),
        "q2_near_edges": sum(1 for e in edges if e["near"]),
        "q3_total_plans": len(plans),
        "q3_M_plans": M["count"],
        "q3_N_plans": N["count"],
        "q4_M_min_c0": M["min_c0"],
        "q4_M_ties_c0": M["ties_c0"],
        "q4_N_min_c0": N["min_c0"],
        "q4_N_ties_c0": N["ties_c0"],
        "q5_M_min_c1": M["min_c1"],
        "q5_M_ties_c1": M["ties_c1"],
        "q5_N_min_c1": N["min_c1"],
        "q5_N_ties_c1": N["ties_c1"],
        "q6_winner_w0": w0,
        "q6_winner_w1": w1,
        "q6_reversal": reversal,
        "q6_w1_canonical_plan": w1_rep,
    }
    canonical_answer = (
        f"{sum_N},{sum_E},{sum_K},{tab_A3},{sum_P10},{sum_KG}|"
        f"{len(edges)},{sum(1 for e in edges if e['near'])}|"
        f"{len(plans)},{M['count']},{N['count']}|"
        f"{M['min_c0']},{M['ties_c0']},{N['min_c0']},{N['ties_c0']}|"
        f"{M['min_c1']},{M['ties_c1']},{N['min_c1']},{N['ties_c1']}|"
        f"{w0},{w1},{reversal},{w1_rep}"
    )
    return {
        "fields": fields,
        "canonical_answer": canonical_answer,
        "edges": edges,
        "M": M,
        "N": N,
        "distance_margins": {
            "D_NEAR": D_NEAR,
            "margin_near_px": margin_near,
            "closest_near": closest_near,
            "D_MAX": D_MAX,
            "margin_max_px": margin_max,
            "closest_max": closest_max,
        },
    }


def mutate(mods):
    bs = [dict(b) for b in BASE_BAYS]
    by_id = {b["id"]: b for b in bs}
    for bid, k, v in mods:
        by_id[bid][k] = v
    return bs


def main():
    base = solve(BASE_BAYS)
    rng = random.Random(20261126)
    stable = 0
    trials = 10000
    for _ in range(trials):
        bs = [dict(b, cx=b["cx"] + rng.uniform(-30.0, 30.0)) for b in BASE_BAYS]
        if solve(bs)["fields"] == base["fields"]:
            stable += 1
    a4_shift = solve(mutate([("A4", "cx", 3550)]))

    cf_specs = [
        ("CF1_B3_cross_shelf_139", "串层把中层红杠 13.90 kr (126.36/kg) 误读为下方 B3 价格", "降低 M 组工况 0 购样代价 58，使 M 组两工况均胜，rev: 1 -> 0", mutate([("B3", "p10", 139), ("B3", "kg", 126)])),
        ("CF2_B3_arrow_tag_148", "忽略红向下箭头把下层 14.80 kr (87.06/kg) 误归给 B3", "降低 M 组两工况代价，使 M 组两工况均胜，rev: 1 -> 0", mutate([("B3", "p10", 148), ("B3", "kg", 87)])),
        ("CF3_B2_leverpostei_131", "将下层 13.10 kr (65.50/kg, LEVERPOSTEI) 误归给中层 B2", "同时改变 sum_P10、sum_KG 及两工况最小代价", mutate([("B2", "p10", 131), ("B2", "kg", 65)])),
        ("CF4_A3_miss_back_can", "漏看 A3 第 4 罐背面营养表朝前（E_A3: 1 -> 0）", "使 A3-B1 与 A3-B2 失效，N 组方案归零，rev: 1 -> 0", mutate([("A3", "E", 0)])),
        ("CF5_A4_all_inverted", "漏看 A4 右上正立罐而误判 4 罐全倒置（E_A4: 3 -> 4, G_A4 = 0）", "A4 失效导致 M 组失去最优方案，两工况均由 N 胜，rev: 1 -> 0", mutate([("A4", "E", 4)])),
        ("CF6_B2_miss_botR_keyhole", "漏看 B2 最下层右罐倒置露出的绿色钥匙孔图标（K_B2: 3 -> 2）", "改变 sum_K (5 -> 4) 及工况 1 中 N 组最小代价 (534 -> 552)", mutate([("B2", "K", 2)])),
        ("CF7_A3_miss_top_peel_tab", "仅看到 A3 第 5 罐而漏看第 1 罐右侧翘起米色耳片（tab_A3: 2 -> 1）", "改变 tab_A3 (2 -> 1) 及工况 1 中 N 组最小代价 (534 -> 526)", mutate([("A3", "tab", 1)])),
        ("CF8_B2_miss_bottom_row", "漏看 B2 最下层 2 罐倒置（E_B2: 2 -> 0）", "使 A2-B2 与 A3-B2 失效，两工况均由 M 胜，rev: 1 -> 0", mutate([("B2", "E", 0)])),
        ("CF9_B3_miss_back_left", "漏看 B3 后排左罐倒置（E_B3: 4 -> 3）", "改变 sum_E (14 -> 13) 及工况 1 中 N 组最小代价 (534 -> 528)", mutate([("B3", "E", 3)])),
    ]

    counterfactuals = []
    for cid, desc, mech, bs in cf_specs:
        res = solve(bs)
        changed = {k: {"baseline": base["fields"][k], "alternative": res["fields"][k]} for k in base["fields"] if base["fields"][k] != res["fields"][k]}
        counterfactuals.append({
            "id": cid, "description": desc, "mechanism": mech,
            "fields": res["fields"], "canonical_answer": res["canonical_answer"],
            "changed_fields": changed, "changed_field_count": len(changed),
            "flips_reversal": base["fields"]["q6_reversal"] != res["fields"]["q6_reversal"],
        })

    out = {
        "question_id": "ZB-SHELF-63728335-v2",
        "image_size": list(IMAGE_SIZE),
        "thresholds": {"D_NEAR": D_NEAR, "D_MAX": D_MAX, "endpoint_error_px": 30.0, "error_bound_px": 60.0},
        "bays": BASE_BAYS,
        "baseline": base,
        "a4_shift_check": {"description": "Shift A4 center +124 px to yellow tray logo center (x=3550)", "all_fields_identical": a4_shift["fields"] == base["fields"], "distance_margins": a4_shift["distance_margins"]},
        "perturbation_check": {"trials": trials, "endpoint_noise_px": 30.0, "pair_error_bound_px": 60.0, "all_fields_stable_count": stable, "stability_rate": stable / trials},
        "counterfactuals": counterfactuals,
    }
    (Path(__file__).parent / "recompute.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Baseline answer:", base["canonical_answer"])
    print("Margins:", base["distance_margins"])
    print("A4 shift +124px identical:", out["a4_shift_check"]["all_fields_identical"])
    print(f"Perturbation stability (+/-30px each endpoint, 2e=60px): {stable}/{trials}")
    for cf in counterfactuals:
        print(f"  {cf['id']:26s} | changed={cf['changed_field_count']:2d} | flip_rev={cf['flips_reversal']} | ans={cf['canonical_answer']}")


if __name__ == "__main__":
    main()
