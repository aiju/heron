"""Running the studies' SPICE netlists on either simulator.

The studies build their circuits as SPICE text (ibis.py's buffers, the
bus_si study's backplane). `run` takes the same arguments as spice.run and
returns the same thing, and runs the netlist on one of:

- **native** (the default): heron.native.sisim, the fixed-step simulator in
  infra/sisim. The netlist is parsed here into its input. A run takes a
  known number of steps, so it can't stall.
- **ngspice**, through spice.run, for cross-checks.

Set the engine with `use(name)` or the HERON_SI_ENGINE environment
variable. The native engine reads this subset of SPICE: R, C, L, K, T
(lossless), D (with a .model), V to ground (a value or PWL), and B current
sources of the form `I = [V(coef)*]pwl(V(a[,b]), x, y, ...)`, which is what
ibis.buffer writes. Anything else is an error, not a guess.
"""

import os
import re

import numpy as np

from . import spice

ENGINES = ("native", "ngspice")
_engine = os.environ.get("HERON_SI_ENGINE", "native")

# The native engine's time step: well under the shortest line in the models
# (10 mm, 58 ps) and fine enough for 0.5 ns edges. HERON_SI_DT overrides it,
# for convergence checks.
DT = float(os.environ.get("HERON_SI_DT", "5e-12"))

# Statistics of the last native run in this process (steps, Newton
# iterations, steps that didn't converge, wall-clock seconds).
last_stats = {}


def use(name):
    """Pick the engine for later runs in this process."""
    global _engine
    if name not in ENGINES:
        raise ValueError(f"unknown engine {name!r}; one of {', '.join(ENGINES)}")
    _engine = name


def current():
    return _engine


def version():
    if _engine == "ngspice":
        return spice.version()
    from heron import native
    return f"sisim (heron native {native.version()}), dt {DT * 1e12:g} ps"


def run(lines, probes, tstop, maxstep=20e-12, title="si", timeout=300):
    """Transient analysis of a netlist (a list of lines, no .end). Returns
    {'time': t, probe: values} for each probe, e.g. 'v(n3)' or 'v(a,b)'.
    Raises RuntimeError, naming the run by `title`, if the run fails."""
    if _engine == "ngspice":
        return spice.run(lines, probes, tstop, maxstep=maxstep, title=title, timeout=timeout)
    return run_native(lines, probes, tstop, title=title, timeout=timeout)


def run_native(lines, probes, tstop, title="si", timeout=300, dt=None):
    global last_stats
    from heron import native
    dt = dt or DT
    net = Netlist(lines, dt)
    pairs = [net.probe(p) for p in probes]
    opts = {"dt": dt, "tstop": tstop, "probes": pairs, "every": 1, "max_seconds": float(timeout)}
    try:
        out = native.sisim.run(net.dict(), opts)
    except (RuntimeError, ValueError) as e:
        raise RuntimeError(f"sisim failed ({title}): {e}") from None
    last_stats = dict(out["stats"])
    t = np.frombuffer(out["time"], dtype="<f8")
    data = np.frombuffer(out["data"], dtype="<f8").reshape(len(t), len(probes))
    res = {"time": t}
    for i, p in enumerate(probes):
        res[p] = data[:, i]
    return res


# -- parsing ------------------------------------------------------------------

_SUFFIX = [("meg", 1e6), ("mil", 25.4e-6), ("t", 1e12), ("g", 1e9), ("k", 1e3), ("m", 1e-3),
           ("u", 1e-6), ("n", 1e-9), ("p", 1e-12), ("f", 1e-15)]
_NUM = re.compile(r"^([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)([a-zA-Z]*)$")


def value(s):
    """A SPICE number: '4.7k', '100n', '1.2e-08', '10p'."""
    m = _NUM.match(s.strip())
    if not m:
        raise ValueError(f"not a number: {s!r}")
    x, unit = float(m.group(1)), m.group(2).lower()
    for suf, scale in _SUFFIX:
        if unit.startswith(suf):
            return x * scale
    return x


_PWL_SRC = re.compile(r"^pwl\s*\((.*)\)\s*$", re.I)
_BEXPR = re.compile(
    r"^I\s*=\s*(?:V\(\s*([\w.]+)\s*\)\s*\*\s*)?pwl\(\s*V\(\s*([\w.]+)\s*(?:,\s*([\w.]+)\s*)?\)\s*,(.*)\)\s*$",
    re.I)
_PROBE = re.compile(r"^v\(\s*([\w.]+)\s*(?:,\s*([\w.]+)\s*)?\)$", re.I)


def _increasing(points, eps):
    """Points with strictly increasing x: a repeated x (ibis.py's PWL
    sources print times to five digits, which can merge two) moves on by
    eps, as a step."""
    out = []
    for x, y in points:
        if out and x <= out[-1][0]:
            x = out[-1][0] + eps
        out.append((x, y))
    return out


def _params(tokens):
    out = {}
    for tok in tokens:
        k, _, v = tok.partition("=")
        out[k.strip().lower()] = value(v)
    return out


class Netlist:
    """A SPICE netlist parsed into the native engine's input."""

    def __init__(self, lines, dt):
        self.dt = dt
        self.nodes = {"0": 0, "gnd": 0}
        self.fixed = {}
        self.res, self.caps, self.inds, self.coup = [], [], [], []
        self.lines, self.tables, self.diodes = [], [], []
        self.ind_names = {}
        self.models = {}
        pending_b, pending_k, pending_d = [], [], []
        for raw in lines:
            ln = raw.strip()
            if not ln or ln.startswith("*"):
                continue
            if ln.lower().startswith(".model"):
                self._model(ln)
                continue
            if ln.startswith("."):
                continue                        # .options and the like
            kind = ln[0].upper()
            tok = ln.split()
            if kind == "R":
                self.res.append({"a": self.node(tok[1]), "b": self.node(tok[2]), "r": value(tok[3])})
            elif kind == "C":
                self.caps.append({"a": self.node(tok[1]), "b": self.node(tok[2]), "c": value(tok[3])})
            elif kind == "L":
                self.ind_names[tok[0].lower()] = len(self.inds)
                self.inds.append({"a": self.node(tok[1]), "b": self.node(tok[2]), "l": value(tok[3])})
            elif kind == "K":
                pending_k.append(tok)
            elif kind == "T":
                self._line(tok)
            elif kind == "V":
                self._vsource(ln, tok)
            elif kind == "B":
                pending_b.append(ln)
            elif kind == "D":
                pending_d.append(tok)
            else:
                raise ValueError(f"the native engine doesn't take this element: {ln[:80]}")
        for tok in pending_k:
            try:
                l1, l2 = self.ind_names[tok[1].lower()], self.ind_names[tok[2].lower()]
            except KeyError:
                raise ValueError(f"coupling of an unknown inductor: {' '.join(tok)}") from None
            self.coup.append({"l1": l1, "l2": l2, "k": value(tok[3])})
        for ln in pending_b:
            self._bsource(ln)
        for tok in pending_d:
            self._diode(tok)

    def node(self, name):
        name = name.lower()
        if name not in self.nodes:
            self.nodes[name] = len(set(self.nodes.values()))
        return self.nodes[name]

    def probe(self, p):
        m = _PROBE.match(p.strip())
        if not m:
            raise ValueError(f"the native engine only probes voltages: {p!r}")
        a = m.group(1).lower()
        b = (m.group(2) or "0").lower()
        if a not in self.nodes or b not in self.nodes:
            raise ValueError(f"probe of an unknown node: {p!r}")
        return [self.nodes[a], self.nodes[b]]

    def _model(self, ln):
        m = re.match(r"^\.model\s+(\S+)\s+(\w+)\s*\((.*)\)\s*$", ln, re.I)
        if not m:
            raise ValueError(f"can't read this model: {ln}")
        self.models[m.group(1).lower()] = (m.group(2).upper(), _params(m.group(3).split()))

    def _vsource(self, ln, tok):
        a, b = tok[1].lower(), tok[2].lower()
        if self.nodes.get(b) != 0:
            raise ValueError(f"the native engine only takes voltage sources to ground: {ln[:80]}")
        rest = ln.split(None, 3)[3].strip()
        m = _PWL_SRC.match(rest)
        if m:
            nums = [value(x) for x in m.group(1).replace(",", " ").split()]
            wave = _increasing([(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)], 1e-15)
        else:
            parts = rest.split()
            if parts[0].lower() == "dc":
                parts = parts[1:]
            wave = [(0.0, value(parts[0]))]
        n = self.node(a)
        if n in self.fixed:
            raise ValueError(f"node {a} has two voltage sources")
        self.fixed[n] = wave

    def _line(self, tok):
        p = _params(tok[5:])
        z0, td = p["z0"], p["td"]
        n1, r1, n2, r2 = (self.node(x) for x in tok[1:5])
        if td >= 2 * self.dt:
            self.lines.append({"end1": [n1], "ref1": r1, "end2": [n2], "ref2": r2,
                               "tv": [[1.0]], "z": [z0], "delay": [td]})
            return
        # too short for the time step: a lumped pi section
        if r1 != r2:
            raise ValueError(f"a line shorter than two time steps must have one reference: {' '.join(tok)}")
        c = td / z0
        self.caps += [{"a": n1, "b": r1, "c": c / 2}, {"a": n2, "b": r2, "c": c / 2}]
        self.inds.append({"a": n1, "b": n2, "l": z0 * td})

    def _bsource(self, ln):
        tok = ln.split(None, 3)
        m = _BEXPR.match(tok[3].strip())
        if not m:
            raise ValueError(f"the native engine can't read this B source: {ln[:100]}")
        coef_node, x, y, pts = m.groups()
        nums = [value(v) for v in pts.replace(",", " ").split()]
        table = _increasing([(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)], 1e-9)
        coef = None
        if coef_node:
            n = self.nodes.get(coef_node.lower())
            if n is None or n not in self.fixed:
                raise ValueError(f"a B source's coefficient must be a node held by a voltage source: {ln[:100]}")
            coef = self.fixed[n]
        self.tables.append({"a": self.node(tok[1]), "b": self.node(tok[2]),
                            "x": self.node(x), "y": self.node(y or "0"), "coef": coef, "table": table})

    def _diode(self, tok):
        kind, p = self.models[tok[3].lower()]
        if kind != "D":
            raise ValueError(f"model {tok[3]} isn't a diode")
        a, b = self.node(tok[1]), self.node(tok[2])
        if p.get("rs"):
            inner = self.node(f"{tok[0]}#inner")
            self.res.append({"a": a, "b": inner, "r": p["rs"]})
            a = inner
        if p.get("tt"):
            raise ValueError("the native engine has no diode transit time (TT)")
        self.diodes.append({"a": a, "b": b, "is": p.get("is", 1e-14), "n": p.get("n", 1.0),
                            "cjo": p.get("cjo", 0.0), "vj": p.get("vj", 1.0), "m": p.get("m", 0.5),
                            "fc": p.get("fc", 0.5)})

    def dict(self):
        return {
            "nodes": len(set(self.nodes.values())),
            "fixed": [{"node": n, "wave": w} for n, w in self.fixed.items()],
            "resistors": self.res, "capacitors": self.caps, "inductors": self.inds,
            "couplings": self.coup, "lines": self.lines, "tables": self.tables,
            "diodes": self.diodes,
        }
