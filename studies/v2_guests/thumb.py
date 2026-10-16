"""ARMv6-M Thumb on the draft 2 CPU with a wider decode table ([D1] in
rtlx.py): what clang emits for a Cortex-M0.

Thumb is the instruction set closest to draft 2's datapath: 16-bit
parcels, little-endian, 32-bit registers, aligned accesses, and flags N, Z,
C, V with the same sense (C is "no borrow" after a subtraction) and the
same condition codes, ARM's. What doesn't fit the unmodified CPU is where
the fields are: three-bit register numbers at bits 2-0, 5-3 and 8-6,
immediates of 3, 5, 7, 8 and 11 bits. On draft 2 a register number can
only come from IR[15:12] or IR[11:8], and the immediate unit takes a few
fixed fields of IR. Without a change Thumb would be done as RV32 is
(registers in banks, fields through tables, some 8 cycles an
instruction); with the decode table giving, for every first parcel, an IR
to load and an immediate, it runs much as draft 2's own code does:

- `xir`: the destination register (or the one read and written) into
  IR[15:12], a source into IR[11:8], so the selectors `d` and `r` address
  them; a third register, where there is one, is a constant of the routine
  (the decode table specialises on it); B<cond>'s condition into IR[3:0].
- `ximm`: the immediate, already shifted, scaled and offset as the
  routine wants it: 4 x imm8 for SP-relative words, 2 x imm8 + 2 for a
  branch (the native PC is the instruction + 2, ARM's PC the
  instruction + 4), and so on. BX = 6 puts it on the B bus.

r0-r14 are locations 0-14 of the bank (bank 0 in supervisor mode, BANK
in user mode); r15 is the native PC. On its own, BKPT halts, and SVC and
the undefined encodings stop. Beside draft 2's own microcode (mixed.py),
SVC #n is draft 2's SWI #n and the undefined encodings its illegal
instruction trap, and an instruction that faults can be restarted: no
register is written before its last memory access (but LDM with the base
in the list). Its constants are in the two global locations draft 2's
microcode leaves free. BL's 32-bit form assumes J1 = J2 = 1 (offsets
within 4 MB).
"""

from heron.studies.v2_hw import ucode as uc
from heron.studies.v2_hw.ucode import mi, merge, chain, branch, loop, end, Node

from . import guest as gm

M32 = 0xFFFFFFFF
G = uc.G
TMP1, TMP2, TMP3, ZERO = uc.TMP1, uc.TMP2, uc.TMP3, uc.ZERO      # draft 2's
K8000, K0FFE = G + 30, G + 31             # the two global locations draft 2 leaves
CONSTS = {K8000: 0x8000, K0FFE: 0x0FFE}
assert not set(CONSTS) & set(uc.CONSTS)
SP, LR = 13, 14
IMM = {"BX": 6}                       # [D1] the predecoded immediate onto B
NZ = dict(fnz="nz")
NZCV = dict(fnz="nz", fc="aluc", fv="ovf")


_MIXED = [False]        # building for mixed.py


def undefined():
    return uc.illegal(2) if _MIXED[0] else gm.stop("thumb illegal")


def svc(n):
    """SVC #n: draft 2's SWI #n beside its microcode, else a stop."""
    if not _MIXED[0]:
        return gm.stop("thumb svc")
    return chain(f"SVC #{n}", mi(ra=uc.VSWI[n >> 6], kv=4 * (n & 63), alu="add", w=TMP2),
                 Node(uc.SAVE_FLAGS, ("next", uc.trap_tail(TMP2, 0, "SWI")), f"SVC #{n}"))


def sext(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


def x(d=0, r=0, lo=0):
    return ((d & 15) << 12) | ((r & 15) << 8) | (lo & 0xFF)


def imm16(v):
    assert -0x8000 <= v < 0x10000, v
    return v & 0xFFFF


# --------------------------------------------------------------------------
# The decode table's view of a first parcel: (key, length, xir, ximm)

def decode(i):
    top5 = i >> 11
    if top5 <= 2:
        op, n, m, d = top5, (i >> 6) & 31, (i >> 3) & 7, i & 7
        return ("shi", op, n), 1, x(d, m), 0
    if top5 == 3:
        sub, immf, mm, n, d = (i >> 9) & 1, (i >> 10) & 1, (i >> 6) & 7, (i >> 3) & 7, i & 7
        return ("as", sub, immf, 0 if immf else mm), 1, x(d, n), mm if immf else 0
    if i >> 13 == 1:
        op, d = (i >> 11) & 3, (i >> 8) & 7
        return ("i8", op), 1, x(d, d), i & 0xFF
    if i >> 10 == 0x10:
        op, m, d = (i >> 6) & 15, (i >> 3) & 7, i & 7
        return ("alu", op), 1, x(d, m), 0
    if i >> 10 == 0x11:
        op, m, d = (i >> 8) & 3, (i >> 3) & 15, (i & 7) | ((i >> 4) & 8)
        return ("hi", op, d == 15, m == 15, (i >> 7) & 1 if op == 3 else 0), 1, x(d, m), 0
    if top5 == 9:
        return ("ldrlit",), 1, x((i >> 8) & 7), 4 * (i & 0xFF) + 2
    if i >> 12 == 5:
        op, m, n, t = (i >> 9) & 7, (i >> 6) & 7, (i >> 3) & 7, i & 7
        return ("rofs", op, m), 1, x(t, n), 0
    if i >> 13 == 3 or i >> 12 == 8:
        size = 2 if i >> 12 == 8 else (1 if (i >> 12) & 1 else 4)
        load, imm, n, t = (i >> 11) & 1, ((i >> 6) & 31) * size, (i >> 3) & 7, i & 7
        return ("iofs", size, load, imm == 0), 1, x(t, n), imm
    if i >> 12 == 9:
        load, t, imm = (i >> 11) & 1, (i >> 8) & 7, (i & 0xFF) * 4
        return ("iofs", 4, load, imm == 0), 1, x(t, SP), imm
    if i >> 12 == 10:
        d, imm = (i >> 8) & 7, (i & 0xFF) * 4
        if (i >> 11) & 1:
            return ("addsp",), 1, x(d, SP), imm
        return ("adr",), 1, x(d), imm + 2
    if i >> 8 == 0xB0:
        imm = (i & 0x7F) * 4
        return ("addsp",), 1, x(SP, SP), imm16(-imm if i & 0x80 else imm)
    if i >> 8 == 0xB2:
        return ("ext", (i >> 6) & 3), 1, x(i & 7, (i >> 3) & 7), 0
    if i >> 9 == 0x5A:
        return ("push", i & 0xFF, (i >> 8) & 1), 1, 0, 0
    if i >> 9 == 0x5E:
        return ("pop", i & 0xFF, (i >> 8) & 1), 1, 0, 0
    if i >> 8 == 0xBA and (i >> 6) & 3 != 2:
        return ("rev", (i >> 6) & 3), 1, x(i & 7, (i >> 3) & 7), 0
    if i >> 8 == 0xBE:
        return ("bkpt",), 1, 0, 0
    if i >> 8 == 0xBF or i & 0xFFEF == 0xB662:
        return ("nop",), 1, 0, 0
    if i >> 12 == 12:
        load, n, lst = (i >> 11) & 1, (i >> 8) & 7, i & 0xFF
        if load:
            return ("ldm", lst, not (lst >> n) & 1), 1, x(0, n), 0
        return ("stm", lst), 1, x(0, n), 0
    if i >> 12 == 13:
        cc = (i >> 8) & 15
        if cc == 15:
            return ("svc", i & 0xFF), 1, 0, 0
        if cc == 14:
            return ("illegal",), 1, 0, 0
        return ("bcc",), 1, x(lo=cc), imm16(2 * sext(i, 8) + 2)
    if top5 == 0x1C:
        return ("b",), 1, 0, imm16(2 * sext(i, 11) + 2)
    if top5 == 0x1E:
        return ("bl",), 2, 0, imm16(sext(i & 0x7FF, 11) << 4)
    return ("illegal",), 1, 0, 0


# --------------------------------------------------------------------------
# Routines

def shift_imm(op, n):
    name = ["LSLS", "LSRS", "ASRS"][op] + f" #{n}"
    if op == 0 and n == 0:
        return end(name, ra="r", alu="passa", w="d", **NZ)
    if n == 0 and op == 1:                       # LSR #32: 0, C = bit 31
        return end(name, ra="r", alu="passa", rz=0b1111, fc="f31", w="d", **NZ)
    if n == 0:                                   # ASR #32: the sign, C = bit 31
        return end(name, ra="r", b="fillall", fill="a31", alu="passb", fc="f31", w="d", **NZ)
    from heron.studies.v1b_hw import ucode as v1b_uc
    steps = [dict(s) for s in v1b_uc.cached_plan(op, n)]
    assert steps[0].get("RFA") == 0
    steps[0]["RFA"] = 1                          # the plan reads rd; Thumb's source is Rm
    body = [merge(s, mi(ldr=1)) for s in steps[:-1]]
    return chain(name, *body, end(name, _fields=merge(steps[-1], mi(w="d", **NZ))))


def addsub(sub, immf, rm):
    name = ("SUBS" if sub else "ADDS") + (" #imm3" if immf else f" r{rm}")
    b = IMM if immf else mi(rb=rm)
    return end(name, _fields=merge(mi(ra="r", alu="sub" if sub else "add", w="d", **NZCV), b))


def imm8(op):
    name = ["MOVS", "CMP", "ADDS", "SUBS"][op] + " #imm8"
    if op == 0:
        return end(name, _fields=merge(IMM, mi(alu="passb", w="d", **NZ)))
    f = mi(ra="d", alu="add" if op == 2 else "sub", **NZCV)
    if op != 1:
        f = merge(f, mi(w="d"))
    return end(name, _fields=merge(f, IMM))


def reg_shift(name, kind):
    """By Rm's low byte (ARM: 0 leaves C; 32 and more shift everything out)."""
    nz_only = end(name, ra="d", alu="passa", **NZ)
    out = end(name, a="r", alu="passa", w="d", **NZ)
    if kind == 0:
        step = mi(a="r", alu="dbl", cin="0", fc="aluc", ldr=1, lcinc=1)
    else:
        step = mi(a="r", alu="passa", rms="shr", sin={1: "0", 2: "f31", 3: "f0"}[kind],
                  fc="f0", ldr=1, lcinc=1)
    body = loop(name, step, "tc", out)
    run = chain(name, mi(a="r", kv=255, alu="xor", ldlc=1),                  # LC <- 255 - n
                branch(name, mi(ra="d", alu="passa", ldr=1, lcinc=1), "tc", body, out))
    if kind in (0, 1):                     # n >= 33: 0 and C = 0
        big = end(name, alu="zero", w="d", czero=1, **NZ)
        test = mi(a="r", kv=33, alu="sub", ldcl="aluc")
    elif kind == 2:                        # n >= 32: the sign, C = it
        big = end(name, ra="d", b="fillall", fill="a31", alu="passb", fc="f31", w="d", **NZ)
        test = mi(a="r", kv=32, alu="sub", ldcl="aluc")
    else:                                  # ROR: n & 31 == 0: unchanged, C = bit 31
        big = end(name, ra="d", alu="passa", fc="f31", w="d", **NZ)
        test = mi(a="r", kv=31, alu="and", ldr=1, ldcl="zero")
    return chain(name, mi(ra="r", kv=255, alu="and", ldr=1, ldcl="zero"),
                 branch(name, test, "cl", branch(name, {}, "cl", run, big), nz_only))


def alu(op):
    name = ["ANDS", "EORS", "LSLS", "LSRS", "ASRS", "ADCS", "SBCS", "RORS", "TST", "RSBS",
            "CMP", "CMN", "ORRS", "MULS", "BICS", "MVNS"][op]
    dr = mi(ra="d", rb="r")
    simple = {0: ("and", NZ, True), 1: ("xor", NZ, True), 5: ("adc", NZCV, True),
              6: ("sbc", NZCV, True), 8: ("and", NZ, False), 10: ("sub", NZCV, False),
              11: ("add", NZCV, False), 12: ("or", NZ, True), 14: ("bic", NZ, True)}
    if op in simple:
        a, fl, wr = simple[op]
        f = merge(dr, mi(alu=a, **fl))
        return end(name, _fields=merge(f, mi(w="d")) if wr else f)
    if op == 9:
        return end(name, ra=ZERO, rb="r", alu="sub", w="d", **NZCV)
    if op == 15:
        return end(name, ra="r", alu="nota", w="d", **NZ)
    if op in (2, 3, 4, 7):
        return reg_shift(name, {2: 0, 3: 1, 4: 2, 7: 3}[op])
    # MULS: the low word of a 32-step unsigned multiply; N, Z
    step = mi(a="r", rb="d", md="mulu", rms="shr", ldr=1, lcinc=1)
    return chain(name, mi(rb="r", md="mqload", alu="zero", ldr=1),
                 mi(kv=-32, alu="passb", ldlc=1),
                 loop(name, step, "tc", end(name, b="mq", alu="passb", w="d", **NZ)))


def hi(op, d15, m15, link):
    name = ["ADD", "CMP", "MOV", "BX"][op] + (" PC" if d15 else "") + (", PC" if m15 else "")
    if op == 3:
        if not link:
            return end("BX", ra="r", alu="passa", ldpc=1)
        return chain("BLX", mi(ra="r", alu="passa", ldr=1),
                     mi(a="pc", pck=1, alu="passa", w=LR),
                     end("BLX", a="r", alu="passa", ldpc=1))
    if m15:
        # PC as the operand reads as the instruction + 4: the native PC + 2
        val = mi(a="pc", pck=1, alu="a", cin="1") if op == 2 else \
            mi(a="pc", pck=1, rb="d", alu="addc", cin="1")
        if op == 1:
            return undefined()
    elif op == 0 and d15:
        val = mi(a="pc", pck=1, rb="r", alu="addc", cin="1")       # ADD PC, Rm
    elif op == 0:
        val = mi(ra="d", rb="r", alu="add")
    elif op == 2:
        val = mi(ra="r", alu="passa")
    else:
        return end(name, ra="d", rb="r", alu="sub", **NZCV)
    return end(name, _fields=merge(val, mi(ldpc=1) if d15 else mi(w="d")))


def ldrlit():
    return chain("LDR lit", merge(mi(a="pc", alu="add", ldr=1), IMM),
                 mi(a="r", kv=-4, alu="and", ldmar=1),
                 end("LDR lit", mem="read", size="word", b="t", alu="passb", w="d"))


SIZES = {1: "byte", 2: "half", 4: "word"}
LANE = {1: "tbyte", 2: "thalf", 4: "t"}


def access(name, size, load, signed=False):
    """The access at MAR: a load into rd, or a store of rd."""
    if not load:
        return end(name, ra="d", mem="write", size=SIZES[size])
    if not signed:
        return end(name, mem="read", size=SIZES[size], b=LANE[size], alu="passb", w="d")
    if size == 1:
        # (x ^ 0x80) - 0x80, the constant from KONST
        return chain(name, mi(mem="read", size="byte", b="tbyte", alu="passb", ldr=1),
                     mi(a="r", kv=0x80, alu="xor", ldr=1),
                     end(name, a="r", kv=0x80, alu="sub", w="d"))
    return chain(name, mi(mem="read", size="half", b="thalf", ra=K8000, alu="xor", rz=0b1100,
                          ldr=1),
                 end(name, a="r", rb=K8000, alu="sub", w="d"))


def rofs(op, rm):
    name = ["STR", "STRH", "STRB", "LDRSB", "LDR", "LDRH", "LDRB", "LDRSH"][op] + f" [Rn, r{rm}]"
    size = [4, 2, 1, 1, 4, 2, 1, 2][op]
    load, signed = op >= 3, op in (3, 7)
    return chain(name, mi(ra="r", rb=rm, alu="add", ldmar=1), access(name, size, load, signed))


def iofs(size, load, zero):
    name = ("LDR" if load else "STR") + {1: "B", 2: "H", 4: ""}[size] + " [Rn, #imm]"
    if zero and load:
        # the address straight from the register on the A bus: one cycle
        return end(name, mem="reada", size=SIZES[size], ra="r", b=LANE[size], alu="passb", w="d")
    addr = mi(ra="r", alu="passa", ldmar=1) if zero else merge(mi(ra="r", alu="add", ldmar=1),
                                                                IMM)
    return chain(name, addr, access(name, size, load))


def ext(op):
    name = ["SXTH", "SXTB", "UXTH", "UXTB"][op]
    if op == 3:
        return end(name, ra="r", alu="passa", rz=0b1110, w="d")
    if op == 2:
        return end(name, ra="r", alu="passa", rz=0b1100, w="d")
    if op == 1:
        return chain(name, mi(ra="r", kv=0x80, alu="xor", rz=0b1110, ldr=1),
                     end(name, a="r", kv=0x80, alu="sub", w="d"))
    return chain(name, mi(ra="r", rb=K8000, alu="xor", rz=0b1100, ldr=1),
                 end(name, a="r", rb=K8000, alu="sub", w="d"))


def rev(op):
    if op == 0:                                  # REV: (ror8(x) & 0xFF00FF00) | (rol8(x) & 0x00FF00FF)
        return chain("REV", mi(ra="r", alu="passa", rms="ror8", rz=0b0101, w=TMP2),
                     mi(ra="r", alu="passa", rms="ror16", ldr=1),
                     mi(a="r", alu="passa", rms="ror8", rz=0b1010, ldr=1),
                     end("REV", a="r", rb=TMP2, alu="or", w="d"))
    # REV16: (x >> 8) & 0x00FF00FF | (x & 0x00FF00FF) << 8; REVSH then sign-extends
    steps = [mi(ra="r", alu="passa", rms="ror8", rz=0b1010, w=TMP2),
             mi(ra="r", alu="passa", rms="ror16", ldr=1),
             mi(a="r", alu="passa", rms="ror8", rz=0b0101, ldr=1)]
    if op == 1:
        return chain("REV16", *steps, end("REV16", a="r", rb=TMP2, alu="or", w="d"))
    return chain("REVSH", *steps, mi(a="r", rb=TMP2, alu="or", ldr=1),
                 mi(a="r", rb=K8000, alu="xor", rz=0b1100, ldr=1),
                 end("REVSH", a="r", rb=K8000, alu="sub", w="d"))


def regs_of(lst):
    return [k for k in range(8) if lst >> k & 1]


def push(lst, m):
    regs = regs_of(lst) + ([LR] if m else [])
    name = "PUSH"
    if not regs:
        return undefined()
    # SP is written after the stores, so that a fault in one restarts PUSH
    stores = [mi(ra=k, mem="write", size="word", marinc=1) for k in regs]
    return chain(name, mi(ra=SP, kv=4 * len(regs), alu="sub", ldmar=1), *stores,
                 end(name, a="mar", kv=4 * len(regs), alu="sub", w=SP))


def pop(lst, p):
    regs = regs_of(lst)
    name = "POP"
    if not regs and not p:
        return undefined()
    loads = [mi(mem="read", size="word", b="t", alu="passb", w=k, marinc=1) for k in regs]
    if p:
        return chain(name, mi(ra=SP, alu="passa", ldmar=1), *loads,
                     mi(a="mar", kv=4, alu="add", w=SP),
                     end(name, mem="read", size="word", b="t", alu="passb", ldpc=1))
    return chain(name, mi(ra=SP, alu="passa", ldmar=1), *loads,
                 end(name, a="mar", alu="passa", w=SP))


def stm(lst):
    regs = regs_of(lst)
    if not regs:
        return undefined()
    stores = [mi(ra=k, mem="write", size="word", marinc=1) for k in regs]
    return chain("STM", mi(ra="r", alu="passa", ldmar=1), *stores,
                 end("STM", a="mar", alu="passa", w="r"))


def ldm(lst, wb):
    regs = regs_of(lst)
    if not regs:
        return undefined()
    loads = [mi(mem="read", size="word", b="t", alu="passb", w=k, marinc=1) for k in regs]
    last = end("LDM", a="mar", alu="passa", w="r") if wb else end("LDM")
    return chain("LDM", mi(ra="r", alu="passa", ldmar=1), *loads, last)


def bl():
    """IMM = sext(S:imm10) << 4: rotated into place, << 12; the second
    parcel's imm11 << 1; LR <- the next instruction | 1; jump."""
    return chain("BL", merge(IMM, mi(alu="passb", rms="ror8", ldr=1)),
                 mi(a="r", alu="passa", rms="ror16", rz=0b0001, ldr=1),
                 mi(ra=K0FFE, b="qh2", fill="0", alu="and", w=TMP1, consume=1),
                 mi(a="r", rb=TMP1, alu="add", ldr=1),
                 mi(a="pc", pck=1, alu="passa", w=LR),
                 end("BL", a="pc", b="r", alu="add", ldpc=1))


class Thumb:
    name = "thumb"
    needs = ("D1",)
    consts = CONSTS                 # what mixed.py's reset writes

    def __init__(self, mixed=False):
        self.mixed = mixed

    def reset(self):
        steps = [mi(alu="zero", ldr=1, w=ZERO), mi(a="r", loadf="nzcv", sset=1)]
        for loc, v in sorted(CONSTS.items()):
            steps += _const(loc, v)
        steps += [mi(alu="zero", w=k) for k in range(15)]
        return chain("reset", *steps, end("reset", alu="zero", ldpc=1))

    def fixed(self):
        return gm.default_fixed(self.name)

    def preload(self):
        return []

    def classify(self, w):
        k, ln, _, _ = decode(w)
        return k, ln

    def xlat(self, w):
        _, _, xir, ximm = decode(w)
        return xir, ximm

    def routine(self, key):
        _MIXED[0] = self.mixed
        k = key[0]
        table = {"shi": shift_imm, "as": addsub, "i8": imm8, "alu": alu, "hi": hi,
                 "rofs": rofs, "iofs": iofs, "ext": ext, "rev": rev, "push": push, "pop": pop,
                 "stm": stm, "ldm": ldm}
        if k in table:
            return table[k](*key[1:])
        if k == "ldrlit":
            return ldrlit()
        if k == "addsp":
            return end("ADD SP", _fields=merge(mi(ra="r", alu="add", w="d"), IMM))
        if k == "adr":
            return chain("ADR", merge(mi(a="pc", alu="add", ldr=1), IMM),
                         end("ADR", a="r", kv=-4, alu="and", w="d"))
        if k == "bcc":
            return end("B<cond>", _fields=merge(mi(a="pc", alu="add", ldpc=1, pccond="bcond",
                                                   ccb="bcc"), IMM))
        if k == "b":
            return end("B", _fields=merge(mi(a="pc", alu="add", ldpc=1), IMM))
        if k == "bl":
            return bl()
        if k == "nop":
            return end("NOP")
        if k == "bkpt":
            return undefined() if _MIXED[0] else gm.stop("thumb halt")
        if k == "svc":
            return svc(key[1])
        return undefined()

    def state(self, m):
        return {"r": [m.rf[k] for k in range(15)], "pc": (m.PC - 2) & M32,
                "nzcv": m.flags_word() & 15}


def _const(loc, val):
    """Steps writing a 32-bit constant into a location."""
    sv = val - (1 << 32) if val & 0x80000000 else val
    if -256 <= sv <= 255:
        return [mi(kv=sv, alu="passb", w=loc)]
    b = [(val >> (8 * i)) & 0xFF for i in range(4)]
    top = max(i for i in range(4) if b[i])
    out = [mi(b="simm", v8="k", k=b[top], fill="0", alu="passb", ldr=1)]
    for i in range(top - 1, -1, -1):
        out += [mi(a="r", alu="passa", rms="ror8", ldr=1)] * 3
        out.append(merge(mi(a="r", alu="or", ldr=1), mi(b="simm", v8="k", k=b[i], fill="0")))
    last = {k: v for k, v in out.pop().items() if k != "LDR"}
    out.append(merge(last, mi(w=loc)))
    return out


_built = {}


def built():
    if "mc" not in _built:
        _built["mc"] = gm.GuestMicrocode(Thumb())
    return _built["mc"]
