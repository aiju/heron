"""Reed's microassembler and microcode: microinstructions written by field,
placed in the control store, and the decode table, as images for the
netlist's parts (CTRL.U_CS0-4, ALU.U_CS0-3, MEM.U_CS0, CTRL.U_DT0-1).

A word is each board's fields (fields.py), its successor and its length.
Fields are written as text, "AOP=ADD RAS=s BIN=BUS IMM=PE_SX IQC=NEXT":
a field's name says its board, a value is a code's name or a number.

  next  "decode"             the next instruction's entry (SEQ DECODE)
        "next"               the word after it in its routine
        ("jump", label)      JT (SEQ JUMP)
        ("if", cnd, label)   label's pair: label if CND's condition is
                             false, the word after it (placed at label's
                             address + 1) if true
        ("brdec", label)     label if this word's predecessor loads PC (a
                             jump, or a branch taken), else decode
  ticks the cycle's length, 5-8 (LEN): 6 where a fetch may happen (BFREE)
        or memory is read, by default

The hardware's rules the microcode keeps (ctrl.py, alu.py, mem.py):

- **A word's successor is chosen while the word before it executes,**
  from the flags as they are then: a condition can test flags set two
  words before the word that branches on it, not one. The executing
  word's TK (a branch) takes the flags as it executes.
- **One K a word:** both ports' K select is the one field, so a word can't
  read two of the microcode's registers (16-31) at once. MQ (load from B,
  drive onto B) is a second, B-side temporary.
- **Each extension parcel is consumed once** (IQC NEXT or H), as the queue
  releases it then; check() follows every path from every entry.
- **A word that may load PC doesn't fetch;** a fetch takes B, so a word
  that drives B doesn't either. Every word that may, sets BFREE.

The pipeline (ctrl.py): a decode happens while the instruction's last
word executes; a branch's word (PCOP BRANCH, TK) is followed by its tail,
whose BRDEC sees the branch's FLUSH.

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
BOARD_OF = {name: board for board in F.SLICES for name, _ in F.SLICES[board]}
CODES = {"RAS": F.RAS, "RBS": F.RBS, "WS": F.WS, "AOP": F.AOP, "CI": F.CI, "FL": F.FL, "BIN": F.BIN,
         "AOUT": F.AOUT, "SI": F.SI, "STOP": F.STOP, "NSZ": F.NSZ, "IMM": F.IMM, "MOP": F.MOP,
         "MSZ": F.MSZ, "MQ": F.MQ,
         "IQC": {"NONE": F.IQC_NONE, "NEXT": F.IQC_NEXT, "H": F.IQC_H},
         "PCOP": {"NONE": F.PCOP_NONE, "DRIVE": F.PCOP_DRIVE, "LOAD": F.PCOP_LOAD,
                  "BRANCH": F.PCOP_BRANCH},
         "IFL": {"HOLD": F.IFL_HOLD, "SET": F.IFL_SET, "CLEAR": F.IFL_CLEAR}}


def parse(text):
    """{board: {field: value}} from "FIELD=value ..."."""
    out = {"CTRL": {}, "ALU": {}, "MEM": {}}
    for tok in (text or "").split():
        name, _, val = tok.partition("=")
        board = BOARD_OF[name]
        codes = CODES.get(name)
        v = codes[val] if codes and val in codes else int(val, 0)
        if name in out[board] and out[board][name] != v:
            raise ValueError(f"{name} twice in {text!r} (one K a word: both ports and WS K share it)")
        out[board][name] = v
    return out


class Word:
    def __init__(self, label=None, fields="", next="decode", ticks=None, note=""):
        self.label = label
        self.f = parse(fields) if isinstance(fields, str) else fields
        self.next = next
        self.ticks = ticks
        self.note = note
        self.addr = None

    def get(self, board, name):
        return self.f[board].get(name, DEFAULTS.get(board, {}).get(name, 0))

    def drives_b(self):
        return (self.get("CTRL", "IMM") != F.IMM["NONE"] or self.get("MEM", "MOP") == F.MOP["LOAD"]
                or bool(self.get("ALU", "BOUT")) or self.get("MEM", "MQ") == F.MQ["DRIVE"])

    def may_load_pc(self):
        return self.get("CTRL", "PCOP") == F.PCOP_LOAD or bool(self.get("CTRL", "TK"))

    def length(self):
        if self.ticks is not None:
            return self.ticks
        memory = self.get("MEM", "MOP") == F.MOP["LOAD"]
        # an address computed in the ALU onto A for MAR: 6 (sta: r + d16)
        mar = self.get("MEM", "MARLD") and self.get("ALU", "AOUT") == F.AOUT["F"]
        return 6 if self.get("CTRL", "BFREE") or memory or mar else 5


def W(label=None, fields="", next="next", **kw):
    return Word(label, fields, next, **kw)


class Program:
    """Words placed in the control store, by label."""

    def __init__(self):
        self.words = [None] * WORDS
        self.labels = {}
        self.free = 16
        self.entries = {}          # first parcel's key -> (label, parcels)
        self._n = 0

    def _label(self, w):
        if w.label is None:
            self._n += 1
            w.label = f"_{self._n}"
        return w.label

    def place(self, word, at=None):
        if at is None:
            while self.words[self.free] is not None:
                self.free += 1
            at = self.free
        if self.words[at] is not None:
            raise ValueError(f"µPC {at:#x} taken")
        word.addr = at
        self.words[at] = word
        self._label(word)
        if word.label in self.labels:
            raise ValueError(f"label {word.label} twice")
        self.labels[word.label] = at
        return at

    def pair(self, false_word, true_word):
        """Two words at an even address and the next: a condition's targets."""
        a = self.free + (self.free & 1)
        while self.words[a] is not None or self.words[a + 1] is not None:
            a += 2
        self.place(false_word, a)
        self.place(true_word, a + 1)
        return false_word.label

    def routine(self, *words):
        """Words in a row: each one's successor, "next", the one after it.
        A word already placed (a pair's) is left where it is."""
        for w, n in zip(words, words[1:]):
            if w.next == "next":
                w.next = ("jump", self._label(n))
        for w in words:
            if w.next == "next":
                raise ValueError(f"{w.label}: the routine's last word has no successor")
            if w.addr is None:
                self.place(w)
        return words[0].label

    def addr(self, label):
        return self.labels[label]

    # ---- the checks ---------------------------------------------------------

    def check(self):
        errors = []
        for w in self.words:
            if w is None:
                continue
            name = w.label or hex(w.addr)
            if w.may_load_pc() and w.get("CTRL", "BFREE"):
                errors.append(f"{name}: fetches in a word that may load PC")
            onto_b = [w.get("CTRL", "IMM") != F.IMM["NONE"], w.get("MEM", "MOP") == F.MOP["LOAD"],
                      bool(w.get("ALU", "BOUT")), w.get("MEM", "MQ") == F.MQ["DRIVE"]]
            if sum(onto_b) > 1:
                errors.append(f"{name}: two drivers onto B")
            if w.get("CTRL", "BFREE") and any(onto_b):
                errors.append(f"{name}: BFREE with B in use")
            if not 5 <= w.length() <= 8:
                errors.append(f"{name}: {w.length()} ticks")
            nxt = w.next
            if isinstance(nxt, tuple) and nxt[0] == "if":
                a = self.addr(nxt[2])
                if a & 1 or self.words[a + 1] is None:
                    errors.append(f"{name}: {nxt[2]} isn't a pair's first")
        if errors:
            raise ValueError("microcode:\n  " + "\n  ".join(errors))

    def successors(self, w):
        nxt = w.next
        if nxt in ("decode", "decode_noirq"):
            return []
        if nxt[0] == "jump":
            return [self.words[self.addr(nxt[1])]]
        if nxt[0] == "if":
            a = self.addr(nxt[2])
            return [self.words[a], self.words[a + 1]]
        if nxt[0] == "brdec":
            return [self.words[self.addr(nxt[1])]]
        raise ValueError(nxt)

    def check_parcels(self, entry_parcels):
        """Every path from each entry consumes its extension parcels once
        (entry_parcels: {label: parcels})."""
        errors = []
        for label, n in entry_parcels.items():
            if label in ("unimpl", "halt"):
                continue
            seen = set()
            todo = [(self.words[self.addr(label)], 0)]
            while todo:
                w, used = todo.pop()
                if (w.addr, used) in seen:
                    continue
                seen.add((w.addr, used))
                if w.get("CTRL", "IQC") in (F.IQC_NEXT, F.IQC_H):
                    used += 1
                if used > n - 1:
                    errors.append(f"{label}: consumes more than its {n - 1} extension parcels at {w.label}")
                    break
                succ = self.successors(w)
                if w.next in ("decode", "decode_noirq") or (isinstance(w.next, tuple) and w.next[0] == "brdec"
                                                          and w.next[1] == "waitd"):
                    if used != n - 1:
                        errors.append(f"{label}: ends at {w.label} having consumed {used} of {n - 1}")
                        break
                    continue
                todo.extend((s, used) for s in succ if s.label not in ("unimpl", "halted", "halt", "halt1"))
        if errors:
            raise ValueError("parcels:\n  " + "\n  ".join(errors[:20]))

    # ---- images -------------------------------------------------------------

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
        elif nxt[0] == "if":
            out["CTRL"].update(SEQ=F.SEQ_JUMP, JT=self.addr(nxt[2]), CND=F.CND[nxt[1]])
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


def auto_bfree(p):
    """BFREE on every word that may fetch: B left free, no PC load, no data
    access."""
    for w in p.words:
        if w is None or w.drives_b() or w.may_load_pc() or w.get("CTRL", "DACC"):
            continue
        if w.get("MEM", "MOP") != F.MOP["NONE"] or w.get("MEM", "MQ") == F.MQ["LOAD"]:
            continue
        if w.get("ALU", "BIN") == F.BIN["BUS"]:
            continue
        w.f["CTRL"]["BFREE"] = 1


# ---- the microcode's registers ------------------------------------------------

LINK, SP, R14 = 7, 15, 14
# constants, made at reset (reset_constants): 13 of the 16 the K field
# reaches past the architectural registers
K_FF0000, K_ONE, K_FF, K_FFFF, K_80, K_8000, K_SIGN, K_M1 = 16, 17, 18, 19, 20, 21, 22, 23
K_0100, K_0200, K_0400, K_0800, K_1F = 24, 25, 26, 27, 28
# temporaries
T2, T0, T1 = 29, 30, 31
K_T0, K_T1 = T0, T1


def reset_constants(p, then):
    """The constants' words, from reset to `then`."""
    words = [W(None, f"AOP=ONES WS=K K={K_M1}"), W(None, f"AOP=PASSB BIN=BUS IMM=ONE WS=K K={K_ONE}")]

    def power(k, n):
        out = [W(None, f"AOP=PASSB BIN=BUS IMM=ONE WS=K K={k}")]
        out += [W(None, f"RAS=K K={k} AOP=SHL CI=0 WS=K") for _ in range(n)]
        return out
    words += power(K_FF, 8) + [W(None, f"RAS=K K={K_FF} AOP=DECA CI=0 WS=K")]
    words += power(K_FFFF, 16) + [W(None, f"RAS=K K={K_FFFF} AOP=DECA CI=0 WS=K")]
    words += power(K_80, 7) + power(K_8000, 15) + power(K_SIGN, 31)
    words += power(K_0100, 8) + power(K_0200, 9) + power(K_0400, 10) + power(K_0800, 11)
    words += power(K_1F, 5) + [W(None, f"RAS=K K={K_1F} AOP=DECA CI=0 WS=K")]
    # 0xFF0000: 0xFF shifted 16
    words += power(K_FF0000, 8) + [W(None, f"RAS=K K={K_FF0000} AOP=DECA CI=0 WS=K")]
    words += [W(None, f"RAS=K K={K_FF0000} AOP=SHL CI=0 WS=K") for _ in range(16)]
    words[-1].next = ("jump", then)
    return p.routine(*words)


# ---- operands -------------------------------------------------------------------

# (i: the index parcel's, MSZ INDEX)
SIZE = {"w": "WORD", "b": "BYTE", "h": "HALF", "i": "INDEX"}
# EA modes 0-E: (key, size) for those that aren't special
MODES = {0: ("r", "w"), 1: ("q", "w"), 2: ("[r]", "w"), 3: ("[r+d]", "w"), 4: ("[sp+n]", "w"),
         5: ("[r+x]", None), 6: ("[r]+", "w"), 7: ("-[r]", "w"), 8: ("[r]", "b"), 9: ("[r+d]", "b"),
         0xA: ("[r]+", "b"), 0xB: ("[r]", "h"), 0xC: ("[r+d]", "h"), 0xD: ("nq", "w"),
         0xE: ("[r14+n]", "w")}
# the special mode's R: (key, size)
SPECIAL = {0: ("#s16", "w"), 1: ("#z16", "w"), 2: ("#hi16", "w"), 3: ("#i32", "w"),
           4: ("[abs16]", "w"), 5: ("[abs16]", "b"), 6: ("[abs16]", "h"),
           7: ("[abs32]", "w"), 8: ("[abs32]", "b"), 9: ("[abs32]", "h"),
           0xA: ("[pc+d]", "w"), 0xB: ("[pc+d]", "b"), 0xC: ("[pc+d]", "h"),
           0xD: ("[abs24+x]", None), 0xE: ("[pc+d24+x]", None)}
CONSTANT = {"q", "nq", "#s16", "#z16", "#hi16", "#i32"}
INDEXED = {"[r+x]", "[abs24+x]", "[pc+d24+x]"}


def ext_parcels(key):
    return {"[r+d]": 1, "[r+x]": 1, "#s16": 1, "#z16": 1, "#hi16": 1, "#i32": 2, "[abs16]": 1,
            "[abs32]": 2, "[pc+d]": 1, "[abs24+x]": 2, "[pc+d24+x]": 2}.get(key, 0)


def address_words(key, size, reg="s"):
    """The words that put a memory operand's address into MAR (the mode's
    register in the register byte's `reg` nibble); not the indexed modes."""
    r = f"RAS={reg}"
    ws = f"WS={reg}"
    if key == "[r]":
        return [f"{r} AOUT=OA MARLD=1"]
    if key == "[r+d]":
        return [f"{r} AOP=ADD CI=0 BIN=BUS IMM=PE_SX IQC=NEXT AOUT=F MARLD=1"]
    if key == "[sp+n]":
        return [f"RAS=K K={SP} AOP=ADD CI=0 BIN=BUS IMM=R4 AOUT=F MARLD=1"]
    if key == "[r14+n]":
        return [f"RAS=K K={R14} AOP=ADD CI=0 BIN=BUS IMM=R4 AOUT=F MARLD=1"]
    if key == "[r]+":
        step = "FOUR" if size == "w" else "ONE"
        return [f"{r} AOUT=OA AOP=ADD CI=0 BIN=BUS IMM={step} {ws} MARLD=1"]
    if key == "-[r]":
        return [f"{r} AOP=SUB CI=OWN BIN=BUS IMM=FOUR AOUT=F {ws} MARLD=1"]
    if key == "[abs16]":
        return ["AOP=PASSB BIN=BUS IMM=PE_SX IQC=NEXT AOUT=F MARLD=1"]
    if key == "[abs32]":
        return ["IQC=H", "AOP=PASSB BIN=BUS IMM=H_PE IQC=NEXT AOUT=F MARLD=1"]
    if key == "[pc+d]":
        return [f"AIN=1 PCOP=DRIVE AOP=ADD CI=0 BIN=BUS IMM=PE_SX IQC=NEXT WS=K K={T0}",
                f"RAS=K K={T0} AOUT=OA MARLD=1"]
    raise ValueError(key)


def constant_src(key):
    """(words before, the source's fields on OB) for a constant."""
    return {"q": ([], "BIN=BUS IMM=Q"), "nq": ([], "BIN=BUS IMM=NQ"),
            "#s16": ([], "BIN=BUS IMM=PE_SX IQC=NEXT"), "#z16": ([], "BIN=BUS IMM=PE_ZX IQC=NEXT"),
            "#hi16": ([], "BIN=BUS IMM=PE_HI IQC=NEXT"),
            "#i32": (["IQC=H"], "BIN=BUS IMM=H_PE IQC=NEXT")}[key]


def load_src(size):
    return f"BIN=BUS MOP=LOAD MSZ={SIZE[size]} DACC=1"




# ---- the indexed modes ------------------------------------------------------------

PE = "BIN=BUS IMM=PE_ZX"
TRAP = "unimpl"


def trap_word():
    return W(None, "", next=("jump", TRAP))


def decisions(p, ops, tests, final):
    """Words for `ops` (field strings) in a row, of which the first
    len(tests) set ST to the bit that tests[i] = (name, trap) names (an
    AND with STOP C32: its carry out is "A & B isn't 0", and N, Z, C and V
    stay); test i decides at the word two after it (its successor is chosen while
    the word before it executes). A decision duplicates the words after
    it: final(state) gives the first word to go on to, state {name: bit}.
    trap(state) True sends a path to unimpl. Returns the first word."""
    at = {i + 2: (name, trap) for i, (name, trap) in enumerate(tests)}
    if len(ops) < len(tests) + 2:
        ops = ops + [""] * (len(tests) + 2 - len(ops))

    def build(pos, state):
        if pos == len(ops):
            return final(state)
        w = W(None, ops[pos])
        if pos in at:
            name, trap = at[pos]
            succ = {}
            for bit in (1, 0):
                st = {**state, name: bit}
                succ[bit] = trap_word() if trap and trap(st) else build(pos + 1, st)
                if succ[bit].addr is None and succ[bit] is not None and succ[bit].label is None:
                    pass
            # (ST: the tested bit, set by the AND's carry out: STOP C32)
            w.next = ("if", "ST", p.pair(succ[0], succ[1]))
        else:
            n = build(pos + 1, state)
            w.next = ("jump", p._label(n))
            if n.addr is None:
                p.place(n)
        return w
    first = build(0, {})
    p.place(first)
    return first


def size_of(state):
    return {0: "b", 1: "h", 2: "w"}[state["z0"] | state["z1"] << 1]


def indexed_rx(p, label, dest, finals, sized):
    """[R + x*s + d8]: T1 = x << s (s's bits tested on ST, the flags
    staying, deciding two words later), T1 += R, then T1 + D8 (the
    parcel's displacement, sign-extended, on B) into dest. Sized, the
    access takes the parcel's size itself (MSZ INDEX, z on the IZ lines):
    finals["i"]() follows, and consumes the parcel (PE is the parcel
    until then); unsized, the sum consumes it and finals["w"]()."""
    a1 = W(label, f"RAS=K K={K_0400} AOP=AND {PE} STOP=C32")                  # s0
    a2 = W(None, f"RAS=K K={K_0800} AOP=AND {PE} STOP=C32")                   # s1
    a3 = W(None, f"RBS=x BIN=RF AOP=PASSB WS=K K={T1}")                       # T1 = x; s0 decides
    a4_1 = W(None, f"RAS=K K={T1} AOP=SHL CI=0 WS=K")
    a4_0 = W(None, "")
    b1 = W(None, f"RAS=K K={T1} AOP=SHL CI=0 WS=K")
    b2 = W(None, f"RAS=K K={T1} AOP=SHL CI=0 WS=K")
    tail = finals["i" if sized else "w"]()
    j2 = W(None, f"RAS=K K={T1} AOP=ADD CI=0 BIN=BUS IMM=D8 {dest}" + ("" if sized else " IQC=NEXT"),
           next=("jump", p._label(tail[0])))
    j1 = W(None, f"RAS=K K={T1} AOP=ADD CI=0 RBS=s BIN=RF WS=K", next=("jump", p._label(j2)))
    p.routine(*tail)
    p.place(j2)
    a4_1.next = a4_0.next = ("if", "ST", p.pair(W(None, "", next=("jump", p._label(j1))), b1))
    p.place(j1)
    b1.next, b2.next = ("jump", p._label(b2)), ("jump", j1.label)
    p.place(b2)
    a3.next = ("if", "ST", p.pair(a4_0, a4_1))
    a1.next, a2.next = ("jump", p._label(a2)), ("jump", p._label(a3))
    p.place(a1), p.place(a2), p.place(a3)
    return label


def indexed(p, label, kind, dest, finals, sized=True):
    """An indexed operand's address (kind "[r+x]", "[abs24+x]" or
    "[pc+d24+x]") into dest ("AOUT=F MARLD=1" for MAR, "WS=d" for LEA):
    T1 = x << s, T0 the displacement or address, then their sum (with R or
    PC) with MQ as the B-side temporary; the parcel's bits tested on ST, so
    that the flags stay, the index parcel (and the second
    parcel) consumed. Then finals[size]() (a routine, size "b", "h" or
    "w" from the parcel's z; z = 3 traps), or finals["w"]() unsized.
    The index parcel at PE: x (bits 15-12), s (11-10), z (9-8), d8 (7-0);
    for abs24 and d24, a23-16 in the low byte and the next parcel a15-0.
    A negative abs24 or d24 traps for now (unimpl)."""
    if kind == "[r+x]":
        return indexed_rx(p, label, dest, finals, sized)
    # T1 = x << s: s0 and s1 tested, decided two words later
    a1 = W(label, f"RAS=K K={K_0400} AOP=AND {PE} STOP=C32")
    a2 = W(None, f"RAS=K K={K_0800} AOP=AND {PE} STOP=C32")
    a3 = W(None, f"RBS=x BIN=RF AOP=PASSB WS=K K={T1}")
    a4_1 = W(None, f"RAS=K K={T1} AOP=SHL CI=0 WS=K")
    a4_0 = W(None, "")
    b1 = W(None, f"RAS=K K={T1} AOP=SHL CI=0 WS=K")
    b2 = W(None, f"RAS=K K={T1} AOP=SHL CI=0 WS=K")
    # the displacement and the sum
    if kind == "[r+x]":
        disp = [f"AOP=PASSB {PE} WS=K K={T0}",
                f"RBS=K K={K_FF} BIN=RF BOUT=1 MQ=LOAD",
                f"RAS=K K={T0} AOP=AND BIN=BUS MQ=DRIVE WS=K",
                f"RBS=K K={K_80} BIN=RF BOUT=1 MQ=LOAD",
                f"RAS=K K={T0} AOP=XOR BIN=BUS MQ=DRIVE WS=K",
                f"RAS=K K={T0} AOP=SUB CI=OWN BIN=BUS MQ=DRIVE WS=K",
                f"RAS=K K={T1} AOP=ADD CI=0 RBS=s BIN=RF WS=K",
                f"RBS=K K={T1} BIN=RF BOUT=1 MQ=LOAD",
                f"RAS=K K={T0} AOP=ADD CI=0 BIN=BUS MQ=DRIVE IQC=NEXT {dest}"]
    else:
        disp = [f"AOP=PASSB BIN=BUS IMM=PE_HI IQC=NEXT WS=K K={T0}",
                f"RBS=K K={K_FF0000} BIN=RF BOUT=1 MQ=LOAD",
                f"RAS=K K={T0} AOP=AND BIN=BUS MQ=DRIVE WS=K",
                f"RAS=K K={T0} AOP=ADD CI=0 BIN=BUS IMM=PE_ZX IQC=NEXT WS=K"]
        if kind == "[pc+d24+x]":
            disp.append(f"AIN=1 PCOP=DRIVE AOP=ADD CI=0 RBS=K K={T0} BIN=RF WS=K")
        disp += [f"RBS=K K={T1} BIN=RF BOUT=1 MQ=LOAD",
                 f"RAS=K K={T0} AOP=ADD CI=0 BIN=BUS MQ=DRIVE {dest}"]
    tests, ops = [], []
    if sized:
        ops += [f"RAS=K K={K_0100} AOP=AND {PE} STOP=C32", f"RAS=K K={K_0200} AOP=AND {PE} STOP=C32"]
        tests += [("z0", None), ("z1", lambda st: st["z0"] and st["z1"])]
    if kind != "[r+x]":
        ops.append(f"RAS=K K={K_80} AOP=AND {PE} STOP=C32")
        tests.append(("neg", lambda st: st["neg"]))
    ops += disp
    built = {}

    def final(state):
        size = size_of(state) if sized else "w"
        if size not in built:
            ws = finals[size]()
            p.routine(*ws)
            built[size] = ws[0]
        return built[size]
    join = decisions(p, ops, tests, final)
    a4_1.next = a4_0.next = ("if", "ST", p.pair(W(None, "", next=("jump", join.label)), b1))
    b1.next, b2.next = ("jump", p._label(b2)), ("jump", join.label)
    p.place(b2)
    a3.next = ("if", "ST", p.pair(a4_0, a4_1))
    a1.next, a2.next = ("jump", p._label(a2)), ("jump", p._label(a3))
    p.place(a1), p.place(a2), p.place(a3)
    return label


# ---- the EA rows ------------------------------------------------------------------

ROWS = {1: "MOV", 3: "MOVS", 4: "ADD", 5: "SUB", 6: "CMP", 8: "AND", 9: "OR", 0xA: "XOR"}


def row_op(row, size="w"):
    """The ALU's fields for a row's operation on OA (rd) and OB."""
    name = ROWS[row] if isinstance(row, int) else row
    if name == "MOV":
        return "AOP=PASSB WS=d"
    if name == "MOVS":
        return "AOP=PASSB WS=d FL=NZ" + ("" if size == "w" else " NSZ=SZ")
    if name == "ADD":
        return "RAS=d AOP=ADD CI=0 FL=NZCV WS=d"
    if name in ("SUB", "CMP"):
        return "RAS=d AOP=SUB CI=OWN FL=NZCV" + (" WS=d" if name == "SUB" else "")
    if name == "BIC":
        return "RAS=d AOP=BIC FL=NZ WS=d"
    if name == "TST":
        return "RAS=d AOP=AND FL=NZ"
    return f"RAS=d AOP={name} FL=NZ WS=d"


def operand_routine(p, label, key, size, op):
    """An operation on a source operand: its address or constant's words,
    then the operation (op(size): fields) with the operand on OB."""
    if key == "r":
        p.routine(W(label, f"{op('w')} RBS=s BIN=RF", next="decode"))
        return label
    if key in INDEXED:
        return indexed(p, label, key, "AOUT=F MARLD=1",
                       {s_: (lambda s_=s_: [W(None, f"{op(s_)} {load_src(s_)}" + (" IQC=NEXT" if s_ == "i" else ""),
                                              next="decode")])
                        for s_ in "bhwi"})
    if key in CONSTANT:
        pre, src = constant_src(key)
        words = [W(None, f) for f in pre] + [W(None, f"{op('w')} {src}", next="decode")]
    else:
        words = [W(None, f) for f in address_words(key, size)]
        words.append(W(None, f"{op(size)} {load_src(size)}", next="decode"))
    words[0].label = label
    p.routine(*words)
    return label


def modes(memory_only=False, no_constants=False):
    """[(col, R or None, key, size)] for the EA modes and the special mode."""
    out = []
    for col, (key, size) in MODES.items():
        if (memory_only or no_constants) and key in CONSTANT:
            continue
        if memory_only and key == "r":
            continue
        out.append((col, None, key, size))
    for R, (key, size) in SPECIAL.items():
        if (memory_only or no_constants) and key in CONSTANT:
            continue
        out.append((0xF, R, key, size))
    return out


def ea_rows(p, entries):
    for row, name in ROWS.items():
        for col, R, key, size in modes(no_constants=(name == "MOVS")):
            label = f"{name}.{col:X}" + (f"{R:X}" if R is not None else "")
            operand_routine(p, label, key, size, lambda s_, row=row: row_op(row, s_))
            entries[(row << 4 | col, None, R)] = (label, 1 + ext_parcels(key))
    # row 7: MOV rd, #u7 and CMP rd, #u7
    p.routine(W("MVI", "AOP=PASSB BIN=BUS IMM=U7 WS=d", next="decode"))
    p.routine(W("CMPI", "RAS=d AOP=SUB CI=OWN BIN=BUS IMM=U7 FL=NZCV", next="decode"))
    for op in range(0x70, 0x80):
        entries[(op, None, None)] = ("MVI" if op < 0x78 else "CMPI", 1)
    # BIC and TST: a register, or the special mode's operands
    for opc, name, spec in ((0xE2, "BIC", 0xEA), (0xE3, "TST", 0xEB)):
        p.routine(W(f"{name}.r", f"{row_op(name)} RBS=s BIN=RF", next="decode"))
        entries[(opc, None, None)] = (f"{name}.r", 1)
        for R, (key, size) in SPECIAL.items():
            label = f"{name}.F{R:X}"
            operand_routine(p, label, key, size, lambda s_, name=name: row_op(name, s_))
            entries[(spec, None, R)] = (label, 1 + ext_parcels(key))


# ---- stores, CLR, INC, DEC ----------------------------------------------------------------

def store_routine(p, label, key, size, data):
    """A store of `data` (fields that put it onto A) to a memory operand."""
    st = f"{data} MOP=STORE DACC=1"
    if key in INDEXED:
        return indexed(p, label, key, "AOUT=F MARLD=1",
                       {s_: (lambda s_=s_: [W(None, f"{st} MSZ={SIZE[s_]}" + (" IQC=NEXT" if s_ == "i" else ""),
                                              next="decode")]) for s_ in "bhwi"})
    words = [W(None, f) for f in address_words(key, size)]
    words.append(W(None, f"{st} MSZ={SIZE[size]}", next="decode"))
    words[0].label = label
    p.routine(*words)
    return label


def rmw_routine(p, label, key, size, delta):
    """INC or DEC of a memory operand: the load and the change into T0 (the
    flags at the operand's size), then the store."""
    step = "AOP=INCA CI=OWN" if delta > 0 else "AOP=DECA CI=0"

    def tail(s_):
        return [W(None, f"AOP=PASSB {load_src(s_)} WS=K K={T0}"),
                W(None, f"RAS=K K={T0} {step} FL=NZ NSZ=SZ MSZ={SIZE[s_]} WS=K"),
                W(None, f"RAS=K K={T0} AOUT=OA MOP=STORE MSZ={SIZE[s_]} DACC=1"
                        + (" IQC=NEXT" if s_ == "i" else ""), next="decode")]
    if key in INDEXED:
        return indexed(p, label, key, "AOUT=F MARLD=1", {s_: (lambda s_=s_: tail(s_)) for s_ in "bhwi"})
    words = [W(None, f) for f in address_words(key, size)] + tail(size)
    words[0].label = label
    p.routine(*words)
    return label


def stores(p, entries):
    # row 2: MOV dst, rd (the data in the register byte's high nibble, the
    # mode's R in its low); 20, 21 and 2D are CLR, INC and DEC
    for col, R, key, size in modes(memory_only=True):
        opc = 0x20 | col
        if opc in (0x20, 0x21, 0x2D):
            continue
        label = f"ST.{col:X}" + (f"{R:X}" if R is not None else "")
        store_routine(p, label, key, size, "RAS=d AOUT=OA")
        entries[(opc, None, R)] = (label, 1 + ext_parcels(key))
    # CLR, INC, DEC ea: the mode M in the high nibble, R in the low
    for opc, name in ((0x20, "CLR"), (0x21, "INC"), (0x2D, "DEC")):
        for col, R, key, size in modes(no_constants=True):
            label = f"{name}.{col:X}" + (f"{R:X}" if R is not None else "")
            if key == "r":
                f = {"CLR": "AOP=ZERO WS=s", "INC": "RAS=s AOP=INCA CI=OWN FL=NZ WS=s",
                     "DEC": "RAS=s AOP=DECA CI=0 FL=NZ WS=s"}[name]
                p.routine(W(label, f, next="decode"))
            elif name == "CLR":
                store_routine(p, label, key, size, "AOP=ZERO AOUT=F")
            else:
                rmw_routine(p, label, key, size, 1 if name == "INC" else -1)
            entries[(opc, col, R)] = (label, 1 + ext_parcels(key))


# ---- LEA ---------------------------------------------------------------------------

def lea(p, entries):
    one = {3: "RAS=s AOP=ADD CI=0 BIN=BUS IMM=PE_SX IQC=NEXT WS=d",
           4: f"RAS=K K={SP} AOP=ADD CI=0 BIN=BUS IMM=R4 WS=d",
           0xE: f"RAS=K K={R14} AOP=ADD CI=0 BIN=BUS IMM=R4 WS=d"}
    for col, f in one.items():
        p.routine(W(f"LEA.{col:X}", f, next="decode"))
        entries[(col, None, None)] = (f"LEA.{col:X}", 1 + ext_parcels(MODES[col][0]))

    def nop():
        return [W(None, "", next="decode")]
    indexed(p, "LEA.5", "[r+x]", "WS=d", {"w": nop}, sized=False)
    entries[(0x05, None, None)] = ("LEA.5", 2)
    spec = {4: ["AOP=PASSB BIN=BUS IMM=PE_SX IQC=NEXT WS=d"],
            7: ["IQC=H", "AOP=PASSB BIN=BUS IMM=H_PE IQC=NEXT WS=d"],
            0xA: ["AIN=1 PCOP=DRIVE AOP=ADD CI=0 BIN=BUS IMM=PE_SX IQC=NEXT WS=d"]}
    for R, fs in spec.items():
        for r in (R, R + 1, R + 2):
            label = f"LEA.F{r:X}"
            ws = [W(None, f) for f in fs]
            ws[-1].next = "decode"
            ws[0].label = label
            p.routine(*ws)
            entries[(0x0F, None, r)] = (label, 1 + ext_parcels(SPECIAL[r][0]))
    for R, kind in ((0xD, "[abs24+x]"), (0xE, "[pc+d24+x]")):
        indexed(p, f"LEA.F{R:X}", kind, "WS=d", {"w": nop}, sized=False)
        entries[(0x0F, None, R)] = (f"LEA.F{R:X}", 3)


# ---- the unary row, SETcc ---------------------------------------------------------------

def unary(p, entries):
    one = {0xD0: ("NOT", "RAS=s AOP=NOTA FL=NZ WS=d"),
           0xD2: ("INCr", "RAS=s AOP=INCA CI=OWN FL=NZ WS=d"),
           0xD3: ("DECr", "RAS=s AOP=DECA CI=0 FL=NZ WS=d"),
           0xD4: ("RLC", "RAS=s AOP=SHL CI=C FL=SH WS=d"),
           0xD5: ("RRC", "RAS=s BIN=SHIFT SI=C AOP=PASSB FL=SH WS=d"),
           0xD9: ("ZXB", f"RAS=K K={K_FF} RBS=s BIN=RF AOP=AND FL=NZ WS=d"),
           0xDA: ("ZXH", f"RAS=K K={K_FFFF} RBS=s BIN=RF AOP=AND FL=NZ WS=d")}
    for opc, (name, f) in one.items():
        p.routine(W(name, f, next="decode"))
        entries[(opc, None, None)] = (name, 1)
    # NEG: ~rs + 1 (C: rs was 0; V: rs was the most negative)
    p.routine(W("NEG", "RAS=s AOP=NOTA WS=d"),
              W(None, "RAS=d AOP=INCA CI=OWN BIN=BUS IMM=ZERO FL=NZCV WS=d", next="decode"))
    entries[(0xD1, None, None)] = ("NEG", 1)
    # SWAP: sixteen rotations
    ws = [W("SWAP", "RAS=s BIN=SHIFT SI=ROT AOP=PASSB WS=d")]
    ws += [W(None, "RAS=d BIN=SHIFT SI=ROT AOP=PASSB WS=d") for _ in range(14)]
    ws.append(W(None, "RAS=d BIN=SHIFT SI=ROT AOP=PASSB FL=NZ WS=d", next="decode"))
    p.routine(*ws)
    entries[(0xD6, None, None)] = ("SWAP", 1)
    # SXB, SXH: (x & mask ^ sign) - sign
    for opc, name, mask, sign in ((0xD7, "SXB", K_FF, K_80), (0xD8, "SXH", K_FFFF, K_8000)):
        p.routine(W(name, f"RAS=K K={mask} RBS=s BIN=RF AOP=AND WS=d"),
                  W(None, f"RAS=d RBS=K K={sign} BIN=RF AOP=XOR WS=d"),
                  W(None, f"RAS=d RBS=K K={sign} BIN=RF AOP=SUB CI=OWN FL=NZ WS=d", next="decode"))
        entries[(opc, None, None)] = (name, 1)
    # SETcc rd (cc in the low nibble): rd = 0, then the condition's flags
    # tested one at a time (they don't change meanwhile), rd = 1 if it holds
    trees = {0: ("Z", 0, 1), 1: ("Z", 1, 0), 2: ("C", 0, 1), 3: ("C", 1, 0), 4: ("N", 0, 1),
             5: ("N", 1, 0), 6: ("V", 0, 1), 7: ("V", 1, 0),
             8: ("C", 0, ("Z", 1, 0)), 9: ("C", 1, ("Z", 0, 1)),
             0xA: ("N", ("V", 1, 0), ("V", 0, 1)), 0xB: ("N", ("V", 0, 1), ("V", 1, 0)),
             0xC: ("Z", ("N", ("V", 1, 0), ("V", 0, 1)), 0),
             0xD: ("Z", ("N", ("V", 0, 1), ("V", 1, 0)), 1), 0xE: 1}

    def node(t):
        if t == 1:
            return W(None, "AOP=PASSB BIN=BUS IMM=ONE WS=d", next="decode")
        if t == 0:
            return W(None, "", next="decode")
        flag, f, tr = t
        return W(None, "", next=("if", flag, p.pair(node(f), node(tr))))
    for cc, t in trees.items():
        label = f"SET.{cc:X}"
        root = node(t)
        p.place(root)
        p.place(W(label, "AOP=ZERO WS=d", next=("jump", root.label)))
        entries[(0xDF, None, cc)] = (label, 1)


# ---- shifts ----------------------------------------------------------------------------

SHIFT_WORD = {"LSL": "RAS=d AOP=SHL CI=0 WS=d", "LSR": "RAS=d BIN=SHIFT SI=0 AOP=PASSB WS=d",
              "ASR": "RAS=d BIN=SHIFT SI=SIGN AOP=PASSB WS=d", "ROR": "RAS=d BIN=SHIFT SI=ROT AOP=PASSB WS=d"}


def shifts(p, entries):
    for k, name in enumerate(("LSL", "LSR", "ASR", "ROR")):
        sh = SHIFT_WORD[name]
        # by n, 0-31: n words, the last setting the flags (n's bit 0 the
        # opcode's, bits 4-1 the register byte's low nibble)
        for n in range(32):
            label = f"{name}.{n}"
            if n == 0:
                p.routine(W(label, "RAS=d AOP=PASSA FL=NZ", next="decode"))
            else:
                ws = [W(None, sh) for _ in range(n - 1)] + [W(None, f"{sh} FL=SH", next="decode")]
                ws[0].label = label
                p.routine(*ws)
            entries[(0xC0 | k << 2 | (n & 1), None, n >> 1)] = (label, 1)
        # by rs & 31: rs into MQ, then a 32-way tree on MQ0, a bit a level,
        # into the shift by n's words above. A node's choice is made while
        # the word before it executes: MQ's load and the first shift bring
        # bit 0 to MQ0 for the root, and the words before levels 1-4 shift
        # on (7 words before the n shifts, against the loop's 2n + 2)
        label = f"{name}.r"

        def tree(level, bits, name=name):
            if level == 5:
                return W(None, "", next=("jump", f"{name}.{bits}"))
            lo, hi = tree(level + 1, bits), tree(level + 1, bits | 1 << level)
            return W(None, "MQ=SHIFT" if level < 3 else "", next=("if", "MQ0", p.pair(lo, hi)))
        root = tree(0, 0)
        p.place(root)
        p.routine(W(label, "RBS=s BIN=RF BOUT=1 MQ=LOAD"), W(None, "MQ=SHIFT", next=("jump", root.label)))
        entries[(0xC2 | k << 2, None, None)] = (label, 1)


# ---- multiply and divide ------------------------------------------------------------------

def mul_loop(src):
    """32 steps of MQ's multiply: rd (the high half) = MQSTEP(rd, src), then
    rd >> 1 with C in at the top, MQ shifted with QIN (F's bit 0) in."""
    out = []
    for _ in range(32):
        out.append(W(None, f"RAS=d AOP=MQSTEP CI=0 {src} BIN=RF FL=NZCV WS=d"))
        out.append(W(None, "RAS=d BIN=SHIFT SI=C AOP=PASSB WS=d MQ=SHIFT"))
    return out


def cv_words(p, nz, overflow):
    """C = V = overflow (1 or 0), then N and Z from rd (nz)."""
    if overflow:
        w = W(None, f"RAS=K K={K_SIGN} RBS=K BIN=RF AOP=ADD CI=0 FL=NZCV")
    else:
        w = W(None, "RAS=d AOP=ADD CI=0 BIN=BUS IMM=ZERO FL=NZCV")
    w.next = ("jump", nz.label)
    return w


def multiply(p, entries):
    for opc, spec, name in ((0xE4, 0xEC, "MULU"), (0xE5, 0xED, "MULS")):
        for R in [None] + list(SPECIAL):
            if R is not None and SPECIAL[R][0] in INDEXED:
                continue
            label = f"{name}." + ("r" if R is None else f"F{R:X}")
            if R is None:
                # (rd may be rs: the source into T0 before rd is cleared)
                src, pre = f"RBS=K K={T0}", [W(None, f"RBS=s BIN=RF AOP=PASSB WS=K K={T0}")]
            else:
                key, size = SPECIAL[R]
                src = f"RBS=K K={T0}"
                if key in CONSTANT:
                    cpre, csrc = constant_src(key)
                    pre = [W(None, f) for f in cpre] + [W(None, f"AOP=PASSB {csrc} WS=K K={T0}")]
                else:
                    pre = [W(None, f) for f in address_words(key, size)]
                    pre.append(W(None, f"AOP=PASSB {load_src(size)} WS=K K={T0}"))
            # T2 = rd (the multiplier, kept for MULS), MQ = T2 and rd = 0
            words = pre + [W(None, f"RAS=d AOP=PASSA WS=K K={T2}"),
                           W(None, f"RBS=K K={T2} BIN=RF BOUT=1 MQ=LOAD AOP=ZERO WS=d")]
            words += mul_loop(src)
            nz = W(None, "RAS=d AOP=PASSA FL=NZ", next="decode")
            p.place(nz)
            if name == "MULS":
                # the signed high half: hi -= (rd < 0 ? src : 0) + (src < 0 ? rd : 0)
                words += [W(None, f"RAS=K K={T2} AOP=PASSA FL=NZ"),             # N: rd < 0
                          W(None, f"{src} BIN=RF AOP=PASSB FL=NZ")]              # N: src < 0
                after = W(None, "")

                def second():
                    return W(None, "", next=("if", "N", p.pair(
                        W(None, "", next=("jump", p._label(after))),
                        W(None, f"RAS=d RBS=K K={T2} BIN=RF AOP=SUB CI=OWN WS=d", next=("jump", p._label(after))))))
                skip = second()
                skip.f = parse("")
                fix = second()
                fix.f = parse(f"RAS=d {src} BIN=RF AOP=SUB CI=OWN WS=d")
                words.append(W(None, "", next=("if", "N", p.pair(skip, fix))))
                p.place(after)
                end = [W(None, "RAS=d AOP=PASSA FL=NZ WS=K K=0"),             # r0 = hi; Z: hi = 0
                       W(None, "AOP=PASSB BIN=BUS MQ=DRIVE WS=d FL=NZ")]       # rd = lo; N: lo < 0
                # overflow unless hi is lo's sign: decided on hi's Z, then lo's N;
                # lo < 0 with hi != 0 needs hi = -1: INCA hi, Z
                minus1 = W(None, "RAS=K K=0 AOP=INCA CI=OWN FL=NZ")
                m2 = W(None, "")
                m3 = W(None, "", next=("if", "Z", p.pair(cv_words(p, nz, 1), cv_words(p, nz, 0))))
                minus1.next, m2.next = ("jump", p._label(m2)), ("jump", p._label(m3))
                p.place(m2), p.place(m3)
                hiz = W(None, "", next=("if", "N", p.pair(cv_words(p, nz, 0), cv_words(p, nz, 1))))
                hinz = W(None, "", next=("if", "N", p.pair(cv_words(p, nz, 1), minus1)))
                end.append(W(None, "", next=("if", "Z", p.pair(hinz, hiz))))
                after.next = ("jump", p._label(end[0]))
                p.routine(*end)
                words[-1].label = words[-1].label or None
                words[0].label = label
                p.routine(*words)
            else:
                end = [W(None, "RAS=d AOP=PASSA FL=NZ WS=K K=0"),
                       W(None, "AOP=PASSB BIN=BUS MQ=DRIVE WS=d"),
                       W(None, "", next=("if", "Z", p.pair(cv_words(p, nz, 1), cv_words(p, nz, 0))))]
                words[0].label = label
                p.routine(*(words + end))
            if R is None:
                entries[(opc, None, None)] = (label, 1)
            else:
                entries[(spec, None, R)] = (label, 1 + ext_parcels(SPECIAL[R][0]))


def div_bits(p, dsrc, after):
    """The 32 bits of the restoring divide, the divisor from dsrc (fields
    that put it on OB): T1 holds the dividend, shifting out at the top as
    the quotient comes in at the bottom; T0 the remainder. Each bit: T0 =
    T0 << 1 | C (the dividend's top bit), T0 -= d (C: no borrow, the
    quotient's bit), T1 = T1 << 1 | C (the quotient's bit in, the next top
    bit out), and, decided on the subtraction's C two words on, T0 += d if
    it borrowed. Returns the first bit's first word; `after` follows."""
    nxt = after
    for i in reversed(range(32)):
        d2 = W(None, f"RAS=K K={T0} AOP=SHL CI=C WS=K")
        d3 = W(None, f"RAS=K K={T0} {dsrc} AOP=SUB CI=OWN FL=NZCV WS=K")
        d4 = W(None, f"RAS=K K={T1} AOP=SHL CI=C FL=NZCV WS=K")
        restore = W(None, f"RAS=K K={T0} {dsrc} AOP=ADD CI=0 WS=K", next=("jump", p._label(nxt)))
        d5 = W(None, "", next=("if", "C", p.pair(restore, W(None, "", next=("jump", p._label(nxt))))))
        p.place(d5)
        d4.next = ("jump", d5.label)
        p.routine(d2, d3, d4)
        nxt = d2
    return nxt


def negate(k):
    """T(k) = -T(k): two words."""
    return [W(None, f"RAS=K K={k} AOP=NOTA WS=K"), W(None, f"RAS=K K={k} AOP=INCA CI=OWN WS=K")]


def divide(p, entries):
    """DIVU rd, rs and DIVS rd, rs (div_bits); r0 = the remainder through MQ
    at the end (one K a word). A zero divisor traps (unimpl, for now).
    DIVS divides the magnitudes, the divisor in MQ (port B can't reach a
    temporary while the remainder takes K), then gives the quotient the
    operands' signs' XOR (T2) and the remainder the dividend's; -2^31 by
    -1 sets V (C stays 0)."""
    # DIVU
    end = [W(None, f"RBS=K K={T0} BIN=RF BOUT=1 MQ=LOAD"),
           W(None, "AOP=PASSB BIN=BUS MQ=DRIVE WS=K K=0"),
           W(None, f"RAS=K K={T1} AOP=PASSA WS=d"),
           W(None, "RAS=d AOP=ADD CI=0 BIN=BUS IMM=ZERO FL=NZCV"),
           W(None, "RAS=d AOP=PASSA FL=NZ", next="decode")]
    p.routine(*end)
    loop = div_bits(p, "RBS=s BIN=RF", end[0])
    first = [W("DIVU.r", "RBS=s BIN=RF AOP=PASSB FL=NZ"),                  # Z: rs = 0
             W(None, f"RAS=d AOP=PASSA WS=K K={T1}"),
             W(None, f"AOP=ZERO WS=K K={T0}"),
             W(None, f"RAS=K K={T1} AOP=SHL CI=0 FL=NZCV WS=K")]          # the first top bit out
    first[2].next = ("if", "Z", p.pair(W(None, "", next=("jump", p._label(first[3]))), trap_word()))
    first[3].next = ("jump", loop.label)
    p.place(first[3])
    p.routine(*first[:3])
    entries[(0xE7, None, None)] = ("DIVU.r", 1)
    # DIVS: the end first
    nz = W(None, "RAS=d AOP=PASSA FL=NZ", next="decode")
    p.place(nz)
    clear = lambda: cv_words(p, nz, 0)
    # V without C: 0 - 0x80000000 (T0, the remainder, is 0 when it overflows)
    ov = [W(None, f"RBS=K K={K_SIGN} BIN=RF BOUT=1 MQ=LOAD"),
          W(None, f"RAS=K K={T0} AOP=SUB CI=OWN BIN=BUS MQ=DRIVE FL=NZCV", next=("jump", nz.label))]
    f6 = W(None, "", next=("if", "N", p.pair(ov[0], clear())))               # T2's N: no overflow
    p.routine(*ov)
    fin = [W(None, f"RBS=K K={T0} BIN=RF BOUT=1 MQ=LOAD"),
           W(None, "AOP=PASSB BIN=BUS MQ=DRIVE WS=K K=0"),                   # r0 = the remainder
           W(None, f"RAS=K K={T1} AOP=PASSA WS=d FL=NZ"),                    # rd = q; N: q's
           W(None, f"RAS=K K={T2} AOP=PASSA FL=NZ"),                         # N: the quotient's sign
           W(None, "", next=("if", "N", p.pair(clear(), f6)))]              # q < 0 with T2 >= 0: V
    p.routine(*fin)

    def rem_sign():
        """Decided on the dividend's N (E2's): the remainder negated."""
        neg = negate(T0)
        neg[-1].next = ("jump", fin[0].label)
        w = W(None, "", next=("if", "N", p.pair(W(None, "", next=("jump", fin[0].label)), neg[0])))
        p.routine(*neg)
        return w
    q_neg = negate(T1)
    r_after_q = rem_sign()
    q_neg[-1].next = ("jump", p._label(r_after_q))
    p.place(r_after_q)
    r_pos = rem_sign()
    e3 = W(None, "", next=("if", "N", p.pair(r_pos, q_neg[0])))
    p.routine(*q_neg)
    ends = [W(None, f"RAS=K K={T2} AOP=PASSA FL=NZ"),                        # E1: N: the quotient's sign
            W(None, "RAS=d AOP=PASSA FL=NZ"),                                 # E2: N: the dividend's
            e3]
    p.routine(*ends)
    loop = div_bits(p, "BIN=BUS MQ=DRIVE", ends[0])
    # the start: the divisor's Z (traps) and N; T2 = rd ^ rs; T1 = rd (N)
    start_loop = W(None, f"RAS=K K={T1} AOP=SHL CI=0 FL=NZCV WS=K", next=("jump", loop.label))
    p.place(start_loop)
    m_neg = negate(T1)
    m_neg[-1].next = ("jump", start_loop.label)
    # J: T0 = 0; its successor from T1's N (W3's flags, unchanged since)
    j_ = W(None, f"AOP=ZERO WS=K K={T0}", next=("if", "N", p.pair(W(None, "", next=("jump", start_loop.label)), m_neg[0])))
    p.routine(*m_neg)
    p.place(j_)
    pos = W(None, "RBS=s BIN=RF BOUT=1 MQ=LOAD", next=("jump", j_.label))
    dneg = [W(None, f"RAS=s AOP=NOTA WS=K K={T0}"), W(None, f"RAS=K K={T0} AOP=INCA CI=OWN WS=K"),
            W(None, f"RBS=K K={T0} BIN=RF BOUT=1 MQ=LOAD", next=("jump", j_.label))]
    w4 = W(None, "", next=("if", "N", p.pair(pos, dneg[0])))                 # the divisor's N (W1's)
    p.routine(*dneg)
    w3 = W(None, f"RAS=d AOP=PASSA FL=NZ WS=K K={T1}",
           next=("if", "Z", p.pair(w4, trap_word())))                       # the divisor's Z (W1's)
    p.routine(W("DIVS.r", "RBS=s BIN=RF AOP=PASSB FL=NZ"),
              W(None, f"RAS=d RBS=s BIN=RF AOP=XOR WS=K K={T2}"), w3)
    entries[(0xE8, None, None)] = ("DIVS.r", 1)


def multiple(p, entries):
    """LDM rb, ra-rc and STM rb, ra-rc (rc in the extension parcel's bits
    15-12): the parcel into MQ, shifted down twelve, then rc's bits off MQ0
    one a word (a 16-way tree, each test deciding two words on), into the
    chain for rc entered at ra; T0 the pointer from rb, each register a
    word that puts it into MAR (T0 += 4) and one that moves the data."""
    for opc, name in ((0x01, "LDM"), (0x02, "STM")):
        chains = {}
        for rc in range(15 + 1):
            chain = {}
            for j in range(rc, -1, -1):
                a = W(None, f"RAS=K K={T0} AOUT=OA AOP=ADD CI=0 BIN=BUS IMM=FOUR WS=K MARLD=1")
                if name == "LDM":
                    b = W(None, f"AOP=PASSB {load_src('w')} WS=K K={j}")
                else:
                    b = W(None, f"RAS=K K={j} AOUT=OA MOP=STORE MSZ=WORD DACC=1")
                b.next = "decode" if j == rc else ("jump", chain[j + 1][0].label)
                a.next = ("jump", p._label(b))
                p.place(a), p.place(b)
                chain[j] = (a, b)
            chains[rc] = chain
        for ra in range(16):
            def tree(level, bits):
                if level == 4:
                    rc = bits
                    if rc < ra:
                        return trap_word()
                    w = W(None, "", next=("jump", chains[rc][ra][0].label))
                    return w
                lo = tree(level + 1, bits)
                hi = tree(level + 1, bits | 1 << level)
                for w in (lo, hi):
                    if w.addr is None and isinstance(w.next, tuple) and w.next[0] == "jump":
                        pass
                # (a node's choice is made while the word before it executes:
                # the twelfth shift brings rc's bit 0 to MQ0 for the root's,
                # which the thirteenth word sees; it and levels 0 and 1 shift
                # on for the next)
                f = "MQ=SHIFT" if level < 2 else ""
                return W(None, f, next=("if", "MQ0", p.pair(lo, hi)))
            root = tree(0, 0)
            p.place(root)
            # MQ = the parcel (consumed), T0 = rb; then the shifts
            ws = [W(f"{name}.{ra:X}", f"AOP=PASSA RAS=s WS=K K={T0} BIN=BUS IMM=PE_ZX MQ=LOAD IQC=NEXT")]
            ws += [W(None, "MQ=SHIFT") for _ in range(13)]
            ws[-1].next = ("jump", root.label)
            p.routine(*ws)
            entries[(opc, ra, None)] = (f"{name}.{ra:X}", 2)


# ---- branches, jumps, calls ----------------------------------------------------------------

def tail_word():
    return W(None, "BFREE=1", next=("brdec", "waitd"))


def branches(p, entries):
    # Bcc, BRA (cc 14) and BSR's jump (cc 15): the adder's target
    p.routine(W("Bcc", "PCOP=BRANCH TK=1"), tail_word())
    p.routine(W("BSR", f"AIN=1 AOP=PASSA WS=K K={LINK} PCOP=DRIVE"), W(None, "PCOP=BRANCH TK=1"), tail_word())
    for op in range(0xB0, 0xC0):
        entries[(op, None, None)] = ("BSR" if op == 0xBF else "Bcc", 1)

    # Jcc d16 (F2, cc in the high nibble): T0 = 2 x ext, then PC + T0 if taken
    def jdisp(label, call):
        ws = [W(label, f"AOP=PASSB BIN=BUS IMM=PE_SX IQC=NEXT WS=K K={T0}"),
              W(None, f"RAS=K K={T0} AOP=SHL CI=0 WS=K"),
              W(None, f"AIN=1 RBS=K K={T0} BIN=RF AOP=ADD CI=0 WS=K PCOP=DRIVE")]
        if call:
            ws.append(W(None, f"AIN=1 AOP=PASSA WS=K K={LINK} PCOP=DRIVE"))
        ws += [W(None, f"RAS=K K={T0} AOUT=OA TK=1"), tail_word()]
        p.routine(*ws)
    jdisp("J.d16", False)
    jdisp("CALL.d16", True)
    for cc in range(16):
        entries[(0xF2, cc, 0)] = ("CALL.d16" if cc == 15 else "J.d16", 2)
    # Jcc abs32 (F3)
    p.routine(W("J.a32", "IQC=H"), W(None, "AOP=PASSB BIN=BUS IMM=H_PE IQC=NEXT AOUT=F TK=1"), tail_word())
    p.routine(W("CALL.a32", "IQC=H"), W(None, f"AOP=PASSB BIN=BUS IMM=H_PE IQC=NEXT WS=K K={T0}"),
              W(None, f"AIN=1 AOP=PASSA WS=K K={LINK} PCOP=DRIVE"),
              W(None, f"RAS=K K={T0} AOUT=OA PCOP=LOAD"), tail_word())
    for cc in range(16):
        entries[(0xF3, cc, 0)] = ("CALL.a32" if cc == 15 else "J.a32", 3)
    # JMP ea and CALL ea (F0, F1: M in the high nibble, R in the low). The
    # operand is read before the link is written
    for opc, name in ((0xF0, "JMP"), (0xF1, "CALL")):
        for col, R, key, size in modes():
            if size not in ("w", None):
                continue
            label = f"{name}.{col:X}" + (f"{R:X}" if R is not None else "")

            def link():
                return [W(None, f"AIN=1 AOP=PASSA WS=K K={LINK} PCOP=DRIVE")] if name == "CALL" else []

            def go():
                return [W(None, f"RAS=K K={T0} AOUT=OA PCOP=LOAD"), tail_word()]

            def fetch_go(src):
                """The operand (fields on OB) into T0 then to PC; a JMP's
                straight onto A for PC, a word less (a CALL writes the link
                after it has read the operand)."""
                if name == "JMP":
                    return [W(None, f"AOP=PASSB {src} AOUT=F PCOP=LOAD"), tail_word()]
                return [W(None, f"AOP=PASSB {src} WS=K K={T0}")] + link() + go()
            if key == "r":
                if name == "JMP":
                    ws = [W(label, "RAS=s AOUT=OA PCOP=LOAD"), tail_word()]
                else:
                    ws = [W(label, f"RAS=s AOP=PASSA WS=K K={T0}")] + link() + go()
                p.routine(*ws)
            elif key in CONSTANT:
                pre, src = constant_src(key)
                ws = [W(None, f) for f in pre] + fetch_go(src)
                ws[0].label = label
                p.routine(*ws)
            elif key in INDEXED:
                def after(fetch_go=fetch_go):
                    return fetch_go(load_src("w"))
                indexed(p, label, key, "AOUT=F MARLD=1", {"w": after}, sized=False)
            else:
                ws = [W(None, f) for f in address_words(key, size)]
                ws += fetch_go(load_src("w"))
                ws[0].label = label
                p.routine(*ws)
            entries[(opc, col, R)] = (label, 1 + ext_parcels(key))
    # DBNZ r, k parcels back: r -= 1; T0 = PC - 2k (NQ is -k); if r != 0, PC = T0
    jump = W(None, f"RAS=K K={T0} AOUT=OA PCOP=LOAD")
    p.routine(jump, tail_word())
    exit_ = W(None, "", next="decode")
    # (the flags stay: r != 0 on ST, an AND of r with all ones, C32)
    p.routine(W("DBNZ", "RAS=d AOP=DECA CI=0 WS=d"),
              W(None, f"RAS=d RBS=K K={K_M1} BIN=RF AOP=AND STOP=C32"),
              W(None, f"AIN=1 PCOP=DRIVE AOP=ADD CI=0 BIN=BUS IMM=NQ WS=K K={T0}"),
              W(None, f"RAS=K K={T0} AOP=ADD CI=0 BIN=BUS IMM=NQ WS=K",
                next=("if", "ST", p.pair(exit_, W(None, "", next=("jump", jump.label))))))
    entries[(0xF6, None, None)] = ("DBNZ", 1)


# ---- SAVE and RESTORE --------------------------------------------------------------------------

def save_restore(p, entries):
    """SAVE ra-rb: rb down to ra, each a pre-decrement of sp into MAR and a
    store; RESTORE ra-rb: ra up to rb, each sp into MAR (sp += 4) and a
    load. A chain for each fixed end, entered at the other."""
    for ra in range(15):
        chain = {}
        for j in range(ra, 15):
            a = W(None, f"RAS=K K={SP} AOP=SUB CI=OWN BIN=BUS IMM=FOUR AOUT=F WS=K MARLD=1")
            b = W(None, f"RAS=K K={j} AOUT=OA MOP=STORE MSZ=WORD DACC=1",
                  next="decode" if j == ra else ("jump", chain[j - 1][0].label))
            a.next = ("jump", p._label(b))
            p.place(a), p.place(b)
            chain[j] = (a, b)
            entries[(0xF4, ra, j)] = (a.label, 1)
    for rb in range(15):
        chain = {}
        for j in range(rb, -1, -1):
            a = W(None, f"RAS=K K={SP} AOUT=OA AOP=ADD CI=0 BIN=BUS IMM=FOUR WS=K MARLD=1")
            b = W(None, f"AOP=PASSB {load_src('w')} WS=K K={j}",
                  next="decode" if j == rb else ("jump", chain[j + 1][0].label))
            a.next = ("jump", p._label(b))
            p.place(a), p.place(b)
            chain[j] = (a, b)
            entries[(0xF5, j, rb)] = (a.label, 1)


# ---- the decode table -------------------------------------------------------------------

def build():
    p = Program()
    entries = {}
    # reset: A = 0 (the ALU's ZERO onto A), PC and FPC from it, the queue
    # empty; then the constants, and WAITD until the first instruction is in
    p.place(Word("reset", "AOP=ZERO AOUT=F PCOP=LOAD", next=("jump", "_consts")), at=0)
    p.place(Word("waitd", "", next="decode", note="decode again"), at=WAITD)
    p.place(Word("halt", "", next=("jump", "halt1")), at=6)
    p.place(Word("halt1", "", next=("jump", "halted")), at=8)
    p.place(Word("halted", "", next=("jump", "halted")), at=9)
    p.place(Word("unimpl", "", next=("jump", "unimpl")), at=7)
    first = reset_constants(p, "waitd")
    p.labels["_consts"] = p.addr(first)
    ea_rows(p, entries)
    stores(p, entries)
    lea(p, entries)
    unary(p, entries)
    shifts(p, entries)
    multiply(p, entries)
    divide(p, entries)
    multiple(p, entries)
    branches(p, entries)
    save_restore(p, entries)
    p.entry_map = entries
    auto_bfree(p)
    p.check()
    p.check_parcels({lab: n for lab, n in entries.values()})
    return p


def entry(p, parcel):
    """(entry label, length in parcels) for an instruction's first parcel:
    entries are keyed (opcode, high nibble, low nibble), None for any."""
    op, rb = parcel & 0xFF, parcel >> 8
    hi, lo = rb >> 4, rb & 15
    e = p.entry_map
    for key in ((op, hi, lo), (op, None, lo), (op, hi, None), (op, None, None)):
        if key in e:
            return e[key]
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
