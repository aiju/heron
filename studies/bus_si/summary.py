"""Report 0021's tables, from the native engine's results in
build/si/results/ (`heron bus_si report` runs the sweeps, then this)."""

import collections
import json
import os

import numpy as np

from heron import ROOT

from . import compare, connector, sweep

OUT = os.path.join(ROOT, "reports", "0021-report-bus-si-revised", "results.md")
R0013 = os.path.join(ROOT, "reports", "0013-report-bus-si")


def _load(preset):
    with open(os.path.join(sweep.OUT["native"], f"{preset}.json")) as f:
        return json.load(f)


def _records(preset):
    return [r for r in _load(preset)["records"] if r["result"] is not None]


def ns(x, digits=1):
    return "–" if x is None else f"{x * 1e9:.{digits}f}"


def _table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---:" if i else "---" for i in range(len(head))) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def _meta(preset):
    d = _load(preset)
    return f"{d['jobs']} jobs, {d['errors']} errors, {d['cpu_minutes']} CPU-minutes"


# -- the engine ---------------------------------------------------------------

def engine_checks():
    out = ["## The engine against ngspice", ""]
    a = os.path.join(R0013, "full.json")
    b = os.path.join(sweep.OUT["native"], "full.json")
    diffs, only, missing = compare.compare(a, b)
    keep = [("line", "rise"), ("line", "fall"), ("line", "vmax"), ("line", "vmin"), ("line", "vol"),
            ("clock", "rise t50"), ("clock", "fall t50"), ("xtalk", "peak"), ("ref", "rise"), ("ref", "fall")]
    rows = []
    for k in keep:
        d = np.abs(diffs[k]) * (1e9 if k[1].split()[-1] in compare.TIMES else 1)
        unit = "ns" if k[1].split()[-1] in compare.TIMES else "V"
        rows.append([f"{k[0]} {k[1]}", len(d), f"{np.median(d):.3f} {unit}", f"{np.percentile(d, 95):.3f} {unit}",
                     f"{np.percentile(d, 99.5):.3f} {unit}", f"{d.max():.3f} {unit}"])
    out += ["Report 0013's `full` preset (ngspice 47) against the native engine, job by job: "
            "the absolute difference of each measurement.", "",
            _table(["Measurement", "Values", "Median", "95%", "99.5%", "Largest"], rows), "",
            f"- Jobs with a result only from the native engine: {len(only['b'])} (report 0013's failures); "
            f"only from ngspice: {len(only['a'])}.",
            f"- Native run: {_meta('full')}."]
    gbd = compare.compare(a, b)[0].get(("sso", "die_gnd"))
    if gbd is not None:
        out.append(f"- Ground bounce (`sso`): the die-ground figures differ by up to {np.abs(gbd).max():.3g} V; "
                   "ngspice's are unphysical in the FCT and ACT cases (tens of kV), the reason report 0013 "
                   "flagged its model as unreliable.")
    d2 = compare.compare(os.path.join(sweep.OUT["native"], "quick.json"),
                         os.path.join(sweep.OUT["native"], "quick-native-dt2.5ps.json"))[0]
    rows = []
    for k in [("line", "rise"), ("line", "fall"), ("line", "vmin"), ("xtalk", "peak")]:
        d = np.abs(d2[k]) * (1e9 if k[1] in compare.TIMES else 1)
        unit = "ns" if k[1] in compare.TIMES else "V"
        rows.append([f"{k[0]} {k[1]}", f"{np.percentile(d, 95):.3f} {unit}", f"{d.max():.3f} {unit}"])
    out += ["", "The `quick` preset at 5 ps against 2.5 ps (the native engine's own time step):", "",
            _table(["Measurement", "95%", "Largest"], rows), ""]
    return out


def connector_check():
    rows = []
    for length in (20e-3, 25e-3):
        for v in ("B1", "B4"):
            near, far = connector.te_check(length, v)
            rows.append([f"{length * 1e3:.0f} mm", v, f"{near * 1e3:+.0f} mV ({abs(near) / 3 * 100:.1f}%)",
                         f"{far * 1e3:+.0f} mV ({abs(far) / 3 * 100:.1f}%)"])
    rows.append(["TE, measured", "B1, B4", "+700 mV (23.3%)", "−600 mV (20.0%)"])
    return ["## The connector against TE's measurement", "",
            "VME P1 pinout, A1–A8 and C1–C8 driven with a 0–3 V, 2 ns ramp; crosstalk on a quiet row-b "
            "pin (`connector.te_check`).", "",
            _table(["Contact length", "Victim", "Near end", "Far end"], rows), ""]


# -- bused lines --------------------------------------------------------------

def loading():
    recs = _records("loading")
    agg = collections.defaultdict(list)
    for r in recs:
        _, pat, stub, c, fam, corner, d = r["job"]
        agg[(pat, stub, c, fam)].append(r["result"]["worst"])

    def cell(ws):
        if not ws:
            return "–"
        ar = max(w["add_rise"] for w in ws if w["add_rise"] is not None)
        af = max(w["add_fall"] for w in ws if w["add_fall"] is not None)
        ex = max(w["extra"] for w in ws)
        return f"{ar * 1e9:.1f} / {af * 1e9:.1f}" + (f" ({ex})" if ex else "")

    out = ["## Card loading", "",
           "The delay the bus adds to the driver's datasheet delay, rise / fall (ns), worst over driver "
           "positions, receivers and both corners, with 22 Ω at every card; in brackets the most "
           "extra threshold crossings. Card load is everything on the card's side of the connector: "
           "trace, package pin, die, and any more inputs.", ""]
    for fam in ("abt", "fct", "hct"):
        rows = []
        for pat in ("all16", "half8", "four", "two"):
            for stub in (25, 50, 75):
                rows.append([pat, stub] + [cell(agg.get((pat, stub, c, fam))) for c in (9, 12, 15, 20, 25)])
        out += [f"**{fam.upper()} cards:**", "",
                _table(["Cards", "Stub (mm)", "9 pF", "12 pF", "15 pF", "20 pF", "25 pF"], rows), ""]
    out.append(f"`loading`: {_meta('loading')}. Cards: `all16` every slot, `half8` every other, "
               "`four` slots 0, 5, 10, 15, `two` slots 0 and 15. A dash: the stub alone is more than that.")
    out.append("")
    return out


def hold():
    recs = _records("loading")
    best = {}
    for r in recs:
        _, pat, stub, c, fam, corner, d = r["job"]
        w = r["result"]["worst"]
        rr, rf = w["ref"]
        for e, ref in (("first_rise", rr), ("first_fall", rf)):
            if w[e] is None:
                continue
            x = w[e] - ref
            if (fam, corner) not in best or x < best[(fam, corner)][0]:
                best[(fam, corner)] = (x, pat, stub, c)
    rows = [[f.upper(), {"min": "slow", "max": "fast"}[c], f"{x * 1e9:+.2f}", f"{p}, {s} mm, {cc} pF"]
            for (f, c), (x, p, s, cc) in sorted(best.items())]
    return ["## Hold time: the earliest change", "",
            "How long after the driver's datasheet delay point (its output crossing 1.5 V into the "
            "datasheet load) the first receiver's input leaves its old valid level, at the least: "
            "negative would mean the bus makes a change arrive earlier than the datasheet delay.", "",
            _table(["Driver", "Corner", "Earliest (ns)", "Where"], rows), ""]


def connector_sensitivity():
    recs = _records("connector")
    agg = collections.defaultdict(list)
    for r in recs:
        _, l, c, fam, corner, d = r["job"]
        agg[(fam, l, c)].append(r["result"]["worst"])
    rows = []
    for fam in ("abt", "fct"):
        for l in (6, 9, 12, 15, 20):
            row = [fam.upper(), l]
            for c in (1, 2, 3):
                ws = agg[(fam, l, c)]
                row.append(f"{max(w['add_rise'] for w in ws) * 1e9:.1f} / {max(w['add_fall'] for w in ws) * 1e9:.1f}")
            rows.append(row)
    return ["## Connector sensitivity", "",
            "16 cards of 12 pF; added delay rise / fall (ns) against the contact's inductance and "
            "capacitance.", "", _table(["Driver", "L (nH)", "1 pF", "2 pF", "3 pF"], rows), ""]


def geometry():
    recs = _records("geometry")
    agg = collections.defaultdict(list)
    for r in recs:
        _, slots, pitch, stub, fam, corner, d = r["job"]
        agg[(fam, stub, slots, pitch)].append(r["result"]["worst"])
    rows = []
    for fam in ("abt", "fct"):
        for stub in (25, 50):
            for slots in (8, 12, 16, 20):
                row = [fam.upper(), stub, slots]
                for pitch in (15.24, 20.32, 25.4):
                    ws = agg[(fam, stub, slots, pitch)]
                    row.append(f"{max(w['add_rise'] for w in ws) * 1e9:.1f} / {max(w['add_fall'] for w in ws) * 1e9:.1f}")
                rows.append(row)
    return ["## Geometry", "",
            "Cards of 12 pF (or the stub's own minimum); added delay rise / fall (ns).", "",
            _table(["Driver", "Stub (mm)", "Slots", "15.24 mm pitch", "20.32 mm", "25.4 mm"], rows), ""]


def backplane():
    recs = _records("backplane")
    rows, rows2 = [], []
    drive = collections.defaultdict(list)
    recv = collections.defaultdict(list)
    for r in recs:
        j = r["job"]
        if j[0] == "bpl-drive":
            drive[(j[1], j[2], j[3])].append(r["result"]["worst"])
        else:
            recv[(j[1], j[2])].append((r["result"]["device"], r["result"]["worst"]))
    for (where, fam, series), ws in sorted(drive.items()):
        rows.append([where, fam.upper(), series, f"{max(w['add_rise'] for w in ws) * 1e9:.1f} / "
                     f"{max(w['add_fall'] for w in ws) * 1e9:.1f}", max(w["extra"] for w in ws),
                     f"{max(w['vmax'] for w in ws):.2f} / {min(w['vmin'] for w in ws):.2f}"])
    for (where, fam), xs in sorted(recv.items()):
        dv = [x for x, _ in xs]
        cw = [w for _, w in xs]
        rows2.append([where, fam.upper(), f"{max(x['add_rise'] for x in dv) * 1e9:.1f} / {max(x['add_fall'] for x in dv) * 1e9:.1f}",
                      f"{max(w['add_rise'] for w in cw) * 1e9:.1f} / {max(w['add_fall'] for w in cw) * 1e9:.1f}"])
    return ["## The backplane's own lines", "",
            "The backplane's logic driving a bused line (DPH, RDY, BERR, W32) to 16 cards of 12 pF, from "
            "beyond slot 0's end (`end`), between slots 7 and 8 (`middle`) or a quarter of the way "
            "along; added delay rise / fall (ns), extra crossings, peaks (V).", "",
            _table(["Logic at", "Driver", "Series (Ω)", "Added delay", "Extra", "Peaks"], rows), "",
            "Its input buffer (on a 15 mm trace) receiving a card's edge: added delay at the buffer, "
            "against the worst card.", "",
            _table(["Logic at", "Cards", "At the buffer", "Worst card"], rows2), ""]


# -- radial lines -------------------------------------------------------------

def sel():
    recs = _records("sel")
    agg = collections.defaultdict(list)
    for r in recs:
        _, length, series, rx, count, corner = r["job"]
        for x in r["result"]["rx"].values():
            agg[(rx, series)].append((corner, x))
    rows = []
    for rx in ("hct", "abt"):
        for series in (0, 22, 33, 47, 56, 68, 82):
            L = agg[(rx, series)]
            fm = min(_VT[c] - x["fall"]["ringback"] for c, x in L)
            rm = min(x["rise"]["ringback"] - _VT[c] for c, x in L)
            lo = min(x["fall"]["peak"] for _, x in L)
            hi = max(x["rise"]["peak"] for _, x in L)
            rates = [x[e]["rate"] for _, x in L for e in ("rise", "fall") if x[e]["rate"]]
            rows.append([rx.upper(), series, f"{fm:+.2f}", f"{rm:+.2f}", f"{lo:.2f} / {hi:.2f}", f"{min(rates):.2f}"])
    return ["## SEL and GNT", "",
            "From an ABT273 on the backplane through the series resistor and 50–350 mm of trace to one "
            "to three inputs at the card; all corners. Margins: how far the ring-back after each edge "
            "stays from the 74HCT132's thresholds (VT+ min and VT− max at the corner's supply); peaks at "
            "the inputs; the slowest edge through 0.8–2.0 V.", "",
            _table(["Inputs", "Series (Ω)", "Falling: margin (V)", "Rising: margin (V)", "Peaks (V)",
                    "Slowest (V/ns)"], rows), ""]


_VT = {"min": 1.2, "typ": 1.3, "max": 1.4}


def clock():
    recs = _records("clock")
    agg = collections.defaultdict(list)
    for r in recs:
        _, drv, group, matched, series, rx, corner, rails = r["job"]
        agg[(drv, rails, series, group)].append((matched, rx, r["result"]))
    rows = []
    names = {"ideal": "ideal", "pkg-cal": "calibrated", "pkg-bbm": "break before make", "pkg": "raw IBIS",
             "pkg-200p": "raw, 200 pF die"}
    for drv in ("cdc329a", "abt244"):
        for rails in ("ideal", "pkg-cal", "pkg", "pkg-200p"):
            for series in (47, 56, 68):
                for group in ("far", "far3"):
                    L = agg[(drv, rails, series, group)]
                    sp = {False: 0.0, True: 0.0}
                    fr, rr, rate, lo, hi, dg = -9, 9, 9, 9, -9, 0
                    for matched, rx, res in L:
                        for e in ("rise", "fall"):
                            ts = [x[e]["t"] for x in res["rx"].values()]
                            sp[matched] = max(sp[matched], max(ts) - min(ts))
                        for x in res["rx"].values():
                            fr = max(fr, x["fall"]["ringback"])
                            rr = min(rr, x["rise"]["ringback"])
                            rate = min(rate, x["rise"]["rate"], x["fall"]["rate"])
                            lo = min(lo, x["fall"]["peak"])
                            hi = max(hi, x["rise"]["peak"])
                        if "die_gnd" in res:
                            dg = max(dg, max(abs(v) for v in res["die_gnd"]))
                    rows.append([drv.upper(), names[rails], series, 6 if group == "far" else 3,
                                 f"{sp[False] * 1e9:.2f}", f"{fr:.2f} / {rr:.2f}", f"{rate:.2f}", f"{lo:.2f} / {hi:.2f}",
                                 f"{dg:.2f}"])
    return ["## The clock tree", "",
            "One clock-driver package on the backplane, in its middle, 30 mm below the connector row, "
            "driving the farthest slots through the series resistor, each to one buffer (ABT244 or "
            "CDC329A input) on its card; all corners. The driver's rails are ideal, or its package's "
            "pins with the raw IBIS fit, or the calibrated model of the ground-bounce study. Spread: "
            "of the arrival (1.5 V) over the package's slots with unmatched trace lengths (0 when "
            "matched). Ring-back: the highest a falling edge comes back up, and the lowest a rising "
            "one comes back down.", "",
            _table(["Driver", "Rails", "Series (Ω)", "Outputs", "Spread (ns)", "Ring-back (V)",
                    "Slowest (V/ns)", "Peaks (V)", "Die ground (V)"], rows), ""]


# -- noise --------------------------------------------------------------------

_PARTS = [("abt", "dip"), ("abt", "soic"), ("abt16245", "tssop"), ("abt2245", "soic"), ("fct", "dip"),
          ("fct", "soic"), ("act", "soic")]
_NAMES = {"abt": "ABT245", "abt16245": "ABT16245", "abt2245": "ABT2245", "fct": "FCT245T", "act": "ACT245"}


def ground_bounce():
    R = {tuple(r["job"]): r["result"] for r in _records("groundbounce")}
    rows = []
    for fam, pkg in _PARTS:
        a, b = R[("volp", fam, pkg, "raw")], R[("volp", fam, pkg, "calibrated")]
        rows.append([_NAMES[fam], pkg.upper(), f"{a['volp']['quiet']:.2f}", f"{b['volp']['quiet']:.2f}"])
    out = ["## Ground bounce", "",
           "**The datasheet test** (one package, the other outputs switching into 50 pF and 500 Ω, "
           "typical corner): the quiet low output's peak, VOLP (V). Published: Fairchild 74ABT245 "
           "(SOIC) 0.7 typical, 1.0 max; TI ABT245B and ABT16245A \"typically < 1 V\"; QSI's FCT244 "
           "measurement (DIP, 7 of 8 switching) about 1.6.", "",
           _table(["Part", "Package", "Raw IBIS", "Calibrated"], rows), ""]
    rows = []
    for model in ("calibrated", "raw"):
        for fam, pkg in _PARTS:
            for lines in (16, 32):
                for edge in ("falling", "rising"):
                    r = R[("gb", fam, pkg, lines, model, edge, "max", 1, None)]
                    base = R[("gb", fam, pkg, 16, model, edge, "max", 1, 1)]
                    q = r["quiet_peak"]
                    po = (r["settle"] - base["settle"]) * 1e9 if r["settle"] and base["settle"] else float("nan")
                    inv = r["quiet_invalid_until"]
                    rows.append([model, _NAMES[fam], pkg.upper(), lines, edge, f"{q:.2f}",
                                 "–" if inv is None else f"{inv * 1e9:.1f}",
                                 f"{max(abs(x) for x in r['card_gnd']):.2f}",
                                 f"{max(abs(x) for x in r['die_gnd_card']):.2f}", f"{po:+.1f}"])
    out += ["**On the bus,** fast corner, one 100 nF capacitor per package: a card in slot 7 drives 16 or "
            "32 lines through 22 Ω (none for the ABT2245) onto 16 cards of 12 pF, all but D7 switching. "
            "Quiet: D7's level at the receivers (its peak when the others fall, its dip when they rise); "
            "invalid until: how long after the edge it is past 0.8 V (or 2.0 V); the card's ground against "
            "the backplane's; the die's ground against the card's; push-out: the switching line's settle "
            "time against one line switching alone.", "",
            _table(["Model", "Part", "Package", "Lines", "Others", "Quiet (V)", "Invalid until (ns)",
                    "Card ground (V)", "Die ground (V)", "Push-out (ns)"], rows), ""]
    rows = []
    for fam, pkg in [("abt", "soic"), ("abt16245", "tssop"), ("fct", "dip")]:
        for d in (1, 0):
            r = R[("gb", fam, pkg, 16, "calibrated", "falling", "max", d, None)]
            rows.append([_NAMES[fam], pkg.upper(), d, f"{r['quiet_peak']:.2f}", f"{max(abs(x) for x in r['card_gnd']):.2f}",
                         f"{max(abs(x) for x in r['die_gnd_card']):.2f}", f"{max(abs(x) for x in r['card_vcc']):.2f}"])
    out += ["**Decoupling** (calibrated, 16 lines falling, fast corner):", "",
            _table(["Part", "Package", "100 nF per package", "Quiet (V)", "Card ground (V)", "Die ground (V)",
                    "Card supply (V)"], rows), ""]
    return out


def crosstalk():
    agg = collections.defaultdict(list)
    for r in _records("crosstalk"):
        _, fam, pkg, model, guard, edge, corner, sel_r = r["job"]
        agg[(guard, fam, pkg, model)].append(r["result"])
    rows = []
    for key in sorted(agg, key=lambda k: (not k[0], k[1], k[2], k[3])):
        L = agg[key]
        rows.append(["yes" if key[0] else "no", key[1].upper(), key[2].upper(), key[3],
                     f"{max(x['sel_peak'] for x in L):.2f}", f"{min(x['sel_margin'] for x in L):+.2f}",
                     f"{min(x['write_dip'] for x in L):.2f}", f"{min(x['write_margin'] for x in L):+.2f}",
                     f"{max(max(abs(v) for v in x['card_gnd']) for x in L):.2f}"])
    return ["## Crosstalk onto SEL and WRITE", "",
            "A simple card's two octal transceivers drive D0–D15 (all switching, either way) next to its "
            "SEL contact (held low: asserted) and WRITE contact (held high: a read); typical and fast "
            "corners, SEL through 33, 56 or 68 Ω. Measured at the card's 74HCT132 inputs, against its "
            "own ground. Guard: the ground pins RFC 0014 asks for on all four sides of SEL and WRITE; "
            "without them the nearest data lines take those pins. Margin: to VT+ min (SEL) and VT− max "
            "(WRITE) at the corner's supply.", "",
            _table(["Guard pins", "Drivers", "Package", "Model", "SEL highest (V)", "SEL margin (V)",
                    "WRITE lowest (V)", "WRITE margin (V)", "Card ground (V)"], rows), ""]


def floating_lines():
    agg = collections.defaultdict(list)
    for r in _records("floating"):
        _, victim, fam, corner, a, k = r["job"]
        agg[(victim, fam, k)].append(r["result"])
    rows = []
    for (victim, fam, k), L in sorted(agg.items()):
        rows.append([victim.upper(), fam.upper(), k, f"{min(x['before'] for x in L):.2f}",
                     f"{min(x['lowest'] for x in L):.2f}", f"{max(x['before'] - x['after_fall'] for x in L):.2f}"])
    return ["## Lines held by a pull-up", "",
            "WAIT released high by an ABT or FCT card, and an open CLASS line, each held by 10 kΩ, "
            "between two neighbours that rise and fall (driven from slot 0 or 7) along the whole "
            "backplane; k is the coupling of their contacts (0.07 with ground pins between, 0.35 "
            "without). All corners: the level before, the lowest after, and how much of the shift "
            "stays.", "",
            _table(["Line", "Released by", "k", "Before (V)", "Lowest (V)", "Lasting shift (V)"], rows), ""]


def convergence():
    runs = steps = bad = jobs = 0
    for preset in PRESETS:
        for r in _records(preset):
            e = r["result"].get("engine") if isinstance(r["result"], dict) else None
            if e:
                jobs += 1
                runs += e["runs"]
                steps += e["steps"]
                bad += e["nonconverged"]
    return ["## Convergence", "",
            f"Over {jobs:,} jobs, {runs:,} native runs and {steps:,} time steps, Newton's method failed "
            f"to converge within its 50 iterations at {bad:,} steps.", ""]


def write():
    parts = [["# Report 0021: tables", "",
              "Generated by `heron bus_si report` from the native engine's sweeps; see the "
              "[report](../0021-report-bus-si-revised.md) for what they mean. Corners: IBIS `min` is "
              "slow (4.5 V, hot), `max` fast (5.5 V, cold).", ""],
             engine_checks(), convergence(), connector_check(), loading(), hold(), connector_sensitivity(), geometry(),
             backplane(), sel(), clock(), ground_bounce(), crosstalk(), floating_lines()]
    text = "\n".join(line for part in parts for line in part).rstrip() + "\n"
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(text)
    return OUT


PRESETS = ["full", "quick", "loading", "connector", "geometry", "backplane", "sel", "clock",
           "groundbounce", "crosstalk", "floating"]
