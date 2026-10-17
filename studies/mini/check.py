"""The register-transfer model against draft 2's instruction-level
simulator (studies/v2_isa), on the program suite and the compiled C
programs, the address error's test (addrerr) and the Lisp's (--lisp).

    heron mini check [NAMES] [--c] [--lisp [--compiled]] [--lockstep] [--queue 1]

The suite was written for draft 1's machine, which is this one's: RAM
from address 0, the vectors at 0, the console at 0xFFFFFF00 (here a test
card in expansion port 2, system.py). The reset routine ends with a jump
to 0, so a program runs from reset with its image in the RAM.

Compared: the console output, the registers, the flags and the first
megabyte of the RAM (the simulator's), after HALT. --lockstep compares the
registers at every instruction.
"""

import argparse
import os
import sys
import time

from heron.infra import asm as asmcore
from heron.infra import isas
from heron.infra.programs import metadata

from .rtl import RTL, RTLError
from .system import System

HERE = os.path.dirname(os.path.abspath(__file__))


TRAPS = ("addrerr",)


def program_paths(names=None):
    from heron.studies.v2_isa.testing import program_paths as v2_paths
    paths = v2_paths(names)
    if names and "exercise" in names:
        from heron.studies.v2_hw import exercise
        paths.append(exercise.write())
    own = os.path.join(HERE, "sw")
    # sw/hw's programs that run as the suite's do, when named
    for n in TRAPS:
        if names and n in names:
            paths.append(os.path.join(own, "hw", n + ".s"))
    if os.path.isdir(own):
        for f in sorted(os.listdir(own)):
            if f.endswith(".s") and (not names or f[:-2] in names):
                p = os.path.join(own, f)
                paths = [q for q in paths if os.path.basename(q) != f] + [p]
    return paths


def run_rtl(image, inp=b"", max_cycles=400_000_000, trace=None, profile=False, queue=2,
            mc=None, system=None):
    s = system or System(inp=inp)
    if image is not None:
        s.load(image)
    m = RTL(s, mc=mc, queue_words=queue)
    if profile:
        from collections import Counter
        m.ucount = Counter()
    m.trace = trace
    m.run(max_cycles)
    return m


def run_isa(image, inp=b"", max_cycles=400_000_000):
    from heron.studies.v2_isa.sim import Machine
    sim = Machine(image, inp=inp)
    sim.run(max_cycles=max_cycles)
    return sim


def compare(sim, m, skip=None):
    """skip: a range of RAM addresses not to compare."""
    diffs = []
    out = m.out
    if out != bytes(sim.dev.out):
        diffs.append(f"output differs: RTL {out[:60]!r}... ISA {bytes(sim.dev.out)[:60]!r}...")
    for i in range(16):
        if m.reg(i) != sim.r[i]:
            diffs.append(f"r{i}: RTL {m.reg(i):08X}, ISA {sim.r[i]:08X}")
    for fl in "nzcv":
        if getattr(m, fl) != getattr(sim, fl):
            diffs.append(f"flag {fl.upper()}: RTL {getattr(m, fl)}, ISA {getattr(sim, fl)}")
    mem = sim.mem
    ram = bytes(m.sys.ram[:len(mem)])
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


def lockstep(image, inp, queue=2):
    """Run both, comparing the registers whenever the RTL decodes."""
    from heron.studies.v2_isa.sim import Machine
    sim = Machine(image, inp=inp)
    state = {"n": 0}

    def check(m):
        if sim.halted:
            return
        pc = (m.PC - 2) & 0xFFFFFFFF
        if sim.pc != pc:
            raise RTLError(f"instruction {state['n']}: RTL decodes {pc:08X}, ISA at {sim.pc:08X}")
        for i in range(16):
            if m.reg(i) != sim.r[i]:
                raise RTLError(f"before {pc:08X} (instruction {state['n']}): r{i} RTL "
                               f"{m.reg(i):08X}, ISA {sim.r[i]:08X}")
        for fl in "nzcv":
            if getattr(m, fl) != getattr(sim, fl):
                raise RTLError(f"before {pc:08X} (instruction {state['n']}): flag {fl} "
                               f"RTL {getattr(m, fl)}, ISA {getattr(sim, fl)}")
        sim.step()
        state["n"] += 1
    return run_rtl(image, inp, trace=check, queue=queue), sim


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


# the Lisp's tests that take minutes on the model, among them the two that
# take address errors (errors, control); the others, and the benchmarks,
# take hours: name them
LISP_SHORT = ("core", "errors", "control", "lists", "reader", "reader_eoi", "symbols")


def lisp_programs(names=None, compiled=False):
    """The Lisp's programs and tests (studies/lisp), built for draft 2:
    [(name, image, input, the RAM not to compare)]. Its car, cdr and calls
    check their operand's type by the address error. compiled: booted
    from the saved image with the compiler, which compiles each program
    before running it. Left out of the comparison: mark_log, where
    (%run-begin) and (%run-end) log each machine's own cycle counter."""
    from heron.studies.lisp import machine, testing
    img = machine.core((), "v2") if compiled else machine.image((), "v2")
    log = machine.image((), "v2").symbols["mark_log"]
    out = []
    for p in testing.program_paths(names):
        with open(p, "rb") as f:
            out.append((f"lisp/{os.path.basename(p)[:-5]}", img, f.read(), (log, log + 4096)))
    return out


def check_image(name, img, inp, lock=False, queue=2, max_cycles=400_000_000, skip=None):
    t0 = time.time()
    try:
        if lock:
            m, sim = lockstep(img, inp, queue)
        else:
            sim = run_isa(img, inp, max_cycles)
            m = run_rtl(img, inp, queue=queue)
    except RTLError as e:
        return name, [f"RTL error: {e}"], None
    diffs = compare(sim, m, skip)
    if name == "interrupts":
        # the timer counts each machine's own cycles: only the output is
        # the same
        diffs = [d for d in diffs if d.startswith("output")]
    info = (m.instructions, m.cycles, m.ticks, time.time() - t0)
    return name, diffs, info


def check_program(path, lock=False, queue=2):
    name = os.path.basename(path)[:-2]
    meta = metadata(path)
    img = asmcore.assemble_file(isas.get("v2"), path)
    skip = None
    if name == "exercise":
        # its HALT, after the last trap's frame: leave the frame out
        sim = run_isa(img, b"", meta["max-cycles"])
        sp = sim.r[15]
        skip = (sp - 8, sp)
    return check_image(name, img, meta["input"], lock, queue, meta["max-cycles"], skip)


def main(argv=None):
    import heron.studies.v2_isa  # noqa: F401
    p = argparse.ArgumentParser(prog="heron mini check")
    p.add_argument("names", nargs="*")
    p.add_argument("--lockstep", action="store_true")
    p.add_argument("--c", action="store_true", help="the compiled C programs (or name them c/NAME)")
    p.add_argument("--queue", type=int, default=2, help="the prefetch queue's depth in words")
    p.add_argument("--lisp", action="store_true",
                   help="the Lisp's short tests, interpreted (or name any of its "
                   "programs lisp/NAME)")
    p.add_argument("--compiled", action="store_true", help="with --lisp: compiled")
    args = p.parse_args(argv)
    bad = 0
    jobs = []
    asm_names = [n for n in args.names if not n.startswith(("c/", "lisp/"))]
    c_names = [n for n in args.names if n.startswith("c/")]
    lisp_names = [n[5:] for n in args.names if n.startswith("lisp/")]
    if args.lisp or lisp_names:
        for name, img, inp, skip in lisp_programs(lisp_names or LISP_SHORT, args.compiled):
            jobs.append(lambda name=name, img=img, inp=inp, skip=skip: check_image(
                name, img, inp, args.lockstep, args.queue, 4_000_000_000, skip))
    if not args.c and not args.lisp and (asm_names or not args.names):
        for path in program_paths(asm_names or None):
            jobs.append(lambda path=path: check_program(path, args.lockstep, args.queue))
    if args.c or c_names:
        for name, img, inp in c_programs(c_names or None):
            jobs.append(lambda name=name, img=img, inp=inp: check_image(
                name, img, inp, args.lockstep, args.queue))
    from .timing import TICK
    for job in jobs:
        name, diffs, info = job()
        if info:
            ins, cyc, ticks, secs = info
            stat = f"{ins:9d} instr {cyc:9d} cycles  CPI {cyc / max(ins, 1):.2f}  " \
                   f"{ticks * TICK / 1e6:8.2f} ms  ({secs:.0f} s)"
        else:
            stat = ""
        print(f"{name:12s} {'ok  ' if not diffs else 'FAIL'} {stat}")
        for d in diffs[:8]:
            print(f"    {d}")
        bad += bool(diffs)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
