"""heron reed_pcb: Reed's boards as printed circuit boards.

  place [--board NAME] [--size DxH] [--floorplan] [--seed N] [--moves N]
        [--gal-sockets] [--half N] [--gap N] [--module N] [--pads STYLE]
                        place a board (default ALU) on RFC 0046's column
                        grid, with the DIN 41612 connectors at the back
                        edge, into build/reed_pcb/<name>/: board.kicad_pcb,
                        board.svg, result.json. --size: the card's depth
                        across and height down, mm (default a double
                        Eurocard, 160x233.35; 220x233.35 with --floorplan);
                        --floorplan: by the hand-made floorplan in
                        floorplan.py rather than annealed (the ALU);
                        --gal-sockets: the ATF22V10C-5s in PLCC-28 sockets,
                        not soldered; --blocks: the ALU in blocks
                        (alu_layout.py), for soldering by hand, on 220 mm
  route [the same options] [--layers 4|6] [--track MM] [--via DIA/DRILL]
                        place a board the same way, then fan out, route on
                        infra's grid router and check it, into
                        build/reed_pcb/<name>-<n>L/: board.kicad_pcb,
                        board.png, result.json. --track: the tracks' width
                        and gaps, --via its size and hole, mm (default
                        infra's 0.127 and 0.45/0.2; with --blocks 0.15 and
                        0.6/0.3)
"""

import argparse
import json


def _placed(args, layers):
    """(board, placer, chips left over) as the options ask."""
    from heron.studies.pcb_columns.grid import Params

    from . import alu_layout, floorplan, place
    prm = Params(half=args.half, gap=args.gap, module=args.module, pads=args.pads)
    default = floorplan.SIZE if args.floorplan or args.blocks else place.CARD
    size = tuple(float(v) for v in args.size.lower().split("x")) if args.size else default
    if args.blocks:
        b, bl, probs = alu_layout.place(args.board.upper(), size, layers)
        return b, None, (["spacing: " + p for p in probs] if probs else [])
    if args.floorplan:
        return floorplan.place(args.board.upper(), size, prm, args.gal_sockets, layers)
    b, pl, left = place.place(args.board.upper(), size, prm, args.seed, args.moves,
                              args.gal_sockets, layers)
    return b, pl, left


def cmd_route(args):
    from . import route
    b, pl, left = _placed(args, args.layers)
    if left:
        print(f"doesn't fit, or breaks the spacing: {left[:5]}")
        return 1
    if args.track:
        b.rules.update(track=args.track, clearance=args.track)
    if args.via:
        dia, drill = (float(v) for v in args.via.split("/"))
        b.rules.update(via_dia=dia, via_drill=drill)
    if args.track or args.via:
        b.name += f"-t{b.rules['track']:g}-v{b.rules['via_dia']:g}"
    res = route.route(b, args.board.upper())
    print(json.dumps(res, indent=1))
    return 0 if res["routed"] and res["checks"]["passed"] else 1


def cmd_place(args):
    from heron.studies.pcb_columns.grid import Params

    from . import alu_layout, floorplan, place
    prm = Params(half=args.half, gap=args.gap, module=args.module, pads=args.pads)
    default = floorplan.SIZE if args.floorplan or args.blocks else place.CARD
    size = tuple(float(v) for v in args.size.lower().split("x")) if args.size else default
    if args.blocks:
        _, _, res = alu_layout.build(args.board.upper(), size)
        print(json.dumps(res, indent=1))
        return 0 if not res["problems"] else 1
    if args.floorplan:
        _, _, res = floorplan.build(args.board.upper(), size=size, params=prm,
                                    gal_sockets=args.gal_sockets)
    else:
        _, _, res = place.build(args.board.upper(), size=size, params=prm, seed=args.seed,
                                moves=args.moves, gal_sockets=args.gal_sockets)
    print(json.dumps({k: v for k, v in res.items() if k != "params"}, indent=1))
    return 0 if not res["left_over"] and not res.get("problems") else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="heron reed_pcb", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd, fn, hlp in (("place", cmd_place, "place a board on the column grid"),
                         ("route", cmd_route, "place a board, then route and check it")):
        p = sub.add_parser(cmd, help=hlp)
        _options(p)
        p.set_defaults(fn=fn)
        if cmd == "route":
            p.add_argument("--layers", type=int, default=6, choices=[4, 6])
            p.add_argument("--track", type=float, help="tracks' width and gaps, mm")
            p.add_argument("--via", help="via size and hole, mm: DIA/DRILL")
    args = ap.parse_args(argv)
    return args.fn(args)


def _options(p):
    p.add_argument("--board", default="ALU", help="CTRL, ALU or MEM")
    p.add_argument("--size", help="the card: depth x height, mm (a double Eurocard: 160x233.35)")
    p.add_argument("--floorplan", action="store_true",
                   help="place by the hand-made floorplan (floorplan.py) instead of annealing")
    p.add_argument("--blocks", action="store_true",
                   help="the ALU in blocks, for soldering by hand (alu_layout.py)")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--moves", type=int, default=60000)
    p.add_argument("--gal-sockets", action="store_true",
                   help="the ATF22V10C-5s in PLCC-28 sockets")
    p.add_argument("--half", type=int, default=5, help="a half-column's width in rows (0.1 inch)")
    p.add_argument("--gap", type=int, default=2,
                   help="rows from a DIP's last pin to the next DIP's pin 1")
    p.add_argument("--module", type=int, default=1, help="box heights in whole modules of N rows")
    p.add_argument("--pads", default="round", choices=["round", "long", "socket", "socket-long"])
