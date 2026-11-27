"""从作者逐隔间事实表穷举接力与双接力方案。仅使用标准库。"""
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARIFFS = {
    "0": {"B": 3, "G": 5, "K": 1, "R": 4, "W": 2, "Y": 6},
    "1": {"B": 7, "G": 1, "K": 5, "R": 2, "W": 4, "Y": 3},
}


def solve(facts):
    objects = {o["id"]: o for o in facts["objects"] if o["eligible"]}
    by_column = [[o for o in objects.values() if o["id"][0] == c] for c in "ABC"]
    ab = [(a["id"], b["id"]) for a, b in itertools.product(*by_column[:2])
          if abs(a["y"] - b["y"]) <= 1000]
    bc = [(b["id"], c["id"]) for b, c in itertools.product(*by_column[1:])
          if abs(b["y"] - c["y"]) <= 1650]
    relays = []
    for a, b, c in itertools.product(*by_column):
        if (a["id"], b["id"]) not in ab or (b["id"], c["id"]) not in bc:
            continue
        for colors in itertools.product(a["colors"], b["colors"], c["colors"]):
            if len(set(colors)) == 3:
                code = "/".join(o["id"] + color for o, color in zip((a, b, c), colors))
                relays.append({"code": code, "ids": [o["id"] for o in (a, b, c)],
                               "colors": colors})
    plans = []
    for first, second in itertools.combinations(sorted(relays, key=lambda r: r["code"]), 2):
        ids = first["ids"] + second["ids"]
        if len(set(ids)) != 6:
            continue
        # 两条接力合用的两个 B 隔间中，恰有一个是白灰类。
        if sum(objects[r["ids"][1]]["colors"] == ["W"] for r in (first, second)) != 1:
            continue
        colors = first["colors"] + second["colors"]
        position_cost = sum(int(i[1:]) for i in ids)
        cost = {mode: position_cost + sum(tariff[color] for color in colors)
                for mode, tariff in TARIFFS.items()}
        plans.append({"code": first["code"] + ";" + second["code"], "cost": cost})
    optimum = {}
    for mode in TARIFFS:
        value = min(p["cost"][mode] for p in plans)
        winners = [p["code"] for p in plans if p["cost"][mode] == value]
        optimum[mode] = {"cost": value, "count": len(winners), "canonical": min(winners),
                         "all_winners": winners}
    return {
        "compartment_counts": [sum(o["id"].startswith(column) for o in facts["objects"])
                               for column in "ABC"],
        "A3_colors": objects["A3"]["colors"], "C3_colors": objects["C3"]["colors"],
        "distance_A2_B3_px": abs(objects["A2"]["y"] - objects["B3"]["y"]),
        "distance_B4_C2_px": abs(objects["B4"]["y"] - objects["C2"]["y"]),
        "ab_edges": ab, "bc_edges": bc,
        "ab_count": len(ab), "bc_count": len(bc), "relay_count": len(relays),
        "plan_count": len(plans), "optimum": optimum,
        "canonical_changed": int(optimum["0"]["canonical"] != optimum["1"]["canonical"]),
        "relays": relays, "plans": plans,
    }


def main():
    facts = json.loads((ROOT / "facts.json").read_text())
    baseline = solve(facts)
    alternatives = {}
    for label, object_id, colors in [
        ("C3_misread_as_blue_only", "C3", ["B"]),
        ("A3_misread_as_yellow_only", "A3", ["Y"]),
    ]:
        altered = json.loads(json.dumps(facts))
        next(o for o in altered["objects"] if o["id"] == object_id)["colors"] = colors
        result = solve(altered)
        fields = ["relay_count", "plan_count", "optimum", "canonical_changed"]
        alternatives[label] = {"changed_input": {object_id: colors},
                               "changed_fields": {k: {"baseline": baseline[k], "alternative": result[k]}
                                                  for k in fields if baseline[k] != result[k]},
                               "result": result}
    result = {"version": "ZB-FERRULES-0318-v1", "baseline": baseline,
              "counterfactuals": alternatives}
    (ROOT / "recompute.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in baseline.items() if k not in ("relays", "plans")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
