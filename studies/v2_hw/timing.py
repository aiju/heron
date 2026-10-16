"""How long each microinstruction's cycle must be: an estimate from the
paths it uses, with worst-case datasheet delays (infra/hw/timing.json) for
the parts RFC 0031 names, until there is a netlist for static timing
analysis to run on.

A cycle is K ticks of 20 ns from a 50 MHz master clock, K = 4 to 19, as on
the fast CPU card of RFC 0024 (studies/v1b_tradeoffs/fastcard.py). Times
here are from the CPU clock's rising edge; the cycle's own work must be
done by the next one:

  - a register (R, MAR, PC, flags, ...) needs its input `setup` before the
    edge;
  - the register file is written in the last tick, and its write strobe
    rises a gate after the edge: data must be there tDW before that;
  - memory is written in a window from tick 4 to the last tick;
  - the next microinstruction's address must reach the control store SRAM
    tAA + the uIR's setup before the edge.

Each path is a sum of the delays of the parts along it (names below), so
the classes can be redone when a part changes. assign_classes() gives every
microinstruction its ticks, picks four lengths that minimise the program
suite's time given a profile (or a fixed set before there is one), and sets
each microinstruction's length class.
"""

import json
import math
import os

from heron.infra.hw import chips

TICK = 20.0
K_MIN, K_MAX = 4, 19
K_BUS = 6                   # a data access may go to the bus: the hold comes at tick 3
K_WRITE = 6                 # the memory write window: tick 4 to the last tick

_T = None


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
    reg = _d("74ABT377", "CLK->Q")                 # uIR, R, T's lanes...
    cnt = _d("74F161", "CLK->Q")                   # PC, FPC, MAR, LC
    mux2 = _d("74F157", "S->Y")
    mux2d = _d("74F157", "A->Y")
    mux4 = _d("74F153", "S->Y")
    mux4d = _d("74F153", "C->Y")
    mux8 = _d("74F151", "S->Y")
    buf = _d("74ABT541", "A->Y")
    bufen = _d("74ABT541", "OE->Y en")
    sram = _d("IS61C6416AL-12", "tAA")
    ram = _d("AS7C4096A-12", "tAA")
    alu_logic = _d("74F181", "AB->F logic")
    # 32-bit add: P/G out of the first 181, two levels of 182, the carry
    # into the last 181, its F
    alu_add = (_d("74F181", "AB->G") + _d("74F182", "PG->G") + _d("74F182", "PG->CN")
               + _d("74F182", "CN->CN") + _d("74F181", "CN->F"))
    gate = _d("74F08", "A->Y")
    xor = _d("74F86", "A->Y")
    cmp = _d("74F521", "P->PEQ")
    latch = 5.3                                     # 74ABT573 D->Q (not in timing.json yet)
    return dict(
        uir=reg,
        # the register file: address mux, SRAM, the read latch
        rf=reg + mux4 + sram + latch,
        pc=cnt + buf, r=reg + buf, r2=reg + mux4d + buf, mar=cnt + buf,
        imm=reg + mux8 + buf,                       # V8 from the uIR
        qh=reg + mux2 + buf,
        mq=_d("74F299", "CLK->Q") + bufen,
        spr=reg + bufen,
        # memory: the map's address mux, the map, the window mux, the RAM
        # the VA mux has three ways (MAR, FPC, the A bus: 74F153s); MAR and
        # FPC through its select, the A bus through its data inputs
        vaddr_mar=cnt, vaddr_fpc=cnt, vaddr_a=mux4d - mux4,
        map=mux4 + sram, phys=mux2d, ram=ram,
        tlat=latch + buf,                           # T, transparent, onto B by lanes
        alu_logic=alu_logic, alu_add=alu_add, carry=_d("74F181", "CN->CN4"),
        res=mux4d, rz=_d("74F153", "G->Y") - mux4d,
        zero=cmp + gate,                            # RES == 0
        vflag=xor + _d("74F151", "D->Y"),
        rf_setup=buf + _c("IS61C6416AL-12", "tDW") - 6.0,  # the strobe rises 6 ns after the edge
        reg_setup=_c("74ABT377", "setup D"), cnt_setup=_c("74F161", "setup data"),
        cs=mux4d + sram + _c("74ABT377", "setup D"),      # next address -> uIR
        decode=sram,                                # the decode table
        gate=gate, mux2=mux2,
    )


_D = None


# Changes to the design whose effect on time RFC 0031 measures, without
# building them: names for estimate()'s `what_if`.
WHAT_IF = {
    "zreg": "Z and V from registers: the cycle that sets them clocks RES and the "
            "operands' signs, and Z and V are worked out after the edge",
    "rfearly": "the register file's addresses a cycle early: muxed from the "
               "control store's output into a register beside the uIR",
}


def estimate(f, what_if=()):
    """Nanoseconds the microinstruction with fields f needs, from the CPU
    clock's edge, and the ticks that gives."""
    global _D
    if _D is None:
        _D = delays()
    d = _D
    if "rfearly" in what_if:
        d = dict(d, rf=d["rf"] - (_d("74F153", "S->Y")))
    mem = f.get("MEM", 0)
    # memory: data at T, or the fetch's word
    memt = d["vaddr_mar"] + d["map"] + d["phys"] + d["ram"]
    fetch = d["vaddr_fpc"] + d["map"] + d["phys"] + d["ram"]
    a = 0.0
    if f.get("ARF"):
        a = d["rf"]
    elif f.get("APC"):
        a = d["pc"]
    elif f.get("AR"):
        a = d["r"]
    elif f.get("AR2"):
        a = d["r2"]
    elif f.get("AMAR"):
        a = d["mar"]
    if mem == 6:                                     # a read at the A bus: VA from it
        memt = a + d["vaddr_a"] + d["map"] + d["phys"] + d["ram"]
    b = 0.0
    if f.get("BRF"):
        b = max(b, d["rf"])
    if f.get("BR"):
        b = max(b, d["r"])
    if f.get("BS0") or f.get("BF1") or f.get("BF23"):
        b = max(b, d["imm"] + (d["rf"] if f.get("FSEL") in (5, 6) and f.get("ARF") else 0))
    bl, bx = f.get("BL", 0), f.get("BX", 0)
    if bl >= 4:
        b = max(b, d["qh"])
    elif bl:
        b = max(b, memt + d["tlat"] if mem in (1, 6) else d["r"])
    if bx == 1:
        b = max(b, d["mq"])
    elif bx:
        b = max(b, (memt if bx == 5 else 0) + d["spr"])
    s = f.get("S", 0)
    m = f.get("M", 0)
    arith = not m
    t_f = max(a, b) + (d["alu_add"] if arith else d["alu_logic"])
    if f.get("MS"):
        t_f = max(a, b) + 12 + d["alu_add"]          # the step select in front of S
    t_res = t_f + d["res"] + (d["rz"] if f.get("RZ") else 0)
    need = 3 * TICK                                  # nothing is shorter than 4 ticks
    if f.get("RFWE"):
        need = max(need, t_res + d["rf_setup"])
    if f.get("LDR") or f.get("LDCTX") or f.get("LDBANK"):
        need = max(need, t_res + d["reg_setup"])
    if f.get("LDMAR") or f.get("LDPC") or f.get("LDLC"):
        need = max(need, t_res + d["cnt_setup"])
    if f.get("FNZ") == 1 and "zreg" in what_if:
        need = max(need, t_res + d["reg_setup"])
    elif f.get("FNZ"):
        need = max(need, t_res + d["zero"] + d["reg_setup"])
    if f.get("FV") == 7 and "zreg" in what_if:
        need = max(need, t_f + d["reg_setup"])
    elif f.get("FV") == 7:
        need = max(need, t_f + d["vflag"] + d["reg_setup"])
    if f.get("FC") == 2:
        need = max(need, max(a, b) + d["alu_add"] - d["res"] + d["reg_setup"])
    if f.get("LDCL"):
        need = max(need, t_res + d["zero"] + d["reg_setup"])
    if f.get("MQM"):
        need = max(need, t_f + 5.5)
    seq = f.get("SEQ", 0)
    # with the register file's addresses a cycle early, the next
    # microinstruction's are muxed after the control store
    cs = d["cs"] + (_d("74F153", "S->Y") if "rfearly" in what_if else 0)
    if seq == 1:                                     # decode: queue -> table -> control store
        t_dec = d["qh"] + d["decode"] + 12 + cs
        if mem == 3:                                 # a refill decodes the word it fetches
            t_dec = fetch + d["mux2"] + d["decode"] + 12 + cs
        need = max(need, t_dec)
    elif f.get("COND"):
        zcond = d["zero"] if "zreg" in what_if else 0
        cond_t = {2: d["r"], 3: d["uir"], 4: d["uir"] + 10 + zcond, 7: d["uir"] + 10 + zcond,
                  9: d["uir"] + 15, 12: d["uir"] + 15}.get(f["COND"], d["uir"] + 8)
        need = max(need, cond_t + d["mux2"] + cs)
    if mem in (1, 2, 4, 5, 6):
        fault = memt + 13                            # the map's bits -> FAULT -> control store
        need = max(need, fault + d["cs"])
        if mem in (1, 6) and not bl:
            need = max(need, memt + d["reg_setup"])
    ticks = max(K_MIN, math.ceil((need + 1.0) / TICK))
    if mem in (1, 2, 6):
        ticks = max(ticks, K_BUS)                    # it may go to the bus
    if mem in (2, 5):
        ticks = max(ticks, K_WRITE)
    if mem == 3:
        ticks = max(ticks, K_BUS)                    # a demand fetch may go to the bus
    return need, min(ticks, K_MAX)


# Four lengths, the jumpers. Until a profile picks them: the commonest needs.
DEFAULT_LENGTHS = (4, 5, 6, 7)


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


def assign_classes(mc, lengths=None):
    """Give every microinstruction in Microcode mc its ticks and a length
    class (LCL) for the jumpers `lengths`."""
    mc.ticks = {}
    mc.need_ns = {}
    for n in mc.nodes:
        ns, t = estimate(mc.word(n))
        mc.ticks[n.addr] = t
        mc.need_ns[n.addr] = ns
    if lengths is None:
        from collections import Counter
        lengths = best_lengths(Counter(mc.ticks.values()))
    lengths = tuple(lengths)
    mc.lengths = lengths
    for n in mc.nodes:
        t = mc.ticks[n.addr]
        cls = next((i for i, L in enumerate(lengths) if L >= t), len(lengths) - 1)
        if lengths[cls] < t:
            raise ValueError(f"{n.name}: needs {t} ticks, longer than every length class")
        n.f = dict(n.f)
        n.f["LCL"] = cls


def write_profile(path, counts):
    with open(path, "w") as f:
        json.dump(counts, f)


def read_profile(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)
