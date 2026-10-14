"""Signal-integrity sweeps: many simulator runs in parallel.

The presets here are report 0013's: `quick` and `full`. They run on
either engine (infra/si/engine.py). Each finished job is appended to
build/si/<preset>-<engine>.jsonl as it completes, so a stopped sweep picks
up where it was, and infra/si/runner.py kills any job that overruns its
deadline. At the end the results are written, compactly, to
<preset>.json: in report 0013's folder for ngspice (the committed
originals), in report 0022's for the native engine.
"""

import json
import os

import numpy as np

from heron import BUILD, ROOT
from heron.infra.si import engine, ibis, runner, spice

from . import bus, noise

WORK = os.path.join(BUILD, "si")
# results: report 0013's committed ngspice files; the native engine's go to
# build/ (they take minutes to remake), and `heron bus_si report` writes
# report 0022's tables from them
OUT = {"ngspice": os.path.join(ROOT, "reports", "0013-report-bus-si"),
       "native": os.path.join(BUILD, "si", "results")}

FAMILIES = ibis.BUS_FAMILIES
ALL_TERMS = list(bus.TERMS)


def _mid(slots):
    return (slots - 1) // 2


PRESETS = {
    # Option 1: the cases that decide something, to see how long a run takes
    "quick": {
        "ibis": {"families": FAMILIES, "corners": ["min", "max"]},
        "ref": {"families": ["abt", "fct", "hct"], "corners": ["min", "max"]},
        "line": {"slots": [16], "families": ["abt", "fct", "hct"],
                 "terms": ["none", "vme", "rc"], "drivers": "end+mid",
                 "corners": ["min", "max"]},
        "clock": {"families": ["act", "fct"], "rseries": [47, 56],
                  "matched": [True, False], "corners": ["max"]},
        "xtalk": {"families": ["abt", "fct"], "terms": ["vme", "rc"], "victim": [0, 1],
                  "k": [0.4], "drivers": "end", "corners": ["max"]},
        "sso": {"families": ["abt", "fct"], "packages": ["dip", "soic"], "count": [1],
                "terms": ["rc"], "edges": ["falling"], "corners": ["max"]},
    },
    # Everything: 8 and 16 slots, all five families and seven terminations,
    # every driver position (the backplane is symmetric, so half of them)
    "full": {
        "ibis": {"families": FAMILIES, "corners": ["typ", "min", "max"]},
        "ref": {"families": FAMILIES, "corners": ["min", "max"]},
        "line": {"slots": [16, 8], "families": FAMILIES, "terms": ALL_TERMS,
                 "drivers": "all", "corners": ["min", "max"]},
        "clock": {"families": ["abt", "act", "fct"], "rseries": [22, 33, 47, 56, 68],
                  "matched": [True, False], "corners": ["min", "max"]},
        "xtalk": {"families": FAMILIES, "terms": ["none", "vme", "thev", "rc", "series+rc"],
                  "victim": [0, 1], "k": [0.2, 0.4], "drivers": "end+mid", "corners": ["max"]},
        "sso": {"families": ["abt", "act", "fct"], "packages": ["dip", "soic"],
                "count": [1, 2, 4], "terms": ["vme", "rc"], "edges": ["falling", "rising"],
                "corners": ["max"]},
    },
}


def _drivers(spec, slots):
    if spec == "all":
        return list(range((slots + 1) // 2))
    if spec == "end":
        return [0]
    return [0, _mid(slots)]


def jobs(preset):
    p = PRESETS[preset]
    out = []
    for f in p["ibis"]["families"]:
        for c in p["ibis"]["corners"]:
            out.append(("ibis", f, c))
    for f in p["ref"]["families"]:
        for c in p["ref"]["corners"]:
            out.append(("ref", f, c))
    q = p["line"]
    for n in q["slots"]:
        for f in q["families"]:
            for t in q["terms"]:
                for c in q["corners"]:
                    for d in _drivers(q["drivers"], n):
                        out.append(("line", n, t, f, c, d))
    q = p["clock"]
    for f in q["families"]:
        for r in q["rseries"]:
            for m in q["matched"]:
                for c in q["corners"]:
                    out.append(("clock", f, r, m, c))
    q = p["xtalk"]
    for f in q["families"]:
        for t in q["terms"]:
            for v in q["victim"]:
                for k in q["k"]:
                    for c in q["corners"]:
                        for d in _drivers(q["drivers"], 16):
                            out.append(("xtalk", t, f, c, d, v, k))
    q = p["sso"]
    for f in q["families"]:
        for pk in q["packages"]:
            for n in q["count"]:
                for t in q["terms"]:
                    for e in q["edges"]:
                        for c in q["corners"]:
                            out.append(("sso", t, f, c, pk, n, e))
    return out


def ibis_check(family, corner):
    """Drive each IBIS reference fixture with the converted model and
    compare: the worst voltage error, and the error in the time of the
    50% point, over the model's V-T waveforms."""
    m, _ = ibis.load(family)
    c = ibis.CORNERS[corner]
    worst_v, worst_t, rows = 0.0, 0.0, []
    for w in m.waveforms:
        t0 = 1e-9
        init = 0 if w["edge"] == "rising" else 1
        src, (ku, kd) = ibis.coefficient_sources("d", family, corner, [t0], initial=init)
        lines = [f"Vcc vcc 0 {m.vcc(corner)}"] + src
        lines += ibis.buffer("d", family, corner, "pad", "vcc", "0", ku, kd)
        lines += [f"Rf pad fx {w['R']}", f"Vf fx 0 {w['V'][c]}"]
        r = engine.run(lines, ["v(pad)"], t0 + w["t"][-1], maxstep=10e-12,
                      title=f"ibis {family} {corner} {w['edge']} {w['V'][c]} V")
        sim = np.interp(w["t"], r["time"] - t0, r["v(pad)"])
        tgt = w["v"][:, c]
        mid = (tgt[0] + tgt[-1]) / 2

        def t50(x):
            s = np.sign(x - mid)
            k = np.flatnonzero(s != s[0])
            return w["t"][k[0]] if len(k) else float("nan")
        dt = t50(sim) - t50(tgt)
        dv = float(np.abs(sim - tgt).max())
        rows.append({"edge": w["edge"], "fixture": w["V"][c], "dv": dv, "dt50": dt})
        worst_v = max(worst_v, dv)
        worst_t = max(worst_t, abs(dt))
    return {"method": {e: m.method.get((e, corner, True)) for e in ("rising", "falling")},
            "dv": worst_v, "dt50": worst_t, "rows": rows}


def run_job(job):
    kind = job[0]
    if kind == "ibis":
        return ibis_check(job[1], job[2])
    if kind == "ref":
        rise, fall = bus.ref_delay(job[1], job[2])
        return {"rise": rise, "fall": fall}
    if kind == "line":
        _, n, t, f, c, d = job
        r = bus.run_line(bus.Backplane(slots=n), bus.TERMS[t], f, c, d)
        return {"slots": r["slots"], "worst": bus.worst({d: r})}
    if kind == "clock":
        _, f, rs, matched, c = job
        r = bus.run_clock(bus.Backplane(), f, c, f, rs, matched)
        return {"rise": r["rise"], "fall": r["fall"]}
    if kind == "xtalk":
        _, t, f, c, d, v, k = job
        r = noise.crosstalk(bus.Backplane(), bus.TERMS[t], f, c, d, v, k_conn=k)
        return {"worst": r["worst"], "slots": r["slots"]}
    if kind == "sso":
        _, t, f, c, pk, n, e = job
        r = noise.ground_bounce(bus.Backplane(), bus.TERMS[t], f, c, 0, packages=n,
                                package=pk, falling=(e == "falling"))
        return {k: r[k] for k in ("quiet", "die_gnd", "die_gnd_min", "card_gnd")}
    raise ValueError(kind)


def _cost(job):
    """Rough relative run time, for scheduling."""
    kind = job[0]
    if kind == "sso":
        return 4 * job[5]                       # per package of switching lines
    if kind == "line":
        return job[1] / 16
    return {"xtalk": 4, "clock": 1}.get(kind, 0.3)


def _recorded(fn, job):
    """Run a job, and note how many native runs and steps it took and how
    many steps Newton's method didn't converge in."""
    engine.reset_totals()
    res = fn(job)
    if isinstance(res, dict) and engine.current() == "native":
        res = dict(res, engine=dict(engine.totals))
    return res


def run_job_recorded(job):
    return _recorded(run_job, job)


def revised_job_recorded(job):
    from . import revised
    return _recorded(revised.run_job, job)


def _setup():
    # the IBIS files and the field solver, once per worker (cached on disk)
    for f in FAMILIES:
        ibis.load(f)
    bus.trace_params()


def timeout_for(name):
    """Per-job deadline (s): a native run takes seconds, an ngspice one
    normally under a minute."""
    return 120 if name == "native" else 300


def all_presets():
    """Every preset: report 0013's, then report 0022's."""
    from . import revised
    return list(PRESETS) + list(revised.PRESETS)


def run(preset, jobs_n=None, dry_run=False, retry_errors=False, limit=None, engine_name=None,
        timeout=None, budget=None):
    from . import revised
    engine_name = engine_name or engine.current()
    engine.use(engine_name)
    if preset in PRESETS:
        todo, fn, cost = jobs(preset), run_job_recorded, _cost
    else:
        todo, fn, cost = revised.jobs(preset), revised_job_recorded, revised.cost
        if engine_name != "native":
            raise SystemExit(f"preset {preset} is for the native engine")
    kinds = {}
    for j in todo:
        kinds[j[0]] = kinds.get(j[0], 0) + 1
    print(f"preset {preset} on {engine_name}: {len(todo)} jobs "
          f"({', '.join(f'{v} {k}' for k, v in kinds.items())})")
    # a run at another time step (HERON_SI_DT) is kept apart
    tag = f"{preset}-{engine_name}" + ("" if engine_name == "ngspice" or engine.DT == 5e-12
                                      else f"-dt{engine.DT * 1e12:g}ps")
    log = os.path.join(WORK, f"{tag}.jsonl")
    if dry_run:
        done = runner.load(log, retry_errors)
        print(f"{sum(1 for j in todo if runner.key(j) in done)} already done")
        return 0
    if engine_name == "ngspice" and not spice.have_ngspice():
        raise SystemExit("ngspice not found on PATH")
    _setup()                                    # download and solve once, before the workers fork
    print("trace:", {k: v for k, v in bus.trace_params().items() if k in ("z0", "tpd")}, flush=True)
    sel = todo
    if limit:
        done = runner.load(log, retry_errors)
        sel = [j for j in todo if runner.key(j) not in done][:limit]
    recs, n_err, wall, complete = runner.run(
        sel, fn, log, workers=jobs_n, timeout=timeout or timeout_for(engine_name),
        budget=budget, retry_errors=retry_errors, setup=_setup, cost=cost)
    done = runner.load(log)
    recs = [done[runner.key(j)] for j in todo if runner.key(j) in done]
    cpu = sum(r["seconds"] for r in recs)
    out_dir = OUT[engine_name]
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{preset}.json" if tag == f"{preset}-{engine_name}" else f"{tag}.json")
    with open(out, "w") as f:
        json.dump({"preset": preset, "engine": engine.version(), "jobs": len(todo), "complete": len(recs),
                   "errors": sum(1 for r in recs if r["error"]),
                   "wall_minutes_last_run": round(wall / 60, 1), "workers": jobs_n or os.cpu_count(),
                   "cpu_minutes": round(cpu / 60, 1), "records": recs}, f, separators=(",", ":"))
    print(f"wrote {out} ({len(recs)} of {len(todo)} jobs, {sum(1 for r in recs if r['error'])} errors)")
    return 1 if n_err or not complete else 0
