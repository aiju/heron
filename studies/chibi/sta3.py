"""Static timing analysis of the two-halves machine on the static timing
engine (infra/sta, RFC 0048): board2.build(sim=True)'s netlist, the clock
generator's 22V10s running their own equations, every check the chips'
descriptions give (infra/hw/chips.py, cells.py).

A case is one distinct microinstruction (sta2.sta_words: an access at MAR
twice, for the RAM and the I/O space) with LEN and HLEN at a trial length:
a cycle from phase F's first edge (time 0) to the edge at which CLK0 next
rises. The control store's outputs read the word once they settle; the
fields that don't time it (JT) are unknown, not 0. Phase F starts in
START's state; the case splits where HWQ (the cycle before's HW) or VEXTQ
(the video's second read) would load X.

Assumed, and so reported: no task starts or ends (TASK and TASKP 0, so
TCHG 0); an access to the I/O space is a fast one (SLOWCS 0: the slow
devices' HOLD isn't timed); RESET_n is high. The video's chips run on
their own phase, which a CPU case doesn't know: netlist() leaves their checks
out (a case of their own is open), and the suite's console (X_IO) isn't on
the board.

A word's ticks are the shortest lengths at which none of its branches
fails a check a length can fix (setup, strobe, width, period) worse than
at the longest lengths: what fails there too, a length doesn't fix (a
path inside phase F, which no length changes), and is reported with the
holds, glitches and loops, which don't depend on the lengths.

  heron chibi hw sta [--paths N] [--write]     (--old: sta2.py's analysis)
"""

import json
import os
import time
from collections import Counter, defaultdict

from heron.infra.hw import waves

from . import board2, parts, routines2, sta2, ucode2 as uc

X = waves.X
TICKS_PATH = sta2.TICKS_PATH
FIXTURES = {"X_IO"}
# the clock generator at phase F's start: U_CGA's state, U_CGB's clocks
# and strobes as the edge that ends a cycle sets them; U_MEMC's strobes and
# U_SLOW idle; no task (TASK and TASKP as they were)
START = {
    **{n: (X, 0) for n in ("PH0", "PH1", "TC0", "TC1", "TC2")},
    "VEXTQ": (X, X),
    "CLK0": (0, 1), "PHW": (0, 1), "HALF": (X, 0), "HCK": (0, 1), "HCKA": (0, X), "HCKB": (0, X),
    "RFWL_n": (1, 1), "RFWH_n": (1, 1), "YAOE": (0, 0), "YBOE": (0, 0),
    **{n: (X, 1) for n in ("WEH_n", "WEL_n", "IORD_n", "IOWR_n")},
    **{n: (X, 0) for n in ("W0", "W1", "W2", "W3", "W4")},
    **{n: (X, 1) for n in ("SWR_n", "SRD_n", "CFOE_n")},
    "SDONE": (X, X),
    "TASK": (0, 0), "TASKP": (0, 0),
}
BRANCH = ["HWQ", "VEXTQ"]
# the video's clocks: chips on them run on the video's own phase
VIDEO_CLOCKS = {"VCK", "WCLK", "PIX", "HS_n"}
# what a length can fix
LENGTH = {"setup", "strobe", "width", "period"}
MAX_LO, MAX_HI = 4, 3


def netlist():
    """The engine's netlist, and the chips the cases leave out."""
    nl = board2.build(sim=True)
    skip = {"U_VQ"}
    for inst in nl.instances:
        if inst.gal is not None and any(r for _, r, _, _ in inst.gal):
            if inst.conn.get("CLK") in VIDEO_CLOCKS:
                skip.add(inst.ref)
        elif inst.type.regs:
            clocks = {inst.conn.get(r.clock) for r in inst.type.regs.values()}
            if clocks & VIDEO_CLOCKS:
                skip.add(inst.ref)
    return waves.export(nl, parts.VARIANT, drop=FIXTURES), sorted(skip)


def case(word, extra, lo, hi, skip):
    """The case for a word (its untimed fields cleared) at lo and hi ticks."""
    f = uc.unpack(word)
    f.update(LEN=lo - 1, HLEN=hi)
    w = uc.pack(f)
    untimed = {n for name in ("JT",) for n in board2.field(name)}
    pins = {n: (w >> bit) & 1 for bit, n in board2.control_nets().items() if n not in untimed}
    for n, v in extra:
        pins[n] = v
        if n == "AIO" and v:
            pins["SLOWCS"] = 0
    return {"label": f"{word:018X} {lo}/{hi}" + "".join(f" {n}={v}" for n, v in extra),
            "clock": "MCLK", "pins": pins, "constant": {"RESET_n": 1}, "start": START,
            "branch": BRANCH, "skip": skip, "end": {"net": "CLK0", "events": 80}}


def key(c):
    return (c["chip"], c["check"], c["what"])


def slacks(branches):
    """{check: its worst slack over the branches} of the failing checks."""
    out = {}
    for b in branches:
        for c in b["worst"]:
            if c["slack"] < 0:
                out[key(c)] = min(out.get(key(c), 0), c["slack"])
    return out


def fixable(branches, base=None):
    """The failing checks a length can fix, worst first: those worse than
    in `base` (slacks() at the longest lengths)."""
    base = base or {}
    out = [c for b in branches for c in b["worst"]
           if c["slack"] < min(0, base.get(key(c), 0)) and c["check"] in LENGTH]
    return sorted(out, key=lambda c: c["slack"])


def run(ex, skip, items, paths, jobs):
    """{(word, two, extra, lo, hi): branches} for the items."""
    cases = [case(w, extra, lo, hi, skip) for (w, two, extra, lo, hi) in items]
    out = waves.analyse(ex, cases, paths=paths, jobs=jobs)
    res = {}
    for item, r in zip(items, out):
        if isinstance(r, dict):
            raise RuntimeError(f"{item}: {r['error']}")
        res[item] = r
    return res


def analyse(paths=1, jobs=None, log=print):
    """Every word's ticks: {(word, two): (lo, hi)}, the results at them,
    and the I/O variants' at the same lengths."""
    t0 = time.time()
    ex, skip = netlist()
    words = sta2.sta_words()
    guess = routines2.load_ticks()
    floor = {}
    for (w, two, extra) in words:
        f = uc.unpack(w)
        floor[(w, two)] = (sta2.floors(f, 0), sta2.floors(f, 1) if two else 0)
    ram = sorted({(w, two, extra) for (w, two, extra) in words if dict(extra).get("AIO") != 1})
    io = sorted({(w, two, extra) for (w, two, extra) in words if dict(extra).get("AIO") == 1})
    cur = {}
    for (w, two, extra) in ram:
        g = guess.get((w, two), (MAX_LO, MAX_HI if two else 0))
        cur[(w, two, extra)] = (max(g[0], floor[(w, two)][0]), max(g[1], floor[(w, two)][1]))
    seen, calls = {}, 0
    # what fails at the longest lengths, which no length fixes (an access
    # to the I/O space has its 6 ticks whatever)
    longest = {k: (MAX_LO, MAX_HI if k[1] else 0) for k in [*cur, *io]}
    seen.update(run(ex, skip, [(*k, lo, hi) for k, (lo, hi) in longest.items()], paths, jobs))
    calls += 1
    base = {k: slacks(seen[(*k, *longest[k])]) for k in longest}
    # the low half first, with the high half at its longest; then the high
    pending = {k: (lo, MAX_HI if k[1] else 0) for k, (lo, hi) in cur.items()}
    for stage in ("lo", "hi"):
        state = {k: None for k in pending}         # the shortest passing length so far
        while pending:
            todo = [(*k, lo, hi) for k, (lo, hi) in pending.items() if (*k, lo, hi) not in seen]
            if todo:
                seen.update(run(ex, skip, todo, paths, jobs))
                calls += 1
            nxt = {}
            for k, (lo, hi) in pending.items():
                ok = not fixable(seen[(*k, lo, hi)], base[k])
                fl_lo, fl_hi = floor[k[:2]]
                if stage == "lo":
                    if ok:
                        state[k] = lo
                        if lo > fl_lo and (*k, lo - 1, hi) not in seen:
                            nxt[k] = (lo - 1, hi)
                    elif state[k] is None and lo < MAX_LO:
                        nxt[k] = (lo + 1, hi)
                else:
                    if ok:
                        state[k] = hi
                        if hi > fl_hi and (*k, lo, hi - 1) not in seen:
                            nxt[k] = (lo, hi - 1)
                    elif state[k] is None and hi < MAX_HI:
                        nxt[k] = (lo, hi + 1)
            pending = nxt
        if stage == "lo":
            for k in cur:
                lo = state.get(k) or MAX_LO
                cur[k] = (lo, cur[k][1])
            pending = {k: (lo, max(hi, floor[k[:2]][1])) for k, (lo, hi) in cur.items() if k[1]}
        else:
            for k, hi in state.items():
                cur[k] = (cur[k][0], hi or MAX_HI)
    for k in cur:
        if not k[1]:
            cur[k] = (cur[k][0], 0)
    # every word's final results (and its I/O variant's) at its lengths
    final = [(*k, lo, hi) for k, (lo, hi) in cur.items()]
    tab = {}
    for (w, two, extra), (lo, hi) in cur.items():
        prev = tab.get((w, two), (0, 0))
        tab[(w, two)] = (max(prev[0], lo), max(prev[1], hi))
    final += [(w, two, extra, *tab[(w, two)]) for (w, two, extra) in io if (w, two) in tab]
    # every failing check with its paths, for the report
    res = run(ex, skip, final, 200, jobs)
    calls += 1
    log(f"{len(seen) + len(final)} cases in {calls} calls, {time.time() - t0:.1f} s")
    return tab, res, base, skip


def write_ticks(tab):
    rows = [[f"{w:018X}", int(two), lo, hi] for (w, two), (lo, hi) in sorted(tab.items())]
    with open(TICKS_PATH, "w") as f:
        f.write("[\n" + ",\n".join(json.dumps(r) for r in rows) + "\n]\n")


def _path(c):
    return [f"      {s['t'] / 1000:7.1f} ns  {s['at']:<16} {s['arc']}" for s in c["path"]]


def report(tab, res, base, skip, paths=2):
    old = routines2.load_ticks()
    lines = []
    lo = Counter(v[0] for v in tab.values())
    hi = Counter(v[1] for v in tab.values() if v[1])
    lines.append(f"low halves' ticks over {len(tab)} words:  "
                 + ", ".join(f"{k}: {v}" for k, v in sorted(lo.items())))
    lines.append(f"high halves' ticks over {sum(hi.values())} words: "
                 + ", ".join(f"{k}: {v}" for k, v in sorted(hi.items())))
    diff = Counter()
    for k, v in tab.items():
        o = old.get(k)
        if o is None:
            diff["new"] += 1
        else:
            for h, (a, b) in (("low", (v[0], o[0])), ("high", (v[1], o[1]))):
                if a > b:
                    diff[f"{h} longer"] += 1
                elif a < b:
                    diff[f"{h} shorter"] += 1
    lines.append("against sta2.py's ticks.json: " + (", ".join(f"{k}: {v}" for k, v in
                                                       sorted(diff.items())) or "the same"))
    lines.append(f"skipped (the video's own phase): {', '.join(skip)}")
    lines.append("")
    # words whose checks fail at the lengths chosen worse than at the
    # longest (an access to the I/O space is checked at its word's lengths,
    # not searched: its 6 ticks are fixed)
    io = {k for k in res if dict(k[2]).get("AIO") == 1}
    stuck = [(k, fixable(b, base.get(k[:3]))) for k, b in res.items() if k not in io]
    stuck = [x for x in stuck if x[1]]
    lines.append(f"cases failing a check a length can fix, even at the lengths chosen: {len(stuck)}")
    for k, fails in sorted(stuck, key=lambda x: x[1][0]["slack"])[:paths]:
        c = fails[0]
        lines.append(f"  {sta2.sta_describe(k[0])} {dict(k[2])} {k[3]}/{k[4]}: {c['chip']} "
                     f"{c['what']} {c['check']} {c['slack'] / 1000:.1f} ns")
        lines += _path(c)
    lines.append("")
    # the checks lengths don't fix, over every case
    other = defaultdict(lambda: [0, None])
    for k, branches in res.items():
        fix = {key(c) for c in fixable(branches, base.get(k[:3]))} if k not in io else set()
        for c in {key(c): c for b in branches for c in b["worst"]
                  if c["slack"] < 0 and key(c) not in fix}.values():
            e = other[(c["chip"], c["check"], c["what"])]
            e[0] += 1
            if e[1] is None or c["slack"] < e[1]["slack"]:
                e[1] = c
    lines.append(f"what no length fixes (holds, glitches, loops, phase F): {len(other)} checks")
    for (chip, check, what), (n, c) in sorted(other.items(), key=lambda kv: kv[1][1]["slack"])[:12]:
        lines.append(f"  {c['slack'] / 1000:7.1f} ns  {check:6} {chip:8} {what} ({n} cases)")
    for (chip, check, what), (n, c) in sorted(other.items(), key=lambda kv: kv[1][1]["slack"])[:paths]:
        lines.append(f"  path of {chip} {what}:")
        lines += _path(c)
    notes = Counter(n for branches in res.values() for b in branches for n in b["notes"])
    if notes:
        lines.append("")
        lines.append("notes: " + "; ".join(f"{n} ({k})" for n, k in notes.most_common(5)))
    return "\n".join(lines)


def cmd_sta(args):
    tab, res, base, skip = analyse(paths=max(2, args.paths))
    print(f"static timing analysis (the two-halves machine, infra/sta): {parts.VARIANT}, "
          f"min and max delays")
    print(report(tab, res, base, skip, args.paths))
    if args.write:
        write_ticks(tab)
        print(f"wrote {os.path.relpath(TICKS_PATH)} ({len(tab)} words)")
    return 0
