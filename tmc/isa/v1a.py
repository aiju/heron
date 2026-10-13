"""ISA draft 1a: 32-bit, 16-bit parcels, load/store (RISC-like).

See docs/isa-v1a.md. Shared parts (system/unary/shift groups, branches,
semantics) live in v1common.
"""

from ..asm import Imm
from . import v1common as c
from .v1common import (M32, W, kinds, norm32, as_signed, sext8, sext16, crosses, nz,
                       ALU_FN, R, sym)

NAME = "v1a"
DESCRIPTION = "draft 1a: 32-bit registers, 16-bit parcels, load/store"
PROGRAM_DIR = "v1a"

REGISTERS = c.REGISTERS
WIDE = True                     # tells the tools to use tmc.sim32
WORD_BYTES = 4
MEM_TOP = c.MEM_TOP
IO_BASE = c.IO_BASE
RESET_VECTOR = c.RESET_VECTOR
IRQ_VECTOR = c.IRQ_VECTOR

OP_SYS, OP_ALU, OP_UN, OP_BCC = 0x0, 0x1, 0x2, 0x3
OP_LD, OP_ST, OP_LDB, OP_STB = 0x4, 0x5, 0x6, 0x7
OP_ALUI, OP_JCC, OP_MEML, OP_SH = 0x8, 0x9, 0xA, 0xB
OP_MVI, OP_ADDI, OP_CMPI = 0xC, 0xD, 0xE
OPMAP = {"un": OP_UN, "sh": OP_SH, "bcc": OP_BCC, "jcc": OP_JCC}

# long memory functions (op A): name -> (fn with disp16, fn with disp32 or None)
MEM_FN = {"LD": (0, 0xA), "ST": (1, 0xB), "LDB": (2, 0xC), "STB": (3, 0xD),
          "LDH": (4, None), "STH": (5, None), "LDSB": (6, None), "LDSH": (7, None),
          "LEA": (8, 0xE)}
MEM_NAMES = ["LD", "ST", "LDB", "STB", "LDH", "STH", "LDSB", "LDSH", "LEA"]
# (is load, size in bytes, sign-extend)
MEM_INFO = {0: ("ld", 4, False), 1: ("st", 4, False), 2: ("ld", 1, False), 3: ("st", 1, False),
            4: ("ld", 2, False), 5: ("st", 2, False), 6: ("ld", 1, True), 7: ("ld", 2, True)}


# ==========================================================================
# Assembler hook


def _imm_kind(v, min_words):
    """Pick op 8's immediate kind for a 32-bit pattern v."""
    sv = as_signed(v)
    if min_words <= 2:
        if -32768 <= sv <= 32767:
            return 0
        if v <= 0xFFFF:
            return 1
        if v & 0xFFFF == 0:
            return 2
    return 3


def _imm_parcels(k, v):
    if k == 0 or k == 1:
        return [v & 0xFFFF]
    if k == 2:
        return [v >> 16]
    return [v & 0xFFFF, v >> 16]


def assemble(name, ops, ctx):
    U = name.upper()
    k = kinds(ops)

    if U == "PUSH":
        return c.asm_common("SAVE", ops, ctx, OPMAP)
    if U == "POP":
        return c.asm_common("RESTORE", ops, ctx, OPMAP)

    out = c.asm_common(U, ops, ctx, OPMAP)
    if out is not None:
        return out

    # ---- two-operand ALU ----
    if U in ALU_FN:
        fn = ALU_FN.index(U)
        if k == "RR":
            return [W(OP_ALU, ops[0].n, ops[1].n, fn)]
        if k == "RI":
            rd = ops[0].n
            v, known = ctx.value(ops[1].expr)
            if known:
                v = norm32(v)
            sv = as_signed(v)
            short = {"MOV": OP_MVI, "CMP": OP_CMPI}.get(U)
            if short is not None and ctx.min_words <= 1 and -128 <= sv <= 127:
                return [W(short, rd) | (sv & 0xFF)]
            kind = _imm_kind(v, ctx.min_words)
            if kind in (0, 3):
                ctx.fix(1, c.ABS16S if kind == 0 else c.ABS32, ops[1].expr)
            return [W(OP_ALUI, rd, kind, fn)] + _imm_parcels(kind, v)
        ctx.error(f"{U} needs 'rd, rs' or 'rd, #imm'")
    if U == "LI":
        if k not in ("RE", "RI"):
            ctx.error("LI needs 'rd, value'")
        return assemble("MOV", [ops[0], Imm(ops[1].expr)], ctx)
    if U in ("MVI", "ADDI", "CMPI"):
        if k not in ("RE", "RI"):
            ctx.error(f"{U} needs 'rd, imm8'")
        v, known = ctx.value(ops[1].expr)
        if known:
            v = as_signed(norm32(v))
            if not -128 <= v <= 127:
                ctx.error(f"value {v} doesn't fit in a signed 8-bit immediate (-128..127)")
        op = {"MVI": OP_MVI, "ADDI": OP_ADDI, "CMPI": OP_CMPI}[U]
        return [W(op, ops[0].n) | (v & 0xFF)]

    # ---- loads, stores, LEA ----
    if U in MEM_FN:
        if U == "LEA" and k == "RE":
            # PC-relative: rd <- PC + disp16
            target, known = ctx.target(ops[1].expr)
            off = target - (ctx.pc + 4)
            if ctx.min_words <= 2 and (not known or -32768 <= off <= 32767):
                ctx.fix(1, c.PC16, ops[1].expr, ctx.pc + 4)
                return [W(OP_MEML, ops[0].n, 0, 9), off & 0xFFFF]
            t, known = ctx.value(ops[1].expr)
            t = norm32(t) if known else 0
            ctx.fix(1, c.ABS32, ops[1].expr)
            return [W(OP_MEML, ops[0].n, 0, 0xE), t & 0xFFFF, t >> 16]
        if k != "RM":
            ctx.error(f"{U} needs 'reg, [base + offset]'")
        mem = ops[1]
        if mem.index is not None:
            ctx.error("draft 1a has no register + register addressing: add the registers first, "
                      "or use [label + reg] for a static array")
        if not mem.plain():
            ctx.error("draft 1a has no size keywords or auto-increment: the size is in the mnemonic")
        rd = ops[0].n
        base = mem.base.n if mem.base else 0
        if mem.base is not None and mem.base.n > 15:
            ctx.error("bad base register")
        if mem.disp is None:
            disp, known = 0, True
        else:
            disp, known = ctx.value(mem.disp)
        if known:
            disp = norm32(disp)
        sd = as_signed(disp)
        if ctx.min_words <= 1 and known:
            if U in ("LD", "ST") and 0 <= sd <= 60 and sd % 4 == 0:
                return [W(OP_LD if U == "LD" else OP_ST, rd, base, sd // 4)]
            if U in ("LDB", "STB") and 0 <= sd <= 15:
                return [W(OP_LDB if U == "LDB" else OP_STB, rd, base, sd)]
        f16, f32 = MEM_FN[U]
        if ctx.min_words <= 2 and (not known or -32768 <= sd <= 32767):
            if mem.disp is not None:
                ctx.fix(1, c.ABS16S, mem.disp)
            return [W(OP_MEML, rd, base, f16), disp & 0xFFFF]
        if f32 is None:
            ctx.error(f"{U} only has a 16-bit displacement: put the address in a register")
        ctx.fix(1, c.ABS32, mem.disp)
        return [W(OP_MEML, rd, base, f32), disp & 0xFFFF, disp >> 16]

    ctx.error(f"unknown instruction {name}")


# ==========================================================================
# Decoder (for the simulator)


def decode(m, pc):
    w = m.parcel(pc)
    op = w >> 12
    d, s, f = (w >> 8) & 15, (w >> 4) & 15, w & 15
    if op == OP_SYS:
        return c.dec_sys(m, pc, w), 1
    if op == OP_ALU:
        return c.dec_alu_rr(m, pc, w, f, d, s), 1
    if op == OP_UN:
        return c.dec_unary(m, pc, w), 1
    if op == OP_BCC:
        return c.dec_bcc(m, pc, w), 1
    if OP_LD <= op <= OP_STB:
        return _dec_short(m, pc, w), 1
    if op == OP_ALUI:
        if s > 3:
            return c.illegal_fn, 1
        n = 3 if s == 3 else 2
        e0 = m.parcel(pc + 2)
        if s == 0:
            v = sext16(e0) & M32
        elif s == 1:
            v = e0
        elif s == 2:
            v = e0 << 16
        else:
            v = e0 | (m.parcel(pc + 4) << 16)
        return c.dec_alu_imm(m, pc, n, f, d, v), n
    if op == OP_JCC:
        fn = c.dec_jcc(m, pc, w)
        return fn, (3 if s == 1 else 2) if s <= 1 and f == 0 else 1
    if op == OP_MEML:
        return _dec_long(m, pc, w)
    if op == OP_SH:
        return c.dec_shift(m, pc, w), 1
    if op == OP_MVI:
        return c.dec_alu_imm(m, pc, 1, 8, d, sext8(w) & M32), 1
    if op == OP_ADDI:
        return _dec_addi(m, pc, d, sext8(w)), 1
    if op == OP_CMPI:
        return c.dec_alu_imm(m, pc, 1, 9, d, sext8(w) & M32), 1
    return c.illegal_fn, 1


def _dec_addi(m, pc, d, v):
    nxt = (pc + 2) & M32
    key = (1, pc & 2, "alu", 1)
    r = m.r

    def fn(m):
        res = nz(m, (r[d] + v) & M32)
        if d:
            r[d] = res
        m.pc = nxt
        return key
    return fn


def _access(m, kind, size, signed, d, a, r):
    """Do one load or store for register d at address a."""
    if kind == "ld":
        if size == 4:
            v = m.rd32(a)
        elif size == 2:
            v = m.rd16(a)
            if signed and v & 0x8000:
                v |= 0xFFFF0000
        else:
            v = m.rd8(a)
            if signed and v & 0x80:
                v |= 0xFFFFFF00
        nz(m, v)
        if d:
            r[d] = v
    elif size == 4:
        m.wr32(a, r[d])
    elif size == 2:
        m.wr16(a, r[d] & 0xFFFF)
    else:
        m.wr8(a, r[d] & 0xFF)


def _dec_short(m, pc, w):
    op = w >> 12
    d, s, o = (w >> 8) & 15, (w >> 4) & 15, w & 15
    word = op in (OP_LD, OP_ST)
    off = 4 * o if word else o
    size = 4 if word else 1
    kind = "ld" if op in (OP_LD, OP_LDB) else "st"
    nxt = (pc + 2) & M32
    p2 = pc & 2
    r = m.r

    def fn(m):
        base = r[s]
        a = (base + off) & M32
        _access(m, kind, size, False, d, a, r)
        m.pc = nxt
        return (1, p2, kind, "rd", size, crosses(base, a))
    return fn


def _dec_long(m, pc, w):
    d, s, f = (w >> 8) & 15, (w >> 4) & 15, w & 15
    if f == 0xF:
        return c.illegal_fn, 1
    p2 = pc & 2
    r = m.r
    if f >= 0xA:
        n = 3
        disp = m.parcel(pc + 2) | (m.parcel(pc + 4) << 16)
        fn16 = [0, 1, 2, 3, 8][f - 0xA]
        ea = "abs" if s == 0 else "rd32"
    else:
        n = 2
        disp = sext16(m.parcel(pc + 2)) & M32
        fn16 = f
        ea = "abs" if s == 0 else "rd"
    nxt = (pc + 2 * n) & M32
    if fn16 == 9:                       # PC-relative LEA
        v = (nxt + disp) & M32
        key = (n, p2, "lea", "pc", crosses(nxt, v))

        def fn(m):
            if d:
                r[d] = v
            m.pc = nxt
            return key
        return fn, n
    if fn16 == 8:                       # LEA
        def fn(m):
            base = r[s]
            a = (base + disp) & M32
            if d:
                r[d] = a
            m.pc = nxt
            return (n, p2, "lea", ea, crosses(base, a) if ea == "rd" else 0)
        return fn, n
    kind, size, signed = MEM_INFO[fn16]

    def fn(m):
        base = r[s]
        a = (base + disp) & M32
        _access(m, kind, size, signed, d, a, r)
        m.pc = nxt
        return (n, p2, kind, ea, size, crosses(base, a) if ea == "rd" else 0)
    return fn, n


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
