#!/usr/bin/env python3
"""Independent solver, counterfactual recomputation, and blind-trial verification for ZB-TOOLS-151686260-v1.

Image: img/居家场景/工具五金/zb-hardware-151686260.jpg (4716x3144, CC BY 4.0)
Ground truth verified at 4x native macro on all 12 upper-row hooks (H1-H12).
"""
import itertools
import json
import random
from pathlib import Path

IMAGE_SIZE = (4716, 3144)

# 4x-macro-verified object fact table for upper-row hooks H1-H12 (left to right).
# x, y: pixel center where the red peg rod exits the frontmost wrench's hanging hole.
# x_alt: alternative horizontal center (triangular hole center for H1-H4, circular hole center for H5-H12).
BASE_HOOKS = [
    {"id": "H1",  "group": "A", "front_brand": "UNIOR",     "size": 28, "blue": 0, "red": 2, "usa": 0, "x": 500,  "y": 830,  "x_alt": 466,  "bbox": [180, 560, 490, 1850]},
    {"id": "H2",  "group": "A", "front_brand": "UNIOR",     "size": 24, "blue": 0, "red": 1, "usa": 0, "x": 928,  "y": 865,  "x_alt": 892,  "bbox": [670, 620, 430, 1680]},
    {"id": "H3",  "group": "A", "front_brand": "UNIOR",     "size": 15, "blue": 0, "red": 3, "usa": 0, "x": 1338, "y": 895,  "x_alt": 1306, "bbox": [1090, 650, 430, 1630]},
    {"id": "H4",  "group": "A", "front_brand": "UNIOR",     "size": 22, "blue": 0, "red": 2, "usa": 0, "x": 1666, "y": 955,  "x_alt": 1646, "bbox": [1460, 730, 390, 1550]},
    {"id": "H5",  "group": "B", "front_brand": "Park Tool", "size": 20, "blue": 1, "red": 2, "usa": 0, "x": 2000, "y": 995,  "x_alt": 2000, "bbox": [1810, 810, 380, 1470]},
    {"id": "H6",  "group": "B", "front_brand": "Park Tool", "size": 19, "blue": 3, "red": 2, "usa": 0, "x": 2340, "y": 1015, "x_alt": 2340, "bbox": [2120, 850, 380, 1420]},
    {"id": "H7",  "group": "B", "front_brand": "Park Tool", "size": 18, "blue": 3, "red": 2, "usa": 1, "x": 2628, "y": 1035, "x_alt": 2628, "bbox": [2430, 890, 360, 1370]},
    {"id": "H8",  "group": "B", "front_brand": "Park Tool", "size": 17, "blue": 4, "red": 2, "usa": 0, "x": 2955, "y": 1065, "x_alt": 2955, "bbox": [2730, 920, 360, 1340]},
    {"id": "H9",  "group": "B", "front_brand": "Park Tool", "size": 16, "blue": 2, "red": 2, "usa": 1, "x": 3255, "y": 1105, "x_alt": 3255, "bbox": [3060, 960, 340, 1280]},
    {"id": "H10", "group": "B", "front_brand": "Park Tool", "size": 15, "blue": 1, "red": 1, "usa": 0, "x": 3445, "y": 1125, "x_alt": 3445, "bbox": [3320, 980, 310, 1240]},
    {"id": "H11", "group": "B", "front_brand": "Park Tool", "size": 14, "blue": 3, "red": 2, "usa": 1, "x": 3745, "y": 1150, "x_alt": 3745, "bbox": [3560, 1000, 300, 1240]},
    {"id": "H12", "group": "B", "front_brand": "Park Tool", "size": 13, "blue": 3, "red": 2, "usa": 0, "x": 3945, "y": 1175, "x_alt": 3945, "bbox": [3800, 1020, 290, 1220]},
]

D_NEAR = 1180.0
D_MAX = 2200.0


def solve(hooks_list, x_key="x"):
    H = {h["id"]: dict(h) for h in hooks_list}
    for h in H.values():
        h["total"] = h["blue"] + h["red"]

    A = [H[h["id"]] for h in hooks_list if h["group"] == "A"]
    B = [H[h["id"]] for h in hooks_list if h["group"] == "B"]

    sum_blue = sum(h["blue"] for h in H.values())
    sum_red = sum(h["red"] for h in H.values())
    usa_sizes = ",".join(str(h["size"]) for h in B if h["usa"] == 1)

    edges = []
    all_dx = []
    for a in A:
        for b in B:
            dx = abs(a[x_key] - b[x_key])
            ds = abs(a["size"] - b["size"])
            t_sum = a["total"] + b["total"]
            all_dx.append({"edge": f"{a['id']}-{b['id']}", "dx": dx, "ds": ds, "t_sum": t_sum})
            if dx <= D_MAX and ds >= 4 and t_sum >= 5:
                near = dx <= D_NEAR
                edges.append({
                    "a": a["id"],
                    "b": b["id"],
                    "dx": dx,
                    "ds": ds,
                    "t_sum": t_sum,
                    "near": near,
                    "c0": (4 if near else 9) + ds + (5 - b["blue"]),
                    "pen": (4 * (b["total"] - 4) if b["total"] >= 5 else 0) + (2 if a["red"] >= 2 else 0),
                })

    plans = []
    for e1, e2 in itertools.combinations(edges, 2):
        if e1["a"] == e2["a"] or e1["b"] == e2["b"]:
            continue
        if int(e1["a"][1:]) > int(e2["a"][1:]):
            e1, e2 = e2, e1
        b1, b2 = H[e1["b"]], H[e2["b"]]
        if b1["usa"] + b2["usa"] != 1:
            continue
        b_sum = b1["blue"] + b2["blue"]
        fam = "M" if b_sum >= 6 else "N"
        c0 = e1["c0"] + e2["c0"]
        c1 = c0 + e1["pen"] + e2["pen"]
        code = f"{e1['a']}-{e1['b']};{e2['a']}-{e2['b']}"
        plans.append({"family": fam, "c0": c0, "c1": c1, "code": code, "b_sum": b_sum})

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
        "q1_sum_blue": sum_blue,
        "q1_sum_red": sum_red,
        "q1_usa_sizes": usa_sizes,
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
        f"{sum_blue},{sum_red},{usa_sizes}|"
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
    hs = [dict(h) for h in BASE_HOOKS]
    by_id = {h["id"]: h for h in hs}
    for hid, key, val in mods:
        by_id[hid][key] = val
    return hs


def main():
    base = solve(BASE_HOOKS, x_key="x")
    alt_anchor = solve(BASE_HOOKS, x_key="x_alt")

    rng = random.Random(20261126)
    perturb_matches = 0
    trials = 10000
    for _ in range(trials):
        hs = [dict(h, x=h["x"] + rng.uniform(-12.0, 12.0)) for h in BASE_HOOKS]
        if solve(hs)["fields"] == base["fields"]:
            perturb_matches += 1

    cf_specs = [
        (
            "CF1_H3_size_monotonic_23",
            "把左红柄区 H3 实际刻字 15 按递减规律误读为 23（其余全对）",
            "改变规格差 |size_a - size_b| >= 4 判定，使近距边 H3-H5 失效，反转位由 1 变为 0",
            mutate([("H3", "size", 23)]),
        ),
        (
            "CF2_H6_blue_2",
            "把 H6(19 mm) 叠挂的 3 把蓝柄误看成 2 把（B_6: 3 -> 2；与盲测第 2 轮视觉错读同源）",
            "改变 M/N 备件分组边界（H6+H7 由 6 降至 5），H3-H6;H4-H7 转入 N 组，两工况均由 N 胜，反转位由 1 变为 0",
            mutate([("H6", "blue", 2)]),
        ),
        (
            "CF3_H1_H4_red_single_1",
            "漏看 H1(28 mm) 与 H4(22 mm) 紧贴叠挂的第 2 把红柄（R_1, R_4: 2 -> 1；100% 复现盲测第 3 轮完整错答）",
            "改变红柄总数 sum_R（23->21）、使 H1-H5 失效（E: 12->11, P: 28->24, P_N: 12->8），并漏计 H4 的 A 组重载加罚（C1_M: 32->30, C1_N: 31->29）",
            mutate([("H1", "red", 1), ("H4", "red", 1)]),
        ),
        (
            "CF4_H1_H4_red_1_and_H6_blue_2",
            "同时漏看 H1/H4 第 2 把红柄且把 H6 蓝柄误读为 2 把（100% 复现盲测第 2 轮完整错答）",
            "同时改变盘点库存、兼容边、分组归属与两工况赢家，反转位由 1 变为 0",
            mutate([("H1", "red", 1), ("H4", "red", 1), ("H6", "blue", 2)]),
        ),
        (
            "CF5_behind_red_single_1",
            "把蓝柄后方叠挂的双层红柄一律误读为仅 1 把（H5-H12 均设 R=1）",
            "改变 B 组总把数 T_b，使多条兼容边与重载加罚改变，反转位由 1 变为 0",
            mutate([(f"H{i}", "red", 1) for i in range(5, 13)]),
        ),
        (
            "CF6_H5_USA_even_guess",
            "按“偶数规格均带 USA”误把 H5(20 mm, 实为 Park Tool 无 USA) 判为 USA=1",
            "改变全局约束 U_b1 + U_b2 = 1，剔除工况 1 最优轻蓝柄方案 H3-H5;H4-H7，反转位由 1 变为 0",
            mutate([("H5", "usa", 1)]),
        ),
        (
            "CF7_H7_USA_missed_dirt",
            "因 H7(18 mm) 蓝柄油污漏看品牌末尾 USA 字样（U_7: 1 -> 0）",
            "改变全局约束 U_b1 + U_b2 = 1，使含 H7 的低成本方案全部失效，反转位由 1 变为 0",
            mutate([("H7", "usa", 0)]),
        ),
        (
            "CF8_H3_red_single_1",
            "漏看 H3(15 mm) 叠挂的后方 2 把红柄，误读为仅 1 把（R_3: 3 -> 1）",
            "改变总库存 T_3（3->1），使近距边 H3-H5 不满足 T_a + T_b >= 5，反转位由 1 变为 0",
            mutate([("H3", "red", 1)]),
        ),
    ]

    counterfactuals = []
    for cid, desc, mechanism, hs in cf_specs:
        res = solve(hs)
        changed = {
            k: {"baseline": base["fields"][k], "alternative": res["fields"][k]}
            for k in base["fields"]
            if base["fields"][k] != res["fields"][k]
        }
        counterfactuals.append({
            "id": cid,
            "description": desc,
            "mechanism": mechanism,
            "fields": res["fields"],
            "canonical_answer": res["canonical_answer"],
            "changed_fields": changed,
            "changed_field_count": len(changed),
            "flips_reversal": base["fields"]["q6_reversal"] != res["fields"]["q6_reversal"],
        })

    out = {
        "question_id": "ZB-TOOLS-151686260-v1",
        "image_size": list(IMAGE_SIZE),
        "thresholds": {"D_NEAR": D_NEAR, "D_MAX": D_MAX, "error_bound_px": 24.0, "endpoint_error_px": 12.0},
        "hooks": BASE_HOOKS,
        "baseline": base,
        "alt_anchor_check": {
            "description": "Use triangular hole center (H1-H4) instead of red peg rod exit center",
            "all_fields_identical": alt_anchor["fields"] == base["fields"],
            "distance_margins": alt_anchor["distance_margins"],
        },
        "perturbation_check": {
            "trials": trials,
            "endpoint_noise_px": 12.0,
            "pair_error_bound_px": 24.0,
            "all_fields_stable_count": perturb_matches,
            "stability_rate": perturb_matches / trials,
        },
        "counterfactuals": counterfactuals,
    }

    out_path = Path(__file__).parent / "recompute.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Baseline answer:", base["canonical_answer"])
    print("Margins:", base["distance_margins"])
    print("Alt-anchor identical:", out["alt_anchor_check"]["all_fields_identical"])
    print(f"Perturbation stability (+/-12px each endpoint, 2e=24px): {perturb_matches}/{trials}")
    for cf in counterfactuals:
        print(f"  {cf['id']:30s} | changed={cf['changed_field_count']:2d} | flip_rev={cf['flips_reversal']} | ans={cf['canonical_answer']}")


if __name__ == "__main__":
    main()
