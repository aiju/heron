"""Draft 1b on the draft 2 CPU, unmodified: the previous draft's binaries,
by microcode only.

1b's instructions are 16-bit parcels at even addresses, little-endian, as
draft 2's are, so the native fetch and decode work. Its main format is
`F D M R`: operation in IR[15:12], register in IR[11:8], mode in IR[7:4]
and the mode's register (or constant) in IR[3:0]. Draft 2 addresses the
register file by IR[15:12] or IR[11:8]:

- 1b's register `d` is draft 2's `r` selector (IR[11:8]): it is read and
  written as it is.
- The mode and the mode's register are seen only by the decode table, so
  the routines are specialised on them: one routine per operation, mode
  and register (`R` a constant of the routine), which is what fills the
  control store (see `heron v2_guests ucode v1b`).
- r0 reads as 0 (location 0 is kept 0); a write to it (d = 0) is a routine
  of its own that leaves the write out.
- The flags are the CPU's own: 1b's N, Z, C, V have draft 2's sense
  (ADC's and SBC's sticky Z included); I is the CPU's I, so interrupts
  work as on the hardware. 1b's flags word is the CPU's bits 4-0.
- SETcc's condition is in IR[7:4], where the branch-condition logic
  doesn't look: a table in the register file (the bank the flags byte
  names, location 17 + cc) gives the answer in two cycles.

Calls push the return address on the stack (1b has no link register);
interrupts and traps push the PC and the flags word and jump through
1b's vectors at 0 (reset 0, IRQ 4, illegal 8, SWI C, divide 10, address
14). HI is location 16.
"""

from heron.studies.v2_hw import ucode as uc
from heron.studies.v2_hw.ucode import mi, merge, chain, branch, loop, end, Node

from . import guest as gm

M32 = 0xFFFFFFFF
G = uc.G
TMP1, TMP2, TMP3 = G, G + 1, G + 2
ZERO, K1F, K80, K8000, KE1 = G + 3, G + 4, G + 5, G + 6, G + 7
CONSTS = {ZERO: 0, K1F: 0x1F, K80: 0x80, K8000: 0x8000, KE1: 0xE1}
SP, HI = 15, 16
RD = "r"                                   # 1b's d is IR[11:8]
L_CC = 17                                  # location 17 + cc of bank (flags byte)
CC_BANKS = range(0x20, 0x40)               # S set, T clear: the flags bytes there are
TABLE_PA = 0x100000
VEC = {"irq": 0x04, "illegal": 0x08, "swi": 0x0C, "divide": 0x10, "address": 0x14}
NZCV = dict(fnz="nz", fc="aluc", fv="ovf")
NZ = dict(fnz="nz")


def cond_true(cc, nzcv):
    n, z, c, v = (nzcv >> 3) & 1, (nzcv >> 2) & 1, (nzcv >> 1) & 1, nzcv & 1
    t = [z, c, n, v, c & (z ^ 1), int(n == v), (z ^ 1) & int(n == v), 1][cc >> 1]
    return t ^ (cc & 1)


def table_image():
    words = []
    for bank in CC_BANKS:
        for cc in range(15):
            words.append(cond_true(cc, bank & 15))
    words += [CONSTS[k] for k in sorted(CONSTS)]
    return b"".join(w.to_bytes(4, "little") for w in words)


_shared = {}


def shared(key, make):
    """A tail built once and reused: routines specialised on a register
    branch into it after their first step. (The placement's merging of
    equal nodes can't merge loops, which are their own successors.)"""
    if key not in _shared:
        _shared[key] = make()
    return _shared[key]


def wr(dz):
    """A write of 1b's d, unless d is r0."""
    return {} if dz else mi(w=RD)


def reg(R):
    """The register file location of 1b's register R as a source: r0 is
    the constant zero."""
    return ZERO if R == 0 else R


# --------------------------------------------------------------------------
# Traps: push the PC (less pcfix bytes) and the flags word; I <- 0; jump


_traps = {}


def trap(vec, pcfix, name=None):
    key = (vec, pcfix)
    if key in _traps:
        return _traps[key]
    name = name or f"trap {vec}"
    n = chain(name,
              mi(b="flags", ra=K1F, alu="and", w=TMP1),
              mi(a="pc", kv=pcfix, alu="sub", ldr=1) if pcfix else mi(a="pc", alu="passa", ldr=1),
              mi(ra=SP, kv=4, alu="sub", w=SP, ldmar=1),
              mi(a="r", mem="write", size="word"),
              mi(ra=SP, kv=4, alu="sub", w=SP, ldmar=1),
              mi(ra=TMP1, mem="write", size="word", fi="0"),
              end(name, kv=VEC[vec], alu="passb", ldpc=1))
    _traps[key] = n
    return n


def call_tail():
    """A call, the target in R: push the PC (the next instruction; a
    store's data comes from the register file or R, so through TMP1) and
    jump. One tail for every call."""
    return shared(("call",), lambda: chain(
        "call", mi(a="pc", alu="passa", w=TMP1),
        mi(ra=SP, kv=4, alu="sub", w=SP, ldmar=1),
        end("call", ra=TMP1, mem="write", size="word", b="r", alu="passb", ldpc=1)))


# --------------------------------------------------------------------------
# Operands: a mode M with register (or constant) R


class Opnd:
    """kind 'reg', 'imm' or 'mem'; pre: steps before the using cycle; use:
    the using cycle's fields (the operand on B); consume: the using cycle
    consumes a parcel; post: ('pi', n) [R]+, ('pd', n) -[R]; base: the
    address is register R itself."""

    def __init__(self, kind, pre, use, size=4, consume=False, post=None, base=None):
        self.kind, self.pre, self.use, self.size = kind, pre, use, size
        self.consume, self.post, self.base = consume, post, base


SIZE = {1: "byte", 2: "half", 4: "word"}
LANE = {1: "tbyte", 2: "thalf", 4: "t"}


def mem_size(M, R):
    if M in (8, 9, 0xA) or (M == 0xF and R in (5, 8, 0xB)):
        return 1
    if M in (0xB, 0xC) or (M == 0xF and R in (6, 9, 0xC)):
        return 2
    return 4


def addr_steps(M, R):
    """Steps leaving MAR = the address of a memory operand (not mode 5), and
    the post-update."""
    if M in (2, 8, 0xB):
        return [mi(ra=reg(R), alu="passa", ldmar=1)], None
    if M in (3, 9, 0xC):
        return [mi(ra=reg(R), b="qh", fill="qh15", alu="add", ldmar=1, consume=1)], None
    if M == 4:
        return [mi(ra=SP, kv=4 * R, alu="add", ldmar=1)], None
    if M in (6, 0xA):
        return [mi(ra=reg(R), alu="passa", ldmar=1)], ("pi", 4 if M == 6 else 1)
    if M == 7:
        return [mi(ra=reg(R), kv=4, alu="sub", ldmar=1, **({} if R == 0 else {"w": R}))], \
            ("pd", 4)
    if M == 0xF and R in (4, 5, 6):
        return [mi(b="qh", fill="qh15", alu="passb", ldmar=1, consume=1)], None
    if M == 0xF and R in (7, 8, 9):
        return [mi(b="qh", fill="0", alu="passb", ldr=1, consume=1),
                mi(a="r", b="qhh", alu="or", ldmar=1, consume=1)], None
    if M == 0xF and R in (0xA, 0xB, 0xC):
        # nxt + d16: the extension parcel's address + 2 + d16
        return [mi(a="pc", pck=1, b="qh", fill="qh15", alu="addc", cin="1", ldmar=1,
                   consume=1)], None
    raise ValueError((M, R))


def opnd(M, R):
    if M == 0:
        return Opnd("reg", [], mi(rb=reg(R)))
    if M == 1:
        return Opnd("imm", [], mi(kv=R))
    if M == 0xD:
        return Opnd("imm", [], mi(kv=-(R + 1)))
    if M == 0xF and R <= 3:
        if R == 0:
            return Opnd("imm", [], mi(b="qh", fill="qh15"), consume=True)
        if R == 1:
            return Opnd("imm", [], mi(b="qh", fill="0"), consume=True)
        if R == 2:
            return Opnd("imm", [], mi(b="qhh"), consume=True)
        return Opnd("imm", [mi(b="qh", fill="0", alu="passb", ldr=1, consume=1),
                            mi(a="r", b="qhh", alu="or", ldr=1, consume=1)], mi(b="r"))
    if M == 0xE or (M == 0xF and R >= 0xD):
        return None
    if M == 5:
        return Opnd("idx", [], {})
    size = mem_size(M, R)
    steps, post = addr_steps(M, R)
    use = mi(mem="read", size=SIZE[size], b=LANE[size])
    base = R if M in (2, 8, 0xB) else None
    return Opnd("mem", steps, use, size=size, post=post, base=base)


# the indexed mode: a dispatch on the index parcel's scale and size; TMP1 <-
# R + d8; SX <- the index register; then TMP1 + x << s

def idx_routine(R, make, key):
    """make(Opnd) -> the routine for a memory operand whose address steps
    are given. Only the first step depends on R; the table of 16 routines
    is shared by every R (key: what else it depends on)."""
    first = mi(ra=reg(R), b="qhb", alu="add", w=TMP1, ldsx="qhx", consume=1)
    return Node(first, ("dispatch", shared(("idx",) + key, lambda: idx_table(make))),
                "indexed")


def idx_table(make):
    table = []
    for i in range(16):
        s, z = i >> 2, i & 3
        if z == 3:
            # a node of its own in each slot, so that the table can be shared
            table.append(trap("illegal", 4).clone())
            continue
        size = (1, 2, 4)[z]
        if s == 0:
            steps = [mi(ra="x", rb=TMP1, alu="add", ldmar=1)]
        else:
            steps = [mi(ra="x", rb="x", alu="add", ldr=1)]               # 2x
            if s == 1:
                steps.append(mi(a="r", rb=TMP1, alu="add", ldmar=1))
            elif s == 2:
                steps.append(mi(a="r2", sina="0", rb=TMP1, alu="add", ldmar=1))
            else:
                steps.append(mi(a="r2", sina="0", alu="passa", ldr=1))
                steps.append(mi(a="r2", sina="0", rb=TMP1, alu="add", ldmar=1))
        o = Opnd("mem", steps, mi(mem="read", size=SIZE[size], b=LANE[size]), size=size)
        table.append(make(o))
    return table


# --------------------------------------------------------------------------
# The EA operations: MOV ST LEA ADD SUB CMP AND OR XOR, JMP/CALL ea

EA_NAME = {1: "MOV", 2: "ST", 3: "LEA", 4: "ADD", 5: "SUB", 6: "CMP", 7: "AND", 8: "OR",
           9: "XOR", 0xB: "JEA"}
ALU = {4: ("add", NZCV), 5: ("sub", NZCV), 6: ("sub", NZCV), 7: ("and", NZ), 8: ("or", NZ),
       9: ("xor", NZ)}


def op_fields(op, dz):
    """The using cycle's operation, the operand on B."""
    if op == 1:
        return merge(mi(alu="passb", **NZ), wr(dz))
    a, fl = ALU[op]
    f = mi(ra=RD, alu=a, **fl)
    return f if op == 6 else merge(f, wr(dz))


def post_step(o, R):
    """[R]+'s update (after the access, in a cycle of its own)."""
    if not o.post or R == 0:
        return []
    kind, n = o.post
    if kind == "pi":
        return [mi(ra=R, kv=n, alu="add", w=R)]
    return []


def load_like(op, o, R, dz, name):
    use = merge(o.use, op_fields(op, dz))
    if o.post and o.post[0] == "pi" and R != 0:
        # the read at the A bus, the register stepped in the same cycle
        acc = mi(mem="reada", size=SIZE[o.size], ra=R, kv=o.post[1], alu="add", w=R)
        return chain(name, acc, end(name, _fields=merge(mi(b=LANE[o.size]),
                                                        op_fields(op, dz))))
    if o.base is not None and op == 1:
        # MOV rd, [R]: one cycle, the address from the A bus
        return end(name, _fields=merge(mi(mem="reada", size=SIZE[o.size], ra=reg(R),
                                          b=LANE[o.size]), op_fields(op, dz)))
    if o.consume:
        return chain(name, *o.pre, merge(use, mi(consume=1)), end(name))
    return chain(name, *o.pre, end(name, _fields=use))


def store_like(o, R, name):
    acc = mi(ra=RD, mem="write", size=SIZE[o.size])
    if o.post and o.post[0] == "pi" and R != 0:
        return chain(name, *o.pre, acc, end(name, ra=R, kv=o.post[1], alu="add", w=R))
    return chain(name, *o.pre, end(name, _fields=acc))


def jea(call, o, R, name):
    """JMP and CALL to the operand's value (a memory operand: the word
    there)."""
    def go(src_fields):
        if not call:
            return end(name, _fields=merge(src_fields, mi(ldpc=1)))
        return chain(name, merge(src_fields, mi(ldr=1)), call_tail())
    if o.kind in ("reg", "imm"):
        if o.consume:
            return chain(name, *o.pre, merge(o.use, mi(alu="passb", ldr=1, consume=1)),
                         go(mi(b="r", alu="passb")))
        return chain(name, *o.pre, go(merge(o.use, mi(alu="passb"))))
    if o.size != 4:
        return trap("illegal", 2)
    steps = list(o.pre)
    read = merge(o.use, mi(alu="passb", ldr=1))
    return chain(name, *steps, read, *post_step(o, R), go(mi(b="r", alu="passb")))


def ea_routine(op, M, R, dz):
    name = f"{EA_NAME[op]} m{M:X}"
    o = opnd(M, R)
    if o is None:
        return trap("illegal", 2)
    if o.kind == "idx":
        if op == 3:                                     # LEA [R + x*s + d8]
            return idx_routine(R, lambda oo: lea_from(oo, dz, name), (op, dz))
        return idx_routine(R, lambda oo: ea_with(op, oo, None, dz, name, idx=True), (op, dz))
    return ea_with(op, o, R, dz, name)


def lea_from(o, dz, name):
    """LEA: the address the steps leave in MAR, into d."""
    return chain(name, *o.pre, end(name, _fields=merge(mi(a="mar", alu="passa"), wr(dz))))


def ea_with(op, o, R, dz, name, idx=False):
    if op == 0xB:
        return jea(dz is False, o, R, name)             # d: 0 JMP, 1 CALL (see classify)
    if op == 2:
        if o.kind != "mem":
            return trap("illegal", 2)
        return store_like(o, R, name)
    if op == 3:
        if o.kind != "mem" or o.post:
            return trap("illegal", 2)
        return lea_from(o, dz, name)
    if o.kind == "mem":
        return load_like(op, o, R, dz, name)
    use = merge(o.use, op_fields(op, dz))
    if o.consume:
        return chain(name, *o.pre, merge(use, mi(consume=1)), end(name))
    return chain(name, *o.pre, end(name, _fields=use))


# --------------------------------------------------------------------------
# The other groups

def bcc(ii, link):
    off = 2 * (ii - 256 if ii & 0x80 else ii)
    if not link:
        return end("Bcc", a="pc", kv=off, alu="add", ldpc=1, pccond="bcond", ccb="set")
    return chain("BSR", mi(a="pc", kv=off, alu="add", ldr=1), call_tail())


def jcc(k, call):
    name = "CALL" if call else "Jcc"
    if k == 0:
        steps = [mi(b="qh2", fill="qh15", alu="passb", ldr=1, consume=1)]
        target = mi(a="pc", b="r", alu="add")
    else:
        steps = [mi(b="qh", fill="0", alu="passb", ldr=1, consume=1),
                 mi(a="r", b="qhh", alu="or", ldr=1, consume=1)]
        target = mi(b="r", alu="passb")
    if not call:
        return chain(name, *steps, end(name, _fields=merge(target, mi(ldpc=1, pccond="bcond",
                                                                      ccb="set"))))
    if k == 0:
        steps.append(mi(a="pc", b="r", alu="add", ldr=1))
    return chain(name, *steps, call_tail())


def unary(f, s, dz):
    name = ["NOT", "NEG", "INC", "DEC", "RLC", "RRC", "SWAP", "SXB", "ZXB", "SXH", "ZXH",
            "CLZ"][f]
    src = reg(s)
    w = wr(dz)

    def one(**kw):
        return end(name, _fields=merge(mi(**kw), w, mi(**NZ)))
    if f == 0:
        return one(ra=src, alu="nota")
    if f == 1:
        return chain(name, mi(alu="zero", ldr=1),
                     end(name, _fields=merge(mi(a="r", rb=src, alu="sub"), w, mi(**NZCV))))
    if f == 2:
        return one(ra=src, alu="inc")
    if f == 3:
        return one(ra=src, alu="dec")
    if f == 4:
        return one(ra=src, alu="dbl", cin="c", fc="aluc", fv="0")
    if f == 5:
        return one(ra=src, alu="passa", rms="shr", sin="c", fc="f0", fv="0")
    if f == 6:
        return one(ra=src, alu="passa", rms="ror16")
    if f == 8:
        return one(ra=src, alu="passa", rz=0b1110)
    if f == 10:
        return one(ra=src, alu="passa", rz=0b1100)
    if f == 7:
        return chain(name, mi(ra=src, kv=0x80, alu="xor", rz=0b1110, ldr=1),
                     one(a="r", kv=0x80, alu="sub"))
    if f == 9:
        # (x ^ s) & 0xFFFF ^ s, s = 32 copies of bit 15
        return chain(name, mi(ra=src, b="fillall", fill="a15", ldsgn=1, alu="xor", rz=0b1100,
                              ldr=1),
                     one(a="r", b="fillall", fill="sgn", alu="xor"))
    # CLZ: shift left until bit 31 (LC counts, starting one low)
    def clz():
        out = end(name, _fields=merge(mi(b="simm", v8="lc", fill="0", alu="passb"), w, mi(**NZ)))
        body = loop(name, mi(a="r2", sina="0", alu="passa", ldr=1, lcinc=1), "r31", out)
        return branch(name, mi(kv=-1, alu="passb", ldlc=1), "cl", body,
                      end(name, _fields=merge(mi(kv=32, alu="passb"), w, mi(**NZ))))
    return chain(name, mi(ra=src, alu="passa", ldr=1, ldcl="zero"), shared(("clz", dz), clz))


def shift_imm(op, n, dz):
    name = ["LSL", "LSR", "ASR", "ROR"][op] + f" #{n}"
    w = wr(dz)
    if n == 0:
        return end(name, ra=RD, alu="passa", fv="0", **NZ)
    from heron.studies.v1b_hw import ucode as v1b_uc
    steps = [dict(s) for s in v1b_uc.cached_plan(op, n)]
    steps[0]["RFA"] = 1                       # the plans read rd as IR[15:12]; 1b's is IR[11:8]
    body = [merge(s, mi(ldr=1)) for s in steps[:-1]]
    return chain(name, *body, end(name, _fields=merge(steps[-1], w, mi(fv="0"), mi(**NZ))))


def shift_reg(op, s, dz):
    name = ["LSL", "LSR", "ASR", "ROR"][op] + " reg"

    def tail():
        wb = end(name, _fields=merge(mi(a="r", alu="passa", fv="0"), wr(dz), mi(**NZ)))
        if op == 0:
            step = mi(a="r", alu="dbl", cin="0", fc="aluc")
        else:
            step = mi(a="r", alu="passa", rms="shr", sin={1: "0", 2: "f31", 3: "f0"}[op],
                      fc="f0")
        body = loop(name, merge(step, mi(ldr=1, lcinc=1)), "tc", wb)
        return branch(name, mi(ra=RD, alu="passa", ldr=1, lcinc=1), "tc", body, wb)
    return chain(name, mi(ra=reg(s), kv=0xE0 - 256, alu="ornb", ldlc=1),
                 shared(("shr", op, dz), tail))


def rr(f, s, dz):
    name = ["ADC", "SBC", "BIC", "TST", "MULU", "MULS", "DIVU", "DIVS", "DIVUL"][f]
    src = reg(s)
    w = wr(dz)
    if f == 0:
        return end(name, _fields=merge(mi(ra=RD, rb=src, alu="adc", fnz="sticky", fc="aluc",
                                          fv="ovf"), w))
    if f == 1:
        return end(name, _fields=merge(mi(ra=RD, rb=src, alu="sbc", fnz="sticky", fc="aluc",
                                          fv="ovf"), w))
    if f == 2:
        return end(name, _fields=merge(mi(ra=RD, rb=src, alu="bic", **NZ), w))
    if f == 3:
        return end(name, ra=RD, rb=src, alu="and", **NZ)
    if f in (4, 5):
        return mul(name, f == 5, src, w)
    return div(name, f, src, w)


def mul(name, signed, src, w):
    """HI:d <- d x src, 32 steps; C = V = the product doesn't fit in 32
    bits. TMP1 = d, TMP2 = src; signed: the high word corrected for the
    signs (- (d < 0 ? src : 0) - (src < 0 ? d : 0))."""
    step = mi(a="r", rb=TMP1, md="mulu", rms="shr", ldr=1, lcinc=1)
    if not signed:
        tail = [mi(a="r", alu="passa", w=HI, ldcl="zero"),
                end(name, _fields=merge(mi(b="mq", alu="passb", fc="ncl", fv="ncl"), w, mi(**NZ)))]
    else:
        tail = [mi(ra=TMP1, fill="a31", ldsgn=1),
                mi(ra=TMP2, b="fillall", fill="sgn", alu="and", w=TMP3),
                mi(a="r", rb=TMP3, alu="sub", ldr=1),
                mi(ra=TMP2, fill="a31", ldsgn=1),
                mi(ra=TMP1, b="fillall", fill="sgn", alu="and", w=TMP3),
                mi(a="r", rb=TMP3, alu="sub", w=HI),
                # overflow iff HI isn't the sign extension of the low word
                mi(b="mq", alu="passb", ldr=1),
                mi(a="r", fill="a31", ldsgn=1),
                mi(ra=HI, b="fillall", fill="sgn", alu="xor", ldcl="zero"),
                end(name, _fields=merge(mi(b="mq", alu="passb", fc="ncl", fv="ncl"), w, mi(**NZ)))]
    core = shared(("mul", signed, bool(w)), lambda: chain(
        name, mi(ra=RD, alu="passa", w=TMP1), mi(rb=TMP2, md="mqload", alu="zero", ldr=1),
        mi(kv=-32, alu="passb", ldlc=1), loop(name, step, "tc", chain(name, *tail))))
    return chain(name, mi(ra=src, alu="passa", w=TMP2), core)


def div(name, f, src, w):
    """Non-restoring division on magnitudes (draft 1b's): R the partial
    remainder, MQ the quotient; TMP3 the divisor. A zero divisor traps
    (registers unchanged), as does nothing else."""
    dz_trap = trap("divide", 2)
    fix = mi(a="r", rb=TMP3, md="fix", ldr=1)
    body_step = mi(a="r2", sina="mq31", rb=TMP3, md="div", ldr=1, lcinc=1)
    if f == 8:                                          # DIVUL: HI:d / src
        out = chain(name, fix, mi(a="r", alu="passa", w=HI),
                    end(name, _fields=merge(mi(b="mq", alu="passb", czero=1, fv="0"), w, mi(**NZ))))
        go = chain(name, mi(ra=HI, alu="passa", ldr=1),
                   mi(a="r", rb=TMP3, alu="sub", ldcl="aluc"),
                   branch(name, {}, "cl",
                          chain(name, mi(rb=RD, md="mqload", a="r", alu="passa", ldr=1),
                                mi(kv=-32, alu="passb", ldlc=1),
                                loop(name, body_step, "tc", out)),
                          end(name, fv="1")))
        return chain(name, mi(ra=src, alu="passa", w=TMP3, ldcl="zero"),
                     shared(("div", f, bool(w)), lambda: branch(name, {}, "cl", go, dz_trap)))
    if f == 6:                                          # DIVU
        out = chain(name, fix, mi(a="r", alu="passa", w=HI),
                    end(name, _fields=merge(mi(b="mq", alu="passb", czero=1, fv="0"), w, mi(**NZ))))
        go = chain(name, mi(ra=RD, alu="passa", w=TMP1),
                   mi(rb=TMP1, md="mqload", alu="zero", ldr=1),
                   mi(kv=-32, alu="passb", ldlc=1), loop(name, body_step, "tc", out))
        return chain(name, mi(ra=src, alu="passa", w=TMP3, ldcl="zero"),
                     shared(("div", f, bool(w)), lambda: branch(name, {}, "cl", go, dz_trap)))
    # DIVS: magnitudes; the quotient's sign is d's xor src's, the
    # remainder's d's; -2^31 / -1 gives -2^31, remainder 0, V
    quot = chain(name,
                 mi(a="r", b="fillall", fill="sgn", alu="xor", ldr=1),
                 mi(a="r", alu="a", cin="sgn", w=HI),                      # remainder
                 mi(ra=TMP1, alu="passa", ldr=1),
                 mi(a="r", rb=TMP2, alu="xor", ldr=1),
                 mi(a="r", fill="a31", ldsgn=1, b="mq", alu="passb", ldr=1),
                 mi(a="r", b="fillall", fill="sgn", alu="xor", ldr=1),
                 end(name, _fields=merge(mi(a="r", alu="a", cin="sgn", czero=1, fv="0"), w,
                                         mi(**NZ))))
    special = chain(name, mi(alu="zero", w=HI),
                    end(name, _fields=merge(mi(b="mq", alu="passb", czero=1, fv="1"), w, mi(**NZ))))
    out = branch(name, mi(a="r", rb=TMP3, md="fix", ldr=1), "mq31", quot,
                 chain(name, mi(ra=TMP1, alu="passa", ldr=1),
                       mi(a="r", rb=TMP2, alu="xor", ldr=1),
                       branch(name, {}, "r31", special,
                              chain(name, mi(alu="zero", ldr=1), quot))))
    go = chain(name,
               mi(ra=TMP2, b="fillall", fill="a31", ldsgn=1, alu="xor", ldr=1),
               mi(a="r", alu="a", cin="sgn", w=TMP3),                      # |src|
               mi(ra=RD, alu="passa", w=TMP1),
               mi(ra=TMP1, b="fillall", fill="a31", ldsgn=1, alu="xor", ldr=1),
               mi(a="r", alu="a", cin="sgn", ldr=1),                       # |d|, SGN = d's sign
               mi(b="r", md="mqload", alu="zero", ldr=1),
               mi(kv=-32, alu="passb", ldlc=1),
               loop(name, body_step, "tc", out))
    return chain(name, mi(ra=src, alu="passa", w=TMP2, ldcl="zero"),
                 shared(("div", f, bool(w)), lambda: branch(name, {}, "cl", go, dz_trap)))


def sys_routine(f, a, b):
    """The system group, 0 a b f."""
    if f == 0:
        n = Node(mi(), None, "HALT")
        n.succ = ("halt",)
        return n
    if f == 1:
        return end("NOP")
    if f == 2:
        return end("JMP rs", ra=reg(b), alu="passa", ldpc=1)
    if f == 3:
        return chain("CALL rs", mi(ra=reg(b), alu="passa", ldr=1), call_tail())
    if f == 4:
        return chain("RET", mi(mem="reada", size="word", ra=SP, kv=4, alu="add", w=SP),
                     end("RET", b="t", alu="passb", ldpc=1))
    if f in (5, 6):
        if not 1 <= a <= b <= 14:
            return trap("illegal", 2)
        regs = list(range(a, b + 1))
        if f == 5:
            stores = [mi(ra=k, mem="write", size="word", marinc=1) for k in regs]
            return chain("SAVE", mi(ra=SP, kv=4 * len(regs), alu="sub", w=SP, ldmar=1),
                         *stores[:-1], end("SAVE", _fields=stores[-1]))
        loads = [mi(mem="read", size="word", b="t", alu="passb", w=k, marinc=1) for k in regs]
        return chain("RESTORE", mi(ra=SP, alu="passa", ldmar=1), *loads,
                     end("RESTORE", a="mar", alu="passa", w=SP))
    if f == 7:
        # RTI: the flags word, then the PC
        return chain("RTI", mi(mem="reada", size="word", ra=SP, kv=4, alu="add", w=SP),
                     mi(b="t", ra=K1F, alu="and", ldr=1),
                     mi(a="r", loadf="sup"),
                     mi(mem="reada", size="word", ra=SP, kv=4, alu="add", w=SP),
                     end("RTI", b="t", alu="passb", ldpc=1))
    if f == 8:
        return end("EI", fi="1")
    if f == 9:
        return end("DI", fi="0")
    if f == 10:
        if b == 0:
            return end("MFF", _fields=merge(mi(b="flags", ra=K1F, alu="and"), wr(a == 0)))
        if b == 1:
            return end("MFHI", _fields=merge(mi(ra=HI, alu="passa"), wr(a == 0)))
        return trap("illegal", 2)
    if f == 11:
        if a == 0:
            return chain("MTF", mi(ra=reg(b), kv=0x1F, alu="and", ldr=1),
                         end("MTF", a="r", loadf="sup"))
        if a == 1:
            return end("MTHI", ra=reg(b), alu="passa", w=HI)
        return trap("illegal", 2)
    if f == 12:
        return trap("swi", 0, "SWI")
    if f == 13 and b != 15:
        # SETcc: bank 16 + NZCV, location 17 + cc
        return chain("SETcc", mi(b="flags", alu="passb", ldbank=1, ubr=1),
                     end("SETcc", _fields=merge(mi(ra=L_CC + b, alu="passa"), wr(a == 0))))
    return trap("illegal", 2)


# --------------------------------------------------------------------------

class V1b:
    name = "v1b"
    no_lockstep = ("interrupts",)

    def reset(self):
        start = [mi(alu="zero", ldr=1), mi(a="r", loadf="sup", sset=1),
                 mi(kv=0x10, alu="passb", rms="ror16", ldr=1),
                 mi(kv=1, alu="passb", rms="shr", sin="f0", w=TMP1),
                 mi(a="r", rb=TMP1, alu="or", ldmar=1)]
        # the condition tables: for LC = 0xE0..0xFF, bank LC - 0xC0 (0x20-0x3F)
        copy = [mi(mem="read", size="word", marinc=1, b="t", alu="passb", w=L_CC + cc, ubw=1)
                for cc in range(15)]
        consts = [mi(mem="read", size="word", marinc=1, b="t", alu="passb", w=k)
                  for k in sorted(CONSTS)]
        regs = [mi(alu="zero", w=k) for k in range(17)]
        tail = chain("reset", *consts, *regs, end("reset", alu="zero", ldpc=1))
        head = Node(mi(b="simm", v8="lc", fill="0", a="r", alu="add", ldbank=1), None, "reset")
        body = chain("reset", *copy[:-1],
                     branch("reset", merge(copy[-1], mi(lcinc=1)), "tc", head, tail))
        head.succ = ("next", body)
        return chain("reset", *start, mi(kv=-0xC0, alu="passb", ldr=1),
                     mi(kv=-32, alu="passb", ldlc=1), head)

    def fixed(self):
        out = gm.default_fixed(self.name)
        out[uc.IRQ_ADDR] = Node(mi(), ("next", trap("irq", 0, "interrupt")), "interrupt")
        for ln in range(4):
            # a misaligned access is 1b's address error; anything else stops
            out[uc.fault_addr(ln)] = branch("fault", {}, "fk0",
                                            chain("fault", {}, gm.stop("v1b fault")),
                                            trap("address", 2 * ln, "address error"))
        return out

    def preload(self):
        return [(TABLE_PA, table_image())]

    def classify(self, w):
        op, d, M, R = w >> 12, (w >> 8) & 15, (w >> 4) & 15, w & 15
        if 1 <= op <= 9 or op == 0xB:
            ln = 1 + _mode_size(M, R)
            if op == 0xB:
                if d > 1:
                    return ("illegal",), 1
                return ("ea", op, M, R, d == 0), ln         # dz carries JMP (True) / CALL
            return ("ea", op, M, R, d == 0 and op not in (2, 6)), ln
        if op == 0xA:
            k, z = M, R
            if k > 1 or z:
                return ("illegal",), 1
            return ("jcc", k, d == 15), 2 if k == 0 else 3
        if op == 0xC:
            return (("un", R, M, d == 0) if R < 12 else ("illegal",)), 1
        if op == 0xD:
            t, sop = R >> 2, R & 3
            if t == 3:
                return ("illegal",), 1
            if t == 2:
                return ("shr", sop, M, d == 0), 1
            return ("shi", sop, M + 16 * t, d == 0), 1
        if op == 0xE:
            return ("bcc", w & 0xFF, d == 15), 1
        if op == 0xF:
            return (("rr", R, M, d == 0) if R < 9 else ("illegal",)), 1
        # system: 0 a b f
        f = R
        if f in (5, 6, 11, 13) or (f == 10):
            return ("sys", f, d, M), 1
        if f in (2, 3):
            return ("sys", f, 0, M), 1
        return ("sys", f, 0, 0), 1

    def routine(self, key):
        k = key[0]
        if k == "illegal":
            return trap("illegal", 2)
        if k == "ea":
            _, op, M, R, dz = key
            return ea_routine(op, M, R, dz)
        if k == "jcc":
            return jcc(key[1], key[2])
        if k == "un":
            return unary(*key[1:])
        if k == "shr":
            return shift_reg(*key[1:])
        if k == "shi":
            return shift_imm(*key[1:])
        if k == "bcc":
            return bcc(key[1], key[2])
        if k == "rr":
            return rr(*key[1:])
        if k == "sys":
            return sys_routine(*key[1:])
        raise ValueError(key)

    def state(self, m):
        f = m.flags_word()
        return {"r": [m.rf[k] for k in range(1, 16)], "hi": m.rf[HI],
                "pc": (m.PC - 2) & M32, "nzcv": f & 15}


def _mode_size(M, R):
    if M in (3, 5, 9, 0xC):
        return 1
    if M == 0xF:
        return 2 if R in (3, 7, 8, 9) else (1 if R <= 0xC else 0)
    return 0


_built = {}


def built():
    if "mc" not in _built:
        _traps.clear()
        _shared.clear()
        _built["mc"] = gm.GuestMicrocode(V1b())
    return _built["mc"]
