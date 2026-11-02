"""heron pcb_columns: placement on a grid of columns and half-columns
(RFC 0046).

  place [--half N] [--gap N] [--module N] [--pads STYLE] [--size DxH]
        [--seed N] [--moves N] [--wire-alone] [--name NAME]
                        place the demonstration slice on a card (default
                        6U x 160 mm) into build/pcb_columns/<name>/:
                        board.kicad_pcb, board.svg, result.json
                        (--wire-alone: for wire alone, the free room
                        wherever it falls)
  report [--write]      RFC 0046's numbers and figures: the variants, the
                        flow's own grid, the boxes, what fits (--write: into
                        reports/0046-rfc-column-grid/)
  fetch                 download the footprints the study uses into
                        build/kicad/footprints/ (done when needed if KiCad's
                        library isn't installed)
"""

import argparse
import json


def cmd_place(args):
    from . import demo
    from .grid import Params
    prm = Params(half=args.half, gap=args.gap, module=args.module, pads=args.pads)
    d, h = (float(v) for v in args.size.lower().split("x"))
    _, _, res = demo.build(prm, (d, h), seed=args.seed, moves=args.moves, name=args.name,
                           tidy=not args.wire_alone)
    print(json.dumps(res, indent=1))
    return 0 if not res["left_over"] and not res.get("problems") else 1


def cmd_report(args):
    from . import report
    return report.main(write=args.write)


def cmd_fetch(args):
    from . import footprints
    footprints.fetch()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="heron pcb_columns", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("place", help="place the demonstration slice")
    p.add_argument("--half", type=int, default=5, help="a half-column's width in rows (0.1 inch)")
    p.add_argument("--gap", type=int, default=2,
                   help="rows from a DIP's last pin to the next DIP's pin 1")
    p.add_argument("--module", type=int, default=1, help="box heights in whole modules of N rows")
    p.add_argument("--pads", default="round", choices=["round", "long", "socket", "socket-long"])
    p.add_argument("--size", default="160x233.35", help="the card: depth x height, mm")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--moves", type=int, default=60000)
    p.add_argument("--wire-alone", action="store_true",
                   help="place for wire alone, not with the free room at the bottom")
    p.add_argument("--name")
    p.set_defaults(fn=cmd_place)
    p = sub.add_parser("report", help="RFC 0046's numbers and figures")
    p.add_argument("--write", action="store_true")
    p.set_defaults(fn=cmd_report)
    p = sub.add_parser("fetch", help="download the footprints")
    p.set_defaults(fn=cmd_fetch)
    args = ap.parse_args(argv)
    return args.fn(args)
