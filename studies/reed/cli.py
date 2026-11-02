"""Reed's command line: heron reed <command> ...

  boards             each board's packages, area and parts
  check              build the whole machine and check it: the netlist's
                     own checks, and each control line driven by its board
                     alone
  sta [--word W]     static timing of each kind of microcycle (sta.WORDS):
                     the shortest length at which nothing a length can fix
                     fails worse than at the longest, and what still fails
                     (--no-wires: sta.py)
"""

import argparse

from . import system


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron reed", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("boards")
    sub.add_parser("check")
    q = sub.add_parser("sta")
    q.add_argument("--word")
    q.add_argument("--paths", type=int, default=2)
    q.add_argument("--no-wires", action="store_true")
    a = p.parse_args(argv)
    if a.cmd == "boards":
        print(system.report())
    elif a.cmd == "check":
        nl = system.machine(sim=True)
        system.check(nl)
        print(f"ok: {len(nl.instances)} instances, every control line driven by its board alone")
    elif a.cmd == "sta":
        from . import sta
        sta.main(a.word, a.paths, not a.no_wires)
    return 0
