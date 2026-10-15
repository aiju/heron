"""The CPU card: the draft 1b CPU (studies/v1b_hw, its card mode) on the
system bus, with its own 50 MHz clock generator and variable-length
cycles. See design.md for the design and its timing.

Three clock domains, all from one 50 MHz oscillator (MCLK):
  - the clock generator, on MCLK: a cycle is a whole number of 20 ns
    ticks, set per microinstruction by its length class (a 16th microcode
    ROM) and the jumpers that map each class to a count;
  - the CPU, on CLK, which the clock generator makes;
  - the bus interface, on the bus clock. The card divides MCLK by 3 (or
    4) and sends it to the backplane on CLKSRC; like every card it then
    clocks its bus logic from its own BCLK pin, through one buffer.
A bus access is one microcycle, held at a fixed point near its end until
the bus transfer is over. The domains only exchange signals at MCLK edges
a fixed number of ticks after the bus clock's source edge, so the
crossings need no synchronisers.
"""

from heron.studies.v1b_hw import cpu

from . import bus

F, ABT, HCT = "74F", "74ABT", "74HCT"
TICK_PS = 20_000

# the counter's preload for a cycle of K ticks: 4 head ticks (counting 0-3),
# then P..15, then two tail ticks
HEAD, TAIL = 4, 2
# the write window opens this many ticks after the edge, and closes two
# before the next
WINDOW_OPEN = 10


def preload(k):
    p = HEAD + 16 + TAIL - k
    if not 0 <= p <= 15:
        raise ValueError(f"a cycle of {k} ticks is out of range "
                         f"({HEAD + TAIL + 1}..{HEAD + TAIL + 16})")
    return p


def build(lengths=(17, 17, 17, 17), bus_div=3):
    """The CPU card. `lengths` are the jumpers: ticks for length classes
    0-3; `bus_div` the bus clock as a fraction of MCLK (3: 60 ns)."""
    if bus_div not in (3, 4):
        raise ValueError("the bus clock is MCLK / 3 or / 4")
    nl = cpu.build(card=True)
    g = nl.gate
    U = cpu.control_nets()
    u = {v[1:]: v for v in U.values()}

    def gf(typ, ins, out):
        return g(typ, ins, out, part=F + typ)

    nl.section("Reset")
    # ---- reset from the bus, through a Schmitt trigger ------------------------
    g("14", ["BUS.RESET_n"], "RSTI", part=HCT + "14")
    g("14", ["RSTI"], "RESET_n", part=HCT + "14")

    nl.section("Clock generator")
    # ---- the clock generator ---------------------------------------------------
    nl.add("osc", "U_OSC", part="oscillator 50 MHz", OUT="MCLK",
           params={"period_ps": TICK_PS, "phase_ps": TICK_PS})
    # the bus clock: a one-hot ring P0..P(n-1), self-starting; the bus
    # clock's source edge is P1 rising
    P = ["PH0", "BUS.CLKSRC"] + [f"PH{i}" for i in range(2, bus_div)]
    if bus_div == 3:
        gf("02", P[:2], "PH0_D")
    else:
        gf("27", P[:3], "PH0_D")
    ph = nl.add("175", "U_PH", part=F + "175", CLK="MCLK", CLR="VCC",
                **{"1D": "PH0_D", "1Q": "PH0", "1QN": "PH0_n"})
    for i in range(1, 4):
        if i < bus_div:
            ph[f"{i + 1}D"], ph[f"{i + 1}Q"] = P[i - 1], P[i]
        else:
            ph[f"{i + 1}D"] = "GND"

    nl.section("Length class")
    # the length class (the 16th microcode ROM) picks the counter's preload
    rom = nl.add("flash", "U_UC15", CE="GND", OE="GND", WE="VCC")
    from heron.studies.v1b_hw import ucode as uc
    upper = {uc.IRQP_BIT: "IRQP", uc.FAULT_BIT: "FAULT", uc.FAULT_BIT + 1: "FLEN0",
             uc.FAULT_BIT + 2: "FLEN1"}
    for i in range(17):
        rom[f"A{i}"] = f"Y{i}" if i < uc.Y_BITS else upper.get(i, "GND")
    for i in range(8):
        rom[f"D{i}"] = f"UD{120 + i}"
    r = nl.add("377", "U_UIR15", CLK="CLK", EN="GND",
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
    # the tick counter (74ACT163: the 74F163's 11.5 ns setups don't fit a
    # 20 ns tick): cleared at the cycle's edge, counts 0-3 (the head),
    # loads P, counts to 15, then two tail ticks T1, T2. Every path in this
    # domain is a flip-flop, at most one 74F gate, and a flip-flop.
    nl.add("163", "U_TC", part="74ACT163", CLK="MCLK", CLR="T2_n", LOAD="H3_n", ENP="HOLD_n",
           ENT="VCC", A="PSEL0", B="PSEL1", C="PSEL2", D="PSEL3",
           QA="TC0", QB="TC1", QC="TC2", QD="TC3", RCO="TCRCO")
    # T1, T2: the tail; H0-H9: ticks 0-9 from the cycle's edge
    H = [f"H{i}" for i in range(WINDOW_OPEN)]
    chain = ["T1", "T2"] + H
    for k in range((len(chain) + 1) // 4 + 1):
        r = nl.add("175", f"U_TH{k}", part=F + "175", CLK="MCLK", CLR="VCC")
        for i in range(4):
            j = 4 * k + i
            if j < len(chain):
                r[f"{i + 1}D"] = "TCRCO" if j == 0 else chain[j - 1]
                r[f"{i + 1}Q"] = chain[j]
            elif j == len(chain):
                r[f"{i + 1}D"], r[f"{i + 1}Q"] = "CLK_D", "CLK"
            elif j == len(chain) + 1:
                r[f"{i + 1}D"], r[f"{i + 1}Q"] = "TC3", "Q3R"
            else:
                r[f"{i + 1}D"] = "GND"
            if chain[j:j + 1] in (["T2"], ["H3"]):
                r[f"{i + 1}QN"] = chain[j] + "_n"
    gf("32", ["T2", "H0"], "CLK_D")    # the CPU clock: high for the first two ticks
    # the write window: open from tick 10 (LATE, set by H9) until the tail
    # (TAIL, set by the count's end, holds through T1 and T2); LATE drops
    # entering T2 and TAIL entering tick 0, so they never change together
    # and WEWIN0 can't glitch
    nl.add("109", "U_WIN", part=F + "109",
           **{"1J": H[-1], "1K": "TAIL_n", "1CLK": "MCLK", "1PRE": "VCC", "1CLR": "VCC",
              "1Q": "LATE",
              "2J": "TCRCO", "2K": "T2_n", "2CLK": "MCLK", "2PRE": "VCC", "2CLR": "VCC",
              "2QN": "TAIL_n"})
    gf("08", ["LATE", "TAIL_n"], "WEWIN0")
    nl.section("Bus hold and crossings")
    # a bus access: hold the count a tick after bit 3 of the count is seen
    # (Q3R: from count 9, or from tick 5 for a short class) until the
    # transfer is done; that leaves at least 6 ticks after it (the class of
    # a bus access keeps P at most 10). Meanwhile the request crosses to
    # the bus side at the edge entering P2 (the tick after CLKSRC rises),
    # and the answer comes back at the edge entering P1 (CLKSRC's next
    # rising edge): the bus side's flip-flops change about 33 ns after
    # CLKSRC rises (the backplane's clock driver, the line, the card's
    # buffer), so earlier edges would catch them changing.
    gf("11", ["Q3R", "BUSACC", "DONEM_n"], "HOLD_J")
    gf("08", ["HOLD", "BUS.CLKSRC"], "BRQ_J")
    gf("00", ["HOLD_n", "BUS.CLKSRC"], "BRQ_K")
    gf("08", ["DQB", "PH0"], "DONEM_J")
    gf("00", ["DQB_n", "PH0"], "DONEM_K")
    nl.add("109", "U_HOLD", part=F + "109",
           **{"1J": "HOLD_J", "1K": "DONEM_n", "1CLK": "MCLK", "1PRE": "VCC", "1CLR": "RESET_n",
              "1Q": "HOLD", "1QN": "HOLD_n",
              "2J": "BRQ_J", "2K": "BRQ_K", "2CLK": "MCLK", "2PRE": "VCC", "2CLR": "RESET_n",
              "2Q": "BRQ", "2QN": "BRQ_n"})
    # MID: from tick 4 to the cycle's edge. The bus read latch drives the
    # data bus only then, once the RAM has let go of it
    nl.add("109", "U_DONE", part=F + "109",
           **{"1J": "DONEM_J", "1K": "DONEM_K", "1CLK": "MCLK", "1PRE": "VCC", "1CLR": "RESET_n",
              "1Q": "DONEM", "1QN": "DONEM_n",
              "2J": "H3", "2K": "T2_n", "2CLK": "MCLK", "2PRE": "VCC", "2CLR": "VCC",
              "2Q": "MID"})

    nl.section("Bus access decode")
    # ---- which accesses go on the bus (CPU side, fast parts: the clock
    # generator reads BUSACC at least 5 ticks, 100 ns, into the cycle) ------
    gf("08", [u["SIZE0"], "MAR1"], "MISF1")
    gf("32", ["MAR0", "MISF1"], "MISF2")
    gf("00", [u["SIZE1"], "MISF2"], "MISF_n")             # not misaligned
    g("04", [u["MEMWR"]], "MEMWR_n", part=HCT + "04")
    gf("00", [u["MEMRD_n"], "MEMWR_n"], "MEMACC")
    gf("21", ["MEMACC", u["ADDRMAR"], "MARBUS", "MISF_n"], "BUSACC")
    g("08", ["BUSACC", "EQ"], "BUSERR", part=HCT + "08")   # into FAULT (cpu.py)
    gf("20", ["BUSACC", "MEMWR_n", "MID", "VCC"], "BUSRD_n")

    nl.section("Bus interface: state")
    # ---- the bus interface (bus clock) ------------------------------------------
    nl.add("clkdrv", "U_KBCK", part="CDC341", A="BUS.BCLK", Y1="BCK")
    nl.add("541", "U_KBI", part=ABT + "541", OE1="GND", OE2="GND",
           A1="BUS.GNT_n", A2="BUS.DPH_n", A3="BUS.RDY_n", A4="BUS.WAIT_n", A5="BUS.BERR_n",
           A6="BUS.IRQ0_n", A7="BUS.IRQ1_n", A8="BUS.IRQ2_n",
           Y1="GNTB_n", Y2="DPHB_n", Y3="RDYB_n", Y4="WAITB_n", Y5="BERRB_n",
           Y6="IRQB0_n", Y7="IRQB1_n", Y8="IRQB2_n")
    nl.add("540", "U_KBJ", part=ABT + "540", OE1="GND", OE2="GND",
           A1="BUS.GNT_n", A2="BUS.DPH_n", A3="BUS.RDY_n", A4="BUS.WAIT_n", A5="BUS.BERR_n",
           A6="GND", A7="GND", A8="GND",
           Y1="GNTP", Y2="DPHP", Y3="RDYP", Y4="WAITP", Y5="BERRP")
    # state: AQ address clock, BQ our transfer under way, OQ we drive the
    # owner's lines, WQ we drive write data, DQB done, EQ it ended with
    # BERR, E1Q/E2Q a bus error's delay before done, RQ the request
    gf("08", ["BQ", "AQ_n"], "BD")                        # our data/recovery clocks
    # start an address clock: granted, asked, not done, and no transfer
    # under way or bus error waiting to become done
    gf("11", ["BQ_n", "E1Q_n", "E2Q_n"], "FREE")
    gf("20", ["GNTP", "BRQ", "DQB_n", "FREE"], "STN_n")
    gf("21", ["GNTP", "BRQ", "DQB_n", "FREE"], "STN")
    gf("20", ["BD", "RDYB_n", "BERRB_n"], "KT1_n")        # not ready yet: carry on
    gf("20", ["BD", "WAITP", "BERRB_n"], "KT2_n")         # WAIT: carry on
    gf("20", ["KT1_n", "KT2_n", "AQ_n", "STN_n"], "BQ_D")
    gf("20", ["GNTB_n", "AQ_n", "KT1_n", "KT2_n"], "OQ_D")
    gf("20", ["WQ", "RDYB_n", "BERRB_n"], "WK1_n")
    gf("20", ["WQ", "WAITP", "BERRB_n"], "WK2_n")
    gf("00", ["AQ", u["MEMWR"]], "WST_n")
    gf("20", ["WK1_n", "WK2_n", "WST_n"], "WQ_D")
    gf("20", ["BD", "RDYP", "WAITB_n", "BERRB_n"], "OK_n")   # ended well
    gf("00", ["DQB", "BRQ"], "DK_n")
    gf("20", ["OK_n", "DK_n", "E2Q_n"], "DQB_D")
    gf("00", ["BD", "BERRP"], "BE_n")                     # ended with BERR
    gf("00", ["EQ", "STN_n"], "EK_n")
    gf("00", ["BE_n", "EK_n"], "EQ_D")
    gf("04", ["BE_n"], "E1Q_D")
    gf("08", ["BRQ", "DQB_n"], "REQQ_D")
    nl.add("175", "U_KFS0", part=F + "175", CLK="BCK", CLR="RESET_n",
           **{"1D": "STN", "1Q": "AQ", "1QN": "AQ_n", "2D": "BQ_D", "2Q": "BQ", "2QN": "BQ_n",
              "3D": "OQ_D", "3Q": "OQ", "3QN": "OQ_n", "4D": "WQ_D", "4Q": "WQ", "4QN": "WQ_n"})
    nl.add("175", "U_KFS1", part=F + "175", CLK="BCK", CLR="RESET_n",
           **{"1D": "DQB_D", "1Q": "DQB", "1QN": "DQB_n", "2D": "EQ_D", "2Q": "EQ",
              "3D": "E1Q_D", "3Q": "E1Q", "3QN": "E1Q_n", "4D": "E1Q", "4QN": "E2Q_n"})
    nl.add("74", "U_KFS2", part=F + "74",
           **{"1D": "REQQ_D", "1CLK": "BCK", "1PRE": "VCC", "1CLR": "RESET_n", "1QN": "REQQ_n",
              "2D": "GND", "2CLK": "GND", "2PRE": "VCC", "2CLR": "VCC"})
    nl.section("Bus interface: address")
    # the owner's lines: START, LOCK (never used), and REQ
    nl.add("125", "U_KBO", part=ABT + "125",
           **{"1OE": "OQ_n", "1A": "AQ_n", "1Y": "BUS.START_n",
              "2OE": "OQ_n", "2A": "VCC", "2Y": "BUS.LOCK_n",
              "3OE": "GND", "3A": "REQQ_n", "3Y": "BUS.REQ_n",
              "4OE": "VCC", "4A": "GND"})
    # address, byte enables and WRITE, registered in the address clock
    g("08", ["BYTE", "ADDR0"], "BE0D_n", part=HCT + "08")
    g("08", ["BYTE", "ADDR0_n"], "BE1D_n", part=HCT + "08")
    src = [("MAR1H", "BUS.A1")] + [(f"MAR{i}", f"BUS.A{i}") for i in range(2, 32)] \
        + [("BE0D_n", "BUS.BE0_n"), ("BE1D_n", "BUS.BE1_n"), ("MEMWR_n", "BUS.WRITE_n")]
    for k in range(4):
        rg = nl.add("823", f"U_KBA{k}", part=ABT + "823", CLK="BCK", EN="STN_n", CLR="VCC",
                    OE="OQ_n")
        for i in range(9):
            j = 9 * k + i
            if j < len(src):
                rg[f"D{i + 1}"], rg[f"Q{i + 1}"] = src[j]
            else:
                rg[f"D{i + 1}"] = "GND"
    nl.section("Bus interface: data")
    # data: D0-D15 <-> BD through the transceivers; writes from DBUS, reads
    # registered at the end of each clock with DPH and not WAIT
    gf("20", ["BD", "MEMWR_n", "DPHP", "WAITB_n"], "RLE_n")
    for k in range(2):
        x = nl.add("245", f"U_KBX{k}", part=ABT + "245", DIR="WQ", OE="GND")
        w = nl.add("541", f"U_KBW{k}", part=ABT + "541", OE1="WQ_n", OE2="GND")
        rl = nl.add("823", f"U_KBR{k}", part=ABT + "823", CLK="BCK", EN="RLE_n", CLR="VCC",
                    OE="BUSRD_n", D9="GND")
        for i in range(8):
            j = 8 * k + i
            x[f"A{i + 1}"], x[f"B{i + 1}"] = f"BD{j}", f"BUS.D{j}"
            w[f"A{i + 1}"], w[f"Y{i + 1}"] = f"DBUS{j}", f"BD{j}"
            rl[f"D{i + 1}"], rl[f"Q{i + 1}"] = f"BD{j}", f"DBUS{j}"

    nl.section("Interrupts")
    # ---- interrupts: any of IRQ0-IRQ2 ---------------------------------------
    g("10", ["IRQB0_n", "IRQB1_n", "IRQB2_n"], "IRQ", part=HCT + "10")

    nl.finish()
    return bus.Card("CPU", nl)
