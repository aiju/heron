"""The study's command line: heron mini_gfx <command> ...

  list                      the programs
  run PROG [--variant c|asm|blk] [--layout L0|L1] [--bandwidth B0|B1|B2]
           [--frames N] [--script FILE] [--png-dir DIR] [--profile N]
           [--poke NAME=V] [-D NAME=V]
                            a program on the mini's simulator, with its
                            script: its output, measurements and
                            screenshots (--profile: the PC every N cycles)
  check                     the library against pixel references in every
                            format and variant, and against the video's
                            decoder in every mode and layout
"""

import argparse
import os
import sys

from heron import BUILD

from . import programs
from .run import TICK


def cmd_list(args):
    for name, p in programs.all_programs().items():
        print(f"{name:24s} {p.title}: {p.about}")
    return 0


def _kv(items):
    out = {}
    for it in items or []:
        k, v = it.split("=", 1)
        out[k] = v
    return out


def cmd_run(args):
    p = programs.get(args.prog)
    script = None
    if args.script:
        with open(args.script) as f:
            script = f.read()
    pokes = {k if k.startswith("_") else "_" + k: int(v, 0) for k, v in _kv(args.poke).items()}
    shots = args.png_dir or os.path.join(BUILD, "mini_gfx", "shots", p.name.replace("/", "-"))
    r = p.run(args.variant, args.layout, args.bandwidth, args.frames, script, shots,
              args.profile, pokes, _kv(args.define))
    sys.stdout.write(r.output)
    print(f"{r.status} after {r.frames} frames; {r.stats['cycles']} cycles, "
          f"{r.stats['ms']:.1f} ms; video steals {r.stats['steal_ticks']} ticks, "
          f"{r.stats['underruns']} underruns")
    if r.trap:
        print(f"TRAP {r.trap}")
    for name, v in r.perf.items():
        print(f"  {name:28s} " + "  ".join(f"{x * TICK / 1e3:.1f} us" if i < 2 else str(x)
                                         for i, x in enumerate(v)))
    if r.shots:
        print(f"screenshots in {shots}: {', '.join(r.shots)}")
    if r.profile:
        tot = sum(r.profile.values())
        for fn, n in sorted(r.profile.items(), key=lambda x: -x[1])[:25]:
            print(f"  {100 * n / tot:5.1f}%  {fn}")
    return 1 if r.trap else 0


def cmd_check(args):
    from . import check
    return check.main()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="heron mini_gfx", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    r = sub.add_parser("run")
    r.add_argument("prog")
    r.add_argument("--variant", choices=("c", "asm", "blk"))
    r.add_argument("--layout", choices=("L0", "L1"))
    r.add_argument("--bandwidth", choices=("B0", "B1", "B2"))
    r.add_argument("--frames", type=int)
    r.add_argument("--script")
    r.add_argument("--png-dir")
    r.add_argument("--profile", type=int, default=0)
    r.add_argument("--poke", action="append")
    r.add_argument("-D", "--define", action="append")
    sub.add_parser("check")
    args = ap.parse_args(argv)
    return {"list": cmd_list, "run": cmd_run, "check": cmd_check}[args.cmd](args)
