"""Chip-level netlist of Heron Mini (RFC 0041): the CPU, its control
store, the 4 MB of RAM.

build(sim=True) is what the chip-level simulator runs (infra/hwsim's
system run): it has the clock generator (a 50.35 MHz oscillator and a
tick counter, the length classes from the uIR), a power-on reset, and
draft 1's I/O page as a 32-bit test fixture in I/O region 7 (on the data
bus, answering without wait states). build() has a fixture in place of the
clock generator, for static timing analysis.

The control store is flash preloaded with the microcode.

Buses
  ABUS   ALU A input   <- register file copy A (through its latches), PC
                          (bit 0 from PCK), R, R x 2 (+ SINA)
  BBUS   ALU B input   <- register file copy B (latches), R, T by byte
                          lane, QH (4 ways), the immediate unit, MQ, the
                          flags
  F      ALU output (74F181 x 8, 74F182 x 3)
  RES    result bus = F through the shift/rotate multiplexer (74F153 x 16)
  VA     the address <- MAR, FPC, the A bus (74F153 x 13: bits 21-0 and 31-28)
  DB     32-bit memory data <- RAM, the I/O space, store data from the A bus
  QH     the prefetch queue's head parcel

Clocking. A cycle of K ticks (19.86 ns) runs H0, H1, the count, then the
tail ticks T1 and T2; CLK rises entering H0. The register file is read
early (its latches transparent) and written late: RW is high for the two
tail ticks (the latches hold, the SRAM's address switches to the write
address, its outputs turn off) and the write strobe is T2, the last tick.
The tail ticks are also when the video may read the RAM (RFC 0041): a
read's data is latched into T, or a fetch's into its queue slot, before
them, and the memory write window MWIN is open from tick 2 to the tail.

See rtl.py for the register-transfer model this netlist implements, and
ucode.py for the fields.
"""

from heron.infra.hw.netlist import Netlist

from . import parts, ucode as uc
from .timing import HEAD, TAIL

TICK_PS = 19_861


def bus(name, n, start=0):
    return [f"{name}{i}" for i in range(start, start + n)]


def control_nets():
    """Control word bit -> uIR output net (with _n for active-low fields)."""
    nets = {}
    for name, (bit, w, al) in uc._pos.items():
        for i in range(w):
            nets[bit + i] = f"u{name}{i if w > 1 else ''}{'_n' if al >> i & 1 else ''}"
    return nets


def preload(k):
    """The tick counter's preload for a cycle of k ticks."""
    p = HEAD + 16 + TAIL - k
    if not 0 <= p <= 15:
        raise ValueError(f"a cycle of {k} ticks is out of range")
    return p


def clock_generator(nl, lengths, por_ps):
    """RFC 0024's clock generator for short cycles, with two tail ticks:
    H0 and H1, the count from the preload to 15, T1 and T2. The length
    class from the uIR's LCL field. RW, the register file's write phase
    and the video's, is T1 or T2; the write strobe T2."""
    g = nl.gate
    nl.section("Reset")
    nl.add("por", "U_POR", RST="PORST_n", params={"release_ps": por_ps})
    nl.add("pullup", "RN_POR", P1="PORST_n")
    g("14", ["PORST_n"], "RSTI")
    g("14", ["RSTI"], "RSTA_n")
    # asserted at once, released at a CLK edge
    nl.add("74", "U_RSY", **{"1D": "VCC", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "RSTA_n",
                             "1Q": "RSY1", "2D": "RSY1", "2CLK": "CLK", "2PRE": "VCC",
                             "2CLR": "RSTA_n", "2Q": "RESET_n"})

    nl.section("Clock generator")
    nl.add("osc", "U_OSC", part="oscillator 50.35 MHz", OUT="MCLK",
           params={"period_ps": TICK_PS, "phase_ps": TICK_PS})
    # the preload, by the length class and XL: a parcel consumed with the
    # queue empty comes from the word the cycle fetches, which takes two
    # ticks more (rtl.DEMAND_HOLD)
    from .rtl import DEMAND_HOLD
    pre = [preload(k) for k in lengths] + [preload(k + DEMAND_HOLD) for k in lengths]
    g("08", ["uCONSUME", "V0_n"], "XL")
    for bit in range(4):
        m = nl.add("151", f"U_LM{bit}", A="uLCL0", B="uLCL1", C="XL", G="GND", Y=f"PSEL{bit}")
        for c in range(8):
            m[f"D{c}"] = "VCC" if (pre[c] >> bit) & 1 else "GND"
    nl.add("163", "U_TC", part="74ACT163", CLK="MCLK", CLR="T2_n", LOAD="H1_n", ENP="VCC",
           ENT="HOLD_n", A="PSEL0", B="PSEL1", C="PSEL2", D="PSEL3",
           QA="TC0", QB="TC1", QC="TC2", QD="TC3", RCO="TCRCO")
    # the hold: the wait states of an access to the I/O space. HOLD from
    # tick 4 for 16 - 2r ticks, r the region (VA[30:28]): the count stops,
    # and its carry, which T1 waits for, is off (a data cycle is 7 ticks
    # or more, so the count is 15 or below). Tick 4, not 3: a read at the
    # A bus has its address from the register file, too late for tick 3.
    # Every step is a flip-flop on the master clock: the hold counter,
    # loaded with 2r + 1 until HOLD rises, counts to its carry, HEND
    # registers that, and HOLD falls a tick later
    nl.section("Hold")
    g("00", ["H3", "IOACC"], "HSTART_n")
    g("00", ["HOLD", "HEND_n"], "HKEEP_n")
    g("00", ["HSTART_n", "HKEEP_n"], "HOLD_D")
    nl.add("74", "U_HOLD", part="74ABT74",
           **{"1D": "HOLD_D", "1CLK": "MCLK", "1PRE": "VCC", "1CLR": "RESET_n",
              "1Q": "HOLD", "1QN": "HOLD_n",
              "2D": "HCRCO", "2CLK": "MCLK", "2PRE": "VCC", "2CLR": "RESET_n",
              "2Q": "HEND", "2QN": "HEND_n"})
    nl.add("163", "U_HC", part="74ACT163", CLK="MCLK", CLR="VCC", LOAD="HOLD", ENP="HOLD",
           ENT="HOLD", A="VCC", B="VA28", C="VA29", D="VA30", RCO="HCRCO")
    nl.section("Clock generator")
    # T1 after the count's carry, T2 after T1; H0 after T2, H1 after H0.
    # H0 never stays on two ticks, so a second pulse dies whatever the
    # flip-flops powered up as
    nl.add("175", "U_TH", CLK="MCLK", CLR="VCC",
           **{"1D": "TCRCO", "1Q": "T1", "1QN": "T1_n",
              "2D": "T1", "2Q": "T2", "2QN": "T2_n",
              "3D": "H0_D", "3Q": "H0", "3QN": "H0_n",
              "4D": "CLK_D", "4Q": "CLK"})
    g("08", ["T2", "H0_n"], "H0_D")
    g("32", ["T2", "H0"], "CLK_D")
    nl.add("175", "U_TH2", CLK="MCLK", CLR="VCC",
           **{"1D": "H0", "1Q": "H1", "1QN": "H1_n", "2D": "H1", "2Q": "H2",
              "3D": "GND", "4D": "GND"})
    # (a fast flip-flop: H3 starts the hold through two gates in a tick)
    nl.add("74", "U_TH3", part="74ABT74",
           **{"1D": "H2", "1CLK": "MCLK", "1PRE": "VCC", "1CLR": "VCC", "1Q": "H3",
              "2D": "GND", "2CLK": "MCLK", "2PRE": "VCC", "2CLR": "VCC"})
    # the write window: MID from tick 2 (J = H1) until H0 (K-bar = T2_n),
    # and not in the tail. The I/O strobe: from the hold's second tick (J =
    # HOLD) until T2 (K-bar = T1_n), a tick after the read latches close
    nl.add("109", "U_WIN",
           **{"1J": "H1", "1K": "T2_n", "1CLK": "MCLK", "1PRE": "VCC", "1CLR": "VCC",
              "1Q": "MID",
              "2J": "HOLD", "2K": "T1_n", "2CLK": "MCLK", "2PRE": "VCC", "2CLR": "RESET_n",
              "2Q": "IOSTB"})
    g("32", ["T1", "T2"], "RW")
    g("02", ["T1", "T2"], "RW_n")
    g("08", ["MID", "RW_n"], "MWIN")
    # LATE: from tick 2, when the cycle before's drivers are off
    g("02", ["H0", "H1"], "LATE")


def build(sim=False, lengths=None, por_ps=2_000_000):
    nl = Netlist()
    g = nl.gate
    U = control_nets()
    u = {v[1:]: v for v in U.values()}          # u["SEQ0"] -> "uSEQ0", u["ARF_n"] ...
    if lengths is None:
        lengths = uc.built().lengths
    lengths = tuple(lengths) + (lengths[-1],) * (4 - len(lengths))

    ABUS, BBUS, F, RES = bus("ABUS", 32), bus("BBUS", 32), bus("F", 32), bus("RES", 32)
    VA, DB = bus("VA", 32), bus("DB", 32)
    IR, QH, Y = bus("IR", 16), bus("QH", 16), bus("Y", uc.Y_BITS)
    RQ, TQ = bus("RQ", 32), bus("TQ", 32)
    MAR, PC = bus("MAR", 32), ["GND"] + bus("PC", 31, 1)
    FPC = ["GND", "GND"] + bus("FPC", 20, 2) + ["GND"] * 10
    LC, SX, EX = bus("LC", 8), bus("SX", 4), bus("EX", 4)

    # ---- clock, reset, rails ------------------------------------------------------
    if sim:
        clock_generator(nl, lengths, por_ps)
    else:
        # for static timing analysis: the clock generator's outputs as
        # functions of the cycle (CLK's edge at 0), and its other phases
        # as they are in the cycle's first part
        nl.add("tickclk", "X_CLK", CLK="CLK", MWIN="MWIN", LATE="LATE", RW="RW", RSTB="T2",
               RESET="RESET_n")
        g("04", ["RW"], "RW_n")
        g("04", ["T2"], "T2_n")
        for net in ("T1", "TCRCO", "MCLK", "H0", "H1", "H2"):
            nl.add("const", f"X_{net}", LO=net)
        nl.add("const", "X_HOLD", LO="HOLD", HI="HOLD_n")
        nl.add("const", "X_IOSTB", LO="IOSTB")
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")
    nl.section("Reset")
    g("04", ["RESET_n"], "RESET")

    # ---- control store -------------------------------------------------------------
    nl.section("Control store")
    YU = ["YU0", "YU1", "YU2"]
    for k in range(uc.WORD_BITS // 8):
        rom = nl.add("flash", f"U_CS{k}", CE="GND", OE="GND", WE="VCC")
        for i in range(17):
            rom[f"A{i}"] = Y[i] if i < uc.Y_BITS else (YU[i - uc.Y_BITS] if i < 16 else "YE")
        for i in range(8):
            rom[f"D{i}"] = f"UD{8 * k + i}"
        r = nl.add("574", f"U_UIR{k}", CLK="CLK", OE="GND")
        for i in range(8):
            r[f"D{i + 1}"] = f"UD{8 * k + i}"
            if 8 * k + i in U:
                r[f"Q{i + 1}"] = U[8 * k + i]

    nl.section("Instruction register")
    for half in (0, 1):
        r = nl.add("377", f"U_IR{half}", CLK="CLK", EN="DECGO_n")
        for i in range(8):
            r[f"D{i + 1}"], r[f"Q{i + 1}"] = QH[8 * half + i], IR[8 * half + i]

    # ---- next address ---------------------------------------------------------------
    nl.section("Next address")
    g("04", [u["COND3"]], "COND3_n")
    nl.add("151", "U_CONDL", A=u["COND0"], B=u["COND1"], C=u["COND2"], G=u["COND3"], Y="CONDL",
           D0=u["NEXT0"], D1="TC", D2=RQ[31], D3="CLQ", D4="CONDT", D5="MQ31", D6="TC4",
           D7="CONDT_n")
    nl.add("151", "U_CONDH", A=u["COND0"], B=u["COND1"], C=u["COND2"], G="COND3_n", Y="CONDH",
           D0="PEND", D1="SXEQ", D2="GND", D3="GND", D4="SX15", D5="MQ0", D6=RQ[0], D7="GND")
    g("32", ["CONDL", "CONDH"], "CONDY")
    for k in range((uc.Y_BITS + 1) // 2):
        m = nl.add("153", f"U_YM{k}", A=u["SEQ0"], B=u["SEQ1"], **{"1G": "YG", "2G": "YG"})
        for sec in (0, 1):
            i = 2 * k + sec
            if i >= uc.Y_BITS:
                for c in range(4):
                    m[f"{sec + 1}C{c}"] = "GND"
                continue
            nxt = "CONDY" if i == 0 else u[f"NEXT{i}"]
            disp = QH[8 + i] if i < 4 else u[f"NEXT{i}"]
            for c, s_ in enumerate([nxt, QH[i], disp, u[f"NEXT{i}"]]):
                m[f"{sec + 1}C{c}"] = s_
            m[f"{sec + 1}Y"] = Y[i]
    # SEQ 1 decode (DEC, from the uIR), 3 halt; the forced entries (refill
    # 001, interrupt 010), which fill their pages, so that only E and U
    # change; and the decode that goes ahead: its first microinstruction
    # at {1, QH}
    g("08", [u["SEQ0"], u["SEQ1"]], "HALTACT")
    g("32", [u["DEC"], "HALTACT"], "DECHALT")
    g("08", ["DECHALT", "PEND"], "FIRQ")
    g("08", [u["DEC"], "PEND_n"], "DECOK")
    # the first parcel is there: in Q0, or (a refill) in the word it fetches
    g("32", ["V0", u["REF"]], "CANDEC")
    g("04", ["CANDEC"], "CANDEC_n")
    # a decode in a cycle that may jump (LDPC) goes to the refill whether it
    # jumps or not, so that the jump's condition isn't on the control
    # store's address: the refill decodes from the queue if it still holds
    # the instruction
    g("32", ["CANDEC_n", u["LDPC"]], "NODEC")
    # Y's low bits are 0 in a decode that can't have its first parcel (a
    # transparent slot, the data bus moving): the refill's page doesn't
    # care, and the address is stable
    g("08", [u["DEC"], "CANDEC_n"], "YGD")
    g("32", ["YGD", "RESET"], "YG")
    g("08", ["DECOK", "NODEC"], "UF0")
    g("04", [u["LDPC"]], "LDPC_n")
    g("21", [u["DEC"], "PEND_n", "CANDEC", "LDPC_n"], "DECGO")
    g("20", [u["DEC"], "PEND_n", "CANDEC", "LDPC_n"], "DECGO_n")
    g("08", ["DECGO", "PC1F"], "DECGOP")
    nl.add("157", "U_UM", S="DECGO", G="RESET",
           **{"1A": "UF0", "1B": QH[13], "1Y": "YU0", "2A": "FIRQ", "2B": QH[14], "2Y": "YU1",
              "3A": "GND", "3B": QH[15], "3Y": "YU2", "4A": "GND", "4B": "VCC", "4Y": "YE"})
    # jump: LDPC, always / on the branch condition / on not CL
    nl.add("153", "U_JUMP", A=u["PCCOND0"], B=u["PCCOND1"],
           **{"1G": "GND", "2G": "VCC", "1C0": "VCC", "1C1": "BCOND", "1C2": "CL_n",
              "1C3": "GND", "1Y": "JC", "2C0": "GND", "2C1": "GND", "2C2": "GND", "2C3": "GND"})
    g("08", [u["LDPC"], "JC"], "JUMP")
    g("00", [u["LDPC"], "JC"], "JUMP_n")

    nl.section("Interrupt request")
    # the interrupt line, active high, registered at every edge (IRQQ); a
    # cycle later, with I as it is in the cycle, PEND
    g("08", ["IRQQ", "IFLAG"], "PEND_D")
    nl.add("74", "U_IRQ",
           **{"1D": "IRQ", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "RESET_n", "1Q": "IRQQ",
              "2D": "PEND_D", "2CLK": "CLK", "2PRE": "VCC", "2CLR": "RESET_n",
              "2Q": "PEND", "2QN": "PEND_n"})

    # ---- register file -----------------------------------------------------------
    # two copies of 32 x 32 bits (r0-r15, then the microcode's own), read
    # through latches in the cycle's first part, written in its last tick
    nl.section("Register file")
    RWA = bus("RWA", 5)
    for k in range(2):
        m = nl.add("153", f"U_RFWM{k}", A=u["RFW0"], B=u["RFW1"], **{"1G": "GND", "2G": "GND"})
        for sec in (0, 1):
            i = 2 * k + sec
            for c, s in enumerate([IR[12 + i], IR[8 + i], SX[i], u[f"RFKW{i}"]]):
                m[f"{sec + 1}C{c}"] = s
            m[f"{sec + 1}Y"] = RWA[i]
    g("11", [u["RFW0"], u["RFW1"], u["RFKW4"]], RWA[4])
    g("00", [u["RFWE"], "T2"], "RFWE_n")
    g("00", [u["RFWE"], "T2"], "RFWB_n")
    # each copy's address: RFA (RFB) selects the read address, RW switches
    # to the write address for the tail, in one 74F151 a bit
    for side, sel, out, oe in (("A", "RFA", ABUS, u["ARF_n"]), ("B", "RFB", BBUS, "BRFE_n")):
        AM = bus(f"RF{side}M", 5)
        for i in range(5):
            m = nl.add("151", f"U_RF{side}A{i}", A=u[f"{sel}0"], B=u[f"{sel}1"], C="RW", G="GND",
                       Y=AM[i])
            if i < 4:
                rd = [IR[12 + i], IR[8 + i], SX[i], u[f"RFK{i}"]]
            else:
                rd = ["GND", "GND", "GND", u["RFK4"]]
            for c in range(4):
                m[f"D{c}"], m[f"D{4 + c}"] = rd[c], RWA[i]
        IO = bus(f"RF{side}IO", 32)
        for k in range(4):
            ram = nl.add("sram", f"U_RF{side}{k}", role="rf", CE="GND", OE="RW", WE="RFWE_n")
            for i in range(15):
                ram[f"A{i}"] = AM[i] if i < 5 else "GND"
            for i in range(8):
                ram[f"IO{i}"] = IO[8 * k + i]
            lat = nl.add("573", f"U_RL{side}{k}", LE="RW_n", OE=oe)
            buf = nl.add("541", f"U_RW{side}{k}", OE1="RFWB_n", OE2="RFWB_n")
            for i in range(8):
                lat[f"D{i + 1}"], lat[f"Q{i + 1}"] = IO[8 * k + i], out[8 * k + i]
                buf[f"A{i + 1}"], buf[f"Y{i + 1}"] = RES[8 * k + i], IO[8 * k + i]

    # ---- A bus -------------------------------------------------------------------
    nl.section("A bus")
    nl.add("153", "U_SINA", A=u["SINA0"], B=u["SINA1"],
           **{"1G": "GND", "2G": "VCC", "1C0": "GND", "1C1": RQ[31], "1C2": "CFLAG",
              "1C3": "MQ31", "1Y": "SINA", "2C0": "GND", "2C1": "GND", "2C2": "GND", "2C3": "GND"})
    R2 = ["SINA"] + RQ[:31]
    PCA = [u["PCK"]] + PC[1:]
    for k in range(4):
        for ref, src, oe in ((f"U_APC{k}", PCA, u["APC_n"]), (f"U_AR{k}", RQ, u["AR_n"]),
                             (f"U_AR2{k}", R2, u["AR2_n"])):
            b = nl.add("541", ref, OE1=oe, OE2=oe)
            for i in range(8):
                b[f"A{i + 1}"], b[f"Y{i + 1}"] = src[8 * k + i], ABUS[8 * k + i]

    # ---- B bus -------------------------------------------------------------------
    nl.section("B bus")
    # the enables straight from the uIR pass a gate, so that they come on
    # about when the decoded ones (below) of the cycle before go off
    for f in ("BRF", "BR", "BF1", "BF23"):
        g("32", [u[f"{f}_n"], "GND"], f"{f}E_n")
    for k in range(4):
        b = nl.add("541", f"U_BR{k}", OE1="BRE_n", OE2="BRE_n")
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = RQ[8 * k + i], BBUS[8 * k + i]
    # T by lanes (BL 1 word, 2 half, 3 byte, moved down to the low lanes by
    # TL, the access's address), and the queue's head (4 as it is, 5 x 2,
    # 6 in the upper half, 7 its low byte)
    bl = nl.add("138", "U_BLD", A=u["BL0"], B=u["BL1"], C=u["BL2"], G1="VCC", G2A="GND", G2B="GND")
    for v, name in ((1, "BLW_n"), (4, "BLQ_n"), (5, "BLQ2_n"), (6, "BLQH_n")):
        bl[f"Y{v}"] = name
    g("04", ["TL0"], "TL0_n")
    g("04", ["TL1"], "TL1_n")
    g("02", ["TL0", "TL1"], "TLB0")
    g("08", ["TL0", "TL1_n"], "TLB1")
    g("08", ["TL0_n", "TL1"], "TLB2")
    g("08", ["TL0", "TL1"], "TLB3")
    #            BL: -  word   half    byte    qh     qh2    qhh    qhb
    for name, ins in (("BT0_n", ["GND", "VCC", "TL1_n", "TLB0", "GND", "GND", "GND", "GND"]),
                      ("BT1_n", ["GND", "VCC", "TL1_n", "GND", "GND", "GND", "GND", "GND"]),
                      ("BT20_n", ["GND", "GND", "TL1", "TLB2", "GND", "GND", "GND", "GND"]),
                      ("TH1_n", ["GND", "GND", "TL1", "GND", "GND", "GND", "GND", "GND"]),
                      ("TB1_n", ["GND", "GND", "GND", "TLB1", "GND", "GND", "GND", "GND"]),
                      ("TB3_n", ["GND", "GND", "GND", "TLB3", "GND", "GND", "GND", "GND"]),
                      ("BQ0_n", ["GND", "GND", "GND", "GND", "VCC", "GND", "GND", "VCC"])):
        nl.add("151", f"U_{name[:-2]}E", A=u["BL0"], B=u["BL1"], C=u["BL2"], G="GND", W=name,
               **{f"D{i}": x for i, x in enumerate(ins)})
    tb = [TQ[8 * k:8 * k + 8] for k in range(4)]
    QH2 = ["GND"] + QH[:15]
    for ref, src, dst, oe in (("U_BT0", tb[0], 0, "BT0_n"), ("U_BT1", tb[1], 1, "BT1_n"),
                              ("U_BT2", tb[2], 2, "BLW_n"), ("U_BT3", tb[3], 3, "BLW_n"),
                              ("U_BT20", tb[2], 0, "BT20_n"), ("U_BT31", tb[3], 1, "TH1_n"),
                              ("U_BT10", tb[1], 0, "TB1_n"), ("U_BT30", tb[3], 0, "TB3_n"),
                              ("U_BQ0", QH[0:8], 0, "BQ0_n"), ("U_BQ1", QH[8:16], 1, "BLQ_n"),
                              ("U_BQ20", QH2[0:8], 0, "BLQ2_n"), ("U_BQ21", QH2[8:16], 1, "BLQ2_n"),
                              ("U_BQH2", QH[0:8], 2, "BLQH_n"), ("U_BQH3", QH[8:16], 3, "BLQH_n")):
        b = nl.add("541", ref, OE1=oe, OE2=oe)
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = src[i], BBUS[8 * dst + i]

    nl.section("Immediate unit")
    nl.add("151", "U_FILLM", A=u["FSEL0"], B=u["FSEL1"], C=u["FSEL2"], G="GND", Y="FILL",
           D0="GND", D1="VCC", D2="GND", D3=QH[15], D4=QH[7], D5=ABUS[31], D6=ABUS[15],
           D7="SGNQ")
    # byte 0: the constant (V8 1), the fill (2) or LC (3), while BS0
    g("04", [u["V80"]], "V80_n")
    g("04", [u["V81"]], "V81_n")
    g("27", [u["BS0_n"], u["V81"], "GND"], "BSK")
    g("04", ["BSK"], "BSK_n")
    g("20", [u["V81"], "V80_n", "BS0", "VCC"], "BSF_n")
    g("20", [u["V81"], u["V80"], "BS0", "VCC"], "BSL_n")
    g("04", [u["BS0_n"]], "BS0")
    for ref, src, dst, oe in (("U_BSK", [u[f"KONST{i}"] for i in range(8)], 0, "BSK_n"),
                              ("U_BSF", ["FILL"] * 8, 0, "BSF_n"),
                              ("U_BSL", LC, 0, "BSL_n"),
                              ("U_BF1", ["FILL"] * 8, 1, "BF1E_n"),
                              ("U_BF2", ["FILL"] * 8, 2, "BF23E_n"),
                              ("U_BF3", ["FILL"] * 8, 3, "BF23E_n")):
        b = nl.add("541", ref, OE1=oe, OE2=oe)
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = src[i], BBUS[8 * dst + i]

    nl.section("B bus")
    # BX: 1 MQ, 2 the flags word (V C Z N I in byte 0; the immediate unit's
    # zero fill in bytes 1-3)
    g("00", [u["BX0"], "BX1_n"], "BXMQ_n")
    g("00", ["BX0_n", u["BX1"]], "BXFL_n")
    g("04", [u["BX0"]], "BX0_n")
    g("04", [u["BX1"]], "BX1_n")
    b = nl.add("541", "U_BFL", OE1="BXFL_n", OE2="BXFL_n")
    for i, src in enumerate(["VFLAG", "CFLAG", "ZFLAG", "NFLAG", "IFLAG", "GND", "GND", "GND"]):
        b[f"A{i + 1}"], b[f"Y{i + 1}"] = src, BBUS[i]

    # ---- MQ ------------------------------------------------------------------------
    nl.section("MQ")
    # 4 x 74F299 on the B bus. Chip k holds bits 8k..8k+7 with I/O n = bit
    # 8k+7-n, so the shift toward Q7 is a right shift of MQ (DS0 in at the
    # top), toward Q0 a left shift (DS7 in at the bottom).

    def mqs(bit):
        return {0: "MQ0", 31: "MQ31"}.get(bit, f"MQS{bit}")
    for k in range(4):
        sr = nl.add("299", f"U_MQ{k}", S0=u["MQM0"], S1=u["MQM1"], OE1="BXMQ_n", OE2="GND",
                    MR="VCC", CP="CLK", Q0S=mqs(8 * k + 7), Q7S=mqs(8 * k))
        for n in range(8):
            sr[f"IO{n}"] = BBUS[8 * k + 7 - n]
        sr["DS0"] = F[0] if k == 3 else mqs(8 * (k + 1))
        sr["DS7"] = "QBIT" if k == 0 else mqs(8 * (k - 1) + 7)

    # ---- ALU control, ALU, result multiplexer (draft 1b's) -----------------------------
    nl.section("ALU control")
    # MS 0: S from the uIR; 1 add if MQ[0]; 2 subtract if MQ[0]; 3 add if
    # S33, else subtract (divide) or pass (MQM 0, the fix-up)
    g("08", ["S33_n", u["MQM1"]], "GSDIV")
    SE = bus("SE", 4)
    for k, (lo, hi), data in ((0, (0, 3), ["MQ0", "GND", "S33Q"]),
                              (1, (1, 2), ["GND", "MQ0", "GSDIV"])):
        m = nl.add("153", f"U_SM{k}", A=u["MS0"], B=u["MS1"], **{"1G": "GND", "2G": "GND"})
        for sec, i in ((1, lo), (2, hi)):
            for c, src in enumerate([u[f"S{i}"]] + data):
                m[f"{sec}C{c}"] = src
            m[f"{sec}Y"] = SE[i]
    nl.add("151", "U_CINM", A=u["CIN0"], B=u["CIN1"], C=u["CIN2"], G="GND", W="CIN_n",
           D0="GND", D1="VCC", D2="CFLAG", D3=ABUS[31], D4="MQ31", D5="SGNQ", D6="MQ0", D7="S33_n")

    nl.section("ALU")
    cn = ["CIN_n", "C4_n", "C8_n", "C12_n", "C16_n", "C20_n", "C24_n", "C28_n"]
    for k in range(8):
        a = nl.add("181", f"U_ALU{k}", M=u["M"], CN=cn[k], P=f"ALUP{k}", G=f"ALUG{k}",
                   **{f"S{i}": SE[i] for i in range(4)})
        for i in range(4):
            a[f"A{i}"], a[f"B{i}"], a[f"F{i}"] = ABUS[4 * k + i], BBUS[4 * k + i], F[4 * k + i]
        if k == 7:
            a["CN4"] = "CARRY_n"
    nl.add("182", "U_CLA0", CN="CIN_n", CNX="C4_n", CNY="C8_n", CNZ="C12_n", P="GP0", G="GG0",
           **{f"P{i}": f"ALUP{i}" for i in range(4)}, **{f"G{i}": f"ALUG{i}" for i in range(4)})
    nl.add("182", "U_CLA1", CN="C16_n", CNX="C20_n", CNY="C24_n", CNZ="C28_n",
           **{f"P{i}": f"ALUP{4 + i}" for i in range(4)},
           **{f"G{i}": f"ALUG{4 + i}" for i in range(4)})
    nl.add("182", "U_CLA2", CN="CIN_n", CNX="C16_n", P0="GP0", G0="GG0",
           P1="VCC", G1="VCC", P2="VCC", G2="VCC", P3="VCC", G3="VCC")
    g("04", ["CARRY_n"], "C32")
    # overflow: V = (A31 ^ B31 ^ S0) & (A31 ^ F31)
    g("86", [BBUS[31], SE[0]], "VT1")
    g("86", [ABUS[31], "VT1"], "VT2")
    g("86", [ABUS[31], F[31]], "VT3")

    nl.section("Result multiplexer")
    g("04", [u["MQM1"]], "MQM1_n")
    g("08", [u["MQM0"], "MQM1_n"], "MULSTEP")
    nl.add("157", "U_MSGN", S="VT2", G="GND",
           **{"1A": F[31], "1B": ABUS[31], "1Y": "MSIGN",
              "2A": "GND", "2B": "GND", "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    nl.add("151", "U_SINM", A=u["SIN0"], B=u["SIN1"], C="MULSTEP", G="GND", Y="SINE",
           D0="GND", D1=F[31], D2="CFLAG", D3=F[0], D4="C32", D5="MSIGN", D6="GND", D7="GND")
    for k in range(16):
        byte = k // 4
        m = nl.add("153", f"U_RES{k}", A=u["RMS0"], B=u["RMS1"],
                   **{"1G": u[f"RZ{byte}"], "2G": u[f"RZ{byte}"]})
        for sec in (0, 1):
            i = 2 * k + sec
            srcs = [F[i], "SINE" if i == 31 else F[i + 1], F[(i + 8) % 32], F[(i + 16) % 32]]
            for c, s in enumerate(srcs):
                m[f"{sec + 1}C{c}"] = s
            m[f"{sec + 1}Y"] = RES[i]

    # ---- registers ------------------------------------------------------------------
    nl.section("R and T")
    for k in range(4):
        r = nl.add("377", f"U_R{k}", CLK="CLK", EN=u["LDR_n"])
        for i in range(8):
            r[f"D{i + 1}"], r[f"Q{i + 1}"] = RES[8 * k + i], RQ[8 * k + i]
    # T, and TL (the access's address bits 1-0): latches, transparent while
    # memory is read into them, from tick 2 (LATE) until the tail
    g("11", ["READING", "RW_n", "LATE"], "TLE")
    for k in range(4):
        t = nl.add("573", f"U_T{k}", LE="TLE", OE="GND")
        for i in range(8):
            t[f"D{i + 1}"], t[f"Q{i + 1}"] = DB[8 * k + i], TQ[8 * k + i]
    nl.add("573", "U_TL", LE="TLE", OE="GND", D1=VA[0], Q1="TL0", D2=VA[1], Q2="TL1",
           **{f"D{i}": "GND" for i in range(3, 9)})

    nl.section("MAR")
    # bits 1-0 and 31-28 load; 21-2 load or count by 4 (MARINC); 27-22 aren't
    # kept: the RAM is 4 MB, and the I/O regions repeat
    nl.add("161", "U_MARL", CLK="CLK", CLR="VCC", LOAD=u["LDMAR_n"], ENP="GND", ENT="GND",
           A=RES[0], B=RES[1], C="GND", D="GND", QA=MAR[0], QB=MAR[1])
    counter_chain(nl, "MAR", MAR, RES, 2, 5, u["LDMAR_n"], u["MARINC"])
    nl.add("161", "U_MARH", CLK="CLK", CLR="VCC", LOAD=u["LDMAR_n"], ENP="GND", ENT="GND",
           A=RES[28], B=RES[29], C=RES[30], D=RES[31], QA=MAR[28], QB=MAR[29], QC=MAR[30],
           QD=MAR[31])

    nl.section("Loop counter")
    nl.add("161", "U_LC0", CLK="CLK", CLR="VCC", LOAD=u["LDLC_n"], ENP=u["LCINC"], ENT="VCC",
           A=RES[0], B=RES[1], C=RES[2], D=RES[3], QA=LC[0], QB=LC[1], QC=LC[2], QD=LC[3],
           RCO="TC4")
    nl.add("161", "U_LC1", CLK="CLK", CLR="VCC", LOAD=u["LDLC_n"], ENP=u["LCINC"], ENT="TC4",
           A=RES[4], B=RES[5], C=RES[6], D=RES[7], QA=LC[4], QB=LC[5], QC=LC[6], QD=LC[7],
           RCO="TC")

    nl.section("SX and EX")
    # LDSX: 1 IR[15:12], 3 the queue head's QH[15:12], 2 count
    m = nl.add("157", "U_SXM", S=u["LDSX1"], G="GND")
    for i in range(4):
        m[f"{i + 1}A"], m[f"{i + 1}B"], m[f"{i + 1}Y"] = IR[12 + i], QH[12 + i], f"SXD{i}"
    g("04", [u["LDSX0"]], "SXLD_n")
    g("04", [u["LDSX0"]], "LDSX0_n")
    g("08", [u["LDSX1"], "LDSX0_n"], "SXEN")
    nl.add("161", "U_SX", CLK="CLK", CLR="VCC", LOAD="SXLD_n", ENP="SXEN", ENT="VCC",
           A="SXD0", B="SXD1", C="SXD2", D="SXD3", QA=SX[0], QB=SX[1], QC=SX[2], QD=SX[3])
    m = nl.add("157", "U_EXM", S=u["LDEX1"], G="GND")
    for j in range(4):
        m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = IR[8 + j], QH[12 + j], f"EXD{j}"
    g("02", [u["LDEX0"], u["LDEX1"]], "EXLD_n")
    ex = nl.add("377", "U_EX", CLK="CLK", EN="EXLD_n",
                **{f"D{j + 1}": f"EXD{j}" for j in range(4)},
                **{f"Q{j + 1}": EX[j] for j in range(4)},
                **{f"D{j}": "GND" for j in range(5, 9)})
    nl.add("521", "U_SXEQ", G="GND", PEQ="SXEQ_n",
           **{f"P{i}": SX[i] if i < 4 else "GND" for i in range(8)},
           **{f"Q{i}": EX[i] if i < 4 else "GND" for i in range(8)})
    g("04", ["SXEQ_n"], "SXEQ")
    g("21", SX, "SX15")

    # ---- PC, FPC and the prefetch queue ----------------------------------------------
    nl.section("PC")
    g("04", ["JUMP_n"], "PCLD")
    # a decode that goes ahead consumes its first parcel; a cycle that
    # consumes has no data access (the microcode's rules)
    g("08", [u["CONSUME"], "JUMP_n"], "CONSC")
    g("32", ["CONSC", "DECGO"], "CONSUMEX")
    counter_chain(nl, "PC", PC, RES, 1, 8, "JUMP_n", "CONSUMEX")
    counter_chain(nl, "FPC", FPC, RES, 2, 5, "JUMP_n", "FPCINC")
    # PC[1] again, from a fast flip-flop, for the queue's head
    g("86", ["PC1F", "CONSUMEX"], "PC1T")
    nl.add("157", "U_PCFM", S="PCLD", G="GND",
           **{"1A": "PC1T", "1B": RES[1], "1Y": "PC1F_D", "2A": "GND", "2B": "GND",
              "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    nl.add("74", "U_PCF", **{"1D": "PC1F_D", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "RESET_n",
                             "1Q": "PC1F", "1QN": "PC1F_n",
                             "2D": "HS_D", "2CLK": "CLK", "2PRE": "VCC", "2CLR": "VCC",
                             "2Q": "HS", "2QN": "HS_n"})

    nl.section("Prefetch queue")
    # a fetch: in any cycle without a data access, if Q1 is free; the word
    # goes into the empty slot (Q0's, slot HS, if the queue is empty)
    g("08", ["FETCHCYC", "V1_n"], "FETCHED")
    g("08", ["FETCHED", "JUMP_n"], "FPCINC")
    # the head word is used up when its high parcel is consumed
    g("08", ["CONSC", "PC1F"], "SHIFTC")
    g("32", ["SHIFTC", "DECGOP"], "SHIFT")
    g("04", ["SHIFT"], "SHIFT_n")
    g("86", ["HS", "SHIFT"], "HS_D")
    # the queue's words after the edge: n = V0 + V1 + fetched - shifted,
    # none after a jump
    g("08", ["V0", "FETCHED"], "QVF")
    g("32", ["V0", "FETCHED"], "QVOF")
    g("08", ["QVOF", "SHIFT_n"], "QVS")
    g("27", ["V1", "QVF", "QVS"], "V0P_n")
    g("02", ["V0P_n", "JUMP"], "V0_D")
    g("32", ["V1", "QVF"], "QV1F")
    g("11", ["QV1F", "SHIFT_n", "JUMP_n"], "V1_D")
    nl.add("74", "U_V", **{"1D": "V0_D", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "VCC",
                           "1Q": "V0", "1QN": "V0_n",
                           "2D": "V1_D", "2CLK": "CLK", "2PRE": "VCC", "2CLR": "VCC",
                           "2Q": "V1", "2QN": "V1_n"})
    # two slots, latches from the data bus: Q0 is slot HS and Q1 the other.
    # A slot is transparent while it is empty, from the cycle's start (so
    # that a word fetched for the decode, or for a parcel the cycle reads,
    # reaches the head at once) until the tail: a J-K flip-flop a slot, set
    # at the CPU clock's edge if the slot is empty after it, cleared
    # entering T1
    g("02", ["HS_D", "V0_D"], "E0A")        # slot 0 empty after the edge: HS' = 0, V0' = 0,
    g("04", ["V1_D"], "V1D_n")
    g("08", ["HS_D", "V1D_n"], "E0B")       # or HS' = 1, V1' = 0
    g("27", ["E0A", "E0B", "GND"], "E0N_n")
    g("04", ["HS_D"], "HSD_n")
    g("08", ["HSD_n", "V1D_n"], "E1A")      # slot 1: HS' = 0, V1' = 0,
    g("02", ["HSD_n", "V0_D"], "E1B")       # or HS' = 1, V0' = 0
    g("27", ["E1A", "E1B", "GND"], "E1N_n")
    # J-K-bar: set entering H0 if the slot is empty then, clear entering
    # H0 if not, and entering T1 (TCRCO); hold otherwise
    g("04", ["TCRCO"], "TCRCO_n")
    for k in range(2):
        g("02", ["T2_n", f"E{k}N_n"], f"LE{k}J")
        g("00", ["T2", f"E{k}N_n"], f"LE{k}K1_n")
        g("08", [f"LE{k}K1_n", "TCRCO_n"], f"LE{k}K_n")
    nl.add("109", "U_QLE",
           **{"1J": "LE0J", "1K": "LE0K_n", "1CLK": "MCLK", "1PRE": "VCC", "1CLR": "VCC",
              "1Q": "QLE0",
              "2J": "LE1J", "2K": "LE1K_n", "2CLK": "MCLK", "2PRE": "VCC", "2CLR": "VCC",
              "2Q": "QLE1"})
    for sl in range(2):
        QS = bus(f"QS{sl}_", 32)
        for k in range(4):
            lat = nl.add("573", f"U_QS{sl}{k}", LE=f"QLE{sl}", OE="GND")
            oe = f"QH{sl}{'LH'[k >> 1]}_n"
            b = nl.add("541", f"U_QB{sl}{k}", OE1=oe, OE2=oe)
            for i in range(8):
                lat[f"D{i + 1}"], lat[f"Q{i + 1}"] = DB[8 * k + i], QS[8 * k + i]
                b[f"A{i + 1}"], b[f"Y{i + 1}"] = QS[8 * k + i], QH[8 * (k & 1) + i]
    # the head parcel, a three-state bus: slot HS's half, by PC1F
    g("00", ["HS_n", "PC1F_n"], "QH0L_n")
    g("00", ["HS_n", "PC1F"], "QH0H_n")
    g("00", ["HS", "PC1F_n"], "QH1L_n")
    g("00", ["HS", "PC1F"], "QH1H_n")

    # ---- memory: the address, the RAM, the I/O space ----------------------------------
    nl.section("Memory")
    md = nl.add("138", "U_MEMD", A=u["MEM0"], B=u["MEM1"], C=u["MEM2"], G1="VCC", G2A="GND",
                G2B="GND")
    for v in range(8):
        md[f"Y{v}"] = f"MEM{v}_n"
    g("00", ["MEM1_n", "MEM6_n"], "READING")
    g("04", ["READING"], "READING_n")
    g("04", ["MEM2_n"], "MEMWR")
    g("04", ["MEM3_n"], "MEM3")
    g("20", ["MEM1_n", "MEM2_n", "MEM6_n", "VCC"], "DATAACC")
    g("04", ["DATAACC"], "FETCHCYC")
    # the address: MAR, FPC (fetch cycles) or the A bus (a read at the A
    # bus), by VAS, which the microcode derives from MEM; bits 21-0 and
    # 31-28 (27-22 aren't decoded)
    VBITS = list(range(22)) + list(range(28, 32))
    for k in range(13):
        m = nl.add("153", f"U_VAM{k}", A=u["VAS0"], B=u["VAS1"], **{"1G": "GND", "2G": "GND"})
        for sec in (0, 1):
            i = VBITS[2 * k + sec]
            for c, s in enumerate([MAR[i], FPC[i], ABUS[i], "GND"]):
                m[f"{sec + 1}C{c}"] = s
            m[f"{sec + 1}Y"] = VA[i]
    # the size (SIZE: 1 byte, 2 half, 3 word), decoded active low; byte
    # enables from the size and VA[1:0]. A misaligned access isn't caught:
    # the RAM sees the aligned word, half or byte
    nl.add("138", "U_SIZED", A=u["SIZE0"], B=u["SIZE1"], C="GND", G1="VCC", G2A="GND",
           G2B="GND", Y1="BYTE_n", Y2="HALF_n", Y3="WORD_n")
    g("04", [u["SIZE1"]], "SIZE1_n")
    g("08", [u["SIZE0"], u["SIZE1"]], "WORD")
    nl.add("138", "U_BYTED", A=VA[0], B=VA[1], C="GND", G1="VCC", G2A="BYTE_n", G2B="GND",
           Y0="BYT0_n", Y1="BYT1_n", Y2="BYT2_n", Y3="BYT3_n")
    g("04", [VA[1]], "VA1_n")
    g("02", ["HALF_n", VA[1]], "HLO")
    g("02", ["HALF_n", "VA1_n"], "HHI")
    g("02", ["WORD", "HLO"], "WHL_n")
    g("02", ["WORD", "HHI"], "WHH_n")
    for k, wh in enumerate(["WHL_n", "WHL_n", "WHH_n", "WHH_n"]):
        g("08", [wh, f"BYT{k}_n"], f"BE{k}_n")
        g("04", [f"BE{k}_n"], f"BE{k}")
    # the I/O space: bit 31 of a data access's address; the region from
    # bits 30-28
    g("04", [VA[31]], "VA31_n")
    g("04", ["DATAACC"], "DATAACC_n")
    g("08", ["DATAACC", VA[31]], "IOACC")
    io = nl.add("138", "U_IORD", A=VA[28], B=VA[29], C=VA[30], G1=VA[31], G2A="DATAACC_n",
                G2B="GND")
    for v in range(8):
        io[f"Y{v}"] = f"IOR{v}_n"
    # the RAM: 4 MB, two banks of four 512K x 8 by VA21; its outputs on in a
    # fetch cycle (nothing else drives the data bus then) and in a read of
    # the RAM
    g("04", [VA[21]], "VA21_n")
    g("32", [VA[21], VA[31]], "CE0_n")
    g("32", ["VA21_n", VA[31]], "CE1_n")
    g("08", ["READING", "VA31_n"], "RAMRD")
    g("02", ["FETCHCYC", "RAMRD"], "RAMOE_n")
    g("11", ["MEMWR", "VA31_n", "MWIN"], "MWOK")
    for k in range(4):
        g("00", ["MWOK", f"BE{k}"], f"WE{k}_n")
    for bank in range(2):
        for k in range(4):
            ram = nl.add("sram512", f"U_RAM{bank}{k}", role="fastram", CE=f"CE{bank}_n",
                         OE="RAMOE_n", WE=f"WE{k}_n")
            for i in range(19):
                ram[f"A{i}"] = VA[2 + i]
            for i in range(8):
                ram[f"IO{i}"] = DB[8 * k + i]
    # store data: the A bus, replicated by size (a write always has one, so
    # SIZE1 is a half or a word)
    nl.section("Store data")
    g("00", ["MEMWR", "LATE"], "SDOE_n")
    a8 = [ABUS[8 * k:8 * k + 8] for k in range(4)]
    for ref, src, dst, oe2 in (("U_SD0", a8[0], 0, "GND"), ("U_SD1", a8[1], 1, "SIZE1_n"),
                               ("U_SDB1", a8[0], 1, "BYTE_n"), ("U_SD2", a8[2], 2, "WORD_n"),
                               ("U_SDB2", a8[0], 2, "WORD"), ("U_SD3", a8[3], 3, "WORD_n"),
                               ("U_SDH3", a8[1], 3, "HALF_n"), ("U_SDB3", a8[0], 3, "BYTE_n")):
        b = nl.add("541", ref, OE1="SDOE_n", OE2=oe2)
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = src[i], DB[8 * dst + i]

    nl.section("I/O")
    # the strobes
    g("00", ["MEMWR", "IOSTB"], "IOWR_n")
    g("00", ["READING", "IOSTB"], "IORD_n")
    # the suite's I/O page: a fixture in region 7, on the data bus. It
    # takes a read at CLK's edge, so its read strobe lasts the cycle
    if sim:
        g("00", ["READING", "LATE"], "IORDX_n")
        x = nl.add("iodev_w32", "X_IO", CLK="CLK", IOSEL="IOR7_n", RD="IORDX_n", WR="IOWR_n",
                   IRQ="IRQ")
        for i in range(2, 8):
            x[f"A{i}"] = VA[i]
        for i in range(4):
            x[f"BE{i}"] = f"BE{i}_n"
        for i in range(32):
            x[f"D{i}"] = DB[i]
    else:
        nl.add("const", "X_STUB", LO="IRQ")

    # ---- flags -------------------------------------------------------------------------
    nl.section("Flags")
    # Z is kept as four bits, each a byte of the result nonzero (NZR, a
    # 74F521's output as it is), and formed after the register. Sticky: Z
    # stays clear once clear. FNZ 3 loads the flags word from the A bus.
    NZR, NZ = bus("NZR", 4), bus("NZ", 4)
    for k in range(4):
        nl.add("521", f"U_Z{k}", G="GND", PEQ=NZR[k],
               **{f"P{i}": RES[8 * k + i] for i in range(8)}, **{f"Q{i}": "GND" for i in range(8)})
    g("32", [NZR[0], "ZFLAG_n"], "NZS0")
    g("04", [ABUS[2]], "ABUS2_n")
    for k in range(2):
        m = nl.add("153", f"U_NZM{k}", A=u["FNZ0"], B=u["FNZ1"], **{"1G": "GND", "2G": "GND"})
        for sec in (0, 1):
            i = 2 * k + sec
            for c, src in enumerate([NZ[i], NZR[i], "NZS0" if i == 0 else NZR[i],
                                     "ABUS2_n" if i == 0 else "GND"]):
                m[f"{sec + 1}C{c}"] = src
            m[f"{sec + 1}Y"] = f"NZD{i}"
    g("02", [NZ[0], NZ[1]], "NZA")
    g("02", [NZ[2], NZ[3]], "NZB")
    g("08", ["NZA", "NZB"], "ZFLAG")
    g("00", ["NZA", "NZB"], "ZFLAG_n")
    nl.add("153", "U_NSEL", A=u["NSEL0"], B=u["NSEL1"],
           **{"1G": "GND", "2G": "VCC", "1C0": RES[31], "1C1": RES[15], "1C2": RES[7],
              "1C3": "GND", "1Y": "NSELV", "2C0": "GND", "2C1": "GND", "2C2": "GND", "2C3": "GND"})
    nl.add("153", "U_FNZ", A=u["FNZ0"], B=u["FNZ1"],
           **{"1G": "GND", "2G": "VCC",
              "1C0": "NFLAG", "1C1": "NSELV", "1C2": "NSELV", "1C3": ABUS[3], "1Y": "NNEXT",
              "2C0": "GND", "2C1": "GND", "2C2": "GND", "2C3": "GND"})
    g("86", [F[7], "FILL"], "F7X")
    g("86", [F[15], "FILL"], "F15X")
    # C, from the inverted output: the carry as the ALU gives it (CN4, low
    # for a carry), one gate sooner
    nl.add("151", "U_CSRC", A=u["CSRC0"], B=u["CSRC1"], C=u["CSRC2"], G="GND", Y="CSRCY",
           W="CSRCY_n", D0=ABUS[1], D1=F[0], D2=F[7], D3=F[8], D4=F[15], D5=F[31], D6="F7X",
           D7="F15X")
    nl.add("151", "U_FC", A=u["FC0"], B=u["FC1"], C=u["CZERO"], G="GND", W="CNEXT",
           D0="CFLAG_n", D1="CSRCY_n", D2="CARRY_n", D3="CLQ", D4="VCC", D5="VCC", D6="VCC",
           D7="VCC")
    # I: hold, set, clear, or A4 with a flags load (FI 3)
    nl.add("153", "U_FI", A=u["FI0"], B=u["FI1"],
           **{"1G": "GND", "2G": "VCC",
              "1C0": "IFLAG", "1C1": "VCC", "1C2": "GND", "1C3": ABUS[4], "1Y": "INEXT",
              "2C0": "GND", "2C1": "GND", "2C2": "GND", "2C3": "GND"})
    # V: FV 7 selects VT3 = A31 ^ F31, with the multiplexer off (output 0)
    # unless the operands' signs allow an overflow (VT2)
    g("10", [u["FV0"], u["FV1"], u["FV2"]], "FVOVF_n")
    g("02", ["FVOVF_n", "VT2"], "FVOFF")
    nl.add("151", "U_FV", A=u["FV0"], B=u["FV1"], C=u["FV2"], G="FVOFF", Y="VNEXT",
           D0="VFLAG", D1="GND", D2="GND", D3=ABUS[0], D4="CL_n", D5="VCC", D6="GND", D7="VT3")
    nl.add("377", "U_FLAGS", CLK="CLK", EN="GND",
           D1="NZD0", Q1=NZ[0], D2="NZD1", Q2=NZ[1], D3="NZD2", Q3=NZ[2], D4="NZD3", Q4=NZ[3],
           D5="NNEXT", Q5="NFLAG", D6="CNEXT", Q6="CFLAG", D7="VNEXT", Q7="VFLAG",
           D8="INEXT", Q8="IFLAG")
    for f in ("C", "V"):
        g("04", [f"{f}FLAG"], f"{f}FLAG_n")

    nl.section("Condition latches")
    # CL as four bits, CL = none set (as Z): by CLSRC, the result zero, the
    # carry, RES[31:16] or RES[31:15] zero, those ANDed with CL
    g("32", ["CL_n", RES[15]], "CLB0H")
    CLB = bus("CLB", 4)
    srcs = [[NZR[0], "CARRY_n", "GND", RES[15], "CL_n", "CLB0H", "GND", "GND"],
            [NZR[1], "GND", "GND", "GND", "GND", "GND", "GND", "GND"],
            [NZR[2], "GND", NZR[2], NZR[2], NZR[2], NZR[2], "GND", "GND"],
            [NZR[3], "GND", NZR[3], NZR[3], NZR[3], NZR[3], "GND", "GND"]]
    for i in range(4):
        nl.add("151", f"U_CLM{i}", A=u["CLSRC0"], B=u["CLSRC1"], C=u["CLSRC2"], G="GND",
               Y=f"CLD{i}", **{f"D{c}": srcs[i][c] for c in range(8)})
    g("04", [u["LDCL"]], "LDCL_n")
    nl.add("377", "U_CLB", CLK="CLK", EN="LDCL_n",
           **{f"D{i + 1}": f"CLD{i}" for i in range(4)}, **{f"Q{i + 1}": CLB[i] for i in range(4)},
           **{f"D{i}": "GND" for i in range(5, 9)})
    g("02", [CLB[0], CLB[1]], "CLA")
    g("02", [CLB[2], CLB[3]], "CLBB")
    g("08", ["CLA", "CLBB"], "CLQ")
    g("00", ["CLA", "CLBB"], "CL_n")
    # SGN, S33
    nl.add("157", "U_LATM", S=u["LDSGN"], G="GND",
           **{"1A": "SGNQ", "1B": "FILL", "1Y": "SGN_D",
              "2A": "GND", "2B": "GND", "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    # divide step: S33 = R31 ^ C32 ^ (subtracting = not S33); the quotient
    # bit is its complement. MQ loads clear S33.
    g("86", [RQ[31], "S33_n"], "RG")
    g("04", ["RG"], "RG_n")
    g("86", ["RG", "CARRY_n"], "QBIT")
    g("86", ["RG_n", "CARRY_n"], "S33NEW")
    g("04", [u["MQM0"]], "MQM0_n")
    g("08", ["MQM0_n", u["MQM1"]], "DIVSTEPC")
    g("00", [u["MQM0"], u["MQM1"]], "MQLOADC_n")
    g("08", ["S33Q", "MQLOADC_n"], "S33KEEP")
    nl.add("157", "U_S33MX", S="DIVSTEPC", G="GND",
           **{"1A": "S33KEEP", "1B": "S33NEW", "1Y": "S33_D",
              "2A": "GND", "2B": "GND", "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    nl.add("74", "U_LAT0", **{"1D": "S33_D", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "VCC",
                              "1Q": "S33Q", "1QN": "S33_n",
                              "2D": "SGN_D", "2CLK": "CLK", "2PRE": "VCC", "2CLR": "VCC",
                              "2Q": "SGNQ"})

    nl.section("Branch condition")
    # cc from IR[15:12] (Jcc), IR[3:0] (Bcc) or IR[11:8] (SETcc)
    CC = bus("CC", 4)
    for k in range(2):
        m = nl.add("153", f"U_CCM{k}", A=u["CCB0"], B=u["CCB1"], **{"1G": "GND", "2G": "GND"})
        for sec in (0, 1):
            i = 2 * k + sec
            for c, s in enumerate([IR[12 + i], IR[i], IR[8 + i], "GND"]):
                m[f"{sec + 1}C{c}"] = s
            m[f"{sec + 1}Y"] = CC[i]
    g("08", ["CFLAG", "ZFLAG_n"], "C_HI")
    g("86", ["NFLAG", "VFLAG"], "N_NE_V")
    g("04", ["N_NE_V"], "N_EQ_V")
    g("02", ["ZFLAG", "N_NE_V"], "C_GT")
    nl.add("151", "U_COND", A=CC[1], B=CC[2], C=CC[3], G="GND", Y="CONDT", W="CONDT_n",
           D0="ZFLAG", D1="CFLAG", D2="NFLAG", D3="VFLAG", D4="C_HI", D5="N_EQ_V", D6="C_GT",
           D7="VCC")
    g("86", ["CONDT", CC[0]], "BCOND")

    nl.finish()
    nl.check()
    return nl


def counter_chain(nl, name, q, d, start, n, load_n, inc):
    """A register of 74F161s for bits start.. of q (its count +1 at bit
    `start`), loaded from d (LOAD), counting with `inc`; the count's carry
    looked ahead through AND gates, as on draft 1b's PC."""
    g = nl.gate
    rco = [f"{name}RCO{s}" for s in range(n)]
    enp = [inc]
    for s in range(1, n):
        if s <= 3:
            g("21" if s == 3 else "11" if s == 2 else "08", [inc] + rco[:s], f"{name}E{s}")
        elif s == 4:
            g("21", rco[:4], f"{name}Q4")
            g("08", [inc, f"{name}Q4"], f"{name}E4")
        elif s == 5:
            g("11", [inc, f"{name}Q4", rco[4]], f"{name}E5")
        elif s == 6:
            g("21", [inc, f"{name}Q4", rco[4], rco[5]], f"{name}E6")
        else:
            g("08", [rco[5], rco[6]], f"{name}Q56")
            g("21", [inc, f"{name}Q4", rco[4], f"{name}Q56"], f"{name}E7")
        enp.append(f"{name}E{s}")
    for s in range(n):
        c = nl.add("161", f"U_{name}{s}", CLK="CLK", CLR="VCC", LOAD=load_n, ENP=enp[s],
                   ENT="VCC", RCO=rco[s])
        for j, (dp, qp) in enumerate(zip("ABCD", ("QA", "QB", "QC", "QD"))):
            bit = start + 4 * s + j
            if bit <= 31:
                c[dp], c[qp] = d[bit], q[bit]
            else:
                c[dp] = "GND"


VARIANT = parts.VARIANT
