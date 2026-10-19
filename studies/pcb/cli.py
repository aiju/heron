"""heron pcb: the system's cards as printed circuit boards.

  build [CARD] [--style smd|dip] [--size WxH] [--layers N] [--free] [--double]
        [--tight] [--pitch WxH] [--gaps A,B] [--router grid|freerouting] [--seed N]
                        place, route and check one board, into
                        build/pcb/<name>/ (board.kicad_pcb, board.png,
                        result.json)
  check FILE [--card CARD] [--style smd|dip]
                        check a board file against the card's netlist: its
                        pads, its copper (with KiCad's zone filler) and
                        KiCad's DRC
  view [NAME...] [--out FILE]
                        the boards (default: the sweep's fully checked ones)
                        as one web page to pan, zoom and look at by layer:
                        build/pcb/viewer.html
  pinouts               the pinouts against KiCad's symbol library
  split                 what splitting the CPU card in two would cost: the
                        signals between the halves
  sweep [--write] [--only LABEL] [--reuse] [--no-freerouting]
                        the experiments of RFC 0023: board sizes, layers,
                        SMD and DIP, single- and double-sided
"""

import argparse
import json
import sys


# a DIP board soldered by hand: closer than RFC 0026's R16, which leaves
# room for selective soldering, and the capacitors under the chips
TIGHT = dict(style="dip", gaps=(1.0, 0.5), halo=0.5, decaps="under-all", pitch=(10.25, 8.8),
             align=False)


def cmd_build(args):
    from . import flow
    w, h = (float(v) for v in args.size.lower().split("x"))
    kw = dict(TIGHT) if args.tight else {"style": args.style}
    if args.pitch:
        kw["pitch"] = tuple(float(v) for v in args.pitch.lower().split("x"))
    if args.gaps:
        kw["gaps"] = tuple(float(v) for v in args.gaps.split(","))
    name = None
    if args.tight:
        name = f"{args.card}-dip-tight-{int(w)}x{int(h)}-{args.layers}L-F"
    res = flow.build(args.card, width=w, height=h, layers=args.layers,
                     sides="FB" if args.double else "F", seed=args.seed,
                     router_name=args.router, name=name,
                     arrangement="free" if args.free or args.double else "grid", **kw)
    print(json.dumps(res, indent=1))
    return 0 if res.get("routed") and not res.get("netlist_errors") else 1


def cmd_check(args):
    from . import cards, flow
    nl = cards.netlists()[args.card]
    maps = cards.pin_maps(nl)
    res = flow.check_board(args.file, nl, args.style, [("P1", maps["P1"]), ("P2", maps["P2"])])
    print(json.dumps(res, indent=1))
    ok = not res["netlist_errors"] and not res.get("copper_opens") and not res.get("copper_shorts") \
        and not res.get("drc_errors")
    return 0 if ok else 1


def cmd_view(args):
    from . import sweep
    path = sweep.viewer(args.names or None, args.out)
    print(path)
    return 0


def cmd_mini(args):
    from . import mini
    return mini.main(args)


def cmd_pinouts(args):
    from heron.infra.pcb import check
    errs = check.check_pinouts()
    for e in errs:
        print(e)
    print(f"{len(errs)} differences from KiCad's symbols")
    return 1 if errs else 0


def cmd_split(args):
    from . import split
    return split.main()


def cmd_sweep(args):
    from . import sweep
    return sweep.main(write=args.write, only=args.only, reuse=args.reuse,
                      freeroute=not args.no_freerouting)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="heron pcb", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="place, route and check one board")
    b.add_argument("card", nargs="?", default="cpu")
    b.add_argument("--style", default="smd", choices=("smd", "dip"))
    b.add_argument("--size", default="340x233.35")
    b.add_argument("--layers", type=int, default=6, choices=(4, 6))
    b.add_argument("--free", action="store_true",
                   help="parts anywhere, not in rows and columns")
    b.add_argument("--double", action="store_true",
                   help="parts on both sides (implies --free; against RFC 0026's R17 "
                        "on a board with through-hole parts)")
    b.add_argument("--tight", action="store_true",
                   help="DIP soldered by hand: 1 mm between pads, 0805 capacitors under the "
                        "chips (closer than RFC 0026's R16)")
    b.add_argument("--pitch", help="the grid's least slot, WxH mm")
    b.add_argument("--gaps", help="the least gaps between courtyards, SMD-THT,THT-THT mm")
    b.add_argument("--router", default="grid", choices=("grid", "freerouting"))
    b.add_argument("--seed", type=int, default=1)
    b.set_defaults(fn=cmd_build)
    c = sub.add_parser("check", help="check a board file against its card's netlist")
    c.add_argument("file")
    c.add_argument("--card", default="cpu")
    c.add_argument("--style", default="smd", choices=("smd", "dip"))
    c.set_defaults(fn=cmd_check)
    v = sub.add_parser("view", help="the boards as a web page")
    v.add_argument("names", nargs="*", help="board folders in build/pcb/")
    v.add_argument("--out")
    v.set_defaults(fn=cmd_view)
    m = sub.add_parser("mini", help="Heron Mini's stacked boards: build, delays, timing")
    m.add_argument("action", choices=("build", "sites", "fit", "delays", "sta"))
    m.add_argument("--style", default="smd", choices=("smd", "dip"))
    m.add_argument("--layers", type=int, default=6, choices=(4, 6))
    m.add_argument("--write", action="store_true",
                   help="delays: into report 0044's folder too")
    m.add_argument("--file", help="sta: the delays (default build/pcb/mini-delays.json)")
    m.set_defaults(fn=cmd_mini)
    sub.add_parser("pinouts", help="the pinouts against KiCad's symbols").set_defaults(fn=cmd_pinouts)
    sub.add_parser("split", help="the cost of splitting the CPU card").set_defaults(fn=cmd_split)
    s = sub.add_parser("sweep", help="the experiments")
    s.add_argument("--write", action="store_true")
    s.add_argument("--only", help="only the boards whose label has this")
    s.add_argument("--reuse", action="store_true", help="read back boards already built")
    s.add_argument("--no-freerouting", action="store_true")
    s.set_defaults(fn=cmd_sweep)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
