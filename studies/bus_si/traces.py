"""Report 0022's figures: waveforms from the jobs behind its numbers.

Each figure reruns a few of revised.py's jobs with their waveforms kept and
draws them (svgplot.py). `heron bus_si traces` writes them to the report's
folder as <name>.svg, in parallel through the runner, so a stuck run is
killed like any other job.
"""

import os

import numpy as np

from heron import BUILD, ROOT
from heron.infra.si import runner

from . import bused, floating, gb, radial, revised, svgplot, sweep, xt

OUT = os.path.join(ROOT, "reports", "0022-report-bus-si-revised")
LOG = os.path.join(BUILD, "si", "traces.jsonl")


def _ns(t, t0):
    return (t - t0) * 1e9


def _crossing(t, v, t0, rising, level=1.5):
    """When v first crosses `level` after t0."""
    return t[np.flatnonzero((t > t0) & ((v >= level) if rising else (v <= level)))[0]]


def _worst(v, keys, after, pick):
    """The trace among `keys` that goes furthest (pick: max or min) after
    the time mask `after`."""
    return pick(keys, key=lambda k: pick(v[k][after]))


def groundbounce():
    parts = [("abt16245", "tssop", "ABT16245, TSSOP"), ("abt", "soic", "ABT245, SOIC"),
             ("fct", "dip", "FCT245T, DIP")]
    die, quiet = [], []
    for i, (fam, pkg, _) in enumerate(parts):
        r = revised.run_job(("gb", fam, pkg, 16, "calibrated", "falling", "max", 1, None), keep=True)
        t, v = r["time"], r["v"]
        after = t > gb.T_EDGE
        q = _worst(v, [k for k in v if k.startswith("q:")], after, max)
        die.append((i, _ns(t, gb.T_EDGE), v["die_gnd_card"]))
        quiet.append((i, _ns(t, gb.T_EDGE), v[q]))
    x = (-2, 20)
    panels = [
        {"title": "Die ground, against the card's", "x": x, "xlabel": "ns from the edge",
         "series": die, "marks": []},
        {"title": "The quiet line, at the worst receiver", "x": x, "y": (-0.5, 1.5),
         "xlabel": "ns from the edge", "series": quiet, "marks": [(0.8, "VIL 0.8 V")]},
    ]
    return panels, [p[2] for p in parts], (
        "Ground bounce: 15 of 16 lines falling",
        "A card in the middle slot drives 16 lines through 22 ohm onto 16 cards of 12 pF; 15 fall at "
        "once, fast corner, calibrated model. Left: the driver's die ground against the card's ground. "
        "Right: the line that stays low, at the receiver where it rises most, against VIL.")


def sel():
    series = [(0, "No resistor"), (33, "33 Ω"), (68, "68 Ω")]
    runs = []
    for r_s, _ in series:
        r = revised.run_job(("sel", 200, r_s, "hct", 1, "max"), keep=True)
        t, (v,) = r["time"], r["v"].values()
        runs.append((t, v))
    # time from the edge without a resistor crossing 1.5 V
    t, v = runs[0]
    t_rise, t_fall = _crossing(t, v, radial.T_RISE, True), _crossing(t, v, radial.T_FALL, False)
    rise = [(i, _ns(t, t_rise), v) for i, (t, v) in enumerate(runs)]
    fall = [(i, _ns(t, t_fall), v) for i, (t, v) in enumerate(runs)]
    x = (-4, 14)
    marks = [(1.4, "VT± 1.4 V"), (-0.5, "−0.5 V limit")]
    panels = [
        {"title": "Rising edge", "x": x, "xlabel": "ns from the input crossing 1.5 V",
         "series": rise, "marks": marks},
        {"title": "Falling edge", "x": x, "xlabel": "ns from the input crossing 1.5 V",
         "series": fall, "marks": marks},
    ]
    return panels, [s[1] for s in series], (
        "SEL at the 74HCT132's input",
        "An ABT273 on the backplane drives SEL through its series resistor and 200 mm of trace to one "
        "74HCT132 input on the card; fast corner. VT± is the gate's VT+ minimum and VT− maximum at "
        "5.5 V, the level ring-back must not recross.")


def crosstalk():
    cases = [(True, "Ground pins around SEL and WRITE"), (False, "Data lines on those pins")]
    sels, wrs = [], []
    for i, (guard, _) in enumerate(cases):
        r = revised.run_job(("xt", "abt", "dip", "calibrated", guard, "falling", "typ", 33), keep=True)
        t, v = r["time"], r["v"]
        after = t > gb.T_EDGE
        s = _worst(v, [k for k in v if k.startswith("sel")], after, max)
        w = _worst(v, [k for k in v if k.startswith("wr")], after, min)
        sels.append((i, _ns(t, gb.T_EDGE), v[s]))
        wrs.append((i, _ns(t, gb.T_EDGE), v[w]))
    x = (-2, 20)
    panels = [
        {"title": "SEL, held low (asserted)", "x": x, "xlabel": "ns from the data edge",
         "series": sels, "marks": [(xt.VT_PLUS_MIN["typ"], "VT+ 1.3 V")]},
        {"title": "WRITE, held high (a read)", "x": x, "xlabel": "ns from the data edge",
         "series": wrs, "marks": [(xt.VT_MINUS_MAX["typ"], "VT− 1.3 V")]},
    ]
    return panels, [c[1] for c in cases], (
        "Crosstalk onto SEL and WRITE during a simple card's read",
        "The card's two ABT245 transceivers in DIP drive D0 to D15 low together, typical corner, "
        "calibrated model. SEL and WRITE at the card's 74HCT132 inputs, against the card's ground, "
        "with the guard ground pins and without them.")


def loading():
    loads = [(12, "12 pF per card"), (20, "20 pF per card")]
    rx = [("s4", "Next slot"), ("s9", "Slot 9"), ("s15", "Far end")]
    panels = []
    for c, title in loads:
        r = revised.run_job(("load", "all16", 25, c, "abt", "max", 3), keep=True)
        t, v = r["time"], r["v"]
        panels.append({"title": title, "x": (-2, 30), "xlabel": "ns from the driver's edge",
                       "series": [(i, _ns(t, bused.T_FALL), v[k]) for i, (k, _) in enumerate(rx)],
                       "marks": [(2.0, "VIH 2.0 V"), (0.8, "VIL 0.8 V")]})
    return panels, [x[1] for x in rx], (
        "A falling edge on a full backplane",
        "An ABT driver in slot 3, 22 ohm, every slot filled with cards of 12 or 20 pF; fast corner. "
        "At 20 pF the first step no longer reaches VIL at the far cards, and the line settles only "
        "after the reflection returns.")


def clock():
    models = [("pkg-cal", "Calibrated"), ("pkg", "Raw IBIS")]
    edges, dies, t0 = [], [], None
    for i, (rails, _) in enumerate(models):
        r = revised.run_job(("clock", "cdc329a", "far", False, 68, "abt244", "max", rails), keep=True)
        t, v = r["time"], r["v"][(0, 0)]
        # time from the calibrated edge crossing 1.5 V
        t0 = t0 or _crossing(t, v, radial.T_FALL, False)
        edges.append((i, _ns(t, t0), v))
        dies.append((i, _ns(t, t0), r["gnd"]))
    x = (-4, 14)
    panels = [
        {"title": "BCLK falling at slot 0's buffer", "x": x, "xlabel": "ns from the input crossing 1.5 V",
         "series": edges, "marks": [(2.0, "VIH 2.0 V"), (0.8, "VIL 0.8 V")]},
        {"title": "The clock driver's die ground", "x": x, "xlabel": "ns from the input crossing 1.5 V",
         "series": dies, "marks": []},
    ]
    return panels, [m[1] for m in models], (
        "The clock driver's own ground bounce",
        "A CDC329A in the middle of the backplane drives six slots (0 to 2 and 13 to 15) through 68 ohm, "
        "all six outputs falling together, fast corner, with the IBIS file's supply currents raw and "
        "calibrated. Left: the clock at slot 0's ABT244. Right: the driver's die ground.")


def wait():
    cases = [(0.07, "Guarded contacts (k = 0.07)"), (0.35, "Unguarded (k = 0.35)")]
    series = []
    for i, (k, _) in enumerate(cases):
        r = revised.run_job(("floating", "wait", "abt", "min", 7, k), keep=True)
        t, v = r["time"], r["v"]
        w = _worst(v, list(v), t > floating.T_RISE, min)
        series.append((i, t * 1e9, v[w]))
    panels = [{"title": "WAIT at the receiver where it dips most", "x": (0, 120), "y": (0, 5),
               "xlabel": "ns; released at 5, neighbours rise at 20, fall at 70",
               "series": series, "marks": [(2.0, "VIH 2.0 V")]}]
    return panels, [c[1] for c in cases], (
        "WAIT held only by its pull-up",
        "The card in slot 7 drives WAIT high and releases it at 5 ns; its two neighbours, driven from "
        "slot 7, rise at 20 ns and fall at 70 ns. Slow corner, ABT, 10 kilohm pull-up.")


FIGURES = {"groundbounce": groundbounce, "sel": sel, "crosstalk": crosstalk, "loading": loading,
           "clock": clock, "wait": wait}


def make(job):
    """One figure's SVG text."""
    _, name = job
    panels, legend, (title, desc) = FIGURES[name]()
    cols = 1 if len(panels) == 1 else 2
    return svgplot.figure(panels, legend, title, desc, cols=cols)


def write(names=None, workers=None, timeout=600):
    """Run the figures (in parallel, each past `timeout` killed) and write
    them. Returns the paths written."""
    names = names or list(FIGURES)
    jobs = [("figure", n) for n in names]
    if os.path.exists(LOG):
        os.remove(LOG)                  # always fresh: the figures follow the code
    sweep._setup()
    recs, n_err, _, _ = runner.run(jobs, make, LOG, workers=workers, timeout=timeout, heartbeat=30)
    paths = []
    for j in jobs:
        rec = recs.get(runner.key(j))
        if rec is None or rec["result"] is None:
            print(f"{j[1]}: failed: {rec['error'] if rec else 'no result'}")
            continue
        path = os.path.join(OUT, f"{j[1]}.svg")
        with open(path, "w") as f:
            f.write(rec["result"])
        paths.append(path)
    return paths
