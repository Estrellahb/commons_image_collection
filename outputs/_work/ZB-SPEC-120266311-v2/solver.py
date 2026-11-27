#!/usr/bin/env python3
"""Independent solver & counterfactual recomputation for ZB-SPEC-120266311-v2 (hardened 12-block version).

Image: img/小众专业实物/珠宝·矿物·标本/zb-specimens-120266311.jpg (3870x3081, CC BY 2.0, unresized)
Upgrades over v1: expands to 12 blocks (132 cards, 137 beetles) adding pallidus (13 cards, 4 bottom-pinned),
hirta (15 cards, 1 lone bottom-pinned on R3C5), murina (15 cards, lone male symbol hidden on R1C3), and
sulphureus (5+5+4=14 cards, 4 bottom-pinned); removes all code/multi-beetle/layout hints from prompt.
"""
import itertools
import json
import math
import random
from pathlib import Path

IMAGE_SIZE = (3870, 3081)

BASE_BLOCKS = [
    {"id": "A1", "group": "A", "taxon": "TENEBRIO / obscurus, F.",         "C":  3, "S":  3, "B": 3, "L": 0, "WX": 0, "X": 0, "cx": 2387, "cy": 1477, "bbox": [2167, 1368, 440, 218]},
    {"id": "A2", "group": "A", "taxon": "HELOPS / caeruleus L.",           "C": 14, "S": 14, "B": 0, "L": 0, "WX": 0, "X": 2, "cx": 2384, "cy": 2136, "bbox": [2092, 1646, 583, 980]},
    {"id": "A3", "group": "A", "taxon": "CYLINDRINOTUS / pallidus, Curt.", "C": 13, "S": 13, "B": 4, "L": 0, "WX": 0, "X": 0, "cx": 2376, "cy": 2771, "bbox": [2092, 2640, 568, 262]},
    {"id": "A4", "group": "A", "taxon": "LAGRIA / atripes Muls. & Guil.",  "C": 11, "S": 11, "B": 0, "L": 0, "WX": 0, "X": 2, "cx": 2850, "cy":  921, "bbox": [2687,  694, 327, 454]},
    {"id": "A5", "group": "A", "taxon": "LAGRIA / hirta, L.",              "C": 15, "S": 15, "B": 1, "L": 0, "WX": 0, "X": 0, "cx": 2842, "cy": 1403, "bbox": [2680, 1208, 325, 390]},
    {"id": "A6", "group": "A", "taxon": "PSEUDOCISTELA / ceramboides, L.", "C":  9, "S":  9, "B": 1, "L": 0, "WX": 0, "X": 0, "cx": 2830, "cy": 2585, "bbox": [2679, 2302, 303, 566]},
    {"id": "B1", "group": "B", "taxon": "ISOMIRA / murina, L.",            "C": 15, "S": 15, "B": 0, "L": 0, "WX": 0, "X": 1, "cx": 3186, "cy":  371, "bbox": [3033,  190, 305, 362]},
    {"id": "B2", "group": "B", "taxon": "PRIONYCHUS / ater, F.",           "C": 12, "S": 12, "B": 2, "L": 8, "WX": 1, "X": 0, "cx": 3180, "cy": 1023, "bbox": [3020,  644, 320, 758]},
    {"id": "B3", "group": "B", "taxon": "PRIONYCHUS / melanarius Germ.",   "C":  9, "S":  9, "B": 4, "L": 1, "WX": 1, "X": 0, "cx": 3172, "cy": 1720, "bbox": [3012, 1448, 320, 544]},
    {"id": "B4", "group": "B", "taxon": "CTENIOPUS / sulphureus, L.",      "C": 14, "S": 14, "B": 4, "L": 0, "WX": 0, "X": 0, "cx": 3161, "cy": 2610, "bbox": [2996, 2386, 330, 449]},
    {"id": "B5", "group": "B", "taxon": "TETRATOMA / desmaresti, Lt.",     "C":  5, "S": 10, "B": 3, "L": 0, "WX": 0, "X": 0, "cx": 3484, "cy":  766, "bbox": [3355,  672, 258, 189]},
    {"id": "B6", "group": "B", "taxon": "PHLOIOTRYA / vaudoueri Muls.",    "C": 12, "S": 12, "B": 2, "L": 0, "WX": 0, "X": 2, "cx": 3508, "cy": 2582, "bbox": [3343, 2305, 329, 555]},
]

D_NEAR = 733.0
D_MAX = 1490.0
WALK_NEAR = 10
WALK_MID = 30
BPEN = 2
WX_CREDIT = 6
L_CREDIT = 2
M_CUT = 44


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
                    "a": a["id"], "b": b["id"], "dist": round(dist, 2),
                    "near": near, "walk": WALK_NEAR if near else WALK_MID, "b_sum": b_sum,
                })

    plans = []
    for e1, e2 in itertools.combinations(edges, 2):
        if e1["a"] == e2["a"] or e1["b"] == e2["b"]:
            continue
        if int(e1["a"][1:]) > int(e2["a"][1:]):
            e1, e2 = e2, e1
        ids = [e1["a"], e1["b"], e2["a"], e2["b"]]
        x_tot = sum(D[k]["X"] for k in ids)
        if x_tot < 1:
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
        "q1_sum_C": sum_C, "q1_sum_S": sum_S, "q1_sum_B": sum_B,
        "q1_sum_L": sum_L, "q1_sum_WX": sum_WX, "q1_sum_X": sum_X,
        "q2_edges": len(edges), "q2_near_edges": sum(1 for e in edges if e["near"]),
        "q3_total_plans": len(plans), "q3_M_plans": M["count"], "q3_N_plans": N["count"],
        "q4_M_min_c0": M["min_c0"], "q4_M_ties_c0": M["ties_c0"],
        "q4_N_min_c0": N["min_c0"], "q4_N_ties_c0": N["ties_c0"],
        "q5_M_min_c1": M["min_c1"], "q5_M_ties_c1": M["ties_c1"],
        "q5_N_min_c1": N["min_c1"], "q5_N_ties_c1": N["ties_c1"],
        "q6_winner_w0": w0, "q6_winner_w1": w1, "q6_reversal": reversal, "q6_w1_canonical_plan": w1_rep,
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
        "fields": fields, "canonical_answer": canonical_answer,
        "edges": edges, "M": M, "N": N,
        "distance_margins": {
            "D_NEAR": D_NEAR, "margin_near_px": margin_near, "closest_near": closest_near,
            "D_MAX": D_MAX, "margin_max_px": margin_max, "closest_max": closest_max,
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
    for _ in range(trials):
        bs = []
        for b in BASE_BLOCKS:
            ang = rng.uniform(0, 2 * math.pi)
            rad = rng.uniform(0, 15.0)
            bs.append(dict(b, cx=b["cx"] + rad * math.cos(ang), cy=b["cy"] + rad * math.sin(ang)))
        if solve(bs)["fields"] == base["fields"]:
            stable += 1
    label_shift_res = solve([dict(b, cy=b["cy"] + 25) for b in BASE_BLOCKS])

    cf_specs = [
        ("CF1_B1_miss_murina_male",  "漏看 B1 (murina) 第 1 行第 3 卡左上角隐藏 ♂ 符号（X_B1: 1 -> 0）", "删除 8 个依赖 B1 性别符号的合法方案（P: 92 -> 84, sum_X: 7 -> 6）", mutate([("B1", "X", 0)])),
        ("CF2_A5_miss_hirta_pin",    "漏看 A5 (hirta) 最右下角唯一 1 张下端插针卡（B_A5: 1 -> 0）", "近距边 A5-B2 与中距边 A5-B6 失效，M 组失去工况 1 最优方案，两工况均由 N 胜，rev: 1 -> 0", mutate([("A5", "B", 0)])),
        ("CF3_A6_miss_ceramb_pin",   "漏看 A6 (ceramboides) 最右下角唯一 1 张下端插针卡（B_A6: 1 -> 0）", "近距边 A6-B6 失效，N 组失去双近距最优方案，两工况均由 M 胜，rev: 1 -> 0", mutate([("A6", "B", 0)])),
        ("CF4_B5_cards_eq_bugs",     "将 B5 (desmaresti) 5 张纸卡误计为 5 只虫体（S_B5: 10 -> 5）", "含 B5 的大样本最优方案跌入 N 组，两工况均由 N 胜，rev: 1 -> 0", mutate([("B5", "S", 5)])),
        ("CF5_B5_miss_1pin",         "漏看 B5 (desmaresti) 1 张下端插针卡（B_B5: 3 -> 2）", "近距边 A4-B5 失效，N 组失去工况 0 最优方案，两工况均由 M 胜，rev: 1 -> 0", mutate([("B5", "B", 2)])),
        ("CF6_B4_guess_15cards",     "按 3x5 满排误数 B4 (sulphureus) 为 15 卡（忽略末行仅 4 卡，C/S: 14 -> 15）", "改变 sum_C、sum_S 及多组方案分组与两工况代价", mutate([("B4", "C", 15), ("B4", "S", 15)])),
        ("CF7_B2_row4_all3_pins",    "误判 B2 (ater) 末行全 3 张均为下端插针（B_B2: 2 -> 3）", "A4-B2 近距边突增（E: 20 -> 22, P: 92 -> 114），大幅改变两工况代价与代表方案", mutate([("B2", "B", 3)])),
        ("CF8_B3_miss_WX_and_pin",   "漏看 B3 (melanarius) 隐藏 WX 代码及第 2 行右卡下端插针（WX:1->0, L:1->0, B:4->3）", "改变 sum_B、sum_L、sum_WX 及两工况 1 最优代价", mutate([("B3", "WX", 0), ("B3", "L", 0), ("B3", "B", 3)])),
        ("CF9_A1_miss_obscurus_pin", "忽略 A1 (obscurus) 全部 3 张下端插针（B_A1: 3 -> 0）", "A1-B1、A1-B2、A1-B6 失效，改变边数、方案数及工况 1 代价", mutate([("A1", "B", 0)])),
        ("CF10_A3_miss_pallid_pins", "漏看 A3 (pallidus) 末行 2 张下端插针（B_A3: 4 -> 2）", "改变 sum_B 及工况 1 两族最小代价", mutate([("A3", "B", 2)])),
        ("CF11_B6_miss_1pin",        "漏看 B6 (vaudoueri) 末行外侧 1 张下端插针（B_B6: 2 -> 1）", "近距边 A6-B6 失效，N 组失去工况 0 最优方案，两工况均由 M 胜，rev: 1 -> 0", mutate([("B6", "B", 1)])),
        ("CF12_B2_WK_as_WX",         "将 B2 (ater) 首卡 WK 误读为 WX（WX_B2: 1 -> 2）", "改变 sum_WX (2 -> 3) 及工况 1 M/N 组最小代价与并列数", mutate([("B2", "WX", 2)])),
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
        "question_id": "ZB-SPEC-120266311-v2",
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
        print(f"  {cf['id']:25s} | changed={cf['changed_field_count']:2d} | flip_rev={cf['flips_reversal']} | ans={cf['canonical_answer']}")


if __name__ == "__main__":
    main()
