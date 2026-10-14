"""Ground bounce: many outputs of one card switching at once.

The driving card sits in a slot of a fully loaded backplane:

- **Packages:** octal '245s in DIP or SOIC, or 16-bit '16245s in TSSOP.
  Each package's die has its own rails, joined by the die's capacitance,
  and reaches the card's planes through its power and ground pins, each
  with its own inductance from the IBIS file. A 100 nF capacitor per
  package (with its ESL) decouples the planes, which also have their own
  capacitance and a bulk capacitor at the connector.
- **The connector:** every contact as one inductance matrix
  (connector.py), so the return current shares the ground and power pins
  as it really would, and the card's ground moves against the
  backplane's.
- **The lines:** every output through 22 ohm and a 25 mm card trace to its
  contact. On the backplane the quiet line and one switching line are
  modelled in full, with all 16 receivers; the other switching lines are
  uniform lines of the loaded impedance to each end, which is all their
  drivers see.

What's measured: the quiet line's glitch at the receivers, the switching
line's settle time (against one line switching alone), and how far the
card's ground and the die's ground move.

Classic IBIS models don't pin down what a driver draws from its rails, so
each case runs with both fits of ibis.Model.coefficients: with the
crowbar current of Kd = 1 - Ku, and break before make.
"""

from dataclasses import dataclass, field, replace

import numpy as np

from heron.infra.si import engine, ibis

from . import bus, bused, connector

SLOT = 7                      # the driving card, in the middle
QUIET = 7                     # which output stays put: D7, mid-package
AGGRESSOR = 6                 # the switching line modelled in full
T_EDGE = 5e-9
T_STOP = 70e-9
CALIBRATED_ALPHA = 4.0


@dataclass(frozen=True)
class Card:
    family: str = "abt"
    package: str = "soic"         # dip, soic (octal parts); tssop (16-bit)
    lines: int = 16               # 16: D0-D15 on P1; 32: and D16-D31 on P2
    switching: int = None         # how many switch (default: all but the quiet one)
    series: float = 22.0          # at each output (0 for parts with their own)
    decaps: int = 1               # 100 nF per package
    decap_esl: float = 3e-9       # a mounted 0805 with its vias: 2-5 nH
    die_c: float = 50e-12         # between the die's rails, per 8 outputs
    plane_c: float = 1e-9         # the card's power and ground planes
    stub: float = 25e-3
    overlap: bool = True          # the IBIS fit (see the module docstring)
    alpha: float = None           # the drivers' strength against their rails (ibis.supply_scale)
    guard: bool = True            # P1 pin map with guard pins

    @staticmethod
    def model(name, **kw):
        """The two models every case runs with: 'raw', the IBIS files as
        they are, which put the datasheet's ground-bounce test at two to
        three times its published value; 'calibrated', break before make
        and drive that follows the die's rails (alpha 4), within about 25%
        of it (volp())."""
        return Card(**kw) if name == "raw" else Card(overlap=False, alpha=CALIBRATED_ALPHA, **kw)

    @property
    def per_package(self):
        return 16 if self.package in ("tssop", "ssop") else 8


def _power_pins(family, package):
    """[(R, L)] of the package's ground pins and of its power pins."""
    _, comps = ibis.load(family)
    pins = comps[package]["pins"]
    g = [tuple(rlc[:2]) for _, (n, _, rlc) in sorted(pins.items()) if n.upper().startswith("GND")]
    v = [tuple(rlc[:2]) for _, (n, _, rlc) in sorted(pins.items()) if n.upper().startswith("VCC")]
    return g, v


def bus_model():
    """The backplane the card drives: 16 slots of 12 pF ABT cards."""
    card = bused.Card(family="abt")
    card = replace(card, extra_c=bused.extra_for(12e-12, card))
    return bused.Bus.full(card=card)


def card_netlist(c, corner, falling, prefix, switching, quiet=(), extra=(), maps=None):
    """The driving card: its planes, its packages with their rails and
    decoupling, outputs D0.. through their series resistors and card
    traces, and the connector(s). Outputs in `switching` switch at T_EDGE
    (falling: from high to low); those in `quiet` stay at the level the
    others go to; the rest stay where the others start. `extra` names more
    signals through the connector, whose two ends the caller wires up.
    `maps` replaces the reference pin maps (P1, P2). Returns (lines, {signal:
    backplane node}, {signal: card node}); the card's ground is
    <prefix>cgnd and its supply <prefix>cvcc."""
    z0, tpd = bus.Backplane().trace()
    p = prefix
    n = c.lines
    names = [f"D{i}" for i in range(n)]
    init = 1 if falling else 0
    out = [f"Vcc vcc 0 {ibis.load(c.family)[0].vcc(corner)}"]
    src, sw = ibis.coefficient_sources(f"{p}sw", c.family, corner, [T_EDGE], initial=init, overlap=c.overlap)
    out += src
    out += [f"V{p}qku {p}q_ku 0 {1 - init}", f"V{p}qkd {p}q_kd 0 {init}",
            f"V{p}hku {p}h_ku 0 {init}", f"V{p}hkd {p}h_kd 0 {1 - init}"]
    # the card's planes
    out += [f"C{p}plane {p}cvcc {p}cgnd {c.plane_c:.4g}",
            f"C{p}bulk {p}cvcc {p}bk 10u", f"L{p}bulk {p}bk {p}bk2 5n", f"R{p}bulk {p}bk2 {p}cgnd 0.05"]
    # packages
    m, _ = ibis.load(c.family)
    gpins, vpins = _power_pins(c.family, c.package)
    n_pkg = (n + c.per_package - 1) // c.per_package
    for j in range(n_pkg):
        out.append(f"C{p}die{j} {p}vd{j} {p}gd{j} {c.die_c * c.per_package / 8:.4g}")
        for k, (r, l) in enumerate(gpins):
            out += [f"L{p}g{j}_{k} {p}gd{j} {p}gx{j}_{k} {l:.4g}", f"R{p}g{j}_{k} {p}gx{j}_{k} {p}cgnd {r:.4g}"]
        for k, (r, l) in enumerate(vpins):
            out += [f"L{p}v{j}_{k} {p}vd{j} {p}vx{j}_{k} {l:.4g}", f"R{p}v{j}_{k} {p}vx{j}_{k} {p}cvcc {r:.4g}"]
        for k in range(c.decaps):
            out += [f"C{p}dc{j}_{k} {p}cvcc {p}dx{j}_{k} 100n", f"L{p}dc{j}_{k} {p}dx{j}_{k} {p}dy{j}_{k} {c.decap_esl:.4g}",
                    f"R{p}dc{j}_{k} {p}dy{j}_{k} {p}cgnd 0.03"]
    # outputs: die pad, pin, series resistor, card trace to the contact
    rp, lp, cp = ibis.pin_rlc(c.family, c.package, model=m.name)
    bp_nodes, card_nodes = {}, {}
    sup = None if c.alpha is None else ibis.supply_scale(m.vcc(corner), c.alpha)
    for i, name in enumerate(names):
        j = i // c.per_package
        coef = sw if i in switching else (f"{p}q_ku", f"{p}q_kd") if i in quiet else (f"{p}h_ku", f"{p}h_kd")
        out += ibis.buffer(f"{p}u{i}", c.family, corner, f"{p}die{i}", f"{p}vd{j}", f"{p}gd{j}", *coef,
                           supply=sup)
        out += [f"L{p}pin{i} {p}die{i} {p}px{i} {lp:.4g}", f"R{p}pin{i} {p}px{i} {p}pp{i} {rp:.4g}",
                f"C{p}pin{i} {p}pp{i} {p}cgnd {cp:.4g}",
                f"R{p}ser{i} {p}pp{i} {p}st{i} {c.series or 1e-3}",
                f"T{p}st{i} {p}st{i} {p}cgnd {p}cc{i} {p}cgnd Z0={z0:.4g} TD={c.stub * tpd:.4g}"]
        card_nodes[name] = f"{p}cc{i}"
        bp_nodes[name] = f"{p}bp{i}"
    for name in extra:
        card_nodes[name] = f"{p}ccx_{name}"
        bp_nodes[name] = f"{p}bpx_{name}"
    # the connector(s)
    m1, m2 = maps or (connector.p1_map(c.guard), connector.p2_map())
    on1 = [s for s in names + list(extra) if s in connector.by_signal(m1)]
    on2 = [s for s in names + list(extra) if s not in on1]
    out += connector.netlist(m1, f"{p}P1", bp_nodes, card_nodes, f"{p}cgnd", f"{p}cvcc", on1)
    if on2:
        out += connector.netlist(m2, f"{p}P2", bp_nodes, card_nodes, f"{p}cgnd", f"{p}cvcc", on2)
    return out, bp_nodes, card_nodes


def loaded_lines(prefix, i, node, b=None, slot=SLOT):
    """A switching line on the backplane, as uniform lines of the loaded
    impedance from `node` to each end."""
    b = b or bus_model()
    bp = b.bp
    zl, tl = _loaded(b)
    left = bp.end + slot * bp.pitch
    right = bp.end + (bp.slots - 1 - slot) * bp.pitch
    return [f"T{prefix}l{i} {node} 0 {prefix}le{i} 0 Z0={zl:.4g} TD={left * tl:.4g}",
            f"T{prefix}r{i} {node} 0 {prefix}re{i} 0 Z0={zl:.4g} TD={right * tl:.4g}"]


def netlist(c, corner, falling=True, prefix="g"):
    """Returns (lines, probes by name)."""
    b = bus_model()
    p = prefix
    n = c.lines
    names = [f"D{i}" for i in range(n)]
    # the line modelled in full switches first; the quiet line never does
    order = [AGGRESSOR] + [i for i in range(n) if i not in (QUIET, AGGRESSOR)]
    switching = order[: (c.switching if c.switching is not None else n - 1)]
    out, bp_nodes, _ = card_netlist(c, corner, falling, p, switching, quiet=(QUIET,))
    # the backplane: the quiet line and one switching line in full, the rest as loaded lines
    probes = {}
    full = {QUIET: "q", AGGRESSOR: "a"}
    for i, name in enumerate(names):
        if i in full:
            tag = f"{p}{full[i]}"
            lines, dies = bused.netlist(b, None, corner, [], prefix=tag, external=(SLOT,))
            out += lines
            out.append(f"R{p}j{i} {bp_nodes[name]} {tag}bps{SLOT} 1e-3")
            for rx, d in dies.items():
                probes[f"{full[i]}:{rx}"] = f"v({d})"
        else:
            out += loaded_lines(p, i, bp_nodes[name], b)
    probes["card_gnd"] = f"v({p}cgnd)"
    probes["card_vcc"] = f"v({p}cvcc,vcc)"
    probes["die_gnd"] = f"v({p}gd0)"
    probes["die_gnd_card"] = f"v({p}gd0,{p}cgnd)"
    probes["quiet_pin"] = f"v({p}pp{QUIET})"
    return out, probes


def _loaded(b):
    """Loaded impedance and delay (s/m) of the backplane with b's cards."""
    bp = b.bp
    z0, tpd = bp.trace()
    cl = tpd / z0
    cd = (bp.conn_c + bused.card_c(b.cards[0], bp)) / bp.pitch
    return z0 / np.sqrt(1 + cd / cl), tpd * np.sqrt(1 + cd / cl)


def run(c, corner, falling=True, keep=False):
    lines, probes = netlist(c, corner, falling)
    names = list(probes)
    r = engine.run(lines, [probes[k] for k in names], T_STOP,
                   title=f"gb {c.family} {c.package} x{c.lines} {corner} {'falling' if falling else 'rising'}")
    t = r["time"]
    v = {k: r[probes[k]] for k in names}
    after = t > T_EDGE
    vil, vih = ibis.thresholds("abt")
    res = {}
    # the quiet line, at each receiver: how far toward the threshold, and
    # until when it's outside its valid region
    q = {k: x for k, x in v.items() if k.startswith("q:")}
    if falling:
        peak = max(float(x[after].max()) for x in q.values())
        bad = [t[after][x[after] > vil] for x in q.values()]
    else:
        peak = min(float(x[after].min()) for x in q.values())
        bad = [t[after][x[after] < vih] for x in q.values()]
    res["quiet_peak"] = peak
    res["quiet_invalid_until"] = max((float(b[-1]) - T_EDGE for b in bad if len(b)), default=None)
    res["quiet_pin_peak"] = float(v["quiet_pin"][after].max() if falling else v["quiet_pin"][after].min())
    # the switching line in full: settle at its receivers
    a = {k: x for k, x in v.items() if k.startswith("a:")}
    settles = [bus.settle(t, x, T_EDGE, T_STOP, not falling, vil, vih) for x in a.values()]
    res["settle"] = None if any(s is None for s in settles) else max(settles)
    for k in ("card_gnd", "card_vcc", "die_gnd", "die_gnd_card"):
        res[k] = (float(v[k][after].min()), float(v[k][after].max()))
    if keep:
        res["time"], res["v"] = t, v
    return res


def volp(family, package, corner="typ", overlap=True, die_c=50e-12, falling=True, alpha=None):
    """The datasheet's ground-bounce test: one package on an ideal board,
    all outputs but one switching into 50 pF and 500 ohm, the last held
    low (VOLP, with the others falling) or high (VOHV, with them rising).
    Returns the quiet pin's peak excursion and the die's ground bounce."""
    m, _ = ibis.load(family)
    per = 16 if package in ("tssop", "ssop") else 8
    gpins, vpins = _power_pins(family, package)
    rp, lp, cp = ibis.pin_rlc(family, package, model=m.name)
    init = 1 if falling else 0
    out = [f"Vcc vcc 0 {m.vcc(corner)}"]
    src, sw = ibis.coefficient_sources("sw", family, corner, [T_EDGE], initial=init, overlap=overlap)
    out += src + [f"Vqku q_ku 0 {1 - init}", f"Vqkd q_kd 0 {init}"]
    out.append(f"Cdie vd gd {die_c * per / 8:.4g}")
    for k, (r, l) in enumerate(gpins):
        out += [f"Lg{k} gd gx{k} {l:.4g}", f"Rg{k} gx{k} 0 {r:.4g}"]
    for k, (r, l) in enumerate(vpins):
        out += [f"Lv{k} vd vx{k} {l:.4g}", f"Rv{k} vx{k} vcc {r:.4g}"]
    sup = None if alpha is None else ibis.supply_scale(m.vcc(corner), alpha)
    for i in range(per):
        coef = ("q_ku", "q_kd") if i == QUIET else sw
        out += ibis.buffer(f"u{i}", family, corner, f"d{i}", "vd", "gd", *coef, supply=sup)
        out += [f"Lp{i} d{i} x{i} {lp:.4g}", f"Rp{i} x{i} p{i} {rp:.4g}", f"Cp{i} p{i} 0 {cp:.4g}",
                f"Cl{i} p{i} 0 50p", f"Rl{i} p{i} 0 500"]
    r = engine.run(out, [f"v(p{QUIET})", "v(gd)"], 40e-9, title=f"volp {family} {package}")
    t = r["time"]
    after = t > T_EDGE
    q = r[f"v(p{QUIET})"][after]
    g = r["v(gd)"][after]
    return {"quiet": float(q.max() if falling else q.min()), "die_gnd": (float(g.min()), float(g.max()))}
