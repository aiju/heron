"""ISA draft 1b: 32-bit, 16-bit parcels, register + addressing mode (CISC-like).

See RFC 0004, Part II (reports/0004-rfc-draft-1-isa.md). Main format `F D M R`: operation, register, mode,
register-or-constant for the mode. This is the disassembler's side;
decoding and executing is Rust (studies/v1_isa/isa/src/v1b.rs), and so is
the encoder the assembler uses (studies/v1_isa/isa/src/asm/v1b.rs). Shared
parts live in v1common.
"""

from . import v1common as c
from .v1common import M32, sext8, sext16, R, sym

NAME = "v1b"
DESCRIPTION = "draft 1b: 32-bit registers, 16-bit parcels, register + addressing mode"

WIDE = True                     # tells the tools to use sim32
MEM_TOP = c.MEM_TOP
IO_BASE = c.IO_BASE
RESET_VECTOR = c.RESET_VECTOR
IRQ_VECTOR = c.IRQ_VECTOR

OP_SYS, OP_MOV, OP_ST, OP_LEA = 0x0, 0x1, 0x2, 0x3
OP_ADD, OP_SUB, OP_CMP, OP_AND, OP_OR, OP_XOR = 0x4, 0x5, 0x6, 0x7, 0x8, 0x9
OP_JCC, OP_JEA, OP_UN, OP_SH, OP_BCC, OP_RR = 0xA, 0xB, 0xC, 0xD, 0xE, 0xF

# EA instructions: name -> opcode
EA_OPS = {"MOV": OP_MOV, "ST": OP_ST, "LEA": OP_LEA, "ADD": OP_ADD, "SUB": OP_SUB,
          "CMP": OP_CMP, "AND": OP_AND, "OR": OP_OR, "XOR": OP_XOR}
EA_NAMES = {v: k for k, v in EA_OPS.items()}
RR_FN = ["ADC", "SBC", "BIC", "TST", "MULU", "MULS", "DIVU", "DIVS", "DIVUL"]

SIZE_NAME = {1: "byte ", 2: "half ", 4: ""}


# ==========================================================================
# Addressing modes


def ea_info(M, Rn, ext):
    """Decode a mode. Returns (operand, extra parcels) where operand is
    ('reg', r) | ('imm', value) | ('mem', base, disp, index, scale, size, timing kind)
    with base None for absolute and 'pc' for PC-relative, or None if reserved."""
    if M == 0:
        return ("reg", Rn), 0
    if M == 1:
        return ("imm", Rn), 0
    if M == 0xD:
        return ("imm", (-(Rn + 1)) & M32), 0
    if M == 2:
        return ("mem", Rn, 0, None, 1, 4, "r"), 0
    if M == 3:
        return ("mem", Rn, sext16(ext[0]), None, 1, 4, "rd"), 1
    if M == 4:
        return ("mem", 15, 4 * Rn, None, 1, 4, "rd"), 0
    if M == 5:
        e = ext[0]
        z = (e >> 8) & 3
        if z == 3:
            return None, 1
        return ("mem", Rn, sext8(e), e >> 12, 1 << ((e >> 10) & 3), (1, 2, 4)[z], "idx"), 1
    if M == 6:
        return ("mem", Rn, 0, None, 1, 4, "pi"), 0
    if M == 7:
        return ("mem", Rn, 0, None, 1, 4, "pd"), 0
    if M == 8:
        return ("mem", Rn, 0, None, 1, 1, "r"), 0
    if M == 9:
        return ("mem", Rn, sext16(ext[0]), None, 1, 1, "rd"), 1
    if M == 0xA:
        return ("mem", Rn, 0, None, 1, 1, "pi"), 0
    if M == 0xB:
        return ("mem", Rn, 0, None, 1, 2, "r"), 0
    if M == 0xC:
        return ("mem", Rn, sext16(ext[0]), None, 1, 2, "rd"), 1
    if M == 0xF:
        if Rn == 0:
            return ("imm", sext16(ext[0]) & M32), 1
        if Rn == 1:
            return ("imm", ext[0]), 1
        if Rn == 2:
            return ("imm", ext[0] << 16), 1
        if Rn == 3:
            return ("imm", ext[0] | (ext[1] << 16)), 2
        if 4 <= Rn <= 6:
            return ("mem", None, sext16(ext[0]) & M32, None, 1, (4, 1, 2)[Rn - 4], "abs"), 1
        if 7 <= Rn <= 9:
            return ("mem", None, ext[0] | (ext[1] << 16), None, 1, (4, 1, 2)[Rn - 7], "abs"), 2
        if 0xA <= Rn <= 0xC:
            return ("mem", "pc", sext16(ext[0]), None, 1, (4, 1, 2)[Rn - 0xA], "pc"), 1
        return None, 0
    return None, 0


def mode_size(M, Rn):
    """Extra parcels a mode needs (from the first parcel alone)."""
    if M in (3, 5, 9, 0xC):
        return 1
    if M == 0xF:
        return 2 if Rn in (3, 7, 8, 9) else (1 if Rn <= 0xC else 0)
    return 0


def size_of(w):
    op = w >> 12
    if 1 <= op <= 9 or op == OP_JEA:
        return 1 + mode_size((w >> 4) & 15, w & 15)
    if op == OP_JCC:
        k, f = (w >> 4) & 15, w & 15
        return 3 if k == 1 and f == 0 else (2 if k == 0 and f == 0 else 1)
    return 1


# ==========================================================================
# Disassembler


_fmt_imm = c.fmt_imm


def dis_ea(M, Rn, ext, nxt, symbols):
    opnd, _ = ea_info(M, Rn, ext)
    if opnd is None:
        return None
    if opnd[0] == "reg":
        return R(Rn)
    if opnd[0] == "imm":
        return _fmt_imm(opnd[1])
    _, base, disp, index, scale, size, tk = opnd
    sz = SIZE_NAME[size]
    if tk == "abs":
        return f"{sz}[{sym(disp & M32, symbols)}]"
    if tk == "pc":
        return f"{sz}[{sym((nxt + disp) & M32, symbols)}]"
    if tk == "pi":
        return f"{sz}[{R(base)}]+"
    if tk == "pd":
        return f"{sz}-[{R(base)}]"
    parts = R(base)
    if index is not None:
        parts += f" + {R(index)}" + (f"*{scale}" if scale != 1 else "")
    if disp:
        parts += f" - {-disp}" if disp < 0 else f" + {disp}"
    return f"{sz}[{parts}]"


def disassemble(ws, pc=0, symbols=None):
    w = ws[0]
    ext = list(ws[1:]) + [0, 0]
    op = w >> 12
    d, M, Rn = (w >> 8) & 15, (w >> 4) & 15, w & 15
    bad = (f".half 0x{w:04X} ; illegal", 1)
    if op == OP_SYS:
        t = c.dis_sys(w)
        return (t, 1) if t else bad
    if op == OP_UN:
        t = c.dis_unary(w)
        return (t, 1) if t else bad
    if op == OP_SH:
        t = c.dis_shift(w)
        return (t, 1) if t else bad
    if op == OP_BCC:
        return c.dis_bcc(w, pc, symbols), 1
    if op == OP_JCC:
        t, n = c.dis_jcc(w, ext, pc, symbols)
        return (t, n) if t else bad
    if op == OP_RR:
        f = w & 15
        if f >= len(RR_FN):
            return bad
        return f"{RR_FN[f]} {R(d)}, {R(M)}", 1
    n = size_of(w)
    nxt = (pc + 2 * n) & M32
    opnd, _ = ea_info(M, Rn, ext)
    if opnd is None:
        return bad
    t = dis_ea(M, Rn, ext, nxt, symbols)
    if op == OP_JEA:
        if d > 1 or (opnd[0] == "mem" and opnd[5] != 4):
            return bad
        return f"{'CALL' if d else 'JMP'} {t}", n
    if op == OP_ST and opnd[0] != "mem":
        return bad
    if op == OP_LEA and (opnd[0] != "mem" or opnd[6] in ("pi", "pd")):
        return bad
    return f"{EA_NAMES[op]} {R(d)}, {t}", n


MODE_CLASS = {"reg": "r", "r": "[r]", "rd": "[r+d]", "abs": "[abs]", "pc": "[pc+d]",
              "idx": "[r+x]", "pi": "[r]+", "pd": "-[r]"}


def mode_class(ws):
    """Short description of the operand mode, for statistics."""
    w = ws[0]
    M, Rn = (w >> 4) & 15, w & 15
    opnd, _ = ea_info(M, Rn, list(ws[1:]) + [0, 0])
    if opnd is None:
        return "?"
    if opnd[0] == "reg":
        return "r"
    if opnd[0] == "imm":
        return "#q" if M in (1, 0xD) else ("#i32" if Rn == 3 else "#i16")
    tk = opnd[6]
    if M == 4:
        tk_name = "[sp+n]"
    else:
        tk_name = MODE_CLASS[tk]
    return {1: "b", 2: "h", 4: ""}[opnd[5]] + tk_name


def kind(ws):
    w = ws[0]
    op, d = w >> 12, (w >> 8) & 15
    if op == OP_SYS:
        if (w & 15) < len(c.SYS_FN):
            k = c.SYS_FN[w & 15]
            return "SETcc" if k == "SET" else k
        return "illegal"
    if op == OP_UN:
        return c.UN_FN[w & 15] if (w & 15) < len(c.UN_FN) else "illegal"
    if op == OP_SH:
        f = w & 15
        return c.SHIFT_FN[f & 3] + (" reg" if f >> 2 == 2 else "")
    if op == OP_BCC:
        return "BSR" if d == 15 else ("BRA" if d == 14 else "Bcc")
    if op == OP_JCC:
        return "CALL" if d == 15 else ("JMP" if d == 14 else "Jcc")
    if op == OP_RR:
        return RR_FN[w & 15] if (w & 15) < len(RR_FN) else "illegal"
    name = "JMP" if op == OP_JEA and d == 0 else ("CALL" if op == OP_JEA else EA_NAMES[op])
    return f"{name} {mode_class(ws)}"
