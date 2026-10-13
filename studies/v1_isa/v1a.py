"""ISA draft 1a: 32-bit, 16-bit parcels, load/store (RISC-like).

See isa-v1a.md. This is the disassembler's side; decoding and executing
is Rust (studies/v1_isa/isa/src/v1a.rs), and so is the encoder the
assembler uses (studies/v1_isa/isa/src/asm/v1a.rs). Shared parts live in
v1common.
"""

from . import v1common as c
from .v1common import M32, as_signed, sext8, sext16, ALU_FN, R, sym

NAME = "v1a"
DESCRIPTION = "draft 1a: 32-bit registers, 16-bit parcels, load/store"

WIDE = True                     # tells the tools to use sim32
MEM_TOP = c.MEM_TOP
IO_BASE = c.IO_BASE
RESET_VECTOR = c.RESET_VECTOR
IRQ_VECTOR = c.IRQ_VECTOR

OP_SYS, OP_ALU, OP_UN, OP_BCC = 0x0, 0x1, 0x2, 0x3
OP_LD, OP_ST, OP_LDB, OP_STB = 0x4, 0x5, 0x6, 0x7
OP_ALUI, OP_JCC, OP_MEML, OP_SH = 0x8, 0x9, 0xA, 0xB
OP_MVI, OP_ADDI, OP_CMPI = 0xC, 0xD, 0xE

# long memory functions (op A) with a 16-bit displacement, by number
MEM_NAMES = ["LD", "ST", "LDB", "STB", "LDH", "STH", "LDSB", "LDSH", "LEA"]


# ==========================================================================
# Disassembler


def size_of(w):
    """Instruction length in parcels, from the first parcel."""
    op, s, f = w >> 12, (w >> 4) & 15, w & 15
    if op == OP_ALUI:
        return 3 if s == 3 else (2 if s < 3 else 1)
    if op == OP_JCC:
        return 3 if s == 1 and f == 0 else (2 if s == 0 and f == 0 else 1)
    if op == OP_MEML:
        return 1 if f == 0xF else (3 if f >= 0xA else 2)
    return 1


def disassemble(ws, pc=0, symbols=None):
    """ws: the parcels at pc (at least size_of(ws[0]) of them).
    Returns (text, parcels)."""
    w = ws[0]
    ext = list(ws[1:]) + [0, 0]
    op = w >> 12
    d, s, f = (w >> 8) & 15, (w >> 4) & 15, w & 15
    bad = (f".half 0x{w:04X} ; illegal", 1)
    if op == OP_SYS:
        t = c.dis_sys(w)
        return (t, 1) if t else bad
    if op == OP_ALU:
        return f"{ALU_FN[f]} {R(d)}, {R(s)}", 1
    if op == OP_UN:
        t = c.dis_unary(w)
        return (t, 1) if t else bad
    if op == OP_BCC:
        return c.dis_bcc(w, pc, symbols), 1
    if OP_LD <= op <= OP_STB:
        m = ["LD", "ST", "LDB", "STB"][op - OP_LD]
        off = 4 * f if op in (OP_LD, OP_ST) else f
        if s == 0:
            return f"{m} {R(d)}, [{sym(off, symbols)}]", 1
        return f"{m} {R(d)}, [{R(s)}{' + ' + str(off) if off else ''}]", 1
    if op == OP_ALUI:
        if s > 3:
            return bad
        if s == 0:
            v = sext16(ext[0]) & M32
        elif s == 1:
            v = ext[0]
        elif s == 2:
            v = ext[0] << 16
        else:
            v = ext[0] | (ext[1] << 16)
        return f"{ALU_FN[f]} {R(d)}, {c.fmt_imm(v)}", size_of(w)
    if op == OP_JCC:
        t, n = c.dis_jcc(w, ext, pc, symbols)
        return (t, n) if t else bad
    if op == OP_MEML:
        if f == 0xF:
            return bad
        n = size_of(w)
        if f >= 0xA:
            disp = ext[0] | (ext[1] << 16)
            name = ["LD", "ST", "LDB", "STB", "LEA"][f - 0xA]
        elif f == 9:
            target = (pc + 4 + sext16(ext[0])) & M32
            return f"LEA {R(d)}, {sym(target, symbols)}", 2
        else:
            disp = sext16(ext[0]) & M32
            name = MEM_NAMES[f]
        if s == 0:
            return f"{name} {R(d)}, [{sym(disp, symbols)}]", n
        sd = as_signed(disp)
        sign = f" - {-sd}" if sd < 0 else f" + {sd}"
        return f"{name} {R(d)}, [{R(s)}{sign}]", n
    if op == OP_SH:
        t = c.dis_shift(w)
        return (t, 1) if t else bad
    if op == OP_MVI:
        return f"MOV {R(d)}, #{sext8(w)}", 1
    if op == OP_ADDI:
        return f"ADDI {R(d)}, {sext8(w)}", 1
    if op == OP_CMPI:
        return f"CMP {R(d)}, #{sext8(w)}", 1
    return bad


def kind(ws):
    """Mnemonic class for instruction-mix statistics."""
    w = ws[0]
    op, d, s, f = w >> 12, (w >> 8) & 15, (w >> 4) & 15, w & 15
    if op == OP_SYS:
        if f < len(c.SYS_FN):
            k = c.SYS_FN[f]
            return "SETcc" if k == "SET" else k
        return "illegal"
    if op == OP_ALU:
        return ALU_FN[f]
    if op == OP_UN:
        return c.UN_FN[f] if f < len(c.UN_FN) else "illegal"
    if op == OP_BCC:
        return "BSR" if d == 15 else ("BRA" if d == 14 else "Bcc")
    if OP_LD <= op <= OP_STB:
        return ["LD", "ST", "LDB", "STB"][op - OP_LD] + " short"
    if op == OP_ALUI:
        return ALU_FN[f] + (" #imm32" if s == 3 else " #imm16")
    if op == OP_JCC:
        return "CALL" if d == 15 else ("JMP" if d == 14 else "Jcc")
    if op == OP_MEML:
        if f == 9:
            return "LEA pc"
        if f >= 0xA:
            return ["LD", "ST", "LDB", "STB", "LEA"][f - 0xA] + " disp32"
        if f == 0xF:
            return "illegal"
        return MEM_NAMES[f] + (" abs" if s == 0 else " long")
    if op == OP_SH:
        return c.SHIFT_FN[f & 3] + (" reg" if f >> 2 == 2 else "")
    return {OP_MVI: "MVI", OP_ADDI: "ADDI", OP_CMPI: "CMPI"}.get(op, "illegal")
