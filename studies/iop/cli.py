"""The I/O processor's command line: heron iop <command> ...

  build [--wcs] [--program S]   the microcode, the Forth and the image flash, into build/iop
  console [--wcs] [--program S] the Forth on the console in this terminal (Ctrl-] quits)
  run LINE...                   power up, type the lines at the Forth, print what it prints
  boot [--wcs] [--program S]    power up, boot the CPU (boot-cpu), print what it prints
                                until it halts; with --wcs, draft 2's control store too
                                (studies/v2_hw's, a minute or so to build the first time),
                                checked against what the CPU card's window holds
  ucode [--list]                the microcode: its size, the primitives, a listing
  words                         the dictionary's words, and their sizes
  bench [--wcs]                 what RFC 0027 estimates, measured: the boot, the Forth's
                                speed, the tick's cost, copy rates, booting the CPU
"""

import argparse
import os
import sys

from heron.studies.iop import build as bld


def add_image_args(p):
    p.add_argument("--program", default=bld.DEFAULT_PROGRAM,
                   help="the CPU's boot program, draft 2 assembly (default: sw/hello.s)")
    p.add_argument("--wcs", action="store_true", help="put draft 2's control store in the image flash")


def make(args):
    try:
        return bld.Build(args.program, args.wcs)
    except bld.BuildError as e:
        print(f"error: {e}", file=sys.stderr)
        return None


def cmd_build(args):
    b = make(args)
    if b is None:
        return 1
    os.makedirs(bld.OUT, exist_ok=True)
    files = {
        "ucode.bin": b.ucode_bytes(),
        "flash.bin": b.flash,
        "ucode.lst": b.mc.listing().encode(),
    }
    for name, data in files.items():
        with open(os.path.join(bld.OUT, name), "wb") as f:
            f.write(data)
    print(f"microcode: {len(b.mc.words)} microinstructions, {len(b.mc.prims)} primitives")
    print(f"dictionary: {b.meta.here} cells, {len(b.meta.words)} words")
    print(f"image flash: {len(b.flash) // 2} halfwords used of {bld.FLASH_HALFWORDS}")
    print(f"in {os.path.relpath(bld.OUT)}")
    return 0


def cmd_console(args):
    from heron.studies.iop import run
    return run.console(args)


def cmd_run(args):
    from heron.studies.iop.run import Session, Timeout
    s = Session(make(args))
    try:
        sys.stdout.write(s.boot().decode("latin-1"))
        for line in args.lines:
            sys.stdout.write(s.command(line, timeout_ms=args.timeout * 1000))
    except Timeout as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"--- {s.ms:.1f} ms simulated", file=sys.stderr)
    return 0


def cmd_boot(args):
    from heron.studies.iop.run import Session, Timeout
    b = make(args)
    if b is None:
        return 1
    s = Session(b)
    try:
        s.boot()
        start = s.ms
        s.s.uart_send(b"boot-cpu cpu-wait\r")
        out = s.until(b" ok\r\n", timeout_ms=args.timeout * 1000)
    except Timeout as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(out.decode("latin-1"))
    c = s.s.cpu()
    print(f"--- the CPU: {c['instructions']} instructions, halted at {c['pc']:08X}; "
          f"{s.ms - start:.1f} ms simulated from boot-cpu")
    if b.cs:
        bad = 0
        for k in range(bld.CS_LANES):
            lane = s.s.lane(k)
            bad += sum(1 for a, w in b.cs["rom"].items() if lane[a] != (w >> (16 * k)) & 0xFFFF)
        dec = s.s.lane(bld.DEC_LANE)
        bad += sum(1 for a, w in enumerate(b.cs["decode"]) if dec[a] != w)
        print(f"the control store: {len(b.cs['rom'])} microinstructions and the decode table, "
              f"{'as built' if not bad else f'{bad} halfwords wrong'}")
        if bad:
            return 1
    return 0


def cmd_ucode(args):
    b = make(args)
    if b is None:
        return 1
    mc = b.mc
    print(f"{len(mc.words)} microinstructions: {sum(1 for a in mc.words if a < 0x8000)} below 0x8000, "
          f"{sum(1 for a in mc.words if a >= 0x8000)} for the primitives")
    prims = sorted(mc.prims.items(), key=lambda x: x[1])
    ends = [a for _, a in prims[1:]] + [max(mc.words) + 1]
    print(" ".join(f"{n}({e - a})" for (n, a), e in zip(prims, ends)))
    if args.list:
        print(mc.listing())
    return 0


def cmd_words(args):
    b = make(args)
    if b is None:
        return 1
    m = b.meta
    ws = sorted(m.words.values(), key=lambda w: w.hdr)
    for w, nxt in zip(ws, ws[1:] + [None]):
        size = (nxt.hdr if nxt else m.here) - w.hdr
        kind = "primitive" if w.xt is not None and w.xt >= 0x8000 else "colon"
        print(f"{w.hdr:04X} {size:4d} {kind:9s} {w.name}")
    return 0


def cmd_bench(args):
    from heron.studies.iop import bench
    print(bench.table(bench.measure(args.wcs)))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron iop", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("build", "console", "ucode", "words"):
        q = sub.add_parser(name)
        add_image_args(q)
        if name == "ucode":
            q.add_argument("--list", action="store_true")
    q = sub.add_parser("run")
    add_image_args(q)
    q.add_argument("lines", nargs="+")
    q.add_argument("--timeout", type=float, default=10, help="seconds simulated a line may take")
    q = sub.add_parser("boot")
    add_image_args(q)
    q.add_argument("--timeout", type=float, default=10, help="seconds simulated the CPU may take")
    q = sub.add_parser("bench")
    q.add_argument("--wcs", action="store_true")
    args = p.parse_args(argv)
    return {"bench": cmd_bench, "build": cmd_build, "console": cmd_console, "run": cmd_run, "boot": cmd_boot,
            "ucode": cmd_ucode, "words": cmd_words}[args.cmd](args)
