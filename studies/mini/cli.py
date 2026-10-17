"""Heron Mini's command line: heron mini <command> ...

  check  [NAMES] [--c] [--lockstep] [--queue N]
                                   the register-transfer model against the
                                   instruction-level simulator (the suite,
                                   --c the compiled C programs)
  run    FILE.s [--input TEXT] [--profile]
                                   one program on the RTL model: cycles, time,
                                   where they go
  ucode  [--list]                  the microcode: its size, length classes
  hw     test|run|bom              the chip-level netlist: programs on the
                                   chip-level simulator against the RTL
                                   model, the parts list
"""

import argparse
import sys


def cmd_run(args):
    from collections import Counter
    from heron.infra import asm as asmcore
    from heron.infra import isas
    from heron.infra.programs import metadata
    from . import check
    from .timing import TICK
    img = asmcore.assemble_file(isas.get("v2"), args.file)
    meta = metadata(args.file)
    inp = args.input.encode() if args.input is not None else meta["input"]
    m = check.run_rtl(img, inp, profile=args.profile, queue=args.queue)
    sys.stdout.write(m.out.decode("latin-1"))
    print(f"\n{m.instructions} instructions, {m.cycles} cycles (CPI {m.cycles / m.instructions:.2f}), "
          f"{m.ticks * TICK / 1e6:.3f} ms, {m.ticks / m.cycles * TICK:.0f} ns a cycle; "
          f"I/O holds {m.hold_ticks * TICK / 1e6:.3f} ms; refills {m.refills}, "
          f"words fetched {m.fetch_words} (wasted {m.fetch_wasted}), parcels fetched on "
          f"demand {m.demand}")
    if args.profile:
        names = Counter()
        for a, n in m.ucount.items():
            node = m.mc.by_addr.get(a)
            names[node.name if node else f"{a:05X}"] += n
        for name, n in names.most_common(25):
            print(f"  {n:9d} {100 * n / m.cycles:5.1f}%  {name}")
    return 0


def cmd_ucode(args):
    from collections import Counter
    from . import ucode as uc
    mc = uc.built()
    print(f"control word: {uc.CONTROL_BITS} bits of {uc.WORD_BITS}")
    print(f"lower half: {mc.used_low} of {1 << uc.Y_BITS} words; "
          f"{len(mc.entry_nodes)} distinct first microinstructions for the 65,536 parcels")
    print(f"length classes {mc.lengths}; ticks needed: "
          f"{dict(sorted(Counter(mc.ticks.values()).items()))} ({mc.estimated} estimated)")
    if args.list:
        for n in sorted(mc.low, key=lambda n: n.addr):
            f = mc.word(n)
            print(f"{n.addr:04X} {n.name:20s} {uc.explain(f)}")
    return 0


def main(argv=None):
    import heron.studies.v2_isa  # noqa: F401
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "check":
        from . import check
        return check.main(argv[1:])
    if argv and argv[0] == "hw":
        from . import hw
        return hw.main(argv[1:])
    p = argparse.ArgumentParser(prog="heron mini")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("file")
    r.add_argument("--input")
    r.add_argument("--profile", action="store_true")
    r.add_argument("--queue", type=int, default=2)
    r.set_defaults(func=cmd_run)
    pf = sub.add_parser("perf")
    pf.add_argument("--force", action="store_true")
    pf.set_defaults(func=lambda a: __import__("heron.studies.mini.perf", fromlist=["x"]).main(a))
    u = sub.add_parser("ucode")
    u.add_argument("--list", action="store_true")
    u.set_defaults(func=cmd_ucode)
    args = p.parse_args(argv)
    return args.func(args)
