"""Crosstalk onto SEL and WRITE at a simple card's connector.

A simple card makes its device's strobes from SEL and WRITE through
Schmitt-trigger gates (74HCT132), which act on edges at any time. In a
read, the card itself drives D0-D15 while SEL is asserted and WRITE is
high, so its own data outputs switch next to both: through the contacts'
mutual inductance, and through the card's ground moving against the
backplane's while their return current crosses the connector. A glitch on
SEL above the gate's VT+ ends the strobe early; one on WRITE below its VT-
turns the read into a write.

- **SEL** comes from a register on the backplane (ABT273) through its
  series resistor and a radial trace, and goes to two HCT inputs.
- **WRITE** is held high by the master in another slot through 22 ohm, on
  the loaded bus, and goes to two HCT inputs.
- **The aggressors** are the card's two octal transceivers driving
  D0-D15 through 22 ohm onto the loaded bus, all switching together.
- **The connector** is connector.victim_map: the data lines on the pins
  nearest SEL and WRITE, with or without RFC 0014's ground pins around
  them.

The victims are measured at the HCT inputs' dies, against the card's
ground: that's what the gate sees.
"""

from dataclasses import replace

import numpy as np

from heron.infra.si import engine, ibis

from . import bus, connector, gb

SEL_LENGTH = 150e-3           # register on the backplane to the slot
WRITE_DRIVER = 0              # the master's slot
T_STOP = 60e-9

# 74HCT132 (Nexperia, all temperatures): VT+ min and VT- max at the
# corners' supplies (4.5, 5.0, 5.5 V); hysteresis at least 0.4 V
VT_PLUS_MIN = {"min": 1.2, "typ": 1.3, "max": 1.4}
VT_MINUS_MAX = {"min": 1.2, "typ": 1.3, "max": 1.4}


def _receivers(p, name, node, corner, gnd, vcc, count=2, z0=None, tpd=None):
    """A card trace from `node` to `count` HCT inputs close together."""
    m, _ = ibis.load("hct")
    rr, lr, cr = ibis.pin_rlc("hct", "soic", model=m.name)
    out = [f"T{p}{name}st {node} {gnd} {p}{name}s {gnd} Z0={z0:.4g} TD={25e-3 * tpd:.4g}"]
    dies = []
    for i in range(count):
        n = f"{p}{name}{i}"
        out += [f"T{p}{name}h{i} {p}{name}s {gnd} {n}h {gnd} Z0={z0:.4g} TD={5e-3 * tpd:.4g}",
                f"C{p}{name}p{i} {n}h {gnd} {cr:.4g}", f"R{p}{name}k{i} {n}h {n}x {rr:.4g}",
                f"L{p}{name}k{i} {n}x {n}d {lr:.4g}"]
        out += ibis.buffer(f"{p}{name}u{i}", "hct", corner, f"{n}d", vcc, gnd)
        dies.append(f"{n}d")
    return out, dies


def netlist(card, corner, falling, guard=True, sel_series=56.0, prefix="x"):
    p = prefix
    bp = bus.Backplane()
    z0, tpd = bp.trace()
    names = [f"D{i}" for i in range(card.lines)]
    maps = (connector.victim_map(guard, aggressors=card.lines), connector.p2_map())
    out, bpn, cdn = gb.card_netlist(card, corner, falling, p, switching=range(card.lines),
                                    extra=("SEL", "WRITE"), maps=maps)
    b = gb.bus_model()
    for i, name in enumerate(names):
        out += gb.loaded_lines(p, i, bpn[name], b)
    # SEL: the backplane's register, held low (asserted), through its
    # series resistor and the radial trace
    src = ["V{0}selku {0}sel_ku 0 0".format(p), "V{0}selkd {0}sel_kd 0 1".format(p)]
    m, _ = ibis.load("abt273")
    rp, lp, cp = ibis.pin_rlc("abt273", "soic", model=m.name)
    out += src + ibis.buffer(f"{p}selu", "abt273", corner, f"{p}seld", "vcc", "0", f"{p}sel_ku", f"{p}sel_kd")
    out += [f"L{p}selk {p}seld {p}selx {lp:.4g}", f"R{p}selk {p}selx {p}selp {rp:.4g}",
            f"C{p}selp {p}selp 0 {cp:.4g}", f"R{p}sels {p}selp {p}selt {sel_series}",
            f"T{p}sel {p}selt 0 {bpn['SEL']} 0 Z0={z0:.4g} TD={SEL_LENGTH * tpd:.4g}"]
    # WRITE: the master holds it high (a read) from slot 0 through 22 ohm,
    # on the loaded bus; the far end is open
    zl, tl = gb._loaded(b)
    left = (gb.SLOT - WRITE_DRIVER) * bp.pitch
    right = bp.end + (bp.slots - 1 - gb.SLOT) * bp.pitch
    m, _ = ibis.load("abt")
    out += [f"V{p}wrku {p}wr_ku 0 1", f"V{p}wrkd {p}wr_kd 0 0"]
    out += ibis.buffer(f"{p}wru", "abt", corner, f"{p}wrd", "vcc", "0", f"{p}wr_ku", f"{p}wr_kd")
    out += [f"R{p}wrs {p}wrd {p}wrt 22", f"T{p}wrl {p}wrt 0 {bpn['WRITE']} 0 Z0={zl:.4g} TD={left * tl:.4g}",
            f"T{p}wrr {bpn['WRITE']} 0 {p}wre 0 Z0={zl:.4g} TD={right * tl:.4g}"]
    # the card's inputs, against its own ground
    sel, sel_dies = _receivers(p, "rs", cdn["SEL"], corner, f"{p}cgnd", f"{p}cvcc", 2, z0, tpd)
    wr, wr_dies = _receivers(p, "rw", cdn["WRITE"], corner, f"{p}cgnd", f"{p}cvcc", 2, z0, tpd)
    out += sel + wr
    probes = {f"sel{i}": f"v({d},{p}cgnd)" for i, d in enumerate(sel_dies)}
    probes.update({f"wr{i}": f"v({d},{p}cgnd)" for i, d in enumerate(wr_dies)})
    probes["card_gnd"] = f"v({p}cgnd)"
    return out, probes


def run(card, corner, falling, guard=True, sel_series=56.0, keep=False):
    lines, probes = netlist(card, corner, falling, guard, sel_series)
    names = list(probes)
    r = engine.run(lines, [probes[k] for k in names], T_STOP,
                   title=f"xt {card.family} {corner} guard {guard}")
    t = r["time"]
    after = t > gb.T_EDGE
    v = {k: r[probes[k]] for k in names}
    sel = max(float(v[k][after].max()) for k in names if k.startswith("sel"))
    wr = min(float(v[k][after].min()) for k in names if k.startswith("wr"))
    res = {"sel_peak": sel, "sel_margin": VT_PLUS_MIN[corner] - sel,
           "write_dip": wr, "write_margin": wr - VT_MINUS_MAX[corner],
           "sel_base": float(np.interp(gb.T_EDGE - 0.5e-9, t, v["sel0"])),
           "write_base": float(np.interp(gb.T_EDGE - 0.5e-9, t, v["wr0"])),
           "card_gnd": (float(v["card_gnd"][after].min()), float(v["card_gnd"][after].max()))}
    if keep:
        res["time"], res["v"] = t, v
    return res


def card(family="hct", package="soic", model="calibrated"):
    """The simple card's data drivers."""
    c = gb.Card.model(model, family=family, package=package)
    return replace(c, lines=16)
