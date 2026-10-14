"""Lines held only by a pull-up: WAIT after its driver lets go, and the
CLASS and REQ lines of an empty slot, while their neighbours switch.

- **WAIT** is bused. The addressed fast card drives it high in the last
  clock of a transfer and lets go; the 10 kohm pull-up then holds it until
  the next card drives it, and through every simple-card transfer, where
  nobody does. With some 200 pF on the line, the pull-up takes
  microseconds to move it, so for the length of a transfer whatever
  crosstalk does to it stays.
- **CLASS** (and REQ) are radial, from the backplane's logic to a slot,
  pulled up at the backplane's end; an empty slot, or a card's open strap,
  leaves the slot end open. The class lookup reads them in the address
  clock, just as the address lines switch.

Each victim runs the length of the backplane between two switching
neighbours (the coupled backplane traces of report 0013's crosstalk model,
field-solved), and where they have contacts at a slot, those couple too.
"""

import numpy as np

from heron.infra.si import engine, ibis

from . import bus, bused, gb, noise

T_RELEASE = 5e-9
T_RISE, T_FALL, T_STOP = 20e-9, 70e-9, 120e-9
PULLUP = 10e3


def _ladders(bp, prefixes):
    """The backplane's segments, coupled three abreast."""
    tp = bus.trace_params()
    L, C = tp["L"], tp["C"]
    n = bp.slots
    nodes = ["bpL"] + [f"bps{k}" for k in range(n)] + ["bpR"]
    xs = [-bp.end] + [k * bp.pitch for k in range(n)] + [(n - 1) * bp.pitch + bp.end]
    out = []
    for i in range(len(nodes) - 1):
        a = [f"{p}{nodes[i]}" for p in prefixes]
        b = [f"{p}{nodes[i + 1]}" for p in prefixes]
        out += noise._coupled_ladder(f"f{i}", (a, b), L, C, xs[i + 1] - xs[i])
    return out


def run(victim, family="abt", corner="max", aggressor_slot=0, victim_slot=7, k_conn=0.35,
        level=1, keep=False):
    """`victim` is 'wait' (released high at T_RELEASE by the card in
    victim_slot) or 'class' (pulled up, open at slot 15). The two
    neighbours rise at T_RISE and fall at T_FALL, driven from
    aggressor_slot. Returns the victim's level before the edges, its
    lowest and highest after, and where it ends up."""
    b = gb.bus_model()
    bp = b.bp
    m, _ = ibis.load(family)
    out = [f"Vcc vcc 0 {m.vcc(corner)}"]
    for p in "ab":
        lines, _ = bused.netlist(b, ("slot", aggressor_slot), corner, [T_RISE, T_FALL], prefix=p,
                                 backplane=False)
        out += lines
    if victim == "wait":
        lines, dies = bused.netlist(b, ("slot", victim_slot), corner, [], initial=level, prefix="v",
                                    backplane=False, release=T_RELEASE, pullup=PULLUP)
        out += lines
        for k in range(bp.slots):
            out += [f"Kfav{k} Lac{k} Lvc{k} {k_conn}", f"Kfvb{k} Lvc{k} Lbc{k} {k_conn}"]
        probes = {name: f"v({d})" for name, d in dies.items()}
    elif victim == "class":
        # the backplane's input at the left end, pulled up; the contact at
        # slot 15, open on the card's side
        out += [f"Rvpu vbpL vcc {PULLUP}"]
        mi, _ = ibis.load(family)
        rp, lp, cp = ibis.pin_rlc(family, "soic", model=mi.name)
        out += [f"Rvin vbpL vin {rp:.4g}", f"Lvin vin vind {lp:.4g}", f"Cvin vbpL 0 {cp:.4g}"]
        out += ibis.buffer("vrx", family, corner, "vind", "vcc", "0")
        k = bp.slots - 1
        out += [f"Cvb{k} vbps{k} 0 {bp.conn_c / 2:.4g}", f"Lvc{k} vbps{k} vc{k} {bp.conn_l:.4g}",
                f"Cvc{k} vc{k} 0 {bp.conn_c / 2:.4g}",
                f"Kfav{k} Lac{k} Lvc{k} {k_conn}", f"Kfvb{k} Lvc{k} Lbc{k} {k_conn}"]
        probes = {"logic": "v(vind)"}
    else:
        raise ValueError(victim)
    out += _ladders(bp, "avb")
    names = list(probes)
    r = engine.run(out, [probes[n] for n in names], T_STOP, title=f"floating {victim} {family} {corner}")
    t = r["time"]
    v = {n: r[probes[n]] for n in names}
    after = t > T_RISE
    before = float(np.mean([np.interp(T_RISE - 1e-9, t, x) for x in v.values()]))
    res = {"before": before,
           "lowest": min(float(x[after].min()) for x in v.values()),
           "highest": max(float(x[after].max()) for x in v.values()),
           "after_rise": min(float(np.interp(T_FALL - 1e-9, t, x)) for x in v.values()),
           "after_fall": min(float(np.interp(T_STOP - 1e-9, t, x)) for x in v.values())}
    if keep:
        res["time"], res["v"] = t, v
    return res
