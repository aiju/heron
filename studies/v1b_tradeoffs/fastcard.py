"""The CPU card with a clock generator for fast parts (74F/74ABT logic,
12 ns memories; parts.py).

v1b_system's card (studies/v1b_system/cpucard.py) was built for 74HCT:
its write window opens 10 ticks into the cycle and a bus access holds at
count 9, so no cycle can be shorter than 13 ticks (260 ns), whatever the
parts. With fast parts most microinstructions need 4-6 ticks. This card
keeps everything else (the CPU in card mode, the length class ROM and its
jumpers, the bus interface: cpucard.bus_interface) and has a clock
generator for short cycles:

  - a cycle is K ticks of 20 ns: two head ticks H0, H1 (the counter is
    cleared to 0 and 1), then the count from P = 19 - K to 15, then one
    tail tick T1. CLK is high for H0 and H1. K is 4 to 19.
  - the write window opens entering tick 2 and closes entering the tail.
    It is MID and not TAILX: MID rises entering tick 2 and falls entering
    H0; TAILX rises entering T1, set straight from the counter's carry
    (74ACT163 CLK->RCO is 15.2 ns, so there's no time for an inverter),
    and falls entering H1. They never change at the same edge, so the
    window can't glitch. MID also says when the bus read latch may drive
    the data bus, as on v1b_system's card.
  - a bus access holds the count from tick 3 until its transfer is done.
    BUSACC (decoded from the MAR and the microinstruction) settles about
    32 ns after the CPU clock, too late for the edge entering tick 2. The
    counter's carry is masked while it holds (ENT), so the count, at most
    P + 1 = 14 (a bus access needs at least K_BUS = 6 ticks), never ends
    the cycle early.
  - a request crosses to the bus side and back at fixed bus clock phases,
    as on v1b_system's card. Since a cycle can now end a few ticks after
    the transfer, the next access may start before the last handshake is
    over: its request (BRQ) only rises once the done signal (DONEM) has
    fallen, and its hold ends when DONEM and BRQ are both high.
"""

from heron.studies.v1b_hw import cpu
from heron.studies.v1b_hw import ucode as uc
from heron.studies.v1b_system import bus, cpucard

from . import parts

F, ABT = "74F", "74ABT"
TICK_PS = 20_000
HEAD, TAIL = 2, 1
WINDOW_OPEN = 2
K_BUS = 6
K_MIN = WINDOW_OPEN + TAIL + 1
K_MAX = HEAD + TAIL + 16


def preload(k):
    """The counter's preload for a cycle of k ticks."""
    p = HEAD + 16 + TAIL - k
    if not 0 <= p <= 15:
        raise ValueError(f"a cycle of {k} ticks is out of range ({K_MIN}..{K_MAX})")
    return p


def build(lengths=(6, 6, 6, 6), bus_div=3):
    """The card: `lengths` are the jumpers, the ticks of length classes 0-3."""
    if bus_div not in (3, 4):
        raise ValueError("the bus clock is MCLK / 3 or / 4")
    nl = cpu.build(card=True)
    g = nl.gate
    U = cpu.control_nets()
    u = {v[1:]: v for v in U.values()}

    def gf(typ, ins, out):
        return g(typ, ins, out, part=F + typ)

    nl.section("Reset")
    g("14", ["BUS.RESET_n"], "RSTI", part="74HCT14")
    g("14", ["RSTI"], "RESET_n", part="74HCT14")

    nl.section("Clock generator")
    nl.add("osc", "U_OSC", part="oscillator 50 MHz", OUT="MCLK",
           params={"period_ps": TICK_PS, "phase_ps": TICK_PS})
    # the bus clock: a one-hot ring, as on v1b_system's card
    P = ["PH0", "BUS.CLKSRC"] + [f"PH{i}" for i in range(2, bus_div)]
    gf("02" if bus_div == 3 else "27", P[:bus_div - 1], "PH0_D")
    ph = nl.add("175", "U_PH", part=F + "175", CLK="MCLK", CLR="VCC",
                **{"1D": "PH0_D", "1Q": "PH0", "1QN": "PH0_n"})
    for i in range(1, 4):
        if i < bus_div:
            ph[f"{i + 1}D"], ph[f"{i + 1}Q"] = P[i - 1], P[i]
        else:
            ph[f"{i + 1}D"] = "GND"

    nl.section("Length class")
    rom = nl.add("flash", "U_UC15", CE="GND", OE="GND", WE="VCC")
    upper = {uc.IRQP_BIT: "IRQP", uc.FAULT_BIT: "FAULT", uc.FAULT_BIT + 1: "FLEN0",
             uc.FAULT_BIT + 2: "FLEN1"}
    for i in range(17):
        rom[f"A{i}"] = f"Y{i}" if i < uc.Y_BITS else upper.get(i, "GND")
    for i in range(8):
        rom[f"D{i}"] = f"UD{120 + i}"
    nl.add("377", "U_UIR15", part=ABT + "377", CLK="CLK", EN="GND",
           **{f"D{i + 1}": f"UD{120 + i}" for i in range(8)}, Q1="LCL0", Q2="LCL1")
    pre = [preload(k) for k in lengths]
    for k in range(2):
        m = nl.add("153", f"U_LM{k}", part=F + "153", A="LCL0", B="LCL1",
                   **{"1G": "GND", "2G": "GND"})
        for sec in (0, 1):
            bit = 2 * k + sec
            for c in range(4):
                m[f"{sec + 1}C{c}"] = "VCC" if (pre[c] >> bit) & 1 else "GND"
            m[f"{sec + 1}Y"] = f"PSEL{bit}"

    nl.section("Clock generator")
    nl.add("163", "U_TC", part="74ACT163", CLK="MCLK", CLR="T1_n", LOAD="H1_n", ENP="HOLD_n",
           ENT="HOLD_n", A="PSEL0", B="PSEL1", C="PSEL2", D="PSEL3",
           QA="TC0", QB="TC1", QC="TC2", QD="TC3", RCO="TCRCO")
    nl.add("175", "U_TH", part=F + "175", CLK="MCLK", CLR="VCC",
           **{"1D": "TCRCO", "1Q": "T1", "1QN": "T1_n",
              "2D": "T1", "2Q": "H0", "2QN": "H0_n",
              "3D": "H0", "3Q": "H1", "3QN": "H1_n",
              "4D": "CLK_D", "4Q": "CLK"})
    gf("32", ["T1", "H0"], "CLK_D")
    nl.add("109", "U_WIN", part=F + "109",
           **{"1J": "H1", "1K": "T1_n", "1CLK": "MCLK", "1PRE": "VCC", "1CLR": "VCC",
              "1Q": "MID",
              "2J": "TCRCO", "2K": "H0_n", "2CLK": "MCLK", "2PRE": "VCC", "2CLR": "VCC",
              "2QN": "TAILX_n"})
    gf("08", ["MID", "TAILX_n"], "WEWIN0")

    nl.section("Bus hold and crossings")
    gf("08", ["H2", "BUSACC"], "HOLD_J")
    gf("00", ["DONEM", "BRQ"], "HOLD_K")
    gf("11", ["HOLD", "BUS.CLKSRC", "DONEM_n"], "BRQ_J")
    gf("00", ["HOLD_n", "BUS.CLKSRC"], "BRQ_K")
    gf("08", ["DQB", "PH0"], "DONEM_J")
    gf("00", ["DQB_n", "PH0"], "DONEM_K")
    nl.add("109", "U_HOLD", part=F + "109",
           **{"1J": "HOLD_J", "1K": "HOLD_K", "1CLK": "MCLK", "1PRE": "VCC", "1CLR": "RESET_n",
              "1Q": "HOLD", "1QN": "HOLD_n",
              "2J": "BRQ_J", "2K": "BRQ_K", "2CLK": "MCLK", "2PRE": "VCC", "2CLR": "RESET_n",
              "2Q": "BRQ", "2QN": "BRQ_n"})
    # DONEM; and H2, H1 a tick later (J = K-bar = H1)
    nl.add("109", "U_DONE", part=F + "109",
           **{"1J": "DONEM_J", "1K": "DONEM_K", "1CLK": "MCLK", "1PRE": "VCC", "1CLR": "RESET_n",
              "1Q": "DONEM", "1QN": "DONEM_n",
              "2J": "H1", "2K": "H1", "2CLK": "MCLK", "2PRE": "VCC", "2CLR": "VCC",
              "2Q": "H2"})

    cpucard.bus_interface(nl, u, slow=parts.FAST_LOGIC)
    nl.finish()
    return bus.Card("CPU", nl)
