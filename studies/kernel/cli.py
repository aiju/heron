"""The kernel study's command line: heron kernel <command> ...

  run PROG[:ARG[:ARG2]] ... [--banks none|half|full] [--softtlb] [--timer N]
          [--io N] [--shared N] [--stats]
                    boot the nucleus with these user programs (user/*.s) as
                    processes, and print what they write
  bench [NAME...] [--banks B]   the nucleus's hot paths, cycles per
                    operation and by routine (bench.py)
  micro             zeroing and copying pages, linkage, coroutines on
                    plain 1a and 1b (micro.py)
  pages [NAME...]   page references of the other studies' bigger programs
                    (pages.py)
  report [--write]  report 0020's tables (--write: its performance.md)
"""

import argparse
import sys

from . import build


def cmd_run(args):
    from . import bench
    features = [args.banks] + (["softtlb"] if args.softtlb else [])
    procs = []
    for i, spec in enumerate(args.progs):
        parts = spec.split(":")
        flags = 0
        if i + 1 in args.io:
            flags |= build.F_IO
        if i + 1 in args.shared:
            flags |= build.F_SHARED
        procs.append(build.Proc(parts[0], int(parts[1], 0) if len(parts) > 1 else 0,
                                flags=flags, arg2=int(parts[2], 0) if len(parts) > 2 else 0))
    r = bench.run(features, procs, timer=args.timer)
    sys.stdout.buffer.write(bytes(r.m.dev.out))
    sys.stdout.flush()
    if args.stats:
        m = r.m
        print(f"\n--- {m.instructions:,} instructions, {m.cycles_for(bench.CONFIG):,} cycles "
              f"({bench.CONFIG}), {m.irqs} interrupts, {m._m.sys['page_faults']} page faults; "
              f"{r.word('n_exit')} of {len(procs)} threads ended (the rest wait)",
              file=sys.stderr)
        prof = bench.profile(r)
        for k, v in prof.most_common(15):
            print(f"  {k:24} {v:12,}", file=sys.stderr)
    for p in r.problems():
        print(f"\nproblem: {p}", file=sys.stderr)
    return 1 if r.problems() else 0


def cmd_bench(args):
    from . import bench
    names = args.names or [s.name for s in bench.SCENARIOS]
    for name in names:
        for b in ([args.banks] if args.banks else build.BANKS):
            r = bench.measure(name, b)
            top = sorted(r.by_routine.items(), key=lambda kv: -kv[1])[:6]
            print(f"{name:9} {b:5} {r.per_op[bench.CONFIG]:8.1f}  "
                  + "  ".join(f"{k}={v:.1f}" for k, v in top))
    return 0


def cmd_micro(args):
    from . import micro
    t = micro.table()
    for name, d in t.items():
        texts, base, _ = micro.ROUTINES[name]
        texts = [x for i, x in enumerate(texts) if i != base]
        for i, text in enumerate(texts):
            print(f"{name:9} {text:52} " + "  ".join(
                f"{isa} " + " / ".join(f"{d[isa][i][c]:7.0f}" for c in micro.CONFIGS)
                for isa in ("v1a", "v1b")))
    print(f"(cycles per iteration: {', '.join(micro.CONFIGS)})")
    return 0


def cmd_pages(args):
    from . import pages
    print(pages.table(pages.measure(args.names or None)))
    return 0


def cmd_report(args):
    from . import report
    return report.main(write=args.write)


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron kernel",
                                description="An operating system for Heron: the benchmark nucleus")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="boot the nucleus with user programs")
    r.add_argument("progs", nargs="+", help="user/NAME.s, with :ARG (r1) and :ARG2 (r2)")
    r.add_argument("--banks", choices=build.BANKS, default="half")
    r.add_argument("--softtlb", action="store_true")
    r.add_argument("--timer", type=int, default=0, help="timer period (0: off)")
    r.add_argument("--io", type=int, action="append", default=[],
                   help="give process N (from 1) the I/O page")
    r.add_argument("--shared", type=int, action="append", default=[],
                   help="give process N the shared pages")
    r.add_argument("--stats", action="store_true")
    b = sub.add_parser("bench", help="the nucleus's hot paths")
    b.add_argument("names", nargs="*")
    b.add_argument("--banks", choices=build.BANKS)
    sub.add_parser("micro", help="small routines on plain 1a and 1b")
    g = sub.add_parser("pages", help="page references of bigger programs")
    g.add_argument("names", nargs="*")
    w = sub.add_parser("report", help="report 0020's tables")
    w.add_argument("--write", action="store_true")
    args = p.parse_args(argv)
    return {"run": cmd_run, "bench": cmd_bench, "micro": cmd_micro, "pages": cmd_pages,
            "report": cmd_report}[args.cmd](args)
