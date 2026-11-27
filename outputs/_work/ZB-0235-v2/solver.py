"""从作者登记的图面事实枚举完整方案，输出有图面依据的替读结果。"""
import json
from collections import Counter
from itertools import combinations, permutations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
THRESHOLDS = (108, 350, 560)
WINDOW = 117
EDGE_POINTS = {"A": (0, 4, 4, 1), "B": (0, 4, 1, 4)}
LID_POINTS = {"white": (1, 3), "stones": (4, 2), "buds": (3, 5), "grains": (1, 2)}


def solve(upper, lower, references, matching_names):
    edges = {}
    for i, top in enumerate(upper, 1):
        for j, bottom in enumerate(lower, 1):
            x1, x2 = top["xy"][0], bottom["xy"][0]
            distance = abs(x1 - x2)
            band = sum(distance > limit for limit in THRESHOLDS)
            edges[i, j] = {
                "d": distance,
                "band": band,
                "midpoint": (x1 + x2) / 2,
                "same": (i, j) in matching_names,
            }

    feasible = []
    window_margins = []
    core_codes = []
    for code in permutations(range(1, len(lower) + 1)):
        pairs = list(enumerate(code, 1))
        joined = [edges[pair] for pair in pairs]
        if any(edge["band"] == 3 and not edge["same"] for edge in joined):
            continue
        if sum(edge["same"] for edge in joined) != 1:
            continue
        if sum(edge["band"] == 0 for edge in joined) > 2:
            continue
        core_codes.append("".join(map(str, code)))
        crossings = sum(j > l for j, l in combinations(code, 2))

        for number, lid in enumerate(references, 1):
            offsets = [
                (abs(edge["midpoint"] - lid["xy"][0]), pair, edge["band"])
                for pair, edge in zip(pairs, joined)
                if not edge["same"]
            ]
            window_margins.extend(
                (abs(offset - WINDOW), offset, core_codes[-1], number, pair)
                for offset, pair, _ in offsets
            )
            in_window = [(pair, band) for offset, pair, band in offsets if offset <= WINDOW]
            if len(in_window) != 1 or in_window[0][1] not in (1, 2):
                continue
            row = {"code": core_codes[-1], "reference": number, "crossings": crossings,
                   "window_edge": in_window[0][0], "bands": [edge["band"] for edge in joined]}
            for tariff, lid_points in zip(EDGE_POINTS, LID_POINTS[lid["type"]]):
                row[tariff] = 2 * crossings + sum(EDGE_POINTS[tariff][edge["band"]] for edge in joined) + lid_points
            feasible.append(row)

    optimum = {}
    for tariff in EDGE_POINTS:
        best = min(row[tariff] for row in feasible)
        winners = [row for row in feasible if row[tariff] == best]
        representative = min(winners, key=lambda row: (row["code"], row["reference"]))
        optimum[tariff] = {
            "score": best,
            "count": len(winners),
            "representative": f"{representative['code']}/{representative['reference']}",
            "window_edge": representative["window_edge"],
            "winners": [f"{row['code']}/{row['reference']}" for row in winners],
        }

    by_ref = Counter(row["reference"] for row in feasible)
    min_band = min(
        (abs(edge["d"] - limit), edge["d"], pair, limit)
        for pair, edge in edges.items()
        for limit in THRESHOLDS
    )
    return {
        "same_name": sorted(matching_names),
        "by_reference": [by_ref[n] for n in range(1, len(references) + 1)],
        "total": len(feasible),
        "optimum": optimum,
        "core_count": len(core_codes),
        "distance_matrix": [[edges[i, j]["d"] for j in range(1, 6)] for i in range(1, 6)],
        "band_matrix": [[edges[i, j]["band"] for j in range(1, 6)] for i in range(1, 6)],
        "min_band_margin": min_band,
        "min_window_margin": min(window_margins),
        "core_codes": core_codes,
        "feasible": feasible,
    }


def main():
    facts = json.loads((ROOT / "facts.json").read_text())
    upper, lower, refs = (facts[key] for key in ("upper", "lower", "references"))
    matching_names = {
        (i, j)
        for i, top in enumerate(upper, 1)
        for j, bottom in enumerate(lower, 1)
        if top["name"] == bottom["name"]
    }
    mistaken_refs = list(refs)
    mistaken_refs.insert(3, {"id":"E2", "xy":[1135, 1715], "type":"stones"})
    data = {
        "version": "ZB-0235-v2",
        "baseline": solve(upper, lower, refs, matching_names),
        "alternatives": {
            "same_color_as_same_name": {
                "changed": "上排 1 与下排 1 的粉堆偏黄，误把这一对视为 CURCUMA 同名边。以 1-1 取代 5-1，保留 4-2。其他图证保持原样。",
                "result": solve(upper, lower, refs, (matching_names - {(5, 1)}) | {(1, 1)}),
            },
            "occluded_lid_as_visible": {
                "changed": "把白牌斜下缘邻近石块处错认成牌下罐的可见圆盖顶，以 x=1135 额外加入灰褐块参照。原参照不变，新参照排在粉紫花苞之后。",
                "result": solve(upper, lower, sorted(mistaken_refs, key=lambda lid: lid["xy"][0]), matching_names),
            },
        },
    }
    (ROOT / "recompute.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
