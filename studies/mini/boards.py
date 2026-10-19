"""Heron Mini on three boards (RFC 0041, 28): which chip goes on which
board, the signals between the boards, the ribbon cables' connectors,
each board's netlist for the PCB study, and the boards' delays for the
timing analysis.

The boards are stacked on standoffs, top to bottom cpu1, cpu2, io (STACK),
and joined by IDC ribbon cables. The CPU is on cpu1 and cpu2: cpu1 starts
with the sequencer's side (the control store and what the microinstruction
addresses, the clock and the flags), cpu2 with the datapath and the
memory; the video, the video RAM and the I/O are on io.

The assignment (assign()):
  1. each chip starts on its section's board (SECTIONS), a gate package
     on the board most of its gates' sections start on, and may move to
     the boards its sections allow (a CPU section to cpu1 or cpu2, an I/O
     one to io only); OVERRIDES pins single chips to a board. A section
     SECTIONS doesn't know is placed by a guess (a video or I/O word in
     its name puts it on io; otherwise on the board most of its nets go
     to, free to move), with a warning;
  2. a k-way Fiduccia-Mattheyses refinement moves chips to minimise the
     wires between the boards: a net on two boards is one wire, on all
     three two (top to middle, middle to bottom). It keeps every board
     at or below the package limit (160, LIMIT 190 at most) and each CPU
     board at least 40 % of the CPU's packages. It is deterministic:
     passes from the start, then restarts from seeded perturbations of
     the best.
A package counts as 1 (a half of a two-part package as a half);
resistor networks and connectors (the CF card's socket) are on boards
but are listed apart and don't count. Fixtures (the test I/O page, the
rails) are on no board.

The crossing signals of each pair of boards go into IDC headers (2 x 20,
2 x 25 or 2 x 32 pins), wire k of the ribbon on pin k, with a ground
after every signal by default (`--per-ground 2` or 3 signals a ground);
the clocks get a ground on each side. Each connector is the same on both
boards; on board a, the connectors to board b are J_<b>_1, J_<b>_2, ...

For the PCB study: netlist(board) is one board's Netlist, its signals
that leave the board renamed BUS.<net>, as the system cards name their
connector pins, so that infra/pcb's parts() and check.compare() put them
on the connector pads by the pin maps (connectors(board): the IDC
headers as (ref, footprint, {pad: net})). pcb_board() is cards.board()'s
counterpart (studies/pcb/cards.py hands `heron pcb build mini-<board>` to
it). `heron mini boards --write` writes the boards as JSON with a README
into build/mini/boards/.

For the timing: add_board_delays(nl) adds a fixed delay (default 1.5 ns:
connector, ribbon, connector) to every output that drives a pin on
another board, in any netlist of the mini (the static timing analysis's
has fixtures for the clock generator and no video: its chips are matched
to the assignment's by their connections). The delay is the output's, so
its loads on its own board see it too: pessimistic for a clean line,
about right for an unterminated ribbon, whose near loads may wait for the
far end's reflection. The clocks (CLK, MCLK) are left out unless asked:
a clock sent to each board through a buffer of matched delay arrives
everywhere together. `heron mini hw sta --boards` and the chip-level
runs' `--boards` use it; `heron mini boards --sta` compares the analysis
with the plain one.

  heron mini boards [--list] [--header 40|50|64] [--per-ground 1|2|3]
                    [--limit N] [--write] [--sta [--board-delay NS]]
"""

import argparse
import json
import math
import os
import random
import re
import sys
from collections import Counter, defaultdict

from heron import BUILD
from heron.infra.hw.netlist import Instance, Netlist
from heron.infra.pcb import packages

from . import board as mini_board, parts

OUT = os.path.join(BUILD, "mini", "boards")

BOARDS = ("cpu1", "cpu2", "io")
STACK = BOARDS                  # top to bottom
CPU = ("cpu1", "cpu2")
IO = ("io",)
TARGET = 160                    # packages a board, ideally (Emily)
LIMIT = 190                     # ... at most
CPU_BALANCE = 0.4               # each CPU board holds at least this share of the CPU's
DELAY_PS = 1500                 # connector, ribbon, connector
HEADERS = {40: (2, 20), 50: (2, 25), 64: (2, 32)}
HEADER = 64
PER_GROUND = 1                  # signals between grounds
CLOCKS = ("MCLK", "CLK")        # a ground each side in the ribbon; no board delay by default
RESETS = ("RESET", "RESET_n")
NOT_CHIPS = {"cf": "connector"}  # types that are on a board but aren't chips
RN_TYPES = ("pullup",)

# section -> (the board it starts on, the boards it may move to)
_SEQ = ("cpu1", CPU)
_DATA = ("cpu2", CPU)
_IO = ("io", IO)
SECTIONS = {
    "Reset": _SEQ, "Clock generator": _SEQ, "Hold": _SEQ, "Control store": _SEQ,
    "Instruction register": _SEQ, "Next address": _SEQ, "Interrupt request": _SEQ,
    "ALU control": _SEQ, "Loop counter": _SEQ, "SX and EX": _SEQ, "Immediate unit": _SEQ,
    "Flags": _SEQ, "Condition latches": _SEQ, "Branch condition": _SEQ, "PC": _SEQ,
    "Prefetch queue": _SEQ,
    "Register file": _DATA, "A bus": _DATA, "B bus": _DATA, "MQ": _DATA, "ALU": _DATA,
    "Result multiplexer": _DATA, "R and T": _DATA, "MAR": _DATA, "Memory": _DATA,
    "Store data": _DATA,
    "Video RAM": _IO, "I/O": _IO, "CF card": _IO, "Expansion ports": _IO, "Timer": _IO,
    "Boot flash": _IO, "UARTs": _IO, "On-board registers": _IO, "Video timing": _IO,
    "Video fetch": _IO, "Video output": _IO, "Video registers": _IO,
}
# a section SECTIONS doesn't name goes on io if its name has one of these
IO_WORDS = re.compile(r"video|palette|uart|serial|keyboard|mouse|ps/?2|timer|sound|speaker|"
                      r"expansion|port|cf\b|compactflash|boot|i/o|led|vram", re.I)
OVERRIDES = {}                  # ref -> board: chips pinned to a board


# ---- the netlist's parts ------------------------------------------------------------


def kind(inst):
    """What a netlist instance is on a board: "chip", "rn" (a resistor
    network), "connector", "other" (on a board, not a chip), or "fixture"
    (on none)."""
    t = inst.type
    if t.family == "fixture":
        return "fixture"
    if t.name in NOT_CHIPS:
        return NOT_CHIPS[t.name]
    if t.name in RN_TYPES:
        return "rn"
    if t.family in ("connector", "conn"):
        return "connector"
    if t.family == "passive":
        return "other"
    return "chip"


def weight(inst):
    """What an instance counts toward its board's packages."""
    return 1.0 / inst.type.per_package if kind(inst) == "chip" else 0.0


def rails(nl):
    """{net: "GND" or "VCC"} for the supply rails: GND, VCC and what a const
    fixture drives (infra/pcb/physical.py's rule)."""
    out = {"GND": "GND", "VCC": "VCC"}
    for inst in nl.instances:
        if inst.type.name == "const":
            for pin, net in inst.conn.items():
                out[net] = "GND" if pin == "LO" else "VCC"
    return out


def signal_nets(nl):
    """{net: [(ref, pin)]}: the nets between the instances that are on
    boards, without the rails."""
    rail = rails(nl)
    out = defaultdict(list)
    for inst in nl.instances:
        if kind(inst) == "fixture":
            continue
        for pin, net in inst.conn.items():
            if net not in rail:
                out[net].append((inst.ref, pin))
    return dict(out)


def gate_sections(nl):
    """{package ref: [section of each gate]} for the gate packages."""
    out = defaultdict(list)
    for g in nl.gates:
        out[g.ref].append(g.section)
    return dict(out)


def natural(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def compress(nets):
    """Net names, buses as ranges: VA2-21, IOS0-7_n."""
    groups = defaultdict(list)
    single = []
    for n in nets:
        m = re.fullmatch(r"(.*?[A-Za-z_])(\d+)(_n)?", n)
        if m:
            groups[(m.group(1), m.group(3) or "")].append(int(m.group(2)))
        else:
            single.append(n)
    out = []
    for (pre, suf), nums in groups.items():
        nums.sort()
        start = prev = nums[0]
        for x in nums[1:] + [None]:
            if x is not None and x == prev + 1:
                prev = x
                continue
            out.append(f"{pre}{start}{suf}" if start == prev else f"{pre}{start}-{prev}{suf}")
            if x is not None:
                start = prev = x
    return sorted(out + single, key=natural)


# ---- the assignment ---------------------------------------------------------------------


def _cost_table(k):
    """Wires a net on a set of boards (a bit mask) needs: one fewer than
    the boards."""
    return [max(0, bin(m).count("1") - 1) for m in range(1 << k)]


class _FM:
    """k-way Fiduccia-Mattheyses: nodes (ints) on boards (ints), nets as
    tuples of nodes, a cost per net from the set of boards it's on, times
    the net's weight."""

    def __init__(self, n, nets, allowed, wt, cap, floor, cost, fixed, nw=None):
        self.n, self.nets, self.allowed, self.wt = n, nets, allowed, wt
        self.cap, self.floor, self.f, self.fixed = cap, floor, cost, fixed
        self.nw = nw or [1] * len(nets)
        self.k = len(cap)
        self.nets_of = [[] for _ in range(n)]
        for j, ns in enumerate(nets):
            for v in ns:
                self.nets_of[v].append(j)

    def load_state(self, side):
        k = self.k
        self.side = list(side)
        self.cnt = [[0] * k for _ in self.nets]
        for j, ns in enumerate(self.nets):
            for v in ns:
                self.cnt[j][self.side[v]] += 1
        self.mask = [sum(1 << b for b in range(k) if c[b]) for c in self.cnt]
        self.load = [0.0] * k
        for v in range(self.n):
            self.load[self.side[v]] += self.wt[v]
        self.cost = sum(w * self.f[m] for w, m in zip(self.nw, self.mask))

    def key(self):
        """What the refinement minimises: the (weighted) wires, then the
        CPU boards' imbalance."""
        return (round(self.cost, 6), round(abs(self.load[0] - self.load[1]), 6))

    def gain(self, v, b):
        a, f, nw = self.side[v], self.f, self.nw
        g = 0
        for j in self.nets_of[v]:
            m, c = self.mask[j], self.cnt[j]
            m2 = ((m & ~(1 << a)) if c[a] == 1 else m) | (1 << b)
            g += nw[j] * (f[m] - f[m2])
        return g

    def feasible(self, v, b):
        a, w = self.side[v], self.wt[v]
        return self.load[b] + w <= self.cap[b] + 1e-9 and self.load[a] - w >= self.floor[a] - 1e-9

    def move(self, v, b):
        """Move v to b; returns the nets whose crossing changed enough to
        change their nodes' gains."""
        a, w = self.side[v], self.wt[v]
        self.side[v] = b
        self.load[a] -= w
        self.load[b] += w
        hot = []
        for j in self.nets_of[v]:
            c = self.cnt[j]
            c[a] -= 1
            c[b] += 1
            m = self.mask[j]
            m2 = ((m & ~(1 << a)) if c[a] == 0 else m) | (1 << b)
            self.cost += self.nw[j] * (self.f[m2] - self.f[m])
            self.mask[j] = m2
            if c[a] <= 1 or c[b] <= 2:
                hot.append(j)
        return hot

    def fm_pass(self, stall=80):
        """One pass: move the unlocked node with the best gain, even a
        negative one, lock it, and keep the best prefix of the moves."""
        locked = [v in self.fixed or len(self.allowed[v]) < 2 for v in range(self.n)]
        gains = [None] * self.n

        def refresh(v):
            gains[v] = [(self.gain(v, b) if b != self.side[v] else None) if b in self.allowed[v]
                        else None for b in range(self.k)]
        for v in range(self.n):
            if not locked[v]:
                refresh(v)
        best, best_i, hist = self.key(), 0, []
        while True:
            pick = None
            for v in range(self.n):
                if locked[v]:
                    continue
                for b, g in enumerate(gains[v]):
                    if g is None or (pick is not None and g <= pick[0]):
                        continue
                    if self.feasible(v, b):
                        pick = (g, v, b)
            if pick is None:
                break
            _, v, b = pick
            hist.append((v, self.side[v]))
            locked[v] = True
            dirty = set()
            for j in self.move(v, b):
                dirty.update(self.nets[j])
            for u in sorted(dirty):
                if not locked[u]:
                    refresh(u)
            if self.key() < best:
                best, best_i = self.key(), len(hist)
            elif len(hist) - best_i > stall:
                break
        for v, a in reversed(hist[best_i:]):
            self.move(v, a)
        return best_i > 0

    def refine(self, passes=40):
        for _ in range(passes):
            if not self.fm_pass():
                break


class Assignment:
    """Every instance that is on a board, and its board: `board_of`
    {ref: board}. `nl` is the netlist it's for; `warnings` what it had to
    guess."""

    def __init__(self, nl, board_of, warnings=(), start=None):
        self.nl = nl
        self.board_of = dict(board_of)
        self.warnings = list(warnings)
        self.start = dict(start or board_of)

    def refs(self, b, what=None):
        return sorted((r for r, x in self.board_of.items()
                       if x == b and (what is None or kind(self.nl.refs[r]) == what)), key=natural)

    def packages(self, b):
        return math.ceil(sum(weight(self.nl.refs[r]) for r in self.refs(b)) - 1e-9)


def _placement(nl, sections=None, overrides=None):
    """(start {ref: board}, allowed {ref: boards}, fixed refs, warnings)."""
    sections = SECTIONS if sections is None else sections
    overrides = OVERRIDES if overrides is None else overrides
    gsec = gate_sections(nl)
    warnings = []
    unknown = set()
    insts = [i for i in nl.instances if kind(i) != "fixture"]

    def rule(sec):
        if sec in sections:
            return sections[sec]
        unknown.add(sec)
        if sec and IO_WORDS.search(sec):
            return ("io", IO)
        return (None, BOARDS)
    start, allowed, fixed = {}, {}, set()
    for inst in insts:
        secs = gsec.get(inst.ref) or [inst.section]
        rules = [rule(s) for s in secs]
        votes = Counter(b for b, _ in rules if b is not None)
        start[inst.ref] = max(BOARDS, key=lambda b: (votes[b], -BOARDS.index(b))) \
            if votes else None
        allowed[inst.ref] = tuple(b for b in BOARDS if any(b in a for _, a in rules))
    # the unknown sections' chips: where most of their nets go
    nets = signal_nets(nl)
    for _round in range(3):
        for inst in insts:
            if start[inst.ref] is not None:
                continue
            votes = Counter()
            for pin, net in inst.conn.items():
                for r, _p in nets.get(net, ()):
                    if r != inst.ref and start.get(r):
                        votes[start[r]] += 1
            if votes or _round == 2:
                start[inst.ref] = max(BOARDS, key=lambda b: (votes[b], -BOARDS.index(b)))
    for sec in sorted(unknown, key=str):
        refs = [i.ref for i in insts if sec in (gsec.get(i.ref) or [i.section])]
        where = sorted({start[r] for r in refs})
        why = "its name" if sec and IO_WORDS.search(sec) else "their nets"
        warnings.append(f"section {sec!r} isn't in boards.SECTIONS: its {len(refs)} chips start "
                        f"on {', '.join(where)} by a guess ({why})")
    for ref, b in overrides.items():
        if ref not in nl.refs:
            warnings.append(f"OVERRIDES names {ref}, which isn't in the netlist")
            continue
        if b not in BOARDS:
            raise ValueError(f"OVERRIDES puts {ref} on {b!r}, not a board")
        start[ref] = b
        allowed[ref] = (b,)
        fixed.add(ref)
    return start, allowed, fixed, warnings


def assign(nl=None, target=TARGET, sections=None, overrides=None, chains=4, restarts=30,
           seed=1, weights=None):
    """The boards for every instance of the mini's netlist (default:
    board.build(sim=True)): an Assignment. After the refinement from the
    start, `chains` independent chains (random seeds seed, seed + 1, ...)
    of `restarts` each: move a third of the movable chips at random from
    the chain's best, refine, keep it if better. The best of the chains
    wins (on the mini's netlist of 333 packages, about 4 s). `weights`
    {net: weight} makes a net's wires count more (default 1): the nets on
    critical paths, for a cut that keeps them on one board."""
    nl = nl or mini_board.build(sim=True)
    start, allowed, fixed, warnings = _placement(nl, sections, overrides)
    refs = sorted(start, key=natural)
    index = {r: i for i, r in enumerate(refs)}
    bi = {b: i for i, b in enumerate(BOARDS)}
    nets, nw = [], []
    for net, pins in sorted(signal_nets(nl).items()):
        ns = tuple(sorted({index[r] for r, _ in pins}))
        if len(ns) > 1:
            nets.append(ns)
            nw.append((weights or {}).get(net, 1))
    wt = [weight(nl.refs[r]) for r in refs]
    side0 = [bi[start[r]] for r in refs]
    cpu_total = sum(w for w, s in zip(wt, side0) if BOARDS[s] in CPU)
    cap = [float(target)] * len(BOARDS)
    floor = [CPU_BALANCE * cpu_total if b in CPU else 0.0 for b in BOARDS]
    fm = _FM(len(refs), nets, [tuple(bi[b] for b in allowed[r]) for r in refs], wt, cap, floor,
             _cost_table(len(BOARDS)), {index[r] for r in fixed}, nw)
    fm.load_state(side0)
    over = [BOARDS[b] for b in range(len(BOARDS)) if fm.load[b] > cap[b]]
    if over:
        warnings.append(f"{', '.join(over)} start above {target} packages: the refinement only "
                        "moves chips off them")
    fm.refine()
    base, base_key = list(fm.side), fm.key()
    best, best_key = base, base_key
    movable = [v for v in range(len(refs)) if v not in fm.fixed and len(fm.allowed[v]) > 1]
    for c in range(chains if movable else 0):
        rnd = random.Random(seed + c)
        cur, cur_key = base, base_key
        for _ in range(restarts):
            fm.load_state(cur)
            for v in rnd.sample(movable, max(1, len(movable) // 3)):
                b = rnd.choice(fm.allowed[v])
                if b != fm.side[v] and fm.feasible(v, b):
                    fm.move(v, b)
            fm.refine()
            if fm.key() < cur_key:
                cur, cur_key = list(fm.side), fm.key()
        if cur_key < best_key:
            best, best_key = cur, cur_key
    out = Assignment(nl, {r: BOARDS[best[i]] for i, r in enumerate(refs)}, warnings,
                     {r: start[r] for r in refs})
    for b in BOARDS:
        n = out.packages(b)
        if n > LIMIT:
            out.warnings.append(f"{b} has {n} packages, more than {LIMIT}")
        elif n > target:
            out.warnings.append(f"{b} has {n} packages, more than {target}")
    return out


_DEFAULT = None


def default():
    """The assignment of board.build(sim=True), computed once."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = assign()
    return _DEFAULT


# ---- what crosses ----------------------------------------------------------------------


def crossing(a):
    """{net: {board: [(ref, pin)]}} for the nets on more than one board."""
    out = {}
    for net, pins in signal_nets(a.nl).items():
        by = defaultdict(list)
        for r, p in pins:
            by[a.board_of[r]].append((r, p))
        if len(by) > 1:
            out[net] = dict(by)
    return out


def pairs_of(boards):
    """The cables a net on these boards takes: neighbours in the stack
    among them (a net on two boards goes straight between them)."""
    s = sorted(boards, key=STACK.index)
    return list(zip(s, s[1:]))


def pair_signals(a, cross=None):
    """{(board, board): [nets]}, the pairs in STACK order."""
    cross = crossing(a) if cross is None else cross
    out = defaultdict(list)
    for net, by in cross.items():
        for p in pairs_of(by):
            out[p].append(net)
    order = sorted(out, key=lambda p: (STACK.index(p[0]), STACK.index(p[1])))
    return {p: sorted(out[p], key=natural) for p in order}


def signal_order(nets):
    """The order signals go into a pair's connectors: the clocks first,
    then by name (a bus together)."""
    return sorted(nets, key=lambda n: (n not in CLOCKS, natural(n)))


def pack(nets, header=HEADER, per_ground=PER_GROUND, clocks=CLOCKS):
    """The wires of IDC headers for these signals: [[net or "GND"] of
    `header` wires]. Wire 1 is a ground, then `per_ground` signals between
    grounds; a clock has a ground on each side."""
    out, cur, run = [], [], 0
    for net in signal_order(nets):
        clk = net in clocks
        while True:
            if not cur:
                cur, run = ["GND"], 0
            pre = 1 if (run >= per_ground or (clk and cur[-1] != "GND")) else 0
            if len(cur) + pre + 1 + (1 if clk else 0) <= header:
                break
            out.append(cur + ["GND"] * (header - len(cur)))
            cur = []
        if pre:
            cur.append("GND")
            run = 0
        cur.append(net)
        run += 1
        if clk:
            cur.append("GND")
            run = 0
        if len(cur) == header:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur + ["GND"] * (header - len(cur)))
    return out


def connectors(a=None, header=HEADER, per_ground=PER_GROUND):
    """[{"ref", "board", "to", "cable", "pins", "footprint", "pinmap"
    {pad: net or GND}}]: every IDC header, one entry each end."""
    a = a or default()
    fp = packages.IDC_HEADERS[header]
    out = []
    for (x, y), nets in pair_signals(a).items():
        for i, wires in enumerate(pack(nets, header, per_ground)):
            pinmap = {str(k + 1): w for k, w in enumerate(wires)}
            cable = f"{x}-{y}/{i + 1}"
            for here, there in ((x, y), (y, x)):
                out.append({"ref": f"J_{there}_{i + 1}", "board": here, "to": there,
                            "cable": cable, "pins": header, "footprint": fp,
                            "pinmap": pinmap})
    return out


def broadcast(nl):
    """The broadcast nets: the clocks, reset, the microinstruction bus."""
    u = set(mini_board.control_nets().values())
    return set(CLOCKS) | set(RESETS) | u


def split_gates(a):
    """(gate packages, [(ref, its gates' sections, the boards those
    sections' chips are mostly on)]) for the packages whose gates serve
    more than one section."""
    gsec = gate_sections(a.nl)
    home = {}
    per = defaultdict(Counter)
    for r, b in a.board_of.items():
        if r not in gsec:
            per[a.nl.refs[r].section][b] += 1
    for sec, c in per.items():
        home[sec] = c.most_common(1)[0][0]
    out = []
    for ref, secs in sorted(gsec.items(), key=lambda kv: natural(kv[0])):
        s = sorted(set(secs), key=str)
        if len(s) > 1 and ref in a.board_of:
            out.append((ref, s, sorted({home.get(x, a.board_of[ref]) for x in s},
                                       key=BOARDS.index)))
    return len(gsec), out


# ---- the report ------------------------------------------------------------------------------


def report(a=None, header=HEADER, per_ground=PER_GROUND, listing=False, top=15):
    a = a or default()
    nl = a.nl
    cross = crossing(a)
    pairs = pair_signals(a, cross)
    out = [f"Heron Mini on {len(BOARDS)} boards (stacked {', '.join(STACK)}, top to bottom): "
           f"{sum(a.packages(b) for b in BOARDS)} packages, at most {TARGET} a board "
           f"({LIMIT} the limit)", ""]
    for w in a.warnings:
        out.append(f"warning: {w}")
    if a.warnings:
        out.append("")
    moved = sorted((r for r in a.board_of if a.board_of[r] != a.start.get(r)), key=natural)
    out.append(f"the refinement moved {len(moved)} chips from their sections' boards: "
               + ", ".join(f"{r} ({nl.refs[r].section}) {a.start[r]}->{a.board_of[r]}"
                           for r in moved[:12]) + (" ..." if len(moved) > 12 else ""))
    out.append("")
    conns = connectors(a, header, per_ground)
    for b in BOARDS:
        chips_ = a.refs(b, "chip")
        out.append(f"{b}: {a.packages(b)} packages")
        by_part = Counter(nl.refs[r].part_number(parts.VARIANT) for r in chips_)
        by_part = sorted(by_part.items(), key=lambda kv: (-kv[1], kv[0]))
        out.append("  " + ", ".join(f"{n} {p}" for p, n in by_part))
        secs = Counter(nl.refs[r].section for r in chips_)
        out.append("  sections: " + ", ".join(f"{s} {n}" for s, n in
                                              sorted(secs.items(), key=lambda kv: -kv[1])))
        rn = a.refs(b, "rn")
        other = a.refs(b, "connector") + a.refs(b, "other")
        jn = [c for c in conns if c["board"] == b]
        out.append(f"  also: {len(rn)} resistor networks ({' '.join(rn) or '-'}); "
                   f"{len(other)} other ({' '.join(other) or '-'}); "
                   f"{len(jn)} IDC headers ({' '.join(c['ref'] for c in jn) or '-'})")
        out.append("")
    out.append(f"signals between the boards: {len(cross)} nets, "
               f"{sum(len(n) for n in pairs.values())} wires")
    for (x, y), nets in pairs.items():
        counts = {h: len(pack(nets, h, per_ground)) for h in HEADERS}
        out.append(f"  {x}-{y}: {len(nets)} signals; IDC headers with a ground every "
                   f"{per_ground} signal{'s' if per_ground > 1 else ''}: "
                   + ", ".join(f"{counts[h]} x {HEADERS[h][0]}x{HEADERS[h][1]}" for h in HEADERS))
        names = compress(nets)
        if listing or len(names) <= 40:
            out.append("    " + " ".join(names))
        else:
            out.append("    " + " ".join(names[:40]) + f" ... ({len(names) - 40} more; --list)")
    out.append("")
    bc = broadcast(nl)
    crossing_bc = sorted((n for n in cross if n in bc), key=natural)
    u = [n for n in crossing_bc if n.startswith("u")]
    out.append("broadcast nets that cross: "
               + "; ".join(f"{n} ({'+'.join(sorted(cross[n], key=BOARDS.index))})"
                           for n in crossing_bc if not n.startswith("u")))
    if u:
        where = Counter("+".join(sorted(cross[n], key=BOARDS.index)) for n in u)
        n_u = len([n for n in bc if n.startswith("u")])
        out.append(f"  the microinstruction: {len(u)} of {n_u} lines cross "
                   f"({', '.join(f'{k}: {v}' for k, v in where.items())})")
    out.append("")
    drv = {}
    for k in (("out", "tri"), ("io",)):         # an oscillator's output is an io pin
        for inst in nl.instances:
            for pin, net in inst.conn.items():
                if inst.kind(pin) in k and kind(inst) != "fixture":
                    drv.setdefault(net, inst.ref)

    def far(net):
        d = drv.get(net)
        home = a.board_of.get(d) if d else None
        return sum(len(p) for b, p in cross[net].items() if b != home)
    worst = sorted(cross, key=lambda n: (-far(n), -len(cross[n]), natural(n)))[:top]
    out.append(f"the nets with the most pins away from their driver's board (top {top}):")
    for n in worst:
        d = drv.get(n)
        out.append(f"  {n:<12} {far(n):3} away; "
                   + ", ".join(f"{b} {len(p)}" for b, p in sorted(cross[n].items(),
                                                                key=lambda kv: BOARDS.index(kv[0])))
                   + (f" (driven by {d} on {a.board_of.get(d)})" if d else ""))
    out.append("")
    total, split = split_gates(a)
    multi = [s for s in split if len(s[2]) > 1]
    out.append(f"gate packages: {total}; {len(split)} serve more than one section, {len(multi)} of "
               f"them sections mostly on different boards (one per board instead: +{len(multi)} "
               "packages at most)")
    for ref, secs, homes in multi:
        out.append(f"  {ref} ({a.board_of[ref]}): {', '.join(map(str, secs))} -> "
                   f"{', '.join(homes)}")
    return "\n".join(out)


# ---- one board's netlist, the export ------------------------------------------------------


def board_netlist(name, a=None, header=HEADER, per_ground=PER_GROUND):
    """One board's Netlist: its instances (copies), the nets that leave it
    renamed BUS.<net>, and `connectors` [(ref, footprint, {pad: net or
    GND})], `board` its name. infra/pcb's parts(nl, style, connectors=)
    puts the BUS nets on the pads by these maps."""
    a = a or default()
    if name not in BOARDS:
        raise KeyError(f"no board {name!r} (boards: {', '.join(BOARDS)})")
    cross = crossing(a)
    rail = rails(a.nl)
    out = Netlist()

    def rename(net):
        if net in rail:
            return rail[net]
        return f"BUS.{net}" if net in cross else net
    for inst in a.nl.instances:
        if a.board_of.get(inst.ref) != name:
            continue
        new = Instance(out, inst.type.name, inst.ref, inst.role, inst.part, inst.params,
                       inst.nocheck)
        new.extra, new.pin_extra = dict(inst.extra), dict(inst.pin_extra)
        new.gal, new.program = inst.gal, inst.program
        new.conn = {p: rename(n) for p, n in inst.conn.items()}
        new.section = inst.section
        out.instances.append(new)
        out.refs[new.ref] = new
    for g in a.nl.gates:
        if g.ref in out.refs:
            out.gates.append(g)
    for s in a.nl.sections:
        if any(i.section == s[1] for i in out.instances):
            out.sections.append(s)
    out.board = name
    out.connectors = [(c["ref"], c["footprint"], dict(c["pinmap"]))
                      for c in connectors(a, header, per_ground) if c["board"] == name]
    return out


def netlist(name, a=None, header=HEADER, per_ground=PER_GROUND):
    """board_netlist() of the default assignment: the PCB study's way in."""
    return board_netlist(name, a, header, per_ground)


def footprints(typ):
    """{style: KiCad footprint or None} for a chip type."""
    out = {}
    for style in ("smd", "dip"):
        try:
            out[style] = packages.footprint_for(typ, style) if typ in packages.PINOUTS else None
        except KeyError:
            out[style] = None
    return out


def export(name, a=None, header=HEADER, per_ground=PER_GROUND):
    """One board as a JSON-able dict (README.md in build/mini/boards
    describes it)."""
    a = a or default()
    nl = board_netlist(name, a, header, per_ground)
    gsec = gate_sections(a.nl)
    cross = crossing(a)
    chips_ = []
    for inst in sorted(nl.instances, key=lambda i: natural(i.ref)):
        fp = footprints(inst.type.name)
        chips_.append({
            "ref": inst.ref, "type": inst.type.name, "kind": kind(inst),
            "part": inst.part_number(parts.VARIANT), "section": inst.section,
            **({"sections": sorted(set(map(str, gsec[inst.ref])))} if inst.ref in gsec else {}),
            "footprint": fp if any(fp.values()) else None})
    nets = defaultdict(list)
    for inst in nl.instances:
        for pin, net in inst.conn.items():
            nets[net[4:] if net.startswith("BUS.") else net].append(f"{inst.ref}.{pin}")
    conns = []
    for c in connectors(a, header, per_ground):
        if c["board"] != name:
            continue
        conns.append({k: c[k] for k in ("ref", "to", "cable", "pins", "footprint", "pinmap")})
        for pad, net in c["pinmap"].items():
            nets[net].append(f"{c['ref']}.{pad}")
    pairs = pair_signals(a, cross)
    summary = {
        "packages": a.packages(name),
        "chips": len([i for i in nl.instances if kind(i) == "chip"]),
        "resistor networks": [i.ref for i in nl.instances if kind(i) == "rn"],
        "other parts": [i.ref for i in nl.instances if kind(i) in ("connector", "other")],
        "idc headers": len(conns),
        "sections": dict(Counter(str(i.section) for i in nl.instances
                                 if kind(i) == "chip").most_common()),
        "signals to": {(y if x == name else x): len(ns) for (x, y), ns in pairs.items()
                       if name in (x, y)},
        "offboard nets": sorted((n for n in cross if name in cross[n]), key=natural),
    }
    return {"board": name, "generated by": "heron mini boards --write",
            "variant": parts.VARIANT, "stack": list(STACK), "header": header,
            "per ground": per_ground, "summary": summary, "chips": chips_,
            "nets": {n: sorted(p, key=natural) for n, p in sorted(nets.items(),
                                                                   key=lambda kv: natural(kv[0]))},
            "connectors": conns}


def load(path):
    """A board's JSON back as a Netlist (connections only, no equations):
    its connectors' pins as nets on `connectors`, as board_netlist()."""
    with open(path) as f:
        d = json.load(f)
    nl = Netlist()
    offboard = set(d["summary"]["offboard nets"])
    by = defaultdict(dict)
    for net, pins in d["nets"].items():
        for rp in pins:
            ref, pin = rp.rsplit(".", 1)
            by[ref][pin] = f"BUS.{net}" if net in offboard else net
    conn_refs = {c["ref"] for c in d["connectors"]}
    for c in d["chips"]:
        inst = Instance(nl, c["type"], c["ref"])
        inst.conn = dict(by[c["ref"]])
        inst.section = c["section"]
        nl.instances.append(inst)
        nl.refs[inst.ref] = inst
    nl.board = d["board"]
    nl.connectors = [(c["ref"], c["footprint"], dict(c["pinmap"])) for c in d["connectors"]]
    missing = set(by) - set(nl.refs) - conn_refs
    if missing:
        raise ValueError(f"{path}: pins of unknown parts {sorted(missing)[:5]}")
    return nl


def missing_footprints(a=None):
    """{chip type: [refs]} that infra/pcb/packages.py has no pinout or
    footprint for."""
    a = a or default()
    out = defaultdict(list)
    for r in a.board_of:
        t = a.nl.refs[r].type.name
        if None in footprints(t).values():
            out[t].append(r)
    return dict(out)


def write(a=None, header=HEADER, per_ground=PER_GROUND, out_dir=OUT):
    """build/mini/boards/<board>.json and README.md."""
    a = a or default()
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for b in BOARDS:
        p = os.path.join(out_dir, f"{b}.json")
        with open(p, "w") as f:
            json.dump(export(b, a, header, per_ground), f, indent=1)
            f.write("\n")
        paths.append(p)
    p = os.path.join(out_dir, "README.md")
    with open(p, "w") as f:
        f.write(readme(a, header, per_ground))
    paths.append(p)
    return paths


def readme(a, header=HEADER, per_ground=PER_GROUND):
    cross = crossing(a)
    pairs = pair_signals(a, cross)
    conns = connectors(a, header, per_ground)
    miss = missing_footprints(a)
    rows = []
    for b in BOARDS:
        rn = a.refs(b, "rn")
        other = a.refs(b, "connector") + a.refs(b, "other")
        rows.append(f"| {b} | {a.packages(b)} | {len(rn)} | {', '.join(other) or '-'} | "
                    f"{len([c for c in conns if c['board'] == b])} |")
    prow = []
    for (x, y), nets in pairs.items():
        n = len(pack(nets, header, per_ground))
        alt = ", ".join(f"{len(pack(nets, h, per_ground))} x {h}" for h in HEADERS if h != header)
        prow.append(f"| {x}-{y} | {len(nets)} | {n} x {header} pins ({alt}) |")
    gnd = "every other wire" if per_ground == 1 else f"one wire in {per_ground + 1}"
    lines = [
        "# Heron Mini's boards",
        "",
        "Generated by `heron mini boards --write` (studies/mini/boards.py) from the",
        "chip-level netlist (`board.build(sim=True)`): don't edit; rerun it after the",
        "netlist changes. The assignment, the report and the timing are in",
        "`heron mini boards` (`--list` lists every crossing signal, `--sta` the",
        "board delays' effect on the microinstructions).",
        "",
        f"Three boards, stacked on standoffs top to bottom {', '.join(STACK)}, joined by",
        f"IDC ribbon cables. The CPU is on cpu1 and cpu2, the video, its RAM and the",
        f"I/O on io. At most {TARGET} packages a board (Emily: ideally 160, {LIMIT} at",
        "most); resistor networks and connectors don't count.",
        "",
        "| Board | Packages | Resistor networks | Other parts | IDC headers |",
        "|---|---:|---:|---|---:|",
        *rows,
        "",
        f"{len(cross)} nets cross between boards. Each pair's signals go into IDC",
        f"headers of {header} pins (2 x {HEADERS[header][1]}), {gnd} ground (wire 1 is a",
        "ground; the clocks have a ground each side):",
        "",
        "| Boards | Signals | Headers |",
        "|---|---:|---|",
        *prow,
        "",
        "A net on all three boards goes top to middle and middle to bottom.",
        "",
        "## Files",
        "",
        "`<board>.json`, one for each board:",
        "",
        "- `board`, `variant` (the parts variant: part numbers), `stack`, `header`, `per ground`;",
        "- `summary`: `packages` (what counts toward the limit), `chips`, `resistor networks`,",
        "  `other parts` (the CF socket), `idc headers`, `sections` (chips per section),",
        "  `signals to` (signals to each other board), `offboard nets`;",
        "- `chips`: `ref`, `type` (infra/hw/chips.py's), `kind` (chip, rn, connector,",
        "  other), `part` (the part number), `section` (a gate package's first gate's; its",
        "  `sections` lists every gate's), `footprint` {`smd`, `dip`: the KiCad footprint",
        "  in each board style} (null where infra/pcb/packages.py has no pinout for the",
        "  type);",
        "- `nets`: net -> [`ref.pin`], logical pins (infra/hw/chips.py's names;",
        "  infra/pcb/packages.py maps them to pads) and the IDC headers' pins",
        "  (`J_cpu2_1.12`: pin 12). The rails are `GND` and `VCC`; a chip's supply",
        "  pins aren't listed (they come with its pinout);",
        "- `connectors`: the IDC headers on this board: `ref` (`J_<other board>_<n>`),",
        "  `to`, `cable` (the same cable at both ends: `cpu1-cpu2/1`), `pins`,",
        "  `footprint`, `pinmap` {pin: net or GND}: pin k is wire k of the ribbon, the",
        "  same at both ends.",
        "",
        "From Python: `heron.studies.mini.boards.netlist(board)` is the board's",
        "`Netlist`, its offboard nets named `BUS.<net>` and its headers on",
        "`nl.connectors` [(ref, footprint, {pin: net})], the way infra/pcb's",
        "`physical.parts()` and `check.compare()` take a card's connectors;",
        "`boards.load(path)` reads a JSON back into one; `boards.pcb_board(board,",
        "style, width, height)` is studies/pcb/cards.py's `board()` for it, so",
        "`heron pcb build mini-cpu1 --size 297x210` runs the PCB flow (it needs",
        "footprints for every type, below).",
        "",
        "## Missing footprints",
        "",
    ]
    if miss:
        lines.append("infra/pcb/packages.py has no pinout or footprint for these types yet:")
        lines.append("")
        for t, refs in sorted(miss.items()):
            lines.append(f"- `{t}`: {', '.join(sorted(refs, key=natural))}"
                         + (f" ({MISSING_NOTES[t]})" if t in MISSING_NOTES else ""))
    else:
        lines.append("None: every type has a pinout and a footprint.")
    lines += [
        "",
        "In the smd style, packages.py's resistor network (`R_Array_Convex_4x0603`,",
        "8 pads) has no pad for a 9-pin network's 8th resistor: check.compare() reports",
        "the nets on P8 of a network that uses it (RN_IOD0, RN_IOD1) as unconnected.",
        "",
        "Also not in the netlist yet, so not on the boards: the UARTs' serial side",
        "(SIN, SOUT, RCLK to BAUDOUT, the modem inputs: the 16C550's pinout names them, no",
        "net reaches them), the expansion ports' connectors, the video connector,",
        "the power input.",
        "",
        "## Timing",
        "",
        "`heron mini hw sta --boards` and the chip-level runs' `--boards` add",
        f"{DELAY_PS / 1000} ns (`--board-delay`) to every output that drives a pin on another",
        "board: the connector, the ribbon and the connector. It delays the",
        "output's loads on its own board too, which is pessimistic for a clean",
        "line and about right for an unterminated one, whose near loads may wait",
        "for the far end's reflection. The clocks are left out (`--board-clocks`",
        "puts them in): a clock sent to each board through a buffer of matched",
        "delay arrives everywhere together. `heron mini boards --sta` lists the",
        "microinstructions that need more ticks.",
        "",
        "## The cut",
        "",
        "Every chip starts on its section's board (boards.SECTIONS), a gate package",
        "on the board most of its gates' sections are on; a k-way Fiduccia-Mattheyses",
        "refinement then moves chips to minimise the wires between boards, keeping",
        f"each board at or below {TARGET} packages, each CPU board at least",
        f"{int(CPU_BALANCE * 100)} % of the CPU's, and the video and I/O sections on io.",
        "",
        "Signals per pair:",
        "",
    ]
    for (x, y), nets in pairs.items():
        lines.append(f"- {x}-{y} ({len(nets)}): " + " ".join(compress(nets)))
    total, split = split_gates(a)
    multi = [s for s in split if len(s[2]) > 1]
    lines += ["", f"Of {total} gate packages, {len(split)} serve more than one section, "
              f"{len(multi)} of them sections mostly on different boards.", ""]
    return "\n".join(lines)


MISSING_NOTES = {
    "cf": "a CompactFlash socket: its footprint depends on the socket chosen",
}


# ---- for the PCB flow ----------------------------------------------------------------------

MOUNTING_HOLE = "MountingHole:MountingHole_3.2mm_M3"
EDGE = 5.0                      # mm: the connectors' and the holes' distance from the edge
CORNER = 12.0                   # mm kept clear of the connectors at each corner (the holes)
GAP = 3.0                       # mm between connectors, and to the parts' region


def pcb_connectors(nl, width, height):
    """The board's IDC headers as parts for infra/pcb: [(Part, {pad:
    net})], fixed, their pin rows along the board's width, in rows: along
    the top edge, along the bottom edge, then rows further in, top and
    bottom by turns (a ribbon reaches a header anywhere on a stacked
    board). A first placement for the PCB study to move."""
    from heron.infra.pcb import board as B
    out = []
    rows = []                       # [edge ("top", "bottom"), y of its edge side, x reached]
    for ref, fp, pinmap in nl.connectors:
        part = B.Part(ref, fp, {}, value=f"IDC {len(pinmap)}", kind="conn")
        part.place(0, 0, 90)
        x0, y0, x1, y1 = part.courtyard()
        w, d = x1 - x0, y1 - y0
        for row in rows:
            start = EDGE + CORNER if row[1] in (EDGE, height - EDGE) else EDGE
            if max(row[2], start) + w <= width - start:
                break
        else:
            k = len(rows)
            edge = ("top", "bottom")[k % 2]
            inset = EDGE + (k // 2) * (d + GAP)
            row = [edge, inset if edge == "top" else height - inset, 0.0]
            if sum(d + GAP for _ in range(k + 1)) > height - 2 * EDGE:
                raise ValueError(f"the IDC headers don't fit on a {width} x {height} board")
            rows.append(row)
        start = EDGE + CORNER if row[1] in (EDGE, height - EDGE) else EDGE
        x = max(row[2], start)
        y = row[1] - y0 if row[0] == "top" else row[1] - y1
        part.place(x - x0, y, 90)
        row[2] = x + w + GAP
        part.edge = row[0]
        part.fixed = True
        out.append((part, dict(pinmap)))
    return out


def pcb_board(name, style="smd", width=297.0, height=210.0, layers=6, rules=None, nl=None):
    """A mini board for studies/pcb's flow, as cards.board() makes a
    card: its parts, the IDC headers placed and fixed, M3 holes in the
    corners for the standoffs, the region left for the parts. Types
    without a footprint (missing_footprints()) raise."""
    from heron.infra.pcb import board as B
    from heron.infra.pcb import physical
    nl = nl or netlist(name)
    miss = sorted({i.type.name for i in nl.instances if kind(i) != "fixture"
                   and None in footprints(i.type.name).values()})
    if miss:
        raise KeyError(f"no footprint in infra/pcb/packages.py for {', '.join(miss)} "
                       f"(on board {name})")
    b = B.Board(f"mini-{name}-{style}", width, height, layers=layers, rules=rules)
    conns = pcb_connectors(nl, width, height)
    for p in physical.parts(nl, style, connectors=conns):
        b.add(p)
    for i, (x, y) in enumerate(((EDGE, EDGE), (width - EDGE, EDGE), (EDGE, height - EDGE),
                                (width - EDGE, height - EDGE))):
        h = B.Part(f"H{i + 1}", MOUNTING_HOLE, {}, value="M3", kind="mech")
        h.place(x, y, 0)
        h.fixed = True
        b.add(h)
    b.pin_maps = [(p.ref, m) for p, m in conns]
    b.netlist = nl
    b.style = style
    # the parts' region: inside the holes, between the headers' rows
    x0, y0, x1, y1 = 2 * EDGE + GAP, 2 * EDGE + GAP, width - 2 * EDGE - GAP, height - 2 * EDGE - GAP
    for p, _ in conns:
        c = p.courtyard()
        if p.edge == "top":
            y0 = max(y0, c[3] + GAP)
        else:
            y1 = min(y1, c[1] - GAP)
    b.region = (x0, y0, x1, y1)
    return b


# ---- the boards' delays ---------------------------------------------------------------------


def match(nl, a=None):
    """{ref: board} for the instances of another netlist of the mini (the
    static timing analysis's, or one built with other options): a chip
    with the same reference, type and connections is where the
    assignment has it; else, as a gate package (whose references depend
    on the order gates were placed) or a fixture standing in for chips,
    where most of the nets it drives are driven from; else, a chip with
    the same reference and type. Instances that match nothing (the rails,
    the test I/O page) are on no board."""
    a = a or default()
    ref_nl = a.nl
    drivers = defaultdict(list)
    for inst in ref_nl.instances:
        if inst.ref not in a.board_of:
            continue
        for pin, net in inst.conn.items():
            if inst.kind(pin) in ("out", "tri", "io"):
                drivers[net].append(inst.ref)
    rail = rails(nl) | rails(ref_nl)
    out = {}
    for inst in nl.instances:
        r = ref_nl.refs.get(inst.ref)
        same = r is not None and r.type.name == inst.type.name and inst.ref in a.board_of
        if same and r.conn == inst.conn:
            out[inst.ref] = a.board_of[inst.ref]
            continue
        votes = Counter()
        for pin, net in inst.conn.items():
            if net in rail or inst.kind(pin) not in ("out", "tri", "io"):
                continue
            for d in drivers.get(net, ()):
                votes[a.board_of[d]] += 1
        if votes:
            out[inst.ref] = max(BOARDS, key=lambda b: (votes[b], -BOARDS.index(b)))
        elif same:
            out[inst.ref] = a.board_of[inst.ref]
    return out


def board_delays(nl, a=None, ps=DELAY_PS, clocks=False):
    """[(ref, pin, ps)]: every output pin of nl that drives a net read on
    another board (by match()), the clocks only with clocks=True."""
    where = match(nl, a)
    rail = rails(nl)
    nets = defaultdict(list)
    for inst in nl.instances:
        for pin, net in inst.conn.items():
            nets[net].append((inst, pin, inst.kind(pin)))
    out = []
    for net, pins in sorted(nets.items()):
        if net in rail or (net in CLOCKS and not clocks):
            continue
        readers = {where[i.ref] for i, p, k in pins if k in ("in", "io") and i.ref in where}
        for inst, pin, k in pins:
            b = where.get(inst.ref)
            if k in ("out", "tri", "io") and b is not None and readers - {b}:
                out.append((inst.ref, pin, ps))
    return out


def add_board_delays(nl, a=None, ps=DELAY_PS, clocks=False):
    """Add board_delays() to nl's instances (Instance.add_pin_delay, which
    infra/hw/sta.py and the chip-level simulator honour). Returns them."""
    d = board_delays(nl, a, ps, clocks)
    for ref, pin, x in d:
        nl.refs[ref].add_pin_delay(pin, x)
    return d


def sta_compare(ps=DELAY_PS, clocks=False, force=False, show=25):
    """The static timing analysis with the boards' delays against the
    plain one (both cached in build/mini): the microinstructions that need
    more ticks, as text."""
    from . import sta, ucode as uc
    plain = sta.analyse(force=force)
    sta.BOARD_DELAYS = board_delays(sta.build(), ps=ps, clocks=clocks)
    try:
        delayed = sta.analyse(force=force)
    finally:
        n_delays = len(sta.BOARD_DELAYS)
        sta.BOARD_DELAYS = None
    mc = uc.built()
    t0, t1 = sta.node_ticks(plain), sta.node_ticks(delayed)
    rows = []
    for n in mc.nodes:
        (T0, k0), (T1, k1) = t0[id(n)], t1[id(n)]
        label = f"{n.name} @{n.addr:04X}" if n.addr is not None else f"{n.name} (entry)"
        rows.append((label, T0, k0, T1, k1))
    worse = [r for r in rows if r[4] != r[2]]
    by = Counter((r[2], r[4]) for r in rows)
    out = [f"static timing analysis with {ps / 1000:.2f} ns on {n_delays} outputs that drive "
           f"another board ({'clocks too' if clocks else 'not the clocks'}), against the plain "
           "analysis (`heron mini hw sta --boards` has the suite's time with the profile):",
           f"  the slowest microinstruction: {max(r[1] for r in rows):.1f} ns plain, "
           f"{max(r[3] for r in rows):.1f} ns with the boards",
           f"  {len(worse)} of {len(rows)} microinstructions need more ticks:"]
    for (k0, k1), c in sorted(by.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        if k0 != k1:
            out.append(f"    {k0} -> {k1} ticks: {c}")
    need0, need1 = Counter(r[2] for r in rows), Counter(r[4] for r in rows)
    out.append("  microinstructions by ticks needed, plain -> with the boards: "
               + ", ".join(f"{k}: {need0[k]} -> {need1[k]}"
                           for k in sorted(set(need0) | set(need1), key=str)))
    if worse:
        out.append("  the most delayed:")
        for label, T0, k0, T1, k1 in sorted(worse, key=lambda r: (-(r[3] - r[1]), r[0]))[:show]:
            out.append(f"    {label:<34} {T0:6.1f} -> {T1:6.1f} ns, {k0} -> {k1} ticks")
    worst = max(delayed, key=lambda r: r[0])
    out.append(f"  the critical check with the boards: {worst[3][0]}: {worst[5]} "
               f"({worst[0]:.1f} ns)")
    return "\n".join(out)


# ---- the command line -------------------------------------------------------------------------


def main(argv=None):
    p = argparse.ArgumentParser(prog="heron mini boards", description=__doc__.split("\n\n")[0])
    p.add_argument("--list", action="store_true", help="every crossing signal, by pair")
    p.add_argument("--header", type=int, choices=sorted(HEADERS), default=HEADER,
                   help="IDC header pins (default %(default)s)")
    p.add_argument("--per-ground", type=int, choices=(1, 2, 3), default=PER_GROUND,
                   help="signals between ground wires (default %(default)s)")
    p.add_argument("--limit", type=int, default=TARGET,
                   help=f"packages a board at most (default %(default)s; {LIMIT} the hard limit)")
    p.add_argument("--write", action="store_true",
                   help="write build/mini/boards/<board>.json and README.md")
    p.add_argument("--sta", action="store_true",
                   help="static timing analysis with the boards' delays against the plain one "
                        "(minutes, then cached)")
    p.add_argument("--board-delay", type=float, default=DELAY_PS / 1000, metavar="NS",
                   help="a crossing's delay (default %(default)s ns)")
    p.add_argument("--clocks", action="store_true", help="delay the clocks too (--sta)")
    args = p.parse_args(argv)
    if args.limit > LIMIT:
        p.error(f"--limit above {LIMIT}")
    a = default() if args.limit == TARGET else assign(target=args.limit)
    print(report(a, args.header, args.per_ground, listing=args.list))
    if args.write:
        for path in write(a, args.header, args.per_ground):
            print(f"wrote {os.path.relpath(path)}")
    if args.sta:
        if args.limit != TARGET:
            print("--sta uses the default assignment", file=sys.stderr)
        print()
        print(sta_compare(round(args.board_delay * 1000), args.clocks))
    return 0
