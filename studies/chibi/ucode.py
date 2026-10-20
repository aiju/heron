"""Chibi Heron's microcode: the control word, the micro-assembler and the
routines for draft 2's plain machine.

The control store is addressed, with no microinstruction register, by

    {PAGE[1:0], N[3:0], OP[7:0], STEP[4:0]}           19 bits, 512K words

OP is the opcode byte, N a dispatch nibble (the register byte's high
nibble at decode; the low nibble or the index parcel's scale and size
after a dispatch), STEP a counter and PAGE says which kind of block runs:

    page 0   decode: N = d (rd, or the mode M of CLR, INC, DEC, JMP, CALL)
    page 1   N = s (the special mode's R, a quick constant, a shift count)
    page 2   N = the index parcel's bits 11-8, {scale, size}
    page 3   the interrupt entry, the exception entry and reset; the same
             block for every N and OP

Every (page, N, OP) has 32 steps. A routine's microinstructions are
placed from step 0; a jump goes to a step of the same block or, changing
PAGE (and loading N), to step 0 of another.

A cycle has two phases. In phase W, the first three ticks, while the
control store's outputs settle, the result register Y drives the D bus:
the register file writes it if the microinstruction before asked
(`wr`), and PC or MAR load it at the end of the phase if it asked
(`AX`). In phase R the microinstruction's own work happens: a source
(`DS`) drives D, the ALU computes D op L, the result goes into Y at the
cycle's end, the flags and L load. So a result written by one
microinstruction is in the register file, PC or MAR for the next.
"""

from collections import OrderedDict

# ---- the control word -------------------------------------------------

FIELDS = [
    ("DS", 3),      # the D bus's source in phase R
    ("SZ", 1),      # a memory access is a byte
    ("IMMF", 5),    # the immediate unit's format
    ("RS", 2),      # register read: K, d or s
    ("KR", 5),      # ... the register number when K (16-31: the temporaries)
    ("HR", 1),      # ... which half
    ("WS", 2),      # register write (of this result, in the next cycle): K, d, s
    ("KW", 5),
    ("HW", 1),
    ("WEN", 1),
    ("AOP", 5),     # ALU operation (A = D, B = L)
    ("SISEL", 2),   # the bit into bit 15 when the result shifts right
    ("RM", 2),      # the result: as is, shifted right, its low byte zero- or sign-extended
    ("FL", 5),      # flag operation
    ("LDL", 1),     # L <- D
    ("MOP", 3),     # memory: none, read at MAR, write at MAR, read at PC, fetch, PC on the bus
    ("AXP", 2),     # PC's half <- this result (in the next cycle's phase W)
    ("AXM", 2),     # MAR's half <- this result, or MAR + 2 (likewise)
    ("IROP", 2),    # the register byte: d + 1, s - 1, or s <- the index parcel's x
    ("NOP", 2),     # the dispatch nibble: <- s, <- MD[11:8]
    ("SEQ", 2),     # next, jump, end
    ("CND", 5),     # condition (bit 4: inverted)
    ("JT", 5),      # jump target step
    ("PT", 2),      # jump target page
    ("HALT", 1),    # the machine has stopped (for the simulations)
]
WORD_BITS = 72                  # nine 8-bit flash chips
ROMS = WORD_BITS // 8
_pos = OrderedDict()
_b = 0
for _n, _w in FIELDS:
    _pos[_n] = (_b, _w, 0)
    _b += _w
assert _b <= WORD_BITS, _b
USED_BITS = _b

# bits stored inverted, so that a word of all ones (an erased flash) does
# nothing harmful and the active-low enables are direct
INVERTED = {"LDL"}

ADDR_BITS = 19
CS_WORDS = 1 << ADDR_BITS
PAGES = 4
STEPS = 32


def addr(page, n, op, step):
    return page << 17 | n << 13 | op << 5 | step


# D bus sources
DS_NONE, DS_RF, DS_MEM, DS_IMM, DS_ADR, DS_PCH = range(6)
# register selects
SEL_K, SEL_D, SEL_S = range(3)
# shift-in sources
SI_0, SI_C, SI_D15, SI_CO = range(4)
# result multiplexer
RM_PASS, RM_SHR, RM_ZXB, RM_SXB = range(4)
# memory operations
MOP_NONE, MOP_RDM, MOP_WRM, MOP_RDP, MOP_FETCH, MOP_PCS = range(6)
# address register operations (deferred: at the next cycle's phase W)
AXP_NONE, AXP_LO, AXP_HI = range(3)
AXM_NONE, AXM_LO, AXM_HI, AXM_INC = range(4)
AX_PCLO, AX_PCHI, AX_MARLO, AX_MARHI, AX_MARINC = ("P", 1), ("P", 2), ("M", 1), ("M", 2), ("M", 3)
IR_NONE, IR_INCD, IR_LDX, IR_DECS = range(4)
N_HOLD, N_S, N_MDZ = range(3)
SEQ_NEXT, SEQ_JUMP, SEQ_END = range(3)

# ALU operations, A = D bus, B = L: (S3-S0, M, carry in), the carry one of
# '0', '1', 'C' (the flag) or 'IC' (the internal carry); 'ST?' picks the
# first form when ST is set, the second when it isn't
AOPS = OrderedDict([
    ("A", (0b1111, 1, "0")),
    ("B", (0b1010, 1, "0")),
    ("ADD", (0b1001, 0, "0")),
    ("ADDC", (0b1001, 0, "C")),
    ("ADDI", (0b1001, 0, "IC")),
    ("SUB", (0b0110, 0, "1")),
    ("SUBC", (0b0110, 0, "C")),
    ("SUBI", (0b0110, 0, "IC")),
    ("AND", (0b1011, 1, "0")),
    ("OR", (0b1110, 1, "0")),
    ("XOR", (0b0110, 1, "0")),
    ("BIC", (0b0111, 1, "0")),
    ("SHL", (0b1100, 0, "0")),
    ("SHLC", (0b1100, 0, "C")),
    ("SHLI", (0b1100, 0, "IC")),
    ("INC", (0b0000, 0, "1")),
    ("INCC", (0b0000, 0, "C")),
    ("INCI", (0b0000, 0, "IC")),
    ("DEC", (0b1111, 0, "0")),
    ("DECC", (0b1111, 0, "C")),
    ("DECI", (0b1111, 0, "IC")),
    ("EXT", ("ST?", "DECI", "INCI")),       # A + sign extension + IC
    ("ZERO", (0b0011, 1, "0")),
    ("ONES", (0b1100, 1, "0")),
    ("NOTA", (0b0000, 1, "0")),
    ("NOTB", (0b0101, 1, "0")),
    ("SEXT", ("ST?", "ONES", "ZERO")),      # ST's sign, all 16 bits
    ("ADDB1", (0b1001, 0, "1")),            # A + B + 1
    ("SUB1", (0b0110, 0, "0")),             # A - B - 1 = A + ~B
    ("EXTC", ("ST?", "DECC", "INCC")),      # A + sign extension + C
    ("EXTSC", ("ST?", "INCC", "DECC")),     # A - sign extension - borrow
])
# the codes, chosen (by annealing) so that the ALU control's 22V10 fits
AOP_CODE = {
    "A": 20, "B": 29, "ADD": 13, "ADDC": 18, "ADDI": 2, "SUB": 23, "SUBC": 19, "SUBI": 7,
    "AND": 28, "OR": 11, "XOR": 27, "BIC": 24, "SHL": 10, "SHLC": 8, "SHLI": 1, "INC": 14,
    "INCC": 12, "INCI": 6, "DEC": 15, "DECC": 16, "DECI": 3, "EXT": 5, "ZERO": 30, "ONES": 9,
    "NOTA": 25, "NOTB": 26, "SEXT": 21, "ADDB1": 22, "SUB1": 31, "EXTC": 4, "EXTSC": 17,
}
assert sorted(AOP_CODE) == sorted(AOPS) and len(set(AOP_CODE.values())) == len(AOPS)
AOP_NAME = {c: n for n, c in AOP_CODE.items()}


def aop_resolve(name, st):
    """(S, M, carry) for an ALU operation with the sign flag ST as it is."""
    v = AOPS[name]
    if v[0] == "ST?":
        return aop_resolve(v[1] if st else v[2], st)
    return v


# flag operations: what each sets, from the cycle's result (z: its 16 bits
# are zero; n15, n7: its bits 15 and 7; co: the ALU's carry out; f0: the
# bit a right shift moves out) and the operands' bits 15 (a15 = D, b15 = L)
FLOPS = [
    "NONE",
    "ADDLO",    # C <- co, Z <- z                     (the low half of an add or subtract)
    "ADDHI",    # C <- co, Z <- Z & z, N, V (add)      (its high half)
    "SUBHI",    # ..., V (subtract)
    "ADDHIZ",   # as ADDHI, with B's bit 15 taken as 0 (a zero-extended operand)
    "SUBHIZ",
    "ADCLO",    # C <- co, Z <- Z & z                 (ADC, SBC: Z sticky)
    "ICLO",     # IC <- co                            (address arithmetic)
    "ICLOZ",    # IC <- co, Z <- z                    (INC, DEC)
    "ICSTZ",    # IC <- co, ST <- z                   (DBNZ)
    "LOGLO",    # Z <- z
    "LOGHI",    # Z <- Z & z, N <- n15
    "NZ16",     # N <- n15, Z <- z
    "NZ8",      # N <- n7, Z <- z
    "SHR",      # C <- f0, V <- 0                     (a step of a right shift)
    "SHL",      # C <- co, V <- 0                     (a step of a left shift)
    "STN",      # ST <- n15
    "STZ",      # ST <- z
    "ICN", "ICZ", "ICC", "ICV", "ICI",     # IC <- N, Z, C, V, I (the flags word, bit by bit)
    "CNZ", "VNZ", "ZNZ", "NNZ", "INZ",     # C, V, Z, N, I <- not z (restoring it)
    "SETI", "CLRI",
    "SETINIT",  # reset is over
]
# the codes, chosen (by annealing) so that each flag's equations in the
# flags' 22V10 fit its macrocell
FL_CODE = {
    "NONE": 0, "ADDLO": 7, "ADDHI": 28, "SUBHI": 12, "ADDHIZ": 14, "SUBHIZ": 30, "ADCLO": 6,
    "ICLO": 2, "ICLOZ": 3, "ICSTZ": 19, "LOGLO": 1, "LOGHI": 4, "NZ16": 5, "NZ8": 21,
    "SHR": 13, "SHL": 15, "STN": 23, "STZ": 27, "ICN": 11, "ICZ": 8, "ICC": 9, "ICV": 10,
    "ICI": 18, "CNZ": 22, "VNZ": 29, "ZNZ": 17, "NNZ": 20, "INZ": 25, "SETI": 16, "CLRI": 24,
    "SETINIT": 26,
}
assert sorted(FL_CODE) == sorted(FLOPS) and len(set(FL_CODE.values())) == len(FLOPS)
FL_NAME = {c: n for n, c in FL_CODE.items()}

# conditions for SEQ_JUMP (CND bit 4 inverts)
CONDS = ["TRUE", "Z", "C", "N", "V", "HI", "LT", "LE", "IC", "ST", "INIT", "IRQP", "NE",
         "A0", "MISW", "I"]
COND_CODE = {n: i for i, n in enumerate(CONDS)}


def cond_value(name, f, a0, a1, ne):
    """A condition's value from the flags (dict), the address bus's bits 0
    and 1 and the register byte's d != s."""
    c = {"TRUE": 1, "Z": f["Z"], "C": f["C"], "N": f["N"], "V": f["V"],
         "HI": f["C"] & (1 - f["Z"]), "LT": f["N"] ^ f["V"],
         "LE": f["Z"] | (f["N"] ^ f["V"]), "IC": f["IC"], "ST": f["ST"], "INIT": f["INIT"],
         "IRQP": f["IRQP"], "NE": ne, "A0": a0, "MISW": a0 | a1, "I": f["I"]}
    return c[name]


# immediate formats: (low byte, high byte), each a function of the
# register byte's d and s (or a constant); 'Z5' drives only bits 7-5 of
# the low byte, as 0, beside PC's bits 20-16 (DS_PCH)
def _u7(k):
    return (lambda d, s: (s << 3 | k) & 0xFF, lambda d, s: 0)


IMMS = OrderedDict([
    ("ZERO", (lambda d, s: 0, lambda d, s: 0)),
    ("Q4", (lambda d, s: s, lambda d, s: 0)),
    ("NQ", (lambda d, s: 0xF0 | (~s & 15), lambda d, s: 0xFF)),
    ("SC4", (lambda d, s: s << 2, lambda d, s: 0)),
    ("B8", (lambda d, s: (d << 5 | s << 1) & 0xFF, lambda d, s: 0xFF if d & 8 else 0)),
    ("DB", (lambda d, s: 0xE0 | (~s & 15) << 1, lambda d, s: 0xFF)),
    ("SH0", (lambda d, s: s << 1, lambda d, s: 0)),
    ("SH1", (lambda d, s: s << 1 | 1, lambda d, s: 0)),
] + [(f"U7_{k}", _u7(k)) for k in range(8)] + [
    ("C1", (lambda d, s: 1, lambda d, s: 0)),
    ("C2", (lambda d, s: 2, lambda d, s: 0)),
    ("C4", (lambda d, s: 4, lambda d, s: 0)),
    ("C8", (lambda d, s: 8, lambda d, s: 0)),
    ("C16", (lambda d, s: 16, lambda d, s: 0)),
    ("C32", (lambda d, s: 32, lambda d, s: 0)),
    ("CM1", (lambda d, s: 0xFF, lambda d, s: 0xFF)),
    ("CM2", (lambda d, s: 0xFE, lambda d, s: 0xFF)),
    ("Z5", (None, lambda d, s: 0)),
    ("C6", (lambda d, s: 6, lambda d, s: 0)),
    ("V_SWI", (lambda d, s: 0x0C, lambda d, s: 0)),
    ("V_ADR", (lambda d, s: 0x14, lambda d, s: 0)),
    ("V_TAG", (lambda d, s: 0x18, lambda d, s: 0)),
    ("C8010", (lambda d, s: 0x10, lambda d, s: 0x80)),
    ("CFF", (lambda d, s: 0xFF, lambda d, s: 0)),
    ("C31", (lambda d, s: 31, lambda d, s: 0)),
])
IMM_CODE = {n: i for i, n in enumerate(IMMS)}
assert len(IMMS) <= 32, len(IMMS)
# vector constants that are also plain constants
IMM_ALIAS = {"V_IRQ": "C4", "V_ILL": "C8", "V_DIV": "C16"}


def imm_value(name, d, s, hi_only=False):
    lo, hi = IMMS[name]
    return (hi(d, s) << 8) | (0 if lo is None else lo(d, s))


# ---- registers ---------------------------------------------------------

class Reg:
    """A register reference: sel K with a number (0-15 the general
    registers, 16-31 the microcode's), or the register byte's d or s."""

    def __init__(self, sel, k=0):
        self.sel, self.k = sel, k

    def __repr__(self):
        return {SEL_K: f"k{self.k}", SEL_D: "d", SEL_S: "s"}[self.sel]


RD = Reg(SEL_D)
RSRC = Reg(SEL_S)


def G(n):
    return Reg(SEL_K, n)


def T(n):
    return Reg(SEL_K, 16 + n)


SP = G(15)
LINK = G(7)
# the microcode's temporaries
T_A, T_B, T_C, T_CNT = T(0), T(1), T(2), T(3)
T_Q, T_R = T(4), T(5)
T_RET, T_VEC, T_FW = T(8), T(9), T(10)


# ---- microinstructions -------------------------------------------------

def u(*parts, **kw):
    """One microinstruction from parts (dicts) and fields; conflicting
    values for a field are an error."""
    out = {}
    for p in list(parts) + [kw]:
        for k, v in p.items():
            if k in out and out[k] != v:
                raise ValueError(f"field {k}: {out[k]} and {v}")
            out[k] = v
    return out


def rd(reg, half=0):
    return {"DS": DS_RF, "RS": reg.sel, "KR": reg.k, "HR": half}


def wr(reg, half=0):
    return {"WEN": 1, "WS": reg.sel, "KW": reg.k, "HW": half}


def imm(name):
    name = IMM_ALIAS.get(name, name)
    return {"DS": DS_IMM, "IMMF": IMM_CODE[name]}


def mem(at="MAR", size=4):
    return {"DS": DS_MEM, "MOP": MOP_RDM if at == "MAR" else MOP_RDP, "SZ": int(size == 1)}


def store(size=4):
    return {"MOP": MOP_WRM, "SZ": int(size == 1)}


def alu(name, rm=RM_PASS, si=SI_0):
    return {"AOP": AOP_CODE[name], "RM": rm, "SISEL": si}


def fl(name):
    return {"FL": FL_CODE[name]}


def ax(code):
    return {"AXP" if code[0] == "P" else "AXM": code[1]}


def pcrb_lo():
    """PC's bits 15-0 on D (the address bus read back)."""
    return {"DS": DS_ADR, "MOP": MOP_PCS}


def pcrb_hi():
    """PC's bits 20-16 on D, the rest 0."""
    return {"DS": DS_PCH, "MOP": MOP_PCS, "IMMF": IMM_CODE["Z5"]}


LDL = {"LDL": 1}


def end():
    """Fetch the next instruction and decode it."""
    return {"MOP": MOP_FETCH, "SEQ": SEQ_END}


def jump(target, cond="TRUE", inv=False, page=None):
    """A jump to a label of this routine, or (page given) to step
    `target` of the block that page and the dispatch nibble select."""
    d = {"SEQ": SEQ_JUMP, "CND": COND_CODE[cond] | (16 if inv else 0), "_goto": target}
    if page is not None:
        d["_page"] = page
    return d


def label(name):
    return {"_label": name}


DEFAULTS = {name: 0 for name, _ in FIELDS}
DEFAULTS["AOP"] = AOP_CODE["A"]      # an ALU left alone passes D (no carry chain)


def pack(f):
    w = 0
    for name, (b, width, _) in _pos.items():
        v = f.get(name, DEFAULTS[name])
        if name in INVERTED:
            v ^= (1 << width) - 1
        assert 0 <= v < (1 << width), (name, v)
        w |= v << b
    return w


def unpack(w):
    out = {}
    for name, (b, width, _) in _pos.items():
        v = (w >> b) & ((1 << width) - 1)
        if name in INVERTED:
            v ^= (1 << width) - 1
        out[name] = v
    return out


# ---- placing routines --------------------------------------------------

def place(ops, page, name):
    """32 control words for one block from a routine: labels resolved,
    jumps within the page or to another page's step."""
    if len(ops) > STEPS:
        raise ValueError(f"{name}: {len(ops)} microinstructions (at most {STEPS})")
    labels = {}
    for i, op in enumerate(ops):
        if "_label" in op:
            labels[op["_label"]] = i
    words = []
    for i, op in enumerate(ops):
        f = {k: v for k, v in op.items() if not k.startswith("_")}
        if "_goto" in op:
            tgt = op["_goto"]
            if "_page" in op:
                f["PT"] = op["_page"]
                f["JT"] = tgt
            else:
                f["PT"] = page
                f["JT"] = labels[tgt] if isinstance(tgt, str) else tgt
        elif f.get("SEQ", 0) == SEQ_NEXT:
            f["PT"] = page
        words.append(f)
    while len(words) < STEPS:
        words.append(dict(HANG_FIELDS, JT=len(words), PT=page))
    return words


# an unused step: the machine stops there
HANG_FIELDS = {"HALT": 1, "SEQ": SEQ_JUMP, "CND": COND_CODE["TRUE"], "JT": 0}
