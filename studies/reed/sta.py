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

  heron reed sta [--word NAME] [--paths N]
"""

import time
from collections import Counter

from heron.infra.hw import waves

from . import fields as F, parts, system

X = waves.X
LENGTH_CHECKS = {"setup", "strobe", "width", "period", "float"}
FIELD_NET = {"MEM": {"MARLD": ["ALE"], "MSZ": ["SZ0", "SZ1"]}}

# the microcycles: {board: {field: value}}; fields not named are 0, but
# NONE where 0 does something
BASE = {"ALU": {"RAS": F.RAS["NONE"], "RBS": F.RBS["NONE"], "BIN": F.BIN["NONE"]}}
WORDS = {
    "ADD r, r": {"ALU": dict(RAS=F.RAS["d"], RBS=F.RBS["s"], WS=F.WS["d"], AOP=F.AOP["ROW"],
                             CI=F.CI["ROW"], FL=F.FL["ROW"], BIN=F.BIN["RF"])},
    "ADD r, #q": {"ALU": dict(RAS=F.RAS["d"], WS=F.WS["d"], AOP=F.AOP["ROW"], CI=F.CI["ROW"],
                              FL=F.FL["ROW"], BIN=F.BIN["BUS"]),
                  "CTRL": dict(IMM=F.IMM["Q"])},
    "r + d16 into MAR": {"ALU": dict(RAS=F.RAS["s"], AOP=F.AOP["ADD"], CI=F.CI["0"], BIN=F.BIN["BUS"],
                                     AOUT=F.AOUT["F"]),
                         "CTRL": dict(IMM=F.IMM["PE_SX"]), "MEM": dict(MARLD=1)},
    "r into MAR": {"ALU": dict(RAS=F.RAS["s"], AOUT=F.AOUT["OA"]), "MEM": dict(MARLD=1)},
    "load, pass": {"ALU": dict(WS=F.WS["d"], AOP=F.AOP["PASSB"], BIN=F.BIN["BUS"]),
                   "MEM": dict(MOP=F.MOP["LOAD"], MSZ=F.MSZ["WORD"])},
    "load, add": {"ALU": dict(RAS=F.RAS["d"], WS=F.WS["d"], AOP=F.AOP["ROW"], CI=F.CI["ROW"],
                              FL=F.FL["ROW"], BIN=F.BIN["BUS"]),
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
    "CTRL.TC0": (X, 0), "CTRL.TC1": (X, 0), "CTRL.TC2": (X, 0), "CTRL.CYC0": (0, 1),
    "CTRL.WPH0": (1, 0), "CTRL.WRS0": (1, 1),
}
STROBES = {}
# named exceptions (RFC 0048 8), each counted in the results
EXCEPTIONS = [
    {"reason": "the read latches' inputs change only after LE closes them (the copies' addresses "
               "and the copies' and Y's enables take LE): at least 2 ns, a GAL and an output "
               "enable, against the latch's 1.8 ns hold; the engine can't order a change after "
               "the enable it follows",
     "chip": f"ALU.U_L{c}{k}", "check": "hold"} for c in "AB" for k in range(4)]
ARMS = ["CTRL.ARM_QCK0", "CTRL.ARM_QCK1", "CTRL.ARM_HCK", "MEM.ARM_MARCK", "IO.ARM_ALEK",
        "VIDEO.ARM_VALEK", "VIDEO.ARM_VWK", "VIDEO.ARM_PXCK"]


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
            if board == "CTRL" and name in ("JT", "SEQ", "CND", "CSPARE"):
                continue
            v = vals.get(name, 0)
            for i, n in enumerate(field_nets(board, name)):
                pins[n] = (v >> i) & 1
        # the parts' outputs (before the µPC changes): the MIRs' D inputs
        packed = F.pack(board, **{k: v for k, v in vals.items()
                                  if not (board == "CTRL" and k in ("JT", "SEQ", "CND", "CSPARE"))})
        start = F.CTRL_REG_BASE if board == "CTRL" else 0
        for b in range(start, 8 * F.PARTS[board]):
            before[f"{board}.cs{board}_{b}"] = (packed >> b) & 1
    # CTRL's sequencer fields: the next word, a plain jump to 0
    for name in ("JT", "SEQ", "CND"):
        for n in field_nets("CTRL", name):
            pins[n] = 0
    return pins, before


def case(name, word, ticks, after_mar=False):
    pins, before = word_values(word)
    before.update(STROBES)
    pins["CTRL.uLEN0"], pins["CTRL.uLEN1"] = (ticks - F.LEN_BASE) & 1, (ticks - F.LEN_BASE) >> 1
    start = dict(START)
    for a in ARMS:
        start[a] = (0, 0)
    if after_mar:
        start["MEM.ARM_MARCK"] = (1, 1)
    # the queue: both slots free (so a fetch is wanted), DP at 0
    for i in range(4):
        start[f"CTRL.PV{i}"] = (0, 0)
    skip = [c["ref"] for c in _ex()["chips"] if c["ref"].split(".")[0] in ("VIDEO", "IO")]
    return {"label": f"{name} @{ticks}", "clock": "CTRL.MCLK0", "pins": pins, "before": before,
            "constant": {"RESET_n": 1, "WAIT_IO": 0, "WAIT_V": 0, "IORD_n": 1, "IOWR_n": 1}, "start": start, "skip": skip,
            "branch": [], "exceptions": EXCEPTIONS, "end": {"net": "CTRL.CYC0", "events": 40}}


_EX = {}


def _ex():
    if "ex" not in _EX:
        nl = system.machine(sim=True)
        _EX["ex"] = waves.export(nl, parts.VARIANT)
    return _EX["ex"]


def failing(branches, kinds=None):
    return [c for b in branches for c in b["worst"] if c["slack"] < 0
            and (kinds is None or c["check"] in kinds)]


def run(names=None, lengths=(5, 6, 7, 8), paths=1, jobs=None):
    """{word: (ticks, results at them)}: the shortest length at which
    nothing a length can fix fails worse than at the longest."""
    ex = _ex()
    names = names or list(WORDS)
    items = [(n, t) for n in names for t in lengths]
    cases = [case(n, WORDS[n], t, after_mar=n.startswith(("load", "store"))) for n, t in items]
    res = waves.analyse(ex, cases, paths=paths, jobs=jobs)
    by = {}
    for (n, t), r in zip(items, res):
        if isinstance(r, dict):
            raise RuntimeError(f"{n} @{t}: {r['error']}")
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


def main(word=None, paths=2):
    t0 = time.time()
    out = run([word] if word else None)
    print(report(out, paths))
    print(f"({time.time() - t0:.0f} s)")
