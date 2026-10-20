"""Chips' timing as data, for the static timing engine (infra/sta, RFC 0048).

A chip type (chips.T) describes its timing with these:

    outputs={pin: Out(function, arcs, enable=, on=, off=)}
    regs={pin: Reg(clock, next, delay, clear=, preset=, enable=, ...)}
    timing=[Setup(...), Width(...), Period(...), Strobe(...)]
    sensitive=[pins]        glitch-sensitive inputs besides clocks and strobes
    asynchronous=[pins]     outputs on a clock of the chip's own (a timer's OUT)
    joins=[(pin, pin)]      pins that are one net to timing (series resistors)

A function is an equation over the chip's pins, in the notation gals.md
prints: `/` not, `·` or `&` and, `+` or `|` or, parentheses, 0 and 1. In a
register's next state the register's own pin is its present state. None
is an opaque function: the output changes whenever an input does, to a
value not known (an ALU's F, a memory's data).

Arcs are {pins: delay}: pins space-separated, or a range "A0-A14"; the
delay a name in the part's timing data, a number of picoseconds, or
Arc(name, min=, when=): its minimum from another name (or a number), and
the condition (an equation) under which the arc applies. A list of
delays gives the same pins several arcs, each under its condition.

describe(inst, variant) turns an instance's description, or a 22V10's
equations (gal.py), into the engine's form: pins by index, sums of
products, and every delay as [min, typ, max] in ps (min None where the
data has none: the engine takes a fraction of typ, RFC 0048 5).
"""

import re


class Arc:
    def __init__(self, name, min=None, when=None):
        self.name, self.min, self.when = name, min, when


class Out:
    def __init__(self, fn, arcs, enable=None, on=None, off=None):
        self.fn, self.arcs = fn, dict(arcs)
        self.enable, self.on, self.off = enable, dict(on or {}), dict(off or {})


class Reg:
    """A register's output: loads `next` at `clock`'s edge ('rise' or
    'fall'), `delay` later; clear and preset are equations that force it
    to 0 and 1 (clear first) through their arcs; enable, on and off as an
    Out's; `feedback` the delay of its state into the chip's own functions
    (a 22V10's tCF), else they see it at once."""

    def __init__(self, clock, next, delay, edge="rise", clear=None, clear_arcs=None,
                 preset=None, preset_arcs=None, enable=None, on=None, off=None,
                 feedback=None):
        self.clock, self.next, self.delay, self.edge = clock, next, delay, edge
        self.clear, self.clear_arcs = clear, dict(clear_arcs or {})
        self.preset, self.preset_arcs = preset, dict(preset_arcs or {})
        self.enable, self.on, self.off = enable, dict(on or {}), dict(off or {})
        self.feedback = feedback


class Setup:
    """The pins' setup and hold to the clock pin's edge, while the next
    state of a register on that clock depends on them."""

    def __init__(self, pins, clock, setup, hold, edge="rise"):
        self.pins, self.clock, self.setup, self.hold, self.edge = pins, clock, setup, hold, edge


class Width:
    """The pin's pulses at `level` (1 high, 0 low) last at least `name`."""

    def __init__(self, pin, level, name):
        self.pin, self.level, self.name = pin, level, name


class Period:
    """The pin's rising edges at least `name` apart (a frequency in MHz if
    the name ends in MHz)."""

    def __init__(self, pin, name):
        self.pin, self.name = pin, name


class Strobe:
    """While `active` (an equation) is true: `stable` {pins: (before the
    start, before the end, after the end)} and `data` {pins: (setup before
    the end, hold after it)}, None for no requirement; at least `width`
    long."""

    def __init__(self, active, stable=None, data=None, width=None):
        self.active, self.stable, self.data, self.width = active, dict(stable or {}), \
            dict(data or {}), width


# ---- equations ------------------------------------------------------------------

_TOKEN = re.compile(r"\s*(?:([A-Za-z0-9_]+)|(.))")


def _tokens(text):
    out, pos = [], 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
        if m.group(1):
            out.append(("name", m.group(1)))
        elif m.group(2).strip():
            out.append(("op", {"&": "·", "|": "+"}.get(m.group(2), m.group(2))))
    return out


def _and(a, b):
    out = []
    for s in a:
        for t in b:
            if all(s.get(k, v) == v for k, v in t.items()):
                out.append({**s, **t})
    return _tidy(out)


def _tidy(f):
    out = []
    for t in f:
        if t not in out:
            out.append(t)
    return [t for t in out
            if not any(o is not t and len(o) < len(t) and all(t.get(k) == v for k, v in o.items())
                       for o in out)]


def _not(f):
    out = [{}]
    for t in f:
        out = _and(out, [{k: 1 - v} for k, v in t.items()])
    return out


def parse(text, pins=None):
    """An equation as a sum of products: [{pin: value}]; [] is 0, [{}] 1.
    pins, if given, are the names it may use."""
    toks = _tokens(text)
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else (None, None)

    def take(kind=None, val=None):
        t = peek()
        if t[0] is None or (kind and t[0] != kind) or (val and t[1] != val):
            raise ValueError(f"equation {text!r}: expected {val or kind} at token {pos[0]}")
        pos[0] += 1
        return t

    def atom():
        k, v = peek()
        if (k, v) == ("op", "/"):
            take()
            return _not(atom())
        if (k, v) == ("op", "("):
            take()
            f = expr()
            take("op", ")")
            return f
        k, v = take("name")
        if v in ("0", "1"):
            return [{}] if v == "1" else []
        if pins is not None and v not in pins:
            raise ValueError(f"equation {text!r}: no pin {v}")
        return [{v: 1}]

    def term():
        f = atom()
        while peek() == ("op", "·"):
            take()
            f = _and(f, atom())
        return f

    def expr():
        f = term()
        while peek() == ("op", "+"):
            take()
            f = _tidy(f + term())
        return f

    f = expr()
    if pos[0] != len(toks):
        raise ValueError(f"equation {text!r}: unexpected {toks[pos[0]][1]!r}")
    return f


def pin_list(spec, pins):
    """'A0-A14' or 'D1 D2 CS' as pin names, checked against pins."""
    out = []
    for word in spec.split():
        m = re.fullmatch(r"(\S*?\D)(\d+)-(?:\1)?(\d+)", word)
        if m:
            out += [f"{m.group(1)}{i}" for i in range(int(m.group(2)), int(m.group(3)) + 1)]
        else:
            out.append(word)
    for p in out:
        if p not in pins:
            raise ValueError(f"no pin {p} (in {spec!r})")
    return out


def check(ctype):
    """Raise ValueError if a chip type's description names a pin it hasn't."""
    names = set(ctype.pin_index)
    for pin, o in ctype.outputs.items():
        pin_list(pin, names)
        if o.fn is not None:
            parse(o.fn, names)
        whens = [a.when for ds in o.arcs.values() for a in (ds if isinstance(ds, list) else [ds])
                 if isinstance(a, Arc)]
        for eq in [o.enable] + whens:
            if eq:
                parse(eq, names)
        for d in (o.arcs, o.on, o.off):
            for spec in d:
                pin_list(spec, names)
    for pin, r in ctype.regs.items():
        pin_list(pin, names | {pin})
        for eq in (r.next, r.clear, r.preset, r.enable):
            if eq:
                parse(eq, names)
        pin_list(r.clock, names)
        for d in (r.clear_arcs, r.preset_arcs, r.on, r.off):
            for spec in d:
                pin_list(spec, names)
    for c in ctype.timing:
        if isinstance(c, Setup):
            pin_list(c.pins, names)
            pin_list(c.clock, names)
        elif isinstance(c, (Width, Period)):
            pin_list(c.pin, names)
        elif isinstance(c, Strobe):
            parse(c.active, names)
            for spec in list(c.stable) + list(c.data):
                pin_list(spec, names)
    for spec in ctype.sensitive + ctype.asynchronous:
        pin_list(spec, names)
    for a, b in ctype.joins:
        pin_list(f"{a} {b}", names)


# ---- an instance's description, as the engine takes it ---------------------------

def _ps(ns):
    return None if ns is None else int(round(ns * 1000))


class _Data:
    """A part's timing data: delays {name: [min, typ, max]} and limits
    {name: value}, in ps, with the instance's add_delay."""

    def __init__(self, timing, part, extra):
        entry = timing.get(part) or {}
        self.part = part
        self.delays = {}
        for name, v in entry.get("delays", {}).items():
            mx = v.get("max", v.get("typ"))
            self.delays[name] = [_ps(v.get("min")), _ps(v.get("typ", mx)), _ps(mx)]
        self.limits = {name: _ps(v) for name, v in entry.get("checks", {}).items()}
        for name, ps in extra.items():
            if name in self.delays:
                self.delays[name] = [None if x is None else x + ps for x in self.delays[name]]
        self.estimated = list(entry.get("estimated", []))

    def delay(self, spec):
        """[min, typ, max] ps for an arc's delay: a name, a number, or an Arc."""
        if isinstance(spec, (int, float)):
            return [int(spec)] * 3
        arc = spec if isinstance(spec, Arc) else Arc(spec)
        if isinstance(arc.name, (int, float)):
            d = [int(arc.name)] * 3
        elif arc.name in self.delays:
            d = list(self.delays[arc.name])
        else:
            raise KeyError(f"{self.part} has no delay {arc.name!r}")
        if arc.min is not None:
            if isinstance(arc.min, (int, float)):
                d[0] = int(arc.min)
            elif arc.min in self.limits:
                d[0] = self.limits[arc.min]
            elif arc.min in self.delays and self.delays[arc.min][0] is not None:
                d[0] = self.delays[arc.min][0]
            else:
                raise KeyError(f"{self.part} has no value {arc.min!r} for a minimum")
        return d

    def limit(self, name):
        """A check's limit in ps, or None if the part's data hasn't it: a
        frequency in MHz is a period."""
        if name is None:
            return None
        if isinstance(name, (int, float)):
            return int(name)
        v = self.limits.get(name)
        if v is not None and name.endswith("MHz"):
            return int(round(1e9 / v))      # v is MHz * 1000 here
        return v


def _sop(f, index):
    return [[[index[p], v] for p, v in sorted(t.items())] for t in f]


def _arcs(arcs, data, index, names):
    out = []
    for spec, ds in arcs.items():
        for d in ds if isinstance(ds, list) else [ds]:
            when = d.when if isinstance(d, Arc) else None
            out.append({"from": [index[p] for p in pin_list(spec, names)], "d": data.delay(d),
                        "name": str(d.name if isinstance(d, Arc) else d),
                        "when": _sop(parse(when, names), index) if when else None})
    return out


def describe(inst, timing, variant):
    """The engine's description of one instance: None if its type has
    none (its outputs are then untimed)."""
    t = inst.type
    if inst.gal is not None:
        return _describe_gal(inst, timing, variant)
    if not (t.outputs or t.regs or t.timing or t.asynchronous or t.joins):
        return None
    data = _Data(timing, inst.part_number(variant), inst.extra)
    names = set(t.pin_index)
    index = t.pin_index
    out = {"outputs": [], "regs": [], "checks": [], "unchecked": [],
           "sensitive": [index[p] for s in t.sensitive for p in pin_list(s, names)],
           "asynchronous": [index[p] for s in t.asynchronous for p in pin_list(s, names)],
           "joins": [[index[a], index[b]] for a, b in t.joins]}
    for pin, o in t.outputs.items():
        out["outputs"].append({
            "pin": index[pin], "fn": None if o.fn is None else _sop(parse(o.fn, names), index),
            "inv": False, "arcs": _arcs(o.arcs, data, index, names),
            "enable": _sop(parse(o.enable, names), index) if o.enable else None,
            "on": _arcs(o.on, data, index, names), "off": _arcs(o.off, data, index, names)})
    for pin, r in t.regs.items():
        out["regs"].append(_reg(index[pin], r, data, index, names))
    for c in t.timing:
        _check(c, data, index, names, out)
    return out


def _reg(pin, r, data, index, names):
    return {"pin": pin, "clock": index[r.clock], "edge": 1 if r.edge == "rise" else 0,
            "next": _sop(parse(r.next, names), index), "inv": False,
            "d": data.delay(r.delay), "name": str(r.delay),
            "clear": _sop(parse(r.clear, names), index) if r.clear else None, "clear_value": 0,
            "clear_arcs": _arcs(r.clear_arcs, data, index, names),
            "preset": _sop(parse(r.preset, names), index) if r.preset else None,
            "preset_arcs": _arcs(r.preset_arcs, data, index, names),
            "enable": _sop(parse(r.enable, names), index) if r.enable else None,
            "on": _arcs(r.on, data, index, names), "off": _arcs(r.off, data, index, names),
            "feedback": data.delay(r.feedback) if r.feedback is not None else None}


def _check(c, data, index, names, out):
    def missing(*ns):
        gone = [n for n in ns if n is not None and data.limit(n) is None]
        if gone:
            out["unchecked"].append(f"{type(c).__name__.lower()}: no {', '.join(map(str, gone))}")
        return bool(gone)
    if isinstance(c, Setup):
        if missing(c.setup, c.hold):
            return
        out["checks"].append({"kind": "setup", "pins": [index[p] for p in pin_list(c.pins, names)],
                              "clock": index[c.clock], "edge": 1 if c.edge == "rise" else 0,
                              "setup": data.limit(c.setup), "hold": data.limit(c.hold),
                              "names": [str(c.setup), str(c.hold)]})
    elif isinstance(c, Width):
        if not missing(c.name):
            out["checks"].append({"kind": "width", "pin": index[c.pin], "level": c.level,
                                  "min": data.limit(c.name), "names": [str(c.name)]})
    elif isinstance(c, Period):
        if not missing(c.name):
            out["checks"].append({"kind": "period", "pin": index[c.pin],
                                  "min": data.limit(c.name), "names": [str(c.name)]})
    elif isinstance(c, Strobe):
        stable = []
        for spec, (a, b, z) in c.stable.items():
            if missing(a, b, z):
                continue
            stable.append({"pins": [index[p] for p in pin_list(spec, names)],
                           "start": data.limit(a), "end": data.limit(b), "after": data.limit(z),
                           "names": [str(n) for n in (a, b, z)]})
        dat = []
        for spec, (s, h) in c.data.items():
            if missing(s, h):
                continue
            dat.append({"pins": [index[p] for p in pin_list(spec, names)],
                        "setup": data.limit(s), "hold": data.limit(h),
                        "names": [str(s), str(h)]})
        width = None if c.width is None or missing(c.width) else data.limit(c.width)
        out["checks"].append({"kind": "strobe", "active": _sop(parse(c.active, names), index),
                              "stable": stable, "data": dat, "width": width,
                              "names": [str(c.width)], "eq": c.active})


def _describe_gal(inst, timing, variant):
    """A 22V10 from its equations: tPD to the combinatorial outputs, tCO
    to the registered ones, tEA and tER for an output's enable, tCF for a
    register fed back into the array, tAP from AR; tS and tH on every
    input a register's next state reads, tW on the clock's high and low."""
    data = _Data(timing, inst.part_number(variant), inst.extra)
    index = inst.type.pin_index

    def sop(terms):
        return [[[index[p], v] for p, v in t] for t in terms]
    tpd = data.delay("tPD")
    on = data.delay("tEA") if "tEA" in data.delays else tpd
    off = data.delay("tER") if "tER" in data.delays else tpd
    tcf = data.delay("tCF") if "tCF" in data.delays else data.delay("CLK->Q")
    reg_pins = {pin for pin, reg, _, _ in inst.gal if reg}
    out = {"outputs": [], "regs": [], "checks": [], "unchecked": [], "sensitive": [],
           "asynchronous": [], "joins": []}
    ar = sop(inst.gal_ar) if getattr(inst, "gal_ar", None) else None
    ar_pins = sorted({p for t in (inst.gal_ar or []) for p, _ in t}) if ar else []
    tap = data.delay("tAP") if "tAP" in data.delays else tpd
    oes = getattr(inst, "gal_oe", {}) or {}
    setup_pins = set()

    def arcs_of(terms, d, name):
        pins = sorted({p for t in terms for p, _ in t})
        return [{"from": [index[p]], "d": d, "name": name, "when": None} for p in pins]
    for pin, reg, inv, terms in inst.gal:
        oe = oes.get(pin)
        en = {"enable": sop(oe) if oe is not None else None,
              "on": arcs_of(oe, on, "tEA") if oe is not None else [],
              "off": arcs_of(oe, off, "tER") if oe is not None else []}
        if reg:
            out["regs"].append({
                "pin": index[pin], "clock": index["CLK"], "edge": 1, "next": sop(terms),
                "inv": bool(inv), "d": data.delay("CLK->Q"), "name": "CLK->Q",
                "clear": ar, "clear_value": int(bool(inv)),
                "clear_arcs": [{"from": [index[p]], "d": tap, "name": "tAP", "when": None}
                               for p in ar_pins],
                "preset": None, "preset_arcs": [], "feedback": tcf, **en})
            setup_pins |= {p for t in terms for p, _ in t}
        else:
            out["outputs"].append({"pin": index[pin], "fn": sop(terms), "inv": bool(inv),
                                   "arcs": arcs_of(terms, tpd, "tPD"), **en})
    setup_pins.discard("CLK")
    if setup_pins and data.limit("setup") is not None:
        out["checks"].append({"kind": "setup", "pins": sorted(index[p] for p in setup_pins),
                              "clock": index["CLK"], "edge": 1, "setup": data.limit("setup"),
                              "hold": data.limit("hold") or 0, "names": ["setup", "hold"]})
    if reg_pins:
        for level in (1, 0):
            if data.limit("tW") is not None:
                out["checks"].append({"kind": "width", "pin": index["CLK"], "level": level,
                                      "min": data.limit("tW"), "names": ["tW"]})
            else:
                out["unchecked"].append("width: no tW")
    return out
