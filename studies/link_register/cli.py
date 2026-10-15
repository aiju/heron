"""The link register study's command line: heron link_register <command> ...

  run    FILE.s [--isa v1b|v1bl] [--stats]   assemble and run a program
  test   [NAME...]                           the ported suite on v1bl, against the expected output
  cc     ARGS...                             the C compiler, for v1bl (heron c_compiler cc's arguments)
  report [--write]                           the report's tables (results.md)
"""

import argparse
import os
import sys

from . import measure


def cmd_run(args):
    from heron.studies.v1_isa.cli import run32
    from heron.infra import asm as asmcore, isas
    from heron.infra.programs import metadata
    mod = isas.get(args.isa)
    img = asmcore.assemble_file(mod, args.file)
    ns = argparse.Namespace(file=args.file, input="", input_file=None, trace=False,
                            stats=args.stats, regs=False, max_cycles=args.max_cycles)
    return run32(ns, mod, img, metadata(args.file)["input"])


def cmd_test(args):
    from heron.studies.v1_isa import testing
    paths = measure.asm_paths("v1bl")
    if args.names:
        paths = [p for p in paths if os.path.basename(p)[:-2] in args.names]
    return testing.run_suite(paths, lambda p: testing.run_program(p, "v1bl"), args.v)


def cmd_cc(rest):
    from heron.studies.c_compiler.cc import __main__ as cc
    p = argparse.ArgumentParser(prog="heron link_register cc",
                                description="the C compiler for v1bl")
    cc.add_arguments(p)
    return cc.run(p.parse_args(rest), "v1bl")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["cc"]:
        return cmd_cc(argv[1:])
    p = argparse.ArgumentParser(prog="heron link_register",
                                description="CALL with a link register: draft 1b against v1bl")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="assemble and run a program")
    r.add_argument("file")
    r.add_argument("--isa", choices=measure.ISAS, default="v1bl")
    r.add_argument("--stats", action="store_true")
    r.add_argument("--max-cycles", type=int, default=50_000_000)
    r.set_defaults(fn=cmd_run)
    t = sub.add_parser("test", help="the ported suite on v1bl")
    t.add_argument("names", nargs="*")
    t.add_argument("-v", action="store_true")
    t.set_defaults(fn=cmd_test)
    sub.add_parser("cc", help="the C compiler for v1bl (heron c_compiler cc's arguments)")
    rp = sub.add_parser("report", help="the report's tables")
    rp.add_argument("--write", action="store_true", help="write the report's results.md")
    rp.set_defaults(fn=lambda a: __import__("heron.studies.link_register.report",
                                            fromlist=["x"]).main(a.write))
    args = p.parse_args(argv)
    return args.fn(args) or 0
