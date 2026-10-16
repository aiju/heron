"""The fixed-base mode study's command line: heron fixed_base <command> ...

  report [--write]  the findings' tables (about 15 minutes; --write:
                    reports/0028-rfc-draft-2-isa/fixed-base-mode-results.md)
  scan egret [--variant asm|c|jit] [NAME...]
  scan lisp [NAME...]
  scan kernel [SCENARIO...]
                    where the field accesses are: for each base register,
                    the cycles a fixed rT there would save, from baseline
                    runs alone
"""

import argparse

from . import experiments as X


def _scan_table(rows):
    """rows: [(label, Scan, per)]: the best three bases of each"""
    for label, sc, per in rows:
        bb = sc.by_base()
        cells = []
        for r, v in bb.most_common(3):
            cells.append(f"r{r} {v / per:.1f}" if per != 1 else
                         f"r{r} {100 * v / sc.cycles['D32-separate']:.2f}%")
        print(f"{label:24} " + "  ".join(cells))


def cmd_scan(args):
    if args.what == "egret":
        from heron.studies.egret.programs import catalogue
        image = X.egret_image(args.variant)
        rows = []
        for name in args.names or catalogue.names():
            _, m, chk = X.egret_program(image, catalogue.program(name))
            rows.append((name, X.scan.Scan().add_machine(m).add_machine(chk, weight=-1), 1))
        _scan_table(rows)
    elif args.what == "lisp":
        runs = X.lisp(args.names or None)
        _scan_table([(n, r["scan"], 1) for n, r in runs.items()])
    else:
        runs = X.kernel([], args.names or None)
        print("cycles saved per operation, D32-separate")
        _scan_table([(f"{n} {b}", r["scan"], r["ops"]) for (n, b), r in runs.items()])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="heron fixed_base", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("report")
    p.add_argument("--write", action="store_true")
    p = sub.add_parser("scan")
    p.add_argument("what", choices=["egret", "lisp", "kernel"])
    p.add_argument("names", nargs="*")
    p.add_argument("--variant", default="asm", choices=["asm", "c", "jit"])
    args = ap.parse_args(argv)
    if args.cmd == "report":
        from . import report
        report.main(args.write)
    else:
        cmd_scan(args)
    return 0
