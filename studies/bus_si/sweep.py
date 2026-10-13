"""Signal-integrity sweeps: many ngspice runs in parallel.

Each finished job is appended to build/si/<preset>.jsonl as it completes, so
an interrupted sweep picks up where it stopped. At the end the results are
written, compactly, to <preset>.json in report 0013's folder, which gets
committed. No tool reads them yet: the system bus RFC (0014, section 9)
summarises them by hand.
"""

import json
import math
import os
import time
from multiprocessing import Pool

import numpy as np

from heron import BUILD, ROOT
from heron.infra.si import ibis, spice

from . import bus, noise

WORK = os.path.join(BUILD, "si")
OUT = os.path.join(ROOT, "reports", "0013-report-bus-si")

FAMILIES = list(ibis.PARTS)
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


def _clean(x):
    """JSON-friendly, rounded."""
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        x = float(x)
        return None if math.isnan(x) else round(x, 13) if abs(x) < 1e-6 else round(x, 4)
    if isinstance(x, np.integer):
        return int(x)
    return x


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
        r = spice.run(lines, ["v(pad)"], t0 + w["t"][-1], maxstep=10e-12,
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
    return {"method": {e: m.method.get((e, corner)) for e in ("rising", "falling")},
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


def _worker(job):
    t0 = time.time()
    try:
        res, err = _clean(run_job(job)), None
    except Exception as e:                      # noqa: BLE001 - keep the sweep going
        msg = str(e)
        if len(msg) > 400:                      # what went wrong, and the end of ngspice's log
            msg = msg[:150] + " [...] " + msg[-250:]
        res, err = None, f"{type(e).__name__}: {msg}"
    return {"job": list(job), "result": res, "error": err, "seconds": round(time.time() - t0, 2)}


def _key(job):
    return json.dumps(list(job))


def _cost(job):
    """Rough relative run time, for scheduling."""
    kind = job[0]
    if kind == "sso":
        return 4 * job[5]                       # per package of switching lines
    if kind == "line":
        return job[1] / 16
    return {"xtalk": 4, "clock": 1}.get(kind, 0.3)


def run(preset, jobs_n=None, dry_run=False, retry_errors=False, limit=None):
    todo = jobs(preset)
    os.makedirs(WORK, exist_ok=True)
    log = os.path.join(WORK, f"{preset}.jsonl")
    done = {}
    if os.path.exists(log):
        with open(log) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec["error"] and retry_errors:
                    continue
                done[_key(rec["job"])] = rec
    pending = [j for j in todo if _key(list(j)) not in done]
    # longest first, so the slow crosstalk and ground-bounce runs overlap
    # with the many short ones instead of trailing at the end
    pending.sort(key=_cost, reverse=True)
    if limit:
        pending = pending[:limit]
    kinds = {}
    for j in todo:
        kinds[j[0]] = kinds.get(j[0], 0) + 1
    print(f"preset {preset}: {len(todo)} jobs ({', '.join(f'{v} {k}' for k, v in kinds.items())}), "
          f"{len(todo) - len(pending)} already done, {len(pending)} to run")
    if dry_run:
        return 0
    if not spice.have_ngspice():
        raise SystemExit("ngspice not found on PATH")
    jobs_n = jobs_n or os.cpu_count() or 4
    # everything the workers share, done once up front: the IBIS downloads
    # and the field solver (about a minute, cached in build/)
    for f in FAMILIES:
        ibis.load(f)
    print("trace:", {k: v for k, v in bus.trace_params().items() if k in ("z0", "tpd")})
    t0 = time.time()
    n_err = 0
    with open(log, "a") as f, Pool(jobs_n) as pool:
        for i, rec in enumerate(pool.imap_unordered(_worker, pending), 1):
            f.write(json.dumps(rec) + "\n")
            f.flush()
            done[_key(rec["job"])] = rec
            if rec["error"]:
                n_err += 1
                print(f"  error in {rec['job']}: {rec['error'][:200]}")
            if i % 10 == 0 or i == len(pending):
                el = time.time() - t0
                print(f"  {i}/{len(pending)} done, {el / 60:.1f} min, "
                      f"~{el / i * (len(pending) - i) / 60:.1f} min to go", flush=True)
    wall = time.time() - t0
    recs = [done[_key(list(j))] for j in todo if _key(list(j)) in done]
    cpu = sum(r["seconds"] for r in recs)
    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, f"{preset}.json")
    with open(out, "w") as f:
        json.dump({"preset": preset, "jobs": len(todo), "complete": len(recs),
                   "errors": sum(1 for r in recs if r["error"]),
                   "wall_minutes_last_run": round(wall / 60, 1), "workers": jobs_n,
                   "cpu_minutes": round(cpu / 60, 1),
                   "ngspice": spice.version(), "records": recs}, f, separators=(",", ":"))
    print(f"{len(pending)} jobs in {wall / 60:.1f} min on {jobs_n} workers "
          f"({cpu / 60:.1f} CPU-min in all records), {n_err} errors; wrote {out}")
    return 1 if n_err else 0
