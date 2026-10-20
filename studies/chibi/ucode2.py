"""The two-halves machine's microcode: the control word, the
micro-assembler's helpers and the encodings (routines2.py has the
routines, rtl2.py the model, board2.py the netlist).

The control store is addressed as the first cut's (ucode.py),

    {PAGE[1:0], N[3:0], OP[7:0], STEP[4:0]}           19 bits, 512K words

with the same pages, and its word is 72 bits in nine flashes.

A microinstruction is a cycle of master-clock ticks (19.86 ns): phase F,
three ticks while the control store's outputs settle and the cycle
before's results are written back, then a low half of LEN ticks and,
if HLEN isn't 0, a high half of HLEN ticks. The low half does what a
first-cut microinstruction does with 16 bits; the high half does the same
to the high halves, so that one microinstruction is a 32-bit operation:

- a register read takes the other half (HR inverted), a write puts the
  high half's result in the other half (HW inverted);
- L is two latches, the low half's and the high half's: the ALU's B is
  the half's, LDL loads the half's;
- the ALU's carry in, for an arithmetic operation, is the low half's
  carry out (HC), whatever the operation's own;
- a memory access is the half's own: at MAR (which an AXM of INC has
  moved on by 2 at the low half's end) or at PC (moved on likewise by a
  read there); a fetch is the cycle's last half's;
- the immediate is the 32-bit value's high half;
- PC's and MAR's low halves load at the low half's end (AXP or AXM of
  LO), their high halves at the high half's;
- the flag operation is the low half's (FL_HIGH has the high half's).

HX changes the high half: ZERO and FILL give a result of 0 or of copies
of ST (a zero- or sign-extension of the low half's result) with nothing on
D and no memory access; IMMH puts the immediate unit's high half on D
(IMMF's) instead of the source, with no memory access (a value read in
the low half, sign-extended into L).

Phase F writes the cycle before's results: the low half's at tick 1,
the high half's at tick 2, each to its half of the register file (four
SRAMs, a pair for each half); PC and MAR loaded from the ALU at the
halves' ends, so they're there for the next cycle.

An access to the I/O space (A31 set) takes a half of five ticks
whatever LEN says, and the slow devices hold it longer (board2.SLOW).
"""

from collections import OrderedDict

from .ucode import (  # noqa: F401  (the encodings the two machines share)
    AOP_CODE, AOP_NAME, AOPS, MOP_FETCH, MOP_LDIRM, MOP_NONE, MOP_PCS, MOP_RDM, MOP_RDP,
    MOP_WRM, RM_PASS, RM_SHR, RM_SXB, RM_ZXB, SEL_D, SEL_K, SEL_S, SI_0, SI_C, SI_CO, SI_D15,
    Reg, G, T, RD, RSRC, SP, LINK, T_A, T_B, T_C, T_CNT, T_Q, T_R, T_RET, T_VEC, T_FW,
    aop_resolve, ADDR_BITS, CS_WORDS, PAGES, STEPS, addr,
)

FIELDS = [
    ("DS", 3),      # the D bus's source
    ("SZ", 1),      # a memory access is a byte
    ("IMMF", 5),    # the immediate unit's format (IMMS: a 32-bit value)
    ("RS", 2),      # register read: K, d or s
    ("KR", 5),
    ("HR", 1),      # ... the low half's half (the high half reads the other)
    ("WS", 2),      # register write (of this result, in the next cycle's phase F)
    ("KW", 5),
    ("HW", 1),
    ("WEN", 1),
    ("AOP", 5),     # ALU operation (A = D, B = L)
    ("SISEL", 2),   # the bit into bit 15 when the result shifts right
    ("RM", 2),      # the result: as is, shifted right, its low byte zero- or sign-extended
    ("FL", 5),      # flag operation
    ("LDL", 1),     # L's half <- D
    ("MOP", 3),     # memory: none, read at MAR, write at MAR, read at PC, fetch, PC on the bus
    ("AXP", 2),     # PC's half <- the ALU, at the half's end
    ("AXM", 2),     # MAR's half <- the ALU, or MAR + 2
    ("IRN", 3),     # the register byte and the dispatch nibble (IRN_*)
    ("SEQ", 2),     # next, jump, end, jump at a task point
    ("CND", 5),     # condition (bit 4: inverted)
    ("JT", 5),      # jump target step
    ("PT", 2),      # jump target page
    ("HALT", 1),    # the machine has stopped (for the simulations)
    ("LEN", 2),     # the low half's ticks, less 1
    ("HLEN", 2),    # the high half's ticks; 0: no high half
    ("HX", 2),      # the high half's variant (HX_*)
]
WORD_BITS = 72
ROMS = WORD_BITS // 8
_pos = OrderedDict()
_b = 0
for _n, _w in FIELDS:
    _pos[_n] = (_b, _w, 0)
    _b += _w
assert _b == WORD_BITS, _b
USED_BITS = _b
INVERTED = {"LDL"}
# the fields static timing analysis doesn't read: the cycle's lengths
# come from it, and the sequencer's jump target and HALT time nothing
UNTIMED = ("JT", "PT", "HALT", "LEN", "HLEN")

# D bus sources: FLW the flags word's bits (a 74HCT541), SWP the last
# half's result with its bytes swapped (two 74HCT574s, loaded at every
# half's end)
DS_NONE, DS_RF, DS_MEM, DS_IMM, DS_ADR, DS_PCH, DS_FLW, DS_SWP = range(8)
AXP_NONE, AXP_LO, AXP_HI = range(3)
AXM_NONE, AXM_LO, AXM_HI, AXM_INC = range(4)
AX_PCLO, AX_PCHI, AX_MARLO, AX_MARHI, AX_MARINC = ("P", 1), ("P", 2), ("M", 1), ("M", 2), ("M", 3)
# the register byte and the dispatch nibble: N <- s; s <- the index
# parcel's x and N <- its bits 11-8; d + 1; s - 1
# (coded so that the dispatch nibble's register reads two of the bits)
IRN_NONE, IRN_INCD, IRN_DECS, IRN_NS, IRN_IDX = 0, 1, 2, 4, 6
SEQ_NEXT, SEQ_JUMP, SEQ_END, SEQ_JUMPT = range(4)
HX_NAT, HX_ZERO, HX_FILL, HX_IMMH = range(4)

# flag operations, the low half's; FL_HIGH: what each does in a high half
FLOPS = [
    "NONE",
    "ADDLO",    # C <- co, Z <- z                (high half: ADDHI)
    "SUBLO",    # the same                       (SUBHI)
    "ADCLO",    # C <- co, Z <- Z & z            (ADDHI)
    "SBCLO",    # the same                       (SUBHI)
    "ICLO",     # IC <- co
    "ICLOZ",    # IC <- co, Z <- z               (LOGHI)
    "LOGLO",    # Z <- z                         (LOGHI)
    "NZ16",     # N <- n15, Z <- z
    "SHR",      # C <- f0, V <- 0
    "SHL",      # C <- co, V <- 0                (SHL)
    "STN",      # ST <- n15
    "STZ",      # ST <- z                        (STZ32: ST <- ST & z)
    "ICSTZ",    # IC <- co, ST <- z              (STZ32)
    "STF0",     # ST <- f0                       (a halfword address's misalignment)
    "STA4",     # ST <- f0 | f1                  (a word address's)
    "CNZ", "VNZ", "ZNZ", "NNZ", "INZ",          # C, V, Z, N, I <- not z
    "BNZ", "BINZ",                              # B, BI <- not z
    "SETI", "CLRI",
    "ENTRY",    # I <- 0, B <- B | BI            (an interrupt's or exception's entry)
    "SETINIT",  # reset is over
    "STC",      # ST <- C
]
FL_HIGH = {"ADDLO": "ADDHI", "SUBLO": "SUBHI", "ADCLO": "ADDHI", "SBCLO": "SUBHI",
           "ICLOZ": "LOGHI", "LOGLO": "LOGHI", "SHL": "SHL", "STZ": "STZ32", "ICSTZ": "STZ32"}
# the codes, chosen by annealing so that each flag's equations in U_FLG
# fit its macrocell
FL_CODE = {
    "NONE": 0, "ADDLO": 6, "SUBLO": 12, "ADCLO": 4, "SBCLO": 14, "ICLO": 5, "ICLOZ": 9,
    "LOGLO": 1, "NZ16": 29, "SHR": 21, "SHL": 20, "STN": 11, "STZ": 16, "ICSTZ": 7, "STF0":
    24, "STA4": 10, "CNZ": 15, "VNZ": 3, "ZNZ": 25, "NNZ": 27, "INZ": 2, "BNZ": 8, "BINZ":
    31, "SETI": 19, "CLRI": 23, "ENTRY": 22, "SETINIT": 17, "STC": 30
}
assert sorted(FL_CODE) == sorted(FLOPS) and len(set(FL_CODE.values())) == len(FLOPS)
FL_NAME = {c: n for n, c in FL_CODE.items()}
# the flags in U_SYS rather than U_FLG
SYS_FLOPS = ("BNZ", "BINZ", "ENTRY", "SETINIT")

# conditions for a jump (CND bit 4 inverts)
CONDS = ["TRUE", "Z", "C", "N", "V", "HI", "LT", "LE", "IC", "ST", "INIT", "IRQP", "NE",
         "A0", "ODT", "I"]
COND_CODE = {n: i for i, n in enumerate(CONDS)}


def cond_value(name, f, ne, odt=0):
    c = {"TRUE": 1, "Z": f["Z"], "C": f["C"], "N": f["N"], "V": f["V"],
         "HI": f["C"] & (1 - f["Z"]), "LT": f["N"] ^ f["V"],
         "LE": f["Z"] | (f["N"] ^ f["V"]), "IC": f["IC"], "ST": f["ST"], "INIT": f["INIT"],
         "IRQP": f["IRQP"], "NE": ne, "A0": 0, "ODT": odt, "I": f["I"]}
    return c[name]


# the immediates: 32-bit values, (low half, high half), each a function of
# the register byte (d, s); the high half may take ST, as the low half has
# left it (SXST: a value read in the low half, sign-extended). Z5's high
# half drives D15-D5 only (as 0: beside PC's bits 20-16 on D4-D0).
def _lo(f):
    return lambda d, s: f(d, s) & 0xFFFF


IMMS = OrderedDict([
    ("ZERO", (lambda d, s: 0, "0")),
    ("Q4", (lambda d, s: s, "0")),
    ("NQ", (lambda d, s: 0xFFF0 | (~s & 15), "1")),
    ("SC4", (lambda d, s: s << 2, "0")),
    ("B8", (lambda d, s: ((d << 5 | s << 1) & 0xFF) | (0xFF00 if d & 8 else 0), "d3")),
    ("DB", (lambda d, s: 0xFFE0 | (~s & 15) << 1, "1")),
    ("SH0", (lambda d, s: s << 1, "0")),
    ("SH1", (lambda d, s: s << 1 | 1, "0")),
] + [(f"U7_{k}", (lambda d, s, k=k: (s << 3 | k) & 0xFF, "0")) for k in range(8)] + [
    ("C1", (lambda d, s: 1, "0")),
    ("C2", (lambda d, s: 2, "0")),
    ("C4", (lambda d, s: 4, "0")),
    ("C8", (lambda d, s: 8, "0")),
    ("C16", (lambda d, s: 16, "0")),
    ("C32", (lambda d, s: 32, "0")),
    ("CM1", (lambda d, s: 0xFFFF, "1")),
    ("C6", (lambda d, s: 6, "0")),
    ("Z5", (None, "Z5")),
    ("V_SWI", (lambda d, s: 0x0C, "0")),
    ("V_ADR", (lambda d, s: 0x14, "0")),
    ("V_TAG", (lambda d, s: 0x18, "0")),
    ("IOIV", (lambda d, s: 0x0002, 0x8018)),      # the interrupt controller's vector
    ("C64", (lambda d, s: 64, "0")),
    ("C31", (lambda d, s: 31, "0")),
    ("SXST", (lambda d, s: 0, "st")),
])
IMM_CODE = {n: i for i, n in enumerate(IMMS)}
assert len(IMMS) <= 32, len(IMMS)
IMM_ALIAS = {"V_IRQ": "C4", "V_ILL": "C8", "V_DIV": "C16"}


def imm_value(name, d, s, half=0, st=0):
    """The immediate's half (16 bits)."""
    lo, hi = IMMS[name]
    if not half:
        return 0 if lo is None else lo(d, s)
    if isinstance(hi, int):
        return hi
    return {"0": 0, "1": 0xFFFF, "d3": 0xFFFF if d & 8 else 0, "st": 0xFFFF if st else 0,
            "Z5": 0}[hi]


# ---- microinstructions -------------------------------------------------

def u(*parts, **kw):
    out = {}
    for p in list(parts) + [kw]:
        for k, v in p.items():
            if k in out and out[k] != v:
                raise ValueError(f"field {k}: {out[k]} and {v}")
            out[k] = v
    return out


W = {"HLEN": 3}                 # a 32-bit operation: a high half (its length timed later)


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


def hx(name, immf=None):
    d = {"HX": {"ZERO": HX_ZERO, "FILL": HX_FILL, "IMMH": HX_IMMH}[name]}
    d.update(W)
    if immf is not None:
        d["IMMF"] = IMM_CODE[immf]
    return d


def pcrb():
    """PC on D, 32 bits: its bits 15-0 read back from the address bus in
    the low half, 20-16 (and zeros) in the high."""
    return dict({"DS": DS_ADR, "MOP": MOP_PCS, "IMMF": IMM_CODE["Z5"]}, **W)


def pcrb_lo():
    return {"DS": DS_ADR, "MOP": MOP_PCS}


LDL = {"LDL": 1}


def end():
    """Fetch the next instruction (in the cycle's last half) and decode it."""
    return {"MOP": MOP_FETCH, "SEQ": SEQ_END}


def jump(target, cond="TRUE", inv=False, page=None, task=False):
    d = {"SEQ": SEQ_JUMPT if task else SEQ_JUMP,
         "CND": COND_CODE[cond] | (16 if inv else 0), "_goto": target}
    if page is not None:
        d["_page"] = page
    return d


def label(name):
    return {"_label": name}


DEFAULTS = {name: 0 for name, _ in FIELDS}
DEFAULTS["AOP"] = AOP_CODE["A"]
DEFAULTS["LEN"] = 3                 # untimed: the longest


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


def untimed_mask():
    m = 0
    for name in UNTIMED:
        b, w, _ = _pos[name]
        m |= ((1 << w) - 1) << b
    return m


def validate(f, where):
    """The rules the hardware puts on a microinstruction."""
    two = f.get("HLEN", 0) != 0
    hxv = f.get("HX", 0)
    mop = f.get("MOP", 0)
    if not two:
        assert hxv == HX_NAT, f"{where}: HX without a high half"
        return
    if hxv == HX_NAT:
        assert f.get("RM", 0) == RM_PASS, f"{where}: a 32-bit operation's result shifted"
        if mop in (MOP_RDM, MOP_WRM):
            assert f.get("AXM", 0) == AXM_INC, f"{where}: a 32-bit access at MAR without INC"
    assert mop != MOP_LDIRM, f"{where}: LDIRM in a 32-bit operation"
    assert FL_NAME.get(f.get("FL", 0)) not in SYS_FLOPS, f"{where}: U_SYS's flags in a 32-bit operation"
    if mop == MOP_FETCH:
        assert not f.get("AXP", 0), f"{where}: a fetch with PC loading"
        assert f.get("DS", 0) != DS_MEM, f"{where}: a fetch and a read in a 32-bit operation"
    assert f.get("AXP", 0) != AXP_HI and f.get("AXM", 0) != AXM_HI, \
        f"{where}: a high half's AX in a 32-bit operation"


def place(ops, page, name):
    """32 control words for one block: labels resolved, jumps within the
    page or to another page's step."""
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
        validate(f, f"{name} step {i}")
        words.append(f)
    while len(words) < STEPS:
        words.append(dict(HANG_FIELDS, JT=len(words), PT=page))
    return words


HANG_FIELDS = {"HALT": 1, "SEQ": SEQ_JUMP, "CND": COND_CODE["TRUE"], "JT": 0}
