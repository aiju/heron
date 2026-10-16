"""What splitting the CPU card in two would cost: the signals between the
halves, for the natural split (control against datapath, by the
netlist's sections) and for the best balanced split a min-cut search
finds (Fiduccia-Mattheyses-style moves from many random starts, each half
holding 38-62 % of the parts' area)."""

import random
from collections import defaultdict

from heron.infra.pcb import kicadlib, packages

from . import cards

CONTROL = {"Control store", "Decode", "Instruction register", "Next address", "Faults",
           "Interrupt request", "Condition latches", "Branch condition", "Reset",
           "Clock generator", "Length class", "Bus hold and crossings", "ALU control",
           "Loop counter"}


def _setup(style="smd"):
    nl = cards.netlists()["cpu"]
    chips = [i for i in nl.instances if i.type.family != "fixture"]
    area = {}
    for i in chips:
        x0, y0, x1, y1 = kicadlib.footprint(packages.footprint_for(i.type.name, style)).courtyard
        area[i.ref] = (x1 - x0) * (y1 - y0)
    nets = defaultdict(set)
    for i in chips:
        for n in i.conn.values():
            if n not in ("GND", "VCC"):
                nets[n].add(i.ref)
    nets = {n: r for n, r in nets.items() if len(r) > 1}
    return chips, area, nets


def cut(nets, side):
    return [n for n, refs in nets.items() if len({side[r] for r in refs}) > 1]


def best_split(nets, area, start, trials=20, seed=0, lo=0.38, hi=0.62):
    refs = list(area)
    tot = sum(area.values())
    nets_of = defaultdict(list)
    for n, rs in nets.items():
        for r in rs:
            nets_of[r].append(n)
    best = None
    for trial in range(trials):
        rnd = random.Random(seed + trial)
        side = dict(start) if trial == 0 else {r: rnd.randint(0, 1) for r in refs}
        cnt = {n: [0, 0] for n in nets}
        for n, rs in nets.items():
            for r in rs:
                cnt[n][side[r]] += 1
        a = [sum(area[r] for r in refs if side[r] == s) for s in (0, 1)]
        moved = True
        while moved:
            moved = False
            order = refs[:]
            rnd.shuffle(order)
            for r in order:
                s, t = side[r], 1 - side[r]
                if not (lo * tot <= a[s] - area[r] and a[t] + area[r] <= hi * tot):
                    continue
                gain = 0
                for n in nets_of[r]:
                    if cnt[n][s] == 1 and cnt[n][t] > 0:
                        gain += 1           # the net stops crossing
                    if cnt[n][t] == 0 and cnt[n][s] > 1:
                        gain -= 1           # the net starts crossing
                if gain > 0:
                    side[r] = t
                    a[s] -= area[r]
                    a[t] += area[r]
                    for n in nets_of[r]:
                        cnt[n][s] -= 1
                        cnt[n][t] += 1
                    moved = True
        c = cut(nets, side)
        if best is None or len(c) < len(best[0]):
            best = (c, side, a)
    return best


def main():
    chips, area, nets = _setup()
    natural = {i.ref: 0 if i.section in CONTROL else 1 for i in chips}
    c = cut(nets, natural)
    n0 = sum(1 for v in natural.values() if v == 0)
    print(f"control against datapath: {len(c)} signals cross "
          f"({n0} and {len(natural) - n0} chips)")
    c, side, a = best_split(nets, area, natural)
    n0 = sum(1 for v in side.values() if v == 0)
    print(f"best balanced split found: {len(c)} signals cross ({n0} and {len(side) - n0} chips, "
          f"{a[0] / sum(a):.0%} and {a[1] / sum(a):.0%} of the area)")
    return 0
