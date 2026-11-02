"""Reed's command line: heron reed <command> ...

  boards             each board's packages, area and parts
  check              build the whole machine and check it: the netlist's
                     own checks, and each control line driven by its board
                     alone
"""

import argparse

from . import system


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron reed", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("boards")
    sub.add_parser("check")
    a = p.parse_args(argv)
    if a.cmd == "boards":
        print(system.report())
    elif a.cmd == "check":
        nl = system.machine(sim=True)
        system.check(nl)
        print(f"ok: {len(nl.instances)} instances, every control line driven by its board alone")
    return 0
