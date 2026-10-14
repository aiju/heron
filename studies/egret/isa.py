"""What instruction-set changes would save Egret's interpreter on draft 1b.

The hand-written interpreter loop (vm/interp_v1b.s) marks the instruction
sequences that an ISA change would replace with ;@name ... ;@end, which the
build makes labels. From a run, each sequence's executions and cycles come
straight from the simulator; what it would cost instead is the timing
model's cost for the instructions that would replace it, taken from
existing instructions with the same work (a register ALU operation, a
not-taken branch, a load), so it's costed by the same rules.
"""

import re
from collections import Counter, defaultdict

from . import build
from .profile import CONFIGS


def regions(img):
    """[(name, start, end)] of the marked sequences"""
    starts, ends = {}, {}
    for name, a in img.symbols.items():
        m = re.search(r"\.R_(\w+)_(\d+)$", name)
        if not m:
            continue
        if m.group(1) == "end":
            ends[int(m.group(2))] = a
        else:
            starts[int(m.group(2))] = (m.group(1), a)
    return [(nm, a, ends[k]) for k, (nm, a) in starts.items() if k in ends]


def idiom_costs(m, base=None, configs=CONFIGS):
    """{name: {"count": executions, config: cycles}} for a run (less base's)"""
    pcc = Counter(m.pc_counts)
    cyc = {c: Counter(m.pc_cycles(c)) for c in configs}
    if base is not None:
        pcc.subtract(base.pc_counts)
        for c in configs:
            cyc[c].subtract(base.pc_cycles(c))
    out = defaultdict(lambda: defaultdict(float))
    for name, a, e in regions(m.image):
        out[name]["count"] += pcc.get(a, 0)
        for c in configs:
            out[name][c] += sum(cyc[c].get(pc, 0) for pc in range(a, e, 2))
    return out


# ---- costing --------------------------------------------------------------------------

def cost(key, config):
    """cycles of an instruction with this timing key, both alignments averaged"""
    from heron.studies.v1_isa import timing32
    a = timing32.cycles((key[0], 0) + tuple(key[1:]), config)
    b = timing32.cycles((key[0], 2) + tuple(key[1:]), config)
    return (a + b) / 2


ALU = (1, "alu", 1)             # a one-parcel ALU operation that writes its result
ALU0 = (1, "alu", 0)            # ... that only sets the flags (CMP, TST)
BR = (1, "br", 0, 0)            # a branch not taken
LD = (1, "ld", "r", 4, 0)       # a word load through a register
LDH = (1, "ld", "r", 2, 0)      # a half load through a register
LEAX = (2, "lea", "idx", 0)     # LEA [r + r]
JMPPI = (1, "jmpm", "pi", 0)    # JMP [r]+
TRAP = (1, "trap",)


def instances(m, base=None, configs=CONFIGS):
    """{(scope, idiom): {"count", "fast", config: cycles}}: every marked
    sequence of a run, by the handler it's in; "fast" is how often the
    instruction after it ran (so count - fast took a branch out of it)"""
    pcc = Counter(m.pc_counts)
    cyc = {c: Counter(m.pc_cycles(c)) for c in configs}
    if base is not None:
        pcc.subtract(base.pc_counts)
        for c in configs:
            cyc[c].subtract(base.pc_cycles(c))
    inv = {}
    for name, a in m.image.symbols.items():
        if ".R_" in name and not name.split(".R_")[1].startswith("end_"):
            inv[a] = name
    out = defaultdict(lambda: defaultdict(float))
    for name, a, e in regions(m.image):
        scope = next((n.split(".R_")[0] for aa, n in inv.items() if aa == a and f".R_{name}_" in n), "?")
        d = out[(scope.split(".")[0], name)]
        d["count"] += pcc.get(a, 0)
        d["fast"] += pcc.get(e, 0)
        for c in configs:
            d[c] += sum(cyc[c].get(pc, 0) for pc in range(a, e, 2))
    return out, pcc, cyc


class Proposal:
    """An ISA change: the marked sequences it replaces (scope regex, idiom),
    what each instance costs instead, and what it costs when it traps."""

    def __init__(self, name, what, replaces, new, trap_on_slow=False, scopes=r".*"):
        self.name = name
        self.what = what
        self.replaces = replaces        # idiom names
        self.new = new                  # [timing keys] that replace one instance
        self.trap_on_slow = trap_on_slow
        self.scopes = scopes

    def saving(self, inst, config):
        old = new = 0.0
        slow = 0.0
        for (scope, idiom), d in inst.items():
            if idiom not in self.replaces or not re.match(self.scopes, scope):
                continue
            old += d[config]
            slow += d["count"] - d["fast"]
            if idiom == self.replaces[0]:
                new += d["count"] * sum(cost(k, config) for k in self.new)
        if self.trap_on_slow:
            # a trap and a handler that finds the slow path (a table
            # search, say 20 cycles) each time the operation isn't on
            # SmallInts or overflows
            new += slow / max(1, len(self.replaces)) * (cost(TRAP, config) + 20)
        return old - new


ARITH = r"op_(add|sub)$"
COMPARE = r"op_(lt|le|gt|ge)$"

PROPOSALS = [
    Proposal("TTST", "tag test of two registers: Z unless both are SmallInts (op F, function 9)",
             ["tag2"], [ALU0, BR]),
    Proposal("TADD/TSUB", "SmallInt add and subtract, trapping when an operand isn't one or the result "
             "overflows (SPARC's TADDccTV, for tag 1)", ["tag2", "tagadd", "tagsub"], [ALU],
             trap_on_slow=True, scopes=ARITH),
    Proposal("TCMP", "compare, trapping when an operand isn't a SmallInt", ["tag2"], [],
             trap_on_slow=True, scopes=COMPARE),
    Proposal("LDCLASS", "load a value's class: a register (SmallInts) or the word it points at",
             ["classof"], [LD]),
    Proposal("XOR3", "three-operand XOR (the method cache's hash without the MOV)",
             ["hash"], [ALU, ALU]),
    Proposal("LDH unaligned", "a 16-bit load at any alignment (the jump offsets)",
             ["jumpoff"], [LDH, ALU, LEAX]),
]


def dispatch_saving(m, layout, cyc, pcc, config):
    """Direct-threaded code instead of bytecode: each MOV r1, byte [r8]+ /
    JMP [r13 + r1*4] becomes JMP [r8]+ (already in 1b)"""
    old = sum(cyc[config].get(pc, 0) for pc in layout.dispatch_pcs)
    jumps = sum(pcc.get(pc, 0) for pc in layout.dispatch_pcs) / 2
    return old - jumps * cost(JMPPI, config)


# ---- native code ----------------------------------------------------------------------
#
# The JIT's code isn't marked, so its sequences are found by disassembling
# what a run executed: each pattern is a few instructions in a row, as the
# templates in vm/jit.c emit them.

class Instr:
    __slots__ = ("pc", "text", "n", "count", "cycles", "part")


def native_code(m, layout, configs=CONFIGS):
    """{pc: Instr}: the native instructions a JIT run executed"""
    from heron.studies.v1_isa import v1b
    mem = m.mem
    out = {}
    cyc = {c: m.pc_cycles(c) for c in configs}
    for (pc, key), n in m.pc_keys.items():
        if not (layout.perm_lo <= pc < layout.perm_hi):
            continue
        i = out.get(pc)
        if i is None:
            i = out[pc] = Instr()
            i.pc, i.count, i.part = pc, 0, layout.native_part(pc)
            ws = [mem[pc + 2 * k] | mem[pc + 2 * k + 1] << 8 for k in range(4)]
            i.text, i.n = v1b.disassemble(ws, pc)
            i.cycles = {c: cyc[c].get(pc, 0) for c in configs}
        i.count += n
    return out


def matches(code, pattern, parts=None):
    """[[Instr]]: each run of instructions, one after another in memory,
    whose texts match pattern's regexes"""
    out = []
    for pc, i in code.items():
        if parts and i.part not in parts:
            continue
        seq, a = [], pc
        for pat in pattern:
            j = code.get(a)
            if j is None or not re.match(pat, j.text):
                break
            seq.append(j)
            a += 2 * j.n
        if len(seq) == len(pattern):
            out.append(seq)
    return out


def seq_cycles(seqs, config, which=None):
    return sum(i.cycles[config] for s in seqs for i in (s if which is None else [s[k] for k in which]))


class NativeChange:
    """A change for native code: the sequences it removes or replaces,
    and the saving per config"""

    def __init__(self, name, kind, what, fn):
        self.name, self.kind, self.what, self.fn = name, kind, what, fn

    def saving(self, code, config, syms):
        return self.fn(code, config, syms)


SENDS = {"SEND", "SEND_SUPER", "stubs"}


def _ldclass(code, config, syms):
    # RRC r2, r1 / JCS (SmallInt) / MOV r2, [r1], and for a SmallInt the
    # stub's MOV r2, [cls_Int] and the branch back: one load
    seqs = matches(code, [r"RRC r2, r1$", r"JCS ", r"MOV r2, \[r1\]$"])
    old = seq_cycles(seqs, config)
    cls_int = f"MOV r2, [0x{syms['_cls_Int']:X}]"
    for i in code.values():
        if i.text == cls_int:
            old += i.cycles[config]
            nxt = code.get(i.pc + 2 * i.n)
            if nxt:
                old += nxt.cycles[config]
    return old - sum(s[0].count for s in seqs) * cost(LD, config)


def _chk(code, config, syms):
    # CMP r11 (or r10), [limit] / JCS overflow: a compare that traps
    seqs = matches(code, [r"CMP r1[01], \[0x[0-9A-F]+\]$", r"JCS "], {"prologue"})
    return seq_cycles(seqs, config, [1])


def _link(code, config, syms):
    # CALL pushes the return address, the prologue pops it into the frame:
    # with a call that leaves it in a register, the push and the pop go
    pops = matches(code, [r"MOV r1, \[sp\]\+$", r"ST r1, \[r11 \+ 20\]$"], {"prologue"})
    calls = sum(s[0].count for s in pops)
    d = cost((3, "call", "abs", 0), config) - cost((3, "jmp", "abs", 0), config)
    return seq_cycles(pops, config, [0]) + calls * d


def _ttst(code, config, syms):
    seqs = matches(code, [r"MOV r3, r1$", r"AND r3, r2$", r"AND r3, #1$", r"JEQ "])
    return seq_cycles(seqs, config) - sum(s[0].count for s in seqs) * (cost(ALU0, config) + cost(BR, config))


def _fallthrough(code, i):
    """how often the instruction after i ran (i a branch: its not-taken count)"""
    j = code.get(i.pc + 2 * i.n)
    return j.count if j else 0


def _tagged(code, config, syms):
    # add, subtract and compare that trap when an operand isn't a SmallInt
    # (or the sum overflows): the templates' tag tests, the DEC that
    # untags an operand and the overflow branch go; each time one of them
    # would have branched to the slow path, a trap
    old = slow = 0.0
    for pat, gone in (([r"MOV r3, r1$", r"AND r3, r2$", r"AND r3, #1$", r"JEQ "], [0, 1, 2, 3]),
                      ([r"RRC r3, r1$", r"JCC "], [0, 1]),
                      ([r"DEC r2, r2$", r"(ADD|SUB) r1, r2$", r"JVS "], [0, 2]),
                      ([r"(ADD|SUB) r1, #-?\d+$", r"JVS "], [1])):
        for s in matches(code, pat):
            old += sum(s[k].cycles[config] for k in gone)
            br = s[gone[-1]]
            slow += br.count - _fallthrough(code, br)
    return old - slow * (cost(TRAP, config) + 20)


def _one_check(code, config, syms):
    # frames and values in one region, growing towards each other: one
    # compare of r10 with r11 for both
    seqs = matches(code, [r"CMP r10, \[0x[0-9A-F]+\]$", r"JCS "], {"prologue"})
    return seq_cycles(seqs, config)


def _no_ip(code, config, syms):
    # C finds a native frame's bytecode from its return address, so a send
    # doesn't set r8 and the prologue doesn't store it
    sets = [i for i in code.values() if i.part in SENDS and re.match(r"MOV r8, #0x", i.text)]
    stores = matches(code, [r"ST r8, \[r11\]$"], {"prologue"})
    return sum(i.cycles[config] for i in sets) + seq_cycles(stores, config)


NATIVE_CHANGES = [
    NativeChange("LDCLASS", "ISA", "load a value's class (as for the interpreter): the class-of "
                 "in every send site, without the SmallInt branch and stub", _ldclass),
    NativeChange("CHK", "ISA", "compare with a bound and trap (68000's CHK): the prologue's two "
                 "stack checks without their branches", _chk),
    NativeChange("BL", "ISA", "a call that leaves the return address in a register: no push in "
                 "the call, no pop in the prologue", _link),
    NativeChange("TTST", "ISA", "tag test of two registers (as for the interpreter), in the "
                 "operators' templates", _ttst),
    NativeChange("TADD/TSUB/TCMP", "ISA", "add, subtract and compare that trap unless both operands "
                 "are SmallInts (and the sum fits), in the operators' templates", _tagged),
    NativeChange("one stack check", "system", "the frames and the values in one region, growing "
                 "towards each other: one register compare for both", _one_check),
    NativeChange("no bytecode ip", "software", "C maps a native frame's return address back to "
                 "its bytecode, so sends don't set r8 nor the prologue store it", _no_ip),
]


def native_kinds(code, config):
    """{what: cycles} for native code, by the kind of instruction"""
    out = Counter()
    for i in code.values():
        t = i.text
        op = t.split()[0]
        if re.search(r"\[r(9|10)\b", t):
            k = "the value stack"           # locals, self and temporaries
        elif "[r11" in t or "[sp]" in t:
            k = "frames"
        elif op in ("CALL", "RET") or op.startswith("J") or op in ("BRA",) or op.startswith("B"):
            k = "branches, calls"
        elif "[" in t:
            k = "other loads, stores"
        else:
            k = "registers"
        out[k] += i.cycles[config]
    return out
