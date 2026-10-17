"""Heron Mini at chip level: board.build(sim=True) on the chip-level
simulator's system run (infra/hwsim), checked against the register-transfer
model started the same way.

Both start from reset: the reset routine, then the reset vector at 0,
where the program's image is in the RAM. The suite's I/O page is the test
fixture in I/O region 7, on the data bus, in both.

  heron mini hw test [NAMES]        programs at chip level against the RTL
                                    model: output, registers, flags, PC,
                                    RAM, cycles and every decode
  heron mini hw run PROG.s [--trace A:B]
  heron mini hw bom                 the parts list
"""

import argparse
import glob
import json
import os
import sys
import time

from heron import BUILD, native
from heron.infra.hw import runner

from . import board, parts, rtl, system, ucode as uc
from .timing import TICK

OUT = os.path.join(BUILD, "mini")
HERE = os.path.dirname(os.path.abspath(__file__))
FETCH_TRACE = 100_000


def sources():
    """What the netlist and the preloads are built from."""
    from heron.studies.v2_isa import v2
    return runner.infra_sources() + glob.glob(os.path.join(HERE, "*.py")) + [v2.__file__]


_LOADED = None


def netlist(lengths=None):
    """The simulation netlist, exported (cached in build/mini). The cache
    is dated by the sources as this process first read them, so a run that
    started before an edit can't pass its netlist off as the new one."""
    global _LOADED
    if _LOADED is None:
        _LOADED = runner.newest(sources())
    lengths = tuple(lengths or uc.built().lengths)
    path = os.path.join(OUT, f"netlist-{'-'.join(map(str, lengths))}.json")
    if not os.path.exists(path) or os.path.getmtime(path) < runner.newest(sources()):
        os.makedirs(OUT, exist_ok=True)
        nl = board.build(sim=True, lengths=lengths)
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(nl.export(variant=parts.VARIANT, corner="max"), f)
        os.utime(tmp, (_LOADED, _LOADED))
        os.replace(tmp, path)
    with open(path) as f:
        return json.load(f)


_rom_images = None


def rom_images():
    """The control store's seventeen flash images, one a byte of the word."""
    global _rom_images
    if _rom_images is None:
        rom = uc.built().rom()
        imgs = [bytearray(uc.CS_WORDS) for _ in range(uc.WORD_BITS // 8)]
        for a, w in rom.items():
            for k in range(len(imgs)):
                imgs[k][a] = (w >> (8 * k)) & 0xFF
        _rom_images = [bytes(i) for i in imgs]
    return _rom_images


def preloads(ram, inp):
    """The memories' contents at the end of reset: the control store, the
    RAM (4 MB), the register file cleared, the input."""
    pre = {f"U_CS{k}": img for k, img in enumerate(rom_images())}
    for bank in range(2):
        for k in range(4):
            pre[f"U_RAM{bank}{k}"] = bytes(ram[(bank << 21) + k:(bank + 1) << 21:4])
    for side in "AB":
        for k in range(4):
            pre[f"U_RF{side}{k}"] = bytes(1 << 15)
    pre["X_IO"] = bytes(inp)
    return pre


FLAGS = ("NFLAG", "ZFLAG", "CFLAG", "VFLAG", "IFLAG")


def trace_buses():
    def b(name, n, start=0):
        return [f"{name}{i}" for i in range(start, start + n)]
    return {"Y": b("Y", uc.Y_BITS), "YU": b("YU", 3) + ["YE"], "PC": ["GND"] + b("PC", 31, 1),
            "QH": b("QH", 16), "IR": b("IR", 16), "ABUS": b("ABUS", 32), "BBUS": b("BBUS", 32),
            "RES": b("RES", 32), "R": b("RQ", 32), "VA": b("VA", 22), "DB": b("DB", 32),
            "MAR": b("MAR", 22), "LC": b("LC", 8), "V": ["V0", "V1", "HS", "PC1F"],
            "S": ["DECGO", "JUMP", "FETCHED", "SHIFT", "PEND", "XL", "UF0", "FIRQ",
                  "QLE0", "QLE1", "T1", "T2", "HOLD", "MID", "LATE"], "FL": list(FLAGS)}


def config(max_cycles, trace=None, fetch_trace=FETCH_TRACE, seed=1):
    """seed: the simulator's random power-up state of every flip-flop."""
    cfg = {
        "seed": seed, "max_cycles": max_cycles,
        "max_ps": int(max_cycles * 30 * 20_000),       # a stopped clock ends the run too
        "clock_net": "CLK", "reset_net": "RESET_n",
        "fetch_net": "DECGO", "fetch_level": 1,
        "addr_nets": ["GND"] + [f"PC{i}" for i in range(1, 32)],
        "data_nets": [f"QH{i}" for i in range(16)],
        "fetch_trace": fetch_trace,
        # HALT, nothing pending, interrupts off
        "stop_when": [[("uSEQ0", 1), ("uSEQ1", 1), ("PEND", 0), ("IFLAG", 0)]],
        "dump": ["X_IO"] + [f"U_RAM{b}{k}" for b in range(2) for k in range(4)]
        + [f"U_RF{s}{k}" for s in "AB" for k in range(4)],
        "observe": list(FLAGS) + [f"PC{i}" for i in range(1, 32)],
    }
    if trace:
        cfg.update(trace_from=trace[0], trace_to=trace[1], trace_buses=trace_buses())
    return cfg


def run(ram, inp=b"", max_cycles=20_000_000, trace=None, lengths=None, seed=1):
    """Run a RAM image at chip level: the outcome, decoded."""
    nl = netlist(lengths)
    hw = native.hwsim.run_system(nl, config(max_cycles, trace, seed=seed), preloads(ram, inp))
    d = hw["dumps"]
    hw["output"] = bytes(d["X_IO"])
    out = bytearray(system.RAM_SIZE)
    for bank in range(2):
        for k in range(4):
            out[(bank << 21) + k:(bank + 1) << 21:4] = d[f"U_RAM{bank}{k}"]
    hw["ram"] = bytes(out)
    for side in "AB":
        chips = [d[f"U_RF{side}{k}"] for k in range(4)]
        hw[f"rf_{side.lower()}"] = [sum(chips[k][a] << (8 * k) for k in range(4))
                                    for a in range(32)]
    n = hw["nets"]
    hw["pc"] = sum(n[f"PC{i}"] << i for i in range(1, 32))
    hw["flags"] = {f: n[f] for f in FLAGS}
    return hw


def reference(image, inp=b"", max_cycles=200_000_000):
    """The RTL model from reset, as the chip-level run starts: with the
    decodes it makes, (cycle from the first, PC, parcel)."""
    s = system.System(inp=inp)
    s.load(image)
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
    for i in range(16):
        if hw["rf_a"][i] != m.rf[i]:
            diffs.append(f"r{i}: hardware {hw['rf_a'][i]:08X}, RTL {m.rf[i]:08X}")
            break
    if hw["rf_a"] != hw["rf_b"]:
        diffs.append("the register file's copies differ")
    for f, attr in zip(FLAGS, "nzcvi"):
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


def check(path, trace=None, lengths=None, seed=1):
    """(RTL model, hardware outcome, differences) for one program."""
    from heron.infra import asm as asmcore
    from heron.infra import isas
    from heron.infra.programs import metadata
    img = asmcore.assemble_file(isas.get("v2"), path)
    inp = metadata(path)["input"]
    m = reference(img, inp)
    ram = bytearray(system.RAM_SIZE)
    for a, b in img.mem.items():
        ram[a] = b
    hw = run(ram, inp, max_cycles=m.cycles + 1000, trace=trace, lengths=lengths, seed=seed)
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
        if name == "interrupts" and not args.names:
            continue
        t0 = time.time()
        m, hw, diffs = check(p, lengths=args.lengths, seed=args.seed)
        ok = not diffs and not hw["violation_total"]
        bad += not ok
        print(f"{name:12s} {'ok  ' if ok else 'FAIL'} {hw['cycles']:9d} cycles "
              f"{hw['time_ps'] / 1e9:8.3f} ms (RTL {(m.ticks - m.ticks0) * TICK / 1e6:8.3f} ms)  "
              f"violations {hw['violation_total']:5d}  ({time.time() - t0:.0f} s)")
        for d in diffs[:6]:
            print(f"    {d}")
        if hw["violation_total"]:
            print(summarize(hw))
    return 1 if bad else 0


def cmd_run(args):
    import heron.studies.v2_isa  # noqa: F401
    trace = tuple(int(x) for x in args.trace.split(":")) if args.trace else None
    m, hw, diffs = check(args.file, trace, args.lengths, args.seed)
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
    nl = board.build(sim=True)
    packages = nl.packages(parts.VARIANT)
    for part, refs in nl.bom(parts.VARIANT).items():
        n = packages[part]
        print(f"{n:3} x {part:<22} {' '.join(refs[:8])}{' ...' if len(refs) > 8 else ''}")
    print(f"{sum(packages.values())} packages")
    return 0


def cmd_sta(args):
    from . import sta
    return sta.main(args)


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron mini hw")
    sub = p.add_subparsers(dest="cmd", required=True)

    def lens(v):
        return tuple(int(x) for x in v.split(","))
    t = sub.add_parser("test")
    t.add_argument("names", nargs="*")
    t.add_argument("--lengths", type=lens, help="the length classes' ticks, e.g. 8,9,10,12")
    t.add_argument("--seed", type=int, default=1)
    t.set_defaults(fn=cmd_test)
    r = sub.add_parser("run")
    r.add_argument("file")
    r.add_argument("--trace")
    r.add_argument("--lengths", type=lens)
    r.add_argument("--seed", type=int, default=1)
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
