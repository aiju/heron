"""Noise on quiet bus lines: crosstalk from neighbours, and ground bounce
from many outputs on one card switching at once."""

import numpy as np

from . import bus, ibis, spice

# coupling between neighbouring DIN 41612 contacts (2.54 mm apart, ~20 mm
# long). Estimated from partial inductances: about 0.45 with no ground pin
# nearby; a ground contact next to the signal lowers it.
K_CONN = 0.4
K_CONN_NEXT = 0.2               # contacts two apart

COPPER_R = 2.4                  # ohm/m, 0.2 mm x 35 um trace


def _coupled_ladder(tag, ends, L, C, length, per_mm=0.2):
    """Lumped coupled LC sections between the node lists ends[0] and
    ends[1], one per 1/per_mm mm (ngspice's CPL element is open-circuit at
    DC and unstable with these loads)."""
    n = len(L)
    sections = max(2, int(round(length * 1e3 * per_mm)))
    dz = length / sections
    out = []
    prev = ends[0]
    for s in range(sections):
        nxt = ends[1] if s == sections - 1 else [f"{tag}x{s}_{i}" for i in range(n)]
        for i in range(n):
            out.append(f"L{tag}_{s}_{i} {prev[i]} {tag}m{s}_{i} {L[i][i] * dz:.5g}")
            out.append(f"R{tag}_{s}_{i} {tag}m{s}_{i} {nxt[i]} {COPPER_R * dz:.4g}")
            # Maxwell matrix: to ground the row sum, between lines -C_ij
            out.append(f"C{tag}_{s}_{i} {nxt[i]} 0 {sum(C[i]) * dz:.5g}")
            for j in range(i + 1, n):
                out.append(f"K{tag}_{s}_{i}{j} L{tag}_{s}_{i} L{tag}_{s}_{j} "
                           f"{L[i][j] / np.sqrt(L[i][i] * L[j][j]):.5g}")
                out.append(f"C{tag}_{s}_{i}{j} {nxt[i]} {nxt[j]} {-C[i][j] * dz:.5g}")
        prev = nxt
    return out


def crosstalk(bp, term, family, corner, driver, victim_level, k_conn=K_CONN):
    """Two aggressors on either side of a victim, all driven from slot
    `driver`. The aggressors switch (rise at T_RISE, fall at T_FALL); the
    victim is held at `victim_level`. Returns the victim's worst excursion
    towards the threshold at any receiver, and per slot."""
    tp = bus.trace_params()
    L, C = tp["L"], tp["C"]
    m, _ = ibis.load(family)
    vcc = m.vcc(corner)
    lines = [f"Vcc vcc 0 {vcc}"]
    dies = {}
    for pfx, edges, init in (("a", [bus.T_RISE, bus.T_FALL], 0), ("v", [], victim_level),
                             ("b", [bus.T_RISE, bus.T_FALL], 0)):
        out, d = bus.line_netlist(bp, term, family, corner, driver, edges, initial=init,
                                  prefix=pfx, backplane=False)
        lines += out
        dies[pfx] = d
    n = bp.slots
    segs = [("L", "0", bp.end)] + [(str(k), str(k + 1), bp.pitch) for k in range(n - 1)] \
        + [(str(n - 1), "R", bp.end)]
    for i, (x, y, length) in enumerate(segs):
        a = [f"{p}bp{x}" for p in "avb"]
        b = [f"{p}bp{y}" for p in "avb"]
        lines += _coupled_ladder(f"g{i}", (a, b), L, C, length)
    for k in range(n):
        lines += [f"Kav{k} Lac{k} Lvc{k} {k_conn}", f"Kvb{k} Lvc{k} Lbc{k} {k_conn}",
                  f"Kab{k} Lac{k} Lbc{k} {k_conn * K_CONN_NEXT / K_CONN:.3g}"]
    probes = [f"v({d})" for d in dies["v"].values()]
    r = spice.run(lines, probes, bus.T_STOP, title=f"xtalk {family} {term.name} {corner}")
    t = r["time"]
    late = t > bus.T_RISE
    res = {}
    for k, d in dies["v"].items():
        if k == driver:
            continue
        v = r[f"v({d})"]
        base = float(np.interp(bus.T_RISE - 0.5e-9, t, v))
        if victim_level == 0:
            res[k] = (base, float(v[late].max()))
        else:
            res[k] = (base, float(v[late].min()))
    pick = max if victim_level == 0 else min
    worst = pick(res.values(), key=lambda bv: bv[1])
    return {"worst": worst, "slots": res, "time": t,
            "v": {k: r[f"v({d})"] for k, d in dies["v"].items()}}


def ground_bounce(bp, term, family, corner, driver, packages=1, package="dip",
                  n_gnd=12, n_vcc=6, decap_esl=3e-9, die_c=100e-12, falling=True):
    """`packages` octal transceivers on the card in slot `driver`, all
    outputs switching at once except one held quiet (low for falling edges,
    high for rising). Every line runs the length of the backplane. Each
    package's ground and VCC pins have their IBIS inductance; the card's
    planes reach the backplane through `n_gnd` and `n_vcc` connector
    contacts, and each package has a 100 nF decoupling capacitor.
    Returns the quiet line's worst excursion at the receivers and the
    die and card ground bounce."""
    bp = bus.Backplane(**{**bp.__dict__, "package": package})
    m, comps = ibis.load(family)
    vcc = m.vcc(corner)
    comp = comps[package]
    gpin = next(rlc for name, mn, rlc in comp["pins"].values() if name.upper() == "GND")
    vpin = next(rlc for name, mn, rlc in comp["pins"].values() if name.upper() == "VCC")
    lines = [f"Vcc vcc 0 {vcc}",
             f"Lcg cgnd 0 {bp.conn_l / n_gnd:.4g}",
             f"Lcv vcc cvcc {bp.conn_l / n_vcc:.4g}",
             f"Cbulk cvcc cvx 22u", f"Rbulk cvx cgnd 0.05"]
    t_edge = bus.T_RISE if falling else bus.T_RISE
    quiet_level = 0 if falling else 1
    init = 1 if falling else 0
    dies = {}
    for j in range(packages):
        lines += [f"Lpg{j} gd{j} gx{j} {gpin[1]:.4g}", f"Rpg{j} gx{j} cgnd {gpin[0]:.4g}",
                  f"Lpv{j} vd{j} vx{j} {vpin[1]:.4g}", f"Rpv{j} vx{j} cvcc {vpin[0]:.4g}",
                  f"Cdie{j} vd{j} gd{j} {die_c:.4g}",
                  f"Cdc{j} cvcc dc{j} 100n", f"Ldc{j} dc{j} dr{j} {decap_esl:.4g}",
                  f"Rdc{j} dr{j} cgnd 0.03"]
        for b in range(8):
            quiet = j == 0 and b == 7
            rails = {driver: ("cvcc", "cgnd"), ("die", driver): (f"vd{j}", f"gd{j}")}
            if quiet:
                out, d = bus.line_netlist(bp, term, family, corner, driver, [],
                                          initial=quiet_level, prefix="q07", rails=rails)
                dies["q07"] = d
            else:
                out, d = bus.equivalent_line_netlist(bp, term, family, corner, driver, [t_edge],
                                                     initial=init, prefix=f"s{j}{b}", rails=rails)
                dies[f"s{j}{b}"] = {driver: d}
            lines += out
    qd = dies["q07"]
    probes = [f"v({d})" for k, d in qd.items() if k != driver] + \
             ["v(gd0)", "v(cgnd)", f"v(vd0,gd0)", f"v({dies['s00'][driver]})"]
    tstop = 60e-9
    r = spice.run(lines, probes, tstop, title=f"sso {family} {package} x{packages}")
    t = r["time"]
    late = t > t_edge
    worst = None
    for k, d in qd.items():
        if k == driver:
            continue
        v = r[f"v({d})"][late]
        x = float(v.max()) if falling else float(v.min())
        if worst is None or (x > worst if falling else x < worst):
            worst = x
    gd = r["v(gd0)"][late]
    cg = r["v(cgnd)"][late]
    return {"quiet": worst,
            "die_gnd": float(gd.max() if falling else gd.min()),
            "die_gnd_min": float(gd.min()),
            "card_gnd": float(np.abs(cg).max()),
            "time": t, "r": r, "quiet_slots": {k: r[f"v({d})"] for k, d in qd.items() if k != driver}}
