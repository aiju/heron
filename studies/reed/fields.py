"""Reed's microinstruction: one word of 80 bits, split by board. Each board
holds its own slice of the control store (45 ns parts on the µPC lines)
and, but for CTRL's sequencer fields, a register of 574s that holds the
word executing.

  CTRL  40 bits, 5 parts: JT, SEQ and CND straight from the parts into the
        next-address logic (the µPC register is their pipeline); the rest
        through 2 x 574
  ALU   32 bits, 4 parts, 4 x 574
  MEM    8 bits, 1 part, 1 x 574

The µPC is 14 bits: 16K words. Each part is 128K x 8 with A14-A16 tied low.
"""

ADDR_BITS = 14

# (name, width), from bit 0 of the board's slice
# (LEN straight from the parts too: the next word's, a cycle early, which
# the clock card takes as the cycle starts)
CTRL_DIRECT = [("JT", 14), ("SEQ", 2), ("CND", 4), ("LEN", 2), ("CSPARE", 2)]
CTRL_REG = [("IQC", 2), ("IMM", 4), ("PCOP", 2), ("BFREE", 1), ("DACC", 1), ("IFL", 2),
            ("TK", 1), ("CSPARE2", 3)]
ALU = [("RAS", 2), ("RBS", 2), ("K", 5), ("WS", 2), ("AOP", 4), ("CI", 2), ("FL", 2), ("AIN", 1),
       ("BIN", 2), ("AOUT", 2), ("BOUT", 1), ("SI", 2), ("STOP", 2), ("NSZ", 2), ("ASPARE", 1)]
MEM = [("MOP", 3), ("MSZ", 2), ("MARLD", 1), ("MQ", 2)]

SLICES = {"CTRL": CTRL_DIRECT + CTRL_REG, "ALU": ALU, "MEM": MEM}
PARTS = {"CTRL": 5, "ALU": 4, "MEM": 1}
# CTRL's registered fields start at its bit 24 (its parts 3 and 4)
CTRL_REG_BASE = 24

# ---- codes ------------------------------------------------------------------

# BRDEC: JT if the executing word loads PC (FLUSH: a jump, or a branch
# taken), else decode (a branch's tail word)
SEQ_JUMP, SEQ_DECODE, SEQ_DECODE_NOIRQ, SEQ_BRDEC = 0, 1, 2, 3
# CND: the condition a JUMP XORs into JT's bit 0 (0: none, so JT itself)
# (interrupts are taken at a decode, not tested)
CND = {"NONE": 0, "Z": 1, "N": 2, "C": 3, "V": 4, "ST": 5, "MQ0": 6, "AERR": 7,
       "CC_OP": 8, "CC_D": 9}
# LEN: the cycle's ticks, 5 + LEN (a cycle that reads and writes the register
# file needs 5: its read, then a write phase of three ticks)
LEN_BASE = 5
# IQC: the queue: none, consume the extension parcel, latch it into H and consume it
IQC_NONE, IQC_NEXT, IQC_H = 0, 1, 2
# IMM: what CTRL drives onto B
IMM = {"NONE": 0, "PE_SX": 1, "PE_ZX": 2, "PE_HI": 3, "H_PE": 4, "Q": 5, "NQ": 6, "U7": 7,
       "S8X2": 8, "R4": 9, "ZERO": 10, "ONE": 11, "FOUR": 12, "VEC": 13}
# PCOP: PC onto A; PC and FPC loaded from A (and the queue emptied); a
# branch's target onto A, PC + 2 x the register byte (the branch adder).
# TK: PC and FPC loaded from A (the queue emptied) if the executing
# instruction's condition holds: its opcode's cc in row B, d's in row F
# (cc 14 and 15 always). A word that may load PC (LOAD or TK) doesn't
# fetch (BFREE 0).
PCOP_NONE, PCOP_DRIVE, PCOP_LOAD, PCOP_BRANCH = 0, 1, 2, 3
IFL_HOLD, IFL_SET, IFL_CLEAR = 0, 1, 2

# ALU: register selects
RAS = {"d": 0, "s": 1, "K": 2, "NONE": 3}
RBS = {"s": 0, "x": 1, "K": 2, "NONE": 3}
WS = {"NONE": 0, "d": 1, "s": 2, "K": 3}
# (the ALU's function, its carry and its flags are the microinstruction's
# alone: each operation has microcode of its own, from the decode table's
# entries, and the opcode doesn't leave CTRL; code 0s are reserved)
AOP = {"RES": 0, "ADD": 1, "SUB": 2, "AND": 3, "OR": 4, "XOR": 5, "PASSA": 6, "PASSB": 7,
       "INCA": 8, "DECA": 9, "SHL": 10, "BIC": 11, "NOTA": 12, "ZERO": 13, "MQSTEP": 14, "ONES": 15}
# CI OWN: the function's own (a subtract and an increment carry in)
CI = {"0": 0, "1": 1, "C": 2, "OWN": 3}
# SH: a shift's: N and Z, C the bit shifted out (OA's bit 0 on the shift
# path, else the carry out: a left shift is A + A), V cleared
FL = {"NONE": 0, "SH": 1, "NZ": 2, "NZCV": 3}
# NSZ: the operand's size for N and Z: N from bit 31, 15 or 7, Z from the
# word, the low half or the low byte (a byte's MOVS, INC, DEC)
NSZ = {"WORD": 0, "HALF": 1, "BYTE": 2}
BIN = {"RF": 0, "BUS": 1, "SHIFT": 2, "NONE": 3}
AOUT = {"NONE": 0, "OA": 1, "F": 2}
SI = {"0": 0, "C": 1, "SIGN": 2, "ROT": 3}
STOP = {"HOLD": 0, "Z": 1, "F31": 2, "C32": 3}

# MEM
# (MOP 3 reserved: FPC loads on CTRL's FLUSH)
MOP = {"NONE": 0, "LOAD": 1, "STORE": 2, "RES": 3}
MSZ = {"BYTE": 0, "HALF": 1, "WORD": 2}
MQ = {"HOLD": 0, "SHIFT": 1, "LOAD": 2, "DRIVE": 3}


def positions(board):
    """{field: (first bit in the board's slice, width)}"""
    out, b = {}, 0
    for name, w in SLICES[board]:
        out[name] = (b, w)
        b += w
    return out


def nets(board, name):
    """The nets a field's bits are on: uFIELDi on the board (after the
    574s), CTRL's sequencer fields straight from its parts."""
    b, w = positions(board)[name]
    return [f"u{name}{i}" if w > 1 else f"u{name}" for i in range(w)]


def word_bits(board):
    """{bit of the board's slice: net}"""
    out = {}
    for name, (b, w) in positions(board).items():
        for i, n in enumerate(nets(board, name)):
            out[b + i] = n
    return out


def pack(board, **fields):
    pos = positions(board)
    w = 0
    for name, v in fields.items():
        b, n = pos[name]
        if v >> n:
            raise ValueError(f"{name}={v} doesn't fit {n} bits")
        w |= v << b
    return w
