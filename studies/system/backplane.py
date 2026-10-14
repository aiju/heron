"""The backplane's logic (RFC 0014 sections 5, 7 and 13.9): slot decode,
the class straps, transfer timing, the arbiter, the bus monitor, the clock
driver, the power-on reset and the pull-ups. Every register is clocked by
the bus clock at the edge that ends a clock; see backplane.md for the
design and its timing.

Its nets that are bus lines have the bus's names (bus.py): D0, START_n,
SEL.3, BCLK.3, CLKSRC.
"""

from heron.infra.hw.netlist import Netlist

from . import bus

F, ABT, ACT = "74F", "74ABT", "74ACT"


def build(n_simple=7, por_ps=2_000_000):
    """The backplane: `n_simple` is N, the data clocks a simple card gets
    (jumpers); `por_ps` how long the power-on reset holds RESET."""
    if not 1 <= n_simple <= 16:
        raise ValueError("N must be 1 to 16")
    nl = Netlist()
    g = nl.gate
    S = bus.SLOTS
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")

    def gf(typ, ins, out):
        return g(typ, ins, out, part=F + typ)

    # ---- clock driver: CLKSRC (from slot 0) to every slot and the logic ----
    for k in range(3):
        d = nl.add("clkdrv", f"U_CD{k}", part="CDC341", A="CLKSRC")
        for i in range(8):
            j = 8 * k + i
            if j < S:
                d[f"Y{i + 1}"] = f"BCLK.{j}"
            elif j == S:
                d[f"Y{i + 1}"] = f"BCLK.{S}"    # the backplane's own logic, like a slot
    # the logic in the middle clocks itself through one buffer, as a card
    # does, so its clock is as late as theirs
    nl.add("clkdrv", "U_CK", part="CDC341", A=f"BCLK.{S}", Y1="CK")
    # ---- power-on reset, pull-ups ------------------------------------------
    nl.add("por", "U_POR", RST="RESET_n", params={"release_ps": por_ps})
    pulled = ([f"CLASS0.{k}" for k in range(S)] + [f"CLASS1.{k}" for k in range(S)]
              + [f"REQ_n.{k}" for k in range(S)]
              + ["START_n", "WRITE_n", "LOCK_n", "WAIT_n", "BE2_n", "BE3_n", "RESET_n"]
              + [f"IRQ{i}_n" for i in range(8)] + [f"D{i}" for i in range(32)])
    for k in range(0, len(pulled), 8):
        rn = nl.add("pullup", f"RN{k // 8}")
        for i, n in enumerate(pulled[k:k + 8]):
            rn[f"P{i + 1}"] = n
    g("14", ["RESET_n"], "RST", part="74HCT14")            # Schmitt-trigger input
    g("14", ["RST"], "RST_n", part="74HCT14")

    # ---- bused inputs, through one buffer (the loading rule) ----------------
    nl.add("541", "U_IN", part=ABT + "541", OE1="GND", OE2="GND",
           A1="A28", A2="A29", A3="A30", A4="A31", A5="START_n", A6="WAIT_n", A7="LOCK_n",
           A8="WRITE_n", Y1="SL0", Y2="SL1", Y3="SL2", Y4="SL3", Y5="STB_n", Y6="WTB_n",
           Y7="LKB_n", Y8="WRB_n")
    SL = ["SL0", "SL1", "SL2", "SL3"]

    # ---- the addressed slot's class, from the live slot bits ---------------
    for b in range(2):
        for h in range(2):
            m = nl.add("151", f"U_CM{b}{h}", part=F + "151", A="SL0", B="SL1", C="SL2", G="GND",
                       Y=f"C{b}{'LH'[h]}")
            for i in range(8):
                m[f"D{i}"] = f"CLASS{b}.{8 * h + i}"
    nl.add("157", "U_CMX", part=F + "157", S="SL3", G="GND",
           **{"1A": "C0L", "1B": "C0H", "1Y": "CL0", "2A": "C1L", "2B": "C1H", "2Y": "CL1",
              "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})

    # ---- transfer timing -----------------------------------------------------
    # state: DQ (a data-phase clock), RQ (a simple card's recovery clock),
    # TQ (the bus monitor's timeout), and the slot and class of the transfer
    # (U_SR, loaded in its address clock)
    gf("32", ["DQ", "RQ"], "ACT")                         # a transfer is under way
    gf("02", ["DQ", "RQ"], "ACT_n")
    gf("32", ["ACT", "STB_n"], "STG_n")                   # starting: an address clock now
    gf("02", ["ACT", "STB_n"], "STG")
    nl.add("377", "U_SR", part=ABT + "377", CLK="CK", EN="STG_n",
           D1="SL0", D2="SL1", D3="SL2", D4="SL3", D5="CL0", D6="CL1", D7="GND", D8="GND",
           Q1="SLOT0", Q2="SLOT1", Q3="SLOT2", Q4="SLOT3", Q5="CLS0", Q6="CLS1")
    gf("04", ["CLS0"], "CLS0_n")
    gf("04", ["CLS1"], "CLS1_n")                          # fast: CLASS1 strapped
    # N data clocks for a simple card: U_CNT counts 16-N .. 15; LAST at 15
    load = 16 - n_simple
    nl.add("163", "U_CNT", part=F + "163", CLK="CK", CLR="VCC", LOAD="STG_n", ENP="DQ", ENT="VCC",
           RCO="LAST", **{p: ("VCC" if (load >> i) & 1 else "GND") for i, p in enumerate("ABCD")})
    gf("04", ["LAST"], "LAST_n")
    # the bus monitor: clocks of a fast transfer with WAIT asserted
    gf("08", ["DQ", "CLS1_n"], "FD")                      # a fast card's data clock
    gf("04", ["WTB_n"], "WT")
    nl.add("163", "U_MON0", part=F + "163", CLK="CK", CLR="FD", LOAD="VCC", ENP="WT", ENT="VCC",
           A="GND", B="GND", C="GND", D="GND", RCO="MON4")
    nl.add("163", "U_MON1", part=F + "163", CLK="CK", CLR="FD", LOAD="VCC", ENP="WT", ENT="MON4",
           A="GND", B="GND", C="GND", D="GND", RCO="MON8")
    # does the next clock carry data? X: yes unless the transfer ends at
    # this edge for a reason known early; Y: a fast card's WAIT is off
    gf("11", ["DQ", "CLS1_n", "TQ_n"], "TF")              # fast, carries on if WAIT
    gf("20", ["DQ", "CLS1_n", "TQ_n"], "TF_n")
    gf("21", ["DQ", "CLS1", "CLS0_n", "LAST_n"], "TS")    # simple, more data clocks
    gf("20", ["DQ", "CLS1", "CLS0_n", "LAST_n"], "TS_n")
    gf("20", ["STG_n", "TF_n", "TS_n"], "X")
    gf("27", ["STG", "TF", "TS"], "X_n")
    gf("08", ["FD", "WTB_n"], "Y")
    gf("00", ["FD", "WTB_n"], "Y_n")
    gf("08", ["X", "Y_n"], "DQ_D")
    gf("21", ["DQ", "CLS1", "CLS0_n", "LAST"], "RQ_D")    # into a simple card's recovery
    nl.add("74", "U_ST0", part=F + "74",
           **{"1D": "DQ_D", "1CLK": "CK", "1PRE": "VCC", "1CLR": "RST_n", "1Q": "DQ",
              "1QN": "DQ_n",
              "2D": "RQ_D", "2CLK": "CK", "2PRE": "VCC", "2CLR": "RST_n", "2Q": "RQ"})
    nl.add("74", "U_ST1", part=F + "74",
           **{"1D": "MON8", "1CLK": "CK", "1PRE": "VCC", "1CLR": "RST_n", "1Q": "TQ",
              "1QN": "TQ_n",
              "2D": "GTD", "2CLK": "CK", "2PRE": "RST_n", "2CLR": "VCC", "2Q": "GRANTED"})
    # SEL: the slot carried on (or the live one, when starting), decoded
    # into registers, so it never glitches
    SN = ["SN0", "SN1", "SN2", "SN3"]
    m = nl.add("157", "U_SN", part=F + "157", S="ACT", G="GND")
    for i in range(4):
        m[f"{i + 1}A"], m[f"{i + 1}B"], m[f"{i + 1}Y"] = SL[i], f"SLOT{i}", SN[i]
    for h in range(2):
        d = nl.add("138", f"U_SD{h}", part=F + "138", A="SN0", B="SN1", C="SN2", G2A="Y",
                   **({"G1": "X", "G2B": "SN3"} if h == 0 else {"G1": "SN3", "G2B": "X_n"}))
        r = nl.add("534", f"U_SEL{h}", part=ABT + "534", CLK="CK", OE="GND")
        for i in range(8):
            d[f"Y{i}"] = f"SD_n.{8 * h + i}"
            r[f"D{i + 1}"], r[f"Q{i + 1}"] = f"SD_n.{8 * h + i}", f"SEL.{8 * h + i}"
    # DPH, RDY, BERR, W32 from the registered state, through one driver
    gf("08", ["CLS1", "CLS0"], "EMPTY")
    gf("32", ["EMPTY", "TQ"], "BERRC")
    gf("00", ["DQ", "BERRC"], "BERRI_n")
    gf("02", ["FD", "RQ"], "RDYI_n")
    gf("20", ["DQ", "CLS1_n", "CLS0_n"], "W32I_n")
    nl.add("541", "U_OUT", part=ABT + "541", OE1="GND", OE2="GND",
           A1="DQ_n", A2="RDYI_n", A3="BERRI_n", A4="W32I_n", A5="GND", A6="GND", A7="GND",
           A8="GND", Y1="DPH_n", Y2="RDY_n", Y3="BERR_n", Y4="W32_n")

    # ---- the arbiter ---------------------------------------------------------
    # Q: the highest slot requesting, or 0 (parking) if none does
    nl.add("148", "U_PE1", part=F + "148", EI="GND", A0="PH0", A1="PH1", A2="PH2", GS="GSH_n",
           EO="EOH", **{f"I{i}": f"REQ_n.{8 + i}" for i in range(8)})
    nl.add("148", "U_PE0", part=F + "148", EI="EOH", A0="PL0", A1="PL1", A2="PL2", GS="GSL_n",
           **{f"I{i}": f"REQ_n.{i}" for i in range(8)})
    Q = ["Q0", "Q1", "Q2", "Q3"]
    for i in range(3):
        gf("00", [f"PH{i}", f"PL{i}"], Q[i])
    gf("00", ["GSH_n", "GSH_n"], "Q3")
    OWN = ["OWN0", "OWN1", "OWN2", "OWN3"]
    nl.add("521", "U_CMP", part=F + "521", G="GND", PEQ="NE",
           **{f"P{i}": (Q[i] if i < 4 else "GND") for i in range(8)},
           **{f"Q{i}": (OWN[i] if i < 4 else "GND") for i in range(8)})
    # withdraw: granted, not locked, and someone else should have the bus
    gf("20", ["GRANTED", "LKB_n", "NE", "RST_n"], "W_n")
    gf("04", ["W_n"], "W")
    gf("08", ["STB_n", "ACT_n"], "IDLE")                  # no transfer under way
    gf("00", ["STB_n", "ACT_n"], "IDLE_n")
    # the grant for the next clock: kept unless withdrawn, given when idle
    m = nl.add("157", "U_GT", part=F + "157", S="GRANTED", G="GND",
               **{"1A": "IDLE", "1B": "W_n", "1Y": "GTD", "2A": "IDLE_n", "2B": "W", "2Y": "GTD_n",
                  "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    ON = ["ON0", "ON1", "ON2", "ON3"]
    m = nl.add("157", "U_ON", part=F + "157", S="GRANTED", G="GND")
    for i in range(4):
        m[f"{i + 1}A"], m[f"{i + 1}B"], m[f"{i + 1}Y"] = Q[i], OWN[i], ON[i]
    nl.add("175", "U_OWN", part=F + "175", CLK="CK", CLR="RST_n",
           **{f"{i + 1}D": ON[i] for i in range(4)}, **{f"{i + 1}Q": OWN[i] for i in range(4)})
    for h in range(2):
        d = nl.add("138", f"U_GD{h}", part=F + "138", A="ON0", B="ON1", C="ON2", G2A="GND",
                   **({"G1": "GTD", "G2B": "ON3"} if h == 0 else {"G1": "ON3", "G2B": "GTD_n"}))
        r = nl.add("574", f"U_GNT{h}", part=ABT + "574", CLK="CK", OE="GND")
        for i in range(8):
            d[f"Y{i}"] = f"GD_n.{8 * h + i}"
            r[f"D{i + 1}"], r[f"Q{i + 1}"] = f"GD_n.{8 * h + i}", f"GNT_n.{8 * h + i}"

    nl.finish()
    return nl                  # checked with its cards (bus.compose)
