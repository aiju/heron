"""Everything drafts 1a and 1b share in Python: the system, unary and shift
groups and branches, as the assembler and disassembler need them, and two
pieces of reference semantics for the draft 1b hardware study.

See isa-v1.md. Decoding and executing instructions is Rust
(studies/v1_isa/isa), which sim32.Machine32 runs.
"""

from heron.infra.asm import AsmError, Reg, RegRange, Imm, Mem, Expr
from heron.infra.obj import ABS32, ABS16S, PC16, PC16H

M32 = 0xFFFFFFFF
RAM_SIZE = 0x100000
IO_BASE = 0xFFFFFF00
MEM_TOP = RAM_SIZE          # the assembler refuses to place anything above this

RESET_VECTOR = 0x00
IRQ_VECTOR = 0x04
ILLEGAL_VECTOR = 0x08
SWI_VECTOR = 0x0C
DIV_VECTOR = 0x10
ADDR_VECTOR = 0x14

REGISTERS = {f"r{i}": i for i in range(16)}
REGISTERS["sp"] = 15


COND = ["EQ", "NE", "CS", "CC", "MI", "PL", "VS", "VC",
        "HI", "LS", "GE", "LT", "GT", "LE", "RA"]
COND_ALIAS = {"HS": 2, "LO": 3, "AL": 14}

ALU_FN = ["ADD", "ADC", "SUB", "SBC", "AND", "OR", "XOR", "BIC",
          "MOV", "CMP", "TST", "MULU", "MULS", "DIVU", "DIVS", "DIVUL"]
UN_FN = ["NOT", "NEG", "INC", "DEC", "RLC", "RRC", "SWAP",
         "SXB", "ZXB", "SXH", "ZXH", "CLZ"]
SHIFT_FN = ["LSL", "LSR", "ASR", "ROR"]
SYS_FN = ["HALT", "NOP", "JMP", "CALL", "RET", "SAVE", "RESTORE", "RTI",
          "EI", "DI", "MFSR", "MTSR", "SWI", "SET"]
SR_NAMES = {0: "flags", 1: "hi"}


def s32(x):
    x &= M32
    return x - (1 << 32) if x & 0x80000000 else x


def sext8(x):
    x &= 0xFF
    return x - 0x100 if x & 0x80 else x


def sext16(x):
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


# ==========================================================================
# Reference semantics
#
# The simulator's semantics are Rust (studies/v1_isa/isa/src/insn.rs).
# These remain in Python for the draft 1b hardware study, which checks its
# microcode's shift sequences against shift() and gives its register
# transfer model the branch conditions of cond_true().


def nz(m, res):
    m.n = res >> 31
    m.z = 1 if res == 0 else 0
    return res


def cond_true(m, cc):
    base = cc >> 1
    if base == 0: t = m.z
    elif base == 1: t = m.c
    elif base == 2: t = m.n
    elif base == 3: t = m.v
    elif base == 4: t = m.c & (m.z ^ 1)
    elif base == 5: t = 1 if m.n == m.v else 0
    elif base == 6: t = (m.z ^ 1) & (1 if m.n == m.v else 0)
    else: t = 1
    return t ^ (cc & 1)


def shift(m, op, x, n):
    if n == 0:
        res = x
    elif op == 0:      # LSL
        m.c = (x >> (32 - n)) & 1
        res = (x << n) & M32
    elif op == 1:      # LSR
        m.c = (x >> (n - 1)) & 1
        res = x >> n
    elif op == 2:      # ASR
        sx = s32(x)
        m.c = (sx >> (n - 1)) & 1
        res = (sx >> n) & M32
    else:              # ROR
        res = ((x >> n) | (x << (32 - n))) & M32
        m.c = res >> 31
    m.v = 0
    return nz(m, res)


# ==========================================================================
# Shared assembler pieces


def W(op, a=0, b=0, c=0):
    return ((op & 15) << 12) | ((a & 15) << 8) | ((b & 15) << 4) | (c & 15)


def kinds(ops):
    out = []
    for o in ops:
        if isinstance(o, Reg): out.append("R")
        elif isinstance(o, Imm): out.append("I")
        elif isinstance(o, Mem): out.append("M")
        elif isinstance(o, Expr): out.append("E")
        else: out.append("?")
    return "".join(out)


def cond_code(suffix):
    s = suffix.upper()
    if s in COND_ALIAS:
        return COND_ALIAS[s]
    if s in COND:
        return COND.index(s)
    return None


def norm32(v):
    """A value as an unsigned 32-bit pattern; accepts -2^31..2^32-1."""
    if not -(1 << 31) <= v < (1 << 32):
        raise AsmError(f"value {v} doesn't fit in 32 bits")
    return v & M32


def fits_s(v, bits):
    v = s32(v) if 0 <= v < (1 << 32) and v >= (1 << 31) else v
    return -(1 << (bits - 1)) <= v < (1 << (bits - 1))


def as_signed(v):
    """Interpret a 32-bit pattern as signed (so 0xFFFFFF00 counts as -256)."""
    if (1 << 31) <= v < (1 << 32):
        return v - (1 << 32)
    return v


def reg_operand(ctx, op, what="register"):
    if not isinstance(op, Reg):
        ctx.error(f"expected a {what}")
    if op.n > 15:
        ctx.error(f"{op.name} can't be used here")
    return op.n


def asm_common(U, ops, ctx, opmap):
    """Instructions encoded the same way in both drafts; only the major
    opcodes differ (opmap: un, sh, bcc, jcc). Returns parcels, or None."""
    k = kinds(ops)
    op_bcc, op_jcc = opmap["bcc"], opmap["jcc"]

    # ---- system group ----
    if U in ("HALT", "NOP", "RET", "RTI", "EI", "DI"):
        if ops:
            ctx.error(f"{U} takes no operands")
        return [W(0, 0, 0, SYS_FN.index(U))]
    if U in ("SAVE", "RESTORE"):
        a, b = reg_range(ctx, ops)
        return [W(0, a, b, SYS_FN.index(U))]
    if U in ("MFSR", "MTSR"):
        if U == "MFSR":
            if len(ops) != 2:
                ctx.error("MFSR needs 'rd, n'")
            rd = reg_operand(ctx, ops[0])
            n = sr_number(ctx, ops[1])
            return [W(0, rd, n, 10)]
        if len(ops) != 2:
            ctx.error("MTSR needs 'n, rs'")
        n = sr_number(ctx, ops[0])
        rs = reg_operand(ctx, ops[1])
        return [W(0, n, rs, 11)]
    if U in ("MFF", "MFHI"):
        if k != "R":
            ctx.error(f"{U} needs one register")
        return [W(0, ops[0].n, 0 if U == "MFF" else 1, 10)]
    if U in ("MTF", "MTHI"):
        if k != "R":
            ctx.error(f"{U} needs one register")
        return [W(0, 0 if U == "MTF" else 1, ops[0].n, 11)]
    if U == "SWI":
        if len(ops) != 1 or not isinstance(ops[0], (Imm, Expr)):
            ctx.error("SWI needs '#n'")
        v, known = ctx.value(ops[0].expr)
        if known and not 0 <= v <= 255:
            ctx.error("SWI number must be 0-255")
        return [W(0, v >> 4, v, 12)]
    if U.startswith("SET") and cond_code(U[3:]) is not None:
        if k != "R":
            ctx.error(f"{U} needs one register")
        return [W(0, ops[0].n, cond_code(U[3:]), 13)]

    # ---- unary group ----
    if U in UN_FN:
        f = UN_FN.index(U)
        if k == "RR":
            return [W(opmap["un"], ops[0].n, ops[1].n, f)]
        if k == "R":
            return [W(opmap["un"], ops[0].n, ops[0].n, f)]
        ctx.error(f"{U} needs 'rd, rs' or 'rd'")

    # ---- shift group ----
    if U in SHIFT_FN:
        f = SHIFT_FN.index(U)
        if k == "RR":
            return [W(opmap["sh"], ops[0].n, ops[1].n, 8 | f)]
        if k == "RI":
            v, known = ctx.value(ops[1].expr)
            if known and not 0 <= v <= 31:
                ctx.error("shift count must be 0-31")
            return [W(opmap["sh"], ops[0].n, v & 15, ((v >> 4) & 1) << 2 | f)]
        ctx.error(f"{U} needs 'rd, #n' or 'rd, rs'")

    # ---- branches ----
    if U == "BSR" or (U[0] == "B" and len(U) == 3 and cond_code(U[1:]) is not None) or U == "BRA":
        cc = 15 if U == "BSR" else cond_code(U[1:])
        if k != "E":
            ctx.error(f"{U} needs a target address")
        target, known = ctx.target(ops[0].expr)
        off = target - (ctx.pc + 2)
        if known and off & 1:
            ctx.error(f"{U} target is at an odd address")
        if ctx.min_words > 1 or (known and not -256 <= off <= 254):
            return jcc(ctx, op_jcc, cc, ops[0].expr)
        return [W(op_bcc, cc) | ((off >> 1) & 0xFF)]
    if U in ("JMP", "CALL") and k == "E":
        return jcc(ctx, op_jcc, 14 if U == "JMP" else 15, ops[0].expr)
    if U in ("JMP", "CALL") and k == "R":
        return [W(0, 0, ops[0].n, SYS_FN.index(U))]
    if U[0] == "J" and cond_code(U[1:]) is not None:
        if k != "E":
            ctx.error(f"{U} needs a target address")
        return jcc(ctx, op_jcc, cond_code(U[1:]), ops[0].expr)
    return None


def jcc(ctx, op_jcc, cc, expr):
    target, known = ctx.target(expr)
    off = target - (ctx.pc + 4)
    if known and off & 1:
        ctx.error("jump target is at an odd address")
    if ctx.min_words > 2 or (known and not -65536 <= off <= 65534):
        t, known = ctx.value(expr)
        t = norm32(t) if known else 0
        ctx.fix(1, ABS32, expr)
        return [W(op_jcc, cc, 1, 0), t & 0xFFFF, t >> 16]
    ctx.fix(1, PC16H, expr, ctx.pc + 4)
    return [W(op_jcc, cc, 0, 0), (off >> 1) & 0xFFFF]


def reg_range(ctx, ops):
    """'r8-r11' (a RegRange) or a single register."""
    if len(ops) == 1 and isinstance(ops[0], Reg):
        a = b = ops[0].n
    elif len(ops) == 1 and isinstance(ops[0], RegRange):
        a, b = ops[0].a.n, ops[0].b.n
    else:
        ctx.error("expected a register range like r8-r11")
    if not 1 <= a <= b <= 14:
        ctx.error("register range must be within r1-r14, low to high")
    return a, b


def sr_number(ctx, op):
    if isinstance(op, Expr) and op.expr[0] == "sym" and op.expr[1].lower() in ("flags", "hi"):
        return 0 if op.expr[1].lower() == "flags" else 1
    if isinstance(op, (Imm, Expr)):
        v, _ = ctx.value(op.expr)
        if v not in SR_NAMES:
            ctx.error("special register must be 0 (flags) or 1 (hi)")
        return v
    ctx.error("expected a special register number")


# ==========================================================================
# Shared disassembler pieces


def R(n):
    return "sp" if n == 15 else f"r{n}"


def fmt_imm(v):
    """Canonical immediate: signed decimal if it fits 16 bits, else hex."""
    v &= M32
    sv = as_signed(v)
    return f"#{sv}" if -32768 <= sv <= 32767 else f"#0x{v:X}"


def sym(v, symbols):
    if symbols and v in symbols:
        return symbols[v]
    return f"0x{v:X}"


def dis_sys(w):
    a, b, f = (w >> 8) & 15, (w >> 4) & 15, w & 15
    if f >= len(SYS_FN):
        return None
    m = SYS_FN[f]
    if m in ("JMP", "CALL"):
        return f"{m} {R(b)}"
    if m in ("SAVE", "RESTORE"):
        if not 1 <= a <= b <= 14:
            return None
        return f"{m} {R(a)}-{R(b)}"
    if m == "MFSR":
        return f"MFSR {R(a)}, {SR_NAMES[b]}" if b in SR_NAMES else None
    if m == "MTSR":
        return f"MTSR {SR_NAMES[a]}, {R(b)}" if a in SR_NAMES else None
    if m == "SWI":
        return f"SWI #{(a << 4) | b}"
    if m == "SET":
        return f"SET{COND[b]} {R(a)}" if b < 15 else None
    return m


def dis_unary(w):
    d, s, f = (w >> 8) & 15, (w >> 4) & 15, w & 15
    if f >= len(UN_FN):
        return None
    return f"{UN_FN[f]} {R(d)}, {R(s)}"


def dis_shift(w):
    d, s, f = (w >> 8) & 15, (w >> 4) & 15, w & 15
    t = f >> 2
    if t == 3:
        return None
    if t == 2:
        return f"{SHIFT_FN[f & 3]} {R(d)}, {R(s)}"
    return f"{SHIFT_FN[f & 3]} {R(d)}, #{s + 16 * t}"


def dis_bcc(w, pc, symbols):
    cc = (w >> 8) & 15
    target = (pc + 2 + 2 * sext8(w)) & M32
    m = "BSR" if cc == 15 else "B" + COND[cc]
    return f"{m} {sym(target, symbols)}"


def dis_jcc(w, ext, pc, symbols):
    cc, k, z = (w >> 8) & 15, (w >> 4) & 15, w & 15
    if k > 1 or z:
        return None, 1
    m = "CALL" if cc == 15 else ("JMP" if cc == 14 else "J" + COND[cc])
    if k == 0:
        target = (pc + 4 + 2 * sext16(ext[0])) & M32
        return f"{m} {sym(target, symbols)}", 2
    target = (ext[0] | (ext[1] << 16)) & 0xFFFFFFFE
    return f"{m} {sym(target, symbols)}", 3
