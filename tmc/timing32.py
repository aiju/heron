"""Cycle estimates for the draft 1 machines (no hardware design yet).

The instruction-level simulator records, for every executed instruction, a
*timing key*: how many parcels it has, where it sits in memory, and an
ISA-independent description of the work it does (an ALU operation, a load
through a given kind of address, a taken branch, ...). This module turns a
key into a cycle count for a given machine configuration, so one simulation
run gives the cycle counts for every configuration.

Configurations vary two things:

- Datapath width: 16 bits (a 32-bit ALU operation takes two passes) or
  32 bits. Either way the register file reads or writes a whole 32-bit
  register in one cycle.
- Fetch style:
    'separate'  every instruction starts with its own fetch cycle; 16-bit bus.
    'overlap'   the next opcode is fetched in the instruction's last cycle when
                the bus is free then (as in the draft 0 hardware); 16-bit bus.
    'wide'      32-bit bus and a two-parcel prefetch buffer: a fetch brings in
                an aligned 32-bit word, parcels already in the buffer are free,
                and the next fetch can happen in any cycle the bus is idle.
                The 32-bit bus also makes word loads and stores one cycle.

Each instruction is described as a few micro-operations, each using some of
three resources for a number of cycles: the ALU ('A'), the memory bus ('B')
and the register file port ('R': one read of up to two registers, or one
write, per cycle). A tiny list scheduler packs them, honouring dependencies,
the way a microcode writer would. The rules are in docs/timing-model-v1.md.
"""

from functools import lru_cache

CONFIGS = {
    "D16-separate": (16, "separate"),
    "D16-overlap": (16, "overlap"),
    "D16-wide": (16, "wide"),
    "D32-separate": (32, "separate"),
    "D32-overlap": (32, "overlap"),
    "D32-wide": (32, "wide"),
}
CONFIG_NAMES = list(CONFIGS)
REFERENCE = "D16-overlap"   # used for the simulator's own cycle count (timer, limits)

# Kinds of instruction after which the next one is NOT fetched sequentially.
NONSEQ = {"jmp", "jmpm", "call", "callm", "ret", "rti", "trap", "irq"}


class Op:
    __slots__ = ("res", "dur", "deps", "sets_pc")

    def __init__(self, res, dur, deps=(), sets_pc=False):
        self.res = res
        self.dur = dur
        self.deps = deps
        self.sets_pc = sets_pc


def _schedule(ops, start, busy):
    """Place ops in order at the earliest cycle their dependencies and
    resources allow. busy maps resource -> set of occupied cycles."""
    end = []
    pc_ready = None
    for op in ops:
        t = start
        for d in op.deps:
            t = max(t, end[d])
        while any(c in busy[r] for r in op.res for c in range(t, t + op.dur)):
            t += 1
        for r in op.res:
            busy[r].update(range(t, t + op.dur))
        end.append(t + op.dur)
        if op.sets_pc:
            pc_ready = t + op.dur
    return end, pc_ready


class Model:
    def __init__(self, dp, fetch):
        self.dp = dp
        self.fetch = fetch
        self.bus = 32 if fetch == "wide" else 16
        self.aw = 1 if dp == 32 else 2          # a 32-bit ALU operation

    # ---- durations ----

    def addr(self, x):
        """Address arithmetic (base + small displacement, PC + offset).

        A 16-bit datapath adds the low halves and only needs a second cycle
        when the upper half changes (like the 6502's page-crossing cycle)."""
        return 1 if self.dp == 32 else 1 + x

    def mem(self, size):
        return 1 if (self.bus == 32 or size <= 2) else 2

    # ---- effective addresses ----

    def ea_ops(self, ops, ea, x, deps=()):
        """Append the ops that load MAR for an addressing kind.

        Returns (index of the op that leaves the address in MAR,
                 list of follow-up ops that update the base register)."""
        A, R, N = ("A",), ("A", "R"), ()
        if ea == "r":                 # MAR <- register
            ops.append(Op(("R",), 1, deps))
            return len(ops) - 1, []
        if ea == "rd":                # register + 16-bit displacement
            ops.append(Op(R, self.addr(x), deps))
            return len(ops) - 1, []
        if ea == "rd32":              # register + 32-bit displacement
            ops.append(Op(R, self.aw, deps))
            return len(ops) - 1, []
        if ea == "abs":               # MAR <- immediate latch
            ops.append(Op(N, 1, deps))
            return len(ops) - 1, []
        if ea == "pc":                # PC + displacement
            ops.append(Op(A, self.addr(x), deps))
            return len(ops) - 1, []
        if ea == "idx":               # base + d8, then + index * scale
            ops.append(Op(R, self.addr(x), deps))
            # the index is a whole 32-bit register: a full add, two passes on D16
            ops.append(Op(R, self.aw, (len(ops) - 1,)))
            return len(ops) - 1, []
        if ea == "pi":                # MAR <- R and T <- R + size in one cycle; R <- T later
            ops.append(Op(R, self.addr(x), deps))
            i = len(ops) - 1
            return i, ("pd", i, x)
        if ea == "pd":                # MAR, T <- R - size; later R <- T
            ops.append(Op(R, self.addr(x), deps))
            i = len(ops) - 1
            return i, ("pd", i, x)
        raise ValueError(ea)

    def _base_update(self, ops, upd):
        """Append the base-register write-back for auto-increment/decrement.
        It runs alongside the memory access where the resources allow."""
        if not upd:
            return
        if upd[0] == "pi":
            ops.append(Op(("A",), self.addr(upd[2]), (upd[1],)))
            ops.append(Op(("R",), 1, (len(ops) - 1,)))
        else:
            ops.append(Op(("R",), 1, (upd[1],)))

    # ---- instruction bodies ----

    def body(self, kind, p):
        """Micro-ops for one instruction (after its extension parcels are in)."""
        ops = []
        aw = self.aw
        if kind == "alu":                       # (wb,)
            ops.append(Op(("A", "R"), aw))
            if p[0]:
                ops.append(Op(("R",), 1, (0,)))
        elif kind == "shift":                   # (steps,)
            ops.append(Op(("A", "R"), max(1, p[0]) * aw))
            ops.append(Op(("R",), 1, (0,)))
        elif kind == "mul":                     # (iterations, signed)
            ops.append(Op(("A", "R"), 1 + p[0] * aw + (2 if p[1] else 0)))
            ops.append(Op(("R",), 1, (0,)))
        elif kind == "div":                     # (signed,)
            ops.append(Op(("A", "R"), 2 + 32 * aw + (2 if p[0] else 0)))
            ops.append(Op(("R",), 1, (0,)))
        elif kind in ("ld", "op"):              # ld: (ea, size, x); op: (ea, size, x, wb)
            ea, size, x = p[0], p[1], p[2]
            mar, upd = self.ea_ops(ops, ea, x)
            ops.append(Op(("B",), self.mem(size), (mar,)))
            m = len(ops) - 1
            if kind == "op":
                ops.append(Op(("A", "R"), aw, (m,)))
                if p[3]:
                    ops.append(Op(("R",), 1, (len(ops) - 1,)))
            else:
                ops.append(Op(("R",), 1, (m,)))
            self._base_update(ops, upd)
        elif kind == "st":                      # (ea, size, x)
            ea, size, x = p
            mar, upd = self.ea_ops(ops, ea, x)
            ops.append(Op(("B",), self.mem(size), (mar,)))
            self._base_update(ops, upd)
        elif kind == "lea":                     # (ea, x)
            mar, _ = self.ea_ops(ops, p[0], p[1])
            ops.append(Op(("R",), 1, (mar,)))
        elif kind == "br":                      # (taken, x)
            if p[0]:
                ops.append(Op(("A",), self.addr(p[1]), sets_pc=True))
            else:
                ops.append(Op((), 1))
        elif kind == "jmp":                     # (how, x): reg / rel / abs
            how = p[0]
            if how == "reg":
                ops.append(Op(("R",), 1, sets_pc=True))
            elif how == "rel":
                ops.append(Op(("A",), self.addr(p[1]), sets_pc=True))
            else:
                ops.append(Op((), 1, sets_pc=True))
        elif kind == "jmpm":                    # (ea, x): PC <- memory word
            mar, upd = self.ea_ops(ops, p[0], p[1])
            ops.append(Op(("B",), self.mem(4), (mar,), sets_pc=True))
            self._base_update(ops, upd)
        elif kind in ("call", "callm"):         # call: (how, x); callm: (ea, x)
            first = ()
            if kind == "callm":                 # read the target into T first
                mar, upd = self.ea_ops(ops, p[0], p[1])
                ops.append(Op(("B",), self.mem(4), (mar,)))
                self._base_update(ops, upd)
                first = (len(ops) - 1,)
            ops.append(Op(("A", "R"), self.addr(0), first))       # MAR, T <- sp - 4
            push = len(ops) - 1
            ops.append(Op(("B",), self.mem(4), (push,)))          # [sp] <- return address
            ops.append(Op(("R",), 1, (push,)))                    # sp <- T
            how = "mem" if kind == "callm" else p[0]
            if how == "rel":
                ops.append(Op(("A",), self.addr(p[1]), (push,), sets_pc=True))
            elif how == "reg":
                ops.append(Op(("R",), 1, (push,), sets_pc=True))
            else:                               # abs, or the target read from memory
                ops.append(Op((), 1, (push,), sets_pc=True))
        elif kind == "ret":
            ops.append(Op(("R",), 1))                             # MAR, T <- sp
            ops.append(Op(("B",), self.mem(4), (0,), sets_pc=True))
            ops.append(Op(("A",), self.addr(0), (0,)))            # T <- T + 4
            ops.append(Op(("R",), 1, (2,)))                       # sp <- T
        elif kind == "rti":
            ops.append(Op(("R",), 1))
            ops.append(Op(("B",), self.mem(4), (0,)))             # flags
            ops.append(Op(("B",), self.mem(4), (1,), sets_pc=True))
            ops.append(Op(("A",), self.addr(0), (0,)))
            ops.append(Op(("R",), 1, (3,)))
        elif kind in ("trap", "irq"):           # push PC and flags, jump to the vector
            ops.append(Op(("A", "R"), self.addr(0)))              # MAR, T <- sp - 8
            ops.append(Op(("B",), self.mem(4), (0,)))
            ops.append(Op(("B",), self.mem(4), (1,)))
            ops.append(Op(("R",), 1, (0,)))
            ops.append(Op((), 1, (0,), sets_pc=True))
        elif kind == "save":                    # (n,)
            n = p[0]
            ops.append(Op(("A", "R"), self.addr(0)))              # MAR <- sp - 4n; reads the first register too
            prev_mem, prev_read = None, 0
            for i in range(n):
                if i:
                    ops.append(Op(("R",), 1, (prev_read,)))
                    prev_read = len(ops) - 1
                deps = (prev_read,) if prev_mem is None else (prev_read, prev_mem)
                ops.append(Op(("B",), self.mem(4), deps))
                prev_mem = len(ops) - 1
            ops.append(Op(("R",), 1, (0,)))                       # sp <- sp - 4n
        elif kind == "restore":                 # (n,)
            n = p[0]
            ops.append(Op(("R",), 1))                             # MAR, T <- sp
            prev = 0
            for i in range(n):
                ops.append(Op(("B",), self.mem(4), (prev,)))
                prev = len(ops) - 1
                ops.append(Op(("R",), 1, (prev,)))
            ops.append(Op(("A",), self.addr(0), (0,)))
            ops.append(Op(("R",), 1, (len(ops) - 1,)))
        elif kind == "sys":                     # NOP, EI, DI, MTSR, HALT
            ops.append(Op((), 1))
        else:
            raise ValueError(f"unknown timing kind {kind}")
        return ops

    # ---- whole instruction ----

    def cycles(self, key):
        n, pc2, kind = key[0], key[1], key[2]
        p = key[3:]
        n_ext = n - 1
        busy = {"A": set(), "B": set(), "R": set()}
        if self.fetch == "wide":
            # parcels at pc+2... ; the opcode's 32-bit word also held pc+2 if pc is aligned
            if pc2 == 0:
                need = max(0, n_ext - 1)
            else:
                need = n_ext
            ext_fetches = (need + 1) // 2
        else:
            ext_fetches = n_ext
        busy["B"].update(range(ext_fetches))
        ops = self.body(kind, p)
        end, pc_ready = _schedule(ops, ext_fetches, busy)
        t = max(end) if end else ext_fetches
        t = max(t, ext_fetches + 1)
        seq = kind not in NONSEQ and not (kind == "br" and p[0])
        if self.fetch == "separate":
            return 1 + t
        if self.fetch == "overlap":
            # the opcode fetch must fall in the last cycle (IR is reloaded then)
            ready = pc_ready if pc_ready is not None else 0
            if (t - 1) not in busy["B"] and ready <= t - 1:
                return t
            return max(t, ready) + 1
        # wide: next parcel already buffered?
        if seq and (pc2 + 2 * n) % 4 == 2:
            return t
        f = max(ext_fetches, pc_ready if pc_ready is not None else 0)
        while f in busy["B"]:
            f += 1
        return max(t, f + 1)


_models = {name: Model(*cfg) for name, cfg in CONFIGS.items()}


@lru_cache(maxsize=None)
def cycles(key, config):
    return _models[config].cycles(key)
