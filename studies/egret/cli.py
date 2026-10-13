"""Egret's command line: heron egret <command> ...

  run    FILE.eg [--host] [--input-file F] [--stats] [--max-cycles N]
                     run a program on the simulated draft 1b machine (or,
                     with --host, on the host build of the VM)
  test   [NAME...] [--heron] [--update]
                     the programs against their expected output, on the
                     host (--heron: also on the simulator; --update: write
                     the expected output of the programs that have no
                     suite counterpart, from the host)
  bench  [NAME...] [--write]
                     cycles of every program on draft 1b, and where they go
                     (--write: the generated part of the report)
  build              build both VMs

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
    out, m = build.run_heron(src, inp, max_cycles=args.max_cycles)
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
            hout, m = build.run_heron(prog.source, prog.input)
            hok = hout == prog.expected()
            line += f"   heron {'ok' if hok else 'FAILED'}  {m.cycles:>12,} cycles"
            ok = ok and hok
        print(line)
        if not ok:
            bad += 1
    return 1 if bad else 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    p = argparse.ArgumentParser(prog="heron egret", description="Egret, a small object language, on draft 1b")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a program")
    r.add_argument("file")
    r.add_argument("--host", action="store_true", help="on the host build of the VM")
    r.add_argument("--input-file", help="the program's input")
    r.add_argument("--stats", action="store_true", help="cycles, and where they go")
    r.add_argument("--max-cycles", type=int, default=build.MAX_CYCLES)
    r.set_defaults(fn=cmd_run)
    t = sub.add_parser("test", help="the programs against their expected output")
    t.add_argument("names", nargs="*")
    t.add_argument("--heron", action="store_true", help="also on the simulator")
    t.add_argument("--update", action="store_true", help="write the expected output of Egret's own programs")
    t.set_defaults(fn=cmd_test)
    b = sub.add_parser("bench", help="cycles on draft 1b")
    b.add_argument("names", nargs="*")
    b.add_argument("--write", action="store_true", help="write the generated part of the report")
    b.set_defaults(fn=lambda a: __import__("heron.studies.egret.bench", fromlist=["x"]).main(a))
    bl = sub.add_parser("build", help="build both VMs")
    bl.set_defaults(fn=lambda a: (print(build.host()), print(build.heron().obj.name), 0)[-1])
    args = p.parse_args(argv)
    return args.fn(args) or 0
