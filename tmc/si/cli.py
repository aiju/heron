"""python3 -m tmc si ...: backplane signal-integrity simulation."""

import argparse
import os
import time

from . import bus, ibis, spice, sweep


def cmd_check(args):
    """Is everything there, and how long will a sweep take?"""
    v = spice.version()
    if not v:
        raise SystemExit("ngspice not found on PATH (see tmc/si/README.md)")
    print("ngspice:", v)
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
    t0 = time.time()
    r = bus.run_line(bus.Backplane(), bus.TERMS["vme"], "abt", "min", 0)
    one = time.time() - t0
    w = bus.worst({0: r})
    print(f"one bus line run (16 slots, ABT, VME terminators): {one:.1f} s; "
          f"worst settle rise {w['rise'] * 1e9:.1f} ns, fall {w['fall'] * 1e9:.1f} ns")
    n = args.jobs or os.cpu_count() or 4
    for p in sweep.PRESETS:
        js = sweep.jobs(p)
        # rough weights: crosstalk ~4x a line run, ground bounce ~3x
        wt = sum({"xtalk": 4, "sso": 3, "ibis": 0.3, "ref": 0.3, "clock": 1}.get(j[0], 1) for j in js)
        print(f"preset {p}: {len(js)} jobs, roughly {wt * one / n / 60:.0f} min on {n} workers")
    return 0


def main(argv):
    p = argparse.ArgumentParser(prog="tmc si", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="check ngspice and the models, time one run, estimate sweeps")
    c.add_argument("-j", "--jobs", type=int)
    c.set_defaults(fn=cmd_check)
    s = sub.add_parser("sweep", help="run a preset sweep (resumes an interrupted one)")
    s.add_argument("--preset", choices=list(sweep.PRESETS), default="quick")
    s.add_argument("-j", "--jobs", type=int, help="parallel ngspice runs (default: all cores)")
    s.add_argument("--dry-run", action="store_true", help="only count the jobs")
    s.add_argument("--retry-errors", action="store_true", help="rerun jobs that failed")
    s.add_argument("--limit", type=int, help="run at most this many jobs")
    s.set_defaults(fn=lambda a: sweep.run(a.preset, a.jobs, a.dry_run, a.retry_errors, a.limit))
    args = p.parse_args(argv)
    return args.fn(args)
