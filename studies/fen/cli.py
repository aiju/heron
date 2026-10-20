"""Fen's command line: heron fen <command> ...

  build                         the kernel, the programs, the boot image and a fresh disk
  console [--fresh] [--fast] [--mhz N]
                                the serial console in this terminal (Ctrl-] quits);
                                the card is kept in build/fen/disk.img
  run CMD...                    boot with a shell on the serial console, run the command
                                lines, print what they print
  ktest                         the kernel's own test (cmd/ktest.c) as init
  shot [-o PNG] [ACTION...]     boot the window system, do things, save the screen;
                                an action is type:TEXT (\\n for Return), click:X,Y,
                                drag:X0,Y0,X1,Y1, menu:N (the desktop menu's Nth item,
                                from 0) or wait:MS
  bench [--write]               the kernel's hot paths, measured in the machine
  banks [--write]               what fewer register banks would cost (RFC 0029's
                                register-banks.md)
  irq [--write]                 how long interrupts are held off, and how often they
                                come (RFC 0040's fen-latency.md)
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


def menu_items():
    return [x for x in build.MENU.splitlines() if x and not x.startswith("#")]


def cmd_shot(args):
    from heron.studies.fen.run import Session
    s = Session(serial=False, clock_hz=args.mhz * 1e6)
    s.run(3000)
    for a in args.actions:
        what, _, arg = a.partition(":")
        nums = [int(v) for v in arg.split(",")] if what in ("click", "drag", "menu", "wait") else []
        if what == "type":
            s.keys(arg.replace("\\n", "\n"))
            s.run(500)
        elif what == "click" and len(nums) == 2:
            s.click(*nums)
            s.run(300)
        elif what == "drag" and len(nums) == 4:
            s.drag(*nums)
            s.run(500)
        elif what == "menu" and len(nums) == 1:
            # the menu opens at the pointer, kept on the screen: from the
            # bottom left corner, its last item ends at the bottom
            top = 480 - (len(menu_items()) * 18 + 4)
            s.mouse_to(20, 470)
            s.c.mouse(0, 0, 1)
            s.run(100)
            s.mouse_to(30, top + 2 + 18 * nums[0] + 9, 1)
            s.c.mouse(0, 0, 0)
            s.run(2000)
        elif what == "wait" and len(nums) == 1:
            s.run(nums[0])
        else:
            print(f"error: no action {a!r}", file=sys.stderr)
            return 1
    out = args.output or os.path.join(build.OUT, "screen.png")
    s.save_png(out)
    print(f"{os.path.relpath(out)}, at {s.ms / 1000:.2f} s simulated")
    return 0


def cmd_bench(args):
    from heron.studies.fen import bench
    return bench.main(args.write)


def cmd_banks(args):
    from heron.studies.fen import banks
    return banks.main(args.write)


def cmd_irq(args):
    from heron.studies.fen import irq
    return irq.main(args.write)


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
    sh = sub.add_parser("shot")
    sh.add_argument("actions", nargs="*")
    sh.add_argument("-o", "--output")
    sh.add_argument("--mhz", type=float, default=6.0)
    sh.set_defaults(fn=cmd_shot)
    b = sub.add_parser("bench")
    b.add_argument("--write", action="store_true", help="write the report's performance.md")
    b.set_defaults(fn=cmd_bench)
    k = sub.add_parser("banks")
    k.add_argument("--write", action="store_true", help="write RFC 0029's register-banks-results.md")
    k.set_defaults(fn=cmd_banks)
    q = sub.add_parser("irq")
    q.add_argument("--write", action="store_true", help="write RFC 0040's fen-latency-results.md")
    q.set_defaults(fn=cmd_irq)
    args = p.parse_args(argv)
    return args.fn(args)
