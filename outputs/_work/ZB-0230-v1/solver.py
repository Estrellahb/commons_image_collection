import itertools
import json
from pathlib import Path

COLORS = {'A': ['橙', '黄', '绿'], 'B': ['绿', '红', '黄'], 'C': ['杂', '白', '红']}
WEIGHTS = {'橙': 4, '黄': 2, '绿': 3, '红': 5, '杂': 1, '白': 6}


def solve(colors):
    routes = []
    for a, b, c, d in itertools.product(range(1, 4), range(1, 4), range(1, 4), (2, 3)):
        if any(abs(x-y) > 1 for x, y in zip((a,b,c), (b,c,d))):
            continue
        chosen = [colors['A'][a-1], colors['B'][b-1], colors['C'][c-1]]
        if len(set(chosen)) != 3:
            continue
        if (d == 2 and '黄' in chosen) or (d == 3 and '红' in chosen):
            continue
        moves = abs(a-b) + abs(b-c) + abs(c-d)
        base = sum(WEIGHTS[color] for color in chosen) + moves
        routes.append({'route': [a,b,c,d], 'colors': chosen, 'base': base})
    result = {'count': len(routes), 'by_tea': [sum(r['route'][3] == d for r in routes) for d in (2,3)]}
    for name, fees in [('工况甲', {2:8, 3:0}), ('工况乙', {2:0, 3:5})]:
        costs = [(r['base'] + fees[r['route'][3]], r['route']) for r in routes]
        minimum = min(v for v, _ in costs)
        winners = sorted(route for v, route in costs if v == minimum)
        result[name] = {'minimum': minimum, 'ties': len(winners), 'representative': winners[0], 'all_winners': winners}
    pairs = [(a, b) for a, b in itertools.combinations(routes, 2) if all(x != y for x, y in zip(a['route'], b['route']))]
    pair_min = min(a['base'] + b['base'] for a, b in pairs)
    result['不复用路线对'] = {'count': len(pairs), 'minimum': pair_min, 'ties': sum(a['base'] + b['base'] == pair_min for a, b in pairs)}
    result['routes'] = routes
    return result

alternative = {key: value[:] for key, value in COLORS.items()}
alternative['C'][0] = '红'
output = {'baseline': solve(COLORS), 'alternative': solve(alternative), 'alternative_description': '将混色胡椒颗粒误按红色归类，C1由杂改红；改变颜色互异及红色禁用约束。'}
Path(__file__).with_name('recompute.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(output, ensure_ascii=False, indent=2))
