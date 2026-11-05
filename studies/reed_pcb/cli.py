"""heron reed_pcb: Reed's boards as printed circuit boards.

  place [--board NAME] [--seed N] [--moves N] [--gal-sockets]
        [--half N] [--gap N] [--module N] [--pads STYLE]
                        place a board (default ALU) on RFC 0046's column
                        grid, on a double Eurocard with the DIN 41612
                        connectors at the back edge, into
                        build/reed_pcb/<name>/: board.kicad_pcb, board.svg,
                        result.json (--gal-sockets: the ATF22V10C-5s in
                        PLCC-28 sockets, not soldered; --size: the card's
                        depth across and height down, mm, the connectors on
                        the height's edge)
"""

import argparse
import json


def cmd_place(args):
    from heron.studies.pcb_columns.grid import Params

    from . import place
    prm = Params(half=args.half, gap=args.gap, module=args.module, pads=args.pads)
    size = tuple(float(v) for v in args.size.lower().split("x"))
    _, _, res = place.build(args.board.upper(), size=size, params=prm, seed=args.seed,
                            moves=args.moves,
                            gal_sockets=args.gal_sockets)
    print(json.dumps({k: v for k, v in res.items() if k != "params"}, indent=1))
    return 0 if not res["left_over"] and not res.get("problems") else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="heron reed_pcb", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("place", help="place a board on the column grid")
    p.add_argument("--board", default="ALU", help="CTRL, ALU or MEM")
    p.add_argument("--size", default="160x233.35",
                   help="the card: depth x height, mm (a double Eurocard: 160x233.35)")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--moves", type=int, default=60000)
    p.add_argument("--gal-sockets", action="store_true",
                   help="the ATF22V10C-5s in PLCC-28 sockets")
    p.add_argument("--half", type=int, default=5, help="a half-column's width in rows (0.1 inch)")
    p.add_argument("--gap", type=int, default=2,
                   help="rows from a DIP's last pin to the next DIP's pin 1")
    p.add_argument("--module", type=int, default=1, help="box heights in whole modules of N rows")
    p.add_argument("--pads", default="round", choices=["round", "long", "socket", "socket-long"])
    p.set_defaults(fn=cmd_place)
    args = ap.parse_args(argv)
    return args.fn(args)
