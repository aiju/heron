"""Running many simulation jobs in parallel, without getting stuck.

A supervisor hands jobs to worker processes, one at a time each, and
watches the clock:

- **Deadlines.** A job that runs past its deadline has its worker's whole
  process group killed (an ngspice child with it), is recorded as a
  timeout, and the worker is replaced. Nothing waits on a stuck job.
- **Resuming.** Each finished job is appended to a log (JSON lines) as it
  completes, so a stopped run carries on where it was.
- **A heartbeat.** Progress is printed at least every `heartbeat` seconds,
  with the oldest running job's age, so a quiet run is visibly alive.
- **A budget.** With `budget`, no new jobs start after that many seconds;
  the rest wait for the next run.

The job function runs in the workers: `fn(job) -> result` (JSON-able);
an exception is recorded as the job's error.
"""

import json
import math
import multiprocessing as mp
import os
import signal
import time
from multiprocessing.connection import wait

import numpy as np


def clean(x):
    """JSON-friendly, rounded."""
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        x = float(x)
        if math.isnan(x) or math.isinf(x):
            return None
        return round(x, 13) if abs(x) < 1e-6 else round(x, 4)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def key(job):
    return json.dumps(list(job))


def _serve(conn, fn, setup):
    # a group of its own, so that killing it takes any children too
    os.setpgrp()
    signal.signal(signal.SIGINT, signal.SIG_IGN)     # the supervisor handles Ctrl-C
    if setup:
        setup()
    while True:
        try:
            job = conn.recv()
        except EOFError:
            return
        if job is None:
            return
        t0 = time.time()
        try:
            res, err = clean(fn(job)), None
        except Exception as e:                       # noqa: BLE001 - keep the sweep going
            msg = str(e)
            if len(msg) > 600:
                msg = msg[:200] + " [...] " + msg[-350:]
            res, err = None, f"{type(e).__name__}: {msg}"
        conn.send({"job": list(job), "result": res, "error": err,
                   "seconds": round(time.time() - t0, 2)})


class _Worker:
    def __init__(self, ctx, fn, setup):
        self.conn, child = ctx.Pipe()
        self.proc = ctx.Process(target=_serve, args=(child, fn, setup), daemon=True)
        self.proc.start()
        child.close()
        self.job = None
        self.started = None

    def kill(self):
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        self.proc.kill()
        self.proc.join(5)
        self.conn.close()

    def stop(self):
        try:
            self.conn.send(None)
        except (BrokenPipeError, OSError):
            pass
        self.proc.join(5)
        if self.proc.is_alive():
            self.kill()


def load(log, retry_errors=False):
    """The finished records in a log, by job key."""
    done = {}
    if os.path.exists(log):
        with open(log) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue                         # a line cut short by a kill
                if rec.get("error") and retry_errors:
                    continue
                done[key(rec["job"])] = rec
    return done


def run(jobs, fn, log, workers=None, timeout=300, budget=None, heartbeat=30,
        retry_errors=False, setup=None, cost=None, out=print):
    """Run `fn` on every job not yet in `log`. Returns (records for all
    jobs that have one, by key; number of errors this run; wall seconds;
    whether every job is done). `timeout` is per job (s); `cost(job)`, if
    given, orders the jobs longest first."""
    os.makedirs(os.path.dirname(log) or ".", exist_ok=True)
    done = load(log, retry_errors)
    pending = [j for j in jobs if key(j) not in done]
    if cost:
        pending.sort(key=cost, reverse=True)
    workers = max(1, min(workers or os.cpu_count() or 4, len(pending) or 1))
    out(f"{len(jobs)} jobs, {len(jobs) - len(pending)} already done, {len(pending)} to run "
        f"on {workers} workers (deadline {timeout} s per job"
        + (f", budget {budget / 60:.0f} min)" if budget else ")"), flush=True)
    t0 = time.time()
    if not pending:
        return {key(j): done[key(j)] for j in jobs if key(j) in done}, 0, 0.0, True
    ctx = mp.get_context("fork" if hasattr(os, "fork") else "spawn")
    pool = [_Worker(ctx, fn, setup) for _ in range(workers)]
    todo = list(pending)
    n_done = n_err = n_timeout = 0
    last_beat = time.time()
    stopped = False
    with open(log, "a") as f:
        def record(rec):
            nonlocal n_done, n_err
            f.write(json.dumps(rec) + "\n")
            f.flush()
            done[key(rec["job"])] = rec
            n_done += 1
            if rec["error"]:
                n_err += 1
                out(f"  error in {rec['job']}: {rec['error'][:300]}", flush=True)

        try:
            while True:
                now = time.time()
                over = budget is not None and now - t0 > budget
                for w in pool:
                    if w.job is None and todo and not over and not stopped:
                        w.job = todo.pop(0)
                        w.started = time.time()
                        w.conn.send(w.job)
                busy = [w for w in pool if w.job is not None]
                if not busy:
                    break
                for conn in wait([w.conn for w in busy], timeout=1.0):
                    w = next(x for x in busy if x.conn is conn)
                    try:
                        rec = conn.recv()
                    except (EOFError, OSError):
                        rec = {"job": list(w.job), "result": None, "seconds": round(time.time() - w.started, 2),
                               "error": f"WorkerDied: exit code {w.proc.exitcode}"}
                        w.kill()
                        pool[pool.index(w)] = _Worker(ctx, fn, setup)
                    else:
                        w.job = None
                    record(rec)
                now = time.time()
                for i, w in enumerate(pool):
                    if w.job is not None and now - w.started > timeout:
                        n_timeout += 1
                        record({"job": list(w.job), "result": None, "seconds": round(now - w.started, 2),
                                "error": f"Timeout: killed after {timeout} s"})
                        w.kill()
                        pool[i] = _Worker(ctx, fn, setup)
                if now - last_beat >= heartbeat:
                    last_beat = now
                    el = now - t0
                    left = len(todo) + sum(1 for w in pool if w.job is not None)
                    eta = el / n_done * left if n_done else float("nan")
                    oldest = max((now - w.started for w in pool if w.job is not None), default=0)
                    out(f"  {n_done}/{len(pending)} done, {n_err} errors, {el / 60:.1f} min, "
                        f"~{eta / 60:.1f} min to go, oldest running job {oldest:.0f} s", flush=True)
        except KeyboardInterrupt:
            out("interrupted: the finished jobs are in the log; run again to carry on", flush=True)
            stopped = True
        finally:
            for w in pool:
                if w.job is not None:
                    w.kill()
                else:
                    w.stop()
    wall = time.time() - t0
    complete = all(key(j) in done for j in jobs)
    out(f"{n_done} jobs in {wall / 60:.1f} min, {n_err} errors ({n_timeout} timeouts)"
        + ("" if complete else f"; {sum(1 for j in jobs if key(j) not in done)} jobs not run yet"), flush=True)
    return {key(j): done[key(j)] for j in jobs if key(j) in done}, n_err, wall, complete
