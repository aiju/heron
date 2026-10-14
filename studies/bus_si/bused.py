"""Bused lines of the revised bus (RFC 0014's 2026-10-14 draft), with the
cards and the backplane's own logic as they now are.

bus.py's line_netlist is report 0013's model, kept as it was so its
presets stay comparable. This one generalises it:

- **Cards per slot:** each slot holds a card (its stub, transceiver family
  and package, series resistor and any extra load) or is empty, in which
  case only the backplane's half of the connector is there.
- **Devices on the backplane:** the backplane's logic drives DPH, RDY,
  BERR and W32, and takes some lines in through a buffer, at a point along
  the bus with a short trace to it and no connector.
- **The driver** is a card or a backplane device.

    term ─ T ─┬─ T ─┬──── T ────┬─ T ─ term
              L     │ (empty)   dev            connector or device trace
              T     ┴           │
             pkg              pkg
             die              die
"""

from dataclasses import dataclass, field, replace

import numpy as np

from heron.infra.si import engine, ibis

from . import bus

T_RISE, T_FALL, T_STOP = bus.T_RISE, bus.T_FALL, bus.T_STOP


@dataclass(frozen=True)
class Card:
    """What a card puts on one bused line."""
    family: str = "abt"
    package: str = "soic"
    stub: float = 25e-3          # connector to the transceiver pin
    series: float = 22.0         # at the transceiver pin, ohm (0: none)
    extra_c: float = 0.0         # more inputs on the net, at the pin (F)


@dataclass(frozen=True)
class Device:
    """A part on the backplane itself, `x` along the bus from slot 0 (m;
    negative is beyond slot 0), at the end of a `stub` of trace."""
    x: float
    family: str = "abt"
    package: str = "soic"
    stub: float = 15e-3
    series: float = 22.0
    extra_c: float = 0.0


@dataclass(frozen=True)
class Bus:
    bp: bus.Backplane = field(default_factory=lambda: bus.Backplane(package="soic"))
    cards: tuple = ()            # one Card or None per slot
    devices: tuple = ()
    term: bus.Term = field(default_factory=lambda: bus.Term("none"))
    empty_c: float = None        # what an empty slot leaves (F); None: half the contact

    @staticmethod
    def full(slots=16, card=Card(), **kw):
        bp = kw.pop("bp", bus.Backplane(slots=slots, package="soic"))
        return Bus(bp=bp, cards=tuple([card] * bp.slots), **kw)

    def with_cards(self, populated, card=Card()):
        return replace(self, cards=tuple(card if k in populated else None for k in range(self.bp.slots)))


def card_c(card, bp=None):
    """Capacitance a card puts on the line on its side of the connector:
    stub, package pin, die and extra (F, typical corner)."""
    bp = bp or bus.Backplane()
    z0, tpd = bp.trace()
    m, _ = ibis.load(card.family, ibis.input_model(card.family))
    _, _, cpin = ibis.pin_rlc(card.family, card.package, model=m.name)
    return card.stub * tpd / z0 + cpin + m.ccomp("typ") + card.extra_c


def extra_for(total, card, bp=None):
    """The extra capacitance that brings a card's load to `total` (F)."""
    return max(0.0, total - card_c(replace(card, extra_c=0.0), bp))


def _part(p, name, family, package, corner, node, g, series, extra_c, z0, tpd, stub,
          drive=None):
    """A stub of trace from `node`, series resistor, package pin and die."""
    model = None if drive else ibis.input_model(family)
    m, _ = ibis.load(family, model)
    rp, lp, cp = ibis.pin_rlc(family, package, model=m.name)
    out = [f"T{p}t{name} {node} {g} {p}s{name} {g} Z0={z0:.4g} TD={stub * tpd:.4g}",
           f"R{p}s{name} {p}s{name} {p}p{name} {series or 1e-3}",
           f"C{p}p{name} {p}p{name} {g} {cp + extra_c:.4g}",
           f"R{p}k{name} {p}p{name} {p}x{name} {rp:.4g}",
           f"L{p}k{name} {p}x{name} {p}d{name} {lp:.4g}"]
    if drive:
        ku, kd = drive
        out += ibis.buffer(f"{p}u{name}", family, corner, f"{p}d{name}", "vcc", g, ku, kd)
    else:
        out += ibis.buffer(f"{p}u{name}", family, corner, f"{p}d{name}", "vcc", g, model=model)
    return out


def netlist(b, driver, corner, edges, initial=0, prefix="", pullup=None, external=(), backplane=True,
            release=None):
    """Netlist lines for one bused line. `driver` is ('slot', k) or
    ('dev', i), or None for a line nobody drives; `edges` its switching
    times. `pullup` (ohm) adds a pull-up to Vcc at the slot-0 end. Slots
    in `external` get nothing at their backplane node (<prefix>bps<k>):
    the caller attaches its own card there. `backplane=False` leaves out
    the backplane's segments, for a caller that couples them. A driver with
    no edges holds `initial`, and with `release` (s) lets go of the line
    then. Returns (lines, {receiver: die node}), receivers named 's<k>' and
    'd<i>'."""
    bp = b.bp
    z0, tpd = bp.trace()
    p = prefix
    n = bp.slots
    # stations along the bus: slots and devices, by position
    st = [(k * bp.pitch, "s", k) for k in range(n)] + [(d.x, "d", i) for i, d in enumerate(b.devices)]
    st.sort()
    x0 = min(-bp.end, st[0][0] - 1e-3)
    x1 = max((n - 1) * bp.pitch + bp.end, st[-1][0] + 1e-3)
    out = []
    nodes = [f"{p}bpL"] + [f"{p}bp{kind}{i}" for _, kind, i in st] + [f"{p}bpR"]
    xs = [x0] + [x for x, _, _ in st] + [x1]
    for j in range(len(xs) - 1 if backplane else 0):
        length = xs[j + 1] - xs[j]
        if length < 1e-6:
            out.append(f"R{p}j{j} {nodes[j]} {nodes[j + 1]} 1e-3")
        else:
            out.append(f"T{p}b{j} {nodes[j]} 0 {nodes[j + 1]} 0 Z0={z0:.4g} TD={length * tpd:.4g}")
    out += bus._termination(b.term, f"{p}bpL", f"{p}L", None)
    out += bus._termination(b.term, f"{p}bpR", f"{p}R", None)
    if pullup:
        out.append(f"R{p}pu {p}bpL vcc {pullup}")
    drive = None
    if driver is not None:
        dkind, didx = driver
        fam = b.cards[didx].family if dkind == "slot" else b.devices[didx].family
        if edges:
            src, drive = ibis.coefficient_sources(f"{p}drv", fam, corner, edges, initial=initial)
            out += src
        elif release is not None:
            # held, then three-state over a nanosecond
            ku, kd = initial, 1 - initial
            out += [f"V{p}drvku {p}drv_ku 0 PWL(0 {ku} {release:.4g} {ku} {release + 1e-9:.4g} 0)",
                    f"V{p}drvkd {p}drv_kd 0 PWL(0 {kd} {release:.4g} {kd} {release + 1e-9:.4g} 0)"]
            drive = (f"{p}drv_ku", f"{p}drv_kd")
        else:
            out += [f"V{p}drvku {p}drv_ku 0 {initial}", f"V{p}drvkd {p}drv_kd 0 {1 - initial}"]
            drive = (f"{p}drv_ku", f"{p}drv_kd")
    dies = {}
    for k in range(n):
        node = f"{p}bps{k}"
        if k in external:
            continue
        c = b.cards[k] if k < len(b.cards) else None
        if c is None:
            out.append(f"C{p}e{k} {node} 0 {(b.empty_c if b.empty_c is not None else bp.conn_c / 2):.4g}")
            continue
        out += [f"C{p}b{k} {node} 0 {bp.conn_c / 2:.4g}",
                f"L{p}c{k} {node} {p}c{k} {bp.conn_l:.4g}",
                f"C{p}c{k} {p}c{k} 0 {bp.conn_c / 2:.4g}"]
        dr = drive if driver == ("slot", k) else None
        out += _part(p, f"s{k}", c.family, c.package, corner, f"{p}c{k}", "0", c.series, c.extra_c,
                     z0, tpd, c.stub, dr)
        dies[f"s{k}"] = f"{p}ds{k}"
    for i, d in enumerate(b.devices):
        dr = drive if driver == ("dev", i) else None
        out += _part(p, f"d{i}", d.family, d.package, corner, f"{p}bpd{i}", "0", d.series, d.extra_c,
                     z0, tpd, d.stub, dr)
        dies[f"d{i}"] = f"{p}dd{i}"
    return out, dies


def _first(t, v, t0, t1, rising, vil, vih):
    """When v first leaves its old valid region after t0: above vil on a
    rising edge, below vih on a falling one. What hold time depends on."""
    sel = (t >= t0) & (t < t1)
    tt, vv = t[sel], v[sel]
    idx = np.flatnonzero(vv > vil) if rising else np.flatnonzero(vv < vih)
    if len(idx) == 0 or idx[0] == 0:
        return None
    i = idx[0]
    thr = vil if rising else vih
    return tt[i - 1] + (thr - vv[i - 1]) * (tt[i] - tt[i - 1]) / (vv[i] - vv[i - 1]) - t0


_refs = {}


def ref_delay(family, corner, package="soic"):
    key = (family, corner, package)
    if key not in _refs:
        _refs[key] = bus.ref_delay(family, corner, package)
    return _refs[key]


def run(b, driver, corner, keep=False):
    """One rising and one falling edge from `driver`. Per receiver: settle
    times and first changes (s, from the start of the driver's edge), the
    delay the bus adds (settle less the datasheet reference point), peaks,
    levels and extra threshold crossings."""
    fam = b.cards[driver[1]].family if driver[0] == "slot" else b.devices[driver[1]].family
    pkg = b.cards[driver[1]].package if driver[0] == "slot" else b.devices[driver[1]].package
    m, _ = ibis.load(fam)
    lines, dies = netlist(b, driver, corner, [T_RISE, T_FALL])
    lines = [f"Vcc vcc 0 {m.vcc(corner)}"] + lines
    probes = [f"v({d})" for d in dies.values()]
    r = engine.run(lines, probes, T_STOP, title=f"bused {fam} {corner} driver {driver}")
    t = r["time"]
    ref_r, ref_f = ref_delay(fam, corner, pkg)
    res = {"rx": {}, "ref": (ref_r, ref_f)}
    if keep:
        res["time"] = t
        res["v"] = {}
    for name, d in dies.items():
        if (driver[0] == "slot" and name == f"s{driver[1]}") or (driver[0] == "dev" and name == f"d{driver[1]}"):
            continue
        v = r[f"v({d})"]
        if keep:
            res["v"][name] = v
        rx = b.cards[int(name[1:])] if name[0] == "s" else b.devices[int(name[1:])]
        vil, vih = ibis.thresholds(rx.family)
        hi = (t > T_RISE) & (t < T_FALL)
        lo = t > T_FALL
        rise = bus.settle(t, v, T_RISE, T_FALL, True, vil, vih)
        fall = bus.settle(t, v, T_FALL, T_STOP, False, vil, vih)
        res["rx"][name] = {
            "rise": rise, "fall": fall,
            "add_rise": None if rise is None else rise - ref_r,
            "add_fall": None if fall is None else fall - ref_f,
            "first_rise": _first(t, v, T_RISE, T_FALL, True, vil, vih),
            "first_fall": _first(t, v, T_FALL, T_STOP, False, vil, vih),
            "vmax": float(v[hi].max()), "vmin": float(v[lo].min()),
            "voh": float(np.interp(T_FALL - 1e-9, t, v)), "vol": float(np.interp(T_STOP - 1e-9, t, v)),
            "extra": max(bus._crossings(t, v, T_RISE, T_FALL, vih) - 1, 0)
            + max(bus._crossings(t, v, T_FALL, T_STOP, vil) - 1, 0),
        }
    return res


def worst(res):
    """Worst case over the receivers of one run."""
    rx = list(res["rx"].values())
    ok = [x for x in rx if x["rise"] is not None and x["fall"] is not None]

    def mx(f):
        return max((x[f] for x in ok), default=None)

    def mn(f):
        vals = [x[f] for x in rx if x[f] is not None]
        return min(vals, default=None)

    return {"settle_rise": mx("rise"), "settle_fall": mx("fall"), "add_rise": mx("add_rise"),
            "add_fall": mx("add_fall"), "first_rise": mn("first_rise"), "first_fall": mn("first_fall"),
            "vmax": max(x["vmax"] for x in rx), "vmin": min(x["vmin"] for x in rx),
            "extra": max(x["extra"] for x in rx), "unsettled": len(rx) - len(ok)}
