"""Radial lines: BCLK, SEL and GNT, each from a register or clock driver
on the backplane to one slot.

    driver die ─ pkg ─ R ─ backplane trace ─ connector ─ card stub ─┬─ rx
       │ (shared rails)                                              ├─ rx
     package power pins                                              └─ rx

The outputs of one package share its power and ground pins, so a clock
driver's outputs switching together bounce its rails and skew each other.
At the card, the stub ends in one to three receivers close together, each
on a short branch.
"""

from dataclasses import dataclass, field

import numpy as np

from heron.infra.si import engine, ibis

from . import bus


@dataclass(frozen=True)
class Radial:
    """One output's path to its slot."""
    length: float                 # backplane trace, driver to connector (m)
    series: float = 47.0          # at the driver (ohm)
    rx_family: str = "hct"
    rx_count: int = 1
    stub: float = 25e-3           # connector to the receivers
    branch: float = 5e-3          # to each receiver from the end of the stub
    rx_package: str = "soic"


@dataclass(frozen=True)
class Driver:
    family: str = "abt273"
    package: str = "soic"
    # power and ground pins of the package, and the die's own capacitance
    # between its rails; None: ideal rails (the rails don't move)
    n_gnd: int = None
    n_vcc: int = None
    die_c: float = 50e-12
    decap_esl: float = 1.5e-9
    # the IBIS fit: with overlap (crowbar current) or break before make,
    # and drive that follows the die's rails; see gb.Card.model
    overlap: bool = True
    alpha: float = None


def netlist(drv, paths, corner, edges, bp=None, prefix="r", initial=0):
    """Netlist lines for a driver package with one output per path, all
    switching at `edges`. Returns (lines, {(path, receiver): die node},
    {path: driver pin node})."""
    bp = bp or bus.Backplane(package="soic")
    z0, tpd = bp.trace()
    p = prefix
    m, comps = ibis.load(drv.family)
    rp, lp, cp = ibis.pin_rlc(drv.family, drv.package, model=m.name)
    out = []
    if drv.n_gnd:
        comp = comps[drv.package]
        r_pkg, l_pkg, _ = comp["pkg"]
        lg, lv = l_pkg[0] / drv.n_gnd, l_pkg[0] / drv.n_vcc
        out += [f"L{p}pg {p}gd {p}gx {lg:.4g}", f"R{p}pg {p}gx 0 {r_pkg[0] / drv.n_gnd:.4g}",
                f"L{p}pv vcc {p}vx {lv:.4g}", f"R{p}pv {p}vx {p}vd {r_pkg[0] / drv.n_vcc:.4g}",
                f"C{p}die {p}vd {p}gd {drv.die_c:.4g}",
                # the decoupling capacitor at the package, through its ESL
                f"C{p}dc vcc {p}dcx 100n", f"L{p}dc {p}dcx {p}dcy {drv.decap_esl:.4g}", f"R{p}dc {p}dcy 0 0.03"]
        vd, gd = f"{p}vd", f"{p}gd"
    else:
        vd, gd = "vcc", "0"
    src, (ku, kd) = ibis.coefficient_sources(f"{p}drv", drv.family, corner, edges, initial=initial,
                                             overlap=drv.overlap)
    out += src
    dies, pins = {}, {}
    sup = None if drv.alpha is None else ibis.supply_scale(m.vcc(corner), drv.alpha)
    for j, path in enumerate(paths):
        out += ibis.buffer(f"{p}b{j}", drv.family, corner, f"{p}o{j}", vd, gd, ku, kd, supply=sup)
        out += [f"L{p}o{j} {p}o{j} {p}ox{j} {lp:.4g}",
                f"R{p}o{j} {p}ox{j} {p}op{j} {rp:.4g}",
                f"C{p}o{j} {p}op{j} 0 {cp:.4g}",
                f"R{p}r{j} {p}op{j} {p}tr{j} {path.series or 1e-3}",
                f"T{p}l{j} {p}tr{j} 0 {p}bp{j} 0 Z0={z0:.4g} TD={path.length * tpd:.4g}",
                f"C{p}b{j} {p}bp{j} 0 {bp.conn_c / 2:.4g}",
                f"L{p}c{j} {p}bp{j} {p}c{j} {bp.conn_l:.4g}",
                f"C{p}c{j} {p}c{j} 0 {bp.conn_c / 2:.4g}",
                f"T{p}t{j} {p}c{j} 0 {p}s{j} 0 Z0={z0:.4g} TD={path.stub * tpd:.4g}"]
        pins[j] = f"{p}op{j}"
        model = ibis.input_model(path.rx_family)
        mr, _ = ibis.load(path.rx_family, model)
        rr, lr, cr = ibis.pin_rlc(path.rx_family, path.rx_package, model=mr.name)
        for i in range(path.rx_count):
            n = f"{j}_{i}"
            out += [f"T{p}h{n} {p}s{j} 0 {p}h{n} 0 Z0={z0:.4g} TD={max(path.branch, 2e-3) * tpd:.4g}",
                    f"C{p}p{n} {p}h{n} 0 {cr:.4g}",
                    f"R{p}k{n} {p}h{n} {p}x{n} {rr:.4g}",
                    f"L{p}k{n} {p}x{n} {p}d{n} {lr:.4g}"]
            out += ibis.buffer(f"{p}u{n}", path.rx_family, corner, f"{p}d{n}", "vcc", "0", model=model)
            dies[(j, i)] = f"{p}d{n}"
    return out, dies, pins


T_RISE, T_FALL, T_STOP = 10e-9, 50e-9, 90e-9


def edge(t, v, t0, t1, rising, lo, hi, vmeas=1.5):
    """One edge at a receiver: the time it crosses vmeas, its rate through
    [lo, hi] (V/ns), how far it rings back once it has crossed the far
    threshold (for a falling edge, the highest it gets after its first
    trough below lo), and its peak beyond the rails."""
    sel = (t >= t0) & (t < t1)
    tt, vv = t[sel], v[sel]

    def cross(thr, up):
        idx = np.flatnonzero(vv >= thr) if up else np.flatnonzero(vv <= thr)
        if len(idx) == 0 or idx[0] == 0:
            return None, None
        i = idx[0]
        return tt[i - 1] + (thr - vv[i - 1]) * (tt[i] - tt[i - 1]) / (vv[i] - vv[i - 1]) - t0, i

    tm, _ = cross(vmeas, rising)
    a, _ = cross(lo if rising else hi, rising)
    b, ib = cross(hi if rising else lo, rising)
    rate = None if (a is None or b is None or b <= a) else (hi - lo) / ((b - a) * 1e9)
    ringback = None
    if ib is not None:
        # from the first trough (falling) or crest (rising) after the edge
        # has crossed the far threshold, how far it comes back
        after = vv[ib:] if rising else -vv[ib:]
        turn = np.flatnonzero(np.diff(after) < 0)
        if len(turn):
            rest = after[turn[0]:]
            ringback = float(rest.min()) if rising else float(-rest.min())
        else:
            ringback = float(vv[-1])
    return {"t": tm, "rate": rate, "ringback": ringback,
            "peak": float(vv.max()) if rising else float(vv.min())}


def run(drv, paths, corner, bp=None, keep=False):
    """A rising and a falling edge on every path. Per receiver, both edges
    (edge() above, with thresholds 0.8 and 2.0 V); times from the start of
    the driver's edge."""
    m, _ = ibis.load(drv.family)
    lines, dies, pins = netlist(drv, paths, corner, [T_RISE, T_FALL], bp)
    lines = [f"Vcc vcc 0 {m.vcc(corner)}"] + lines
    names = list(dies)
    probes = [f"v({dies[k]})" for k in names]
    if drv.n_gnd:
        probes += ["v(rgd)", "v(rvd,rgd)"]
    r = engine.run(lines, probes, T_STOP, title=f"radial {drv.family} {corner}")
    t = r["time"]
    res = {"rx": {}}
    if keep:
        res["time"], res["v"] = t, {}
    for k in names:
        v = r[f"v({dies[k]})"]
        if keep:
            res["v"][k] = v
        res["rx"][f"{k[0]}.{k[1]}"] = {"rise": edge(t, v, T_RISE, T_FALL, True, 0.8, 2.0),
                                      "fall": edge(t, v, T_FALL, T_STOP, False, 0.8, 2.0)}
    if drv.n_gnd:
        g = r["v(rgd)"]
        res["die_gnd"] = (float(g.min()), float(g.max()))
        if keep:
            res["gnd"] = g
    return res
