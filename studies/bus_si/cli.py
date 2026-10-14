"""heron bus_si ...: backplane signal-integrity simulation."""

import argparse
import os
import time

from . import bus, compare, sweep
from heron.infra.si import engine, ibis, spice


def cmd_check(args):
    """Is everything there, and how long will a sweep take?"""
    from heron import native
    print("native engine:", engine.version() if native.load() else "missing")
    v = spice.version()
    print("ngspice:", v or "not found (only needed for cross-checks: --engine ngspice)")
    for f in ibis.PARTS:
        m, _ = ibis.load(f)
        print(f"IBIS {ibis.PARTS[f]['name']}: {m.name}, {len(m.waveforms)} waveforms")
    t0 = time.time()
    tp = bus.trace_params()
    print(f"trace: Z0 {tp['z0']:.1f} ohm, {tp['tpd'] * 1e9:.2f} ps/mm "
          f"(closed form {tp['hammerstad_z0']:.1f} ohm) [{time.time() - t0:.0f} s]")
    for f in ("act", "abt"):
        t0 = time.time()
        r = sweep.ibis_check(f, "typ")
        print(f"IBIS check {f}: worst 50% time error {r['dt50'] * 1e9:.2f} ns, "
              f"methods {r['method']} [{time.time() - t0:.1f} s]")
    one = {}
    for e in ("native",) + (("ngspice",) if v else ()):
        engine.use(e)
        t0 = time.time()
        r = bus.run_line(bus.Backplane(), bus.TERMS["vme"], "abt", "min", 0)
        one[e] = time.time() - t0
        w = bus.worst({0: r})
        print(f"one bus line run on {e} (16 slots, ABT, VME terminators): {one[e]:.1f} s; "
              f"worst settle rise {w['rise'] * 1e9:.2f} ns, fall {w['fall'] * 1e9:.2f} ns")
    n = args.jobs or os.cpu_count() or 4
    for p in sweep.PRESETS:
        js = sweep.jobs(p)
        # rough weights: crosstalk ~4x a line run, ground bounce ~3x
        wt = sum({"xtalk": 4, "sso": 3, "ibis": 0.3, "ref": 0.3, "clock": 1}.get(j[0], 1) for j in js)
        est = ", ".join(f"{e} roughly {wt * t / n / 60:.0f} min" for e, t in one.items())
        print(f"preset {p}: {len(js)} jobs on {n} workers: {est}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron bus_si", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="check the engines and the models, time one run, estimate sweeps")
    c.add_argument("-j", "--jobs", type=int)
    c.set_defaults(fn=cmd_check)
    s = sub.add_parser("sweep", help="run a preset sweep (resumes an interrupted one)")
    s.add_argument("--preset", choices=sweep.all_presets(), default="quick")
    s.add_argument("--engine", choices=engine.ENGINES, default="native",
                   help="native (default) or ngspice, for cross-checks")
    s.add_argument("-j", "--jobs", type=int, help="parallel runs (default: all cores)")
    s.add_argument("--timeout", type=float, help="kill a job after this many seconds "
                   "(default 120 native, 300 ngspice)")
    s.add_argument("--budget", type=float, help="start no new jobs after this many minutes")
    s.add_argument("--dry-run", action="store_true", help="only count the jobs")
    s.add_argument("--retry-errors", action="store_true", help="rerun jobs that failed")
    s.add_argument("--limit", type=int, help="run at most this many jobs")
    s.set_defaults(fn=lambda a: sweep.run(a.preset, a.jobs, a.dry_run, a.retry_errors, a.limit, a.engine,
                                          a.timeout, a.budget * 60 if a.budget else None))
    k = sub.add_parser("compare", help="compare two results files of a preset, job by job")
    k.add_argument("a")
    k.add_argument("b")
    k.set_defaults(fn=lambda a: compare.main([a.a, a.b]))
    args = p.parse_args(argv)
    return args.fn(args)
