"""The instruction profiles' command line: heron v1b_profile <command> ...

  list    [PATTERN...]                the traces there are, and which the database has
  collect [PATTERN...] [--exclude P] [--jobs N] [--db PATH] [--missing] [--no-shadow]
                                      run them with profiles attached, into the database
  sql     QUERY [--db PATH]           a query, printed as a table
  summary [--db PATH]                 the traces in the database
  merge   OTHER.db... [--db PATH]     copy the traces of other databases into this one
                                      (replacing those of the same name)

PATTERN is a trace name, a prefix of one (`lisp`, `egret/fib`) or a glob
(`*/compiled`). The database is build/v1b_profile/profile.db unless --db
says otherwise.
"""

import argparse
import sqlite3
import sys

from . import collect as C


def table(cur, limit=None, out=sys.stdout):
    """Print a query's rows as an aligned table."""
    cols = [d[0] for d in cur.description or []]
    rows = cur.fetchall() if limit is None else cur.fetchmany(limit)

    def fmt(v):
        if v is None:
            return ""
        if isinstance(v, float):
            return f"{v:,.2f}"
        if isinstance(v, int):
            return f"{v:,}"
        return str(v)
    cells = [[fmt(v) for v in r] for r in rows]
    widths = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(cols)]
    nums = [all(isinstance(r[i], (int, float)) or r[i] is None for r in rows) for i in range(len(cols))]
    print("  ".join(c.rjust(w) if n else c.ljust(w) for c, w, n in zip(cols, widths, nums)), file=out)
    print("  ".join("-" * w for w in widths), file=out)
    for r in cells:
        print("  ".join(c.rjust(w) if n else c.ljust(w) for c, w, n in zip(r, widths, nums)).rstrip(),
              file=out)


SUMMARY = """
SELECT name, isa, ok, instructions, static_insns AS static, hw_cycles,
       ROUND(1.0 * hw_cycles / instructions, 2) AS hw_cpi, d32_sep, irqs, mismatches AS mism,
       seconds
FROM trace ORDER BY name
"""


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron v1b_profile",
                                description="Instruction profiles of draft 1b programs")
    sub = p.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="the traces, and which the database has")
    ls.add_argument("patterns", nargs="*")
    ls.add_argument("--db", default=C.DB_PATH)
    co = sub.add_parser("collect", help="run traces with profiles attached, into the database")
    co.add_argument("patterns", nargs="*")
    co.add_argument("--exclude", action="append", default=[], metavar="PATTERN")
    co.add_argument("--jobs", type=int, default=None)
    co.add_argument("--db", default=C.DB_PATH)
    co.add_argument("--missing", action="store_true", help="only those not in the database")
    co.add_argument("--no-shadow", action="store_true",
                    help="without the hardware shadow (no hardware cycles; faster)")
    q = sub.add_parser("sql", help="run a query on the database")
    q.add_argument("query")
    q.add_argument("--db", default=C.DB_PATH)
    q.add_argument("--limit", type=int, default=None)
    sm = sub.add_parser("summary", help="the traces in the database")
    sm.add_argument("--db", default=C.DB_PATH)
    mg = sub.add_parser("merge", help="copy the traces of other databases into this one")
    mg.add_argument("others", nargs="+")
    mg.add_argument("--db", default=C.DB_PATH)
    a = p.parse_args(argv)

    if a.cmd == "merge":
        db = C.Database(a.db)
        for path in a.others:
            other = C.Database(path)
            names = other.names()
            for name in names:
                db.store(*other.load(name))
            other.close()
            print(f"{len(names)} traces from {path}")
        db.prune()
        db.close()
        return 0

    if a.cmd in ("list", "collect"):
        from . import traces
        ts = traces.select(a.patterns, getattr(a, "exclude", None))
        have = set()
        try:
            db = C.Database(a.db)
            have = set(db.names())
            db.close()
        except sqlite3.Error:
            pass
        if a.cmd == "list":
            for t in ts:
                print(f"{'*' if t.name in have else ' '} {t.name:<34} {t.isa:<5} {t.description[:90]}")
            print(f"{len(ts)} traces, {len(have & {t.name for t in ts})} in {a.db} (*)")
            return 0
        if a.missing:
            ts = [t for t in ts if t.name not in have]
        if not ts:
            print("no traces to collect")
            return 0
        from . import runner
        failed = runner.collect(ts, a.db, a.jobs, shadow=not a.no_shadow)
        return 1 if failed else 0

    con = sqlite3.connect(a.db)
    try:
        cur = con.execute(SUMMARY if a.cmd == "summary" else a.query)
        table(cur, getattr(a, "limit", None))
    except sqlite3.Error as e:
        print(f"heron v1b_profile: {e}", file=sys.stderr)
        return 1
    finally:
        con.close()
    return 0
