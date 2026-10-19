"""How long each microinstruction's cycle must be: what static timing
analysis of the netlist measured (ticks.json, once it exists), or else an
estimate from the paths the microinstruction uses, with worst-case
datasheet delays (infra/hw/timing.json) for the parts RFC 0041 names.

A cycle is K ticks of the 50.35 MHz master clock (twice VGA's pixel
clock, 19.86 ns a tick), K = 5 to 20, from a clock generator like draft
2's CPU's (RFC 0031, 2) with two tail ticks: two head ticks, the count,
two tail ticks. Times are from the CPU clock's rising edge; the cycle's
own work must be done by the next one:

  - a register (R, MAR, PC, flags, ...) needs its input `setup` before the
    edge;
  - the register file is written in the last tick, its address switched
    to the write address for the two tail ticks;
  - the two tail ticks also belong to the video (RFC 0041): RAM data a
    cycle reads must be in T (or a queue slot) by then;
  - memory is written in a window from tick 2 to the tail;
  - a data access may be to the I/O space, whose wait states hold the
    count from tick 3: such a cycle is at least 6 ticks;
  - the next microinstruction's address must reach the control store
    flash tACC + the uIR's setup before the edge.

assign_classes() gives every microinstruction its ticks, picks four
lengths that minimise the program suite's time given a profile (or the
commonest needs before there is one), and sets each microinstruction's
length class.
"""

import json
import math
import os

from heron.infra.hw import chips

# ns: the master clock is twice VGA's pixel clock, 25.175 MHz; while an
# XGA mode is shown it is 65 MHz, XGA's pixel clock (RFC 0042), and the
# clock generator's length classes are another table, from static timing
# analysis at that tick (HERON_MINI_TICK: the tick the analysis runs at)
VGA_TICK = 1e3 / 50.35
XGA_TICK = 1e3 / 65
TICK = float(os.environ.get("HERON_MINI_TICK", VGA_TICK))
HEAD, TAIL = 2, 2
K_MIN, K_MAX = HEAD + 1 + TAIL, HEAD + 16 + TAIL
VIDEO_TICKS = TAIL          # the tail ticks are the video's
K_WRITE = HEAD + 1 + TAIL   # the write window: tick 2 to the tail
K_READ = HEAD + TAIL + 1    # a read's data is in by the tail
K_DATA = 7                  # a data access may hold the count from tick 4

_T = None
HERE = os.path.dirname(os.path.abspath(__file__))
XTICKS_PATH = os.path.join(HERE, "ticks-xga.json")
TICKS_PATH = os.path.join(HERE, "ticks.json") if abs(TICK - VGA_TICK) < 1e-6 else XTICKS_PATH
NOT_TIMED = ("NEXT", "LCL", "LL")    # fields that don't change a cycle's paths


def _d(part, name):
    global _T
    if _T is None:
        _T = chips.load_timing()
    return _T[part]["delays"][name]["max"]


def _c(part, name):
    global _T
    if _T is None:
        _T = chips.load_timing()
    return _T[part]["checks"][name]


def delays():
    """The building blocks, in ns (worst case)."""
    reg = _d("74ABT574", "CLK->Q")                 # uIR, R, the slots...
    cnt = _d("74F161", "CLK->Q")                   # PC, FPC, MAR, LC
    mux2 = _d("74F157", "S->Y")
    mux4 = _d("74F153", "S->Y")
    mux4d = _d("74F153", "C->Y")
    mux8 = _d("74F151", "S->Y")
    buf = _d("74ABT541", "A->Y")
    bufen = _d("74ABT541", "OE->Y en")
    sram = _d("AS7C256A-12", "tAA")
    ram = _d("AS7C4096A-12", "tAA")
    flash = _d("SST39SF010A-55", "tACC")
    latch = _d("74ABT573", "D->Q")
    alu_logic = _d("74F181", "AB->F logic")
    # 32-bit add: P/G out of the first 181, two levels of 182, the carry
    # into the last 181, its F
    alu_add = (_d("74F181", "AB->G") + _d("74F182", "PG->G") + _d("74F182", "PG->CN")
               + _d("74F182", "CN->CN") + _d("74F181", "CN->F"))
    gate = _d("74F08", "A->Y")
    xor = _d("74F86", "A->Y")
    cmp = _d("74F521", "P->PEQ")
    return dict(
        uir=reg,
        # the register file: address mux, SRAM, the read latch
        rf=reg + mux8 + sram + latch,
        pc=cnt + buf, r=reg + buf, r2=reg + mux4d + buf,
        imm=reg + bufen,                            # KONST or the fill onto B
        fill=reg + mux8 + buf,
        qh=reg + bufen,                             # the queue's head: a slot's half
        mq=_d("74F299", "CLK->Q") + bufen,
        spr=reg + bufen,
        # memory: the address mux (MAR, FPC or the A bus: 74F153s), the RAM
        vaddr_reg=cnt + mux4d, vaddr_a=mux4d,
        ram=ram,
        tlat=latch + buf,                           # T, transparent, onto B by lanes
        slot=latch + buf,                           # a queue slot, transparent, onto QH
        alu_logic=alu_logic, alu_add=alu_add, carry=_d("74F181", "CN->CN4"),
        res=mux4d, rz=_d("74F153", "G->Y") - mux4d,
        zero=cmp + gate,                            # RES == 0
        vflag=xor + _d("74F151", "D->Y"),
        rf_setup=buf + _c("AS7C256A-12", "tDW") - 6.0,   # the strobe rises 6 ns after the edge
        reg_setup=_c("74ABT574", "setup D"), cnt_setup=_c("74F161", "setup data"),
        cs=flash + _c("74ABT574", "setup D"),           # next address -> uIR
        gate=gate, mux2=mux2, mux4=mux4, mux4d=mux4d, mux8=mux8,
    )


_D = None


def estimate(f):
    """Nanoseconds the microinstruction with fields f needs, from the CPU
    clock's edge, and the ticks that gives."""
    global _D
    if _D is None:
        _D = delays()
    d = _D
    mem = f.get("MEM", 0)
    memt = d["vaddr_reg"] + d["ram"]                 # data from the RAM, MAR's address
    fetch = d["vaddr_reg"] + d["ram"] + d["slot"]    # a fetched word's half on QH
    a = 0.0
    if f.get("ARF"):
        a = d["rf"]
    elif f.get("APC"):
        a = d["pc"]
    elif f.get("AR"):
        a = d["r"]
    elif f.get("AR2"):
        a = d["r2"]
    if mem == 6:                                     # a read at the A bus: the address from it
        memt = a + d["vaddr_a"] + d["ram"]
    b = 0.0
    if f.get("BRF"):
        b = max(b, d["rf"])
    if f.get("BR"):
        b = max(b, d["r"])
    if f.get("BS0") or f.get("BF1") or f.get("BF23"):
        b = max(b, d["imm"], d["fill"] + (d["rf"] if f.get("FSEL") in (5, 6) and f.get("ARF")
                                          else 0))
    bl, bx = f.get("BL", 0), f.get("BX", 0)
    if bl >= 4:
        # the queue's head; or, if the queue is empty, the word this cycle
        # fetches (a cycle that consumes a parcel fetches it if need be)
        b = max(b, fetch if f.get("CONSUME") or f.get("SEQ") == 2 else d["qh"])
    elif bl:
        b = max(b, memt + d["tlat"] if mem in (1, 6) else d["r"])
    if bx:
        b = max(b, d["mq"] if bx == 1 else d["spr"])
    m = f.get("M", 0)
    arith = not m
    t_f = max(a, b) + (d["alu_add"] if arith else d["alu_logic"])
    if f.get("MS"):
        t_f = max(a, b) + 12 + d["alu_add"]          # the step select in front of S
    t_res = t_f + d["res"] + (d["rz"] if f.get("RZ") else 0)
    need = (K_MIN - 1) * TICK                        # nothing is shorter than K_MIN
    if f.get("RFWE"):
        need = max(need, t_res + d["rf_setup"])
    if f.get("LDR"):
        need = max(need, t_res + d["reg_setup"])
    if f.get("LDMAR") or f.get("LDPC") or f.get("LDLC"):
        need = max(need, t_res + d["cnt_setup"])
    if f.get("FNZ"):
        need = max(need, t_res + d["zero"] + d["reg_setup"])
    if f.get("FV") == 7:
        need = max(need, t_f + d["vflag"] + d["reg_setup"])
    if f.get("FC") == 2:
        need = max(need, max(a, b) + d["alu_add"] - d["res"] + d["reg_setup"])
    if f.get("LDCL"):
        need = max(need, t_res + d["zero"] + d["reg_setup"])
    if f.get("MQM"):
        need = max(need, t_f + 5.5)
    seq = f.get("SEQ", 0)
    # the next address: SEQ selects the Y multiplexers (74F153s) as the
    # cycle starts; their data is NEXT, the head parcel or the condition
    sel = d["uir"] + d["mux4"]
    if seq == 1:                                     # decode: the head parcel -> control store
        t_dec = max(sel, d["qh"] + d["mux4d"]) + d["cs"]
        if mem == 3:                                 # a refill decodes the word it fetches
            t_dec = max(sel, fetch + d["mux4d"]) + d["cs"]
        need = max(need, t_dec)
    elif seq == 2:                                   # dispatch on the head parcel
        need = max(need, max(sel, fetch + d["mux4d"]) + d["cs"])
    elif f.get("COND"):
        cond_t = {2: d["r"], 3: d["uir"], 4: d["uir"] + 10, 7: d["uir"] + 10,
                  9: d["uir"] + 15, 12: d["uir"] + 15}.get(f["COND"], d["uir"] + 8)
        need = max(need, max(sel, cond_t + d["mux8"] + d["mux4d"]) + d["cs"])
    else:
        need = max(need, sel + d["cs"])
    ticks = max(K_MIN, math.ceil((need + 1.0) / TICK))
    # the video's ticks: a read's data, and a fetch's word, must be in
    # before them
    if mem in (1, 3, 6):
        rd = memt if mem != 3 else fetch
        ticks = max(ticks, K_READ, math.ceil((rd + d["reg_setup"]) / TICK) + VIDEO_TICKS)
    if mem == 2:
        ticks = max(ticks, K_WRITE)
    if mem in (1, 2, 6):
        ticks = max(ticks, K_DATA)
    return need, min(ticks, K_MAX)


# Four lengths, the jumpers. Until a profile picks them: the commonest needs.
DEFAULT_LENGTHS = (5, 6, 7, 8)


def best_lengths(need_counts, k=4):
    """Four lengths minimising sum(count x length) where each microinstruction
    takes the shortest length >= its need: need_counts {ticks: count}."""
    needs = sorted(need_counts)
    if len(needs) <= k:
        return tuple(sorted(set(needs) | set(range(needs[-1], needs[-1] + k - len(needs)))))[:k]
    best = None
    import itertools
    top = needs[-1]
    for combo in itertools.combinations(needs[:-1], k - 1):
        lens = combo + (top,)
        cost = 0
        for n, c in need_counts.items():
            cost += c * min(L for L in lens if L >= n)
        if best is None or cost < best[0]:
            best = (cost, lens)
    return best[1]


def word_mask():
    """The control word's bits that a cycle's timing depends on."""
    from . import ucode as uc
    m = (1 << uc.WORD_BITS) - 1
    for name in NOT_TIMED:
        bit, w, _ = uc._pos[name]
        m &= ~(((1 << w) - 1) << bit)
    return m


def timing_key(f):
    """A microinstruction's key in ticks.json."""
    from . import ucode as uc
    return f"{uc.pack(f) & word_mask():x}"


_TABLE = {}


def measured(path=None):
    """{key: ns} from static timing analysis (ticks.json, or path), or {}."""
    path = path or TICKS_PATH
    if path not in _TABLE:
        _TABLE[path] = {}
        if os.path.exists(path):
            with open(path) as f:
                _TABLE[path] = json.load(f)["ns"]
    return _TABLE[path]


def ticks_of(ns, f, tick=None):
    """Ticks for a cycle that needs ns, at least what the clock generator
    and the memory rules make it."""
    tick = tick or TICK
    if ns > K_MAX * tick:
        raise ValueError(f"a cycle of {ns:.1f} ns is longer than {K_MAX} ticks")
    mem = f.get("MEM", 0)
    t = max(K_MIN, math.ceil(ns / tick - 1e-9))
    if mem in (1, 3, 6):
        t = max(t, K_READ)
    if mem == 2:
        t = max(t, K_WRITE)
    if mem in (1, 2, 6):
        t = max(t, K_DATA)
    return t


def assign_classes(mc, lengths=None, profile=None):
    """Give every microinstruction in Microcode mc its ticks (measured, or
    estimated: mc.estimated counts those) and a length class (LCL) for the
    jumpers `lengths`. profile: {node id: executions}, to pick the lengths
    by."""
    from collections import Counter
    mc.ticks = {}
    mc.need_ns = {}
    mc.estimated = 0
    table = measured()
    for n in mc.nodes:
        f = mc.word(n, 0 if n.addr is None else n.addr)
        ns = table.get(timing_key(f))
        if ns is None:
            ns, t = estimate(f)
            mc.estimated += 1
        else:
            t = ticks_of(ns, f)
        mc.ticks[id(n)] = t
        mc.need_ns[id(n)] = ns
    if lengths is None:
        if profile:
            counts = Counter()
            for i, c in profile.items():
                if i in mc.ticks:
                    counts[mc.ticks[i]] += c
        else:
            counts = Counter(mc.ticks.values())
        lengths = best_lengths(counts)
    lengths = tuple(lengths)
    mc.lengths = lengths
    for n in mc.nodes:
        t = mc.ticks[id(n)]
        cls = next((i for i, L in enumerate(lengths) if L >= t), len(lengths) - 1)
        if lengths[cls] < t:
            raise ValueError(f"{n.name}: needs {t} ticks, longer than every length class")
        n.f = dict(n.f)
        n.f["LCL"] = cls
    # XGA's lengths: each class as long as its longest member needs at
    # XGA's tick (measured, or estimated from the VGA need)
    xtable = measured(XTICKS_PATH) if abs(TICK - VGA_TICK) < 1e-6 else {}
    mc.xticks = {}
    for n in mc.nodes:
        f = mc.word(n, 0 if n.addr is None else n.addr)
        ns = xtable.get(timing_key(f))
        if ns is None:
            ns = mc.need_ns[id(n)] + 2 * (VGA_TICK - XGA_TICK) + XGA_TICK
        mc.xticks[id(n)] = ticks_of(ns, f, XGA_TICK)
    xl = [max([mc.xticks[id(n)] for n in mc.nodes if n.f["LCL"] == c] or [lengths[c] + 1])
          for c in range(len(lengths))]
    if len(lengths) < 4:
        # a spare class: split the one whose members' XGA ticks differ the
        # most, those that need fewer in the class as it is
        best = None
        for c in range(len(lengths)):
            xs = Counter(mc.xticks[id(n)] for n in mc.nodes if n.f["LCL"] == c)
            for lo in xs:
                gain = sum(k * (xl[c] - lo) for x, k in xs.items() if x <= lo)
                if lo < xl[c] and (best is None or gain > best[0]):
                    best = (gain, c, lo)
        if best:
            _, c, lo = best
            for n in mc.nodes:
                if n.f["LCL"] == c and mc.xticks[id(n)] > lo:
                    n.f["LCL"] = len(lengths)
            lengths = lengths + (lengths[c],)
            xl = xl[:c] + [lo] + xl[c + 1:] + [xl[c]]
            mc.lengths = lengths
    mc.xlengths = tuple(xl)
