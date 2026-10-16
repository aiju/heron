"""Static timing analysis of the draft 2 CPU's netlist: infra/hw/sta.py's
case analysis, once per distinct microinstruction, on cpu.build()'s
netlist with the clock generator as a fixture (`tickclk`): CLK's edge at
0, the phases the tick counter makes at fixed times after it, and the
register file in its read phase.

  MWIN   the memory write window, from tick 4 to the tail tick
  LATE   from tick 2: the store data's drivers

The register file's write phase, which the case analysis doesn't see, is
checked here (extra_checks), at the corner's delays:

  - the read latches (and T's) close when RW rises, two ticks before the
    edge: what they hold must be there their setup before;
  - the write strobe is the tail tick: the result must reach the SRAM
    through the write buffers tDW before it ends, the write address tAS
    before it starts, and FAULT, which gates it, must have settled;
  - FAULT gates memory writes too: it must settle before the window opens.

A microinstruction's ticks are its period in 20 ns ticks, rounded up, and
at least what the clock generator and the memory rules (timing.py's K_MIN,
K_BUS, K_WRITE) make it.

`heron v2_hw hw sta` writes the analysis (cached in build/v2_hw): the
slowest microinstructions with their critical paths, the ticks against
timing.py's estimate, and the program suite's time with each.
"""

import json
import math
import os
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

from heron.infra.hw import chips, runner, sta as hsta

from . import cpu, hw, parts, timing, ucode as uc

NAME = "v2"
TICK = timing.TICK
CORNER = "max"
TURNOFF = True                  # three-state buses and multiplexers: see infra/hw/sta.py
SHARP = True
WS, WE = 0.5, 0.875             # unused: the windows are WINDOWS'


def _delays(chip_type, part=None):
    timing_db = chips.load_timing()
    pn = chips.part_number(parts.VARIANT, chip_type, part=part)
    return {k: v / 1000.0 for k, v in chips.delays_for(timing_db, pn, CORNER).items()}


def _clock_offsets():
    """When the clock generator's phases change, after CLK's edge, beyond
    their ticks: each is a flip-flop on the master clock, as CLK is, and
    gates."""
    d175 = _delays("175")["CLK->Q"]
    return {
        "MWIN": _delays("109")["CLK->Q"] - d175 + _delays("08")["A->Y"],
        "LATE": _delays("02")["A->Y"],
        "RW": _delays("163", "74ACT163")["CLK->RCO"] - d175 + _delays("32")["A->Y"],
        "T1": 0.0,
    }


OFFSETS = _clock_offsets()
WINDOWS = {
    "MWIN": (0.0, 4 * TICK + OFFSETS["MWIN"], 1.0, -TICK + OFFSETS["MWIN"]),
    "LATE": (0.0, 2 * TICK + OFFSETS["LATE"], 0.0, 0.0),
}


def build():
    return cpu.build(sim=False)


def control_nets():
    """uIR bit -> net, for the fields the case analysis holds constant (not
    the next address or the length class: timing.NOT_TIMED)."""
    mask = timing.word_mask()
    return {b: n for b, n in cpu.control_nets().items() if mask >> b & 1}


def _mask():
    return timing.word_mask()


# The queue's and the fetch's state, split: with a parcel in Q0 the head
# comes from it, and only then does the decode's length decide whether a
# refill's fetch faults; with FOK a prefetch reads the RAM at the kept page,
# without it the map translates FPC and nothing is fetched
QUEUE = tuple((("V0", v), ("V0_n", 1 - v), ("FOK", f), ("FOK_n", 1 - f))
              for v in (0, 1) for f in (0, 1))


# A decode goes ahead, or a forced entry (trace, interrupt) takes the
# address: then the decode table doesn't reach the control store
DECODE = ((("TSQ", 0), ("TSQ_n", 1), ("IRQP", 0), ("IRQP_n", 1)),
          (("TSQ", 1), ("TSQ_n", 0)),
          (("TSQ", 0), ("TSQ_n", 1), ("IRQP", 1), ("IRQP_n", 0)))


def uses_queue(f):
    """Whether a microinstruction reads the queue's head as an operand:
    then Q0 holds it (the decode waited for the whole instruction)."""
    return (f.get("BL", 0) >= 4 or f.get("FSEL", 0) in (3, 4) or f.get("LDSX") == 3
            or f.get("LDEX") == 2 or f.get("CONSUME") or f.get("SEQ") == uc.SEQ_DISPATCH)


def states(f):
    """The extra constants a microinstruction is analysed with."""
    qs = [q for q in QUEUE if not (uses_queue(f) and dict(q)["V0"] == 0)]
    if f.get("SEQ") in (uc.SEQ_DECODE, uc.SEQ_HALT):
        return [q + d for q in qs for d in DECODE]
    return qs


def sta_words():
    """{(control word, extra constants): [labels]} for every distinct
    microinstruction (the next address and the length class left out), in
    each state it may meet."""
    words = defaultdict(list)
    mc = uc.built()
    mask = _mask()
    for n in mc.nodes:
        f = mc.word(n)
        for q in states(f):
            words[(uc.pack(f) & mask, q)].append(f"{n.name} @{n.addr:04X}")
    return words


# ---- the register file's write phase, and FAULT ------------------------------------------


def extra_checks(case, N):
    out = []
    u = {v[1:]: v for v in cpu.control_nets().values()}
    d = {ref: N.delay[ref] for ref in ("U_RWA0", "U_RFAA0", "U_RFA0", "U_RLA0")}
    nand3 = N.delay[N.drivers["RFWE_n"][0][0].ref]["A->Y"]
    inv = N.delay[N.drivers["RW_n"][0][0].ref]["A->Y"]
    and2 = N.delay[N.drivers["TLE"][0][0].ref]["A->Y"]
    sram = d["U_RFA0"]
    rw = -2 * TICK + OFFSETS["RW"]                   # RW rises, after T
    strobe = -TICK + OFFSETS["T1"] + nand3          # the write strobe falls, after T
    # the latches close as LE falls: they hold what's there their setup before
    for inst in N.insts:
        if inst.type.model != "latch573":
            continue
        le = inst.conn["LE"]
        if case.net(le)[0] == 0:
            continue
        if le == "RW_n" and case.pin(inst, "OE")[0] == 1:
            continue                    # the register file's latch, not on its bus
        close = rw + inv + (and2 if le == "TLE" else 0)
        su = N.delay[inst.ref]["setup D"]
        worst = max(range(1, 9), key=lambda i: case.pin(inst, f"D{i}")[1])
        t = case.pin(inst, f"D{worst}")[1]
        if t != hsta.NEG:
            out.append(("setup", t + su - close, f"{inst.ref} latch setup (closes at RW)",
                        inst.conn[f"D{worst}"]))
    fault_t = case.net("FAULT_n")[1]
    if case.net(u["RFWE"])[0] != 0:
        res = [f"RES{i}" for i in range(32)]
        worst = max(res, key=lambda n: case.net(n)[1])
        t = case.net(worst)[1]
        buf = d["U_RWA0"]["A->Y"]
        out.append(("setup", t + buf + sram["tDW"] - nand3,
                    "register file write: data setup to end of write (tDW)", worst))
        rwa = [f"RWA{i}" for i in range(13)] + ["GW_n"]
        worst = max(rwa, key=lambda n: case.net(n)[1])
        mux = d["U_RFAA0"]["D->Y"]
        out.append(("setup", case.net(worst)[1] + mux + sram["tAS"] - strobe,
                    "register file write: address setup to write (tAS)", worst))
        if fault_t != hsta.NEG:
            out.append(("setup", fault_t - (strobe - nand3),
                        "register file write: FAULT settles before the strobe", "FAULT_n"))
    if case.net("MWOK")[0] != 0 and fault_t != hsta.NEG:
        a, b, _, _ = WINDOWS["MWIN"]
        if fault_t > b:
            out.append(("setup", math.inf, "memory write: FAULT settles after the window opens",
                        "FAULT_n"))
    return out


def fixed_checks(N):
    """Requirements that don't depend on the microinstruction or the period:
    (description, slack in ns)."""
    sram = N.delay["U_RFA0"]
    nand3 = N.delay[N.drivers["RFWE_n"][0][0].ref]["A->Y"]
    nand2 = N.delay[N.drivers["RFWB_n"][0][0].ref]["A->Y"]
    buf = N.delay["U_RWA0"]
    mux = N.delay["U_RFAA0"]
    rw = -2 * TICK + OFFSETS["RW"]
    strobe = -TICK + nand3
    return [
        ("register file: write buffers on, tDW before the strobe ends",
         nand3 - (-TICK + nand2 + buf["OE->Y en"] + sram["tDW"])),
        ("register file: write address switched (RW), tAS before the strobe",
         strobe - (rw + mux["S->Y"] + sram["tAS"])),
        ("register file: write pulse width (tWP)", TICK - sram["tWP"]),
        ("memory: write pulse width at the shortest write (K_WRITE)",
         (timing.K_WRITE - 5) * TICK - _delays("sram512", "AS7C4096A-12")["tWP"]),
    ]


# ---- running it ------------------------------------------------------------------------

_N = None


def _init():
    global _N
    import sys
    sys.setrecursionlimit(20000)
    _N = hsta.Netlist(build(), parts.VARIANT, CORNER)


def _one(item):
    import sys
    (w, extra), labels = item
    _c, chk = hsta.case_checks(sys.modules[__name__], _N, w, extra, 1000.0, WS, WE)
    T = hsta.min_period(chk, WS, WE)
    worst = hsta.worst_check(chk, T if T < math.inf else 1000.0, WS, WE)
    return T, w, [list(e) for e in extra], labels, worst[1], worst[2]


def analyse(force=False, jobs=4):
    """[(period, control word, extra constants, labels, critical check,
    endpoint)], slowest first, cached in build/v2_hw by the sources."""
    path = os.path.join(hw.OUT, "sta.json")
    if not force and os.path.exists(path) and \
            os.path.getmtime(path) >= runner.newest(hw.sources()):
        with open(path) as f:
            return [tuple(r) for r in json.load(f)]
    items = list(sta_words().items())
    with ProcessPoolExecutor(jobs, initializer=_init) as ex:
        res = list(ex.map(_one, items, chunksize=16))
    res.sort(key=lambda r: -r[0])
    os.makedirs(hw.OUT, exist_ok=True)
    with open(path, "w") as f:
        json.dump(res, f)
    return res


def ticks_of(T, f):
    """Ticks for a period of T ns (inf if no length class is that long)."""
    return math.inf if T > timing.K_MAX * TICK else timing.ticks_of(T, f)


def node_ticks(res):
    """{control store address: (STA ns, STA ticks)}, the worst queue state."""
    mc = uc.built()
    by_word = defaultdict(float)
    for r in res:
        by_word[r[1]] = max(by_word[r[1]], r[0])
    mask = _mask()
    out = {}
    for n in mc.nodes:
        f = mc.word(n)
        T = by_word[uc.pack(f) & mask]
        out[n.addr] = (T, ticks_of(T, f))
    return out


# ---- the report --------------------------------------------------------------------------


def _fmt_T(T):
    return "never" if T == math.inf else f"{T:.1f}"


def report(res, rows=None, paths=4):
    """The analysis as text: rows are perf.profile()'s, for how often each
    microinstruction runs."""
    from . import perf
    mc = uc.built()
    nt = node_ticks(res)
    N = hsta.Netlist(build(), parts.VARIANT, CORNER)
    me = __import__(__name__, fromlist=["x"])
    out = [f"static timing analysis of the draft 2 CPU: {parts.VARIANT}, {CORNER} delays, "
           f"{len({r[1] for r in res})} distinct microinstructions in {len(res)} states (the queue, "
           "FOK, the forced entries)",
           ""]
    out.append("fixed requirements (slack):")
    for desc, sl in fixed_checks(N):
        out.append(f"  {sl:6.1f} ns  {desc}")
    out.append("")
    # against timing.py's estimate, and the classes the microcode has
    # (from ticks.json: if it is current, every microinstruction fits)
    count = Counter()
    if rows:
        for r in rows:
            if r["name"] in perf.SKIP:
                continue
            for a, n in r["ucount"].items():
                count[a] += n
    pairs, dyn = Counter(), Counter()
    late = []
    est_ticks = {}
    for n in mc.nodes:
        est = est_ticks[n.addr] = timing.estimate(mc.word(n))[1]
        T, t = nt[n.addr]
        pairs[(est, t)] += 1
        dyn[(est, t)] += count[n.addr]
        cls = mc.lengths[n.f["LCL"]]
        if t > cls:
            late.append((count[n.addr], n, T, t, cls))
    out.append("ticks: timing.py's estimate against the netlist's (microinstructions, and "
               "how often they run in the suite)")
    for (est, t), k in sorted(pairs.items(), key=lambda x: (x[0][0], str(x[0][1]))):
        out.append(f"  estimate {est:2d}  netlist {t!s:>3}  {k:5d}  {dyn[(est, t)]:>12,}")
    out.append("")
    out.append(f"the microcode's length classes {mc.lengths} ({len(mc.estimated)} microinstructions "
               f"estimated, not in ticks.json): {len(late)} need more than their class gives")
    for cnt, n, T, t, cls in sorted(late, key=lambda x: -x[0])[:15]:
        out.append(f"  {n.name:<28} @{n.addr:04X}  {_fmt_T(T):>6} ns: {t} ticks, class {cls}  "
                   f"({cnt:,} runs)")
    out.append("")
    if rows:
        need = Counter()
        for a, k in count.items():
            need[nt[a][1]] += k
        finite = {t: k for t, k in need.items() if t != math.inf}
        if len(finite) == len(need):
            def suite(ticks):
                lens = timing.best_lengths(ticks)
                return sum(k * min(L for L in lens if L >= t) for t, k in ticks.items()), lens
            ts, lens = suite(finite)
            need_e = Counter()
            for a, k in count.items():
                need_e[est_ticks[a]] += k
            te, elens = suite(need_e)
            hold = sum(r["hold"] for r in rows if r["name"] not in perf.SKIP)
            out.append(f"the suite (without {', '.join(perf.SKIP)}): {(te + hold) * TICK / 1e6:.2f} ms "
                       f"with the estimate's ticks (classes {elens}), "
                       f"{(ts + hold) * TICK / 1e6:.2f} ms with the netlist's (classes {lens})")
            out.append("")
    seen = set()
    shown = 0
    for T, w, extra, labels, what, net in res[:len(res) if paths else 0]:
        key = (what, net)
        if key in seen:
            continue
        seen.add(key)
        extra = tuple(tuple(e) for e in extra)
        c, chk = hsta.case_checks(me, N, w, extra, T if T < math.inf else 1000.0, WS, WE)
        e = dict(extra)
        q = ("queue empty" if e.get("V0") == 0 else "queue not empty") + \
            (", FOK" if e.get("FOK") else ", no FOK")
        out.append(f"{_fmt_T(T)} ns: {labels[0]} ({len(labels)} addresses, {q}): {what}")
        for net_, t, ref, dn in c.path(net):
            out.append(f"    {t:7.1f} ns  {net_:<14} {ref:<10} {dn}")
        out.append("")
        shown += 1
        if shown >= paths:
            break
    return "\n".join(out)


def write_table(res):
    """ticks.json: every distinct microinstruction's period, the worst over
    the states it may meet, for timing.assign_classes()."""
    ns = defaultdict(float)
    for T, w, *_rest in res:
        if T == math.inf:
            raise ValueError("a microinstruction that never meets its timing")
        ns[f"{w:x}"] = max(ns[f"{w:x}"], round(T, 1))
    with open(timing.TICKS_PATH, "w") as f:
        json.dump({"generated by": "heron v2_hw hw sta --write", "variant": parts.VARIANT,
                   "corner": CORNER, "ns": dict(sorted(ns.items()))}, f, indent=0)
        f.write("\n")


def main(args):
    res = analyse(force=args.force)
    if args.write:
        write_table(res)
    rows = None
    if not args.no_profile:
        from . import perf
        rows = perf.profile()
    print(report(res, rows, paths=args.paths))
    return 0
