"""Chip-level netlist of the v0 CPU (plus 64 KB RAM and the I/O page).

Buses
  ABUS  ALU A input   <- RF copy A, PC, R
  BBUS  ALU B input   <- RF copy B, immediate unit, memory data, T, R, flags
  F     ALU output (74181 x4 + 74182)
  RES   result bus = F through the byte/shift multiplexer (74HCT153 x8)
  DBUS  memory data   <- RAM, I/O, result bus, PC
  ADDR  memory address <- PC or MAR

Register file: two copies of 16 x 16 bits in fast SRAM (4 chips), one per
ALU input, written together from R. See docs/hardware.md.
"""

from .netlist import Netlist
from . import microcode as mc


def bus(name, n, start=0):
    return [f"{name}{i}" for i in range(start, start + n)]


def control_nets():
    """Microcode field bit -> net name (with _n for active-low fields)."""
    nets = {}
    for name, (bit, w, al) in mc._pos.items():
        for i in range(w):
            nets[bit + i] = f"u{name}{i if w > 1 else ''}{'_n' if al else ''}"
    return nets


def build():
    nl = Netlist()
    g = nl.gate
    U = control_nets()
    u = {v.lstrip("u"): v for v in U.values()}     # e.g. u["BSRC0"] -> "uBSRC0", u["ARF_n"]

    ABUS, BBUS, F, RES = bus("ABUS", 16), bus("BBUS", 16), bus("F", 16), bus("RES", 16)
    DBUS, ADDR, IR = bus("DBUS", 16), bus("ADDR", 16), bus("IR", 16)
    RQ, TQ, MAR, MARIN = bus("R", 16), bus("T", 16), bus("MAR", 16), bus("MARIN", 16)
    PC = ["GND"] + bus("PC", 15, 1)      # PC bit 0 is always 0

    # ---- fixtures: clock/reset generator, rails, I/O devices ----------------
    nl.add("clockgen", "X_CLK", CLK="CLK", WEWIN="WEWIN", RESET="RESET_n")
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")

    # ---- control store ------------------------------------------------------
    STEP = bus("STEP", 4)
    nl.add("163", "U_STEP", CLK="CLK", CLR="STEPCLR_n", LOAD="VCC", ENP=u["HALT_n"], ENT="VCC",
           A="GND", B="GND", C="GND", D="GND", QA=STEP[0], QB=STEP[1], QC=STEP[2], QD=STEP[3])
    g("08", [u["END_n"], "RESET_n"], "STEPCLR_n")

    UA = STEP + IR[0:4] + IR[12:16] + ["IRQP", "LINK", "MODEIRQ", "MODERST", "GND"]
    for k in range(mc.ROMS):
        rom = nl.add("flash", f"U_UC{k}", CE="GND", OE="GND", WE="VCC")
        for i, a in enumerate(UA):
            rom[f"A{i}"] = a
        for i in range(8):
            if 8 * k + i in U:
                rom[f"D{i}"] = U[8 * k + i]

    # mode register: updated at END. MODERST is set asynchronously by reset.
    nl.add("157", "U_MODEMUX", S=u["END_n"], G="GND",
           **{"1A": "IRQP", "1B": "MODEIRQ", "1Y": "MODEIRQ_D",
              "2A": "GND", "2B": "MODERST", "2Y": "MODERST_D",
              "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    nl.add("74", "U_MODE", **{"1D": "MODEIRQ_D", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "RESET_n",
                              "1Q": "MODEIRQ",
                              "2D": "MODERST_D", "2CLK": "CLK", "2PRE": "RESET_n", "2CLR": "VCC",
                              "2Q": "MODERST"})
    # interrupt request: synchronise, then register IRQ & I_next
    nl.add("74", "U_IRQ", **{"1D": "IRQ", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "RESET_n", "1Q": "IRQS",
                             "2D": "IRQP_D", "2CLK": "CLK", "2PRE": "VCC", "2CLR": "RESET_n",
                             "2Q": "IRQP"})
    g("08", ["IRQS", "INEXT"], "IRQP_D")

    # B bus source decoder
    nl.add("138", "U_BDEC", A=u["BSRC0"], B=u["BSRC1"], C=u["BSRC2"], G1="VCC", G2A="GND", G2B="GND",
           Y1="RFB_OE_n", Y2="IMM_OE_n", Y3="MEMB_OE_n", Y4="T_OE_n", Y5="RB_OE_n", Y6="FLG_OE_n")
    g("08", ["IMM_OE_n", "FLG_OE_n"], "IMMHI_OE_n")    # flags need a zero high byte

    # ---- instruction register and predecode ---------------------------------
    for half, ref in ((0, "U_IRL"), (1, "U_IRH")):
        r = nl.add("377", ref, CLK="CLK", EN=u["LDIR_n"])
        for i in range(8):
            r[f"D{i + 1}"] = DBUS[8 * half + i]
            r[f"Q{i + 1}"] = IR[8 * half + i]
    g("21", DBUS[8:12], "LINKD")
    irx = nl.add("377", "U_IRX", CLK="CLK", EN=u["LDIR_n"], D1="LINKD", Q1="LINK")
    for i in range(2, 9):
        irx[f"D{i}"] = "GND"

    # ---- register file -----------------------------------------------------
    RFAA, RFBA = bus("RFAA", 4), bus("RFBA", 4)
    for side, sel, addr in (("A", "RFA", RFAA), ("B", "RFB", RFBA)):
        for k in range(2):
            m = nl.add("153", f"U_RF{side}M{k}", A=u[f"{sel}0"], B=u[f"{sel}1"], **{"1G": "GND", "2G": "GND"})
            for sec in (0, 1):
                bit = 2 * k + sec
                srcs = [IR[8 + bit], IR[4 + bit], "VCC", "GND"]     # d, s, sp (15), zero
                for i, s in enumerate(srcs):
                    m[f"{sec + 1}C{i}"] = s
                m[f"{sec + 1}Y"] = addr[bit]
    for side, addr, data, oe in (("A", RFAA, ABUS, u["ARF_n"]), ("B", RFBA, BBUS, "RFB_OE_n")):
        for half in (0, 1):
            ram = nl.add("sram", f"U_RF{side}{'LH'[half]}", role="rf", CE="GND", OE=oe, WE="RFWE_n")
            for i in range(15):
                ram[f"A{i}"] = addr[i] if i < 4 else "GND"
            for i in range(8):
                ram[f"IO{i}"] = data[8 * half + i]
    g("32", [RFAA[0], RFAA[1]], "RFNZ01")
    g("32", [RFAA[2], RFAA[3]], "RFNZ23")
    g("32", ["RFNZ01", "RFNZ23"], "RFNZ")
    g("32", ["RFNZ", "MODERST"], "RFWOK")        # r0 is writable only during reset
    g("10", [u["RFWE"], "WEWIN", "RFWOK"], "RFWE_n")

    # ---- R (result holding register) ---------------------------------------
    for half in (0, 1):
        r = nl.add("377", f"U_R{'LH'[half]}", CLK="CLK", EN=u["LDR_n"])
        ba = nl.add("541", f"U_RA{'LH'[half]}", OE1=u["AR_n"], OE2="GND")
        bb = nl.add("541", f"U_RB{'LH'[half]}", OE1="RB_OE_n", OE2="GND")
        for i in range(8):
            b = 8 * half + i
            r[f"D{i + 1}"] = RES[b]
            r[f"Q{i + 1}"] = RQ[b]
            ba[f"A{i + 1}"] = RQ[b]
            ba[f"Y{i + 1}"] = ABUS[b]
            bb[f"A{i + 1}"] = RQ[b]
            bb[f"Y{i + 1}"] = BBUS[b]

    # ---- T (memory data holding register) ----------------------------------
    for half in (0, 1):
        r = nl.add("377", f"U_T{'LH'[half]}", CLK="CLK", EN=u["LDT_n"])
        bb = nl.add("541", f"U_TB{'LH'[half]}", OE1="T_OE_n", OE2="GND")
        for i in range(8):
            b = 8 * half + i
            r[f"D{i + 1}"] = DBUS[b]
            r[f"Q{i + 1}"] = TQ[b]
            bb[f"A{i + 1}"] = TQ[b]
            bb[f"Y{i + 1}"] = BBUS[b]

    # ---- program counter -----------------------------------------------------
    ent = "VCC"
    for k in range(4):
        c = nl.add("161", f"U_PC{k}", CLK="CLK", CLR="RESET_n", LOAD="PCLOAD_n", ENP="INCPC", ENT=ent,
                   RCO=f"PCRCO{k}")
        for j, (dp, qp) in enumerate(zip("ABCD", ("QA", "QB", "QC", "QD"))):
            bit = 1 + 4 * k + j
            if bit <= 15:
                c[dp] = RES[bit]
                c[qp] = PC[bit]
            else:
                c[dp] = "GND"
        ent = f"PCRCO{k}"
    g("02", [u["ADDRMAR"], u["MEMRD_n"]], "INCPC")          # every read at PC increments PC
    g("86", ["CONDW", IR[8]], "COND_n")
    g("00", [u["PCCOND"], "COND_n"], "CONDOK")
    g("00", [u["LDPC"], "CONDOK"], "PCLOAD_n")
    for half in (0, 1):
        pa = nl.add("541", f"U_PCA{'LH'[half]}", OE1=u["APC_n"], OE2="GND")
        pd = nl.add("541", f"U_PCD{'LH'[half]}", OE1=u["DPC_n"], OE2="GND")
        for i in range(8):
            b = 8 * half + i
            pa[f"A{i + 1}"] = PC[b]
            pa[f"Y{i + 1}"] = ABUS[b]
            pd[f"A{i + 1}"] = PC[b]
            pd[f"Y{i + 1}"] = DBUS[b]

    # ---- MAR and the address multiplexer -------------------------------------
    for k in range(4):
        m = nl.add("157", f"U_MARM{k}", S=u["MARSRC"], G="GND")
        a = nl.add("157", f"U_ADM{k}", S=u["ADDRMAR"], G="GND")
        for j in range(4):
            b = 4 * k + j
            m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = RES[b], ABUS[b], MARIN[b]
            a[f"{j + 1}A"], a[f"{j + 1}B"], a[f"{j + 1}Y"] = PC[b], MAR[b], ADDR[b]
    for half in (0, 1):
        r = nl.add("377", f"U_MAR{'LH'[half]}", CLK="CLK", EN=u["LDMAR_n"])
        for i in range(8):
            r[f"D{i + 1}"] = MARIN[8 * half + i]
            r[f"Q{i + 1}"] = MAR[8 * half + i]

    # ---- immediate unit ------------------------------------------------------
    N = bus("IMMN", 4)
    consts = {0: ["VCC", "GND", "GND"], 1: ["GND", "VCC", "GND"], 2: ["GND", "GND", "VCC"],
              3: ["GND", "GND", "GND"]}            # nibble bit -> (const 1, 2, 4)
    for k in range(2):
        m = nl.add("153", f"U_NSEL{k}", A=u["NSEL0"], B=u["NSEL1"], **{"1G": "GND", "2G": "GND"})
        for sec in (0, 1):
            bit = 2 * k + sec
            for i, s in enumerate([IR[bit]] + consts[bit]):
                m[f"{sec + 1}C{i}"] = s
            m[f"{sec + 1}Y"] = N[bit]
    X = N + bus("IMMX", 4, 4)
    for i in range(4, 8):
        g("08", [IR[i], u["IMM8"]], X[i])           # X[7] is also the sign
    IMMV = bus("IMMV", 8)
    for k in range(2):
        m = nl.add("157", f"U_SCALE{k}", S=u["SCALE"], G="GND")
        for j in range(4):
            b = 4 * k + j
            m[f"{j + 1}A"] = X[b]
            m[f"{j + 1}B"] = X[b - 1] if b > 0 else "GND"
            m[f"{j + 1}Y"] = IMMV[b]
    lo = nl.add("541", "U_IMML", OE1="IMM_OE_n", OE2="GND")
    hi = nl.add("541", "U_IMMH", OE1="IMMHI_OE_n", OE2="GND")
    for i in range(8):
        lo[f"A{i + 1}"], lo[f"Y{i + 1}"] = IMMV[i], BBUS[i]
        hi[f"A{i + 1}"], hi[f"Y{i + 1}"] = X[7], BBUS[8 + i]

    # ---- ALU -----------------------------------------------------------------
    cn_in = ["CIN_n", "CNX", "CNY", "CNZ"]
    for k in range(4):
        a = nl.add("181", f"U_ALU{k}", M=u["M"], CN=cn_in[k], P=f"ALUP{k}", G=f"ALUG{k}",
                   **{f"S{i}": u[f"S{i}"] for i in range(4)})
        for i in range(4):
            a[f"A{i}"], a[f"B{i}"], a[f"F{i}"] = ABUS[4 * k + i], BBUS[4 * k + i], F[4 * k + i]
        if k == 3:
            a["CN4"] = "CARRY_n"
    nl.add("182", "U_CLA", CN="CIN_n", CNX="CNX", CNY="CNY", CNZ="CNZ",
           **{f"P{i}": f"ALUP{i}" for i in range(4)}, **{f"G{i}": f"ALUG{i}" for i in range(4)})
    # carry-in and shift-in share the CSEL field
    nl.add("153", "U_CSEL", A=u["CSEL0"], B=u["CSEL1"],
           **{"1G": "GND", "2G": "GND",
              "1C0": "VCC", "1C1": "GND", "1C2": "CFLAG_n", "1C3": "CFLAG_n", "1Y": "CIN_n",
              "2C0": "GND", "2C1": F[15], "2C2": "CFLAG", "2C3": "GND", "2Y": "SIN"})

    # ---- result multiplexer: byte lanes, swap, shift right, sign-extend ------
    g("08", [u["BYTE"], MAR[0]], "BYTEODD")
    g("32", [u["LO0"], "BYTEODD"], "LOSEL0")
    for k in range(4):
        m = nl.add("153", f"U_LO{k}", A="LOSEL0", B=u["LO1"], **{"1G": "GND", "2G": "GND"})
        for sec in (0, 1):
            i = 2 * k + sec
            for c, s in enumerate([F[i], F[i + 8], F[i + 1], F[i]]):
                m[f"{sec + 1}C{c}"] = s
            m[f"{sec + 1}Y"] = RES[i]
    for k in range(4):
        m = nl.add("153", f"U_HI{k}", A=u["HI0"], B=u["HI1"], **{"1G": u["HIZERO"], "2G": u["HIZERO"]})
        for sec in (0, 1):
            j = 8 + 2 * k + sec
            for c, s in enumerate([F[j], F[j - 8], F[j + 1] if j < 15 else "SIN", F[7]]):
                m[f"{sec + 1}C{c}"] = s
            m[f"{sec + 1}Y"] = RES[j]

    # ---- flags ----------------------------------------------------------------
    nl.add("688", "U_Z0", G="GND", PEQ="ZLO_n",
           **{f"P{i}": RES[i] for i in range(8)}, **{f"Q{i}": "GND" for i in range(8)})
    nl.add("688", "U_Z1", G="GND", PEQ="ZHI_n",
           **{f"P{i}": RES[8 + i] for i in range(8)}, **{f"Q{i}": "GND" for i in range(8)})
    g("32", ["ZLO_n", "ZHI_n"], "ZNEW_n")       # 1 = result not zero
    g("04", [RES[2]], "RES2_n")
    g("04", ["CARRY_n"], "CARRY")
    # overflow: add (S0=1) V = !(A15^B15) & (A15^F15); subtract (S0=0) V = (A15^B15) & (A15^F15)
    g("86", [BBUS[15], u["S0"]], "VT1")
    g("86", [ABUS[15], "VT1"], "VT2")
    g("86", [ABUS[15], F[15]], "VT3")
    g("08", ["VT2", "VT3"], "VNEW")
    nl.add("153", "U_FNZ", A=u["SETNZ"], B=u["LOADF"],
           **{"1G": "GND", "2G": "GND",
              "1C0": "NFLAG", "1C1": RES[15], "1C2": RES[3], "1C3": RES[3], "1Y": "NNEXT",
              "2C0": "ZFLAG_n", "2C1": "ZNEW_n", "2C2": "RES2_n", "2C3": "RES2_n", "2Y": "ZNEXT_n"})
    nl.add("153", "U_FCV", A=u["SETCV"], B=u["LDCV"],
           **{"1G": "GND", "2G": "GND",
              "1C0": "CFLAG", "1C1": "CARRY", "1C2": RES[1], "1C3": F[0], "1Y": "CNEXT",
              "2C0": "VFLAG", "2C1": "VNEW", "2C2": RES[0], "2C3": "GND", "2Y": "VNEXT"})
    nl.add("153", "U_FI", A=u["IWR"], B=u["LOADF"],
           **{"1G": "GND", "2G": "VCC",
              "1C0": "IFLAG", "1C1": u["IVAL"], "1C2": RES[4], "1C3": RES[4], "1Y": "INEXT",
              "2C0": "GND", "2C1": "GND", "2C2": "GND", "2C3": "GND"})
    nl.add("175", "U_FLAGS", CLK="CLK", CLR="VCC",
           **{"1D": "NNEXT", "1Q": "NFLAG", "1QN": "NFLAG_n",
              "2D": "ZNEXT_n", "2Q": "ZFLAG_n", "2QN": "ZFLAG",      # Z is stored inverted
              "3D": "CNEXT", "3Q": "CFLAG", "3QN": "CFLAG_n",
              "4D": "VNEXT", "4Q": "VFLAG", "4QN": "VFLAG_n"})
    nl.add("74", "U_IFLAG", **{"1D": "INEXT", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "RESET_n", "1Q": "IFLAG",
                               "2D": "GND", "2CLK": "GND", "2PRE": "VCC", "2CLR": "VCC"})
    fb = nl.add("541", "U_FLGB", OE1="FLG_OE_n", OE2="GND")
    for i, s in enumerate(["VFLAG", "CFLAG", "ZFLAG", "NFLAG", "IFLAG", "GND", "GND", "GND"]):
        fb[f"A{i + 1}"], fb[f"Y{i + 1}"] = s, BBUS[i]

    # ---- branch condition (ARM encoding: IR[11:9] picks a test, IR[8] inverts) --
    g("08", ["CFLAG", "ZFLAG_n"], "C_HI")
    g("86", ["NFLAG", "VFLAG_n"], "N_EQ_V")      # N xor !V = (N == V)
    g("08", ["ZFLAG_n", "N_EQ_V"], "C_GT")
    nl.add("151", "U_COND", A=IR[9], B=IR[10], C=IR[11], G="GND", W="CONDW",
           D0="ZFLAG", D1="CFLAG", D2="NFLAG", D3="VFLAG", D4="C_HI", D5="N_EQ_V", D6="C_GT", D7="VCC")

    # ---- memory data paths -----------------------------------------------------
    for half in (0, 1):
        db = nl.add("541", f"U_DB{'LH'[half]}", OE1="MEMB_OE_n", OE2="GND")
        rd = nl.add("541", f"U_RD{'LH'[half]}", OE1=u["DRES_n"], OE2="GND")
        for i in range(8):
            b = 8 * half + i
            db[f"A{i + 1}"], db[f"Y{i + 1}"] = DBUS[b], BBUS[b]
            rd[f"A{i + 1}"], rd[f"Y{i + 1}"] = RES[b], DBUS[b]

    # ---- memory: 2 x 32K x 8 RAM, I/O page at FF00-FFFF ------------------------
    # I/O select comes from MAR rather than the address mux (the PC never
    # points at the I/O page), which takes the decoder off the RAM access path.
    g("30", MAR[8:16], "MARIO_n")
    g("04", [u["ADDRMAR"]], "ADDRMAR_n")
    g("02", ["MARIO_n", "ADDRMAR_n"], "IOSEL")
    g("04", ["IOSEL"], "IOSEL_n")
    g("04", [ADDR[0]], "ADDR0_n")
    g("00", [u["BYTE"], ADDR[0]], "LOEN")          # byte write to an odd address: no low lane
    g("00", [u["BYTE"], "ADDR0_n"], "HIEN")
    g("10", [u["MEMWR"], "WEWIN", "LOEN"], "WEL_n")
    g("10", [u["MEMWR"], "WEWIN", "HIEN"], "WEH_n")
    for half, we in ((0, "WEL_n"), (1, "WEH_n")):
        ram = nl.add("sram", f"U_RAM{'LH'[half]}", role="ram", CE="IOSEL", OE=u["MEMRD_n"], WE=we)
        for i in range(15):
            ram[f"A{i}"] = ADDR[i + 1]
        for i in range(8):
            ram[f"IO{i}"] = DBUS[8 * half + i]
    io = nl.add("iodev", "X_IO", CLK="CLK", IOSEL="IOSEL_n", RD=u["MEMRD_n"], WEL="WEL_n", WEH="WEH_n",
                IRQ="IRQ")
    for i in range(8):
        io[f"A{i}"] = ADDR[i]
    for i in range(16):
        io[f"D{i}"] = DBUS[i]

    nl.finish()
    nl.check()
    return nl
