#!/usr/bin/env python3
"""Independent solver & counterfactual recomputation for ZB-SPEC-120266311-v1.

Image: img/小众专业实物/珠宝·矿物·标本/zb-specimens-120266311.jpg (3870x3081, CC BY 2.0, unresized)
Natural History Museum London Coleoptera Drawer 27 (flat orthographic museum scan).
"""
import itertools
import json
import math
import random
from pathlib import Path

IMAGE_SIZE = (3870, 3081)

BASE_BLOCKS = [
    {"id": "A1", "group": "A", "taxon": "TENEBRIO / molitor, L.",          "C": 12, "S": 12, "B": 0, "L": 0, "WX": 0, "X": 2, "cx": 2385, "cy": 1138, "bbox": [2095,  935, 580, 405]},
    {"id": "A2", "group": "A", "taxon": "TENEBRIO / obscurus, F.",         "C":  3, "S":  3, "B": 3, "L": 0, "WX": 0, "X": 0, "cx": 2385, "cy": 1478, "bbox": [2170, 1375, 430, 205]},
    {"id": "A3", "group": "A", "taxon": "HELOPS / caeruleus L.",           "C": 14, "S": 14, "B": 0, "L": 0, "WX": 0, "X": 2, "cx": 2385, "cy": 2122, "bbox": [2095, 1645, 580, 955]},
    {"id": "A4", "group": "A", "taxon": "LAGRIA / atripes Muls. & Guil.",  "C": 11, "S": 11, "B": 0, "L": 0, "WX": 0, "X": 2, "cx": 2845, "cy":  920, "bbox": [2685,  700, 320, 440]},
    {"id": "A5", "group": "A", "taxon": "PSEUDOCISTELA / ceramboides, L.", "C":  9, "S":  9, "B": 1, "L": 0, "WX": 0, "X": 0, "cx": 2840, "cy": 2585, "bbox": [2685, 2305, 310, 560]},
    {"id": "B1", "group": "B", "taxon": "PRIONYCHUS / ater, F.",           "C": 12, "S": 12, "B": 2, "L": 8, "WX": 1, "X": 0, "cx": 3175, "cy": 1020, "bbox": [3020,  650, 310, 740]},
    {"id": "B2", "group": "B", "taxon": "PRIONYCHUS / melanarius Germ.",   "C":  9, "S":  9, "B": 4, "L": 1, "WX": 1, "X": 0, "cx": 3170, "cy": 1725, "bbox": [3015, 1455, 310, 540]},
    {"id": "B3", "group": "B", "taxon": "TETRATOMA / desmaresti, Lt.",     "C":  5, "S": 10, "B": 3, "L": 0, "WX": 0, "X": 0, "cx": 3488, "cy":  775, "bbox": [3350,  685, 275, 180]},
    {"id": "B4", "group": "B", "taxon": "MELANDRYA / caraboides, L.",      "C": 10, "S": 10, "B": 2, "L": 0, "WX": 0, "X": 0, "cx": 3508, "cy": 1835, "bbox": [3345, 1455, 325, 760]},
    {"id": "B5", "group": "B", "taxon": "PHLOIOTRYA / vaudoueri Muls.",    "C": 12, "S": 12, "B": 2, "L": 0, "WX": 0, "X": 2, "cx": 3508, "cy": 2585, "bbox": [3345, 2305, 325, 560]},
]

D_NEAR = 735.0
D_MAX = 1465.0
WALK_NEAR = 10
WALK_MID = 30
BPEN = 1
WX_CREDIT = 4
L_CREDIT = 2
M_CUT = 40


def solve(blocks_list):
    D = {b["id"]: dict(b) for b in blocks_list}
    A = [D[b["id"]] for b in blocks_list if b["group"] == "A"]
    B = [D[b["id"]] for b in blocks_list if b["group"] == "B"]

    sum_C = sum(b["C"] for b in D.values())
    sum_S = sum(b["S"] for b in D.values())
    sum_B = sum(b["B"] for b in D.values())
    sum_L = sum(b["L"] for b in D.values())
    sum_WX = sum(b["WX"] for b in D.values())
    sum_X = sum(b["X"] for b in D.values())

    edges = []
    all_dist = []
    for a in A:
        for b in B:
            dist = math.hypot(a["cx"] - b["cx"], a["cy"] - b["cy"])
            b_sum = a["B"] + b["B"]
            all_dist.append({"edge": f"{a['id']}-{b['id']}", "dist": round(dist, 2), "b_sum": b_sum})
            if dist <= D_MAX and b_sum >= 3:
                near = dist <= D_NEAR
                edges.append({
                    "a": a["id"],
                    "b": b["id"],
                    "dist": round(dist, 2),
                    "near": near,
                    "walk": WALK_NEAR if near else WALK_MID,
                    "b_sum": b_sum,
                })

    plans = []
    for e1, e2 in itertools.combinations(edges, 2):
        if e1["a"] == e2["a"] or e1["b"] == e2["b"]:
            continue
        if int(e1["a"][1:]) > int(e2["a"][1:]):
            e1, e2 = e2, e1
        ids = [e1["a"], e1["b"], e2["a"], e2["b"]]
        x_tot = sum(D[k]["X"] for k in ids)
        if x_tot < 2:
            continue
        c_tot = sum(D[k]["C"] for k in ids)
        s_tot = sum(D[k]["S"] for k in ids)
        b_tot = sum(D[k]["B"] for k in ids)
        l_tot = sum(D[k]["L"] for k in ids)
        wx_tot = sum(D[k]["WX"] for k in ids)
        walk = e1["walk"] + e2["walk"]
        c0 = c_tot + walk
        c1 = s_tot + walk + BPEN * (sum_B - b_tot) - WX_CREDIT * wx_tot - L_CREDIT * l_tot
        fam = "M" if s_tot >= M_CUT else "N"
        code = f"{e1['a']}-{e1['b']};{e2['a']}-{e2['b']}"
        plans.append({
            "family": fam, "code": code, "c0": c0, "c1": c1,
            "c_tot": c_tot, "s_tot": s_tot, "b_tot": b_tot, "l_tot": l_tot, "wx_tot": wx_tot, "x_tot": x_tot, "walk": walk
        })

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
            "min_c0": m0, "ties_c0": len(b0), "best_c0": b0,
            "min_c1": m1, "ties_c1": len(b1), "best_c1": b1,
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

    closest_near = min(all_dist, key=lambda d: abs(d["dist"] - D_NEAR))
    closest_max = min(all_dist, key=lambda d: abs(d["dist"] - D_MAX))
    margin_near = round(abs(closest_near["dist"] - D_NEAR), 2)
    margin_max = round(abs(closest_max["dist"] - D_MAX), 2)

    fields = {
        "q1_sum_C": sum_C,
        "q1_sum_S": sum_S,
        "q1_sum_B": sum_B,
        "q1_sum_L": sum_L,
        "q1_sum_WX": sum_WX,
        "q1_sum_X": sum_X,
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
        f"{sum_C},{sum_S},{sum_B},{sum_L},{sum_WX},{sum_X}|"
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
    bs = [dict(b) for b in BASE_BLOCKS]
    by_id = {b["id"]: b for b in bs}
    for bid, k, v in mods:
        by_id[bid][k] = v
    return bs


def main():
    base = solve(BASE_BLOCKS)
    rng = random.Random(20261126)
    stable = 0
    trials = 10000
    # Endpoint radial error up to 15 px -> pair error bound 2e = 30 px
    for _ in range(trials):
        bs = []
        for b in BASE_BLOCKS:
            ang = rng.uniform(0, 2 * math.pi)
            rad = rng.uniform(0, 15.0)
            bs.append(dict(b, cx=b["cx"] + rad * math.cos(ang), cy=b["cy"] + rad * math.sin(ang)))
        if solve(bs)["fields"] == base["fields"]:
            stable += 1

    # Alternative anchor check: including each block's printed species label strip (+20 px to +30 px in y)
    label_shifted = [dict(b, cy=b["cy"] + 25) for b in BASE_BLOCKS]
    label_shift_res = solve(label_shifted)

    cf_specs = [
        ("CF1_A5_miss_pin",        "漏看 A5 (ceramboides) 最右下角唯一 1 张下端插针卡（B_A5: 1 -> 0）", "A5-B5 与 A5-B4 失效，M 组失去唯一双近距方案，工况 0/1 均由 N 胜，rev: 1 -> 0", mutate([("A5", "B", 0)])),
        ("CF2_B5_miss_1pin",       "漏看 B5 (vaudoueri) 第 3 行外侧 1 张下端插针卡（B_B5: 2 -> 1）", "A5-B5 失效，M 组失去双近距最优方案，两工况均由 N 胜，rev: 1 -> 0", mutate([("B5", "B", 1)])),
        ("CF3_B3_cards_eq_bugs",   "将 B3 (desmaresti) 5 张纸卡误计为 5 只虫体（忽略 3 虫卡与 4 虫卡，S_B3: 10 -> 5）", "A4-B3;A5-B5 虫体总数由 42 跌至 37 落入 N 组，两工况均由 N 胜，rev: 1 -> 0", mutate([("B3", "S", 5)])),
        ("CF4_B3_miss_1pin",       "漏看 B3 (desmaresti) 1 张下端插针卡（B_B3: 3 -> 2）", "A4-B3 与 A1-B3 失效，M 组失去双近距方案，两工况均由 N 胜，rev: 1 -> 0", mutate([("B3", "B", 2)])),
        ("CF5_B1_row4_all3_pins",  "误判 B1 (ater) 第 4 行全 3 张均为下端插针（B_B1: 2 -> 3）", "近距边 A4-B1 (344.8 px) 等 3 条边突增，M 组获得 A4-B1;A5-B5 两工况均胜，rev: 1 -> 0", mutate([("B1", "B", 3)])),
        ("CF6_A2_miss_all_pins",   "按常规忽略 A2 (obscurus) 全部 3 张下端插针（B_A2: 3 -> 0）", "A2-B1 与 A2-B4 失效，N 组失去含 B1 代码的工况 1 最优方案，两工况均由 M 胜，rev: 1 -> 0", mutate([("A2", "B", 0)])),
        ("CF7_B2_miss_WX_and_pin", "漏看 B2 (melanarius) 第 2 行中卡隐藏 WX 代码及第 2 行右卡下端插针（WX:1->0, L:1->0, B:4->3）", "改变 sum_B、sum_L、sum_WX 与两工况 1 最优代价", mutate([("B2", "WX", 0), ("B2", "L", 0), ("B2", "B", 3)])),
        ("CF8_B1_WK_as_WX",        "将 B1 (ater) 首卡右上角 WK 误读为 WX（WX_B1: 1 -> 2）", "改变 sum_WX (2 -> 3) 及工况 1 N 组最小代价 (65 -> 61)", mutate([("B1", "WX", 2)])),
        ("CF9_B4_miss_pins",       "漏看 B4 (caraboides) 第 4 行 2 张下端插针（B_B4: 2 -> 0）", "使 A5-B4 失效，改变 sum_B、E、P、P_M、P_N 及工况 1 代价", mutate([("B4", "B", 0)])),
        ("CF10_A3_guess_16",       "按 4x4 满排补猜 A3 (caeruleus) 为 16 卡 16 虫（忽略底排中空，C/S: 14 -> 16）", "改变 sum_C、sum_S 及 M/N 分组边界（A2-B1;A3-B2 由 N 组移入 M 组）", mutate([("A3", "C", 16), ("A3", "S", 16)])),
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
        "question_id": "ZB-SPEC-120266311-v1",
        "image_size": list(IMAGE_SIZE),
        "thresholds": {"D_NEAR": D_NEAR, "D_MAX": D_MAX, "endpoint_error_px": 15.0, "error_bound_px": 30.0},
        "blocks": BASE_BLOCKS,
        "baseline": base,
        "label_shift_check": {"description": "Uniform +25 px y-shift including species label strips", "all_fields_identical": label_shift_res["fields"] == base["fields"]},
        "perturbation_check": {"trials": trials, "endpoint_radial_noise_px": 15.0, "pair_error_bound_px": 30.0, "all_fields_stable_count": stable, "stability_rate": stable / trials},
        "counterfactuals": counterfactuals,
    }
    (Path(__file__).parent / "recompute.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Baseline answer:", base["canonical_answer"])
    print("Margins:", base["distance_margins"])
    print("Label shift identical:", out["label_shift_check"]["all_fields_identical"])
    print(f"Perturbation stability (radial <=15px, 2e=30px): {stable}/{trials}")
    flips = sum(1 for c in counterfactuals if c["flips_reversal"])
    print(f"Counterfactuals flipping reversal: {flips}/{len(counterfactuals)}")
    for cf in counterfactuals:
        print(f"  {cf['id']:24s} | changed={cf['changed_field_count']:2d} | flip_rev={cf['flips_reversal']} | ans={cf['canonical_answer']}")


if __name__ == "__main__":
    main()
