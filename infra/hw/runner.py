"""Running a machine on the chip-level simulator (infra/hwsim), and the
command line for it: `heron <study> hw <command>`.

  bom      [--variant V]                     parts list
  run      PROG.s [--period NS] [--variant V] [--corner typ|max] [--trace A:B]
                                             run on the timing simulator and
                                             cross-check against the ISA simulator
  test     [NAMES] [--period NS] ...         run programs on the timing simulator
  sweep    PROG.s [--variant V] [--corner C] find the shortest clock period that works
  sta      [--variant V] [--corner C]        static timing analysis

Everything here takes a *machine*: a module that describes one design to
these tools. A machine module has:

  NAME          short name ("v0", "v1b"), used in file names under build/
  UCODE_DIR     directory under build/ for its ROM images
  NETLIST_TAG   prefix for its netlist files in build/ ("" or "v1b-")
  RAM_BYTES     size of the RAM image handed to the simulator
  CONFIG        the simulator's settings for this machine: the nets and chips
                its run loop needs (see infra/hwsim/src/machine.rs)
  ucode         module with unpack() and _pos, to decode microcode in traces
  build()       the netlist (heron.infra.hw.netlist.Netlist)
  control_nets()  {control word bit: net name}
  rom_names()   {chip reference: file name}
  rom_images()  {chip reference: bytes}
  sources()     files the ROM images and netlist are built from
  trace_buses() {name: [nets]} for --trace
  run_isa(path, inp)        (image, reference run) from the instruction-level model
  compare(m, hw, check_cycles)  differences between the reference and the hardware
  program_paths(names)      the test programs
  sta_words()   {(control word, extra constants): [labels]} for static timing
"""

import argparse
import glob
import json
import os
import sys

from heron import BUILD, native
from heron.infra.programs import metadata
from . import chips


def newest(paths):
    return max(os.path.getmtime(p) for p in paths)


def infra_sources():
    """The files in infra/hw that every machine's ROM images and netlists
    are built with: the netlist language, the chip library and its timing."""
    here = os.path.dirname(os.path.abspath(__file__))
    return glob.glob(os.path.join(here, "*.py")) + [chips.TIMING_PATH]


def ensure_ucode(machine):
    """The machine's ROM images, rebuilt if out of date: {chip reference: file}."""
    out = os.path.join(BUILD, machine.UCODE_DIR)
    names = machine.rom_names()
    files = {ref: os.path.join(out, n) for ref, n in names.items()}
    if not all(os.path.exists(f) for f in files.values()) or \
            min(os.path.getmtime(f) for f in files.values()) < newest(machine.sources()):
        os.makedirs(out, exist_ok=True)
        for ref, img in machine.rom_images().items():
            with open(files[ref], "wb") as f:
                f.write(img)
    return files


def ensure_netlist(machine, variant, corner):
    path = os.path.join(BUILD, f"netlist-{machine.NETLIST_TAG}{variant}-{corner}.json")
    if not os.path.exists(path) or os.path.getmtime(path) < newest(machine.sources()):
        os.makedirs(BUILD, exist_ok=True)
        nl = machine.build()
        tmp = f"{path}.{os.getpid()}"          # runs in parallel may build it at once
        with open(tmp, "w") as f:
            json.dump(nl.export(variant=variant, corner=corner), f)
        os.replace(tmp, path)
    return path


def run_hw(machine, img, period_ns, variant=chips.DEFAULT_VARIANT, corner="max", seed=1, inp=b"",
           max_cycles=10_000_000, trace=None, fetch_trace=200_000, we=(0.5, 0.875), zero_regs=True):
    """Run a program image on the chip-level simulator. Returns its outcome
    (infra/hwsim/src/machine.rs): cycles, registers, RAM, the console
    output, fetches, timing violations, bus contention, and with
    trace=(first, last) cycle the trace lines."""
    roms = {}
    for ref, path in ensure_ucode(machine).items():
        with open(path, "rb") as f:
            roms[ref] = f.read()
    with open(ensure_netlist(machine, variant, corner)) as f:
        netlist = json.load(f)
    cfg = {
        "period_ps": int(round(period_ns * 1000)), "seed": seed,
        "we_start": we[0], "we_end": we[1],
        "max_cycles": max_cycles, "input": inp, "fetch_trace": fetch_trace,
        "zero_regs": zero_regs,
    }
    cfg.update(machine.CONFIG)
    if trace:
        cfg.update(trace_from=trace[0], trace_to=trace[1], trace_buses=machine.trace_buses())
    return native.hwsim.run(netlist, cfg, roms, img.to_bytes(machine.RAM_BYTES))


def summarize(hw):
    lines = [f"  {hw['cycles']} cycles, {hw['events']:,} events, {hw['wall_seconds']:.1f} s wall "
             f"({hw['cycles'] / max(hw['wall_seconds'], 1e-9):,.0f} cycles/s)"]
    if hw["violation_total"]:
        lines.append(f"  {hw['violation_total']} timing violations:")
        for v in hw["violation_summary"][:8]:
            lines.append(f"    {v['what']}: {v['count']}x, worst slack {v['worst_slack_ps'] / 1000:.1f} ns")
    c = hw["contention"]
    if c["count"]:
        lines.append(f"  bus contention: {c['count']} episodes, longest {c['max_ps'] / 1000:.1f} ns "
                     f"({', '.join(f'{k} {v}' for k, v in c['histogram'].items() if v)})")
    return "\n".join(lines)


def decode_trace(machine, lines, out=None):
    out = out or sys.stdout             # sys.stdout now, not when this module was imported
    mc = machine.ucode
    for line in lines:
        parts = line.split()
        fields = dict(p.split("=") for p in parts[1:])
        u = mc.unpack(int(fields.pop("U"), 16))
        active = []
        for name, (_, w, _) in mc._pos.items():
            if u[name]:
                active.append(name if w == 1 else f"{name}={u[name]}")
        out.write(f"{parts[0]:>6} " + " ".join(f"{k}={v}" for k, v in fields.items()) + "\n")
        out.write(f"{'':>6}   {' '.join(active)}\n")


def program_input(path):
    return metadata(path)["input"]


def cmd_run(machine, args):
    inp = program_input(args.file)
    img, m = machine.run_isa(args.file, inp)
    trace = tuple(int(x) for x in args.trace.split(":")) if args.trace else None
    hw = run_hw(machine, img, args.period, args.variant, args.corner, args.seed, inp,
                max_cycles=m.cycles + 1000, trace=trace)
    uses_irq = m.irqs > 0
    diffs = machine.compare(m, hw, check_cycles=not uses_irq)
    print(f"{os.path.basename(args.file)} at {args.period} ns ({args.variant}, {args.corner} delays):")
    print(summarize(hw))
    if hw["output"]:
        print("  output: " + repr(hw["output"][:200]))
    if diffs:
        print("  MISMATCH vs ISA simulator:")
        for d in diffs[:12]:
            print("    " + d)
    else:
        print("  matches the ISA simulator" + (" (cycle-exact)" if not uses_irq else ""))
    if trace:
        decode_trace(machine, hw["trace"])
    return 1 if diffs or hw["violation_total"] else 0


def cmd_test(machine, args):
    paths = machine.program_paths(args.names or None)
    fails = 0
    for p in paths:
        inp = program_input(p)
        img, m = machine.run_isa(p, inp)
        if m.cycles > args.max_cycles:
            print(f"{os.path.basename(p):<14} skipped ({m.cycles:,} cycles > --max-cycles)")
            continue
        hw = run_hw(machine, img, args.period, args.variant, args.corner, args.seed, inp,
                    max_cycles=m.cycles + 1000)
        diffs = machine.compare(m, hw, check_cycles=m.irqs == 0)
        ok = not diffs and not hw["violation_total"]
        fails += not ok
        print(f"{os.path.basename(p):<14} {'ok' if ok else 'FAIL':<5} {hw['cycles']:>9} cycles "
              f"{hw['wall_seconds']:6.1f} s  violations {hw['violation_total']:>5}  "
              f"contention max {hw['contention']['max_ps'] / 1000:.1f} ns")
        for d in diffs[:5]:
            print("    " + d)
    return 1 if fails else 0


def passes(machine, img, m, inp, period, variant, corner, seed=1):
    hw = run_hw(machine, img, period, variant, corner, seed, inp, max_cycles=m.cycles + 1000,
                fetch_trace=0)
    diffs = machine.compare(m, hw, check_cycles=False)
    return (not diffs and hw["violation_total"] == 0), hw, diffs


def cmd_sweep(machine, args):
    inp = program_input(args.file)
    img, m = machine.run_isa(args.file, inp)
    lo, hi = args.lo, args.hi
    ok, hw, _ = passes(machine, img, m, inp, hi, args.variant, args.corner)
    if not ok:
        print(f"fails even at {hi} ns:\n{summarize(hw)}")
        return 1
    while hi - lo > args.step:
        mid = round((lo + hi) / 2, 1)
        ok, hw, diffs = passes(machine, img, m, inp, mid, args.variant, args.corner)
        print(f"  {mid:7.1f} ns: {'ok' if ok else 'fails'}"
              + ("" if ok else f" ({hw['violation_total']} violations{', wrong result' if diffs else ''})"))
        if ok:
            hi = mid
        else:
            lo = mid
    print(f"shortest working period: {hi} ns ({1000 / hi:.2f} MHz)")
    return 0


def cmd_bom(machine, args):
    nl = machine.build()
    total = 0
    for part, refs in nl.bom(args.variant).items():
        print(f"{len(refs):3} x {part:<16} {' '.join(refs[:8])}{' ...' if len(refs) > 8 else ''}")
        total += len(refs)
    print(f"{total} chips")
    return 0


def cmd_sta(machine, args):
    from . import sta
    return sta.cmd_sta(machine, args)


def main(argv, machine, prog=None):
    p = argparse.ArgumentParser(prog=prog or f"heron {machine.NAME} hw")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--variant", default=chips.DEFAULT_VARIANT, choices=list(chips.VARIANTS))
        sp.add_argument("--corner", default="max", choices=["typ", "max"])
        sp.add_argument("--seed", type=int, default=1)

    r = sub.add_parser("run")
    r.add_argument("file")
    r.add_argument("--period", type=float, default=500.0, help="clock period in ns")
    r.add_argument("--trace", help="cycle range A:B to trace")
    common(r)
    r.set_defaults(fn=cmd_run)

    t = sub.add_parser("test")
    t.add_argument("names", nargs="*")
    t.add_argument("--period", type=float, default=500.0)
    t.add_argument("--max-cycles", type=int, default=3_000_000)
    common(t)
    t.set_defaults(fn=cmd_test)

    s = sub.add_parser("sweep")
    s.add_argument("file")
    s.add_argument("--lo", type=float, default=100.0)
    s.add_argument("--hi", type=float, default=600.0)
    s.add_argument("--step", type=float, default=2.0)
    common(s)
    s.set_defaults(fn=cmd_sweep)

    b = sub.add_parser("bom")
    b.add_argument("--variant", default=chips.DEFAULT_VARIANT, choices=list(chips.VARIANTS))
    b.set_defaults(fn=cmd_bom)

    st = sub.add_parser("sta")
    common(st)
    st.add_argument("--paths", type=int, default=5)
    st.set_defaults(fn=cmd_sta)

    args = p.parse_args(argv)
    return args.fn(machine, args)
