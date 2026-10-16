"""The draft 2 CPU's command line: heron v2_hw <command> ...

  check  [NAMES] [--lockstep]      the register-transfer model against the
                                   instruction-level simulator (the suite)
  run    FILE.s [--input TEXT] [--bus] [--profile]
                                   one program on the RTL model: cycles, time,
                                   where they go (--bus: the code on the
                                   memory card, fetched over the bus)
  ucode  [--list]                  the microcode: its size, length classes,
                                   and (--list) every microinstruction
"""

import argparse
import sys


def cmd_run(args):
    from collections import Counter
    from heron.infra import asm as asmcore
    from heron.infra import isas
    from heron.infra.programs import metadata
    from . import check, ucode as uc
    img = asmcore.assemble_file(isas.get("v2"), args.file)
    inp = args.input.encode() if args.input is not None else metadata(args.file)["input"]
    m = check.run_rtl(img, inp, code_base=0x08000000 if args.bus else 0,
                      prefetch_bus=args.prefetch_bus, profile=args.profile)
    sys.stdout.write(m.out.decode("latin-1"))
    print(f"\n{m.instructions} instructions, {m.cycles} cycles (CPI {m.cycles / m.instructions:.2f}), "
          f"{m.ticks * 20 / 1e6:.3f} ms, {m.ticks / m.cycles * 20:.0f} ns a cycle; "
          f"bus holds {m.hold_ticks * 20 / 1e6:.3f} ms; refills {m.refills}, "
          f"words fetched {m.fetch_words} (wasted {m.fetch_wasted})")
    if args.profile:
        names = Counter()
        for a, n in m.ucount.items():
            node = m.mc.by_addr.get(a)
            names[node.name if node else f"{a:04X}"] += n
        for name, n in names.most_common(25):
            print(f"  {n:9d} {100 * n / m.cycles:5.1f}%  {name}")
    return 0


def cmd_ucode(args):
    from collections import Counter
    from . import ucode as uc
    mc = uc.built()
    print(f"{len(mc.nodes)} microinstructions in {1 << uc.Y_BITS} slots, {len(mc.entry)} routines; "
          f"control word {uc.CONTROL_BITS} bits")
    print(f"length classes (ticks): {mc.lengths}")
    print("microinstructions by ticks needed:", dict(sorted(Counter(mc.ticks.values()).items())))
    if args.list:
        for n in sorted(mc.nodes, key=lambda n: n.addr):
            print(f"{n.addr:04X} {mc.ticks[n.addr]:2d} {n.name:24s} {uc.explain(mc.word(n))}")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["check"]:
        from .check import main as check_main
        return check_main(argv[1:])
    p = argparse.ArgumentParser(prog="heron v2_hw", description="The draft 2 CPU")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="the RTL model against the instruction-level simulator")
    r = sub.add_parser("run", help="a program on the RTL model")
    r.add_argument("file")
    r.add_argument("--input")
    r.add_argument("--bus", action="store_true", help="the code on the memory card")
    r.add_argument("--prefetch-bus", action="store_true",
                   help="prefetch from bus space in any cycle, not only refills")
    r.add_argument("--profile", action="store_true")
    r.set_defaults(fn=cmd_run)
    u = sub.add_parser("ucode", help="the microcode")
    u.add_argument("--list", action="store_true")
    u.set_defaults(fn=cmd_ucode)
    args = p.parse_args(argv)
    return args.fn(args) or 0
