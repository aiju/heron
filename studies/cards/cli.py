"""The napkin designs' command line: heron cards <command> ...

  napkin [--write]   the boards' parts and the instructions' timings, as
                     tables (--write: into reports/0049-rfc-board-first/napkin.md)
"""

import argparse
import os

from . import napkin


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron cards", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("napkin")
    q.add_argument("--write", action="store_true", help="write the RFC's napkin.md")
    a = p.parse_args(argv)
    if a.cmd == "napkin":
        if a.write:
            print(f"wrote {os.path.relpath(napkin.write())}")
        else:
            print(napkin.tables())
    return 0
