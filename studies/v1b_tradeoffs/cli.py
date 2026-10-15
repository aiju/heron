"""The study's command line: heron v1b_tradeoffs <command> ...

  report [--write] [--hw] [--jobs N]
                        the generated tables of RFC 0024 (--write: into
                        its results.md; --hw: run the three systems'
                        suites at chip level first, about 30 minutes)
  parts [SET...] [--corner C] [--path]
                        static timing of the 1b CPU with other parts (the
                        sets in parts.py), and the suite's time
  cpu ARGS...           v1b_hw's chip-level tools (heron v1b_hw hw ...)
                        with these sets as --variant too; "exercise" for
                        the exercise program's path, e.g.
                        cpu sweep exercise --variant fast --lo 95 --hi 115
  fast [--parts SET] lengths      the fast system's length classes
  fast [--parts SET] run PROG.s   one program on the fast system at chip level
  fast [--parts SET] test [NAMES] the suite on the fast system at chip level
                        (SET: fast, the default, or fast-flash)
"""

import argparse
import os
import sys


def cmd_parts(argv):
    from . import parts, timing
    p = argparse.ArgumentParser(prog="heron v1b_tradeoffs parts")
    p.add_argument("sets", nargs="*", default=list(parts.DESCRIBE))
    p.add_argument("--corner", default="max", choices=["max", "typ"])
    p.add_argument("--path", action="store_true", help="the slowest path of each set")
    a = p.parse_args(argv)
    for r in timing.table(a.sets, (a.corner,)):
        print(f"{r['set']:<12} {r['corner']}: period {r['period']:6.1f} ns; suite fixed "
              f"{r['fixed']:.3f} s, ideal {r['ideal']:.3f} s, 4 classes {r['classes']:.3f} s "
              f"({', '.join(map(str, r['lengths']))} ticks)")
        if a.path:
            print(timing.critical_path(r["set"], a.corner))
    return 0


def cmd_fast(argv):
    from . import fastsys
    p = argparse.ArgumentParser(prog="heron v1b_tradeoffs fast")
    p.add_argument("--parts", default=fastsys.VARIANT, choices=fastsys.SETS)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("lengths")
    r = sub.add_parser("run")
    r.add_argument("file")
    r.add_argument("--max-cycles", type=int, default=20_000_000)
    t = sub.add_parser("test")
    t.add_argument("names", nargs="*")
    t.add_argument("--jobs", type=int, default=4)
    a = p.parse_args(argv)
    if a.cmd == "lengths":
        _cls, d = fastsys.classes(a.parts)
        print(f"length classes: {d['lengths']} ticks of 20 ns; the suite's microcycles in "
              f"{d['ticks'] * 20e-9:.3f} s ({d['fixed_ticks'] * 20e-9:.3f} s at a fixed "
              f"{max(d['lengths'])} ticks)")
        return 0
    if a.cmd == "run":
        diffs, hw, _m = fastsys.check(a.file, max_cycles=a.max_cycles, variant=a.parts)
        print(f"{os.path.basename(a.file)}: {hw['cycles']} cycles, {hw['time_ps'] / 1e6:.1f} us, "
              f"{hw['violation_total']} timing violations")
        for d in diffs:
            print("  " + d)
        return 1 if diffs or hw["violation_total"] else 0
    fails = 0
    for name, (diffs, hw) in sorted(fastsys.test(a.names, a.jobs, a.parts).items()):
        ok = not diffs and hw and not hw["violation_total"]
        fails += not ok
        if hw:
            print(f"{name:<12} {'ok' if ok else 'FAIL':<5} {hw['cycles']:>9} cycles "
                  f"{hw['time_ps'] / 1e9:8.3f} ms  violations {hw['violation_total']}")
        for d in diffs:
            print("    " + d)
    return 1 if fails else 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "report":
        from . import report
        return report.main(rest)
    if cmd == "parts":
        return cmd_parts(rest)
    if cmd == "fast":
        return cmd_fast(rest)
    if cmd == "cpu":
        from heron.infra.hw import runner
        from heron.studies.v1b_hw import check, machine
        from . import parts  # noqa: F401  (registers the sets)
        rest = [check.exercise_path() if x == "exercise" else x for x in rest]
        return runner.main(rest, machine, prog="heron v1b_tradeoffs cpu")
    print(f"heron v1b_tradeoffs: no command {cmd!r}", file=sys.stderr)
    return 2
