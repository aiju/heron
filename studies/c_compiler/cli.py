"""The C compiler study's command line: heron c_compiler <command> ...

  cc     [--isa v1a|v1b] FILE... [-o OUT] [-c | -S | --run] ...   compile (see cc/__main__.py)
  bench  [--write]    compiled C against the hand-written programs
                      (--write: the generated part of report 0011)
"""

import argparse
import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["cc"]:          # the compiler has its own options, -c and -o among them
        from .cc.__main__ import main as cc_main
        return cc_main(argv[1:])
    p = argparse.ArgumentParser(prog="heron c_compiler", description="A C compiler for drafts 1a and 1b")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("cc", help="compile C, and link and run it (heron c_compiler cc --help)")
    b = sub.add_parser("bench", help="compiled C against the hand-written programs")
    b.add_argument("--write", action="store_true", help="write the generated part of report 0011")
    b.set_defaults(fn=lambda args: __import__("heron.studies.c_compiler.bench", fromlist=["x"]).main(
        ["--write"] if args.write else []))
    args = p.parse_args(argv)
    return args.fn(args) or 0
