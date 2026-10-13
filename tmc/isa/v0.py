"""ISA draft 0: 16 registers, one hex digit per field.

Everything ISA-specific lives here: register names, the assembler hook,
the disassembler and the instruction semantics used by the simulator.
See docs/isa-v0.md for the human-readable spec.

Word layout: op(15:12) a(11:8) b(7:4) c(3:0)
  a = rd (destination) or condition, b = rs (source/base), c = fn or offset.
"""

from ..asm import Reg, Imm, Mem, Expr

NAME = "v0"
DESCRIPTION = "draft 0: 16x16-bit registers, 4-4-4-4 encoding, load/store"
PROGRAM_DIR = "v0"

REGISTERS = {f"r{i}": i for i in range(16)}
REGISTERS["sp"] = 15

# I/O page: addresses at or above this go to devices, not RAM.
IO_BASE = 0xFF00

RESET_VECTOR = 0x0000
IRQ_VECTOR = 0x0004
TRAP_VECTOR = 0x0008

# Flag word layout (MFF/MTF, interrupt frames)
F_V, F_C, F_Z, F_N, F_I = 0, 1, 2, 3, 4

SYS_FN = ["HALT", "NOP", "JMP", "CALL", "RET", "PUSH", "POP", "RTI",
          "EI", "DI", "MFF", "MTF", "SWI"]
ALU_FN = ["ADD", "ADC", "SUB", "SBC", "AND", "OR", "XOR", "BIC", "MOV", "CMP", "TST"]
UN_FN = ["NOT", "NEG", "INC", "DEC", "SHL", "SHR", "ASR", "RLC", "RRC",
         "SWAB", "SXT", "ZXT"]
MEM_FN = ["LD", "ST", "LDB", "STB", "LEA"]
COND = ["EQ", "NE", "CS", "CC", "MI", "PL", "VS", "VC",
        "HI", "LS", "GE", "LT", "GT", "LE", "RA"]  # 15 = link (BSR/CALL)
COND_ALIAS = {"HS": 2, "LO": 3, "AL": 14}

OP_SYS, OP_ALU, OP_UN, OP_BCC = 0x0, 0x1, 0x2, 0x3
OP_LD, OP_ST, OP_LDB, OP_STB = 0x4, 0x5, 0x6, 0x7
OP_ALUI, OP_JCC, OP_MEML, OP_EAE = 0x8, 0x9, 0xA, 0xB
OP_MVI, OP_ADDI, OP_CMPI, OP_RSVD = 0xC, 0xD, 0xE, 0xF


def W(op, a=0, b=0, c=0):
    return (op << 12) | ((a & 15) << 8) | ((b & 15) << 4) | (c & 15)


def sext8(x):
    x &= 0xFF
    return x - 0x100 if x & 0x80 else x


# ==========================================================================
# Assembler hook


def _cond_code(suffix):
    s = suffix.upper()
    if s in COND_ALIAS:
        return COND_ALIAS[s]
    if s in COND:
        return COND.index(s)
    return None


def _kinds(ops):
    out = []
    for o in ops:
        if isinstance(o, Reg): out.append("R")
        elif isinstance(o, Imm): out.append("I")
        elif isinstance(o, Mem): out.append("M")
        elif isinstance(o, Expr): out.append("E")
        else: out.append("?")
    return "".join(out)


def _fits_s8(v):
    return -128 <= v <= 127


def _imm16(ctx, expr, what="immediate"):
    v, known = ctx.value(expr)
    if known and not -32768 <= v <= 0xFFFF:
        ctx.error(f"{what} {v} doesn't fit in 16 bits")
    return v & 0xFFFF, known


def _simm8(ctx, expr):
    v, known = ctx.value(expr)
    if known:
        if 0xFF80 <= v <= 0xFFFF:
            v -= 0x10000
        if not _fits_s8(v):
            ctx.error(f"value {v} doesn't fit in a signed 8-bit immediate (-128..127)")
    return v & 0xFF


def assemble(name, ops, ctx):
    U = name.upper()
    k = _kinds(ops)

    def bad():
        ctx.error(f"bad operands for {U}: expected {expect.get(U, '?')}")

    expect = {}

    # ---- system group (op 0) ----
    if U in ("HALT", "NOP", "RET", "RTI", "EI", "DI", "SWI"):
        if ops:
            ctx.error(f"{U} takes no operands")
        return [W(OP_SYS, 0, 0, SYS_FN.index(U))]
    if U in ("PUSH", "MTF"):
        if k != "R":
            ctx.error(f"{U} needs one register")
        return [W(OP_SYS, 0, ops[0].n, SYS_FN.index(U))]
    if U in ("POP", "MFF"):
        if k != "R":
            ctx.error(f"{U} needs one register")
        return [W(OP_SYS, ops[0].n, 0, SYS_FN.index(U))]
    if U in ("JMP", "CALL"):
        if k == "R":
            return [W(OP_SYS, 0, ops[0].n, SYS_FN.index(U))]
        if k == "E":
            v, _ = _imm16(ctx, ops[0].expr, "address")
            return [W(OP_JCC, 14 if U == "JMP" else 15), v]
        ctx.error(f"{U} needs a register or an address")

    # ---- two-operand ALU (op 1 / op 8, short forms C/D/E) ----
    if U in ALU_FN:
        fn = ALU_FN.index(U)
        if k == "RR":
            return [W(OP_ALU, ops[0].n, ops[1].n, fn)]
        if k == "RI":
            rd = ops[0].n
            v, known = ctx.value(ops[1].expr)
            if known and 0xFF80 <= v <= 0xFFFF:
                v -= 0x10000
            short = {"MOV": OP_MVI, "ADD": OP_ADDI, "CMP": OP_CMPI}.get(U)
            if short is not None and not ctx.long and _fits_s8(v):
                return [W(short, rd) | (v & 0xFF)]
            v, _ = _imm16(ctx, ops[1].expr)
            return [W(OP_ALUI, rd, 0, fn), v]
        ctx.error(f"{U} needs 'rd, rs' or 'rd, #imm'")
    if U == "LI":
        if k != "RE" and k != "RI":
            ctx.error("LI needs 'rd, value'")
        return assemble("MOV", [ops[0], Imm(ops[1].expr)], ctx)
    if U in ("MVI", "ADDI", "CMPI"):
        if k not in ("RE", "RI"):
            ctx.error(f"{U} needs 'rd, imm8'")
        op = {"MVI": OP_MVI, "ADDI": OP_ADDI, "CMPI": OP_CMPI}[U]
        return [W(op, ops[0].n) | _simm8(ctx, ops[1].expr)]

    # ---- unary (op 2) ----
    if U in UN_FN:
        fn = UN_FN.index(U)
        if k == "RR":
            return [W(OP_UN, ops[0].n, ops[1].n, fn)]
        if k == "R":
            return [W(OP_UN, ops[0].n, ops[0].n, fn)]
        ctx.error(f"{U} needs 'rd, rs' or 'rd'")

    # ---- loads and stores ----
    if U in MEM_FN:
        if k != "RM":
            ctx.error(f"{U} needs 'reg, [base + offset]'")
        if ops[1].index is not None:
            ctx.error("register + register addressing doesn't exist: add the registers "
                      "first, or use [label + reg] for a static array")
        if not ops[1].plain():
            ctx.error("draft 0 has no size keywords or auto-increment: use [base + offset]")
        rd = ops[0].n
        base = ops[1].base.n if ops[1].base else 0
        if ops[1].disp is None:
            disp, known = 0, True
        else:
            disp, known = ctx.value(ops[1].disp)
        if known and not -32768 <= disp <= 0xFFFF:
            ctx.error(f"offset {disp} doesn't fit in 16 bits")
        if not ctx.long and U != "LEA":
            if U in ("LD", "ST") and 0 <= disp <= 30 and disp % 2 == 0:
                return [W(OP_LD if U == "LD" else OP_ST, rd, base, disp // 2)]
            if U in ("LDB", "STB") and 0 <= disp <= 15:
                return [W(OP_LDB if U == "LDB" else OP_STB, rd, base, disp)]
        return [W(OP_MEML, rd, base, MEM_FN.index(U)), disp & 0xFFFF]

    # ---- branches: B<cc> (relative) and J<cc> (absolute) ----
    # An out-of-range Bcc becomes Jcc and BSR becomes CALL (same cycles, one
    # more word), like the other short/long forms.
    if U == "BSR" or (U[0] == "B" and _cond_code(U[1:]) is not None):
        cc = 15 if U == "BSR" else _cond_code(U[1:])
        if k != "E":
            ctx.error(f"{U} needs a target address")
        target, known = ctx.value(ops[0].expr)
        off = target - (ctx.pc + 2)
        if known and off & 1:
            ctx.error(f"{U} target is at an odd address")
        if ctx.long or (known and not -256 <= off <= 254):
            v, _ = _imm16(ctx, ops[0].expr, "address")
            return [W(OP_JCC, cc), v]
        return [W(OP_BCC, cc) | ((off >> 1) & 0xFF)]
    if U[0] == "J" and _cond_code(U[1:]) is not None:
        cc = _cond_code(U[1:])
        if k != "E":
            ctx.error(f"{U} needs a target address")
        v, _ = _imm16(ctx, ops[0].expr, "address")
        return [W(OP_JCC, cc), v]

    ctx.error(f"unknown instruction {name}")


# ==========================================================================
# Disassembler


def _sym(v, symbols):
    if symbols and v in symbols:
        return symbols[v]
    return f"0x{v:04X}"


def disassemble(w, nxt=0, pc=0, symbols=None):
    """Return (text, size_in_words) for the instruction word w at pc.

    nxt is the following word (used by two-word instructions).
    symbols maps address -> name for nicer output.
    """
    op, a, b, c = w >> 12, (w >> 8) & 15, (w >> 4) & 15, w & 15
    R = lambda n: "sp" if n == 15 else f"r{n}"
    if op == OP_SYS:
        if c >= len(SYS_FN):
            return f".word 0x{w:04X} ; illegal", 1
        m = SYS_FN[c]
        if m in ("JMP", "CALL", "PUSH", "MTF"):
            return f"{m} {R(b)}", 1
        if m in ("POP", "MFF"):
            return f"{m} {R(a)}", 1
        return m, 1
    if op == OP_ALU:
        if c >= len(ALU_FN):
            return f".word 0x{w:04X} ; illegal", 1
        return f"{ALU_FN[c]} {R(a)}, {R(b)}", 1
    if op == OP_UN:
        if c >= len(UN_FN):
            return f".word 0x{w:04X} ; illegal", 1
        return f"{UN_FN[c]} {R(a)}, {R(b)}", 1
    if op == OP_BCC:
        target = (pc + 2 + 2 * sext8(w)) & 0xFFFF
        m = "BSR" if a == 15 else "B" + COND[a]
        return f"{m} {_sym(target, symbols)}", 1
    if op in (OP_LD, OP_ST, OP_LDB, OP_STB):
        m = ["LD", "ST", "LDB", "STB"][op - OP_LD]
        off = c * 2 if op in (OP_LD, OP_ST) else c
        return f"{m} {R(a)}, [{R(b)}{' + ' + str(off) if off else ''}]", 1
    if op == OP_ALUI:
        if c >= len(ALU_FN):
            return f".word 0x{w:04X} ; illegal", 1
        return f"{ALU_FN[c]} {R(a)}, #0x{nxt:04X}", 2
    if op == OP_JCC:
        m = "CALL" if a == 15 else ("JMP" if a == 14 else "J" + COND[a])
        return f"{m} {_sym(nxt, symbols)}", 2
    if op == OP_MEML:
        if c >= len(MEM_FN):
            return f".word 0x{w:04X} ; illegal", 1
        if b == 0:
            return f"{MEM_FN[c]} {R(a)}, [{_sym(nxt, symbols)}]", 2
        return f"{MEM_FN[c]} {R(a)}, [{R(b)} + 0x{nxt:04X}]", 2
    if op in (OP_MVI, OP_ADDI, OP_CMPI):
        m = {OP_MVI: "MVI", OP_ADDI: "ADDI", OP_CMPI: "CMPI"}[op]
        return f"{m} {R(a)}, {sext8(w)}", 1
    return f".word 0x{w:04X} ; illegal", 1


def size_of(w):
    """Instruction length in words, as the hardware sees it."""
    op = w >> 12
    if op in (OP_ALUI, OP_JCC):
        return 2
    if op == OP_MEML and (w & 15) < len(MEM_FN):
        return 2
    return 1


def kind(w):
    """Short mnemonic used for instruction-mix statistics."""
    op, a, c = w >> 12, (w >> 8) & 15, w & 15
    if op == OP_SYS:
        return SYS_FN[c] if c < len(SYS_FN) else "illegal"
    if op == OP_ALU:
        return ALU_FN[c] if c < len(ALU_FN) else "illegal"
    if op == OP_UN:
        return UN_FN[c] if c < len(UN_FN) else "illegal"
    if op == OP_BCC:
        return "BSR" if a == 15 else ("BRA" if a == 14 else "Bcc")
    if op in (OP_LD, OP_ST, OP_LDB, OP_STB):
        return ["LD", "ST", "LDB", "STB"][op - OP_LD]
    if op == OP_ALUI:
        return (ALU_FN[c] + " #imm16") if c < len(ALU_FN) else "illegal"
    if op == OP_JCC:
        return "CALL" if a == 15 else ("JMP" if a == 14 else "Jcc")
    if op == OP_MEML:
        return (MEM_FN[c] + " long") if c < len(MEM_FN) else "illegal"
    return {OP_MVI: "MVI", OP_ADDI: "ADDI", OP_CMPI: "CMPI"}.get(op, "illegal")


# ==========================================================================
# Semantics
#
# `m` is a tmc.sim.Machine: m.r[16], m.pc, flags m.n m.z m.c m.v m.i,
# memory via m.rd16/m.wr16/m.rd8/m.wr8 (which handle the I/O page).


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
    elif base == 5: t = int(m.n == m.v)
    elif base == 6: t = (m.z ^ 1) & int(m.n == m.v)
    else: t = 1
    return t ^ (cc & 1)


def _add(m, a, b, cin):
    r = a + b + cin
    res = r & 0xFFFF
    m.c = r >> 16
    m.v = (((a ^ res) & (b ^ res)) >> 15) & 1
    m.n = res >> 15
    m.z = int(res == 0)
    return res


def _nz(m, res):
    m.n = res >> 15
    m.z = int(res == 0)
    return res


def alu(m, fn, a, b):
    """Two-operand ALU op. Returns (result, writes_rd)."""
    if fn == 0: return _add(m, a, b, 0), True
    if fn == 1: return _add(m, a, b, m.c), True
    if fn == 2: return _add(m, a, b ^ 0xFFFF, 1), True
    if fn == 3: return _add(m, a, b ^ 0xFFFF, m.c), True
    if fn == 4: return _nz(m, a & b), True
    if fn == 5: return _nz(m, a | b), True
    if fn == 6: return _nz(m, a ^ b), True
    if fn == 7: return _nz(m, a & ~b & 0xFFFF), True
    if fn == 8: return _nz(m, b), True
    if fn == 9: return _add(m, a, b ^ 0xFFFF, 1), False
    if fn == 10: return _nz(m, a & b), False
    return None, False


def unary(m, fn, x):
    if fn == 0: return _nz(m, x ^ 0xFFFF)
    if fn == 1: return _add(m, 0, x ^ 0xFFFF, 1)
    if fn == 2: return _add(m, x, 1, 0)
    if fn == 3: return _add(m, x, 0xFFFE, 1)
    if fn == 4: return _add(m, x, x, 0)
    if fn in (5, 6, 8):
        top = {5: 0, 6: x & 0x8000, 8: m.c << 15}[fn]
        m.c = x & 1
        m.v = 0
        return _nz(m, (x >> 1) | top)
    if fn == 7: return _add(m, x, x, m.c)
    if fn == 9: return _nz(m, ((x >> 8) | (x << 8)) & 0xFFFF)
    if fn == 10: return _nz(m, (x & 0xFF) | (0xFF00 if x & 0x80 else 0))
    if fn == 11: return _nz(m, x & 0xFF)
    return None


def push(m, v):
    sp = (m.r[15] - 2) & 0xFFFF
    m.r[15] = sp
    m.wr16(sp, v)


def pop(m):
    sp = m.r[15]
    v = m.rd16(sp)
    m.r[15] = (sp + 2) & 0xFFFF
    return v


def enter_interrupt(m, vector):
    """IRQ or trap: push PC, push flags, disable interrupts, jump to vector."""
    push(m, m.pc)
    push(m, flags_word(m))
    m.i = 0
    m.pc = vector


def step(m):
    """Execute one instruction. Returns (word, taken) for timing/statistics.

    `taken` is True/False for conditional branches and jumps, None otherwise.
    """
    r = m.r
    pc = m.pc
    w = m.rd16(pc)
    pc = (pc + 2) & 0xFFFF
    op = w >> 12
    a = (w >> 8) & 15
    b = (w >> 4) & 15
    c = w & 15
    taken = None

    if op == OP_ALU or op == OP_ALUI:
        if op == OP_ALUI:
            src = m.rd16(pc)
            pc = (pc + 2) & 0xFFFF
        else:
            src = r[b]
        res, wr = alu(m, c, r[a], src)
        if res is None:
            m.pc = pc
            m.illegal(w)
            enter_interrupt(m, TRAP_VECTOR)
            return w, None
        if wr and a:
            r[a] = res
    elif op == OP_LD or op == OP_LDB or op == OP_ST or op == OP_STB:
        addr = (r[b] + (c << 1 if op <= OP_ST else c)) & 0xFFFF
        if op == OP_LD:
            if a: r[a] = _nz(m, m.rd16(addr))
            else: _nz(m, m.rd16(addr))
        elif op == OP_LDB:
            v = _nz(m, m.rd8(addr))
            if a: r[a] = v
        elif op == OP_ST:
            m.wr16(addr, r[a])
        else:
            m.wr8(addr, r[a] & 0xFF)
    elif op == OP_BCC:
        if a == 15:
            m.pc = pc
            push(m, pc)
            pc = (pc + 2 * sext8(w)) & 0xFFFF
        else:
            taken = bool(cond_true(m, a))
            if taken:
                pc = (pc + 2 * sext8(w)) & 0xFFFF
    elif op == OP_MVI:
        v = sext8(w) & 0xFFFF
        _nz(m, v)
        if a: r[a] = v
    elif op == OP_ADDI:
        v = _add(m, r[a], sext8(w) & 0xFFFF, 0)
        if a: r[a] = v
    elif op == OP_CMPI:
        _add(m, r[a], (sext8(w) & 0xFFFF) ^ 0xFFFF, 1)
    elif op == OP_UN:
        res = unary(m, c, r[b])
        if res is None:
            m.pc = pc
            m.illegal(w)
            enter_interrupt(m, TRAP_VECTOR)
            return w, None
        if a: r[a] = res
    elif op == OP_JCC:
        target = m.rd16(pc) & 0xFFFE
        pc = (pc + 2) & 0xFFFF
        if a == 15:
            m.pc = pc
            push(m, pc)
            pc = target
        else:
            taken = bool(cond_true(m, a))
            if taken:
                pc = target
    elif op == OP_MEML:
        if c >= len(MEM_FN):
            m.pc = pc
            m.illegal(w)
            enter_interrupt(m, TRAP_VECTOR)
            return w, None
        disp = m.rd16(pc)
        pc = (pc + 2) & 0xFFFF
        addr = (r[b] + disp) & 0xFFFF
        if c == 0:
            v = _nz(m, m.rd16(addr))
            if a: r[a] = v
        elif c == 1:
            m.wr16(addr, r[a])
        elif c == 2:
            v = _nz(m, m.rd8(addr))
            if a: r[a] = v
        elif c == 3:
            m.wr8(addr, r[a] & 0xFF)
        else:
            if a: r[a] = addr
    elif op == OP_SYS:
        if c == 0:      # HALT
            m.halted = True
        elif c == 1:    # NOP
            pass
        elif c == 2:    # JMP rs
            pc = r[b] & 0xFFFE
        elif c == 3:    # CALL rs
            target = r[b] & 0xFFFE
            m.pc = pc
            push(m, pc)
            pc = target
        elif c == 4:    # RET
            pc = pop(m) & 0xFFFE
        elif c == 5:    # PUSH rs (pushes the value before the push)
            v = r[b]
            push(m, v)
        elif c == 6:    # POP rd
            v = _nz(m, pop(m))
            if a: r[a] = v
        elif c == 7:    # RTI
            set_flags_word(m, pop(m))
            pc = pop(m) & 0xFFFE
        elif c == 8:    # EI
            m.i = 1
        elif c == 9:    # DI
            m.i = 0
        elif c == 10:   # MFF rd
            if a: r[a] = flags_word(m)
        elif c == 11:   # MTF rs
            set_flags_word(m, r[b])
        elif c == 12:   # SWI
            m.pc = pc
            enter_interrupt(m, TRAP_VECTOR)
            return w, None
        else:
            m.pc = pc
            m.illegal(w)
            enter_interrupt(m, TRAP_VECTOR)
            return w, None
    else:               # B (EAE, reserved) and F (reserved)
        m.pc = pc
        m.illegal(w)
        enter_interrupt(m, TRAP_VECTOR)
        return w, None
    m.pc = pc
    return w, taken
