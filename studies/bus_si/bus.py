"""Backplane models for the system bus.

One bus line runs along the backplane past every slot. At each slot it
leaves through a DIN 41612 contact onto the card, along a stub to the
card's transceiver: package pin, then the IBIS buffer at the die. Each end
of the backplane may carry a terminator. One card drives; every other
card's transceiver is a receiver (its outputs in three-state).

    term ─ T ─┬─ T ─┬─ T ─ ... ─┬─ T ─ term        backplane, 20.32 mm pitch
              L     L           L                  connector
              │     │           │
              T     T           T                  card stub
              │     │           │
             pkg   pkg         pkg
              │     │           │
             die   die         die                 IBIS model
"""

import json
import os
from dataclasses import dataclass

import numpy as np

from heron.infra.si import engine, fields, ibis

CACHE = os.path.join(ibis.BUILD, "..", "si-fields.json")

# 4-layer 1.6 mm stack-up: 35 µm outer copper on 0.21 mm of 7628 prepreg
TRACE_W = 0.2e-3
TRACE_T = 35e-6
PREPREG_H = 0.21e-3
ER = 4.4
PITCH_TRACES = 1.27e-3          # neighbouring traces where they pass between pins


def trace_params():
    """Field-solved Z0, delay and coupling of the standard trace (cached)."""
    key = f"{TRACE_W}/{TRACE_T}/{PREPREG_H}/{ER}/{PITCH_TRACES}"
    try:
        with open(CACHE) as f:
            c = json.load(f)
        if c.get("key") == key:
            return c
    except (OSError, ValueError):
        pass
    z0, tpd = fields.single_line(TRACE_W, TRACE_T, PREPREG_H, ER)
    L, C = fields.coupled_lines(TRACE_W, TRACE_T, PREPREG_H, PITCH_TRACES, 3, ER)
    zh, th = fields.hammerstad(TRACE_W, TRACE_T, PREPREG_H, ER)
    c = {"key": key, "z0": z0, "tpd": tpd, "L": L.tolist(), "C": C.tolist(),
         "hammerstad_z0": zh, "hammerstad_tpd": th}
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w") as f:
        json.dump(c, f, indent=1)
    return c


@dataclass(frozen=True)
class Backplane:
    slots: int = 16
    pitch: float = 20.32e-3     # 4HP
    end: float = 10e-3          # end slot to terminator
    stub: float = 25e-3         # connector to transceiver on the card
    conn_l: float = 12e-9       # DIN 41612 contact, estimated from geometry
    conn_c: float = 2e-12       # contact plus the two plated holes
    package: str = "dip"
    z0: float = None            # trace impedance and delay; None = field-solved
    tpd: float = None

    def trace(self):
        if self.z0 is None:
            p = trace_params()
            return p["z0"], p["tpd"]
        return self.z0, self.tpd

    def slot_capacitance(self, family):
        """Lumped capacitance a card adds at its slot (F)."""
        z0, tpd = self.trace()
        m, _ = ibis.load(family)
        _, _, cpin = ibis.pin_rlc(family, self.package, model=m.name)
        return self.conn_c + self.stub * tpd / z0 + cpin + m.ccomp("typ")

    def loaded(self, family):
        """Loaded impedance (ohm) and delay (s/m) of the backplane trace."""
        z0, tpd = self.trace()
        cl = tpd / z0
        cd = self.slot_capacitance(family) / self.pitch
        return z0 / np.sqrt(1 + cd / cl), tpd * np.sqrt(1 + cd / cl)


@dataclass(frozen=True)
class Term:
    """Termination at both ends of the backplane, plus an optional series
    resistor at every card's transceiver."""
    name: str
    pullup: float = None        # Thevenin: resistor to Vcc
    pulldown: float = None      # and to ground
    r: float = None             # RC: series R ...
    c: float = None             # ... and C to ground
    series: float = None        # at each card
    diodes: bool = False        # Schottky clamps to Vcc and ground at the ends

    def describe(self):
        parts = []
        if self.pullup:
            parts.append(f"{self.pullup:.0f} Ω to +5 V and {self.pulldown:.0f} Ω to ground at each end")
        if self.r:
            parts.append(f"{self.r:.0f} Ω + {self.c * 1e12:.0f} pF to ground at each end")
        if self.diodes:
            parts.append("Schottky clamps to +5 V and ground at each end")
        if self.series:
            parts.append(f"{self.series:.0f} Ω in series at every card's transceiver")
        return "; ".join(parts) or "nothing"


TERMS = {
    "none": Term("none"),
    "vme": Term("vme", pullup=330, pulldown=470),
    "thev": Term("thev", pullup=220, pulldown=330),
    "rc": Term("rc", r=33, c=220e-12),
    "diode": Term("diode", diodes=True),
    "series": Term("series", series=22),
    "series+rc": Term("series+rc", series=22, r=33, c=220e-12),
}

SCHOTTKY = ".model dsch D(IS=1e-7 N=1.05 RS=1.5 CJO=10p TT=0)"


def _termination(term, node, tag, vcc):
    out = []
    if term.pullup:
        out += [f"Rtu{tag} {node} vcc {term.pullup}", f"Rtd{tag} {node} 0 {term.pulldown}"]
    if term.r:
        out += [f"Rtr{tag} {node} tc{tag} {term.r}", f"Ctc{tag} tc{tag} 0 {term.c:.4g}"]
    if term.diodes:
        out += [f"Dth{tag} {node} vcc dsch", f"Dtl{tag} 0 {node} dsch"]
    return out


def line_netlist(bp, term, family, corner, driver, edges, initial=0, recv=None, prefix="",
                 rails=None, backplane=True):
    """Netlist lines for one bus line. `driver` is the driving slot (or None
    for an undriven line), `edges` its switching times (none: held at
    `initial`). Receivers are of family `recv` (default: the driver's).
    Node names carry `prefix`, so several lines can share one netlist.
    `rails` maps a slot to its card's (vcc, ground) nodes, for ground
    bounce; others use the ideal rails. `backplane=False` leaves out the
    backplane segments, for a caller that couples them. Returns (lines,
    die nodes by slot)."""
    recv = recv or family
    rails = rails or {}
    z0, tpd = bp.trace()
    p = prefix
    out = []
    if term.diodes:
        out.append(SCHOTTKY)
    n = bp.slots
    if backplane:
        out.append(f"T{p}e0 {p}bpL 0 {p}bp0 0 Z0={z0:.4g} TD={bp.end * tpd:.4g}")
        for k in range(n - 1):
            out.append(f"T{p}s{k} {p}bp{k} 0 {p}bp{k + 1} 0 Z0={z0:.4g} TD={bp.pitch * tpd:.4g}")
        out.append(f"T{p}e1 {p}bp{n - 1} 0 {p}bpR 0 Z0={z0:.4g} TD={bp.end * tpd:.4g}")
    out += _termination(term, f"{p}bpL", f"{p}L", None)
    out += _termination(term, f"{p}bpR", f"{p}R", None)
    dies = {}
    for k in range(n):
        fam = family if k == driver else recv
        m, _ = ibis.load(fam)
        vcc, g = rails.get(k, ("vcc", "0"))
        rp, lp, cp = ibis.pin_rlc(fam, bp.package, model=m.name)
        out += [
            f"C{p}b{k} {p}bp{k} 0 {bp.conn_c / 2:.4g}",
            f"L{p}c{k} {p}bp{k} {p}c{k} {bp.conn_l:.4g}",
            f"C{p}c{k} {p}c{k} {g} {bp.conn_c / 2:.4g}",
            f"T{p}t{k} {p}c{k} {g} {p}s{k} {g} Z0={z0:.4g} TD={bp.stub * tpd:.4g}",
            f"R{p}s{k} {p}s{k} {p}p{k} {term.series or 1e-3}",
            f"C{p}p{k} {p}p{k} {g} {cp:.4g}",
            f"R{p}k{k} {p}p{k} {p}x{k} {rp:.4g}",
            f"L{p}k{k} {p}x{k} {p}d{k} {lp:.4g}",
        ]
        if k == driver:
            die_v, die_g = rails.get(("die", k), (vcc, g))
            if edges:
                src, (ku, kd) = ibis.coefficient_sources(f"{p}drv", fam, corner, edges, initial=initial)
                out += src
            else:
                out += [f"V{p}drvku {p}drv_ku 0 {initial}", f"V{p}drvkd {p}drv_kd 0 {1 - initial}"]
                ku, kd = f"{p}drv_ku", f"{p}drv_kd"
            out += ibis.buffer(f"{p}u{k}", fam, corner, f"{p}d{k}", die_v, die_g, ku, kd)
        else:
            out += ibis.buffer(f"{p}u{k}", fam, corner, f"{p}d{k}", vcc, g)
        dies[k] = f"{p}d{k}"
    return out, dies


def equivalent_line_netlist(bp, term, family, corner, driver, edges, initial=0, prefix="",
                            rails=None):
    """A driven line with the receivers smeared out: the driving card in
    full, the backplane as uniform lines of the loaded impedance and delay
    to each end. Cheap, for ground bounce, where only the driver's current
    matters. Returns (lines, driver die node)."""
    rails = rails or {}
    z0, tpd = bp.trace()
    zl, tl = bp.loaded(family)
    p = prefix
    k = driver
    vcc, g = rails.get(k, ("vcc", "0"))
    die_v, die_g = rails.get(("die", k), (vcc, g))
    m, _ = ibis.load(family)
    rp, lp, cp = ibis.pin_rlc(family, bp.package, model=m.name)
    left = bp.end + k * bp.pitch
    right = bp.end + (bp.slots - 1 - k) * bp.pitch
    out = []
    if term.diodes:
        out.append(SCHOTTKY)
    out += [
        f"T{p}l {p}bp 0 {p}bpL 0 Z0={zl:.4g} TD={left * tl:.4g}",
        f"T{p}r {p}bp 0 {p}bpR 0 Z0={zl:.4g} TD={right * tl:.4g}",
        f"C{p}b {p}bp 0 {bp.conn_c / 2:.4g}",
        f"L{p}c {p}bp {p}c {bp.conn_l:.4g}",
        f"C{p}c {p}c {g} {bp.conn_c / 2:.4g}",
        f"T{p}t {p}c {g} {p}s {g} Z0={z0:.4g} TD={bp.stub * tpd:.4g}",
        f"R{p}s {p}s {p}p {term.series or 1e-3}",
        f"C{p}p {p}p {g} {cp:.4g}",
        f"R{p}k {p}p {p}x {rp:.4g}",
        f"L{p}k {p}x {p}d {lp:.4g}",
    ]
    out += _termination(term, f"{p}bpL", f"{p}L", None)
    out += _termination(term, f"{p}bpR", f"{p}R", None)
    src, (ku, kd) = ibis.coefficient_sources(f"{p}drv", family, corner, edges, initial=initial)
    out += src
    out += ibis.buffer(f"{p}u", family, corner, f"{p}d", die_v, die_g, ku, kd)
    return out, f"{p}d"


def clock_netlist(bp, family, corner, recv, rseries, lengths, edges, prefix="k"):
    """A clock buffer on the backplane driving each slot over its own
    trace: buffer die, package, series resistor, trace of the given length,
    connector, card stub, one receiver. Returns (lines, receiver dies)."""
    z0, tpd = bp.trace()
    p = prefix
    out = []
    src, (ku, kd) = ibis.coefficient_sources(f"{p}drv", family, corner, edges)
    out += src
    m, _ = ibis.load(family)
    rp, lp, cp = ibis.pin_rlc(family, bp.package, model=m.name)
    mr, _ = ibis.load(recv)
    rr, lr, cr = ibis.pin_rlc(recv, bp.package, model=mr.name)
    dies = {}
    for k, length in enumerate(lengths):
        out += ibis.buffer(f"{p}b{k}", family, corner, f"{p}o{k}", "vcc", "0", ku, kd)
        out += [
            f"L{p}o{k} {p}o{k} {p}ox{k} {lp:.4g}",
            f"R{p}o{k} {p}ox{k} {p}op{k} {rp:.4g}",
            f"C{p}o{k} {p}op{k} 0 {cp:.4g}",
            f"R{p}r{k} {p}op{k} {p}tr{k} {rseries}",
            f"T{p}l{k} {p}tr{k} 0 {p}bp{k} 0 Z0={z0:.4g} TD={length * tpd:.4g}",
            f"C{p}b{k} {p}bp{k} 0 {bp.conn_c / 2:.4g}",
            f"L{p}c{k} {p}bp{k} {p}c{k} {bp.conn_l:.4g}",
            f"C{p}c{k} {p}c{k} 0 {bp.conn_c / 2:.4g}",
            f"T{p}t{k} {p}c{k} 0 {p}s{k} 0 Z0={z0:.4g} TD={bp.stub * tpd:.4g}",
            f"C{p}p{k} {p}s{k} 0 {cr:.4g}",
            f"R{p}k{k} {p}s{k} {p}x{k} {rr:.4g}",
            f"L{p}k{k} {p}x{k} {p}d{k} {lr:.4g}",
        ]
        out += ibis.buffer(f"{p}u{k}", recv, corner, f"{p}d{k}", "vcc", "0")
        dies[k] = f"{p}d{k}"
    return out, dies


# -- measurements -------------------------------------------------------------

def settle(t, v, t0, t1, rising, vil, vih):
    """Time after t0 at which v last crossed into its valid region in
    [t0, t1): above vih for a rising edge, below vil for a falling one.
    None if it never got there."""
    sel = (t >= t0) & (t < t1)
    tt, vv = t[sel], v[sel]
    bad = vv < vih if rising else vv > vil
    if bad[-1]:
        return None
    idx = np.flatnonzero(bad)
    if len(idx) == 0:
        return 0.0
    i = idx[-1]
    # interpolate the crossing
    thr = vih if rising else vil
    ta, tb, va, vb = tt[i], tt[i + 1], vv[i], vv[i + 1]
    tc = ta + (thr - va) * (tb - ta) / (vb - va) if vb != va else tb
    return tc - t0


def ref_delay(family, corner, package="dip"):
    """Time from the start of the IBIS edge to Vmeas into the datasheet
    test load, at the pin: (rising, falling). Bus delays are measured from
    this, so they add to the datasheet propagation delay."""
    rref, vref, cref, vmeas = ibis.test_load(family)
    m, _ = ibis.load(family)
    rp, lp, cp = ibis.pin_rlc(family, package, model=m.name)
    t0, t1 = 2e-9, 60e-9
    src, (ku, kd) = ibis.coefficient_sources("drv", family, corner, [t0, t1])
    lines = [f"Vcc vcc 0 {m.vcc(corner)}"] + src
    lines += ibis.buffer("u", family, corner, "d", "vcc", "0", ku, kd)
    lines += [f"Lk d x {lp:.4g}", f"Rk x p {rp:.4g}", f"Cp p 0 {cp:.4g}",
              f"Cl p 0 {cref:.4g}"]
    if rref:
        lines += [f"Rl p vr {rref}", f"Vr vr 0 {vref}"]
    r = engine.run(lines, ["v(p)"], 120e-9, title=f"ref {family} {corner}")
    t, v = r["time"], r["v(p)"]
    rise = settle(t, v, t0, t1, True, vmeas, vmeas)
    fall = settle(t, v, t1, 120e-9, False, vmeas, vmeas)
    return rise, fall


T_RISE = 10e-9
T_FALL = 90e-9
T_STOP = 170e-9


def _crossings(t, v, t0, t1, thr):
    sel = (t >= t0) & (t < t1)
    s = np.sign(v[sel] - thr)
    s = s[s != 0]
    return int(np.count_nonzero(s[1:] != s[:-1]))


def run_line(bp, term, family, corner, driver, recv=None, keep=False):
    """Simulate one rising and one falling edge from `driver`. Returns
    per-receiver measurements, and the waveforms if `keep`."""
    m, _ = ibis.load(family)
    vcc = m.vcc(corner)
    lines, dies = line_netlist(bp, term, family, corner, driver, [T_RISE, T_FALL], recv=recv)
    lines = [f"Vcc vcc 0 {vcc}"] + lines
    probes = [f"v({d})" for d in dies.values()]
    r = engine.run(lines, probes, T_STOP,
                  title=f"line {bp.slots} slots {family} {term.name} {corner} slot {driver}")
    t = r["time"]
    vil, vih = ibis.thresholds(recv or family)
    res = {"slots": {}}
    if keep:
        res["time"] = t
        res["v"] = {k: r[f"v({d})"] for k, d in dies.items()}
    for k, d in dies.items():
        v = r[f"v({d})"]
        hi = (t > T_RISE) & (t < T_FALL)
        lo = t > T_FALL
        res["slots"][k] = {
            "rise": settle(t, v, T_RISE, T_FALL, True, vil, vih),
            "fall": settle(t, v, T_FALL, T_STOP, False, vil, vih),
            "vmax": float(v[hi].max()), "vmin": float(v[lo].min()),
            "voh": float(np.interp(T_FALL - 1e-9, t, v)),
            "vol": float(np.interp(T_STOP - 1e-9, t, v)),
            # threshold crossings beyond the one an edge needs: ringing
            # back through the threshold region (non-monotonic edge)
            "extra": max(_crossings(t, v, T_RISE, T_FALL, vih) - 1, 0)
                     + max(_crossings(t, v, T_FALL, T_STOP, vil) - 1, 0),
        }
    return res


def worst(results, driver_exclude=True):
    """Worst-case numbers over all (driver, receiver) pairs."""
    w = {"rise": 0.0, "fall": 0.0, "vmax": -9.0, "vmin": 9.0, "voh": 9.0, "vol": -9.0,
         "extra": 0, "fail": False}
    for drv, res in results.items():
        for k, s in res["slots"].items():
            if driver_exclude and k == drv:
                continue
            for e in ("rise", "fall"):
                if s[e] is None:
                    w["fail"] = True
                else:
                    w[e] = max(w[e], s[e])
            w["vmax"] = max(w["vmax"], s["vmax"])
            w["vmin"] = min(w["vmin"], s["vmin"])
            w["voh"] = min(w["voh"], s["voh"])
            w["vol"] = max(w["vol"], s["vol"])
            w["extra"] = max(w["extra"], s["extra"])
    return w


# -- clock --------------------------------------------------------------------

def edge_metrics(t, v, t0, t1, rising, vil=0.8, vih=2.0, vmeas=1.5):
    """Crossing time of vmeas, transition time vil->vih, threshold-region
    re-crossings and over/undershoot of one edge in [t0, t1)."""
    sel = (t >= t0) & (t < t1)
    tt, vv = t[sel], v[sel]
    def first(thr, up):
        idx = np.flatnonzero(vv >= thr) if up else np.flatnonzero(vv <= thr)
        if len(idx) == 0 or idx[0] == 0:
            return None
        i = idx[0]
        return tt[i - 1] + (thr - vv[i - 1]) * (tt[i] - tt[i - 1]) / (vv[i] - vv[i - 1])
    a, b = (vil, vih) if rising else (vih, vil)
    ta, tm, tb = first(a, rising), first(vmeas, rising), first(b, rising)
    extra = max(_crossings(t, v, t0, t1, vil) - 1, 0) + max(_crossings(t, v, t0, t1, vih) - 1, 0)
    return {"t50": None if tm is None else tm - t0,
            "tr": None if (ta is None or tb is None) else tb - ta,
            "extra": extra, "vmax": float(vv.max()), "vmin": float(vv.min())}


def clock_lengths(bp, matched, offset=30e-3):
    """Trace lengths from a clock buffer in the middle of the backplane,
    `offset` below the connector row, to each slot."""
    mid = (bp.slots - 1) / 2 * bp.pitch
    raw = [abs(k * bp.pitch - mid) + offset for k in range(bp.slots)]
    return [max(raw)] * bp.slots if matched else raw


def run_clock(bp, family, corner, recv, rseries, matched=True):
    m, _ = ibis.load(family)
    lines, dies = clock_netlist(bp, family, corner, recv, rseries, clock_lengths(bp, matched),
                                [T_RISE, T_FALL])
    lines = [f"Vcc vcc 0 {m.vcc(corner)}"] + lines
    r = engine.run(lines, [f"v({d})" for d in dies.values()], T_STOP,
                  title=f"clock {family} {corner} R={rseries}")
    t = r["time"]
    out = {"time": t, "v": {}, "rise": {}, "fall": {}}
    for k, d in dies.items():
        v = r[f"v({d})"]
        out["v"][k] = v
        out["rise"][k] = edge_metrics(t, v, T_RISE, T_FALL, True)
        out["fall"][k] = edge_metrics(t, v, T_FALL, T_STOP, False)
    return out
