"""Compare the draft 1b RTL model with the instruction-level simulator.

    heron v1b_hw check [NAMES...] [-v]
"""

import argparse
import os
import sys
import time

from heron.infra import asm as asmcore
from heron.infra import isas
from heron.studies.v1_isa.sim32 import Machine32
from heron.studies.v1_isa.testing import metadata, program_paths
from .rtl import RTL, RTLError


def compare(m, r):
    """Differences between a Machine32 and an RTL run. Programs that take
    interrupts are compared on their output only: when an interrupt arrives
    depends on the cycle counts, which the two don't share."""
    diffs = []
    if bytes(m.dev.out) != r.out:
        diffs.append(f"output differs: ISA {bytes(m.dev.out)[:60]!r} RTL {r.out[:60]!r}")
    if m.irqs:
        return diffs
    for i in range(1, 16):
        if m.r[i] != r.rf[i]:
            diffs.append(f"r{i}: ISA {m.r[i]:08X} RTL {r.rf[i]:08X}")
    if r.rf[0]:
        diffs.append(f"r0 = {r.rf[0]:08X}")
    if m.hi != r.hi:
        diffs.append(f"HI: ISA {m.hi:08X} RTL {r.hi:08X}")
    for fl in "nzcvi":
        if getattr(m, fl) != getattr(r, fl):
            diffs.append(f"flag {fl.upper()}: ISA {getattr(m, fl)} RTL {getattr(r, fl)}")
    if m.pc != r.PC:
        diffs.append(f"PC: ISA {m.pc:08X} RTL {r.PC:08X}")
    bad = [a for a in range(len(m.mem)) if m.mem[a] != r.mem[a]]
    if bad:
        a = bad[0]
        diffs.append(f"memory differs at {len(bad)} bytes, first {a:05X}: ISA {m.mem[a]:02X} RTL {r.mem[a]:02X}")
    return diffs


def exercise_path():
    """Write the generated exercise program to build/ and return its path."""
    from heron import BUILD
    from . import exercise
    out = os.path.join(BUILD, "exercise_v1b.s")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(exercise.source())
    return out


def run_both(path, isa=None):
    isa = isa or isas.get("v1b")
    meta = metadata(path)
    img = asmcore.assemble_file(isa, path)
    m = Machine32(isa, img, inp=meta["input"])
    m.run(max_cycles=meta["max-cycles"])
    r = RTL(img, inp=meta["input"])
    t = time.time()
    r.run(max_cycles=20 * meta["max-cycles"])
    return m, r, time.time() - t


def lockstep(path, limit=10_000_000):
    """Run the RTL model and the ISA simulator side by side and report the
    first instruction after which registers, flags or the PC differ."""
    isa = isas.get("v1b")
    meta = metadata(path)
    img = asmcore.assemble_file(isa, path)
    m = Machine32(isa, img, inp=meta["input"])
    r = RTL(img, inp=meta["input"])
    syms = {v: k for k, v in img.symbols.items()} if hasattr(img, "symbols") else {}
    count = 0
    prev_pc = None
    while not r.halted and count < limit:
        before = r.total
        nfetch = len(r.fetch_log or [])
        r.fetch_log = r.fetch_log or []
        while len(r.fetch_log) == nfetch and not r.halted:
            r.step()
        if r.halted:
            break
        if not r.started or len(r.fetch_log) == 1:
            continue
        # the RTL just fetched instruction k+1: instruction k has finished
        pc = m.pc
        m.step()
        count += 1
        cyc, addr, word = r.fetch_log[-1]
        diffs = []
        if addr != m.pc:
            diffs.append(f"fetch at {addr:08X}, ISA PC {m.pc:08X}")
        for i in range(16):
            if m.r[i] != r.rf[i]:
                diffs.append(f"r{i}: ISA {m.r[i]:08X} RTL {r.rf[i]:08X}")
        if m.hi != r.hi:
            diffs.append(f"HI: ISA {m.hi:08X} RTL {r.hi:08X}")
        for fl in "nzcvi":
            if getattr(m, fl) != getattr(r, fl):
                diffs.append(f"{fl.upper()}: ISA {getattr(m, fl)} RTL {getattr(r, fl)}")
        if diffs:
            ws = [m.parcel(pc + 2 * i) for i in range(3)]
            text, _ = isa.disassemble(ws, pc, syms)
            print(f"after instruction {count} at {pc:08X}: {text}   ({r.total - before} cycles)")
            for d in diffs:
                print("    " + d)
            return False
    print(f"{count} instructions in lockstep")
    return True


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron v1b_hw check",
                                description="the RTL model against the instruction-level simulator")
    p.add_argument("names", nargs="*")
    p.add_argument("-v", action="store_true")
    p.add_argument("--lockstep", action="store_true")
    a = p.parse_args(argv)
    fails = 0
    paths = []
    for n in a.names or [None]:
        if n == "exercise":
            paths.append(exercise_path())
        elif n is not None and n.endswith(".s"):
            paths.append(n)
        else:
            paths += program_paths([n] if n else None, "v1b")
    if a.lockstep:
        return 0 if all([lockstep(p) for p in paths]) else 1
    for path in paths:
        name = os.path.basename(path)[:-2]
        try:
            m, r, dt = run_both(path)
        except RTLError as e:
            print(f"{name:<12} RTL ERROR {e}")
            fails += 1
            continue
        diffs = compare(m, r)
        print(f"{name:<12} {'ok' if not diffs else 'FAIL':<5} {m.instructions:>9} instr "
              f"{r.cycles:>10} cycles  CPI {r.cycles / max(1, m.instructions):5.2f}  {dt:6.1f} s")
        for d in diffs[:8 if a.v else 3]:
            print("    " + d)
        fails += bool(diffs)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
