"""Enumerate the frozen image transcription and image-supported alternatives."""
import itertools
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def solve(objects):
    columns = [[o for o in objects if o['column'] == col] for col in 'ABCD']
    lookup = {(o['column'], o['rank']): o for o in objects}

    def edge(left, right):
        return abs(left['rank'] - right['rank']) <= 2 and left['F'] + right['F'] >= 1

    edge_counts = [sum(edge(a, b) for a in left for b in right)
                   for left, right in zip(columns, columns[1:])]
    routes = []
    for selected in itertools.product(*columns):
        if sum(o['F'] for o in selected) != 3 or sum(o['H'] for o in selected) < 3:
            continue
        if all(edge(a, b) for a, b in zip(selected, selected[1:])):
            routes.append(tuple(o['rank'] for o in selected))

    def route_cost(route, scenario):
        base = sum((a - b) ** 2 for a, b in zip(route, route[1:]))
        if scenario == 0:
            return base
        warm = sum(lookup[(col, rank)]['H'] for col, rank in zip('ABCD', route))
        if warm == 3:
            return base + 4 * route[1]
        return base + 3 * (6 - route[3])

    plans = []
    for first, second in itertools.combinations(sorted(routes), 2):
        if not all(a < b for a, b in zip(first, second)):
            continue
        warm = sum(lookup[(col, rank)]['H']
                   for route in (first, second) for col, rank in zip('ABCD', route))
        if warm == 7:
            plans.append((first, second))
    optima = []
    for scenario in (0, 1):
        scores = []
        for first, second in plans:
            costs = (route_cost(first, scenario), route_cost(second, scenario))
            scores.append((max(costs), sum(costs)))
        if not scores:
            optima.append(None)
            continue
        best = min(scores)
        winners = [plan for plan, score in zip(plans, scores) if score == best]
        representative = min(first + second for first, second in winners)
        optima.append([*best, len(winners), list(representative)])
    answer = [
        [[len(col), sum(o['F'] for o in col), sum(o['H'] for o in col)] for col in columns],
        edge_counts, len(routes), len(plans), *optima,
    ]
    return {'answer': answer, 'routes': routes, 'plans': plans,
            'representative_costs': [None if opt is None else
                                     [route_cost(tuple(opt[3][:4]), s),
                                      route_cost(tuple(opt[3][4:]), s)]
                                     for s, opt in enumerate(optima)]}


def main():
    facts = json.loads((HERE / 'facts.json').read_text())
    baseline = solve(facts['objects'])
    alternatives = []
    for object_id, attribute, value, explanation in [
        ('A5', 'F', 1, '把前翅残余零星青绿色小点当作成片主斑'),
        ('C4', 'H', 1, '把乳白奶油黄色后翅斑当作橙色暖斑'),
    ]:
        changed = [dict(o) for o in facts['objects']]
        for obj in changed:
            if obj['id'] == object_id:
                obj[attribute] = value
        result = solve(changed)
        alternatives.append({'change': [object_id, attribute, value], 'visual_basis': explanation,
                             'result': result,
                             'changed_questions': [i + 1 for i, (a, b) in enumerate(
                                 zip(baseline['answer'], result['answer'])) if a != b]})
    out = {'version': HERE.name, 'baseline': baseline, 'alternatives': alternatives}
    (HERE / 'recompute.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({'baseline': baseline['answer'], 'alternatives': [
        {'change': a['change'], 'answer': a['result']['answer'],
         'changed_questions': a['changed_questions']} for a in alternatives]}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
