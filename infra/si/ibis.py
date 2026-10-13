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

# family -> where to get it, which model is the bus-side I/O pin, and the
# DIP and SOIC package components
PARTS = {
    "abt": dict(name="74ABT245B", code="scbm052", file="sn74abt245b.ibs",
                model="ABT245B_BIO", dip="ABT245B_N", soic="ABT245B_DW",
                sha256="9246237eaf28f90b71af787f2939bcc7a3f908c3245cccce03192fbe1ae51924"),
    "act": dict(name="74ACT245", code="SCAM044", file="sn74act245.ibs",
                model="ACT245_IO", dip="ACT245_N", soic="ACT245_DW",
                sha256="7b665f636266f35735dd1ae162e063fcc53c00a3296758501b4c41e113be31d6"),
    "fct": dict(name="74FCT245T", code="SCCM001", file="cy74fct245t.ibs",
                model="FCT245T_IO", dip="FCT245T_P", soic="FCT245T_SO",
                sha256="38f531773efef5c6a0d84eee9935ce582a5993a17285d2db7ab791ed2c29bb1f"),
    "ahct": dict(name="74AHCT245", code="SCLM076", file="sn74ahct245.ibs",
                 model="AHCT245_IO", dip="AHCT245_N", soic="AHCT245_DW",
                 sha256="46db38822ee2426183543f8ab7b48d5f6f4950360ecf296ce0dea28468ea0792"),
    "hct": dict(name="74HCT245", code="SCLM097", file="sn74hct245.ibs",
                model="HCT245_IO", dip="HCT245_N", soic="HCT245_DW",
                sha256="a1f2739882cd857c87e6fba3072ff754941143122325268ec93428db3236914e"),
}

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
        self._k = {}

    def vcc(self, corner):
        return self.params["Vcc"][CORNERS[corner]]

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

    def coefficients(self, edge, corner, dt=5e-12):
        """(t, Ku, Kd) for a 'rising' or 'falling' edge at the die pad."""
        key = (edge, corner)
        if key in self._k:
            return self._k[key]
        c = CORNERS[corner]
        vcc = self.vcc(corner)
        cc = self.ccomp(corner)
        wfs = [w for w in self.waveforms if w["edge"] == edge]
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
        if len(wfs) >= 2:
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
            den = np.where(np.abs(a1 - a2) > 1e-6, a1 - a2, 1e-6)
            ku = np.clip((b - a2) / den, -0.1, 1.2)
            on = ku if edge == "rising" else 1 - ku
            v = np.interp(t, wfs[j]["t"], wfs[j]["v"][:, c])
            frac = np.abs(v - v[0]) / max(abs(v[-1] - v[0]), 1e-9)
            i90 = int(np.argmax(frac >= 0.9))
            ramp = np.clip((t - t[i90]) / 0.5e-9, 0, 1)
            on = np.where(t <= t[i90], on, on[i90] + (1 - on[i90]) * ramp)
            ku = on if edge == "rising" else 1 - on
            kd = 1 - ku
            method = "one waveform"
        self.method = getattr(self, "method", {})
        self.method[key] = method
        res = (t, np.clip(ku, -0.3, 1.5), np.clip(kd, -0.3, 1.5))
        self._k[key] = res
        return res


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
            order = np.argsort(a[:, 0])
            model.tables[section] = (a[order, 0], a[order, 1:4])
        elif section == "waveform":
            wf["t"] = a[:, 0]
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
                elif kw == "end":
                    break
                continue
            s = line.strip()
            if model is not None and section is None or section == "ramp":
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


def load(family):
    """(Model, component dict for 'dip' and 'soic') for a family."""
    if family not in _cache:
        p = PARTS[family]
        models, comps = parse(fetch(family))
        _cache[family] = (models[p["model"]], {"dip": comps[p["dip"]], "soic": comps[p["soic"]]})
    return _cache[family]


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


def buffer(name, family, corner, pad, vcc, gnd, ku=None, kd=None):
    """Netlist lines for one buffer at die node `pad`, with rails `vcc` and
    `gnd`. `ku`/`kd` name nodes carrying the switching coefficients (as
    voltages); None means three-state (a receiver)."""
    m, _ = load(family)
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
        if coef is not None:
            expr = f"V({coef})*{expr}"
        out.append(f"B{name}{kind[:3]}{kind[-2:]} {n1} {n2} I = {expr}")
    return out


def coefficient_sources(name, family, corner, edges, t0=0.0, initial=0, maxpts=80):
    """Voltage sources {name}_ku / {name}_kd carrying Ku and Kd for a driver
    that starts at logic level `initial` and switches at each time in
    `edges` (the start of the IBIS waveform)."""
    m, _ = load(family)
    level = initial
    ku_pts = [(0.0, float(level)), ]
    kd_pts = [(0.0, float(1 - level))]
    for te in edges:
        edge = "rising" if level == 0 else "falling"
        t, ku, kd = m.coefficients(edge, corner)
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
