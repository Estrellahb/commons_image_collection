"""Independent enumeration by choosing an ordered pair in each column."""
import itertools
import json
from pathlib import Path

from solver import solve

HERE = Path(__file__).resolve().parent


def independent(objects):
    table = {(o['column'], o['rank']): (o['F'], o['H']) for o in objects}
    ranks = [sorted(o['rank'] for o in objects if o['column'] == c) for c in 'ABCD']

    def valid(route):
        attributes = [table[c, r] for c, r in zip('ABCD', route)]
        return (sum(f for f, h in attributes) == 3 and
                sum(h for f, h in attributes) >= 3 and
                all(abs(route[k] - route[k + 1]) <= 2 and
                    attributes[k][0] + attributes[k + 1][0] > 0 for k in range(3)))

    single_count = sum(valid(route) for route in itertools.product(*ranks))
    valid_plans = []
    for selections in itertools.product(*(list(itertools.combinations(col, 2)) for col in ranks)):
        first = tuple(s[0] for s in selections)
        second = tuple(s[1] for s in selections)
        if valid(first) and valid(second):
            warm = sum(table[c, r][1] for route in (first, second)
                       for c, r in zip('ABCD', route))
            if warm == 7:
                valid_plans.append((first, second))

    optimal = []
    for scenario in (0, 1):
        records = []
        for pair in valid_plans:
            costs = []
            for route in pair:
                a, b, c, d = route
                cost = (a - b) ** 2 + (b - c) ** 2 + (c - d) ** 2
                if scenario:
                    warm = sum(table[col, rank][1] for col, rank in zip('ABCD', route))
                    cost += {3: 4 * b, 4: 3 * (6 - d)}[warm]
                costs.append(cost)
            records.append((max(costs), sum(costs), pair[0] + pair[1]))
        if not records:
            optimal.append(None)
            continue
        records.sort()
        best = records[0][:2]
        ties = sum(record[:2] == best for record in records)
        optimal.append([*best, ties, list(records[0][2])])
    return [single_count, len(valid_plans), *optimal]


objects = json.loads((HERE / 'facts.json').read_text())['objects']
checks = []
for change in [None, ('A5', 'F', 1), ('C4', 'H', 1)]:
    changed = [dict(o) for o in objects]
    if change:
        for obj in changed:
            if obj['id'] == change[0]:
                obj[change[1]] = change[2]
    expected = solve(changed)['answer'][2:]
    actual = independent(changed)
    assert expected == actual, (change, expected, actual)
    checks.append({'change': change, 'independent_answer_questions_3_to_6': actual, 'equal': True})
(HERE / 'independent_verification.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2))
print('正确读法与两种易混读法的单路线、双路线及全部优化字段独立复算一致。')
