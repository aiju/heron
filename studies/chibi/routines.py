"""The routines: every (page, N, OP) block of the control store.

`block(page, n, op)` gives one block's microinstructions (ucode.place
makes the words). Page 0 is entered by decoding (N = d), pages 1 and 2
by a dispatch from page 0 (N = s, or the index parcel's scale and size),
page 3 by the interrupt check at the end of an instruction, by reset, by
an exception or by HALT's wait; page 3's block is the same for every N
and OP.

Conventions (ucode.py has the cycle): a result written with `wr` is in
the register file for the next microinstruction, and one given to PC or
MAR with AX is there by the next one's phase R, so a memory access at
MAR comes in the microinstruction after the one that computes its high
half. The D bus carries one value a
cycle, so a 32-bit operation on two operands takes four: an operand's
half into L, then the other on D through the ALU, twice.
"""

from .ucode import (
    AX_MARHI, AX_MARINC, AX_MARLO, AX_PCHI, AX_PCLO, G, IR_INCD, IR_LDX, LDL, LINK,
    N_MDZ, N_S, RD, RM_SHR, RM_SXB, RM_ZXB, RSRC, SI_C, SI_D15, SP, T_A, T_B,
    T_C, T_CNT, T_FW, T_Q, T_R, T_RET, T_VEC, alu, ax, end, fl, imm, jump, label, mem,
    pcrb_hi, pcrb_lo, rd, store, u, wr, DS_ADR, IR_DECS, MOP_FETCH, MOP_PCS,
)

# page 3's entries
P3_IRQ = 0          # the interrupt check at an instruction's end (and reset)
P3_HALT = 5         # an interrupt ends HALT's wait
P3_EXC = 8          # an exception: T_VEC and T_RET set


class Unimplemented(Exception):
    pass


# ---- helpers -------------------------------------------------------------

def fuse_end(op):
    """op with the fetch and decode of the next instruction, if it can
    take them (it uses neither the memory nor the sequencer), else None."""
    if op.get("SEQ", 0) != 0 or op.get("MOP", 0) not in (0, MOP_PCS) or "_goto" in op:
        return None
    if op.get("AXP", 0):
        return None             # PC changes at the next cycle: fetch after it
    if op.get("DS") == DS_ADR and op.get("MOP", 0) == 0:
        return None             # MAR read back: the fetch would put PC there
    f = dict(op)
    f["MOP"] = MOP_FETCH
    f["SEQ"] = 2
    return f


def finish(ops):
    """ops with the next instruction's fetch: in the last one if it can
    take it, else after."""
    if ops:
        f = fuse_end(ops[-1])
        if f is not None:
            return ops[:-1] + [f]
    return ops + [u(end())]


def trap(vec, unwind):
    """An exception: T_VEC <- the vector, T_RET <- PC less `unwind`
    parcels, then page 3's entry."""
    ops = [u(imm(vec), alu("A"), wr(T_VEC, 0))]
    if unwind:
        ops += [u(imm({1: "C2", 2: "C4", 3: "C6"}[unwind]), LDL),
                u(pcrb_lo(), alu("SUB"), fl("ICLO"), wr(T_RET, 0)),
                u(pcrb_hi(), alu("DECI"), wr(T_RET, 1), jump(P3_EXC, page=3))]
    else:
        ops += [u(pcrb_lo(), alu("A"), wr(T_RET, 0)),
                u(pcrb_hi(), alu("A"), wr(T_RET, 1), jump(P3_EXC, page=3))]
    return ops


def illegal(parcels=1):
    return trap("V_ILL", parcels)


def with_trap(ops, stub):
    """ops, then the trap stub they jump to ('_trap')."""
    return ops + [label("_trap")] + stub if stub else ops


def merge_label(ops):
    """Put label-only entries onto the next microinstruction."""
    out, pending = [], {}
    for op in ops:
        if set(op) == {"_label"}:
            pending = op
            continue
        if pending:
            op = dict(op, **pending)
            pending = {}
        out.append(op)
    assert not pending, "label at the end"
    return out


# ---- operands ------------------------------------------------------------

class Operand:
    """A source operand: the microinstructions that get it ready (`pre`),
    its low half as a D source (`lo`: fields), or in L already (`lo_l`),
    its high half as a D source, None (zero) or 'SEXT' (ST's sign);
    memory operands' size and alignment check, and the parcels the
    instruction has read once `pre` is done."""

    def __init__(self, pre=(), lo=None, hi=None, size=4, memory=False, parcels=1, lo_l=False):
        self.pre = list(pre)
        self.lo, self.hi, self.size = lo, hi, size
        self.memory, self.parcels, self.lo_l = memory, parcels, lo_l

    @property
    def check(self):
        if not self.memory:
            return None
        return {4: "MISW", 2: "A0", 1: None}[self.size]


SIZE = {2: 4, 3: 4, 4: 4, 6: 4, 7: 4, 0xE: 4, 8: 1, 9: 1, 0xA: 1, 0xB: 2, 0xC: 2}
CONST_N = {1: "C1", 2: "C2", 4: "C4"}


def ea_pre(mode, dest="MAR", parcels=1):
    """The microinstructions that compute a mode's address into MAR (dest
    'MAR') or a register; with the parcels read. Auto-increment and
    -decrement update the register here, before the access."""
    size = SIZE[mode]
    if dest == "MAR":
        lo, hi = ax(AX_MARLO), ax(AX_MARHI)
    else:
        lo, hi = wr(dest, 0), wr(dest, 1)
    if mode in (2, 8, 0xB):
        return [u(rd(RSRC, 0), alu("A"), lo), u(rd(RSRC, 1), alu("A"), hi)], parcels
    if mode in (3, 9, 0xC):
        return [u(mem("PC"), LDL, alu("A"), fl("STN")),
                u(rd(RSRC, 0), alu("ADD"), fl("ICLO"), lo),
                u(rd(RSRC, 1), alu("EXT"), hi)], parcels + 1
    if mode in (4, 0xE):
        base = SP if mode == 4 else G(14)
        return [u(imm("SC4"), LDL),
                u(rd(base, 0), alu("ADD"), fl("ICLO"), lo),
                u(rd(base, 1), alu("INCI"), hi)], parcels
    if mode in (6, 0xA):
        return [u(rd(RSRC, 0), alu("A"), lo, LDL),
                u(rd(RSRC, 1), alu("A"), hi),
                u(imm(CONST_N[size]), alu("ADD"), fl("ICLO"), wr(RSRC, 0)),
                u(rd(RSRC, 1), alu("INCI"), wr(RSRC, 1))], parcels
    if mode == 7:
        return [u(imm(CONST_N[size]), LDL),
                u(rd(RSRC, 0), alu("SUB"), fl("ICLO"), wr(RSRC, 0), lo),
                u(rd(RSRC, 1), alu("DECI"), wr(RSRC, 1), hi)], parcels
    raise Unimplemented(f"mode {mode:X}")


def mem_operand(pre, size, parcels):
    if size == 4:
        return Operand(pre, u(mem("MAR", 4), ax(AX_MARINC)), mem("MAR", 4), 4, True, parcels)
    return Operand(pre, mem("MAR", size), None, size, True, parcels)


def mode_operand(mode):
    """A page 0 mode's operand (not 5 or F, which dispatch)."""
    if mode == 0:
        return Operand([], rd(RSRC, 0), rd(RSRC, 1))
    if mode == 1:
        return Operand([], imm("Q4"), None)
    if mode == 0xD:
        return Operand([], imm("NQ"), imm("CM1"))
    pre, parcels = ea_pre(mode)
    return mem_operand(pre, SIZE[mode], parcels)


def special_first():
    """Page 0's microinstruction for the special mode: the first extension
    parcel into L and T_A, its sign into ST, and the dispatch on s."""
    return u(mem("PC"), LDL, alu("A"), fl("STN"), wr(T_A, 0), {"NOP": N_S},
             jump(0, page=1))


def special_operand(s):
    """Page 1's operand for the special mode's R = s (the first parcel in
    L and T_A.lo, its sign in ST); None for the forms that trap."""
    if s == 0:
        return Operand([], None, "SEXT", parcels=2, lo_l=True)
    if s == 1:
        return Operand([], None, None, parcels=2, lo_l=True)
    if s == 2:
        return Operand([], imm("ZERO"), rd(T_A, 0), parcels=2)
    if s == 3:
        return Operand([], None, mem("PC"), parcels=3, lo_l=True)
    size = {0: 4, 1: 1, 2: 2}[(s - 4) % 3] if 4 <= s <= 0xC else None
    if 4 <= s <= 6:
        pre = [u(alu("B"), ax(AX_MARLO)), u(alu("SEXT"), ax(AX_MARHI))]
        return mem_operand(pre, size, 2)
    if 7 <= s <= 9:
        pre = [u(alu("B"), ax(AX_MARLO)), u(mem("PC"), alu("A"), ax(AX_MARHI))]
        return mem_operand(pre, size, 3)
    if 0xA <= s <= 0xC:
        pre = [u(pcrb_lo(), alu("ADD"), fl("ICLO"), ax(AX_MARLO)),
               u(pcrb_hi(), alu("EXT"), ax(AX_MARHI))]
        return mem_operand(pre, size, 2)
    return None


def special_ea(s, dest):
    """LEA's special forms: the address into dest; None where it traps."""
    if 4 <= s <= 6:
        return [u(alu("B"), wr(dest, 0)), u(alu("SEXT"), wr(dest, 1))], 2
    if 7 <= s <= 9:
        return [u(alu("B"), wr(dest, 0)), u(mem("PC"), alu("A"), wr(dest, 1))], 3
    if 0xA <= s <= 0xC:
        return [u(pcrb_lo(), alu("ADD"), fl("ICLO"), wr(dest, 0)),
                u(pcrb_hi(), alu("EXT"), wr(dest, 1))], 2
    return None


def index_first():
    """Page 0's microinstructions for the indexed mode: the base into T_A,
    then the index parcel: d8 sign-extended into T_B.lo (its sign in ST),
    x into s, and the dispatch on its scale and size."""
    return [u(rd(RSRC, 0), alu("A"), wr(T_A, 0)),
            u(rd(RSRC, 1), alu("A"), wr(T_A, 1)),
            u(mem("PC"), alu("A", rm=RM_SXB), fl("STN"), wr(T_B, 0), {"IROP": IR_LDX},
              {"NOP": N_MDZ}, jump(0, page=2))]


def index_ea(z, dest="MAR"):
    """Page 2's address: T_A (the base) + T_B (d8) + x << scale, into dest;
    the access's size; None for the size that traps."""
    scale, size = z >> 2, z & 3
    if size == 3:
        return None
    lo, hi = (ax(AX_MARLO), ax(AX_MARHI)) if dest == "MAR" else (wr(dest, 0), wr(dest, 1))
    ops = [u(alu("SEXT"), wr(T_B, 1)),                         # d8's high half
           u(rd(T_B, 0), LDL),
           u(rd(T_A, 0), alu("ADD"), fl("ICLO"), wr(T_A, 0)),
           u(rd(T_B, 1), LDL),
           u(rd(T_A, 1), alu("ADDI"), wr(T_A, 1))]
    src = RSRC
    for k in range(scale):                                      # x << scale into T_C
        ops += [u(rd(src, 0), alu("SHL"), fl("ICLO"), wr(T_C, 0)),
                u(rd(src, 1), alu("SHLI"), wr(T_C, 1))]
        src = T_C
    ops += [u(rd(src, 0), LDL),
            u(rd(T_A, 0), alu("ADD"), fl("ICLO"), lo),
            u(rd(src, 1), LDL),
            u(rd(T_A, 1), alu("ADDI"), hi)]
    return ops, {0: 1, 1: 2, 2: 4}[size]


# ---- consumers -----------------------------------------------------------

ALU_OPS = {
    # name: (low, high, low flags, high flags, writes, high with B = 0, its flags)
    "ADD": ("ADD", "ADDC", "ADDLO", "ADDHI", True, "INCC", "ADDHIZ"),
    "SUB": ("SUB", "SUBC", "ADDLO", "SUBHI", True, "DECC", "SUBHIZ"),
    "CMP": ("SUB", "SUBC", "ADDLO", "SUBHI", False, "DECC", "SUBHIZ"),
    "AND": ("AND", "AND", "LOGLO", "LOGHI", True, "ZERO", "LOGHI"),
    "OR": ("OR", "OR", "LOGLO", "LOGHI", True, "A", "LOGHI"),
    "XOR": ("XOR", "XOR", "LOGLO", "LOGHI", True, "A", "LOGHI"),
    "BIC": ("BIC", "BIC", "LOGLO", "LOGHI", True, "A", "LOGHI"),
    "TST": ("AND", "AND", "LOGLO", "LOGHI", False, "ZERO", "LOGHI"),
    "ADC": ("ADDC", "ADDC", "ADCLO", "ADDHI", True, "INCC", "ADDHIZ"),
    "SBC": ("SUBC", "SUBC", "ADCLO", "SUBHI", True, "DECC", "SUBHIZ"),
}


def adr_stub(opnd):
    return trap("V_ADR", opnd.parcels) if opnd.check else []


def checked(op, opnd):
    """The first access of a memory operand, jumping to the trap stub when
    it's misaligned."""
    if opnd.check:
        return u(op, jump("_trap", opnd.check))
    return op


def c_mov(opnd, flags=False, dest=RD):
    """dest <- the operand (MOVS: with N and Z)."""
    size = opnd.size
    flo = fhi = None
    if flags:
        flo, fhi = {4: ("LOGLO", "LOGHI"), 2: ("NZ16", None), 1: ("NZ8", None)}[size]
        if opnd.hi is not None and size != 4:
            flo, fhi = "LOGLO", "LOGHI"
    ops = list(opnd.pre)
    lo = u(alu("B")) if opnd.lo_l else u(opnd.lo, alu("A"))
    lo = u(lo, wr(dest, 0), fl(flo) if flo else {})
    ops.append(checked(lo, opnd))
    if opnd.hi is None:
        hi = u(alu("ZERO"), wr(dest, 1))
    elif opnd.hi == "SEXT":
        hi = u(alu("SEXT"), wr(dest, 1), fl(fhi) if fhi else {})
    else:
        hi = u(opnd.hi, alu("A"), wr(dest, 1), fl(fhi) if fhi else {})
    ops.append(hi)
    return with_trap(finish(ops), adr_stub(opnd))


def c_alu(opnd, name):
    """rd <- rd op the operand, or only the flags."""
    alo, ahi, flo, fhi, writes, ahz, fhz = ALU_OPS[name]
    ops = list(opnd.pre)
    if opnd.hi == "SEXT":                      # the special mode's sign-extended constant
        ops.append(u(alu("SEXT"), wr(T_A, 1)))
        hi = rd(T_A, 1)
    else:
        hi = opnd.hi
    if not opnd.lo_l:
        ops.append(checked(u(opnd.lo, LDL), opnd))
    ops.append(u(rd(RD, 0), alu(alo), fl(flo), wr(RD, 0) if writes else {}))
    if hi is None:
        ops.append(u(rd(RD, 1), alu(ahz), fl(fhz), wr(RD, 1) if writes else {}))
    else:
        ops += [u(hi, LDL), u(rd(RD, 1), alu(ahi), fl(fhi), wr(RD, 1) if writes else {})]
    return with_trap(finish(ops), adr_stub(opnd))


def c_store(pre, size, parcels):
    """[the address] <- rd (the register byte's high nibble)."""
    opnd = mem_operand(pre, size, parcels)
    ops = list(pre)
    if size == 4:
        ops += [checked(u(rd(RD, 0), store(4), ax(AX_MARINC)), opnd), u(rd(RD, 1), store(4))]
    else:
        ops.append(checked(u(rd(RD, 0), store(size)), opnd))
    return with_trap(finish(ops), adr_stub(opnd))


def c_clr(pre, size, parcels):
    opnd = mem_operand(pre, size, parcels)
    ops = list(pre)
    if size == 4:
        ops += [checked(u(imm("ZERO"), store(4), ax(AX_MARINC)), opnd),
                u(imm("ZERO"), store(4))]
    else:
        ops.append(checked(u(imm("ZERO"), store(size)), opnd))
    return with_trap(finish(ops), adr_stub(opnd))


def c_incdec(pre, size, parcels, dec):
    """INC or DEC on memory: read, add, write back, N and Z from the value
    written."""
    opnd = mem_operand(pre, size, parcels)
    # the operand into L first: a device's read leaves no time for the carry
    # chain in the same cycle; then D (1 or -1, its high half 0 or -1) + L
    a_lo = "ADD"
    k_lo = "CM1" if dec else "C1"
    ops = list(pre)
    if size == 4:
        ops += [checked(u(mem("MAR", 4), LDL), opnd),
                u(imm(k_lo), alu(a_lo), fl("ICLO"), wr(T_A, 0)),
                u(rd(T_A, 0), store(4), ax(AX_MARINC), alu("A"), fl("LOGLO")),
                u(mem("MAR", 4), LDL),
                u(imm("CM1" if dec else "ZERO"), alu("ADDI"), wr(T_A, 1)),
                u(rd(T_A, 1), store(4), alu("A"), fl("LOGHI"))]
    elif size == 2:
        ops += [checked(u(mem("MAR", 2), LDL), opnd),
                u(imm(k_lo), alu(a_lo), wr(T_A, 0)),
                u(rd(T_A, 0), store(2), alu("A"), fl("NZ16"))]
    else:
        ops += [u(mem("MAR", 1), LDL),
                u(imm(k_lo), alu(a_lo), wr(T_A, 0)),
                u(rd(T_A, 0), store(1), alu("A", rm=RM_ZXB), fl("NZ8"))]
    return with_trap(finish(ops), adr_stub(opnd))


def c_jump(opnd, link):
    """PC <- the operand's value (CALL: r7 <- the next instruction's address,
    after the operand is read)."""
    if opnd.memory and opnd.size != 4:
        return opnd.pre + illegal(opnd.parcels)
    ops = list(opnd.pre)
    if link:
        ops += [u(pcrb_lo(), alu("A"), wr(T_B, 0)), u(pcrb_hi(), alu("A"), wr(T_B, 1))]
    if opnd.hi == "SEXT":
        ops.append(u(alu("SEXT"), wr(T_A, 1)))
        hi = rd(T_A, 1)
    else:
        hi = opnd.hi
    lo = u(alu("B")) if opnd.lo_l else u(opnd.lo, alu("A"))
    ops.append(checked(u(lo, ax(AX_PCLO)), opnd))
    ops.append(u(alu("ZERO") if hi is None else u(hi, alu("A")), ax(AX_PCHI)))
    if link:
        ops += [u(rd(T_B, 0), alu("A"), wr(LINK, 0)), u(rd(T_B, 1), alu("A"), wr(LINK, 1))]
    return with_trap(finish(ops), adr_stub(opnd))


def c_lea(pre):
    return finish(pre)


# ---- the instruction groups ----------------------------------------------

ROWS = {1: "MOV", 2: "ST", 3: "MOVS", 4: "ADD", 5: "SUB", 6: "CMP", 8: "AND", 9: "OR", 0xA: "XOR"}


def row_op(name, opnd):
    if name == "MOV":
        return c_mov(opnd)
    if name == "MOVS":
        return c_mov(opnd, flags=True)
    return c_alu(opnd, name)


def gen_row(op, page, n):
    row, mode = op >> 4, op & 15
    name = ROWS[row]
    if name == "ST":
        if mode in (0, 1, 0xD):
            return gen_mmode(op, page, n)
        if page == 0:
            if mode == 0xF:
                return [special_first()]
            if mode == 5:
                return index_first()
            pre, parcels = ea_pre(mode)
            return c_store(pre, SIZE[mode], parcels)
        if page == 1:
            o = special_operand(n)
            if o is None or not o.memory:
                return illegal(2)
            return c_store(o.pre, o.size, o.parcels)
        ea = index_ea(n)
        if ea is None:
            return illegal(2)
        return c_store(ea[0], ea[1], 2)
    if name == "MOVS" and mode in (1, 0xD):
        return illegal()                    # MFUR, MTUR
    if page == 0:
        if mode == 0xF:
            return [special_first()]
        if mode == 5:
            return index_first()
        return row_op(name, mode_operand(mode))
    if page == 1:
        o = special_operand(n)
        if o is None:
            return illegal(2)
        return row_op(name, o)
    ea = index_ea(n)
    if ea is None:
        return illegal(2)
    return row_op(name, mem_operand(ea[0], ea[1], 2))


MMODE = {0x20: "CLR", 0x21: "INC", 0x2D: "DEC", 0xF0: "JMP", 0xF1: "CALL"}


def gen_mmode(op, page, n):
    """CLR, INC, DEC, JMP and CALL: the mode M in d."""
    name = MMODE[op]
    if page == 0:
        m = n
        if m == 0xF:
            return [special_first()]
        if m == 5:
            return index_first()
        if name in ("JMP", "CALL"):
            return c_jump(mode_operand(m), name == "CALL")
        if m in (1, 0xD):
            return illegal()
        if m == 0:
            if name == "CLR":
                return finish([u(alu("ZERO"), wr(RSRC, 0)), u(alu("ZERO"), wr(RSRC, 1))])
            a_lo, a_hi = ("DEC", "DECI") if name == "DEC" else ("INC", "INCI")
            return finish([u(rd(RSRC, 0), alu(a_lo), fl("ICLOZ"), wr(RSRC, 0)),
                           u(rd(RSRC, 1), alu(a_hi), fl("LOGHI"), wr(RSRC, 1))])
        pre, parcels = ea_pre(m)
        return mem_rmw(name, pre, SIZE[m], parcels)
    if page == 1:
        o = special_operand(n)
        if o is None:
            return illegal(2)
        if name in ("JMP", "CALL"):
            return c_jump(o, name == "CALL")
        if not o.memory:
            return illegal(o.parcels)
        return mem_rmw(name, o.pre, o.size, o.parcels)
    ea = index_ea(n)
    if ea is None:
        return illegal(2)
    if name in ("JMP", "CALL"):
        return c_jump(mem_operand(ea[0], ea[1], 2), name == "CALL")
    return mem_rmw(name, ea[0], ea[1], 2)


def mem_rmw(name, pre, size, parcels):
    if name == "CLR":
        return c_clr(pre, size, parcels)
    return c_incdec(pre, size, parcels, name == "DEC")


def gen_lea(op, page, n):
    mode = op & 15
    if page == 0:
        if mode == 0xF:
            return [special_first()]
        if mode == 5:
            return index_first()
        pre, _ = ea_pre(mode, dest=RD)
        return c_lea(pre)
    if page == 1:
        e = special_ea(n, RD)
        return illegal(2) if e is None else c_lea(e[0])
    ea = index_ea(n, dest=RD)
    return illegal(2) if ea is None else c_lea(ea[0])


def gen_u7(op, page, n):
    k = op & 7
    if op < 0x78:
        return finish([u(imm(f"U7_{k}"), alu("A"), wr(RD, 0)), u(alu("ZERO"), wr(RD, 1))])
    return c_alu(Operand([], imm(f"U7_{k}"), None), "CMP")


def branch(cond):
    """PC <- PC + L (the displacement, its sign in ST), if cond; then the
    fetch."""
    return [u(pcrb_lo(), alu("ADD"), fl("ICLO"), ax(AX_PCLO)),
            u(pcrb_hi(), alu("EXT"), ax(AX_PCHI)),
            u(end())]


# the branch conditions by cc: (condition, inverted)
CC = {0: ("Z", False), 1: ("Z", True), 2: ("C", False), 3: ("C", True), 4: ("N", False),
      5: ("N", True), 6: ("V", False), 7: ("V", True), 8: ("HI", False), 9: ("HI", True),
      0xA: ("LT", True), 0xB: ("LT", False), 0xC: ("LE", True), 0xD: ("LE", False)}


def link_ops():
    return [u(pcrb_lo(), alu("A"), wr(LINK, 0)), u(pcrb_hi(), alu("A"), wr(LINK, 1))]


def gen_bcc(op, page, n):
    cc = op & 15
    first = u(imm("B8"), alu("A"), LDL, fl("STN"))
    if cc in (0xE, 0xF):
        ops = (link_ops() if cc == 0xF else []) + [first] + branch(None)
        return ops
    c, inv = CC[cc]
    return [u(first, jump("nt", c, not inv))] + branch(c) + [label("nt"), u(end())]


def gen_jcc(op, page, n):
    """F2 Jcc rel16 (PC + 2 s16), F3 Jcc abs32; cc = d."""
    cc = n
    ops = []
    if op == 0xF2:
        ops.append(u(mem("PC"), alu("A"), LDL, fl("STN")))
        if cc < 0xE:
            c, inv = CC[cc]
            ops[-1] = u(ops[-1], jump("nt", c, not inv))
        if cc == 0xF:
            ops += link_ops()
        ops += [u(pcrb_lo(), alu("ADD"), fl("ICLO"), wr(T_A, 0)),
                u(pcrb_hi(), alu("EXT"), wr(T_A, 1)),
                u(rd(T_A, 0), alu("ADD"), fl("ICLO"), ax(AX_PCLO)),
                u(rd(T_A, 1), alu("EXT"), ax(AX_PCHI)),
                u(end())]
    else:
        ops += [u(mem("PC"), alu("A"), wr(T_A, 0)), u(mem("PC"), alu("A"), wr(T_A, 1))]
        if cc < 0xE:
            c, inv = CC[cc]
            ops[-1] = u(ops[-1], jump("nt", c, not inv))
        if cc == 0xF:
            ops += link_ops()
        ops += [u(rd(T_A, 0), alu("A"), ax(AX_PCLO)), u(rd(T_A, 1), alu("A"), ax(AX_PCHI)),
                u(end())]
    if cc < 0xE:
        ops += [label("nt"), u(end())]
    return ops


def gen_shift(op, page, n):
    """Row C: LSL, LSR, ASR, ROR by n (C0-C1 ...: page 1 knows n) or by rs.
    Up to six steps are unrolled; more loop on T_CNT."""
    kind = (op >> 2) & 3            # 0 LSL, 1 LSR, 2 ASR, 3 ROR
    by_reg = (op & 3) == 2
    if (op & 3) == 3:
        return illegal()
    if not by_reg and page == 0:
        return [u({"NOP": N_S}, jump(0, page=1))]
    step = shift1(kind)
    if by_reg:
        ops = [u(imm("C31"), LDL),
               u(rd(RSRC, 0), alu("AND"), fl("STZ"), wr(T_CNT, 0)),
               u(jump("done", "ST"))]
    else:
        count = 2 * n + (op & 1)
        if count <= 6:
            return finish([s for _ in range(count) for s in step] + nz32(RD))
        ops = [u(imm(f"SH{op & 1}"), alu("A"), wr(T_CNT, 0))]
    loop = [u(rd(T_CNT, 0), alu("DEC"), fl("STZ"), wr(T_CNT, 0))] + step
    loop[0] = u(loop[0], label("loop"))
    loop[-1] = u(loop[-1], jump("loop", "ST", True))
    ops += loop + nz32(RD)
    if by_reg:
        # a count of 0: N and Z, V <- 0, C as it was
        ops += [u(end()), u(rd(RD, 0), alu("A"), fl("LOGLO"), label("done")),
                u(rd(RD, 1), alu("A"), fl("LOGHI")), u(imm("ZERO"), alu("A"), fl("VNZ"))]
    return finish(merge_label(ops))


def shift1(kind):
    """rd shifted by one: C the bit out, V 0."""
    if kind == 0:
        return [u(rd(RD, 0), alu("SHL"), fl("SHL"), wr(RD, 0)),
                u(rd(RD, 1), alu("SHLC"), fl("SHL"), wr(RD, 1))]
    if kind in (1, 2):
        si = SI_D15 if kind == 2 else 0
        return [u(rd(RD, 1), alu("A", rm=RM_SHR, si=si), fl("SHR"), wr(RD, 1)),
                u(rd(RD, 0), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(RD, 0))]
    return [u(rd(RD, 0), alu("A", rm=RM_SHR), fl("SHR")),
            u(rd(RD, 1), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(RD, 1)),
            u(rd(RD, 0), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(RD, 0))]


def nz32(reg):
    return [u(rd(reg, 0), alu("A"), fl("LOGLO")), u(rd(reg, 1), alu("A"), fl("LOGHI"))]


def gen_unary(op, page, n):
    """Row D: rd <- f(rs)."""
    f = op & 15
    if f == 0:      # NOT
        return finish([u(rd(RSRC, 0), alu("NOTA"), fl("LOGLO"), wr(RD, 0)),
                       u(rd(RSRC, 1), alu("NOTA"), fl("LOGHI"), wr(RD, 1))])
    if f == 1:      # NEG
        return finish([u(rd(RSRC, 0), LDL), u(imm("ZERO"), alu("SUB"), fl("ADDLO"), wr(RD, 0)),
                       u(rd(RSRC, 1), LDL), u(imm("ZERO"), alu("SUBC"), fl("SUBHI"), wr(RD, 1))])
    if f in (2, 3):  # INC, DEC
        a_lo, a_hi = ("INC", "INCI") if f == 2 else ("DEC", "DECI")
        return finish([u(rd(RSRC, 0), alu(a_lo), fl("ICLOZ"), wr(RD, 0)),
                       u(rd(RSRC, 1), alu(a_hi), fl("LOGHI"), wr(RD, 1))])
    if f == 4:      # RLC
        return finish([u(rd(RSRC, 0), alu("SHLC"), fl("SHL"), wr(RD, 0)),
                       u(rd(RSRC, 1), alu("SHLC"), fl("SHL"), wr(RD, 1))] + nz32(RD))
    if f == 5:      # RRC
        return finish([u(rd(RSRC, 1), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(RD, 1)),
                       u(rd(RSRC, 0), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(RD, 0))]
                      + nz32(RD))
    if f == 6:      # SWAP
        return finish([u(rd(RSRC, 0), LDL), u(rd(RSRC, 1), alu("A"), fl("LOGLO"), wr(RD, 0)),
                       u(alu("B"), fl("LOGHI"), wr(RD, 1))])
    if f in (7, 8):     # SXB, SXH
        rm = RM_SXB if f == 7 else 0
        return finish([u(rd(RSRC, 0), alu("A", rm=rm), fl("STN"), wr(RD, 0)),
                       u(alu("SEXT"), wr(RD, 1)),
                       u(rd(RD, 0), alu("A"), fl("NZ16"))])
    if f == 9:      # ZXB
        return finish([u(rd(RSRC, 0), alu("A", rm=RM_ZXB), fl("NZ16"), wr(RD, 0)),
                       u(alu("ZERO"), wr(RD, 1))])
    if f == 0xA:    # ZXH
        return finish([u(rd(RSRC, 0), alu("A"), fl("LOGLO"), wr(RD, 0)),
                       u(alu("ZERO"), fl("LOGHI"), wr(RD, 1))])
    if f == 0xB:    # CLZ: the half with a one in it shifted until its top bit is
        return finish([
            u(rd(RSRC, 1), alu("A"), fl("STZ"), wr(T_A, 0)),
            u(alu("ZERO"), wr(T_CNT, 0), jump("lo", "ST")),
            u(rd(T_A, 0), alu("A"), fl("STN"), jump("loop")),
            label("lo"),
            u(rd(RSRC, 0), alu("A"), fl("STZ"), wr(T_A, 0)),
            u(imm("C16"), alu("A"), wr(T_CNT, 0), jump("zero", "ST")),
            u(rd(T_A, 0), alu("A"), fl("STN")),
            label("loop"),
            u(rd(T_A, 0), alu("SHL"), fl("STN"), wr(T_A, 0), jump("done", "ST")),
            u(rd(T_CNT, 0), alu("INC"), wr(T_CNT, 0), jump("loop")),
            label("zero"),
            u(imm("C32"), alu("A"), wr(T_CNT, 0)),
            label("done"),
            u(rd(T_CNT, 0), alu("A"), fl("NZ16"), wr(RD, 0)),
            u(alu("ZERO"), wr(RD, 1))])
    if f == 0xE:    # REV: each half rotated by 8, the halves swapped; page 0 the high
        def rot8(half, t):
            """t <- rs's half rotated by 8: IC <- the top bit, then t <<= 1 with
            it, eight times."""
            ops = [u(rd(RSRC, half), alu("SHL"), fl("ICLO")),
                   u(rd(RSRC, half), alu("SHLI"), wr(t, 0))]
            for _ in range(7):
                ops += [u(rd(t, 0), alu("SHL"), fl("ICLO")), u(rd(t, 0), alu("SHLI"), wr(t, 0))]
            return ops
        if page == 0:
            ops = rot8(1, T_A)
            ops[-1] = u(ops[-1], jump(0, page=1))
            return ops
        if page == 1:
            return finish(rot8(0, T_B) + [u(rd(T_A, 0), alu("A"), fl("LOGLO"), wr(RD, 0)),
                                          u(rd(T_B, 0), alu("A"), fl("LOGHI"), wr(RD, 1))])
        return []
    if f == 0xF:    # SETcc rd: cc = s
        if page == 0:
            return [u({"NOP": N_S}, jump(0, page=1))]
        if n == 0xF:
            return illegal()
        if n == 0xE:
            return finish([u(imm("C1"), alu("A"), wr(RD, 0)), u(alu("ZERO"), wr(RD, 1))])
        c, inv = CC[n]
        return [u(jump("one", c, inv)),
                u(alu("ZERO"), wr(RD, 0)), u(alu("ZERO"), wr(RD, 1), end()),
                label("one"),
                u(imm("C1"), alu("A"), wr(RD, 0)), u(alu("ZERO"), wr(RD, 1), end())]
    raise Unimplemented(f"unary {op:02X}")


def gen_rowe(op, page, n):
    f = op & 15
    if f in (0, 1, 2, 3):
        name = ["ADC", "SBC", "BIC", "TST"][f]
        return c_alu(mode_operand(0), name)
    if f in (0xA, 0xB):
        name = ["BIC", "TST"][f - 0xA]
        if page == 0:
            return [special_first()]
        o = special_operand(n)
        return illegal(2) if o is None else c_alu(o, name)
    if f == 4:
        return mulu(RSRC)
    if f == 5:
        return muls(page)
    if f == 6:
        return mula(page)
    if f == 7:
        return divu(RSRC, long=False)
    if f == 8:
        return divs(page)
    if f == 9:
        return divu(RSRC, long=True)
    if f == 0xF:
        return illegal()
    raise Unimplemented(f"row E {op:02X}")


def mul_loop(src, a=RD):
    """T_R:T_Q <- a * src, unsigned: shift and add, 32 steps."""
    return [u(rd(a, 0), alu("A"), wr(T_Q, 0)), u(rd(a, 1), alu("A"), wr(T_Q, 1)),
            u(alu("ZERO"), wr(T_R, 0)), u(alu("ZERO"), wr(T_R, 1)),
            u(imm("C32"), alu("A"), wr(T_CNT, 0)),
            label("loop"),
            u(rd(T_CNT, 0), alu("DEC"), fl("STZ"), wr(T_CNT, 0)),
            u(rd(T_Q, 0), alu("A", rm=RM_SHR), fl("SHR")),                # C <- the multiplier's bit
            u(jump("shift", "C", True)),
            u(rd(src, 0), LDL), u(rd(T_R, 0), alu("ADD"), fl("ADDLO"), wr(T_R, 0)),
            u(rd(src, 1), LDL), u(rd(T_R, 1), alu("ADDC"), fl("SHL"), wr(T_R, 1)),
            label("shift"),
            u(rd(T_R, 1), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(T_R, 1)),
            u(rd(T_R, 0), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(T_R, 0)),
            u(rd(T_Q, 1), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(T_Q, 1)),
            u(rd(T_Q, 0), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(T_Q, 0),
              jump("loop", "ST", True))]


def mul_result():
    """rd <- T_Q, N and Z from it: the last writes, after r0's, so that rd
    wins where it is r0."""
    return [u(rd(T_Q, 0), alu("A"), fl("LOGLO"), wr(RD, 0)),
            u(rd(T_Q, 1), alu("A"), fl("LOGHI"), wr(RD, 1))]


def mulu(src):
    """r0:rd <- rd * src, unsigned: shift and add, 32 steps. N and Z from rd,
    C = V = r0 isn't 0."""
    ops = mul_loop(src) + [
        u(rd(T_R, 0), alu("A"), wr(G(0), 0), LDL),
        u(rd(T_R, 1), alu("A"), wr(G(0), 1)),
        u(rd(T_R, 1), alu("OR"), fl("CNZ")),
        u(rd(T_R, 1), alu("OR"), fl("VNZ"))] + mul_result()
    return finish(ops)


def mula(page):
    """MULA r0:r1, rd, rs: r0:r1 <- r0:r1 + rd * rs, signed; the flags
    don't change, so the multiply's are put back from T_FW."""
    if page == 0:
        return flags_word(T_FW) + signed_product()
    if page == 1:
        ops = less(RD, "c") + [label("c")]
        for k, (acc, half, part) in enumerate(((1, 0, T_Q), (1, 1, T_Q), (0, 0, T_R), (0, 1, T_R))):
            ops += [u(rd(part, half), LDL),
                    u(rd(G(acc), half), alu("ADD" if k == 0 else "ADDI"),
                      fl("ICLO") if k < 3 else {}, wr(G(acc), half))]
        ops.append(u(rd(T_FW, 0), LDL))
        for bit, f in ((1, "VNZ"), (2, "CNZ"), (4, "ZNZ")):
            ops.append(u(imm(f"C{bit}"), alu("AND"), fl(f)))
        return finish(ops)
    return []


def neg_into(dst, x):
    """dst <- 0 - x, x's low half in L already (x a register)."""
    return [u(imm("ZERO"), alu("SUB"), fl("ICLO"), wr(dst, 0)),
            u(rd(x, 1), LDL),
            u(imm("ZERO"), alu("SUBI"), wr(dst, 1))]


def less(x, skip):
    """T_R <- T_R - x if ST (the sign the step before found), else to `skip`."""
    return [u(rd(x, 0), LDL, jump(skip, "ST", True)),
            u(rd(T_R, 0), alu("SUB"), fl("ICLO"), wr(T_R, 0)),
            u(rd(x, 1), LDL),
            u(rd(T_R, 1), alu("SUBI"), wr(T_R, 1))]


def signed_product(a=RD, b=RSRC):
    """T_R:T_Q <- a * b, signed, as page 0's part: the unsigned product,
    its high half less b if a is negative; then ST <- b's sign and on to
    page 1, which takes a off if b is negative (less(a, ...))."""
    return (mul_loop(b, a) + [u(rd(a, 1), alu("A"), fl("STN"))] + less(b, "b")
            + [label("b"), u(rd(b, 1), alu("A"), fl("STN"), jump(0, page=1))])


def gen_mulfx(op, page, n):
    """FD 00 MULFX r0:rd, rs, #n (the extension parcel: rd, rs, 000, n):
    page 0 reads the extension, rd into s (IR_LDX) and rs into N; page 2,
    a block for each rs, multiplies; page 1 checks the extension's
    reserved bits, puts the product's high half in r0, shifts the product
    right by n (a bit at a time, arithmetic) and sets the flags as MULS
    does from what's left."""
    if page == 0:
        if n != 0:
            return illegal(1)
        return [u(jump("bad", "NE")),                                       # the register byte isn't 0
                u(mem("PC"), alu("A"), wr(T_C, 0), {"IROP": IR_LDX}, {"NOP": N_MDZ},
                  jump(0, page=2)),
                label("bad")] + illegal(1)
    if page == 2:
        ops = signed_product(RSRC, G(n))
        ops[-1] = u({k: v for k, v in ops[-1].items() if k not in ("SEQ", "CND", "_goto", "_page")})
        return ops + less(RSRC, "c") + [label("c"),
                                        u(imm("C31"), LDL, jump(0, page=1))]
    ops = [u(rd(T_C, 0), alu("AND"), wr(T_CNT, 0)),                       # n
           u(rd(T_C, 0), alu("A", rm=RM_ZXB), wr(T_C, 0)),
           u(rd(T_CNT, 0), LDL),
           u(rd(T_C, 0), alu("XOR"), fl("STZ")),                           # bits 7-5 clear
           u(rd(T_CNT, 0), alu("A"), fl("STZ"), jump("_trap", "ST", True)),
           u(rd(T_R, 0), alu("A"), wr(G(0), 0)),
           u(rd(T_R, 1), alu("A"), wr(G(0), 1)),
           label("loop"),
           u(rd(T_CNT, 0), alu("DEC"), fl("STZ"), wr(T_CNT, 0), jump("done", "ST")),
           u(rd(T_R, 1), alu("A", rm=RM_SHR, si=SI_D15), fl("SHR"), wr(T_R, 1)),
           u(rd(T_R, 0), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(T_R, 0)),
           u(rd(T_Q, 1), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(T_Q, 1)),
           u(rd(T_Q, 0), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(T_Q, 0), jump("loop")),
           label("done"),
           u(rd(T_Q, 1), alu("A"), fl("STN")),                             # ST <- the result's sign
           u(rd(T_R, 0), alu("A"), LDL, jump("neg", "ST")),
           u(rd(T_R, 1), alu("OR"), fl("CNZ")),                            # the rest isn't 0
           u(rd(T_R, 1), alu("OR"), fl("VNZ"), jump("fin")),
           label("neg"),
           u(rd(T_R, 1), alu("AND"), wr(T_A, 0)),                          # the rest isn't FFFFFFFF
           u(rd(T_A, 0), alu("INC"), fl("CNZ")),
           u(rd(T_A, 0), alu("INC"), fl("VNZ")),
           label("fin"),
           u(rd(T_Q, 0), alu("A"), fl("LOGLO"), wr(RSRC, 0)),
           u(rd(T_Q, 1), alu("A"), fl("LOGHI"), wr(RSRC, 1), end())]
    return ops + [label("_trap")] + illegal(2)


def muls(page):
    """MULS r0:rd, rs: signed_product, then the flags (C = V = r0 isn't
    rd's sign extension). rd and rs are read again after the loop: nothing
    is written until the end."""
    if page == 0:
        return signed_product()
    if page == 1:
        ops = less(RD, "c") + [
            label("c"),
            u(rd(T_Q, 1), alu("A"), fl("STN")),                            # ST <- rd's new sign
            u(rd(T_R, 0), alu("A"), wr(G(0), 0), LDL),
            u(rd(T_R, 1), alu("A"), wr(G(0), 1), jump("neg", "ST")),
            u(rd(T_R, 1), alu("OR"), fl("CNZ")),                           # r0 isn't 0
            u(rd(T_R, 1), alu("OR"), fl("VNZ"), jump("fin")),
            label("neg"),
            u(rd(T_R, 1), alu("AND"), wr(T_A, 0)),                         # r0 isn't FFFFFFFF
            u(rd(T_A, 0), alu("INC"), fl("CNZ")),
            u(rd(T_A, 0), alu("INC"), fl("VNZ")),
            label("fin")] + mul_result()
        return finish(ops)
    return []


def div_loop(src, rem):
    """rem:T_Q / src, restoring, 32 steps: T_Q the quotient, rem the
    remainder (T_A a scratch)."""
    return [label("loop"),
            u(rd(T_CNT, 0), alu("DEC"), fl("STZ"), wr(T_CNT, 0)),
            u(rd(T_Q, 0), alu("SHL"), fl("ICLO"), wr(T_Q, 0)),
            u(rd(T_Q, 1), alu("SHLI"), fl("ICLO"), wr(T_Q, 1)),
            u(rd(rem, 0), alu("SHLI"), fl("ICLO"), wr(rem, 0)),
            u(rd(rem, 1), alu("SHLI"), fl("ICLO"), wr(rem, 1)),
            u(rd(src, 0), LDL),
            u(rd(rem, 0), alu("SUB"), fl("ADDLO"), wr(T_A, 0)),
            u(rd(src, 1), LDL),
            u(rd(rem, 1), alu("SUBC"), fl("SHL"), wr(T_A, 1), jump("take", "IC")),
            u(jump("next", "C", True)),
            label("take"),
            u(rd(T_A, 0), alu("A"), wr(rem, 0)),
            u(rd(T_A, 1), alu("A"), wr(rem, 1)),
            u(rd(T_Q, 0), alu("INC"), wr(T_Q, 0)),
            label("next"),
            u(jump("loop", "ST", True))]


def divs(page):
    """DIVS r0:rd, rs: the unsigned divide of the magnitudes, the remainder
    taking rd's sign and the quotient negated if the signs differ: page 0
    the magnitudes (T_Q, T_B), page 1 the loop, page 2 the signs and the
    flags. The one quotient that doesn't fit, 0x80000000 / -1, comes out
    as 0x80000000 with V set, as the ISA has it."""
    if page == 0:
        ops = [u(rd(RSRC, 0), LDL),
               u(rd(RSRC, 1), alu("OR"), fl("STZ")),
               u(rd(RSRC, 1), alu("A"), fl("STN"), wr(T_B, 1), jump("_trap", "ST")),
               u(rd(RSRC, 0), alu("A"), wr(T_B, 0), LDL, jump("bpos", "ST", True))]
        ops += neg_into(T_B, RSRC) + [
            label("bpos"),
            u(rd(RD, 1), alu("A"), fl("STN"), wr(T_Q, 1)),
            u(rd(RD, 0), alu("A"), wr(T_Q, 0), LDL, jump("apos", "ST", True))]
        ops += neg_into(T_Q, RD) + [
            label("apos"),
            u(alu("ZERO"), wr(T_R, 0)), u(alu("ZERO"), wr(T_R, 1)),
            u(imm("C32"), alu("A"), wr(T_CNT, 0), jump(0, page=1))]
        return ops + [label("_trap")] + trap("V_DIV", 1)
    if page == 1:
        return div_loop(T_B, T_R) + [u(jump(0, page=2))]
    ops = [u(rd(RD, 1), alu("A"), fl("STN")),
           u(rd(T_R, 0), LDL, jump("rpos", "ST", True))]
    ops += neg_into(T_R, T_R) + [
        label("rpos"),
        u(rd(RD, 1), LDL),
        u(rd(RSRC, 1), alu("XOR"), fl("STN")),                             # the signs differ
        u(rd(T_Q, 0), LDL, jump("qpos", "ST", True))]
    ops += neg_into(T_Q, T_Q) + [
        u(alu("ZERO"), fl("SHR"), jump("fin")),                            # C = V = 0
        label("qpos"),
        u(rd(T_Q, 1), alu("A"), fl("STN")),
        u(alu("ZERO"), fl("SHR"), jump("fin", "ST", True)),
        u(imm("C1"), alu("A"), fl("VNZ")),                                 # the quotient 2^31
        label("fin"),
        u(rd(T_R, 0), alu("A"), wr(G(0), 0)),
        u(rd(T_R, 1), alu("A"), wr(G(0), 1))] + mul_result()
    return finish(ops)


def divu(src, long):
    """DIVU r0:rd, rs: rd <- rd / rs, r0 <- the remainder; DIVUL: r0:rd / rs.
    Restoring division, 32 steps; dividing by zero is a divide error, and
    DIVUL with r0 >= rs sets V and changes nothing. DIVUL keeps the
    remainder in r0 as it goes (rs = r0 is the overflow), DIVU in T_R."""
    rem = G(0) if long else T_R
    ops = [u(rd(src, 0), LDL),
           u(rd(src, 1), alu("OR"), fl("STZ")),
           u(rd(RD, 0), alu("A"), wr(T_Q, 0), jump("_trap", "ST")),
           u(rd(RD, 1), alu("A"), wr(T_Q, 1))]
    if long:
        # r0 >= rs: the quotient doesn't fit (IC: no borrow; the flags stay)
        ops += [u(rd(src, 0), LDL), u(rd(G(0), 0), alu("SUB"), fl("ICLO")),
                u(rd(src, 1), LDL), u(rd(G(0), 1), alu("SUBI"), fl("ICLO")),
                u(imm("C32"), alu("A"), wr(T_CNT, 0), jump("ovf", "IC"))]
    else:
        ops += [u(alu("ZERO"), wr(T_R, 0)), u(alu("ZERO"), wr(T_R, 1)),
                u(imm("C32"), alu("A"), wr(T_CNT, 0))]
    ops += div_loop(src, rem)
    if not long:
        ops += [u(rd(T_R, 0), alu("A"), wr(G(0), 0)), u(rd(T_R, 1), alu("A"), wr(G(0), 1))]
    ops += [u(rd(T_Q, 0), alu("A"), fl("LOGLO"), wr(RD, 0)),
            u(rd(T_Q, 1), alu("A"), fl("LOGHI"), wr(RD, 1)),
            u(alu("ZERO"), fl("SHR"), end())]
    if long:
        ops += [label("ovf"), u(imm("CM1"), alu("A"), fl("VNZ"), end())]
    return ops + [label("_trap")] + trap("V_DIV", 1)


def gen_save(op, page, n):
    """F4 SAVE ra-rb: from rb down, each pushed (s counts down to d);
    F5 RESTORE ra-rb: from [sp] up into ra..rb (d counts up to s)."""
    if op == 0xF4:
        return [u(imm("C4"), LDL),
                label("loop"),
                u(rd(SP, 0), alu("SUB"), fl("ICLO"), wr(SP, 0), ax(AX_MARLO)),
                u(rd(SP, 1), alu("DECI"), wr(SP, 1), ax(AX_MARHI)),
                u(rd(RSRC, 0), store(4), ax(AX_MARINC)),
                u(rd(RSRC, 1), store(4), {"IROP": IR_DECS}, jump("loop", "NE")),
                u(end())]
    return [u(rd(SP, 0), alu("A"), ax(AX_MARLO)),
            u(rd(SP, 1), alu("A"), ax(AX_MARHI)),
            u(imm("C4"), LDL),
            label("loop"),
            u(mem("MAR", 4), alu("A"), wr(RD, 0), ax(AX_MARINC)),
            u(mem("MAR", 4), alu("A"), wr(RD, 1), ax(AX_MARINC)),
            u(rd(SP, 0), alu("ADD"), fl("ICLO"), wr(SP, 0)),
            u(rd(SP, 1), alu("INCI"), wr(SP, 1), {"IROP": IR_INCD}, jump("loop", "NE")),
            u(end())]


def gen_dbnz(op, page, n):
    """DBNZ r, back k: r = d, k - 1 = s. No flag changes."""
    return [u(imm("DB"), LDL),
            u(rd(RD, 0), alu("DEC"), fl("ICSTZ"), wr(RD, 0)),
            u(rd(RD, 1), alu("DECI"), wr(RD, 1), jump("taken", "ST", True)),
            u(rd(RD, 1), alu("A"), fl("STZ")),
            u(jump("taken", "ST", True)),
            u(end()),
            label("taken"),
            u(pcrb_lo(), alu("ADD"), fl("ICLO"), ax(AX_PCLO)),
            u(pcrb_hi(), alu("DECI"), ax(AX_PCHI)),
            u(end())]


def gen_system(op, page, n):
    """FE: EI, DI, RTI, HALT (second byte 00-03); SPL is illegal here."""
    if page == 0:
        if n != 0:
            return illegal()
        return [u({"NOP": N_S}, jump(0, page=1))]
    s = n
    if s == 0:
        return [u(fl("SETI"), end())]
    if s == 1:
        return [u(fl("CLRI"), end())]
    if s == 2:
        return rti()
    if s == 3:
        return [u(jump("stop", "I", True)),
                label("wait"),
                u(jump("wait", "IRQP", True)),
                u(jump(P3_HALT, page=3)),
                label("stop"),
                u({"HALT": 1}, jump("stop"))]
    return illegal()


def rti():
    """Pop the flags word, then the PC."""
    ops = [u(rd(SP, 0), alu("A"), ax(AX_MARLO)),
           u(rd(SP, 1), alu("A"), ax(AX_MARHI)),
           u(mem("MAR", 4), LDL, ax(AX_MARINC)),
           u(mem("MAR", 4), ax(AX_MARINC))]
    for bit, f in ((1, "VNZ"), (2, "CNZ"), (4, "ZNZ"), (8, "NNZ"), (16, "INZ")):
        ops.append(u(imm(f"C{bit}"), alu("AND"), fl(f)))
    ops += [u(mem("MAR", 4), alu("A"), ax(AX_PCLO), ax(AX_MARINC)),
            u(mem("MAR", 4), alu("A"), ax(AX_PCHI)),
            u(imm("C8"), LDL),
            u(rd(SP, 0), alu("ADD"), fl("ICLO"), wr(SP, 0)),
            u(rd(SP, 1), alu("INCI"), wr(SP, 1)),
            u(end())]
    return ops


def gen_flags_sr(op, page, n):
    """06 MFSR rd, n (only n = 0, the flags word); 07 MTSR n, rs (n = d)."""
    if op == 0x06:
        if page == 0:
            return [u({"NOP": N_S}, jump(0, page=1))]
        if n != 0:
            return illegal()
        return finish(flags_word(RD))
    if n != 0:
        return illegal()
    ops = [u(rd(RSRC, 0), LDL)]
    for bit, f in ((1, "VNZ"), (2, "CNZ"), (4, "ZNZ"), (8, "NNZ"), (16, "INZ")):
        ops.append(u(imm(f"C{bit}"), alu("AND"), fl(f)))
    return finish(ops)


def flags_word(dest):
    """dest <- the flags word, V C Z N I in bits 0-4, built bit by bit
    through IC."""
    ops = [u(fl("ICI")),
           u(imm("ZERO"), alu("SHLI"), wr(dest, 0), fl("ICN"))]
    for f in ("ICZ", "ICC", "ICV"):
        ops.append(u(rd(dest, 0), alu("SHLI"), wr(dest, 0), fl(f)))
    ops += [u(rd(dest, 0), alu("SHLI"), wr(dest, 0)), u(alu("ZERO"), wr(dest, 1))]
    return ops


def gen_swi(op, page, n):
    return trap("V_SWI", 0)


def page3():
    ops = [u(jump("reset", "INIT", True)),                                  # 0
           u(imm("V_IRQ"), alu("A"), wr(T_VEC, 0)),                         # 1
           u(imm("C2"), LDL),                                               # 2
           u(pcrb_lo(), alu("SUB"), fl("ICLO"), wr(T_RET, 0)),              # 3
           u(pcrb_hi(), alu("DECI"), wr(T_RET, 1), jump("exc")),             # 4
           u(imm("V_IRQ"), alu("A"), wr(T_VEC, 0), label("halt")),          # 5: HALT
           u(pcrb_lo(), alu("A"), wr(T_RET, 0)),                            # 6
           u(pcrb_hi(), alu("A"), wr(T_RET, 1)),                            # 7
           u(imm("C4"), LDL, label("exc")),                                 # 8
           u(rd(SP, 0), alu("SUB"), fl("ICLO"), wr(SP, 0), ax(AX_MARLO)),
           u(rd(SP, 1), alu("DECI"), wr(SP, 1), ax(AX_MARHI)),
           u(rd(T_RET, 0), store(4), ax(AX_MARINC)),
           u(rd(T_RET, 1), store(4))]
    ops += flags_word(T_FW)
    ops += [u(rd(SP, 0), alu("SUB"), fl("ICLO"), wr(SP, 0), ax(AX_MARLO)),
            u(rd(SP, 1), alu("DECI"), wr(SP, 1), ax(AX_MARHI)),
            u(rd(T_FW, 0), store(4), ax(AX_MARINC), fl("CLRI")),
            u(imm("ZERO"), store(4)),
            u(rd(T_VEC, 0), alu("A"), ax(AX_PCLO)),
            u(alu("ZERO"), ax(AX_PCHI)),
            u(end()),
            u(fl("SETINIT"), jump(0, page=1), label("reset"))]
    return ops


BOOT_MAGIC = 0x1F               # the boot flash's byte 0 when it holds an image


def boot():
    """Reset's second part, in opcode 00's page-1 block (reset clears OP and
    N): if the boot flash's byte 0 is BOOT_MAGIC, copy byte 1's count of
    256-byte pages from its byte 2 on into RAM at 0, a byte at a time;
    then enter the program at 0. The flash's byte n is at 0x8010_0000 + 2n."""
    return [u(imm("ZERO"), alu("A"), ax(AX_MARLO)),
            u(imm("C8010"), alu("A"), ax(AX_MARHI)),
            u(imm("C31"), LDL),
            u(mem("MAR", 1), alu("XOR"), fl("STZ"), ax(AX_MARINC)),     # ST: the magic's there
            u(mem("MAR", 1), alu("A"), wr(T_CNT, 0), jump("enter", "ST", True)),
            u(imm("C4"), alu("A"), wr(T_A, 0)),                         # T_A: the flash's address
            u(imm("C8010"), alu("A"), wr(T_A, 1)),
            u(alu("ZERO"), wr(T_B, 0)), u(alu("ZERO"), wr(T_B, 1)),     # T_B: RAM's
            u(imm("C2"), LDL),
            label("loop"),
            u(rd(T_A, 0), alu("A"), ax(AX_MARLO)),
            u(rd(T_A, 1), alu("A"), ax(AX_MARHI)),
            u(mem("MAR", 1), alu("A"), wr(T_C, 0)),
            u(rd(T_B, 0), alu("A"), ax(AX_MARLO)),
            u(rd(T_B, 1), alu("A"), ax(AX_MARHI)),
            u(rd(T_C, 0), store(1)),
            u(rd(T_B, 0), alu("INC"), fl("ICLO"), wr(T_B, 0)),
            u(rd(T_B, 0), alu("A", rm=RM_ZXB), fl("STZ")),              # ST: a page's end
            u(rd(T_B, 1), alu("INCI"), wr(T_B, 1)),
            u(rd(T_A, 0), alu("ADD"), fl("ICLO"), wr(T_A, 0)),
            u(rd(T_A, 1), alu("INCI"), wr(T_A, 1), jump("loop", "ST", True)),
            u(rd(T_CNT, 0), alu("DEC"), fl("STZ"), wr(T_CNT, 0)),
            u(jump("loop", "ST", True)),
            label("enter"),
            u(alu("ZERO"), ax(AX_PCLO)),
            u(alu("ZERO"), ax(AX_PCHI)),
            u(end())]


def _entries():
    out, i = {}, 0
    for op in page3():
        if "_label" in op:
            out[op["_label"]] = i
        if set(op) != {"_label"}:
            i += 1
    return out


ENTRIES = _entries()
assert ENTRIES["exc"] == P3_EXC and ENTRIES["halt"] == P3_HALT, ENTRIES


# ---- the decode ------------------------------------------------------------

def routine(page, n, op):
    """One block's microinstructions, with labels."""
    if page == 3:
        return page3()
    row = op >> 4
    if op in MMODE:
        return gen_mmode(op, page, n)
    if row in ROWS:
        return gen_row(op, page, n)
    if op in (0x03, 0x04, 0x05, 0x0E, 0x0F):
        return gen_lea(op, page, n)
    if row == 7:
        return gen_u7(op, page, n)
    if row == 0xB:
        return gen_bcc(op, page, n)
    if op in (0xF2, 0xF3):
        return gen_jcc(op, page, n)
    if row == 0xC:
        return gen_shift(op, page, n)
    if row == 0xD:
        return gen_unary(op, page, n)
    if row == 0xE:
        return gen_rowe(op, page, n)
    if op in (0xF4, 0xF5):
        return gen_save(op, page, n)
    if op == 0xF6:
        return gen_dbnz(op, page, n)
    if op == 0xFE:
        return gen_system(op, page, n)
    if op == 0xFC:
        return gen_swi(op, page, n)
    if op == 0xFD:
        return gen_mulfx(op, page, n)
    if op in (0x06, 0x07):
        return gen_flags_sr(op, page, n)
    if op == 0x00 and page == 1 and n == 0:
        return boot()
    if op in (0x00, 0xFF, 0xC3, 0xC7, 0xCB, 0xCF, 0xEF, 0xF7, 0xF8, 0xF9, 0xFA, 0xFB):
        return illegal()
    raise Unimplemented(f"{op:02X}")


# ---- the control store ---------------------------------------------------

class ControlStore:
    """Every block placed: `words` (packed, by address), `fields` (unpacked,
    by address, for the model), `missing` (the opcodes not yet written,
    whose blocks stop the machine)."""

    def __init__(self):
        from . import ucode as uc
        self.words = [0] * uc.CS_WORDS
        self.missing = {}
        cache = {}
        for page in range(uc.PAGES):
            for n in range(16):
                for op in range(256):
                    try:
                        ops = page3_ops() if page == 3 else routine(page, n, op)
                    except Unimplemented as e:
                        self.missing.setdefault(op, str(e))
                        ops = []
                    words = uc.place(merge_label(ops), page, f"{page}/{n:X}/{op:02X}")
                    base = uc.addr(page, n, op, 0)
                    for i, f in enumerate(words):
                        k = tuple(sorted(f.items()))
                        w = cache.get(k)
                        if w is None:
                            w = cache[k] = uc.pack(f)
                        self.words[base + i] = w
        self.distinct = len(cache)


_P3 = None


def page3_ops():
    global _P3
    if _P3 is None:
        _P3 = page3()
    return _P3


_CS = None


def control_store():
    global _CS
    if _CS is None:
        _CS = ControlStore()
    return _CS
