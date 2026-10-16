"""Fen's command line: heron fen <command> ...

  build                         the kernel, the programs, the boot image and a fresh disk
  console [--fresh] [--fast] [--mhz N]
                                the serial console in this terminal (Ctrl-] quits);
                                the card is kept in build/fen/disk.img
  run CMD...                    boot with a shell on the serial console, run the command
                                lines, print what they print
  ktest                         the kernel's own test (cmd/ktest.c) as init
  shot [--do ACTIONS] [-o PNG]  boot the window system, do things, save the screen
"""

import argparse
import os
import sys

from heron.studies.fen import build


def cmd_build(args):
    try:
        img, kimg = build.boot_image()
        disk = build.disk()
    except build.BuildError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    with open(os.path.join(build.OUT, "boot.img"), "wb") as f:
        f.write(img)
    with open(os.path.join(build.OUT, "disk.img"), "wb") as f:
        f.write(disk)
    k = kimg.symbols["__end"] - build.KERNEL_BASE
    print(f"kernel {k} bytes; boot image {len(img)} bytes; disk {len(disk) >> 10} KB "
          f"with {len([n for n in build.programs() if n not in build.NOT_IN_BIN])} programs")
    print(f"in {os.path.relpath(build.OUT)}")
    return 0


def cmd_console(args):
    from heron.studies.fen import run
    return run.console(args)


def cmd_run(args):
    from heron.studies.fen.run import Session, Timeout
    s = Session(serial=True, clock_hz=args.mhz * 1e6)
    try:
        s.boot()
        for line in args.commands:
            print(f"% {line}")
            sys.stdout.write(s.command(line, timeout_ms=args.timeout * 1000))
    except Timeout as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.log:
        print("--- the kernel's log:")
        print(s.log.decode(errors="replace"))
    print(f"--- {s.ms / 1000:.2f} s simulated, {s.c.instructions} instructions", file=sys.stderr)
    return 0


def cmd_ktest(args):
    from heron import native
    img, _ = build.boot_image([("init", "ktest"), "ktchild", "ktcrash", "ktspin"])
    c = native.fen.Computer()
    c.load(0, img)
    log = b""
    for _ in range(200):
        c.run(c.cycles_at(c.now_ns + 50_000_000))
        log += c.debug_take()
        if b" failed\n" in log:
            break
    sys.stdout.write(log.decode(errors="replace"))
    return 0 if b", 0 failed" in log else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron fen", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    c = sub.add_parser("console")
    c.add_argument("--fresh", action="store_true", help="a fresh disk, not the one kept")
    c.add_argument("--fast", action="store_true", help="as fast as the host goes")
    c.add_argument("--mhz", type=float, default=6.0)
    c.set_defaults(fn=cmd_console)
    r = sub.add_parser("run")
    r.add_argument("commands", nargs="+")
    r.add_argument("--mhz", type=float, default=6.0)
    r.add_argument("--timeout", type=float, default=120, help="seconds of simulated time a command may take")
    r.add_argument("--log", action="store_true", help="also print the kernel's log")
    r.set_defaults(fn=cmd_run)
    sub.add_parser("ktest").set_defaults(fn=cmd_ktest)
    args = p.parse_args(argv)
    return args.fn(args)
