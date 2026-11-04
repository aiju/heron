"""The benchmark's command line: heron bench <command> ...

  list                                  the workloads
  run      NAME [--size S] [--stats]    run one on the instruction-level simulator
  test     [NAME...] [--size S]         every workload against its expected output
  expected [NAME...] [--size S]         write the expected outputs from the host
                                        references (gcc, or the workload's Python)
  stats    [NAME...] [--size S]         size, instruction mix and reference cycles
  time     [NAME...] [--size S] [--on M] [--jobs N] [--force]
                                        absolute times on an implementation
                                        (M: v2_hw, Full Heron's register-transfer
                                        model; cached in build/bench/)
  report   [--write]                    the tables of the results page

Sizes are `test` (tens of thousands of instructions, for the chip-level
simulators) and `ref` (hundreds of thousands, the one the results quote).
"""

import argparse
import sys

from . import suite


def _sizes(args):
    return suite.SIZES if args.size == "all" else (args.size,)


def cmd_list(args):
    for w in suite.workloads():
        print(f"{w.name:<14} {w.part:<4} {w.category:<14} {w.title}")
    return 0


def cmd_run(args):
    w = suite.get(args.name)
    r = suite.run(w, args.size)
    sys.stdout.write(r.output.decode("latin-1"))
    m = r.machine
    print(f"--- {w.name} ({args.size}): {m.instructions} instructions, "
          f"{m.cycles} cycles", file=sys.stderr)
    if args.stats:
        _print_stats(suite.stats(r))
        if args.profile:
            _print_profile(r)
    if not r.ok:
        print(f"error: {r.error}", file=sys.stderr)
        return 1
    return 0


def _print_stats(s):
    print(f"code {s['code_bytes']} bytes, {s['code_touched']} executed; image "
          f"{s['image_bytes']} bytes; stack {s['stack_bytes']} bytes", file=sys.stderr)
    n = s["instructions"]
    for k, c in sorted(s["kinds"].items(), key=lambda kv: -kv[1]):
        print(f"  {k:<18} {c:>9} {100 * c / n:5.1f}%", file=sys.stderr)


def _print_profile(r):
    import bisect
    from collections import Counter
    from heron.studies.v2_isa import sim
    m, img = r.machine, r.image
    labels = sorted((a, n) for n, a in img.symbols.items() if "." not in n)
    starts = [a for a, _ in labels]
    per = Counter()
    pcc = m.pc_cycles(sim.REFERENCE)
    total = sum(pcc.values()) or 1
    for pc, c in pcc.items():
        i = bisect.bisect_right(starts, pc or 0) - 1
        per[labels[i][1] if i >= 0 else "?"] += c
    print("cycles by routine:", file=sys.stderr)
    for k, c in per.most_common(20):
        print(f"  {k:<28} {c:>10} {100 * c / total:5.1f}%", file=sys.stderr)


def cmd_test(args):
    failed = 0
    for w in suite.workloads(args.names or None):
        for size in _sizes(args):
            try:
                r = suite.run(w, size)
            except suite.BenchError as e:
                print(f"{w.name:<14} {size:<5} FAIL  {e}")
                failed += 1
                continue
            m = r.machine
            status = "ok" if r.ok else "FAIL"
            print(f"{w.name:<14} {size:<5} {status:<5} {m.instructions:>10} instr "
                  f"{m.cycles:>11} cycles" + ("" if r.ok else f"  {r.error}"))
            failed += not r.ok
    return 1 if failed else 0


def cmd_expected(args):
    for w in suite.workloads(args.names or None):
        for size, n in suite.write_expected(w, _sizes(args)):
            print(f"{w.name:<14} {size:<5} {n} bytes")
    return 0


def cmd_stats(args):
    for w in suite.workloads(args.names or None):
        for size in _sizes(args):
            r = suite.run(w, size)
            print(f"{w.name} ({size}): {r.machine.instructions} instructions"
                  + ("" if r.ok else f"  FAIL {r.error}"), file=sys.stderr)
            _print_stats(suite.stats(r))
    return 0


def cmd_time(args):
    from . import targets
    rows = targets.times(args.on, [w.name for w in suite.workloads(args.names or None)],
                         args.size, jobs=args.jobs, force=args.force)
    bad = 0
    for row in rows:
        ok = row["ok"]
        bad += not ok
        print(f"{row['name']:<14} {row['instructions']:>10} instr {row['cycles']:>10} cycles "
              f"{row['ms']:9.2f} ms" + ("" if ok else "  FAIL: output differs"))
    return 1 if bad else 0


def cmd_report(args):
    from . import report
    return report.main(write=args.write)


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron bench", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    r = sub.add_parser("run")
    r.add_argument("name")
    r.add_argument("--size", choices=suite.SIZES, default="ref")
    r.add_argument("--stats", action="store_true")
    r.add_argument("--profile", action="store_true", help="with --stats: cycles by routine")
    r.set_defaults(fn=cmd_run)
    for name, fn, default in (("test", cmd_test, "all"), ("expected", cmd_expected, "all"),
                              ("stats", cmd_stats, "ref")):
        t = sub.add_parser(name)
        t.add_argument("names", nargs="*")
        t.add_argument("--size", choices=suite.SIZES + ("all",), default=default)
        t.set_defaults(fn=fn)
    t = sub.add_parser("time")
    t.add_argument("names", nargs="*")
    t.add_argument("--size", choices=suite.SIZES, default="ref")
    t.add_argument("--on", default="v2_hw")
    t.add_argument("--jobs", type=int, default=4)
    t.add_argument("--force", action="store_true")
    t.set_defaults(fn=cmd_time)
    t = sub.add_parser("report")
    t.add_argument("--write", action="store_true")
    t.set_defaults(fn=cmd_report)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except suite.BenchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
