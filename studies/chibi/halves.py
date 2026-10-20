"""The two-halves variant's time on the suite, an exploration: the first
cut's microcode, folded as the register-transfer model runs it. A
microinstruction that is a 32-bit operation's high half (it reads or writes
a high half, or loads PC's or MAR's) becomes the high half of the
microinstruction it twins (or a low half the high half before it, the
order of a right shift's halves): the last one before it, within three steps of
the same block run straight through, with the same sources, destinations,
memory operation and latch load, that hasn't a high half yet. Each half
takes the ticks static timing analysis gives it (sta2.py); a cycle is phase
F's three ticks and its halves. The video's buffer is simulated against
the cycles: a word wanted every 8 ticks while a line is shown, read in each
cycle's phase F and in each half that doesn't use memory.

A straight port: microcode written for two-half microinstructions could do
better, and the fold ignores the few twins a flag between them would part.

  heron chibi hw halves
"""

import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

from . import check, routines, sta, sta2, ucode as uc
from .rtl import RTL

LINE, SHOWN, LINES, VISIBLE = 1600, 1280, 525, 480      # ticks a line, ticks shown; lines


def tick_table():
    res, _ = sta2.analyse()
    return {key: (sta2.ticks(lo[0], sta2.L_START), sta2.ticks(hi[0], sta2.L_END) if hi else None)
            for key, lo, hi in res}


def high(f):
    return bool((f["DS"] == uc.DS_RF and f["HR"]) or (f["WEN"] and f["HW"]) or f["AXM"] == 2
                or f["AXP"] == 2)


def shape(f):
    return (f["DS"], f["RS"], f["KR"], f["WS"], f["KW"], f["WEN"], f["MOP"], f["LDL"], f["SZ"])


class Video:
    """The buffer between the reads and the shifter, `cap` words."""

    def __init__(self, cap, f_only=False):
        self.cap, self.fifo, self.next, self.short = cap, cap, 0, 0
        self.f_only = f_only

    def advance(self):
        self.next += 8
        if self.next % LINE >= SHOWN:
            self.next += LINE - self.next % LINE
        if self.next // LINE % LINES >= VISIBLE:
            self.next += (LINES - self.next // LINE % LINES) * LINE

    def slot(self, t, read=True):
        while self.next <= t:
            if self.fifo:
                self.fifo -= 1
            else:
                self.short += 1         # a cycle stretched for the video
            self.advance()
        if read and self.fifo < self.cap and not (self.f_only and read == "half"):
            self.fifo += 1


class Folded(RTL):
    def __init__(self, s, table):
        super().__init__(s)
        self.cs = routines.control_store()
        self.table = table
        self.mask = 0
        for name in sta.UNTIMED:
            b, w, _ = uc._pos[name]
            self.mask |= ((1 << w) - 1) << b
        self.open = []                  # this block's cycles still open to a high half
        self.last = None
        self.t = 0
        self.lengths = Counter()
        self.videos = [Video(1), Video(2), Video(1, True), Video(2, True), Video(4, True)]
        self.cache = {}

    def close(self, rec):
        L, H, mem_l, mem_h = rec[:4]
        n = 3 + L + (H or 0)
        self.lengths[n] += 1
        for v in self.videos:
            v.slot(self.t + 3)
            v.slot(self.t + 3 + L, "half" if not mem_l else False)
            if H:
                v.slot(self.t + n, "half" if not mem_h else False)
        self.t += n

    def cycle(self):
        a = uc.addr(self.page, self.N, self.op, self.step)
        f = self.cache.get(a)
        if f is None:
            f = self.cache[a] = uc.unpack(self.cs.words[a])
        mem = f["MOP"] in (uc.MOP_RDM, uc.MOP_WRM)
        io = mem and bool(self.mar31)
        key = (self.cs.words[a] & ~self.mask, (("A31", int(io)),) if mem else ())
        L, H = self.table[key]
        block = (self.page, self.N, self.op)
        if self.last is None or self.last[0] != block or self.last[1] + 1 != self.step:
            while self.open:
                self.close(self.open.pop(0))
        self.last = (block, self.step)
        twin = None
        if not io and H:
            # a high half after its low half; or, high half first (a right
            # shift's order), a low half after its high
            sh, hf = shape(f), high(f)
            for rec in reversed(self.open):
                if rec[1] is None and rec[4] == sh and rec[5] != hf:
                    twin = rec
                    break
        if twin is not None:
            twin[1], twin[3] = H, mem
        else:
            self.open.append([max(L, 2 if mem else 1), None, mem, False, shape(f), high(f)])
            if len(self.open) > 3:
                self.close(self.open.pop(0))
        super().cycle()

    def finish(self):
        while self.open:
            self.close(self.open.pop(0))


def run_one(args):
    import heron.studies.v2_isa  # noqa: F401
    from heron.infra.programs import metadata
    from .system import System
    path, table = args
    img = check.assemble(path)
    s = System(metadata(path)["input"])
    s.load(img)
    m = Folded(s, table)
    m.run(100_000_000)
    m.finish()
    return (os.path.basename(path)[:-2], m.cycles, m.t, m.lengths,
            [((v.cap, v.f_only), v.short) for v in m.videos])


def best_classes(lengths, n=4):
    """The n cycle lengths that minimise the time, each cycle rounded up."""
    import itertools
    ls = sorted(lengths)
    best = None
    for cl in itertools.combinations(ls, min(n, len(ls))):
        if cl[-1] != ls[-1]:
            continue
        t = sum(c * min(x for x in cl if x >= L) for L, c in lengths.items())
        if best is None or t < best[0]:
            best = (t, cl)
    return best


def cmd_halves(args):
    from heron.studies.v2_isa import testing
    table = tick_table()
    paths = testing.program_paths()
    with ProcessPoolExecutor(4) as ex:
        rows = list(ex.map(run_one, [(p, table) for p in paths]))
    K, T = sta2.K, sta.VGA_PERIOD
    tot = Counter()
    lengths = Counter()
    short = Counter()
    print(f"{'program':10} {'cycles now':>11} {'cycles':>10} {'ticks':>11} {'speed-up':>9}")
    for name, cyc, ticks, ls, vs in rows:
        lengths.update(ls)
        n = sum(ls.values())
        tot["now"] += cyc
        tot["cycles"] += n
        tot["ticks"] += ticks
        for cap, s in vs:
            short[cap] += s
        print(f"{name:10} {cyc:11d} {n:10d} {ticks:11d} {cyc * T / (ticks * K):8.2f}x")
    now, new = tot["now"] * T, tot["ticks"] * K
    print(f"{'total':10} {tot['now']:11d} {tot['cycles']:10d} {tot['ticks']:11d} {now / new:8.2f}x")
    print("cycle lengths (ticks):", ", ".join(f"{L}: {100 * c / tot['cycles']:.1f}%"
                                              for L, c in sorted(lengths.items())))
    t4, cl = best_classes(lengths)
    print(f"four length classes {cl}: x{now / (t4 * K):.2f}")
    for (cap, fo), n in sorted(short.items()):
        print(f"video buffer of {cap} word{'s' * (cap > 1)}, reads in "
              f"{'phase F only' if fo else 'phase F and idle halves'}: {n} stretches "
              f"({100 * 2 * n / tot['ticks']:.2f}% of the time at 2 ticks each)")
    return 0
