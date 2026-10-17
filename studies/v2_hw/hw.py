"""The draft 2 CPU at chip level: cpu.build(sim=True) on the chip-level
simulator's system run (infra/hwsim), checked against the
register-transfer model started the same way.

Both start from reset: the reset routine, then the reset vector at
physical 0, where the I/O processor's boot image (iop.boot_image) jumps to
a shim that maps the first 1 MB and starts the program at virtual 0. The
I/O page is on the card's data bus in both (System(io_local=True)), and
nothing answers in the other slots.

  heron v2_hw hw test [NAMES]       programs at chip level against the RTL
                                    model: output, registers, flags, PC,
                                    RAM, cycles and every decode
  heron v2_hw hw run PROG.s [--trace A:B]
  heron v2_hw hw sta [--paths N]    static timing analysis
  heron v2_hw hw bom                the parts list
"""

import argparse
import glob
import json
import os
import sys
import time

from heron import BUILD, native
from heron.infra.hw import runner

from . import cpu, iop, parts, rtl, system, ucode as uc

OUT = os.path.join(BUILD, "v2_hw")
HERE = os.path.dirname(os.path.abspath(__file__))
FETCH_TRACE = 100_000


def sources():
    """What the netlist and the preloads are built from."""
    from heron.studies.v2_isa import v2
    return runner.infra_sources() + glob.glob(os.path.join(HERE, "*.py")) + [v2.__file__]


def netlist(lengths=None):
    """The simulation netlist, exported (cached in build/v2_hw)."""
    lengths = tuple(lengths or uc.built().lengths)
    path = os.path.join(OUT, f"netlist-{'-'.join(map(str, lengths))}.json")
    if not os.path.exists(path) or os.path.getmtime(path) < runner.newest(sources()):
        os.makedirs(OUT, exist_ok=True)
        nl = cpu.build(sim=True, lengths=lengths)
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(nl.export(variant=parts.VARIANT, corner="max"), f)
        os.replace(tmp, path)
    with open(path) as f:
        return json.load(f)


def preloads(mem, inp):
    """The memories' contents at the end of reset: the control store and the
    decode table (the microcode, as the I/O processor writes them), the
    RAM ({physical address: byte}), the register file cleared, the input."""
    mc = uc.built()
    pre = {}
    rom = mc.rom()
    for k in range(uc.WORD_BITS // 16):
        for h in range(2):
            img = bytearray(1 << 16)
            sh = 16 * k + 8 * h
            for a, w in rom.items():
                img[a] = (w >> sh) & 0xFF
            pre[f"U_CS{k}{'LH'[h]}"] = bytes(img)
    dec = mc.decode_table()
    pre["U_DECL"] = bytes(d & 0xFF for d in dec)
    pre["U_DECH"] = bytes(d >> 8 for d in dec)
    ram = [bytearray(1 << 19) for _ in range(4)]
    for a, b in mem.items():
        if a < 0x200000:
            ram[a & 3][a >> 2] = b
    for k in range(4):
        pre[f"U_RAM{k}"] = bytes(ram[k])
    for side in "AB":
        for k in range(4):
            pre[f"U_RF{side}{k}"] = bytes(1 << 16)
    pre["X_IO"] = bytes(inp)
    return pre


FLAGS = ("NFLAG", "ZFLAG", "CFLAG", "VFLAG", "IFLAG", "SFLAG", "TFLAG")


def trace_buses():
    def b(name, n, start=0):
        return [f"{name}{i}" for i in range(start, start + n)]
    return {"Y": b("Y", uc.Y_BITS), "UA": b("UA", 3), "PC": ["GND"] + b("PC", 31, 1),
            "QH": b("QH", 16), "IR": b("IR", 16), "ABUS": b("ABUS", 32), "BBUS": b("BBUS", 32),
            "RES": b("RES", 32), "R": b("RQ", 32), "VA": b("VA", 32), "DB": b("DB", 32),
            "MAR": b("MAR", 32), "LC": b("LC", 8), "V": ["V0", "V1"],
            "F": ["FAULT", "DECGO", "FREFILL_n", "JUMP", "FETCHED"], "FL": list(FLAGS),
            "SQ": ["DECACT", "HALTACT", "TSQ", "IRQP", "COMPLETE", "YOFF", "UF0", "UF1", "FTRACE",
                   "FIRQ", "W2", "W3", "FITS1", "FOK", "PC1F"]}


def config(max_cycles, trace=None, fetch_trace=FETCH_TRACE, seed=1):
    """seed: the simulator's random power-up state of every flip-flop."""
    cfg = {
        "seed": seed, "max_cycles": max_cycles,
        "clock_net": "CLK", "reset_net": "RESET_n",
        "fetch_net": "DECGO", "fetch_level": 1,
        "addr_nets": ["GND"] + [f"PC{i}" for i in range(1, 32)],
        "data_nets": [f"QH{i}" for i in range(16)],
        "fetch_trace": fetch_trace,
        # HALT, nothing pending, interrupts off
        "stop_when": [[("uSEQ0", 1), ("uSEQ1", 1), ("IRQP", 0), ("FAULT", 0), ("IFLAG", 0)]],
        "dump": ["X_IO"] + [f"U_RAM{k}" for k in range(4)]
        + [f"U_RF{s}{k}" for s in "AB" for k in range(4)],
        "observe": list(FLAGS) + [f"PC{i}" for i in range(1, 32)],
    }
    if trace:
        cfg.update(trace_from=trace[0], trace_to=trace[1], trace_buses=trace_buses())
    return cfg


def run(mem, inp=b"", max_cycles=20_000_000, trace=None, lengths=None, seed=1):
    """Run a RAM image at chip level: the outcome, decoded."""
    hw = native.hwsim.run_system(netlist(lengths), config(max_cycles, trace, seed=seed),
                                 preloads(mem, inp))
    d = hw["dumps"]
    hw["output"] = bytes(d["X_IO"])
    ram = bytearray(4 << 19)
    for k in range(4):
        ram[k::4] = d[f"U_RAM{k}"]
    hw["ram"] = bytes(ram)
    for side in "AB":
        chips = [d[f"U_RF{side}{k}"] for k in range(4)]
        hw[f"rf_{side.lower()}"] = [sum(chips[k][a] << (8 * k) for k in range(4))
                                    for a in range(0x2000)]
    n = hw["nets"]
    hw["pc"] = sum(n[f"PC{i}"] << i for i in range(1, 32))
    hw["flags"] = {f: n[f] for f in FLAGS}
    return hw


def reference(mem, inp=b"", max_cycles=200_000_000):
    """The RTL model from reset, as the chip-level run starts: with the
    decodes it makes, (cycle from the first, PC, parcel)."""
    s = system.System(io_local=True)
    s.add(system.IO_WINDOW, system.ConsoleCard(inp))
    for a, b in mem.items():
        s.poke(a, b)
    m = rtl.RTL(s)
    m.fetch_log = []

    def log(mm):
        if not mm.fetch_log:
            mm.ticks0 = mm.ticks                # the program's time leaves reset out
        mm.fetch_log.append((mm.cycles - 1, (mm.PC - 2) & 0xFFFFFFFF, mm.IR))
    m.trace = log
    m.run(max_cycles)
    c0 = m.fetch_log[0][0]
    m.fetch_log = [(c - c0 - 1, a, w) for c, a, w in m.fetch_log]
    m.prog_cycles = m.cycles - c0 - 1
    return m


def compare(m, hw):
    """Differences between the RTL model's run and the chip-level one."""
    diffs = []
    if not hw["halted"]:
        diffs.append(f"the hardware did not halt: {hw['reason']}")
    if hw["output"] != m.out:
        diffs.append(f"output differs: hardware {hw['output'][:80]!r}, RTL {m.out[:80]!r}")
    if hw["cycles"] != m.prog_cycles:
        diffs.append(f"cycles: hardware {hw['cycles']}, RTL {m.prog_cycles}")
    for i in range(0x2000):
        if hw["rf_a"][i] != m.rf[i]:
            diffs.append(f"RF[{i:04X}]: hardware {hw['rf_a'][i]:08X}, RTL {m.rf[i]:08X}")
            break
    if hw["rf_a"] != hw["rf_b"]:
        diffs.append("the register file's copies differ")
    for f, attr in zip(FLAGS, "nzcvist"):
        if hw["flags"][f] != getattr(m, attr):
            diffs.append(f"flag {f[0]}: hardware {hw['flags'][f]}, RTL {getattr(m, attr)}")
    if hw["pc"] != m.PC:
        diffs.append(f"PC: hardware {hw['pc']:08X}, RTL {m.PC:08X}")
    if hw["ram"] != bytes(m.sys.ram):
        bad = [a for a in range(len(m.sys.ram)) if hw["ram"][a] != m.sys.ram[a]]
        a = bad[0]
        diffs.append(f"RAM differs at {len(bad)} bytes, first {a:06X}: hardware "
                     f"{hw['ram'][a]:02X}, RTL {m.sys.ram[a]:02X}")
    for i, (h, r) in enumerate(zip(hw["fetches"], m.fetch_log)):
        if tuple(h) != tuple(r):
            diffs.append(f"decode #{i}: hardware cycle {h[0]} PC {h[1]:08X} parcel {h[2]:04X}; "
                         f"RTL cycle {r[0]} PC {r[1]:08X} parcel {r[2]:04X}")
            break
    if hw["fetch_count"] != len(m.fetch_log):
        diffs.append(f"decodes: hardware {hw['fetch_count']}, RTL {len(m.fetch_log)}")
    return diffs


def check(path, trace=None, lengths=None):
    """(name, differences, hardware outcome) for one program."""
    from heron.infra import asm as asmcore
    from heron.infra import isas
    from heron.infra.programs import metadata
    img = asmcore.assemble_file(isas.get("v2"), path)
    inp = metadata(path)["input"]
    mem = iop.boot_image(img)
    m = reference(mem, inp)
    hw = run(mem, inp, max_cycles=m.cycles + 1000, trace=trace, lengths=lengths)   # reset too
    return m, hw, compare(m, hw)


def summarize(hw):
    out = [f"  {hw['cycles']} cycles, {hw['time_ps'] / 1e9:.3f} ms, {hw['events']:,} events, "
           f"{hw['wall_seconds']:.1f} s wall"]
    if hw["violation_total"]:
        out.append(f"  {hw['violation_total']} timing violations:")
        for v in hw["violation_summary"][:10]:
            out.append(f"    {v['what']}: {v['count']}x, worst slack {v['worst_slack_ps'] / 1000:.1f} ns")
    c = hw["contention"]
    if c["count"]:
        out.append(f"  bus contention: {c['count']} episodes, longest {c['max_ps'] / 1000:.1f} ns "
                   f"({', '.join(n['net'] for n in c['worst_nets'][:6])})")
    return "\n".join(out)


def cmd_test(args):
    from . import check as chk
    import heron.studies.v2_isa  # noqa: F401
    paths = chk.program_paths(args.names or None)
    bad = 0
    for p in paths:
        name = os.path.basename(p)[:-2]
        if name in ("systest", "isanotes", "interrupts") and not args.names:
            continue
        t0 = time.time()
        m, hw, diffs = check(p, lengths=args.lengths)
        ok = not diffs and not hw["violation_total"]
        bad += not ok
        print(f"{name:12s} {'ok  ' if ok else 'FAIL'} {hw['cycles']:9d} cycles "
              f"{hw['time_ps'] / 1e9:8.3f} ms (RTL {(m.ticks - m.ticks0) * 20 / 1e6:8.3f} ms)  "
              f"violations {hw['violation_total']:5d}  ({time.time() - t0:.0f} s)")
        for d in diffs[:6]:
            print(f"    {d}")
        if hw["violation_total"]:
            print(summarize(hw))
    return 1 if bad else 0


def cmd_run(args):
    import heron.studies.v2_isa  # noqa: F401
    trace = tuple(int(x) for x in args.trace.split(":")) if args.trace else None
    m, hw, diffs = check(args.file, trace, args.lengths)
    print(summarize(hw))
    sys.stdout.write(hw["output"].decode("latin-1"))
    print()
    for d in diffs:
        print("  " + d)
    if trace:
        for line in hw["trace"]:
            print(line)
    return 1 if diffs else 0


def cmd_bom(args):
    nl = cpu.build(sim=True)
    packages = nl.packages(parts.VARIANT)
    for part, refs in nl.bom(parts.VARIANT).items():
        n = packages[part]
        halves = f" ({len(refs)} halves)" if n != len(refs) else ""
        print(f"{n:3} x {part:<16} {' '.join(refs[:8])}{' ...' if len(refs) > 8 else ''}{halves}")
    print(f"{sum(packages.values())} packages")
    return 0


def cmd_sta(args):
    from . import sta
    return sta.main(args)


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron v2_hw hw")
    sub = p.add_subparsers(dest="cmd", required=True)
    def lens(v):
        return tuple(int(x) for x in v.split(","))
    t = sub.add_parser("test")
    t.add_argument("names", nargs="*")
    t.add_argument("--lengths", type=lens, help="the length classes' ticks, e.g. 8,9,10,12")
    t.set_defaults(fn=cmd_test)
    r = sub.add_parser("run")
    r.add_argument("file")
    r.add_argument("--trace")
    r.add_argument("--lengths", type=lens)
    r.set_defaults(fn=cmd_run)
    b = sub.add_parser("bom")
    b.set_defaults(fn=cmd_bom)
    s = sub.add_parser("sta")
    s.add_argument("--paths", type=int, default=3)
    s.add_argument("--force", action="store_true", help="redo the analysis, not the cached one")
    s.add_argument("--write", action="store_true",
                   help="write ticks.json, the measured periods the microcode's classes come from")
    s.add_argument("--no-profile", action="store_true",
                   help="without the suite's counts (which take minutes the first time)")
    s.set_defaults(fn=cmd_sta)
    args = p.parse_args(argv)
    return args.fn(args)
