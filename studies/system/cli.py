"""The system's command line: heron system <command> ...

  run    PROG.s [--trace A:B] [--max-cycles N]
                         run a program on the whole system at chip level
                         and check it against the instruction-level model
  test   [NAMES] [--jobs N] [--isa]
                         the program suite at chip level (--isa: only on
                         the instruction-level model, in seconds)
  bom    [--card NAME]   the parts list, per card
  lengths                the length classes: what each microinstruction
                         needs, and the jumpers for every set of parts
  schematic [--out FILE] [--fragment]
                         the schematic viewer (build/system/schematic.html),
                         a page with every card's sheets
"""

import argparse
import os
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

from heron.infra.hw import chips, runner


def check(path, hw=None, max_cycles=20_000_000):
    """Run a program at chip level (unless hw is given) and compare it with
    the instruction-level model: (differences, hw, isa machine)."""
    from . import machine, programs
    name = os.path.basename(path)[:-2]
    _img, m = programs.run_isa(path)
    if hw is None:
        _img, hw = machine.run(path, max_cycles=max_cycles)
    diffs = []
    if not hw["halted"]:
        diffs.append(f"didn't halt: {hw['reason']} after {hw['cycles']} cycles")
    exp = programs.expected(name)
    if hw["output"] != exp:
        diffs.append(f"output differs from the expected output: {hw['output'][-80:]!r}")
    if m.bus_dump("uart") != exp:
        diffs.append("the instruction-level model's output differs from the expected output")
    ram, ref = bytearray(hw["ram"]), bytearray(m.mem)
    # words whose contents depend on how long things take (a program lists
    # them as ";! timing-dependent: sym ...")
    syms = programs.assemble(path).symbols
    for sym in programs.metadata(path).get("timing-dependent", "").split():
        a = syms[sym]
        ram[a:a + 4] = ref[a:a + 4] = bytes(4)
    if ram != ref:
        bad = [a for a in range(len(ref)) if ram[a] != ref[a]]
        diffs.append(f"RAM differs at {len(bad)} bytes, first {bad[0]:05X}: hardware {ram[bad[0]]:02X}, "
                     f"model {ref[bad[0]]:02X}")
    if hw["mem"] != m.bus_dump("mem"):
        diffs.append("the memory card differs")
    if hw["cf"] != m.bus_dump("cf"):
        diffs.append("the CF card's image differs")
    for i in range(16):
        if hw["regs_a"][i] != m.r[i] and not (i == 0):
            diffs.append(f"r{i}: hardware {hw['regs_a'][i]:08X}, model {m.r[i]:08X}")
            break
    if hw["regs_a"] != hw["regs_b"]:
        diffs.append("the register file's copies disagree")
    return diffs, hw, m


def _job(path):
    try:
        diffs, hw, m = check(path)
    except Exception as e:      # noqa: BLE001  (reported, not raised: one program per job)
        return path, [f"{type(e).__name__}: {e}"], None
    keep = {k: hw[k] for k in ("cycles", "time_ps", "wall_seconds", "violation_total",
                               "violation_summary", "contention")}
    return path, diffs, keep


def cmd_run(args):
    from . import machine
    trace = tuple(int(x) for x in args.trace.split(":")) if args.trace else None
    _img, hw = machine.run(args.file, max_cycles=args.max_cycles, trace=trace)
    diffs, hw, m = check(args.file, hw)
    print(f"{os.path.basename(args.file)} on the system:")
    print(runner.summarize(hw))
    print(f"  {hw['time_ps'] / 1e6:.1f} us, {hw['time_ps'] / 1000 / max(hw['cycles'], 1):.0f} ns "
          f"per cycle on average")
    if hw["output"]:
        print("  output: " + repr(hw["output"][:200]))
    if diffs:
        print("  MISMATCH:")
        for d in diffs[:12]:
            print("    " + d)
    else:
        print("  matches the instruction-level model")
    for line in hw.get("trace", []):
        print(line)
    return 1 if diffs or hw["violation_total"] else 0


def cmd_test(args):
    from . import programs
    paths = programs.program_paths(args.names or None)
    if args.isa:
        fails = 0
        for p in paths:
            name = os.path.basename(p)[:-2]
            _img, m = programs.run_isa(p)
            ok = m.bus_dump("uart") == programs.expected(name)
            fails += not ok
            print(f"{name:<14} {'ok' if ok else 'FAIL'} {m.cycles:>10} cycles")
        return 1 if fails else 0
    fails = 0
    with ProcessPoolExecutor(args.jobs) as ex:
        for path, diffs, hw in ex.map(_job, paths):
            name = os.path.basename(path)[:-2]
            ok = not diffs and hw and not hw["violation_total"]
            fails += not ok
            if hw:
                print(f"{name:<14} {'ok' if ok else 'FAIL':<5} {hw['cycles']:>9} cycles "
                      f"{hw['time_ps'] / 1e9:8.3f} ms  {hw['time_ps'] / 1000 / max(hw['cycles'], 1):5.0f} ns/cycle "
                      f"{hw['wall_seconds']:6.1f} s  violations {hw['violation_total']:>4}  "
                      f"contention max {hw['contention']['max_ps'] / 1000:.1f} ns", flush=True)
                for v in hw["violation_summary"][:4]:
                    print(f"    {v['what']}: {v['count']}x, worst slack {v['worst_slack_ps'] / 1000:.1f} ns")
            else:
                print(f"{name:<14} FAIL", flush=True)
            for d in diffs[:5]:
                print("    " + d)
    return 1 if fails else 0


def cmd_bom(args):
    from . import machine
    nl = machine.build()
    per = Counter()
    by_card = {}
    for inst in nl.instances:
        if inst.type.family in ("fixture", "passive"):
            continue
        card = inst.ref.split(".")[0]
        if args.card and card != args.card:
            continue
        by_card.setdefault(card, Counter())[inst.part_number()] += 1
        per[card] += 1
    for card, parts in sorted(by_card.items()):
        print(f"{card}: {sum(parts.values())} chips")
        for part, n in sorted(parts.items()):
            print(f"  {n:3} x {part}")
    print(f"{sum(per.values())} chips")
    return 0


def cmd_lengths(args):
    from . import lengths, machine
    cls, d = machine.classes()
    print(f"length classes (default parts, worst case): {d['lengths']} ticks of "
          f"{lengths.TICK:g} ns")
    print(f"the program suite: {d['ticks']:,} ticks, against {d['fixed_ticks']:,} at a fixed "
          f"{max(d['lengths'])} ticks ({d['fixed_ticks'] / d['ticks']:.3f}x)")
    print(f"microinstructions per class: {sorted(Counter(cls.values()).items())}")
    for variant in chips.VARIANTS:
        for corner in ("max", "typ"):
            print(f"  jumpers for {variant}, {corner}: {lengths.jumpers(cls, variant, corner)}")
    return 0


CARDS = {"BP": "Backplane", "CPU": "CPU card, slot 0", "MEM": "Memory card, slot 1",
         "IO": "I/O card, slot 15"}


def cmd_schematic(args):
    from heron import BUILD
    from heron.infra.hw import schematic
    from . import machine
    out = args.out or os.path.join(BUILD, "system", "schematic.html")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    html = schematic.page(machine.build(), "Heron draft 1b system", CARDS,
                          standalone=not args.fragment)
    with open(out, "w") as f:
        f.write(html)
    print(f"{out}: {len(html) // 1024} KB")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    p = argparse.ArgumentParser(prog="heron system", description="The system on the bus")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a program on the system at chip level")
    r.add_argument("file")
    r.add_argument("--trace", help="cycle range A:B to trace")
    r.add_argument("--max-cycles", type=int, default=20_000_000)
    r.set_defaults(fn=cmd_run)
    t = sub.add_parser("test", help="the program suite on the system")
    t.add_argument("names", nargs="*")
    t.add_argument("--jobs", type=int, default=4)
    t.add_argument("--isa", action="store_true", help="only on the instruction-level model")
    t.set_defaults(fn=cmd_test)
    b = sub.add_parser("bom", help="the parts list")
    b.add_argument("--card")
    b.set_defaults(fn=cmd_bom)
    sub.add_parser("lengths", help="the length classes").set_defaults(fn=cmd_lengths)
    sc = sub.add_parser("schematic", help="the schematic viewer")
    sc.add_argument("--out", help="where to write it (default build/system/schematic.html)")
    sc.add_argument("--fragment", action="store_true",
                    help="without the document around it, for a page host that adds it")
    sc.set_defaults(fn=cmd_schematic)
    args = p.parse_args(argv)
    return args.fn(args) or 0
