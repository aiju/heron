"""Chibi Heron at chip level: board.build(sim=True) on the chip-level
simulator's system run (infra/hwsim), checked against the register-transfer
model.

Both start from reset (the reset routine, then the program at 0, its image
in the RAM); the suite's I/O page is a test fixture at 0xFFFF_FF00.

  heron chibi hw test [NAMES]       programs at chip level against the RTL
                                    model: output, registers, flags, RAM, and
                                    every instruction fetch with its cycle
  heron chibi hw run PROG.s [--trace A:B]
  heron chibi hw sta [--paths N]    static timing analysis (sta.py)
  heron chibi hw sta2 [--suite]     the two-halves variant's (sta2.py)
  heron chibi hw halves             its time on the suite, folded (halves.py)
  heron chibi hw bom                the parts list
"""

import argparse
import glob
import json
import os
import sys

from heron import BUILD, native
from heron.infra.hw import runner

from . import board, check, parts, routines, ucode as uc

OUT = os.path.join(BUILD, "chibi")
HERE = os.path.dirname(os.path.abspath(__file__))


def sources():
    return runner.infra_sources() + glob.glob(os.path.join(HERE, "*.py"))


_LOADED = None


def netlist():
    """The simulation netlist, exported (cached in build/chibi)."""
    global _LOADED
    if _LOADED is None:
        _LOADED = runner.newest(sources())
    path = os.path.join(OUT, "netlist.json")
    if not os.path.exists(path) or os.path.getmtime(path) < _LOADED:
        os.makedirs(OUT, exist_ok=True)
        nl = board.build(sim=True)
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(nl.export(variant=parts.VARIANT, corner="max"), f)
        os.utime(tmp, (_LOADED, _LOADED))
        os.replace(tmp, path)
    with open(path) as f:
        return json.load(f)


_ROMS = None


def rom_images():
    """The control store's nine flash images, one a byte of the word."""
    global _ROMS
    if _ROMS is None:
        words = routines.control_store().words
        imgs = [bytearray(uc.CS_WORDS) for _ in range(uc.ROMS)]
        for a, w in enumerate(words):
            for k in range(uc.ROMS):
                imgs[k][a] = (w >> (8 * k)) & 0xFF
        _ROMS = [bytes(i) for i in imgs]
    return _ROMS


def preloads(ram, inp=b"", kbd=b"", mouse=b""):
    pre = {f"U_CS{k}": img for k, img in enumerate(rom_images())}
    for r in range(2):
        for b in range(2):
            pre[f"U_RAM{r}{b}"] = bytes(ram[(r << 20) + b:(r + 1) << 20:2])
    for k in range(2):
        pre[f"U_RF{k}"] = bytes(1 << 15)
    pre["U_BOOT"] = bytes([0xFF]) * 0x20000
    pre["X_IO"] = bytes(inp)
    pre["U_UART0"] = b""
    pre["U_UART1"] = b""
    pre["X_KBD"] = bytes(kbd)
    pre["X_MOUSE"] = bytes(mouse)
    return pre


FLAGS = ("F_N", "F_Z", "F_C", "F_V", "F_I")


def trace_buses():
    def b(name, n, start=0):
        return [f"{name}{i}" for i in range(start, start + n)]
    return {"STEP": b("STEP", 5), "OP": b("OP", 8), "N": b("N", 4), "PAGE": b("PAGE", 2),
            "D": b("D", 16), "MD": b("MD", 16), "A": b("A", 21), "F": b("F", 16), "L": b("L", 16),
            "RA": b("RA", 6), "FL": list(FLAGS) + ["F_IC", "F_ST"]}


def config(max_cycles, trace=None, fetch_trace=200_000, seed=1):
    cfg = {
        "seed": seed, "max_cycles": max_cycles,
        "max_ps": int(max_cycles * 200_000) + 10_000_000,
        "clock_net": "CLK0", "reset_net": "RESET_n",
        "fetch_net": "LDIR", "fetch_level": 1,
        "addr_nets": [f"A{i}" for i in range(21)],
        "data_nets": [f"MD{i}" for i in range(16)],
        "fetch_trace": fetch_trace,
        "stop_when": [[("uHALT", 1)]],
        "dump": ["X_IO"] + [f"U_RAM{r}{b}" for r in range(2) for b in range(2)]
        + ["U_RF0", "U_RF1"],
        "observe": list(FLAGS),
    }
    if trace:
        cfg.update(trace_from=trace[0], trace_to=trace[1], trace_buses=trace_buses())
    return cfg


def run(ram, inp=b"", max_cycles=20_000_000, trace=None, seed=1, kbd=b"", mouse=b""):
    """A RAM image at chip level: the outcome, decoded. kbd and mouse: the
    bytes the PS/2 devices send."""
    nl = netlist()
    hw = native.hwsim.run_system(nl, config(max_cycles, trace, seed=seed),
                                 preloads(ram, inp, kbd, mouse))
    d = hw["dumps"]
    hw["output"] = bytes(d["X_IO"])
    out = bytearray(len(ram))
    for r in range(2):
        for b in range(2):
            out[(r << 20) + b:(r + 1) << 20:2] = d[f"U_RAM{r}{b}"]
    hw["ram"] = bytes(out)
    rf = [d["U_RF0"][a] | d["U_RF1"][a] << 8 for a in range(64)]
    hw["regs"] = [rf[i] | rf[32 + i] << 16 for i in range(16)]
    hw["flags"] = {k[2:]: hw["nets"][k] for k in FLAGS}
    return hw


def compare(m, hw):
    """The model's run against the netlist's."""
    out = []
    if hw["output"] != bytes(m.sys.console.out):
        out.append(f"output {hw['output'][:60]!r} against the model's "
                   f"{bytes(m.sys.console.out)[:60]!r}")
    for i in range(16):
        if hw["regs"][i] != m.reg(i):
            out.append(f"r{i} = {hw['regs'][i]:08X}, the model {m.reg(i):08X}")
    for k, v in hw["flags"].items():
        if v != m.f[k]:
            out.append(f"{k} = {v}, the model {m.f[k]}")
    bad = [a for a in range(len(hw["ram"])) if hw["ram"][a] != m.sys.ram[a]]
    if bad:
        out.append(f"{len(bad)} RAM bytes differ, the first at {bad[0]:06X}")
    # the fetches: the same addresses and parcels, at the same cycles
    mf = m.decodes
    hf = hw["fetches"]
    n = min(len(mf), len(hf))
    off = hf[0][0] - mf[0][0] if n else 0
    for i in range(n):
        (hc, ha, hd), (mc, ma, md) = hf[i], mf[i]
        if (ha & ~1, hd) != (ma, md) or hc - mc != off:
            out.append(f"fetch {i}: cycle {hc}, {ha:06X} {hd:04X}; the model cycle {mc + off}, "
                       f"{ma:06X} {md:04X}")
            break
    if hw["fetch_count"] != len(mf):
        out.append(f"{hw['fetch_count']} fetches, the model {len(mf)}")
    return out


def summary(hw):
    lines = [f"  {hw['cycles']} cycles, {hw['events']:,} events, {hw['wall_seconds']:.1f} s wall"
             f" ({hw['reason']})"]
    if hw["violation_total"]:
        lines.append(f"  {hw['violation_total']} timing violations:")
        for v in hw["violation_summary"][:8]:
            lines.append(f"    {v['what']}: {v['count']}x, worst slack {v['worst_slack_ps'] / 1000:.1f} ns")
    c = hw["contention"]
    if c["count"]:
        lines.append(f"  bus contention: {c['count']} episodes, longest {c['max_ps'] / 1000:.1f} ns")
    return "\n".join(lines)


def run_program(path, trace=None, verbose=True):
    from heron.infra.programs import metadata
    img = check.assemble(path)
    inp = metadata(path)["input"]
    m = check.run_rtl(img, inp, log=True)
    ram = bytes(m_ram(img))
    hw = run(ram, inp, max_cycles=m.cycles + 2000, trace=trace)
    diffs = compare(m, hw)
    return m, hw, diffs


def m_ram(img):
    from .system import System
    s = System()
    s.load(img)
    return s.ram


def cmd_run(args):
    trace = tuple(int(x) for x in args.trace.split(":")) if args.trace else None
    m, hw, diffs = run_program(args.file, trace)
    print(f"{os.path.basename(args.file)}:")
    print(summary(hw))
    print(f"  output: {hw['output'][:200]!r}")
    for line in hw.get("trace", []):
        print("  " + line)
    for d in diffs[:12]:
        print("  " + d)
    print("  matches the model" if not diffs else f"  {len(diffs)} differences")
    return 1 if diffs else 0


def cmd_test(args):
    from heron.studies.v2_isa import testing
    bad = 0
    for p in testing.program_paths(args.names or None):
        name = os.path.basename(p)[:-2]
        _, ref, rdiffs = check.check_program(p)
        if rdiffs:
            print(f"{name:12} skipped: the model doesn't run it yet ({rdiffs[0]})")
            continue
        m, hw, diffs = run_program(p)
        v = hw["violation_total"]
        if diffs or v:
            bad += 1
            print(f"{name:12} FAIL  {diffs[0] if diffs else f'{v} timing violations'}")
            for dd in diffs[1:4]:
                print(f"{'':18}{dd}")
        else:
            print(f"{name:12} ok    {hw['cycles']:9d} cycles, {hw['wall_seconds']:.0f} s")
    return 1 if bad else 0


def cmd_bom(args):
    nl = board.build(sim=True)
    bom = nl.bom(parts.VARIANT, passives=False)
    real = {p: refs for p, refs in bom.items()}
    total = 0
    for p, refs in sorted(real.items(), key=lambda kv: -len(kv[1])):
        total += len(refs)
        print(f"  {len(refs):3d}  {p:22} {' '.join(sorted(refs))[:90]}")
    print(f"  {total:3d}  packages")
    by = {}
    for inst in nl.instances:
        if inst.type.family in ("fixture", "passive"):
            continue
        by[inst.section] = by.get(inst.section, 0) + 1
    print()
    for sec, n in by.items():
        print(f"  {n:3d}  {sec}")
    return 0


def main(argv):
    p = argparse.ArgumentParser(prog="heron chibi hw")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("test")
    t.add_argument("names", nargs="*")
    r = sub.add_parser("run")
    r.add_argument("file")
    r.add_argument("--trace")
    s = sub.add_parser("sta")
    s.add_argument("--paths", type=int, default=3)
    s.add_argument("--write", action="store_true")
    s2 = sub.add_parser("sta2")
    s2.add_argument("--paths", type=int, default=2)
    s2.add_argument("--suite", action="store_true")
    sub.add_parser("halves")
    sub.add_parser("bom")
    args = p.parse_args(argv)
    if args.cmd == "test":
        return cmd_test(args)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "bom":
        return cmd_bom(args)
    if args.cmd == "sta":
        from . import sta
        return sta.cmd_sta(args)
    if args.cmd == "halves":
        from . import halves
        return halves.cmd_halves(args)
    if args.cmd == "sta2":
        from . import sta2
        return sta2.cmd_sta2(args)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
