"""Microcode and decode table for the draft 2 CPU.

See RFC 0031, Part I, for the datapath these signals drive, and rtl.py for
the register-transfer model that runs them.

The control store is writable: nine 64K x 16 SRAMs hold the 144-bit
microinstruction (140 bits used) and a tenth the decode table. The I/O
processor fills them at boot through the card's slave port. They are
pipelined as in draft 1b: the SRAMs are addressed with the address of the
*next* microinstruction, and their outputs are clocked into the
microinstruction register (uIR) at every edge.

Control store address, 16 bits: {U[2:0], Y[12:0]}

    U = 000          Y, the next address the sequencer chose
    U = 001, Y = 0   refill: the decode found the next instruction
                     incomplete in the prefetch queue, or the cycle jumped
    U = 010, Y = 0   interrupt entry (decode with an interrupt pending)
    U = 011, Y = 0   trace entry (decode with T set when the instruction
                     started)
    U = 1LL, Y = 0   a fault in this cycle's memory access (page fault,
                     misaligned, bus error); LL is the number of parcels
                     the instruction has consumed, so the fault routine can
                     wind the PC back

    SEQ 0  Y = NEXT, or {NEXT[12:1], cond} for a branch
    SEQ 1  decode: Y = the decode table's entry for the head parcel of
           the prefetch queue (QH); IR <- QH and the parcel is consumed.
           Forced to one of the entries above when it can't go ahead
    SEQ 2  dispatch: Y = {NEXT[12:4], QH[11:8]}, on the index parcel's
           scale and size
    SEQ 3  halt: Y = NEXT (itself), unless an interrupt is pending

Unlike draft 1b there's no fetch cycle: instructions are fetched into the
prefetch queue in cycles that don't use memory, and the decode reads the
queue. A register is written in the same cycle as its value is computed
(the register file is read in the first two ticks of the cycle into
latches, and written in its last tick).

Microinstructions are written as dicts of logical field values with mi(),
linked into a graph (Node), and placed by Microcode, which also builds
the decode table.
"""

from collections import defaultdict

from heron.studies.v2_isa import v2

# --------------------------------------------------------------------------
# Control word: (name, width, active_low). Active-low fields are stored
# inverted, so a logical 1 means "asserted" everywhere in this file.

FIELDS = [
    # sequencer
    ("NEXT", 13, False), ("SEQ", 2, False), ("COND", 4, False),
    # A bus: register file copy A, PC (bit 0 from PCK), R, R x 2, MAR
    ("ARF", 1, True), ("APC", 1, True), ("AR", 1, True), ("AR2", 1, True), ("AMAR", 1, True),
    ("PCK", 1, False), ("SINA", 2, False),
    # B bus: register file copy B, R, T (by lanes), the queue head, the
    # immediate unit, MQ, special registers, the page map
    ("BRF", 1, True), ("BR", 1, True), ("BL", 3, False), ("BX", 3, False),
    ("BS0", 1, True), ("BF1", 1, True), ("BF23", 1, True),
    # register file: read addresses for the two copies (RFK when constant),
    # the write address (RFKW when constant)
    ("RFA", 2, False), ("RFB", 2, False), ("RFW", 2, False), ("RFK", 6, False),
    ("RFKW", 6, False), ("RFWE", 1, False), ("UBR", 1, False), ("UBW", 1, False),
    # SX (a register number that counts) and EX (where a count stops)
    ("LDSX", 2, False), ("SXINC", 1, False), ("LDEX", 2, False),
    # ALU
    ("S", 4, False), ("M", 1, False), ("CIN", 3, False), ("MQM", 2, False), ("MS", 2, False),
    # result multiplexer
    ("RMS", 2, False), ("RZ", 4, False), ("SIN", 2, False),
    # immediate unit
    ("V8", 3, False), ("FSEL", 3, False), ("KONST", 8, False), ("LDSGN", 1, False),
    # registers
    ("LDR", 1, True), ("LDMAR", 1, True), ("MARINC", 1, False), ("LDPC", 1, False),
    ("PCCOND", 2, False), ("CONSUME", 1, False), ("LDLC", 1, True), ("LCINC", 1, False),
    ("CCB", 2, False), ("LDCTX", 1, False), ("LDBANK", 1, False),
    # memory
    ("MEM", 3, False), ("SIZE", 2, False),
    # flags and condition latches
    ("FNZ", 2, False), ("NSEL", 2, False), ("FC", 2, False), ("CZERO", 1, False),
    ("CSRC", 3, False), ("FV", 3, False), ("FI", 2, False), ("LFM", 2, False),
    ("SSET", 1, False), ("LDCL", 1, False), ("CLSRC", 3, False),
    # length class
    ("LCL", 2, False),
]

WORD_BITS = 144             # nine 64K x 16 SRAMs
Y_BITS = 13
U_SHIFT = Y_BITS


def _layout():
    pos, bit = {}, 0
    for name, w, al in FIELDS:
        pos[name] = (bit, w, al)
        bit += w
    assert bit <= WORD_BITS, bit
    return pos


_pos = _layout()
CONTROL_BITS = sum(w for _, w, _ in FIELDS)

# --------------------------------------------------------------------------
# Encodings. The ones shared with draft 1b's datapath keep its values, so
# that its shift planner (studies/v1b_hw/ucode.py) can be reused.

SEQ_NEXT, SEQ_DECODE, SEQ_DISPATCH, SEQ_HALT = 0, 1, 2, 3
CONDS = {"false": 0, "tc": 1, "r31": 2, "cl": 3, "condt": 4, "mq31": 5, "tc4": 6,
         "ncondt": 7, "sup": 8, "sxeq": 9, "fk0": 10, "fk1": 11, "sx15": 12, "mq0": 13,
         "r0": 14}
RFSEL = {"d": 0, "r": 1, "s": 2, "x": 2}           # 3 = RFK constant
# B lanes from T (by the access's size and address) or the queue's head
# parcel: as it is, x 2 (a branch offset), in the upper half, its low byte
BL = {None: 0, "t": 1, "thalf": 2, "tbyte": 3, "qh": 4, "qh2": 5, "qhh": 6, "qhb": 7}
# B from a special source: MQ, the flags word, FSR, FAR, the page map
BX = {None: 0, "mq": 1, "flags": 2, "fsr": 3, "far": 4, "map": 5}
LDSX = {None: 0, "d": 1, "r": 2, "qhx": 3}
LDEX = {None: 0, "r": 1, "qhx": 2}
CIN = {"0": 0, "1": 1, "c": 2, "a31": 3, "mq31": 4, "sgn": 5, "mq0": 6, "s33n": 7}
MD = {None: (0, 0, None), "mqload": (3, 0, None), "mulu": (1, 1, "0"), "muls": (1, 2, "mq0"),
      "div": (2, 3, "s33n"), "fix": (0, 3, "0"), "shr64": (1, 0, None)}
RMS = {"f": 0, "shr": 1, "ror8": 2, "ror16": 3}
SIN = {"0": 0, "f31": 1, "c": 2, "f0": 3}
SINA = {"0": 0, "r31": 1, "c": 2, "mq31": 3}
# immediate byte 0: the branch offset x 2 (IR[15:8] << 1), the
# microinstruction's constant, the fill, LC, and the parcel's constants:
# the quick constant q = IR[11:8], -(q + 1) = {1111, ~q}, the 7-bit
# constant {IR[11:8], IR[2:0]} and the slot offset 4q
V8 = {"bcc": 0, "k": 1, "fill": 2, "lc": 3, "q": 4, "nq": 5, "u7": 6, "s4": 7}
# the fill bit, for bytes 1-3: 0, 1, IR15 (the branch offset's sign), QH15
# and QH7 (an extension parcel's or its low byte's sign), A31, A15, SGN
FSEL = {"0": 0, "1": 1, "ir15": 2, "qh15": 3, "qh7": 4, "a31": 5, "a15": 6, "sgn": 7}
PCCOND = {None: 0, "bcond": 1, "ncl": 2}
CCB = {"jcc": 0, "bcc": 1, "set": 2}       # cc from IR[15:12], IR[3:0], IR[11:8]
MEM = {None: 0, "read": 1, "write": 2, "fetch": 3, "mapr": 4, "mapw": 5, "reada": 6}
SIZE = {None: 0, "byte": 1, "half": 2, "word": 3}
FNZ = {None: 0, "nz": 1, "sticky": 2, "loadf": 3}
NSEL = {31: 0, 15: 1, 7: 2}
FC = {None: 0, "csrc": 1, "aluc": 2, "ncl": 3}
CSRC = {"b1": 0, "f0": 1, "f7": 2, "f8": 3, "f15": 4, "f31": 5, "f7x": 6, "f15x": 7}
FV = {None: 0, "0": 2, "a0": 3, "ncl": 4, "1": 5, "ovf": 7}
FI = {None: 0, "1": 1, "0": 2, "a4": 3}
# which flags a flags load (FNZ loadf, from the A bus) takes: NZCV (MTSR in
# user mode), NZCV, I and T (MTSR in supervisor mode), or all of them with
# S (RTI)
LFM = {"nzcv": 0, "sup": 1, "all": 2}
# condition latch CL: RES == 0, the ALU carry, RES[31:16] == 0,
# RES[31:15] == 0, or one of the last two ANDed with CL
CLSRC = {"zero": 0, "aluc": 1, "hz16": 2, "hz17": 3, "and_hz16": 4, "and_hz17": 5}

# 74181 functions (active-high data): (M, S3..S0) and the carry they need.
ALU = {
    "add": (0, 0b1001, "0"), "adc": (0, 0b1001, "c"), "addc": (0, 0b1001, None),
    "sub": (0, 0b0110, "1"), "sbc": (0, 0b0110, "c"),
    "inc": (0, 0b0000, "1"), "dec": (0, 0b1111, "0"),
    "a": (0, 0b0000, None),           # A + carry-in, carry from cin=
    "dbl": (0, 0b1100, None),         # A + A + carry-in
    "and": (1, 0b1011, None), "or": (1, 0b1110, None), "xor": (1, 0b0110, None),
    "bic": (1, 0b0111, None), "passa": (1, 0b1111, None), "passb": (1, 0b1010, None),
    "nota": (1, 0b0000, None), "zero": (1, 0b0011, None), "ornb": (1, 0b1000, None),
    "xnor": (1, 0b1001, None),
}

# Register file: per bank, r0-r15, HI (16), LO (17); RFK >= 32 is outside
# the banks, the microcode's own: scratch and constants the reset routine
# writes, and the special registers that live in the register file.
SP, LINK, OBJ, HI, LO = 15, 7, 14, 16, 17
G = 32
TMP1, TMP2, TMP3 = G + 0, G + 1, G + 2
ZERO, ONES, VBASE, K0FFF, KE1, KE0, K1000 = G + 3, G + 4, G + 5, G + 6, G + 7, G + 8, G + 9
CTXC, BANKC, MAPAS = G + 10, G + 11, G + 12      # ctx, bank, and mapa << 12
VEC = {}                                         # vector name -> its RFK
VECTORS = {"reset": 0x00, "irq": 0x04, "illegal": 0x08, "divide": 0x10, "address": 0x14,
           "tag": 0x18, "privilege": 0x1C, "page": 0x20, "trace": 0x24}
for _i, _n in enumerate(VECTORS):
    VEC[_n] = G + 13 + _i
VSWI = [G + 22 + k for k in range(4)]            # 0x8000_0100 + 0x100 k: SWI #64k..
K80, K7F, MAPMASK, KMULFX = G + 26, G + 27, G + 28, G + 29
CONSTS = {ZERO: 0, ONES: 0xFFFFFFFF, VBASE: 0x80000000, K0FFF: 0x0FFF, KE1: 0xE1, KE0: 0xE0,
          K1000: 0x1000, CTXC: 0, BANKC: 0, MAPAS: 0, K80: 0x80808080, K7F: 0x7F7F7F7F,
          MAPMASK: 0x7FFFF000, KMULFX: 0xE0}
CONSTS.update({VEC[n]: 0x80000000 | v for n, v in VECTORS.items()})
CONSTS.update({VSWI[k]: 0x80000100 + 0x100 * k for k in range(4)})
RF_NAMES = {SP: "sp", HI: "HI", LO: "LO", TMP1: "TMP1", TMP2: "TMP2", TMP3: "TMP3",
            ZERO: "ZERO", ONES: "ONES", VBASE: "VBASE", K0FFF: "K0FFF", KE1: "KE1",
            KE0: "KE0", K1000: "K1000", CTXC: "CTXC", BANKC: "BANKC", MAPAS: "MAPAS",
            K80: "K80", K7F: "K7F", MAPMASK: "MAPMASK", KMULFX: "KMULFX"}
RF_NAMES.update({VEC[n]: f"V_{n}" for n in VECTORS})
RF_NAMES.update({VSWI[k]: f"V_SWI{k}" for k in range(4)})

# --------------------------------------------------------------------------
# Building microinstructions


def _put(f, k, v):
    if k in f and f[k] != v:
        raise ValueError(f"microcode conflict on {k}: {f[k]} vs {v}")
    f[k] = v


def _rf(f, side, sel):
    if isinstance(sel, int):
        _put(f, side, 3)
        _put(f, "RFKW" if side == "RFW" else "RFK", sel)
    else:
        _put(f, side, RFSEL[sel])


B_PRESETS = {
    "r": ("BR",), "simm": ("BS0", "BF1", "BF23"), "fillall": ("BS0", "BF1", "BF23"),
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
        elif k == "w":                        # write RES into a register
            _put(f, "RFWE", 1)
            _rf(f, "RFW", v)
        elif k == "a":
            _put(f, {"pc": "APC", "r": "AR", "r2": "AR2", "mar": "AMAR"}[v], 1)
        elif k == "b":
            if v in B_PRESETS:
                for e in B_PRESETS[v]:
                    _put(f, e, 1)
                if v == "fillall":
                    _put(f, "V8", V8["fill"])
            elif v in ("t", "thalf", "tbyte"):
                _put(f, "BL", BL[v])
                if v != "t":
                    _put(f, "BF23", 1)
                    _put(f, "FSEL", FSEL["0"])
                    if v == "tbyte":
                        _put(f, "BF1", 1)
            elif v in ("qh", "qh2"):          # the head parcel, extended by fill=
                _put(f, "BL", BL[v])
                _put(f, "BF23", 1)
            elif v == "qhh":                  # the head parcel << 16
                _put(f, "BL", BL["qhh"])
                _put(f, "BS0", 1)
                _put(f, "BF1", 1)
                _put(f, "V8", V8["k"])
                _put(f, "KONST", 0)
                _put(f, "FSEL", FSEL["0"])
            elif v == "qhb":                  # its low byte, sign-extended
                _put(f, "BL", BL["qhb"])
                _put(f, "BF1", 1)
                _put(f, "BF23", 1)
                _put(f, "FSEL", FSEL["qh7"])
            elif v in ("flags", "fsr"):
                _put(f, "BX", BX[v])
                _put(f, "BF1", 1)
                _put(f, "BF23", 1)
                _put(f, "FSEL", FSEL["0"])
            elif v in ("far", "map", "mq"):
                _put(f, "BX", BX[v])
            else:
                raise KeyError(v)
        elif k == "kv":                       # a constant on the B bus
            if not -256 <= v <= 255:
                raise ValueError(f"constant {v} doesn't fit the immediate unit")
            for e in B_PRESETS["simm"]:
                _put(f, e, 1)
            _put(f, "V8", V8["k"])
            _put(f, "KONST", v & 0xFF)
            _put(f, "FSEL", FSEL["1" if v < 0 else "0"])
        elif k == "imm":                      # one of the parcel's constants
            for e in B_PRESETS["simm"]:
                _put(f, e, 1)
            _put(f, "V8", V8[v])
            _put(f, "FSEL", FSEL["1" if v == "nq" else ("ir15" if v == "bcc" else "0")])
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
        elif k == "mem":
            _put(f, "MEM", MEM[v])
        elif k == "size":
            _put(f, "SIZE", SIZE[v])
        elif k == "pccond":
            _put(f, "PCCOND", PCCOND[v])
        elif k == "ccb":
            _put(f, "CCB", CCB[v])
        elif k == "ldsx":
            _put(f, "LDSX", LDSX[v])
        elif k == "ldex":
            _put(f, "LDEX", LDEX[v])
        elif k == "fnz":
            _put(f, "FNZ", FNZ[v])
        elif k == "nsel":
            _put(f, "NSEL", NSEL[v])
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
        elif k == "loadf":                    # flags from the A bus
            _put(f, "FNZ", FNZ["loadf"])
            _put(f, "FC", FC["csrc"])
            _put(f, "CSRC", CSRC["b1"])
            _put(f, "FV", FV["a0"])
            _put(f, "LFM", LFM[v])
            if v != "nzcv":
                _put(f, "FI", FI["a4"])
        elif k == "ldcl":
            _put(f, "LDCL", 1)
            _put(f, "CLSRC", CLSRC[v])
        elif k in ("ldr", "ldmar", "marinc", "ldpc", "consume", "ldlc", "lcinc", "ldctx",
                   "ldbank", "pck", "sxinc", "ubr", "ubw", "sset", "czero", "ldsgn"):
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
          | ("dispatch", [16 nodes]) | ("halt",)
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
        return Node(self.f, self.succ, self.name)


def end(name="", _fields=None, **kw):
    """Last microinstruction of an instruction: it decodes the next one.
    _fields: a field dict to start from."""
    f = merge(_fields or {}, mi(**kw))
    return Node(f, ("decode",), name)


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
    """A microinstruction that repeats until cond holds, then goes on. The
    condition is evaluated in each repetition, before its own effects."""
    n = Node(f, None, name)
    n.succ = ("branch", CONDS[cond], n, exit_node)
    return n


# --------------------------------------------------------------------------
# Traps
#
# Entering an exception (RFC 0029, 6): the flags word as it was into TMP1,
# then S <- 1 (bank 0), I <- 0, T <- 0; the PC and the flags pushed on
# bank 0's sp; the jump to the vector, whose address is a constant in the
# register file. Five cycles, then the refill at the vector.

_trap_cache = {}
SAVE_FLAGS = mi(w=TMP1, b="flags", alu="passb")


def trap_tail(vecreg, pcfix, name):
    """Everything after the flags word has gone into TMP1: the saved PC is
    the PC less pcfix bytes."""
    key = (vecreg, pcfix)
    if key in _trap_cache:
        return _trap_cache[key]
    pc = mi(a="pc", kv=pcfix, alu="sub") if pcfix else mi(a="pc", alu="passa")
    node = chain(name,
                 merge(pc, mi(ldr=1, sset=1)),                        # R <- saved PC
                 mi(ra=SP, kv=8, alu="sub", ldmar=1, w=SP),           # bank 0's sp
                 mi(ra=TMP1, mem="write", size="word", marinc=1),
                 end(name, a="r", mem="write", size="word", rb=vecreg, alu="passb",
                     ldpc=1))
    _trap_cache[key] = node
    return node


def trap(vec, pcfix, name=None):
    """Trap through vector `vec` (a VECTORS name), saving the PC less pcfix
    bytes: the instruction's own address for a fault, the next one's
    otherwise."""
    name = name or f"trap {vec}"
    return Node(SAVE_FLAGS, ("next", trap_tail(VEC[vec], pcfix, name)), name)


def illegal(pcfix=2):
    return trap("illegal", pcfix, "illegal")


def privileged(name, body, pcfix=2):
    """In user mode, a privilege violation; in supervisor mode, body."""
    return branch(name, {}, "sup", trap("privilege", pcfix, name), body)


# --------------------------------------------------------------------------
# Operands
#
# opnd(M, R) describes how an instruction gets its operand in mode M with
# register R (IR[11:8]): the steps before the cycle that uses it, the
# fields that put it on the B bus in that cycle, and what else that cycle
# implies. A memory operand is used in the cycle that reads it: T is
# transparent while memory is read, so a load writes its register in the
# same cycle.


class Opnd:
    def __init__(self, kind, pre, use, size=4, consume=False, post=None, base=False):
        self.kind = kind          # 'reg', 'imm', 'mem', 'idx'
        self.pre = pre            # steps before the using cycle
        self.use = use            # fields of the using cycle (operand on B)
        self.size = size
        self.consume = consume    # the using cycle consumes a parcel (it can't decode)
        self.post = post          # ('post', n): [R]+; ('pre', None): -[R], R holds the base
        self.base = base          # [R] or [R]+: the address is R itself, so a read can
                                  # take it from the A bus (MEM reada) without MAR


def size_name(n):
    return {1: "byte", 2: "half", 4: "word"}[n]


def mode_size(M, R):
    """Operand size of a memory mode (4 for non-memory)."""
    if M in (8, 9, 0xA) or (M == 0xF and R in (5, 8, 0xB)):
        return 1
    if M in (0xB, 0xC) or (M == 0xF and R in (6, 9, 0xC)):
        return 2
    return 4


def ext_parcels(M, R):
    return v2.mode_size(M, R)


def is_mem(M, R):
    return M not in (0, 1, 0xD) and not (M == 0xF and R <= 3)


def is_idx(M, R):
    return M == 5 or (M == 0xF and R in (0xD, 0xE))


def tload(size):
    """B bus fields for a loaded value of `size` bytes (from T's lanes)."""
    return mi(b={1: "tbyte", 2: "thalf", 4: "t"}[size])


def addr_steps(M, R, dest):
    """Steps that put a memory operand's address into MAR (dest 'mar') or
    R (dest 'r'). Not for the indexed modes. Returns (steps, post)."""
    out = {"ldmar": 1} if dest == "mar" else {"ldr": 1}
    if M in (2, 8, 0xB):                              # [R]
        return [mi(ra="r", alu="passa", **out)], None
    if M in (3, 9, 0xC):                              # [R + d16]
        return [mi(ra="r", b="qh", fill="qh15", alu="add", consume=1, **out)], None
    if M in (4, 0xE):                                 # [sp + 4R], [r14 + 4R]
        return [mi(ra=SP if M == 4 else OBJ, imm="s4", alu="add", **out)], None
    if M in (6, 0xA):                                 # [R]+: the base after the access
        return [mi(ra="r", alu="passa", **out)], ("post", 4 if M == 6 else 1)
    if M == 7:                                        # -[R]: R keeps the new base
        return [mi(ra="r", kv=4, alu="sub", ldr=1, **({"ldmar": 1} if dest == "mar" else {}))], \
            ("pre", None)
    if M == 0xF and R in (4, 5, 6):                   # [abs16]
        return [mi(b="qh", fill="qh15", alu="passb", consume=1, **out)], None
    if M == 0xF and R in (7, 8, 9):                   # [abs32]
        return [mi(b="qh", fill="0", alu="passb", ldr=1, consume=1),
                mi(a="r", b="qhh", alu="or", consume=1, **out)], None
    if M == 0xF and R in (0xA, 0xB, 0xC):             # [pc + d16]: PC + 2 + d16
        return [mi(a="pc", pck=1, b="qh", fill="qh15", alu="addc", cin="1", consume=1,
                   **out)], None
    raise ValueError(f"mode {M:X}/{R:X} has no address")


def opnd(M, R):
    """The operand of mode M, register R."""
    if M == 0:
        return Opnd("reg", [], mi(rb="r"))
    if M == 1:
        return Opnd("imm", [], mi(imm="q"))
    if M == 0xD:
        return Opnd("imm", [], mi(imm="nq"))
    if M == 0xF and R <= 3:
        if R == 0:
            return Opnd("imm", [], mi(b="qh", fill="qh15"), consume=True)
        if R == 1:
            return Opnd("imm", [], mi(b="qh", fill="0"), consume=True)
        if R == 2:
            return Opnd("imm", [], mi(b="qhh"), consume=True)
        return Opnd("imm", [mi(b="qh", fill="0", alu="passb", ldr=1, consume=1),
                            mi(a="r", b="qhh", alu="or", ldr=1, consume=1)], mi(b="r"))
    if is_idx(M, R):
        return Opnd("idx", [], {})
    size = mode_size(M, R)
    steps, post = addr_steps(M, R, "mar")
    use = merge(mi(mem="read", size=size_name(size)), tload(size))
    return Opnd("mem", steps, use, size=size, post=post, base=M in (2, 6, 8, 0xA, 0xB))


# ---- the indexed modes ---------------------------------------------------
#
# The first cycle dispatches on the index parcel's scale and size (a table
# of 16 routines), puts base + d8 into TMP1 and the index register's number
# into SX. For the special mode's tables, the next cycles build the 24-bit
# address (PC-relative for E) in TMP1. Then TMP1 + x * 2^s.


def idx_first(M, R):
    """(dispatch cycle, steps after it) of an indexed mode."""
    if M == 5:                                        # [R + x*s + d8]
        return mi(ra="r", b="qhb", alu="add", w=TMP1, ldsx="qhx", consume=1), []
    disp = mi(b="qhb", alu="passb", ldr=1, ldsx="qhx", consume=1)      # sext(a23-16)
    after = [mi(a="r", alu="passa", rms="ror16", rz=0b0011, ldr=1)]       # << 16
    if R == 0xD:                                      # [abs24 + x*s]
        after.append(mi(a="r", b="qh", fill="0", alu="or", w=TMP1, consume=1))
    else:                                             # [pc + d24 + x*s]
        after.append(mi(a="r", b="qh", fill="0", alu="or", ldr=1, consume=1))
        after.append(mi(a="pc", b="r", alu="add", w=TMP1))   # PC: the next instruction
    return disp, after


def idx_addr(s, dest):
    """TMP1 + x * 2^s into MAR or R."""
    out = {"ldmar": 1} if dest == "mar" else {"ldr": 1}
    if s == 0:
        return [mi(ra="x", rb=TMP1, alu="add", **out)]
    steps = [mi(ra="x", rb="x", alu="add", ldr=1)]                 # R <- 2x
    if s == 1:
        steps.append(mi(a="r", rb=TMP1, alu="add", **out))
    elif s == 2:
        steps.append(mi(a="r2", sina="0", rb=TMP1, alu="add", **out))
    else:
        steps.append(mi(a="r2", sina="0", alu="passa", ldr=1))      # R <- 4x
        steps.append(mi(a="r2", sina="0", rb=TMP1, alu="add", **out))
    return steps


def idx_routine(opname, M, R, name):
    disp, after = idx_first(M, R)
    table = []
    for i in range(TABLE):
        s, z = i >> 2, i & 3
        sub = f"{name} s{s}z{z}"
        if z == 3:
            table.append(illegal(4))     # the opcode and the index parcel consumed
        else:
            table.append(idx_entry(opname, s, (1, 2, 4)[z], after, sub))
    return Node(disp, ("dispatch", table), name)


def idx_entry(opname, s, size, after, name):
    if opname == "LEA":
        st = after + idx_addr(s, "r")
        last = {k: v for k, v in st[-1].items() if k != "LDR"}
        return chain(name, *st[:-1], end(name, _fields=merge(last, mi(w="d"))))
    if opname in ("JMP", "CALL") and size != 4:
        return illegal(4)
    st = after + idx_addr(s, "mar")
    o = Opnd("mem", st, merge(mi(mem="read", size=size_name(size)), tload(size)), size=size)
    return mem_op(opname, o, name)


# --------------------------------------------------------------------------
# Instructions with a mode: rows 1-6 and 8-A, CLR/INC/DEC, JMP/CALL, LEA,
# and BIC/TST/MULU/MULS with the special mode

ALU_OF = {"ADD": "add", "SUB": "sub", "CMP": "sub", "AND": "and", "OR": "or", "XOR": "xor",
          "BIC": "bic", "TST": "and"}
ARITH = ("ADD", "SUB", "CMP")
NOWRITE = ("CMP", "TST")
NBIT = {1: 7, 2: 15, 4: 31}


def op_fields(opname, size):
    """The using cycle's fields for an operation, the operand on B."""
    if opname == "MOV":
        return mi(w="d", alu="passb")
    if opname == "MOVS":
        return mi(w="d", alu="passb", fnz="nz", nsel=NBIT[size])
    flags = {"fc": "aluc", "fv": "ovf"} if opname in ARITH else {}
    f = mi(ra="d", alu=ALU_OF[opname], fnz="nz", **flags)
    if opname not in NOWRITE:
        f = merge(f, mi(w="d"))
    return f


def load_like(opname, o, name):
    """MOV, MOVS and the ALU rows with operand o."""
    if o.post and o.post[0] == "pre":
        # -[R]: the base from R in the access cycle (T latches the value),
        # then the operation from T
        acc = merge(mi(mem="read", size="word"), mi(b="r", alu="passb", w="r"))
        return chain(name, *o.pre, acc, end(name, _fields=merge(tload(4), op_fields(opname, 4))))
    if o.post:
        # [R]+: the base stepped in the access cycle, which reads at the
        # base on the A bus; the operation from T
        acc = merge(mi(mem="reada", size=size_name(o.size)), mi(ra="r", kv=o.post[1], alu="add",
                                                                 w="r"))
        return chain(name, acc,
                     end(name, _fields=merge(tload(o.size), op_fields(opname, o.size))))
    if o.base and opname in ("MOV", "MOVS"):
        # [R]: one cycle, the address from the A bus (an ALU operation
        # needs the A bus for rd, so goes through MAR)
        return end(name, _fields=merge(mi(mem="reada", size=size_name(o.size), ra="r"),
                                       tload(o.size), op_fields(opname, o.size)))
    using = merge(o.use, op_fields(opname, o.size))
    if o.consume:
        return chain(name, *o.pre, merge(using, mi(consume=1)), end(name))
    return chain(name, *o.pre, end(name, _fields=using))


def store_like(o, name, zero=False):
    """MOV [ea], rd (a store), and CLR [ea]."""
    acc = merge(mi(ra=ZERO if zero else "d"),
                mi(mem="write", size=size_name(o.size)))
    if o.post and o.post[0] == "pre":
        return chain(name, *o.pre, end(name, _fields=merge(acc, mi(b="r", alu="passb", w="r"))))
    if o.post:
        return chain(name, *o.pre, acc, end(name, ra="r", kv=o.post[1], alu="add", w="r"))
    return chain(name, *o.pre, end(name, _fields=acc))


def rmw_like(o, name, dec):
    """INC and DEC on memory: read and add into R, then store, setting N
    and Z from the value stored (the store's cycle, so a fault in it leaves
    the flags alone)."""
    size = o.size
    rz = {1: 0b1110, 2: 0b1100, 4: 0}[size]
    calc = merge(mi(mem="read", size=size_name(size)), tload(size),
                 mi(ra=ONES if dec else ZERO, alu="addc", cin="0" if dec else "1", rz=rz, ldr=1))
    store = mi(a="r", alu="passa", mem="write", size=size_name(size),
               fnz="nz", nsel=NBIT[size])
    if o.post and o.post[0] == "pre":
        # -[R]: the new base waits in TMP2 while R holds the value
        pre = o.pre[:-1] + [merge(o.pre[-1], mi(w=TMP2))]
        return chain(name, *pre, calc, store, end(name, rb=TMP2, alu="passb", w="r"))
    if o.post:
        return chain(name, *o.pre, calc, store, end(name, ra="r", kv=o.post[1], alu="add",
                                                     w="r"))
    return chain(name, *o.pre, calc, end(name, _fields=store))


def jump_to(call, name, src):
    """JMP and CALL to a value: src are the fields that put it on RES. A
    call first writes r7 with the PC, the next instruction's address."""
    if not call:
        return end(name, _fields=merge(src, mi(ldpc=1)))
    return chain(name, mi(a="pc", alu="passa", w=LINK), end(name, _fields=merge(src, mi(ldpc=1))))


def mem_op(opname, o, name):
    """An operation on a memory operand o (MAR set by o.pre)."""
    if opname == "ST":
        return store_like(o, name)
    if opname == "CLR":
        return store_like(o, name, zero=True)
    if opname in ("INC", "DEC"):
        return rmw_like(o, name, opname == "DEC")
    if opname in ("MULU", "MULS"):
        return mul_mem(opname, name, o)
    if opname in ("JMP", "CALL"):
        call = opname == "CALL"
        if o.size != 4:
            return None
        if o.post:
            if o.post[0] == "pre":
                pre = o.pre
                acc = merge(mi(mem="read", size="word"), mi(b="r", alu="passb", w="r"))
            else:
                pre = []
                acc = merge(mi(mem="reada", size="word"), mi(ra="r", kv=o.post[1], alu="add",
                                                             w="r"))
            if call:
                return chain(name, *pre, acc, mi(a="pc", alu="passa", w=LINK),
                             end(name, b="t", alu="passb", ldpc=1))
            return chain(name, *pre, acc, end(name, b="t", alu="passb", ldpc=1))
        if o.base and not call:
            return end(name, _fields=mi(mem="reada", size="word", ra="r", b="t", alu="passb",
                                        ldpc=1))
        acc = mi(mem="read", size="word", b="t")
        if call:
            # r7 <- PC in the access cycle (not written if it faults)
            return chain(name, *o.pre, merge(acc, mi(a="pc", alu="passa", w=LINK)),
                         end(name, b="t", alu="passb", ldpc=1))
        return chain(name, *o.pre, end(name, _fields=merge(acc, mi(alu="passb", ldpc=1))))
    return load_like(opname, o, name)


def ea_routine(opname, M, R, name):
    if is_idx(M, R):
        return idx_routine(opname, M, R, name)
    o = opnd(M, R)
    if o.kind == "reg":
        if opname == "CLR":
            return end(name, alu="zero", w="r")
        if opname in ("INC", "DEC"):
            return end(name, ra="r", alu="inc" if opname == "INC" else "dec", w="r", fnz="nz")
        if opname in ("MULU", "MULS"):
            return mul_core(opname, name, "r")
    if o.kind == "mem":
        return mem_op(opname, o, name)
    if opname in ("MULU", "MULS"):
        return mul_mem(opname, name, o)
    return load_like(opname, o, name)


def lea_routine(M, R, name):
    if is_idx(M, R):
        return idx_routine("LEA", M, R, name)
    steps, _ = addr_steps(M, R, "r")
    last = {k: v for k, v in steps[-1].items() if k not in ("LDR", "CONSUME")}
    last = merge(last, mi(w="d"))
    if steps[-1].get("CONSUME"):
        return chain(name, *steps[:-1], merge(last, mi(consume=1)), end(name))
    return chain(name, *steps[:-1], end(name, _fields=last))


def jea_routine(call, M, R, name):
    """JMP ea and CALL ea (F0, F1): the mode in the register byte's high
    nibble. The target is the operand's value."""
    if M == 0:
        if call and R == LINK:
            # CALL r7: the target before r7 changes
            return chain(name, mi(ra="r", alu="passa", ldr=1), mi(a="pc", alu="passa", w=LINK),
                         end(name, a="r", alu="passa", ldpc=1))
        return jump_to(call, name, mi(ra="r", alu="passa"))
    if is_idx(M, R):
        return idx_routine("CALL" if call else "JMP", M, R, name)
    o = opnd(M, R)
    if o.kind == "imm":
        if o.pre:                                     # a 32-bit constant, in R
            return chain(name, *o.pre, jump_to(call, name, mi(a="r", alu="passa")))
        if o.consume:
            return chain(name, merge(o.use, mi(alu="passb", ldr=1, consume=1)),
                         jump_to(call, name, mi(a="r", alu="passa")))
        return jump_to(call, name, merge(o.use, mi(alu="passb")))
    r = mem_op("CALL" if call else "JMP", o, name)
    return r if r is not None else illegal(2 + 2 * ext_parcels(M, R))


# --------------------------------------------------------------------------
# Unary operations and shifts


def unary_routine(name):
    """Row D: rd <- f(rs)."""
    wb = mi(w="d", fnz="nz")

    def one(**kw):
        return end(name, _fields=merge(mi(**kw), wb))
    if name == "NOT":
        return one(ra="r", alu="nota")
    if name == "NEG":
        return one(ra=ZERO, rb="r", alu="sub", fc="aluc", fv="ovf")
    if name == "INC":
        return one(ra="r", alu="inc")
    if name == "DEC":
        return one(ra="r", alu="dec")
    if name == "RLC":
        return one(ra="r", alu="dbl", cin="c", fc="aluc", fv="0")
    if name == "RRC":
        return one(ra="r", alu="passa", rms="shr", sin="c", fc="f0", fv="0")
    if name == "SWAP":
        return one(ra="r", alu="passa", rms="ror16")
    if name == "SXB":   # ((x ^ 0x80) & 0xFF) - 0x80
        return chain(name, mi(ra="r", kv=0x80, alu="xor", rz=0b1110, ldr=1),
                     one(a="r", kv=0x80, alu="sub"))
    if name == "ZXB":
        return one(ra="r", alu="passa", rz=0b1110)
    if name == "SXH":   # (x ^ s) & 0xFFFF ^ s, s = 32 copies of bit 15
        return chain(name, mi(ra="r", b="fillall", fill="a15", ldsgn=1, alu="xor", rz=0b1100,
                              ldr=1),
                     one(a="r", b="fillall", fill="sgn", alu="xor"))
    if name == "ZXH":
        return one(ra="r", alu="passa", rz=0b1100)
    lc_out = merge(mi(b="simm", v8="lc", fill="0", alu="passb"), wb)
    # CL <- rs == 0 first; the next cycle branches on it (a branch tests the
    # condition latch as the cycle starts)
    first = mi(ra="r", alu="passa", ldr=1, ldcl="zero")
    if name == "CLZ":
        # LC counts the shifts; the loop exits one shift late (it tests bit
        # 31 before shifting), so LC starts at -1
        out = end(name, _fields=lc_out)
        body = loop(name, mi(a="r2", sina="0", alu="passa", ldr=1, lcinc=1), "r31", out)
        return chain(name, first, branch(name, mi(kv=-1, alu="passb", ldlc=1), "cl",
                                         body, one(kv=32, alu="passb")))
    if name == "FFS":
        # tentative: shift right until bit 0 is set, the same way
        out = end(name, _fields=lc_out)
        body = loop(name, mi(a="r", alu="passa", rms="shr", sin="0", ldr=1, lcinc=1), "r0", out)
        return chain(name, first, branch(name, mi(kv=-1, alu="passb", ldlc=1), "cl",
                                         body, one(kv=32, alu="passb")))
    if name == "POPC":
        # tentative: each round clears the lowest set bit, R & (R - 1)
        out = end(name, _fields=lc_out)
        step = Node(mi(a="r", alu="dec", w=TMP2), None, name)
        clear = Node(mi(a="r", rb=TMP2, alu="and", ldr=1, lcinc=1, ldcl="zero"), ("next", step),
                     name)
        step.succ = ("branch", CONDS["cl"], clear, out)
        return chain(name, first, mi(kv=0, alu="passb", ldlc=1), step)
    if name == "REV":
        # tentative: (ror8(x) & 0xFF00FF00) | (rol8(x) & 0x00FF00FF)
        return chain(name,
                     mi(ra="r", alu="passa", rms="ror8", rz=0b0101, w=TMP2),     # b0 . b2 .
                     mi(ra="r", alu="passa", rms="ror16", ldr=1),                # b1 b0 b3 b2
                     mi(a="r", alu="passa", rms="ror8", rz=0b1010, ldr=1),       # . b1 . b3
                     one(a="r", rb=TMP2, alu="or"))
    raise ValueError(name)


def shift_routine(kind, n):
    """A shift by a constant: draft 1b's planner (studies/v1b_hw), whose
    steps this datapath has too. The last step writes rd and the flags."""
    from heron.studies.v1b_hw import ucode as v1b_uc
    name = f"{v2.SHIFTS[kind]} #{n}"
    if n == 0:
        return end(name, ra="d", alu="passa", w="d", fnz="nz", fv="0")
    steps = [dict(s) for s in v1b_uc.cached_plan(kind, n)]
    for s in steps:
        for k in s:
            if k not in _pos:
                raise ValueError(f"shift plan field {k} isn't in this datapath")
    body = [merge(s, mi(ldr=1)) for s in steps[:-1]]
    return chain(name, *body, end(name, _fields=merge(steps[-1], mi(w="d", fnz="nz", fv="0"))))


def shift_reg_routine(kind):
    """A shift by a register: LC <- 255 - (rs & 31), then one bit a cycle."""
    name = f"{v2.SHIFTS[kind]} reg"
    wb = end(name, a="r", alu="passa", w="d", fnz="nz", fv="0")
    if kind == 0:
        step = mi(a="r", alu="dbl", cin="0", fc="aluc")
    else:
        step = mi(a="r", alu="passa", rms="shr", sin={1: "0", 2: "f31", 3: "f0"}[kind], fc="f0")
    body = loop(name, merge(step, mi(ldr=1, lcinc=1)), "tc", wb)
    return chain(name, mi(ra="r", kv=0xE0 - 256, alu="ornb", ldlc=1),
                 branch(name, mi(ra="d", alu="passa", ldr=1, lcinc=1), "tc", body, wb))


# --------------------------------------------------------------------------
# Multiply and divide: draft 1b's algorithms (report 0012, 5), on MQ


def mul_mem(opname, name, o):
    """MULU and MULS with the special mode: the operand into TMP3 first."""
    if o.kind == "mem":
        steps = list(o.pre) + [merge(o.use, mi(alu="passb", w=TMP3))]
    elif o.pre:
        steps = list(o.pre) + [mi(b="r", alu="passb", w=TMP3)]
    elif o.consume:
        steps = [merge(o.use, mi(alu="passb", w=TMP3, consume=1))]
    else:
        steps = [merge(o.use, mi(alu="passb", w=TMP3))]
    return chain(name, *steps, mul_core(opname, name, TMP3))


def mul_core(opname, name, src):
    """HI:rd <- rd x src, src a register field ('r') or a location. The
    multiplier goes to MQ; R accumulates the high half; 16 steps when the
    operands fit in 16 bits, else 32."""
    if opname == "MULU":
        step = mi(a="r", rb="d", md="mulu", rms="shr", ldr=1, lcinc=1)
        tail32 = chain(name, mi(a="r", alu="passa", w=HI, ldcl="zero"),
                       end(name, b="mq", alu="passb", w="d", fnz="nz", fc="ncl", fv="ncl"))
        small = chain(name, mi(a="r", b="mq", alu="or", rms="ror16", ldr=1),
                      mi(alu="zero", w=HI),
                      end(name, a="r", alu="passa", w="d", fnz="nz", czero=1, fv="0"))
        # multiplier < 2^16, multiplicand not: P = rd x m; R = P >> 16 and
        # MQ = {P[15:0], 0} after 16 steps... with the multiplicand's high
        # half the product needs the general recombination
        general = chain(name, mi(ra=TMP1, alu="passa", rms="ror16", rz=0b1100, ldr=1),
                        mi(a="r", alu="passa", w=HI, ldcl="zero"),
                        mi(ra=TMP1, alu="passa", rz=0b1100, ldr=1),
                        mi(a="r", b="mq", alu="or", rms="ror16", ldr=1),
                        end(name, a="r", alu="passa", w="d", fnz="nz", fc="ncl", fv="ncl"))
        exit16 = branch(name, mi(a="r", alu="passa", w=TMP1), "cl", general, small)
        return chain(name,
                     mi(rb=src, md="mqload", alu="passb", ldcl="hz16"),
                     mi(ra="d", alu="passa", ldcl="and_hz16"),
                     mi(ra=KE1, alu="passa", ldlc=1),
                     branch(name, mi(ra=ZERO, rb="d", md="mulu", rms="shr", ldr=1), "cl",
                            loop(name, step, "tc", tail32), loop(name, step, "tc4", exit16)))
    # MULS: the accumulator stays signed (each step shifts in the sum's true
    # sign), and the last step subtracts: the multiplier's top bit weighs
    # -2^31 (or -2^15)
    step = mi(a="r", rb="d", md="mulu", rms="shr", sin="f31", ldr=1, lcinc=1)
    last = mi(a="r", rb="d", md="muls", rms="shr", sin="f31", ldr=1)
    # overflow iff HI isn't the sign extension of the low word
    tail32 = chain(name, last, mi(a="r", alu="passa", w=HI),
                   mi(a="r", alu="a", cin="mq31", ldcl="zero"),
                   end(name, b="mq", alu="passb", w="d", fnz="nz", fc="ncl", fv="ncl"))
    big = chain(name, mi(rb=src, md="mqload", alu="zero", ldr=1),
                loop(name, step, "tc", tail32))
    small16 = chain(name, last, mi(a="r", alu="passa", rz=0b1100, ldr=1),
                    mi(a="r", b="mq", alu="or", rms="ror16", ldr=1),
                    mi(a="r", alu="passa", w="d", fnz="nz", fill="a31", ldsgn=1),
                    end(name, b="fillall", fill="sgn", alu="passb", w=HI, czero=1, fv="0"))
    small = chain(name, mi(b="r", md="mqload", alu="zero", ldr=1),
                  loop(name, step, "tc4", small16))
    # x fits in 16 signed bits iff x ^ (32 copies of its sign) < 2^15
    return chain(name,
                 mi(ra="d", b="fillall", fill="a31", alu="xor", ldcl="hz17"),
                 mi(ra=src, b="fillall", fill="a31", alu="xor", ldcl="and_hz17"),
                 mi(ra=KE1, alu="passa", ldlc=1),
                 branch(name, mi(ra=src, alu="passa", rz=0b1100, ldr=1), "cl", big, small))


def div_routine(name):
    """Non-restoring, the partial remainder in R (its sign in S33), the
    quotient's bits shifted into MQ."""
    divz = trap("divide", 2)
    if name in ("DIVU", "DIVUL"):
        out = chain(name, mi(a="r", rb="r", md="fix", ldr=1),
                    mi(a="r", alu="passa", w=HI),
                    end(name, b="mq", alu="passb", w="d", fnz="nz", czero=1, fv="0"))
        body = loop(name, mi(a="r2", sina="mq31", rb="r", md="div", ldr=1, lcinc=1), "tc", out)
        if name == "DIVU":
            return chain(name, mi(ra="r", alu="passa", ldcl="zero"),
                         mi(ra=KE0, alu="passa", ldlc=1),
                         branch(name, mi(rb="d", md="mqload", alu="zero", ldr=1), "cl",
                                body, divz))
        # DIVUL: HI >= rs would overflow: V, and nothing else changes
        ovf = end(name, fv="1")
        return chain(name, mi(ra="r", alu="passa", ldcl="zero"),
                     mi(ra=KE0, alu="passa", ldlc=1),
                     branch(name, mi(ra=HI, rb="r", alu="sub", ldcl="aluc"), "cl",
                            branch(name, mi(rb="d", md="mqload", ra=HI, alu="passa", ldr=1), "cl",
                                   body, ovf),
                            divz))
    # DIVS: on magnitudes, the signs fixed at the end
    quot = chain(name,
                 mi(a="r", b="fillall", fill="sgn", alu="xor", ldr=1),
                 mi(a="r", alu="a", cin="sgn", ldr=1),            # remainder, sign of rd
                 mi(a="r", alu="passa", w=HI),
                 mi(ra="d", rb="r", alu="xor", ldr=1),
                 mi(a="r", fill="a31", ldsgn=1, b="mq", alu="passb", ldr=1),
                 mi(a="r", b="fillall", fill="sgn", alu="xor", ldr=1),
                 end(name, a="r", alu="a", cin="sgn", w="d", fnz="nz", czero=1, fv="0"))
    # |rd| = 2^31 and |rs| = 1: the quotient is 0x80000000 either way, and
    # V is set if the signs were equal
    special = chain(name, mi(ra="d", rb="r", alu="xor", ldr=1),
                    branch(name, mi(alu="zero", w=HI), "r31",
                           end(name, b="mq", alu="passb", w="d", fnz="nz", czero=1, fv="1"),
                           end(name, b="mq", alu="passb", w="d", fnz="nz", czero=1, fv="0")))
    out = branch(name, mi(a="r", rb=TMP1, md="fix", ldr=1), "mq31", quot, special)
    body = loop(name, mi(a="r2", sina="mq31", rb=TMP1, md="div", ldr=1, lcinc=1), "tc", out)
    return chain(name,
                 mi(ra="r", b="fillall", fill="a31", ldsgn=1, alu="xor", ldr=1),
                 mi(a="r", alu="a", cin="sgn", w=TMP1, ldcl="zero"),       # |rs|
                 branch(name, mi(ra="d", b="fillall", fill="a31", ldsgn=1, alu="xor", ldr=1),
                        "cl",
                        chain(name, mi(a="r", alu="a", cin="sgn", ldr=1),   # |rd|
                              mi(b="r", md="mqload", ra=KE0, alu="passa", ldlc=1),
                              mi(alu="zero", ldr=1),
                              body),
                        divz))


def rr_routine(name):
    """Row E's register forms, and the other register-register cells."""
    d = mi(ra="d", rb="r")
    if name in ("ADC", "SBC"):
        return end(name, _fields=merge(d, mi(alu=name.lower(), fc="aluc", fv="ovf", w="d",
                                             fnz="sticky")))
    if name == "BIC":
        return end(name, _fields=merge(d, mi(alu="bic", w="d", fnz="nz")))
    if name == "TST":
        return end(name, _fields=merge(d, mi(alu="and", fnz="nz")))
    if name in ("MULU", "MULS"):
        return mul_core(name, name, "r")
    if name in ("DIVU", "DIVS", "DIVUL"):
        return div_routine(name)
    if name == "MERGE":
        # tentative: (rd & ~HI) | (rs & HI)
        return chain(name, mi(ra="d", rb=HI, alu="bic", w=TMP2),
                     mi(ra="r", rb=HI, alu="and", ldr=1),
                     end(name, a="r", rb=TMP2, alu="or", w="d", fnz="nz"))
    if name == "ADD.B4":
        # tentative: ((a & 7F7F7F7F) + (b & 7F7F7F7F)) ^ ((a ^ b) & 80808080)
        return chain(name,
                     mi(ra="d", rb="r", alu="xor", ldr=1),
                     mi(a="r", rb=K80, alu="and", w=TMP2),
                     mi(ra="d", rb=K7F, alu="and", ldr=1),
                     mi(ra="r", rb=K7F, alu="and", w=TMP3),
                     mi(a="r", rb=TMP3, alu="add", ldr=1),
                     end(name, a="r", rb=TMP2, alu="xor", w="d", fnz="nz"))
    raise ValueError(name)


def mula_routine():
    """Tentative MULA rd, rs: HI:LO <- HI:LO + rd x rs, signed; no flags.
    MULS's 32-step loop, then a 64-bit add."""
    name = "MULA"
    step = mi(a="r", rb="d", md="mulu", rms="shr", sin="f31", ldr=1, lcinc=1)
    last = mi(a="r", rb="d", md="muls", rms="shr", sin="f31", ldr=1)
    acc = chain(name, last,
                mi(a="r", alu="passa", w=TMP2),                         # high
                mi(b="mq", alu="passb", ldr=1),                         # low
                mi(ra=LO, b="r", alu="add", w=LO, ldcl="aluc"),
                branch(name, mi(ra=TMP2, alu="passa", ldr=1), "cl",
                       end(name, ra=HI, b="r", alu="add", w=HI),
                       end(name, ra=HI, b="r", alu="addc", cin="1", w=HI)))
    return chain(name, mi(ra=KE1, alu="passa", ldlc=1),
                 mi(rb="r", md="mqload", alu="zero", ldr=1),
                 loop(name, step, "tc", acc))


def mulfx_routine():
    """Tentative MULFX rd, rs, #n (FD 00, then a parcel: rd in 15-12, rs in
    11-8, n in 4-0, 7-5 zero): rd <- (rd x rs) >> n, signed, HI <- the
    product's high half. The parcel is checked, then a dispatch on its
    bits 11-8 picks a routine per rs, with SX = rd."""
    name = "MULFX"
    table = [mulfx_body(rs, name) for rs in range(16)]
    first = Node(mi(b="qh", fill="0", alu="passb", w=TMP3, ldsx="qhx", consume=1),
                 ("dispatch", table), name)
    return chain(name, mi(ra=KMULFX, b="qh", fill="0", alu="and", ldcl="zero"),
                 branch(name, {}, "cl", illegal(2), first))


def mulfx_body(rs, name):
    """SX = rd, TMP3 = the parcel: MULS of r[SX] by r[rs], 16 steps if both
    fit in 16 signed bits, else 32; then R:MQ shifted right n places, one a
    cycle (MQ shifting right with R, R's sign in)."""
    step = mi(a="r", rb="x", md="mulu", rms="shr", sin="f31", ldr=1, lcinc=1)
    last = mi(a="r", rb="x", md="muls", rms="shr", sin="f31", ldr=1)
    shift = mi(a="r", alu="passa", md="shr64", rms="shr", sin="f31", ldr=1, lcinc=1)
    nload = mi(ra=TMP3, kv=0xE0 - 256, alu="ornb", ldlc=1)            # LC <- 255 - n
    # 32 steps: R:MQ is the product P, HI <- R; shifted, MQ is the result,
    # and it fits iff R is MQ's sign extension
    fin = chain(name, mi(a="r", alu="a", cin="mq31", ldcl="zero"),
                end(name, b="mq", alu="passb", w="x", fnz="nz", fc="ncl", fv="ncl"))
    big = chain(name, last, nload,
                branch(name, mi(a="r", alu="passa", w=HI, lcinc=1), "tc",
                       loop(name, shift, "tc", fin), fin))
    # 16 steps: R:MQ is P x 2^16 (MQ's low half the multiplier's sign, not
    # part of it); shifted, the result is R:MQ's bits 47-16. P has 31
    # bits, so it fits and HI is its sign
    sfin = chain(name, mi(a="r", alu="passa", rz=0b1100, w=TMP2),
                 mi(b="mq", alu="passb", rz=0b0011, ldr=1),
                 mi(ra=TMP2, b="r", alu="or", rms="ror16", w="x", fnz="nz"),
                 end(name, b="fillall", fill="sgn", alu="passb", w=HI, czero=1, fv="0"))
    small = chain(name, last, nload,
                  branch(name, mi(a="r", fill="a31", ldsgn=1, lcinc=1), "tc",
                         loop(name, shift, "tc", sfin), sfin))
    return chain(name,
                 mi(ra="x", b="fillall", fill="a31", alu="xor", ldcl="hz17"),
                 mi(ra=rs, b="fillall", fill="a31", alu="xor", ldcl="and_hz17"),
                 mi(ra=KE1, alu="passa", ldlc=1),
                 branch(name, mi(rb=rs, md="mqload", alu="zero", ldr=1), "cl",
                        loop(name, step, "tc", big), loop(name, step, "tc4", small)))


# --------------------------------------------------------------------------
# Branches and calls
#
# A cycle that loads the PC flushes the prefetch queue and points the fetch
# at the target. If it's the instruction's last (decode) cycle, the decode
# is forced to the refill entry; otherwise the next cycle is a decode that
# fetches ("refill-type": MEM fetch).


def bcc_routine(cc):
    name = {15: "BSR", 14: "BRA"}.get(cc, f"B{v2.COND[cc] if cc < 15 else ''}")
    target = mi(a="pc", imm="bcc", alu="add", ldpc=1)             # PC + 2 x s8
    if cc == 15:
        return chain(name, mi(a="pc", alu="passa", w=LINK), end(name, _fields=target))
    if cc == 14:
        return end(name, _fields=target)
    return end(name, _fields=merge(target, mi(pccond="bcond", ccb="bcc")))


def jcc_routine(cc, absolute):
    """F2 (PC-relative) and F3 (absolute); cc 14 is JMP, 15 CALL."""
    base = {15: "CALL", 14: "JMP"}.get(cc, f"J{v2.COND[cc] if cc < 15 else ''}")
    name = base + (" abs" if absolute else "")
    cond = {} if cc >= 14 else mi(pccond="bcond", ccb="jcc")
    refill = end(name, mem="fetch")
    if not absolute:
        target = mi(a="pc", pck=1, b="qh2", fill="qh15", alu="addc", cin="1")   # PC + 2 + 2 s16
        if cc == 15:
            # r7 <- PC + 2, the next instruction (the parcel isn't consumed)
            return chain(name, mi(a="pc", pck=1, alu="a", cin="1", w=LINK),
                         end(name, _fields=merge(target, mi(ldpc=1))))
        return chain(name, merge(target, cond, mi(ldpc=1, consume=1)), refill)
    first = mi(b="qh", fill="0", alu="passb", ldr=1, consume=1)
    tgt = mi(a="r", b="qhh", alu="or")
    if cc == 15:
        return chain(name, first, merge(tgt, mi(ldr=1, consume=1)),
                     mi(a="pc", alu="passa", w=LINK), end(name, a="r", alu="passa", ldpc=1))
    return chain(name, first, merge(tgt, cond, mi(ldpc=1, consume=1)), refill)


def dbnz_routine(k):
    """r <- r - 1; unless that's 0, PC <- PC - 2k (PC: the next instruction)."""
    name = "DBNZ"
    return chain(name, mi(ra="d", alu="dec", w="d", ldcl="zero"),
                 end(name, a="pc", kv=-2 * k, alu="add", ldpc=1, pccond="ncl"))


# --------------------------------------------------------------------------
# Multiple registers: a loop, one register a cycle, the register number
# counting in SX until it reaches EX


def save_routine(a, b):
    """SAVE ra-rb: MAR, R <- sp - 4n (n from the register byte: the decode
    table gives each range its own first cycle), the registers from SX up,
    then sp <- R."""
    name = "SAVE"
    final = end(name, b="r", alu="passb", w=SP)
    body = Node(mi(ra="x", mem="write", size="word", marinc=1, sxinc=1), None, name)
    body.succ = ("branch", CONDS["sxeq"], body, final)
    return chain(name, mi(ra=SP, kv=4 * (b - a + 1), alu="sub", ldmar=1, ldr=1, ldsx="d",
                          ldex="r"), body)


def restore_routine(a, b):
    name = "RESTORE"
    final = end(name, ra=SP, kv=4 * (b - a + 1), alu="add", w=SP)
    body = Node(mi(mem="read", size="word", b="t", alu="passb", w="x", marinc=1, sxinc=1), None,
                name)
    body.succ = ("branch", CONDS["sxeq"], body, final)
    return chain(name, mi(ra=SP, alu="passa", ldmar=1, ldsx="d", ldex="r"), body)


def ldm_routine(store):
    """LDM rb, ra-rc and STM: ra in the high nibble, rb (the base) in the
    low one, rc in the parcel's bits 15-12, whose other bits must be 0. A
    dry run of SX from ra checks rc >= ra before any access. rb doesn't
    change (an LDM whose range holds rb loads it in its turn)."""
    name = "STM" if store else "LDM"
    bad = illegal(4)
    if store:
        body = Node(mi(ra="x", mem="write", size="word", marinc=1, sxinc=1), None,
                    name)
    else:
        body = Node(mi(mem="read", size="word", b="t", alu="passb", w="x", marinc=1, sxinc=1),
                    None, name)
    body.succ = ("branch", CONDS["sxeq"], body, end(name))
    start = Node(mi(ra="r", alu="passa", ldmar=1, ldsx="d"), ("next", body), name)
    eq = Node({}, None, name)
    t15 = Node({}, None, name)
    dry = Node(mi(sxinc=1), ("next", eq), name)
    eq.succ = ("branch", CONDS["sxeq"], t15, start)
    t15.succ = ("branch", CONDS["sx15"], dry, bad)
    check = mi(ra=K0FFF, b="qh", fill="0", alu="and", ldcl="zero", ldex="qhx", ldsx="d",
               consume=1)
    return chain(name, check, branch(name, {}, "cl", bad, eq))


# --------------------------------------------------------------------------
# System instructions (RFC 0029)


def mfsr_routine(n):
    name = f"MFSR {n}"

    def rd(**kw):
        return end(name, _fields=merge(mi(**kw), mi(w="d")))
    if n == 0:
        return rd(b="flags", alu="passb")
    if n in (1, 2):
        return rd(rb=HI if n == 1 else LO, alu="passb")
    if n < 8:
        return rd(rb=ZERO, alu="passb")
    if n == 8:
        body = rd(b="far", alu="passb")
    elif n == 9:
        body = rd(b="fsr", alu="passb")
    elif n == 10:
        body = rd(rb=CTXC, alu="passb")
    elif n == 11:
        # mapa, kept as mapa << 12: >> 8 by a rotation, then four shifts
        body = chain(name, mi(ra=MAPAS, alu="passa", rms="ror8", rz=0b1000, ldr=1),
                     mi(a="r", alu="passa", rms="shr", sin="0", ldr=1),
                     mi(a="r", alu="passa", rms="shr", sin="0", ldr=1),
                     mi(a="r", alu="passa", rms="shr", sin="0", ldr=1),
                     rd(a="r", alu="passa", rms="shr", sin="0"))
    elif n == 12:
        # the map entry at mapa: MAR <- mapa << 12, the map onto B
        body = chain(name, mi(rb=MAPAS, alu="passb", ldmar=1),
                     rd(mem="mapr", b="map", alu="passb"))
    elif n == 13:
        body = rd(rb=BANKC, alu="passb")
    else:
        body = rd(rb=ZERO, alu="passb")
    return privileged(name, body)


def mtsr_routine(n):
    name = f"MTSR {n}"
    if n == 0:
        return branch(name, {}, "sup", end(name, ra="r", loadf="nzcv"),
                      end(name, ra="r", loadf="sup"))
    if n in (1, 2):
        return end(name, ra="r", alu="passa", w=HI if n == 1 else LO)
    if n < 8:
        return end(name)
    if n in (8, 9, 14, 15):
        body = end(name)                              # read only, or reserved
    elif n == 10:
        body = end(name, ra="r", kv=0x7F, alu="and", w=CTXC, ldctx=1)
    elif n == 11:
        # mapa <- rs, kept as (rs << 12) & 0x7FFFF000: x4 a cycle
        dbl = mi(a="r2", sina="0", alu="dbl", cin="0", ldr=1)
        body = chain(name, mi(ra="r", alu="passa", ldr=1), dbl, dbl, dbl, dbl, dbl, dbl,
                     end(name, a="r", rb=MAPMASK, alu="and", w=MAPAS))
    elif n == 12:
        # map[mapa] <- rs, and mapa moves on by one
        body = chain(name, mi(rb=MAPAS, alu="passb", ldmar=1),
                     mi(mem="mapw", rb="r", ra=K1000, alu="passa", ldr=1),
                     end(name, ra=MAPAS, b="r", alu="add", w=MAPAS))
    elif n == 13:
        body = end(name, ra="r", alu="passa", rz=0b1110, w=BANKC, ldbank=1)
    else:
        raise ValueError(n)
    return privileged(name, body)


def mfur_routine():
    return privileged("MFUR", end("MFUR", ra="r", ubr=1, alu="passa", w="d"))


def mtur_routine():
    return privileged("MTUR", end("MTUR", ra="r", alu="passa", w="d", ubw=1))


def swi_routine(n):
    """SWI #n: through vector 0x8000_0100 + 4n, the next instruction saved."""
    name = f"SWI #{n}"
    return chain(name, mi(ra=VSWI[n >> 6], kv=4 * (n & 63), alu="add", w=TMP2),
                 Node(SAVE_FLAGS, ("next", trap_tail(TMP2, 0, "SWI")), name))


def rti_routine():
    """Pop the flags word, then the PC, in bank 0; the flags (S with them)
    and the jump in the last cycle."""
    name = "RTI"
    body = chain(name,
                 mi(ra=SP, alu="passa", ldmar=1),
                 mi(mem="read", size="word", b="t", alu="passb", ldr=1, marinc=1),   # flags
                 mi(mem="read", size="word", ra=SP, kv=8, alu="add", w=SP),           # PC
                 end(name, a="r", loadf="all", b="t", alu="passb", ldpc=1))
    return privileged(name, body)


def halt_routine():
    return privileged("HALT", Node({}, ("halt",), "HALT"))


def ei_di(val):
    name = "EI" if val else "DI"
    return privileged(name, end(name, fi="1" if val else "0"))


def setcc_routine(cc):
    name = f"SET{v2.COND[cc]}"
    if cc == 14:
        return end(name, kv=1, alu="passb", w="d")
    return branch(name, mi(ccb="set"), "ncondt" if cc & 1 else "condt",
                  end(name, kv=0, alu="passb", w="d"), end(name, kv=1, alu="passb", w="d"))


def tagged_routine(op):
    """Tentative: TMOV TTST TADD TSUB TCMP. The tag check (bit 0 clear) on
    rs, or on both; TADD and TSUB also trap on overflow, which a trial
    operation into R finds before anything changes."""
    name = v2.TAGGED[op]
    tag = trap("tag", 2)
    if name == "TMOV":
        return chain(name, mi(ra="r", kv=1, alu="and", ldcl="zero"),
                     branch(name, {}, "cl", tag, end(name, ra="r", alu="passa", w="d")))
    if name == "TTST":
        op_end = end(name, ra="d", rb="r", alu="and", fnz="nz")
    elif name == "TCMP":
        op_end = end(name, ra="d", rb="r", alu="sub", fnz="nz", fc="aluc", fv="ovf")
    else:
        alu = "add" if name == "TADD" else "sub"
        # overflow iff bit 31 of (rd ^ res) & (b ^ res), b = rs or ~rs
        op_end = chain(name,
                       mi(ra="d", rb="r", alu=alu, ldr=1),
                       mi(ra="d", b="r", alu="xor", w=TMP2),
                       mi(ra="r", b="r", alu="xor" if alu == "add" else "xnor", ldr=1),
                       mi(ra=TMP2, b="r", alu="and", ldr=1),
                       branch(name, {}, "r31",
                              end(name, ra="d", rb="r", alu=alu, w="d", fnz="nz", fc="aluc",
                                  fv="ovf"),
                              tag))
    return chain(name, mi(ra="d", rb="r", alu="or", ldr=1),
                 mi(a="r", kv=1, alu="and", ldcl="zero"),
                 branch(name, {}, "cl", tag, op_end))


# --------------------------------------------------------------------------
# Decode: which routine runs for each first parcel

EA_ROWS = {1: "MOV", 2: "ST", 3: "MOVS", 4: "ADD", 5: "SUB", 6: "CMP", 8: "AND", 9: "OR",
           0xA: "XOR"}


def _sub(M, R):
    """The part of R a routine depends on: all of it for the modes whose R
    is a constant or picks the operand (1, 4, D, E, F), none for the others
    (R comes from IR)."""
    return R if M in (1, 4, 0xD, 0xE, 0xF) else 0


def classify(w):
    """Routine key and instruction length (parcels) for a first parcel."""
    op, rb = w & 0xFF, w >> 8
    hi, lo = rb >> 4, rb & 15
    row, col = op >> 4, op & 15
    ill = (("illegal",), 1)
    if op in v2.FREE:
        return ill
    if op in (0x01, 0x02):
        return ("ldm", op == 0x02), 2
    if 0x04 <= op <= 0x07:
        M = [3, 4, 5, 0xF][op - 4]
        R = lo if M in (4, 0xF) else 0
        n = 1 + ext_parcels(M, lo)
        if M == 0xF and (lo <= 3 or lo == 0xF):
            return ("illegal",), n
        return ("lea", M, R), n
    if op == 0x08:
        return ("rr", "ADD.B4"), 1
    if 0x09 <= op <= 0x0D:
        return ("tag", op), 1
    if op == 0x0E:
        return ("mfsr", lo), 1
    if op == 0x0F:
        return ("mtsr", hi), 1
    if op in (0x20, 0x21, 0x2D):
        name = {0x20: "CLR", 0x21: "INC", 0x2D: "DEC"}[op]
        n = 1 + ext_parcels(hi, lo)
        if hi in (1, 0xD) or (hi == 0xF and (lo <= 3 or lo == 0xF)):
            return ("illegal",), n
        return ("ea", name, hi, _sub(hi, lo)), n
    if 0x70 <= op <= 0x7F:
        return ("u7", op >= 0x78), 1
    if 0xB0 <= op <= 0xBF:
        return ("bcc", col), 1
    if 0xC0 <= op <= 0xCF:
        kind = (op >> 2) & 3
        if op & 3 in (0, 1):
            return ("shift", kind, lo << 1 | (op & 1)), 1
        if op & 3 == 2:
            return ("shreg", kind), 1
        return ill
    if 0xD0 <= op <= 0xDE:
        return ("un", v2.UNARY[col]), 1
    if op == 0xDF:
        return (("setcc", lo), 1) if lo != 15 else ill
    if op == 0xE6:
        return ("mula",), 1
    if 0xE0 <= op <= 0xE9:
        return ("rr", v2.ROW_E[col]), 1
    if 0xEA <= op <= 0xED:
        n = 1 + ext_parcels(0xF, lo)
        if lo == 0xF:
            return ("illegal",), n
        return ("ea", v2.ROW_E[col], 0xF, lo), n
    if op == 0xEE:
        return ("rr", "MERGE"), 1
    if op in (0xF0, 0xF1):
        n = 1 + ext_parcels(hi, lo)
        if hi == 0xF and lo == 0xF:
            return ("illegal",), n
        return ("jea", op == 0xF1, hi, _sub(hi, lo) if hi != 0 else lo), n
    if op == 0xF2:
        return (("jcc", hi, False), 2) if lo == 0 else (("illegal",), 2)
    if op == 0xF3:
        return (("jcc", hi, True), 3) if lo == 0 else (("illegal",), 3)
    if op in (0xF4, 0xF5):
        if hi > lo or lo > 14:
            return ill
        return ("save" if op == 0xF4 else "restore", hi, lo), 1
    if op == 0xF6:
        return ("dbnz", lo + 1), 1
    if op == 0xFC:
        return ("swi", rb), 1
    if op == 0xFD:
        return (("mulfx",), 2) if rb == 0 else ill
    if op == 0xFE:
        return {0: ("ei", 1), 1: ("ei", 0), 2: ("rti",), 3: ("halt",)}.get(rb, ("illegal",)), 1
    if row in EA_ROWS:
        if row == 3 and col in (1, 0xD):
            return (("mfur",) if col == 1 else ("mtur",)), 1
        n = 1 + ext_parcels(col, lo)
        if col == 0xF and lo == 0xF:
            return ("illegal",), n
        name = EA_ROWS[row]
        if name == "ST" and not (is_mem(col, lo) or col == 5):
            return ("illegal",), n
        return ("ea", name, col, _sub(col, lo)), n
    return ill


def routine(key):
    kind = key[0]
    if kind == "illegal":
        return illegal(2)
    if kind == "ea":
        _, name, M, R = key
        rname = f"{name} m{M:X}" + (f"/{R:X}" if M in (1, 4, 0xD, 0xE, 0xF) else "")
        return ea_routine(name, M, R, rname)
    if kind == "lea":
        _, M, R = key
        return lea_routine(M, R, f"LEA m{M:X}" + (f"/{R:X}" if M in (4, 0xF) else ""))
    if kind == "u7":
        if key[1]:
            return end("CMP #u7", ra="d", imm="u7", alu="sub", fnz="nz", fc="aluc", fv="ovf")
        return end("MOV #u7", imm="u7", alu="passb", w="d")
    simple = {"bcc": bcc_routine, "shreg": shift_reg_routine, "un": unary_routine,
              "setcc": setcc_routine, "rr": rr_routine, "dbnz": dbnz_routine,
              "swi": swi_routine, "ei": ei_di, "mfsr": mfsr_routine, "mtsr": mtsr_routine,
              "ldm": ldm_routine, "tag": tagged_routine}
    if kind in simple:
        return simple[kind](key[1])
    if kind == "shift":
        return shift_routine(key[1], key[2])
    if kind == "jea":
        _, call, M, R = key
        return jea_routine(call, M, R, ("CALL" if call else "JMP") + f" m{M:X}")
    if kind == "jcc":
        return jcc_routine(key[1], key[2])
    if kind == "save":
        return save_routine(key[1], key[2])
    if kind == "restore":
        return restore_routine(key[1], key[2])
    if kind == "mula":
        return mula_routine()
    if kind == "mulfx":
        return mulfx_routine()
    if kind == "rti":
        return rti_routine()
    if kind == "halt":
        return halt_routine()
    if kind == "mfur":
        return mfur_routine()
    if kind == "mtur":
        return mtur_routine()
    raise ValueError(key)


def reset_routine():
    """Reset (control store address 0): the register file's constants, the
    flags (S set, nothing else), ctx and bank 0, then the jump to the reset
    vector, 0x8000_0000."""
    steps = [mi(kv=0, alu="passb", w=ZERO, ldctx=1, ldbank=1),
             mi(kv=-1, alu="passb", w=ONES),
             mi(kv=1, alu="passb", rms="shr", sin="f0", w=VBASE),    # 0x8000_0000
             mi(ra=ZERO, loadf="nzcv", sset=1)]                       # S; I, T, N Z C V 0

    def const(loc, val):
        sv = val - (1 << 32) if val & 0x80000000 else val
        if -256 <= sv <= 255:
            return [mi(kv=sv, alu="passb", w=loc)]
        if val & 0x80000000 and (val & 0x7FFFFFFF) <= 255:
            return [mi(ra=VBASE, kv=val & 0xFF, alu="or", w=loc)]
        b = [(val >> (8 * i)) & 0xFF for i in range(4)]
        top = max(i for i in range(4) if b[i])
        out = [mi(b="simm", v8="k", k=b[top], fill="0", alu="passb", ldr=1)]
        for i in range(top - 1, -1, -1):
            out += [mi(a="r", alu="passa", rms="ror8", ldr=1)] * 3        # << 8
            out.append(merge(mi(a="r", alu="or", ldr=1), mi(b="simm", v8="k", k=b[i], fill="0")))
        last = {k: v for k, v in out.pop().items() if k != "LDR"}
        out.append(merge(last, mi(w=loc)))
        return out
    for loc in sorted(CONSTS):
        if loc not in (ZERO, ONES, VBASE):
            steps += const(loc, CONSTS[loc])
    steps.append(mi(alu="zero", w=HI))
    steps.append(mi(alu="zero", w=LO))
    return chain("reset", *steps, end("reset", rb=VEC["reset"], alu="passb", ldpc=1))


# --------------------------------------------------------------------------
# Placement

TABLE = 16
REFILL_ADDR = 1 << U_SHIFT
IRQ_ADDR = 2 << U_SHIFT
TRACE_ADDR = 3 << U_SHIFT


def fault_addr(ln):
    """Control store address of the fault entry for an instruction that has
    consumed ln parcels."""
    return (4 | ln) << U_SHIFT


def fault_entry(ln):
    """A fault in a memory access: FK says which kind (0 page fault, 1
    misaligned, 2 bus error, which goes to the address error vector), FAR
    and FSR hold its address and reason. The saved PC is the
    instruction's own, ln parcels back."""
    pcfix = 2 * ln
    page = trap_tail(VEC["page"], pcfix, "page fault")
    addr = trap_tail(VEC["address"], pcfix, "address error")
    return branch("fault", SAVE_FLAGS, "fk1", branch("fault", {}, "fk0", page, addr), addr)


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
    from each other. A node wanted in two groups (or at a fixed address)
    is cloned."""
    groups = {}
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
            continue
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
    """Merge identical free-standing nodes (same fields, same successors)."""
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
    """Placed microcode: control store contents, decode table, entry points."""

    def __init__(self):
        _trap_cache.clear()
        self.reset = reset_routine()
        self.reset.fixed = 0
        self.fixed = {REFILL_ADDR: end("refill", mem="fetch"),
                      IRQ_ADDR: trap("irq", 0, "interrupt"),
                      TRACE_ADDR: trap("trace", 0, "trace")}
        for ln in range(4):
            self.fixed[fault_addr(ln)] = fault_entry(ln)
        for a, n in self.fixed.items():
            n.fixed = a
        self.keys, self.lens = {}, {}
        self.entry = {}
        for w in range(0x10000):
            k, ln = classify(w)
            self.keys[w], self.lens[w] = k, ln
            if k not in self.entry:
                self.entry[k] = routine(k)
        roots = [self.reset, *self.fixed.values(), *self.entry.values()]
        self.groups = _assign_slots(roots)
        nodes = _reachable(roots)
        nodes = _dedup(nodes, {id(n) for n in roots})
        self.nodes = _reachable(roots)
        self._place()
        self._check()
        from . import timing
        timing.assign_classes(self)

    def _place(self):
        size = 1 << Y_BITS
        used = [None] * size
        used[0] = self.reset
        self.reset.addr = 0
        for n in self.nodes:
            if n.fixed is not None:
                n.addr = n.fixed
        groups = defaultdict(list)
        for n in self.nodes:
            if n.slot is not None:
                groups[n.slot[0]].append(n)
        top = size
        for gid, members in groups.items():
            if self.groups[gid] != "table":
                continue
            top -= TABLE
            for m in members:
                m.addr = top + m.slot[1]
                assert used[m.addr] is None
                used[m.addr] = m
        pos = 2
        for gid, members in groups.items():
            if self.groups[gid] != "pair":
                continue
            while used[pos] is not None or used[pos + 1] is not None:
                pos += 2
            for m in members:
                m.addr = pos + m.slot[1]
                used[m.addr] = m
            pos += 2
        free = (a for a in range(1, size) if used[a] is None)
        for n in self.nodes:
            if n.addr is None:
                n.addr = next(free)
                used[n.addr] = n
        if any(n.addr >= top for n in self.nodes
               if (n.slot is None or self.groups[n.slot[0]] != "table") and n.fixed is None):
            raise RuntimeError("microcode doesn't fit")
        self.used = len(self.nodes)
        self.by_addr = {n.addr: n for n in self.nodes}

    def word(self, n):
        """Field dict of node n as stored at its address."""
        f = dict(n.f)
        s = n.succ
        if s[0] == "next":
            assert s[1].addr is not None and s[1].addr < (1 << Y_BITS), n.name
            f["SEQ"], f["NEXT"] = SEQ_NEXT, s[1].addr
        elif s[0] == "branch":
            a0, a1 = s[2].addr, s[3].addr
            assert a0 % 2 == 0 and a1 == a0 + 1, n.name
            f["SEQ"], f["NEXT"], f["COND"] = SEQ_NEXT, a0, s[1]
        elif s[0] == "decode":
            f["SEQ"] = SEQ_DECODE
        elif s[0] == "dispatch":
            base = s[1][0].addr
            assert base % TABLE == 0
            f["SEQ"], f["NEXT"] = SEQ_DISPATCH, base
        elif s[0] == "halt":
            f["SEQ"], f["NEXT"] = SEQ_HALT, n.addr
        return f

    def _check(self):
        """Rules the hardware relies on."""
        data = (MEM["read"], MEM["write"], MEM["mapr"], MEM["mapw"], MEM["reada"])
        for n in self.nodes:
            f = n.f
            mem = f.get("MEM", 0)
            if f.get("CONSUME") and n.succ[0] == "decode":
                raise ValueError(f"{n.name}: consumes a parcel and decodes")
            if f.get("CONSUME") and mem in data:
                raise ValueError(f"{n.name}: consumes a parcel in a data access")
            if mem == MEM["write"] and not f.get("ARF") and not f.get("AR"):
                raise ValueError(f"{n.name}: a write with nothing on the A bus")
            if mem == MEM["reada"] and not f.get("ARF"):
                raise ValueError(f"{n.name}: a read at the A bus without a register on it")
            if n.succ[0] == "dispatch" and not f.get("CONSUME"):
                raise ValueError(f"{n.name}: a dispatch that doesn't consume its parcel")

    def rom(self):
        """{control store address: control word}."""
        return {n.addr: pack(self.word(n)) for n in self.nodes}

    def decode_table(self):
        """64K entries: Y | LEN << 13."""
        return [self.entry[self.keys[w]].addr | (self.lens[w] << Y_BITS) for w in range(0x10000)]


IDLE = pack(mi())

_built = None


def built():
    global _built
    if _built is None:
        _built = Microcode()
    return _built


def explain(f):
    """A microinstruction's fields, briefly (for listings and errors)."""
    return " ".join(f"{k}={v}" for k, v in sorted(f.items()) if v)
