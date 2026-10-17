"""The IOP's card as a netlist, for the chip-level simulator (RFC 0027,
2-5; RFC 0037, 22): a first cut, built to run the same microcode as the
microinstruction-level model (sim/), clock for clock.

The parts are the v2-fast variant's (studies/v2_hw/parts.py): 74F and
74ABT logic, 74F181/182, 16-bit 74ABT registers and buffers as their 8-
and 9-bit halves. Where the library lacks a part RFC 0027 names, a
substitute stands in, and `SUBSTITUTES` says which.

The microcycle (RFC 0027, 3.2) is two bus clocks, from E0 through E1 to
E2. PH is its half: 0 the first, 1 the second. At each rising edge of
BCLK, PH turns to 1 (E1) unless STALL1 holds the first half, and back to
0 (E2) unless STALL2 holds the second. Every register is clocked by BCLK
with an enable: E1EN (the next edge is E1) for F and the carry, E2EN for
uIR, uPC, AC, X, BANK, AH0, AH1, LC and CTRL. The SRAM is written from
E1 until BCLK falls (PH and not PHD, PH taken on the falling edge).

The I/O bus side (RFC 0037, 16 and 22) runs an access in three states,
S0 (idle, or the setup), STB (the strobe) and HLD (the hold), with an
8-bit counter CNT that each state starts from 0 and a comparator against
its field of the device's timing table entry: a state ends at the edge
where CNT equals its field. An access starts in S0 the clock after the
microinstruction that makes it begins, or after the last access's hold.
Its address and WRITE are latched when S0 ends, its write data when STB
ends, and its read data at the strobe's end (a latch open during STB).
"""

from heron.infra.hw.netlist import Netlist
from heron.studies.v2_hw import parts

VARIANT = parts.VARIANT
BCLK_PS = 60_000                # RFC 0037's bus clock
UART_PS = 67_817                # 14.7456 MHz, the console UART's oscillator
CLKB_PS = 250_000               # 4 MHz, the timer's
POR_PS = 2_000_000

SUBSTITUTES = [
    ("74ABT16652 (the bus data registers, BA and AB)", "four 74ABT16823 halves"),
    ("74ABT273 (CTRL), a 74x259 as the study has it", "a 74F175 with a 74F138 and gates"),
    ("74F139 (field decoders)", "74F138"),
    ("SST39SF040 (the image flash, 512K x 8)", "SST39SF010A (128K x 8): 128K halfwords"),
    ("AS6C4008-55 (the shared RAM)", "AS7C4096A-12: the 55 ns part is too slow to read onto R in a "
                                     "microcycle's first half"),
    ("74HCT154 and SEL's registers", "two 74F138 enabled by the strobe's flip-flop"),
]


def bus(name, n, start=0):
    return [f"{name}{i}" for i in range(start, start + n)]


R = bus("R", 16)            # the register bus
T = bus("T", 16)            # the transfer bus
KB = bus("KB", 16)          # the K bus: uIR's K, or F for a dispatch
UPC = bus("UPC", 16)
UD = bus("UD", 48)          # the microcode flash's outputs
AF = bus("AF", 16)          # the ALU's result
ACQ = bus("ACQ", 16)
XQ = bus("XQ", 16)
SA = bus("SA", 16)          # the SRAM's address
IOD = bus("IOD", 16)        # the I/O bus's data
IOA = bus("IOA", 8)
ADEV = bus("ADEV", 4)
TTD = bus("TTD", 16)        # the timing table's data
INT = bus("INT", 16)

# The microinstruction's fields above K (sim/src/micro.rs): bit -> net.
FIELDS = {"REG": (16, 6), "RS": (22, 2), "S": (24, 4), "MI": (28, 1), "CI": (29, 1), "WB": (30, 1),
          "LD": (31, 3), "BUS": (34, 2), "SEG": (36, 1), "SZ": (37, 2), "T": (39, 3), "SEQ": (42, 2),
          "COND": (44, 3), "TASK": (47, 1)}


def field_nets():
    nets = {}
    for name, (bit, w) in FIELDS.items():
        for i in range(w):
            nets[bit + i] = f"u{name}{i if w > 1 else ''}"
    return nets


U = field_nets()


# Not yet: the system bus side, the slave side and the doorbells. Until
# they're there nothing stalls for the bus, and ATN, the doorbells and the
# slots' INT lines (pulled down, RFC 0037, 19) are quiet.
STUB = {n: "GND" for n in ["STALL1_BUS", "STALL2_BUS", "BELL"] + bus("ATN", 4) + bus("DB", 16)
        + [INT[i] for i in range(16) if i not in (12, 14)]}


def u(name, i=None):
    bit, w = FIELDS[name]
    return U[bit + (i or 0)]


def reg(nl, ref, d, q, clk="BCLK", en="GND", clr="VCC", oe="GND", part=None):
    """A 74ABT16823 half: up to 9 bits, D to Q."""
    pins = {"CLK": clk, "EN": en, "CLR": clr, "OE": oe}
    for i in range(9):
        pins[f"D{i + 1}"] = d[i] if i < len(d) else "GND"
        if i < len(q) and q[i] is not None:
            pins[f"Q{i + 1}"] = q[i]
    return nl.add("16823h", ref, part=part, **pins)


def buf(nl, ref, a, y, oe):
    """A 74ABT16244 half: up to 8 bits, A onto Y."""
    pins = {"OE1": oe, "OE2": oe}
    for i in range(8):
        pins[f"A{i + 1}"] = a[i] if i < len(a) else "GND"
        if i < len(y):
            pins[f"Y{i + 1}"] = y[i]
    return nl.add("16244h", ref, **pins)


def latch(nl, ref, d, q, le, oe="GND"):
    """A 74ABT16373 half: up to 8 bits, transparent while LE is high."""
    pins = {"LE": le, "OE": oe}
    for i in range(8):
        pins[f"D{i + 1}"] = d[i] if i < len(d) else "GND"
        if i < len(q):
            pins[f"Q{i + 1}"] = q[i]
    return nl.add("16373h", ref, **pins)


def xcvr(nl, ref, a, b, dir_, oe):
    """A 74ABT16245 half: A to B with DIR high."""
    pins = {"DIR": dir_, "OE": oe}
    for i in range(8):
        pins[f"A{i + 1}"], pins[f"B{i + 1}"] = a[i], b[i]
    return nl.add("245", ref, part="74ABT16245", **pins)


def dec(nl, ref, a, g1="VCC", g2a="GND", g2b="GND", y=None):
    """A 74F138: a = (A, B, C); y = {output: net}."""
    pins = {"A": a[0], "B": a[1], "C": a[2], "G1": g1, "G2A": g2a, "G2B": g2b}
    for k, n in (y or {}).items():
        pins[f"Y{k}"] = n
    return nl.add("138", ref, **pins)


def build(sim=True):
    """The card. `sim`: with its oscillators and power-on reset (for the
    simulator), else for timing analysis (not yet)."""
    nl = Netlist()
    g = nl.gate

    # ------------------------------------------------------------ clock, reset
    nl.section("Clock and reset")
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")
    nl.add("osc", "U_OSC", part="oscillator 16.667 MHz", OUT="BCLK0",
           params={"period_ps": BCLK_PS, "phase_ps": BCLK_PS})
    nl.add("clkdrv", "U_CK", part="CDC341", A="BCLK0", Y1="BCLK")
    g("04", ["BCLK"], "BCLK_n")
    nl.add("por", "U_POR", RST="PORST_n", params={"release_ps": POR_PS})
    nl.add("pullup", "RN_POR", P1="PORST_n")
    g("14", ["PORST_n"], "RESET")
    g("14", ["RESET"], "RESET_n")

    # ------------------------------------------------------------ the phase
    nl.section("Microcycle")
    nl.add("74", "U_PH", **{"1D": "PH_D", "1CLK": "BCLK", "1PRE": "VCC", "1CLR": "RESET_n",
                            "1Q": "PH", "1QN": "PH_n",
                            "2D": "PH", "2CLK": "BCLK_n", "2PRE": "VCC", "2CLR": "RESET_n",
                            "2Q": "PHD", "2QN": "PHD_n"})
    g("04", ["STALL1"], "GO1")
    nl.add("157", "U_PHM", S="PH", G="GND", **{"1A": "GO1", "1B": "STALL2", "1Y": "PH_D",
                                               "2A": "GND", "2B": "GND", "3A": "GND", "3B": "GND",
                                               "4A": "GND", "4B": "GND"})
    g("02", ["PH", "STALL1"], "E1EN")
    g("02", ["PH_n", "STALL2"], "E2EN")
    g("04", ["E2EN"], "E2EN_n")
    # STALL1: the first half waits; STALL2: the second
    g("08", ["pF0", "IODONE_n"], "STALL1_IO")
    g("32", ["STALL1_IO", STUB["STALL1_BUS"]], "STALL1")
    g("08", ["pIOS2", "IODONE_n"], "STALL2_IO")
    g("32", ["STALL2_IO", STUB["STALL2_BUS"]], "STALL2")

    # ------------------------------------------------------------ microcode
    nl.section("Microprogram counter")
    for k in range(4):
        nl.add("161", f"U_PC{k}", CLK="BCLK", CLR="RESET_n", LOAD="UPCLD_n", ENP="E2EN",
               ENT="VCC" if k == 0 else f"PCC{k - 1}", RCO=f"PCC{k}",
               A=KB[4 * k], B=KB[4 * k + 1], C=KB[4 * k + 2], D=KB[4 * k + 3],
               QA=UPC[4 * k], QB=UPC[4 * k + 1], QC=UPC[4 * k + 2], QD=UPC[4 * k + 3])
    nl.section("Microcode")
    for k in range(6):
        pins = {f"A{i}": UPC[i] for i in range(16)}
        pins.update({"A16": "GND", "CE": "GND", "OE": "GND", "WE": "VCC"})
        pins.update({f"D{i}": UD[8 * k + i] for i in range(8)})
        nl.add("flash", f"U_UC{k}", part="SST39SF010A-55", **pins)
    nl.section("Predecoding")
    # what the first half's paths need at once, decoded from the next
    # microinstruction as the flash gives it and registered with it in
    # uIR's spare bits (RFC 0027, 3.6): the SRAM's address, R's and T's
    # sources, a device onto R, the I/O bus. Reset clears uIR, so the
    # active-low ones are stored inverted (n... = not).
    ud = {b: UD[b] for b in range(48)}
    g("04", [ud[22]], "PDRS0_n")
    g("04", [ud[23]], "PDRS1_n")
    g("08", [ud[22], "PDRS1_n"], "PD_MEM")            # RS 1: memory at X
    g("00", [ud[22], "PDRS1_n"], "PD_NMEM")           # and not, for the other drivers
    g("08", [ud[23], "PDRS0_n"], "PD_K")              # RS 2: K
    g("08", [ud[22], ud[23]], "PD_T")                 # RS 3: T
    dec(nl, "U_PDT", [ud[39], ud[40], ud[41]], y={k: f"PDT{k}_n" for k in range(2, 7)})
    g("00", ["PDT2_n", "PDT5_n"], "PD_FT")            # F onto T
    g("04", ["PDT6_n"], "PDT6")
    g("08", ["PD_T", "PDT6"], "PD_TD")                # a device onto R
    g("04", ["PD_TD"], "PD_TD_n")
    dec(nl, "U_PDD", [ud[19], ud[20], ud[21]], g2a="PD_TD_n", y={k: f"PDF{k}_n" for k in range(4)})
    dec(nl, "U_PDE", [ud[16], ud[17], ud[18]], g2a="PDF3_n", y={k: f"PDE{k}_n" for k in range(3)})
    for k in range(3):
        g("04", [f"PDF{k}_n"], f"PD_F{k}")
        g("04", [f"PDE{k}_n"], f"PD_E{k}")
    g("20", ["PDT3_n", "PDT4_n", "PDT5_n", "VCC"], "PDT345")
    g("27", [ud[19], ud[20], ud[21]], "PDDEV0")
    g("08", ["PDDEV0", "PDT345"], "PD_IOS2")          # the I/O bus, stretching the second half
    g("32", ["PD_IOS2", "PD_F0"], "PD_IO")            # the I/O bus at all
    nl.section("Microinstruction register")
    reg(nl, "U_IR0", UD[0:9], KB[0:9], en="E2EN_n", clr="RESET_n", oe="KOE_n")
    reg(nl, "U_IR1", UD[9:16], KB[9:16], en="E2EN_n", clr="RESET_n", oe="KOE_n")
    for h in range(4):
        lo = 16 + 9 * h
        bits = list(range(lo, min(lo + 9, 48)))
        d, q = [UD[b] for b in bits], [U[b] for b in bits]
        if h == 3:
            d += ["PD_MEM", "PD_NMEM", "PD_K", "PD_T"]
            q += ["pMEM", "pNMEM", "pK", "pT"]
        reg(nl, f"U_IR{h + 2}", d, q, en="E2EN_n", clr="RESET_n")
    reg(nl, "U_IR6", ["PD_FT", "PD_F0", "PD_F1", "PD_F2", "PD_E0", "PD_E1", "PD_E2", "PD_IOS2", "PD_IO"],
        ["pFT", "pF0", "pF1", "pF2", "pE0", "pE1", "pE2", "pIOS2", "pIO"], en="E2EN_n", clr="RESET_n")

    nl.section("Sequencer")
    g("04", ["uCOND2"], "uCOND2_n")
    nl.add("151", "U_CMX", A=u("COND", 0), B=u("COND", 1), C=u("COND", 2), G="GND",
           D0="VCC", D1="CY", D2="R15", D3="LC15_n", D4="ATTN", D5=STUB["BELL"], D6="GND", D7="GND",
           Y="COND", W="COND_n")
    nl.add("153", "U_SEQ", A=u("SEQ", 0), B=u("SEQ", 1), **{
        "1G": "GND", "2G": "GND", "1C0": "GND", "1C1": "COND", "1C2": "COND_n", "1C3": "VCC",
        "1Y": "TAKEN", "2C0": "GND", "2C1": "GND", "2C2": "GND", "2C3": "COND", "2Y": "DISPF"})
    g("00", ["E2EN", "TAKEN"], "UPCLD_n")
    g("00", ["PH", "DISPF"], "DISPF2_n")
    g("04", ["DISPF2_n"], "KOE_n")
    g("00", ["PH_n", "pK"], "KROE_n")
    buf(nl, "U_KR0", KB[0:8], R[0:8], "KROE_n")
    buf(nl, "U_KR1", KB[8:16], R[8:16], "KROE_n")
    buf(nl, "U_RK0", R[0:8], KB[0:8], "DISPF2_n")
    buf(nl, "U_RK1", R[8:16], KB[8:16], "DISPF2_n")

    # ------------------------------------------------------------ R's sources
    nl.section("R bus")
    g("32", ["PH", u("RS", 1)], "SRAM_OE_n")       # RS 0 or 1, the first half

    # ------------------------------------------------------------ ALU and F
    nl.section("ALU")
    g("04", ["uMI"], "uM")
    g("04", ["uCI"], "CIN_n")
    cn = ["CIN_n", "CX_n", "CYY_n", "CZ_n"]
    for k in range(4):
        a = nl.add("181", f"U_ALU{k}", M="uM", CN=cn[k], P=f"AP{k}", G=f"AG{k}",
                   **{f"S{i}": u("S", i) for i in range(4)})
        for i in range(4):
            a[f"A{i}"], a[f"B{i}"], a[f"F{i}"] = R[4 * k + i], ACQ[4 * k + i], AF[4 * k + i]
        if k == 3:
            a["CN4"] = "ALUCO_n"
    nl.add("182", "U_CLA", CN="CIN_n", CNX="CX_n", CNY="CYY_n", CNZ="CZ_n",
           **{f"P{i}": f"AP{i}" for i in range(4)}, **{f"G{i}": f"AG{i}" for i in range(4)})
    # HOLD: the all-zero ALU field
    g("27", [u("S", 0), u("S", 1), u("S", 2)], "HZ0")
    g("27", [u("S", 3), "uMI", "uCI"], "HZ1")
    g("00", ["HZ0", "HZ1"], "HOLD_n")
    g("00", ["E1EN", "HOLD_n"], "FLD_n")
    nl.section("F, AC, X")
    reg(nl, "U_F0", AF[0:9], R[0:9], en="FLD_n", oe="PH_n")
    reg(nl, "U_F1", AF[9:16] + ["ALUCO_n"], R[9:16] + ["CYS_n"], en="FLD_n", oe="PH_n")
    g("04", ["CYS_n"], "CY")
    dec(nl, "U_LDD", [u("LD", 0), u("LD", 1), u("LD", 2)], g1="E2EN",
        y={1: "LDAC_n", 2: "LDX_n", 3: "LDBANK_n", 4: "LDAH0_n", 5: "LDAH1_n", 6: "LDLC_n",
           7: "LDCTRL_n"})
    reg(nl, "U_AC0", R[0:9], ACQ[0:9], en="LDAC_n")
    reg(nl, "U_AC1", R[9:16], ACQ[9:16], en="LDAC_n")
    reg(nl, "U_X0", R[0:9], XQ[0:9], en="LDX_n")
    reg(nl, "U_X1", R[9:16], XQ[9:16], en="LDX_n")

    # ------------------------------------------------------------ the SRAM
    nl.section("Registers and memory")
    reg(nl, "U_BANK", R[0:8], SA[6:14], en="LDBANK_n", oe="pMEM")
    buf(nl, "U_SAX0", XQ[0:8], SA[0:8], "pNMEM")
    buf(nl, "U_SAX1", XQ[8:16], SA[8:16], "pNMEM")
    buf(nl, "U_SAR", [u("REG", i) for i in range(6)] + ["VCC", "VCC"], SA[0:6] + SA[14:16], "pMEM")
    g("20", ["uWB", "PH", "PHD_n", "VCC"], "SWE_n")
    for h, side in enumerate("LH"):
        pins = {f"A{i}": SA[i] for i in range(16)}
        pins.update({f"IO{i}": R[8 * h + i] for i in range(8)})
        nl.add("sram64k", f"U_RAM{side}", part="IS61C6416AL-12", CE="GND", OE="SRAM_OE_n",
               WE="SWE_n", **pins)

    # ------------------------------------------------------------ LC, CTRL
    nl.section("Loop counter and control register")
    g("21", ["uCOND2_n", u("COND", 1), u("COND", 0), "E2EN"], "LCCNT")
    nl.add("161", "U_LC", CLK="BCLK", CLR="VCC", LOAD="LDLC_n", ENP="LCCNT", ENT="VCC",
           A=R[0], B=R[1], C=R[2], D=R[3], QA="LC0", QB="LC1", QC="LC2", QD="LC3")
    g("20", ["LC0", "LC1", "LC2", "LC3"], "LC15_n")
    # CTRL, RFC 0027's control register as the study has it: loading it
    # from R sets bit R[2:0] to R[3]
    dec(nl, "U_CSEL", [R[0], R[1], R[2]], g2a="LDCTRL_n", y={i: f"CSEL{i}_n" for i in range(4)})
    ctrl = ["SESSION", "WORK", "BRESET", "IORESET"]
    for i, q in enumerate(ctrl):
        g("04", [f"CSEL{i}_n"], f"CSEL{i}")
        g("00", [q, f"CSEL{i}_n"], f"CK{i}A")
        g("00", [R[3], f"CSEL{i}"], f"CK{i}B")
        g("00", [f"CK{i}A", f"CK{i}B"], f"CTRL{i}_D")
    nl.add("175", "U_CTRL", CLK="BCLK", CLR="RESET_n",
           **{f"{i + 1}D": f"CTRL{i}_D" for i in range(4)}, **{f"{i + 1}Q": q for i, q in enumerate(ctrl)})

    # ------------------------------------------------------------ T and its devices
    nl.section("T bus")
    dec(nl, "U_TD", [u("T", 0), u("T", 1), u("T", 2)], y={k: f"TDY{k}_n" for k in range(1, 7)})
    # the bridge, a buffer each way: T onto R in the first half (RS 3), F
    # onto T in the second (AB <- F, dev <- F)
    g("00", ["PH_n", "pT"], "TROE_n")
    g("00", ["PH", "pFT"], "RTOE_n")
    buf(nl, "U_TR0", T[0:8], R[0:8], "TROE_n")
    buf(nl, "U_TR1", T[8:16], R[8:16], "TROE_n")
    buf(nl, "U_RT0", R[0:8], T[0:8], "RTOE_n")
    buf(nl, "U_RT1", R[8:16], T[8:16], "RTOE_n")
    g("08", ["TDY4_n", "TDY5_n"], "DEVW_n")         # a device written from T at E2
    g("04", ["DEVW_n"], "DEVW")
    g("04", [u("REG", 4)], "uREG4_n")
    g("04", [u("REG", 5)], "uREG5_n")
    g("11", [u("REG", 3), "uREG4_n", "uREG5_n"], "DEV1")
    g("11", [u("REG", 3), "uREG4_n", u("REG", 5)], "DEV5")
    # a device onto T: in the first half for RS 3 (predecoded, the whole
    # microinstruction, as nothing else uses T then), in the second for
    # AB <- dev
    g("00", ["PH", "TY3"], "DEVRD2_n")
    g("04", ["TDY3_n"], "TY3")
    dec(nl, "U_DRD", [u("REG", 3), u("REG", 4), u("REG", 5)], g2a="DEVRD2_n",
        y={0: "DRDY0B_n", 1: "DRDY1B_n", 2: "DRDY2B_n", 3: "DRDY3_n"})
    for k in range(3):
        g("04", [f"DRDY{k}B_n"], f"DRDY{k}B")
        g("02", [f"pF{k}", f"DRDY{k}B"], f"DRDY{k}_n")
    dec(nl, "U_DWD", [u("REG", 3), u("REG", 4), u("REG", 5)], g1="E2EN", g2a="DEVW_n",
        y={2: "DWDY2_n", 3: "DWDY3_n", 4: "DWDY4_n"})

    nl.section("Swap and page registers")
    reg(nl, "U_SW0", T[8:16], T[0:8], en="DWDY2_n", oe="DRDY2_n")
    reg(nl, "U_SW1", T[0:8], T[8:16], en="DWDY2_n", oe="DRDY2_n")
    dec(nl, "U_PGW", [u("REG", 0), u("REG", 1), u("REG", 2)], g2a="DWDY4_n",
        y={0: "PGW0_n", 1: "PGW1_n"})
    reg(nl, "U_SRP", T[0:7], bus("SRP", 7), en="PGW0_n")
    reg(nl, "U_FLP0", T[0:9], bus("FLP", 9), en="PGW1_n")
    reg(nl, "U_FLP1", T[9:11], bus("FLP", 2, 9), en="PGW1_n")

    nl.section("Event ports")
    dec(nl, "U_EVR", [u("REG", 0), u("REG", 1), u("REG", 2)], g2a="DRDY3_n",
        y={0: "EV0OEB_n", 1: "EV1OEB_n", 2: "EV2OEB_n"})
    for k in range(3):
        g("04", [f"EV{k}OEB_n"], f"EV{k}OEB")
        g("02", [f"pE{k}", f"EV{k}OEB"], f"EV{k}OE_n")
    ints = [STUB.get(n, n) for n in INT]
    buf(nl, "U_EV00", ints[0:8], T[0:8], "EV0OE_n")
    buf(nl, "U_EV01", ints[8:16], T[8:16], "EV0OE_n")
    buf(nl, "U_EV10", [STUB.get(n, n) for n in bus("ATN", 4)], T[0:8], "EV1OE_n")
    buf(nl, "U_EV11", ["GND"] * 7 + ["TICK"], T[8:16], "EV1OE_n")
    dbs = [STUB.get(n, n) for n in bus("DB", 16)]
    buf(nl, "U_EV20", dbs[0:8], T[0:8], "EV2OE_n")
    buf(nl, "U_EV21", dbs[8:16], T[8:16], "EV2OE_n")
    dec(nl, "U_EVW", [u("REG", 0), u("REG", 1), u("REG", 2)], g2a="DWDY3_n",
        y={1: "TICKCLR_n", 2: "DBCLR_n"})
    # the tick: the timer's OUT0 rising, taken into BCLK's time
    nl.add("74", "U_TKS", nocheck=True, **{
        "1D": "TOUT0", "1CLK": "BCLK", "1PRE": "VCC", "1CLR": "RESET_n", "1Q": "TKS1",
        "2D": "TKS1", "2CLK": "BCLK", "2PRE": "VCC", "2CLR": "RESET_n", "2QN": "TKS2_n"})
    g("08", ["TKS1", "TKS2_n"], "TICKSET")
    g("32", ["TICK", "TICKSET"], "TICKA")
    g("08", ["TICKA", "TICKCLR_n"], "TICK_D")
    g("32", ["TICK", "WORK"], "ATTA")
    g("32", ["ATTA", STUB["BELL"]], "ATTN")

    nl.section("Shared RAM")
    g("04", ["SRP4"], "SRP4_n")
    g("20", ["PH", "PHD_n", "DEVW", "DEV1"], "SRWE_n")
    for b in range(2):
        for h, side in enumerate("LH"):
            pins = {f"A{i}": XQ[i + 1] for i in range(15)}
            pins.update({f"A{15 + i}": f"SRP{i}" for i in range(4)})
            pins.update({f"IO{i}": T[8 * h + i] for i in range(8)})
            nl.add("sram512", f"U_SR{b}{side}", part="AS7C4096A-12", OE="DRDY1_n", WE="SRWE_n",
                   CE="SRP4" if b == 0 else "SRP4_n", **pins)

    nl.section("Timing table")
    # addressed by X[11:8]. A write: the SRAMs' outputs off for the whole
    # microinstruction, T onto their data in the second half, and the strobe
    # from E1 to BCLK's fall. An access reads SETUP and STROBE while its
    # microinstruction runs, so X is still its; HOLD is latched at the
    # strobe's end, as X may change after.
    g("00", ["DEVW", "DEV5"], "TTSEL_n")
    g("04", ["TTSEL_n"], "TTSEL")
    g("20", ["PH", "DEVW", "DEV5", "VCC"], "TTW_n")
    g("20", ["PH", "PHD_n", "DEVW", "DEV5"], "TTWE_n")
    for h in range(2):
        pins = {f"A{i}": XQ[8 + i] if i < 4 else "GND" for i in range(15)}
        pins.update({f"IO{i}": TTD[8 * h + i] for i in range(8)})
        nl.add("sram", f"U_TT{h}", part="CY7C199D-10", CE="GND", OE="TTSEL", WE="TTWE_n", **pins)
        buf(nl, f"U_TTB{h}", T[8 * h:8 * h + 8], TTD[8 * h:8 * h + 8], "TTW_n")

    # ------------------------------------------------------------ the I/O bus side
    nl.section("I/O bus side")
    # what the microinstruction does on the I/O bus: predecoded
    g("08", ["pIO", "IODONE_n"], "IOREQ")
    # the state: S0 (STB and HLD both 0), STB, HLD. In S0 CNT counts the
    # setup's clocks from 0 and the first clock's comparison, against SETUP,
    # is quick, as X may have changed at its start; STB and HLD compare CNT
    # with their fields
    g("02", ["STB", "HLD"], "S0")
    g("32", ["STB", "HLD"], "SBUSY")
    g("86", ["CNT0", TTD[0]], "SD0")
    g("86", ["CNT1", TTD[1]], "SD1")
    g("02", ["SD0", "SD1"], "EQS0")
    # the strobe and the hold each end where CNT equals their field: two
    # comparators, so that nothing switches in front of them as HLD starts
    g("11", ["S0", "IOREQ", "EQS0"], "GOSTB")
    g("08", ["STB", "PEQS"], "STBSTAY")
    g("32", ["GOSTB", "STBSTAY"], "STB_D")
    g("02", ["STB_n", "PEQS"], "STBEND")
    g("04", ["STBEND"], "STBEND_n")
    g("02", ["HLD_n", "PEQH"], "HLDEND")
    g("08", ["HLD", "PEQH"], "HLDSTAY")
    g("32", ["STBEND", "HLDSTAY"], "HLD_D")
    g("32", ["STBEND", "IODONE"], "IODA")
    g("08", ["IODA", "E2EN_n"], "IODONE_D")
    nl.add("175", "U_IOS", CLK="BCLK", CLR="RESET_n",
           **{"1D": "STB_D", "1Q": "STB", "1QN": "STB_n", "2D": "HLD_D", "2Q": "HLD", "2QN": "HLD_n",
              "3D": "IODONE_D", "3Q": "IODONE", "3QN": "IODONE_n", "4D": "TICK_D", "4Q": "TICK"})
    # CNT: counts in STB and HLD, and in S0 while an access's setup goes
    # on; to 0 when STB or HLD ends, or a setup longer than a clock; held
    # at 0 when the setup is its first clock alone
    g("32", ["CNT0", "CNT1"], "CNTNZ")
    g("11", ["S0", "CNTNZ", "EQS0"], "CZC")
    g("27", ["STBEND", "HLDEND", "CZC"], "CNTLD_n")
    g("32", ["SD0", "SD1"], "EQS0_n")
    g("20", ["S0", "IOREQ", "EQS0_n", "VCC"], "CNTS0_n")
    g("00", ["CNTS0_n", "SBUSY_n"], "CNTEN")
    g("04", ["SBUSY"], "SBUSY_n")
    reg(nl, "U_HQ", TTD[8:12], bus("HQ", 4), en="STBEND_n")
    for k in range(2):
        nl.add("161", f"U_CNT{k}", CLK="BCLK", CLR="RESET_n", LOAD="CNTLD_n", ENP="CNTEN",
               ENT="VCC" if k == 0 else "CNTC0", RCO=f"CNTC{k}", A="GND", B="GND", C="GND", D="GND",
               QA=f"CNT{4 * k}", QB=f"CNT{4 * k + 1}", QC=f"CNT{4 * k + 2}", QD=f"CNT{4 * k + 3}")
    nl.add("521", "U_CMPS", part="74F521", G="GND", PEQ="PEQS", **{f"P{i}": f"CNT{i}" for i in range(8)},
           **{f"Q{i}": TTD[2 + i] if i < 6 else "GND" for i in range(8)})
    nl.add("521", "U_CMPH", part="74F521", G="GND", PEQ="PEQH", **{f"P{i}": f"CNT{i}" for i in range(8)},
           **{f"Q{i}": f"HQ{i}" if i < 4 else "GND" for i in range(8)})
    # the address, the device and WRITE, latched when S0 ends
    latch(nl, "U_IOA", XQ[0:8], IOA, "S0")
    latch(nl, "U_IODV", XQ[8:12] + ["DEVW"], ADEV + ["AWRITE"], "S0")
    g("04", ["AWRITE"], "AWRITE_n")
    g("00", ["STB", "AWRITE_n"], "IORD_n")
    g("00", ["STB", "AWRITE"], "IOWR_n")
    # data: read, latched at the strobe's end; write, held through the hold
    latch(nl, "U_IORL0", IOD[0:8], T[0:8], "STB", oe="DRDY0_n")
    latch(nl, "U_IORL1", IOD[8:16], T[8:16], "STB", oe="DRDY0_n")
    g("32", ["SBUSY", "IOREQ"], "IOACT")
    g("00", ["AWRITE", "IOACT"], "IOWOE_n")
    latch(nl, "U_IOWL0", T[0:8], IOD[0:8], "HLD_n", oe="IOWOE_n")
    latch(nl, "U_IOWL1", T[8:16], IOD[8:16], "HLD_n", oe="IOWOE_n")
    # the slots' strobes (RFC 0037, 16): SEL0-SEL11, through the strobe
    dec(nl, "U_SELL", ADEV[0:3], g2a=ADEV[3], g2b="STB_n", y={k: f"SEL{k}_n" for k in range(8)})
    dec(nl, "U_SELM", ADEV[0:3], g1=ADEV[3], g2a=ADEV[2], g2b="STB_n", y={k: f"SEL{k + 8}_n" for k in range(4)})
    # the card's own devices, 12-15: chip selects from the address alone,
    # with RD and WR as the strobes
    dec(nl, "U_SELH", ADEV[0:3], g1=ADEV[3], y={k: f"CS{k + 8}_n" for k in range(4, 8)})

    # ------------------------------------------------------------ the card's own devices
    nl.section("Console UART")
    nl.add("osc", "U_UOSC", part="oscillator 14.7456 MHz", OUT="UCLK", params={"period_ps": UART_PS})
    g("32", ["IORESET", "RESET"], "UMR")
    nl.add("16c550", "U_UART", **{f"D{i}": IOD[i] for i in range(8)}, A0=IOA[0], A1=IOA[1], A2=IOA[2],
           CS0="VCC", CS1="VCC", CS2="CS12_n", RD="IORD_n", WR="IOWR_n", MR="UMR", XIN="UCLK",
           INTR=INT[12])
    nl.section("Image flash")
    for h in range(2):
        pins = {f"A{i}": IOA[i] for i in range(8)}
        pins.update({f"A{8 + i}": f"FLP{i}" for i in range(9)})
        pins.update({f"D{i}": IOD[8 * h + i] for i in range(8)})
        nl.add("flash", f"U_FL{h}", part="SST39SF010A-70", CE="CS13_n", OE="IORD_n", WE="VCC", **pins)
    nl.section("Timer")
    nl.add("osc", "U_BOSC", part="oscillator 4 MHz", OUT="CLKB", params={"period_ps": CLKB_PS})
    nl.add("82c54", "U_TMR", **{f"D{i}": IOD[i] for i in range(8)}, A0=IOA[0], A1=IOA[1],
           CS="CS14_n", RD="IORD_n", WR="IOWR_n", CLK0="CLKB", CLK1="CLKB", CLK2="CLKB",
           GATE0="VCC", GATE1="VCC", GATE2="VCC", OUT0="TOUT0", OUT2=INT[14])
    nl.section("Ports")
    g("32", ["CS15_n", "IOWR_n"], "LEDW0")
    g("32", ["LEDW0", IOA[0]], "LEDCLK")
    nl.add("574", "U_LED", OE="GND", CLK="LEDCLK", **{f"D{i + 1}": IOD[i] for i in range(8)},
           **{f"Q{i + 1}": f"LED{i}" for i in range(8)})

    nl.finish()
    nl.check()
    return nl
