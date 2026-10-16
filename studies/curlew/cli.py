"""Curlew's command line: heron curlew <command> ...

  run    PROG.cw [--features F,G] [--stats] [--profile] [--input-file F]
                     compile a program and run it on the draft 2 simulator
  ref    PROG.cw [--input-file F]
                     run it on the reference interpreter
  test   [NAME...] [--features F,G] [-v]
                     the programs and tests against their expected output
  asm    PROG.cw [--features F,G] [-o FILE]
                     the generated assembly
  core   PROG.cw [--stage desugared|simplified|lifted]
                     the program in Core, after a stage (lifted: what the
                     code generator gets)
  report [--write]   the measurements of the report (--write: its tables)

A program's input is the file its `-- input: FILE` line names, or
--input-file. The features are build.FEATURES: the ISA experiments
(tagged, onereg, nostackcheck, ...) and the optimiser's switches.
"""

import argparse
import sys

from .lexer import CurlewError


def features_of(args):
    return [f for f in (args.features or "").split(",") if f]


def load(args):
    from . import testing
    p = testing.Program(args.file)
    if args.input_file:
        with open(args.input_file, "rb") as f:
            p.input = f.read()
    return p


def cmd_run(args):
    from . import machine, profile
    p = load(args)
    r = machine.run(p.text, p.input, features_of(args), max_cycles=args.max_cycles)
    sys.stdout.buffer.write(r.output)
    sys.stdout.flush()
    m = r.machine
    if args.stats or args.profile:
        st = r.stats()
        print(f"\n--- {m.instructions:,} instructions, {m.cycles_for(machine.CONFIG):,} cycles "
              f"({machine.CONFIG}), {st['gc_count']} collections, {st['allocated']:,} bytes allocated, "
              f"{st['copied']:,} copied" + (f", {st['tag_traps']:,} tag traps" if st["tag_traps"] else ""),
              file=sys.stderr)
    if args.profile:
        profile.print_profile(r, sys.stderr)
    if r.error:
        print(f"\nerror: {r.error}", file=sys.stderr)
        print(m.regs_str(), file=sys.stderr)
        return 1
    return 0


def cmd_ref(args):
    from . import reference
    p = load(args)
    sys.stdout.buffer.write(reference.run(p.text, p.input))
    return 0


def cmd_test(args):
    from . import testing
    return testing.run_suite(args.names, features_of(args), verbose=args.v)


def cmd_asm(args):
    from . import build
    p = load(args)
    c = build.compile_program(p.text, features_of(args))
    if args.o:
        with open(args.o, "w") as f:
            f.write(c.asm)
    else:
        sys.stdout.write(c.asm)
    return 0


def cmd_core(args):
    from . import build, core
    p = load(args)
    c = build.compile_core(p.text, build.Options(features_of(args)))
    prog = {"desugared": c.core, "simplified": c.simplified, "lifted": c.lifted}[args.stage]
    print(core.show_program(prog))
    return 0


def cmd_report(args):
    from . import report
    return report.main(["--write"] if args.write else [])


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron curlew", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("run", "ref", "asm", "core"):
        s = sub.add_parser(name)
        s.add_argument("file")
        s.add_argument("--input-file")
        s.add_argument("--features")
        if name == "run":
            s.add_argument("--stats", action="store_true")
            s.add_argument("--profile", action="store_true")
            s.add_argument("--max-cycles", type=int, default=4_000_000_000)
        if name == "asm":
            s.add_argument("-o")
        if name == "core":
            s.add_argument("--stage", default="lifted", choices=("desugared", "simplified", "lifted"))
    s = sub.add_parser("test")
    s.add_argument("names", nargs="*")
    s.add_argument("--features")
    s.add_argument("-v", action="store_true")
    s = sub.add_parser("report")
    s.add_argument("--write", action="store_true")
    args = p.parse_args(argv)
    try:
        return {"run": cmd_run, "ref": cmd_ref, "test": cmd_test, "asm": cmd_asm, "core": cmd_core,
                "report": cmd_report}[args.cmd](args)
    except CurlewError as e:
        print(f"{getattr(args, 'file', '')}:{e}", file=sys.stderr)
        return 1
