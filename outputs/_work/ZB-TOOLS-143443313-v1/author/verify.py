#!/usr/bin/env python3
"""Independently check the reported results by choosing two slots per row first."""

import json
from itertools import combinations, product
from pathlib import Path

HERE = Path(__file__).resolve().parent
facts = json.loads((HERE / 'facts.json').read_text())
report = json.loads((HERE.parent / 'recompute.json').read_text())


def verify(run, *, trust_print=False, swap_yellow=False):
    slots = {s['id']: s for s in facts['slots']}
    left, right = (facts['anchors'][k]['xy'][0] for k in ('L', 'R'))
    colors = {'red', 'yellow'}

    def collar(slot):
        return 'red' if swap_yellow and slot == 'B01' else slots[slot]['collar']

    def x(slot):
        return slots[slot]['label_xy'][0]

    first = [k for k in slots if k[0] == 'A' and collar(k) in colors and left - 1680 <= x(k) <= left + 1680]
    middle = [k for k, s in slots.items() if k[0] == 'B' and (s['symbol'] == 'hex' or collar(k) in colors)]
    last = [k for k, s in slots.items() if k[0] == 'C' and s['symbol'] == 'star-dot'
            and (trust_print or not s['blade']) and right - 1750 <= x(k) <= right + 1750]
    ab = {(a, b) for a, b in product(first, middle) if x(a) - 1490 <= x(b) <= x(a) + 1490
          and (slots[b]['symbol'] == 'hex' or {collar(a), collar(b)} == colors)}
    bc = {(b, c) for b, c in product(middle, last) if x(b) - 1230 <= x(c) <= x(b) + 1230}
    ticket_count = sum(sum(v == b for _, v in ab) * sum(u == b for u, _ in bc) for b in middle)
    losses = []
    for a, b, c in product(combinations(first, 2), combinations(middle, 2), combinations(last, 2)):
        for ordering in product((False, True), repeat=2):
            b_order = b[::-1] if ordering[0] else b
            c_order = c[::-1] if ordering[1] else c
            triplets = list(zip(a, b_order, c_order))
            if any((i, j) not in ab or (j, k) not in bc for i, j, k in triplets):
                continue
            s, t = sorted(sum(slots[k]['number'] * w for k, w in zip(ticket, (1, 2, 1))) for ticket in triplets)
            dm, dn = abs(s - 45) + abs(t - 52), abs(s - 44) + abs(t - 51)
            codes = tuple(''.join(k[1:] for k in ticket) for ticket in triplets)
            losses.append((dm, dn, max(dm, dn), dm + dn, codes))
    best_m = min(row[0] for row in losses)
    best_n = min(row[1] for row in losses)
    best_joint = min(row[2:4] for row in losses)
    tied = [row[-1] for row in losses if row[2:4] == best_joint]
    expected = (len(first), len(ab), len(bc), len(last), ticket_count, len(losses),
                best_m, sum(row[0] == best_m for row in losses),
                best_n, sum(row[1] == best_n for row in losses), *best_joint, len(tied), *min(tied))
    assert expected == tuple(run['answers'].values()), (expected, run['answers'])
    print(run['response'])


if __name__ == '__main__':
    verify(report['baseline'])
    verify(report['alternatives']['flat_blade_accepted'], trust_print=True)
    verify(report['alternatives']['reflected_red_at_B01'], swap_yellow=True)
