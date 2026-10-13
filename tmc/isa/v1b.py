"""ISA draft 1b: 32-bit, 16-bit parcels, register + addressing mode (CISC-like).

See docs/isa-v1b.md. Main format `F D M R`: operation, register, mode,
register-or-constant for the mode. Shared parts live in v1common.
"""

from ..asm import Reg, Imm, Mem, Expr
from . import v1common as c
from .v1common import (M32, W, kinds, norm32, as_signed, sext8, sext16, crosses, nz,
                       ALU_IMPL, R, sym)

NAME = "v1b"
DESCRIPTION = "draft 1b: 32-bit registers, 16-bit parcels, register + addressing mode"
PROGRAM_DIR = "v1b"

REGISTERS = dict(c.REGISTERS)
REGISTERS["pc"] = 16            # only meaningful as [pc + label]
WIDE = True                     # tells the tools to use tmc.sim32
WORD_BYTES = 4
MEM_TOP = c.MEM_TOP
IO_BASE = c.IO_BASE
RESET_VECTOR = c.RESET_VECTOR
IRQ_VECTOR = c.IRQ_VECTOR

OP_SYS, OP_MOV, OP_ST, OP_LEA = 0x0, 0x1, 0x2, 0x3
OP_ADD, OP_SUB, OP_CMP, OP_AND, OP_OR, OP_XOR = 0x4, 0x5, 0x6, 0x7, 0x8, 0x9
OP_JCC, OP_JEA, OP_UN, OP_SH, OP_BCC, OP_RR = 0xA, 0xB, 0xC, 0xD, 0xE, 0xF
OPMAP = {"un": OP_UN, "sh": OP_SH, "bcc": OP_BCC, "jcc": OP_JCC}

# EA instructions: op -> ALU function number
EA_OPS = {"MOV": OP_MOV, "ST": OP_ST, "LEA": OP_LEA, "ADD": OP_ADD, "SUB": OP_SUB,
          "CMP": OP_CMP, "AND": OP_AND, "OR": OP_OR, "XOR": OP_XOR}
EA_NAMES = {v: k for k, v in EA_OPS.items()}
EA_ALU = {OP_MOV: 8, OP_ADD: 0, OP_SUB: 2, OP_CMP: 9, OP_AND: 4, OP_OR: 5, OP_XOR: 6}
RR_FN = ["ADC", "SBC", "BIC", "TST", "MULU", "MULS", "DIVU", "DIVS", "DIVUL"]
RR_ALU = [1, 3, 7, 10, 11, 12, 13, 14, 15]

SIZES = {"byte": 1, "half": 2, "word": 4, None: 4}
SIZE_NAME = {1: "byte ", 2: "half ", 4: ""}
SCALE_CODE = {1: 0, 2: 1, 4: 2, 8: 3}


# ==========================================================================
# Addressing modes


def ea_info(M, Rn, ext):
    """Decode a mode. Returns (operand, extra parcels) where operand is
    ('reg', r) | ('imm', value) | ('mem', base, disp, index, scale, size, timing kind)
    with base None for absolute and 'pc' for PC-relative, or None if reserved."""
    if M == 0:
        return ("reg", Rn), 0
    if M == 1:
        return ("imm", Rn), 0
    if M == 0xD:
        return ("imm", (-(Rn + 1)) & M32), 0
    if M == 2:
        return ("mem", Rn, 0, None, 1, 4, "r"), 0
    if M == 3:
        return ("mem", Rn, sext16(ext[0]), None, 1, 4, "rd"), 1
    if M == 4:
        return ("mem", 15, 4 * Rn, None, 1, 4, "rd"), 0
    if M == 5:
        e = ext[0]
        z = (e >> 8) & 3
        if z == 3:
            return None, 1
        return ("mem", Rn, sext8(e), e >> 12, 1 << ((e >> 10) & 3), (1, 2, 4)[z], "idx"), 1
    if M == 6:
        return ("mem", Rn, 0, None, 1, 4, "pi"), 0
    if M == 7:
        return ("mem", Rn, 0, None, 1, 4, "pd"), 0
    if M == 8:
        return ("mem", Rn, 0, None, 1, 1, "r"), 0
    if M == 9:
        return ("mem", Rn, sext16(ext[0]), None, 1, 1, "rd"), 1
    if M == 0xA:
        return ("mem", Rn, 0, None, 1, 1, "pi"), 0
    if M == 0xB:
        return ("mem", Rn, 0, None, 1, 2, "r"), 0
    if M == 0xC:
        return ("mem", Rn, sext16(ext[0]), None, 1, 2, "rd"), 1
    if M == 0xF:
        if Rn == 0:
            return ("imm", sext16(ext[0]) & M32), 1
        if Rn == 1:
            return ("imm", ext[0]), 1
        if Rn == 2:
            return ("imm", ext[0] << 16), 1
        if Rn == 3:
            return ("imm", ext[0] | (ext[1] << 16)), 2
        if 4 <= Rn <= 6:
            return ("mem", None, sext16(ext[0]) & M32, None, 1, (4, 1, 2)[Rn - 4], "abs"), 1
        if 7 <= Rn <= 9:
            return ("mem", None, ext[0] | (ext[1] << 16), None, 1, (4, 1, 2)[Rn - 7], "abs"), 2
        if 0xA <= Rn <= 0xC:
            return ("mem", "pc", sext16(ext[0]), None, 1, (4, 1, 2)[Rn - 0xA], "pc"), 1
        return None, 0
    return None, 0


def mode_size(M, Rn):
    """Extra parcels a mode needs (from the first parcel alone)."""
    if M in (3, 5, 9, 0xC):
        return 1
    if M == 0xF:
        return 2 if Rn in (3, 7, 8, 9) else (1 if Rn <= 0xC else 0)
    return 0


def size_of(w):
    op = w >> 12
    if 1 <= op <= 9 or op == OP_JEA:
        return 1 + mode_size((w >> 4) & 15, w & 15)
    if op == OP_JCC:
        k, f = (w >> 4) & 15, w & 15
        return 3 if k == 1 and f == 0 else (2 if k == 0 and f == 0 else 1)
    return 1


# ==========================================================================
# Decoder


def _reader(m, size):
    return m.rd32 if size == 4 else (m.rd16 if size == 2 else m.rd8)


def _addr_fn(r, opnd, nxt):
    """Returns (address function m -> (a, x), post-update function or None)."""
    _, base, disp, index, scale, size, tk = opnd
    if tk == "r":
        return (lambda: (r[base], 0)), None
    if tk == "rd":
        def f():
            b = r[base]
            a = (b + disp) & M32
            return a, crosses(b, a)
        return f, None
    if tk == "abs":
        a0 = disp & M32
        return (lambda: (a0, 0)), None
    if tk == "pc":
        a1 = (nxt + disp) & M32
        x1 = crosses(nxt, a1)
        return (lambda: (a1, x1)), None
    if tk == "idx":
        def f():
            b = r[base]
            a = (b + disp + r[index] * scale) & M32
            return a, crosses(b, a)
        return f, None
    if tk == "pi":
        def post(a):
            if base:
                r[base] = (a + size) & M32
        return (lambda: (r[base], 0)), post

    def f():
        b = r[base]
        a = (b - size) & M32
        return a, crosses(b, a)

    def post(a):
        if base:
            r[base] = a
    return f, post


def decode(m, pc):
    w = m.parcel(pc)
    op = w >> 12
    d, M, Rn = (w >> 8) & 15, (w >> 4) & 15, w & 15
    if op == OP_SYS:
        return c.dec_sys(m, pc, w), 1
    if op == OP_UN:
        return c.dec_unary(m, pc, w), 1
    if op == OP_SH:
        return c.dec_shift(m, pc, w), 1
    if op == OP_BCC:
        return c.dec_bcc(m, pc, w), 1
    if op == OP_JCC:
        k, f = M, Rn
        n = 3 if k == 1 and f == 0 else (2 if k == 0 and f == 0 else 1)
        return c.dec_jcc(m, pc, w), n
    if op == OP_RR:
        f = w & 15
        if f >= len(RR_FN):
            return c.illegal_fn, 1
        return c.dec_alu_rr(m, pc, w, RR_ALU[f], d, M), 1
    # EA instructions (ops 1-9 and B)
    n = 1 + mode_size(M, Rn)
    ext = [m.parcel(pc + 2 * i) for i in range(1, n)] + [0, 0]
    opnd, _ = ea_info(M, Rn, ext)
    if opnd is None:
        return c.illegal_fn, n
    nxt = (pc + 2 * n) & M32
    p2 = pc & 2
    r = m.r
    cls = opnd[0]

    if op == OP_JEA:
        if d > 1 or (cls == "mem" and opnd[5] != 4):
            return c.illegal_fn, n
        call = d == 1
        if cls == "reg":
            key = (n, p2, "call" if call else "jmp", "reg", 0)

            def fn(m):
                t = r[Rn] & 0xFFFFFFFE
                if call:
                    c.push(m, nxt)
                m.pc = t
                return key
            return fn, n
        if cls == "imm":
            t0 = opnd[1] & 0xFFFFFFFE
            key = (n, p2, "call" if call else "jmp", "abs", 0)

            def fn(m):
                if call:
                    c.push(m, nxt)
                m.pc = t0
                return key
            return fn, n
        addr, post = _addr_fn(r, opnd, nxt)
        tk = opnd[6]
        kind = "callm" if call else "jmpm"

        def fn(m):
            a, x = addr()
            t = m.rd32(a) & 0xFFFFFFFE
            if post:
                post(a)
            if call:
                c.push(m, nxt)
            m.pc = t
            return (n, p2, kind, tk, x)
        return fn, n

    if op == OP_ST:
        if cls != "mem":
            return c.illegal_fn, n
        addr, post = _addr_fn(r, opnd, nxt)
        size, tk = opnd[5], opnd[6]
        wr = m.wr32 if size == 4 else (m.wr16 if size == 2 else m.wr8)
        mask = (1 << (8 * size)) - 1

        def fn(m):
            v = r[d]
            a, x = addr()
            wr(a, v & mask)
            if post:
                post(a)
            m.pc = nxt
            return (n, p2, "st", tk, size, x)
        return fn, n

    if op == OP_LEA:
        if cls != "mem" or opnd[6] in ("pi", "pd"):
            return c.illegal_fn, n
        addr, _ = _addr_fn(r, opnd, nxt)
        tk = opnd[6]

        def fn(m):
            a, x = addr()
            if d:
                r[d] = a
            m.pc = nxt
            return (n, p2, "lea", tk, x)
        return fn, n

    # MOV and the ALU operations
    fno = EA_ALU[op]
    impl = ALU_IMPL[fno]
    wb = 1 if c.ALU_WRITES[fno] else 0
    if cls == "reg":
        key = (n, p2, "alu", wb)

        def fn(m):
            res = impl(m, r[d], r[Rn])
            if res is not None and d:
                r[d] = res
            m.pc = nxt
            return key
        return fn, n
    if cls == "imm":
        return c.dec_alu_imm(m, pc, n, fno, d, opnd[1] & M32), n
    addr, post = _addr_fn(r, opnd, nxt)
    size, tk = opnd[5], opnd[6]
    rd_mem = _reader(m, size)
    if op == OP_MOV:
        def fn(m):
            a, x = addr()
            v = rd_mem(a)
            if post:
                post(a)
            nz(m, v)
            if d:
                r[d] = v
            m.pc = nxt
            return (n, p2, "ld", tk, size, x)
        return fn, n

    def fn(m):
        a, x = addr()
        v = rd_mem(a)
        if post:
            post(a)
        res = impl(m, r[d], v)
        if res is not None and d:
            r[d] = res
        m.pc = nxt
        return (n, p2, "op", tk, size, x, wb)
    return fn, n


# ==========================================================================
# Assembler hook


def _imm_mode(ctx, expr, min_ext, n_before=1):
    """Encode a constant operand. Returns (M, R, ext parcels)."""
    v, known = ctx.value(expr)
    if known:
        v = norm32(v)
    sv = as_signed(v)
    if min_ext == 0:
        if 0 <= sv <= 15:
            return 1, sv, []
        if -16 <= sv <= -1:
            return 0xD, -sv - 1, []
    if min_ext <= 1:
        if -32768 <= sv <= 32767:
            ctx.fix(n_before, c.ABS16S, expr)
            return 0xF, 0, [v & 0xFFFF]
        if v <= 0xFFFF:
            return 0xF, 1, [v]
        if v & 0xFFFF == 0:
            return 0xF, 2, [v >> 16]
    ctx.fix(n_before, c.ABS32, expr)
    return 0xF, 3, [v & 0xFFFF, v >> 16]


def _mem_mode(ctx, mem, min_ext, n_before=1):
    """Encode a memory operand. Returns (M, R, ext parcels)."""
    size = SIZES[mem.size]
    if mem.base is not None and mem.base.n == 16:            # [pc + label]
        if mem.index is not None or mem.postinc or mem.predec:
            ctx.error("[pc + ...] takes only a label")
        target, known = (ctx.target(mem.disp) if mem.disp is not None else (0, True))
        off = target - (ctx.pc + 2 * (n_before + 1))
        if known and not -32768 <= off <= 32767:
            ctx.error("PC-relative target out of range (±32 KB)")
        if mem.disp is not None:
            ctx.fix(n_before, c.PC16, mem.disp, ctx.pc + 2 * (n_before + 1))
        return 0xF, {4: 0xA, 1: 0xB, 2: 0xC}[size], [off & 0xFFFF]
    if mem.postinc or mem.predec:
        if mem.postinc:
            if size == 4:
                return 6, mem.base.n, []
            if size == 1:
                return 0xA, mem.base.n, []
            ctx.error("there is no half [r]+ mode")
        if size != 4:
            ctx.error("-[r] only exists for words")
        return 7, mem.base.n, []
    if mem.index is not None:
        if mem.scale not in SCALE_CODE:
            ctx.error("index scale must be 1, 2, 4 or 8")
        if mem.index.n > 15:
            ctx.error("bad index register")
        d8, known = (ctx.value(mem.disp) if mem.disp is not None else (0, True))
        if known and not -128 <= as_signed(norm32(d8)) <= 127:
            ctx.error("the indexed mode's displacement must fit in 8 bits")
        base = mem.base.n if mem.base is not None else 0
        z = {1: 0, 2: 1, 4: 2}[size]
        e = (mem.index.n << 12) | (SCALE_CODE[mem.scale] << 10) | (z << 8) | (d8 & 0xFF)
        return 5, base, [e]
    disp, known = (ctx.value(mem.disp) if mem.disp is not None else (0, True))
    if known:
        disp = norm32(disp)
    sd = as_signed(disp)
    if mem.base is None:                                     # absolute
        if min_ext <= 1 and (not known or -32768 <= sd <= 32767):
            if mem.disp is not None:
                ctx.fix(n_before, c.ABS16S, mem.disp)
            return 0xF, {4: 4, 1: 5, 2: 6}[size], [disp & 0xFFFF]
        off = disp - (ctx.pc + 2 * (n_before + 1))
        if min_ext <= 1 and known and ctx.abs_pc and -32768 <= off <= 32767:
            return 0xF, {4: 0xA, 1: 0xB, 2: 0xC}[size], [off & 0xFFFF]
        ctx.fix(n_before, c.ABS32, mem.disp)
        return 0xF, {4: 7, 1: 8, 2: 9}[size], [disp & 0xFFFF, disp >> 16]
    b = mem.base.n
    if known and not -32768 <= sd <= 32767:
        ctx.error("displacement doesn't fit in 16 bits: compute the address in a register")
    if min_ext == 0 and known and sd == 0:
        return {4: 2, 1: 8, 2: 0xB}[size], b, []
    if min_ext == 0 and known and b == 15 and size == 4 and 0 <= sd <= 60 and sd % 4 == 0:
        return 4, sd // 4, []
    if mem.disp is not None:
        ctx.fix(n_before, c.ABS16S, mem.disp)
    return {4: 3, 1: 9, 2: 0xC}[size], b, [disp & 0xFFFF]


def _ea(ctx, op, n_before=1):
    min_ext = max(0, ctx.min_words - n_before)
    if isinstance(op, Reg):
        if op.n > 15:
            ctx.error("pc can only be used as [pc + label]")
        return 0, op.n, []
    if isinstance(op, Imm):
        return _imm_mode(ctx, op.expr, min_ext, n_before)
    if isinstance(op, Mem):
        return _mem_mode(ctx, op, min_ext, n_before)
    ctx.error("expected a register, #constant or [memory] operand")


def assemble(name, ops, ctx):
    U = name.upper()
    k = kinds(ops)

    if U == "PUSH":
        if k != "R":
            ctx.error("PUSH needs one register")
        return assemble("ST", [ops[0], Mem(Reg(15, "sp"), None, predec=True)], ctx)
    if U == "POP":
        if k != "R":
            ctx.error("POP needs one register")
        return assemble("MOV", [ops[0], Mem(Reg(15, "sp"), None, postinc=True)], ctx)
    if U == "LI":
        if k not in ("RE", "RI"):
            ctx.error("LI needs 'rd, value'")
        return assemble("MOV", [ops[0], Imm(ops[1].expr)], ctx)
    if U in ("JMP", "CALL") and k in ("M", "I"):
        M, Rn, ext = _ea(ctx, ops[0])
        if isinstance(ops[0], Mem) and SIZES[ops[0].size] != 4:
            ctx.error(f"{U} through memory needs a word")
        return [W(OP_JEA, 1 if U == "CALL" else 0, M, Rn)] + ext

    out = c.asm_common(U, ops, ctx, OPMAP)
    if out is not None:
        return out

    if U in EA_OPS:
        if len(ops) != 2 or not isinstance(ops[0], Reg):
            ctx.error(f"{U} needs 'rd, operand'")
        rd = c.reg_operand(ctx, ops[0])
        src = ops[1]
        if U == "LEA" and isinstance(src, Expr):
            src = Mem(None, src.expr)
        if isinstance(src, Expr):
            ctx.error(f"{U}: write #value for a constant or [address] for memory")
        M, Rn, ext = _ea(ctx, src)
        if U == "ST" and M in (0, 1, 0xD) or (U == "ST" and M == 0xF and Rn <= 3):
            ctx.error("ST needs a memory operand")
        if U == "LEA" and (M in (0, 1, 0xD, 6, 7, 0xA) or (M == 0xF and Rn <= 3)):
            ctx.error("LEA needs a memory operand without auto-increment")
        return [W(EA_OPS[U], rd, M, Rn)] + ext

    if U in RR_FN:
        if k != "RR":
            ctx.error(f"{U} only works on two registers in draft 1b")
        return [W(OP_RR, ops[0].n, ops[1].n, RR_FN.index(U))]
    if U in ("MVI", "ADDI", "CMPI"):
        ctx.error(f"draft 1b has no {U}: use MOV/ADD/CMP with #value")
    ctx.error(f"unknown instruction {name}")


# ==========================================================================
# Disassembler


_fmt_imm = c.fmt_imm


def dis_ea(M, Rn, ext, nxt, symbols):
    opnd, _ = ea_info(M, Rn, ext)
    if opnd is None:
        return None
    if opnd[0] == "reg":
        return R(Rn)
    if opnd[0] == "imm":
        return _fmt_imm(opnd[1])
    _, base, disp, index, scale, size, tk = opnd
    sz = SIZE_NAME[size]
    if tk == "abs":
        return f"{sz}[{sym(disp & M32, symbols)}]"
    if tk == "pc":
        return f"{sz}[{sym((nxt + disp) & M32, symbols)}]"
    if tk == "pi":
        return f"{sz}[{R(base)}]+"
    if tk == "pd":
        return f"{sz}-[{R(base)}]"
    parts = R(base)
    if index is not None:
        parts += f" + {R(index)}" + (f"*{scale}" if scale != 1 else "")
    if disp:
        parts += f" - {-disp}" if disp < 0 else f" + {disp}"
    return f"{sz}[{parts}]"


def disassemble(ws, pc=0, symbols=None):
    w = ws[0]
    ext = list(ws[1:]) + [0, 0]
    op = w >> 12
    d, M, Rn = (w >> 8) & 15, (w >> 4) & 15, w & 15
    bad = (f".half 0x{w:04X} ; illegal", 1)
    if op == OP_SYS:
        t = c.dis_sys(w)
        return (t, 1) if t else bad
    if op == OP_UN:
        t = c.dis_unary(w)
        return (t, 1) if t else bad
    if op == OP_SH:
        t = c.dis_shift(w)
        return (t, 1) if t else bad
    if op == OP_BCC:
        return c.dis_bcc(w, pc, symbols), 1
    if op == OP_JCC:
        t, n = c.dis_jcc(w, ext, pc, symbols)
        return (t, n) if t else bad
    if op == OP_RR:
        f = w & 15
        if f >= len(RR_FN):
            return bad
        return f"{RR_FN[f]} {R(d)}, {R(M)}", 1
    n = size_of(w)
    nxt = (pc + 2 * n) & M32
    opnd, _ = ea_info(M, Rn, ext)
    if opnd is None:
        return bad
    t = dis_ea(M, Rn, ext, nxt, symbols)
    if op == OP_JEA:
        if d > 1 or (opnd[0] == "mem" and opnd[5] != 4):
            return bad
        return f"{'CALL' if d else 'JMP'} {t}", n
    if op == OP_ST and opnd[0] != "mem":
        return bad
    if op == OP_LEA and (opnd[0] != "mem" or opnd[6] in ("pi", "pd")):
        return bad
    return f"{EA_NAMES[op]} {R(d)}, {t}", n


MODE_CLASS = {"reg": "r", "r": "[r]", "rd": "[r+d]", "abs": "[abs]", "pc": "[pc+d]",
              "idx": "[r+x]", "pi": "[r]+", "pd": "-[r]"}


def mode_class(ws):
    """Short description of the operand mode, for statistics."""
    w = ws[0]
    M, Rn = (w >> 4) & 15, w & 15
    opnd, _ = ea_info(M, Rn, list(ws[1:]) + [0, 0])
    if opnd is None:
        return "?"
    if opnd[0] == "reg":
        return "r"
    if opnd[0] == "imm":
        return "#q" if M in (1, 0xD) else ("#i32" if Rn == 3 else "#i16")
    tk = opnd[6]
    if M == 4:
        tk_name = "[sp+n]"
    else:
        tk_name = MODE_CLASS[tk]
    return {1: "b", 2: "h", 4: ""}[opnd[5]] + tk_name


def kind(ws):
    w = ws[0]
    op, d = w >> 12, (w >> 8) & 15
    if op == OP_SYS:
        if (w & 15) < len(c.SYS_FN):
            k = c.SYS_FN[w & 15]
            return "SETcc" if k == "SET" else k
        return "illegal"
    if op == OP_UN:
        return c.UN_FN[w & 15] if (w & 15) < len(c.UN_FN) else "illegal"
    if op == OP_SH:
        f = w & 15
        return c.SHIFT_FN[f & 3] + (" reg" if f >> 2 == 2 else "")
    if op == OP_BCC:
        return "BSR" if d == 15 else ("BRA" if d == 14 else "Bcc")
    if op == OP_JCC:
        return "CALL" if d == 15 else ("JMP" if d == 14 else "Jcc")
    if op == OP_RR:
        return RR_FN[w & 15] if (w & 15) < len(RR_FN) else "illegal"
    name = "JMP" if op == OP_JEA and d == 0 else ("CALL" if op == OP_JEA else EA_NAMES[op])
    return f"{name} {mode_class(ws)}"
