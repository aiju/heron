"""Microcode and decode ROM for the draft 1b implementation.

See docs/hardware-v1b.md for the datapath these signals drive.

The control store is pipelined. The microcode ROMs are always addressed with
the address of the *next* microinstruction, and their outputs are clocked
into the microinstruction register (uIR) at every clock edge, so the control
signals are valid a register delay after the edge instead of a ROM access
later. The next address Y is chosen during the current cycle:

    SEQ 0  Y = NEXT, or {NEXT[11:1], cond}
                                       branch: the condition replaces bit 0
                                       (NEXT[0] is 0 in a branch)
    SEQ 1  Y = decode ROM output       end of instruction: the decode ROM looks
                                       at the data bus, where the next
                                       instruction's first parcel is arriving
                                       (or, with GOIRQ, gives interrupt entry)
    SEQ 2  Y = {NEXT[11:5], DBUS[11:8], DBUS[7:0] != 0}
                                       indexed-mode dispatch on the extension
                                       parcel being fetched
    reset  Y = 0

ROM address = {FAULT & LEN, FAULT, IRQP, Y}. The IRQP = 1 half is a copy of
the other, except that instruction-ending microinstructions don't fetch and
go to interrupt entry instead, and HALT stops waiting. A misaligned access
(FAULT) forces Y to 0 and selects one of the fault pages, whose word 0 is
the address error entry for that instruction length; the select lines of
the Y multiplexer never depend on the data path.

Microinstructions are written as dicts of logical field values with the
helpers below, linked into a graph (Node), and placed in the ROM by
`build()`, which also produces the decode ROM.
"""

import random
from collections import defaultdict

from ..isa import v1b
from ..isa import v1common as c

# --------------------------------------------------------------------------
# Control word: (name, width, active_low). Active-low fields are stored
# inverted, so a logical 1 means "asserted" everywhere in this file.

FIELDS = [
    # sequencer
    ("NEXT", 12, False), ("SEQ", 2, False), ("COND", 3, False), ("GOIRQ", 1, False),
    ("HALT", 1, False),
    # A bus drivers
    ("ARF", 1, True), ("APC", 1, True), ("AR", 1, True), ("AR2", 1, True), ("ABR", 1, True),
    # B bus drivers, per byte lane
    ("BRF", 1, True), ("BR", 1, True), ("BT0", 1, True), ("BT1", 1, True), ("BT23", 1, True),
    ("BS0", 1, True), ("BF1", 1, True), ("BF23", 1, True), ("BMQ", 1, True), ("BFL", 1, True),
    ("BT2", 1, True),
    ("TLANE", 1, False),
    # data bus driver
    ("DSRC", 2, True),
    # register file
    ("RFA", 2, False), ("RFB", 2, False), ("LDX", 1, True), ("RFK", 5, False),
    ("RFWE", 1, False), ("WR0", 1, False),
    # ALU
    ("S", 4, False), ("M", 1, False), ("CIN", 3, False), ("MQM", 2, False), ("MS", 2, False),
    # result multiplexer and shift inputs
    ("RMS", 2, False), ("RZ", 4, False), ("SIN", 2, False), ("SINA", 2, False),
    # immediate unit
    ("V8", 2, False), ("FSEL", 3, False), ("KONST", 8, False), ("LDSGN", 1, False),
    # register loads
    ("LDR", 1, True), ("LDMAR", 1, True), ("MARSRC", 1, False), ("LDTL", 1, True),
    ("LDTH", 1, True), ("LDIR", 1, True), ("LDPC", 1, False), ("PCCOND", 1, False),
    ("LDLC", 1, True), ("LCINC", 1, False), ("CCB", 1, False),
    # memory
    ("MEMRD", 1, True), ("MEMWR", 1, False), ("ADDRMAR", 1, False), ("SIZE", 2, False),
    ("HIWORD", 1, False),
    # flags and condition latches
    ("FNZ", 2, False), ("FC", 2, False), ("CZERO", 1, False), ("CSRC", 3, False),
    ("FV", 3, False), ("FI", 2, False), ("LDCL", 1, False), ("CLSRC", 3, False),
]

ROMS = 15
ROM_ADDR_BITS = 17          # SST39SF010A
Y_BITS = 12

def _layout():
    """Bit positions: NEXT takes the first Y_BITS bits, the rest are packed
    first-fit (widest first) so that no field is split between two ROMs."""
    pos = {"NEXT": (0, Y_BITS, False)}
    free = [8] * ROMS
    free[0], free[1] = 0, 16 - Y_BITS
    for name, w, al in sorted((f for f in FIELDS if f[0] != "NEXT"), key=lambda f: -f[1]):
        for k in range(ROMS):
            if free[k] >= w:
                pos[name] = (8 * k + 8 - free[k], w, al)
                free[k] -= w
                break
        else:
            raise AssertionError(f"control word doesn't fit in {ROMS} ROMs")
    return pos


_pos = _layout()
CONTROL_BITS = sum(w for _, w, _ in FIELDS)
WIDTH = {name: w for name, w, _ in FIELDS}

# encodings
SEQ_NEXT, SEQ_DECODE, SEQ_DISPATCH = 0, 1, 2
# condt: the branch condition's test (Z, C, N, V, HI, N == V, GT or always)
# before the polarity bit; a routine branches on condt or ncondt depending
# on the polarity bit of the instruction it serves
CONDS = {"false": 0, "tc": 1, "r31": 2, "cl": 3, "condt": 4, "mq31": 5, "tc4": 6, "ncondt": 7}
# store data onto the data bus: bit 0 = RES[7:0] on the low lane (lo, byte),
# bit 1 = lo or hi (decoded by the 74HCT541s' two enables, no decoder)
DSRC = {None: 0, "lo": 3, "hi": 2, "byte": 1}
# s is the SX register: IR[7:4], or the index register number (T[15:12]) after
# the indexed mode's extension parcel was fetched with ldx
RFSEL = {"d": 0, "r": 1, "s": 2, "x": 2}           # 3 = RFK constant
CIN = {"0": 0, "1": 1, "c": 2, "a31": 3, "mq31": 4, "sgn": 5, "mq0": 6, "s33n": 7}
# MQM: the 74HCT299 mode pins of MQ (S1 S0: 00 hold, 01 shift toward the
# LSB, 10 toward the MSB, 11 load). MS: in a step, the ALU function comes
# from MQ[0] or S33 instead of S (the carry in still comes from CIN, M is 0):
#   1 add X if MQ[0]           mulu: multiply step, shifting R:MQ right with
#   2 subtract X if MQ[0]      muls: C32 or (SIN f31) the true sign of the sum
#   3 add X if S33, else subtract it (div), or else pass (fix)
# md= sets both (and the carry in).
MD = {None: (0, 0, None), "mqload": (3, 0, None), "mulu": (1, 1, "0"), "muls": (1, 2, "mq0"),
      "div": (2, 3, "s33n"), "fix": (0, 3, "0")}
RMS = {"f": 0, "shr": 1, "ror8": 2, "ror16": 3}
SIN = {"0": 0, "f31": 1, "c": 2, "f0": 3}
SINA = {"0": 0, "r31": 1, "c": 2, "mq31": 3}
V8 = {"bcc": 0, "k": 1, "fill": 2, "lc": 3}
FSEL = {"0": 0, "1": 1, "ir7": 2, "t7": 3, "t15": 4, "a31": 5, "a15": 6, "sgn": 7}
SIZE = {None: 0, "byte": 1, "half": 2, "word": 3}
FNZ = {None: 0, "nz": 1, "sticky": 2, "loadf": 3}
FC = {None: 0, "csrc": 1, "aluc": 2, "ncl": 3}
CSRC = {"b1": 0, "f0": 1, "f7": 2, "f8": 3, "f15": 4, "f31": 5, "f7x": 6, "f15x": 7}
# ovf is 7 so that one gate can tell it (the multiplexer is disabled when
# the operands' signs rule overflow out)
FV = {None: 0, "0": 2, "b0": 3, "ncl": 4, "1": 5, "ovf": 7}
FI = {None: 0, "1": 1, "0": 2, "b4": 3}
# condition latch CL: B == 0, the ALU carry, B[31:16] == 0, B[31:15] == 0,
# or one of the last two ANDed with CL
CLSRC = {"zero": 0, "aluc": 1, "hz16": 2, "hz17": 3, "and_hz16": 4, "and_hz17": 5}

# 74181 functions (active-high data): (M, S3..S0) and the carry they need.
ALU = {
    "add": (0, 0b1001, "0"), "adc": (0, 0b1001, "c"),
    "sub": (0, 0b0110, "1"), "sbc": (0, 0b0110, "c"),
    "inc": (0, 0b0000, "1"), "dec": (0, 0b1111, "0"),
    "a": (0, 0b0000, None),           # A + carry-in, carry from cin=
    "dbl": (0, 0b1100, None),         # A + A + carry-in
    "and": (1, 0b1011, None), "or": (1, 0b1110, None), "xor": (1, 0b0110, None),
    "bic": (1, 0b0111, None), "passa": (1, 0b1111, None), "passb": (1, 0b1010, None),
    "nota": (1, 0b0000, None), "zero": (1, 0b0011, None), "ornb": (1, 0b1000, None),
}

# Register file locations above r15 (the SRAMs have room): HI and scratch.
SP, HI, TMP1, KC1, KC0 = 15, 16, 17, 24, 25
RF_CONSTS = {KC1: 0xE1, KC0: 0xE0}      # loop counts, written by the reset routine


# --------------------------------------------------------------------------
# Building microinstructions

def _put(f, k, v):
    if k in f and f[k] != v:
        raise ValueError(f"microcode conflict on {k}: {f[k]} vs {v}")
    f[k] = v


def _rf(f, side, sel):
    """Point RF port 'RFA' or 'RFB' at d, r, s, x or a constant location."""
    if isinstance(sel, int):
        _put(f, side, 3)
        _put(f, "RFK", sel)
    else:
        _put(f, side, RFSEL[sel])


B_PRESETS = {
    "rf": ("BRF",), "r": ("BR",), "t": ("BT0", "BT1", "BT23"),
    "tlo": ("BT0", "BT1", "BF23"),            # half: fill= decides zero/sign extension
    "t2": ("BT2", "BF23"),                    # 2 * T.lo, sign-extended (fill t15): Jcc offsets
    "tbyte": ("BT0", "BF1", "BF23"),          # byte from the lane MAR[0] picks (TLANE)
    "tb0": ("BT0", "BF1", "BF23"),            # the indexed mode's d8
    "simm": ("BS0", "BF1", "BF23"),           # V8 in byte 0, fill above
    "thi": ("BS0", "BF1", "BT23"),            # T.hi << 16 (V8 = KONST 0, fill 0)
    "mq": ("BMQ",), "flags": ("BFL", "BF1", "BF23"),
    "fillall": ("BS0", "BF1", "BF23"),        # all 32 bits = fill
}


def mi(**kw):
    """One microinstruction (dict of logical field values)."""
    f = {}
    for k, v in kw.items():
        if v is None or v is False:
            continue
        if k == "ra":
            _put(f, "ARF", 1)
            _rf(f, "RFA", v)
        elif k == "rb":
            _put(f, "BRF", 1)
            _rf(f, "RFB", v)
        elif k == "a":
            _put(f, {"pc": "APC", "r": "AR", "r2": "AR2", "br": "ABR"}[v], 1)
        elif k == "b":
            for e in B_PRESETS[v]:
                _put(f, e, 1)
            if v == "tbyte":
                _put(f, "TLANE", 1)
            if v == "thi":
                _put(f, "V8", V8["k"])
                _put(f, "KONST", 0)
                _put(f, "FSEL", FSEL["0"])
            if v == "fillall":
                _put(f, "V8", V8["fill"])
            if v == "flags":
                _put(f, "FSEL", FSEL["0"])
        elif k == "kv":                       # a constant on the B bus
            if not -256 <= v <= 255:
                raise ValueError(f"constant {v} doesn't fit the immediate unit")
            for e in B_PRESETS["simm"]:
                _put(f, e, 1)
            _put(f, "V8", V8["k"])
            _put(f, "KONST", v & 0xFF)
            _put(f, "FSEL", FSEL["1" if v < 0 else "0"])
        elif k == "fill":
            _put(f, "FSEL", FSEL[v])
        elif k == "v8":
            _put(f, "V8", V8[v])
        elif k == "k":
            _put(f, "KONST", v)
        elif k == "alu":
            m, s, cin = ALU[v]
            _put(f, "M", m)
            _put(f, "S", s)
            if cin is not None:
                _put(f, "CIN", CIN[cin])
        elif k == "cin":
            _put(f, "CIN", CIN[v])
        elif k == "md":
            mqm, ms, cin = MD[v]
            _put(f, "MQM", mqm)
            _put(f, "MS", ms)
            if cin is not None:
                _put(f, "CIN", CIN[cin])
        elif k == "rms":
            _put(f, "RMS", RMS[v])
        elif k == "rz":
            _put(f, "RZ", v)
        elif k == "sin":
            _put(f, "SIN", SIN[v])
        elif k == "sina":
            _put(f, "SINA", SINA[v])
        elif k == "marsrc":
            _put(f, "MARSRC", int(v == "a"))
        elif k == "mem":
            # fetch: opcode at PC into IR; ext/exthi: extension parcel at PC
            # into T.lo/T.hi; rdlo/rdhi: data at MAR into T.lo/T.hi;
            # wrlo/wrhi/wrbyte: result bus to memory at MAR
            if v in ("fetch", "ext", "exthi"):
                _put(f, "MEMRD", 1)
                _put(f, "ADDRMAR", 0)
                _put(f, {"fetch": "LDIR", "ext": "LDTL", "exthi": "LDTH"}[v], 1)
            elif v in ("rdlo", "rdhi"):
                _put(f, "MEMRD", 1)
                _put(f, "ADDRMAR", 1)
                _put(f, "LDTL" if v == "rdlo" else "LDTH", 1)
                if v == "rdhi":
                    _put(f, "HIWORD", 1)
            elif v in ("wrlo", "wrhi", "wrbyte"):
                _put(f, "MEMWR", 1)
                _put(f, "ADDRMAR", 1)
                _put(f, "DSRC", DSRC[v[2:]])
                if v == "wrhi":
                    _put(f, "HIWORD", 1)
            else:
                raise KeyError(v)
        elif k == "size":
            _put(f, "SIZE", SIZE[v])
        elif k == "wb":                       # write the B bus into a register
            _put(f, "RFWE", 1)
            _put(f, "ABR", 1)
            _rf(f, "RFA", v)
            _rf(f, "RFB", v)
        elif k == "fnz":
            _put(f, "FNZ", FNZ[v])
        elif k == "fc":
            if v in CSRC:
                _put(f, "FC", FC["csrc"])
                _put(f, "CSRC", CSRC[v])
            else:
                _put(f, "FC", FC[v])
        elif k == "fv":
            _put(f, "FV", FV[v])
        elif k == "fi":
            _put(f, "FI", FI[v])
        elif k == "loadf":                    # all five flags from the B bus
            _put(f, "FNZ", FNZ["loadf"])
            _put(f, "FC", FC["csrc"])
            _put(f, "CSRC", CSRC["b1"])
            _put(f, "FV", FV["b0"])
            _put(f, "FI", FI["b4"])
        elif k == "ldcl":
            _put(f, "LDCL", 1)
            _put(f, "CLSRC", CLSRC[v])
        elif k in ("ldr", "ldmar", "ldtl", "ldth", "ldpc", "pccond", "ldlc", "lcinc", "ccb",
                   "ldsgn", "wr0", "czero", "halt", "goirq", "ldx"):
            _put(f, k.upper(), 1)
        else:
            raise KeyError(f"unknown microcode keyword {k}")
    return f


def merge(*parts):
    out = {}
    for p in parts:
        for k, v in p.items():
            _put(out, k, v)
    return out


def pack(f):
    """Field dict -> integer control word (physical levels)."""
    word = 0
    for name, (bit, w, al) in _pos.items():
        v = f.get(name, 0)
        assert 0 <= v < (1 << w), (name, v)
        if al:
            v ^= (1 << w) - 1
        word |= v << bit
    return word


def unpack(word):
    out = {}
    for name, (bit, w, al) in _pos.items():
        v = (word >> bit) & ((1 << w) - 1)
        if al:
            v ^= (1 << w) - 1
        out[name] = v
    return out


# --------------------------------------------------------------------------
# Microcode graph

class Node:
    """One microinstruction and how the next one is chosen.

    succ: ("next", node) | ("branch", cond, node0, node1) | ("decode",)
          | ("dispatch", [32 nodes]) | ("halt",)
    """
    __slots__ = ("f", "succ", "name", "addr", "slot", "fixed")

    def __init__(self, f, succ=None, name=""):
        self.f = f
        self.succ = succ
        self.name = name
        self.addr = None
        self.slot = None
        self.fixed = None

    def clone(self):
        n = Node(self.f, self.succ, self.name)
        return n


def end(name="", **kw):
    """Last microinstruction of an instruction: fetches the next one."""
    return Node(merge(mi(mem="fetch"), mi(**kw)), ("decode",), name)


def chain(name, *items):
    """Link dicts (and a final Node) into a straight sequence; returns the head."""
    items = list(items)
    tail = items.pop()
    if not isinstance(tail, Node):
        raise TypeError("chain must end with a Node")
    nxt = tail
    for f in reversed(items):
        if isinstance(f, Node):
            raise TypeError("only the last item of a chain can be a Node")
        nxt = Node(f, ("next", nxt), name)
    return nxt


def branch(name, f, cond, if0, if1):
    return Node(f, ("branch", CONDS[cond], if0, if1), name)


def loop(name, f, cond, exit_node):
    """A microinstruction that repeats until cond holds (it is evaluated each
    time, from the state before that repetition), then goes to exit_node."""
    n = Node(f, None, name)
    n.succ = ("branch", CONDS[cond], n, exit_node)
    return n


# --------------------------------------------------------------------------
# Common pieces

FETCH_EXT = mi(mem="ext")


def sp_minus(k, also=None):
    """MAR, R <- sp - k."""
    return merge(mi(ra=SP, kv=k, alu="sub", ldmar=1, ldr=1), also or {})


def push_pc():
    """The two bus cycles that store PC at MAR (word)."""
    return [mi(a="pc", alu="passa", mem="wrlo", size="word"),
            mi(a="pc", alu="passa", mem="wrhi")]


_trap_cache = {}


def trap(vector, pcfix):
    """Push PC (minus pcfix) and the flags, I <- 0, jump to the vector."""
    key = (vector, pcfix)
    if key in _trap_cache:
        return _trap_cache[key]
    name = {0x04: "irq", 0x08: "illegal", 0x0C: "swi", 0x10: "divzero", 0x14: "addrerr"}[vector]
    steps = []
    if pcfix:
        steps.append(mi(a="pc", kv=pcfix, alu="sub", ldpc=1))
    steps += [
        sp_minus(8),
        mi(b="flags", alu="passb", mem="wrlo", size="word"),
        # I <- 0 early enough that the pending-interrupt bit is clear before
        # this routine's final fetch (not in the cycle above: an address
        # error there must leave the flags alone)
        mi(b="flags", alu="passb", mem="wrhi", fi="0"),
        mi(ra=SP, kv=4, alu="sub", ldmar=1),
        mi(a="pc", alu="passa", mem="wrlo"),
        mi(a="pc", alu="passa", mem="wrhi"),
        mi(kv=vector, alu="passb", ldpc=1),
    ]
    node = chain(name, *steps, end(name, wb=SP, b="r"))
    _trap_cache[key] = node
    return node


def illegal(pcfix=2):
    return trap(c.ILLEGAL_VECTOR, pcfix)


# --------------------------------------------------------------------------
# Effective addresses (draft 1b modes)

def size_name(n):
    return {1: "byte", 2: "half", 4: "word"}[n]


def mode_size(M, R):
    """Operand size of a memory mode (4 for non-memory)."""
    if M in (8, 9, 0xA) or (M == 0xF and R in (5, 8, 0xB)):
        return 1
    if M in (0xB, 0xC) or (M == 0xF and R in (6, 9, 0xC)):
        return 2
    return 4


def is_mem(M, R):
    return M not in (0, 1, 0xD) and not (M == 0xF and R <= 3)


def addr_steps(M, R, dest="mar"):
    """Steps that put the address of a memory operand into MAR (dest='mar')
    or R (dest='r', for LEA). Returns (steps, update) where update is
    'post'/'pre' with the new base value left in R, or None.
    Not used for the indexed mode (5), which dispatches."""
    load = {"ldmar": 1} if dest == "mar" else {"ldr": 1}
    if M in (2, 8, 0xB):                              # [R]
        if dest == "mar":
            return [mi(ra="r", marsrc="a", ldmar=1)], None
        return [mi(ra="r", alu="passa", ldr=1)], None
    if M in (3, 9, 0xC):                              # [R + d16]
        return [FETCH_EXT, mi(ra="r", b="tlo", fill="t15", alu="add", **load)], None
    if M == 4:                                        # [sp + 4R]
        return [mi(ra=SP, kv=4 * R, alu="add", **load)], None
    if M in (6, 0xA):                                 # [R]+
        size = 4 if M == 6 else 1
        return [mi(ra="r", marsrc="a", ldmar=1, kv=size, alu="add", ldr=1)], "post"
    if M == 7:                                        # -[R]
        return [mi(ra="r", kv=4, alu="sub", ldmar=1, ldr=1)], "pre"
    if M == 0xF and R in (4, 5, 6):                   # [abs16]
        return [FETCH_EXT, mi(b="tlo", fill="t15", alu="passb", **load)], None
    if M == 0xF and R in (7, 8, 9):                   # [abs32]
        return [FETCH_EXT, mi(mem="exthi"), mi(b="t", alu="passb", **load)], None
    if M == 0xF and R in (0xA, 0xB, 0xC):             # [pc + d16]
        return [FETCH_EXT, mi(a="pc", b="tlo", fill="t15", alu="add", **load)], None
    raise ValueError(f"mode {M:X}/{R:X} has no address")


def load_steps(size, update):
    """Bus cycles reading a memory operand at MAR into T (base update in the
    last one). Returns (steps, operand B-bus spec)."""
    wb = mi(wb="r", b="r") if update else {}
    if size == 4:
        return [mi(mem="rdlo", size="word"), merge(mi(mem="rdhi"), wb)], {"b": "t"}
    if size == 2:
        assert not update
        return [mi(mem="rdlo", size="half")], {"b": "tlo", "fill": "0"}
    # bytes can't be misaligned, so the base can be written in the same cycle
    return [merge(mi(mem="rdlo", size="byte"), wb)], {"b": "tbyte", "fill": "0"}


def store_steps(size):
    """Bus cycles storing rd at MAR (the ALU passes it to the result bus)."""
    if size == 4:
        return [mi(ra="d", alu="passa", mem="wrlo", size="word"),
                mi(ra="d", alu="passa", mem="wrhi")]
    if size == 2:
        return [mi(ra="d", alu="passa", mem="wrlo", size="half")]
    return [mi(ra="d", alu="passa", mem="wrbyte", size="byte")]


def index_addr(s, dz, dest="mar"):
    """Address steps for the indexed mode after the extension parcel is in
    T: base (IR R field) + T[7:0] + x * 2^s, x = T[15:12] (copied to SX)."""
    final = {"ldmar": 1} if dest == "mar" else {"ldr": 1}
    steps = []
    if s == 0:
        if dz:
            return [mi(ra="r", rb="x", alu="add", **final)]
        steps.append(mi(ra="r", rb="x", alu="add", ldr=1))
    elif s in (1, 2):
        if s == 1:
            steps.append(mi(ra="x", alu="passa", ldr=1))
        else:
            steps.append(mi(ra="x", alu="dbl", cin="0", ldr=1))
        # A = 2R + 0, B = base
        if dz:
            steps.append(mi(a="r2", sina="0", rb="r", alu="add", **final))
            return steps
        steps.append(mi(a="r2", sina="0", rb="r", alu="add", ldr=1))
    else:
        steps.append(mi(ra="x", alu="dbl", cin="0", ldr=1))
        steps.append(mi(a="r2", sina="0", alu="dbl", cin="0", ldr=1))
        if dz:
            steps.append(mi(a="r", rb="r", alu="add", **final))
            return steps
        steps.append(mi(a="r", rb="r", alu="add", ldr=1))
    steps.append(mi(a="r", b="tb0", fill="t7", alu="add", **final))
    return steps


# --------------------------------------------------------------------------
# Instruction routines

EA_OPS = {1: "MOV", 2: "ST", 3: "LEA", 4: "ADD", 5: "SUB", 6: "CMP", 7: "AND", 8: "OR",
          9: "XOR"}
ALU_OF = {"ADD": "add", "SUB": "sub", "CMP": "sub", "AND": "and", "OR": "or", "XOR": "xor"}


def op_tail(opname, opnd, name):
    """The steps after the operand is available on the B bus (opnd: mi()
    keywords selecting it). Returns the head node."""
    rf = opnd.get("rb") is not None
    if opname == "MOV":
        if rf:
            return chain(name, mi(alu="passb", ldr=1, **opnd), end(name, wb="d", b="r", fnz="nz"))
        return end(name, wb="d", fnz="nz", **opnd)
    if opname in ALU_OF:
        flags = {"fc": "aluc", "fv": "ovf"} if opname in ("ADD", "SUB", "CMP") else {}
        step = mi(ra="d", alu=ALU_OF[opname], ldr=1, **opnd, **flags)
        if opname == "CMP":
            return chain(name, step, end(name, b="r", fnz="nz"))
        return chain(name, step, end(name, wb="d", b="r", fnz="nz"))
    if opname == "JMP":
        return chain(name, mi(alu="passb", ldpc=1, **opnd), end(name))
    if opname == "CALL":
        return chain(name, sp_minus(4), *push_pc(), mi(alu="passb", ldpc=1, **opnd),
                     end(name, wb=SP, b="r"))
    raise ValueError(opname)


def ea_routine(op, k, M, R):
    """ops 1-9 and B. k is the d field for op B (0 JMP, 1 CALL)."""
    opname = "JMP" if (op == 0xB and k == 0) else ("CALL" if op == 0xB else EA_OPS[op])
    name = f"{opname} m{M:X}" + (f"/{R:X}" if M in (1, 4, 0xD, 0xF) else "")
    if M == 0:
        return op_tail(opname, {"rb": "r"}, name)
    if M in (1, 0xD):
        v = R if M == 1 else -(R + 1)
        return op_tail(opname, {"kv": v}, name)
    if M == 0xF and R <= 3:
        if R == 3:
            return chain(name, FETCH_EXT, mi(mem="exthi"), op_tail(opname, {"b": "t"}, name))
        if R == 2:
            return chain(name, mi(mem="exthi"), op_tail(opname, {"b": "thi"}, name))
        fill = "t15" if R == 0 else "0"
        return chain(name, FETCH_EXT, op_tail(opname, {"b": "tlo", "fill": fill}, name))
    if M == 5:
        table = []
        for i in range(32):
            s, z, dz = i >> 3, (i >> 1) & 3, (i & 1) ^ 1
            table.append(index_entry(opname, s, z, dz, f"{name} s{s}z{z}{'' if dz else 'd'}"))
        return Node(mi(mem="ext", ldx=1), ("dispatch", table), name)
    size = mode_size(M, R)
    if opname == "LEA" and M == 0xF and R in (4, 5, 6):
        return chain(name, FETCH_EXT, end(name, wb="d", b="tlo", fill="t15"))
    if opname == "LEA" and M == 0xF and R in (7, 8, 9):
        return chain(name, FETCH_EXT, mi(mem="exthi"), end(name, wb="d", b="t"))
    if opname == "LEA":
        steps, _ = addr_steps(M, R, dest="r")
        return chain(name, *steps, end(name, wb="d", b="r"))
    steps, update = addr_steps(M, R)
    return mem_tail(opname, steps, update, size, name)


def mem_tail(opname, steps, update, size, name):
    """Address steps done (MAR set; R holds the new base for update), now
    the access and the operation."""
    if opname == "ST":
        tail = end(name, wb="r", b="r") if update else end(name)
        return chain(name, *steps, *store_steps(size), tail)
    lsteps, opnd = load_steps(size, update)
    return chain(name, *steps, *lsteps, op_tail(opname, opnd, name))


def index_entry(opname, s, z, dz, name):
    if z == 3:
        return illegal(4)
    size = (1, 2, 4)[z]
    if opname in ("JMP", "CALL") and size != 4:
        return illegal(4)
    if opname == "LEA":
        return chain(name, *index_addr(s, dz, dest="r"), end(name, wb="d", b="r"))
    return mem_tail(opname, index_addr(s, dz), None, size, name)


def unary_routine(fn):
    name = c.UN_FN[fn]
    wb = end(name, wb="d", b="r", fnz="nz")
    wbv = end(name, wb="d", b="r", fnz="nz", fv="0")
    if name == "NOT":
        return chain(name, mi(ra="s", alu="nota", ldr=1), wb)
    if name == "NEG":
        return chain(name, mi(ra=0, rb="s", alu="sub", ldr=1, fc="aluc", fv="ovf"), wb)
    if name == "INC":
        return chain(name, mi(ra="s", alu="inc", ldr=1), wb)
    if name == "DEC":
        return chain(name, mi(ra="s", alu="dec", ldr=1), wb)
    if name == "RLC":
        return chain(name, mi(ra="s", alu="dbl", cin="c", fc="aluc", ldr=1), wbv)
    if name == "RRC":
        return chain(name, mi(ra="s", alu="passa", rms="shr", sin="c", fc="f0", ldr=1), wbv)
    if name == "SWAP":
        return chain(name, mi(ra="s", alu="passa", rms="ror16", ldr=1), wb)
    if name == "SXB":   # ((x ^ 0x80) & 0xFF) - 0x80
        return chain(name, mi(ra="s", kv=0x80, alu="xor", rz=0b1110, ldr=1),
                     mi(a="r", kv=0x80, alu="sub", ldr=1), wb)
    if name == "ZXB":
        return chain(name, mi(ra="s", alu="passa", rz=0b1110, ldr=1), wb)
    if name == "SXH":   # (x ^ s) & 0xFFFF ^ s, s = 32 copies of bit 15
        return chain(name, mi(ra="s", b="fillall", fill="a15", ldsgn=1, alu="xor", rz=0b1100, ldr=1),
                     mi(a="r", b="fillall", fill="sgn", alu="xor", ldr=1), wb)
    if name == "ZXH":
        return chain(name, mi(ra="s", alu="passa", rz=0b1100, ldr=1), wb)
    if name == "CLZ":
        # LC counts the shifts; the loop exits one shift late (it tests bit 31
        # before shifting), so LC starts at -1.
        out = end(name, wb="d", b="simm", v8="lc", fill="0", fnz="nz")
        body = loop(name, mi(a="r2", sina="0", alu="passa", ldr=1, lcinc=1), "r31", out)
        zero = end(name, wb="d", kv=32, fnz="nz")
        return chain(name, mi(kv=-1, alu="passb", ldlc=1),
                     mi(rb="s", alu="passb", ldr=1, ldcl="zero"),
                     branch(name, {}, "cl", body, zero))
    raise ValueError(name)


# ---- shifts by a constant: search for the shortest step sequence ----------
#
# A shift by n is a short sequence of steps, each one cycle: single-bit
# shifts (right through the result multiplexer, left with the ALU's A + A or
# the R x 2 driver), byte rotations through the result multiplexer with byte
# lanes cleared, and for ASR the trick of working on x ^ s (s = 32 copies of
# the sign) as a logical shift and XORing s back at the end. The carry must
# come out right too: it is set by the last step that sets it. plan_shift()
# finds the shortest sequence by breadth-first search over what the steps do
# to a set of test values, so every plan is checked as it is found.

M32 = 0xFFFFFFFF


def _rot(v, rms):
    if rms == "ror8":
        return ((v >> 8) | (v << 24)) & M32
    if rms == "ror16":
        return ((v >> 16) | (v << 16)) & M32
    return v


def _zmask(rz):
    m = M32
    for i in range(4):
        if rz >> i & 1:
            m &= ~(0xFF << (8 * i)) & M32
    return m


def _bit(v, i):
    return (v >> i) & 1


def _plain_steps():
    """(label, needs R (not usable first), mi dict, fn(a, r, c, sgn) -> (v, c, sgn)).
    a is the A operand (the register for a first step, else R)."""
    out = []
    for sn in ("0", "f31", "f0"):
        def f(a, r, cc, sg, sn=sn):
            sin = {"0": 0, "f31": _bit(a, 31), "f0": _bit(a, 0)}[sn]
            return ((a >> 1) | (sin << 31)) & M32, _bit(a, 0), sg
        out.append((f"sr1/{sn}", False, mi(alu="passa", rms="shr", sin=sn, fc="f0"), f))
    out.append(("sl1", False, mi(alu="dbl", cin="0", fc="aluc"),
                lambda a, r, cc, sg: ((a << 1) & M32, _bit(a, 31), sg)))

    def rl1(a, r, cc, sg):
        v = ((a << 1) | _bit(a, 31)) & M32
        return v, _bit(v, 31), sg
    out.append(("rl1", False, mi(alu="dbl", cin="a31", fc="f31"), rl1))
    out.append(("sl2", True, mi(a="r2", sina="0", alu="dbl", cin="0", fc="aluc"),
                lambda a, r, cc, sg: ((r << 2) & M32, _bit(r, 30), sg)))

    def rl2(a, r, cc, sg):
        v = ((r << 2) | (r >> 30)) & M32
        return v, _bit(v, 31), sg
    out.append(("rl2", True, mi(a="r2", sina="r31", alu="dbl", cin="a31", fc="f31"), rl2))
    combos = [("ror8", 0, ("f7", "f8")), ("ror8", 0b1000, ("f7",)), ("ror8", 0b0111, ("f8",)),
              ("ror8", 0b0001, ("f8",)), ("ror8", 0b0011, ("f8",)), ("ror8", 0b1100, ("f7",)),
              ("ror8", 0b1110, ("f7",)),
              ("ror16", 0, ("f15",)), ("ror16", 0b1100, ("f15",)), ("ror16", 0b0011, ()),
              ("ror16", 0b1110, ("f15",)),
              ("f", 0b0001, ("f0",)), ("f", 0b0011, ("f0",)), ("f", 0b0111, ("f0",))]
    for rms, rz, css in combos:
        for cs in (None,) + css:
            def f(a, r, cc, sg, rms=rms, rz=rz, cs=cs):
                return _rot(a, rms) & _zmask(rz), cc if cs is None else _bit(a, int(cs[1:])), sg
            kw = dict(alu="passa", rms=rms, rz=rz)
            if cs:
                kw["fc"] = cs
            out.append((f"{rms}/{rz:04b}/{cs}", False, mi(**kw), f))
    return out


def _xor_first():
    """First steps of an arithmetic shift: A ^ s, SGN <- sign."""
    out = []
    for rms, rz in [("f", 0), ("shr", 0), ("ror8", 0b1000), ("ror16", 0b1100)]:
        # (taking the carry here too would make the slowest path in the
        # machine: register -> fill -> B bus -> ALU -> carry flag)
        for cs in (None,):
            def f(a, r, cc, sg, rms=rms, rz=rz, cs=cs):
                s = _bit(a, 31)
                x = a ^ (M32 if s else 0)
                v = x >> 1 if rms == "shr" else _rot(x, rms) & _zmask(rz)
                return v, cc if cs is None else _bit(x, int(cs[1:-1])) ^ s, s
            kw = dict(b="fillall", fill="a31", ldsgn=1, alu="xor", rms=rms, rz=rz)
            if rms == "shr":
                kw["sin"] = "0"
            if cs:
                kw["fc"] = cs
            out.append((f"X{rms}/{rz:04b}/{cs}", False, mi(**kw), f))
    return out


def _xor_later():
    out = []
    for rms, rz in [("ror8", 0b1000), ("ror8", 0b1100), ("ror8", 0b1110), ("ror16", 0b1100),
                    ("ror16", 0b1110)]:
        for cs in (None, "f7x", "f15x"):
            def f(a, r, cc, sg, rms=rms, rz=rz, cs=cs):
                return _rot(a, rms) & _zmask(rz), cc if cs is None else _bit(a, int(cs[1:-1])) ^ sg, sg
            kw = dict(alu="passa", rms=rms, rz=rz, fill="sgn")
            if cs:
                kw["fc"] = cs
            out.append((f"XB{rms}/{rz:04b}/{cs}", False, mi(**kw), f))
    out.append(("XBsr1", False, mi(alu="passa", rms="shr", sin="0"),
                lambda a, r, cc, sg: (a >> 1, cc, sg)))
    return out


_UNXOR = mi(a="r", b="fillall", fill="sgn", alu="xor")


def _useful(kind, label):
    """Steps worth trying for each kind of shift (keeps the search small)."""
    if label.startswith("sr1/"):
        return label == "sr1/" + {0: "", 1: "0", 2: "f31", 3: "f0"}[kind]
    if label in ("sl1", "sl2"):
        return kind == 0
    if label in ("rl1", "rl2"):
        return kind == 3
    rms, rz, cs = label.split("/")
    if kind == 3:
        return rz == "0000"
    if kind == 2:
        return False                    # arithmetic shifts use the XOR steps
    if kind == 1:                       # LSR clears high bytes
        return rms != "f" and rz in ("0000", "1000", "1100", "1110")
    return rz in ("0000", "0001", "0011", "0111")


def _exec_plan(prog, x, cin):
    """Run a shift plan on one value with the same step semantics the RTL
    model uses (tmc.hw.rtl_v1b) and return (value, carry)."""
    from .rtl_v1b import alu32
    r, cc, sgn = 0, cin, 0
    for i, f in enumerate(prog):
        if f.get("ARF"):
            a = x
        elif f.get("AR2"):
            a = ((r << 1) | ((r >> 31) if f.get("SINA") == SINA["r31"] else 0)) & M32
        else:
            a = r
        fsel = f.get("FSEL", 0)
        fill = {0: 0, 5: a >> 31, 7: sgn}[fsel]
        b = M32 if (f.get("BF23") and fill) else 0
        cin_v = {0: 0, 1: 1, 3: a >> 31}[f.get("CIN", 0)]
        F, c32 = alu32(a, b, f.get("S", 0), f.get("M", 0), cin_v)
        rms = f.get("RMS", 0)
        if rms == 1:
            sin = {0: 0, 1: F >> 31, 3: F & 1}[f.get("SIN", 0)]
            res = (F >> 1) | (sin << 31)
        else:
            res = _rot(F, ["f", "", "ror8", "ror16"][rms])
        res &= _zmask(f.get("RZ", 0))
        if f.get("FC") == FC["aluc"]:
            cc = c32
        elif f.get("FC"):
            cs = f["CSRC"]
            cc = [None, F & 1, F >> 7 & 1, F >> 8 & 1, F >> 15 & 1, F >> 31,
                  (F >> 7 ^ fill) & 1, (F >> 15 ^ fill) & 1][cs]
        if f.get("LDSGN"):
            sgn = fill
        r = res
    return r, cc


def _verify(kind, n, prog, count=500):
    rng = random.Random(77 + 32 * kind + n)

    class _M:
        pass
    for i in range(count):
        x = rng.getrandbits(32) if i > 3 else (0, M32, 0x80000000, 0x7FFFFFFF)[i]
        cin = rng.getrandbits(1)
        m = _M()
        m.c, m.v = cin, 0
        want = (c.shift(m, kind, x, n), m.c)
        if _exec_plan(prog, x, cin) != want:
            return False
    return True


def plan_shift(kind, n):
    """Shortest step sequence for an immediate shift (kind 0 LSL, 1 LSR,
    2 ASR, 3 ROR; 1 <= n <= 31). The first step reads rd from the register
    file; later ones work on R. Returns a list of mi dicts."""
    rng = random.Random(1000 + 32 * kind + n)
    tests = [rng.getrandbits(32) for _ in range(20)] + [0x80000000, 0x7FFFFFFF, 1, M32]
    cins = [rng.getrandbits(1) for _ in tests]

    class _M:
        pass

    def ref(x, cin):
        m = _M()
        m.c, m.v = cin, 0
        return c.shift(m, kind, x, n), m.c
    goal = tuple(ref(x, ci) for x, ci in zip(tests, cins))
    plain = [st for st in _plain_steps() if _useful(kind, st[0])]
    xlater = _xor_later()

    def run(states, fn, first):
        out = []
        for x, (v, cc, sg) in zip(tests, states):
            a = x if first else v
            out.append(fn(a, v, cc, sg))
        return tuple(out)

    def result(states):
        return tuple((v, cc) for v, cc, sg in states)

    start = tuple((x, ci, 0) for x, ci in zip(tests, cins))
    frontier = []
    seen = set()
    for lab, needs_r, f, fn in plain:
        if needs_r:
            continue
        st = run(start, fn, True)
        if (st, 0) not in seen:
            seen.add((st, 0))
            frontier.append((st, 0, [merge(f, mi(ra="d"))]))
    if kind == 2:
        for lab, needs_r, f, fn in _xor_first():
            st = run(start, fn, True)
            if (st, 1) not in seen:
                seen.add((st, 1))
                frontier.append((st, 1, [merge(f, mi(ra="d"))]))
    for depth in range(1, 12):
        for st, inx, prog in frontier:
            if not inx and result(st) == goal and _verify(kind, n, prog):
                return prog
            if inx:     # finish with the XOR back
                fin = tuple((v ^ (M32 if sg else 0), cc, sg) for v, cc, sg in st)
                if result(fin) == goal and _verify(kind, n, prog + [_UNXOR]):
                    return prog + [_UNXOR]
        nxt = []
        for st, inx, prog in frontier:
            steps = xlater if inx else plain
            for lab, needs_r, f, fn in steps:
                nst = run(st, fn, False)
                key = (nst, inx)
                if key in seen:
                    continue
                seen.add(key)
                g = f if f.get("AR2") else merge(f, mi(a="r"))
                nxt.append((nst, inx, prog + [g]))
        frontier = nxt
    raise RuntimeError(f"no shift plan for kind {kind} n {n}")


_PLAN_CACHE = None


def _plan_cache_path():
    import os
    return os.path.join(os.path.dirname(__file__), "..", "..", "build", "shiftplans-v1b.json")


def _planner_source():
    """Everything plan_shift()'s results depend on, as text: the source of
    every function in this module it reaches by name, directly or through
    other functions, and the values of the tables they read; cached_plan();
    and the whole of tmc/isa/v1common.py (the reference semantics) and
    tmc/hw/rtl_v1b.py (the ALU model). Editing anything else here, the
    routines or the listings, keeps the cached plans."""
    import inspect
    import types
    from . import rtl_v1b
    g = globals()
    parts = [inspect.getsource(cached_plan), inspect.getsource(c), inspect.getsource(rtl_v1b)]
    todo, seen = ["plan_shift"], set()
    while todo:
        name = todo.pop()
        if name in seen or name not in g:
            continue                    # builtins, attribute names, locals
        seen.add(name)
        obj = g[name]
        if isinstance(obj, types.ModuleType):
            parts.append(inspect.getsource(obj) if obj.__name__.startswith("tmc.") else obj.__name__)
            continue
        if not isinstance(obj, (types.FunctionType, type)):
            parts.append(f"{name} = {obj!r}")
            continue
        parts.append(inspect.getsource(obj))
        funcs = [obj] if isinstance(obj, types.FunctionType) else \
            [getattr(v, "__func__", v) for v in vars(obj).values()]
        codes = [f.__code__ for f in funcs if isinstance(f, types.FunctionType)]
        while codes:                    # nested functions and lambdas too
            co = codes.pop()
            todo += co.co_names
            codes += [k for k in co.co_consts if isinstance(k, types.CodeType)]
    return "\n".join(parts)


def cached_plan(kind, n):
    """plan_shift() is a search (seconds per shift); plans are cached in
    build/, keyed by a hash of everything they depend on (_planner_source()),
    so they're redone when any of it changes."""
    global _PLAN_CACHE
    import hashlib
    import json
    import os
    path = _plan_cache_path()
    if _PLAN_CACHE is None:
        tag = hashlib.sha1(_planner_source().encode()).hexdigest()
        _PLAN_CACHE = {"tag": tag, "plans": {}}
        try:
            with open(path) as f:
                d = json.load(f)
            if d.get("tag") == tag:
                _PLAN_CACHE = d
        except (OSError, ValueError):
            pass
    key = f"{kind}/{n}"
    if key not in _PLAN_CACHE["plans"]:
        _PLAN_CACHE["plans"][key] = plan_shift(kind, n)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(_PLAN_CACHE, f)
        except OSError:
            pass
    return [dict(p) for p in _PLAN_CACHE["plans"][key]]


def shift_routine(kind, n):
    name = f"{c.SHIFT_FN[kind]} #{n}"
    wb = end(name, wb="d", b="r", fnz="nz", fv="0")
    if n == 0:
        return chain(name, mi(ra="d", alu="passa", ldr=1), wb)
    steps = [merge(s, mi(ldr=1)) for s in cached_plan(kind, n)]
    return chain(name, *steps, wb)


def shift_reg_routine(kind):
    """Shift by a register: LC <- 255 - (rs & 31), then one bit per cycle."""
    name = f"{c.SHIFT_FN[kind]} reg"
    wb = end(name, wb="d", b="r", fnz="nz", fv="0")
    if kind == 0:
        step = mi(a="r", alu="dbl", cin="0", fc="aluc")
    else:
        step = mi(a="r", alu="passa", rms="shr", sin={1: "0", 2: "f31", 3: "f0"}[kind], fc="f0")
    body = loop(name, merge(step, mi(ldr=1, lcinc=1)), "tc", wb)
    # the loop test sees LC before that iteration's count, so count once on
    # the way in (the test there, before its count, catches a zero count)
    return chain(name, mi(ra="s", kv=0xE0 - 256, alu="ornb", ldlc=1),
                 branch(name, mi(ra="d", alu="passa", ldr=1, lcinc=1), "tc", body, wb))


def rr_routine(fn):
    name = v1b.RR_FN[fn]
    if name in ("ADC", "SBC"):
        return chain(name, mi(ra="d", rb="s", alu=name.lower(), fc="aluc", fv="ovf", ldr=1),
                     end(name, wb="d", b="r", fnz="sticky"))
    if name == "BIC":
        return chain(name, mi(ra="d", rb="s", alu="bic", ldr=1), end(name, wb="d", b="r", fnz="nz"))
    if name == "TST":
        return chain(name, mi(ra="d", rb="s", alu="and", ldr=1), end(name, b="r", fnz="nz"))
    if name == "MULU":
        # shift-and-add, multiplier in MQ, high half of the product in R
        step = mi(a="r", rb="d", md="mulu", rms="shr", ldr=1, lcinc=1)
        tail32 = chain(name, mi(wb=HI, b="r", ldcl="zero"),
                       end(name, wb="d", b="mq", fnz="nz", fc="ncl", fv="ncl"))
        # a multiplier below 2^16 needs 16 steps; then R = P >> 16 and
        # MQ = {P[15:0], 0}: the low word is ror16((R & 0xFFFF) | MQ)
        small = chain(name, mi(a="r", b="mq", alu="or", rms="ror16", ldr=1), mi(wb=HI, kv=0),
                      end(name, wb="d", b="r", fnz="nz", czero=1, fv="0"))
        general = chain(name, mi(ra=TMP1, alu="passa", rms="ror16", rz=0b1100, ldr=1),
                        mi(wb=HI, b="r", ldcl="zero"),
                        mi(ra=TMP1, alu="passa", rz=0b1100, ldr=1),
                        mi(a="r", b="mq", alu="or", rms="ror16", ldr=1),
                        end(name, wb="d", b="r", fnz="nz", fc="ncl", fv="ncl"))
        # CL: both operands below 2^16 (the product's high word is then 0)
        exit16 = branch(name, mi(wb=TMP1, b="r"), "cl", general, small)
        return chain(name, mi(rb="s", md="mqload", ra=KC1, alu="passa", ldlc=1, ldcl="hz16"),
                     branch(name, mi(ra=0, rb="d", md="mulu", rms="shr", ldr=1, ldcl="and_hz16"),
                            "cl", loop(name, step, "tc", tail32), loop(name, step, "tc4", exit16)))
    if name == "MULS":
        # the same loop with a signed accumulator (shifting in the sum's true
        # sign), subtracting X in the last step: the multiplier's top bit
        # weighs -2^31 (or -2^15)
        step = mi(a="r", rb="d", md="mulu", rms="shr", sin="f31", ldr=1, lcinc=1)
        last = mi(a="r", rb="d", md="muls", rms="shr", sin="f31", ldr=1)
        # overflow iff HI isn't the sign extension of the low word, i.e.
        # HI + (bit 31 of the low word) != 0
        tail32 = chain(name, last, mi(wb=HI, b="r", alu="a", cin="mq31", ldr=1),
                       mi(b="r", ldcl="zero"),
                       end(name, wb="d", b="mq", fnz="nz", fc="ncl", fv="ncl"))
        big = chain(name, mi(rb="s", md="mqload", ra=0, alu="passa", ldr=1),
                    loop(name, step, "tc", tail32))
        # both operands fit in 16 bits: 16 steps on the multiplier's low half,
        # and the product fits in 32 bits, so HI is its sign
        small16 = chain(name, last, mi(a="r", alu="passa", rz=0b1100, ldr=1),
                        mi(a="r", b="mq", alu="or", rms="ror16", ldr=1),
                        mi(wb="d", b="r", fnz="nz", fill="a31", ldsgn=1),
                        end(name, wb=HI, b="fillall", fill="sgn", czero=1, fv="0"))
        small = loop(name, step, "tc4", small16)
        # x fits in 16 bits as a signed number iff x ^ (32 copies of its sign)
        # is below 2^15
        return chain(name,
                     mi(ra="d", b="fillall", fill="a31", alu="xor", ldr=1),
                     mi(b="r", ldcl="hz17", ra=KC1, alu="passa", ldlc=1),
                     mi(ra="s", b="fillall", fill="a31", alu="xor", ldr=1),
                     mi(b="r", ldcl="and_hz17", ra="s", alu="passa", rz=0b1100, ldr=1),
                     # MQ <- the multiplier's low half (reloaded whole if too
                     # big), R <- 0 (the accumulator)
                     branch(name, mi(b="r", md="mqload", ra=0, alu="passa", ldr=1), "cl",
                            big, small))
    # divides: non-restoring, partial remainder in R (sign in S33), quotient
    # bits shifted into MQ
    divz = trap(c.DIV_VECTOR, 2)
    if name in ("DIVU", "DIVUL"):
        out = chain(name, mi(a="r", rb="s", md="fix", ldr=1), mi(wb=HI, b="r"),
                    end(name, wb="d", b="mq", fnz="nz", czero=1, fv="0"))
        body = loop(name, mi(a="r2", sina="mq31", rb="s", md="div", ldr=1, lcinc=1), "tc", out)
        if name == "DIVU":
            return chain(name, mi(rb="s", ldcl="zero", ra=KC0, alu="passa", ldlc=1),
                         branch(name, mi(rb="d", md="mqload", ra=0, alu="passa", ldr=1), "cl",
                                body, divz))
        ovf = end(name, fv="1")
        return chain(name, mi(rb="s", ldcl="zero", ra=KC0, alu="passa", ldlc=1),
                     branch(name, mi(ra=HI, rb="s", alu="sub", ldcl="aluc"), "cl",
                            branch(name, mi(rb="d", md="mqload", ra=HI, alu="passa", ldr=1), "cl",
                                   body, ovf),
                            divz))
    if name == "DIVS":
        quot = chain(name,
                     mi(a="r", b="fillall", fill="sgn", alu="xor", ldr=1),
                     mi(a="r", alu="a", cin="sgn", ldr=1),            # remainder, sign of rd
                     mi(wb=HI, b="r"),
                     mi(ra="d", rb="s", alu="xor", ldr=1),
                     mi(a="r", fill="a31", ldsgn=1, b="mq", alu="passb", ldr=1),
                     mi(a="r", b="fillall", fill="sgn", alu="xor", ldr=1),
                     mi(a="r", alu="a", cin="sgn", ldr=1),            # quotient
                     end(name, wb="d", b="r", fnz="nz", czero=1, fv="0"))
        # |rd| = 2^31 and |rs| = 1: quotient 0x80000000 either way, V if the
        # signs were equal
        special = chain(name, mi(ra="d", rb="s", alu="xor", ldr=1),
                        branch(name, mi(wb=HI, kv=0), "r31",
                               end(name, wb="d", b="mq", fnz="nz", czero=1, fv="1"),
                               end(name, wb="d", b="mq", fnz="nz", czero=1, fv="0")))
        out = branch(name, mi(a="r", rb=TMP1, md="fix", ldr=1), "mq31", quot, special)
        body = loop(name, mi(a="r2", sina="mq31", rb=TMP1, md="div", ldr=1, lcinc=1), "tc", out)
        return chain(name,
                     mi(ra="s", b="fillall", fill="a31", ldsgn=1, alu="xor", ldr=1),
                     mi(a="r", alu="a", cin="sgn", ldr=1),            # |rs|
                     mi(wb=TMP1, b="r", ldcl="zero"),
                     branch(name, mi(ra="d", b="fillall", fill="a31", ldsgn=1, alu="xor", ldr=1),
                            "cl",
                            chain(name, mi(a="r", alu="a", cin="sgn", ldr=1),     # |rd|
                                  mi(b="r", md="mqload", ra=KC0, alu="passa", ldlc=1),
                                  mi(ra=0, alu="passa", ldr=1),
                                  body),
                            divz))
    raise ValueError(name)


def save_routine(a, b):
    n = b - a + 1
    name = f"SAVE r{a}-r{b}"
    steps = [sp_minus(4 * n)]
    for i in range(a, b + 1):
        if i > a:
            steps.append(mi(ra=SP, kv=4 * (i - a) - 4 * n, alu="add", ldmar=1))
        steps.append(mi(ra=i, alu="passa", mem="wrlo", size="word"))
        steps.append(mi(ra=i, alu="passa", mem="wrhi"))
    return chain(name, *steps, end(name, wb=SP, b="r"))


def restore_routine(a, b):
    n = b - a + 1
    name = f"RESTORE r{a}-r{b}"
    steps = [mi(ra=SP, marsrc="a", ldmar=1, kv=4 * n, alu="add", ldr=1)]
    for i in range(a, b + 1):
        # the previous register is written from T while its successor's low
        # half is read into T; the next address is computed during the
        # high-half read (the ALU is idle in bus cycles)
        wb = mi(wb=i - 1, b="t") if i > a else {}
        steps.append(merge(mi(mem="rdlo", size="word" if i == a else None), wb))
        nxt = mi(ra=SP, kv=4 * (i - a + 1), alu="add", ldmar=1) if i < b else {}
        steps.append(merge(mi(mem="rdhi"), nxt))
    steps.append(mi(wb=b, b="t"))
    return chain(name, *steps, end(name, wb=SP, b="r"))


def sys_routine(fn, a, b):
    name = c.SYS_FN[fn]
    if name == "NOP":
        return end(name)
    if name == "HALT":
        return Node({}, ("halt",), name)
    if name == "JMP":
        return chain(name, mi(rb="s", alu="passb", ldpc=1), end(name))
    if name == "CALL":
        return op_tail("CALL", {"rb": "s"}, name)
    if name == "RET":
        return chain(name, mi(ra=SP, marsrc="a", ldmar=1, kv=4, alu="add", ldr=1),
                     mi(mem="rdlo", size="word"),
                     mi(mem="rdhi", wb=SP, b="r"),
                     mi(b="t", alu="passb", ldpc=1), end(name))
    if name == "RTI":
        return chain(name, mi(ra=SP, marsrc="a", ldmar=1, kv=8, alu="add", ldr=1),
                     mi(mem="rdlo", size="word"),                    # flags word
                     mi(ra=SP, kv=4, alu="add", ldmar=1),
                     mi(mem="rdlo", b="t", loadf=1),                 # PC low; flags from T
                     mi(mem="rdhi", wb=SP, b="r"),
                     mi(b="t", alu="passb", ldpc=1), end(name))
    if name in ("EI", "DI"):
        return end(name, fi="1" if name == "EI" else "0")
    if name == "MFSR":
        if b == 0:
            return end("MFF", wb="d", b="flags")
        return chain("MFHI", mi(rb=HI, alu="passb", ldr=1), end("MFHI", wb="d", b="r"))
    if name == "MTSR":
        if a == 0:
            return end("MTF", rb="s", loadf=1)
        return chain("MTHI", mi(rb="s", alu="passb", ldr=1), end("MTHI", wb=HI, b="r"))
    if name == "SWI":
        return trap(c.SWI_VECTOR, 0)
    if name == "SET":
        return branch("SETcc", mi(ccb=1), "ncondt" if b else "condt",
                      end("SETcc", wb="d", kv=0), end("SETcc", wb="d", kv=1))
    if name == "SAVE":
        return save_routine(a, b)
    if name == "RESTORE":
        return restore_routine(a, b)
    raise ValueError(name)


def jcc_routine(kind, k, pol):
    """op A: kind 'cond' / 'jmp' / 'call'; k 0 relative, 1 absolute; pol is
    the condition's polarity bit."""
    name = {"cond": "Jcc", "jmp": "JMP", "call": "CALL"}[kind] + (" rel" if k == 0 else " abs")
    cond = "ncondt" if pol else "condt"
    if k == 0:
        add = mi(a="pc", b="t2", fill="t15", alu="add", ldpc=1)     # PC + 2 * offset
        if kind == "cond":
            return branch(name, FETCH_EXT, cond, end(name), chain(name, add, end(name)))
        if kind == "jmp":
            return chain(name, FETCH_EXT, add, end(name))
        return chain(name, merge(FETCH_EXT, sp_minus(4)), *push_pc(), add,
                     end(name, wb=SP, b="r"))
    load = mi(b="t", alu="passb", ldpc=1)
    if kind == "cond":
        return chain(name, FETCH_EXT,
                     branch(name, mi(mem="exthi"), cond, end(name), chain(name, load, end(name))))
    if kind == "jmp":
        return chain(name, FETCH_EXT, mi(mem="exthi"), load, end(name))
    return chain(name, merge(FETCH_EXT, sp_minus(4)), mi(mem="exthi"), *push_pc(), load,
                 end(name, wb=SP, b="r"))


def bcc_routine(link):
    add = mi(a="pc", b="simm", v8="bcc", fill="ir7", alu="add", ldpc=1)
    if not link:
        return chain("Bcc", merge(add, mi(pccond=1)), end("Bcc"))
    return chain("BSR", sp_minus(4), *push_pc(), add, end("BSR", wb=SP, b="r"))


# --------------------------------------------------------------------------
# Decode: which routine runs for each first parcel

def classify(w):
    """Routine key for an instruction's first parcel."""
    op, d, M, R = w >> 12, (w >> 8) & 15, (w >> 4) & 15, w & 15
    if op == 0:
        f, a, b = R, d, M
        if f >= len(c.SYS_FN):
            return ("illegal",)
        name = c.SYS_FN[f]
        if name in ("SAVE", "RESTORE"):
            return ("sys", f, a, b) if 1 <= a <= b <= 14 else ("illegal",)
        if name == "MFSR":
            return ("sys", f, 0, b) if b in c.SR_NAMES else ("illegal",)
        if name == "MTSR":
            return ("sys", f, a, 0) if a in c.SR_NAMES else ("illegal",)
        if name == "SET":
            return ("sys", f, 0, b & 1) if b != 15 else ("illegal",)
        return ("sys", f, 0, 0)
    if op == 0xC:
        return ("un", R) if R < len(c.UN_FN) else ("illegal",)
    if op == 0xD:
        t = R >> 2
        if t == 3:
            return ("illegal",)
        if t == 2:
            return ("shreg", R & 3)
        return ("shift", R & 3, M + 16 * t)
    if op == 0xE:
        return ("bcc", int(d == 15))
    if op == 0xA:
        if M > 1 or R:
            return ("illegal",)
        if d >= 14:
            return ("jcc", "call" if d == 15 else "jmp", M, 0)
        return ("jcc", "cond", M, d & 1)
    if op == 0xF:
        return ("rr", R) if R < len(v1b.RR_FN) else ("illegal",)
    # EA instructions
    if M == 0xE or (M == 0xF and R >= 0xD):
        return ("illegal",)
    mem = is_mem(M, R) or M == 5
    if op == 0xB:
        if d > 1 or (mem and M != 5 and mode_size(M, R) != 4):
            return ("illegal",)
    if op == 2 and not mem:
        return ("illegal",)
    if op == 3 and (not mem or M in (6, 7, 0xA)):
        return ("illegal",)
    sub = R if M in (1, 4, 0xD, 0xF) else None
    return ("ea", op, d if op == 0xB else None, M, sub)


def routine(key):
    kind = key[0]
    if kind == "illegal":
        return illegal(2)
    if kind == "sys":
        return sys_routine(*key[1:])
    if kind == "un":
        return unary_routine(key[1])
    if kind == "shift":
        return shift_routine(key[1], key[2])
    if kind == "shreg":
        return shift_reg_routine(key[1])
    if kind == "bcc":
        return bcc_routine(key[1])
    if kind == "jcc":
        return jcc_routine(*key[1:])
    if kind == "rr":
        return rr_routine(key[1])
    if kind == "ea":
        _, op, k, M, sub = key
        return ea_routine(op, k, M, sub if sub is not None else 0)
    raise ValueError(key)


def reset_routine():
    zero = mi(kv=0)
    steps = [merge(zero, mi(wb=0, wr0=1, loadf=1)), merge(zero, mi(wb=HI))]
    for loc, val in RF_CONSTS.items():
        steps.append(mi(wb=loc, kv=val - 256 if val > 127 else val))
    return chain("reset", *steps, end("reset"))


# --------------------------------------------------------------------------
# Placement

IRQP_BIT = Y_BITS               # ROM address bits above Y
FAULT_BIT = Y_BITS + 1          # FAULT, then FAULT & LEN0, FAULT & LEN1


def fault_page(ln):
    """ROM address of the address error entry for instruction length ln."""
    return (1 << FAULT_BIT) | (ln << (FAULT_BIT + 1))


def _successors(n):
    s = n.succ
    if s[0] == "next":
        return [s[1]]
    if s[0] == "branch":
        return [s[2], s[3]]
    if s[0] == "dispatch":
        return list(s[1])
    return []


def _reachable(roots):
    seen, order, stack = set(), [], list(roots)
    while stack:
        n = stack.pop()
        if id(n) in seen:
            continue
        seen.add(id(n))
        order.append(n)
        stack.extend(_successors(n))
    return order


def _assign_slots(roots):
    """Branch pairs and dispatch tables need their members at fixed offsets
    from each other. Members are grouped; a node wanted in two different
    groups (or at a fixed address) is cloned."""
    groups = {}             # gid -> kind
    work = _reachable(roots)
    done = set()
    while work:
        n = work.pop()
        if id(n) in done:
            continue
        done.add(id(n))
        s = n.succ
        if s[0] == "branch":
            members, kind = [s[2], s[3]], "pair"
        elif s[0] == "dispatch":
            members, kind = list(s[1]), "table"
        else:
            continue
        g0 = members[0].slot[0] if members[0].slot else None
        if g0 is not None and all(m.slot == (g0, i) for i, m in enumerate(members)):
            continue                                  # an existing group fits
        gid = len(groups)
        groups[gid] = kind
        new = []
        for i, m in enumerate(members):
            if m.slot is not None or m.fixed is not None or any(m is x for x in new):
                m = m.clone()
                work.append(m)
            m.slot = (gid, i)
            new.append(m)
        if kind == "pair":
            n.succ = ("branch", s[1], new[0], new[1])
        else:
            n.succ = ("dispatch", new)
    return groups


def _dedup(nodes, keep):
    """Merge identical free-standing nodes (same fields, same successors).
    Nodes in `keep` (entry points) are never replaced."""
    while True:
        canon = {}
        rep = {}
        for n in nodes:
            if n.slot is not None or n.fixed is not None or n.succ[0] in ("branch", "dispatch"):
                continue
            key = (tuple(sorted(n.f.items())), n.succ[0], tuple(id(x) for x in _successors(n)))
            if key in canon:
                if id(n) in keep:
                    if id(canon[key]) in keep:
                        continue
                    rep[id(canon[key])] = n
                    canon[key] = n
                else:
                    rep[id(n)] = canon[key]
            else:
                canon[key] = n
        if not rep:
            return nodes

        def r(x):
            while id(x) in rep:
                x = rep[id(x)]
            return x
        for n in nodes:
            s = n.succ
            if s[0] == "next":
                n.succ = ("next", r(s[1]))
            elif s[0] == "branch":
                n.succ = ("branch", s[1], r(s[2]), r(s[3]))
            elif s[0] == "dispatch":
                n.succ = ("dispatch", [r(x) for x in s[1]])
        nodes = [n for n in nodes if id(n) not in rep]


class Microcode:
    """Placed microcode: ROM contents, decode ROM, entry points."""

    def __init__(self):
        _trap_cache.clear()
        self.reset = reset_routine()
        self.reset.fixed = 0
        self.faults = {}
        for ln in range(4):
            node = trap(c.ADDR_VECTOR, 2 * max(ln, 1)).clone()
            node.fixed = "fault"            # word 0 of a fault page, outside Y space
            self.faults[ln] = node
        self.irq = trap(c.IRQ_VECTOR, 0)
        self.keys = {}
        self.entry = {}
        for w in range(0x10000):
            k = classify(w)
            self.keys[w] = k
            if k not in self.entry:
                self.entry[k] = routine(k)
        roots = [self.reset, *self.faults.values(), self.irq, *self.entry.values()]
        self.groups = _assign_slots(roots)
        nodes = _reachable(roots)
        nodes = _dedup(nodes, {id(n) for n in roots})
        nodes = _reachable(roots)
        self.nodes = nodes
        self._place()
        self._check()

    def _place(self):
        size = 1 << Y_BITS
        used = [None] * size
        for n in self.nodes:
            if n.fixed == "fault":
                n.addr = -1
            elif n.fixed is not None:
                n.addr = n.fixed
                used[n.addr] = n
        # tables (32-aligned) from the top, pairs and singles from the bottom
        groups = defaultdict(list)
        for n in self.nodes:
            if n.slot is not None:
                groups[n.slot[0]].append(n)
        top = size
        for gid, members in groups.items():
            if self.groups[gid] != "table":
                continue
            top -= 32
            for m in members:
                m.addr = top + m.slot[1]
                assert used[m.addr] is None
                used[m.addr] = m
        pos = 0
        for gid, members in groups.items():
            if self.groups[gid] != "pair":
                continue
            while used[pos] is not None or used[pos + 1] is not None:
                pos += 2
            for m in members:
                m.addr = pos + m.slot[1]
                used[m.addr] = m
            pos += 2
        free = (a for a in range(size) if used[a] is None)
        for n in self.nodes:
            if n.addr is None:
                n.addr = next(free)
                used[n.addr] = n
        self.used = sum(1 for u in used if u is not None)
        if any(n.addr >= top for n in self.nodes
               if n.slot is None or self.groups[n.slot[0]] != "table"):
            raise RuntimeError("microcode doesn't fit")
        self.by_addr = used

    def word(self, n, irq=False):
        """Field dict of node n as stored at its address (IRQP = irq)."""
        f = dict(n.f)
        s = n.succ
        if s[0] == "next":
            assert s[1].addr >= 0
            f["SEQ"], f["NEXT"] = SEQ_NEXT, s[1].addr
        elif s[0] == "branch":
            a0, a1 = s[2].addr, s[3].addr
            assert a0 >= 0 and a0 % 2 == 0 and a1 == a0 + 1, n.name
            f["SEQ"], f["NEXT"], f["COND"] = SEQ_NEXT, a0, s[1]
        elif s[0] == "decode":
            f["SEQ"] = SEQ_DECODE
        elif s[0] == "dispatch":
            base = s[1][0].addr
            assert base % 32 == 0
            f["SEQ"], f["NEXT"] = SEQ_DISPATCH, base
        elif s[0] == "halt":
            f["SEQ"], f["NEXT"], f["HALT"] = SEQ_NEXT, n.addr, 1
        if irq:
            if s[0] == "decode":
                for k in ("MEMRD", "LDIR", "ADDRMAR"):
                    f.pop(k, None)
                f["GOIRQ"] = 1
            elif s[0] == "halt":
                f = {"SEQ": SEQ_DECODE, "GOIRQ": 1}
        return f

    def _check(self):
        for n in self.nodes:
            f = n.f
            if f.get("SIZE", 0) >= 2:
                # an address error must leave the machine as it was
                for k in ("LDPC", "FNZ", "FC", "CZERO", "FV", "FI", "RFWE"):
                    if f.get(k):
                        raise ValueError(f"{n.name}: {k} in a checked memory access")
            if f.get("RFWE"):
                if f.get("RFA") != f.get("RFB") or f.get("ARF") or f.get("BRF"):
                    raise ValueError(f"{n.name}: bad register write")
            if f.get("LDPC") and f.get("MEMRD") and not f.get("ADDRMAR"):
                raise ValueError(f"{n.name}: PC load during a fetch")

    def rom(self):
        """{ROM address: control word} for both IRQP halves."""
        out = {}
        for n in self.nodes:
            if n.fixed == "fault":
                continue
            out[n.addr] = pack(self.word(n))
            out[(1 << IRQP_BIT) | n.addr] = pack(self.word(n, irq=True))
        for ln, n in self.faults.items():
            out[fault_page(ln)] = pack(self.word(n))
            out[fault_page(ln) | (1 << IRQP_BIT)] = pack(self.word(n, irq=True))
        return out

    def decode_rom(self):
        """Decode ROM contents: address {GOIRQ, parcel} -> Y | LEN << Y_BITS."""
        img = [0] * (1 << 17)
        for w in range(0x10000):
            ln = v1b.size_of(w) if self.keys[w][0] != "illegal" else 1
            img[w] = self.entry[self.keys[w]].addr | (ln << Y_BITS)
        for w in range(0x10000):
            img[0x10000 | w] = self.irq.addr
        return img


IDLE = pack(mi())

_built = None


def built():
    global _built
    if _built is None:
        _built = Microcode()
    return _built


def rom_images():
    """15 microcode ROM images and 2 decode ROM images (bytes, 128K each)."""
    mc = built()
    rom = mc.rom()
    size = 1 << ROM_ADDR_BITS
    imgs = [bytearray(size) for _ in range(ROMS)]
    idle = IDLE
    for a in range(size):
        w = rom.get(a, idle)
        for k in range(ROMS):
            imgs[k][a] = (w >> (8 * k)) & 0xFF
    dec = mc.decode_rom()
    dimgs = [bytearray(size), bytearray(size)]
    for a, v in enumerate(dec):
        dimgs[0][a] = v & 0xFF
        dimgs[1][a] = v >> 8
    return imgs, dimgs


def describe_word(f):
    """Short text for a field dict (for listings)."""
    parts = []
    for name, (_, w, _) in _pos.items():
        v = f.get(name, 0)
        if v and name not in ("NEXT",):
            parts.append(name if w == 1 else f"{name}={v}")
    return " ".join(parts)


# --------------------------------------------------------------------------
# Listings

_RF_NAMES = {SP: "sp", HI: "HI", TMP1: "TMP1", KC1: "24 = 0xE1", KC0: "25 = 0xE0"}
_ALU_NAMES = {
    (0, 0b1001): "A+B", (0, 0b0110): "A-B-1", (0, 0b0000): "A", (0, 0b1111): "A-1",
    (0, 0b1100): "A+A", (1, 0b1011): "A&B", (1, 0b1110): "A|B", (1, 0b0110): "A^B",
    (1, 0b0111): "A&~B", (1, 0b1111): "A", (1, 0b1010): "B", (1, 0b0000): "~A",
    (1, 0b0011): "0", (1, 0b1000): "A|~B",
}
_CIN_NAMES = {v: k for k, v in CIN.items()}
_FILL_NAMES = {v: k for k, v in FSEL.items()}
_CLSRC_NAMES = {v: k for k, v in CLSRC.items()}
_CSRC_NAMES = {0: "B[1]", 1: "F0", 2: "F7", 3: "F8", 4: "F15", 5: "F31", 6: "F7^fill",
               7: "F15^fill"}
_SIN_NAMES = {v: k for k, v in SIN.items()}
_COND_NAMES = {v: k for k, v in CONDS.items()}
_STEP_NAMES = {(1, 1): "multiply step: R + B if MQ[0]", (1, 2): "multiply step: R - B if MQ[0]",
               (2, 3): "divide step", (0, 3): "divide fix-up: R + B if S33"}


def _rf_name(f, side):
    sel = f.get(side, 0)
    if sel == 3:
        k = f.get("RFK", 0)
        return _RF_NAMES.get(k, f"r{k}")
    return ("d", "r", "s")[sel]


def explain(f):
    """Readable summary of a microinstruction's field dict (without sequencing)."""
    out = []
    # what the B bus carries
    b = []
    if f.get("BRF"):
        b.append(f"rf[{_rf_name(f, 'RFB')}]")
    if f.get("BR"):
        b.append("R")
    if f.get("BMQ"):
        b.append("MQ")
    if f.get("BFL"):
        b.append("flags")
    if f.get("BT2"):
        b.append("2*T.lo")
    if f.get("BT0") and f.get("BT1") and f.get("BT23"):
        b.append("T")
    elif f.get("BT0") and f.get("BT1") and f.get("BF23") and not f.get("TLANE"):
        b.append(f"T.lo, upper half fill({_FILL_NAMES[f.get('FSEL', 0)]})")
    else:
        if f.get("BT0"):
            b.append("T byte (MAR[0])" if f.get("TLANE") else "T[7:0]")
        if f.get("BT1"):
            b.append("T[15:8]")
        if f.get("BT23"):
            b.append("T[31:16]")
    fill = _FILL_NAMES[f.get("FSEL", 0)]
    if f.get("BS0"):
        v8 = f.get("V8", 0)
        if v8 == V8["k"] and f.get("BF1") and f.get("BF23") and fill in ("0", "1"):
            k = f.get("KONST", 0)
            b.append(f"#{k - 256 if fill == '1' else k}")
        elif v8 == V8["fill"] and f.get("BF1") and f.get("BF23"):
            b.append(f"fill({fill})")
        else:
            b.append({0: "branch offset*2", 1: f"#{f.get('KONST', 0)} (byte 0)", 2: f"fill({fill})",
                      3: "LC"}[v8])
    if (f.get("BF1") or f.get("BF23")) and not (f.get("BS0") and f.get("BF1") and f.get("BF23")) \
            and not (f.get("BT0") and f.get("BT1") and not f.get("TLANE")):
        b.append(f"fill({fill}) above")
    if b:
        out.append("B=" + ", ".join(b))
    # A bus
    if f.get("ABR"):
        a = "A=B"
    elif f.get("ARF"):
        a = f"A=rf[{_rf_name(f, 'RFA')}]"
    elif f.get("APC"):
        a = "A=PC"
    elif f.get("AR"):
        a = "A=R"
    elif f.get("AR2"):
        a = f"A=2R+{[None, 'R31', 'C', 'MQ31'][f.get('SINA', 0)] or '0'}"
    else:
        a = None
    if a and not f.get("RFWE"):
        out.append(a)
    # ALU and result
    uses_alu = (f.get("LDR") or (f.get("LDMAR") and not f.get("MARSRC")) or f.get("LDPC")
                or f.get("LDLC") or f.get("DSRC") or f.get("MS") or f.get("FC") == FC["aluc"]
                or f.get("FV") == FV["ovf"] or (f.get("LDCL") and f.get("CLSRC") == CLSRC["aluc"])
                or f.get("FC") == FC["csrc"] and f.get("CSRC", 0) != CSRC["b1"])
    if uses_alu:
        ms, mqm = f.get("MS", 0), f.get("MQM", 0)
        if ms:
            alu = _STEP_NAMES.get((mqm, ms), "step")
        else:
            alu = _ALU_NAMES.get((f.get("M", 0), f.get("S", 0)), f"S={f.get('S', 0)}")
            cin = _CIN_NAMES[f.get("CIN", 0)]
            if f.get("M", 0) == 0 and cin != "0":
                if alu == "A-B-1":
                    alu = "A-B" if cin == "1" else f"A-B-1+{cin.upper()}"
                else:
                    alu += {"1": "+1", "c": "+C"}.get(cin, f"+{cin}")
        rms = f.get("RMS", 0)
        if rms == RMS["shr"]:
            sin = _SIN_NAMES[f.get("SIN", 0)]
            if (mqm == 1) and f.get("SIN", 0) == SIN["0"]:
                sin = "carry"
            elif mqm == 1:
                sin = "sign"
            alu = f"({alu}) >> 1 [{sin} in]"
        elif rms in (RMS["ror8"], RMS["ror16"]):
            alu = f"({alu}) ror {8 if rms == RMS['ror8'] else 16}"
        rz = f.get("RZ", 0)
        if rz:
            alu += " clear bytes " + "".join(str(i) for i in range(4) if rz >> i & 1)
        dests = []
        if f.get("LDR"):
            dests.append("R")
        if f.get("LDMAR") and not f.get("MARSRC"):
            dests.append("MAR")
        if f.get("LDPC"):
            dests.append("PC" + (" if cond" if f.get("PCCOND") else ""))
        if f.get("LDLC"):
            dests.append("LC")
        out.append((", ".join(dests) + " ← " if dests else "RES = ") + alu)
    if f.get("LDMAR") and f.get("MARSRC"):
        out.append("MAR ← A")
    if f.get("LCINC"):
        out.append("LC+1")
    # memory
    if f.get("MEMRD"):
        if not f.get("ADDRMAR"):
            if f.get("LDIR"):
                out.append("fetch: IR ← [PC], PC += 2")
            else:
                out.append(("T.hi" if f.get("LDTH") else "T.lo") + " ← [PC], PC += 2")
        else:
            out.append(("T.hi ← [MAR+2]" if f.get("HIWORD") else "T.lo ← [MAR]"))
    if f.get("MEMWR"):
        d = {DSRC["lo"]: "RES[15:0]", DSRC["hi"]: "RES[31:16]", DSRC["byte"]: "RES[7:0]"}
        out.append(("[MAR+2]" if f.get("HIWORD") else "[MAR]") + " ← " + d.get(f.get("DSRC", 0), "?"))
    if f.get("SIZE"):
        out.append(f"({[None, 'byte', 'half', 'word'][f['SIZE']]} access)")
    if f.get("LDX"):
        out.append("SX ← DBUS[15:12]")
    if f.get("RFWE"):
        out.append(f"rf[{_rf_name(f, 'RFA')}] ← B" + (" (r0 too)" if f.get("WR0") else ""))
    mqm = f.get("MQM", 0)
    if mqm == 3:
        out.append("MQ ← B")
    # flags and latches
    fnz = f.get("FNZ", 0)
    if fnz:
        out.append({1: "NZ", 2: "NZ (Z sticky)", 3: "flags ← B"}[fnz])
    if f.get("CZERO"):
        out.append("C ← 0")
    elif f.get("FC") and fnz != 3:
        fc = f["FC"]
        out.append("C ← " + {FC["aluc"]: "carry", FC["ncl"]: "!CL",
                             FC["csrc"]: _CSRC_NAMES[f.get("CSRC", 0)]}[fc])
    fv = f.get("FV", 0)
    if fv and fnz != 3:
        out.append("V ← " + {FV["ovf"]: "overflow", FV["0"]: "0", FV["1"]: "1", FV["b0"]: "B[0]",
                             FV["ncl"]: "!CL"}[fv])
    fi = f.get("FI", 0)
    if fi and fnz != 3:
        out.append("I ← " + {v: k for k, v in FI.items()}[fi])
    if f.get("LDCL"):
        out.append(f"CL ← {_CLSRC_NAMES[f.get('CLSRC', 0)]}")
    if f.get("LDSGN"):
        out.append("SGN ← fill")
    if f.get("CCB"):
        out.append("(condition from IR[7:4])")
    if f.get("GOIRQ"):
        out.append("decode → interrupt entry")
    if f.get("HALT"):
        out.append("halt")
    return "; ".join(out) if out else "(nothing)"


def describe_routine(entry):
    """Lines describing a routine: one per microinstruction, numbered in
    the order they're reached, with the sequencing."""
    order, index, stack = [], {}, [entry]
    while stack:
        n = stack.pop()
        if id(n) in index:
            continue
        index[id(n)] = len(order)
        order.append(n)
        s = n.succ
        if s[0] == "next":
            stack.append(s[1])
        elif s[0] == "branch":
            stack += [x for x in (s[3], s[2]) if x is not n]
    lines = []
    for i, n in enumerate(order):
        s = n.succ
        if s[0] == "next":
            j = index[id(s[1])]
            seq = "" if j == i + 1 else f" → {j}"
        elif s[0] == "branch":
            cond = _COND_NAMES[s[1]]
            if s[2] is n:
                seq = f" ↺ until {cond}, then → {index[id(s[3])]}"
            else:
                seq = f" → if {cond}: {index[id(s[3])]} else {index[id(s[2])]}"
        elif s[0] == "decode":
            seq = "   END"
        elif s[0] == "dispatch":
            seq = " → one of 32 routines, by the extension parcel"
        else:
            seq = " ↺ (until an interrupt)"
        lines.append(f"{i:>2}: {explain(n.f)}{seq}")
    return lines


LISTING_EXAMPLES = """
        NOP
        MOV   r1, #5
        ADD   r1, r2
        CMP   r1, r2
        ADD   r1, #1000
        MOV   r1, #70000
        MOV   r1, [r2 + 4]
        MOV   r1, byte [r2 + 1]
        ADD   r1, [r2]
        MOV   r1, [r2]+
        ST    r1, [r2 + 4]
        ST    r1, -[sp]
        LEA   r1, [r2 + r4*8 + 4]
        LSL   r1, #4
        ASR   r1, #8
        ROR   r1, #7
        LSL   r1, r4
        INC   r1
x:      BEQ   x
        JEQ   x
        BSR   x
        CALL  x
        CALL  r9
        RET
        SETEQ r1
        MULU  r1, r2
        MULS  r1, r2
        DIVU  r1, r2
        SAVE  r8-r11
        RESTORE r8-r11
        HALT
"""


def describe():
    """Markdown listing of representative routines."""
    from .. import asm as asmcore
    mc = built()
    img = asmcore.assemble_text(v1b, LISTING_EXAMPLES)
    L = ["# Draft 1b microcode: selected routines", "",
         "Generated by `python3 -m tmc --isa v1b ucode --doc`; don't edit by hand. The whole",
         f"microcode ({len(mc.nodes):,} microinstructions) is in `build/ucode-v1b/ucode.lst` after",
         "`python3 -m tmc --isa v1b ucode`. Field meanings are in",
         "[hardware-v1b.md](hardware-v1b.md) and `tmc/hw/ucode_v1b.py`.", "",
         "One line per clock cycle, numbered in the order they can run. `B=` is what",
         "drives the B bus, `rf[d]`, `rf[r]` and `rf[s]` are the registers named by the",
         "instruction's fields, `END` marks the last cycle, which fetches the next",
         "instruction (a register write in the same cycle is the write-back). Branches",
         "test a condition: `condt`/`ncondt` is the instruction's branch condition",
         "(per polarity), `tc` the loop counter at its end, `tc4` its low nibble,",
         "`cl` the condition latch.", ""]
    shown = set()

    def emit(title, node):
        L.append(f"**{title}**")
        L.append("")
        L.append("```")
        L.extend(describe_routine(node))
        L.append("```")
        L.append("")
    for st in img.stmts:
        if st.kind != "insn":
            continue
        key = classify(st.words[0])
        if key in shown:
            continue
        shown.add(key)
        text = " ".join(st.text.split(";")[0].split()).replace("x:", "").strip()
        node = mc.entry[key]
        emit(f"`{text}`", node)
        if node.succ[0] == "dispatch":
            ext = st.words[1]
            i = (((ext >> 8) & 15) << 1) | int(ext & 0xFF != 0)
            emit(f"`{text}`, after the dispatch (extension parcel {ext:04X})", node.succ[1][i])
    emit("Interrupt entry", mc.irq)
    emit("Address error (one-parcel instruction)", mc.faults[1])
    emit("Reset", mc.reset)
    return "\n".join(L)


def full_listing():
    """Every placed microinstruction: address, routine name, readable fields."""
    mc = built()
    lines = []
    for a, n in enumerate(mc.by_addr):
        if n is None:
            continue
        f = mc.word(n)
        lines.append(f"{a:03X} {pack(f):030X} {n.name:<22} {explain(n.f)}"
                     f" [{'END' if n.succ[0] == 'decode' else 'SEQ=%d NEXT=%03X COND=%d' % (f.get('SEQ', 0), f.get('NEXT', 0), f.get('COND', 0))}]")
    return "\n".join(lines) + "\n"


def cmd_ucode(args):
    import os
    mc = built()
    if getattr(args, "doc", False):
        path = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "microcode-v1b.md")
        with open(path, "w") as f:
            f.write(describe())
        print(f"wrote {os.path.normpath(path)}")
        return 0
    out = args.o or "build/ucode-v1b"
    os.makedirs(out, exist_ok=True)
    imgs, dimgs = rom_images()
    for k, img in enumerate(imgs):
        with open(os.path.join(out, f"ucode{k}.bin"), "wb") as f:
            f.write(img)
    for k, img in enumerate(dimgs):
        with open(os.path.join(out, f"decode{k}.bin"), "wb") as f:
            f.write(img)
    with open(os.path.join(out, "ucode.lst"), "w") as f:
        f.write(full_listing())
    print(f"{CONTROL_BITS} control bits in {ROMS} ROMs, {len(mc.nodes)} microinstructions "
          f"({mc.used} of {1 << Y_BITS} slots), 2 decode ROMs -> {out}/")
    return 0
