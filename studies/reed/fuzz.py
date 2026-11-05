"""Reed's microcode against draft 2's instruction-level simulator, an
instruction at a time: random instructions of each family, on registers
and memory set up so that their operands are valid, on the cycle-level
model (model.py); registers, flags and the data area compared. A share
of the cases have their pointers misaligned: those that then fault are
compared at the address error's vector (a HALT at 0x14 on both machines,
physical 0x14 being vbr + 0x14 on Reed too), for precise faults: the
registers, the flags, the data but the frame's sr, and the saved PC.

  heron reed fuzz [FAMILY...] [--n N] [--seed S]
"""

import random

from heron.infra import asm as asmcore, isas
import heron.studies.v2_isa  # noqa: F401 (registers the ISA)

from . import model, ucode

DATA, DATA_END = 0x4000, 0x9000         # the data area: random bytes
CODE = 0x200                            # the instruction under test
ISA = None


def isa():
    global ISA
    if ISA is None:
        ISA = isas.get("v2")
    return ISA


def parcels(op, rb, *ext):
    return [op | rb << 8] + [e & 0xFFFF for e in ext]


def program(regs, insn, data):
    """An image: r0-r15 = regs, then the instruction (a list of parcels) at
    CODE, then HALT; the data area's bytes. HALTs at the vectors of an
    illegal instruction, a divide error and an address error."""
    lines = ["        .org 0", "        JMP  init", "        .org 0x08", "        HALT",
             "        .org 0x10", "        HALT", "        .org 0x14", "        HALT",
             "        .org 0x40", "init:"] + [f"        MOV  r{i}, #{v:#x}" for i, v in enumerate(regs)]
    lines += [f"        JMP  {CODE:#x}"]
    img = asmcore.assemble_text(isa(), "\n".join(lines), name="fuzz.s")
    mem = dict(img.mem)
    a = CODE
    for p in insn + [0x03FE]:
        mem[a], mem[a + 1] = p & 255, p >> 8
        a += 2
    for i, b in enumerate(data):
        mem[DATA + i] = b
    img.mem = mem
    return img


def run_both(img, max_cycles=200_000):
    from heron.studies.v2_isa.sim import Machine
    ref = Machine(img)
    ref.run(max_cycles=max_cycles)
    m = model.run_image(img, max_cycles=max_cycles, prog=PROG[0])
    return ref, m


PROG = [None]


def compare(ref, m):
    bad = []
    if m.stopped != "halt":
        bad.append(f"the model stopped at {m.stopped}")
    regs = m.regs()
    for r in range(16):
        if regs[r] != ref.r[r]:
            bad.append(f"r{r} {regs[r]:08X}, the reference {ref.r[r]:08X}")
    fz = m._znow() if m.zpend else m.fzh
    flags = (m.fn, fz, m.fc, m.fv)
    rflags = (int(ref.n), int(ref.z), int(ref.c), int(ref.v))
    if flags != rflags:
        bad.append(f"NZCV {flags}, the reference {rflags}")
    mem = ref.mem
    diff = [a for a in range(DATA, DATA_END) if m.ram[a] != mem[a]]
    if diff:
        bad.append(f"{len(diff)} data bytes differ, the first at {diff[0]:05X}")
    return bad


# ---- the families -------------------------------------------------------------

def pointer(rng):
    return DATA + 0x800 + 4 * rng.randrange(0x400)


def value(rng):
    return rng.choice([0, 1, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, rng.getrandbits(32),
                       rng.getrandbits(8), rng.getrandbits(16), -rng.getrandbits(7) & 0xFFFFFFFF])


def ea_ext(rng, M, R, size):
    """Extension parcels for an EA mode (an aligned, in-area operand)."""
    al = {"w": 4, "h": 2, "b": 1}[size]
    if M in (3, 9, 0xC):
        return [al * rng.randrange(-0x100, 0x100) & 0xFFFF]
    if M == 5:
        x = rng.randrange(16)
        return [x << 12 | rng.randrange(4) << 10 | {"b": 0, "h": 1, "w": 2}[size] << 8
                | (4 * rng.randrange(-32, 32)) & 0xFF]
    if M == 0xF:
        if R in (0, 1, 2):
            return [rng.getrandbits(16)]
        if R == 3:
            return [rng.getrandbits(16), rng.getrandbits(16)]
        a = DATA + 0x800 + al * rng.randrange(0x400)
        if R in (4, 5, 6):
            return [a]
        if R in (7, 8, 9):
            return [a & 0xFFFF, a >> 16]
        if R in (0xA, 0xB, 0xC):
            pc_after = CODE + 4
            return [(a - pc_after) & 0xFFFF]
        if R in (0xD, 0xE):
            x = rng.randrange(16)
            base = a if R == 0xD else a - (CODE + 6)
            return [x << 12 | rng.randrange(4) << 10 | {"b": 0, "h": 1, "w": 2}[size] << 8 | (base >> 16) & 0xFF,
                    base & 0xFFFF]
    return []


MEM_MODES = {2: "w", 3: "w", 4: "w", 6: "w", 7: "w", 8: "b", 9: "b", 0xA: "b", 0xB: "h", 0xC: "h", 0xE: "w",
             5: None}
SPECIAL_MEM = {4: "w", 5: "b", 6: "h", 7: "w", 8: "b", 9: "h", 0xA: "w", 0xB: "b", 0xC: "h", 0xD: None, 0xE: None}


def regs_for(rng, alu=False):
    regs = [pointer(rng) for _ in range(16)]
    if alu:
        regs = [value(rng) for _ in range(16)]
    return regs


def gen_ea(rng, rows=(1, 3, 4, 5, 6, 8, 9, 0xA)):
    row = rng.choice(rows)
    M = rng.choice([0, 1, 0xD, 0xF] + list(MEM_MODES))
    d, R = rng.randrange(16), rng.randrange(16)
    if M == 0xF:
        R = rng.choice([0, 1, 2, 3] + list(SPECIAL_MEM))
    if row == 3 and (M in (1, 0xD) or (M == 0xF and R < 4)):
        M = 0
    size = MEM_MODES.get(M) or (SPECIAL_MEM.get(R) if M == 0xF else "w") or rng.choice("bhw")
    ext = ea_ext(rng, M, R, size)
    alu = M in (0, 1, 0xD) or (M == 0xF and R < 4)
    return regs_for(rng, alu), parcels(row << 4 | M, d << 4 | R, *ext)


def gen_store(rng):
    M = rng.choice(list(MEM_MODES) + [0xF])
    if M in (0, 1, 0xD):
        M = 2
    d, R = rng.randrange(16), rng.randrange(16)
    if M == 0xF:
        R = rng.choice(list(SPECIAL_MEM))
    size = MEM_MODES.get(M) or (SPECIAL_MEM.get(R) if M == 0xF else "w") or rng.choice("bhw")
    regs = regs_for(rng)
    if M in (6, 7, 0xA) and d == R:
        d = (R + 1) & 15
    if d != R and not (M == 5 and d == (ea_ext(random.Random(0), 5, R, "w")[0] >> 12)):
        regs[d] = value(rng)
    return regs, parcels(0x20 | M, d << 4 | R, *ea_ext(rng, M, R, size))


def gen_clr_inc_dec(rng):
    opc = rng.choice([0x20, 0x21, 0x2D])
    M = rng.choice([0] + list(MEM_MODES) + [0xF])
    R = rng.randrange(16)
    if M == 0xF:
        R = rng.choice(list(SPECIAL_MEM))
    size = MEM_MODES.get(M) or (SPECIAL_MEM.get(R) if M == 0xF else "w") or rng.choice("bhw")
    return regs_for(rng, M == 0), parcels(opc, M << 4 | R, *ea_ext(rng, M, R, size))


def gen_lea(rng):
    col = rng.choice([3, 4, 5, 0xE, 0xF])
    d, R = rng.randrange(16), rng.randrange(16)
    if col == 0xF:
        R = rng.choice(list(SPECIAL_MEM))
    size = SPECIAL_MEM.get(R) if col == 0xF else "w"
    return regs_for(rng), parcels(col, d << 4 | R, *ea_ext(rng, col if col != 0xF else 0xF, R, size or "w"))


def gen_unary(rng):
    opc = rng.choice([0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xDF])
    d, s = rng.randrange(16), rng.randrange(16)
    if opc == 0xDF:
        s = rng.randrange(15)
    regs = regs_for(rng, True)
    # some flags first: a CMP of two registers
    return regs, parcels(0x60, rng.randrange(256)) + parcels(opc, d << 4 | s)


def gen_shift(rng):
    k = rng.randrange(4)
    d = rng.randrange(16)
    if rng.random() < 0.5:
        n = rng.randrange(32)
        return regs_for(rng, True), parcels(0xC0 | k << 2 | (n & 1), d << 4 | n >> 1)
    return regs_for(rng, True), parcels(0xC2 | k << 2, d << 4 | rng.randrange(16))


def gen_mul(rng):
    opc = rng.choice([0xE4, 0xE5, 0xEC, 0xED])
    d, s = rng.randrange(1, 16), rng.randrange(16)
    regs = regs_for(rng, True)
    if opc >= 0xEC:
        R = rng.choice([0, 1, 2, 3, 4, 7, 0xA, 0xD, 0xE])
        if R in (0xD, 0xE):
            ext = ea_ext(rng, 0xF, R, rng.choice("bhw"))
            x = ext[0] >> 12
            regs[x] = 0
            return regs, parcels(opc, d << 4 | R, *ext)
        return regs, parcels(opc, d << 4 | R, *ea_ext(rng, 0xF, R, "w"))
    return regs, parcels(opc, d << 4 | s)


def flags_first(rng):
    """A CMP of two registers first, for flags to start from."""
    return parcels(0x60, rng.randrange(256))


def gen_carry(rng):
    d, s = rng.randrange(16), rng.randrange(16)
    regs = regs_for(rng, True)
    if rng.random() < 0.3:
        regs[d] = (-regs[s]) & 0xFFFFFFFF
    return regs, flags_first(rng) + parcels(rng.choice([0xE0, 0xE1]), d << 4 | s)


def gen_clz(rng):
    d, s = rng.randrange(16), rng.randrange(16)
    regs = regs_for(rng, True)
    regs[s] = rng.choice([0, 1, 0x80000000, rng.getrandbits(32) >> rng.randrange(33)])
    return regs, flags_first(rng) + parcels(0xDB, d << 4 | s)


def gen_divul(rng):
    d, s = rng.randrange(1, 16), rng.randrange(1, 16)
    regs = regs_for(rng, True)
    r = rng.random()
    if r < 0.1:
        regs[s] = 0
    elif r < 0.7:
        regs[s] = regs[s] or 1
        regs[0] = rng.randrange(regs[s])
    if 15 not in (d, s):
        regs[15] = pointer(rng)         # (a divide error's frame goes there)
    return regs, flags_first(rng) + parcels(0xE9, d << 4 | s)


def gen_movsi(rng):
    R = rng.randrange(4)
    return regs_for(rng, True), parcels(0x3F, rng.randrange(16) << 4 | R, *ea_ext(rng, 0xF, R, "w"))


def gen_neg24(rng):
    """MOV rd, [abs24 + x] with abs24 negative (sign-extended), x bringing it
    back into the data area."""
    size = rng.choice("bhw")
    al = {"w": 4, "h": 2, "b": 1}[size]
    t = DATA + 0x800 + al * rng.randrange(0x400)
    k = rng.randrange(1, 0x800000)
    a24 = (-k) & 0xFFFFFF
    d, x = rng.randrange(16), rng.randrange(1, 16)
    regs = regs_for(rng)
    regs[x] = (t + k) & 0xFFFFFFFF
    z = {"b": 0, "h": 1, "w": 2}[size]
    return regs, parcels(0x1F, d << 4 | 0xD, x << 12 | z << 8 | a24 >> 16, a24 & 0xFFFF)


def gen_div(rng):
    d, s = rng.randrange(1, 16), rng.randrange(16)
    regs = regs_for(rng, True)
    if rng.random() < 0.1:
        regs[d], regs[s] = 0x80000000, 0xFFFFFFFF
    if regs[s] == 0:
        regs[s] = 7
    return regs, parcels(rng.choice([0xE7, 0xE8]), d << 4 | s)


def gen_multiple(rng):
    ra = rng.randrange(16)
    rc = rng.randrange(ra, 16)
    rb = rng.randrange(16)
    regs = regs_for(rng)
    for j in range(ra, rc + 1):
        if j != rb:
            regs[j] = value(rng)
    return regs, parcels(rng.choice([0x01, 0x02]), ra << 4 | rb, rc << 12)


def gen_bictst(rng):
    opc = rng.choice([0xE2, 0xE3, 0xEA, 0xEB])
    d, s = rng.randrange(16), rng.randrange(16)
    if opc >= 0xEA:
        R = rng.choice([0, 1, 2, 3] + list(SPECIAL_MEM))
        size = SPECIAL_MEM.get(R, "w") or rng.choice("bhw")
        return regs_for(rng, R < 4), parcels(opc, d << 4 | R, *ea_ext(rng, 0xF, R, size))
    return regs_for(rng, True), parcels(opc, d << 4 | s)


def gen_mvi(rng):
    u7 = rng.randrange(128)
    op = (0x70 if rng.random() < 0.5 else 0x78) | (u7 & 7)
    return regs_for(rng, True), parcels(op, rng.randrange(16) << 4 | u7 >> 3)


def gen_save(rng):
    ra = rng.randrange(15)
    rb = rng.randrange(ra, 15)
    regs = regs_for(rng, True)
    regs[15] = DATA + 0x1000 + 4 * rng.randrange(0x100)
    return regs, parcels(0xF4 if rng.random() < 0.5 else 0xF5, ra << 4 | rb)


FAMILIES = {"ea": gen_ea, "store": gen_store, "clr": gen_clr_inc_dec, "lea": gen_lea, "unary": gen_unary,
            "shift": gen_shift, "mul": gen_mul, "div": gen_div, "bictst": gen_bictst, "mvi": gen_mvi,
            "save": gen_save, "multiple": gen_multiple, "carry": gen_carry, "clz": gen_clz,
            "divul": gen_divul, "movsi": gen_movsi, "neg24": gen_neg24}


def compare_trap(ref, m):
    """After an address or divide error on both: the registers (sp 8 lower on both,
    the frame's), the flags, the data but the frame's flags word or sr,
    and the frame's PC."""
    bad = []
    if m.stopped != "halt":
        bad.append(f"the model stopped at {m.stopped}")
    regs = m.regs()
    for r in range(16):
        if regs[r] != ref.r[r]:
            bad.append(f"r{r} {regs[r]:08X}, the reference {ref.r[r]:08X}")
    fz = m._znow() if m.zpend else m.fzh
    flags = (m.fn, fz, m.fc, m.fv)
    rflags = (int(ref.n), int(ref.z), int(ref.c), int(ref.v))
    if flags != rflags:
        bad.append(f"NZCV {flags}, the reference {rflags}")
    sp = ref.r[15]
    mem = ref.mem
    diff = [a for a in range(DATA, DATA_END) if m.ram[a] != mem[a] and not sp <= a < sp + 4]
    if diff:
        bad.append(f"{len(diff)} data bytes differ, the first at {diff[0]:05X}")
    return bad


def misalign(rng, regs):
    """The pointers (into the data area) moved off their alignment."""
    k = rng.randrange(1, 4)
    # (but sp, which the exception's frame goes on)
    return [r + k if DATA <= r < DATA_END and i != 15 else r for i, r in enumerate(regs)]


TRAPPING = {"ea", "store", "clr", "mul", "bictst", "multiple", "save"}


def fuzz(families=None, n=200, seed=1, stop_at=5):
    """{family: [failure lines]}"""
    if PROG[0] is None:
        PROG[0] = ucode.build()
    rng = random.Random(seed)
    out = {}
    for fam in families or FAMILIES:
        fails = []
        for i in range(n):
            regs, insn = FAMILIES[fam](rng)
            if fam in TRAPPING and rng.random() < 0.3:
                regs = misalign(rng, regs)
            data = bytes(rng.getrandbits(8) for _ in range(DATA_END - DATA))
            img = program(regs, insn, data)
            dis = isa().disassemble(insn + [0, 0], CODE)
            if "illegal" in dis[0]:
                continue
            from heron.studies.v2_isa.sim import Machine
            ref = Machine(img)
            try:
                ref.run(max_cycles=200_000)
            except Exception:
                continue                  # the reference faults: not a test
            trapped = bool(ref.traps)
            if trapped and not all("misaligned" in t[1] or "divide" in t[1] for t in ref.traps):
                continue
            try:
                m = model.run_image(img, max_cycles=200_000, prog=PROG[0])
                bad = compare_trap(ref, m) if trapped else compare(ref, m)
            except model.ModelError as e:
                bad = [f"model: {e}"]
            if bad:
                fails.append(f"{' '.join(f'{p:04X}' for p in insn)}  {dis[0]}: " + "; ".join(bad[:3]))
                if len(fails) >= stop_at:
                    break
        out[fam] = fails
    return out


def main(families=None, n=200, seed=1):
    res = fuzz(families, n, seed)
    for fam, fails in res.items():
        print(f"{fam:<8} {'ok' if not fails else f'{len(fails)} failing'}")
        for f in fails:
            print("   ", f)
