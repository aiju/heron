"""Everything drafts 1a and 1b share: semantics, the system, unary and shift
groups, branches, and the matching assembler and disassembler pieces.

See docs/isa-v1.md. Instructions are decoded once per address into a
closure `fn(m) -> timing key` that executes the instruction on a
sim32.Machine32 and returns the key timing32 turns into cycles:
(parcels, pc & 2, kind, *params).
"""

from heron.infra.asm import AsmError, Reg, RegRange, Imm, Mem, Expr
from heron.infra.obj import ABS32, ABS16S, PC16, PC16H

M32 = 0xFFFFFFFF
RAM_SIZE = 0x100000
IO_BASE = 0xFFFFFF00
MEM_TOP = RAM_SIZE          # the assembler refuses to place anything above this

RESET_VECTOR = 0x00
IRQ_VECTOR = 0x04
ILLEGAL_VECTOR = 0x08
SWI_VECTOR = 0x0C
DIV_VECTOR = 0x10
ADDR_VECTOR = 0x14

REGISTERS = {f"r{i}": i for i in range(16)}
REGISTERS["sp"] = 15

F_V, F_C, F_Z, F_N, F_I = 0, 1, 2, 3, 4

COND = ["EQ", "NE", "CS", "CC", "MI", "PL", "VS", "VC",
        "HI", "LS", "GE", "LT", "GT", "LE", "RA"]
COND_ALIAS = {"HS": 2, "LO": 3, "AL": 14}

ALU_FN = ["ADD", "ADC", "SUB", "SBC", "AND", "OR", "XOR", "BIC",
          "MOV", "CMP", "TST", "MULU", "MULS", "DIVU", "DIVS", "DIVUL"]
UN_FN = ["NOT", "NEG", "INC", "DEC", "RLC", "RRC", "SWAP",
         "SXB", "ZXB", "SXH", "ZXH", "CLZ"]
SHIFT_FN = ["LSL", "LSR", "ASR", "ROR"]
SYS_FN = ["HALT", "NOP", "JMP", "CALL", "RET", "SAVE", "RESTORE", "RTI",
          "EI", "DI", "MFSR", "MTSR", "SWI", "SET"]
SR_NAMES = {0: "flags", 1: "hi"}


class Trap(Exception):
    """Raised by an instruction to enter a trap. fault=True saves the
    faulting instruction's address, False the next instruction's."""

    def __init__(self, vector, fault=True, why=""):
        super().__init__(why)
        self.vector = vector
        self.fault = fault
        self.why = why


def illegal(why="illegal instruction"):
    raise Trap(ILLEGAL_VECTOR, True, why)


def s32(x):
    x &= M32
    return x - (1 << 32) if x & 0x80000000 else x


def sext8(x):
    x &= 0xFF
    return x - 0x100 if x & 0x80 else x


def sext16(x):
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


def crosses(a, b):
    """1 if a and b differ in their upper 16 bits (a 16-bit datapath then
    needs a second cycle for the address)."""
    return 1 if (a ^ b) >> 16 else 0


def shift_steps(n):
    """Microcode steps for a shift by n: halves, then bytes, then bits."""
    return n // 16 + (n % 16) // 8 + n % 8


# ==========================================================================
# Semantics


def nz(m, res):
    m.n = res >> 31
    m.z = 1 if res == 0 else 0
    return res


def add(m, a, b, cin):
    r = a + b + cin
    res = r & M32
    m.c = r >> 32
    m.v = (((a ^ res) & (b ^ res)) >> 31) & 1
    m.n = res >> 31
    m.z = 1 if res == 0 else 0
    return res


def flags_word(m):
    return (m.v << F_V) | (m.c << F_C) | (m.z << F_Z) | (m.n << F_N) | (m.i << F_I)


def set_flags_word(m, x):
    m.v = (x >> F_V) & 1
    m.c = (x >> F_C) & 1
    m.z = (x >> F_Z) & 1
    m.n = (x >> F_N) & 1
    m.i = (x >> F_I) & 1


def cond_true(m, cc):
    base = cc >> 1
    if base == 0: t = m.z
    elif base == 1: t = m.c
    elif base == 2: t = m.n
    elif base == 3: t = m.v
    elif base == 4: t = m.c & (m.z ^ 1)
    elif base == 5: t = 1 if m.n == m.v else 0
    elif base == 6: t = (m.z ^ 1) & (1 if m.n == m.v else 0)
    else: t = 1
    return t ^ (cc & 1)


# Two-operand ALU functions: f(m, a, b) -> result, or None for "no write".
def _adc(m, a, b):
    z = m.z
    r = add(m, a, b, m.c)
    m.z &= z
    return r


def _sbc(m, a, b):
    z = m.z
    r = add(m, a, b ^ M32, m.c)
    m.z &= z
    return r


def _cmp(m, a, b):
    add(m, a, b ^ M32, 1)
    return None


def _tst(m, a, b):
    nz(m, a & b)
    return None


def _mulu(m, a, b):
    p = a * b
    m.hi = p >> 32
    m.c = m.v = 1 if m.hi else 0
    return nz(m, p & M32)


def _muls(m, a, b):
    p = s32(a) * s32(b)
    m.hi = (p >> 32) & M32
    m.c = m.v = 0 if -(1 << 31) <= p < (1 << 31) else 1
    return nz(m, p & M32)


def _divu(m, a, b):
    if b == 0:
        raise Trap(DIV_VECTOR, True, "divide by zero")
    m.hi = a % b
    m.c = m.v = 0
    return nz(m, a // b)


def _divs(m, a, b):
    if b == 0:
        raise Trap(DIV_VECTOR, True, "divide by zero")
    sa, sb = s32(a), s32(b)
    m.c = 0
    if sa == -(1 << 31) and sb == -1:
        m.hi = 0
        m.v = 1
        return nz(m, 0x80000000)
    q = abs(sa) // abs(sb)
    if (sa < 0) != (sb < 0):
        q = -q
    m.hi = (sa - q * sb) & M32
    m.v = 0
    return nz(m, q & M32)


def _divul(m, a, b):
    if b == 0:
        raise Trap(DIV_VECTOR, True, "divide by zero")
    if m.hi >= b:
        m.v = 1
        return None
    d = (m.hi << 32) | a
    m.hi = d % b
    m.c = m.v = 0
    return nz(m, d // b)


ALU_IMPL = [
    lambda m, a, b: add(m, a, b, 0),
    _adc,
    lambda m, a, b: add(m, a, b ^ M32, 1),
    _sbc,
    lambda m, a, b: nz(m, a & b),
    lambda m, a, b: nz(m, a | b),
    lambda m, a, b: nz(m, a ^ b),
    lambda m, a, b: nz(m, a & (b ^ M32)),
    lambda m, a, b: nz(m, b),
    _cmp,
    _tst,
    _mulu,
    _muls,
    _divu,
    _divs,
    _divul,
]
ALU_WRITES = [True] * 9 + [False, False] + [True] * 5


def alu_timing(fn, b):
    """Timing key tail for an ALU function with second operand b."""
    if fn == 11:
        return ("mul", b.bit_length(), 0)
    if fn == 12:
        return ("mul", abs(s32(b)).bit_length(), 1)
    if fn in (13, 15):
        return ("div", 0)
    if fn == 14:
        return ("div", 1)
    return ("alu", 1 if ALU_WRITES[fn] else 0)


def _rlc(m, x):
    r = ((x << 1) | m.c) & M32
    m.c = x >> 31
    m.v = 0
    return nz(m, r)


def _rrc(m, x):
    r = (x >> 1) | (m.c << 31)
    m.c = x & 1
    m.v = 0
    return nz(m, r)


UN_IMPL = [
    lambda m, x: nz(m, x ^ M32),
    lambda m, x: add(m, 0, x ^ M32, 1),
    lambda m, x: nz(m, (x + 1) & M32),
    lambda m, x: nz(m, (x - 1) & M32),
    _rlc,
    _rrc,
    lambda m, x: nz(m, ((x >> 16) | (x << 16)) & M32),
    lambda m, x: nz(m, (x & 0xFF) | (0xFFFFFF00 if x & 0x80 else 0)),
    lambda m, x: nz(m, x & 0xFF),
    lambda m, x: nz(m, (x & 0xFFFF) | (0xFFFF0000 if x & 0x8000 else 0)),
    lambda m, x: nz(m, x & 0xFFFF),
    lambda m, x: nz(m, 32 - x.bit_length()),
]


def shift(m, op, x, n):
    if n == 0:
        res = x
    elif op == 0:      # LSL
        m.c = (x >> (32 - n)) & 1
        res = (x << n) & M32
    elif op == 1:      # LSR
        m.c = (x >> (n - 1)) & 1
        res = x >> n
    elif op == 2:      # ASR
        sx = s32(x)
        m.c = (sx >> (n - 1)) & 1
        res = (sx >> n) & M32
    else:              # ROR
        res = ((x >> n) | (x << (32 - n))) & M32
        m.c = res >> 31
    m.v = 0
    return nz(m, res)


def push(m, v):
    sp = (m.r[15] - 4) & M32
    m.wr32(sp, v)
    m.r[15] = sp


def pop(m):
    sp = m.r[15]
    v = m.rd32(sp)
    m.r[15] = (sp + 4) & M32
    return v


def enter_interrupt(m, vector, ret_pc):
    """IRQ or trap: push PC, push flags, disable interrupts, jump to vector."""
    push(m, ret_pc)
    push(m, flags_word(m))
    m.i = 0
    m.pc = vector


# ==========================================================================
# Shared decoders. Each returns fn(m) -> timing key; n is the length in
# parcels, nxt the address of the next instruction.


def dec_sys(m, pc, w):
    a, b, f = (w >> 8) & 15, (w >> 4) & 15, w & 15
    nxt = (pc + 2) & M32
    p2 = pc & 2
    r = m.r
    if f == 0:
        def fn(m):
            m.halted = True
            m.pc = nxt
            return (1, p2, "sys")
    elif f == 1:
        def fn(m):
            m.pc = nxt
            return (1, p2, "sys")
    elif f == 2:
        def fn(m):
            m.pc = r[b] & 0xFFFFFFFE
            return (1, p2, "jmp", "reg", 0)
    elif f == 3:
        def fn(m):
            t = r[b] & 0xFFFFFFFE
            push(m, nxt)
            m.pc = t
            return (1, p2, "call", "reg", 0)
    elif f == 4:
        def fn(m):
            m.pc = pop(m) & 0xFFFFFFFE
            return (1, p2, "ret")
    elif f in (5, 6):
        if not 1 <= a <= b <= 14:
            return illegal_fn
        cnt = b - a + 1
        if f == 5:
            def fn(m):
                sp = (r[15] - 4 * cnt) & M32
                for i in range(cnt):
                    m.wr32(sp + 4 * i, r[a + i])
                r[15] = sp
                m.pc = nxt
                return (1, p2, "save", cnt)
        else:
            def fn(m):
                sp = r[15]
                vals = [m.rd32(sp + 4 * i) for i in range(cnt)]
                for i in range(cnt):
                    r[a + i] = vals[i]
                r[15] = (sp + 4 * cnt) & M32
                m.pc = nxt
                return (1, p2, "restore", cnt)
    elif f == 7:
        def fn(m):
            fl = pop(m)
            set_flags_word(m, fl)
            m.pc = pop(m) & 0xFFFFFFFE
            return (1, p2, "rti")
    elif f in (8, 9):
        val = 1 if f == 8 else 0

        def fn(m):
            m.i = val
            m.pc = nxt
            return (1, p2, "sys")
    elif f == 10:
        if b not in SR_NAMES:
            return illegal_fn

        def fn(m):
            v = flags_word(m) if b == 0 else m.hi
            if a:
                r[a] = v
            m.pc = nxt
            return (1, p2, "alu", 1)
    elif f == 11:
        if a not in SR_NAMES:
            return illegal_fn

        def fn(m):
            if a == 0:
                set_flags_word(m, r[b])
            else:
                m.hi = r[b]
            m.pc = nxt
            return (1, p2, "sys")
    elif f == 12:
        def fn(m):
            m.pc = nxt
            raise Trap(SWI_VECTOR, False, "SWI")
    elif f == 13:
        if b == 15:
            return illegal_fn

        def fn(m):
            if a:
                r[a] = cond_true(m, b)
            m.pc = nxt
            return (1, p2, "alu", 1)
    else:
        return illegal_fn
    return fn


def illegal_fn(m):
    illegal()


def dec_unary(m, pc, w):
    d, s, f = (w >> 8) & 15, (w >> 4) & 15, w & 15
    if f >= len(UN_FN):
        return illegal_fn
    impl = UN_IMPL[f]
    nxt = (pc + 2) & M32
    key = (1, pc & 2, "alu", 1)
    r = m.r

    def fn(m):
        v = impl(m, r[s])
        if d:
            r[d] = v
        m.pc = nxt
        return key
    return fn


def dec_shift(m, pc, w):
    d, s, f = (w >> 8) & 15, (w >> 4) & 15, w & 15
    op, t = f & 3, f >> 2
    nxt = (pc + 2) & M32
    p2 = pc & 2
    r = m.r
    if t == 3:
        return illegal_fn
    if t < 2:
        cnt = s + 16 * t
        key = (1, p2, "shift", shift_steps(cnt))

        def fn(m):
            v = shift(m, op, r[d], cnt)
            if d:
                r[d] = v
            m.pc = nxt
            return key
    else:
        def fn(m):
            cnt = r[s] & 31
            v = shift(m, op, r[d], cnt)
            if d:
                r[d] = v
            m.pc = nxt
            return (1, p2, "shift", shift_steps(cnt))
    return fn


def dec_alu_rr(m, pc, w, fn_no, d, s):
    """rd <- rd op rs for an ALU function number (draft 1a op 1, 1b op F)."""
    impl = ALU_IMPL[fn_no]
    nxt = (pc + 2) & M32
    p2 = pc & 2
    r = m.r
    if fn_no in (11, 12, 13, 14, 15):
        def fn(m):
            b = r[s]
            res = impl(m, r[d], b)
            if res is not None and d:
                r[d] = res
            m.pc = nxt
            return (1, p2) + alu_timing(fn_no, b)
        return fn
    key = (1, p2) + alu_timing(fn_no, 0)

    def fn(m):
        res = impl(m, r[d], r[s])
        if res is not None and d:
            r[d] = res
        m.pc = nxt
        return key
    return fn


def dec_alu_imm(m, pc, n, fn_no, d, v):
    """rd <- rd op #v (draft 1a op 8 and the small-immediate forms)."""
    impl = ALU_IMPL[fn_no]
    nxt = (pc + 2 * n) & M32
    key = (n, pc & 2) + alu_timing(fn_no, v)
    r = m.r

    def fn(m):
        res = impl(m, r[d], v)
        if res is not None and d:
            r[d] = res
        m.pc = nxt
        return key
    return fn


def dec_bcc(m, pc, w):
    cc = (w >> 8) & 15
    nxt = (pc + 2) & M32
    target = (nxt + 2 * sext8(w)) & M32
    p2 = pc & 2
    x = crosses(nxt, target)
    if cc == 15:
        key = (1, p2, "call", "rel", x)

        def fn(m):
            push(m, nxt)
            m.pc = target
            return key
        return fn
    k_taken = (1, p2, "br", 1, x)
    k_not = (1, p2, "br", 0, 0)

    def fn(m):
        if cond_true(m, cc):
            m.pc = target
            return k_taken
        m.pc = nxt
        return k_not
    return fn


def dec_jcc(m, pc, w):
    """Jcc/JMP/CALL with a 16-bit PC-relative or a 32-bit absolute target."""
    cc, k, z = (w >> 8) & 15, (w >> 4) & 15, w & 15
    if k > 1 or z:
        return illegal_fn
    p2 = pc & 2
    if k == 0:
        n = 2
        nxt = (pc + 4) & M32
        target = (nxt + 2 * sext16(m.parcel(pc + 2))) & M32
        how, x = "rel", crosses(nxt, target)
    else:
        n = 3
        nxt = (pc + 6) & M32
        target = (m.parcel(pc + 2) | (m.parcel(pc + 4) << 16)) & 0xFFFFFFFE
        how, x = "abs", 0
    if cc == 15:
        key = (n, p2, "call", how, x)

        def fn(m):
            push(m, nxt)
            m.pc = target
            return key
        return fn
    k_taken = (n, p2, "jmp", how, x)
    k_not = (n, p2, "br", 0, 0)

    def fn(m):
        if cc == 14 or cond_true(m, cc):
            m.pc = target
            return k_taken
        m.pc = nxt
        return k_not
    return fn


# ==========================================================================
# Shared assembler pieces


def W(op, a=0, b=0, c=0):
    return ((op & 15) << 12) | ((a & 15) << 8) | ((b & 15) << 4) | (c & 15)


def kinds(ops):
    out = []
    for o in ops:
        if isinstance(o, Reg): out.append("R")
        elif isinstance(o, Imm): out.append("I")
        elif isinstance(o, Mem): out.append("M")
        elif isinstance(o, Expr): out.append("E")
        else: out.append("?")
    return "".join(out)


def cond_code(suffix):
    s = suffix.upper()
    if s in COND_ALIAS:
        return COND_ALIAS[s]
    if s in COND:
        return COND.index(s)
    return None


def norm32(v):
    """A value as an unsigned 32-bit pattern; accepts -2^31..2^32-1."""
    if not -(1 << 31) <= v < (1 << 32):
        raise AsmError(f"value {v} doesn't fit in 32 bits")
    return v & M32


def fits_s(v, bits):
    v = s32(v) if 0 <= v < (1 << 32) and v >= (1 << 31) else v
    return -(1 << (bits - 1)) <= v < (1 << (bits - 1))


def as_signed(v):
    """Interpret a 32-bit pattern as signed (so 0xFFFFFF00 counts as -256)."""
    if (1 << 31) <= v < (1 << 32):
        return v - (1 << 32)
    return v


def reg_operand(ctx, op, what="register"):
    if not isinstance(op, Reg):
        ctx.error(f"expected a {what}")
    if op.n > 15:
        ctx.error(f"{op.name} can't be used here")
    return op.n


def asm_common(U, ops, ctx, opmap):
    """Instructions encoded the same way in both drafts; only the major
    opcodes differ (opmap: un, sh, bcc, jcc). Returns parcels, or None."""
    k = kinds(ops)
    op_bcc, op_jcc = opmap["bcc"], opmap["jcc"]

    # ---- system group ----
    if U in ("HALT", "NOP", "RET", "RTI", "EI", "DI"):
        if ops:
            ctx.error(f"{U} takes no operands")
        return [W(0, 0, 0, SYS_FN.index(U))]
    if U in ("SAVE", "RESTORE"):
        a, b = reg_range(ctx, ops)
        return [W(0, a, b, SYS_FN.index(U))]
    if U in ("MFSR", "MTSR"):
        if U == "MFSR":
            if len(ops) != 2:
                ctx.error("MFSR needs 'rd, n'")
            rd = reg_operand(ctx, ops[0])
            n = sr_number(ctx, ops[1])
            return [W(0, rd, n, 10)]
        if len(ops) != 2:
            ctx.error("MTSR needs 'n, rs'")
        n = sr_number(ctx, ops[0])
        rs = reg_operand(ctx, ops[1])
        return [W(0, n, rs, 11)]
    if U in ("MFF", "MFHI"):
        if k != "R":
            ctx.error(f"{U} needs one register")
        return [W(0, ops[0].n, 0 if U == "MFF" else 1, 10)]
    if U in ("MTF", "MTHI"):
        if k != "R":
            ctx.error(f"{U} needs one register")
        return [W(0, 0 if U == "MTF" else 1, ops[0].n, 11)]
    if U == "SWI":
        if len(ops) != 1 or not isinstance(ops[0], (Imm, Expr)):
            ctx.error("SWI needs '#n'")
        v, known = ctx.value(ops[0].expr)
        if known and not 0 <= v <= 255:
            ctx.error("SWI number must be 0-255")
        return [W(0, v >> 4, v, 12)]
    if U.startswith("SET") and cond_code(U[3:]) is not None:
        if k != "R":
            ctx.error(f"{U} needs one register")
        return [W(0, ops[0].n, cond_code(U[3:]), 13)]

    # ---- unary group ----
    if U in UN_FN:
        f = UN_FN.index(U)
        if k == "RR":
            return [W(opmap["un"], ops[0].n, ops[1].n, f)]
        if k == "R":
            return [W(opmap["un"], ops[0].n, ops[0].n, f)]
        ctx.error(f"{U} needs 'rd, rs' or 'rd'")

    # ---- shift group ----
    if U in SHIFT_FN:
        f = SHIFT_FN.index(U)
        if k == "RR":
            return [W(opmap["sh"], ops[0].n, ops[1].n, 8 | f)]
        if k == "RI":
            v, known = ctx.value(ops[1].expr)
            if known and not 0 <= v <= 31:
                ctx.error("shift count must be 0-31")
            return [W(opmap["sh"], ops[0].n, v & 15, ((v >> 4) & 1) << 2 | f)]
        ctx.error(f"{U} needs 'rd, #n' or 'rd, rs'")

    # ---- branches ----
    if U == "BSR" or (U[0] == "B" and len(U) == 3 and cond_code(U[1:]) is not None) or U == "BRA":
        cc = 15 if U == "BSR" else cond_code(U[1:])
        if k != "E":
            ctx.error(f"{U} needs a target address")
        target, known = ctx.target(ops[0].expr)
        off = target - (ctx.pc + 2)
        if known and off & 1:
            ctx.error(f"{U} target is at an odd address")
        if ctx.min_words > 1 or (known and not -256 <= off <= 254):
            return jcc(ctx, op_jcc, cc, ops[0].expr)
        return [W(op_bcc, cc) | ((off >> 1) & 0xFF)]
    if U in ("JMP", "CALL") and k == "E":
        return jcc(ctx, op_jcc, 14 if U == "JMP" else 15, ops[0].expr)
    if U in ("JMP", "CALL") and k == "R":
        return [W(0, 0, ops[0].n, SYS_FN.index(U))]
    if U[0] == "J" and cond_code(U[1:]) is not None:
        if k != "E":
            ctx.error(f"{U} needs a target address")
        return jcc(ctx, op_jcc, cond_code(U[1:]), ops[0].expr)
    return None


def jcc(ctx, op_jcc, cc, expr):
    target, known = ctx.target(expr)
    off = target - (ctx.pc + 4)
    if known and off & 1:
        ctx.error("jump target is at an odd address")
    if ctx.min_words > 2 or (known and not -65536 <= off <= 65534):
        t, known = ctx.value(expr)
        t = norm32(t) if known else 0
        ctx.fix(1, ABS32, expr)
        return [W(op_jcc, cc, 1, 0), t & 0xFFFF, t >> 16]
    ctx.fix(1, PC16H, expr, ctx.pc + 4)
    return [W(op_jcc, cc, 0, 0), (off >> 1) & 0xFFFF]


def reg_range(ctx, ops):
    """'r8-r11' (a RegRange) or a single register."""
    if len(ops) == 1 and isinstance(ops[0], Reg):
        a = b = ops[0].n
    elif len(ops) == 1 and isinstance(ops[0], RegRange):
        a, b = ops[0].a.n, ops[0].b.n
    else:
        ctx.error("expected a register range like r8-r11")
    if not 1 <= a <= b <= 14:
        ctx.error("register range must be within r1-r14, low to high")
    return a, b


def sr_number(ctx, op):
    if isinstance(op, Expr) and op.expr[0] == "sym" and op.expr[1].lower() in ("flags", "hi"):
        return 0 if op.expr[1].lower() == "flags" else 1
    if isinstance(op, (Imm, Expr)):
        v, _ = ctx.value(op.expr)
        if v not in SR_NAMES:
            ctx.error("special register must be 0 (flags) or 1 (hi)")
        return v
    ctx.error("expected a special register number")


# ==========================================================================
# Shared disassembler pieces


def R(n):
    return "sp" if n == 15 else f"r{n}"


def fmt_imm(v):
    """Canonical immediate: signed decimal if it fits 16 bits, else hex."""
    v &= M32
    sv = as_signed(v)
    return f"#{sv}" if -32768 <= sv <= 32767 else f"#0x{v:X}"


def sym(v, symbols):
    if symbols and v in symbols:
        return symbols[v]
    return f"0x{v:X}"


def dis_sys(w):
    a, b, f = (w >> 8) & 15, (w >> 4) & 15, w & 15
    if f >= len(SYS_FN):
        return None
    m = SYS_FN[f]
    if m in ("JMP", "CALL"):
        return f"{m} {R(b)}"
    if m in ("SAVE", "RESTORE"):
        if not 1 <= a <= b <= 14:
            return None
        return f"{m} {R(a)}-{R(b)}"
    if m == "MFSR":
        return f"MFSR {R(a)}, {SR_NAMES[b]}" if b in SR_NAMES else None
    if m == "MTSR":
        return f"MTSR {SR_NAMES[a]}, {R(b)}" if a in SR_NAMES else None
    if m == "SWI":
        return f"SWI #{(a << 4) | b}"
    if m == "SET":
        return f"SET{COND[b]} {R(a)}" if b < 15 else None
    return m


def dis_unary(w):
    d, s, f = (w >> 8) & 15, (w >> 4) & 15, w & 15
    if f >= len(UN_FN):
        return None
    return f"{UN_FN[f]} {R(d)}, {R(s)}"


def dis_shift(w):
    d, s, f = (w >> 8) & 15, (w >> 4) & 15, w & 15
    t = f >> 2
    if t == 3:
        return None
    if t == 2:
        return f"{SHIFT_FN[f & 3]} {R(d)}, {R(s)}"
    return f"{SHIFT_FN[f & 3]} {R(d)}, #{s + 16 * t}"


def dis_bcc(w, pc, symbols):
    cc = (w >> 8) & 15
    target = (pc + 2 + 2 * sext8(w)) & M32
    m = "BSR" if cc == 15 else "B" + COND[cc]
    return f"{m} {sym(target, symbols)}"


def dis_jcc(w, ext, pc, symbols):
    cc, k, z = (w >> 8) & 15, (w >> 4) & 15, w & 15
    if k > 1 or z:
        return None, 1
    m = "CALL" if cc == 15 else ("JMP" if cc == 14 else "J" + COND[cc])
    if k == 0:
        target = (pc + 4 + 2 * sext16(ext[0])) & M32
        return f"{m} {sym(target, symbols)}", 2
    target = (ext[0] | (ext[1] << 16)) & 0xFFFFFFFE
    return f"{m} {sym(target, symbols)}", 3
