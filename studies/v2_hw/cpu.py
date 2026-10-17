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
            nets[bit + i] = f"u{name}{i if w > 1 else ''}{'_n' if al >> i & 1 else ''}"
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
    g("14", ["RSTI"], "RSTA_n")
    # asserted at once, released at a CLK edge: everything, the card's
    # registers too, sees the same last edge of reset
    nl.add("74", "U_RSY", **{"1D": "VCC", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "RSTA_n",
                             "1Q": "RSY1", "2D": "RSY1", "2CLK": "CLK", "2PRE": "VCC",
                             "2CLR": "RSTA_n", "2Q": "RESET_n"})

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
    # T1, H0, H1: the tick after the count's carry, and one and two ticks
    # later. Nothing resets them, and with 4-tick cycles two pulses could
    # chase each other round (T1 and H0 each two ticks wide, the clock's
    # edge inside the register file's write): H0 never stays on two ticks,
    # so the second pulse dies whatever the flops powered up as
    nl.add("175", "U_TH", CLK="MCLK", CLR="VCC",
           **{"1D": "TCRCO", "1Q": "T1", "1QN": "T1_n",
              "2D": "H0_D", "2Q": "H0", "2QN": "H0_n",
              "3D": "H0", "3Q": "H1", "3QN": "H1_n",
              "4D": "CLK_D", "4Q": "CLK"})
    g("08", ["T1", "H0_n"], "H0_D")
    g("32", ["T1", "H0"], "CLK_D")
    # H2, H3: H1 a tick and two later; the write window opens entering
    # tick 4, once a write's address has been translated and checked
    nl.add("175", "U_TH2", CLK="MCLK", CLR="VCC",
           **{"1D": "H1", "1Q": "H2", "2D": "H2", "2Q": "H3", "3D": "GND", "4D": "GND"})
    # (not in a cycle whose tail is tick 3: H3 and T1 at once would toggle MID)
    g("08", ["H3", "T1_n"], "MIDJ")
    nl.add("109", "U_WIN",
           **{"1J": "MIDJ", "1K": "T1_n", "1CLK": "MCLK", "1PRE": "VCC", "1CLR": "VCC",
              "1Q": "MID",
              "2J": "TCRCO", "2K": "H0_n", "2CLK": "MCLK", "2PRE": "VCC", "2CLR": "VCC",
              "2QN": "TAILX_n"})
    g("08", ["MID", "TAILX_n"], "MWIN")
    g("32", ["TCRCO", "T1"], "RW")
    # LATE: from tick 2, when a read's RAM outputs are off; the store data
    # drives the card's data bus only then
    g("02", ["H0", "H1"], "LATE")


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
    LC, SX, EX = bus("LC", 8), bus("SX", 4), bus("EX", 4)
    BANK, CTX = bus("BANK", 8), bus("CTX", 7)

    # ---- clock, reset, rails ------------------------------------------------------
    if sim:
        clock_generator(nl, lengths, por_ps)
    else:
        nl.add("tickclk", "X_CLK", CLK="CLK", MWIN="MWIN", LATE="LATE", RW="RW", RSTB="T1",
               RESET="RESET_n")
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
        r = nl.add("16374h", f"U_UIR{k}", CLK="CLK", OE="GND")
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
        r = nl.add("16823h", f"U_IR{half}", CLK="CLK", EN="DECGO_n", CLR="VCC", OE="GND", D9="GND")
        for i in range(8):
            r[f"D{i + 1}"], r[f"Q{i + 1}"] = QH[8 * half + i], IR[8 * half + i]
    nl.add("16823h", "U_LEN", CLK="CLK", EN="DECGO_n", CLR="VCC", OE="GND",
           D1=DEC[13], Q1="LEN0", D2=DEC[14], Q2="LEN1", **{f"D{i}": "GND" for i in range(3, 10)})
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
           D0="SFLAG", D1="SXEQ", D2="FK0", D3="FK1", D4="SX15", D5="MQ0", D6=RQ[0], D7="MSGT")
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
    g("11", ["DECACT", "TSQ_n", "PEND"], "FIRQD")
    g("08", ["HALTACT", "PEND"], "FIRQH")
    g("32", ["FIRQD", "FIRQH"], "FIRQ")
    g("11", ["DECACT", "TSQ_n", "PEND_n"], "DECOK")
    # the refill entry: the instruction isn't all there, or the cycle jumps
    g("00", ["DECOK", "COMPLETE_n"], "FREFILL_n")
    g("20", ["DECOK", u["LDPC"], "JC", "VCC"], "JDOK_n")
    g("08", ["DECOK", "JUMP_n"], "DECOKJ")
    g("11", ["DECOKJ", "COMPLETE", "FAULT_n"], "DECGO")
    g("20", ["DECOKJ", "COMPLETE", "FAULT_n", "VCC"], "DECGO_n")
    # for the PC's count and the queue's shift, a jump needn't count: the
    # PC loads, the queue empties
    g("11", ["DECOK", "COMPLETE", "FAULT_n"], "DECGOX")
    g("21", ["DECOK", "COMPLETE", "FAULT_n", "PC1F"], "DECGOP")
    # YOFF: one gate after the late ones (FAULT, the refill, a jump)
    g("27", ["RESET", "FTRACE", "FIRQ"], "YOFFE_n")
    g("20", ["DECACT", u["LDPC"], "JC", "VCC"], "JDEC_n")      # a decode that jumps
    g("20", ["YOFFE_n", "FREFILL_n", "FAULT_n", "JDEC_n"], "YOFF")
    g("32", ["FIRQ", "FTRACE"], "UF1")
    g("00", ["DECACT", "TSQ"], "FTRACE_n")
    g("20", ["FTRACE_n", "FREFILL_n", "JDOK_n", "VCC"], "UF0")
    # a fault's entry has the parcels the instruction consumed: 0 for a refill's fetch
    g("08", ["LEN0", "MEM3_n"], "LL0")
    g("08", ["LEN1", "MEM3_n"], "LL1")
    nl.add("157", "U_UM", S="FAULT", G="RESET",
           **{"1A": "UF0", "1B": "LL0", "1Y": "UA0", "2A": "UF1", "2B": "LL1", "2Y": "UA1",
              "3A": "GND", "3B": "VCC", "3Y": "UA2", "4A": "GND", "4B": "GND"})
    # the queue holds the whole next instruction: its first parcel in Q0
    # (or, in a refill, in the word it fetches), the rest there or in this
    # cycle's fetch. The decode table's length (1-3 parcels) selects which.
    g("20", ["V1_n", "PFOK_n", "RFOK_n", "VCC"], "W3")       # a second word
    g("20", ["V1_n", "PFOK_n", "RFOK_n", "PC1F"], "W2")
    g("11", ["MEM3", "V1_n", "OKNEW"], "RF1")
    g("21", ["MEM3", "V1_n", "OKNEW", "PC1F_n"], "RF2")
    nl.add("151", "U_COMPL", A=DEC[13], B=DEC[14], C="V0", G="GND", Y="COMPLETE", W="COMPLETE_n",
           D0="RF1", D1="RF1", D2="RF2", D3="GND", D4="VCC", D5="VCC", D6="W2", D7="W3")
    # whether the instruction fits in Q0 (a refill's fetch fault counts only if not)
    g("00", [DEC[13], DEC[14]], "NOTL3")
    g("04", [DEC[14]], "L1ONLY")
    nl.add("157", "U_FITS", S="PC1F", G="GND",
           **{"1A": "NOTL3", "1B": "L1ONLY", "1Y": "FITS1",
              "2A": "GND", "2B": "GND", "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    g("04", ["FITS1"], "FITS1_n")
    # jump: LDPC, always / on the branch condition / on not CL
    nl.add("153", "U_JUMP", A=u["PCCOND0"], B=u["PCCOND1"],
           **{"1G": "GND", "2G": "VCC", "1C0": "VCC", "1C1": "BCOND", "1C2": "CL_n",
              "1C3": "GND", "1Y": "JC", "2C0": "GND", "2C1": "GND", "2C2": "GND", "2C3": "GND"})
    g("08", [u["LDPC"], "JC"], "JUMP")
    g("00", [u["LDPC"], "JC"], "JUMP_n")
    nl.add("74", "U_TS", **{"1D": "TS_D", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "RESET_n",
                            "1Q": "TSQ", "1QN": "TSQ_n", "2D": "HS_D", "2CLK": "CLK",
                            "2PRE": "VCC", "2CLR": "VCC", "2Q": "HS", "2QN": "HS_n"})

    nl.section("Interrupt request")
    # RFC 0040: the CPU card's levels 1-8 (LV1_n-LV8_n, active low), its
    # message register full (MSGF) and its NMI, registered at every edge
    # (LQ); a cycle later, the decision: PEND, and with it LT, the level
    # (L, for IPL) and the vector's offset (VX, 0x40 + 4(L - 1) or the
    # NMI's 0x04), and MSGT, level 7 with a message waiting. LT holds from
    # an interrupt's entry (SSET) until I is set again or an NMI comes, so
    # that the entry sees the level it was taken for
    LQN = [f"LQ{i}_n" for i in range(1, 9)]
    nl.add("16823h", "U_RQ", CLK="CLK", EN="GND", CLR="VCC", OE="GND",
           **{f"D{i}": f"LV{i}_n" for i in range(1, 9)}, D9="MSGF",
           **{f"Q{i}": LQN[i - 1] for i in range(1, 9)}, Q9="MSGQ")
    # the highest level requesting (148: its code is ~(L - 1)), and L
    nl.add("148", "U_LVE", EI="GND", **{f"I{i}": LQN[i] for i in range(8)},
           A0="LEN_A0", A1="LEN_A1", A2="LEN_A2", GS="LGS_n")
    g("86", ["LEN_A1", "LEN_A0"], "LEV1")
    g("32", ["LEN_A1", "LEN_A0"], "LEN_A10")
    g("86", ["LEN_A2", "LEN_A10"], "LEV2")
    g("02", ["LEN_A2", "LEN_A10"], "LEV3")
    # above IPL: T_k, a level above k requesting, selected by IPL (none
    # above IPL 8 and up)
    TN = {7: LQN[7]}
    for k in range(6, -1, -1):
        g("08", [LQN[k], TN[k + 1]], f"TA{k}_n")
        TN[k] = f"TA{k}_n"
    nl.add("151", "U_IPLC", A="IPL0", B="IPL1", C="IPL2", G="GND", W="ABOVE0",
           **{f"D{k}": TN[k] for k in range(8)})
    g("04", ["IPL3"], "IPL3_n")
    g("11", ["IFLAG", "ABOVE0", "IPL3_n"], "PENDL")
    g("32", ["NMIQ", "PENDL"], "PEND_D")
    nl.add("74", "U_IRQ",
           **{"1D": "NMI", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "RESET_n", "1Q": "NMIQ",
              "1QN": "NMIQ_n", "2D": "PEND_D", "2CLK": "CLK", "2PRE": "VCC", "2CLR": "RESET_n",
              "2Q": "PEND", "2QN": "PEND_n"})
    # LT: VX = NMI ? 001 : L - 1; L; NMIT_n; MSGT, level 7 the highest, a
    # message waiting, no NMI
    g("00", ["NMIQ_n", "LEN_A0"], "VX0")
    g("02", ["NMIQ", "LEN_A1"], "VX1")
    g("02", ["NMIQ", "LEN_A2"], "VX2")
    g("04", [LQN[6]], "LQ7")
    g("21", ["LQ7", LQN[7], "MSGQ", "NMIQ_n"], "MSGT_D")
    g("32", ["IFLAG", "NMIQ"], "LTLD")
    g("00", ["LTLD", "SSET_n"], "LTLD_n")
    nl.add("16823h", "U_LT", CLK="CLK", EN="LTLD_n", CLR="VCC", OE="GND",
           D1="VX0", Q1="VX0Q", D2="VX1", Q2="VX1Q", D3="VX2", Q3="VX2Q",
           D4="LEN_A0", Q4="LT0", D5="LEV1", Q5="LT1", D6="LEV2", Q6="LT2", D7="LEV3", Q7="LT3",
           D8="NMIQ_n", Q8="NMIT_n", D9="MSGT_D", Q9="MSGT")

    # ---- register file -----------------------------------------------------------
    # two copies of 16K x 32 ({G, bank, register}); read through latches in
    # the cycle's first part, written in its last tick. Every bank has its
    # own copy of the G locations, so both copies always see the same bank
    nl.section("Register file")
    # the write address {G, bank, register}, from the IR's fields, SX or a
    # constant (RFKW); the bank in user mode or with UBW, for G too
    g("32", [u["UBW"], "SFLAG_n"], "USEBW")
    g("11", [u["RFW0"], u["RFW1"], u["RFKW5"]], "GW")
    g("04", ["GW"], "GW_n")
    RWA = bus("RWA", 13)
    for k in range(2):
        m = nl.add("153", f"U_RFWM{k}", A=u["RFW0"], B=u["RFW1"], **{"1G": "GND", "2G": "GND"})
        for sec in (0, 1):
            i = 2 * k + sec
            for c, s in enumerate([IR[12 + i], IR[8 + i], SX[i], u[f"RFKW{i}"]]):
                m[f"{sec + 1}C{c}"] = s
            m[f"{sec + 1}Y"] = RWA[i]
    g("11", [u["RFW0"], u["RFW1"], u["RFKW4"]], RWA[4])
    # A14: the message level's registers (M in supervisor mode, not with
    # UBW, not G), sixteen of their own
    g("04", ["MFLAG"], "MFLAG_n")
    g("02", ["USEBW", "MFLAG_n"], "MBW")
    g("00", ["MBW", "GW_n"], "MBWR_n")
    for i in range(8):
        g("08", [BANK[i], "USEBW"], RWA[5 + i])
    g("10", [u["RFWE"], "T1", "FAULT_n"], "RFWE_n")
    g("00", [u["RFWE"], "T1"], "RFWB_n")
    # the read address's bank: BANK in user mode, or if the cycle before set
    # UBR; kept in a register (EB, loaded every cycle with what BANK and S
    # will be) so that it is there at the edge
    g("04", ["SNEXT"], "SNEXT_n")
    nl.add("157", "U_UBM", S="FAULT", G="GND",
           **{"1A": "SNEXT_n", "1B": "SFLAG_n", "1Y": "SNX_n", "2A": "MNEXT", "2B": "MFLAG",
              "2Y": "MNX", "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    g("32", [u["UBR"], "SNX_n"], "USEBR_D")

    g("04", ["BANKLD_n"], "BANKLD")
    BANKN, EB = bus("BANKN", 8), bus("EB", 8)
    for k in range(2):
        m = nl.add("157", f"U_BKN{k}", S="BANKLD", G="GND")
        for j in range(4):
            i = 4 * k + j
            m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = BANK[i], RES[i], BANKN[i]
    for i in range(8):
        g("08", [BANKN[i], "USEBR_D"], f"EBD{i}")
    nl.add("16374h", "U_EB", CLK="CLK", OE="GND", **{f"D{i + 1}": f"EBD{i}" for i in range(8)},
           **{f"Q{i + 1}": EB[i] for i in range(8)})
    # MB, the same way: the read's message level registers, M as it will be
    # in supervisor mode without UBR; for a constant only if not G
    g("02", [u["UBR"], "SNX_n"], "USEBR_N")
    g("08", ["MNX", "USEBR_N"], "MB_D")
    # (with a faster copy of the uIR's RFK5_n beside it)
    rfk5 = next(b for b, n in U.items() if n == u["RFK5_n"])
    nl.add("74", "U_MB", **{"1D": "MB_D", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "VCC",
                            "1Q": "MB", "1QN": "MB_n", "2D": f"UD{rfk5}", "2CLK": "CLK",
                            "2PRE": "VCC", "2CLR": "VCC", "2Q": "RFK5F_n"})
    g("00", ["MB", "RFK5F_n"], "MBK_n")
    # the bank, for both copies: EB, and the write's for the last two ticks
    RFBK = bus("RFBK", 8)
    for k in range(2):
        m = nl.add("157", f"U_RFBK{k}", S="RW", G="GND")
        for j in range(4):
            i = 4 * k + j
            m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = EB[i], RWA[5 + i], RFBK[i]
    # each copy's register and G: RFA (RFB) selects the read address, RW
    # switches to the write address for the last two ticks, in one 74F151 a
    # bit
    for side, sel, out, oe in (("A", "RFA", ABUS, u["ARF_n"]), ("B", "RFB", BBUS, "BRFE_n")):
        AM = bus(f"RF{side}M", 15)
        for i in [*range(5), 13, 14]:
            m = nl.add("151", f"U_RF{side}A{i}", A=u[f"{sel}0"], B=u[f"{sel}1"], C="RW", G="GND")
            if i < 4:
                rd = [IR[12 + i], IR[8 + i], SX[i], u[f"RFK{i}"]]
            elif i == 4:
                rd = ["GND", "GND", "GND", u["RFK4"]]
            elif i == 13:                   # G, from the inverted output
                rd = ["VCC", "VCC", "VCC", u["RFK5_n"]]
            else:                           # A14, from the inverted output too
                rd = ["MB_n", "MB_n", "MB_n", "MBK_n"]
            wr = {13: "GW_n", 14: "MBWR_n"}.get(i) or RWA[i]
            for c in range(4):
                m[f"D{c}"], m[f"D{4 + c}"] = rd[c], wr
            m["W" if i >= 13 else "Y"] = AM[i]
        AM[5:13] = RFBK
        IO = bus(f"RF{side}IO", 32)
        for k in range(4):
            ram = nl.add("sram64k", f"U_RF{side}{k}", role="rf", CE="GND", OE="RW", WE="RFWE_n")
            for i in range(16):
                ram[f"A{i}"] = AM[i] if i < 15 else "GND"
            for i in range(8):
                ram[f"IO{i}"] = IO[8 * k + i]
            lat = nl.add("16373h", f"U_RL{side}{k}", LE="RW_n", OE=oe)
            buf = nl.add("16244h", f"U_RW{side}{k}", OE1="RFWB_n", OE2="RFWB_n")
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
            b = nl.add("16244h", ref, OE1=oe, OE2=oe)
            for i in range(8):
                b[f"A{i + 1}"], b[f"Y{i + 1}"] = src[8 * k + i], ABUS[8 * k + i]

    # ---- B bus -------------------------------------------------------------------
    nl.section("B bus")
    # the enables straight from the uIR pass a gate, so that they come on
    # about when the decoded ones (below) of the cycle before go off
    for f in ("BRF", "BR", "BS0", "BF1", "BF23"):
        g("32", [u[f"{f}_n"], "GND"], f"{f}E_n")
    for k in range(4):
        b = nl.add("16244h", f"U_BR{k}", OE1="BRE_n", OE2="BRE_n")
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = RQ[8 * k + i], BBUS[8 * k + i]
    # T by lanes (BL 1 word, 2 half, 3 byte, moved down to the low lanes by
    # TL, the access's address), and the queue's head (4 as it is, 5 x 2,
    # 6 in the upper half, 7 its low byte)
    # each enable one gate after the uIR, so that the cycle before's drivers
    # turn off soon: the 74F138's outputs, or a 74F151 by BL whose inputs are
    # what TL selects (its inverted output the enable)
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
        b = nl.add("16244h", ref, OE1=oe, OE2=oe)
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
    for ref, src, dst, oe in (("U_BS0", V8, 0, "BS0E_n"), ("U_BF1", ["FILL"] * 8, 1, "BF1E_n"),
                              ("U_BF2", ["FILL"] * 8, 2, "BF23E_n"),
                              ("U_BF3", ["FILL"] * 8, 3, "BF23E_n")):
        b = nl.add("16244h", ref, OE1=oe, OE2=oe)
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = src[i], BBUS[8 * dst + i]

    nl.section("B bus")
    bx = nl.add("138", "U_BXD", A=u["BX0"], B=u["BX1"], C=u["BX2"], G1="VCC", G2A="GND",
                G2B="GND")
    for v, name in ((1, "BXMQ_n"), (2, "BXFL_n"), (3, "BXFSR_n"), (4, "BXFAR_n"), (5, "BXMAP_n"),
                    (6, "BXLV_n"), (7, "BXMSG_n")):
        bx[f"Y{v}"] = name
    # sr: N Z C V in byte 0, byte 2 zero, S I T M IPL in byte 3 (byte 1 is
    # the immediate unit's zero fill)
    for ref, srcs, dst in (("U_BFL", ["VFLAG", "CFLAG", "ZFLAG", "NFLAG"] + ["GND"] * 4, 0),
                           ("U_BFL2", ["GND"] * 8, 2),
                           ("U_BFL3", [f"IPL{i}" for i in range(4)]
                            + ["MFLAG", "TFLAG", "IFLAG", "SFLAG"], 3)):
        b = nl.add("16244h", ref, OE1="BXFL_n", OE2="BXFL_n")
        for i, src in enumerate(srcs):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = src, BBUS[8 * dst + i]
    # the interrupt's vector offset: 0x40 + 4(L - 1), or 0x04 for the NMI
    b = nl.add("16244h", "U_BLV", OE1="BXLV_n", OE2="BXLV_n")
    for i, src in enumerate(["GND", "GND", "VX0Q", "VX1Q", "VX2Q", "GND", "NMIT_n", "GND"]):
        b[f"A{i + 1}"], b[f"Y{i + 1}"] = src, BBUS[i]
    mapsrc = [[MD[0], MD[1], MD[2]] + ["GND"] * 5, ["GND"] * 4 + MD[3:7], MD[7:15], MD[15:23]]
    for k in range(4):
        b = nl.add("16244h", f"U_BMAP{k}", OE1="BXMAP_n", OE2="BXMAP_n")
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
        r = nl.add("16823h", f"U_R{k}", CLK="CLK", EN="RLD_n", CLR="VCC", OE="GND", D9="GND")
        for i in range(8):
            r[f"D{i + 1}"], r[f"Q{i + 1}"] = RES[8 * k + i], RQ[8 * k + i]
    # T, and TL (the access's address bits 1-0): latches, transparent while
    # memory is read into them, from tick 2 (LATE) until the write phase:
    # not at the cycle's start, while READING still shows the cycle before
    # and VA already moves
    g("11", ["READING", "RW_n", "LATE"], "TLE")
    for k in range(4):
        t = nl.add("16373h", f"U_T{k}", LE="TLE", OE="GND")
        for i in range(8):
            t[f"D{i + 1}"], t[f"Q{i + 1}"] = DB[8 * k + i], TQ[8 * k + i]
    nl.add("16373h", "U_TL", LE="TLE", OE="GND", D1=VA[0], Q1="TL0", D2=VA[1], Q2="TL1",
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
    # LDSX: 1 IR[15:12], 3 the queue head's QH[15:12], 2 count
    m = nl.add("157", "U_SXM", S=u["LDSX1"], G="GND")
    for i in range(4):
        m[f"{i + 1}A"], m[f"{i + 1}B"], m[f"{i + 1}Y"] = IR[12 + i], QH[12 + i], f"SXD{i}"
    g("00", [u["LDSX0"], "FAULT_n"], "SXLD_n")
    g("04", [u["LDSX0"]], "LDSX0_n")
    g("11", [u["LDSX1"], "LDSX0_n", "FAULT_n"], "SXEN")
    nl.add("161", "U_SX", CLK="CLK", CLR="VCC", LOAD="SXLD_n", ENP="SXEN", ENT="VCC",
           A="SXD0", B="SXD1", C="SXD2", D="SXD3", QA=SX[0], QB=SX[1], QC=SX[2], QD=SX[3])
    m = nl.add("157", "U_EXM", S=u["LDEX1"], G="GND")
    for j in range(4):
        m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = IR[8 + j], QH[12 + j], f"EXD{j}"
    g("32", [u["LDEX0"], u["LDEX1"]], "LDEXNZ")
    g("00", ["LDEXNZ", "FAULT_n"], "EXLD_n")
    nl.add("16823h", "U_EX", CLK="CLK", EN="EXLD_n", CLR="VCC", OE="GND", D9="GND",
           **{f"D{j + 1}": f"EXD{j}" for j in range(4)}, **{f"Q{j + 1}": EX[j] for j in range(4)},
           **{f"D{j}": "GND" for j in range(5, 9)})
    nl.add("688", "U_SXEQ", G="GND", PEQ="SXEQ_n",
           **{f"P{i}": SX[i] if i < 4 else "GND" for i in range(8)},
           **{f"Q{i}": EX[i] if i < 4 else "GND" for i in range(8)})
    g("04", ["SXEQ_n"], "SXEQ")
    g("21", SX, "SX15")

    nl.section("Faults")
    nl.add("16823h", "U_CTX", CLK="CLK", EN="CTXLD_n", CLR="VCC", OE="GND", D9="GND",
           **{f"D{i + 1}": RES[i] for i in range(7)}, **{f"Q{i + 1}": CTX[i] for i in range(7)},
           D8="GND")
    nl.add("16823h", "U_BANK", CLK="CLK", EN="BANKLD_n", CLR="VCC", OE="GND", D9="GND",
           **{f"D{i + 1}": RES[i] for i in range(8)}, **{f"Q{i + 1}": BANK[i] for i in range(8)})
    g("00", [u["LDCTX"], "FAULT_n"], "CTXLD_n")
    g("00", [u["LDBANK"], "FAULT_n"], "BANKLD_n")

    # ---- PC, FPC and the prefetch queue ----------------------------------------------
    nl.section("PC")
    g("00", ["JUMP", "FAULT_n"], "PCLD_n")
    g("04", ["PCLD_n"], "PCLD")
    # a decode that goes ahead has no fault and no jump, and doesn't consume;
    # a cycle that consumes has no data access and isn't a refill (the
    # microcode's rules), so it can't fault
    g("08", [u["CONSUME"], "JUMP_n"], "CONSC")
    g("32", ["CONSC", "DECGOX"], "CONSUMEX")
    counter_chain(nl, "PC", PC, RES, 1, 8, "PCLD_n", "CONSUMEX")
    counter_chain(nl, "FPC", FPC, RES, 2, 8, "PCLD_n", "FPCINC")
    # PC[1] again, from a fast flip-flop, for the queue's head; and the
    # fetch's translation is valid (FOK)
    g("86", ["PC1F", "CONSUMEX"], "PC1T")
    nl.add("157", "U_PCFM", S="PCLD", G="GND",
           **{"1A": "PC1T", "1B": RES[1], "1Y": "PC1F_D", "2A": "GND", "2B": "GND",
              "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    nl.add("74", "U_PCF", **{"1D": "PC1F_D", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "RESET_n",
                             "1Q": "PC1F", "1QN": "PC1F_n",
                             "2D": "FOK_D", "2CLK": "CLK", "2PRE": "VCC", "2CLR": "RESET_n",
                             "2Q": "FOK", "2QN": "FOK_n"})

    nl.section("Fetch translation")
    # FPC's page, kept from the map's translation (in a refill, or a cycle
    # without a data access while FOK is clear): the prefetch reads the RAM
    # at it without the map. A jump clears FOK, and so does FPC moving into
    # the next page.
    g("08", [u["VAS0"], u["VAS1"]], "PF")             # a cycle that may prefetch
    g("08", ["PF", "FOK"], "PFOK")
    g("20", [u["VAS0"], u["VAS1"], "FOK", "VCC"], "PFOK_n")
    g("08", ["PF", "FOK_n"], "PFT")
    g("32", ["MEM3", "PFT"], "TRANS")
    g("02", ["LOCAL_n", "XFAULT"], "OKNEW")
    g("00", ["TRANS", "FAULT_n"], "FPPNLD_n")
    fppn = nl.add("16823h", "U_FPPN", CLK="CLK", EN="FPPNLD_n", CLR="VCC", OE="GND")
    for i in range(9):
        fppn[f"D{i + 1}"], fppn[f"Q{i + 1}"] = PA[12 + i], f"FPPN{i}"
    nl.add("688", "U_FPCE", G="GND", PEQ="FPCE_n",
           **{f"P{i}": FPC[2 + i] for i in range(8)}, **{f"Q{i}": "VCC" for i in range(8)})
    g("00", [FPC[10], FPC[11]], "FPCE2_n")
    g("02", ["FPCE_n", "FPCE2_n"], "PAGEEND")
    g("08", ["V1_n", "PAGEEND"], "KILL")                 # a fetch would leave the page
    # FOK next: a translation that commits (no fault, no jump) sets it to its
    # result, unless its own fetch leaves the page; else it stays, but for a
    # jump or a prefetch that leaves the page (a fault leaves everything)
    g("00", ["KILL", "MEM3"], "KR_n")
    g("08", ["OKNEW", "KR_n"], "OKB")
    g("11", ["TRANS", "FAULT_n", "JUMP_n"], "TRC")
    g("32", ["FAULT", "JUMP_n"], "FJ")
    g("00", ["KILL", "PFOK"], "KP_n")
    g("11", ["FOK", "FJ", "KP_n"], "FOKH")
    nl.add("157", "U_FOKM", S="TRC", G="GND",
           **{"1A": "FOKH", "1B": "OKB", "1Y": "FOK_D", "2A": "GND", "2B": "GND",
              "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    nl.section("Prefetch queue")
    # a fetch: room in the queue, and a prefetch with the kept translation,
    # or a refill whose translation is good, in the card's RAM
    g("00", ["MEM3", "OKNEW"], "RFOK_n")
    g("00", ["PFOK_n", "RFOK_n"], "FETCHOK")
    g("08", ["FETCHOK", "V1_n"], "FETCHED")
    g("11", ["FETCHED", "FAULT_n", "JUMP_n"], "FPCINC")
    g("08", ["CONSC", "PC1F"], "SHIFTC")
    g("32", ["SHIFTC", "DECGOP"], "SHIFT")
    # two slots, loaded straight from the card's data bus: Q0 is slot HS, Q1
    # the other, and a shift toggles HS (in TS's spare flip-flop) instead of
    # moving a word. A slot loads in every cycle its entry is empty (V0 or
    # V1 off), so the word a fetch brings is there when V0 or V1 comes on,
    # and the load enables don't wait for the shift. Each half reaches the
    # head through a 74ABT16244 half, which turns off as fast as it turns on
    g("86", ["HS", "SHIFT"], "HS_D")
    nl.add("157", "U_QSL", S="HS", G="GND",
           **{"1A": "V0", "1B": "V1", "1Y": "QS0LD_n", "2A": "V1", "2B": "V0", "2Y": "QS1LD_n",
              "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    for sl in range(2):
        QS = bus(f"QS{sl}_", 32)
        for k in range(4):
            r = nl.add("16823h", f"U_QS{sl}{k}", CLK="CLK", EN=f"QS{sl}LD_n", CLR="VCC",
                       OE="GND", D9="GND")
            oe = f"QH{sl}{'LH'[k >> 1]}_n"
            b = nl.add("16244h", f"U_QB{sl}{k}", OE1=oe, OE2=oe)
            for i in range(8):
                r[f"D{i + 1}"], r[f"Q{i + 1}"] = DB[8 * k + i], QS[8 * k + i]
                b[f"A{i + 1}"], b[f"Y{i + 1}"] = QS[8 * k + i], QH[8 * (k & 1) + i]
    # V0, V1: a jump empties the queue, a fault leaves it; the shift (late:
    # it follows the decode) selects last
    g("11", ["V0", "W3", "JUMP_n"], "V0S")              # shifted: a second word
    g("32", ["V0", "FETCHED"], "V0ORF")
    g("08", ["FAULT_n", "JUMP_n"], "QCOMMIT")
    for v, x in (("V0", "V0ORF"), ("V1", "V0S")):
        g("08", ["FAULT", v], f"{v}H")
        g("08", ["QCOMMIT", x], f"{v}N")
        g("32", [f"{v}H", f"{v}N"], f"{v}NS")
    nl.add("157", "U_VNX", S="SHIFT", G="GND",
           **{"1A": "V0NS", "1B": "V0S", "1Y": "V0_D", "2A": "V1NS", "2B": "GND", "2Y": "V1_D",
              "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    nl.add("74", "U_V", **{"1D": "V0_D", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "VCC",
                           "1Q": "V0", "1QN": "V0_n",
                           "2D": "V1_D", "2CLK": "CLK", "2PRE": "VCC", "2CLR": "VCC",
                           "2Q": "V1", "2QN": "V1_n"})
    # the head parcel, a three-state bus: Q0's half (by PC1F), or the word
    # this cycle fetches if the queue is empty
    for sl, hs in ((0, "HS_n"), (1, "HS")):
        g("20", ["V0", hs, "PC1F_n", "VCC"], f"QH{sl}L_n")
        g("20", ["V0", hs, "PC1F", "VCC"], f"QH{sl}H_n")
    g("32", ["V0", "PC1F"], "QHDL_n")
    g("32", ["V0", "PC1F_n"], "QHDH_n")
    for k in range(4):
        oe = "QHDH_n" if k >> 1 else "QHDL_n"
        b = nl.add("16244h", f"U_QD{k}", OE1=oe, OE2=oe)
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = DB[8 * k + i], QH[8 * (k & 1) + i]

    # ---- memory: the virtual address, the map, the window, faults, RAM ----------------------
    nl.section("Memory")
    # MEM's top bit is stored inverted, so that a refill (3) is one gate
    md = nl.add("138", "U_MEMD", A=u["MEM0"], B=u["MEM1"], C=u["MEM2_n"], G1="VCC", G2A="GND",
                G2B="GND")
    for v in range(8):
        md[f"Y{v ^ 4}"] = f"MEM{v}_n"
    g("00", ["MEM1_n", "MEM6_n"], "READING")
    g("04", ["READING"], "READING_n")
    g("20", ["MEM1_n", "MEM2_n", "MEM6_n", "VCC"], "XLATE")
    g("04", ["XLATE"], "XLATE_n")
    g("00", ["MEM0_n", "MEM3_n"], "FETCHCYC")
    g("11", [u["MEM0"], u["MEM1"], u["MEM2_n"]], "MEM3")
    g("04", ["MEM2_n"], "MEMWR")
    g("04", ["MEM5_n"], "MAPW")
    g("04", ["MEM6_n"], "MEM6")
    # the virtual address: MAR, FPC (fetch cycles) or the A bus (a read at
    # the A bus), by VAS, which the microcode derives from MEM
    for k in range(16):
        m = nl.add("153", f"U_VAM{k}", A=u["VAS0"], B=u["VAS1"], **{"1G": "GND", "2G": "GND"})
        for sec in (0, 1):
            i = 2 * k + sec
            for c, s in enumerate([MAR[i], FPC[i], ABUS[i], FPC[i]]):
                m[f"{sec + 1}C{c}"] = s
            m[f"{sec + 1}Y"] = VA[i]
    # the page map: {CTX, VA[23:12]}, or MAR[30:12] for MFSR/MTSR mapd
    MA = bus("MA", 19)
    for k in range(2):
        m = nl.add("157", f"U_MAM{k}", S=u["MAPA"], G="GND")
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
    # translation (RFC 0029, 3): the window, or the map's page; for a
    # prefetch with FOK, the kept page (the RAM's part of it)
    g("08", [VA[31], "SFLAG"], "WIN")
    win = VA[12:31] + ["GND"]
    for k in range(5):
        m = nl.add("153", f"U_PAM{k}", A="WIN", B="PFOK", **{"1G": "GND", "2G": "GND"})
        for sec in (0, 1):
            i = 2 * k + sec
            for c, s_ in enumerate([MD[3 + i], win[i], f"FPPN{i}", f"FPPN{i}"]):
                m[f"{sec + 1}C{c}"] = s_ if i < 9 else "GND"
            m[f"{sec + 1}Y"] = PA[12 + i] if i < 9 else f"PAX{i}"
    for k in range(3):
        m = nl.add("157", f"U_PAH{k}", S="WIN", G="GND")
        for j in range(4):
            i = 9 + 4 * k + j
            if i < 20:
                m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = MD[3 + i], win[i], PA[12 + i]
            else:
                m[f"{j + 1}A"], m[f"{j + 1}B"] = "GND", "GND"
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
    # the translation fault, fast: the map's V, W, X select whether the
    # access may use the page; then the window, the range
    g("32", ["MEMWR", "FETCHCYC"], "WRFE")
    nl.add("151", "U_MAPF", A=MD[0], B=MD[1], C=MD[2], G="GND", Y="MAPF", W="MAPF_n",
           D0="VCC", D1="WRFE", D2="VCC", D3="FETCHCYC", D4="VCC", D5="MEMWR", D6="VCC",
           D7="GND")
    nl.add("153", "U_XF", A=VA[31], B="VAHINZ",
           **{"1G": "GND", "1C0": "MAPF", "1C1": "SFLAG_n", "1C2": "VCC", "1C3": "SFLAG_n",
              "1Y": "XFAULT",
              "2G": "GND", "2C0": "MAPF_n", "2C1": "SFLAG", "2C2": "GND", "2C3": "SFLAG",
              "2Y": "XFAULT_n"})
    # the size (SIZE: 1 byte, 2 half, 3 word), decoded active low; and
    # alignment: a half at an odd address, or a word at one that isn't a
    # multiple of 4, is SIZE1 & (VA0 | VA1 & SIZE0)
    nl.add("138", "U_SIZED", A=u["SIZE0"], B=u["SIZE1"], C="GND", G1="VCC", G2A="GND",
           G2B="GND", Y1="BYTE_n", Y2="HALF_n", Y3="WORD_n")
    g("04", [u["SIZE1"]], "SIZE1_n")
    g("08", [u["SIZE0"], u["SIZE1"]], "WORD")
    g("08", [VA[1], u["SIZE0"]], "MISW1")
    g("32", [VA[0], "MISW1"], "MISV")
    g("08", [u["SIZE1"], "MISV"], "MIS1")
    g("08", ["MIS1", "XLATE"], "MISALIGN")
    g("00", ["MIS1", "XLATE"], "MISALIGN_n")
    # what answers (RFC 0037, 5.1): the card's RAM (region 0), or the
    # registers from 0x7000_0000 (the card's own; here a fixture, which also
    # stands for the I/O page at the top); anything else is the bus
    # interface's, which isn't drawn
    nl.add("688", "U_LOCAL", G="GND", PEQ="LOCAL_n",
           **{f"P{i}": PA[28 + i] if i < 4 else "GND" for i in range(8)},
           **{f"Q{i}": "GND" for i in range(8)})
    g("04", ["LOCAL_n"], "LOCAL")
    nl.add("688", "U_IOSL", G="GND", PEQ="IOSLOT_n",
           **{f"P{i}": PA[28 + i] if i < 4 else "GND" for i in range(8)},
           **{f"Q{i}": "VCC" if i < 3 else "GND" for i in range(8)})
    # a fault: a data access misaligned or not translated; a refill's fetch
    # that fails when the decode needs its word (RQ), which can only be from
    # the card's RAM here
    g("32", ["V0_n", "FITS1_n"], "FNEED")
    g("11", ["MEM3", "V1_n", "FNEED"], "RQ")
    g("32", ["XLATE", "RQ"], "XQ")
    # the translation fault where it counts (XQ), in as few gates after the
    # map as can be: the map's V, W, X select it for a mapped page (the
    # 74F151's strobe off otherwise), the window from user mode and the
    # range beside it
    g("08", ["WRFE", "XQ"], "WRFEQ")
    g("08", ["FETCHCYC", "XQ"], "FETQ")
    g("08", ["MEMWR", "XQ"], "WRQ")
    g("32", [VA[31], "VAHINZ"], "UNMAPPED")
    nl.add("151", "U_MAPQ", A=MD[0], B=MD[1], C=MD[2], G="UNMAPPED", W="MAPFQ_n",
           D0="XQ", D1="WRFEQ", D2="XQ", D3="FETQ", D4="XQ", D5="WRQ", D6="XQ", D7="GND")
    nl.add("157", "U_RUM", S=VA[31], G="GND",
           **{"1A": "VAHINZ", "1B": "SFLAG_n", "1Y": "RU", "2A": "GND", "2B": "GND",
              "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    g("00", ["RU", "XQ"], "RUQ_n")
    g("08", ["RUQ_n", "MISALIGN_n"], "FT1_n")
    g("00", ["LOCAL_n", "RQ"], "FT3_n")
    g("21", ["MAPFQ_n", "FT1_n", "FT3_n", "VCC"], "FAULT_n")
    g("20", ["MAPFQ_n", "FT1_n", "FT3_n", "VCC"], "FAULT")
    # FK: 0 page fault, 1 misaligned (2, a bus error, no longer happens);
    # FSR for a page fault; FAR
    nl.add("16823h", "U_FK", CLK="CLK", EN="FAULT_n", CLR="VCC", OE="GND",
           D1="MISALIGN", Q1="FK0", D2="GND", Q2="FK1", **{f"D{i}": "GND" for i in range(3, 10)})
    g("10", ["FAULT", "XFAULT", "MISALIGN_n"], "FSRLD_n")
    fsr = nl.add("16823h", "U_FSR", CLK="CLK", EN="FSRLD_n", CLR="VCC", OE="BXFSR_n", D9="GND")
    for i, s in enumerate(["R_INV", "R_NOW", "R_NOX", "R_RANGE", "R_USER", "MEMWR", "FETCHCYC",
                           "SFLAG"]):
        fsr[f"D{i + 1}"], fsr[f"Q{i + 1}"] = s, BBUS[i]
    for k in range(4):
        far = nl.add("16823h", f"U_FAR{k}", CLK="CLK", EN="FAULT_n", CLR="VCC", OE="BXFAR_n",
                     D9="GND")
        for i in range(8):
            far[f"D{i + 1}"], far[f"Q{i + 1}"] = VA[8 * k + i], BBUS[8 * k + i]
    # byte enables, from the size and VA[1:0]
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
    # the RAM: 2 MB, slot 0 (repeated)
    # always selected; its outputs on in any fetch cycle (nothing else
    # drives the data bus then) and in a read of the card's RAM
    nl.add("153", "U_RAMOE", A="FETCHCYC", B="READING",
           **{"1G": "GND", "1C0": "VCC", "1C1": "GND", "1C2": "LOCAL_n", "1C3": "GND",
              "1Y": "RAMOE_n", "2G": "VCC", "2C0": "GND", "2C1": "GND", "2C2": "GND",
              "2C3": "GND"})
    g("11", ["MEMWR", "FAULT_n", "LOCAL"], "MWOK")
    for k in range(4):
        g("20", ["MWOK", "MWIN", f"BE{k}", "VCC"], f"WE{k}_n")
        ram = nl.add("sram512", f"U_RAM{k}", role="fastram", CE="GND", OE="RAMOE_n",
                     WE=f"WE{k}_n")
        for i in range(19):
            ram[f"A{i}"] = PA[2 + i]
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
        # a 541 where two enables must both be low; a 16244 half has one
        b = (nl.add("16244h", ref, OE1="SDOE_n", OE2="SDOE_n") if oe2 == "GND" else
             nl.add("541", ref, OE1="SDOE_n", OE2=oe2))
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = src[i], DB[8 * dst + i]
    # the I/O page: a fixture, on the card's data bus
    g("02", ["MISALIGN", "XFAULT"], "XOK")
    g("04", ["IOSLOT_n"], "IOSLOT")
    g("10", ["IOSLOT", "XLATE", "XOK"], "IOSEL_n")
    g("00", ["MEMWR", "MWIN"], "IOWR_n")
    if sim:
        # it drives the data bus from tick 3, once the RAM's outputs are off
        g("32", ["H3", "MID"], "TICK3")
        g("00", ["READING", "TICK3"], "IORD_n")
        io = nl.add("cpucard_w32", "X_IO", CLK="CLK", MCLK="MCLK", RESET_n="RESET_n",
                    IOSEL="IOSEL_n", RD="IORD_n", WR="IOWR_n", IRQ="IO_IRQ",
                    MSGF="MSGF", NMI="NMI", MSGOE="BXMSG_n", NMIACK="NMIACK",
                    **{f"LV{i}": f"LV{i}_n" for i in range(1, 9)})
        for i in list(range(2, 16)) + list(range(24, 28)):
            io[f"A{i}"] = PA[i] if i >= 12 else VA[i]
        for i in range(4):
            io[f"BE{i}"] = f"BE{i}_n"
        for i in range(32):
            io[f"D{i}"] = DB[i]
            io[f"B{i}"] = BBUS[i]
    else:
        # the CPU card's levels and NMI, none requesting; the message
        # register, whose outputs drive B, is the card's
        nl.add("const", "X_STUB", LO="MSGF")
        nl.add("const", "X_STUBN", LO="NMI")
        for i in range(1, 9):
            nl.add("const", f"X_LV{i}", HI=f"LV{i}_n")

    # ---- flags -------------------------------------------------------------------------
    nl.section("Flags")
    # Z is kept as four bits, each a byte of the result nonzero (NZR, a
    # 74F521's output as it is), and formed after the register; CL the same
    # way (below). Sticky: Z stays clear once clear.
    NZR, NZ = bus("NZR", 4), bus("NZ", 4)
    for k in range(4):
        nl.add("688", f"U_Z{k}", G="GND", PEQ=NZR[k],
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
    nl.add("16823h", "U_NZ", CLK="CLK", EN="FAULT", CLR="VCC", OE="GND",
           **{f"D{i + 1}": f"NZD{i}" for i in range(4)}, **{f"Q{i + 1}": NZ[i] for i in range(4)},
           **{f"D{i}": "GND" for i in range(5, 10)})
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
    nl.add("153", "U_FI", A=u["FI0"], B=u["FI1"],
           **{"1G": "GND", "2G": "VCC",
              "1C0": "IFLAG", "1C1": "VCC", "1C2": "GND", "1C3": ABUS[30], "1Y": "INEXT1",
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
           **{"1A": "TFLAG", "1B": ABUS[29], "1Y": "TN",
              "2A": "MFLAG", "2B": ABUS[28], "2Y": "MN1",
              "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    nl.add("157", "U_SSM", G="GND", S="SLOAD",
           **{"1A": "SFLAG", "1B": ABUS[31], "1Y": "SN",
              "2A": "GND", "2B": "GND", "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    g("08", ["TN", "SSET_n"], "TNEXT")
    g("32", ["SN", u["SSET"]], "SNEXT")
    g("08", ["INEXT1", "SSET_n"], "INEXT2")
    # also M
    nl.add("16823h", "U_FLAGS", CLK="CLK", EN="FAULT", CLR="VCC", OE="GND",
           D1="NNEXT", Q1="NFLAG", D2="GND", D3="CNEXT", Q3="CFLAG",
           D4="VNEXT", Q4="VFLAG", D5="INEXT2", Q5="IFLAG", D6="SNEXT", Q6="SFLAG",
           D7="TNEXT", Q7="TFLAG", D8="MNEXT", Q8="MFLAG", D9="GND")
    for f in ("C", "V", "S"):
        g("04", [f"{f}FLAG"], f"{f}FLAG_n")
    # IPL and M (RFC 0029, 2; RFC 0040, 2.4): IPL from A[27:24] with LFM 1
    # or 2 (a flags load that takes it, or SPL), from L at an interrupt's
    # entry (SSET with LFM 1) unless it is the NMI, which that acknowledges;
    # M from A28 with a flags load (TLOAD), MSGT at an interrupt's entry, 0
    # at any other exception's
    g("08", [u["LFM0"], "SSET_n"], "IPLA0")
    g("08", [u["LFM1"], "SSET_n"], "IPLA1")
    g("32", ["IPLA0", "IPLA1"], "IPLA")
    g("04", [u["LFM1"]], "LFM1_n")
    g("11", [u["SSET"], u["LFM0"], "LFM1_n"], "INTE")
    g("08", ["INTE", "NMIT_n"], "IPLL")
    g("02", ["NMIT_n", "INTE_n"], "NMIACK")
    g("04", ["INTE"], "INTE_n")
    m = nl.add("157", "U_IPLM", S="IPLA", G="GND")
    for i in range(4):
        m[f"{i + 1}A"], m[f"{i + 1}B"], m[f"{i + 1}Y"] = f"LT{i}", ABUS[24 + i], f"IPLN{i}"
    g("02", ["IPLA", "IPLL"], "IPLHOLD")
    g("32", ["IPLHOLD", "FAULT"], "IPLLD_n")
    nl.add("16823h", "U_IPL", CLK="CLK", EN="IPLLD_n", CLR="VCC", OE="GND",
           **{f"D{i + 1}": f"IPLN{i}" for i in range(4)}, **{f"Q{i + 1}": f"IPL{i}" for i in range(4)},
           **{f"D{i}": "GND" for i in range(5, 10)})
    # M: A28 with a flags load (the second section of T's multiplexer),
    # cleared by SSET, MSGT at an interrupt's entry
    g("08", ["INTE", "MSGT"], "MSGTE")
    g("08", ["MN1", "SSET_n"], "MN2")
    g("32", ["MN2", "MSGTE"], "MNEXT")

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
    g("00", [u["LDCL"], "FAULT_n"], "LDCLC_n")
    nl.add("16823h", "U_CLB", CLK="CLK", EN="LDCLC_n", CLR="VCC", OE="GND",
           **{f"D{i + 1}": f"CLD{i}" for i in range(4)}, **{f"Q{i + 1}": CLB[i] for i in range(4)},
           **{f"D{i}": "GND" for i in range(5, 10)})
    g("02", [CLB[0], CLB[1]], "CLA")
    g("02", [CLB[2], CLB[3]], "CLBB")
    g("08", ["CLA", "CLBB"], "CLQ")
    g("00", ["CLA", "CLBB"], "CL_n")
    # SGN, S33
    g("08", [u["LDSGN"], "FAULT_n"], "LDSGNC")
    nl.add("157", "U_LATM", S="LDSGNC", G="GND",
           **{"1A": "SGNQ", "1B": "FILL", "1Y": "SGN_D",
              "2A": "GND", "2B": "GND", "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
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
