"""Chibi Heron at chip level: the two-halves machine's netlist,
board2.build(sim=True), on the chip-level simulator's system run
(infra/hwsim), checked against its register-transfer model (rtl2.py);
--first takes the first cut's instead (board.py, rtl.py).

Both start from reset (the reset routine, then the program at 0, its image
in the RAM); the suite's I/O page is a test fixture at 0xFFFF_FF00.

  heron chibi hw test [NAMES] [--first]
                                    programs at chip level against the RTL
                                    model: output, registers, flags, RAM, and
                                    every instruction fetch with its cycle
  heron chibi hw run PROG.s [--trace A:B] [--first]
  heron chibi hw sta [--paths N] [--write] [--first]
                                    static timing analysis (sta2.py; --write:
                                    the ticks table, ticks.json; --first:
                                    the first cut's, sta.py)
  heron chibi hw odt [--cycles N]   ODT's session at chip level, against the
                                    model
  heron chibi hw copper [--cycles N]
                                    the copper's test at chip level, against
                                    the model
  heron chibi hw bom [--first]      the parts list
"""

import argparse
import glob
import json
import os
import sys

from heron import BUILD, native
from heron.infra.hw import runner

from . import board, board2, check, parts, routines, routines2, ucode as uc

OUT = os.path.join(BUILD, "chibi")
HERE = os.path.dirname(os.path.abspath(__file__))


def sources():
    return runner.infra_sources() + glob.glob(os.path.join(HERE, "*.py"))


_LOADED = None


HALT_PS = 60_000_000             # ODT's session: the halt button held to 60 us


def netlist(first=False, halt=False):
    """The simulation netlist, exported (cached in build/chibi): the
    two-halves machine's (board2), or the first cut's; with the halt
    button held through reset."""
    global _LOADED
    if _LOADED is None:
        _LOADED = runner.newest(sources())
    name = "netlist-first.json" if first else "netlist-halt.json" if halt else "netlist.json"
    path = os.path.join(OUT, name)
    if not os.path.exists(path) or os.path.getmtime(path) < _LOADED:
        os.makedirs(OUT, exist_ok=True)
        nl = board.build(sim=True) if first else \
            board2.build(sim=True, halt_ps=HALT_PS if halt else 0)
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(nl.export(variant=parts.VARIANT, corner="max"), f)
        os.utime(tmp, (_LOADED, _LOADED))
        os.replace(tmp, path)
    with open(path) as f:
        return json.load(f)


_ROMS = {}


def rom_images(first=False):
    """The control store's nine flash images, one a byte of the word."""
    if first not in _ROMS:
        cs = routines.control_store() if first else routines2.control_store()
        imgs = [bytearray(uc.CS_WORDS) for _ in range(uc.ROMS)]
        for a, w in enumerate(cs.words):
            for k in range(uc.ROMS):
                imgs[k][a] = (w >> (8 * k)) & 0xFF
        _ROMS[first] = [bytes(i) for i in imgs]
    return _ROMS[first]


def rf_chips(first=False):
    return ["U_RF0", "U_RF1"] if first else ["U_RFL0", "U_RFL1", "U_RFH0", "U_RFH1"]


def preloads(ram, inp=b"", kbd=b"", mouse=b"", first=False, uart=b""):
    pre = {f"U_CS{k}": img for k, img in enumerate(rom_images(first))}
    for r in range(2):
        for b in range(2):
            pre[f"U_RAM{r}{b}"] = bytes(ram[(r << 20) + b:(r + 1) << 20:2])
    for k in rf_chips(first):
        pre[k] = bytes(1 << 15)
    pre["U_BOOT"] = bytes([0xFF]) * 0x20000
    pre["X_IO"] = bytes(inp)
    pre["U_UART0"] = bytes(uart)
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


def config(max_cycles, trace=None, fetch_trace=200_000, seed=1, first=False):
    cfg = {
        "seed": seed, "max_cycles": max_cycles,
        "max_ps": int(max_cycles * (200_000 if first else 700_000)) + 10_000_000,
        "clock_net": "CLK0", "reset_net": "RESET_n",
        "fetch_net": "LDIR", "fetch_level": 1,
        "addr_nets": [f"A{i}" for i in range(21)],
        "data_nets": [f"MD{i}" for i in range(16)],
        "fetch_trace": fetch_trace,
        "stop_when": [[("uHALT", 1)]],
        "dump": ["X_IO"] + [f"U_RAM{r}{b}" for r in range(2) for b in range(2)]
        + rf_chips(first),
        "observe": list(FLAGS),
    }
    if trace:
        cfg.update(trace_from=trace[0], trace_to=trace[1], trace_buses=trace_buses())
    return cfg


def run(ram, inp=b"", max_cycles=20_000_000, trace=None, seed=1, kbd=b"", mouse=b"",
        first=False, uart=None):
    """A RAM image at chip level: the outcome, decoded. kbd and mouse: the
    bytes the PS/2 devices send; uart, what's typed at UART 0, with the
    halt button held through reset (ODT's session)."""
    nl = netlist(first, halt=uart is not None)
    cfg = config(max_cycles, trace, seed=seed, first=first)
    if uart is not None:
        cfg["dump"].append("U_UART0")
    hw = native.hwsim.run_system(nl, cfg, preloads(ram, inp, kbd, mouse, first, uart or b""))
    d = hw["dumps"]
    hw["output"] = bytes(d["X_IO"])
    if uart is not None:
        hw["uart"] = bytes(d["U_UART0"])
    out = bytearray(len(ram))
    for r in range(2):
        for b in range(2):
            out[(r << 20) + b:(r + 1) << 20:2] = d[f"U_RAM{r}{b}"]
    hw["ram"] = bytes(out)
    if first:
        rf = [d["U_RF0"][a] | d["U_RF1"][a] << 8 for a in range(64)]
        hw["regs"] = [rf[i] | rf[32 + i] << 16 for i in range(16)]
    else:
        hw["regs"] = [d["U_RFL0"][i] | d["U_RFL1"][i] << 8 | d["U_RFH0"][i] << 16
                      | d["U_RFH1"][i] << 24 for i in range(16)]
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


def run_program(path, trace=None, verbose=True, first=False):
    from heron.infra.programs import metadata
    img = check.assemble(path)
    inp = metadata(path)["input"]
    m = check.run_rtl(img, inp, log=True, first=first)
    ram = bytes(m_ram(img))
    hw = run(ram, inp, max_cycles=m.cycles + 2000, trace=trace, first=first)
    diffs = compare(m, hw)
    return m, hw, diffs


ODT_PROGRAM = os.path.join(HERE, "programs", "odt.s")
# ODT's test session: what's typed (as fast as the line goes)
ODT_KEYS = b"x2000/\r%1/\rs%1/5678\r2000/11223344\n\r%2/\nssssss%2/\r4g"


def odt_model(img, keys, max_cycles=1_000_000):
    """The model's run of an ODT session, from reset with the halt button
    held."""
    from .rtl2 import RTL2
    from .system2 import System2
    s = System2(uart=keys)
    s.load(img)
    s.halt_req = 1
    m = RTL2(s)
    m.run(max_cycles)
    return m


COPPER_PROGRAM = os.path.join(HERE, "programs", "copper.s")


def outcome_diffs(m, hw, uart=False):
    """What a run left, at chip level against the model, without the
    fetches' timing (a terminal's or the scanline's isn't the model's)."""
    diffs = []
    pairs = [("printed", hw["output"], bytes(m.sys.console.out))]
    if uart:
        pairs.append(("sent", hw["uart"], bytes(m.sys.uart.out)))
    for what, h, mm in pairs:
        if h != mm:
            diffs.append(f"{what} {h!r}, the model {mm!r}")
    diffs += [f"r{i} = {hw['regs'][i]:08X}, the model {m.reg(i):08X}"
              for i in range(16) if hw["regs"][i] != m.reg(i)]
    bad = [a for a in range(len(hw["ram"])) if hw["ram"][a] != m.sys.ram[a]]
    if bad:
        diffs.append(f"{len(bad)} RAM bytes differ, the first at {bad[0]:06X}")
    if hw["violation_total"]:
        diffs.append(f"{hw['violation_total']} timing violations")
    return diffs


def report(name, hw, diffs, shown):
    print(f"{name}:")
    print(summary(hw))
    for d in diffs:
        print("  " + d)
    print(f"  {shown!r}")
    print("  matches the model" if not diffs else f"  {len(diffs)} differences")
    return 1 if diffs else 0


def cmd_odt(args):
    """ODT's session at chip level against the model's: what it sends, the
    registers and RAM it leaves."""
    img = check.assemble(ODT_PROGRAM)
    m = odt_model(img, ODT_KEYS)
    hw = run(bytes(m_ram(img)), max_cycles=args.cycles, uart=ODT_KEYS)
    return report("odt", hw, outcome_diffs(m, hw, uart=True),
                  bytes(m.sys.uart.out).decode("latin1"))


def cmd_copper(args):
    """The copper's test (programs/copper.s) at chip level against the model."""
    img = check.assemble(COPPER_PROGRAM)
    m = check.run_rtl(img)
    hw = run(bytes(m_ram(img)), max_cycles=args.cycles)
    return report("copper", hw, outcome_diffs(m, hw), hw["output"])


def m_ram(img):
    from .system import System
    s = System()
    s.load(img)
    return s.ram


def cmd_run(args):
    trace = tuple(int(x) for x in args.trace.split(":")) if args.trace else None
    m, hw, diffs = run_program(args.file, trace, first=args.first)
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
        _, ref, rdiffs = check.check_program(p, first=args.first)
        if rdiffs:
            print(f"{name:12} skipped: the model doesn't run it yet ({rdiffs[0]})")
            continue
        m, hw, diffs = run_program(p, first=args.first)
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
    nl = board.build(sim=True) if args.first else board2.build(sim=True)
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
    t.add_argument("--first", action="store_true", help="the first cut's netlist")
    r = sub.add_parser("run")
    r.add_argument("file")
    r.add_argument("--trace")
    r.add_argument("--first", action="store_true")
    s = sub.add_parser("sta")
    s.add_argument("--paths", type=int, default=2)
    s.add_argument("--write", action="store_true", help="the ticks table (ticks.json)")
    s.add_argument("--first", action="store_true", help="the first cut's analysis")
    o = sub.add_parser("odt", help="ODT's session at chip level, against the model")
    o.add_argument("--cycles", type=int, default=600_000)
    c = sub.add_parser("copper", help="the copper's test at chip level, against the model")
    c.add_argument("--cycles", type=int, default=600_000)
    b = sub.add_parser("bom")
    b.add_argument("--first", action="store_true")
    args = p.parse_args(argv)
    if args.cmd == "test":
        return cmd_test(args)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "bom":
        return cmd_bom(args)
    if args.cmd == "odt":
        return cmd_odt(args)
    if args.cmd == "copper":
        return cmd_copper(args)
    if args.cmd == "sta":
        if args.first:
            from . import sta
            return sta.cmd_sta(args)
        from . import sta2
        return sta2.cmd_sta(args)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
