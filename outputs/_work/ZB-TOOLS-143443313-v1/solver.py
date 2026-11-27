#!/usr/bin/env python3
"""Recompute the frozen prompt from the author observations using the standard library."""

import json
from itertools import combinations, product
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIMITS = dict(LA=1680, AB=1490, BC=1230, CR=1750)
TARGETS = ((45, 52), (44, 51))
COLORS = {'red', 'yellow'}


def solve(facts, *, ignore_blade=False, collar_201=None, skip_gate=None):
    slots = {row: [s.copy() for s in facts['slots'] if s['row'] == row] for row in 'ABC'}
    if collar_201 is not None:
        slots['B'][0]['collar'] = collar_201
    upper = [s for s in slots['A'] if s['collar'] in COLORS]
    middle = [s for s in slots['B'] if s['symbol'] == 'hex' or s['collar'] in COLORS]
    lower = [s for s in slots['C'] if s['symbol'] == 'star-dot' and (ignore_blade or not s['blade'])]
    anchors = {k: v['xy'][0] for k, v in facts['anchors'].items()}
    errors = facts['reading_error_x_px']
    comparisons = {edge: [] for edge in LIMITS}

    def passes(edge, left, right, x_left, x_right, error_bound):
        distance = abs(x_left - x_right)
        limit = LIMITS[edge]
        comparisons[edge].append(dict(left=left, right=right, distance=distance,
                                      limit=limit, margin=abs(distance - limit), error_bound=error_bound))
        return distance <= limit or skip_gate == edge

    def gate(edge, anchor, slot):
        endpoint = (anchor, anchors[anchor])
        point = (slot['id'], slot['label_xy'][0])
        left, right = (endpoint, point) if edge == 'LA' else (point, endpoint)
        return passes(edge, left[0], right[0], left[1], right[1], errors['anchor'] + errors['slot'])

    def connect(edge, a, b):
        return passes(edge, a['id'], b['id'], a['label_xy'][0], b['label_xy'][0], 2 * errors['slot'])

    top = [s for s in upper if gate('LA', 'L', s)]
    bottom = [s for s in lower if gate('CR', 'R', s)]
    ab = [(a['id'], b['id']) for a, b in product(top, middle)
          if (b['symbol'] == 'hex' or a['collar'] != b['collar']) and connect('AB', a, b)]
    bc = [(b['id'], c['id']) for b, c in product(middle, bottom) if connect('BC', b, c)]
    values = {s['id']: s['number'] for s in facts['slots']}
    tickets = sorted(((a, b, c), int(values[a] + 2 * values[b] + values[c]))
                     for (a, b), (b2, c) in product(ab, bc) if b == b2)

    def code(ticket):
        return ''.join(s[1:] for s in ticket)

    pairs = []
    for (first, a), (second, b) in combinations(tickets, 2):
        if set(first).isdisjoint(second):
            s, t = sorted((a, b))
            deviations = tuple(abs(s - u) + abs(t - v) for u, v in TARGETS)
            pairs.append((deviations, (code(first), code(second)), (a, b)))

    per_mode = []
    for i in range(len(TARGETS)):
        best = min(d[i] for d, _, _ in pairs)
        per_mode.append((best, sum(d[i] == best for d, _, _ in pairs)))
    joint_key = min((max(d), sum(d)) for d, _, _ in pairs)
    joint = [(codes, points, deviations) for deviations, codes, points in pairs
             if (max(deviations), sum(deviations)) == joint_key]
    codes, points, deviations = min(joint)
    answers = dict(LA=len(top), AB=len(ab), BC=len(bc), CR=len(bottom),
                   tickets=len(tickets), pairs=len(pairs),
                   M_min=per_mode[0][0], M_ties=per_mode[0][1],
                   N_min=per_mode[1][0], N_ties=per_mode[1][1],
                   joint_max=joint_key[0], joint_sum=joint_key[1], joint_ties=len(joint),
                   ticket1=codes[0], ticket2=codes[1])
    groups = [('LA', 'AB', 'BC', 'CR'), ('tickets',), ('pairs',),
              ('M_min', 'M_ties', 'N_min', 'N_ties'),
              ('joint_max', 'joint_sum', 'joint_ties', 'ticket1', 'ticket2')]
    return dict(answers=answers,
                response='|'.join(','.join(str(answers[k]) for k in group) for group in groups),
                edges=dict(LA=[s['id'] for s in top], AB=ab, BC=bc, CR=[s['id'] for s in bottom]),
                tickets=[dict(slots=ids, points=value) for ids, value in tickets],
                representative=dict(points_in_code_order=points, deviations=deviations),
                comparisons=comparisons)


def main():
    facts = json.loads((ROOT / 'author/facts.json').read_text())
    baseline = solve(facts)
    alternatives = {
        'flat_blade_accepted': solve(facts, ignore_blade=True),
        'reflected_red_at_B01': solve(facts, collar_201='red'),
    }
    assert alternatives['flat_blade_accepted']['answers']['joint_max'] != baseline['answers']['joint_max']
    assert alternatives['reflected_red_at_B01']['answers']['pairs'] != baseline['answers']['pairs']
    checks = {k: min(rows, key=lambda row: row['margin'] / row['error_bound'])
              for k, rows in baseline['comparisons'].items()}
    assert all(v['margin'] > v['error_bound'] for v in checks.values())
    for variant in alternatives.values():
        assert all(row['margin'] > row['error_bound']
                   for rows in variant['comparisons'].values() for row in rows)
    anchor_ablations = {k: solve(facts, skip_gate=k)['answers'] for k in ('LA', 'CR')}
    assert all(v['pairs'] != baseline['answers']['pairs'] for v in anchor_ablations.values())
    delta = {name: {k: [v, alt['answers'][k]] for k, v in baseline['answers'].items() if v != alt['answers'][k]}
             for name, alt in alternatives.items()}
    doc = dict(baseline=baseline, alternatives=alternatives, changed_fields=delta,
               closest_thresholds=checks, anchor_gate_ablations=anchor_ablations)
    print(json.dumps(doc, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
