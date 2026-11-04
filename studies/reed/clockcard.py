"""The clock card: a small card in a slot of its own (the backplane's
middle), with the oscillator, the clock generator and the clock trees.
The backplane stays passive but for routing the card's outputs, a trace
to each slot.

  X_OSC    the master clock (50.35 MHz, a tick 19.86 ns): MCLK_S
  U_CGA    the clock generator (the 22V10's 5 ns grade), counting the
           cycle's ticks: a cycle is 5 + LEN ticks, held at its
           fourth-last tick while a WAIT line is up; CYC_S (ticks 0-1),
           WPH_S (the last three, the write phase) and WRS_S (low for the
           middle of those, the write strobe)
  U_T*     a CDC341 for each of MCLK, CYC, WPH, WRS and WRSE (MEM's strobe,
           half a tick before WRS), an output a slot

LEN comes from CTRL's control store: the next word's, a cycle early, on
two backplane lines, which U_CGA takes as a cycle starts (LENR, the
cycle's own); WAIT_IO and WAIT_V from IO and VIDEO.

CGA_CLOCK chooses what clocks U_CGA: "osc", the oscillator itself, or
"tree", MCLK's tree's own output on the card, as a slot's MCLK is.
"""

from heron.infra.hw import gal as G
from heron.infra.hw.netlist import Netlist

from . import bus as BP, fields as F
from .common import table
from .parts import FAST_GAL

TICK_PS = 19861
CGA_CLOCK = "osc"
# HALF_WPH: WPH rises half a tick late and WRS, the write strobe, is half
# a tick late (U_CGB, on the inverted master clock), so the write phase is
# two and a half ticks and the read half a tick longer
HALF_WPH = True
# LATE_WRS: the register file's strobe half a tick later than MEM's
LATE_WRS = True
LEN = ["LEN0", "LEN1"]


def build(sim=True):
    nl = Netlist()
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")
    if sim:
        nl.add("osc", "X_OSC", OUT="MCLK_S", params={"period_ps": TICK_PS, "phase_ps": 5000})
    sources = {c: f"{c}_S" for c in BP.CLOCKS}
    if not HALF_WPH:
        sources["WRSE"] = "WRS_S"
    elif not LATE_WRS:
        sources["WRS"] = "WRSE_S"
    for c in BP.CLOCKS:
        nl.add("clkdrv", f"U_T{c}", A=sources[c],
               **{f"Y{i + 1}": BP.slot_clock(c, b) for i, b in enumerate(BP.BOARDS)},
               **({"Y6": "MCLK_CARD"} if c == "MCLK" else {"Y6": f"T{c}_NC6"}),
               **{f"Y{i}": f"T{c}_NC{i}" for i in range(7, 9)})
    tc = ["TC0", "TC1", "TC2"]
    lenr = ["LENR0", "LENR1"]
    ins = tc + lenr + ["WAIT_IO", "WAIT_V"]

    def nxt(t0, t1, t2, l0, l1, w0, w1):
        t, n = t0 | t1 << 1 | t2 << 2, F.LEN_BASE + (l0 | l1 << 1)
        if t >= n - 1:
            return 0
        if (w0 or w1) and t == n - 4:
            return t
        return t + 1

    def cyc_len(t0, t1, t2, l0, l1, w0, w1):
        return F.LEN_BASE + (l0 | l1 << 1)

    outs = {}
    # the cycle's length: LEN as the cycle starts, else held
    start = table(ins, lambda *b: int(nxt(*b) == 0))
    for i in range(2):
        outs[lenr[i]] = ([{**t, LEN[i]: 1} for t in start]
                         + [{**t, lenr[i]: 1} for t in table(ins, lambda *b: int(nxt(*b) != 0))],
                         True, False)
    for i in range(3):
        outs[f"TC{i}"] = (table(ins, lambda *b, i=i: (nxt(*b) >> i) & 1), True, False)
    outs["CYC_S"] = (table(ins, lambda *b: nxt(*b) in (0, 1)), True, False)
    wph = "WPH0" if HALF_WPH else "WPH_S"
    outs[wph] = (table(ins, lambda *b: nxt(*b) >= cyc_len(*b) - 3), True, False)
    # (WRSE_S, the strobe where U_CGA makes it, is MEM's: its data comes
    # over A, which the next cycle's word may drive)
    wrs = "WRSE_S" if HALF_WPH else "WRS_S"
    outs[wrs] = (table(ins, lambda *b: nxt(*b) == cyc_len(*b) - 2), True, True)
    clock = "MCLK_S" if CGA_CLOCK == "osc" else "MCLK_CARD"
    G.add(nl, "U_CGA", outs, clock=clock).part = FAST_GAL
    if HALF_WPH:
        # WPHD: WPH0 half a tick later; WPH_S rises with it and falls with
        # WPH0, at the cycle's end; WRS_S, the strobe, all of it half a tick
        # later (so that it starts a tick after the write phase does, and
        # ends just after the cycle: the address and the data stay until
        # the next cycle's LEW)
        nl.add("04", "U_INV", **{"1A": clock, "1Y": "MCLKN_C", **{f"{i}A": "GND" for i in range(2, 7)}})
        G.add(nl, "U_CGB", {"WPHD": ([{"WPH0": 1}], True, False),
                            "WPH_S": ([{"WPH0": 1, "WPHD": 1}], False, False),
                            **({"WRS_S": ([{"WRSE_S": 1}], True, False)} if LATE_WRS else {})},
              clock="MCLKN_C").part = FAST_GAL

    nl.finish()
    return nl
