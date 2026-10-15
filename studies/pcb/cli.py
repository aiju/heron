"""heron pcb: the system's cards as printed circuit boards.

  build [CARD] [--style smd|dip] [--size WxH] [--layers N] [--double]
        [--router grid|freerouting] [--seed N]
                        place, route and check one board, into
                        build/pcb/<name>/ (board.kicad_pcb, board.png,
                        result.json)
  check FILE [--card CARD] [--style smd|dip]
                        check a board file against the card's netlist: its
                        pads, its copper (with KiCad's zone filler) and
                        KiCad's DRC
  pinouts               the pinouts against KiCad's symbol library
  split                 what splitting the CPU card in two would cost: the
                        signals between the halves
  sweep [--write]       the experiments of RFC 0023: board sizes, layers,
                        SMD and DIP, single- and double-sided
"""

import argparse
import json
import sys


def cmd_build(args):
    from . import flow
    w, h = (float(v) for v in args.size.lower().split("x"))
    res = flow.build(args.card, args.style, w, h, layers=args.layers,
                     sides="FB" if args.double else "F", seed=args.seed,
                     router_name=args.router)
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
    return sweep.main(write=args.write, only=args.only)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="heron pcb", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="place, route and check one board")
    b.add_argument("card", nargs="?", default="cpu")
    b.add_argument("--style", default="smd", choices=("smd", "dip"))
    b.add_argument("--size", default="380x220")
    b.add_argument("--layers", type=int, default=6, choices=(4, 6))
    b.add_argument("--double", action="store_true", help="parts on both sides")
    b.add_argument("--router", default="grid", choices=("grid", "freerouting"))
    b.add_argument("--seed", type=int, default=1)
    b.set_defaults(fn=cmd_build)
    c = sub.add_parser("check", help="check a board file against its card's netlist")
    c.add_argument("file")
    c.add_argument("--card", default="cpu")
    c.add_argument("--style", default="smd", choices=("smd", "dip"))
    c.set_defaults(fn=cmd_check)
    sub.add_parser("pinouts", help="the pinouts against KiCad's symbols").set_defaults(fn=cmd_pinouts)
    sub.add_parser("split", help="the cost of splitting the CPU card").set_defaults(fn=cmd_split)
    s = sub.add_parser("sweep", help="the experiments")
    s.add_argument("--write", action="store_true")
    s.add_argument("--only")
    s.set_defaults(fn=cmd_sweep)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
