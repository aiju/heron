"""Chip-level netlist of the draft 1b CPU (plus 1 MB RAM and the I/O page).

Buses
  ABUS  ALU A input   <- RF copy A, PC, R, R x 2 (+ shift-in), the bridge from B
  BBUS  ALU B input   <- RF copy B, R, T (by byte lane), 2 x T.lo, the
                         immediate unit (V8 byte, fill bytes), flags, MQ
  F     ALU output (74181 x 8, 74182 x 3)
  RES   result bus = F through the shift/rotate multiplexer (74HCT153 x 16)
  DBUS  16-bit memory data <- RAM, I/O, the result bus (store data)
  ADDR  memory address <- PC or MAR (20 bits: 1 MB, mirrored)

The control signals are the outputs of the microinstruction register (uIR,
15 x 74HCT377) which loads the microcode ROMs' outputs at every clock edge.
See docs/hardware-v1b.md and tmc/hw/ucode_v1b.py (field meanings) and
tmc/hw/rtl_v1b.py (the register-transfer model this netlist implements).
"""

from .netlist import Netlist
from . import ucode_v1b as uc


def bus(name, n, start=0):
    return [f"{name}{i}" for i in range(start, start + n)]


def control_nets():
    """Control word bit -> uIR output net (with _n for active-low fields)."""
    nets = {}
    for name, (bit, w, al) in uc._pos.items():
        for i in range(w):
            nets[bit + i] = f"u{name}{i if w > 1 else ''}{'_n' if al else ''}"
    return nets


def build():
    nl = Netlist()
    g = nl.gate
    U = control_nets()
    u = {v[1:]: v for v in U.values()}          # u["BSRC0"] -> "uBSRC0", u["ARF_n"] ...

    ABUS, BBUS, F, RES = bus("ABUS", 32), bus("BBUS", 32), bus("F", 32), bus("RES", 32)
    DBUS, ADDR, IR = bus("DBUS", 16), bus("ADDR", 20), bus("IR", 16)
    RQ, TQ = bus("RQ", 32), bus("TQ", 32)
    PC = ["GND"] + bus("PC", 31, 1)              # PC bit 0 is always 0
    MAR = bus("MAR", 20) + ["MAR31"]             # bits 0-19 and 31 (I/O select)
    Y = bus("Y", uc.Y_BITS)
    DEC = bus("DEC", 16)
    LC = bus("LC", 8)

    # ---- fixtures: clock/reset generator, rails --------------------------------
    nl.add("clockgen", "X_CLK", CLK="CLK", WEWIN="WEWIN0", RESET="RESET_n")
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")
    g("04", ["RESET_n"], "RESET")
    g("08", ["WEWIN0", "RESET_n"], "WEWIN")       # no writes while reset is held

    # ---- control store: ROMs addressed by the next address, uIR ------------------
    # address {FAULT & LEN, FAULT, IRQP, Y}: see tmc/hw/ucode_v1b.py
    upper = {uc.IRQP_BIT: "IRQP", uc.FAULT_BIT: "FAULT", uc.FAULT_BIT + 1: "FLEN0",
             uc.FAULT_BIT + 2: "FLEN1"}
    for k in range(uc.ROMS):
        rom = nl.add("flash", f"U_UC{k}", CE="GND", OE="GND", WE="VCC")
        for i in range(17):
            rom[f"A{i}"] = Y[i] if i < uc.Y_BITS else upper.get(i, "GND")
        for i in range(8):
            rom[f"D{i}"] = f"UD{8 * k + i}"
        r = nl.add("377", f"U_UIR{k}", CLK="CLK", EN="GND")
        for i in range(8):
            r[f"D{i + 1}"] = f"UD{8 * k + i}"
            if 8 * k + i in U:
                r[f"Q{i + 1}"] = U[8 * k + i]

    # decode ROM: first parcel on the data bus (or GOIRQ) -> routine address, length
    for k in range(2):
        rom = nl.add("flash", f"U_DEC{k}", CE="GND", OE="GND", WE="VCC")
        for i in range(16):
            rom[f"A{i}"] = DBUS[i]
        rom["A16"] = u["GOIRQ"]
        for i in range(8):
            rom[f"D{i}"] = DEC[8 * k + i]

    # IR, and the instruction length (for address-error entry) beside it
    for half in (0, 1):
        r = nl.add("377", f"U_IR{half}", CLK="CLK", EN=u["LDIR_n"])
        for i in range(8):
            r[f"D{i + 1}"] = DBUS[8 * half + i]
            r[f"Q{i + 1}"] = IR[8 * half + i]
    irx = nl.add("377", "U_IRX", CLK="CLK", EN=u["LDIR_n"], D1=DEC[uc.Y_BITS], Q1="LEN0",
                 D2=DEC[uc.Y_BITS + 1], Q2="LEN1")
    for i in range(3, 9):
        irx[f"D{i}"] = "GND"

    # next-address multiplexer: 0 NEXT (bit 0: the condition), 1 decode, 2 dispatch
    # (bit 0: DBUS[7:0] != 0)
    nl.add("688", "U_DZ", G="GND", PEQ="DZ_n",
           **{f"P{i}": DBUS[i] for i in range(8)}, **{f"Q{i}": "GND" for i in range(8)})
    nl.add("151", "U_CONDM", A=u["COND0"], B=u["COND1"], C=u["COND2"], G="GND", Y="CONDY",
           D0=u["NEXT0"], D1="TC", D2=RQ[31], D3="CLQ", D4="CONDT", D5="MQ31", D6="TC4",
           D7="CONDT_n")
    # misaligned access: word (SIZE 3) at MAR[1:0] != 0, half (SIZE 2) at MAR[0] = 1.
    # It turns the Y multiplexer off (Y = 0) and selects a fault page.
    g("08", [u["SIZE0"], MAR[1]], "MIS1")
    g("32", [MAR[0], "MIS1"], "MIS2")
    g("08", [u["SIZE1"], "MIS2"], "FAULT")
    g("04", ["FAULT"], "FAULT_n")
    g("08", ["FAULT", "LEN0"], "FLEN0")
    g("08", ["FAULT", "LEN1"], "FLEN1")
    g("32", ["RESET", "FAULT"], "YOFF")
    for k in range((uc.Y_BITS + 1) // 2):
        m = nl.add("153", f"U_YM{k}", A=u["SEQ0"], B=u["SEQ1"], **{"1G": "YOFF", "2G": "YOFF"})
        for sec in (0, 1):
            i = 2 * k + sec
            if i >= uc.Y_BITS:
                for c in range(4):
                    m[f"{sec + 1}C{c}"] = "GND"
                continue
            nxt = "CONDY" if i == 0 else u[f"NEXT{i}"]
            disp = "DZ_n" if i == 0 else (DBUS[7 + i] if i <= 4 else u[f"NEXT{i}"])
            for c, s in enumerate([nxt, DEC[i], disp, "GND"]):
                m[f"{sec + 1}C{c}"] = s
            m[f"{sec + 1}Y"] = Y[i]

    # interrupt request: synchronise, then pending = request & I (next value)
    nl.add("74", "U_IRQ", **{"1D": "IRQ", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "RESET_n",
                             "1Q": "IRQS",
                             "2D": "IRQP_D", "2CLK": "CLK", "2PRE": "VCC", "2CLR": "RESET_n",
                             "2Q": "IRQP"})
    g("08", ["IRQS", "INEXT"], "IRQP_D")

    # ---- register file: two copies of 32 x 32 bits ------------------------------
    # SX: the s register field, loaded with IR[7:4] at every fetch and with the
    # index register number (DBUS[15:12]) when the indexed mode's extension
    # parcel is fetched (LDX)
    SX, SXD = bus("SX", 4), bus("SXD", 4)
    m = nl.add("157", "U_SXM", S=u["LDX_n"], G="GND")
    for j in range(4):
        m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = DBUS[12 + j], DBUS[4 + j], SXD[j]
    g("08", [u["LDIR_n"], u["LDX_n"]], "LDSX_n")
    r = nl.add("377", "U_SX", CLK="CLK", EN="LDSX_n")
    for j in range(8):
        if j < 4:
            r[f"D{j + 1}"], r[f"Q{j + 1}"] = SXD[j], SX[j]
        else:
            r[f"D{j + 1}"] = "GND"
    RFAA, RFBA = bus("RFAA", 5), bus("RFBA", 5)
    for side, sel, addr in (("A", "RFA", RFAA), ("B", "RFB", RFBA)):
        for k in range(2):
            m = nl.add("153", f"U_RF{side}M{k}", A=u[f"{sel}0"], B=u[f"{sel}1"],
                       **{"1G": "GND", "2G": "GND"})
            for sec in (0, 1):
                i = 2 * k + sec
                for c, s in enumerate([IR[8 + i], IR[i], SX[i], u[f"RFK{i}"]]):
                    m[f"{sec + 1}C{c}"] = s
                m[f"{sec + 1}Y"] = addr[i]
        g("21", [u[f"{sel}0"], u[f"{sel}1"], u["RFK4"]], addr[4])
    for side, addr, data, oe in (("A", RFAA, ABUS, u["ARF_n"]), ("B", RFBA, BBUS, u["BRF_n"])):
        for k in range(4):
            ram = nl.add("sram", f"U_RF{side}{k}", role="rf", CE="GND", OE=oe, WE="RFWE_n")
            for i in range(15):
                ram[f"A{i}"] = addr[i] if i < 5 else "GND"
            for i in range(8):
                ram[f"IO{i}"] = data[8 * k + i]
    # r0 is never written, except by the reset routine (WR0)
    g("32", [RFAA[0], RFAA[1]], "RFNZ01")
    g("32", [RFAA[2], RFAA[3]], "RFNZ23")
    g("32", ["RFNZ01", "RFNZ23"], "RFNZ03")
    g("32", ["RFNZ03", RFAA[4]], "RFNZ")
    g("32", ["RFNZ", u["WR0"]], "RFWOK")
    g("10", [u["RFWE"], "WEWIN", "RFWOK"], "RFWE_n")

    # ---- A bus drivers: PC, R, R x 2 + SINA, bridge from B ------------------------
    nl.add("153", "U_SINA", A=u["SINA0"], B=u["SINA1"],
           **{"1G": "GND", "2G": "VCC", "1C0": "GND", "1C1": RQ[31], "1C2": "CFLAG",
              "1C3": "MQ31", "1Y": "SINA", "2C0": "GND", "2C1": "GND", "2C2": "GND", "2C3": "GND"})
    R2 = ["SINA"] + RQ[:31]
    for k in range(4):
        for ref, src, oe in ((f"U_APC{k}", PC, u["APC_n"]), (f"U_AR{k}", RQ, u["AR_n"]),
                             (f"U_AR2{k}", R2, u["AR2_n"]), (f"U_ABR{k}", BBUS, u["ABR_n"])):
            b = nl.add("541", ref, OE1=oe, OE2="GND")
            for i in range(8):
                b[f"A{i + 1}"], b[f"Y{i + 1}"] = src[8 * k + i], ABUS[8 * k + i]

    # ---- B bus drivers -----------------------------------------------------------
    for k in range(4):
        b = nl.add("541", f"U_BR{k}", OE1=u["BR_n"], OE2="GND")
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = RQ[8 * k + i], BBUS[8 * k + i]
    # T by byte lane; byte 0 comes from T's byte 1 for a byte at an odd address
    # (the 541s' second enables pick the lane)
    g("00", [u["TLANE"], MAR[0]], "ODD_n")
    g("08", [u["TLANE"], MAR[0]], "ODD")
    for ref, src, dst, oe, oe2 in (("U_BT0", TQ[0:8], BBUS[0:8], u["BT0_n"], "ODD"),
                                   ("U_BT10", TQ[8:16], BBUS[0:8], u["BT0_n"], "ODD_n"),
                                   ("U_BT1", TQ[8:16], BBUS[8:16], u["BT1_n"], "GND"),
                                   ("U_BT2", TQ[16:24], BBUS[16:24], u["BT23_n"], "GND"),
                                   ("U_BT3", TQ[24:32], BBUS[24:32], u["BT23_n"], "GND")):
        b = nl.add("541", ref, OE1=oe, OE2=oe2)
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = src[i], dst[i]
    T2 = ["GND"] + TQ[0:15]                       # 2 * T.lo (bit 16 = T15 comes from the fill)
    for k in range(2):
        b = nl.add("541", f"U_BTX{k}", OE1=u["BT2_n"], OE2="GND")
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = T2[8 * k + i], BBUS[8 * k + i]
    # immediate unit: byte 0 = V8 (branch offset x 2, constant, fill, LC), fill above
    nl.add("151", "U_FILLM", A=u["FSEL0"], B=u["FSEL1"], C=u["FSEL2"], G="GND", Y="FILL",
           D0="GND", D1="VCC", D2=IR[7], D3=TQ[7], D4=TQ[15], D5=ABUS[31], D6=ABUS[15], D7="SGNQ")
    V8 = bus("V8", 8)
    for k in range(4):
        m = nl.add("153", f"U_V8M{k}", A=u["V80"], B=u["V81"], **{"1G": "GND", "2G": "GND"})
        for sec in (0, 1):
            i = 2 * k + sec
            bcc = "GND" if i == 0 else IR[i - 1]
            for c, s in enumerate([bcc, u[f"KONST{i}"], "FILL", LC[i]]):
                m[f"{sec + 1}C{c}"] = s
            m[f"{sec + 1}Y"] = V8[i]
    for ref, src, dst, oe in (("U_BS0", V8, BBUS[0:8], u["BS0_n"]),
                              ("U_BF1", ["FILL"] * 8, BBUS[8:16], u["BF1_n"]),
                              ("U_BF2", ["FILL"] * 8, BBUS[16:24], u["BF23_n"]),
                              ("U_BF3", ["FILL"] * 8, BBUS[24:32], u["BF23_n"]),
                              ("U_BFL", ["VFLAG", "CFLAG", "ZFLAG", "NFLAG", "IFLAG", "GND", "GND",
                                         "GND"], BBUS[0:8], u["BFL_n"])):
        b = nl.add("541", ref, OE1=oe, OE2="GND")
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = src[i], dst[i]

    # MQ: 4 x 74HCT299 on the B bus. Chip k holds bits 8k..8k+7 with I/O n =
    # bit 8k+7-n, so the 299's shift toward Q7 is a right shift of MQ (DS0
    # in at the top) and its shift toward Q0 a left shift (DS7 in at the bottom).
    def mqs(bit):
        return {0: "MQ0", 31: "MQ31"}.get(bit, f"MQS{bit}")
    for k in range(4):
        sr = nl.add("299", f"U_MQ{k}", S0=u["MQM0"], S1=u["MQM1"], OE1=u["BMQ_n"], OE2="GND",
                    MR="VCC", CP="CLK", Q0S=mqs(8 * k + 7), Q7S=mqs(8 * k))
        for n in range(8):
            sr[f"IO{n}"] = BBUS[8 * k + 7 - n]
        sr["DS0"] = F[0] if k == 3 else mqs(8 * (k + 1))
        sr["DS7"] = "QBIT" if k == 0 else mqs(8 * (k - 1) + 7)

    # ---- loop counter ------------------------------------------------------------
    nl.add("161", "U_LC0", CLK="CLK", CLR="VCC", LOAD=u["LDLC_n"], ENP=u["LCINC"], ENT="VCC",
           A=RES[0], B=RES[1], C=RES[2], D=RES[3], QA=LC[0], QB=LC[1], QC=LC[2], QD=LC[3],
           RCO="TC4")
    nl.add("161", "U_LC1", CLK="CLK", CLR="VCC", LOAD=u["LDLC_n"], ENP=u["LCINC"], ENT="TC4",
           A=RES[4], B=RES[5], C=RES[6], D=RES[7], QA=LC[4], QB=LC[5], QC=LC[6], QD=LC[7],
           RCO="TC")

    # ---- ALU control: multiply/divide steps take over the function ----------------
    # MS (step select) 0: S from the uIR; 1 add if MQ[0] (S = 1001 or 0000);
    # 2 subtract if MQ[0] (0110 or 0000); 3 add if S33, else subtract (divide)
    # or pass (fix-up, MQM = 00). The carry in always comes from CIN (the
    # microcode picks mq0 or s33n for steps) and M from the uIR.
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

    # ---- ALU: 8 x 74181, two-level carry lookahead (3 x 74182) ----------------------
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
           **{f"P{i}": f"ALUP{4 + i}" for i in range(4)}, **{f"G{i}": f"ALUG{4 + i}" for i in range(4)})
    nl.add("182", "U_CLA2", CN="CIN_n", CNX="C16_n", P0="GP0", G0="GG0",
           P1="VCC", G1="VCC", P2="VCC", G2="VCC", P3="VCC", G3="VCC")
    g("04", ["CARRY_n"], "C32")
    # overflow: V = (A31 ^ B31 ^ S0) & (A31 ^ F31); S0 tells adding from subtracting
    g("86", [BBUS[31], SE[0]], "VT1")
    g("86", [ABUS[31], "VT1"], "VT2")
    g("86", [ABUS[31], F[31]], "VT3")                  # OVF = VT2 & VT3, see U_FV

    # ---- result multiplexer: F, F >> 1, ror 8, ror 16; bytes can be cleared ----------
    g("04", [u["MQM1"]], "MQM1_n")
    g("08", [u["MQM0"], "MQM1_n"], "MULSTEP")                # MQ shifts right
    # the sign of a Booth step's 33-bit sum (F31 ^ OVF) is A31 if the operands'
    # signs agree (VT2), else F31
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

    # ---- R, T ------------------------------------------------------------------------
    for k in range(4):
        r = nl.add("377", f"U_R{k}", CLK="CLK", EN=u["LDR_n"])
        t = nl.add("377", f"U_T{k}", CLK="CLK", EN=u["LDTL_n"] if k < 2 else u["LDTH_n"])
        for i in range(8):
            r[f"D{i + 1}"], r[f"Q{i + 1}"] = RES[8 * k + i], RQ[8 * k + i]
            t[f"D{i + 1}"], t[f"Q{i + 1}"] = DBUS[8 * (k % 2) + i], TQ[8 * k + i]

    # ---- MAR (bits 0-19 and 31) from the result bus or straight from the A bus ---------
    MARIN = bus("MARIN", 21)
    msrc = [(RES[i], ABUS[i]) for i in range(20)] + [(RES[31], ABUS[31])]
    for k in range(6):
        m = nl.add("157", f"U_MARM{k}", S=u["MARSRC"], G="GND")
        for j in range(4):
            i = 4 * k + j
            if i < 21:
                m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = msrc[i][0], msrc[i][1], MARIN[i]
            else:
                m[f"{j + 1}A"], m[f"{j + 1}B"] = "GND", "GND"
    for k in range(3):
        r = nl.add("377", f"U_MAR{k}", CLK="CLK", EN=u["LDMAR_n"])
        for j in range(8):
            i = 8 * k + j
            if i < 21:
                r[f"D{j + 1}"], r[f"Q{j + 1}"] = MARIN[i], MAR[i]
            else:
                r[f"D{j + 1}"] = "GND"

    # ---- PC: 8 x 74HCT161 (bits 1-31), +2 on every read at the PC ------------------------
    g("02", [u["MEMRD_n"], u["ADDRMAR"]], "PCINC")
    rco = [f"PCRCO{s}" for s in range(8)]
    g("21", ["PCINC", rco[0]], "PCE1")
    g("21", ["PCINC", rco[0], rco[1]], "PCE2")
    g("21", ["PCINC", rco[0], rco[1], rco[2]], "PCE3")
    g("21", [rco[0], rco[1], rco[2], rco[3]], "PCQ4")
    g("21", ["PCINC", "PCQ4"], "PCE4")
    g("21", ["PCINC", "PCQ4", rco[4]], "PCE5")
    g("21", ["PCINC", "PCQ4", rco[4], rco[5]], "PCE6")
    g("08", [rco[5], rco[6]], "PCQ56")
    g("21", ["PCINC", "PCQ4", rco[4], "PCQ56"], "PCE7")
    enp = ["PCINC", "PCE1", "PCE2", "PCE3", "PCE4", "PCE5", "PCE6", "PCE7"]
    for s in range(8):
        c = nl.add("161", f"U_PC{s}", CLK="CLK", CLR="RESET_n", LOAD="PCLOAD_n", ENP=enp[s],
                   ENT="VCC", RCO=rco[s])
        for j, (dp, qp) in enumerate(zip("ABCD", ("QA", "QB", "QC", "QD"))):
            bit = 1 + 4 * s + j
            if bit <= 31:
                c[dp], c[qp] = RES[bit], PC[bit]
            else:
                c[dp] = "GND"
    g("00", [u["PCCOND"], "BCOND_n"], "CONDOK")
    g("00", [u["LDPC"], "CONDOK"], "PCLOAD_n")

    # ---- address multiplexer and memory --------------------------------------------------
    g("32", [MAR[1], u["HIWORD"]], "MAR1H")
    asrc = [("GND", MAR[0]), (PC[1], "MAR1H")] + [(PC[i], MAR[i]) for i in range(2, 20)]
    for k in range(5):
        m = nl.add("157", f"U_ADM{k}", S=u["ADDRMAR"], G="GND")
        for j in range(4):
            i = 4 * k + j
            m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = asrc[i][0], asrc[i][1], ADDR[i]
    # the I/O page is anything with MAR[31] set (decoded from MAR, not the address
    # mux). A misaligned access still reads the RAM (the data is ignored) but
    # never selects the I/O device, whose reads have side effects.
    g("08", [u["ADDRMAR"], "MAR31"], "RAMOFF")
    g("10", [u["ADDRMAR"], "MAR31", "FAULT_n"], "IOSEL_n")
    g("04", [u["SIZE1"]], "SIZE1_n")
    g("08", [u["SIZE0"], "SIZE1_n"], "BYTE")           # SIZE 1: one byte lane
    g("04", [ADDR[0]], "ADDR0_n")
    g("00", ["BYTE", ADDR[0]], "LOEN")
    g("00", ["BYTE", "ADDR0_n"], "HIEN")
    g("08", [u["MEMWR"], "FAULT_n"], "MWOK")
    g("10", ["MWOK", "WEWIN", "LOEN"], "WEL_n")
    g("10", ["MWOK", "WEWIN", "HIEN"], "WEH_n")
    for half, we in ((0, "WEL_n"), (1, "WEH_n")):
        ram = nl.add("sram512", f"U_RAM{'LH'[half]}", role="ram", CE="RAMOFF", OE=u["MEMRD_n"], WE=we)
        for i in range(19):
            ram[f"A{i}"] = ADDR[i + 1]
        for i in range(8):
            ram[f"IO{i}"] = DBUS[8 * half + i]
    io = nl.add("iodev32", "X_IO", CLK="CLK", IOSEL="IOSEL_n", RD=u["MEMRD_n"], WEL="WEL_n",
                WEH="WEH_n", IRQ="IRQ")
    for i in range(8):
        io[f"A{i}"] = ADDR[i]
    for i in range(16):
        io[f"D{i}"] = DBUS[i]

    # store data: result bus low half (DSRC 11), high half (10), or low byte on
    # both lanes (01). The two enables of each 541 decode it, so the drivers
    # turn off quickly when the next cycle's RAM read turns on.
    g("04", [u["DSRC0_n"]], "DSRC0")
    g("04", [u["DSRC1_n"]], "DSRC1")
    for ref, src, dst, oe1, oe2 in (("U_DR0", RES[0:8], DBUS[0:8], u["DSRC0_n"], "GND"),
                                    ("U_DR1", RES[8:16], DBUS[8:16], u["DSRC0_n"], u["DSRC1_n"]),
                                    ("U_DR2", RES[16:24], DBUS[0:8], "DSRC0", u["DSRC1_n"]),
                                    ("U_DR3", RES[24:32], DBUS[8:16], "DSRC0", u["DSRC1_n"]),
                                    ("U_DRB", RES[0:8], DBUS[8:16], u["DSRC0_n"], "DSRC1")):
        b = nl.add("541", ref, OE1=oe1, OE2=oe2)
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = src[i], dst[i]

    # ---- flags ---------------------------------------------------------------------------
    for k in range(4):
        nl.add("688", f"U_Z{k}", G="GND", PEQ=f"ZB{k}_n",
               **{f"P{i}": BBUS[8 * k + i] for i in range(8)}, **{f"Q{i}": "GND" for i in range(8)})
    g("32", ["ZB0_n", "ZB1_n"], "NZ01")
    g("32", ["ZB2_n", "ZB3_n"], "NZ23")
    g("02", ["NZ01", "NZ23"], "ZERO")
    g("02", ["NZ23", "GND"], "HZ16")                   # B[31:16] == 0
    g("02", ["NZ23", BBUS[15]], "HZ17")                # B[31:15] == 0
    g("08", ["ZFLAG", "ZERO"], "ZSTICKY")
    nl.add("153", "U_FNZ", A=u["FNZ0"], B=u["FNZ1"],
           **{"1G": "GND", "2G": "GND",
              "1C0": "NFLAG", "1C1": BBUS[31], "1C2": BBUS[31], "1C3": BBUS[3], "1Y": "NNEXT",
              "2C0": "ZFLAG", "2C1": "ZERO", "2C2": "ZSTICKY", "2C3": BBUS[2], "2Y": "ZNEXT"})
    g("86", [F[7], "FILL"], "F7X")
    g("86", [F[15], "FILL"], "F15X")
    nl.add("151", "U_CSRC", A=u["CSRC0"], B=u["CSRC1"], C=u["CSRC2"], G="GND", Y="CSRCY",
           D0=BBUS[1], D1=F[0], D2=F[7], D3=F[8], D4=F[15], D5=F[31], D6="F7X", D7="F15X")
    nl.add("153", "U_FC", A=u["FC0"], B=u["FC1"],
           **{"1G": u["CZERO"], "2G": "VCC",
              "1C0": "CFLAG", "1C1": "CSRCY", "1C2": "C32", "1C3": "CL_n", "1Y": "CNEXT",
              "2C0": "GND", "2C1": "GND", "2C2": "GND", "2C3": "GND"})
    # V: FV 7 selects VT3 = A31 ^ F31, with the multiplexer disabled (output 0)
    # unless the operands' signs allow an overflow (VT2)
    g("10", [u["FV0"], u["FV1"], u["FV2"]], "FVOVF_n")
    g("02", ["FVOVF_n", "VT2"], "FVOFF")
    nl.add("151", "U_FV", A=u["FV0"], B=u["FV1"], C=u["FV2"], G="FVOFF", Y="VNEXT",
           D0="VFLAG", D1="GND", D2="GND", D3=BBUS[0], D4="CL_n", D5="VCC", D6="GND", D7="VT3")
    nl.add("153", "U_FI", A=u["FI0"], B=u["FI1"],
           **{"1G": "GND", "2G": "VCC",
              "1C0": "IFLAG", "1C1": "VCC", "1C2": "GND", "1C3": BBUS[4], "1Y": "INEXT",
              "2C0": "GND", "2C1": "GND", "2C2": "GND", "2C3": "GND"})
    nl.add("175", "U_FLAGS", CLK="CLK", CLR="VCC",
           **{"1D": "NNEXT", "1Q": "NFLAG", "1QN": "NFLAG_n",
              "2D": "ZNEXT", "2Q": "ZFLAG", "2QN": "ZFLAG_n",
              "3D": "CNEXT", "3Q": "CFLAG", "3QN": "CFLAG_n",
              "4D": "VNEXT", "4Q": "VFLAG", "4QN": "VFLAG_n"})
    nl.add("74", "U_IFLAG", **{"1D": "INEXT", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "RESET_n",
                               "1Q": "IFLAG", "1QN": "IFLAG_n",
                               "2D": "GND", "2CLK": "GND", "2PRE": "VCC", "2CLR": "VCC"})

    # condition latch CL, sign latch SGN, divide sign S33
    # CLSRC 4 and 5 AND the test with CL: the multiplexer is disabled if CL is 0
    g("08", [u["CLSRC2"], "CL_n"], "CLOFF")
    nl.add("151", "U_CLM", A=u["CLSRC0"], B=u["CLSRC1"], C=u["CLSRC2"], G="CLOFF", Y="CLSRCY",
           D0="ZERO", D1="C32", D2="HZ16", D3="HZ17", D4="HZ16", D5="HZ17", D6="GND", D7="GND")
    # divide step: the new sign S33 = R31 ^ C32 ^ (subtracting = S33_n), and the
    # quotient bit is its complement; both are one XOR after the carry out
    # (C32 = !CARRY_n)
    g("86", [RQ[31], "S33_n"], "RG")
    g("04", ["RG"], "RG_n")
    g("86", ["RG", "CARRY_n"], "QBIT")                  # quotient bit into MQ
    g("86", ["RG_n", "CARRY_n"], "S33NEW")
    g("04", [u["MQM0"]], "MQM0_n")
    g("08", ["MQM0_n", u["MQM1"]], "DIVSTEP")          # MQ shifts left
    g("00", [u["MQM0"], u["MQM1"]], "MQLOAD_n")
    g("08", ["S33Q", "MQLOAD_n"], "S33KEEP")
    # two independent 2:1 multiplexers in one 74HCT153 (select CL by A, SGN by B)
    nl.add("153", "U_LATM", A=u["LDCL"], B=u["LDSGN"], **{"1G": "GND", "2G": "GND",
           "1C0": "CLQ", "1C1": "CLSRCY", "1C2": "CLQ", "1C3": "CLSRCY", "1Y": "CL_D",
           "2C0": "SGNQ", "2C1": "SGNQ", "2C2": "FILL", "2C3": "FILL", "2Y": "SGN_D"})
    nl.add("157", "U_S33MX", S="DIVSTEP", G="GND",
           **{"1A": "S33KEEP", "1B": "S33NEW", "1Y": "S33_D",
              "2A": "GND", "2B": "GND", "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    nl.add("74", "U_LAT0", **{"1D": "CL_D", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "VCC",
                              "1Q": "CLQ", "1QN": "CL_n",
                              "2D": "SGN_D", "2CLK": "CLK", "2PRE": "VCC", "2CLR": "VCC",
                              "2Q": "SGNQ"})
    nl.add("74", "U_LAT1", **{"1D": "S33_D", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "VCC",
                              "1Q": "S33Q", "1QN": "S33_n",
                              "2D": "GND", "2CLK": "GND", "2PRE": "VCC", "2CLR": "VCC"})

    # ---- branch condition (ARM encoding): cc from IR[11:8], or IR[7:4] for SETcc -------
    CC = bus("CC", 4)
    m = nl.add("157", "U_CCM", S=u["CCB"], G="GND")
    for j in range(4):
        m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = IR[8 + j], IR[4 + j], CC[j]
    g("08", ["CFLAG", "ZFLAG_n"], "C_HI")
    g("86", ["NFLAG", "VFLAG_n"], "N_EQ_V")
    g("08", ["ZFLAG_n", "N_EQ_V"], "C_GT")
    nl.add("151", "U_COND", A=CC[1], B=CC[2], C=CC[3], G="GND", Y="CONDT", W="CONDT_n",
           D0="ZFLAG", D1="CFLAG", D2="NFLAG", D3="VFLAG", D4="C_HI", D5="N_EQ_V", D6="C_GT", D7="VCC")
    # microcode branches use CONDT or CONDT_n (the decode ROM picks a routine
    # for each polarity); conditional PC loads (Bcc) apply the polarity here
    g("86", ["CONDT_n", CC[0]], "BCOND_n")

    nl.finish()
    nl.check()
    return nl


# nets the hardware simulator needs (see hwsim/main.go)
CONFIG = {
    "rf_chips": {"A": [f"U_RFA{k}" for k in range(4)], "B": [f"U_RFB{k}" for k in range(4)]},
    "rf_entries": 32,
    "ram_chips": ["U_RAML", "U_RAMH"],
    "ram_bits": 19,
    "addr_bits": 20,
    "pc_bits": 31,
    "fetch_net": "uLDIR_n",
    "halt_net": "uHALT",
    "halt_level": 1,
    "start": "first_fetch",
    "io_model": "iodev32",
}
