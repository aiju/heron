"""The draft 1b hardware's command line: heron v1b_hw <command> ...

  ucode  [-o DIR] [--doc]          microcode ROM images and full listing in
                                   build/ucode-v1b (--doc: microcode.md)
  hw     ...                       chip-level tools (see heron.infra.hw.runner):
                                   run, test, sweep, bom, sta
  check  [NAMES] [--lockstep] [-v] the RTL model against the instruction-level
                                   simulator ("exercise" too)
  report [--hw] [--jobs N]         write the generated part of report 0012
"""

import argparse
import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["check"]:
        from .check import main as check_main
        return check_main(argv[1:])
    p = argparse.ArgumentParser(prog="heron v1b_hw", description="The draft 1b hardware")
    sub = p.add_subparsers(dest="cmd", required=True)

    u = sub.add_parser("ucode", help="build the microcode and decode ROM images")
    u.add_argument("-o", metavar="DIR", help="output directory (default build/ucode-v1b)")
    u.add_argument("--doc", action="store_true", help="write microcode.md (selected routines) instead")
    u.set_defaults(fn=lambda args: __import__("heron.studies.v1b_hw.ucode", fromlist=["x"]).cmd_ucode(args))

    h = sub.add_parser("hw", help="chip-level tools")
    h.add_argument("rest", nargs=argparse.REMAINDER)
    h.set_defaults(fn=lambda args: _hw(args.rest))

    sub.add_parser("check", help="the RTL model against the instruction-level simulator "
                                 "(heron v1b_hw check --help)")

    rp = sub.add_parser("report", help="write the generated part of report 0012")
    rp.add_argument("--hw", action="store_true",
                    help="also run the chip-level simulator (programs and clock sweeps; 30-60 minutes)")
    rp.add_argument("--jobs", type=int, default=4)
    rp.set_defaults(fn=lambda args: __import__("heron.studies.v1b_hw.report", fromlist=["x"]).main(
        (["--hw"] if args.hw else []) + ["--jobs", str(args.jobs)]))

    args = p.parse_args(argv)
    return args.fn(args) or 0


def _hw(argv):
    from heron.infra.hw import runner
    from . import machine
    return runner.main(argv, machine)
