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

The variants (variants()), at their word's lengths: an access to the I/O
space at each device, its address pinned (DEVICES: the slow ones' HOLD
with them); a task running the words the tasks run, starting at their
entries, and ending (TCHG) before every other word (TASKS). The cycle
before's tails are every case's worst, until they no longer change.

Assumed, and so reported: RESET_n is high. The video's chips run on
their own phase, which a CPU case doesn't know: netlist() leaves their
checks out (a case of their own is open), and the suite's console (X_IO)
isn't on the board.

A word's ticks are the shortest lengths at which none of its branches
fails a check a length can fix (setup, strobe, width, period, float)
worse than at the longest lengths: what fails there too, a length
doesn't fix (a path inside phase F, which no length changes), and is
reported with the holds, handovers, glitches and loops, which don't
depend on the lengths.

  heron chibi hw sta [--paths N] [--write]     (--old: sta2.py's analysis)
"""

import json
import os
import re
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


def _slot(v):
    """The address of a device's 4 KB in the I/O space (board2.io's slot)."""
    return {"MAR20": 1, "A16": 1, "A12": v & 1, "A13": v >> 1 & 1, "A14": v >> 2 & 1}


# an access to the I/O space, at each device (board2.io, slow_devices):
# the address that selects it, pinned; the slow ones by A6-A4. The CF
# card at PIO mode 0 only (CFFAST 0): its data has PIO 0's figures, not
# PIO 4's
DEVICES = {
    "uart0": _slot(6), "irq": _slot(5), "vc": _slot(4), "ps2": _slot(3), "uart1": _slot(1),
    "flash": {"MAR20": 0},
    "timer": {**_slot(2), "A6": 0, "A5": 0, "A4": 0},
    "palette": {**_slot(2), "A6": 0, "A5": 0, "A4": 1},
    "sample": {**_slot(2), "A6": 0, "A5": 1, "A4": 0},
    "cffast": {**_slot(2), "A6": 0, "A5": 1, "A4": 1},
    "cf0cmd": {**_slot(2), "A6": 1, "A5": 0, "CFFAST": 0},
    "cf0ctl": {**_slot(2), "A6": 1, "A5": 1, "CFFAST": 0},
}
# a task (board2.tasks, U_LCK's TCHG): running, starting at the cycle's
# start, ending there (TCHG: phase F a tick longer)
TASKS = {"run": {"TASK": (1, 1), "TASKP": (1, 1)},
         "start": {"TASK": (0, 1), "TASKP": (0, 0)},
         "end": {"TASK": (1, 0), "TASKP": (1, 1)}}
# the video's clocks: chips on them run on the video's own phase
VIDEO_CLOCKS = {"VCK", "WCLK", "PIX", "HS_n"}
# what a length can fix
LENGTH = {"setup", "strobe", "width", "period", "float"}
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
    ex = waves.export(nl, parts.VARIANT, drop=FIXTURES)
    # U_ALUC's nocheck is the chip-level simulator's exception for HC, not
    # a synchroniser: the cases name it (carry_used)
    for c in ex["chips"]:
        if c["ref"] == "U_ALUC":
            c["nocheck"] = False
    return ex, sorted(skip)


def carry_used(f, two):
    """Whether the high half takes the low half's carry (HC): a 32-bit
    arithmetic operation's (sta2.carry_used)."""
    if not two or f["HX"] != uc.HX_NAT or f["AOP"] not in uc.AOP_NAME:
        return False
    return any(uc.aop_resolve(uc.AOP_NAME[f["AOP"]], st)[1] == 0 for st in (0, 1))


def case(word, extra, lo, hi, skip):
    """The case for a word (its untimed fields cleared) at lo and hi ticks."""
    f = uc.unpack(word)
    f.update(LEN=lo - 1, HLEN=hi)
    w = uc.pack(f)
    untimed = {n for name in ("JT",) for n in board2.field(name)}
    pins = {n: (w >> bit) & 1 for bit, n in board2.control_nets().items() if n not in untimed}
    start = dict(START)
    events = 80
    for n, v in extra:
        if n == "DEV":
            pins.update(DEVICES[v])
            if "CFFAST" in DEVICES[v]:
                start["CFFAST"] = (DEVICES[v]["CFFAST"],) * 2
            if "A6" in DEVICES[v]:
                events = 200                # the slow devices' HOLD: up to 32 ticks a half
        elif n == "TASK":
            start.update(TASKS[v])
        else:
            pins[n] = v
    exceptions = []
    if not carry_used(f, hi > 0):
        exceptions.append({"reason": "HC, the low half's carry, matters only to a high half "
                                     "that takes it", "chip": "U_ALUC"})
    return {"label": f"{word:018X} {lo}/{hi}" + "".join(f" {n}={v}" for n, v in extra),
            "clock": "MCLK", "pins": pins, "constant": {"RESET_n": 1}, "start": start,
            "branch": BRANCH, "skip": skip, "exceptions": exceptions,
            "end": {"net": "CLK0", "events": events}}


def task_words():
    """The words the tasks run (from TASK_BASE), and their entries: as
    (word, two halves) like sta2.sta_words's keys."""
    cs = routines2.ControlStore(ticks={})
    mask = uc.untimed_mask()
    key = {a: (w & ~mask, uc.unpack(w)["HLEN"] != 0) for a, w in enumerate(cs.words)}
    return ({key[a] for a in key if a >= uc.TASK_BASE},
            {key[uc.DEVICE_BASE], key[uc.COPPER_BASE]})


def variants(words):
    """The cases beyond the words' own: an access to the I/O space at each
    device, and a task running, starting or ending, as (word, two, extra)."""
    tasks, entries = task_words()
    io, task = [], []
    for (w, two, extra) in words:
        devs = [(("DEV", d),) for d in DEVICES] if dict(extra).get("AIO") == 1 else [()]
        for dev in devs:
            io += [(w, two, extra + dev)] if dev else []
            if (w, two) in tasks:
                task.append((w, two, extra + dev + (("TASK", "run"),)))
            if (w, two) in entries:
                task.append((w, two, extra + dev + (("TASK", "start"),)))
            if (w, two) not in tasks and not dev:
                task.append((w, two, extra + (("TASK", "end"),)))
    return io, task


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


def run(ex, skip, items, paths, jobs, tails=()):
    """{(word, two, extra, lo, hi): branches} for the items."""
    cases = [case(w, extra, lo, hi, skip) for (w, two, extra, lo, hi) in items]
    out = waves.analyse(ex, cases, paths=paths, jobs=jobs, tails=list(tails))
    res = {}
    for item, r in zip(items, out):
        if isinstance(r, dict):
            raise RuntimeError(f"{item}: {r['error']}")
        res[item] = r
    return res


def analyse(jobs=None, log=print):
    """Every word's ticks: {(word, two): (lo, hi)}, the results at them,
    and the variants' (variants()) at the same lengths."""
    t0 = time.time()
    ex, skip = netlist()
    words = sta2.sta_words()
    guess = routines2.load_ticks()
    floor = {}
    for (w, two, extra) in words:
        f = uc.unpack(w)
        floor[(w, two)] = (sta2.floors(f, 0), sta2.floors(f, 1) if two else 0)
    ram = sorted({(w, two, extra) for (w, two, extra) in words if dict(extra).get("AIO") != 1})
    io, task = variants(sorted(words))
    cur = {}
    for (w, two, extra) in ram:
        g = guess.get((w, two), (MAX_LO, MAX_HI if two else 0))
        cur[(w, two, extra)] = (max(g[0], floor[(w, two)][0]), max(g[1], floor[(w, two)][1]))
    seen, calls = {}, 0
    # what fails at the longest lengths, which no length fixes (an access
    # to the I/O space has its 6 ticks whatever, its slow devices' more)
    longest = {k: (MAX_LO, MAX_HI if k[1] else 0) for k in [*cur, *task]}
    seen.update(failing(run(ex, skip, [(*k, lo, hi) for k, (lo, hi) in longest.items()], 0,
                            jobs)))
    calls += 1
    base = {k: slacks(seen[(*k, *longest[k])]) for k in longest}
    # the low half first, with the high half at its longest; then the high
    pending = {k: (lo, MAX_HI if k[1] else 0) for k, (lo, hi) in cur.items()}
    for stage in ("lo", "hi"):
        state = {k: None for k in pending}         # the shortest passing length so far
        while pending:
            todo = [(*k, lo, hi) for k, (lo, hi) in pending.items() if (*k, lo, hi) not in seen]
            if todo:
                seen.update(failing(run(ex, skip, todo, 0, jobs)))
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
    # every word's final results (and its variants') at its lengths
    final = [(*k, lo, hi) for k, (lo, hi) in cur.items()]
    tab = {}
    for (w, two, extra), (lo, hi) in cur.items():
        prev = tab.get((w, two), (0, 0))
        tab[(w, two)] = (max(prev[0], lo), max(prev[1], hi))
    final += [(w, two, extra, *tab[(w, two)]) for (w, two, extra) in io + task if (w, two) in tab]
    # with the cycle before's tails: any word may follow any, so each net's
    # worst over the cases, until they no longer change
    tails, runs, first, res = [], 0, None, None
    while True:
        res = None                  # the last round's goes before the next comes
        res = slim(run(ex, skip, final, 1, jobs, tails))
        calls += 1
        runs += 1
        first = first or failing(res)
        new = worst_tails(res.values())
        if new == tails or runs == 4:
            break
        tails = new
    # the paths of the checks the report shows: each kind's worst, and
    # the worst a length could fix
    shown = {}
    for k, branches in res.items():
        for c in (c for b in branches for c in b["worst"] if c["slack"] < 0):
            stuck = (c["check"] in LENGTH and dict(k[2]).get("AIO") != 1
                     and c["slack"] < min(0, base.get(k[:3], {}).get(key(c), 0)))
            for tag in (c["check"], "stuck") if stuck else (c["check"],):
                if tag not in shown or c["slack"] < shown[tag][1]:
                    shown[tag] = (k, c["slack"])
    again = sorted({k for k, _ in shown.values()})
    res.update(slim(run(ex, skip, again, 200, jobs, tails)))
    calls += 1
    log(f"{len(seen) + len(final) * runs + len(again)} cases in {calls} calls, "
        f"{time.time() - t0:.1f} s")
    return tab, res, base, skip, {"tails": tails, "runs": runs, "stable": new == tails,
                                  "worse": worse(first, res), "coverage": waves.coverage(ex)}


def slim(results):
    """The results with only their failing checks, each cut to what the
    report reads."""
    for branches in results.values():
        for b in branches:
            b["worst"] = [{n: c[n] for n in ("chip", "check", "what", "slack", "path", "against")}
                          for c in b["worst"] if c["slack"] < 0]
    return results


def failing(results):
    """The results with only their failing checks, as slacks() and
    fixable() read them: a branch of their own."""
    return {k: [{"worst": [{n: c[n] for n in ("chip", "check", "what", "slack")}
                           for b in branches for c in b["worst"] if c["slack"] < 0]}]
            for k, branches in results.items()}


def worst_tails(results):
    """Each net's changes in flight past a cycle's end, over every branch:
    (net, earliest, latest), ps from the end."""
    worst = {}
    for branches in results:
        for b in branches:
            for net, e, l in b["tails"]:
                w = worst.get(net)
                worst[net] = (min(w[0], e), max(w[1], l)) if w else (e, l)
    return sorted((n, e, l) for n, (e, l) in worst.items())


def worse(before, after):
    """{check: (slack before, after)}: the checks the tails make worse."""
    out = {}
    for k, branches in after.items():
        a = slacks(before[k])
        for c, v in slacks(branches).items():
            if v < a.get(c, 0) and (c not in out or v < out[c][1]):
                out[c] = (a.get(c, 0), v)
    return out


def write_ticks(tab):
    rows = [[f"{w:018X}", int(two), lo, hi] for (w, two), (lo, hi) in sorted(tab.items())]
    with open(TICKS_PATH, "w") as f:
        f.write("[\n" + ",\n".join(json.dumps(r) for r in rows) + "\n]\n")


def _path(c):
    out = [f"      {s['t'] / 1000:7.1f} ns  {s['at']:<16} {s['arc']}" for s in c["path"]]
    if c["against"]:
        out.append("    against:")
        out += [f"      {s['t'] / 1000:7.1f} ns  {s['at']:<16} {s['arc']}" for s in c["against"]]
    return out


def report(tab, res, base, skip, more, paths=2):
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
    lines.append(f"what no length fixes (holds, handovers, glitches, loops, phase F): "
                 f"{len(other)} checks")
    kinds = defaultdict(list)
    for (chip, check, what), (n, c) in sorted(other.items(), key=lambda kv: kv[1][1]["slack"]):
        kinds[check].append((chip, what, n, c))
    for check, rows in sorted(kinds.items(), key=lambda kv: kv[1][0][3]["slack"]):
        chips = len({r[0] for r in rows})
        lines.append(f"  {check}: {len(rows)} checks on {chips} chips, the worst "
                     f"{rows[0][3]['slack'] / 1000:.1f} ns")
        # a chip's checks with the same slack in as many cases, together
        alike = defaultdict(list)
        for chip, what, n, c in rows:
            alike[(chip, round(c["slack"], -1), n)].append((what, c))
        for (chip, _, n), group in list(alike.items())[:5]:
            like = f" and {len(group) - 1} like it" if len(group) > 1 else ""
            lines.append(f"    {group[0][1]['slack'] / 1000:7.1f} ns  {chip:8} {group[0][0]}{like} "
                         f"({n} cases)")
        if paths and rows[0][3]["path"] + rows[0][3]["against"]:
            lines.append(f"    the path of {rows[0][0]} {rows[0][1]}:")
            lines += _path(rows[0][3])
    lines.append("")
    lines += _variants(res)
    lines += _crossings(res)
    lines += _coverage(res, more["coverage"], skip)
    lines += _exceptions(res, skip)
    lines += _unresolved(res)
    lines += _tails(more)
    notes = Counter(n for branches in res.values() for b in branches for n in b["notes"])
    if notes:
        lines.append("")
        lines.append("notes: " + "; ".join(f"{n} ({k})" for n, k in notes.most_common(5)))
    return "\n".join(lines)


def _variants(res):
    """The variants' own failures: the checks failing at a device that
    fail at no other, and with a task that fail in no case without one."""
    fails = defaultdict(dict)       # (DEV or TASK, its value or None): {check: worst}
    count = Counter()
    for k, branches in res.items():
        tags = dict((n, v) for n, v in k[2] if n in ("DEV", "TASK"))
        for fam in ("DEV", "TASK"):
            t = (fam, tags.get(fam))
            count[t] += 1
            for c in (c for b in branches for c in b["worst"] if c["slack"] < 0):
                if key(c) not in fails[t] or c["slack"] < fails[t][key(c)]["slack"]:
                    fails[t][key(c)] = c
    lines = ["the variants: their own failing checks (at one device and no other; "
             "with a task, and in no case without)"]
    for t in sorted(t for t in count if t[1] is not None):
        others = set().union(*(set(f) for u, f in fails.items() if u[0] == t[0] and u != t
                               and (u[1] is None or t[0] == "DEV")))
        own = sorted((c for kk, c in fails[t].items() if kk not in others),
                     key=lambda c: c["slack"])
        lines.append(f"  {t[0]}={t[1]}: {count[t]} cases, {len(own)} checks of its own"
                     + "".join(f"; {c['slack'] / 1000:.1f} ns {c['check']} {c['chip']} "
                               f"{c['what']}" for c in own[:3]))
    lines.append("")
    return lines


def _crossings(res):
    """The synchronisers' captures (RFC 0048 9.7), with the time their
    outputs have to settle in."""
    sync = {}
    for branches in res.values():
        for b in branches:
            for x in b["crossings"]:
                k = (x["chip"], x["pin"], x["source"])
                if x["settle"] is not None:
                    sync[k] = min(sync.get(k, x["settle"]), x["settle"])
                else:
                    sync.setdefault(k, None)
    lines = ["asynchronous inputs at synchronisers, and the time their outputs have to settle:"]
    for (chip, pin, src), settle in sorted(sync.items()):
        t = f"{settle / 1000:.2f} ns" if settle is not None else "nothing reads it in a case"
        lines.append(f"  {chip} {pin} from {src}: {t}")
    return lines


def _coverage(res, cov, skip):
    """What the cases leave untimed (RFC 0048 9.8)."""
    lines = []
    seen = {i for branches in res.values() for b in branches for i in b["evaluated"]}
    never = [c for i, c in enumerate(cov["checks"]) if i not in seen and c[0] not in skip]
    lines.append(f"coverage: {len(cov['checks'])} checks, {len(seen)} evaluated in some case; "
                 f"{len(never)} in none, the video's chips aside")
    by = Counter(f"{chip} {kind}" for chip, kind, _ in never)
    if by:
        lines.append("  in none: " + ", ".join(f"{k} ({n})" if n > 1 else k
                                                 for k, n in sorted(by.items())))
    for name, what in (("undescribed", "chips with no description"),
                       ("untimed", "outputs nothing times")):
        if cov[name]:
            lines.append(f"  {what}: {', '.join(cov[name])}")
    if cov["unchecked"]:
        lines.append("  checks the data hasn't the figures for: "
                     + ", ".join(f"{c} {w}" for c, w in cov["unchecked"]))
    srcs = defaultdict(list)
    for chip, src in cov["async_forces"]:
        srcs[src].append(chip)
    for src, chips in sorted(srcs.items()):
        lines.append(f"  clears and presets {src} reaches: {', '.join(sorted(chips))}")
    return lines


def _exceptions(res, skip):
    """What each of the cases' exceptions took."""
    taken, cases = Counter(), Counter()
    for (w, two, extra, lo, hi), branches in res.items():
        exc = case(w, extra, lo, hi, skip)["exceptions"]
        for e, n in zip(exc, map(max, zip(*(b["excepted"] for b in branches)))):
            k = (e.get("chip"), e["reason"])
            taken[k] += n
            cases[k] += 1
    return [f"exceptions: {chip or 'any chip'}, {reason}: {taken[(chip, reason)]} checks "
            f"in {cases[(chip, reason)]} cases" for chip, reason in sorted(taken)]


def _unresolved(res):
    """What the branches couldn't check for want of values."""
    lines = []
    why = Counter()
    for branches in res.values():
        for b in branches:
            for u in b["unresolved"]:
                why[re.sub(r" from [\d.]+ ns", "", u.split(": ", 1)[1])] += 1
    if why:
        lines.append("unresolved, for values a case doesn't know (by branch): "
                     + "; ".join(f"{w} ({n})" for w, n in why.most_common()))
    repeats = sum(1 for branches in res.values() for b in branches if b["repeats"] is not None)
    lines.append(f"branches that came back to an earlier state: {repeats}")
    return lines


def _tails(more):
    """The cycle before's tails and what they cost."""
    tails = more["tails"]
    lines = [f"the cycle before's tails: {len(tails)} nets, "
             + (f"stable after {more['runs']} runs" if more["stable"]
                else f"still changing after {more['runs']} runs")]
    if tails:
        late = sorted(tails, key=lambda t: -t[2])[:4]
        lines.append("  the latest: " + ", ".join(f"{n} {l / 1000:.1f} ns" for n, _, l in late))
    lines.append(f"  checks they make worse: {len(more['worse'])}")
    for (chip, check, what), (a, b) in sorted(more["worse"].items(), key=lambda kv: kv[1][1])[:4]:
        lines.append(f"    {chip} {check} {what}: {a / 1000:.1f} -> {b / 1000:.1f} ns")
    return lines


def cmd_sta(args):
    tab, res, base, skip, more = analyse()
    print(f"static timing analysis (the two-halves machine, infra/sta): {parts.VARIANT}, "
          f"min and max delays")
    print(report(tab, res, base, skip, more, args.paths))
    if args.write:
        write_ticks(tab)
        print(f"wrote {os.path.relpath(TICKS_PATH)} ({len(tab)} words)")
    return 0
