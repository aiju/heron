"""Static timing analysis of Heron Mini's netlist: infra/hw/sta.py's case
analysis, once per distinct microinstruction, on board.build()'s netlist
with the clock generator as a fixture (`tickclk`): CLK's edge at 0, the
phases the tick counter makes at fixed times after it, and the register
file in its read phase.

  MWIN   the memory write window, from tick 2 to the tail
  LATE   from tick 2: the store data's drivers, T's latches
  PHASE  H1, falling as tick 2 starts (H0 is over by then): the register
         file's A latches and its address

The tail, which the case analysis doesn't see, is checked here
(extra_checks), at the corner's delays:

  - the read latches, T's and the queue's slots close as the tail starts
    (RW rises, two ticks before the edge): what they hold must be there
    their setup before;
  - the register file's write strobe is the last tick, T2: the result must
    reach the SRAM through the write buffers tDW before it ends, and the
    write address tAS before it starts.

A microinstruction's ticks are its period in ticks, rounded up, and at
least what the clock generator and the memory rules (timing.py's K_MIN,
K_DATA, K_WRITE) make it.

`heron mini hw sta` writes the analysis (cached in build/mini): the
slowest microinstructions with their critical paths, the ticks against
timing.py's estimate, and the program suite's time with each.
"""

import json
import sys
import math
import os
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

from heron.infra.hw import chips, runner, sta as hsta

from . import board, hw, parts, timing, ucode as uc

NAME = "mini"
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
    their ticks: each is a 22V10's register on the master clock, as CLK
    is, the combinatorial ones (MWIN, LATE, RW) a 22V10 later."""
    gal = _delays("22v10")["tPD"]
    return {"MWIN": gal, "LATE": gal, "RW": gal, "QLE": 0.0, "T2": 0.0}


OFFSETS = _clock_offsets()
WINDOWS = {
    "MWIN": (0.0, 2 * TICK + OFFSETS["MWIN"], 1.0, -2 * TICK + OFFSETS["MWIN"]),
    "LATE": (0.0, 2 * TICK + OFFSETS["LATE"], 0.0, 0.0),
    "PHASE": (0.0, 2 * TICK, 0.0, 0.0),
}
# the A operand latches close as the late phase starts (PHASE) in a cycle
# that reads B from the register file too: the B read after it doesn't
# reach the A bus
CLOSING = ("RLEA",)


# the boards' delays (boards.py): [(ref, pin, ps)] on this netlist's
# outputs that drive another board, or None (`heron mini hw sta --boards`)
BOARD_DELAYS = None


def build():
    nl = board.build(sim=False)
    if BOARD_DELAYS:
        from . import boards
        boards.apply_board_delays(nl, BOARD_DELAYS)
    return nl


def cache_path():
    """The analysis's cache, named by what it depends on: the netlist (with
    any board delays), the microinstructions, the tick and the analysis's
    code, so that edits elsewhere in the study (boards.py) don't redo it."""
    import hashlib
    import inspect
    h = hashlib.sha1()
    h.update(json.dumps(build().export(variant=parts.VARIANT, corner=CORNER),
                        sort_keys=True).encode())
    h.update(repr(sorted(sta_words().items())).encode())
    h.update(repr((TICK, parts.VARIANT, CORNER)).encode())
    for m in (sys.modules[__name__], timing, hsta):
        h.update(inspect.getsource(m).encode())
    return os.path.join(hw.OUT, f"sta-{h.hexdigest()[:12]}.json")


def control_nets():
    """uIR bit -> net, for the fields the case analysis holds constant (not
    the next address or the length class: timing.NOT_TIMED)."""
    mask = timing.word_mask()
    return {b: n for b, n in board.control_nets().items() if mask >> b & 1}


def _mask():
    return timing.word_mask()


# The queue's state: with Q0 empty, slot 0 (taken as the head: the slots
# are alike) is transparent and the head parcel comes from the word this
# cycle fetches; otherwise from the slot's latch
QUEUE = ((("V0", 0), ("V0_n", 1), ("V1", 0), ("V1_n", 1), ("QLE0", 1), ("HS", 0), ("HS_n", 1)),
         (("V0", 1), ("V0_n", 0), ("QLE0", 0), ("HS", 0), ("HS_n", 1)))
# a decode goes ahead, or the interrupt entry takes the address
DECODE = ((("PEND", 0), ("PEND_n", 1)), (("PEND", 1), ("PEND_n", 0)))


def consumes(f):
    """Whether a microinstruction reads the queue's head as an operand: if
    the queue is empty then, the hold gives its cycle two ticks more
    (rtl.DEMAND_HOLD)."""
    return bool(f.get("CONSUME"))


def period(T, f, extra):
    """The period a microinstruction's class must have, from its analysis
    in one state: less the hold's ticks where the hold gives them."""
    if consumes(f) and dict(extra).get("V0") == 0:
        from .rtl import DEMAND_HOLD
        return T - DEMAND_HOLD * TICK
    return T


def states(f):
    """The extra constants a microinstruction is analysed with."""
    if f.get("SEQ") in (uc.SEQ_DECODE, uc.SEQ_HALT):
        return [q + d for q in QUEUE for d in DECODE]
    return list(QUEUE)


def sta_words():
    """{(control word, extra constants): [labels]} for every distinct
    microinstruction (the next address and the length class left out), in
    each state it may meet."""
    words = defaultdict(list)
    mc = uc.built()
    mask = _mask()
    for n in mc.nodes:
        f = mc.word(n, 0 if n.addr is None else n.addr)
        label = f"{n.name} @{n.addr:04X}" if n.addr is not None else f"{n.name} (entry)"
        for q in states(f):
            words[(uc.pack(f) & mask, q)].append(label)
    return words


# ---- the tail: the latches close, the register file is written ---------------------------


def extra_checks(case, N):
    out = []
    u = {v[1:]: v for v in board.control_nets().values()}
    d = {ref: N.delay[ref] for ref in ("U_RWA0", "U_RFG0", "U_RFA0", "U_RLA0")}
    gtpd = d["U_RFG0"]["tPD"]
    nand2 = N.delay[N.drivers["RFWE_n"][0][0].ref]["A->Y"]
    tle = N.delay[N.drivers["TLE"][0][0].ref]
    and3 = tle.get("A->Y", tle.get("tPD"))           # T's latch enable: a 22V10 (U_BTL)
    sram = d["U_RFA0"]
    rw = -2 * TICK + OFFSETS["RW"]                   # RW rises and RW_n falls, after T
    strobe = -TICK + OFFSETS["T2"] + nand2          # the write strobe falls, after T
    # the latches close as LE falls: they hold what's there their setup before
    for inst in N.insts:
        if inst.type.model != "latch573":
            continue
        le = inst.conn["LE"]
        if case.net(le)[0] == 0:
            continue
        if le == "RW_n" and case.pin(inst, "OE")[0] == 1:
            continue                    # the register file's latch, not on its bus
        if le == "RLEA" and case.net(u["BRF_n"])[0] == 0:
            # an A operand latch in a cycle that reads B too: it closes as
            # the late phase starts, whatever the period, holding the A
            # address's read
            opened = case.open("RLEA")
            ta = max(opened.pin(inst, f"D{i}")[1] for i in range(1, 9))
            late = case.net("RLEA")[1]
            su = N.delay[inst.ref]["setup D"]
            if ta + su > late:
                out.append(("setup", 1000.0, f"{inst.ref}: the A operand late for the late phase by "
                            f"{ta + su - late:.1f} ns", inst.conn["D1"]))
            continue
        if le in ("RW_n", "RLEA"):
            close = rw + (0.0 if le == "RW_n" else gtpd)
        elif le == "TLE":
            close = rw + and3
        else:                           # a queue slot: its J-K flip-flop, entering T1
            close = -2 * TICK + OFFSETS["QLE"]
        su = N.delay[inst.ref]["setup D"]
        worst = max(range(1, 9), key=lambda i: case.pin(inst, f"D{i}")[1])
        t = case.pin(inst, f"D{worst}")[1]
        if t != hsta.NEG:
            out.append(("setup", t + su - close, f"{inst.ref} latch setup (closes at RW)",
                        inst.conn[f"D{worst}"]))
    # the queue slots' enables, a 22V10 on the master clock: at the edge
    # that ends T2, a 22V10's clock-to-output before CLK's, it takes whether
    # the slots are empty after it, from the queue's next state
    gd = _delays("22v10")
    for net in ("V0_D", "V1_D", "HS_D"):
        t = case.net(net)[1]
        if t != hsta.NEG:
            out.append(("setup", t + gd["setup"] + gd["CLK->Q"],
                        "U_QGB setup (the master clock's edge ending T2)", net))
    # an access to the I/O space starts the hold as tick 3 ends: IOACC to
    # HOLD's register, the region to the hold counter's preload. Not a
    # matter of the period: a microinstruction that misses it can't hold
    if case.net("IOACC")[0] != 0:
        e3 = 4 * TICK - gd["CLK->Q"]
        need = [("IOACC", gd["setup"], "the hold's start")]
        need += [(f"VA{i}", gd["setup"], "the hold counter's preload")
                 for i in (28, 29, 30)]
        for net, after, what in need:
            t = case.net(net)[1]
            if t != hsta.NEG and t + after > e3:
                out.append(("setup", 1000.0, f"I/O: {what} late by {t + after - e3:.1f} ns", net))
    if case.net(u["RFWE"])[0] != 0:
        res = [f"RES{i}" for i in range(32)]
        worst = max(res, key=lambda n: case.net(n)[1])
        t = case.net(worst)[1]
        buf = d["U_RWA0"]["A->Y"]
        out.append(("setup", t + buf + sram["tDW"] - nand2,
                    "register file write: data setup to end of write (tDW)", worst))
        rwa = [u["RFW0"], u["RFW1"]] + [f"IR{i}" for i in range(8, 16)] + \
            [f"SX{i}" for i in range(4)] + [u[f"RFKW{i}"] for i in range(5)]
        worst = max(rwa, key=lambda n: case.net(n)[1])
        # the address moves on once RW_n and RLEA have closed the latches
        t = max(case.net(worst)[1], rw + gtpd)
        out.append(("setup", t + gtpd + sram["tAS"] - strobe,
                    "register file write: address setup to write (tAS)", worst))
    return out


def fixed_checks(N):
    """Requirements that don't depend on the microinstruction or the period:
    (description, slack in ns)."""
    sram = N.delay["U_RFA0"]
    nand2 = N.delay[N.drivers["RFWE_n"][0][0].ref]["A->Y"]
    buf = N.delay["U_RWA0"]
    mux = N.delay["U_RFG0"]
    rw = -2 * TICK + OFFSETS["RW"]
    strobe = -TICK + nand2
    return [
        ("register file: write buffers on, tDW before the strobe ends",
         nand2 - (-TICK + nand2 + buf["OE->Y en"] + sram["tDW"])),
        ("register file: write address switched (RW), tAS before the strobe",
         strobe - (rw + mux["tPD"] + mux["tPD"] + sram["tAS"])),
        ("register file: write pulse width (tWP)", TICK - sram["tWP"]),
        ("memory: write pulse width at the shortest write (K_WRITE)",
         (timing.K_WRITE - 4) * TICK - _delays("sram512", "AS7C4096A-12")["tWP"]),
    ]


# ---- running it ------------------------------------------------------------------------

_N = None


def _init(delays=None):
    global _N, BOARD_DELAYS
    import sys
    sys.setrecursionlimit(20000)
    BOARD_DELAYS = delays
    _N = hsta.Netlist(build(), parts.VARIANT, CORNER)


def _one(item):
    import sys
    (w, extra), labels = item
    _c, chk = hsta.case_checks(sys.modules[__name__], _N, w, extra, 1000.0, WS, WE)
    T = hsta.min_period(chk, WS, WE)
    worst = hsta.worst_check(chk, T if T < math.inf else 1000.0, WS, WE)
    f = uc.unpack(w)
    return period(T, f, extra), w, [list(e) for e in extra], labels[:3], len(labels), worst[1], \
        worst[2]


def analyse(force=False, jobs=4):
    """[(period, control word, extra constants, labels, count, critical
    check, endpoint)], slowest first, cached in build/mini by the sources."""
    path = cache_path()
    if not force and os.path.exists(path):
        with open(path) as f:
            return [tuple(r) for r in json.load(f)]
    items = list(sta_words().items())
    with ProcessPoolExecutor(jobs, initializer=_init, initargs=(BOARD_DELAYS,)) as ex:
        res = list(ex.map(_one, items, chunksize=16))
    res.sort(key=lambda r: -r[0])
    os.makedirs(hw.OUT, exist_ok=True)
    with open(path, "w") as f:
        json.dump(res, f)
    return res


def _trace(item):
    import sys
    T, w, extra, net = item
    extra = tuple(tuple(e) for e in extra)
    c, _chk = hsta.case_checks(sys.modules[__name__], _N, w, extra,
                               T if T < math.inf else 1000.0, WS, WE)
    return [(n, t, ref, dn) for n, t, ref, dn in c.path(net)]


def traces(rows, jobs=4):
    """The critical paths of some of analyse()'s rows (with the current
    BOARD_DELAYS): [[(net, arrival, ref, delay name)]], in a pool."""
    items = [(r[0], r[1], r[2], r[6]) for r in rows]
    with ProcessPoolExecutor(jobs, initializer=_init, initargs=(BOARD_DELAYS,)) as ex:
        return list(ex.map(_trace, items, chunksize=4))


def ticks_of(T, f):
    """Ticks for a period of T ns (inf if no length class is that long)."""
    return math.inf if T > timing.K_MAX * TICK else timing.ticks_of(T, f)


def node_ticks(res):
    """{node id: (STA ns, STA ticks)}, the worst queue state."""
    mc = uc.built()
    by_word = defaultdict(float)
    for r in res:
        by_word[r[1]] = max(by_word[r[1]], r[0])
    mask = _mask()
    out = {}
    for n in mc.nodes:
        f = mc.word(n, 0 if n.addr is None else n.addr)
        T = by_word[uc.pack(f) & mask]
        out[id(n)] = (T, ticks_of(T, f))
    return out


def _suite(ticks):
    """(ticks, the length classes) for {ticks needed: cycles}, with the
    best classes for them."""
    lens = timing.best_lengths(ticks)
    return sum(k * min(L for L in lens if L >= t) for t, k in ticks.items()), lens


def suite_ticks(res, rows):
    """(ticks, length classes, {ticks needed: cycles}) the suite and the C
    programs take with analyse()'s periods (rows: perf.profile()'s), not
    counting the I/O holds; ticks None if a microinstruction never meets
    its timing."""
    from . import perf
    nt = node_ticks(res)
    need = Counter()
    for i, k in perf.node_profile(rows).items():
        need[nt[i][1]] += k
    finite = {t: k for t, k in need.items() if t != math.inf}
    if len(finite) != len(need):
        return None, None, finite
    ts, lens = _suite(finite)
    return ts, lens, finite


def suite_ms(res, rows):
    """The suite and the C programs in ms with analyse()'s periods, the
    I/O holds included."""
    from . import perf
    ts, _lens, _ = suite_ticks(res, rows)
    hold = sum(r["hold"] for r in rows if r["name"] not in perf.SKIP)
    return None if ts is None else (ts + hold) * TICK / 1e6


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
    out = [f"static timing analysis of Heron Mini: {parts.VARIANT}, {CORNER} delays, "
           f"{len({r[1] for r in res})} distinct microinstructions in {len(res)} states (the queue, "
           "the interrupt)", ""]
    out.append("fixed requirements (slack):")
    for desc, sl in fixed_checks(N):
        out.append(f"  {sl:6.1f} ns  {desc}")
    out.append("")
    count = Counter(perf.node_profile(rows)) if rows else Counter()
    pairs, dyn = Counter(), Counter()
    est_ticks = {}
    for n in mc.nodes:
        f = mc.word(n, 0 if n.addr is None else n.addr)
        est = est_ticks[id(n)] = timing.estimate(f)[1]
        T, t = nt[id(n)]
        pairs[(est, t)] += 1
        dyn[(est, t)] += count[id(n)]
    out.append("ticks: timing.py's estimate against the netlist's (microinstructions, and "
               "how often they run in the suite)")
    for (est, t), k in sorted(pairs.items(), key=lambda x: (x[0][0], str(x[0][1]))):
        out.append(f"  estimate {est:2d}  netlist {t!s:>3}  {k:5d}  {dyn[(est, t)]:>12,}")
    out.append("")
    if rows:
        need_e = Counter()
        for i, k in count.items():
            need_e[est_ticks[i]] += k
        ts, lens, finite = suite_ticks(res, rows)
        if ts is not None:
            te, elens = _suite(need_e)
            hold = sum(r["hold"] for r in rows if r["name"] not in perf.SKIP)
            out.append(f"the suite and the C programs: {(te + hold) * TICK / 1e6:.1f} ms "
                       f"with the estimate's ticks (classes {elens}), "
                       f"{(ts + hold) * TICK / 1e6:.1f} ms with the netlist's (classes {lens})")
            dist = ", ".join(f"{t}: {100 * k / sum(finite.values()):.0f}%"
                             for t, k in sorted(finite.items()))
            out.append(f"  cycles by ticks needed: {dist}")
            out.append("")
    # with the boards' delays, each step's board, and * where it crosses
    where, crossing = {}, set()
    if BOARD_DELAYS:
        from . import boards
        where = boards.match(board.build(sim=False))
        crossing = {(ref, pin) for ref, pin, _ in BOARD_DELAYS}
    seen = set()
    shown = 0
    for T, w, extra, labels, nlab, what, net in res[:len(res) if paths else 0]:
        key = (what, net)
        if key in seen:
            continue
        seen.add(key)
        extra = tuple(tuple(e) for e in extra)
        c, chk = hsta.case_checks(me, N, w, extra, T if T < math.inf else 1000.0, WS, WE)
        e = dict(extra)
        q = "queue empty" if e.get("V0") == 0 else "queue not empty"
        out.append(f"{_fmt_T(T)} ns: {labels[0]} ({nlab} cases, {q}): {what}")
        for net_, t, ref, dn in c.path(net):
            b = ""
            if where:
                inst = N.by_ref.get(ref)
                x = any((ref, pin) in crossing for pin, n_ in inst.conn.items() if n_ == net_) \
                    if inst else False
                b = f"  {where.get(ref, '-'):<5}{' *' if x else ''}"
            out.append(f"    {t:7.1f} ns  {net_:<14} {ref:<10} {dn}{b}")
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
        json.dump({"generated by": "heron mini hw sta --write", "variant": parts.VARIANT,
                   "corner": CORNER, "ns": dict(sorted(ns.items()))}, f, indent=0)
        f.write("\n")


def main(args):
    if getattr(args, "xga", False) and abs(TICK - timing.XGA_TICK) > 1e-6:
        # the analysis at XGA's tick, in a process that has it from the start
        import subprocess
        import sys
        argv = [a for a in sys.argv[1:] if a != "--xga"]
        env = dict(os.environ, HERON_MINI_TICK=repr(timing.XGA_TICK))
        return subprocess.run([sys.executable, "-m", "heron"] + argv, env=env).returncode
    global BOARD_DELAYS
    if getattr(args, "boards", False):
        if args.write:
            import sys
            print("--write takes the plain analysis: leave out --boards", file=sys.stderr)
            return 2
        from . import boards
        BOARD_DELAYS = boards.board_delays(build(), ps=round(args.board_delay * 1000),
                                           clocks=args.board_clocks)
        print(f"with the boards' delays (boards.py): {args.board_delay} ns on "
              f"{len(BOARD_DELAYS)} inputs on another board than their net's driver and bus drivers"
              f"{', the clocks too' if args.board_clocks else ''}\n")
    res = analyse(force=args.force)
    if args.write:
        write_table(res)
    rows = None
    if not args.no_profile:
        from . import perf
        rows = perf.profile()
    print(report(res, rows, paths=args.paths))
    return 0
