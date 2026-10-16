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
    if names and "exercise" in names:
        from . import exercise
        paths.append(exercise.write())
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


def boot(m, pc=0, user=False):
    """Run the reset microcode; then, as a boot program would after
    setting up the map, start at pc (in user mode, bank 0, if user)."""
    for _ in range(10000):
        if m.uaddr == uc.REFILL_ADDR:
            break
        m.step()
    else:
        raise RTLError("the reset routine didn't finish")
    m.PC = pc
    m.FPC = pc & ~3
    m.V0 = m.V1 = 0
    if user:
        m.s = 0


def run_rtl(image, inp=b"", max_cycles=200_000_000, code_base=0, prefetch_bus=False, mc=None,
            trace=None, profile=False, user=False):
    s = make_system(image, inp, code_base, prefetch_bus)
    m = RTL(s, mc=mc)
    boot(m, user=user)
    m.cycles = m.ticks = m.hold_ticks = 0
    m.instructions = 0
    if profile:
        from collections import Counter
        m.ucount = Counter()
    m.trace = trace
    m.run(max_cycles)
    return m


def run_booted(image, inp=b"", max_cycles=200_000_000):
    """The whole boot: an empty control store and RAM, the I/O processor
    loading them through the CPU card's slave port, RESET, RUN; then the
    reset routine, the shim, and the program. Returns (RTL model, IOP)."""
    from . import iop as iopm
    s = System()
    s.add(1, MemoryCard())
    s.add(15, ConsoleCard(inp))
    slave = iopm.CPUCardSlave(s)
    iop = iopm.IOP(slave)
    iop.load_microcode(uc.built())
    iop.load_ram(iopm.boot_image(image))
    iop.start()
    m = RTL(s, rom=slave.rom(), decode=slave.decode())
    m.run(max_cycles)
    return m, iop


def run_isa(image, inp=b"", max_cycles=200_000_000):
    from heron.studies.v2_isa.sim import Machine
    sim = Machine(image, inp=inp)
    sim.run(max_cycles=max_cycles)
    return sim


def compare(sim, m, code_base=0, skip=None):
    """skip: a range of RAM addresses not to compare."""
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
    if skip:
        mem = bytearray(mem)
        ram = bytearray(ram)
        for a in range(*skip):
            mem[a] = ram[a] = 0
    if ram != bytes(mem):
        bad = [a for a in range(len(mem)) if ram[a] != mem[a]]
        a = bad[0]
        diffs.append(f"RAM differs at {len(bad)} bytes, first {a:05X}: RTL {ram[a]:02X}, "
                     f"ISA {mem[a]:02X}")
    return diffs


def lockstep(image, inp, path, user=False):
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
        # MFSR rd, flags: this machine's flags word has S (and T)
        mfsr = state.get("mfsr")
        for i in range(16):
            mask = ~0x60 & 0xFFFFFFFF if i == mfsr else 0xFFFFFFFF
            if m.reg(i) & mask != sim.r[i] & mask:
                state["err"] = (f"before {pc:08X} (instruction {state['n']}): r{i} RTL "
                                f"{m.reg(i):08X}, ISA {sim.r[i]:08X}")
                raise RTLError(state["err"])
        ir = m.IR
        state["mfsr"] = (ir >> 12) & 15 if (ir & 0xFF) == 0x0E and (ir >> 8) & 15 == 0 else None
        for fl in "zcv":
            if getattr(m, fl) != getattr(sim, fl):
                state["err"] = (f"before {pc:08X} (instruction {state['n']}): flag {fl} "
                                f"RTL {getattr(m, fl)}, ISA {getattr(sim, fl)}")
                raise RTLError(state["err"])
        sim.step()
        state["n"] += 1
    return run_rtl(image, inp, trace=check, user=user), sim


def c_programs(names=None):
    """The C programs (studies/c_compiler/programs), compiled for draft 2:
    [(name, image, input)]."""
    import glob
    from heron.studies.c_compiler.bench import CDIR
    from heron.studies.c_compiler.cc import driver
    from heron.studies.v2_isa.testing import PROGRAMS
    out = []
    for path in sorted(glob.glob(os.path.join(CDIR, "*.c"))):
        name = os.path.basename(path)[:-2]
        if names and f"c/{name}" not in names and name not in names:
            continue
        _, img, _ = driver.build([path], "v2", program=driver.Program("v2"))
        asm = os.path.join(PROGRAMS, name + ".s")
        inp = metadata(asm)["input"] if os.path.exists(asm) else b""
        out.append((f"c/{name}", img, inp))
    return out


CODE_BASE = 0


def check_image(name, img, inp, lock=False, max_cycles=400_000_000, path=""):
    t0 = time.time()
    try:
        if lock:
            m, sim = lockstep(img, inp, path)
        else:
            sim = run_isa(img, inp, max_cycles)
            m = run_rtl(img, inp, code_base=CODE_BASE)
    except RTLError as e:
        return name, [f"RTL error: {e}"], None
    diffs = compare(sim, m, code_base=CODE_BASE)
    info = (m.instructions, m.cycles, m.ticks, time.time() - t0)
    return name, diffs, info


def expected_output(name):
    """For this study's own programs (sw/): the suite's expected output for
    a copy of a suite program, else sw/expected/NAME.txt."""
    p = os.path.join(HERE, "sw", "expected", name + ".txt")
    if os.path.exists(p):
        with open(p, "rb") as f:
            return f.read()
    from heron.studies.v1_isa.testing import expected_output as suite_expected
    return suite_expected(name)


def check_own(path, name, img, inp, max_cycles):
    """A program of this study's own: its output against the expected."""
    t0 = time.time()
    try:
        m = run_rtl(img, inp, max_cycles)
    except RTLError as e:
        return name, [f"RTL error: {e}"], None
    exp = expected_output(name)
    diffs = []
    if exp is None:
        diffs.append("no expected output")
    elif m.out != exp:
        diffs.append(f"output differs from the expected: {m.out[-200:]!r}")
    return name, diffs, (m.instructions, m.cycles, m.ticks, time.time() - t0)


def check_exercise(img, lock):
    """The exercise program runs in user mode (bank 0, which the modes then
    share), so that its flags words are draft 1's; its HALT traps as a
    privilege violation, to a HALT, and the trap's frame is left out of
    the comparison."""
    t0 = time.time()
    try:
        if lock:
            m, sim = lockstep(img, b"", "exercise", user=True)
        else:
            sim = run_isa(img, b"", 400_000_000)
            m = run_rtl(img, b"", user=True)
    except RTLError as e:
        return "exercise", [f"RTL error: {e}"], None
    sp = sim.r[15]
    diffs = compare(sim, m, skip=(sp - 8, sp))
    diffs = [d for d in diffs if not d.startswith("r15")]
    return "exercise", diffs, (m.instructions, m.cycles, m.ticks, time.time() - t0)


def check_program(path, lock=False, verbose=False):
    name = os.path.basename(path)[:-2]
    meta = metadata(path)
    inp = meta["input"]
    img = asmcore.assemble_file(isas.get("v2"), path)
    if os.path.dirname(os.path.abspath(path)) == os.path.join(HERE, "sw"):
        return check_own(path, name, img, inp, meta["max-cycles"])
    if name == "exercise":
        return check_exercise(img, lock)
    t0 = time.time()
    try:
        if lock:
            m, sim = lockstep(img, inp, path)
        else:
            sim = run_isa(img, inp, meta["max-cycles"])
            m = run_rtl(img, inp, code_base=CODE_BASE)
    except RTLError as e:
        return name, [f"RTL error: {e}"], None
    diffs = compare(sim, m, code_base=CODE_BASE)
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
    p.add_argument("--c", action="store_true", help="the compiled C programs (or name them c/NAME)")
    p.add_argument("--bus", action="store_true",
                   help="the programs on the memory card: every fetch and access over the bus")
    args = p.parse_args(argv)
    global CODE_BASE
    if args.bus:
        CODE_BASE = 0x08000000
    bad = 0
    jobs = []
    asm_names = [n for n in args.names if not n.startswith("c/")]
    c_names = [n for n in args.names if n.startswith("c/")]
    if not args.c and (asm_names or not args.names):
        for path in program_paths(asm_names or None):
            jobs.append(lambda path=path: check_program(path, args.lockstep, args.v))
    if args.c or c_names:
        for name, img, inp in c_programs(c_names or None):
            jobs.append(lambda name=name, img=img, inp=inp: check_image(name, img, inp,
                                                                         args.lockstep))
    for job in jobs:
        name, diffs, info = job()
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
