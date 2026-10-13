"""The Lisp study's command line: heron lisp <command> ...

  run    PROG.lisp [-c] [--stats] [--profile] [--input-file F]   run a program on the 1b
                                         simulator (-c: compiled)
  ref    PROG.lisp                       run it on the reference interpreter
  test   [NAME...] [-c] [-v] [--features F]   the programs and tests against their
                                         expected output
  build  [-l FILE.lst]                   assemble the runtime (and write a listing)
  report [--write] [NAME...]             the measurements behind report 0016
                                         (--write: its performance.md)
"""

import argparse
import sys

CONFIG = "D32-separate"         # the 1b hardware's configuration (report 0012)


def cmd_run(args):
    from . import machine, profile
    with open(args.file, "rb") as f:
        text = f.read()
    if args.input_file:
        with open(args.input_file, "rb") as f:
            text += f.read()
    features = [f for f in (args.features or "").split(",") if f]
    r = machine.run(text, features, max_cycles=args.max_cycles, compiled=args.compiled)
    sys.stdout.buffer.write(r.output)
    sys.stdout.flush()
    m = r.machine
    if args.stats or args.profile:
        st = r.stats()
        print(f"\n--- {m.instructions:,} instructions, {m.cycles_for(CONFIG):,} cycles ({CONFIG}), "
              f"{st['gc_count']} collections, {st['allocated']:,} bytes allocated, "
              f"{st['copied']:,} copied", file=sys.stderr)
    if args.profile:
        profile.print_profile(r, CONFIG)
    if r.error:
        print(f"\nerror: {r.error}", file=sys.stderr)
        print(m.regs_str(), file=sys.stderr)
        return 1
    return 0


def cmd_ref(args):
    from . import reference
    with open(args.file, "rb") as f:
        text = f.read()
    sys.stdout.buffer.write(reference.run(text))
    return 0


def cmd_test(args):
    from . import testing
    features = [f for f in (args.features or "").split(",") if f]
    return testing.run_suite(args.names, features, verbose=args.v, compiled=args.compiled)


def cmd_build(args):
    from . import build
    img = build.build([f for f in (args.features or "").split(",") if f])
    lo, hi = img.extent()
    print(f"image {lo:05X}-{hi - 1:05X}, {img.code_bytes()} bytes of runtime code")
    if args.l:
        with open(args.l, "w") as f:
            f.write(img.listing())
    return 0


def cmd_report(args):
    from . import report
    return report.main((["--write"] if args.write else []) + args.names)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    p = argparse.ArgumentParser(prog="heron lisp", description="A Lisp for draft 1b")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a program on the 1b simulator")
    r.add_argument("file")
    r.add_argument("--stats", action="store_true", help="instructions, cycles, collections")
    r.add_argument("--profile", action="store_true", help="where the cycles went")
    r.add_argument("--input-file", help="more console input, after the program")
    r.add_argument("--features", help="ISA experiments to build the runtime with (comma-separated)")
    r.add_argument("--max-cycles", type=int, default=5_000_000_000)
    r.add_argument("-c", "--compiled", action="store_true", help="load the compiler first: compile the program")
    r.set_defaults(fn=cmd_run)
    f = sub.add_parser("ref", help="run a program on the reference interpreter")
    f.add_argument("file")
    f.set_defaults(fn=cmd_ref)
    t = sub.add_parser("test", help="the programs and tests against their expected output")
    t.add_argument("names", nargs="*")
    t.add_argument("-v", action="store_true", help="show where the output differs")
    t.add_argument("-c", "--compiled", action="store_true", help="compile the programs")
    t.add_argument("--features", help="ISA experiments (comma-separated; isa.md)")
    t.set_defaults(fn=cmd_test)
    b = sub.add_parser("build", help="assemble the runtime")
    b.add_argument("-l", help="write a listing")
    b.add_argument("--features")
    b.set_defaults(fn=cmd_build)
    rp = sub.add_parser("report", help="the measurements behind report 0016")
    rp.add_argument("names", nargs="*")
    rp.add_argument("--write", action="store_true", help="write reports/0016-report-lisp/performance.md")
    rp.set_defaults(fn=cmd_report)
    args = p.parse_args(argv)
    return args.fn(args) or 0
