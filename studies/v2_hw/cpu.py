"""Chip-level netlist of the draft 2 CPU (RFC 0031): the CPU card's core,
its 2 MB of RAM, the page map and the control store, without the bus
interface.

build(sim=True) is what the chip-level simulator runs (infra/hwsim's
system run, machine.py): it has the card's clock generator (a 50 MHz
oscillator and RFC 0024's tick counter, the length classes from the uIR),
a power-on reset, and draft 1's I/O page as a 32-bit test fixture in
slot 15 (on the card's data bus, answering without a bus transfer). Any
other address outside the card's RAM is a bus error: there is no bus
interface here. build() has a fixture in place of the clock generator,
for static timing analysis.

The control store and the decode table are SRAM preloaded with the
microcode, as the I/O processor would leave them; the slave port that
writes them is not drawn (their write enables are tied off).

Buses
  ABUS   ALU A input   <- register file copy A (through its latches), PC
                          (bit 0 from PCK), R, R x 2 (+ SINA), MAR
  BBUS   ALU B input   <- register file copy B (latches), R, T by byte
                          lane, QH (4 ways), the immediate unit, MQ, the
                          flags, FSR, FAR, the map entry
  F      ALU output (74F181 x 8, 74F182 x 3)
  RES    result bus = F through the shift/rotate multiplexer (74F153 x 16)
  VA     virtual address <- MAR, FPC or the A bus (74F153 x 16)
  PA     physical address: VA[11:0], and the map entry's page or the window
  MD     the page map's data (MD[2:0] V, W, X; MD[22:3] the physical page)
  DB     32-bit memory data <- RAM, the I/O page, store data from the A bus
  QH     the prefetch queue's head parcel

Clocking. A cycle of K ticks (20 ns) runs H0, H1, the count, then the tail
tick T1; CLK rises entering H0. The register file is read early (its
latches transparent) and written late: RW is high for the last two ticks
(the latches hold, the SRAM's address switches to the write address, its
outputs turn off) and the write strobe is T1, the last tick. The memory
write window MWIN is open from tick 4 to the tail, so that a write's
address has been translated and checked (FAULT settled) before it opens:
a cycle that writes memory is at least 6 ticks. The commit of
everything a cycle loads is gated by FAULT (RFC 0031, 5).

See rtl.py for the register-transfer model this netlist implements, and
ucode.py for the fields.
"""

from heron.infra.hw.netlist import Netlist

from . import parts, ucode as uc

TICK_PS = 20_000
HEAD, TAIL = 2, 1


def bus(name, n, start=0):
    return [f"{name}{i}" for i in range(start, start + n)]


def control_nets():
    """Control word bit -> uIR output net (with _n for active-low fields)."""
    nets = {}
    for name, (bit, w, al) in uc._pos.items():
        for i in range(w):
            nets[bit + i] = f"u{name}{i if w > 1 else ''}{'_n' if al else ''}"
    return nets


def preload(k):
    """The tick counter's preload for a cycle of k ticks (RFC 0024's fast card)."""
    p = HEAD + 16 + TAIL - k
    if not 0 <= p <= 15:
        raise ValueError(f"a cycle of {k} ticks is out of range")
    return p


def clock_generator(nl, lengths, por_ps):
    """RFC 0024's clock generator for short cycles (studies/v1b_tradeoffs/
    fastcard.py), the length class from the uIR's LCL field; with the
    register file's write phase RW and strobe T1. No bus: nothing holds the
    count."""
    g = nl.gate
    nl.section("Reset")
    nl.add("por", "U_POR", RST="PORST_n", params={"release_ps": por_ps})
    nl.add("pullup", "RN_POR", P1="PORST_n")
    g("14", ["PORST_n"], "RSTI")
    g("14", ["RSTI"], "RESET_n")

    nl.section("Clock generator")
    nl.add("osc", "U_OSC", part="oscillator 50 MHz", OUT="MCLK",
           params={"period_ps": TICK_PS, "phase_ps": TICK_PS})
    pre = [preload(k) for k in lengths]
    for k in range(2):
        m = nl.add("153", f"U_LM{k}", A="uLCL0", B="uLCL1", **{"1G": "GND", "2G": "GND"})
        for sec in (0, 1):
            bit = 2 * k + sec
            for c in range(4):
                m[f"{sec + 1}C{c}"] = "VCC" if (pre[c] >> bit) & 1 else "GND"
            m[f"{sec + 1}Y"] = f"PSEL{bit}"
    nl.add("163", "U_TC", part="74ACT163", CLK="MCLK", CLR="T1_n", LOAD="H1_n", ENP="VCC",
           ENT="VCC", A="PSEL0", B="PSEL1", C="PSEL2", D="PSEL3",
           QA="TC0", QB="TC1", QC="TC2", QD="TC3", RCO="TCRCO")
    nl.add("175", "U_TH", CLK="MCLK", CLR="VCC",
           **{"1D": "TCRCO", "1Q": "T1", "1QN": "T1_n",
              "2D": "T1", "2Q": "H0", "2QN": "H0_n",
              "3D": "H0", "3Q": "H1", "3QN": "H1_n",
              "4D": "CLK_D", "4Q": "CLK"})
    g("32", ["T1", "H0"], "CLK_D")
    # H2, H3: H1 a tick and two later; the write window opens entering
    # tick 4, once a write's address has been translated and checked
    nl.add("175", "U_TH2", CLK="MCLK", CLR="VCC",
           **{"1D": "H1", "1Q": "H2", "2D": "H2", "2Q": "H3", "3D": "GND", "4D": "GND"})
    nl.add("109", "U_WIN",
           **{"1J": "H3", "1K": "T1_n", "1CLK": "MCLK", "1PRE": "VCC", "1CLR": "VCC",
              "1Q": "MID",
              "2J": "TCRCO", "2K": "H0_n", "2CLK": "MCLK", "2PRE": "VCC", "2CLR": "VCC",
              "2QN": "TAILX_n"})
    g("08", ["MID", "TAILX_n"], "MWIN")
    g("32", ["TCRCO", "T1"], "RW")


def build(sim=False, lengths=None, por_ps=2_000_000):
    nl = Netlist()
    g = nl.gate
    U = control_nets()
    u = {v[1:]: v for v in U.values()}          # u["SEQ0"] -> "uSEQ0", u["ARF_n"] ...
    if lengths is None:
        lengths = uc.built().lengths

    ABUS, BBUS, F, RES = bus("ABUS", 32), bus("BBUS", 32), bus("F", 32), bus("RES", 32)
    VA, MD, DB = bus("VA", 32), bus("MD", 24), bus("DB", 32)
    PA = VA[:12] + bus("PA", 20, 12)
    IR, QH, DEC, Y = bus("IR", 16), bus("QH", 16), bus("DEC", 16), bus("Y", uc.Y_BITS)
    RQ, TQ = bus("RQ", 32), bus("TQ", 32)
    MAR, PC, FPC = bus("MAR", 32), ["GND"] + bus("PC", 31, 1), ["GND", "GND"] + bus("FPC", 30, 2)
    QA, QB = bus("QA", 32), bus("QB", 32)
    LC, SX, EX = bus("LC", 8), bus("SX", 4), bus("EX", 4)
    BANK, CTX = bus("BANK", 8), bus("CTX", 7)

    # ---- clock, reset, rails ------------------------------------------------------
    if sim:
        clock_generator(nl, lengths, por_ps)
    else:
        nl.add("tickclk", "X_CLK", CLK="CLK", MWIN="MWIN", RW="RW", RSTB="T1", RESET="RESET_n")
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")
    nl.section("Reset")
    g("04", ["RESET_n"], "RESET")
    nl.section("Register file")
    g("04", ["RW"], "RW_n")

    # ---- control store -------------------------------------------------------------
    nl.section("Control store")
    UA = ["UA0", "UA1", "UA2"]
    for k in range(uc.WORD_BITS // 16):
        for h in range(2):
            ram = nl.add("sram64k", f"U_CS{k}{'LH'[h]}", role="cs", CE="GND", OE="GND", WE="VCC")
            for i in range(16):
                ram[f"A{i}"] = Y[i] if i < uc.Y_BITS else UA[i - uc.Y_BITS]
            for i in range(8):
                ram[f"IO{i}"] = f"UD{16 * k + 8 * h + i}"
    for k in range(uc.WORD_BITS // 8):
        r = nl.add("377", f"U_UIR{k}", CLK="CLK", EN="GND")
        for i in range(8):
            r[f"D{i + 1}"] = f"UD{8 * k + i}"
            if 8 * k + i in U:
                r[f"Q{i + 1}"] = U[8 * k + i]

    nl.section("Decode")
    for h in range(2):
        ram = nl.add("sram64k", f"U_DEC{'LH'[h]}", role="decode", CE="GND", OE="GND", WE="VCC")
        for i in range(16):
            ram[f"A{i}"] = QH[i]
        for i in range(8):
            ram[f"IO{i}"] = DEC[8 * h + i]

    nl.section("Instruction register")
    for half in (0, 1):
        r = nl.add("377", f"U_IR{half}", CLK="CLK", EN="DECGO_n")
        for i in range(8):
            r[f"D{i + 1}"], r[f"Q{i + 1}"] = QH[8 * half + i], IR[8 * half + i]
    nl.add("377", "U_LEN", CLK="CLK", EN="DECGO_n", D1=DEC[13], Q1="LEN0", D2=DEC[14], Q2="LEN1",
           **{f"D{i}": "GND" for i in range(3, 9)})
    # TS <- T at a decode that goes ahead; cleared by exception entry and reset
    g("00", [u["SSET"], "FAULT_n"], "SSETC_n")
    g("08", ["DECGO", "TFLAG"], "TSA")
    g("11", ["DECGO_n", "SSETC_n", "TSQ"], "TSB")
    g("32", ["TSA", "TSB"], "TS_D")

    # ---- next address ---------------------------------------------------------------
    nl.section("Next address")
    g("04", [u["COND3"]], "COND3_n")
    nl.add("151", "U_CONDL", A=u["COND0"], B=u["COND1"], C=u["COND2"], G=u["COND3"], Y="CONDL",
           D0=u["NEXT0"], D1="TC", D2=RQ[31], D3="CLQ", D4="CONDT", D5="MQ31", D6="TC4",
           D7="CONDT_n")
    nl.add("151", "U_CONDH", A=u["COND0"], B=u["COND1"], C=u["COND2"], G="COND3_n", Y="CONDH",
           D0="SFLAG", D1="SXEQ", D2="FK0", D3="FK1", D4="SX15", D5="MQ0", D6=RQ[0], D7="GND")
    g("32", ["CONDL", "CONDH"], "CONDY")
    for k in range((uc.Y_BITS + 1) // 2):
        m = nl.add("153", f"U_YM{k}", A=u["SEQ0"], B=u["SEQ1"], **{"1G": "YOFF", "2G": "YOFF"})
        for sec in (0, 1):
            i = 2 * k + sec
            if i >= uc.Y_BITS:
                for c in range(4):
                    m[f"{sec + 1}C{c}"] = "GND"
                continue
            nxt = "CONDY" if i == 0 else u[f"NEXT{i}"]
            disp = QH[8 + i] if i < 4 else u[f"NEXT{i}"]
            for c, s in enumerate([nxt, DEC[i], disp, u[f"NEXT{i}"]]):
                m[f"{sec + 1}C{c}"] = s
            m[f"{sec + 1}Y"] = Y[i]
    # SEQ 1 decode, 3 halt; the forced entries (refill 001, interrupt 010,
    # trace 011, fault 1LL) and the decode that goes ahead
    g("04", [u["SEQ1"]], "SEQ1_n")
    g("08", [u["SEQ0"], "SEQ1_n"], "DECACT")
    g("08", [u["SEQ0"], u["SEQ1"]], "HALTACT")
    g("08", ["DECACT", "TSQ"], "FTRACE")
    g("11", ["DECACT", "TSQ_n", "IRQP"], "FIRQD")
    g("08", ["HALTACT", "IRQP"], "FIRQH")
    g("32", ["FIRQD", "FIRQH"], "FIRQ")
    g("11", ["DECACT", "TSQ_n", "IRQP_n"], "DECOK")
    g("08", ["DECOK", "COMPLETE_n"], "FREFILL")
    g("11", ["DECOK", "COMPLETE", "FAULT_n"], "DECGO")
    g("04", ["DECGO"], "DECGO_n")
    g("32", ["FAULT", "RESET"], "YOFF1")
    g("32", ["FTRACE", "FIRQ"], "YOFF2")
    g("32", ["YOFF1", "YOFF2"], "YOFF3")
    g("32", ["YOFF3", "FREFILL"], "YOFF")
    g("32", ["FIRQ", "FTRACE"], "UF1")
    g("32", ["FREFILL", "FTRACE"], "UF0")
    # a fault's entry has the parcels the instruction consumed: 0 for a refill's fetch
    g("08", ["LEN0", "MEM3_n"], "LL0")
    g("08", ["LEN1", "MEM3_n"], "LL1")
    nl.add("157", "U_UM", S="FAULT", G="RESET",
           **{"1A": "UF0", "1B": "LL0", "1Y": "UA0", "2A": "UF1", "2B": "LL1", "2Y": "UA1",
              "3A": "GND", "3B": "VCC", "3Y": "UA2", "4A": "GND", "4B": "GND"})
    # the queue holds the whole next instruction (with this cycle's fetch),
    # and the cycle doesn't jump
    g("08", ["V0", "FETCHED"], "V0F")
    g("32", ["V1", "V0F"], "QW2")
    g("86", ["V0", "FETCHED"], "VXF")
    g("08", ["VXF", "V1_n"], "QW1")
    g("00", [DEC[13], DEC[14]], "NOTL3")
    g("04", [DEC[14]], "L1ONLY")
    nl.add("157", "U_FITS", S="PC1", G="GND",
           **{"1A": "NOTL3", "1B": "L1ONLY", "1Y": "FITS1",
              "2A": "GND", "2B": "GND", "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    g("04", ["FITS1"], "FITS1_n")
    g("08", ["QW1", "FITS1"], "QC1")
    g("32", ["QW2", "QC1"], "QCW")
    g("08", ["QCW", "JUMP_n"], "COMPLETE")
    g("04", ["COMPLETE"], "COMPLETE_n")
    # jump: LDPC, always / on the branch condition / on not CL
    nl.add("153", "U_JUMP", A=u["PCCOND0"], B=u["PCCOND1"],
           **{"1G": "GND", "2G": "VCC", "1C0": "VCC", "1C1": "BCOND", "1C2": "CL_n",
              "1C3": "GND", "1Y": "JC", "2C0": "GND", "2C1": "GND", "2C2": "GND", "2C3": "GND"})
    g("08", [u["LDPC"], "JC"], "JUMP")
    g("04", ["JUMP"], "JUMP_n")
    nl.add("74", "U_TS", **{"1D": "TS_D", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "RESET_n",
                            "1Q": "TSQ", "1QN": "TSQ_n",
                            "2D": "GND", "2CLK": "GND", "2PRE": "VCC", "2CLR": "VCC"})

    nl.section("Interrupt request")
    # synchronised, then held a cycle more: pending = that & I (now)
    nl.add("74", "U_IRQ", nocheck=True,
           **{"1D": "IRQ", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "RESET_n", "1Q": "IRQS",
              "2D": "IRQS", "2CLK": "CLK", "2PRE": "VCC", "2CLR": "RESET_n", "2Q": "IRQS2"})
    g("08", ["IRQS2", "IFLAG"], "IRQP")
    g("04", ["IRQP"], "IRQP_n")

    # ---- register file -----------------------------------------------------------
    # two copies of 16K x 32 ({G, bank, register}); read through latches in
    # the cycle's first part, written in its last tick
    nl.section("Register file")
    g("32", [u["UBR"], "SFLAG_n"], "USEBR")
    g("32", [u["UBW"], "SFLAG_n"], "USEBW")
    EBR = bus("EBR", 8)
    for i in range(8):
        g("08", [BANK[i], "USEBR"], EBR[i])
    g("11", [u["RFW0"], u["RFW1"], u["RFKW5"]], "GW")
    g("04", ["GW"], "GW_n")
    RWA = bus("RWA", 13) + ["GW"]
    for k in range(2):
        m = nl.add("153", f"U_RFWM{k}", A=u["RFW0"], B=u["RFW1"], **{"1G": "GND", "2G": "GND"})
        for sec in (0, 1):
            i = 2 * k + sec
            for c, s in enumerate([IR[12 + i], IR[8 + i], SX[i], u[f"RFKW{i}"]]):
                m[f"{sec + 1}C{c}"] = s
            m[f"{sec + 1}Y"] = RWA[i]
    g("11", [u["RFW0"], u["RFW1"], u["RFKW4"]], RWA[4])
    for i in range(8):
        g("11", [BANK[i], "USEBW", "GW_n"], RWA[5 + i])
    g("10", [u["RFWE"], "T1", "FAULT_n"], "RFWE_n")
    g("00", [u["RFWE"], "T1"], "RFWB_n")
    for side, sel, out, oe in (("A", "RFA", ABUS, u["ARF_n"]), ("B", "RFB", BBUS, u["BRF_n"])):
        g("11", [u[f"{sel}0"], u[f"{sel}1"], u["RFK5"]], f"G{side}")
        g("04", [f"G{side}"], f"G{side}_n")
        RA = bus(f"RF{side}A", 13) + [f"G{side}"]
        for k in range(2):
            m = nl.add("153", f"U_RF{side}M{k}", A=u[f"{sel}0"], B=u[f"{sel}1"],
                       **{"1G": "GND", "2G": "GND"})
            for sec in (0, 1):
                i = 2 * k + sec
                for c, s in enumerate([IR[12 + i], IR[8 + i], SX[i], u[f"RFK{i}"]]):
                    m[f"{sec + 1}C{c}"] = s
                m[f"{sec + 1}Y"] = RA[i]
        g("11", [u[f"{sel}0"], u[f"{sel}1"], u["RFK4"]], RA[4])
        for i in range(8):
            g("08", [EBR[i], f"G{side}_n"], RA[5 + i])
        AM = bus(f"RF{side}M", 14)
        for k in range(4):
            m = nl.add("157", f"U_RF{side}S{k}", S="RW", G="GND")
            for j in range(4):
                i = 4 * k + j
                if i < 14:
                    m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = RA[i], RWA[i], AM[i]
                else:
                    m[f"{j + 1}A"], m[f"{j + 1}B"] = "GND", "GND"
        IO = bus(f"RF{side}IO", 32)
        for k in range(4):
            ram = nl.add("sram64k", f"U_RF{side}{k}", role="rf", CE="GND", OE="RW", WE="RFWE_n")
            for i in range(16):
                ram[f"A{i}"] = AM[i] if i < 14 else "GND"
            for i in range(8):
                ram[f"IO{i}"] = IO[8 * k + i]
            lat = nl.add("573", f"U_RL{side}{k}", LE="RW_n", OE=oe)
            buf = nl.add("541", f"U_RW{side}{k}", OE1="RFWB_n", OE2="GND")
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
                             (f"U_AR2{k}", R2, u["AR2_n"]), (f"U_AMAR{k}", MAR, u["AMAR_n"])):
            b = nl.add("541", ref, OE1=oe, OE2="GND")
            for i in range(8):
                b[f"A{i + 1}"], b[f"Y{i + 1}"] = src[8 * k + i], ABUS[8 * k + i]

    # ---- B bus -------------------------------------------------------------------
    nl.section("B bus")
    for k in range(4):
        b = nl.add("541", f"U_BR{k}", OE1=u["BR_n"], OE2="GND")
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = RQ[8 * k + i], BBUS[8 * k + i]
    # T by lanes (BL 1 word, 2 half, 3 byte, moved down to the low lanes by
    # TL, the access's address), and the queue's head (4 as it is, 5 x 2,
    # 6 in the upper half, 7 its low byte)
    bl = nl.add("138", "U_BLD", A=u["BL0"], B=u["BL1"], C=u["BL2"], G1="VCC", G2A="GND", G2B="GND")
    for v, name in ((1, "BLW_n"), (2, "BLH_n"), (3, "BLB_n"), (4, "BLQ_n"), (5, "BLQ2_n"),
                    (6, "BLQH_n"), (7, "BLQB_n")):
        bl[f"Y{v}"] = name
    nl.add("138", "U_TLD", A="TL0", B="TL1", C="GND", G1="VCC", G2A="BLB_n", G2B="GND",
           Y0="TB0_n", Y1="TB1_n", Y2="TB2_n", Y3="TB3_n")
    g("04", ["BLH_n"], "BLH")
    g("04", ["TL1"], "TL1_n")
    g("00", ["BLH", "TL1_n"], "TH0_n")
    g("00", ["BLH", "TL1"], "TH1_n")
    g("11", ["BLW_n", "TH0_n", "TB0_n"], "BT0_n")
    g("08", ["BLW_n", "TH0_n"], "BT1_n")
    g("08", ["TH1_n", "TB2_n"], "BT20_n")
    g("08", ["BLQ_n", "BLQB_n"], "BQ0_n")
    tb = [TQ[8 * k:8 * k + 8] for k in range(4)]
    QH2 = ["GND"] + QH[:15]
    for ref, src, dst, oe in (("U_BT0", tb[0], 0, "BT0_n"), ("U_BT1", tb[1], 1, "BT1_n"),
                              ("U_BT2", tb[2], 2, "BLW_n"), ("U_BT3", tb[3], 3, "BLW_n"),
                              ("U_BT20", tb[2], 0, "BT20_n"), ("U_BT31", tb[3], 1, "TH1_n"),
                              ("U_BT10", tb[1], 0, "TB1_n"), ("U_BT30", tb[3], 0, "TB3_n"),
                              ("U_BQ0", QH[0:8], 0, "BQ0_n"), ("U_BQ1", QH[8:16], 1, "BLQ_n"),
                              ("U_BQ20", QH2[0:8], 0, "BLQ2_n"), ("U_BQ21", QH2[8:16], 1, "BLQ2_n"),
                              ("U_BQH2", QH[0:8], 2, "BLQH_n"), ("U_BQH3", QH[8:16], 3, "BLQH_n")):
        b = nl.add("541", ref, OE1=oe, OE2="GND")
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = src[i], BBUS[8 * dst + i]

    nl.section("Immediate unit")
    nl.add("151", "U_FILLM", A=u["FSEL0"], B=u["FSEL1"], C=u["FSEL2"], G="GND", Y="FILL",
           D0="GND", D1="VCC", D2=IR[15], D3=QH[15], D4=QH[7], D5=ABUS[31], D6=ABUS[15],
           D7="SGNQ")
    for i in range(4):
        g("04", [IR[8 + i]], f"IRN{8 + i}")
    V8 = bus("V8", 8)
    for i in range(8):
        srcs = [IR[i + 7] if i >= 1 else "GND", u[f"KONST{i}"], "FILL", LC[i],
                IR[8 + i] if i < 4 else "GND", f"IRN{8 + i}" if i < 4 else "VCC",
                IR[i] if i < 3 else (IR[8 + i - 3] if i < 7 else "GND"),
                IR[8 + i - 2] if 2 <= i <= 5 else "GND"]
        nl.add("151", f"U_V8M{i}", A=u["V80"], B=u["V81"], C=u["V82"], G="GND", Y=V8[i],
               **{f"D{c}": s for c, s in enumerate(srcs)})
    for ref, src, dst, oe in (("U_BS0", V8, 0, u["BS0_n"]), ("U_BF1", ["FILL"] * 8, 1, u["BF1_n"]),
                              ("U_BF2", ["FILL"] * 8, 2, u["BF23_n"]),
                              ("U_BF3", ["FILL"] * 8, 3, u["BF23_n"])):
        b = nl.add("541", ref, OE1=oe, OE2="GND")
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = src[i], BBUS[8 * dst + i]

    nl.section("B bus")
    bx = nl.add("138", "U_BXD", A=u["BX0"], B=u["BX1"], C=u["BX2"], G1="VCC", G2A="GND",
                G2B="GND")
    for v, name in ((1, "BXMQ_n"), (2, "BXFL_n"), (3, "BXFSR_n"), (4, "BXFAR_n"), (5, "BXMAP_n")):
        bx[f"Y{v}"] = name
    b = nl.add("541", "U_BFL", OE1="BXFL_n", OE2="GND")
    for i, s in enumerate(["VFLAG", "CFLAG", "ZFLAG", "NFLAG", "IFLAG", "SFLAG", "TFLAG", "GND"]):
        b[f"A{i + 1}"], b[f"Y{i + 1}"] = s, BBUS[i]
    mapsrc = [[MD[0], MD[1], MD[2]] + ["GND"] * 5, ["GND"] * 4 + MD[3:7], MD[7:15], MD[15:23]]
    for k in range(4):
        b = nl.add("541", f"U_BMAP{k}", OE1="BXMAP_n", OE2="GND")
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = mapsrc[k][i], BBUS[8 * k + i]

    # ---- MQ ------------------------------------------------------------------------
    nl.section("MQ")
    # 4 x 74F299 on the B bus. Chip k holds bits 8k..8k+7 with I/O n = bit
    # 8k+7-n, so the shift toward Q7 is a right shift of MQ (DS0 in at the
    # top), toward Q0 a left shift (DS7 in at the bottom). Held on a fault.
    g("08", [u["MQM0"], "FAULT_n"], "MQS0")
    g("08", [u["MQM1"], "FAULT_n"], "MQS1")

    def mqs(bit):
        return {0: "MQ0", 31: "MQ31"}.get(bit, f"MQS{bit}")
    for k in range(4):
        sr = nl.add("299", f"U_MQ{k}", S0="MQS0", S1="MQS1", OE1="BXMQ_n", OE2="GND",
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
    g("32", [u["LDR_n"], "FAULT"], "RLD_n")
    for k in range(4):
        r = nl.add("377", f"U_R{k}", CLK="CLK", EN="RLD_n")
        for i in range(8):
            r[f"D{i + 1}"], r[f"Q{i + 1}"] = RES[8 * k + i], RQ[8 * k + i]
    # T, and TL (the access's address bits 1-0): latches, transparent while
    # memory is read into them, until the write phase (well before the
    # address can change)
    g("08", ["READING", "RW_n"], "TLE")
    for k in range(4):
        t = nl.add("573", f"U_T{k}", LE="TLE", OE="GND")
        for i in range(8):
            t[f"D{i + 1}"], t[f"Q{i + 1}"] = DB[8 * k + i], TQ[8 * k + i]
    nl.add("573", "U_TL", LE="TLE", OE="GND", D1=VA[0], Q1="TL0", D2=VA[1], Q2="TL1",
           **{f"D{i}": "GND" for i in range(3, 9)})

    nl.section("MAR")
    g("32", [u["LDMAR_n"], "FAULT"], "MARLD_n")
    g("08", [u["MARINC"], "FAULT_n"], "MARINCC")
    nl.add("161", "U_MARL", CLK="CLK", CLR="VCC", LOAD="MARLD_n", ENP="GND", ENT="GND",
           A=RES[0], B=RES[1], C="GND", D="GND", QA=MAR[0], QB=MAR[1])
    counter_chain(nl, "MAR", MAR, RES, 2, 8, "MARLD_n", "MARINCC")

    nl.section("Loop counter")
    g("32", [u["LDLC_n"], "FAULT"], "LCLD_n")
    g("08", [u["LCINC"], "FAULT_n"], "LCEN")
    nl.add("161", "U_LC0", CLK="CLK", CLR="VCC", LOAD="LCLD_n", ENP="LCEN", ENT="VCC",
           A=RES[0], B=RES[1], C=RES[2], D=RES[3], QA=LC[0], QB=LC[1], QC=LC[2], QD=LC[3],
           RCO="TC4")
    nl.add("161", "U_LC1", CLK="CLK", CLR="VCC", LOAD="LCLD_n", ENP="LCEN", ENT="TC4",
           A=RES[4], B=RES[5], C=RES[6], D=RES[7], QA=LC[4], QB=LC[5], QC=LC[6], QD=LC[7],
           RCO="TC")

    nl.section("SX and EX")
    for k in range(2):
        m = nl.add("153", f"U_SXM{k}", A=u["LDSX0"], B=u["LDSX1"], **{"1G": "GND", "2G": "GND"})
        for sec in (0, 1):
            i = 2 * k + sec
            for c, s in enumerate(["GND", IR[12 + i], IR[8 + i], QH[12 + i]]):
                m[f"{sec + 1}C{c}"] = s
            m[f"{sec + 1}Y"] = f"SXD{i}"
    g("32", [u["LDSX0"], u["LDSX1"]], "LDSXNZ")
    g("00", ["LDSXNZ", "FAULT_n"], "SXLD_n")
    g("08", [u["SXINC"], "FAULT_n"], "SXEN")
    nl.add("161", "U_SX", CLK="CLK", CLR="VCC", LOAD="SXLD_n", ENP="SXEN", ENT="VCC",
           A="SXD0", B="SXD1", C="SXD2", D="SXD3", QA=SX[0], QB=SX[1], QC=SX[2], QD=SX[3])
    m = nl.add("157", "U_EXM", S=u["LDEX1"], G="GND")
    for j in range(4):
        m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = IR[8 + j], QH[12 + j], f"EXD{j}"
    g("32", [u["LDEX0"], u["LDEX1"]], "LDEXNZ")
    g("00", ["LDEXNZ", "FAULT_n"], "EXLD_n")
    nl.add("377", "U_EX", CLK="CLK", EN="EXLD_n",
           **{f"D{j + 1}": f"EXD{j}" for j in range(4)}, **{f"Q{j + 1}": EX[j] for j in range(4)},
           **{f"D{j}": "GND" for j in range(5, 9)})
    nl.add("688", "U_SXEQ", G="GND", PEQ="SXEQ_n",
           **{f"P{i}": SX[i] if i < 4 else "GND" for i in range(8)},
           **{f"Q{i}": EX[i] if i < 4 else "GND" for i in range(8)})
    g("04", ["SXEQ_n"], "SXEQ")
    g("21", SX, "SX15")

    nl.section("Faults")
    nl.add("377", "U_CTX", CLK="CLK", EN="CTXLD_n",
           **{f"D{i + 1}": RES[i] for i in range(7)}, **{f"Q{i + 1}": CTX[i] for i in range(7)},
           D8="GND")
    nl.add("377", "U_BANK", CLK="CLK", EN="BANKLD_n",
           **{f"D{i + 1}": RES[i] for i in range(8)}, **{f"Q{i + 1}": BANK[i] for i in range(8)})
    g("00", [u["LDCTX"], "FAULT_n"], "CTXLD_n")
    g("00", [u["LDBANK"], "FAULT_n"], "BANKLD_n")

    # ---- PC, FPC and the prefetch queue ----------------------------------------------
    nl.section("PC")
    g("00", ["JUMP", "FAULT_n"], "PCLD_n")
    g("32", [u["CONSUME"], "DECGO"], "CONS")
    g("11", ["CONS", "FAULT_n", "JUMP_n"], "CONSUMEX")
    counter_chain(nl, "PC", PC, RES, 1, 8, "PCLD_n", "CONSUMEX")
    counter_chain(nl, "FPC", FPC, RES, 2, 8, "PCLD_n", "FPCINC")

    nl.section("Prefetch queue")
    # a fetch: a cycle without a data access, room in the queue, a page the
    # fetch may use, in the card's RAM
    g("21", ["FETCHCYC", "V1_n", "XFAULT_n", "LOCAL"], "FETCHED")
    g("11", ["FETCHED", "FAULT_n", "JUMP_n"], "FPCINC")
    g("08", ["CONSUMEX", "PC1"], "SHIFT")
    g("04", ["SHIFT"], "SHIFT_n")
    g("08", ["V0_n", "FPCINC"], "Q0NEW")
    g("02", ["SHIFT", "Q0NEW"], "QALD_n")
    g("10", ["FPCINC", "V0", "SHIFT_n"], "QBLD_n")
    QAD = bus("QAD", 32)
    for k in range(8):
        m = nl.add("157", f"U_QAM{k}", S="V1", G="GND")
        for j in range(4):
            i = 4 * k + j
            m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = DB[i], QB[i], QAD[i]
    for k in range(4):
        ra = nl.add("377", f"U_QA{k}", CLK="CLK", EN="QALD_n")
        rb = nl.add("377", f"U_QB{k}", CLK="CLK", EN="QBLD_n")
        for i in range(8):
            ra[f"D{i + 1}"], ra[f"Q{i + 1}"] = QAD[8 * k + i], QA[8 * k + i]
            rb[f"D{i + 1}"], rb[f"Q{i + 1}"] = DB[8 * k + i], QB[8 * k + i]
    # V0, V1: a jump empties the queue, a fault leaves it
    g("32", ["V1", "FETCHED"], "VF")
    g("08", ["V0", "VF"], "V0VF")
    g("32", ["V0", "FETCHED"], "V0ORF")
    nl.add("157", "U_VNX", S="SHIFT", G="GND",
           **{"1A": "V0ORF", "1B": "V0VF", "1Y": "V0X", "2A": "GND", "2B": "GND",
              "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    g("08", ["V0VF", "SHIFT_n"], "V1X")
    g("08", ["FAULT_n", "JUMP_n"], "QCOMMIT")
    for v in ("V0", "V1"):
        g("08", ["FAULT", v], f"{v}H")
        g("08", ["QCOMMIT", f"{v}X"], f"{v}N")
        g("32", [f"{v}H", f"{v}N"], f"{v}_D")
    nl.add("74", "U_V", **{"1D": "V0_D", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "VCC",
                           "1Q": "V0", "1QN": "V0_n",
                           "2D": "V1_D", "2CLK": "CLK", "2PRE": "VCC", "2CLR": "VCC",
                           "2Q": "V1", "2QN": "V1_n"})
    # the head parcel: Q0's half, or the word this cycle fetches if the queue is empty
    for k in range(8):
        m = nl.add("153", f"U_QH{k}", A="V0", B="PC1", **{"1G": "GND", "2G": "GND"})
        for sec in (0, 1):
            i = 2 * k + sec
            for c, s in enumerate([DB[i], QA[i], DB[16 + i], QA[16 + i]]):
                m[f"{sec + 1}C{c}"] = s
            m[f"{sec + 1}Y"] = QH[i]

    # ---- memory: the virtual address, the map, the window, faults, RAM ----------------------
    nl.section("Memory")
    md = nl.add("138", "U_MEMD", A=u["MEM0"], B=u["MEM1"], C=u["MEM2"], G1="VCC", G2A="GND",
                G2B="GND")
    for v in range(8):
        md[f"Y{v}"] = f"MEM{v}_n"
    g("00", ["MEM1_n", "MEM6_n"], "READING")
    g("04", ["READING"], "READING_n")
    g("10", ["MEM1_n", "MEM2_n", "MEM6_n"], "XLATE")
    g("04", ["XLATE"], "XLATE_n")
    g("00", ["MEM0_n", "MEM3_n"], "FETCHCYC")
    g("00", ["MEM4_n", "MEM5_n"], "MAPACC")
    g("04", ["MEM3_n"], "MEM3")
    g("04", ["MEM2_n"], "MEMWR")
    g("04", ["MEM5_n"], "MAPW")
    g("04", ["MEM6_n"], "MEM6")
    # the virtual address: MAR, FPC (fetch cycles) or the A bus (a read at the A bus)
    for k in range(16):
        m = nl.add("153", f"U_VAM{k}", A="FETCHCYC", B="MEM6", **{"1G": "GND", "2G": "GND"})
        for sec in (0, 1):
            i = 2 * k + sec
            for c, s in enumerate([MAR[i], FPC[i], ABUS[i], "GND"]):
                m[f"{sec + 1}C{c}"] = s
            m[f"{sec + 1}Y"] = VA[i]
    # the page map: {CTX, VA[23:12]}, or MAR[30:12] for MFSR/MTSR mapd
    MA = bus("MA", 19)
    for k in range(2):
        m = nl.add("157", f"U_MAM{k}", S="MAPACC", G="GND")
        for j in range(4):
            i = 4 * k + j
            if i < 7:
                m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = CTX[i], MAR[24 + i], MA[12 + i]
            else:
                m[f"{j + 1}A"], m[f"{j + 1}B"] = "GND", "GND"
    g("00", ["MAPW", "MWIN"], "MAPWE_n")
    for k in range(3):
        ram = nl.add("sram512", f"U_MAP{k}", role="fastram", CE="GND", OE="MAPW", WE="MAPWE_n")
        for i in range(19):
            ram[f"A{i}"] = VA[12 + i] if i < 12 else MA[i]
        for i in range(8):
            ram[f"IO{i}"] = MD[8 * k + i]
    # the entry from B, inside the write window: the map's outputs are off
    # from the cycle's start
    g("04", ["MWIN"], "MWIN_n")
    mdsrc = BBUS[0:3] + BBUS[12:32] + ["GND"]
    for k in range(3):
        b = nl.add("541", f"U_MWB{k}", OE1="MEM5_n", OE2="MWIN_n")
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = mdsrc[8 * k + i], MD[8 * k + i]
    # translation (RFC 0029, 3): the window, or the map's page
    g("08", [VA[31], "SFLAG"], "WIN")
    win = VA[12:31] + ["GND"]
    for k in range(5):
        m = nl.add("157", f"U_PAM{k}", S="WIN", G="GND")
        for j in range(4):
            i = 4 * k + j
            m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = MD[3 + i], win[i], PA[12 + i]
    nl.add("688", "U_VAHI", G="GND", PEQ="VAHINZ",
           **{f"P{i}": VA[24 + i] if i < 7 else "GND" for i in range(8)},
           **{f"Q{i}": "GND" for i in range(8)})
    g("04", [VA[31]], "VA31_n")
    g("08", [VA[31], "SFLAG_n"], "R_USER")
    g("08", ["VA31_n", "VAHINZ"], "R_RANGE")
    g("02", [VA[31], "VAHINZ"], "MAPPED")
    for i in range(3):
        g("04", [MD[i]], f"MD{i}_n")
    g("08", ["MAPPED", "MD0_n"], "R_INV")
    g("08", ["MAPPED", MD[0]], "MAPV")
    g("11", ["MAPV", "MEMWR", "MD1_n"], "R_NOW")
    g("11", ["MAPV", "FETCHCYC", "MD2_n"], "R_NOX")
    g("32", ["R_USER", "R_RANGE"], "XF1")
    g("32", ["R_INV", "R_NOW"], "XF2")
    g("32", ["XF1", "XF2"], "XF3")
    g("32", ["XF3", "R_NOX"], "XFAULT")
    g("04", ["XFAULT"], "XFAULT_n")
    # alignment, by size
    g("04", [u["SIZE0"]], "SIZE0_n")
    g("04", [u["SIZE1"]], "SIZE1_n")
    g("08", [u["SIZE0"], u["SIZE1"]], "WORD")
    g("08", ["SIZE0_n", u["SIZE1"]], "HALF")
    g("08", [u["SIZE0"], "SIZE1_n"], "BYTE")
    g("04", ["WORD"], "WORD_n")
    g("04", ["HALF"], "HALF_n")
    g("04", ["BYTE"], "BYTE_n")
    g("32", [VA[0], VA[1]], "VA01")
    g("08", ["WORD", "VA01"], "MISW")
    g("08", ["HALF", VA[0]], "MISH")
    g("32", ["MISW", "MISH"], "MIS1")
    g("08", ["MIS1", "XLATE"], "MISALIGN")
    g("04", ["MISALIGN"], "MISALIGN_n")
    # what answers: the card's RAM (slot 0) or the I/O page (slot 15)
    g("32", [PA[27], PA[28]], "SL1")
    g("32", [PA[29], PA[30]], "SL2")
    g("32", ["SL1", "SL2"], "SL3")
    g("02", ["SL3", PA[31]], "LOCAL")
    g("04", ["LOCAL"], "LOCAL_n")
    g("21", PA[27:31], "SLOT15")
    g("04", [PA[31]], "PA31_n")
    g("08", ["SLOT15", "PA31_n"], "IOSLOT")
    g("02", ["LOCAL", "IOSLOT"], "NOANS")
    # a fault: a data access misaligned, not translated or not answered; a
    # refill's fetch that fails when the decode needs its word
    g("32", ["MISALIGN", "XFAULT"], "DF1")
    g("32", ["DF1", "NOANS"], "DF2")
    g("08", ["DF2", "XLATE"], "DFAULT")
    g("32", ["XFAULT", "LOCAL_n"], "FFR")
    g("32", ["V0_n", "FITS1_n"], "FNEED")
    g("11", ["MEM3", "V1_n", "FFR"], "FF1")
    g("08", ["FF1", "FNEED"], "FFAULT")
    g("32", ["DFAULT", "FFAULT"], "FAULT")
    g("04", ["FAULT"], "FAULT_n")
    # FK: 0 page fault, 1 misaligned, 2 bus error; FSR for a page fault; FAR
    g("11", ["MISALIGN_n", "XFAULT_n", "LOCAL_n"], "FK1_D")
    nl.add("377", "U_FK", CLK="CLK", EN="FAULT_n", D1="MISALIGN", Q1="FK0", D2="FK1_D", Q2="FK1",
           **{f"D{i}": "GND" for i in range(3, 9)})
    g("10", ["FAULT", "XFAULT", "MISALIGN_n"], "FSRLD_n")
    fsr = nl.add("823", "U_FSR", CLK="CLK", EN="FSRLD_n", CLR="VCC", OE="BXFSR_n", D9="GND")
    for i, s in enumerate(["R_INV", "R_NOW", "R_NOX", "R_RANGE", "R_USER", "MEMWR", "FETCHCYC",
                           "SFLAG"]):
        fsr[f"D{i + 1}"], fsr[f"Q{i + 1}"] = s, BBUS[i]
    for k in range(4):
        far = nl.add("823", f"U_FAR{k}", CLK="CLK", EN="FAULT_n", CLR="VCC", OE="BXFAR_n",
                     D9="GND")
        for i in range(8):
            far[f"D{i + 1}"], far[f"Q{i + 1}"] = VA[8 * k + i], BBUS[8 * k + i]
    # byte enables, from the size and VA[1:0]
    nl.add("138", "U_BYTED", A=VA[0], B=VA[1], C="GND", G1="BYTE", G2A="GND", G2B="GND",
           Y0="BYT0_n", Y1="BYT1_n", Y2="BYT2_n", Y3="BYT3_n")
    g("04", [VA[1]], "VA1_n")
    g("08", ["HALF", "VA1_n"], "HLO")
    g("08", ["HALF", VA[1]], "HHI")
    g("02", ["WORD", "HLO"], "WHL_n")
    g("02", ["WORD", "HHI"], "WHH_n")
    for k, wh in enumerate(["WHL_n", "WHL_n", "WHH_n", "WHH_n"]):
        g("08", [wh, f"BYT{k}_n"], f"BE{k}_n")
        g("04", [f"BE{k}_n"], f"BE{k}")
    # the RAM: 2 MB, slot 0 (repeated)
    g("32", ["READING", "FETCHCYC"], "RDF")
    g("00", ["LOCAL", "RDF"], "RAMOE_n")
    g("11", ["MEMWR", "FAULT_n", "LOCAL"], "MWOK")
    for k in range(4):
        g("10", ["MWOK", "MWIN", f"BE{k}"], f"WE{k}_n")
        ram = nl.add("sram512", f"U_RAM{k}", role="fastram", CE="LOCAL_n", OE="RAMOE_n",
                     WE=f"WE{k}_n")
        for i in range(19):
            ram[f"A{i}"] = PA[2 + i]
        for i in range(8):
            ram[f"IO{i}"] = DB[8 * k + i]
    # store data: the A bus, replicated by size
    nl.section("Store data")
    a8 = [ABUS[8 * k:8 * k + 8] for k in range(4)]
    for ref, src, dst, oe2 in (("U_SD0", a8[0], 0, "GND"), ("U_SD1", a8[1], 1, "BYTE"),
                               ("U_SDB1", a8[0], 1, "BYTE_n"), ("U_SD2", a8[2], 2, "WORD_n"),
                               ("U_SDB2", a8[0], 2, "WORD"), ("U_SD3", a8[3], 3, "WORD_n"),
                               ("U_SDH3", a8[1], 3, "HALF_n"), ("U_SDB3", a8[0], 3, "BYTE_n")):
        b = nl.add("541", ref, OE1="MEM2_n", OE2=oe2)
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = src[i], DB[8 * dst + i]
    # the I/O page: a fixture, on the card's data bus
    g("02", ["MISALIGN", "XFAULT"], "XOK")
    g("10", ["IOSLOT", "XLATE", "XOK"], "IOSEL_n")
    g("00", ["MEMWR", "MWIN"], "IOWR_n")
    if sim:
        io = nl.add("iodev_w32", "X_IO", CLK="CLK", IOSEL="IOSEL_n", RD="READING_n", WR="IOWR_n",
                    IRQ="IRQ")
        for i in range(2, 8):
            io[f"A{i}"] = VA[i]
        for i in range(4):
            io[f"BE{i}"] = f"BE{i}_n"
        for i in range(32):
            io[f"D{i}"] = DB[i]
    else:
        nl.add("const", "X_STUB", LO="IRQ")

    # ---- flags -------------------------------------------------------------------------
    nl.section("Flags")
    for k in range(4):
        nl.add("688", f"U_Z{k}", G="GND", PEQ=f"ZB{k}_n",
               **{f"P{i}": RES[8 * k + i] for i in range(8)}, **{f"Q{i}": "GND" for i in range(8)})
    g("32", ["ZB0_n", "ZB1_n"], "NZ01")
    g("32", ["ZB2_n", "ZB3_n"], "NZ23")
    g("02", ["NZ01", "NZ23"], "ZERO")
    g("02", ["NZ23", "GND"], "HZ16")                   # RES[31:16] == 0
    g("02", ["NZ23", RES[15]], "HZ17")                 # RES[31:15] == 0
    g("08", ["ZFLAG", "ZERO"], "ZSTICKY")
    nl.add("153", "U_NSEL", A=u["NSEL0"], B=u["NSEL1"],
           **{"1G": "GND", "2G": "VCC", "1C0": RES[31], "1C1": RES[15], "1C2": RES[7],
              "1C3": "GND", "1Y": "NSELV", "2C0": "GND", "2C1": "GND", "2C2": "GND", "2C3": "GND"})
    nl.add("153", "U_FNZ", A=u["FNZ0"], B=u["FNZ1"],
           **{"1G": "GND", "2G": "GND",
              "1C0": "NFLAG", "1C1": "NSELV", "1C2": "NSELV", "1C3": ABUS[3], "1Y": "NNEXT",
              "2C0": "ZFLAG", "2C1": "ZERO", "2C2": "ZSTICKY", "2C3": ABUS[2], "2Y": "ZNEXT"})
    g("86", [F[7], "FILL"], "F7X")
    g("86", [F[15], "FILL"], "F15X")
    nl.add("151", "U_CSRC", A=u["CSRC0"], B=u["CSRC1"], C=u["CSRC2"], G="GND", Y="CSRCY",
           D0=ABUS[1], D1=F[0], D2=F[7], D3=F[8], D4=F[15], D5=F[31], D6="F7X", D7="F15X")
    nl.add("153", "U_FC", A=u["FC0"], B=u["FC1"],
           **{"1G": u["CZERO"], "2G": "VCC",
              "1C0": "CFLAG", "1C1": "CSRCY", "1C2": "C32", "1C3": "CL_n", "1Y": "CNEXT",
              "2C0": "GND", "2C1": "GND", "2C2": "GND", "2C3": "GND"})
    nl.add("153", "U_FI", A=u["FI0"], B=u["FI1"],
           **{"1G": "GND", "2G": "VCC",
              "1C0": "IFLAG", "1C1": "VCC", "1C2": "GND", "1C3": ABUS[4], "1Y": "INEXT1",
              "2C0": "GND", "2C1": "GND", "2C2": "GND", "2C3": "GND"})
    # V: FV 7 selects VT3 = A31 ^ F31, with the multiplexer off (output 0)
    # unless the operands' signs allow an overflow (VT2)
    g("10", [u["FV0"], u["FV1"], u["FV2"]], "FVOVF_n")
    g("02", ["FVOVF_n", "VT2"], "FVOFF")
    nl.add("151", "U_FV", A=u["FV0"], B=u["FV1"], C=u["FV2"], G="FVOFF", Y="VNEXT",
           D0="VFLAG", D1="GND", D2="GND", D3=ABUS[0], D4="CL_n", D5="VCC", D6="GND", D7="VT3")
    # S, T, I: a flags load (FNZ 3) takes T and I with LFM 1 or 2, S with 2;
    # exception entry (SSET) sets S and clears I and T
    g("08", [u["FNZ0"], u["FNZ1"]], "LOADF")
    g("32", [u["LFM0"], u["LFM1"]], "LFMNZ")
    g("08", ["LOADF", "LFMNZ"], "TLOAD")
    g("08", ["LOADF", u["LFM1"]], "SLOAD")
    g("04", [u["SSET"]], "SSET_n")
    nl.add("157", "U_STM", G="GND", S="TLOAD",
           **{"1A": "TFLAG", "1B": ABUS[6], "1Y": "TN",
              "2A": "GND", "2B": "GND", "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    nl.add("157", "U_SSM", G="GND", S="SLOAD",
           **{"1A": "SFLAG", "1B": ABUS[5], "1Y": "SN",
              "2A": "GND", "2B": "GND", "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    g("08", ["TN", "SSET_n"], "TNEXT")
    g("32", ["SN", u["SSET"]], "SNEXT")
    g("08", ["INEXT1", "SSET_n"], "INEXT2")
    nl.add("377", "U_FLAGS", CLK="CLK", EN="FAULT",
           D1="NNEXT", Q1="NFLAG", D2="ZNEXT", Q2="ZFLAG", D3="CNEXT", Q3="CFLAG",
           D4="VNEXT", Q4="VFLAG", D5="INEXT2", Q5="IFLAG", D6="SNEXT", Q6="SFLAG",
           D7="TNEXT", Q7="TFLAG", D8="GND")
    for f in ("Z", "C", "V", "S"):
        g("04", [f"{f}FLAG"], f"{f}FLAG_n")

    nl.section("Condition latches")
    # CL, SGN, S33; CLSRC 4 and 5 AND the test with CL
    g("08", [u["CLSRC2"], "CL_n"], "CLOFF")
    nl.add("151", "U_CLM", A=u["CLSRC0"], B=u["CLSRC1"], C=u["CLSRC2"], G="CLOFF", Y="CLSRCY",
           D0="ZERO", D1="C32", D2="HZ16", D3="HZ17", D4="HZ16", D5="HZ17", D6="GND", D7="GND")
    g("08", [u["LDCL"], "FAULT_n"], "LDCLC")
    g("08", [u["LDSGN"], "FAULT_n"], "LDSGNC")
    nl.add("153", "U_LATM", A="LDCLC", B="LDSGNC", **{"1G": "GND", "2G": "GND",
           "1C0": "CLQ", "1C1": "CLSRCY", "1C2": "CLQ", "1C3": "CLSRCY", "1Y": "CL_D",
           "2C0": "SGNQ", "2C1": "SGNQ", "2C2": "FILL", "2C3": "FILL", "2Y": "SGN_D"})
    # divide step: S33 = R31 ^ C32 ^ (subtracting = not S33); the quotient
    # bit is its complement. MQ loads clear S33.
    g("86", [RQ[31], "S33_n"], "RG")
    g("04", ["RG"], "RG_n")
    g("86", ["RG", "CARRY_n"], "QBIT")
    g("86", ["RG_n", "CARRY_n"], "S33NEW")
    g("04", [u["MQM0"]], "MQM0_n")
    g("11", ["MQM0_n", u["MQM1"], "FAULT_n"], "DIVSTEPC")
    g("10", [u["MQM0"], u["MQM1"], "FAULT_n"], "MQLOADC_n")
    g("08", ["S33Q", "MQLOADC_n"], "S33KEEP")
    nl.add("157", "U_S33MX", S="DIVSTEPC", G="GND",
           **{"1A": "S33KEEP", "1B": "S33NEW", "1Y": "S33_D",
              "2A": "GND", "2B": "GND", "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    nl.add("74", "U_LAT0", **{"1D": "CL_D", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "VCC",
                              "1Q": "CLQ", "1QN": "CL_n",
                              "2D": "SGN_D", "2CLK": "CLK", "2PRE": "VCC", "2CLR": "VCC",
                              "2Q": "SGNQ"})
    nl.add("74", "U_LAT1", **{"1D": "S33_D", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "VCC",
                              "1Q": "S33Q", "1QN": "S33_n",
                              "2D": "GND", "2CLK": "GND", "2PRE": "VCC", "2CLR": "VCC"})

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
    g("86", ["NFLAG", "VFLAG_n"], "N_EQ_V")
    g("08", ["ZFLAG_n", "N_EQ_V"], "C_GT")
    nl.add("151", "U_COND", A=CC[1], B=CC[2], C=CC[3], G="GND", Y="CONDT", W="CONDT_n",
           D0="ZFLAG", D1="CFLAG", D2="NFLAG", D3="VFLAG", D4="C_HI", D5="N_EQ_V", D6="C_GT",
           D7="VCC")
    g("86", ["CONDT_n", CC[0]], "BCOND_n")
    g("04", ["BCOND_n"], "BCOND")

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
