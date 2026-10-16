"""The NMOS 6502 on the draft 2 CPU, unmodified: microcode only.

The 6502's instructions are 1 to 3 bytes at any address; draft 2 fetches
and decodes 16-bit parcels at even addresses. **Every guest byte is kept
twice**: the guest's 64 KB is 128 KB here, the halfword at native address
PB + 2a holding P[a] = guest[a] | guest[a + 1] << 8. So:

- The native PC is PB + 2 x the 6502's PC, and the native fetch, the
  prefetch queue and the decode table work as they are: the parcel at the
  PC is {the next byte, the opcode}, and consuming a parcel moves the 6502
  on by one byte. The decode table sees the opcode and its first operand
  byte (whose top bit picks the base for a zero-page address, see below).
- After the decode the head parcel QH is {second operand byte, first}: an
  instruction's 16-bit operand, already put together, and its first
  operand byte is IR[15:8], which the immediate unit gives doubled and
  sign-extended (the branch offset field) -- a branch offset, or a
  zero-page address x 2.
- A 16-bit read at any address (pointers in the zero page, JMP (ind), the
  return address) is one aligned halfword read.
- A store writes two bytes: P[a]'s low byte and P[a - 1]'s high byte.

The page map makes the address arithmetic free: the 128 KB are mapped at
PB, and the upper half (0x8000-0xFFFF) again below PB, so that PB + 2a
works for a 16-bit operand as the immediate unit gives it, doubled and
sign-extended (-0x8000 to 0x7FFF), and for the sums of an index register
and an operand up to 0x100FF; code runs on from 0xFFFF to 0, and a store
to 0 reaches P[0xFFFF].

A, X, Y and S are bank 0's locations 0-3; N, Z and C are the CPU's own
flags (8-bit N from bit 7, Z from the result masked to a byte, C from bit
8 or the ALU's carry, whose sense for SBC and CMP is the 6502's); V comes
from ADC and SBC done in the top byte, where the ALU's own overflow is the
6502's. D is kept in MQ[0], which a microbranch tests, and as 8 in PD; I
as 4 in PI. Tables in the register file (bank i, location L, as for RV32)
turn the flags into P and back.

The opcode 0x02, one of the NMOS 6502's JAM opcodes, halts. RESET jumps
through 0xFFFC. Pushes of two bytes (JSR, BRK) and pulls (RTS, RTI) don't
wrap around the stack page; pushes and pulls of one byte do. A zero-page
pointer at 0xFF takes its high byte from 0x100, as abs does. Decimal mode
ADC and SBC give BCD results and C for valid BCD operands, N, Z and V from
the binary operation.
"""

from heron.studies.v2_hw import ucode as uc
from heron.studies.v2_hw.ucode import mi, merge, chain, branch, end, Node

from . import guest as gm
from .m6502_ref import OPS, LENGTH

M32 = 0xFFFFFFFF
G = uc.G
PB = 0x20000                 # the native address of P[0]
P_PHYS = 0x40000             # where P is in the CPU card's RAM
IO_PAGE = 0x7FFFF000         # draft 1's I/O page (slot 15, through the window's physical)
TABLE_PA = 0x100000

A, X, Y, S, PI, PD = 0, 1, 2, 3, 4, 5
REG = {"A": A, "X": X, "Y": Y}
TMP1, TMP2, TMP3 = G, G + 1, G + 2
_consts = ["PB", "PB512", "PBm1", "PB512m1", "PBm2", "PBp2", "SB", "SBm1", "SBm3", "KN",
           "KZ", "KC", "KV", "KFF00", "K0F", "KF0", "K6", "K1", "KFF", "K60", "ZERO"]
K = {n: G + 3 + i for i, n in enumerate(_consts)}
CONSTS = {K["PB"]: PB, K["PB512"]: PB + 512, K["PBm1"]: PB - 1, K["PB512m1"]: PB + 511,
          K["PBm2"]: PB - 2, K["PBp2"]: PB + 2, K["SB"]: PB + 0x200, K["SBm1"]: PB + 0x1FF,
          K["SBm3"]: PB + 0x1FD, K["KN"]: 8, K["KZ"]: 4, K["KC"]: 2, K["KV"]: 1,
          K["KFF00"]: 0xFFFFFF00, K["K0F"]: 0x0F, K["KF0"]: 0xF0, K["K6"]: 6, K["K1"]: 1,
          K["KFF"]: 0xFF, K["K60"]: 0x60, K["ZERO"]: 0}
assert max(CONSTS) < 64

# tables: location L of bank i
L_P, L_PL, L_BITNV, L_D = 16, 17, 18, 19
TABLES = {
    # the CPU's NZCV (flags word bits 3-0) -> the 6502's P bits N, V, Z, C
    L_P: lambda i: ((i >> 3) << 7) | ((i & 1) << 6) | (((i >> 2) & 1) << 1) | ((i >> 1) & 1),
    # the 6502's P -> the CPU's flags word (NZCV)
    L_PL: lambda i: ((i >> 7) << 3) | (((i >> 1) & 1) << 2) | ((i & 1) << 1) | ((i >> 6) & 1),
    # a byte -> N and V as BIT sets them, in the flags word
    L_BITNV: lambda i: ((i >> 7) << 3) | ((i >> 6) & 1),
    L_D: lambda i: (i >> 3) & 1,                       # P -> D
}


def table_image():
    words = []
    for i in range(256):
        for L in sorted(TABLES):
            words.append(TABLES[L](i) & M32)
    words += [CONSTS[k] for k in sorted(CONSTS)]
    return b"".join(w.to_bytes(4, "little") for w in words)


def doubled(image):
    """The guest's 64 KB as P: P[a] = guest[a] | guest[a + 1] << 8."""
    g = bytearray(65536)
    g[:len(image)] = image
    out = bytearray(0x20000)
    for a in range(65536):
        out[2 * a] = g[a]
        out[2 * a + 1] = g[(a + 1) & 0xFFFF]
    return bytes(out)


# --------------------------------------------------------------------------
# Steps

def zp_base(ir15, minus1=False):
    """The constant to add to IR[15:8] x 2 (sign-extended) for a zero-page
    address: PB, or PB + 512 when the address's top bit is set."""
    if minus1:
        return K["PB512m1"] if ir15 else K["PBm1"]
    return K["PB512"] if ir15 else K["PB"]


def addr(mode, ir15, reg=None, minus1=False):
    """Steps leaving MAR = the native address of the operand (and, with
    minus1, R = MAR - 1, for a store's second byte), consuming the operand
    parcels. reg: the index register for zpx/abx etc."""
    xr = REG.get(reg)
    if mode == "zp":
        if minus1:
            return [mi(ra=zp_base(ir15, True), imm="bcc", alu="add", ldr=1, consume=1),
                    mi(a="r", alu="inc", ldmar=1)]
        return [mi(ra=zp_base(ir15), imm="bcc", alu="add", ldmar=1, consume=1)]
    if mode in ("zpx", "zpy"):
        first = mi(ra=xr, b="qh", fill="0", alu="add", rz=0b1110, ldr=1, consume=1)
        if minus1:
            return [first, mi(a="r2", sina="0", rb=K["PBm1"], alu="add", ldr=1),
                    mi(a="r", alu="inc", ldmar=1)]
        return [first, mi(a="r2", sina="0", rb=K["PB"], alu="add", ldmar=1)]
    if mode == "abs":
        if minus1:
            return [mi(ra=K["PBm1"], b="qh2", fill="qh15", alu="add", ldr=1, consume=1),
                    mi(a="r", alu="inc", ldmar=1, consume=1)]
        return [mi(ra=K["PB"], b="qh2", fill="qh15", alu="add", ldmar=1, consume=1),
                mi(consume=1)]
    if mode in ("abx", "aby"):
        first = mi(ra=xr, b="qh", fill="0", alu="add", ldr=1, consume=1)
        if minus1:
            return [first, mi(a="r2", sina="0", rb=K["PBm1"], alu="add", ldr=1, consume=1),
                    mi(a="r", alu="inc", ldmar=1)]
        return [first, mi(a="r2", sina="0", rb=K["PB"], alu="add", ldmar=1, consume=1)]
    if mode == "izx":
        steps = [mi(ra=X, b="qh", fill="0", alu="add", rz=0b1110, ldr=1, consume=1),
                 mi(a="r2", sina="0", rb=K["PB"], alu="add", ldmar=1),
                 mi(mem="read", size="half", b="thalf", alu="passb", ldr=1)]
    elif mode == "izy":
        steps = [mi(ra=zp_base(ir15), imm="bcc", alu="add", ldmar=1, consume=1),
                 mi(mem="read", size="half", b="thalf", ra=Y, alu="add", ldr=1)]
    else:
        raise ValueError(mode)
    if minus1:
        return steps + [mi(a="r2", sina="0", rb=K["PBm1"], alu="add", ldr=1),
                        mi(a="r", alu="inc", ldmar=1)]
    return steps + [mi(a="r2", sina="0", rb=K["PB"], alu="add", ldmar=1)]


def read_byte(**kw):
    """The cycle that reads the operand byte (T, transparent, on B)."""
    return mi(mem="read", size="byte", b="tbyte", **kw)


NZ = dict(fnz="nz", nsel=7)


def store2(name, src):
    """Store the byte on the A bus (fields src) at MAR and MAR - 1 (in R)."""
    return chain(name, merge(src, mi(mem="write", size="byte", b="r", alu="passb", ldmar=1)),
                 end(name, _fields=merge(src, mi(mem="write", size="byte"))))


# --------------------------------------------------------------------------
# Instructions

def op_load(name, reg, mode, ir15):
    dst = REG[name[2]]
    if mode == "imm":
        return chain(name, mi(b="qh", fill="0", alu="passb", rz=0b1110, w=dst, consume=1, **NZ),
                     end(name))
    return chain(name, *addr(mode, ir15, reg),
                 end(name, _fields=read_byte(alu="passb", w=dst, **NZ)))


def op_store(name, reg, mode, ir15):
    src = REG[name[2]]
    return chain(name, *addr(mode, ir15, reg, minus1=True), store2(name, mi(ra=src)))


LOGIC = {"AND": "and", "ORA": "or", "EOR": "xor"}


def operand_then(name, mode, ir15, reg, fields_mem, fields_imm):
    """An operation on the operand byte: from memory, the read cycle does it
    (fields_mem, B = the byte); immediate, R <- the byte first."""
    if mode == "imm":
        return chain(name, mi(b="qh", fill="0", alu="passb", rz=0b1110, ldr=1, consume=1),
                     end(name, _fields=fields_imm))
    return chain(name, *addr(mode, ir15, reg), end(name, _fields=merge(read_byte(), fields_mem)))


def op_logic(name, reg, mode, ir15):
    alu = LOGIC[name]
    return operand_then(name, mode, ir15, reg,
                        mi(ra=A, alu=alu, w=A, **NZ), mi(ra=A, b="r", alu=alu, w=A, **NZ))


def op_cmp(name, reg, mode, ir15):
    r = {"CMP": A, "CPX": X, "CPY": Y}[name]
    f = dict(alu="sub", rz=0b1110, fc="aluc", **NZ)
    return operand_then(name, mode, ir15, reg, mi(ra=r, **f), mi(ra=r, b="r", **f))


def op_adc_sbc(name, reg, mode, ir15):
    """Binary, in the top byte: R <- M << 24 (ADC: with the 24 bits below
    set, so that the carry in reaches bit 24); TMP1 <- A << 24; then the
    ALU's carry, overflow, N and Z are the 6502's; back to the low byte.
    The step that makes TMP1 branches on D (MQ[0]) to the decimal path."""
    adc = name == "ADC"
    if adc:
        prep_mem = mi(ra=K["KFF00"], alu="or", rms="ror8", ldr=1)
        head = ([mi(ra=K["KFF00"], b="qh", fill="0", alu="or", rms="ror8", ldr=1, consume=1)]
                if mode == "imm" else addr(mode, ir15, reg) + [merge(read_byte(), prep_mem)])
    else:
        # the immediate masked first: QH's high byte is the next opcode
        head = ([mi(b="qh", fill="0", alu="passb", rz=0b1110, ldr=1, consume=1),
                 mi(b="r", alu="passb", rms="ror8", ldr=1)]
                if mode == "imm" else
                addr(mode, ir15, reg) + [merge(read_byte(), mi(alu="passb", rms="ror8", ldr=1))])
    op = mi(ra=TMP1, b="r", alu="adc" if adc else "sbc", rz=0b0111, ldr=1, fnz="nz", fc="aluc",
            fv="ovf")
    binary = chain(name, op, mi(a="r", alu="passa", rms="ror8", ldr=1),        # A << 16
                   end(name, a="r", alu="passa", rms="ror16", w=A))
    # M again, for the decimal path: the byte in T, or the immediate, which
    # is IR[15:8] (the immediate unit's doubled offset, halved)
    if mode == "imm":
        m = mi(imm="bcc", alu="passb", rms="shr", sin="0", rz=0b1110, w=TMP2)
    else:
        m = mi(b="tbyte", alu="passb", w=TMP2)
    dec = chain(name + " decimal", m, (adc_decimal if adc else sbc_decimal)(name + " decimal"))
    return chain(name, *head,
                 branch(name, mi(ra=A, alu="passa", rms="ror8", w=TMP1), "mq0", binary, dec))


def adc_decimal(n):
    """TMP2 = M, TMP1 = A << 24, C = the carry in. BCD for valid operands:
    lo = A & 15 + M & 15 + C, + 6 if >= 10; r = A & F0 + M & F0 + lo, + 0x60
    if >= 0xA0; C = r > 0xFF. N, Z, V: the binary addition's."""
    # the result into TMP3; the binary flags (C still the carry in); then C
    # from the BCD result's bit 8, and A
    tail = chain(n, mi(a="r", alu="passa", w=TMP3),
                 mi(ra=TMP2, kv=-256, alu="or", rms="ror8", ldr=1),
                 mi(ra=TMP1, b="r", alu="adc", rz=0b0111, fnz="nz", fv="ovf"),
                 end(n, ra=TMP3, alu="passa", fc="f8", rz=0b1110, w=A))
    hi = chain(n, mi(ra=A, kv=0xF0, alu="and", w=TMP3),
               mi(a="r", rb=TMP3, alu="add", ldr=1),
               mi(ra=TMP2, kv=0xF0, alu="and", w=TMP3),
               mi(a="r", rb=TMP3, alu="add", ldr=1),
               mi(a="r", kv=0xA0, alu="sub", ldcl="aluc"),
               branch(n, {}, "cl", tail,
                      chain(n, mi(a="r", rb=K["K60"], alu="add", ldr=1), tail)))
    return chain(n, mi(ra=A, kv=15, alu="and", ldr=1),
                 mi(ra=TMP2, kv=15, alu="and", w=TMP3),
                 mi(a="r", rb=TMP3, alu="adc", ldr=1),
                 mi(a="r", kv=10, alu="sub", ldcl="aluc"),
                 branch(n, {}, "cl", hi, chain(n, mi(a="r", kv=6, alu="add", ldr=1), hi)))


def sbc_decimal(n):
    """TMP2 = M, TMP1 = A << 24, C = not borrow in. lo = A & 15 - M & 15 -
    !C, - 6 if negative; r = A & F0 - M & F0 + lo, - 0x60 if negative. N,
    Z, V and C: the binary subtraction's."""
    tail = chain(n, mi(a="r", alu="passa", w=TMP3),
                 mi(ra=TMP2, alu="passa", rms="ror8", ldr=1),
                 mi(ra=TMP1, b="r", alu="sbc", rz=0b0111, fnz="nz", fc="aluc", fv="ovf"),
                 end(n, ra=TMP3, alu="passa", rz=0b1110, w=A))
    hi = chain(n, mi(ra=A, kv=0xF0, alu="and", w=TMP3),
               mi(a="r", rb=TMP3, alu="add", ldr=1),
               mi(ra=TMP2, kv=0xF0, alu="and", w=TMP3),
               mi(a="r", rb=TMP3, alu="sub", ldr=1),
               branch(n, {}, "r31", tail,
                      chain(n, mi(a="r", rb=K["K60"], alu="sub", ldr=1), tail)))
    return chain(n, mi(ra=A, kv=15, alu="and", ldr=1),
                 mi(ra=TMP2, kv=15, alu="and", w=TMP3),
                 mi(a="r", rb=TMP3, alu="sbc", ldr=1),
                 branch(n, {}, "r31", hi, chain(n, mi(a="r", kv=6, alu="sub", ldr=1), hi)))


def op_bit(name, reg, mode, ir15):
    """Z from A & M (the CPU's Z, then read back with C), N and V from M
    through the table; then the flags word loaded."""
    return chain(name, *addr(mode, ir15, reg),
                 merge(read_byte(), mi(alu="passb", ldbank=1, ubr=1)),
                 mi(ra=L_BITNV, alu="passa", w=TMP2),
                 mi(ra=A, b="tbyte", alu="and", fnz="nz"),
                 mi(b="flags", ra=K["K6"], alu="and", ldr=1),
                 mi(a="r", rb=TMP2, alu="or", ldr=1),
                 end(name, a="r", loadf="nzcv"))


# shifts and rotates: f(T or A) -> result, C. On the low byte: ASL as x + x
# (C from bit 8), LSR as x >> 1 (C from bit 0), ROL as x + x + C; ROR in the
# top byte: (x << 24) >> 1 with C shifted in, C from x's bit 0.

def shift_steps(name, src, dst):
    """Steps computing name(src) into dst (src, dst: register locations),
    setting N, Z and C. src may be T (src None: the byte just read, its
    read cycle is the first step)."""
    if name in ("ASL", "ROL"):
        pre = [] if src is not None else [merge(read_byte(), mi(alu="passb", w=TMP1))]
        s = src if src is not None else TMP1
        return pre + [mi(ra=s, rb=s, alu="adc" if name == "ROL" else "add", rz=0b1110,
                         fc="f8", w=dst, **NZ)]
    if name == "LSR":
        if src is None:
            return [merge(read_byte(), mi(alu="passb", rms="shr", sin="0", fc="f0", w=dst,
                                          **NZ))]
        return [mi(ra=src, alu="passa", rms="shr", sin="0", fc="f0", w=dst, **NZ)]
    # ROR, in the top byte so that C can come in at bit 31: TMP3 <- x << 24;
    # TMP3 >> 1 with C in; C <- x's bit 0; back to the low byte. (R is kept:
    # a store's second address is in it.)
    if src is None:
        pre = [merge(read_byte(), mi(alu="passb", rms="ror8", rz=0b0111, w=TMP3))]
        c_from = mi(b="tbyte", alu="passb", fc="f0")
    else:
        pre = [mi(ra=src, alu="passa", rms="ror8", rz=0b0111, w=TMP3)]
        c_from = mi(ra=src, alu="passa", fc="f0")
    return pre + [mi(ra=TMP3, alu="passa", rms="shr", sin="c", rz=0b0111, w=TMP3, fnz="nz"),
                  c_from,
                  mi(ra=TMP3, alu="passa", rms="ror8", w=TMP3),
                  mi(ra=TMP3, alu="passa", rms="ror16", w=dst)]


def op_shift(name, reg, mode, ir15):
    if mode == "acc":
        steps = shift_steps(name, A, A)
        return chain(name, *steps[:-1], end(name, _fields=steps[-1]))
    steps = shift_steps(name, None, TMP2)
    return chain(name, *addr(mode, ir15, reg, minus1=True), *steps, store2(name, mi(ra=TMP2)))


def op_incdec(name, reg, mode, ir15):
    k = K["K1"] if name == "INC" else K["KFF"]
    return chain(name, *addr(mode, ir15, reg, minus1=True),
                 merge(read_byte(), mi(ra=k, alu="add", rz=0b1110, w=TMP2, **NZ)),
                 store2(name, mi(ra=TMP2)))


def op_reg1(name):
    """One-byte register instructions: one cycle, which also decodes."""
    f = {"INX": mi(ra=X, alu="inc", rz=0b1110, w=X, **NZ),
         "INY": mi(ra=Y, alu="inc", rz=0b1110, w=Y, **NZ),
         "DEX": mi(ra=X, alu="dec", rz=0b1110, w=X, **NZ),
         "DEY": mi(ra=Y, alu="dec", rz=0b1110, w=Y, **NZ),
         "TAX": mi(ra=A, alu="passa", w=X, **NZ), "TAY": mi(ra=A, alu="passa", w=Y, **NZ),
         "TXA": mi(ra=X, alu="passa", w=A, **NZ), "TYA": mi(ra=Y, alu="passa", w=A, **NZ),
         "TSX": mi(ra=S, alu="passa", w=X, **NZ), "TXS": mi(ra=X, alu="passa", w=S),
         "CLC": mi(czero=1), "SEC": mi(ra=K["KC"], fc="b1"),
         "CLV": mi(fv="0"), "NOP": mi(),
         "CLI": mi(alu="zero", w=PI), "SEI": mi(kv=4, alu="passb", w=PI),
         "SED": mi(kv=8, alu="passb", w=PD)}
    if name == "SED":
        return chain(name, mi(kv=1, alu="passb", md="mqload"), end(name, _fields=f[name]))
    if name == "CLD":
        return end(name, _fields=mi(kv=0, alu="passb", w=PD, md="mqload"))
    return end(name, _fields=f[name])


BRANCH = {"BPL": ("KN", 0), "BMI": ("KN", 1), "BVC": ("KV", 0), "BVS": ("KV", 1),
          "BCC": ("KC", 0), "BCS": ("KC", 1), "BNE": ("KZ", 0), "BEQ": ("KZ", 1)}


def op_branch(name):
    """CL <- the flag's test, so that the branch is taken iff not CL; the
    offset is IR[15:8], which the immediate unit doubles: the native PC
    moves by 2 a byte."""
    mask, taken_if = BRANCH[name]
    test = mi(ra=K[mask], b="flags", alu="and" if taken_if else "bic", ldcl="zero", consume=1)
    return chain(name, test, end(name, a="pc", imm="bcc", alu="add", ldpc=1, pccond="ncl"))


def op_jmp(name, mode):
    if mode == "abs":
        return end(name, ra=K["PB"], b="qh2", fill="qh15", alu="add", ldpc=1)
    return chain(name, mi(ra=K["PB"], b="qh2", fill="qh15", alu="add", ldmar=1),
                 mi(mem="read", size="half", b="thalf", alu="passb", ldr=1),
                 end(name, a="r2", sina="0", rb=K["PB"], alu="add", ldpc=1))


def push2(name, value_steps, then):
    """Push the 16-bit value in TMP1 (hi first): the halfword at the new
    S + 1, the byte below it, the byte above it; S <- S - 2. No wrap."""
    return chain(name, *value_steps,
                 mi(ra=S, rb=S, alu="add", ldr=1),                       # 2S
                 mi(a="r", rb=K["SBm3"], alu="add", ldr=1),              # y - 1
                 mi(a="r", alu="inc", ldmar=1),                          # y
                 mi(ra=TMP1, mem="write", size="half", b="r", alu="passb", ldmar=1),
                 mi(ra=TMP1, mem="write", size="byte", alu="passa", rms="ror8", w=TMP2),
                 mi(a="r", kv=3, alu="add", ldmar=1),                    # x = y + 2
                 mi(ra=TMP2, mem="write", size="byte"),
                 mi(ra=S, kv=2, alu="sub", rz=0b1110, w=S),
                 then)


def op_jsr(name):
    # the return address - 1 = the JSR's own address + 2 = (PC - PB + 2) / 2
    v = [mi(a="pc", rb=K["PBm2"], alu="sub", rms="shr", sin="0", rz=0b1100, w=TMP1)]
    return push2(name, v, end(name, ra=K["PB"], b="qh2", fill="qh15", alu="add", ldpc=1))


def pull_half(name, n=2):
    """R <- the halfword at S + 1 (the byte there and the one above it);
    S <- S + n. No wrap."""
    return [mi(ra=S, rb=S, alu="add", ldr=1),
            mi(a="r", rb=K["SB"], alu="add", ldr=1),
            mi(a="r", kv=2, alu="add", ldmar=1),
            mi(mem="read", size="half", b="thalf", alu="passb", ldr=1),
            mi(ra=S, kv=n, alu="add", rz=0b1110, w=S)]


def op_rts(name):
    # PC <- PB + 2 (v + 1)
    return chain(name, *pull_half(name),
                 end(name, a="r2", sina="0", rb=K["PBp2"], alu="add", ldpc=1))


def push1(name, src):
    """Push the byte on the A bus (src fields): at S, wrapping in page 1."""
    return [mi(ra=S, rb=S, alu="add", ldr=1),
            mi(a="r", rb=K["SBm1"], alu="add", ldr=1),
            mi(a="r", alu="inc", ldmar=1),
            merge(src, mi(mem="write", size="byte", b="r", alu="passb", ldmar=1)),
            merge(src, mi(mem="write", size="byte"))]


def op_pha(name):
    return chain(name, *push1(name, mi(ra=A)), end(name, ra=S, alu="dec", rz=0b1110, w=S))


def p_value(dst, b=1):
    """dst <- P as the 6502 pushes it: the table's N V Z C, then 0x30 (B and
    the unused bit), D (PD) and I (PI)."""
    return [mi(b="flags", ra=K["K0F"], alu="and", ldbank=1, ubr=1),
            mi(ra=L_P, kv=0x30 if b else 0x20, alu="or", ldr=1),
            mi(a="r", rb=PD, alu="or", ldr=1),
            mi(a="r", rb=PI, alu="or", w=dst)]


def op_php(name):
    return chain(name, *p_value(TMP1), *push1(name, mi(ra=TMP1)),
                 end(name, ra=S, alu="dec", rz=0b1110, w=S))


def pull1(name):
    """S <- S + 1; MAR <- its native address (the read is the caller's)."""
    return [mi(ra=S, alu="inc", rz=0b1110, w=S, ldr=1),
            mi(a="r2", sina="0", rb=K["SB"], alu="add", ldmar=1)]


def op_pla(name):
    return chain(name, *pull1(name), end(name, _fields=read_byte(alu="passb", w=A, **NZ)))


def set_p(name, then):
    """P from the byte in TMP1: the flags through the table, D (MQ[0] and
    PD), I (PI)."""
    return chain(name,
                 mi(ra=TMP1, alu="passa", ldbank=1, ubr=1),
                 mi(ra=L_PL, alu="passa", ldr=1, ubr=1),
                 mi(a="r", loadf="nzcv", ubr=1),
                 mi(rb=L_D, alu="passb", md="mqload"),
                 mi(ra=TMP1, kv=8, alu="and", w=PD),
                 mi(ra=TMP1, kv=4, alu="and", w=PI),
                 then)


def op_plp(name):
    return chain(name, *pull1(name), merge(read_byte(), mi(alu="passb", w=TMP1)),
                 set_p(name, end(name)))


def op_rti(name):
    # P, then the return address (the instruction to return to)
    return chain(name, *pull1(name), merge(read_byte(), mi(alu="passb", w=TMP1)),
                 set_p(name, chain(name, *pull_half(name),
                                   end(name, a="r2", sina="0", rb=K["PB"], alu="add",
                                       ldpc=1))))


def op_brk(name):
    """Push the BRK's address + 2, then P with B set; I <- 1; PC <- (FFFE)."""
    v = [mi(a="pc", rb=K["PBm2"], alu="sub", rms="shr", sin="0", rz=0b1100, w=TMP1)]
    tail = chain(name, *p_value(TMP1), *push1(name, mi(ra=TMP1)),
                 mi(ra=S, alu="dec", rz=0b1110, w=S),
                 mi(kv=4, alu="passb", w=PI),
                 mi(kv=-2, alu="passb", rz=0b1100, ldr=1),               # 0xFFFE
                 mi(a="r2", sina="0", rb=K["PB"], alu="add", ldmar=1),
                 mi(mem="read", size="half", b="thalf", alu="passb", ldr=1),
                 end(name, a="r2", sina="0", rb=K["PB"], alu="add", ldpc=1))
    return push2(name, v, tail)


def op_jam(name):
    return gm.stop("m6502 halt")


# --------------------------------------------------------------------------

class M6502:
    name = "m6502"

    def reset(self):
        start = [mi(alu="zero", ldr=1), mi(a="r", loadf="nzcv", sset=1),
                 mi(kv=0x10, alu="passb", rms="ror16", ldr=1),
                 mi(kv=1, alu="passb", rms="shr", sin="f0", w=TMP1),
                 mi(a="r", rb=TMP1, alu="or", ldmar=1),
                 mi(alu="zero", ldlc=1)]
        copy = [mi(mem="read", size="word", marinc=1, b="t", alu="passb", w=L, ubw=1)
                for L in sorted(TABLES)]
        consts = [mi(mem="read", size="word", marinc=1, b="t", alu="passb", w=k)
                  for k in sorted(CONSTS)]
        regs = [mi(alu="zero", w=r) for r in (A, X, Y, PD)]
        regs += [mi(kv=0xFD, alu="passb", w=S), mi(kv=4, alu="passb", w=PI),
                 mi(kv=0, alu="passb", md="mqload")]
        # PC <- PB + 2 x the halfword at 0xFFFC
        vec = [mi(kv=-4, alu="passb", rz=0b1100, ldr=1),               # 0xFFFC
               mi(a="r2", sina="0", rb=K["PB"], alu="add", ldmar=1),
               mi(mem="read", size="half", b="thalf", alu="passb", ldr=1)]
        tail = chain("reset", *consts, *regs, *vec,
                     end("reset", a="r2", sina="0", rb=K["PB"], alu="add", ldpc=1))
        head = Node(mi(b="simm", v8="lc", fill="0", alu="passb", ldbank=1), None, "reset")
        last = merge(copy[-1], mi(lcinc=1))
        body = chain("reset", *copy[:-1], branch("reset", last, "tc", head, tail))
        head.succ = ("next", body)
        return chain("reset", *start, head)

    def fixed(self):
        return gm.default_fixed(self.name)

    def preload(self):
        return [(TABLE_PA, table_image())]

    def setup(self, sys, image):
        setup(sys, image)

    def classify(self, w):
        op, ir15 = w & 0xFF, w >> 15
        name, mode = OPS.get(op, (None, None))
        if name is None:
            return ("illegal",), 1
        ln = 2 if name in BRANCH else LENGTH[mode]
        zp_like = mode in ("zp", "izy")
        return (name, mode, ir15 if zp_like else 0), min(ln, 3)

    def routine(self, key):
        if key[0] == "illegal":
            return gm.stop("m6502 illegal")
        name, mode, ir15 = key
        reg = {"zpx": "X", "abx": "X", "izx": "X", "zpy": "Y", "aby": "Y", "izy": "Y"}.get(mode)
        if name in ("LDA", "LDX", "LDY"):
            return op_load(name, reg, mode, ir15)
        if name in ("STA", "STX", "STY"):
            return op_store(name, reg, mode, ir15)
        if name in LOGIC:
            return op_logic(name, reg, mode, ir15)
        if name in ("CMP", "CPX", "CPY"):
            return op_cmp(name, reg, mode, ir15)
        if name in ("ADC", "SBC"):
            return op_adc_sbc(name, reg, mode, ir15)
        if name == "BIT":
            return op_bit(name, reg, mode, ir15)
        if name in ("ASL", "LSR", "ROL", "ROR"):
            return op_shift(name, reg, mode, ir15)
        if name in ("INC", "DEC"):
            return op_incdec(name, reg, mode, ir15)
        if name in BRANCH:
            return op_branch(name)
        if name == "JMP":
            return op_jmp(name, mode)
        simple = {"JSR": op_jsr, "RTS": op_rts, "PHA": op_pha, "PHP": op_php, "PLA": op_pla,
                  "PLP": op_plp, "RTI": op_rti, "BRK": op_brk, "JAM": op_jam}
        if name in simple:
            return simple[name](name)
        return op_reg1(name)

    def pc(self, m):
        return ((m.PC - 2 - PB) >> 1) & 0xFFFF

    def state(self, m):
        f = m.flags_word()
        return {"a": m.rf[A], "x": m.rf[X], "y": m.rf[Y], "s": m.rf[S],
                "pc": ((m.PC - 2 - PB) // 2) & 0xFFFF, "nzcv": f & 15, "d": m.MQ & 1}


def setup(sys, image):
    """What the I/O processor and the boot program do: the doubled image at
    P_PHYS, and its page map."""
    p = doubled(image)
    sys.ram[P_PHYS:P_PHYS + len(p)] = p
    make_map(sys)


def make_map(sys):
    """The page map for the doubled memory (context 0)."""
    def page(vp, pp):
        sys.map[vp] = (pp << 12) | 0b111
    pb = PB >> 12
    pp = P_PHYS >> 12
    for i in range(32):
        page(pb + i, pp + i)
    for i in range(16):
        page(pb - 16 + i, pp + 16 + i)    # below: 0x8000-0xFFFF again, for PB + 2 sext(a)
    page(pb + 32, pp)                     # above: past 0xFFFF
    page(pb + 0x1C, IO_PAGE >> 12)        # guest 0xE000-0xE7FF: the console,
    page(pb - 0x10 + 0x0C, IO_PAGE >> 12)  # in both places


_built = {}


def built():
    if "mc" not in _built:
        _built["mc"] = gm.GuestMicrocode(M6502())
    return _built["mc"]
