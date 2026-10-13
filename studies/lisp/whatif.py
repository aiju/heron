"""What-if costing: what a change to the instruction set or the system
would save, from a measured run, without building it.

Each scenario picks out instructions of a run by what they are (their
parcels: the operation, the addressing mode, the registers) and costs
them again as they would be with the change, through the same timing
model (studies/v1_isa/timing-model-v1.md), or not at all if the change
makes them unnecessary. The rest of the run is unchanged, which is right
for these changes: none of them changes the code around the instructions
it affects.

The runs are the measured windows of compiled programs (measure.py), or
whole interpreted runs.
"""

from collections import Counter

from heron.studies.v1_isa import timing32

from . import measure

CONFIG = measure.CONFIG

# the timing keys of the instructions the scenarios add or substitute
ALU_W = (1, 0, "alu", 1)        # an ALU operation that writes a register
ALU_NW = (1, 0, "alu", 0)       # one that doesn't (CMP)
BR_NOT = (1, 0, "br", 0, 0)     # a branch not taken


def cyc(key):
    return timing32.cycles(key, CONFIG)


def decode(mem, pc):
    """(op, d, mode, R, d16 or None) of the instruction at pc."""
    p = mem[pc] | mem[pc + 1] << 8
    op, d, mode, r = p >> 12, (p >> 8) & 15, (p >> 4) & 15, p & 15
    d16 = None
    if 1 <= op <= 9 or op == 0xB:
        if mode in (3, 9, 0xC):
            x = mem[pc + 2] | mem[pc + 3] << 8
            d16 = x - 0x10000 if x & 0x8000 else x
        elif mode == 0xF and r in (4, 5, 6):
            d16 = mem[pc + 2] | mem[pc + 3] << 8
    return op, d, mode, r, d16


def shorter(key):
    """The key of the same access as a one-parcel [R] form."""
    n, p2, kind, *rest = key
    if kind in ("ld", "st"):
        ea, size, x = rest
        return (n - 1, p2, kind, "r", size, 0)
    if kind == "op":
        ea, size, x, wb = rest
        return (n - 1, p2, kind, "r", size, 0, wb)
    if kind in ("jmpm", "callm"):
        return (n - 1, p2, kind, "r", 0)
    return key


SCENARIOS = {
    "short-pair": "car, cdr, set-car! and set-cdr! ([R - 1], [R + 3]) in one parcel",
    "heap-limit-reg": "the heap limit in a register: CMP r14, r instead of CMP r14, [limit]",
    "stack-limit-hw": "the stack limit checked by hardware: no CMP sp, [limit] and branch",
    "unbound-free": "unbound globals caught without a check: no CMP r, #1 and branch",
    "argc-free": "the argument count checked without instructions: no CMP r2, #n and branch",
    "no-align-traps": "no alignment traps: car, cdr and calls check their argument's tag",
    "call-1a": "a call through the call slot as 1a would make it: a load, then CALL r",
}


def analyse(counts, mem, image, compiled=True):
    """Cycles each scenario saves (negative: costs), for a Counter of
    (pc, key) -> executions."""
    sym = image.symbols
    code_base = sym["gen_end"]
    limits = {sym["cons_limit"], sym["heap_limit"]}
    stack_limit = sym["stack_limit"]
    out = Counter()
    by_pc = {}
    for (pc, key), n in counts.items():
        if pc is not None and n:
            by_pc.setdefault(pc, []).append((key, n))
    for pc, keys in by_pc.items():
        op, d, mode, r, d16 = decode(mem, pc)
        nxt_keys = None
        for key, n in keys:
            kind = key[2]
            here = cyc(key)
            # car and cdr: a memory operand at [R - 1] or [R + 3]
            if 1 <= op <= 9 and mode == 3 and d16 in (-1, 3):
                out["short-pair"] += n * (here - cyc(shorter(key)))
                out["no-align-traps"] -= n * (3 * cyc(ALU_W) + cyc(ALU_NW) + cyc(BR_NOT))
            # a call through the call slot: CALL/JMP [R + 1], or MOV r, [R + 1]
            if mode == 3 and d16 == 1 and (op == 0xB or op == 1):
                out["no-align-traps"] -= n * (2 * cyc(ALU_W) + cyc(ALU_NW) + cyc(BR_NOT))
                if op == 0xB and kind in ("callm", "jmpm"):
                    load = (2, key[1], "ld", "rd", 4, 0)
                    jump = (1, key[1], "call" if kind == "callm" else "jmp", "reg", 0)
                    out["call-1a"] -= n * (cyc(load) + cyc(jump) - here)
            # the heap limit: CMP r14, [abs]
            if op == 6 and d == 14 and mode == 0xF and r == 4 and d16 in limits:
                out["heap-limit-reg"] += n * (here - cyc(ALU_NW))
            # the stack limit: CMP sp, [stack_limit] and the branch after it
            if op == 6 and d == 15 and mode == 0xF and r == 4 and d16 == stack_limit:
                out["stack-limit-hw"] += n * here
                out["stack-limit-hw"] += branch_after(by_pc, pc + 4)
            if compiled and pc >= code_base:
                # CMP r1, #1 (unbound) and CMP r2, #n (argument count), then a branch
                if op == 6 and mode == 1 and d == 1 and r == 1:
                    out["unbound-free"] += n * here + branch_after(by_pc, pc + 2)
                if op == 6 and mode == 1 and d == 2:
                    out["argc-free"] += n * here + branch_after(by_pc, pc + 2)
    return out


def branch_after(by_pc, pc):
    """The cycles of the branch at pc."""
    return sum(n * cyc(key) for key, n in by_pc.get(pc, []) if key[2] in ("br", "jmp"))


def compiled_counts(text, features=()):
    """(counts, run) for a compiled program's measured windows."""
    c = measure.measure(text, features, compiled=True)
    return measure.window_counts(text, features, c["run"]), c["run"], c["cycles"]


def interpreted_counts(text, features=()):
    i = measure.measure(text, features)
    run = i["run"]
    return Counter({(pc, k): n for pc, k, n in run.machine._m.pc_keys()}), run, i["cycles"]
