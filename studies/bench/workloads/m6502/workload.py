"""A 6502 emulator in hand-written assembly running a ROM of 8-bit
software: emulation done the software way, as a hobbyist runs old 8-bit
programs on a newer machine (report 0039 did it in microcode instead,
on branch claude/festive-cerf-qxo439).

The emulator (emu.s, and ops_*.s for the instructions) has every
documented NMOS opcode and addressing mode, decimal-mode ADC and SBC as
the NMOS chip gets them, the indirect JMP's page bug, the stack wrapping
in page 1, and the datasheet's cycle count, page crossings included.
It dispatches through a 256-entry table, one handler per opcode with its
addressing mode written out. A, X, Y, S, the PC (as a host address) and
the counts live in registers. N and Z are kept lazily, as the last
result sign-extended (one SXB per instruction, a ZXB or TST at a
branch), C as 0 or 1, ready for ADC, and V in bit 7 of
(A ^ sum) & (M ^ sum); D and I, rarely read, are in memory. The 6502's
64 KB is a byte array in Heron's RAM, aligned to 64 KB so that the PC's
host address is the 6502's PC in its low half. At start-up the emulator
copies the 4 KB ROM to the top of it; the 6502 runs until it writes the
DONE port, and its printed output, registers, cycle and instruction
counts and a hash of the RAM holding its results are reported.

The 6502 program (program.a65, assembled by asm6502.py into the ROM)
runs, for REPS passes: the BYTE sieve, a Shell sort of pseudo-random
signed words with a table-driven CRC-16, 16-bit division checked by
multiplication, string copying, case folding, counting, comparing and
reversing, Fibonacci numbers in 12-digit BCD in decimal mode, and a
Forth-like bytecode machine dispatched with the RTS trick running Collatz
chains; a BRK "system call" per pass, and printing through a vectored
putc with decimal conversion in decimal mode at the end. `test` runs
6,500 6502 instructions, `ref` 107,000 (two passes of larger problems).

Where the time goes (ref, the instruction-level profile): about 10.5
Heron instructions per 6502 instruction, three of them the dispatch
(the opcode, the count, the jump through the table) and one the cycle
count. Taken branches are 11% of the cycles (their page check),
then the loads (LDA zp 8%, LDA abs,Y and (zp),Y 5% each), ADC and SBC
(5.5%, and 3.5% more in decimal mode), stores, increments and
subroutine calls; no one handler dominates, as in a real emulator
running real programs.

The reference is cpu6502.py, a 6502 in plain Python written unlike the
assembly (it decodes opcodes from their bit fields and costs cycles by
the datasheet's rules), on the same ROM. Its self-test, `python3 -m
heron.studies.bench.workloads.m6502.cpu6502`, checks its decoder against
the assembler, its decimal mode against a second formulation on every
input, and the program's printed results against Python's own
computation of them."""

import functools
import os

from . import asm6502, cpu6502

TITLE = "a 6502 emulator running 8-bit programs"
PART = "asm"
CATEGORY = "emulation"
SOURCES = ["emu.s", "ops_load.s", "ops_alu.s", "ops_rmw.s", "ops_flow.s"]
SIZES = {
    "test": {"REPS": 1, "SIEVE": 16, "SORTN": 6, "DIVN": 1, "TEXTN": 12,
             "FIBN": 3, "VMN": 2},
    "ref": {"REPS": 2, "SIEVE": 300, "SORTN": 48, "DIVN": 8, "TEXTN": 160,
            "FIBN": 40, "VMN": 6},
}

HERE = os.path.dirname(os.path.abspath(__file__))
ROM_BASE = 0xF000               # the program's ROM: $F000-$FFFF
HASH_END = 0x0600               # emu.s hashes the 6502's memory below this


@functools.lru_cache(None)
def _assemble(params):
    with open(os.path.join(HERE, "program.a65")) as f:
        text = f.read()
    a = asm6502.assemble(text, dict(params), "program.a65")
    lo, hi = a.span()
    code = sorted(x for x in a.written if x < 0xFFFA)
    if lo < ROM_BASE or code[-1] >= 0xFFFA:
        raise asm6502.AsmError(f"the program doesn't fit its ROM: ${lo:04X}-${hi - 1:04X}")
    return a


def data(p):
    """The ROM, which emu.s copies to the top of the 6502's memory."""
    mem = _assemble(tuple(sorted(p.items()))).mem
    return {"rom": bytes(mem[ROM_BASE:])}


def reference(p):
    """The same ROM on cpu6502.py's emulator, reported as emu.s reports."""
    mem = _assemble(tuple(sorted(p.items()))).mem
    cpu = cpu6502.Cpu(mem).run()
    h = 5381
    for b in cpu.mem[:HASH_END]:
        h = ((h * 33) ^ b) & 0xFFFFFFFF
    out = bytes(cpu.out)
    for label, v in (("pc", cpu.pc), ("a", cpu.a), ("x", cpu.x), ("y", cpu.y),
                     ("p", cpu.p), ("s", cpu.s), ("cycles", cpu.cycles),
                     ("instructions", cpu.instructions), ("memory", h),
                     ("jammed", int(cpu.jammed))):
        out += f"{label} {v:08x}\n".encode()
    return out
