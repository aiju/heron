"""Egret's command line: heron egret <command> ...

  run    FILE.eg [--host] [--variant asm|c|jit] [--isa v2] [--input-file F] [--stats]
         [--max-cycles N]
                     run a program on the simulated draft 1b machine (--isa
                     v2: draft 2; --host: on the host build of the VM)
  test   [NAME...] [--heron [--variant asm|c|jit|both|all] [--isa v2]] [--update]
                     the programs against their expected output, on the
                     host (--heron: also on the simulator, with the
                     hand-written interpreter loop, the C one, the JIT,
                     the first two or all three; --update: write the
                     expected output of the programs that have no suite
                     counterpart, from the host)
  bench  [NAME...] [--write] [--isa v2]
                     cycles of every program on draft 1b, and where they go
                     (--write: the generated part of report 0017; --isa v2:
                     draft 2 against 1b, report 0032's)
  build  [--isa v2]   build the VM for the host and every build for 1b (or 2)

A program's input (gets, read_all) follows a line __END__ in the console
input; `run` and `test` take it from --input-file, or from the program's
`#! input: FILE` line (relative to the program).
"""

import argparse
import os
import sys

from . import build
from .programs import catalogue


def cmd_run(args):
    with open(args.file, "rb") as f:
        src = f.read()
    inp = catalogue.input_for(args.file, args.input_file)
    if args.host:
        out, status = build.run_host(src, inp)
        sys.stdout.buffer.write(out)
        return status
    out, m = build.run_heron(src, inp, isa=args.isa, max_cycles=args.max_cycles,
                             variant=args.variant)
    sys.stdout.buffer.write(out)
    sys.stdout.flush()
    if not m.halted:
        print(f"\nstopped at the cycle limit ({args.max_cycles})", file=sys.stderr)
        return 1
    if args.stats:
        from . import profile
        profile.print_stats(m, sys.stderr)
    return 0


def cmd_test(args):
    from .programs import catalogue as cat
    names = args.names or cat.names()
    bad = 0
    for name in names:
        prog = cat.program(name)
        out, status = build.run_host(prog.source, prog.input)
        if args.update and prog.own_expected:
            with open(prog.expected_path, "wb") as f:
                f.write(out)
        ok = out == prog.expected()
        line = f"{name:<14} host {'ok' if ok else 'FAILED'}"
        if args.heron:
            for variant in ({"both": ["asm", "c"], "all": build.VARIANTS}.get(args.variant) or [args.variant]):
                hout, m = build.run_heron(prog.source, prog.input, isa=args.isa, variant=variant)
                hok = hout == prog.expected()
                line += f"   {variant} {'ok' if hok else 'FAILED'} {m.cycles:>12,}"
                ok = ok and hok
        print(line)
        if not ok:
            bad += 1
    return 1 if bad else 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    p = argparse.ArgumentParser(prog="heron egret",
                                description="Egret, a small object language, on drafts 1b and 2")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a program")
    r.add_argument("file")
    r.add_argument("--host", action="store_true", help="on the host build of the VM")
    r.add_argument("--input-file", help="the program's input")
    r.add_argument("--stats", action="store_true", help="cycles, and where they go")
    r.add_argument("--max-cycles", type=int, default=build.MAX_CYCLES)
    r.add_argument("--variant", choices=build.VARIANTS, default="asm",
                   help="the hand-written interpreter loop (asm), the C one (c) or the JIT (jit)")
    r.add_argument("--isa", choices=build.ISAS, default="v1b", help="draft 1b (the default) or draft 2")
    r.set_defaults(fn=cmd_run)
    t = sub.add_parser("test", help="the programs against their expected output")
    t.add_argument("names", nargs="*")
    t.add_argument("--heron", action="store_true", help="also on the simulator")
    t.add_argument("--variant", choices=list(build.VARIANTS) + ["both", "all"], default="all",
                   help="with --heron: the VM with the hand-written interpreter loop (asm), the C one (c), native code (jit), the first two (both) or all three (all)")
    t.add_argument("--isa", choices=build.ISAS, default="v1b", help="with --heron: draft 1b (the default) or draft 2")
    t.add_argument("--update", action="store_true", help="write the expected output of Egret's own programs")
    t.set_defaults(fn=cmd_test)
    b = sub.add_parser("bench", help="cycles on draft 1b (--isa v2: draft 2 against 1b)")
    b.add_argument("names", nargs="*")
    b.add_argument("--write", action="store_true", help="write the generated part of the report")
    b.add_argument("--isa", choices=build.ISAS, default="v1b",
                   help="v2: draft 2 against 1b, report 0032's tables")
    b.set_defaults(fn=lambda a: __import__("heron.studies.egret." + ("bench_v2" if a.isa == "v2" else "bench"),
                                           fromlist=["x"]).main(a))
    bl = sub.add_parser("build", help="build the VM for the host and for 1b (or 2)")
    bl.add_argument("--isa", choices=build.ISAS, default="v1b", help="draft 1b (the default) or draft 2")
    bl.set_defaults(fn=lambda a: (print(build.host()), [build.heron(a.isa, variant=v) for v in build.VARIANTS], 0)[-1])
    args = p.parse_args(argv)
    return args.fn(args) or 0
