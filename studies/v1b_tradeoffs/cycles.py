"""Cycle counts for other microarchitectures, from the program suite's
executed instructions.

The model is draft 1's timing model (studies/v1_isa/isa/src/timing.rs,
timing-model-v1.md) ported to Python, with more knobs:

  dp     ALU width, 8, 16 or 32 bits: a 32-bit operation takes 32/dp passes
  bus    memory bus width, 8, 16 or 32 bits
  rfw    register file width: moving a 32-bit register takes 32/rfw passes
  fetch  "separate" (its own cycle per instruction), "overlap" (in the last
         cycle when the bus is free), "wide" (32-bit bus, two-parcel
         prefetch buffer)
  wbf    with a separate fetch, the last register write shares the fetch
         cycle (the draft 1b hardware does this)
  mul    "early": one step per significant bit of the multiplier (the
         model's rule); "fixed": 16 or 32 steps (the draft 1b hardware);
         "r4": two bits a step, 8 or 16 steps
  rf2    a two-phase register file: written in the second half of a cycle,
         after its producer, without taking the read port (an optimistic
         bound: no stalls when the next instruction reads the register)

With dp=32, bus=16, separate fetch, wbf and fixed multiplies it is the 1b
hardware: its cycles over the suite are within 0.1% of the RTL model's
(geometric mean; 0.92-1.15 per program). The other configurations are
then estimates relative to that machine.
"""

import math
import os
import pickle
from collections import Counter, defaultdict
from functools import lru_cache

from heron import BUILD
from heron.infra import asm as asmcore
from heron.infra.programs import metadata
from heron.studies.v1_isa import isas, timing32
from heron.studies.v1_isa.sim32 import Machine32
from heron.studies.v1_isa.testing import program_paths

OUT = os.path.join(BUILD, "v1b_tradeoffs")
A, B, R = 1, 2, 4
SKIP = ("hello", "interrupts")      # as report 0012: no work / mostly halted


class Busy:
    def __init__(self):
        self.c = [set(), set(), set()]

    def free(self, res, t, dur):
        return all(c not in self.c[i] for i in range(3) if res >> i & 1 for c in range(t, t + dur))

    def take(self, res, t, dur):
        for i in range(3):
            if res >> i & 1:
                self.c[i].update(range(t, t + dur))

    def bus(self, c):
        return c in self.c[1]


def schedule(ops, start, busy):
    end, pc_ready = [], None
    for res, dur, deps, sets_pc in ops:
        t = max([start] + [end[d] for d in deps])
        while not busy.free(res, t, dur):
            t += 1
        busy.take(res, t, dur)
        end.append(t + dur)
        if sets_pc:
            pc_ready = t + dur
    return end, pc_ready


class Config:
    def __init__(self, dp=32, bus=16, fetch="separate", mul="fixed", wbf=None, rfw=32, rf2=False):
        self.dp, self.busw, self.fetch, self.mul, self.rfw, self.rf2 = dp, bus, fetch, mul, rfw, rf2
        self.wbf = (fetch == "separate") if wbf is None else wbf

    def key(self):
        return (self.dp, self.busw, self.fetch, self.mul, self.wbf, self.rfw, self.rf2)

    def name(self):
        parts = [f"D{self.dp}", f"B{self.busw}", self.fetch]
        if self.rfw != 32:
            parts.append(f"RF{self.rfw}")
        if self.rf2:
            parts.append("2-phase RF")
        parts.append({"fixed": "mul 16/32", "early": "mul early-out", "r4": "mul 2 bits"}[self.mul])
        return " ".join(parts)

    def cycles(self, key):
        return _cycles(self.key(), key)

    # ---- the micro-operations of one instruction (as timing.rs)

    def aw(self):
        return 32 // self.dp

    def addr(self, x):
        if self.dp == 32:
            return 1
        if self.dp == 16:
            return 1 + x
        return 2 + 2 * x                 # bytes 0-1 of a 16-bit offset, more on a carry

    def rp(self):
        return 32 // self.rfw

    def mem(self, size):
        return max(1, (8 * size) // self.busw)

    def parcel(self):
        return 2 if self.busw == 8 else 1

    def wb(self, ops, deps):
        ops.append((0, 0, deps, False) if self.rf2 else (R, self.rp(), deps, False))

    def ea_ops(self, ops, ea, x, deps):
        ar = A | R
        if ea == "r":
            ops.append((R, self.rp(), deps, False))
        elif ea == "rd":
            ops.append((ar, self.addr(x), deps, False))
        elif ea == "rd32":
            ops.append((ar, self.aw(), deps, False))
        elif ea == "abs":
            ops.append((0, 1, deps, False))
        elif ea == "pc":
            ops.append((A, self.addr(x), deps, False))
        elif ea == "idx":
            ops.append((ar, self.addr(x), deps, False))
            ops.append((ar, self.aw(), [len(ops) - 1], False))
        else:                            # pi, pd: MAR <- R and R +/- size in one cycle
            ops.append((ar, self.addr(x), deps, False))
            return len(ops) - 1, len(ops) - 1
        return len(ops) - 1, None

    def body(self, kind, p):
        ops = []
        aw, ar = self.aw(), A | R
        if kind == "alu":
            ops.append((ar, aw, [], False))
            if p[0]:
                self.wb(ops, [0])
        elif kind == "shift":
            ops.append((ar, max(p[0], 1) * aw, [], False))
            self.wb(ops, [0])
        elif kind == "mul":
            bits, signed = p
            steps = {"early": bits, "fixed": 16 if bits <= 16 else 32,
                     "r4": 8 if bits <= 16 else 16}[self.mul]
            ops.append((ar, 1 + steps * aw + (2 if signed else 0), [], False))
            self.wb(ops, [0])
        elif kind == "div":
            ops.append((ar, 2 + 32 * aw + (2 if p[0] else 0), [], False))
            self.wb(ops, [0])
        elif kind in ("ld", "op"):
            mar, upd = self.ea_ops(ops, p[0], p[2], [])
            ops.append((B, self.mem(p[1]), [mar], False))
            m = len(ops) - 1
            if kind == "op":
                ops.append((ar, aw, [m], False))
                if p[3]:
                    self.wb(ops, [len(ops) - 1])
            else:
                self.wb(ops, [m])
            if upd is not None:
                self.wb(ops, [upd])
        elif kind == "st":
            mar, upd = self.ea_ops(ops, p[0], p[2], [])
            ops.append((B, self.mem(p[1]), [mar], False))
            if upd is not None:
                self.wb(ops, [upd])
        elif kind == "lea":
            mar, _ = self.ea_ops(ops, p[0], p[1], [])
            self.wb(ops, [mar])
        elif kind == "br":
            ops.append((A, self.addr(p[1]), [], True) if p[0] else (0, 1, [], False))
        elif kind == "jmp":
            ops.append({"reg": (R, self.rp(), [], True), "rel": (A, self.addr(p[1]), [], True),
                        "abs": (0, 1, [], True)}[p[0]])
        elif kind == "jmpm":
            mar, upd = self.ea_ops(ops, p[0], p[1], [])
            ops.append((B, self.mem(4), [mar], True))
            if upd is not None:
                self.wb(ops, [upd])
        elif kind in ("call", "callm"):
            first = []
            if kind == "callm":
                mar, upd = self.ea_ops(ops, p[0], p[1], [])
                ops.append((B, self.mem(4), [mar], False))
                if upd is not None:
                    self.wb(ops, [upd])
                first = [len(ops) - 1]
            ops.append((ar, self.addr(0), first, False))
            push = len(ops) - 1
            ops.append((B, self.mem(4), [push], False))
            ops.append((R, self.rp(), [push], False))
            if kind == "call" and p[0] == "rel":
                ops.append((A, self.addr(p[1]), [push], True))
            elif kind == "call" and p[0] == "reg":
                ops.append((R, self.rp(), [push], True))
            else:
                ops.append((0, 1, [push], True))
        elif kind == "ret":
            ops += [(R, self.rp(), [], False), (B, self.mem(4), [0], True),
                    (A, self.addr(0), [0], False), (R, self.rp(), [2], False)]
        elif kind == "rti":
            ops += [(R, self.rp(), [], False), (B, self.mem(4), [0], False),
                    (B, self.mem(4), [1], True), (A, self.addr(0), [0], False),
                    (R, self.rp(), [3], False)]
        elif kind in ("trap", "irq"):
            ops += [(ar, self.addr(0), [], False), (B, self.mem(4), [0], False),
                    (B, self.mem(4), [1], False), (R, self.rp(), [0], False), (0, 1, [0], True)]
        elif kind == "save":
            ops.append((ar, self.addr(0), [], False))
            prev_mem, prev_read = None, 0
            for i in range(p[0]):
                if i > 0:
                    ops.append((R, self.rp(), [prev_read], False))
                    prev_read = len(ops) - 1
                deps = [prev_read] + ([prev_mem] if prev_mem is not None else [])
                ops.append((B, self.mem(4), deps, False))
                prev_mem = len(ops) - 1
            ops.append((R, self.rp(), [0], False))
        elif kind == "restore":
            ops.append((R, self.rp(), [], False))
            prev = 0
            for _ in range(p[0]):
                ops.append((B, self.mem(4), [prev], False))
                prev = len(ops) - 1
                ops.append((R, self.rp(), [prev], False))
            ops.append((A, self.addr(0), [0], False))
            ops.append((R, self.rp(), [len(ops) - 1], False))
        else:                            # sys
            ops.append((0, 1, [], False))
        return ops


NONSEQ = ("jmp", "jmpm", "call", "callm", "ret", "rti", "trap", "irq")


@lru_cache(maxsize=None)
def _cycles(cfg_key, key):
    c = Config(*cfg_key[:4], wbf=cfg_key[4], rfw=cfg_key[5], rf2=cfg_key[6])
    n, pc2, kind, p = key[0], key[1], key[2], key[3:]
    n_ext = max(n - 1, 0)
    busy = Busy()
    pcy = c.parcel()
    if c.fetch == "wide":
        need = max(n_ext - 1, 0) if pc2 == 0 else n_ext
        ext = -(-need // 2) if c.busw == 32 else need * pcy
    else:
        ext = n_ext * pcy
    busy.take(B, 0, ext)
    ops = c.body(kind, p)
    nonseq = kind in NONSEQ or (kind == "br" and p[0])
    if c.wbf and c.fetch == "separate" and ops and ops[-1][0] == R and not nonseq:
        last = ops.pop()                 # rides in the fetch cycle
        end, _ = schedule(ops, ext, busy)
        return max(end + [ext + 1]) + max(pcy, last[1])
    end, pc_ready = schedule(ops, ext, busy)
    t = max(end + [ext + 1])
    if c.fetch == "separate":
        return pcy + t
    if c.fetch == "overlap":
        ready = pc_ready or 0
        if all(not busy.bus(t - 1 - i) for i in range(pcy)) and ready <= t - pcy:
            return t
        return max(t, ready) + pcy
    if c.busw == 32 and not nonseq and (pc2 + 2 * n) % 4 == 2:
        return t
    f = max(ext, pc_ready or 0)
    while busy.bus(f):
        f += 1
    return max(t, f + 1)


HARDWARE = Config(32, 16, "separate", "fixed", wbf=True)


# ---- the program suite's executed instructions

def _cached(name, srcs, compute):
    """compute(), cached in build/v1b_tradeoffs/name until a source changes."""
    path = os.path.join(OUT, name)
    srcs = list(srcs) + [os.path.abspath(__file__)]
    if os.path.exists(path) and os.path.getmtime(path) > max(os.path.getmtime(p) for p in srcs):
        with open(path, "rb") as f:
            return pickle.load(f)
    out = compute()
    os.makedirs(OUT, exist_ok=True)
    tmp = f"{path}.{os.getpid()}"
    with open(tmp, "wb") as f:
        pickle.dump(out, f)
    os.replace(tmp, path)
    return out


def keys(isa="v1b"):
    """{program: [((pc, timing key), count)]} from the instruction-level
    simulator; cached."""
    def compute():
        mod = isas.get(isa)
        out = {}
        for p in program_paths(None, isa):
            img = asmcore.assemble_file(mod, p)
            m = Machine32(mod, img, inp=metadata(p)["input"])
            m.run(max_cycles=400_000_000)
            out[os.path.basename(p)[:-2]] = list(m.pc_keys.items())
        return out
    return _cached(f"keys-{isa}.pkl", program_paths(None, isa), compute)


def _hw_job(path):
    from heron.studies.v1b_hw.rtl import RTL
    mod = isas.get("v1b")
    img = asmcore.assemble_file(mod, path)
    r = RTL(img, inp=metadata(path)["input"])
    r.fetch_log = []
    r.run(max_cycles=400_000_000)
    per_pc = Counter()
    log = [f for f in r.fetch_log if f[0] >= 0]
    for (c0, a0, _), (c1, _, _) in zip(log, log[1:]):
        per_pc[a0] += c1 - c0
    if log:
        per_pc[log[-1][1]] += r.cycles - log[-1][0]
    return os.path.basename(path)[:-2], r.cycles, dict(per_pc)


def hardware(jobs=4):
    """{program: (cycles, {pc: cycles spent there})} on the 1b RTL model
    (the hardware's exact cycles); cached."""
    from heron.studies.v1b_hw import machine

    def compute():
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(jobs) as ex:
            res = list(ex.map(_hw_job, program_paths(None, "v1b")))
        return {name: (cyc, per_pc) for name, cyc, per_pc in res}
    return _cached("hw-cycles.pkl", program_paths(None, "v1b") + machine.sources(), compute)


def geomean(xs):
    xs = list(xs)
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


def total(cfg, prog_keys):
    return sum(n * cfg.cycles(k) for (_pc, k), n in prog_keys)


def programs(isa="v1b"):
    return [p for p in keys(isa) if p not in SKIP]


def relative(cfg, isa="v1b"):
    """Geometric mean over the programs of cycles in cfg / cycles in the
    hardware configuration (same ISA unless isa differs: 1a against 1b)."""
    kb, ki = keys("v1b"), keys(isa)
    return geomean(total(cfg, ki[p]) / total(HARDWARE, kb[p]) for p in programs("v1b"))


def calibration():
    """Per program: hardware cycles (RTL) / the model's hardware
    configuration; and their geometric mean."""
    hw, k = hardware(), keys("v1b")
    per = {p: hw[p][0] / total(HARDWARE, k[p]) for p in programs("v1b")}
    return per, geomean(per.values())


def rust_check(n=200):
    """The port against the Rust model, for the six configurations it
    has, over the suite's most common keys: [(config, key, rust, port)]
    where they differ (empty if none do)."""
    cfgs = {"D16-separate": Config(16, 16, "separate", "early", wbf=False),
            "D16-overlap": Config(16, 16, "overlap", "early"),
            "D16-wide": Config(16, 32, "wide", "early"),
            "D32-separate": Config(32, 16, "separate", "early", wbf=False),
            "D32-overlap": Config(32, 16, "overlap", "early"),
            "D32-wide": Config(32, 32, "wide", "early")}
    count = Counter()
    for isa in ("v1a", "v1b"):
        for prog in keys(isa).values():
            for (_pc, k), c in prog:
                count[k] += c
    bad = []
    for k, _ in count.most_common(n):
        for name, cfg in cfgs.items():
            a, b = timing32.cycles(k, name), cfg.cycles(k)
            if a != b:
                bad.append((name, k, a, b))
    return bad


# ---- floors and what-ifs

def data_transfers(k):
    """Sizes of the data transfers an instruction makes."""
    kind = k[2]
    if kind in ("ld", "st", "op"):
        return [k[4]]
    if kind == "jmpm":
        return [4]
    if kind == "callm":
        return [4, 4]
    if kind in ("call", "ret"):
        return [4]
    if kind == "rti":
        return [4, 4]
    if kind in ("irq", "trap"):
        return [4, 4]
    if kind in ("save", "restore"):
        return [4] * k[3]
    return []


def floors():
    """Cycles per instruction (geometric mean over the programs) of the
    hardware and of three floors: the 16-bit bus busy every cycle
    (parcels and data halves), the same for a 32-bit bus, and one ALU
    cycle per instruction or per multiply, divide or shift step."""
    hw, k = hardware(), keys("v1b")
    rows = defaultdict(list)
    for p in programs("v1b"):
        n = b16 = b32 = alu = 0
        for (_pc, key), c in k[p]:
            x = data_transfers(key)
            n += c
            b16 += c * (key[0] + sum(2 if s == 4 else 1 for s in x))
            b32 += c * ((key[1] // 2 + key[0] + 1) // 2 + len(x))
            kind = key[2]
            steps = (16 if key[3] <= 16 else 32) if kind == "mul" else \
                32 if kind == "div" else key[3] if kind == "shift" else 0
            alu += c * max(1, steps)
        rows["hardware"].append(hw[p][0] / n)
        rows["bus16"].append(b16 / n)
        rows["bus32"].append(b32 / n)
        rows["alu"].append(alu / n)
        rows["max16"].append(max(b16, alu) / n)
        rows["max32"].append(max(b32, alu) / n)
    return {name: geomean(v) for name, v in rows.items()}


def _per_pc(prog_keys, per_pc):
    bypc = defaultdict(list)
    for (pc, key), n in prog_keys:
        bypc[pc].append((key, n))
    for pc, lst in bypc.items():
        tot = sum(n for _, n in lst)
        h = per_pc.get(pc, 0) if pc is not None else 0
        for key, n in lst:
            yield key, n, h / tot


def whatif(fn):
    """Geometric mean, and per program, of the hardware's cycles with each
    instruction's cycles changed by fn(key, cycles)."""
    hw, k = hardware(), keys("v1b")
    per = {}
    for p in programs("v1b"):
        rows = list(_per_pc(k[p], hw[p][1]))
        per[p] = sum(n * fn(key, c) for key, n, c in rows) / sum(n * c for key, n, c in rows)
    return geomean(per.values()), per


def _steps(key):
    return 16 if key[3] <= 16 else 32


WHATIFS = {
    "multiply stops early (one step per multiplier bit)":
        lambda key, c: c - _steps(key) + max(key[3], 1) if key[2] == "mul" else c,
    "multiply two bits a step":
        lambda key, c: c - _steps(key) // 2 if key[2] == "mul" else c,
    "both":
        lambda key, c: c - _steps(key) + math.ceil(max(key[3], 1) / 2) if key[2] == "mul" else c,
    "divide two bits a step":
        lambda key, c: c - 16 if key[2] == "div" else c,
    "no multiply or divide hardware (a shift-and-add subroutine)":
        lambda key, c: (20 + 10 * max(key[3], 1)) if key[2] == "mul" else
        (30 + 8 * 32) if key[2] == "div" else c,
}


def cycle_kinds():
    """Executed microcycles by what they do, over the suite (the RTL
    model's profile): {kind: count}."""
    from heron.studies.v1b_hw import ucode as uc
    from heron.studies.v1b_system import lengths
    prof, words = lengths.profile(), lengths.rom_words()
    out = Counter()
    for a, c in prof.items():
        f = uc.unpack(words[a])
        if f["LDIR"]:
            k = "opcode fetch"
        elif f["MEMRD"] and not f["ADDRMAR"]:
            k = "extension parcel"
        elif f["MEMRD"]:
            k = "data read (a 16-bit half)"
        elif f["MEMWR"]:
            k = "data write (a 16-bit half)"
        elif f["MS"]:
            k = "multiply or divide step"
        elif f["HALT"]:
            k = "halt"
        else:
            k = "ALU, address or shift"
        out[k] += c
    return out


GRID = [
    Config(32, 16, "separate", "fixed"),
    Config(32, 16, "separate", "early"),
    Config(32, 16, "overlap", "fixed"),
    Config(32, 16, "overlap", "fixed", rf2=True),
    Config(32, 32, "wide", "fixed"),
    Config(32, 32, "wide", "early"),
    Config(32, 32, "wide", "fixed", rf2=True),
    Config(32, 32, "wide", "early", rf2=True),
    Config(32, 8, "separate", "fixed"),
    Config(16, 16, "separate", "fixed", rfw=16),
    Config(16, 16, "separate", "fixed"),
    Config(16, 16, "overlap", "fixed", rfw=16),
    Config(16, 32, "wide", "fixed", rfw=16),
    Config(16, 32, "wide", "fixed"),
    Config(16, 32, "wide", "early", rf2=True),
    Config(8, 8, "separate", "fixed", rfw=8),
    Config(8, 16, "separate", "fixed", rfw=8),
    Config(8, 32, "wide", "fixed", rfw=8),
]
