"""The two-halves machine's routines: every (page, N, OP) block of the
control store (ucode2.py has the microinstruction and the pages).

The first cut's routines (routines.py) rewritten for microinstructions
that do 32-bit operations: `W` marks one with a high half, which does to
the high halves what its low half does to the low. Conventions:

- a result written with `wr` is in the register file for the next
  microinstruction; PC and MAR loaded with AX are there for it too;
- the condition of a jump sees the flags as the cycle's last half starts:
  a 32-bit microinstruction's jump sees what its own low half did;
- a memory access's alignment is checked where its address is computed,
  in the microinstruction that loads MAR (STA4 or STF0 into ST, and a
  jump to the trap stub on it), so that a misaligned access traps before
  anything is changed; a jump checks its target likewise (STF0);
- a task may run after a microinstruction that ends an instruction or
  jumps with `task=True` (a task point): there MAR and the flags but ST and
  IC are dead (a task uses them), L is kept (no task touches it).
"""

from . import odt
from .ucode2 import (
    AX_MARINC, AX_MARLO, AX_PCLO, DS_ADR, DS_FLW, G, IMM_CODE, IRN_DECS, IRN_IDX,
    IRN_INCD, IRN_NS, LDL, LINK, MOP_FETCH, MOP_LDIRM, MOP_PCS, RD, RM_SHR, RM_SXB, RM_ZXB,
    RSRC, SEQ_END, SEQ_NEXT, SI_C, SI_D15, SP, T_A, T_B, T_C, T_CNT, T_FW, T_Q, T_R, T_RET,
    T_VEC, W, alu, ax, end, fl, hx, imm, jump, label, mem, pcrb, rd, store, u, wr,
)

P3_IRQ = 0


class Unimplemented(Exception):
    pass


def irn(code):
    return {"IRN": code}


FLW = {"DS": DS_FLW, "IMMF": IMM_CODE["ZERO"]}      # the flags word on D (15-7: 0)

# ---- helpers -------------------------------------------------------------


def fuse_end(op):
    """op with the next instruction's fetch (in its last half), if it can
    take it, else None."""
    if op.get("SEQ", SEQ_NEXT) != SEQ_NEXT or op.get("MOP", 0) not in (0, MOP_PCS) or \
            "_goto" in op:
        return None
    if op.get("AXP", 0):
        return None
    if op.get("DS") == DS_ADR and op.get("MOP", 0) == 0:
        return None
    f = dict(op)
    f["MOP"] = MOP_FETCH
    f["SEQ"] = 2
    return f


def finish(ops):
    if ops:
        f = fuse_end(ops[-1])
        if f is not None:
            return ops[:-1] + [f]
    return ops + [u(end())]


VEC_SUMS = {"V_ADR": ("C16", "C4"), "V_TAG": ("C16", "C8")}     # 0x14, 0x18


def trap(vec, unwind):
    """An exception: T_VEC <- the vector, T_RET <- PC less `unwind`
    parcels, then page 3's entry."""
    if vec in VEC_SUMS:         # (vectors the immediates haven't)
        a, b = VEC_SUMS[vec]
        ops = [u(imm(a), LDL, W), u(imm(b), alu("ADD"), wr(T_VEC), W)]
    else:
        ops = [u(imm(vec), alu("A"), wr(T_VEC), W)]
    if unwind:
        ops += [u(imm({1: "C2", 2: "C4", 3: "C6"}[unwind]), LDL, W),
                u(pcrb(), alu("SUB"), wr(T_RET), jump("exc", page=3))]
    else:
        ops += [u(pcrb(), alu("A"), wr(T_RET), jump("exc", page=3))]
    return ops


def illegal(parcels=1):
    return trap("V_ILL", parcels)


def with_stubs(ops, stubs):
    """ops, then each stub (label: microinstructions) they jump to."""
    for name, stub in stubs.items():
        if stub:
            ops = ops + [label(name)] + stub
    return ops


def merge_label(ops):
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


CHECK = {4: "STA4", 2: "STF0", 1: None}


def chk(size):
    """The alignment check of an address computed in this microinstruction."""
    c = CHECK[size]
    return u(fl(c), jump("_trap", "ST")) if c else {}


# ---- operands ------------------------------------------------------------

class Operand:
    """A source operand: the microinstructions that get it ready (`pre`),
    then either a 32-bit D source (`val`: fields for a W microinstruction)
    or the value in L already (`in_l`); a 16- or 8-bit memory operand
    (zero-extended) has `size` 2 or 1. `stub`: the parcels to unwind for
    the address's trap, None if nothing traps."""

    def __init__(self, pre=(), val=None, size=4, memory=False, parcels=1, in_l=False, stub=None):
        self.pre = list(pre)
        self.val, self.size, self.memory = val, size, memory
        self.parcels, self.in_l, self.stub = parcels, in_l, stub

    def to_l(self):
        if self.in_l:
            return []
        if self.memory and self.size < 4:
            return [u(mem("MAR", self.size), LDL, hx("IMMH", "ZERO"))]
        return [u(self.val, LDL, W)]

    def stubs(self):
        return {"_trap": trap("V_ADR", self.stub) if self.stub is not None else []}


SIZE = {2: 4, 3: 4, 4: 4, 6: 4, 7: 4, 0xE: 4, 8: 1, 9: 1, 0xA: 1, 0xB: 2, 0xC: 2}
CONST_N = {1: "C1", 2: "C2", 4: "C4"}


def ea_pre(mode, dest="MAR", parcels=1):
    """A mode's address into MAR (checked) or into a register (dest, not
    checked); the parcels read."""
    size = SIZE[mode]
    if dest == "MAR":
        lo, c = ax(AX_MARLO), chk(size)
    else:
        lo, c = wr(dest), {}
    if mode in (2, 8, 0xB):
        return [u(rd(RSRC), alu("A"), lo, W, c)], parcels
    if mode in (3, 9, 0xC):
        return [u(mem("PC"), LDL, alu("A"), fl("STN"), hx("IMMH", "SXST")),
                u(rd(RSRC), alu("ADD"), lo, W, c)], parcels + 1
    if mode in (4, 0xE):
        base = SP if mode == 4 else G(14)
        return [u(imm("SC4"), LDL, W), u(rd(base), alu("ADD"), lo, W, c)], parcels
    if mode in (6, 0xA):
        return [u(rd(RSRC), alu("A"), lo, LDL, W, c),
                u(imm(CONST_N[size]), alu("ADD"), wr(RSRC), W)], parcels
    if mode == 7:
        return [u(imm(CONST_N[size]), LDL, W),
                u(rd(RSRC), alu("SUB"), lo, W, c),
                u(rd(RSRC), alu("SUB"), wr(RSRC), W)], parcels
    raise Unimplemented(f"mode {mode:X}")


def mem_operand(pre, size, parcels):
    stub = parcels if size > 1 else None
    if size == 4:
        return Operand(pre, u(mem("MAR", 4), ax(AX_MARINC)), 4, True, parcels, stub=stub)
    return Operand(pre, None, size, True, parcels, stub=stub)


def mode_operand(mode):
    if mode == 0:
        return Operand([], rd(RSRC))
    if mode == 1:
        return Operand([], imm("Q4"))
    if mode == 0xD:
        return Operand([], imm("NQ"))
    pre, parcels = ea_pre(mode)
    return mem_operand(pre, SIZE[mode], parcels)


def special_first():
    """Page 0's microinstruction for the special mode: the first extension
    parcel sign-extended into L and T_A, its sign in ST; the dispatch on s."""
    return u(mem("PC"), LDL, alu("A"), fl("STN"), wr(T_A), hx("IMMH", "SXST"), irn(IRN_NS),
             jump(0, page=1))


def special_operand(s):
    """Page 1's operand for the special mode's R = s; None where it traps."""
    if s == 0:
        return Operand([], rd(T_A), parcels=2, in_l=True)
    if s == 1:
        return Operand([u(rd(T_A), LDL, hx("IMMH", "ZERO"))], None, parcels=2, in_l=True)
    if s == 2:
        return Operand([u(rd(T_A, 1), LDL, W), u(imm("ZERO"), LDL)], None, parcels=2, in_l=True)
    if s == 3:
        return Operand([u(mem("PC"), alu("A"), wr(T_A, 1))], rd(T_A), parcels=3)
    size = {0: 4, 1: 1, 2: 2}[(s - 4) % 3] if 4 <= s <= 0xC else None
    if 4 <= s <= 6:
        return mem_operand([u(alu("B"), ax(AX_MARLO), W, chk(size))], size, 2)
    if 7 <= s <= 9:
        pre = [u(mem("PC"), alu("A"), wr(T_A, 1)), u(rd(T_A), alu("A"), ax(AX_MARLO), W, chk(size))]
        return mem_operand(pre, size, 3)
    if 0xA <= s <= 0xC:
        return mem_operand([u(pcrb(), alu("ADD"), ax(AX_MARLO), chk(size))], size, 2)
    return None


TABLES = (0xD, 0xE)


def table_first(s, page=2):
    """Page 1's part of the special mode's tables (R = D, E: an index parcel
    with the address's bits 23-16, then bits 15-0): the address (for E, from
    the next instruction's) into T_A, 0 into T_B, then the index parcel read
    again with IRN_IDX for page 2's indexed address, as the indexed mode's."""
    ops = [u(rd(T_A, 0), alu("A", rm=RM_SXB), wr(T_A, 1)),
           u(mem("PC"), alu("A"), wr(T_A, 0))]
    if s == 0xE:
        ops += [u(rd(T_A), LDL, W), u(pcrb(), alu("ADD"), wr(T_A))]
    return ops + [u(imm("ZERO"), alu("A"), wr(T_B), W),
                  u(imm("C4"), LDL, W),
                  u(pcrb(), alu("SUB"), ax(AX_MARLO), W),
                  u(mem("MAR", 2), alu("A"), irn(IRN_IDX), jump(0, page=page))]


def special_ea(s, dest):
    if 4 <= s <= 6:
        return [u(alu("B"), wr(dest), W)]
    if 7 <= s <= 9:
        return [u(mem("PC"), alu("A"), wr(T_A, 1)), u(rd(T_A), alu("A"), wr(dest), W)]
    if 0xA <= s <= 0xC:
        return [u(pcrb(), alu("ADD"), wr(dest))]
    return None


def index_first():
    """Page 0's part of the indexed mode: the base into T_A, the index
    parcel's d8 sign-extended into T_B, x into s, the dispatch on its scale
    and size."""
    return [u(rd(RSRC), alu("A"), wr(T_A), W),
            u(mem("PC"), alu("A", rm=RM_SXB), fl("STN"), wr(T_B), hx("FILL"), irn(IRN_IDX),
              jump(0, page=2))]


def index_ea(z, dest="MAR"):
    """Page 2's address: T_A + T_B + (x << scale), into MAR (checked) or dest;
    the access's size; None for the size that traps."""
    scale, size = z >> 2, z & 3
    if size == 3:
        return None
    size = {0: 1, 1: 2, 2: 4}[size]
    lo, c = (ax(AX_MARLO), chk(size)) if dest == "MAR" else (wr(dest), {})
    ops = [u(rd(T_B), LDL, W), u(rd(T_A), alu("ADD"), wr(T_A), W)]
    src = RSRC
    for _ in range(scale):
        ops.append(u(rd(src), alu("SHL"), wr(T_C), W))
        src = T_C
    ops += [u(rd(src), LDL, W), u(rd(T_A), alu("ADD"), lo, W, c)]
    return ops, size


# ---- consumers -----------------------------------------------------------

ALU_OPS = {     # name: (ALU operation, flags, writes rd)
    "ADD": ("ADD", "ADDLO", True), "SUB": ("SUB", "SUBLO", True), "CMP": ("SUB", "SUBLO", False),
    "AND": ("AND", "LOGLO", True), "OR": ("OR", "LOGLO", True), "XOR": ("XOR", "LOGLO", True),
    "BIC": ("BIC", "LOGLO", True), "TST": ("AND", "LOGLO", False),
    "ADC": ("ADDC", "ADCLO", True), "SBC": ("SUBC", "SBCLO", True),
}


def c_mov(opnd, flags=False, dest=RD):
    ops = list(opnd.pre)
    if opnd.memory and opnd.size == 1 and flags:
        # N and Z from the byte sign-extended, the value zero-extended
        ops += [u(mem("MAR", 1), alu("A", rm=RM_SXB), fl("NZ16"), LDL),
                u(alu("B"), wr(dest), hx("ZERO"))]
    elif opnd.memory and opnd.size < 4:
        f = fl("NZ16") if flags else {}
        ops.append(u(mem("MAR", opnd.size), alu("A", rm=RM_ZXB if opnd.size == 1 else 0),
                     wr(dest), hx("ZERO"), f))
    else:
        src = u(alu("B")) if opnd.in_l else u(opnd.val, alu("A"))
        ops.append(u(src, wr(dest), W, fl("LOGLO") if flags else {}))
    return with_stubs(finish(ops), opnd.stubs())


def c_alu(opnd, name):
    a, f, writes = ALU_OPS[name]
    ops = list(opnd.pre) + opnd.to_l()
    ops.append(u(rd(RD), alu(a), fl(f), wr(RD) if writes else {}, W))
    return with_stubs(finish(ops), opnd.stubs())


def c_store(pre, size, parcels):
    opnd = mem_operand(pre, size, parcels)
    ops = list(pre)
    if size == 4:
        ops.append(u(rd(RD), store(4), ax(AX_MARINC), W))
    else:
        ops.append(u(rd(RD), store(size)))
    return with_stubs(finish(ops), opnd.stubs())


def c_clr(pre, size, parcels):
    opnd = mem_operand(pre, size, parcels)
    ops = list(pre)
    if size == 4:
        ops.append(u(imm("ZERO"), store(4), ax(AX_MARINC), W))
    else:
        ops.append(u(imm("ZERO"), store(size)))
    return with_stubs(finish(ops), opnd.stubs())


def save_address(pre, reg):
    """pre with the address (the microinstruction loading MAR) written to reg too."""
    out = []
    for op in pre:
        if op.get("AXM") == AX_MARLO[1]:
            op = u(op, wr(reg))
        out.append(op)
    return out


def c_incdec(pre, size, parcels, dec):
    """INC or DEC on memory: read, add, write back; N and Z from the value."""
    opnd = mem_operand(pre, size, parcels)
    k = "CM1" if dec else "C1"
    if size == 4:
        ops = save_address(pre, T_B) + [
            u(mem("MAR", 4), ax(AX_MARINC), LDL, W),
            u(imm(k), alu("ADD"), fl("ICLOZ"), wr(T_A), W),
            u(rd(T_B), alu("A"), ax(AX_MARLO), W),
            u(rd(T_A), store(4), ax(AX_MARINC), W)]
    elif size == 2:
        ops = list(pre) + [u(mem("MAR", 2), LDL),
                           u(imm(k), alu("ADD"), fl("NZ16"), wr(T_A, 0)),
                           u(rd(T_A, 0), store(2))]
    else:
        ops = list(pre) + [u(mem("MAR", 1), LDL),
                           u(imm(k), alu("ADD"), wr(T_A, 0)),
                           u(rd(T_A, 0), store(1), alu("A", rm=RM_SXB), fl("NZ16"))]
    return with_stubs(finish(ops), opnd.stubs())


def c_jump(opnd, link, read=1):
    """PC <- the operand (CALL: r7 <- the next instruction's address, after
    the operand is read); an odd target traps (V_ADR) with PC at it. A byte
    or halfword operand is illegal, before its address is computed (`read`:
    the parcels read by then)."""
    if opnd.memory and opnd.size != 4:
        return illegal(read)
    ops = list(opnd.pre)
    if link:
        ops.append(u(pcrb(), alu("A"), wr(T_B)))
    src = u(alu("B")) if opnd.in_l else u(opnd.val, alu("A"))
    ops.append(u(src, ax(AX_PCLO), W, fl("STF0"), jump("_odd", "ST")))
    if link:
        ops.append(u(rd(T_B), alu("A"), wr(LINK), W))
    stubs = opnd.stubs()
    stubs["_odd"] = trap("V_ADR", 0)
    return with_stubs(finish(ops), stubs)


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
        if page == 0:
            if mode == 0xF:
                return [special_first()]
            if mode == 5:
                return index_first()
            pre, parcels = ea_pre(mode)
            return c_store(pre, SIZE[mode], parcels)
        if page == 1:
            if n in TABLES:
                return table_first(n)
            o = special_operand(n)
            if o is None or not o.memory:
                return illegal(2)
            return c_store(o.pre, o.size, o.parcels)
        ea = index_ea(n)
        parcels = 3 if mode == 0xF else 2
        if ea is None:
            return illegal(parcels)
        return c_store(ea[0], ea[1], parcels)
    if name == "MOVS" and mode in (1, 0xD):
        return illegal()                    # MFUR, MTUR
    if page == 0:
        if mode == 0xF:
            return [special_first()]
        if mode == 5:
            return index_first()
        return row_op(name, mode_operand(mode))
    if page == 1:
        if n in TABLES:
            return table_first(n)
        o = special_operand(n)
        if o is None:
            return illegal(2)
        return row_op(name, o)
    ea = index_ea(n)
    parcels = 3 if mode == 0xF else 2
    if ea is None:
        return illegal(parcels)
    return row_op(name, mem_operand(ea[0], ea[1], parcels))


MMODE = {0x20: "CLR", 0x21: "INC", 0x2D: "DEC", 0xF0: "JMP", 0xF1: "CALL"}


def gen_mmode(op, page, n):
    name = MMODE[op]
    if page == 0:
        m = n
        if m == 0xF:
            return [special_first()]
        if m == 5:
            return index_first()
        if name in ("JMP", "CALL"):
            return c_jump(mode_operand(m), name == "CALL", 1)
        if m in (1, 0xD):
            return illegal()
        if m == 0:
            if name == "CLR":
                return finish([u(alu("ZERO"), wr(RSRC), W)])
            return finish([u(rd(RSRC), alu("DEC" if name == "DEC" else "INC"), fl("ICLOZ"),
                             wr(RSRC), W)])
        pre, parcels = ea_pre(m)
        return mem_rmw(name, pre, SIZE[m], parcels)
    if page == 1:
        if n in TABLES:
            return table_first(n, page=4)
        o = special_operand(n)
        if o is None:
            return illegal(2)
        if name in ("JMP", "CALL"):
            return c_jump(o, name == "CALL", 2)
        if not o.memory:
            return illegal(2)
        return mem_rmw(name, o.pre, o.size, o.parcels)
    parcels = 3 if page == 4 else 2         # page 4: the tables', page 2 the indexed mode's
    ea = index_ea(n)
    if ea is None:
        return illegal(parcels)
    if name in ("JMP", "CALL"):
        return c_jump(mem_operand(ea[0], ea[1], parcels), name == "CALL", parcels)
    return mem_rmw(name, ea[0], ea[1], parcels)


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
        return finish(pre)
    if page == 1:
        if n in TABLES:
            return table_first(n)
        e = special_ea(n, RD)
        return illegal(2) if e is None else finish(e)
    ea = index_ea(n, dest=RD)
    return illegal(3 if mode == 0xF else 2) if ea is None else finish(ea[0])


def gen_u7(op, page, n):
    k = op & 7
    if op < 0x78:
        return finish([u(imm(f"U7_{k}"), alu("A"), wr(RD), W)])
    return c_alu(Operand([], imm(f"U7_{k}")), "CMP")


def link_ops():
    return [u(pcrb(), alu("A"), wr(LINK))]


# the branch conditions by cc: (condition, inverted)
CC = {0: ("Z", False), 1: ("Z", True), 2: ("C", False), 3: ("C", True), 4: ("N", False),
      5: ("N", True), 6: ("V", False), 7: ("V", True), 8: ("HI", False), 9: ("HI", True),
      0xA: ("LT", True), 0xB: ("LT", False), 0xC: ("LE", True), 0xD: ("LE", False)}


def gen_bcc(op, page, n):
    cc = op & 15
    first = u(imm("B8"), LDL, W)
    taken = [u(pcrb(), alu("ADD"), ax(AX_PCLO)), u(end())]
    if cc in (0xE, 0xF):
        return (link_ops() if cc == 0xF else []) + [first] + taken
    c, inv = CC[cc]
    return [u(first, jump("nt", c, not inv))] + taken + [label("nt"), u(end())]


def gen_jcc(op, page, n):
    """F2 Jcc rel16 (PC + 2 s16), F3 Jcc abs32; cc = d."""
    cc = n
    if op == 0xF2:
        ops = [u(mem("PC"), LDL, alu("A"), fl("STN"), hx("IMMH", "SXST"))]
    else:
        ops = [u(mem("PC"), alu("A"), wr(T_A), W)]
    if cc < 0xE:
        c, inv = CC[cc]
        ops[-1] = u(ops[-1], jump("nt", c, not inv))
    if cc == 0xF:
        ops += link_ops()
    if op == 0xF2:
        ops += [u(pcrb(), alu("ADD"), wr(T_A)), u(rd(T_A), alu("ADD"), ax(AX_PCLO), W)]
    else:
        ops += [u(rd(T_A), alu("A"), ax(AX_PCLO), W, fl("STF0"), jump("_odd", "ST"))]
    ops.append(u(end()))
    if cc < 0xE:
        ops += [label("nt"), u(end())]
    if op == 0xF3:
        ops += [label("_odd")] + trap("V_ADR", 0)
    return ops


def gen_shift(op, page, n):
    """Row C: LSL, LSR, ASR, ROR by n (page 1 knows n) or by rs. Up to six
    steps are unrolled; more loop on T_CNT."""
    kind = (op >> 2) & 3
    by_reg = (op & 3) == 2
    if (op & 3) == 3:
        return illegal()
    if not by_reg and page == 0:
        return [u(irn(IRN_NS), jump(0, page=1))]
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
    loop[-1] = u(loop[-1], jump("loop", "ST", True, task=True))
    ops += loop + nz32(RD)
    if by_reg:
        ops += [u(end()), u(rd(RD), alu("A"), fl("LOGLO"), W, label("done")),
                u(imm("ZERO"), alu("A"), fl("VNZ"))]
    return finish(merge_label(ops))


def shift1(kind):
    """rd shifted by one: C the bit out, V 0."""
    if kind == 0:
        return [u(rd(RD), alu("SHL"), fl("SHL"), wr(RD), W)]
    if kind in (1, 2):
        si = SI_D15 if kind == 2 else 0
        return [u(rd(RD, 1), alu("A", rm=RM_SHR, si=si), fl("SHR"), wr(RD, 1)),
                u(rd(RD, 0), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(RD, 0))]
    return [u(rd(RD, 0), alu("A", rm=RM_SHR), fl("SHR")),
            u(rd(RD, 1), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(RD, 1)),
            u(rd(RD, 0), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(RD, 0))]


def nz32(reg):
    return [u(rd(reg), alu("A"), fl("LOGLO"), W)]


def gen_unary(op, page, n):
    """Row D: rd <- f(rs)."""
    f = op & 15
    if f == 0:      # NOT
        return finish([u(rd(RSRC), alu("NOTA"), fl("LOGLO"), wr(RD), W)])
    if f == 1:      # NEG
        return finish([u(rd(RSRC), LDL, W), u(imm("ZERO"), alu("SUB"), fl("SUBLO"), wr(RD), W)])
    if f in (2, 3):  # INC, DEC
        return finish([u(rd(RSRC), alu("INC" if f == 2 else "DEC"), fl("ICLOZ"), wr(RD), W)])
    if f == 4:      # RLC
        return finish([u(rd(RSRC), alu("SHLC"), fl("SHL"), wr(RD), W)] + nz32(RD))
    if f == 5:      # RRC
        return finish([u(rd(RSRC, 1), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(RD, 1)),
                       u(rd(RSRC, 0), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(RD, 0))]
                      + nz32(RD))
    if f == 6:      # SWAP: the high half read first, into rd's low half
        return finish([u(rd(RSRC, 1), alu("A"), fl("LOGLO"), wr(RD, 0), W)])
    if f in (7, 8):     # SXB, SXH
        rm = RM_SXB if f == 7 else 0
        return finish([u(rd(RSRC, 0), alu("A", rm=rm), fl("STN"), wr(RD, 0), hx("FILL")),
                       u(rd(RD, 0), alu("A"), fl("NZ16"))])
    if f == 9:      # ZXB
        return finish([u(rd(RSRC, 0), alu("A", rm=RM_ZXB), fl("NZ16"), wr(RD, 0), hx("ZERO"))])
    if f == 0xA:    # ZXH
        return finish([u(rd(RSRC, 0), alu("A"), wr(RD, 0), hx("ZERO")),
                       u(rd(RD), alu("A"), fl("LOGLO"), W)])
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
            u(rd(T_CNT, 0), alu("A"), fl("NZ16"), wr(RD, 0), hx("ZERO"))])
    if f in (0xC, 0xD):
        return gen_ffs_popc(f)
    if f == 0xE:    # REV: each half zero-extended and shifted up 8, its bytes then apart
        return finish([u(rd(RSRC, 0), alu("A"), wr(T_A, 0), hx("ZERO")),
                       u(rd(RSRC, 1), alu("A"), wr(T_B, 0), hx("ZERO"))]
                      + [u(rd(t), alu("SHL"), wr(t), W) for _ in range(8) for t in (T_A, T_B)]
                      + [u(rd(T_A, 1), LDL),
                         u(rd(T_A, 0), alu("OR"), wr(RD, 1)),     # rd.hi: rs.lo's bytes swapped
                         u(rd(T_B, 1), LDL),
                         u(rd(T_B, 0), alu("OR"), wr(RD, 0))] + nz32(RD))
    if f == 0xF:    # SETcc rd: cc = s
        if page == 0:
            return [u(irn(IRN_NS), jump(0, page=1))]
        if n == 0xF:
            return illegal()
        if n == 0xE:
            return finish([u(imm("C1"), alu("A"), wr(RD), W)])
        c, inv = CC[n]
        return [u(jump("one", c, inv)),
                u(alu("ZERO"), wr(RD), W, end()),
                label("one"),
                u(imm("C1"), alu("A"), wr(RD), W, end())]
    raise Unimplemented(f"unary {op:02X}")


def gen_rowe(op, page, n):
    f = op & 15
    if f in (0, 1, 2, 3):
        return c_alu(mode_operand(0), ["ADC", "SBC", "BIC", "TST"][f])
    if f in (0xA, 0xB):
        if page == 0:
            return [special_first()]
        if page == 2:
            ea = index_ea(n)
            return illegal(3) if ea is None else c_alu(mem_operand(ea[0], ea[1], 3),
                                                        ["BIC", "TST"][f - 0xA])
        if n in TABLES:
            return table_first(n)
        o = special_operand(n)
        return illegal(2) if o is None else c_alu(o, ["BIC", "TST"][f - 0xA])
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
    if f in (0xC, 0xD):
        return gen_mul_special(op, page, n)
    if f == 0xE:
        return gen_merge(op, page, n)
    if f == 0xF:
        return illegal()
    raise Unimplemented(f"row E {op:02X}")


# ---- multiply and divide ---------------------------------------------------

def short_count(x, then, shift=False):
    """T_CNT <- 31, or 15 if x's high half is 0 (16 steps do); with shift,
    T_Q (x) moved up a half then, so that 16 steps of a divide see it all.
    `then`: the label that follows."""
    return [u(rd(x, 1), alu("A"), fl("STZ")),
            u(imm("C31"), alu("A"), wr(T_CNT, 0), jump(then, "ST", True)),
            u(imm("C16"), alu("DEC"), wr(T_CNT, 0))] + (
        [u(rd(T_Q, 0), alu("A"), wr(T_Q, 1)), u(imm("ZERO"), alu("A"), wr(T_Q, 0))]
        if shift else [])


def mul_loop(src, a=RD):
    """T_R:T_Q <- a * src, unsigned: shift and add, 32 steps, or 16 if a is
    under 2^16 (the count in T_CNT, its end in IC; src in L; a read again
    after the loop, since a task may change ST). Only C and V change, and
    IC."""
    return [u(rd(a), alu("A"), wr(T_Q), W),
            u(imm("ZERO"), alu("A"), wr(T_R), W),
            u(rd(src), LDL, W)] + short_count(a, "loop") + [
            label("loop"),
            u(rd(T_Q, 0), alu("A", rm=RM_SHR), fl("SHR")),                    # C <- the bit
            u(rd(T_CNT, 0), alu("DEC"), fl("ICLO"), wr(T_CNT, 0), jump("shift", "C", True)),
            u(rd(T_R), alu("ADD"), fl("SHL"), wr(T_R), W),                     # C <- the carry
            label("shift"),
            u(rd(T_R, 1), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(T_R, 1)),
            u(rd(T_R, 0), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(T_R, 0)),
            u(rd(T_Q, 1), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(T_Q, 1)),
            u(rd(T_Q, 0), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(T_Q, 0),
              jump("loop", "IC", task=True)),
            # 16 steps: the product is T_R:T_Q's bits 63-16
            u(rd(a, 1), alu("A"), fl("STZ")),
            u(jump("full", "ST", True)),
            u(rd(T_Q, 1), alu("A"), wr(T_Q, 0)),
            u(rd(T_R, 0), alu("A"), wr(T_Q, 1)),
            u(rd(T_R, 1), alu("A"), wr(T_R, 0)),
            u(imm("ZERO"), alu("A"), wr(T_R, 1)),
            label("full")]


def mul_result():
    """rd <- T_Q, N and Z from it: the last write, so that rd wins over r0."""
    return [u(rd(T_Q), alu("A"), fl("LOGLO"), wr(RD), W)]


def r0_nonzero_cv():
    """C = V = T_R isn't 0 (T_R.lo in L)."""
    return [u(rd(T_R, 1), alu("OR"), fl("CNZ")), u(rd(T_R, 1), alu("OR"), fl("VNZ"))]


def mulu(src, pre=()):
    """r0:rd <- rd * src, unsigned. N and Z from rd, C = V = r0 isn't 0."""
    ops = list(pre) + mul_loop(src) + [u(rd(T_R), alu("A"), wr(G(0)), W),
                           u(rd(T_R, 0), LDL)] + r0_nonzero_cv() + mul_result()
    return finish(ops)


def flags_bits(src_l_ops, which):
    """Each flag in `which` <- its bit of the flags word in L."""
    bits = {"V": ("C1", "VNZ"), "C": ("C2", "CNZ"), "Z": ("C4", "ZNZ"), "N": ("C8", "NNZ"),
            "I": ("C16", "INZ"), "B": ("C32", "BNZ"), "BI": ("C64", "BINZ")}
    return src_l_ops + [u(imm(bits[k][0]), alu("AND"), fl(bits[k][1])) for k in which]


def mula(page):
    """MULA r0:r1, rd, rs: r0:r1 <- r0:r1 + rd * rs, signed; the flags stay
    (put back from T_FW)."""
    if page == 0:
        return [u(FLW, alu("A"), wr(T_FW), hx("ZERO"))] + signed_product()
    if page == 1:
        ops = less(RD, "c") + [label("c"),
                               u(rd(T_Q), LDL, W),
                               u(rd(G(1)), alu("ADD"), fl("SHL"), wr(G(1)), W),
                               u(rd(T_R), LDL, W),
                               u(rd(G(0)), alu("ADDC"), wr(G(0)), W)]
        ops += flags_bits([u(rd(T_FW, 0), LDL)], ("V", "C", "Z"))
        return finish(ops)
    return []


def neg_into(dst, x, skip=None):
    """dst <- 0 - x (if skip: or on to it if ST isn't set)."""
    return [u(rd(x), LDL, W, jump(skip, "ST", True) if skip else {}),
            u(imm("ZERO"), alu("SUB"), wr(dst), W)]


def less(x, skip):
    """T_R <- T_R - x if ST, else to `skip`."""
    return [u(rd(x), LDL, W, jump(skip, "ST", True)),
            u(rd(T_R), alu("SUB"), wr(T_R), W)]


def signed_product(a=RD, b=RSRC):
    """T_R:T_Q <- a * b, signed, as page 0's part: the unsigned product, its
    high half less b if a is negative; then ST <- b's sign and on to page 1,
    which takes a off if b is negative (less(a, ...))."""
    return (mul_loop(b, a) + [u(rd(a, 1), alu("A"), fl("STN"))] + less(b, "b")
            + [label("b"), u(rd(b, 1), alu("A"), fl("STN"), jump(0, page=1))])


def gen_mulfx(op, page, n):
    """FD 00 MULFX r0:rd, rs, #n (the extension parcel: rd, rs, 000, n)."""
    if page == 0:
        if n != 0:
            return illegal(1)
        return [u(jump("bad", "NE")),
                u(mem("PC"), alu("A"), wr(T_C, 0), irn(IRN_IDX), jump(0, page=2)),
                label("bad")] + illegal(1)
    if page == 2:
        ops = signed_product(RSRC, G(n))
        ops[-1] = u({k: v for k, v in ops[-1].items() if k not in ("SEQ", "CND", "_goto", "_page")})
        return ops + less(RSRC, "c") + [label("c"), u(imm("C31"), LDL, jump(0, page=1))]
    ops = [u(rd(T_C, 0), alu("AND"), wr(T_CNT, 0)),                       # n
           u(rd(T_C, 0), alu("A", rm=RM_ZXB), wr(T_C, 0)),
           u(rd(T_CNT, 0), LDL),
           u(rd(T_C, 0), alu("XOR"), fl("STZ")),                           # bits 7-5 clear
           u(rd(T_CNT, 0), alu("A"), fl("STZ"), jump("_trap", "ST", True)),
           u(rd(T_R), alu("A"), wr(G(0)), W),
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
           u(rd(T_Q), alu("A"), fl("LOGLO"), wr(RSRC), W, end())]
    return ops + [label("_trap")] + illegal(2)


def muls(page, b=RSRC):
    """MULS r0:rd, rs: signed_product, then the flags (C = V = r0 isn't rd's
    sign extension)."""
    if page == 0:
        return signed_product()
    if page == 1:
        ops = less(RD, "c") + [
            label("c"),
            u(rd(T_Q, 1), alu("A"), fl("STN")),                            # ST <- rd's new sign
            u(rd(T_R), alu("A"), wr(G(0)), W),
            u(rd(T_R, 0), LDL, jump("neg", "ST")),
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
    """rem:T_Q / src, restoring, T_CNT + 1 steps (src in L, the count's end
    in IC; 16 with T_Q moved up, for a dividend under 2^16):
    T_Q the quotient, rem the remainder (T_A a scratch)."""
    return [label("loop"),
            u(rd(T_CNT, 0), alu("DEC"), fl("ICLO"), wr(T_CNT, 0)),
            u(rd(T_Q), alu("SHL"), fl("SHL"), wr(T_Q), W),
            u(rd(rem), alu("SHLC"), fl("SHL"), wr(rem), W),
            u(fl("STC")),                                           # ST <- the bit out of rem
            u(rd(rem), alu("SUB"), fl("SUBLO"), wr(T_A), W, jump("take", "ST")),
            u(jump("next", "C", True)),
            label("take"),
            u(rd(T_A), alu("A"), wr(rem), W),
            u(rd(T_Q, 0), alu("INC"), wr(T_Q, 0), jump("loop", "IC", task=True)),
            label("next"),
            u(jump("loop", "IC", task=True))]


def divs(page):
    """DIVS r0:rd, rs: the magnitudes' unsigned divide, the remainder taking
    rd's sign and the quotient negated if the signs differ (page 0 the
    magnitudes, page 1 the loop, page 2 the signs and the flags)."""
    if page == 0:
        ops = [u(rd(RSRC, 0), LDL),
               u(rd(RSRC, 1), alu("OR"), fl("STZ")),
               u(rd(RSRC, 1), alu("A"), fl("STN"), jump("_trap", "ST")),
               u(rd(RSRC), alu("A"), wr(T_B), W, jump("bpos", "ST", True))]
        ops += neg_into(T_B, RSRC) + [
            label("bpos"),
            u(rd(RD, 1), alu("A"), fl("STN")),
            u(rd(RD), alu("A"), wr(T_Q), W, jump("apos", "ST", True))]
        ops += neg_into(T_Q, RD) + [
            label("apos"),
            u(imm("ZERO"), alu("A"), wr(T_R), W),
            u(rd(T_B), LDL, W)] + short_count(T_Q, "go", shift=True) + [
            label("go"),
            u(jump(0, page=1))]
        return ops + [label("_trap")] + trap("V_DIV", 1)
    if page == 1:
        return div_loop(T_B, T_R) + [u(jump(0, page=2))]
    ops = [u(rd(RD, 1), alu("A"), fl("STN"))]
    ops += neg_into(T_R, T_R, "rpos") + [
        label("rpos"),
        u(rd(RD, 1), LDL),
        u(rd(RSRC, 1), alu("XOR"), fl("STN")),                             # the signs differ
        u(jump("qpos", "ST", True))]
    ops += neg_into(T_Q, T_Q) + [
        u(alu("ZERO"), fl("SHR"), jump("fin")),                            # C = V = 0
        label("qpos"),
        u(rd(T_Q, 1), alu("A"), fl("STN")),
        u(alu("ZERO"), fl("SHR"), jump("fin", "ST", True)),
        u(imm("C1"), alu("A"), fl("VNZ")),                                 # the quotient 2^31
        label("fin"),
        u(rd(T_R), alu("A"), wr(G(0)), W)] + mul_result()
    return finish(ops)


def divu(src, long):
    """DIVU r0:rd, rs: rd <- rd / rs, r0 <- the remainder; DIVUL: r0:rd / rs.
    Dividing by zero is a divide error; DIVUL with r0 >= rs sets V and
    changes nothing."""
    rem = G(0) if long else T_R
    ops = [u(rd(src, 0), LDL),
           u(rd(src, 1), alu("OR"), fl("STZ")),
           u(rd(RD), alu("A"), wr(T_Q), W, jump("_trap", "ST"))]
    if long:
        # r0 >= rs: IC, no borrow (the flags stay)
        ops += [u(rd(src, 0), LDL), u(rd(G(0), 0), alu("SUB"), fl("ICLO")),
                u(rd(src, 1), LDL), u(rd(G(0), 1), alu("SUBI"), fl("ICLO")),
                u(rd(src), LDL, W),
                u(imm("C31"), alu("A"), wr(T_CNT, 0), jump("ovf", "IC"))]
    else:
        ops += [u(rd(src), LDL, W),
                u(imm("ZERO"), alu("A"), wr(T_R), W)] + short_count(T_Q, "loop", shift=True)
    ops += div_loop(src, rem)
    if not long:
        ops += [u(rd(T_R), alu("A"), wr(G(0)), W)]
    ops += [u(rd(T_Q), alu("A"), fl("LOGLO"), wr(RD), W),
            u(alu("ZERO"), fl("SHR"), end())]
    if long:
        ops += [label("ovf"), u(imm("CM1"), alu("A"), fl("VNZ"), end())]
    return ops + [label("_trap")] + trap("V_DIV", 1)


# ---- the rest ----------------------------------------------------------------

def gen_save(op, page, n):
    """F4 SAVE ra-rb: from rb down, each pushed (s counts down to d);
    F5 RESTORE ra-rb: from [sp] up into ra..rb (d counts up to s). Each
    register a task point: MAR comes from sp again after it."""
    check = u(rd(SP), alu("A"), W, chk(4))
    if op == 0xF4:
        ops = [u(imm("C4"), LDL, W), check,
               label("loop"),
               u(rd(SP), alu("SUB"), wr(SP), ax(AX_MARLO), W),
               u(rd(RSRC), store(4), ax(AX_MARINC), W, irn(IRN_DECS), jump("loop", "NE", task=True)),
               u(end())]
    else:
        ops = [u(imm("C4"), LDL, W), check,
               label("loop"),
               u(rd(SP), alu("A"), ax(AX_MARLO), W),
               u(mem("MAR", 4), alu("A"), wr(RD), ax(AX_MARINC), W),
               u(rd(SP), alu("ADD"), wr(SP), W, irn(IRN_INCD), jump("loop", "NE", task=True)),
               u(end())]
    return ops + [label("_trap")] + trap("V_ADR", 1)


def gen_dbnz(op, page, n):
    """DBNZ r, back k: r = d, k - 1 = s. No flag changes."""
    return [u(imm("DB"), LDL, W),
            u(rd(RD), alu("DEC"), fl("ICSTZ"), wr(RD), W),
            u(pcrb(), alu("ADD"), wr(T_A), jump("nt", "ST")),
            u(rd(T_A), alu("A"), ax(AX_PCLO), W),
            u(end()),
            label("nt"),
            u(end())]


def gen_system(op, page, n):
    """FE: EI, DI, RTI, HALT (second byte 00-03)."""
    if page == 0:
        if n != 0:
            return illegal()
        return [u(irn(IRN_NS), jump(0, page=1))]
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
                u(jump("halt", page=3)),
                label("stop"),                  # stopped; the halt button takes it to ODT
                u({"HALT": 1}, jump("stop", "ODT", True)),
                u(jump("halt", page=3))]
    return illegal()


FLAGS_ALL = ("V", "C", "Z", "N", "I", "BI", "B")


def rti():
    """Pop the flags word, then PC; sp moves on in the bank it's in, then B
    (and BI) change with the other flags."""
    ops = [u(rd(SP), alu("A"), ax(AX_MARLO), W, chk(4)),
           u(mem("MAR", 4), alu("A"), wr(T_FW), ax(AX_MARINC), W),
           u(mem("MAR", 4), alu("A"), ax(AX_PCLO), ax(AX_MARINC), W, fl("STF0"),
             jump("_odd", "ST")),
           u(imm("C8"), LDL, W),
           u(rd(SP), alu("ADD"), wr(SP), W)]
    ops = flags_bits(ops + [u(rd(T_FW, 0), LDL)], FLAGS_ALL)
    return finish(ops) + [label("_trap")] + trap("V_ADR", 1) + [label("_odd")] + trap("V_ADR", 0)


def gen_flags_sr(op, page, n):
    """06 MFSR rd, n (n = 0, the flags word); 07 MTSR n, rs (n = d)."""
    if op == 0x06:
        if page == 0:
            return [u(irn(IRN_NS), jump(0, page=1))]
        if n != 0:
            return illegal()
        return finish([u(FLW, alu("A"), wr(RD), hx("ZERO"))])
    if n != 0:
        return illegal()
    return finish(flags_bits([u(rd(RSRC, 0), LDL)], FLAGS_ALL))


def gen_swi(op, page, n):
    return trap("V_SWI", 0)


def page3():
    """The interrupt's entry and reset's (µPC 0x000-0x0FF; at an instruction's end PC is past the
    next instruction's first parcel), HALT's wait's end, an exception's
    entry (T_VEC and T_RET set), ODT's entry (from HALT's wait too, PC
    past it) and reset."""
    return [
        u(jump("reset", "INIT", True)),                                  # 0
        u(jump("odt", "ODT")),
        u(imm("IOIV"), alu("A"), ax(AX_MARLO), W),                       # the controller's vector
        u(mem("MAR", 1), alu("A", rm=RM_ZXB), wr(T_VEC), hx("ZERO")),    # MD7-0
        u(imm("C2"), LDL, W),
        u(pcrb(), alu("SUB"), wr(T_RET), jump("exc")),
        label("halt"),
        u(pcrb(), alu("A"), wr(T_RET), jump("odt2", "ODT")),           # (ODT asked for)
        u(imm("IOIV"), alu("A"), ax(AX_MARLO), W),
        u(mem("MAR", 1), alu("A", rm=RM_ZXB), wr(T_VEC), hx("ZERO")),    # MD7-0
        label("exc"),
        u(FLW, alu("A"), wr(T_FW), hx("ZERO")),                         # before the entry's I and B
        u(fl("ENTRY")),
        u(imm("C8"), LDL, W),
        u(rd(SP), alu("SUB"), wr(SP), ax(AX_MARLO), W),                  # sp in the bank now
        u(rd(T_FW), store(4), ax(AX_MARINC), W),
        u(rd(T_RET), store(4), ax(AX_MARINC), W),
        u(rd(T_VEC), alu("A"), ax(AX_PCLO), W),
        u(end()),
        label("odt"),
        u(imm("C2"), LDL, W),
        u(pcrb(), alu("SUB"), wr(T_RET)),
        label("odt2"),
        # ODT's word at the controller's +4 loads d and s (9 and 0, as
        # odt.py wants them); then its routine
        u(imm("C2"), LDL, W),
        u(imm("IOIV"), alu("ADD"), ax(AX_MARLO), wr(odt.T_IO4), W),
        u({"MOP": MOP_LDIRM}, jump("entry", routine="odt")),
        label("reset"),
        u(fl("SETINIT"), jump(0, routine="uart_init")),
    ]


COPPTR = 0x60       # the copper's place in its list: a word in RAM


def copper():
    """The copper: a task (at ucode2.TASK_BASE) while the scanline
    is the copper's target line (COPREQ). Its list goes on from the word at
    COPPTR, which it moves on, of entries:

        MOVE  an I/O address (bit 31 set: 0xFFFF_xxxx), then the word whose low half is
              written there
        WAIT  bits 31 and 30 clear: its low half (CEN, bit 15, and the line)
              written at the controller's +6; the task ends
        JUMP  bit 31 clear, 30 set: the list goes on at the word's address
              (its bits 20-0)

    A task's registers are its own bank's; it uses ST, and L, put back."""
    TL, TP, TX, TV = T_A, T_B, T_C, T_Q
    return [u(alu("B"), wr(TL), W),                                 # L
            u(imm("C64"), LDL, W),
            u(imm("C32"), alu("ADD"), ax(AX_MARLO), W),               # COPPTR
            u(mem("MAR", 4), alu("A"), wr(TP), ax(AX_MARINC), W),
            u(imm("C4"), LDL, W),
            label("loop"),
            u(rd(TP), alu("A"), ax(AX_MARLO), W),
            u(mem("MAR", 4), alu("A"), wr(TX), ax(AX_MARINC), W),
            u(rd(TP), alu("ADD"), wr(TP), W),
            u(rd(TX, 1), alu("A"), fl("STN")),                        # ST: a MOVE
            u(rd(TX, 1), alu("SHL"), fl("STN"), jump("move", "ST")),  # ST: a JUMP
            u(jump("jmp", "ST")),
            u(imm("IOIV"), alu("ADD"), ax(AX_MARLO), W),              # +6
            u(rd(TX, 0), store(2)),
            u(imm("C64"), LDL, W),
            u(imm("C32"), alu("ADD"), ax(AX_MARLO), W),
            u(rd(TP), store(4), ax(AX_MARINC), W),
            u(rd(TL), LDL, W, {"SEQ": SEQ_END}),
            label("move"),
            u(mem("MAR", 4), alu("A"), wr(TV), ax(AX_MARINC), W),
            u(rd(TP), alu("ADD"), wr(TP), W),
            u(rd(TX), alu("A"), ax(AX_MARLO), W),
            u(rd(TV, 0), store(2), jump("loop")),
            label("jmp"),                                             # bit 30 off: RAM
            u(imm("C31"), LDL),
            u(rd(TX, 1), alu("AND"), wr(TP, 1)),
            u(rd(TX, 0), alu("A"), wr(TP, 0)),
            u(imm("C4"), LDL, W, jump("loop"))]


BOOT_MAGIC = 0x1F


def uart_init():
    """Reset's first part: UART 0 to 115200
    baud (the divisor 1), 8N1, its FIFOs on, DTR and RTS: ODT's console
    until a program changes it."""
    return [u(imm("C2"), LDL, W),
            u(imm("IOU0"), alu("ADD"), wr(T_A), ax(AX_MARLO), W),  # 0xFFFF_E002: DLM's
            u(imm("C64"), LDL),
            u(imm("C64"), alu("ADD"), wr(T_C, 0)),             # DLAB
            u(imm("C4"), LDL, W),
            u(rd(T_A), alu("ADD"), wr(T_B), ax(AX_MARLO), W),  # +6: LCR
            u(rd(T_C, 0), store(1)),
            u(rd(T_A), alu("A"), ax(AX_MARLO), W),
            u(imm("ZERO"), store(1)),                          # DLM
            u(imm("C2"), LDL, W),
            u(rd(T_A), alu("SUB"), ax(AX_MARLO), W),
            u(imm("C1"), store(1)),                            # DLL
            u(rd(T_B), alu("A"), ax(AX_MARLO), W),
            u(imm("U7_3"), store(1)),                          # LCR: 8N1
            u(rd(T_B), alu("ADD"), ax(AX_MARLO), W),
            u(imm("U7_3"), store(1)),                          # MCR: DTR and RTS
            u(rd(T_A), alu("ADD"), ax(AX_MARLO), W),
            u(imm("U7_7"), store(1), jump(0, routine="boot"))]  # FCR: the FIFOs, emptied


def boot():
    """Reset's second part: if the boot flash's byte 0 is BOOT_MAGIC, copy byte 1's count of
    256-byte pages from its byte 2 on into RAM at 0; then enter the program
    at 0. The flash's byte n is at 0xFFE0_0000 + 2n."""
    return [u(imm("IOFL"), alu("A"), wr(T_A), ax(AX_MARLO), W),
            u(imm("C31"), LDL),
            u(mem("MAR", 1), alu("XOR"), fl("STZ"), ax(AX_MARINC)),     # ST: the magic's there
            u(mem("MAR", 1), alu("A"), wr(T_CNT, 0), jump("enter", "ST", True)),
            u(imm("C4"), LDL, W),
            u(rd(T_A), alu("ADD"), wr(T_A), W),                # the flash's byte 2
            u(imm("ZERO"), alu("A"), wr(T_B), W),              # RAM's 0
            u(imm("C2"), LDL, W),
            label("loop"),
            u(rd(T_A), alu("A"), ax(AX_MARLO), W),
            u(mem("MAR", 1), alu("A"), wr(T_C, 0)),
            u(rd(T_B), alu("A"), ax(AX_MARLO), W),
            u(rd(T_C, 0), store(1)),
            u(rd(T_B), alu("INC"), wr(T_B), W),
            u(rd(T_B, 0), alu("A", rm=RM_ZXB), fl("STZ")),     # ST: a page's end
            u(rd(T_A), alu("ADD"), wr(T_A), W, jump("loop", "ST", True)),
            u(rd(T_CNT, 0), alu("DEC"), fl("STZ"), wr(T_CNT, 0)),
            u(jump("loop", "ST", True)),
            label("enter"),
            u(imm("ZERO"), alu("A"), ax(AX_PCLO), W),
            u(end())]


# ---- the instructions the first cut hadn't ---------------------------------

SMALL = {0: "ZERO", 1: "C1", 2: "C2", 4: "C4", 6: "C6", 8: "C8", 12: "V_SWI", 16: "C16"}


def const_into(reg, v):
    """reg's low half <- v (0-15), from the immediates' constants."""
    if v in SMALL:
        return [u(imm(SMALL[v]), alu("A"), wr(reg, 0))]
    for x in SMALL:
        for y in SMALL:
            if x and y and x + y == v:
                return [u(imm(SMALL[y]), LDL), u(imm(SMALL[x]), alu("ADD"), wr(reg, 0))]
            if x and y and x - y == v:
                return [u(imm(SMALL[y]), LDL), u(imm(SMALL[x]), alu("SUB"), wr(reg, 0))]
    raise ValueError(v)


def gen_ldm(op, page, n):
    """01 LDM rb, ra-rc and 02 STM: ra in d, rb in s, rc the extension
    parcel's top nibble (its other bits 0, rc >= ra). Page 0 (N = ra) puts
    ra in T_C and the base in T_A and reads the extension (s <- rc, N <- its
    bits 11-8: page 2's block); page 2 checks it and the base's alignment,
    then a microinstruction a register."""
    if page == 0:
        return const_into(T_C, n) + [
            u(rd(RSRC), alu("A"), wr(T_A), W),
            u(mem("PC"), alu("A", rm=RM_ZXB), fl("STZ"), irn(IRN_IDX), jump(0, page=2))]
    if page != 2:
        return []
    if n != 0:
        return illegal(2)
    if op == 0x01:
        step = u(mem("MAR", 4), alu("A"), wr(RD), ax(AX_MARINC), W, irn(IRN_INCD),
                 jump("loop", "NE"))
    else:
        step = u(rd(RD), store(4), ax(AX_MARINC), W, irn(IRN_INCD), jump("loop", "NE"))
    return [u(jump("bad", "ST", True)),                     # bits 7-0 aren't 0
            u(rd(T_C, 0), LDL),
            u(imm("Q4"), alu("SUB"), fl("STN")),            # ST: rc < ra
            u(jump("bad", "ST")),
            u(rd(T_A), alu("A"), ax(AX_MARLO), W, chk(4)),
            u(step, label("loop")),
            u(end()),
            label("bad")] + illegal(2) + [label("_trap")] + trap("V_ADR", 2)


def gen_addb4(op, page, n):
    """08 ADD.B4 rd, rs: the four bytes added apart: (rd & M) + (rs & M),
    with (rd ^ rs) & ~M on top, M = 0x7F7F7F7F (built in T_C); N and Z."""
    return finish([
        u(imm("C64"), LDL),
        u(imm("C64"), alu("ADD"), wr(T_C, 0)),
        u(rd(T_C, 0), alu("DEC"), wr(T_C, 0)),          # 0x7F
        u(rd(T_C, 0), alu("A"), wr(T_B, 0))]
        + [u(rd(T_B, 0), alu("SHL"), wr(T_B, 0))] * 8 + [    # 0x7F00
        u(rd(T_B, 0), LDL),
        u(rd(T_C, 0), alu("OR"), wr(T_C, 0)),           # 0x7F7F
        u(rd(T_C, 0), alu("A"), wr(T_C, 1)),
        u(rd(T_C), LDL, W),
        u(rd(RD), alu("AND"), wr(T_A), W),
        u(rd(RSRC), alu("AND"), wr(T_B), W),
        u(rd(T_B), LDL, W),
        u(rd(T_A), alu("ADD"), wr(T_A), W),
        u(rd(RSRC), LDL, W),
        u(rd(RD), alu("XOR"), wr(T_B), W),
        u(rd(T_C), LDL, W),
        u(rd(T_B), alu("BIC"), wr(T_B), W),
        u(rd(T_B), LDL, W),
        u(rd(T_A), alu("XOR"), fl("LOGLO"), wr(RD), W)])


TAGGED = {9: "MOV", 0xA: "TST", 0xB: "ADD", 0xC: "SUB", 0xD: "CMP"}


def gen_tagged(op, page, n):
    """09-0D TMOV TTST TADD TSUB TCMP rd, rs: a tag check (bit 0 of rs, or of
    rd | rs) and, for TADD and TSUB, an overflow check first; either traps
    (V_TAG, the instruction unwound) with nothing changed."""
    name = TAGGED[op]
    if name == "MOV":
        ops = [u(rd(RSRC), alu("A"), fl("STF0"), W, jump("_tag", "ST")),
               u(rd(RSRC), alu("A"), wr(RD), W)]
        return finish(ops) + [label("_tag")] + trap("V_TAG", 1)
    ops = [u(rd(RSRC), LDL, W),
           u(rd(RD), alu("OR"), fl("STF0"), W, jump("_tag", "ST"))]
    if name in ("ADD", "SUB"):
        a = "ADD" if name == "ADD" else "SUB"
        ops += [u(rd(RD), alu(a), wr(T_A), W),               # r, flags unchanged
                u(rd(T_A), LDL, W),
                u(rd(RD), alu("XOR"), wr(T_B), W)]          # a ^ r
        if name == "ADD":
            ops.append(u(rd(RSRC), alu("XOR"), wr(T_C), W))  # b ^ r
        else:
            ops += [u(rd(RSRC), LDL, W), u(rd(RD), alu("XOR"), wr(T_C), W)]     # a ^ b
        ops += [u(rd(T_C, 1), LDL),
                u(rd(T_B, 1), alu("AND"), fl("STN")),         # ST: the overflow
                u(rd(RSRC), LDL, W, jump("_tag", "ST"))]
    a, f, writes = ALU_OPS[name]
    ops.append(u(rd(RD), alu(a), fl(f), wr(RD) if writes else {}, W))
    return finish(ops) + [label("_tag")] + trap("V_TAG", 1)


def keep_cv(ops):
    """ops with C and V as they were: saved in T_FW first, put back after."""
    return [u(FLW, alu("A"), wr(T_FW), hx("ZERO"))] + ops + \
        flags_bits([u(rd(T_FW, 0), LDL)], ("V", "C"))


def shr32(reg):
    return [u(rd(reg, 1), alu("A", rm=RM_SHR), fl("SHR"), wr(reg, 1)),
            u(rd(reg, 0), alu("A", rm=RM_SHR, si=SI_C), fl("SHR"), wr(reg, 0))]


def gen_ffs_popc(f):
    """DC FFS rd, rs (the trailing zeros, 32 for 0), DD POPC (the ones): N
    and Z from the count."""
    if f == 0xC:
        body = [u(rd(RSRC), alu("A"), fl("STZ"), wr(T_A), W),
                u(imm("C32"), alu("A"), wr(T_CNT, 0), jump("done", "ST")),
                u(imm("ZERO"), alu("A"), wr(T_CNT, 0)),
                u(rd(T_A, 0), alu("A"), fl("STF0"), label("loop")),
                u(jump("done", "ST"))] + shr32(T_A) + [
                u(rd(T_CNT, 0), alu("INC"), wr(T_CNT, 0), jump("loop"))]
    else:
        body = [u(rd(RSRC), alu("A"), fl("STZ"), wr(T_A), W),
                u(imm("ZERO"), alu("A"), wr(T_CNT, 0), jump("done", "ST"))]
        body += [u(shr32(T_A)[0], label("loop")), shr32(T_A)[1],
                 u(rd(T_CNT, 0), alu("INCC"), wr(T_CNT, 0)),
                 u(rd(T_A), alu("A"), fl("STZ"), W),
                 u(jump("loop", "ST", True))]
    ops = keep_cv(body + [u(rd(T_CNT, 0), alu("A"), wr(T_CNT, 0), label("done"))])
    return finish(merge_label(ops + [u(rd(T_CNT, 0), alu("A"), fl("NZ16"), wr(RD, 0),
                                       hx("ZERO"))]))


def operand_into(o, reg):
    """The special mode's operand into reg, 32 bits."""
    ops = list(o.pre)
    if o.memory and o.size < 4:
        ops.append(u(mem("MAR", o.size), alu("A", rm=RM_ZXB if o.size == 1 else 0), wr(reg),
                     hx("ZERO")))
    elif o.in_l:
        ops.append(u(alu("B"), wr(reg), W))
    else:
        ops.append(u(o.val, alu("A"), wr(reg), W))
    return ops


def gen_mul_special(op, page, n):
    """EC MULU r0:rd, (the special mode's operand), ED MULS: the operand into
    T_B on page 1, then MULU's or MULS's routine on it (MULS's second part on
    page 2, its N still R)."""
    if page == 0:
        return [special_first()]
    if page == 1 and n in TABLES:
        return table_first(n, page=4)
    if page in (1, 4):
        if page == 4:
            ea = index_ea(n)
            o = None if ea is None else mem_operand(ea[0], ea[1], 3)
        else:
            o = special_operand(n)
        if o is None:
            return illegal(3 if page == 4 else 2)
        pre = operand_into(o, T_B)
        if op == 0xEC:
            return with_stubs(mulu(T_B, pre), o.stubs())
        ops = signed_product(RD, T_B)
        ops[-1] = u({k: v for k, v in ops[-1].items() if k not in ("_page",)}, _page=2)
        return with_stubs(pre + ops, o.stubs())
    if op == 0xED:
        return muls(1, b=T_B)
    return []


def gen_merge(op, page, n):
    """EE MERGE rd, rs: rd <- (rd & ~r0) | (rs & r0); N and Z."""
    return finish([u(rd(G(0)), LDL, W),
                   u(rd(RSRC), alu("AND"), wr(T_A), W),
                   u(rd(RD), alu("BIC"), wr(T_B), W),
                   u(rd(T_A), LDL, W),
                   u(rd(T_B), alu("OR"), fl("LOGLO"), wr(RD), W)])


# ---- the decode ------------------------------------------------------------

def routine(page, n, op):
    """The block of (page, N, opcode) (flat.py's)."""
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
    if op in (0x01, 0x02):
        return gen_ldm(op, page, n)
    if op == 0x08:
        return gen_addb4(op, page, n)
    if 0x09 <= op <= 0x0D:
        return gen_tagged(op, page, n)
    if op in (0x00, 0xFF, 0xC3, 0xC7, 0xCB, 0xCF, 0xEF, 0xF7, 0xF8, 0xF9, 0xFA, 0xFB):
        return illegal()
    raise Unimplemented(f"{op:02X}")


# ---- the control store ---------------------------------------------------

ROUTINES = {"p3": lambda: page3_ops(), "copper": lambda: copper(), "uart_init": lambda: uart_init(),
            "boot": lambda: boot(), "odt": lambda: odt.routine()}


def ControlStore(ticks=None):
    """The flat store (flat.py), its lengths from the timing analysis's
    table (`ticks`, ticks.json's by default)."""
    from . import flat
    return flat.ControlStore(routine, ROUTINES, load_ticks() if ticks is None else ticks)


def load_ticks():
    """The timing analysis's table: {(word, two halves): (low ticks, high
    ticks)} (sta2.py writes it)."""
    import json
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ticks.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        rows = json.load(f)
    return {(int(w, 16), bool(two)): (lo, hi) for w, two, lo, hi in rows}


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
