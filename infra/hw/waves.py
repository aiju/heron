"""Static timing analysis on waveforms (RFC 0048): a netlist's export for
the static timing engine (infra/sta), and the calls into it.

    export(nl, variant)            the engine's netlist: nets (those a series
                                   resistor joins merged), every chip with
                                   its description (cells.describe) and its
                                   pins' wiring delays, the pulled-up nets
    analyse(exported, cases, ...)  heron.native.sta.analyse: each case's
                                   branches, their checks and slacks

A case is a dict:

    label     a name for the reports
    clock     the reference clock's net (an oscillator's): time 0 is one of
              its rising edges, and an event is each of its edges
    pins      {net: 0 or 1}: values the net settles to (its timing still
              computed), as a control store's outputs read a word
    start     {net: (before, after)}: a register's output just before the
              edge at 0 and what it takes there (2 for X)
    branch    [net]: registers that split the case where they'd load X
    end       {"net": net, "events": n}: the window ends at the first edge
              after 0 at which net rises; at most n events
"""

from heron import native

from . import cells, chips

X = 2


def export(nl, variant=chips.DEFAULT_VARIANT, drop=()):
    """The engine's netlist for nl, without the chips whose references
    are in drop (a simulation's fixtures)."""
    timing = chips.load_timing()
    insts = [i for i in nl.instances if i.ref not in drop]
    root = {}

    def find(n):
        while root.get(n, n) != n:
            n = root[n]
        return n
    for inst in insts:
        for a, b in inst.type.joins:
            if a in inst.conn and b in inst.conn:
                ra, rb = find(inst.conn[a]), find(inst.conn[b])
                if ra != rb:
                    # keep the rails' names, else the first
                    if rb in ("GND", "VCC"):
                        ra, rb = rb, ra
                    root[rb] = ra
    ids, names = {}, []
    for inst in insts:
        for net in inst.conn.values():
            r = find(net)
            if r not in ids:
                ids[r] = len(names)
                names.append(r)
    out, pulled = [], set()
    for inst in insts:
        t = inst.type
        nets = [ids[find(inst.conn[p])] if p in inst.conn else -1 for p, _ in t.pins]
        if t.model == "pullup" or t.name == "rpull":
            pulled |= {n for (p, k), n in zip(t.pins, nets) if k == "pull" and n >= 0}
        out.append({
            "ref": inst.ref, "type": t.name, "model": t.model, "family": t.family,
            "part": inst.part_number(variant), "pins": [p for p, _ in t.pins], "nets": nets,
            "params": {k: int(v) for k, v in inst.params.items()}, "nocheck": inst.nocheck,
            "desc": cells.describe(inst, timing, variant),
            "pin_delays": [int(inst.pin_extra.get(p, 0)) for p, _ in t.pins],
        })
    return {"nets": names, "chips": out, "pulled": sorted(pulled), "variant": variant,
            "aliases": {n: find(n) for n in root}}


def analyse(exported, cases, fraction=0.3, tolerance=1000, marginal=2000, paths=1, jobs=None):
    """Every case's branches, as dicts: the engine's results
    (infra/sta/src/result.rs)."""
    opts = {"fraction": fraction, "tolerance": tolerance, "marginal": marginal, "paths": paths}
    return native.sta.analyse(exported, list(cases), opts, jobs or 0)
