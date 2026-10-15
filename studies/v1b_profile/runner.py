"""Collecting traces: each one runs in a worker process, and the parent
stores what it found in the database.

    collect_one(name) -> (trace row, tables)
    collect(names, db, jobs)
"""

import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

from heron.infra import isas

from . import collect as C


def _isa(name):
    # the variants register when their studies are imported
    if name == "v1bx":
        import heron.studies.lisp  # noqa: F401
    elif name == "v1bs":
        import heron.studies.kernel  # noqa: F401
    return isas.get(name)


def collect_one(name, shadow=True):
    """Run one trace with a profile attached: (trace row, tables)."""
    from .traces import by_name
    t = by_name(name)
    attached = []

    def attach(m):
        attached.append(C.attach(m, shadow))

    t0 = time.time()
    done, error = None, None
    try:
        done = t.run(attach)
    except Exception:
        error = traceback.format_exc(limit=8)
    seconds = time.time() - t0
    if not attached:
        raise RuntimeError(f"{name}: no machine was made\n{error or ''}")
    res = C.results(attached[-1])
    isa_name = done.isa if done else t.isa
    syms = done.symbols if done else C.Symbols()
    tables = C.rows(res, syms, _isa(isa_name))
    tot = C.totals(res)
    notes = [n for n in (done.notes if done else None, tot.pop("notes"), error) if n]
    out = done.output if done else b""
    row = dict(name=t.name, study=t.study, program=t.program, variant=t.variant,
               language=t.language, isa=isa_name, description=t.description,
               input=t.input or None, ok=None if done is None or done.ok is None else int(done.ok),
               output=out[:4096].decode("latin-1") or None, notes="\n".join(notes) or None,
               seconds=round(seconds, 2), source=C.source_id(), **tot)
    if error:
        row["ok"] = 0
    return row, tables


def _job(name, shadow):
    try:
        return name, collect_one(name, shadow), None
    except Exception:
        return name, None, traceback.format_exc(limit=8)


def prepare(traces, log=print):
    """Build what the traces share (VM images, the Lisp's cores) once."""
    seen = set()
    for t in traces:
        p = t.prepare
        if p is None:
            continue
        key = (getattr(p, "func", p).__name__, getattr(p, "args", ()))
        if key in seen:
            continue
        seen.add(key)
        log(f"preparing {key[0]}{key[1] or ''}")
        p()


def collect(traces, db_path=C.DB_PATH, jobs=None, shadow=True, log=print):
    """Collect the traces into the database, the heaviest first. Returns
    the names that failed."""
    traces = sorted(traces, key=lambda t: -t.weight)
    prepare(traces, log)
    db = C.Database(db_path)
    failed = []
    jobs = jobs or os.cpu_count() or 1
    t0 = time.time()

    def store(name, result, err):
        if err:
            failed.append(name)
            log(f"{name:<34} FAILED\n{err}")
            return
        row, tables = result
        db.store(row, tables)
        ok = {None: "-", 1: "ok", 0: "WRONG"}[row["ok"]]
        warn = ""
        if row["mismatches"] or row["shadow_errors"]:
            warn = f"  shadow: {row['mismatches']} mismatches, {row['shadow_errors']} errors"
        log(f"{name:<34} {ok:<5} {row['instructions']:>12,} instructions {row['hw_cycles']:>14,} "
            f"hw cycles {row['seconds']:>7.1f} s{warn}")

    try:
        if jobs == 1:
            for t in traces:
                store(*_job(t.name, shadow))
        else:
            with ProcessPoolExecutor(jobs) as ex:
                futs = [ex.submit(_job, t.name, shadow) for t in traces]
                for f in as_completed(futs):
                    store(*f.result())
    finally:
        db.prune()
        db.close()
    log(f"{len(traces) - len(failed)} of {len(traces)} traces in {db_path} ({time.time() - t0:.0f} s)")
    return failed


if __name__ == "__main__":
    collect_one(sys.argv[1])
