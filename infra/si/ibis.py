"""IBIS buffer models for the bus transceivers, as ngspice behavioural sources.

The models are TI's IBIS files for the '245 octal transceivers. They are
downloaded from ti.com on first use into build/ibis/ rather than committed.

A buffer is the standard IBIS behavioural model:

    I(pad) = Ku(t)·Ipu(Vcc − V) + Kd(t)·Ipd(V) + Igc(V) + Ipc(Vcc − V) + C_comp·dV/dt

with currents positive into the pin. Ku and Kd, the pull-up and pull-down
switching coefficients, come from the two V-T waveforms each edge has (one
into a fixture to ground, one into a fixture to Vcc) by solving a 2×2
system at each time step. A receiver, or a driver in three-state, is the
same model with Ku = Kd = 0.
"""

import hashlib
import io
import os
import re
import urllib.request
import zipfile

import numpy as np

from heron import BUILD as _BUILD

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(_BUILD, "ibis")

# part -> where to get it, which model is the bus-side pin (the output for
# drivers that aren't transceivers, with `input` naming the input model),
# and its package components. The '245s are the bus transceivers of report
# 0013; the rest came in for report 0021.
PARTS = {
    "abt": dict(name="74ABT245B", code="scbm052", file="sn74abt245b.ibs",
                model="ABT245B_BIO", packages={"dip": "ABT245B_N", "soic": "ABT245B_DW"},
                sha256="9246237eaf28f90b71af787f2939bcc7a3f908c3245cccce03192fbe1ae51924"),
    "act": dict(name="74ACT245", code="SCAM044", file="sn74act245.ibs",
                model="ACT245_IO", packages={"dip": "ACT245_N", "soic": "ACT245_DW"},
                sha256="7b665f636266f35735dd1ae162e063fcc53c00a3296758501b4c41e113be31d6"),
    "fct": dict(name="74FCT245T", code="SCCM001", file="cy74fct245t.ibs",
                model="FCT245T_IO", packages={"dip": "FCT245T_P", "soic": "FCT245T_SO"},
                sha256="38f531773efef5c6a0d84eee9935ce582a5993a17285d2db7ab791ed2c29bb1f"),
    "ahct": dict(name="74AHCT245", code="SCLM076", file="sn74ahct245.ibs",
                 model="AHCT245_IO", packages={"dip": "AHCT245_N", "soic": "AHCT245_DW"},
                 sha256="46db38822ee2426183543f8ab7b48d5f6f4950360ecf296ce0dea28468ea0792"),
    "hct": dict(name="74HCT245", code="SCLM097", file="sn74hct245.ibs",
                model="HCT245_IO", packages={"dip": "HCT245_N", "soic": "HCT245_DW"},
                sha256="a1f2739882cd857c87e6fba3072ff754941143122325268ec93428db3236914e"),
    # 16-bit flow-through transceiver; an old file with ramps but no V-T waveforms
    "abt16245": dict(name="74ABT16245A", code="SCBM006", file="abt16245a.ibs",
                     model="ABT16245A_I_O", packages={"tssop": "ABT16245A_DGG", "ssop": "ABT16245A_DL"},
                     sha256="36eaa6f1cc75b0bfb20fc157a8e2d9ec599db5a738f8ec237e8aa016d1d46d3a"),
    # octal transceiver with 25 ohm series resistors on its B port
    "abt2245": dict(name="74ABT2245", code="SCBM061", file="sn74abt2245.ibs",
                    model="ABT2245_BIO", packages={"dip": "ABT2245_N", "soic": "ABT2245_DW"},
                    sha256="2f9f00717bbdbd3329a11e961f53ca1d921dba075544fa5192653116b0410bcc"),
    # a registered output (for SEL and GNT) and a buffer (per-card clock)
    # (its C_comp of 1.4 pF min and 52 pF max is implausible: typ is used)
    "abt273": dict(name="74ABT273", code="SCBM081", file="sn74abt273.ibs", ccomp_typ=True,
                   model="ABT273_OUT", input="ABT273_CLK", packages={"dip": "ABT273_N", "soic": "ABT273_DW"},
                   sha256="f119839b2fb0ee99d28f5a28a6a59a47063a33ccf174b6cf4e3598c3f810ef32"),
    "abt244": dict(name="74ABT244A", code="SCBM092", file="sn74abt244a.ibs",
                   model="ABT244A_OUT", input="ABT244A_IN", packages={"dip": "ABT244A_N", "soic": "ABT244A_DW"},
                   sha256="8303cfd57562acad670e33e46943245c96b77241b4c38d5fa1fe8ccee737cff2"),
    # 5 V clock drivers, 1 to 6 (one package each, no per-pin values)
    "cdc329a": dict(name="CDC329A", code="SCAM016", file="cdc329a.ibs",
                    model="CDC329_OUT", input="CDC329_IN", packages={"ssop": "CDC329A(CLOCK_DRIVER)"},
                    sha256="b87e27bbeb472b343d7ad42f2ebe575d77c20d6be5b2340ecb662f1f88fa6644"),
    "cdc391": dict(name="CDC391", code="SCAM017", file="cdc391.ibs",
                   model="CDC391_OUT", input="CDC391_IN", packages={"ssop": "CDC391(5.0V_CLOCK_DRIVER)"},
                   sha256="4e43da0e2a11c837901b24f8b8e32081d2150d154b206e62e3b0560ccc2503ba"),
}

# the families report 0013's sweeps cover
BUS_FAMILIES = ["abt", "act", "fct", "ahct", "hct"]

CORNERS = {"typ": 0, "min": 1, "max": 2}

LEAK = 100e3                   # ohm, per input

_SCALE = {"T": 1e12, "G": 1e9, "M": 1e6, "k": 1e3, "m": 1e-3, "u": 1e-6,
          "n": 1e-9, "p": 1e-12, "f": 1e-15}
_NUM = re.compile(r"^([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)([TGMkmunpf]?)")


def num(s):
    """An IBIS number ('6.88pF', '9.766E-12s', '4.2e-02'); None for NA."""
    m = _NUM.match(s)
    if not m:
        return None
    return float(m.group(1)) * _SCALE.get(m.group(2), 1.0)


def fetch(family):
    """Path of the family's .ibs file, downloading it if needed."""
    p = PARTS[family]
    path = os.path.join(BUILD, p["file"])
    if os.path.exists(path):
        return path
    os.makedirs(BUILD, exist_ok=True)
    url = "https://www.ti.com/lit/zip/" + p["code"]
    with urllib.request.urlopen(url, timeout=60) as r:
        data = r.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != p["sha256"]:
        print(f"warning: {url} has changed since these results were made "
              f"(sha256 {digest[:12]}…)")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(p["file"]))
        with open(path, "wb") as f:
            f.write(z.read(name))
    return path


def _triple(fields, default=None):
    """typ/min/max from a row of fields, with NA falling back to typ."""
    vals = [num(f) for f in fields[:3]]
    while len(vals) < 3:
        vals.append(None)
    typ = vals[0] if vals[0] is not None else default
    return [typ if v is None else v for v in vals]


class Model:
    def __init__(self, name):
        self.name = name
        self.params = {}            # Vinl, Vinh, C_comp, Vcc, ...
        self.tables = {}            # pulldown, pullup, gnd_clamp, power_clamp: (V, I[3])
        self.waveforms = []         # dicts: edge, R, V (per corner), t, v[3]
        self.ramp = {}              # rising/falling: [(dV, dt)] per corner; R_load
        self._k = {}

    def vcc(self, corner):
        return self.params["Vcc"][CORNERS[corner]]

    def _ramp_waveforms(self, edge):
        if edge not in self.ramp:
            raise ValueError(f"{self.name}: no {edge} waveforms and no ramp")
        return _ramp_waveforms_impl(self, edge)

    def ccomp(self, corner):
        return self.params["C_comp"][CORNERS[corner]]

    def table(self, kind, corner):
        if kind not in self.tables:
            return None
        v, i = self.tables[kind]
        return v, i[:, CORNERS[corner]]

    # -- switching coefficients -------------------------------------------

    def _current(self, kind, x, corner):
        t = self.table(kind, corner)
        if t is None:
            return np.zeros_like(x)
        return np.interp(x, t[0], t[1])

    def coefficients(self, edge, corner, dt=5e-12, overlap=True):
        """(t, Ku, Kd) for a 'rising' or 'falling' edge at the die pad.

        A fit from one waveform has to assume how the transistor that turns
        off does so. With `overlap` (report 0013's models) it's Kd = 1 - Ku,
        so both are half on mid-edge and a crowbar current runs from Vcc to
        ground: 40-200 mA in these files, more than the load current. That
        doesn't change the output, but it does change what the package's
        power pins carry. Without it, the transistor that turns off does so
        at once (break before make), and the one that turns on is fitted to
        the same waveform: the same output, no crowbar current. The truth is
        in between; ground bounce is run both ways."""
        key = (edge, corner, overlap)
        if key in self._k:
            return self._k[key]
        c = CORNERS[corner]
        vcc = self.vcc(corner)
        cc = self.ccomp(corner)
        wfs = [w for w in self.waveforms if w["edge"] == edge] or self._ramp_waveforms(edge)
        tend = max(w["t"][-1] for w in wfs)
        t = np.arange(0.0, tend + dt / 2, dt)
        rows, rhs = [], []
        for w in wfs:
            v = np.interp(t, w["t"], w["v"][:, c])
            dv = np.gradient(v, t)
            b = (w["V"][c] - v) / w["R"] - cc * dv \
                - self._current("gnd_clamp", v, corner) \
                - self._current("power_clamp", vcc - v, corner)
            rows.append((self._current("pullup", vcc - v, corner),
                         self._current("pulldown", v, corner)))
            rhs.append(b)
        start = (0.0, 1.0) if edge == "rising" else (1.0, 0.0)
        method = None
        if len(wfs) >= 2 and overlap:
            (a11, a12), (a21, a22) = rows[0], rows[1]
            det = a11 * a22 - a12 * a21
            scale = np.abs(a11 * a22) + np.abs(a12 * a21) + 1e-30
            ok = np.abs(det) > 0.02 * scale
            safe = np.where(ok, det, 1.0)
            ku = (rhs[0] * a22 - a12 * rhs[1]) / safe
            kd = (a11 * rhs[1] - a21 * rhs[0]) / safe
            # Where both fixtures leave one transistor without current (a
            # bipolar pull-up above ~3.5 V, say) its coefficient is
            # undetermined and doesn't matter; interpolate across the gap.
            good = np.flatnonzero(ok)
            if len(good):
                for k, s in ((ku, start[0]), (kd, start[1])):
                    k[~ok] = np.interp(t[~ok], t[good], k[good], left=s, right=k[good[-1]])
                on, off = (ku, kd) if edge == "rising" else (kd, ku)
                on /= on[-1]
                off -= off[-1]
                if min(ku.min(), kd.min()) > -0.2 and max(ku.max(), kd.max()) < 1.25:
                    method = "two waveforms"
        if method is None:
            # The two waveforms don't agree with the V-I tables (TI's ABT,
            # FCT and HCT files): fit the waveform where the switching
            # transistor works against the fixture, with Kd = 1 - Ku, up to
            # 90% of the swing, then ramp to full strength so the DC levels
            # come from the V-I tables.
            want = 0.0 if edge == "rising" else vcc
            j = min(range(len(wfs)), key=lambda i: abs(wfs[i]["V"][c] - want))
            (a1, a2), b = rows[j], rhs[j]
            if overlap:
                den = np.where(np.abs(a1 - a2) > 1e-6, a1 - a2, 1e-6)
                ku = np.clip((b - a2) / den, -0.1, 1.2)
                on = ku if edge == "rising" else 1 - ku
            else:
                # only the transistor turning on: b = K·a
                a = a1 if edge == "rising" else a2
                on = np.clip(b / np.where(np.abs(a) > 1e-9, a, 1e-9), -0.1, 1.2)
            v = np.interp(t, wfs[j]["t"], wfs[j]["v"][:, c])
            frac = np.abs(v - v[0]) / max(abs(v[-1] - v[0]), 1e-9)
            i90 = int(np.argmax(frac >= 0.9))
            ramp = np.clip((t - t[i90]) / 0.5e-9, 0, 1)
            on = np.where(t <= t[i90], on, on[i90] + (1 - on[i90]) * ramp)
            if overlap:
                ku = on if edge == "rising" else 1 - on
                kd = 1 - ku
                method = "one waveform"
            else:
                ku, kd = (on, np.zeros_like(on)) if edge == "rising" else (np.zeros_like(on), on)
                method = "one waveform, no overlap"
        self.method = getattr(self, "method", {})
        self.method[key] = method
        res = (t, np.clip(ku, -0.3, 1.5), np.clip(kd, -0.3, 1.5))
        self._k[key] = res
        return res


def _dc_level(model, kind_on, corner, rf, vf):
    """The pad voltage with one transistor fully on into a fixture."""
    vcc = model.vcc(corner)
    lo, hi = -1.0, vcc + 1.0
    for _ in range(60):
        v = (lo + hi) / 2
        i = (vf - v) / rf                       # into the pad
        if kind_on == "pullup":
            cur = model._current("pullup", np.array([vcc - v]), corner)[0]
        else:
            cur = model._current("pulldown", np.array([v]), corner)[0]
        cur += model._current("gnd_clamp", np.array([v]), corner)[0] \
            + model._current("power_clamp", np.array([vcc - v]), corner)[0]
        # cur is the buffer's current into the pad; balance against the fixture
        if cur > i:
            hi = v
        else:
            lo = v
    return (lo + hi) / 2


def _ramp_waveforms_impl(model, edge):
    """A V-T waveform made from [Ramp]: a straight 0-100% edge taking
    dt/0.6 (dt is its 20-80% time) into R_load, to ground for a rising edge
    and to Vcc for a falling one, between the DC levels the V-I tables
    give. What converters do with ramp-only files."""
    r = model.ramp.get("R_load") or 50.0
    rows = model.ramp[edge]
    vfix = [0.0] * 3 if edge == "rising" else [model.params["Vcc"][c] for c in range(3)]
    tend = max(dt for _, dt in rows) / 0.6 * 1.5 + 1e-9
    t = np.linspace(0.0, tend, 400)
    v = np.zeros((len(t), 3))
    for c, name in enumerate(("typ", "min", "max")):
        dv, dt = rows[c]
        full = dt / 0.6
        lo = _dc_level(model, "pulldown", name, r, vfix[c])
        hi = _dc_level(model, "pullup", name, r, vfix[c])
        a, b = (lo, hi) if edge == "rising" else (hi, lo)
        t0 = 0.2e-9
        v[:, c] = a + (b - a) * np.clip((t - t0) / full, 0, 1)
    return [{"edge": edge, "R": r, "V": vfix, "t": t, "v": v, "from_ramp": True}]


def parse(path):
    """{model name: Model}, {component name: {'pkg': (R, L, C), 'pins': {...}}}."""
    models, comps = {}, {}
    model = comp = None
    section = None
    wf = None
    rows = []

    def flush():
        nonlocal rows
        if model is None or section is None or not rows:
            rows = []
            return
        a = np.array(rows)
        if section in ("pulldown", "pullup", "gnd_clamp", "power_clamp"):
            # a few files hold nonsense far outside the rails (CDC329A: 1e23 A)
            a[:, 1:4] = np.clip(a[:, 1:4], -100.0, 100.0)
            order = np.argsort(a[:, 0])
            model.tables[section] = (a[order, 0], a[order, 1:4])
        elif section == "waveform":
            # tables start at t = 0; a few files carry a large offset
            # (CDC329A: 110 ns). FCT's 10 ps is left alone.
            wf["t"] = a[:, 0] - (a[0, 0] if a[0, 0] > 1e-9 else 0.0)
            wf["v"] = a[:, 1:4]
            model.waveforms.append(wf)
        rows = []

    with open(path, errors="replace") as f:
        for raw in f:
            line = raw.split("|", 1)[0].rstrip()
            if not line.strip():
                continue
            m = re.match(r"^\[([^\]]+)\]\s*(.*)$", line.strip())
            if m:
                flush()
                kw = m.group(1).strip().lower().replace("_", " ")
                arg = m.group(2).split()
                section = None
                if kw == "model":
                    model = Model(arg[0])
                    models[arg[0]] = model
                    comp = None
                elif kw == "component":
                    comp = {"pkg": None, "pins": {}}
                    comps[arg[0]] = comp
                    model = None
                elif kw == "package":
                    section = "package"
                elif kw == "pin" and comp is not None:
                    section = "pin"
                elif model is not None and kw in ("pulldown", "pullup", "gnd clamp", "power clamp"):
                    section = kw.replace(" ", "_")
                elif model is not None and kw in ("rising waveform", "falling waveform"):
                    section = "waveform"
                    wf = {"edge": kw.split()[0], "R": None, "V": None}
                elif model is not None and kw == "voltage range":
                    model.params["Vcc"] = _triple(arg)
                elif model is not None and kw == "pullup reference":
                    model.params["Vcc"] = _triple(arg)
                elif model is not None and kw == "ramp":
                    section = "ramp"
                    model.ramp = {}
                elif kw == "end":
                    break
                continue
            s = line.strip()
            if section == "ramp" and model is not None:
                f2 = s.split()
                if f2[0].lower() in ("dv/dt_r", "dv/dt_f"):
                    vals = []
                    for x in f2[1:4]:
                        dv, _, dt = x.partition("/")
                        vals.append((num(dv), num(dt)) if dt else None)
                    while len(vals) < 3:
                        vals.append(None)
                    vals = [v if v is not None and None not in v else vals[0] for v in vals]
                    model.ramp["rising" if f2[0].lower().endswith("r") else "falling"] = vals
                    continue
                m = re.match(r"^R_load\s*=\s*(\S+)", s, re.I)
                if m:
                    model.ramp["R_load"] = num(m.group(1))
                continue
            if model is not None and section is None:
                m = re.match(r"^(\w+)\s*=\s*(\S+)", s)
                if m and model is not None:
                    model.params[m.group(1)] = num(m.group(2))
                    continue
                f2 = s.split()
                if model is not None and f2[0] == "C_comp":
                    model.params["C_comp"] = _triple(f2[1:])
                continue
            if section == "waveform":
                m = re.match(r"^(\w+)\s*=\s*(\S+)", s)
                if m:
                    k, v = m.group(1), num(m.group(2))
                    if k == "R_fixture":
                        wf["R"] = v
                    elif k == "V_fixture":
                        wf["V"] = [v, v, v]
                    elif k == "V_fixture_min":
                        wf["V"][1] = v
                    elif k == "V_fixture_max":
                        wf["V"][2] = v
                    elif k in ("C_fixture", "L_fixture", "R_dut", "L_dut", "C_dut") and v:
                        raise ValueError(f"{path}: {k} != 0 not supported")
                    continue
            f2 = s.split()
            if section in ("pulldown", "pullup", "gnd_clamp", "power_clamp", "waveform"):
                vals = [num(x) for x in f2[:4]]
                if vals[0] is None:
                    continue
                typ = vals[1]
                rows.append([vals[0]] + [typ if v is None else v for v in vals[1:4]])
            elif section == "package" and comp is not None:
                if f2[0] in ("R_pkg", "L_pkg", "C_pkg"):
                    comp.setdefault("pkgd", {})[f2[0]] = _triple(f2[1:])
                    d = comp["pkgd"]
                    if len(d) == 3:
                        comp["pkg"] = (d["R_pkg"], d["L_pkg"], d["C_pkg"])
            elif section == "pin" and comp is not None:
                rlc = [num(x) for x in f2[3:6]] if len(f2) >= 6 else [None] * 3
                comp["pins"][f2[0]] = (f2[1], f2[2], rlc)
    flush()
    return models, comps


_cache = {}


def _parsed(family):
    if family not in _cache:
        _cache[family] = parse(fetch(family))
    return _cache[family]


def load(family, model=None):
    """(Model, {package: component}) for a part: its bus-side model, or the
    named one (e.g. PARTS[family]['input'])."""
    p = PARTS[family]
    models, comps = _parsed(family)
    m = models[model or p["model"]]
    if p.get("ccomp_typ") and "C_comp" in m.params:
        m.params["C_comp"] = [m.params["C_comp"][0]] * 3
    return m, {k: comps[v] for k, v in p["packages"].items()}


def input_model(family):
    """The name of the part's input model (its bus-side model for the
    transceivers)."""
    return PARTS[family].get("input", PARTS[family]["model"])


def pin_rlc(family, package, corner="typ", signal=None, model=None):
    """Package R, L, C of one pin: a named signal's own values, else the
    worst (largest L) pin of the given model, else the package default."""
    _, comps = load(family)
    comp = comps[package]
    c = CORNERS[corner]
    best = None
    for sig, (name, mname, rlc) in comp["pins"].items():
        if None in rlc:
            continue
        if (signal and name == signal) or (not signal and model and mname == model):
            if best is None or rlc[1] > best[1]:
                best = rlc
    if best is not None:
        return tuple(best)
    r, l, cc = comp["pkg"]
    return r[c], l[c], cc[c]


# -- ngspice text -------------------------------------------------------------

def _pwl(expr, x, y, maxpts=60):
    """ngspice pwl() over a table, thinned to at most maxpts points."""
    x, y = np.asarray(x), np.asarray(y)
    keep = _thin(x, y, maxpts)
    pts = ", ".join(f"{x[i]:.4g},{y[i]:.5g}" for i in keep)
    return f"pwl({expr}, {pts})"


def _thin(x, y, maxpts):
    """Indices of a subset of points that keeps a piecewise-linear table's
    shape: greedily add the point of largest error."""
    n = len(x)
    if n <= maxpts:
        return list(range(n))
    keep = [0, n - 1]
    span = max(np.ptp(y), 1e-12)
    while len(keep) < maxpts:
        ks = sorted(keep)
        approx = np.interp(x, x[ks], y[ks])
        err = np.abs(approx - y)
        i = int(np.argmax(err))
        if err[i] < span * 1e-4:
            break
        keep.append(i)
    return sorted(set(keep))


def supply_scale(vnom, alpha, vt=1.0, points=24):
    """A driver's strength against its own rail-to-rail voltage, relative
    to its nominal supply: ((V − vt)/(vnom − vt))^alpha, 0 below vt. The
    shape of a transistor's drive against its gate voltage; classic IBIS
    has none, which is why it overstates ground bounce (IBIS 5 adds
    [ISSO] tables for this). (x, y) points over 0 to 2·vnom."""
    v = np.linspace(0.0, 2 * vnom, points)
    s = np.clip((v - vt) / (vnom - vt), 0.0, None) ** alpha
    return list(zip(v, s))


def buffer(name, family, corner, pad, vcc, gnd, ku=None, kd=None, model=None, supply=None):
    """Netlist lines for one buffer at die node `pad`, with rails `vcc` and
    `gnd`. `ku`/`kd` name nodes carrying the switching coefficients (as
    voltages); None means three-state (a receiver). `model` picks another
    of the part's models (its input model, say). `supply` (supply_scale's
    table) makes the driver's strength follow V(vcc, gnd)."""
    m, _ = load(family, model)
    out = [f"* {name}: {PARTS[family]['name']} {m.name} ({corner})"]
    out.append(f"C{name}c {pad} {gnd} {m.ccomp(corner):.4g}")
    # input leakage, which is what holds a bipolar (ABT) high level at
    # ~3.5 V when there is no DC load; the IBIS pull-up gives no current
    # within 0.9 V of Vcc
    out.append(f"R{name}leak {pad} {gnd} {LEAK:.4g}")
    for kind, ref, coef in (("pulldown", "gnd", kd), ("pullup", "vcc", ku),
                            ("gnd_clamp", "gnd", None), ("power_clamp", "vcc", None)):
        t = m.table(kind, corner)
        if t is None:
            continue
        if kind in ("pulldown", "pullup") and coef is None:
            continue
        v, i = t
        if ref == "gnd":
            arg, n1, n2 = f"V({pad},{gnd})", pad, gnd
        else:
            arg, n1, n2 = f"V({vcc},{pad})", pad, vcc
        expr = _pwl(arg, v, i)
        if coef is not None and supply is not None:
            xs, ys = zip(*supply)
            expr = f"{_pwl(f'V({vcc},{gnd})', xs, ys)}*{expr}"
        if coef is not None:
            expr = f"V({coef})*{expr}"
        out.append(f"B{name}{kind[:3]}{kind[-2:]} {n1} {n2} I = {expr}")
    return out


def coefficient_sources(name, family, corner, edges, t0=0.0, initial=0, maxpts=80, overlap=True):
    """Voltage sources {name}_ku / {name}_kd carrying Ku and Kd for a driver
    that starts at logic level `initial` and switches at each time in
    `edges` (the start of the IBIS waveform). `overlap`: see
    Model.coefficients."""
    m, _ = load(family)
    level = initial
    ku_pts = [(0.0, float(level)), ]
    kd_pts = [(0.0, float(1 - level))]
    for te in edges:
        edge = "rising" if level == 0 else "falling"
        t, ku, kd = m.coefficients(edge, corner, overlap=overlap)
        keep = sorted(set(_thin(t, ku, maxpts)) | set(_thin(t, kd, maxpts)))
        for i in keep:
            ku_pts.append((te + t[i], ku[i]))
            kd_pts.append((te + t[i], kd[i]))
        level = 1 - level
    out = []
    for suffix, pts in (("ku", ku_pts), ("kd", kd_pts)):
        clean = []
        for tt, v in pts:
            if clean and tt <= clean[-1][0]:
                tt = clean[-1][0] + 1e-13
            clean.append((tt, v))
        body = " ".join(f"{tt:.5g} {v:.5g}" for tt, v in clean)
        out.append(f"V{name}{suffix} {name}_{suffix} 0 PWL({body})")
    return out, (f"{name}_ku", f"{name}_kd")


def thresholds(family):
    m, _ = load(family)
    return m.params.get("Vinl", 0.8), m.params.get("Vinh", 2.0)


def test_load(family):
    """The datasheet timing load (Rref to Vref, Cref) and Vmeas."""
    m, _ = load(family)
    p = m.params
    return p.get("Rref"), p.get("Vref", 0.0), p.get("Cref"), p.get("Vmeas", 1.5)
