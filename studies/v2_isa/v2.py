"""ISA draft 2: 32-bit, 16-bit parcels of an opcode byte and a register byte.

See reports/0028-rfc-draft-2-isa.md and isa-v2.md. A parcel's opcode byte
comes first in memory, so it is the parcel's low byte; the register byte
holds `rd` in its high nibble and the mode's register `R` in its low one.
The modes are draft 1b's (studies/v1_isa/isa-v1b.md), with mode E,
`[r14 + 4R]`, a second slot mode, and two tables added to the special
mode. This is the disassembler's side; decoding and
executing is Rust (isa/src/decode.rs, insn.rs), and so is the encoder the
assembler uses (isa/src/asm.rs).
"""

NAME = "v2"
DESCRIPTION = "draft 2: 32-bit registers, 16-bit parcels of an opcode byte and a register byte"

WIDE = True                     # 32-bit: the tools disassemble it
M32 = 0xFFFFFFFF
RAM_SIZE = 0x100000
MEM_TOP = RAM_SIZE              # the linker places nothing above this
IO_BASE = 0xFFFFFF00
RESET_VECTOR = 0x00
IRQ_VECTOR = 0x04

COND = ["EQ", "NE", "CS", "CC", "MI", "PL", "VS", "VC",
        "HI", "LS", "GE", "LT", "GT", "LE", "RA"]
# rows with every mode as a column
EA_ROWS = {1: "MOV", 2: "ST", 3: "MOVS", 4: "ADD", 5: "SUB", 6: "CMP", 8: "AND", 9: "OR", 0xA: "XOR"}
TAGGED = {0x09: "TMOV", 0x0A: "TTST", 0x0B: "TADD", 0x0C: "TSUB", 0x0D: "TCMP"}
UNARY = ["NOT", "NEG", "INC", "DEC", "RLC", "RRC", "SWAP", "SXB", "SXH", "ZXB", "ZXH",
         "CLZ", "FFS", "POPC", "REV"]
ROW_E = ["ADC", "SBC", "BIC", "TST", "MULU", "MULS", "MULA", "DIVU", "DIVS", "DIVUL",
         "BIC", "TST", "MULU", "MULS", "MERGE"]
SHIFTS = ["LSL", "LSR", "ASR", "ROR"]
# LO is numbered after the kernel study's system registers, 0-8
SR_NAMES = {0: "flags", 1: "hi", 9: "lo"}
# the free cells, ILLEGAL, and CAS and the FPU escape, which aren't designed
FREE = {0x00, 0x03, 0x31, 0x3D, 0xC3, 0xC7, 0xCB, 0xCF, 0xEF, 0xF7, 0xF8, 0xF9, 0xFA, 0xFB,
        0xFF}

SIZE_NAME = {1: "byte ", 2: "half ", 4: ""}


def sext8(x):
    x &= 0xFF
    return x - 0x100 if x & 0x80 else x


def sext16(x):
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


def sext24(x):
    x &= 0xFFFFFF
    return x - 0x1000000 if x & 0x800000 else x


def R(n):
    return "sp" if n == 15 else f"r{n}"


def sym(v, symbols):
    if symbols and v in symbols:
        return symbols[v]
    return f"0x{v:X}"


def fmt_imm(v):
    """Canonical constant: signed decimal if it fits 16 bits, else hex."""
    v &= M32
    sv = v - (1 << 32) if v & 0x80000000 else v
    return f"#{sv}" if -32768 <= sv <= 32767 else f"#0x{v:X}"


# ==========================================================================
# Addressing modes


def ea_info(M, Rn, ext):
    """Decode a mode. Returns (operand, extra parcels) where operand is
    ('reg', r) | ('imm', value) | ('mem', base, disp, index, scale, size,
    timing kind), with base None for an absolute address and 'pc' for a
    PC-relative one (disp then the offset), or None for a mode that traps.
    Mode E, [r14 + 4R], is a word at r14 + 4R, as mode 4 is at sp + 4R.
    The special mode's tables are D, [abs24 + x*s], ('mem', None, address,
    x, s, size, 'absx'), and E, [pc + d24 + x*s], ('mem', 'pc', d24, x, s,
    size, 'pcx')."""
    def indexed(base, disp, e, tk):
        z = (e >> 8) & 3
        if z == 3:
            return None
        return ("mem", base, disp, e >> 12, 1 << ((e >> 10) & 3), (1, 2, 4)[z], tk)

    n = mode_size(M, Rn)
    if M == 0:
        return ("reg", Rn), n
    if M == 1:
        return ("imm", Rn), n
    if M == 0xD:
        return ("imm", (-(Rn + 1)) & M32), n
    if M == 5:
        return indexed(Rn, sext8(ext[0]), ext[0], "idx"), n
    if M in (4, 0xE):
        return ("mem", 15 if M == 4 else 14, 4 * Rn, None, 1, 4, "rd"), n
    simple = {2: (4, "r"), 3: (4, "rd"), 6: (4, "pi"), 7: (4, "pd"), 8: (1, "r"),
              9: (1, "rd"), 0xA: (1, "pi"), 0xB: (2, "r"), 0xC: (2, "rd")}
    if M in simple:
        size, tk = simple[M]
        return ("mem", Rn, sext16(ext[0]) if tk == "rd" else 0, None, 1, size, tk), n
    if M != 0xF:
        return None, n
    size3 = (4, 1, 2)
    if Rn == 0:
        return ("imm", sext16(ext[0]) & M32), n
    if Rn == 1:
        return ("imm", ext[0]), n
    if Rn == 2:
        return ("imm", ext[0] << 16), n
    if Rn == 3:
        return ("imm", ext[0] | (ext[1] << 16)), n
    if 4 <= Rn <= 6:
        return ("mem", None, sext16(ext[0]) & M32, None, 1, size3[Rn - 4], "abs"), n
    if 7 <= Rn <= 9:
        return ("mem", None, ext[0] | (ext[1] << 16), None, 1, size3[Rn - 7], "abs"), n
    if 0xA <= Rn <= 0xC:
        return ("mem", "pc", sext16(ext[0]), None, 1, size3[Rn - 0xA], "pc"), n
    if Rn in (0xD, 0xE):
        a = sext24(((ext[0] & 0xFF) << 16) | ext[1])
        if Rn == 0xD:
            return indexed(None, a, ext[0], "absx"), n
        return indexed("pc", a, ext[0], "pcx"), n
    return None, n


def mode_size(M, Rn):
    """Extra parcels a mode needs (from the first parcel alone)."""
    if M in (3, 5, 9, 0xC):
        return 1
    if M == 0xF:
        return 2 if Rn in (3, 7, 8, 9, 0xD, 0xE) else (1 if Rn <= 0xC else 0)
    return 0


def _ext_for(op, rb):
    """The extension parcels of an instruction, from its first parcel."""
    hi, lo = rb >> 4, rb & 15
    row, col = op >> 4, op & 15
    if op in (0x01, 0x02):
        return 1
    if 0x04 <= op <= 0x07:
        return mode_size((3, 4, 5, 0xF)[op - 4], lo)
    if op in (0x20, 0x21, 0x2D, 0xF0, 0xF1):
        return mode_size(hi, lo)
    if op in TAGGED or op in FREE:
        return 0
    if row in EA_ROWS:
        return mode_size(col, lo)
    if 0xEA <= op <= 0xED:
        return mode_size(0xF, lo)
    if op == 0xF2:
        return 1
    if op == 0xF3:
        return 2
    if (op == 0xFD and rb == 0x10) or (op == 0xFE and rb in (0x10, 0x11)):
        return 1
    return 0


def size_of(w):
    return 1 + _ext_for(w & 0xFF, w >> 8)


# ==========================================================================
# Disassembler


def dis_ea(M, Rn, ext, nxt, symbols, sized=True):
    """A mode as the assembler takes it; `sized=False` leaves out the size
    (LEA's operand)."""
    opnd, _ = ea_info(M, Rn, ext)
    if opnd is None:
        return None
    if opnd[0] == "reg":
        return R(Rn)
    if opnd[0] == "imm":
        return fmt_imm(opnd[1])
    _, base, disp, index, scale, size, tk = opnd
    sz = SIZE_NAME[size] if sized else ""
    if tk == "abs":
        return f"{sz}[{sym(disp & M32, symbols)}]"
    if tk == "pc":
        return f"{sz}[{sym((nxt + disp) & M32, symbols)}]"
    if tk == "pi":
        return f"{sz}[{R(base)}]+"
    if tk == "pd":
        return f"{sz}-[{R(base)}]"
    x = R(index) + (f"*{scale}" if scale != 1 else "") if index is not None else None
    if tk in ("r", "rd", "idx"):
        parts = R(base) + (f" + {x}" if x else "")
        if disp:
            parts += f" - {-disp}" if disp < 0 else f" + {disp}"
        return f"{sz}[{parts}]"
    if tk == "pcx":
        return f"{sz}[pc + {sym((nxt + disp) & M32, symbols)} + {x}]"
    if symbols and (disp & M32) in symbols:
        return f"{sz}[{symbols[disp & M32]} + {x}]"
    if scale == 1:
        # as [R + d16] prints, which this is when it fits
        return f"{sz}[{x} - {-disp}]" if disp < 0 else f"{sz}[{x} + {disp}]"
    return f"{sz}[{sym(disp & M32, symbols)} + {x}]"


def hex_parcels(ws):
    """An instruction's parcels in hex: the first as its two bytes in memory,
    opcode first, and the extension parcels, which carry data, as 16-bit
    values."""
    return " ".join([f"{ws[0] & 0xFF:02X} {ws[0] >> 8:02X}"] + [f"{w:04X}" for w in ws[1:]])


def _range(a, b):
    return f"{R(a)}-{R(b)}"


def disassemble(ws, pc=0, symbols=None):
    """The instruction at pc, whose parcels start with ws: (text, parcels)."""
    w = ws[0]
    ext = list(ws[1:]) + [0, 0]
    op, rb = w & 0xFF, w >> 8
    hi, lo = rb >> 4, rb & 15
    row, col = op >> 4, op & 15
    bad = (f".half 0x{w:04X} ; illegal", 1)
    n = size_of(w)
    nxt = (pc + 2 * n) & M32
    rr = f"{R(hi)}, {R(lo)}"
    if op in FREE:
        return bad
    if op in (0x01, 0x02):
        e = ext[0]
        if e & 0xFFF or e >> 12 < hi:
            return bad
        return f"{'LDM' if op == 1 else 'STM'} {R(lo)}, {_range(hi, e >> 12)}", 2
    if 0x04 <= op <= 0x07:
        M = (3, 4, 5, 0xF)[op - 4]
        opnd, _ = ea_info(M, lo, ext)
        if opnd is None or opnd[0] != "mem":
            return bad
        return f"LEA {R(hi)}, {dis_ea(M, lo, ext, nxt, symbols, sized=False)}", n
    if op == 0x08:
        return f"ADD.B4 {rr}", 1
    if op == 0x0E:
        if lo in (1, 9):
            return f"MF{SR_NAMES[lo].upper()} {R(hi)}", 1
        return f"MFSR {R(hi)}, {SR_NAMES.get(lo, lo)}", 1
    if op == 0x0F:
        if hi in (1, 9):
            return f"MT{SR_NAMES[hi].upper()} {R(lo)}", 1
        return f"MTSR {SR_NAMES.get(hi, hi)}, {R(lo)}", 1
    if op in TAGGED:
        return f"{TAGGED[op]} {rr}", 1
    if op in (0x20, 0x21, 0x2D):
        name = {0x20: "CLR", 0x21: "INC", 0x2D: "DEC"}[op]
        opnd, _ = ea_info(hi, lo, ext)
        if opnd is None or opnd[0] == "imm":
            return bad
        return f"{name} {dis_ea(hi, lo, ext, nxt, symbols)}", n
    if row in EA_ROWS:
        if row == 3 and col in (1, 0xD):
            return bad
        opnd, _ = ea_info(col, lo, ext)
        if opnd is None:
            return bad
        t = dis_ea(col, lo, ext, nxt, symbols)
        if row == 2:
            if opnd[0] != "mem":
                return bad
            if col == 7 and lo == 15:
                return f"PUSH {R(hi)}", 1
            return f"MOV {t}, {R(hi)}", n
        if row == 1 and col == 6 and lo == 15:
            return f"POP {R(hi)}", 1
        return f"{EA_ROWS[row]} {R(hi)}, {t}", n
    if row == 7:
        return f"{'MOV' if op < 0x78 else 'CMP'} {R(hi)}, #{(lo << 3) | (op & 7)}", 1
    if row == 0xB:
        target = (pc + 2 + 2 * sext8(rb)) & M32
        return f"{'BSR' if col == 15 else 'B' + COND[col]} {sym(target, symbols)}", 1
    if row == 0xC:
        name = SHIFTS[(op >> 2) & 3]
        if op & 3 == 2:
            return f"{name} {rr}", 1
        return f"{name} {R(hi)}, #{(lo << 1) | (op & 1)}", 1
    if row == 0xD:
        if col == 15:
            return (f"SET{COND[lo]} {R(hi)}", 1) if lo < 15 else bad
        # in place: one register, as it's written
        return f"{UNARY[col]} {R(hi) if hi == lo else rr}", 1
    if row == 0xE:
        if 0xA <= col <= 0xD:
            opnd, _ = ea_info(0xF, lo, ext)
            if opnd is None:
                return bad
            return f"{ROW_E[col]} {R(hi)}, {dis_ea(0xF, lo, ext, nxt, symbols)}", n
        return f"{ROW_E[col]} {rr}", 1
    # row F
    if op in (0xF0, 0xF1):
        opnd, _ = ea_info(hi, lo, ext)
        if opnd is None or (opnd[0] == "mem" and opnd[5] != 4):
            return bad
        return f"{'JMP' if op == 0xF0 else 'CALL'} {dis_ea(hi, lo, ext, nxt, symbols)}", n
    if op in (0xF2, 0xF3):
        if lo:
            return bad
        m = "CALL" if hi == 15 else ("JMP" if hi == 14 else "J" + COND[hi])
        if op == 0xF2:
            target = (pc + 4 + 2 * sext16(ext[0])) & M32
        else:
            target = (ext[0] | (ext[1] << 16)) & 0xFFFFFFFE
        return f"{m} {sym(target, symbols)}", n
    if op in (0xF4, 0xF5):
        if not hi <= lo <= 14:
            return bad
        return f"{'SAVE' if op == 0xF4 else 'RESTORE'} {_range(hi, lo)}", 1
    if op == 0xF6:
        return f"DBNZ {R(hi)}, {sym((pc + 2 - 2 * (lo + 1)) & M32, symbols)}", 1
    if op == 0xFC:
        return f"SWI #{rb}", 1
    if op == 0xFD:
        if rb == 0x10:
            e = ext[0]
            if e & 0xE0:
                return bad
            return f"MULFX {R(e >> 12)}, {R((e >> 8) & 15)}, #{e & 31}", 2
        return {0x00: ("RET", 1), 0xFD: ("NOP", 1)}.get(rb, bad)
    if op == 0xFE:
        if rb in (0x10, 0x11):
            e = ext[0]
            if e & 0xFF:
                return bad
            return f"{'MFUR' if rb == 0x10 else 'MTUR'} {R(e >> 12)}, {R((e >> 8) & 15)}", 2
        return {0: ("EI", 1), 1: ("DI", 1), 2: ("RTI", 1), 3: ("HALT", 1)}.get(rb, bad)
    return bad


MODE_CLASS = {"r": "[r]", "rd": "[r+d]", "abs": "[abs]", "pc": "[pc+d]", "idx": "[r+x]",
              "pi": "[r]+", "pd": "-[r]", "absx": "[abs+x]", "pcx": "[pc+x]"}


def mode_class(M, Rn, ext):
    """Short description of a mode, for statistics."""
    opnd, _ = ea_info(M, Rn, ext)
    if opnd is None:
        return "?"
    if opnd[0] == "reg":
        return "r"
    if opnd[0] == "imm":
        return "#q" if M in (1, 0xD) else ("#i32" if Rn == 3 else "#i16")
    name = {4: "[sp+n]", 0xE: "[r14+n]"}.get(M) or MODE_CLASS[opnd[6]]
    return {1: "b", 2: "h", 4: ""}[opnd[5]] + name


def kind(ws):
    """What the instruction is, for the instruction mix: the map's labels
    (ST, MVI, CMPI) with the mode's class."""
    w = ws[0]
    ext = list(ws[1:]) + [0, 0]
    op, rb = w & 0xFF, w >> 8
    hi, lo = rb >> 4, rb & 15
    row, col = op >> 4, op & 15
    if disassemble(ws)[0].startswith(".half"):
        return "illegal"
    if op in (0x01, 0x02):
        return "LDM" if op == 1 else "STM"
    if 0x04 <= op <= 0x07:
        return "LEA " + mode_class((3, 4, 5, 0xF)[op - 4], lo, ext)
    if op in TAGGED:
        return TAGGED[op]
    if op in (0x20, 0x21, 0x2D):
        return {0x20: "CLR", 0x21: "INC", 0x2D: "DEC"}[op] + " " + mode_class(hi, lo, ext)
    if row in EA_ROWS:
        return f"{EA_ROWS[row]} {mode_class(col, lo, ext)}"
    if row == 7:
        return "MVI" if op < 0x78 else "CMPI"
    if row == 0xB:
        return "BSR" if col == 15 else ("BRA" if col == 14 else "Bcc")
    if row == 0xC:
        return SHIFTS[(op >> 2) & 3] + (" reg" if op & 3 == 2 else "")
    if row == 0xD:
        return "SETcc" if col == 15 else UNARY[col]
    if row == 0xE:
        if 0xA <= col <= 0xD:
            return f"{ROW_E[col]} {mode_class(0xF, lo, ext)}"
        return ROW_E[col]
    if op in (0xF0, 0xF1):
        return f"{'JMP' if op == 0xF0 else 'CALL'} {mode_class(hi, lo, ext)}"
    if op in (0xF2, 0xF3):
        return "CALL" if hi == 15 else ("JMP" if hi == 14 else "Jcc")
    return disassemble(ws)[0].split()[0]
