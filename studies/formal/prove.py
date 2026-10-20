"""Prove the draft 1b hardware's decode cases, in parallel.

    heron formal prove [--kind ea] [--key "ea 4 None 0 None"] [--sample N]
                       [--jobs 4] [--budget 600] [--out FILE]

Each case runs in a process of its own, killed if it takes longer than
the budget. Results go to build/formal/v1b-results.json (or --out), one
entry per case, merged with what is there already.
"""

import argparse
import json
import multiprocessing as mp
import os
import random
import time

from heron import BUILD

from . import v1b

DEFAULT_OUT = os.path.join(BUILD, "formal", "v1b-results.json")


def _work(case, budget_ms, conn):
    try:
        r = v1b.prove_case(case, timeout_ms=budget_ms)
        conn.send({"status": r.status, "seconds": r.seconds, "paths": r.paths,
                   "error": r.error})
    except Exception as e:                 # noqa: BLE001  (report anything)
        conn.send({"status": "error", "seconds": 0, "paths": [], "error": repr(e)})
    conn.close()


def run(cases, jobs=4, budget=600, out=DEFAULT_OUT, quiet=False):
    """Prove `cases`, `jobs` at a time; returns {case name: result dict}."""
    ctx = mp.get_context("fork")
    results = load(out)
    pending = list(cases)
    running = []
    t0 = time.time()
    done = 0

    def finish(case, res):
        nonlocal done
        done += 1
        res["free"] = case.free
        res["length"] = case.length
        results[case.name()] = res
        if not quiet:
            paths = res["paths"]
            cyc = max((p[1] for p in paths), default=0)
            print(f"[{done}/{len(cases)} {time.time() - t0:6.0f}s] {case.name():<34} "
                  f"{res['status']:<8} {res['seconds']:7.1f}s  {len(paths)} paths, "
                  f"up to {cyc} cycles  {res.get('error') or _detail(paths)}", flush=True)
        save(results, out)

    while pending or running:
        while pending and len(running) < jobs:
            case = pending.pop(0)
            a, b = ctx.Pipe(duplex=False)
            p = ctx.Process(target=_work, args=(case, budget * 1000, b))
            p.start()
            b.close()
            running.append((case, p, a, time.time()))
        time.sleep(0.05)
        for item in list(running):
            case, p, conn, started = item
            if conn.poll():
                res = conn.recv()
                p.join()
                running.remove(item)
                finish(case, res)
            elif not p.is_alive():
                running.remove(item)
                finish(case, {"status": "error", "seconds": time.time() - started, "paths": [],
                              "error": f"worker died ({p.exitcode})"})
            elif time.time() - started > budget:
                p.kill()
                p.join()
                running.remove(item)
                finish(case, {"status": "budget", "seconds": time.time() - started,
                              "paths": [], "error": f"over the budget of {budget} s"})
    return results


def _detail(paths):
    bad = [p for p in paths if p[0] != "proved"]
    return bad[0][2][:100] if bad else ""


def load(out):
    if os.path.exists(out):
        with open(out) as f:
            return json.load(f)
    return {}


def save(results, out):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w") as f:
        json.dump(results, f, indent=0, sort_keys=True)
    os.replace(tmp, out)


def slow_last(c):
    """The kinds of case known to run out of time go last, so that a run
    has most of its results early: illegal instructions, then multiply and
    divide, then the indexed mode."""
    if c.key[0] == "illegal":
        return 3
    if c.key[0] == "rr" and c.key[1] >= 4:
        return 2
    return 1 if c.key[0] == "ea" and c.key[3] == 5 else 0


def select(kind=None, keys=None, sample=None, seed=1, skip_done=None):
    cs = sorted(v1b.cases(), key=slow_last)
    if kind:
        cs = [c for c in cs if c.key[0] == kind]
    if keys:
        cs = [c for c in cs if c.name() in keys]
    if skip_done:
        cs = [c for c in cs if c.name() not in skip_done]
    if sample is not None and sample < len(cs):
        cs = random.Random(seed).sample(cs, sample)
    return cs


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron formal prove")
    p.add_argument("--kind", help="only routines of this kind (ea, sys, shift, un, rr, ...)")
    p.add_argument("--key", action="append", help="one case by its routine key (repeatable)")
    p.add_argument("--sample", type=int, help="a random sample of the cases")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--budget", type=int, default=900, help="seconds per case")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--resume", action="store_true", help="skip cases already in the results")
    args = p.parse_args(argv)
    v1b.netlist()
    v1b.roms()
    done = load(args.out) if args.resume else None
    cs = select(args.kind, args.key, args.sample, args.seed, done)
    res = run(cs, args.jobs, args.budget, args.out)
    counts = {}
    for c in cs:
        s = res[c.name()]["status"]
        counts[s] = counts.get(s, 0) + 1
    print(", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return 0
