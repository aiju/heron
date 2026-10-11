"""Chip-level tools: python3 -m tmc hw <command>

  bom      [--variant V]                     parts list
  run      PROG.s [--period NS] [--variant V] [--corner typ|max] [--trace A:B]
                                             run on the timing simulator and
                                             cross-check against the ISA simulator
  test     [NAMES] [--period NS] ...         run programs on the timing simulator
  sweep    PROG.s [--variant V] [--corner C] find the shortest clock period that works
  sta      [--variant V] [--corner C]        static timing analysis
"""

import argparse
import glob
import json
import os
import subprocess
import sys
import time

from .. import asm as asmcore
from .. import isa as isas
from ..sim import Machine
from . import chips, cpu_v0, microcode

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUILD = os.path.join(ROOT, "build")
HWSIM_SRC = os.path.join(ROOT, "hwsim")
HWSIM = os.path.join(BUILD, "hwsim")


def newest(paths):
    return max(os.path.getmtime(p) for p in paths)


def ensure_hwsim():
    srcs = glob.glob(os.path.join(HWSIM_SRC, "*.go"))
    if not os.path.exists(HWSIM) or os.path.getmtime(HWSIM) < newest(srcs):
        os.makedirs(BUILD, exist_ok=True)
        subprocess.run(["go", "build", "-o", HWSIM, "."], cwd=HWSIM_SRC, check=True)
    return HWSIM


def py_sources():
    return glob.glob(os.path.join(ROOT, "tmc", "hw", "*.py")) + [chips.TIMING_PATH]


def ensure_ucode():
    out = os.path.join(BUILD, "ucode")
    files = [os.path.join(out, f"ucode{k}.bin") for k in range(microcode.ROMS)]
    if not all(os.path.exists(f) for f in files) or min(os.path.getmtime(f) for f in files) < newest(py_sources()):
        os.makedirs(out, exist_ok=True)
        for k, img in enumerate(microcode.rom_images()):
            with open(files[k], "wb") as f:
                f.write(img)
    return {f"U_UC{k}": files[k] for k in range(microcode.ROMS)}


def ensure_netlist(variant, corner):
    path = os.path.join(BUILD, f"netlist-{variant}-{corner}.json")
    if not os.path.exists(path) or os.path.getmtime(path) < newest(py_sources()):
        os.makedirs(BUILD, exist_ok=True)
        nl = cpu_v0.build()
        with open(path, "w") as f:
            json.dump(nl.export(variant=variant, corner=corner), f)
    return path


def trace_buses():
    def bus(name, n, start=0):
        return [f"{name}{i}" for i in range(start, start + n)]
    ctl = cpu_v0.control_nets()
    return {
        "STEP": bus("STEP", 4), "IR": bus("IR", 16), "PC": ["GND"] + bus("PC", 15, 1),
        "ADDR": bus("ADDR", 16), "DBUS": bus("DBUS", 16), "ABUS": bus("ABUS", 16),
        "BBUS": bus("BBUS", 16), "F": bus("F", 16), "RES": bus("RES", 16), "R": bus("R", 16),
        "T": bus("T", 16), "MAR": bus("MAR", 16),
        "NZCVI": ["IFLAG", "VFLAG", "CFLAG", "ZFLAG", "NFLAG"][::-1],
        "MODE": ["MODERST", "MODEIRQ", "IRQP", "LINK"],
        "U": [ctl.get(i, "GND") for i in range(microcode.CONTROL_BITS)],
    }


def run_isa(path, inp=b"", isa_name="v0"):
    isa = isas.get(isa_name)
    img = asmcore.assemble_file(isa, path)
    m = Machine(isa, img, inp=inp, timing=microcode.timing_function(isa_name))
    m.fetch_log = []
    m.run(max_cycles=200_000_000)
    return img, m


def run_hw(img, period_ns, variant=chips.DEFAULT_VARIANT, corner="max", seed=1, inp=b"",
           max_cycles=10_000_000, trace=None, fetch_trace=200_000, tag="run", we=(0.5, 0.875),
           zero_regs=True):
    ensure_hwsim()
    roms = ensure_ucode()
    netlist = ensure_netlist(variant, corner)
    work = os.path.join(BUILD, "runs")
    os.makedirs(work, exist_ok=True)
    stem = os.path.join(work, f"{tag}-{os.getpid()}-{time.time_ns()}")
    with open(stem + ".ram", "wb") as f:
        f.write(img.to_bytes())
    cfg = {
        "netlist": netlist, "roms": roms, "ram_image": stem + ".ram", "ram_lo": "U_RAML", "ram_hi": "U_RAMH",
        "ram_dump": stem + ".dump", "period_ps": int(round(period_ns * 1000)), "seed": seed,
        "we_start": we[0], "we_end": we[1],
        "max_cycles": max_cycles, "input": inp.decode("latin-1"), "fetch_trace": fetch_trace,
        "zero_regs": zero_regs,
        "out": stem + ".json",
    }
    if trace:
        cfg.update(trace_from=trace[0], trace_to=trace[1], trace_file=stem + ".trace", trace_buses=trace_buses())
    with open(stem + ".cfg", "w") as f:
        json.dump(cfg, f)
    subprocess.run([HWSIM, stem + ".cfg"], check=True)
    with open(stem + ".json") as f:
        res = json.load(f)
    with open(stem + ".dump", "rb") as f:
        res["ram"] = f.read()
    res["output"] = bytes(res["output"])
    res["trace_file"] = stem + ".trace" if trace else None
    for ext in (".ram", ".cfg", ".json", ".dump"):
        os.remove(stem + ext)
    return res


def compare(m, hw, check_cycles=True):
    """Differences between an ISA-sim Machine and a hardware result."""
    diffs = []
    if not hw["halted"]:
        diffs.append(f"hardware did not halt: {hw['reason']}")
    if hw["output"] != bytes(m.dev.out):
        diffs.append("console output differs")
    if check_cycles and hw["cycles"] != m.cycles:
        diffs.append(f"cycles: hardware {hw['cycles']}, ISA sim {m.cycles}")
    for i in range(1, 16):
        if hw["regs_a"][i] != m.r[i] and m.reg_written[i]:
            diffs.append(f"r{i}: hardware {hw['regs_a'][i]:04X}, ISA sim {m.r[i]:04X}")
        if hw["regs_b"][i] != hw["regs_a"][i]:
            diffs.append(f"r{i}: register file copies disagree ({hw['regs_a'][i]:04X} / {hw['regs_b'][i]:04X})")
    if hw["regs_a"][0] != 0:
        diffs.append(f"r0 is {hw['regs_a'][0]:04X}")
    for f, attr in (("NFLAG", "n"), ("ZFLAG", "z"), ("CFLAG", "c"), ("VFLAG", "v"), ("IFLAG", "i")):
        if hw["flags"][f] != getattr(m, attr):
            diffs.append(f"flag {f[0]}: hardware {hw['flags'][f]}, ISA sim {getattr(m, attr)}")
    if hw["pc"] != m.pc:
        diffs.append(f"PC: hardware {hw['pc']:04X}, ISA sim {m.pc:04X}")
    ram = hw["ram"]
    bad = [a for a in range(0xFF00) if ram[a] != m.mem[a]]
    if bad:
        a = bad[0]
        diffs.append(f"memory differs at {len(bad)} bytes, first {a:04X}: hardware {ram[a]:02X}, ISA sim {m.mem[a]:02X}")
    if check_cycles and m.fetch_log is not None:
        for i, (h, s) in enumerate(zip(hw["fetches"], m.fetch_log)):
            if tuple(h) != tuple(s):
                diffs.append(f"fetch #{i}: hardware cycle {h[0]} addr {h[1]:04X} word {h[2]:04X}; "
                             f"ISA sim cycle {s[0]} addr {s[1]:04X} word {s[2]:04X}")
                break
    return diffs


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


def decode_trace(path, out=sys.stdout):
    for line in open(path):
        parts = line.split()
        fields = dict(p.split("=") for p in parts[1:])
        u = microcode.unpack(int(fields.pop("U"), 16))
        active = []
        for name, (_, w, _) in microcode._pos.items():
            if u[name]:
                active.append(name if w == 1 else f"{name}={u[name]}")
        out.write(f"{parts[0]:>6} " + " ".join(f"{k}={v}" for k, v in fields.items()) + "\n")
        out.write(f"{'':>6}   {' '.join(active)}\n")


def program_input(path):
    from ..testing import metadata
    return metadata(path)["input"]


def cmd_run(args):
    inp = program_input(args.file)
    img, m = run_isa(args.file, inp)
    trace = tuple(int(x) for x in args.trace.split(":")) if args.trace else None
    hw = run_hw(img, args.period, args.variant, args.corner, args.seed, inp,
                max_cycles=m.cycles + 1000, trace=trace)
    uses_irq = m.irqs > 0
    diffs = compare(m, hw, check_cycles=not uses_irq)
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
        decode_trace(hw["trace_file"])
    return 1 if diffs or hw["violation_total"] else 0


def cmd_test(args):
    from ..testing import program_paths
    paths = program_paths(args.names)
    fails = 0
    for p in paths:
        inp = program_input(p)
        img, m = run_isa(p, inp)
        if m.cycles > args.max_cycles:
            print(f"{os.path.basename(p):<14} skipped ({m.cycles:,} cycles > --max-cycles)")
            continue
        hw = run_hw(img, args.period, args.variant, args.corner, args.seed, inp, max_cycles=m.cycles + 1000)
        diffs = compare(m, hw, check_cycles=m.irqs == 0)
        ok = not diffs and not hw["violation_total"]
        fails += not ok
        print(f"{os.path.basename(p):<14} {'ok' if ok else 'FAIL':<5} {hw['cycles']:>9} cycles "
              f"{hw['wall_seconds']:6.1f} s  violations {hw['violation_total']:>5}  "
              f"contention max {hw['contention']['max_ps'] / 1000:.1f} ns")
        for d in diffs[:5]:
            print("    " + d)
    return 1 if fails else 0


def passes(img, m, inp, period, variant, corner, seed=1):
    hw = run_hw(img, period, variant, corner, seed, inp, max_cycles=m.cycles + 1000, fetch_trace=0)
    diffs = compare(m, hw, check_cycles=False)
    return (not diffs and hw["violation_total"] == 0), hw, diffs


def cmd_sweep(args):
    inp = program_input(args.file)
    img, m = run_isa(args.file, inp)
    lo, hi = args.lo, args.hi
    ok, hw, _ = passes(img, m, inp, hi, args.variant, args.corner)
    if not ok:
        print(f"fails even at {hi} ns:\n{summarize(hw)}")
        return 1
    while hi - lo > args.step:
        mid = round((lo + hi) / 2, 1)
        ok, hw, diffs = passes(img, m, inp, mid, args.variant, args.corner)
        print(f"  {mid:7.1f} ns: {'ok' if ok else 'fails'}"
              + ("" if ok else f" ({hw['violation_total']} violations{', wrong result' if diffs else ''})"))
        if ok:
            hi = mid
        else:
            lo = mid
    print(f"shortest working period: {hi} ns ({1000 / hi:.2f} MHz)")
    return 0


def cmd_bom(args):
    nl = cpu_v0.build()
    total = 0
    for part, refs in nl.bom(args.variant).items():
        print(f"{len(refs):3} x {part:<16} {' '.join(refs[:8])}{' ...' if len(refs) > 8 else ''}")
        total += len(refs)
    print(f"{total} chips")
    return 0


def main(argv):
    p = argparse.ArgumentParser(prog="tmc hw")
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
    st.set_defaults(fn=lambda a: __import__("tmc.hw.sta", fromlist=["x"]).cmd_sta(a))

    args = p.parse_args(argv)
    return args.fn(args)
