"""Reed's microassembler: microinstructions written by field, placed in
the control store, and the decode table, as images for the netlist's
parts (CTRL.U_CS0-4, ALU.U_CS0-3, MEM.U_CS0, CTRL.U_DT0-1).

A word is each board's fields (fields.py), its successor and its length:

  next  "decode"           the next instruction's entry (SEQ DECODE)
        ("jump", label)    JT (SEQ JUMP, CND NONE)
        ("brdec", label)   label if this word's predecessor loads PC (a
                           jump, or a branch taken), else decode (SEQ BRDEC)
  ticks the cycle's length, 5-8 (LEN): 6 where a fetch may happen (BFREE)
        or memory is read, by default

The successor and the length are the word's own; the hardware reads them
a cycle early (the direct fields), which is the assembler's business.

The pipeline the microcode is written for (ctrl.py): a word's direct
fields are read while the word before it executes, so a word's successor
is chosen then, and a decode (the next instruction's entry) happens while
the instruction's last word is being read. A branch's word (PCOP BRANCH,
TK) is followed by its tail, whose BRDEC sees the branch's FLUSH.

Fixed words: 0 reset, WAITD (2, a word that decodes again: the queue
filling), IVEC (4, an interrupt's entry; not written yet), and HALT and
UNIMPL, which jump to themselves (a run stops there: HALT's after two
more words, as the last instruction writes its result in the next cycle).
"""

from . import fields as F
from .ctrl import IVEC, WAITD

WORDS = 1 << F.ADDR_BITS
CTRL_DIRECT = ("JT", "SEQ", "CND", "LEN", "CSPARE")
# fields whose 0 isn't "nothing"
DEFAULTS = {"ALU": {"RAS": F.RAS["NONE"], "RBS": F.RBS["NONE"], "BIN": F.BIN["NONE"]}}


class Word:
    def __init__(self, label=None, ctrl=None, alu=None, mem=None, next="decode", ticks=None,
                 note=""):
        self.label = label
        self.f = {"CTRL": dict(ctrl or {}), "ALU": dict(alu or {}), "MEM": dict(mem or {})}
        self.next = next
        self.ticks = ticks
        self.note = note
        self.addr = None

    def get(self, board, name):
        return self.f[board].get(name, DEFAULTS.get(board, {}).get(name, 0))

    def length(self):
        if self.ticks is not None:
            return self.ticks
        memory = self.get("MEM", "MOP") == F.MOP["LOAD"]
        # an address computed in the ALU onto A for MAR: 6 (sta: r + d16)
        mar = self.get("MEM", "MARLD") and self.get("ALU", "AOUT") == F.AOUT["F"]
        return 6 if self.get("CTRL", "BFREE") or memory or mar else 5


class Program:
    """Words placed in the control store, by label."""

    def __init__(self):
        self.words = [None] * WORDS
        self.labels = {}
        self.free = 10

    def place(self, word, at=None):
        if at is None:
            while self.words[self.free] is not None:
                self.free += 1
            at = self.free
        if self.words[at] is not None:
            raise ValueError(f"µPC {at:#x} taken")
        word.addr = at
        self.words[at] = word
        if word.label:
            if word.label in self.labels:
                raise ValueError(f"label {word.label} twice")
            self.labels[word.label] = at
        return at

    def routine(self, *words):
        """Words in a row: each one's successor, unless given, the next."""
        for w, n in zip(words, words[1:]):
            if w.next == "next":
                if n.label is None:
                    n.label = f"_{id(n)}"
                w.next = ("jump", n.label)
        for w in words:
            self.place(w)
        return words[0].label

    def addr(self, label):
        return self.labels[label]

    def check(self):
        errors = []
        for w in self.words:
            if w is None:
                continue
            c = w.f["CTRL"]
            loads_pc = c.get("PCOP") == F.PCOP_LOAD or c.get("TK")
            if loads_pc and c.get("BFREE"):
                errors.append(f"{w.label or hex(w.addr)}: fetches in a word that may load PC")
            onto_b = [c.get("IMM", 0) != F.IMM["NONE"], w.get("MEM", "MOP") == F.MOP["LOAD"],
                      bool(w.get("ALU", "BOUT"))]
            if sum(onto_b) > 1:
                errors.append(f"{w.label or hex(w.addr)}: two drivers onto B")
            if c.get("BFREE") and any(onto_b):
                errors.append(f"{w.label or hex(w.addr)}: BFREE with B in use")
            if not 5 <= w.length() <= 8:
                errors.append(f"{w.label or hex(w.addr)}: {w.length()} ticks")
        if errors:
            raise ValueError("microcode:\n  " + "\n  ".join(errors))

    def fields(self, w):
        """{board: {field: value}} for a word, its successor resolved."""
        out = {b: {**DEFAULTS.get(b, {}), **w.f[b]} for b in w.f}
        nxt = w.next
        if nxt == "decode":
            out["CTRL"].update(SEQ=F.SEQ_DECODE, JT=0)
        elif nxt == "decode_noirq":
            out["CTRL"].update(SEQ=F.SEQ_DECODE_NOIRQ, JT=0)
        elif nxt[0] == "jump":
            out["CTRL"].update(SEQ=F.SEQ_JUMP, JT=self.addr(nxt[1]), CND=F.CND["NONE"])
        elif nxt[0] == "brdec":
            out["CTRL"].update(SEQ=F.SEQ_BRDEC, JT=self.addr(nxt[1]))
        else:
            raise ValueError(f"successor {nxt!r}")
        out["CTRL"]["LEN"] = w.length() - F.LEN_BASE
        return out

    def images(self):
        """{board: [word values by µPC]}"""
        out = {b: [0] * WORDS for b in F.SLICES}
        for a, w in enumerate(self.words):
            if w is None:
                continue
            for b, vals in self.fields(w).items():
                out[b][a] = F.pack(b, **vals)
        return out


# ---- the microcode ----------------------------------------------------------

K_T0, K_T1 = 30, 31            # the register file's scratch words
LINK = 7                       # calls leave the return address in r7

ALU_OPS = {1: ("PASSB", None, None), 4: ("ADD", "0", "NZCV"), 5: ("SUB", "OWN", "NZCV"),
           6: ("SUB", "OWN", "NZCV"), 8: ("AND", None, "NZ"), 9: ("OR", None, "NZ"),
           0xA: ("XOR", None, "NZ"), 3: ("PASSB", None, "NZ")}
ROW_NAME = {1: "MOV", 3: "MOVS", 4: "ADD", 5: "SUB", 6: "CMP", 8: "AND", 9: "OR", 0xA: "XOR"}


def alu_op(row, **extra):
    """The ALU's fields for a row's operation on OA (rd) and OB, its
    result to rd (but CMP's)."""
    aop, ci, fl = ALU_OPS[row]
    f = dict(AOP=F.AOP[aop], RAS=F.RAS["d"])
    if ci:
        f["CI"] = F.CI[ci]
    if fl:
        f["FL"] = F.FL[fl]
    if row != 6:
        f["WS"] = F.WS["d"]
    f.update(extra)
    return f


def build():
    p = Program()
    # reset: A = 0 (the ALU's ZERO onto A), PC and FPC from it, the queue
    # empty; then WAITD until the first instruction is in
    p.place(Word("reset", alu=dict(AOP=F.AOP["ZERO"], AOUT=F.AOUT["F"]),
                 ctrl=dict(PCOP=F.PCOP_LOAD), next=("jump", "waitd")), at=0)
    p.place(Word("waitd", ctrl=dict(BFREE=1), next="decode", note="decode again"), at=WAITD)
    # HALT: two words more, so that the last instruction's write is done
    p.place(Word("halt", next=("jump", "halt1")), at=6)
    p.place(Word("halt1", next=("jump", "halted")), at=8)
    p.place(Word("halted", next=("jump", "halted")), at=9)
    p.place(Word("unimpl", next=("jump", "unimpl")), at=7)

    # the EA rows' operations on each mode they have here
    for row in ROW_NAME:
        name = ROW_NAME[row]
        # mode 0: a register
        p.routine(Word(f"{name}.r", alu=alu_op(row, RBS=F.RBS["s"], BIN=F.BIN["RF"]), ctrl=dict(BFREE=1)))
        # modes 1 and D: #Rn, #-(Rn+1); F0, F1: #sext16, #zext16 (consumed)
        p.routine(Word(f"{name}.q", alu=alu_op(row, BIN=F.BIN["BUS"]), ctrl=dict(IMM=F.IMM["Q"])))
        p.routine(Word(f"{name}.nq", alu=alu_op(row, BIN=F.BIN["BUS"]), ctrl=dict(IMM=F.IMM["NQ"])))
        p.routine(Word(f"{name}.i16s", alu=alu_op(row, BIN=F.BIN["BUS"]),
                       ctrl=dict(IMM=F.IMM["PE_SX"], IQC=F.IQC_NEXT)))
        p.routine(Word(f"{name}.i16z", alu=alu_op(row, BIN=F.BIN["BUS"]),
                       ctrl=dict(IMM=F.IMM["PE_ZX"], IQC=F.IQC_NEXT)))
        # F3: #imm32 (H takes the low parcel, then H:PE)
        p.routine(Word(f"{name}.i32", ctrl=dict(IQC=F.IQC_H, BFREE=1), next="next"),
                  Word(alu=alu_op(row, BIN=F.BIN["BUS"]), ctrl=dict(IMM=F.IMM["H_PE"], IQC=F.IQC_NEXT)))
        # modes 2, 3, F4: a word at [Rn], [Rn + d16], [abs16] (MAR, then the load)
        load = Word(alu=alu_op(row, BIN=F.BIN["BUS"]), mem=dict(MOP=F.MOP["LOAD"], MSZ=F.MSZ["WORD"]),
                    ctrl=dict(DACC=1))
        p.routine(Word(f"{name}.[r]", alu=dict(RAS=F.RAS["s"], AOUT=F.AOUT["OA"]), mem=dict(MARLD=1),
                       next="next"), load)
        load2 = Word(alu=alu_op(row, BIN=F.BIN["BUS"]), mem=dict(MOP=F.MOP["LOAD"], MSZ=F.MSZ["WORD"]),
                     ctrl=dict(DACC=1))
        p.routine(Word(f"{name}.[r+d]", alu=dict(RAS=F.RAS["s"], AOP=F.AOP["ADD"], CI=F.CI["0"],
                                                 BIN=F.BIN["BUS"], AOUT=F.AOUT["F"]),
                       ctrl=dict(IMM=F.IMM["PE_SX"], IQC=F.IQC_NEXT), mem=dict(MARLD=1), next="next"),
                  load2)
        load3 = Word(alu=alu_op(row, BIN=F.BIN["BUS"]), mem=dict(MOP=F.MOP["LOAD"], MSZ=F.MSZ["WORD"]),
                     ctrl=dict(DACC=1))
        p.routine(Word(f"{name}.[abs]", alu=dict(AOP=F.AOP["PASSB"], BIN=F.BIN["BUS"], AOUT=F.AOUT["F"]),
                       ctrl=dict(IMM=F.IMM["PE_SX"], IQC=F.IQC_NEXT), mem=dict(MARLD=1), next="next"),
                  load3)
    # ST rd, [Rn] / [Rn + d16] / [abs16]: the address into MAR, then rd onto A
    store = dict(alu=dict(RAS=F.RAS["d"], AOUT=F.AOUT["OA"]), mem=dict(MOP=F.MOP["STORE"], MSZ=F.MSZ["WORD"]),
                 ctrl=dict(DACC=1))
    p.routine(Word("ST.[r]", alu=dict(RAS=F.RAS["s"], AOUT=F.AOUT["OA"]), mem=dict(MARLD=1), next="next"),
              Word(**store))
    p.routine(Word("ST.[r+d]", alu=dict(RAS=F.RAS["s"], AOP=F.AOP["ADD"], CI=F.CI["0"], BIN=F.BIN["BUS"],
                                        AOUT=F.AOUT["F"]),
                   ctrl=dict(IMM=F.IMM["PE_SX"], IQC=F.IQC_NEXT), mem=dict(MARLD=1), next="next"),
              Word(**store))
    p.routine(Word("ST.[abs]", alu=dict(AOP=F.AOP["PASSB"], BIN=F.BIN["BUS"], AOUT=F.AOUT["F"]),
                   ctrl=dict(IMM=F.IMM["PE_SX"], IQC=F.IQC_NEXT), mem=dict(MARLD=1), next="next"),
              Word(**store))
    # row 7: MOV rd, #q and CMP rd, #q (q: 7 bits, U7)
    p.routine(Word("MOV.u7", alu=alu_op(1, BIN=F.BIN["BUS"]), ctrl=dict(IMM=F.IMM["U7"])))
    p.routine(Word("CMP.u7", alu=alu_op(6, BIN=F.BIN["BUS"]), ctrl=dict(IMM=F.IMM["U7"])))
    # LSL rd, #1 and LSR rd, #1 (row C, by one): a bit a word
    p.routine(Word("LSL.1", alu=dict(RAS=F.RAS["d"], AOP=F.AOP["SHL"], CI=F.CI["0"], WS=F.WS["d"],
                                     FL=F.FL["NZCV"]), ctrl=dict(BFREE=1)))
    p.routine(Word("LSR.1", alu=dict(RAS=F.RAS["d"], AOP=F.AOP["PASSB"], BIN=F.BIN["SHIFT"], SI=F.SI["0"],
                                     WS=F.WS["d"], FL=F.FL["NZ"]), ctrl=dict(BFREE=1)))
    branches(p)
    p.check()
    return p


def branches(p):
    """The branches and calls (RFC 0049 14.4, the branch adder): a word
    that sends the target out and loads PC and FPC from it if the
    condition holds (TK), then the tail, which fetches and goes to WAITD if
    PC was loaded, else to the next instruction."""
    tail = dict(ctrl=dict(BFREE=1), next=("brdec", "waitd"))
    # Bcc, BRA (cc 14) and BSR's jump (cc 15): the adder's target
    p.routine(Word("Bcc", ctrl=dict(PCOP=F.PCOP_BRANCH, TK=1), next="next"), Word(**tail))
    # BSR: r7 = PC (the address after it), then as BRA
    p.routine(Word("BSR", alu=dict(AIN=1, AOP=F.AOP["PASSA"], WS=F.WS["K"], K=LINK), ctrl=dict(PCOP=F.PCOP_DRIVE),
                   next="next"),
              Word(ctrl=dict(PCOP=F.PCOP_BRANCH, TK=1), next="next"), Word(**tail))
    # JMP r / RET (JMP r7): Rn onto A, PC and FPC from it
    p.routine(Word("JMP.r", alu=dict(RAS=F.RAS["s"], AOUT=F.AOUT["OA"]), ctrl=dict(PCOP=F.PCOP_LOAD),
                   next="next"), Word(**tail))
    # Jcc / JMP / CALL disp16 (0xF2): PC + 4 + 2 x ext; PC is the address
    # after it, so T0 = 2 x ext, T1 = PC + T0, then T1 onto A if taken
    def jdisp(label, call):
        words = [Word(label, alu=dict(AOP=F.AOP["PASSB"], BIN=F.BIN["BUS"], WS=F.WS["K"], K=K_T0),
                      ctrl=dict(IMM=F.IMM["PE_SX"], IQC=F.IQC_NEXT), next="next"),
                 Word(alu=dict(RAS=F.RAS["K"], K=K_T0, AOP=F.AOP["SHL"], CI=F.CI["0"], WS=F.WS["K"]),
                      next="next"),
                 Word(alu=dict(AIN=1, RBS=F.RBS["K"], K=K_T0, BIN=F.BIN["RF"], AOP=F.AOP["ADD"], CI=F.CI["0"],
                               WS=F.WS["K"]), ctrl=dict(PCOP=F.PCOP_DRIVE), next="next")]
        # (WS K writes K_T0's address; the add's result goes to T0 too, as
        # T0's K is the one the word gives)
        if call:
            words.append(Word(alu=dict(AIN=1, AOP=F.AOP["PASSA"], WS=F.WS["K"], K=LINK),
                              ctrl=dict(PCOP=F.PCOP_DRIVE), next="next"))
        words += [Word(alu=dict(RAS=F.RAS["K"], K=K_T0, AOUT=F.AOUT["OA"]), ctrl=dict(TK=1), next="next"),
                  Word(**tail)]
        p.routine(*words)
    jdisp("J.d16", call=False)
    jdisp("CALL.d16", call=True)


# ---- the decode table ---------------------------------------------------------

def mode_size(M, Rn):
    if M in (3, 5, 9, 0xC):
        return 1
    if M == 0xF:
        if Rn in (0, 1, 2, 4, 5, 6, 0xA, 0xB, 0xC):
            return 1
        if Rn in (3, 7, 8, 9, 0xD, 0xE):
            return 2
    return 0


def entry(p, parcel):
    """(entry label, length in parcels) for an instruction's first parcel."""
    op, rb = parcel & 0xFF, parcel >> 8
    row, col = op >> 4, op & 15
    hi, lo = rb >> 4, rb & 15
    if row in ROW_NAME or row == 2:
        name = "ST" if row == 2 else ROW_NAME[row]
        n = 1 + mode_size(col, lo)
        modes = {0: "r", 1: "q", 0xD: "nq", 2: "[r]", 3: "[r+d]"}
        m = modes.get(col)
        if col == 0xF:
            m = {0: "i16s", 1: "i16z", 3: "i32", 4: "[abs]"}.get(lo)
        label = f"{name}.{m}"
        return (label if m and label in p.labels else "unimpl"), n
    if row == 7:
        return ("MOV.u7" if op < 0x78 else "CMP.u7"), 1
    if row == 0xB:
        return ("BSR" if col == 15 else "Bcc"), 1
    if row == 0xC and op & 3 != 2 and ((lo << 1) | (op & 1)) == 1 and (op >> 2) & 3 in (0, 1):
        return ("LSL.1" if (op >> 2) & 3 == 0 else "LSR.1"), 1
    if op == 0xF0 and hi == 0:
        return "JMP.r", 1
    if op == 0xF2 and lo == 0:
        return ("CALL.d16" if hi == 15 else "J.d16"), 2
    if op == 0xFE and rb == 3:
        return "halt", 1
    return "unimpl", 1


def decode_table(p):
    """Two parts' images: U_DT0 the entry's bits 7-0, U_DT1 bits 13-8 and
    the length (bits 7-6)."""
    lo, hi = bytearray(1 << 17), bytearray(1 << 17)
    for parcel in range(1 << 16):
        label, n = entry(p, parcel)
        a = p.addr(label)
        lo[parcel] = a & 0xFF
        hi[parcel] = (a >> 8) & 0x3F | (n & 3) << 6
    return bytes(lo), bytes(hi)


def images(p=None):
    """{chip reference in the machine: image} for every control-store part
    and the decode table."""
    p = p or build()
    out = {}
    for board, words in p.images().items():
        for k in range(F.PARTS[board]):
            img = bytearray(1 << 17)
            for a, w in enumerate(words):
                img[a] = (w >> (8 * k)) & 0xFF
            out[f"{board}.U_CS{k}"] = bytes(img)
    out["CTRL.U_DT0"], out["CTRL.U_DT1"] = decode_table(p)
    return out


def listing(p=None):
    p = p or build()
    lines = []
    for a, w in enumerate(p.words):
        if w is None:
            continue
        f = p.fields(w)
        parts = [f"{a:04x} {w.label or '':<14} {w.length()}t"]
        for b in ("CTRL", "ALU", "MEM"):
            parts.append(b + " " + " ".join(f"{k}={v}" for k, v in sorted(f[b].items()) if v))
        lines.append("  ".join(parts))
    return "\n".join(lines)
