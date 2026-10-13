"""Everything drafts 1a and 1b share in Python: the system, unary and shift
groups and branches, as the disassembler needs them, and two pieces of
reference semantics for the draft 1b hardware study.

See isa-v1.md. Decoding, executing and assembling instructions is Rust
(studies/v1_isa/isa): sim32.Machine32 runs the simulator, and the
assembler (heron.infra.asm) calls the encoders.
"""

M32 = 0xFFFFFFFF
RAM_SIZE = 0x100000
IO_BASE = 0xFFFFFF00
MEM_TOP = RAM_SIZE          # the linker places nothing above this (the assembler: isa/src/asm/)

RESET_VECTOR = 0x00
IRQ_VECTOR = 0x04
ILLEGAL_VECTOR = 0x08
SWI_VECTOR = 0x0C
DIV_VECTOR = 0x10
ADDR_VECTOR = 0x14


COND = ["EQ", "NE", "CS", "CC", "MI", "PL", "VS", "VC",
        "HI", "LS", "GE", "LT", "GT", "LE", "RA"]

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
# Shared disassembler pieces


def as_signed(v):
    """Interpret a 32-bit pattern as signed (so 0xFFFFFF00 counts as -256)."""
    if (1 << 31) <= v < (1 << 32):
        return v - (1 << 32)
    return v


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
