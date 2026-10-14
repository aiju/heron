"""The memory card: 2 MB of 12 ns SRAM as a fast 32-bit card (RFC 0014
section 12's example). See cards.md for the design and its timing.

- The address, byte enables and WRITE are registered at the end of every
  address clock.
- A read takes one data clock. A write takes two: the card holds WAIT in
  the first and writes the SRAMs during it, so the master's data is still
  there when the write ends. Writing in one clock would need the write to
  end before the clock edge; this card has no faster clock to time that.
- Halfwords and bytes travel on D0-D15 (A1 picks the half); words on
  D0-D31. The swap between D0-D15 and the upper half happens on the card,
  behind the bus transceivers, so each bus line sees one transceiver pin.
- The card's ID (16 bits) is at any address with A27 set.
"""

from heron.infra.hw.netlist import Netlist

from . import bus

F, ABT = "74F", "74ABT"
CARD_ID = 0x0102                       # memory, 2 MB


def build(card_id=CARD_ID):
    nl = Netlist()
    g = nl.gate
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")
    bus.strap_class(nl, "fast32")

    def gf(typ, ins, out):
        return g(typ, ins, out, part=F + typ)

    nl.add("clkdrv", "U_CK", part="CDC341", A="BUS.BCLK", Y1="MCK")
    nl.add("541", "U_IN", part=ABT + "541", OE1="GND", OE2="GND",
           A1="BUS.START_n", A2="BUS.WRITE_n", A3="BUS.SEL", A4="BUS.BE0_n", A5="BUS.BE1_n",
           A6="BUS.BE2_n", A7="BUS.BE3_n", A8="GND",
           Y1="STB_n", Y2="WRB_n", Y3="SELB", Y4="BEB0_n", Y5="BEB1_n", Y6="BEB2_n",
           Y7="BEB3_n")
    # registered at the end of every address clock (START low)
    src = [f"BUS.A{i}" for i in range(1, 21)] + ["BUS.A27", "BEB0_n", "BEB1_n", "BEB2_n",
                                                 "BEB3_n", "WRB_n"]
    dst = [f"RA{i}" for i in range(1, 21)] + ["RA27", "RBE0_n", "RBE1_n", "RBE2_n", "RBE3_n",
                                              "RWR_n"]
    for k in range(4):
        r = nl.add("377", f"U_AR{k}", part=ABT + "377", CLK="MCK", EN="STB_n")
        for i in range(8):
            j = 8 * k + i
            if j < len(src):
                r[f"D{i + 1}"], r[f"Q{i + 1}"] = src[j], dst[j]
            else:
                r[f"D{i + 1}"] = "GND"
    # what the transfer is
    gf("04", ["RA1"], "RA1_n")
    gf("04", ["RWR_n"], "WRT")                          # a write
    gf("00", ["RBE2_n", "RBE3_n"], "WORD")              # BE2 or BE3: a word
    for i in range(4):
        gf("04", [f"RBE{i}_n"], f"BE{i}")
    gf("04", ["SELB"], "SELB_n")
    # byte lanes: 0 and 1 hold A1 = 0's half (and a word's low half), 2 and 3
    # A1 = 1's half (and a word's high half)
    gf("08", ["RA1_n", "BE0"], "LN0")
    gf("08", ["RA1_n", "BE1"], "LN1")
    gf("00", ["RA1", "BE0"], "LN2A_n")
    gf("00", ["WORD", "BE2"], "LN2B_n")
    gf("00", ["LN2A_n", "LN2B_n"], "LN2")
    gf("00", ["RA1", "BE1"], "LN3A_n")
    gf("00", ["WORD", "BE3"], "LN3B_n")
    gf("00", ["LN3A_n", "LN3B_n"], "LN3")
    # a write's first data clock: WAIT, and the write strobes
    gf("11", ["SELB", "WRT", "WQ_n"], "WQ_D")
    nl.add("74", "U_WQ", part=F + "74",
           **{"1D": "WQ_D", "1CLK": "MCK", "1PRE": "VCC", "1CLR": "VCC", "1Q": "WQ",
              "1QN": "WQ_n",
              "2D": "GND", "2CLK": "GND", "2PRE": "VCC", "2CLR": "VCC"})
    gf("20", ["SELB", "WRT", "WQ_n"], "WAITV_n")
    nl.add("125", "U_WT", part=ABT + "125",
           **{"1OE": "SELB_n", "1A": "WAITV_n", "1Y": "BUS.WAIT_n",
              "2OE": "VCC", "2A": "GND", "3OE": "VCC", "3A": "GND", "4OE": "VCC", "4A": "GND"})
    for i in range(4):
        gf("20", ["SELB", "WRT", "WQ_n", f"LN{i}"], f"WE{i}_n")
    # SRAM outputs: lanes 0-1 for A1 = 0, lanes 2-3 for A1 = 1 or a word
    gf("00", ["RWR_n", "RA1_n"], "OE01_n")
    gf("32", ["RA1", "WORD"], "HI")
    gf("00", ["RWR_n", "HI"], "OE23_n")
    CD = [f"CD{i}" for i in range(32)]
    for k in range(4):
        ram = nl.add("sram512", f"U_RAM{k}", role="fastram", CE="RA27",
                     OE="OE01_n" if k < 2 else "OE23_n", WE=f"WE{k}_n")
        for i in range(19):
            ram[f"A{i}"] = f"RA{i + 2}"
        for i in range(8):
            ram[f"IO{i}"] = CD[8 * k + i]
    # transceivers: D0-D15 <-> CD0-15 in every transfer, D16-D31 <-> CD16-31
    # for words, and CD0-15 <-> CD16-31 (the swap) at A1 = 1
    gf("00", ["SELB", "WORD"], "OEU_n")
    gf("00", ["SELB", "RA1"], "OES_n")
    for k in range(2):
        xl = nl.add("245", f"U_XL{k}", part=ABT + "245", DIR="RWR_n", OE="SELB_n")
        xu = nl.add("245", f"U_XU{k}", part=ABT + "245", DIR="RWR_n", OE="OEU_n")
        xs = nl.add("245", f"U_XS{k}", part=ABT + "245", DIR="WRT", OE="OES_n")
        for i in range(8):
            j = 8 * k + i
            xl[f"A{i + 1}"], xl[f"B{i + 1}"] = CD[j], f"BUS.D{j}"
            xu[f"A{i + 1}"], xu[f"B{i + 1}"] = CD[16 + j], f"BUS.D{16 + j}"
            xs[f"A{i + 1}"], xs[f"B{i + 1}"] = CD[j], CD[16 + j]
    # the ID, read at A27 = 1, A1 = 0
    gf("20", ["RWR_n", "RA27", "RA1_n"], "IDOE_n")
    for k in range(2):
        b = nl.add("541", f"U_ID{k}", part=ABT + "541", OE1="IDOE_n", OE2="GND")
        for i in range(8):
            b[f"A{i + 1}"] = "VCC" if (card_id >> (8 * k + i)) & 1 else "GND"
            b[f"Y{i + 1}"] = CD[8 * k + i]

    nl.finish()
    return bus.Card("MEM", nl)
