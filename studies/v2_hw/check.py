"""The register-transfer model against draft 2's instruction-level
simulator (studies/v2_isa), on the program suite.

    heron v2_hw check [NAMES] [--lockstep] [-v]

The suite was written for draft 1's machine: RAM from address 0, the
console at 0xFFFFFF00, the vectors at 0. On this CPU (RFC 0029's system
architecture) the harness does what a boot program would: it maps context
0's first megabyte onto physical memory, one to one, and starts the
program at address 0 in supervisor mode, so the program's own addresses
work unchanged; the console at 0xFFFFFF00 is the window's physical
0x7FFFFF00, slot 15. RFC 0029's vectors are at 0x8000_0000 + 4n, which
reach the same physical words as the program's vector table, except
SWI's: `interrupts` (the one program that uses SWI and the timer) has a
copy for this machine in sw/.

Compared: the console output, the registers, HI and LO, the flags and all
of RAM, after HALT. --lockstep compares the registers at every
instruction.
"""

import argparse
import os
import sys
import time

from heron.infra import asm as asmcore
from heron.infra import isas
from heron.infra.programs import metadata

from . import ucode as uc
from .rtl import RTL, RTLError
from .system import ConsoleCard, MemoryCard, System

HERE = os.path.dirname(os.path.abspath(__file__))


def program_paths(names=None):
    from heron.studies.v2_isa.testing import program_paths as v2_paths
    paths = v2_paths(names)
    own = os.path.join(HERE, "sw")
    if os.path.isdir(own):
        for f in sorted(os.listdir(own)):
            if f.endswith(".s") and (not names or f[:-2] in names):
                p = os.path.join(own, f)
                paths = [q for q in paths if os.path.basename(q) != f] + [p]
    return paths


def make_system(image, inp=b"", code_base=0, prefetch_bus=False):
    """The system the suite runs on: the CPU card's 2 MB, a memory card in
    slot 1, the console in slot 15; context 0's first 1 MB mapped onto
    physical code_base (0: the CPU card's RAM; 0x0800_0000: the memory
    card, to run the program over the bus)."""
    s = System(prefetch_bus=prefetch_bus)
    s.add(1, MemoryCard())
    s.add(15, ConsoleCard(inp))
    s.load(image, code_base)
    s.identity_map(0, 256, base=code_base)
    return s


def boot(m, pc=0):
    """Run the reset microcode; then, as a boot program would after
    setting up the map, start at pc."""
    for _ in range(10000):
        if m.uaddr == uc.REFILL_ADDR:
            break
        m.step()
    else:
        raise RTLError("the reset routine didn't finish")
    m.PC = pc
    m.FPC = pc & ~3
    m.V0 = m.V1 = 0


def run_rtl(image, inp=b"", max_cycles=200_000_000, code_base=0, prefetch_bus=False, mc=None,
            trace=None, profile=False):
    s = make_system(image, inp, code_base, prefetch_bus)
    m = RTL(s, mc=mc)
    boot(m)
    m.cycles = m.ticks = m.hold_ticks = 0
    m.instructions = 0
    if profile:
        from collections import Counter
        m.ucount = Counter()
    m.trace = trace
    m.run(max_cycles)
    return m


def run_isa(image, inp=b"", max_cycles=200_000_000):
    from heron.studies.v2_isa.sim import Machine
    sim = Machine(image, inp=inp)
    sim.run(max_cycles=max_cycles)
    return sim


def compare(sim, m, code_base=0):
    diffs = []
    out = m.out
    if out != bytes(sim.dev.out):
        diffs.append(f"output differs: RTL {out[:60]!r}... ISA {bytes(sim.dev.out)[:60]!r}...")
    for i in range(16):
        if m.reg(i) != sim.r[i]:
            diffs.append(f"r{i}: RTL {m.reg(i):08X}, ISA {sim.r[i]:08X}")
    if m.hi != sim.hi:
        diffs.append(f"HI: RTL {m.hi:08X}, ISA {sim.hi:08X}")
    if m.lo != sim.lo:
        diffs.append(f"LO: RTL {m.lo:08X}, ISA {sim.lo:08X}")
    for fl in "nzcv":
        if getattr(m, fl) != getattr(sim, fl):
            diffs.append(f"flag {fl.upper()}: RTL {getattr(m, fl)}, ISA {getattr(sim, fl)}")
    mem = sim.mem
    if code_base == 0:
        ram = bytes(m.sys.ram[:len(mem)])
    else:
        ram = bytes(m.sys.peek(code_base + a) for a in range(len(mem)))
    if ram != bytes(mem):
        bad = [a for a in range(len(mem)) if ram[a] != mem[a]]
        a = bad[0]
        diffs.append(f"RAM differs at {len(bad)} bytes, first {a:05X}: RTL {ram[a]:02X}, "
                     f"ISA {mem[a]:02X}")
    return diffs


def lockstep(image, inp, path):
    """Run both, comparing the registers whenever the RTL decodes."""
    from heron.studies.v2_isa.sim import Machine
    sim = Machine(image, inp=inp)
    state = {"n": 0, "err": None}

    def check(m):
        # the RTL has decoded the instruction at m.PC - 2: the ISA
        # simulator should be about to execute it
        if state["err"]:
            return
        if sim.halted:
            return
        pc = (m.PC - 2) & 0xFFFFFFFF
        while sim.pc != pc and not sim.halted and state["n"] < 10:
            # interrupts and traps: the simulator enters them inside step()
            break
        if sim.pc != pc:
            state["err"] = f"instruction {state['n']}: RTL decodes {pc:08X}, ISA at {sim.pc:08X}"
            raise RTLError(state["err"])
        for i in range(16):
            if m.reg(i) != sim.r[i]:
                state["err"] = (f"before {pc:08X} (instruction {state['n']}): r{i} RTL "
                                f"{m.reg(i):08X}, ISA {sim.r[i]:08X}")
                raise RTLError(state["err"])
        for fl in "zcv":
            if getattr(m, fl) != getattr(sim, fl):
                state["err"] = (f"before {pc:08X} (instruction {state['n']}): flag {fl} "
                                f"RTL {getattr(m, fl)}, ISA {getattr(sim, fl)}")
                raise RTLError(state["err"])
        sim.step()
        state["n"] += 1
    return run_rtl(image, inp, trace=check), sim


def check_program(path, lock=False, verbose=False):
    name = os.path.basename(path)[:-2]
    meta = metadata(path)
    inp = meta["input"]
    img = asmcore.assemble_file(isas.get("v2"), path)
    t0 = time.time()
    try:
        if lock:
            m, sim = lockstep(img, inp, path)
        else:
            sim = run_isa(img, inp, meta["max-cycles"])
            m = run_rtl(img, inp)
    except RTLError as e:
        return name, [f"RTL error: {e}"], None
    diffs = compare(sim, m)
    if name == "interrupts" and "sw" not in path:
        diffs = [d for d in diffs if d.startswith("output")]
    info = (m.instructions, m.cycles, m.ticks, time.time() - t0)
    return name, diffs, info


def main(argv=None):
    import heron.studies.v2_isa  # noqa: F401
    p = argparse.ArgumentParser(prog="heron v2_hw check")
    p.add_argument("names", nargs="*")
    p.add_argument("--lockstep", action="store_true")
    p.add_argument("-v", action="store_true")
    args = p.parse_args(argv)
    bad = 0
    for path in program_paths(args.names or None):
        name, diffs, info = check_program(path, args.lockstep, args.v)
        if info:
            ins, cyc, ticks, secs = info
            stat = f"{ins:9d} instr {cyc:9d} cycles  CPI {cyc / max(ins, 1):.2f}  " \
                   f"{ticks * 20 / 1e6:8.2f} ms  ({secs:.0f} s)"
        else:
            stat = ""
        print(f"{name:12s} {'ok  ' if not diffs else 'FAIL'} {stat}")
        for d in diffs[:8]:
            print(f"    {d}")
        bad += bool(diffs)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
