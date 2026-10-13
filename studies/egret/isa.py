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
from .bench import CONFIGS


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
