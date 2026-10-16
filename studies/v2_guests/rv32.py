"""RV32IM on the draft 2 CPU, unmodified: microcode only.

The native fetch works as it is: RISC-V's instructions are 32 bits, two
parcels, at 4-byte boundaries, so the prefetch queue fetches them and the
decode table is indexed by the first parcel, P1 = insn[15:0]:

    P1:  15 rs1[0] | 14-12 funct3 | 11-7 rd | 6-0 opcode
    P2:  15-9 funct7 | 8-4 rs2 | 3-0 rs1[4:1]        (the head parcel, QH)

What doesn't fit is where the register numbers are. Draft 2's register
file is addressed by IR[15:12], IR[11:8], the counter SX or a constant,
and RISC-V's fields are five bits wide, at bits 7, 15 and 20. So:

- **Every register is a bank.** x_n is location 0 of register bank n. A
  register number is computed by the ALU into BANK (any 8 bits), and the
  next cycle reads that bank (UBR), or the cycle writes it (UBW). Two
  registers can't be read in one cycle.
- **Fields of the second parcel come out of tables in the register file.**
  The register file is 256 banks of 32 locations: location L of bank i is
  entry i of a 256-entry table. A byte of P2 into BANK, then one read,
  gives rs2, or a slice of an immediate, in two cycles where a shift
  would take four or five (the datapath shifts by 1, 8 or 16). The I/O
  processor puts the tables in RAM with the program (preload), and the
  reset routine copies them into the register file.
- **rd, rs1[0] and the S- and B-type immediates' low bits are in P1**, so
  the decode table gives them for free: routines are specialised on them
  (rd's low bit, rs1's low bit, the immediate's five bits as a constant).
  rd[4:1] is IR[11:8], the immediate unit's q.

There are no flags in RISC-V, so the CPU's own flags and condition latch
are the microcode's scratch. Branches use the native branch condition
where P1's IR[15:12] (rs1[0] and funct3) happens to be the right
condition code: 0 EQ, 1 NE, 4 MI, 5 PL, which is BEQ, BNE, BLT and BGE
when rs1 is even; else the condition latch.

What the C programs need is here (RV32IM without CSRs, FENCE a no-op).
ECALL and EBREAK stop the machine; EBREAK is the normal end.
"""

from heron.studies.v2_hw import ucode as uc
from heron.studies.v2_hw.ucode import mi, merge, chain, branch, loop, end, Node

from . import guest as gm

M32 = 0xFFFFFFFF
G = uc.G
TMP1, TMP2, TMP3 = G, G + 1, G + 2
ZERO, K801E, K2, K80, K8000 = G + 3, G + 4, G + 5, G + 6, G + 7
CONSTS = {ZERO: 0, K801E: 0x801E, K2: 2, K80: 0x80, K8000: 0x8000}

# the tables: location L of bank i holds TABLES[L](i)


def _sx8(i):
    return i - 256 if i & 0x80 else i


L_SHR3, L_LCSH, L_IHI, L_ILO, L_SHI, L_BHI0, L_BHI1, L_JHI, L_JLO = range(16, 25)
TABLES = {
    L_SHR3: lambda i: i >> 3,                                 # P2[8:1] -> rs2 (shamt)
    L_LCSH: lambda i: 255 - (i >> 3),                         # P2[8:1] -> LC for a shift
    L_IHI: lambda i: _sx8(i) << 4,                            # I-imm from P2[15:8]
    L_ILO: lambda i: i >> 4,                                  # ... and P2[7:4]
    L_SHI: lambda i: (_sx8(i) >> 1) << 5,                     # S-imm[11:5] from P2[15:9]
    # B-imm[12|10:5] from P2[15:9], with imm[11] (from P1) 0 or 1
    L_BHI0: lambda i: (-4096 if i & 0x80 else 0) | (((i >> 1) & 63) << 5),
    L_BHI1: lambda i: (-4096 if i & 0x80 else 0) | (((i >> 1) & 63) << 5) | 0x800,
    # J-imm[20|10:4] from P2[15:8], and [3:1|11|19:16] from P2[7:0]
    L_JHI: lambda i: (-(1 << 20) if i & 0x80 else 0) | ((i & 0x7F) << 4),
    L_JLO: lambda i: ((i >> 5) << 1) | (((i >> 4) & 1) << 11) | ((i & 15) << 16),
}
K12_BANK = 255          # locations 0-15: k << 12, read with IR[15:12] (U-imm, J-imm[15:12])
TABLE_PA = 0x100000     # where the I/O processor puts them: past the guest's megabyte

SEXT = {0: (1, K80, 0b1110), 1: (2, K8000, 0b1100)}     # LB, LH: size, sign bit, RZ


def table_image():
    """The words the reset routine copies, in its order."""
    words = []
    for i in range(256):
        for L in sorted(TABLES):
            words.append(TABLES[L](i) & M32)
    words += [(k << 12) for k in range(16)]
    words += [CONSTS[k] for k in sorted(CONSTS)]
    return b"".join(w.to_bytes(4, "little") for w in words)


# --------------------------------------------------------------------------
# Steps

def bank_rs1(ir15, consume=False, cl=False):
    """BANK <- rs1 = {P2[3:0], P1[15]}, and UBR: the next step reads
    x[rs1] at location 0. cl: also CL <- (funct7[5] == 0), from P2[14].
    An odd rs1 takes a second step, with MAR as the scratch (R is kept)."""
    f = mi(b="qh2", fill="0", ra=K801E, alu="and", consume=consume)
    if cl:
        f = merge(f, mi(ldcl="hz17"))
    if not ir15:
        return [merge(f, mi(ldbank=1, ubr=1))]
    return [merge(f, mi(ldmar=1)), mi(a="mar", alu="inc", ldbank=1, ubr=1)]


def bank_rs2(consume=False):
    """BANK <- rs2 = P2[8:4] through the table, and UBR."""
    return [mi(b="qh", fill="0", alu="passb", rms="shr", sin="0", ldbank=1, ubr=1,
               consume=consume),
            mi(ra=L_SHR3, alu="passa", ldbank=1, ubr=1)]


def bank_rd(rd0):
    """BANK <- rd = {IR[11:8], IR[7]}: (4q + 2 rd[0]) >> 1. The next step
    writes x[rd] with UBW."""
    if rd0:
        return mi(ra=K2, imm="s4", alu="add", rms="shr", sin="0", ldbank=1)
    return mi(imm="s4", alu="passb", rms="shr", sin="0", ldbank=1)


def by_p2(table, **kw):
    """Two steps: BANK <- a byte of P2 (hi: P2[15:8], lo: P2[7:0]), UBR."""
    if table == "hi":
        return mi(b="qh", fill="0", alu="passb", rms="ror8", ldbank=1, ubr=1, **kw)
    return mi(b="qh", fill="0", alu="passb", ldbank=1, ubr=1, **kw)


def imm_i():
    """R <- the I-type immediate, sext(P2[15:4]): four steps. (The two
    register file ports share one constant address, RFK: a table and a
    scratch location can't both be read in a cycle, so R holds the part.)"""
    return [by_p2("hi"), mi(ra=L_IHI, alu="passa", ldr=1),
            by_p2("lo"), mi(ra=L_ILO, b="r", alu="add", ldr=1)]


def write_rd(name, rd0, value):
    """The last two steps: BANK <- rd; x[rd] <- value (fields that put it on
    RES), then decode."""
    return [bank_rd(rd0), end(name, _fields=merge(value, mi(w=0, ubw=1)))]


def raw(s, m, cin=None, **kw):
    """A 74181 function by its select lines, for the ones ucode.ALU hasn't
    named."""
    f = merge(mi(**kw), {"S": s, "M": m})
    if cin is not None:
        f["CIN"] = uc.CIN[cin]
    return f


# --------------------------------------------------------------------------
# Instructions

def nop2(name):
    return chain(name, mi(consume=1), end(name))


ALU_OPS = {0: "add", 4: "xor", 6: "or", 7: "and"}


def alu_tail(name, f3, rd0, a, b, sub=False):
    """R <- a op b, then x[rd] <- R; or SLT, SLTU through the sign; a and b
    are field dicts putting the operands on A and B."""
    if f3 in ALU_OPS or sub:
        op = mi(alu="sub" if sub else ALU_OPS[f3], ldr=1)
        return chain(name, merge(a, b, op), *write_rd(name, rd0, mi(a="r", alu="passa")))
    # SLT (2): the subtraction's true sign; SLTU (3): its carry (a >= b)
    cmp = merge(a, b, mi(alu="sub", md="shr64", rms="shr", sin="f31" if f3 == 2 else "0",
                         ldr=1))
    zero = end(name, alu="zero", w=0, ubw=1)
    one = end(name, kv=1, alu="passb", w=0, ubw=1)
    lt_if_r31 = (zero, one) if f3 == 2 else (one, zero)
    return chain(name, cmp, branch(name, bank_rd(rd0), "r31", *lt_if_r31))


def shift_tail(name, kind, rd0, entry=None):
    """LC = 255 - n: the step that enters the loop (entry's fields, LC + 1;
    n = 0 skips the loop), n steps shifting R, and the write."""
    out = chain(name, *write_rd(name, rd0, mi(a="r", alu="passa")))
    if kind == "sll":
        step = mi(a="r2", sina="0", alu="passa", ldr=1, lcinc=1)
    else:
        step = mi(a="r", alu="passa", rms="shr", sin="f31" if kind == "sra" else "0", ldr=1,
                  lcinc=1)
    body = loop(name, step, "tc", out)
    return branch(name, merge(entry or {}, mi(lcinc=1)), "tc", body, out)


def op_imm(f3, rd0, ir15):
    name = {0: "ADDI", 1: "SLLI", 2: "SLTI", 3: "SLTIU", 4: "XORI", 5: "SRxI", 6: "ORI",
            7: "ANDI"}[f3]
    if f3 in (1, 5):
        # LC <- 255 - shamt (shamt = P2[8:4]); CL tells SRLI from SRAI
        pre = [mi(b="qh", fill="0", alu="passb", rms="shr", sin="0", ldbank=1, ubr=1),
               mi(ra=L_LCSH, alu="passa", ldlc=1)]
        rs1 = bank_rs1(ir15, consume=True, cl=True)
        load = mi(ra=0, alu="passa", ldr=1)
        if f3 == 1:
            return chain(name, *pre, *rs1, shift_tail(name, "sll", rd0, load))
        return chain(name, *pre, *rs1,
                     branch(name, load, "cl",
                            shift_tail(name + " SRAI", "sra", rd0),
                            shift_tail(name + " SRLI", "srl", rd0)))
    return chain(name, *imm_i(), *bank_rs1(ir15, consume=True),
                 alu_tail(name, f3, rd0, mi(ra=0), mi(b="r")))


def op_reg(f3, rd0, ir15):
    """R-type: R <- x[rs1], then BANK <- rs2 with a dispatch on funct7[0]
    (the M extension); CL says funct7[5] (SUB, SRA)."""
    base_name = {0: "ADD", 1: "SLL", 2: "SLT", 3: "SLTU", 4: "XOR", 5: "SRx", 6: "OR",
                 7: "AND"}[f3]
    mname = {0: "MUL", 1: "MULH", 2: "MULHSU", 3: "MULHU", 4: "DIV", 5: "DIVU", 6: "REM",
             7: "REMU"}[f3]
    rs2b = mi(ra=L_SHR3, alu="passa", ldbank=1, ubr=1)
    a, b = mi(a="r"), mi(rb=0)
    if f3 == 0:
        base = branch(base_name, rs2b, "cl",
                      alu_tail("SUB", 0, rd0, a, b, sub=True), alu_tail("ADD", 0, rd0, a, b))
    elif f3 in (1, 5):
        def sh(kind):
            # LC <- 255 - (x[rs2] & 31); R holds x[rs1]
            return chain(base_name, mi(ra=0, kv=-32, alu="ornb", ldlc=1),
                         shift_tail(base_name, kind, rd0))
        if f3 == 1:
            base = chain(base_name, rs2b, sh("sll"))
        else:
            base = branch(base_name, rs2b, "cl", sh("sra"), sh("srl"))
    else:
        base = chain(base_name, rs2b, alu_tail(base_name, f3, rd0, a, b))
    m = chain(mname, rs2b, muldiv(mname, f3, rd0))
    table = [m if i & 2 else base for i in range(16)]
    first = mi(b="qh", fill="0", alu="passb", rms="shr", sin="0", ldbank=1, ubr=1, consume=1)
    return chain(base_name, *bank_rs1(ir15, cl=True), mi(ra=0, alu="passa", ldr=1),
                 Node(first, ("dispatch", table), base_name))


def muldiv(name, f3, rd0):
    """R = x[rs1], BANK = rs2 (UBR set): TMP1 <- a (SGN <- its sign),
    TMP2 <- b."""
    save = [mi(a="r", alu="passa", w=TMP1, fill="a31", ldsgn=1, ubr=1)]
    if f3 < 4:
        # unsigned 32 x 32 -> R:MQ, a bit a step, MQ the multiplier
        step = mi(a="r", rb=TMP1, md="mulu", rms="shr", ldr=1, lcinc=1)
        if f3 == 0:
            done = chain(name, *write_rd(name, rd0, mi(b="mq", alu="passb")))
        elif f3 == 3:
            done = chain(name, *write_rd(name, rd0, mi(a="r", alu="passa")))
        else:
            # the signed high word: - (a < 0 ? b : 0), and for MULH also
            # - (b < 0 ? a : 0); the masks from SGN
            fix = [mi(ra=TMP2, b="fillall", fill="sgn", alu="and", w=TMP3),
                   mi(a="r", rb=TMP3, alu="sub", ldr=1)]
            if f3 == 1:
                fix += [mi(ra=TMP2, fill="a31", ldsgn=1),
                        mi(ra=TMP1, b="fillall", fill="sgn", alu="and", w=TMP3),
                        mi(a="r", rb=TMP3, alu="sub", ldr=1)]
            done = chain(name, *fix, *write_rd(name, rd0, mi(a="r", alu="passa")))
        body = loop(name, step, "tc", done)
        return chain(name, *save, mi(ra=0, alu="passa", w=TMP2),
                     mi(rb=TMP2, md="mqload", alu="zero", ldr=1),
                     mi(kv=-32, alu="passb", ldlc=1), body)
    # divide: non-restoring on magnitudes, R the partial remainder, MQ the
    # quotient; TMP3 the divisor. Division by zero: RISC-V's answers
    signed = f3 in (4, 6)
    rem = f3 in (6, 7)
    dz = chain(name, *write_rd(name, rd0, mi(ra=TMP1, alu="passa") if rem
                                else mi(kv=-1, alu="passb")))
    fix = mi(a="r", rb=TMP3, md="fix", ldr=1)
    body_step = mi(a="r2", sina="mq31", rb=TMP3, md="div", ldr=1, lcinc=1)
    if not signed:
        out = chain(name, fix, *write_rd(name, rd0, mi(a="r", alu="passa") if rem
                                          else mi(b="mq", alu="passb")))
        go = chain(name, mi(rb=TMP1, md="mqload", alu="zero", ldr=1),
                   mi(kv=-32, alu="passb", ldlc=1), loop(name, body_step, "tc", out))
        return chain(name, *save, mi(ra=0, alu="passa", w=TMP3, ldcl="zero"),
                     branch(name, {}, "cl", go, dz))
    if rem:
        # the remainder takes a's sign (SGN, set from a last)
        out = chain(name, fix, mi(a="r", b="fillall", fill="sgn", alu="xor", ldr=1),
                    *write_rd(name, rd0, mi(a="r", alu="a", cin="sgn")))
    else:
        # the quotient's sign is a's xor b's
        out = chain(name, fix, mi(ra=TMP1, alu="passa", ldr=1),
                    mi(a="r", rb=TMP2, alu="xor", ldr=1),
                    mi(a="r", fill="a31", ldsgn=1, b="mq", alu="passb", ldr=1),
                    mi(a="r", b="fillall", fill="sgn", alu="xor", ldr=1),
                    *write_rd(name, rd0, mi(a="r", alu="a", cin="sgn")))
    go = chain(name,
               mi(ra=TMP2, b="fillall", fill="a31", ldsgn=1, alu="xor", ldr=1),
               mi(a="r", alu="a", cin="sgn", w=TMP3),                               # |b|
               mi(ra=TMP1, b="fillall", fill="a31", ldsgn=1, alu="xor", ldr=1),
               mi(a="r", alu="a", cin="sgn", ldr=1),                                # |a|
               mi(b="r", md="mqload", alu="zero", ldr=1),
               mi(kv=-32, alu="passb", ldlc=1), loop(name, body_step, "tc", out))
    return chain(name, *save, mi(ra=0, alu="passa", w=TMP2, ldcl="zero"),
                 branch(name, {}, "cl", go, dz))


def load(f3, rd0, ir15):
    name = {0: "LB", 1: "LH", 2: "LW", 4: "LBU", 5: "LHU"}[f3]
    size = {0: "byte", 1: "half", 2: "word", 4: "byte", 5: "half"}[f3]
    addr = [*imm_i(), *bank_rs1(ir15, consume=True), mi(ra=0, b="r", alu="add", ldmar=1)]
    if f3 in SEXT:
        n, k, rz = SEXT[f3]
        lane = "tbyte" if n == 1 else "thalf"
        return chain(name, *addr,
                     mi(mem="read", size=size, b=lane, ra=k, alu="xor", rz=rz, ldr=1),
                     *write_rd(name, rd0, mi(a="r", rb=k, alu="sub")))
    lane = {2: "t", 4: "tbyte", 5: "thalf"}[f3]
    return chain(name, *addr, merge(mi(mem="read", size=size), bank_rd(rd0)),
                 end(name, b=lane, alu="passb", w=0, ubw=1))


def store(f3, ir15, imm40):
    name = {0: "SB", 1: "SH", 2: "SW"}[f3]
    size = {0: "byte", 1: "half", 2: "word"}[f3]
    return chain(name, by_p2("hi"), mi(ra=L_SHI, kv=imm40, alu="add", ldr=1),
                 *bank_rs1(ir15), mi(ra=0, b="r", alu="add", ldmar=1),
                 *bank_rs2(consume=True),
                 end(name, ra=0, mem="write", size=size))


def branch_insn(f3, ir15, imm11, c):
    """TMP2 <- offset - 4 (P2 is consumed by the time PC is added); R <-
    x[rs1]; BANK <- rs2; compare; jump."""
    name = {0: "BEQ", 1: "BNE", 4: "BLT", 5: "BGE", 6: "BLTU", 7: "BGEU"}[f3]
    head = [by_p2("hi"), mi(ra=L_BHI1 if imm11 else L_BHI0, kv=c - 4, alu="add", w=TMP2),
            *bank_rs1(ir15), mi(ra=0, alu="passa", ldr=1), *bank_rs2(consume=True)]
    jump = mi(a="pc", rb=TMP2, alu="add", ldpc=1)
    a_b = mi(a="r", rb=0)                 # x[rs1] - x[rs2]
    b_a = mi(ra=0, b="r")                 # x[rs2] - x[rs1]
    if f3 == 6:                           # taken iff a < b unsigned: no carry
        return chain(name, *head, merge(a_b, mi(alu="sub", ldcl="aluc")),
                     end(name, _fields=merge(jump, mi(pccond="ncl"))))
    if f3 == 7:                           # taken iff not b > a: b - a - 1 doesn't carry
        return chain(name, *head, merge(b_a, raw(0b0110, 0, cin="0", ldcl="aluc")),
                     end(name, _fields=merge(jump, mi(pccond="ncl"))))
    if not ir15:
        # IR[15:12] = funct3: EQ, NE from Z; MI, PL from N, which is the
        # subtraction's true sign
        if f3 in (0, 1):
            cmp = merge(a_b, mi(alu="sub", fnz="nz"))
        else:
            cmp = merge(a_b, mi(alu="sub", md="shr64", rms="shr", sin="f31", fnz="nz"))
        return chain(name, *head, cmp,
                     end(name, _fields=merge(jump, mi(pccond="bcond", ccb="jcc"))))
    # IR[15:12] = 8 + funct3: GT and LE of b - a are BLT and BGE; BNE from
    # the condition latch; BEQ a microcode branch
    if f3 in (4, 5):
        return chain(name, *head, merge(b_a, mi(alu="sub", fnz="nz", fv="ovf")),
                     end(name, _fields=merge(jump, mi(pccond="bcond", ccb="jcc"))))
    cmp = merge(a_b, mi(alu="sub", ldcl="zero"))
    if f3 == 1:
        return chain(name, *head, cmp, end(name, _fields=merge(jump, mi(pccond="ncl"))))
    return chain(name, *head, cmp, branch(name, {}, "cl", end(name), end(name, _fields=jump)))


def jal(rdz, rd0, k0):
    name = "JAL" if not rdz else "J"
    steps = [by_p2("hi"), mi(ra=L_JHI, kv=-4, alu="add", ldr=1),
             by_p2("lo", consume=1), mi(ra=L_JLO, b="r", alu="add", ldr=1)]
    if not k0:
        steps += [mi(kv=-1, alu="passb", ldbank=1, ubr=1),       # bank 255: k << 12
                  mi(ra="d", b="r", alu="add", ldr=1)]
    if not rdz:
        steps += [bank_rd(rd0), mi(a="pc", alu="passa", w=0, ubw=1)]
    return chain(name, *steps, end(name, a="pc", b="r", alu="add", ldpc=1))


def jalr(rdz, rd0, ir15):
    name = "JALR" if not rdz else "JR"
    steps = [*imm_i(), *bank_rs1(ir15, consume=True), mi(ra=0, b="r", alu="add", ldr=1)]
    if not rdz:
        steps += [bank_rd(rd0), mi(a="pc", alu="passa", w=0, ubw=1)]
    return chain(name, *steps, end(name, a="r", alu="passa", ldpc=1))


def lui(rd0, k0, auipc):
    name = "AUIPC" if auipc else "LUI"
    if k0:
        steps = [mi(b="qhh", alu="passb", ldr=1, consume=1)]
    else:
        steps = [mi(kv=-1, alu="passb", ldbank=1, ubr=1),
                 mi(ra="d", b="qhh", alu="or", ldr=1, consume=1)]
    if not auipc:
        return chain(name, *steps, *write_rd(name, rd0, mi(a="r", alu="passa")))
    return chain(name, *steps, mi(a="pc", b="r", alu="add", ldr=1),
                 *write_rd(name, rd0, mi(a="r", kv=4, alu="sub")))


def system():
    """ECALL (P2 = 0) or EBREAK (P2 = 0x0010): both stop; EBREAK is the
    normal end."""
    return chain("SYSTEM", mi(b="qh", fill="0", alu="passb", ldcl="zero", consume=1),
                 branch("SYSTEM", {}, "cl", gm.stop("rv32 halt"), gm.stop("rv32 ecall")))


# --------------------------------------------------------------------------
# The guest

class RV32:
    name = "rv32"

    def reset(self):
        """S set, flags clear; MAR <- the tables (in the window); for each
        bank i: BANK <- i, then a word read and written to location L, one
        a cycle; the k << 12 bank; the constants; x0 <- 0; jump to 0."""
        n_t = len(TABLES)
        start = [mi(alu="zero", ldr=1), mi(a="r", loadf="nzcv", sset=1),
                 mi(kv=0x10, alu="passb", rms="ror16", ldr=1),          # 0x0010_0000
                 mi(kv=1, alu="passb", rms="shr", sin="f0", w=TMP1),    # 0x8000_0000
                 mi(a="r", rb=TMP1, alu="or", ldmar=1),
                 mi(alu="zero", ldlc=1)]
        copy = [mi(mem="read", size="word", marinc=1, b="t", alu="passb", w=L, ubw=1)
                for L in sorted(TABLES)]
        k12 = [mi(kv=-1, alu="passb", ldbank=1)]
        k12 += [mi(mem="read", size="word", marinc=1, b="t", alu="passb", w=k, ubw=1)
                for k in range(16)]
        consts = [mi(mem="read", size="word", marinc=1, b="t", alu="passb", w=k)
                  for k in sorted(CONSTS)]
        tail = chain("reset", *k12, *consts, mi(alu="zero", w=0),
                     end("reset", alu="zero", ldpc=1))
        head = Node(mi(b="simm", v8="lc", fill="0", alu="passb", ldbank=1), None, "reset")
        last = merge(copy[-1], mi(lcinc=1))
        body = chain("reset", *copy[:-1], branch("reset", last, "tc", head, tail))
        head.succ = ("next", body)
        assert n_t == len(copy)
        return chain("reset", *start, head)

    def fixed(self):
        return gm.default_fixed(self.name)

    def preload(self):
        return [(TABLE_PA, table_image())]

    def classify(self, w):
        if w & 3 != 3:
            return ("illegal",), 1
        op, rd, f3, ir15 = w & 0x7F, (w >> 7) & 31, (w >> 12) & 7, w >> 15
        rd0, rdz = rd & 1, rd == 0
        k0 = ((w >> 12) & 15) == 0
        if op in (0x37, 0x17):
            return (("nop2",) if rdz else ("lui", rd0, k0, op == 0x17)), 2
        if op == 0x6F:
            return ("jal", rdz, rd0, k0), 2
        if op == 0x67 and f3 == 0:
            return ("jalr", rdz, rd0, ir15), 2
        if op == 0x63 and f3 not in (2, 3):
            return ("br", f3, ir15, rd & 1, rd & 0x1E), 2
        if op == 0x03 and f3 in (0, 1, 2, 4, 5):
            return (("nop2",) if rdz else ("ld", f3, rd0, ir15)), 2
        if op == 0x23 and f3 <= 2:
            return ("st", f3, ir15, rd), 2
        if op == 0x13:
            return (("nop2",) if rdz else ("opi", f3, rd0, ir15)), 2
        if op == 0x33:
            return (("nop2",) if rdz else ("op", f3, rd0, ir15)), 2
        if op == 0x0F:
            return ("nop2",), 2
        if w == 0x0073:
            return ("system",), 2
        return ("illegal",), 1

    def routine(self, key):
        k = key[0]
        if k == "illegal":
            return gm.stop("rv32 illegal")
        if k == "nop2":
            return nop2("NOP")
        if k == "lui":
            return lui(*key[1:])
        if k == "jal":
            return jal(*key[1:])
        if k == "jalr":
            return jalr(*key[1:])
        if k == "br":
            return branch_insn(*key[1:])
        if k == "ld":
            return load(*key[1:])
        if k == "st":
            return store(*key[1:])
        if k == "opi":
            return op_imm(*key[1:])
        if k == "op":
            return op_reg(*key[1:])
        if k == "system":
            return system()
        raise ValueError(key)

    def state(self, m):
        """x0-x31 and the PC of the instruction being decoded."""
        return {"x": [m.rf[n << 5] for n in range(32)], "pc": (m.PC - 2) & M32}


_built = {}


def built(**opts):
    key = tuple(sorted(opts.items()))
    if key not in _built:
        _built[key] = gm.GuestMicrocode(RV32(**opts))
    return _built[key]
