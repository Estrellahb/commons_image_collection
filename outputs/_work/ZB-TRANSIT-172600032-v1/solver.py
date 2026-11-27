"""Recompute ZeroBench answers from the native-photo transcription."""
import csv
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, replace
from itertools import combinations, product
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCREEN_PAIRS = ("AB", "AC", "AD", "BC", "BD", "CD")
PARTITIONS = (("AB", "CD"), ("AC", "BD"), ("AD", "BC"))
GATE = re.compile(r"[A-Z][0-9]+")


@dataclass(frozen=True)
class Row:
    screen: str
    time: str
    destination: str
    flight: str
    help: str
    gate: str
    row_number: int

    @property
    def minutes(self):
        hour, minute = map(int, self.time.split(":"))
        return hour * 60 + minute


def load_rows():
    with (HERE / "transcription.tsv").open() as file:
        reader = csv.DictReader(file, delimiter="\t")
        screen_counts = Counter()
        rows = []
        for fields in reader:
            screen_counts[fields["screen"]] += 1
            rows.append(Row(**fields, row_number=screen_counts[fields["screen"]]))
    assert screen_counts == {"A": 31, "B": 31, "C": 31, "D": 31}
    assert len({row.flight for row in rows}) == len(rows)
    assert all(not row.help or re.fullmatch(r"T\d+", row.help) for row in rows)
    return rows


def candidates(rows):
    by_screens = {key: [] for key in SCREEN_PAIRS}
    eligible = [row for row in rows if GATE.fullmatch(row.gate)]
    for first, second in combinations(eligible, 2):
        if first.screen != second.screen and first.destination == second.destination:
            by_screens[first.screen + second.screen].append((first, second))
    return by_screens


def complete_plans(edges):
    by_partition = {}
    for first, second in PARTITIONS:
        plans = []
        for left, right in product(edges[first], edges[second]):
            if left[0].destination == right[0].destination:
                continue
            if sum(bool(row.help) for row in (*left, *right)) != 1:
                continue
            minutes = sum(abs(a.minutes - b.minutes) for a, b in (left, right))
            changes = sum(a.gate[0] != b.gate[0] for a, b in (left, right))
            ordered_rows = sorted((*left, *right), key=lambda row: row.screen)
            plans.append({
                "flights": tuple(row.flight for row in ordered_rows),
                "destinations": (left[0].destination, right[0].destination),
                "time_points": minutes,
                "prefix_changes": changes,
                "surcharge_points": minutes + 100 * changes,
            })
        by_partition[first + "/" + second] = plans
    return by_partition


def optimum(plans, score):
    minimum = min(plan[score] for plan in plans)
    winners = [plan for plan in plans if plan[score] == minimum]
    return {
        "cost": minimum,
        "count": len(winners),
        "representative": min(plan["flights"] for plan in winners),
        "all_winners": sorted(plan["flights"] for plan in winners),
    }


def solve(rows):
    edges = candidates(rows)
    by_partition = complete_plans(edges)
    plans = [plan for group in by_partition.values() for plan in group]
    assert len({plan["flights"] for plan in plans}) == len(plans)
    regular = optimum(plans, "time_points")
    surcharge = optimum(plans, "surcharge_points")
    # Removal only filters existing plans. Recalculate over the surviving list.
    removals = {}
    for row in sorted(rows, key=lambda row: row.flight):
        after = min((plan["surcharge_points"] for plan in plans
                     if row.flight not in plan["flights"]), default=None)
        if after != surcharge["cost"]:
            removals[row.flight] = after
    return {
        "q1": {key: len(value) for key, value in edges.items()},
        "q2": {key: len(value) for key, value in by_partition.items()},
        "q3": regular,
        "q4": surcharge,
        "q5": {"count": len(removals), "minimum_after_removal": removals},
        "candidate_pairs": {
            key: [[asdict(a), asdict(b)] for a, b in group] for key, group in edges.items()
        },
        "complete_plans": by_partition,
    }


def main():
    rows = load_rows()
    baseline = solve(rows)
    alternative = solve([
        replace(row, help={"UA9791": "", "DL9235": "T3"}[row.flight])
        if row.flight in {"UA9791", "DL9235"} else row
        for row in rows
    ])
    assert baseline["q1"] == alternative["q1"]
    assert all(baseline[key] != alternative[key] for key in ("q2", "q3", "q4", "q5"))
    output = {
        "baseline": baseline,
        "alternative": alternative,
        "changed_visual_input": "第二屏把苏黎世 UA9791 的 T3 错绑到上一行法兰克福 DL9235。",
        "changed_constraint": "AB 苏黎世对的 Help 数从 1 变 0，BD 的 DL9235—UA9203 从 1 变 2。",
    }
    (HERE / "recompute.json").write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    for label in ("baseline", "alternative"):
        print(label, {key: value for key, value in output[label].items() if key.startswith("q")})


if __name__ == "__main__":
    main()
