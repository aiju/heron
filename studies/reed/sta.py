"""Reed's static timing on the engine (infra/sta, RFC 0048): the whole
machine's netlist, the clock generator's 22V10 running its equations on
the master clock, every check the chips' descriptions give.

A case is a kind of microcycle (WORDS): every board's slice of the
microinstruction, at a trial length. The window runs from the master
clock's edge at which a cycle starts (U_CGA at tick 0) to the edge at
which the next one does (CYC0 rises again). The microinstruction
registers take the word at the cycle's start: the control store's
outputs read it before 0, until the µPC's change reaches them; the
registers' outputs are pinned to it. CTRL's sequencer fields, which come
straight from its parts, read the next word, a plain jump.

The boards' clocks all come from the backplane (CYC through each board's
CDC341), so the skew between boards is the backplane's and the CDC341s'.

Left out, and so reported: RESET_n is high, and the WAIT lines low and
IORD_n and IOWR_n high (no I/O access is timed yet: a load or store is
to memory); the VIDEO board runs on its own phase and the
IO board's devices on their accesses, so neither's checks count here.

The wires (wires()): the napkin's 1-12 ns from board to board over the
backplane, 0-1 ns on a board; the clocks the backplane's tree's (bus.tree),
1-2.5 ns on each slot's trace, 0-2 ns from CTRL's sources to the tree. No
load derating: the parts' data has no pin capacitances yet.

  heron reed sta [--word NAME] [--paths N] [--no-wires]
"""

import time
from collections import Counter

from heron.infra.hw import waves

from . import bus as BP, clockcard, fields as F, parts, system

X = waves.X
LENGTH_CHECKS = {"setup", "strobe", "width", "period", "float"}
FIELD_NET = {"MEM": {"MARLD": ["ALE"], "MSZ": ["SZ0", "SZ1"]}, "CTRL": {"LEN": ["LEN0", "LEN1"]}}

# the microcycles: {board: {field: value}}; fields not named are 0, but
# NONE where 0 does something
BASE = {"ALU": {"RAS": F.RAS["NONE"], "RBS": F.RBS["NONE"], "BIN": F.BIN["NONE"]}}
WORDS = {
    "ADD r, r": {"ALU": dict(RAS=F.RAS["d"], RBS=F.RBS["s"], WS=F.WS["d"], AOP=F.AOP["ADD"],
                             CI=F.CI["0"], FL=F.FL["NZCV"], BIN=F.BIN["RF"])},
    "ADD r, #q": {"ALU": dict(RAS=F.RAS["d"], WS=F.WS["d"], AOP=F.AOP["ADD"], CI=F.CI["0"],
                              FL=F.FL["NZCV"], BIN=F.BIN["BUS"]),
                  "CTRL": dict(IMM=F.IMM["Q"])},
    "r + d16 into MAR": {"ALU": dict(RAS=F.RAS["s"], AOP=F.AOP["ADD"], CI=F.CI["0"], BIN=F.BIN["BUS"],
                                     AOUT=F.AOUT["F"]),
                         "CTRL": dict(IMM=F.IMM["PE_SX"]), "MEM": dict(MARLD=1)},
    "r into MAR": {"ALU": dict(RAS=F.RAS["s"], AOUT=F.AOUT["OA"]), "MEM": dict(MARLD=1)},
    "load, pass": {"ALU": dict(WS=F.WS["d"], AOP=F.AOP["PASSB"], BIN=F.BIN["BUS"]),
                   "MEM": dict(MOP=F.MOP["LOAD"], MSZ=F.MSZ["WORD"])},
    "load, add": {"ALU": dict(RAS=F.RAS["d"], WS=F.WS["d"], AOP=F.AOP["ADD"], CI=F.CI["0"],
                              FL=F.FL["NZCV"], BIN=F.BIN["BUS"]),
                  "MEM": dict(MOP=F.MOP["LOAD"], MSZ=F.MSZ["WORD"])},
    "load byte": {"ALU": dict(WS=F.WS["d"], AOP=F.AOP["PASSB"], BIN=F.BIN["BUS"]),
                  "MEM": dict(MOP=F.MOP["LOAD"], MSZ=F.MSZ["BYTE"])},
    "store": {"ALU": dict(RAS=F.RAS["d"], AOUT=F.AOUT["OA"]),
              "MEM": dict(MOP=F.MOP["STORE"], MSZ=F.MSZ["WORD"])},
    "fetch": {"CTRL": dict(BFREE=1)},
    "jump (K onto A, FPC and PC from A)": {"ALU": dict(RAS=F.RAS["K"], K=31, AOUT=F.AOUT["OA"]),
                                           "MEM": dict(MOP=F.MOP["FPC"]),
                                           "CTRL": dict(PCOP=F.PCOP_LOAD)},
    "PC + disp (a branch's target)": {"ALU": dict(AIN=1, WS=F.WS["K"], K=30, AOP=F.AOP["ADD"],
                                                  CI=F.CI["0"], BIN=F.BIN["BUS"]),
                                      "CTRL": dict(IMM=F.IMM["S8X2"], PCOP=F.PCOP_DRIVE)},
    "shift right": {"ALU": dict(RAS=F.RAS["d"], WS=F.WS["d"], AOP=F.AOP["PASSB"], BIN=F.BIN["SHIFT"],
                                SI=F.SI["0"])},
}
# the case's state as it starts: the queue's (a slot free, for a fetch)
START = {
    "CLK.TC0": (X, 0), "CLK.TC1": (X, 0), "CLK.TC2": (X, 0), "CLK.CYC_S": (0, 1),
    "CLK.WPH_S": (1, 0), "CLK.WRS_S": (1, 1), "CLK.WPH0": (1, 0),
}
STROBES = {}
# named exceptions (RFC 0048 8), each counted in the results: none but
# the false path below
EXCEPTIONS = []
# and a false path: LEW (LE's copy) switches the copies' addresses and
# the copies' and Y's enables, only while the latches are closed, so what
# it changes reaches them after they close (or as they open); every check
# but the register file's own (its writes go through LEW) leaves it out
LEW_REASON = ("LEW changes the read latches' inputs only while they are closed: at least 2 ns "
              "after they close (a GAL and an output enable, against their 1.8 ns hold), and as "
              "they open; the engine can't order a change after the enable it follows")


def lew_exceptions(ex):
    return [{"reason": LEW_REASON, "chip": c["ref"], "through": "ALU.LEW"} for c in ex["chips"]
            if not c["ref"].startswith(("ALU.U_RFA", "ALU.U_RFB"))]


# the gated clocks that clear two ticks in (common.gated_clock)
ARMDS = {"IO.ARMD_ALEK"}
ARMS = ["IO.ARM_ALEK", "VIDEO.ARM_VALEK", "VIDEO.ARM_VWK", "VIDEO.ARM_PXCK"]
# the load enables as the case starts: nothing loads at the edge at 0 but
# MAR after a word that loads it (as the gated clocks' ARMs were)
NO_LOAD = {"CTRL.QLD0_n": 1, "CTRL.QLD1_n": 1, "CTRL.HLD_n": 1}


def field_nets(board, name):
    nets = FIELD_NET.get(board, {}).get(name) or F.nets(board, name)
    return [n if n in system.backplane_nets() else f"{board}.{n}" for n in nets]


def word_values(word):
    """{net: bit} of the microinstruction registers' outputs, and {net: bit}
    of the control store's outputs before the cycle (the same word), for a
    word {board: {field: value}}."""
    pins, before = {}, {}
    for board in F.SLICES:
        vals = {**BASE.get(board, {}), **word.get(board, {})}
        for name, w in F.SLICES[board]:
            if board == "CTRL" and name in ("JT", "SEQ", "CND", "LEN", "CSPARE"):
                continue
            v = vals.get(name, 0)
            for i, n in enumerate(field_nets(board, name)):
                pins[n] = (v >> i) & 1
        # the parts' outputs (before the µPC changes): the MIRs' D inputs
        packed = F.pack(board, **{k: v for k, v in vals.items()
                                  if not (board == "CTRL" and k in ("JT", "SEQ", "CND", "LEN", "CSPARE"))})
        start = F.CTRL_REG_BASE if board == "CTRL" else 0
        for b in range(start, 8 * F.PARTS[board]):
            before[f"{board}.cs{board}_{b}"] = (packed >> b) & 1
    # CTRL's sequencer fields: the next word, a plain jump to 0
    for name in ("JT", "SEQ", "CND"):
        for n in field_nets("CTRL", name):
            pins[n] = 0
    return pins, before


def case(name, word, ticks, after_mar=False, wired=True):
    pins, before = word_values(word)
    before.update(STROBES)
    # the cycle's length on the card (LENR, taken as it starts); LEN, the
    # next word's, the same
    ln = ticks - F.LEN_BASE
    pins["LEN0"], pins["LEN1"] = ln & 1, ln >> 1
    start = dict(START)
    if clockcard.HALF_WPH:
        # (WPHD loads on the inverted clock: high from the cycle before)
        del start["CLK.WPH_S"]
        before["CLK.WPHD"] = 1
    else:
        del start["CLK.WPH0"]
    start["CLK.LENR0"], start["CLK.LENR1"] = (X, ln & 1), (X, ln >> 1)
    for a in ARMS:
        start[a] = (0, 0)
        if a.replace("ARM_", "ARMD_") in ARMDS:
            start[a.replace("ARM_", "ARMD_")] = (0, 0)
    before.update(NO_LOAD)
    before["ALE"] = 1 if after_mar else 0
    before["MEM.ALE_n"] = 0 if after_mar else 1
    # the queue: both slots free (so a fetch is wanted), DP at 0
    for i in range(4):
        start[f"CTRL.PV{i}"] = (0, 0)
    skip = [c["ref"] for c in _ex(wired)["chips"] if c["ref"].split(".")[0] in ("VIDEO", "IO")]
    return {"label": f"{name} @{ticks}", "clock": "CLK.MCLK_S", "pins": pins, "before": before,
            "constant": {"RESET_n": 1, "WAIT_IO": 0, "WAIT_V": 0, "IORD_n": 1, "IOWR_n": 1}, "start": start, "skip": skip,
            "branch": ["ALU.WEN"], "exceptions": EXCEPTIONS + lew_exceptions(_ex(wired)), "end": {"net": "CLK.CYC_S", "events": 40}}


# the wires (min, max ps), from a net's drivers to a receiving pin: the
# napkin's (RFC 0049 2.2: 10 ns for the backplane, 2 ns on the receiving
# board), the minimum 0 where the receiving board drives the net too
BACKPLANE = (1000, 12000)
ON_BOARD = (0, 1000)
# the clocks: the tree's trace to each slot, matched; a source's, from
# CTRL to the tree's buffer beside its slot
SLOT_CLOCK = (1000, 2500)
SOURCE = (0, 2000)
DRIVES = ("out", "tri", "io")


def wires(nl):
    """{(ref, pin): (min, max)} for every receiving pin in the machine."""
    bp = system.backplane_nets()
    slots = {BP.slot_clock(c, b) for c in BP.CLOCKS for b in BP.BOARDS}
    sources = set(BP.SOURCES.values())
    out = {}
    for net, conns in nl.nets().items():
        if net in ("GND", "VCC"):
            continue
        conns = [(i, p, k) for i, p, k in conns if i.type.family != "passive"]
        drivers = {i.ref.split(".")[0] for i, p, k in conns if k in DRIVES}
        for i, p, k in conns:
            if k == "out":
                continue
            if net in slots:
                w = SLOT_CLOCK
            elif net in sources:
                w = SOURCE
            elif net in bp:
                w = (0 if i.ref.split(".")[0] in drivers else BACKPLANE[0], BACKPLANE[1])
            else:
                w = ON_BOARD
            out[(i.ref, p)] = w
    return out


_EX = {}


def _ex(wired=True):
    """The machine's export: with the wires, or (wired False) none."""
    if wired not in _EX:
        nl = system.machine(sim=True)
        _EX[wired] = waves.export(nl, parts.VARIANT, wires=wires(nl) if wired else None)
    return _EX[wired]


def failing(branches, kinds=None):
    return [c for b in branches for c in b["worst"] if c["slack"] < 0
            and (kinds is None or c["check"] in kinds)]


def run(names=None, lengths=(5, 6, 7, 8), paths=1, jobs=None, wired=True):
    """{word: (ticks, results at them)}: the shortest length at which
    nothing a length can fix fails worse than at the longest."""
    ex = _ex(wired)
    names = names or list(WORDS)
    items = [(n, t) for n in names for t in lengths]
    cases = [case(n, WORDS[n], t, after_mar=n.startswith(("load", "store")), wired=wired)
             for n, t in items]
    res = waves.analyse(ex, cases, paths=paths, jobs=jobs)
    by = {}
    for (n, t), r in zip(items, res):
        if isinstance(r, dict):
            raise RuntimeError(f"{n} @{t}: {r['error']}")
        if not any(b["checks"] for b in r):
            # the engine times nothing when the clocks' edges can't be told
            # apart (as with the clocks on one shared net over a 1-12 ns wire)
            raise RuntimeError(f"{n} @{t}: the engine timed no checks")
        by[(n, t)] = r
    out = {}
    for n in names:
        longest = {(c["chip"], c["check"], c["what"]): c["slack"] for c in failing(by[(n, lengths[-1])])}
        chosen = lengths[-1]
        for t in lengths:
            worse = [c for c in failing(by[(n, t)], LENGTH_CHECKS)
                     if c["slack"] < longest.get((c["chip"], c["check"], c["what"]), 0)]
            if not worse:
                chosen = t
                break
        out[n] = (chosen, by[(n, chosen)], by[(n, lengths[-1])])
    return out


def report(out, paths=2):
    lines = []
    for n, (t, res, longest) in out.items():
        fails = failing(res)
        kinds = Counter(c["check"] for c in fails)
        lines.append(f"{n:<38} {t} ticks   failing there: "
                     + (", ".join(f"{k} {v}" for k, v in sorted(kinds.items())) or "none"))
        shown = set()
        for c in sorted(fails, key=lambda c: c["slack"]):
            key = (c["chip"].rstrip("0123456789"), c["check"])
            if key in shown or len(shown) >= paths:
                continue
            shown.add(key)
            lines.append(f"    {c['chip']} {c['check']} {c['what']}: {c['slack'] / 1000:.1f} ns")
    return "\n".join(lines)


def main(word=None, paths=2, wired=True):
    t0 = time.time()
    out = run([word] if word else None, wired=wired)
    print(report(out, paths))
    print(f"({time.time() - t0:.0f} s)")
