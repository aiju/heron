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
POR_PS = 2_000_000              # the backplane's COLD at power-up (the bench's)
WDOG_PS = 99_000_000_000        # the watchdog: 0.45 x 220k x 1 uF
WDCOLD_PS = 990_000_000         # and the COLD it then asserts: 0.45 x 22k x 100 nF
RTC_TIME = 20_000_101_000_000   # the clock chip's time at power-up (yyyymmddhhmmss)

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


SB = "SB_"                  # the system bus's lines (RFC 0037, 3), active low as it has them
SBA = [None] + bus("SB_A", 31, 1)
SBD = bus("SB_D", 16)

# The slots' INT lines are quiet (pulled down, RFC 0037, 19): no I/O cards
# are fitted yet.
STUB = {n: "GND" for n in [INT[i] for i in range(16) if i not in (12, 14)]}
SRA = bus("SRA", 20)        # the shared RAM's halfword address


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


# A second master on the bench (add_bench's `master`): a scripted vector
# fixture, as studies/v1b_system/bfm.py's, which owns the bus throughout
# (the IOP mustn't ask for it then).
M_OUT = (["SB_START_n", "SB_WRITE_n", "SB_BE0_n", "SB_BE1_n"] + SBA[1:32] + SBD)
M_IN = ["SB_WAIT_n", "RESET_n"] + SBD
M_CONDS = 4
M_DELAY_PS = 20_000


def build(sim=True, bench=False, master=False, watchdog=(WDOG_PS, WDCOLD_PS)):
    """The card. `sim`: with its oscillators (for the simulator), else for
    timing analysis (not yet). `bench`: with what the simulator needs
    around it on the system bus (add_bench), the backplane's COLD at
    power-up among it, and `master` a second master there. `watchdog`:
    how long it waits for a kick, and the COLD it then asserts."""
    nl = Netlist()
    g = nl.gate

    # ------------------------------------------------------------ clock, reset
    nl.section("Clock and reset")
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")
    nl.add("osc", "U_OSC", part="oscillator 16.667 MHz", OUT="BCLK0",
           params={"period_ps": BCLK_PS, "phase_ps": BCLK_PS})
    nl.add("clkdrv", "U_CK", part="CDC341", A="BCLK0", Y1="BCLK")
    g("04", ["BCLK"], "BCLK_n")
    # COLD (RFC 0037, 7) through a Schmitt trigger; reset ends at a clock
    # edge, through one flip-flop
    g("14", ["SB_COLD_n"], "COLD")
    g("14", ["COLD"], "COLDS_n")
    nl.add("74", "U_RSY", part="74ABT74", **{"1D": "VCC", "1CLK": "BCLK", "1PRE": "VCC", "1CLR": "COLDS_n",
                                             "1Q": "RESET_n", "1QN": "RESET", "2D": "PULSE1", "2CLK": "BCLK",
                                             "2PRE": "VCC", "2CLR": "RESET_n", "2QN": "PULSE2_n"})

    # ------------------------------------------------------------ the phase
    nl.section("Microcycle")
    nl.add("74", "U_PH", **{"1D": "PH_D", "1CLK": "BCLK", "1PRE": "VCC", "1CLR": "RESET_n",
                            "1Q": "PH", "1QN": "PH_n",
                            "2D": "PH", "2CLK": "BCLK_n", "2PRE": "VCC", "2CLR": "RESET_n",
                            "2Q": "PHD", "2QN": "PHD_n"})
    # E1 unless the first half waits: for an I/O read onto R, for the bus
    # (system_bus: the WAIT line's own term is last, as it comes late); E2
    # unless the second half waits, on registered signals alone, as E2EN
    # goes to every register that loads at E2
    g("00", ["pF0", "IODONE_n"], "STALL1_IO_n")
    g("21", ["PH_n", "STALL1_IO_n", "BSTALL_n", "WSTALL_n"], "E1EN")
    g("08", ["PH", "STALL2"], "PHSTAY")
    g("32", ["E1EN", "PHSTAY"], "PH_D")
    g("08", ["pIOS2", "IODONE_n"], "STALL2_IO")
    g("32", ["STALL2_IO", "STALL2_BUS"], "STALL2")
    g("02", ["PH_n", "STALL2"], "E2EN")
    g("04", ["E2EN"], "E2EN_n")

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
    # sources, a device onto R, the I/O bus, the system bus. Reset clears
    # uIR, so the active-low ones are stored inverted (n... = not).
    ud = {b: UD[b] for b in range(48)}
    g("04", [ud[22]], "PDRS0_n")
    g("04", [ud[23]], "PDRS1_n")
    g("08", [ud[22], "PDRS1_n"], "PD_MEM")            # RS 1: memory at X
    g("00", [ud[22], "PDRS1_n"], "PD_NMEM")           # and not, for the other drivers
    g("08", [ud[23], "PDRS0_n"], "PD_K")              # RS 2: K
    g("08", [ud[22], ud[23]], "PD_T")                 # RS 3: T
    dec(nl, "U_PDT", [ud[39], ud[40], ud[41]], y={k: f"PDT{k}_n" for k in range(1, 7)})
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
    g("08", ["PD_T", "PDT6_n"], "PD_BAR")             # BA onto R
    g("32", [ud[34], ud[35]], "PD_BUS")               # a transfer on the system bus
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
    reg(nl, "U_IR7", ["PD_BAR", "PD_BUS"], ["pBAR", "BUSOP"], en="E2EN_n", clr="RESET_n")

    nl.section("Sequencer")
    g("04", ["uCOND2"], "uCOND2_n")
    nl.add("151", "U_CMX", A=u("COND", 0), B=u("COND", 1), C=u("COND", 2), G="GND",
           D0="VCC", D1="CY", D2="R15", D3="LC15_n", D4="ATTN", D5="BELL", D6="GND", D7="GND",
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
    for i in range(4):
        g("04", [f"SB_ATN{i}_n"], f"ATN{i}")
    buf(nl, "U_EV10", bus("ATN", 4), T[0:8], "EV1OE_n")
    buf(nl, "U_EV11", ["GND"] * 5 + ["OWN", "STUCK", "TICK"], T[8:16], "EV1OE_n")
    buf(nl, "U_EV20", bus("DB", 8), T[0:8], "EV2OE_n")
    buf(nl, "U_EV21", bus("DB", 8, 8), T[8:16], "EV2OE_n")
    dec(nl, "U_EVW", [u("REG", 0), u("REG", 1), u("REG", 2)], g2a="DWDY3_n",
        y={1: "TICKCLR_n", 2: "DBCLR_n", 3: "STKCLR_n"})
    # the tick: the timer's OUT0 rising, taken into BCLK's time
    nl.add("74", "U_TKS", nocheck=True, **{
        "1D": "TOUT0", "1CLK": "BCLK", "1PRE": "VCC", "1CLR": "RESET_n", "1Q": "TKS1",
        "2D": "TKS1", "2CLK": "BCLK", "2PRE": "VCC", "2CLR": "RESET_n", "2QN": "TKS2_n"})
    g("08", ["TKS1", "TKS2_n"], "TICKSET")
    g("32", ["TICK", "TICKSET"], "TICKA")
    g("08", ["TICKA", "TICKCLR_n"], "TICK_D")
    g("32", ["TICK", "WORK"], "ATTA")
    g("32", ["ATTA", "BELL"], "ATTN")

    nl.section("Shared RAM")
    # its address: the core's {page, X} but in the slave side's T clocks,
    # the slave side's then (slave_side)
    core_a = XQ[1:16] + bus("SRP", 5)
    buf(nl, "U_SRAC0", core_a[0:8], SRA[0:8], "STAKE")
    buf(nl, "U_SRAC1", core_a[8:16], SRA[8:16], "STAKE")
    buf(nl, "U_SRAC2", core_a[16:20], SRA[16:20], "STAKE")
    g("04", ["SRA19"], "SRA19_n")
    g("20", ["PH", "PHD_n", "DEVW", "DEV1"], "SRWE_n")
    for side in "LH":
        g("08", ["SRWE_n", f"SSWE{side}_n"], f"SRWE{side}_n")
    g("08", ["DRDY1_n", "SSOE_n"], "SROE_n")
    for b in range(2):
        for h, side in enumerate("LH"):
            pins = {f"A{i}": SRA[i] for i in range(19)}
            pins.update({f"IO{i}": T[8 * h + i] for i in range(8)})
            nl.add("sram512", f"U_SR{b}{side}", part="AS7C4096A-12", OE="SROE_n", WE=f"SRWE{side}_n",
                   CE="SRA19" if b == 0 else "SRA19_n", **pins)

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
    # A second copy, written with it, serves the window's accesses, by the
    # window's device: a multiplexer in front of the first would lengthen
    # an access's first clock, which starts from X
    g("32", ["TTSEL", "WSEL"], "TTOEC_n")
    g("32", ["TTSEL", "WSEL_n"], "TTOEW_n")
    nl.add("157", "U_TTWA", S="TTSEL", G="GND", **{f"{i + 1}A": f"WA{8 + i}" for i in range(4)},
           **{f"{i + 1}B": XQ[8 + i] for i in range(4)}, **{f"{i + 1}Y": f"WTA{i}" for i in range(4)})
    for h in range(2):
        pins = {f"A{i}": XQ[8 + i] if i < 4 else "GND" for i in range(15)}
        pins.update({f"IO{i}": TTD[8 * h + i] for i in range(8)})
        nl.add("sram", f"U_TT{h}", part="CY7C199D-10", CE="GND", OE="TTOEC_n", WE="TTWE_n", **pins)
        pins = {f"A{i}": f"WTA{i}" if i < 4 else "GND" for i in range(15)}
        pins.update({f"IO{i}": TTD[8 * h + i] for i in range(8)})
        nl.add("sram", f"U_TTW{h}", part="CY7C199D-10", CE="GND", OE="TTOEW_n", WE="TTWE_n", **pins)
        buf(nl, f"U_TTB{h}", T[8 * h:8 * h + 8], TTD[8 * h:8 * h + 8], "TTW_n")

    # ------------------------------------------------------------ the I/O bus side
    nl.section("I/O bus side")
    # what the microinstruction does on the I/O bus: predecoded
    g("11", ["pIO", "IODONE_n", "WSEL_n"], "IOREQ")
    # an access in S0, its setup: the core's, or the window's (WSEL)
    g("08", ["WSEL", "S0"], "WS0")
    g("32", ["IOREQ", "WS0"], "AREQ")
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
    g("11", ["S0", "AREQ", "EQS0"], "GOSTB")
    g("08", ["STB", "PEQS"], "STBSTAY")
    g("32", ["GOSTB", "STBSTAY"], "STB_D")
    g("02", ["STB_n", "PEQS"], "STBEND")
    g("04", ["STBEND"], "STBEND_n")
    g("02", ["HLD_n", "PEQH"], "HLDEND")
    g("08", ["HLD", "PEQH"], "HLDSTAY")
    g("32", ["STBEND", "HLDSTAY"], "HLD_D")
    g("08", ["STBEND", "WSEL_n"], "STBENDC")          # the core's own
    g("32", ["STBENDC", "IODONE"], "IODA")
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
    g("20", ["S0", "AREQ", "EQS0_n", "VCC"], "CNTS0_n")
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
    # the address, the device and WRITE: the core's or the window's,
    # latched when S0 ends
    iox = bus("IOX", 13)
    buf(nl, "U_IOXC0", XQ[0:8], iox[0:8], "WSEL")
    buf(nl, "U_IOXC1", XQ[8:12] + ["DEVW"], iox[8:13], "WSEL")
    buf(nl, "U_IOXW0", bus("WA", 8), iox[0:8], "WSEL_n")
    buf(nl, "U_IOXW1", bus("WA", 4, 8) + ["WAWR"], iox[8:13], "WSEL_n")
    latch(nl, "U_IOA", iox[0:8], IOA, "S0")
    latch(nl, "U_IODV", iox[8:13], ADEV + ["AWRITE"], "S0")
    g("04", ["AWRITE"], "AWRITE_n")
    g("00", ["STB", "AWRITE_n"], "IORD_n")
    g("00", ["STB", "AWRITE"], "IOWR_n")
    # data: read, latched at the strobe's end; write, held through the hold
    latch(nl, "U_IORL0", IOD[0:8], T[0:8], "STB", oe="DRDY0_n")
    latch(nl, "U_IORL1", IOD[8:16], T[8:16], "STB", oe="DRDY0_n")
    g("32", ["SBUSY", "AREQ"], "IOACT")
    g("20", ["AWRITE", "IOACT", "WSEL_n", "VCC"], "IOWOE_n")
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
    # register 0: the LEDs out, the inputs in; register 1 out: the
    # watchdog's kick (bit 0, as it's written), the clock chip's CE, SCLK
    # and I/O pulled low (1-3), the panel's shift chain's data, clock and
    # latch (4-6). Both clocked at the strobe's end.
    g("32", ["CS15_n", "IOWR_n"], "LEDW0")
    g("32", ["LEDW0", IOA[0]], "LEDCLK")
    nl.add("574", "U_LED", OE="GND", CLK="LEDCLK", **{f"D{i + 1}": IOD[i] for i in range(8)},
           **{f"Q{i + 1}": f"LED{i}" for i in range(8)})
    g("04", [IOA[0]], "IOA0_n")
    g("32", ["LEDW0", "IOA0_n"], "P1W_n")
    nl.add("823", "U_P1", OE="GND", CLK="P1W_n", EN="GND", CLR="RESET_n",
           **{f"D{i + 1}": IOD[i] if i < 8 else "GND" for i in range(9)},
           **{f"Q{i + 2}": n for i, n in enumerate(["RTC_CE", "RTC_SCLK", "RTC_IOLO", "PNL_DO", "PNL_CK",
                                                     "PNL_LT"])})
    # the inputs: the clock chip's I/O, the panel's data, jumpers J2-J7
    # (pulled up, fitted to GND)
    g("32", ["CS15_n", "IORD_n"], "RD15_n")
    nl.add("541", "U_PIN", OE1="RD15_n", OE2=IOA[0], **{f"A{i + 1}": n for i, n in enumerate(
        ["RTC_IO", "PNL_DI"] + bus("JMP", 6, 2))}, **{f"Y{i + 1}": IOD[i] for i in range(8)})
    nl.add("pullup", "RN_1", P1="RTC_IO", P2="PNL_DI", **{f"P{i + 1}": f"JMP{i}" for i in range(2, 8)})
    nl.section("Time of day")
    nl.add("ds1302", "U_RTC", CE="RTC_CE", SCLK="RTC_SCLK", IO="RTC_IO", params={"time": RTC_TIME})
    nl.section("Watchdog")
    # armed by the first kick: 1Q high while kicks come within WDOG_PS;
    # when it falls, the second half asserts COLD for WDCOLD_PS, which
    # resets the whole system and this card
    nl.add("123", "U_WDG", part="74HCT123", **{
        "1A": "P1W_n", "1B": IOD[0], "1R": "RESET_n", "1Q": "WDOK",
        "2A": "WDOK", "2B": "VCC", "2R": "VCC", "2Q": "WDCOLD", "WAKE": "WDG_WAKE"},
           params={"width1_ps": watchdog[0], "width2_ps": watchdog[1]})

    system_bus(nl)
    slave_side(nl)
    window(nl)
    if bench:
        add_bench(nl, master)
    nl.finish()
    nl.check()
    return nl


def system_bus(nl):
    """The system bus side as a master (RFC 0027, 4.1; RFC 0037, 5-6). A
    transfer's address clock is the second half's last: E1-E2, unless an
    I/O bus access stretches the second half; its data clocks follow from
    E2 while the slave holds WAIT. AL and AHOUT take the address at E1,
    START, WRITE and BE are registered for the address clock; BA takes the
    read data at the data phase's end, AB drives the write data through
    it. Not yet: the 32-bit path, LOCK, the stuck-transfer counter."""
    g = nl.gate
    nl.section("System bus: addresses")
    reg(nl, "U_AH00", R[0:9], bus("AH0_", 9), en="LDAH0_n")
    reg(nl, "U_AH01", R[9:16], bus("AH0_", 7, 9), en="LDAH0_n")
    reg(nl, "U_AH10", R[0:9], bus("AH1_", 9), en="LDAH1_n")
    reg(nl, "U_AH11", R[9:16], bus("AH1_", 7, 9), en="LDAH1_n")
    # AH0 or AH1 onto AHI by SEG, for AHOUT
    g("04", ["uSEG"], "uSEG_n")
    for k, (lo, n) in enumerate(((0, 8), (8, 8))):
        buf(nl, f"U_AHS0{k}", bus("AH0_", n, lo), bus("AHI", n, lo), "uSEG")
        buf(nl, f"U_AHS1{k}", bus("AH1_", n, lo), bus("AHI", n, lo), "uSEG_n")
    g("04", ["uBUS0"], "uBUS0_n_")
    g("00", ["E1EN", "BUSOP"], "ALLD_n")
    reg(nl, "U_AL0", R[0:9], ["AL0"] + SBA[1:9], en="ALLD_n", oe="GNTQ_n")
    reg(nl, "U_AL1", R[9:16], SBA[9:16], en="ALLD_n", oe="GNTQ_n")
    reg(nl, "U_AHO0", bus("AHI", 9), SBA[16:25], en="ALLD_n", oe="GNTQ_n")
    reg(nl, "U_AHO1", bus("AHI", 7, 9), SBA[25:32], en="ALLD_n", oe="GNTQ_n")

    nl.section("System bus: control")
    # START for the address clock: from E1, or, when an I/O access
    # stretches the second half, from the strobe's end
    g("04", ["pIOS2"], "pIOS2_n")
    g("08", ["BUSOP", "pIOS2_n"], "BSTA")
    g("08", ["E1EN", "BSTA"], "STA_A")
    g("21", ["PH", "pIOS2", "STBEND", "BUSOP"], "STA_B")
    g("32", ["STA_A", "STA_B"], "START_D")
    g("04", ["START_D"], "START_D_n")
    # WRITE (BUS 2) and the byte enables (SZ: 0 byte 0, 1 byte 1, 2 both)
    g("08", ["uBUS1", "uBUS0_n_"], "BWRITE")
    g("02", ["uSZ0", "uSZ1"], "BBE1_n_")
    reg(nl, "U_BCTL", ["BWRITE", "uSZ0", "BBE1_n_"], ["WRQ", "BE0Q_n", "BE1Q_n"], en="START_D_n")
    g("04", ["WRQ"], "WRQ_n")
    # the owner's lines, while GNT was sampled; START a clock
    nl.add("175", "U_BST", CLK="BCLK", CLR="RESET_n", **{
        "1D": "START_D", "1Q": "STARTQ", "1QN": "STARTQ_n",
        "2D": "DP_D", "2Q": "DP", "2QN": "DP_n",
        "3D": "GNT", "3Q": "GNTQ", "3QN": "GNTQ_n",
        "4D": "GND"})
    g("04", ["SB_GNT3_n"], "GNT")
    buf(nl, "U_BOWN", ["STARTQ_n", "WRQ_n", "BE0Q_n", "BE1Q_n", "VCC"],
        ["SB_START_n", "SB_WRITE_n", "SB_BE0_n", "SB_BE1_n", "SB_LOCK_n"], "GNTQ_n")
    g("04", ["SESSION"], "SB_REQ3_n")
    nl.add("05", "U_BRST", **{"1A": "BRESETX", "1Y": "SB_RESET_n", "2A": "WDCOLD", "2Y": "SB_COLD_n",
                              "3A": "RTC_IOLO", "3Y": "RTC_IO", "4A": "GND", "5A": "GND", "6A": "GND"})
    # the data phase: from the address clock's end while WAIT is held
    g("04", ["SB_WAIT_n"], "WAIT")
    g("11", ["DP", "WAIT", "PMASK_n"], "DPW")
    g("32", ["STARTQ", "DPW"], "DP_D")
    g("08", ["DP", "SB_WAIT_n"], "DPEND")
    g("08", ["DP", "WRQ"], "WDP")
    g("08", ["DP", "WRQ_n"], "RDP")
    g("00", ["DPEND", "WRQ_n"], "BALD_n")
    stuck_counter(nl)
    # stalls: a transfer waits at E1 for GNT and for the last data phase's
    # end, a move of BA for the read's data (onto R, a clock more): the
    # terms without WAIT in BSTALL_n, WAIT's in WSTALL_n. AB's loads wait in
    # the second half for the clock after the last write's end
    g("08", ["BUSOP", "SB_GNT3_n"], "BSA")            # (GNT, active low: it comes late)
    g("08", ["pBAR", "RDP"], "BSB")
    g("02", ["BSA", "BSB"], "BSTALL_n")
    g("08", ["BUSOP", "DP"], "WSA")
    g("08", ["TBA", "RDP"], "WSB")
    # (not in the stuck-transfer counter's RESET's first two clocks: a
    # slave's WAIT lets go when RESET clears it, at any time in the clock)
    g("27", ["WSA", "WSB", "PMASK"], "WSAB_n")
    g("32", ["SB_WAIT_n", "WSAB_n"], "WSTALL_n")
    g("08", ["ABLOAD", "WDP"], "STALL2_BUS")

    nl.section("System bus: data")
    g("20", ["TDY1_n", "TDY2_n", "TDY3_n", "VCC"], "ABLOAD")
    g("00", ["TDY1_n", "TDY4_n"], "TBA")             # BA onto T in the second half
    g("00", ["E2EN", "ABLOAD"], "ABLD_n")
    g("00", ["PH_n", "pBAR"], "BAOA_n")
    g("00", ["PH", "TBA"], "BAOB_n")
    g("08", ["BAOA_n", "BAOB_n"], "BAOE_n")
    g("04", ["WDP"], "WDP_n")
    reg(nl, "U_AB0", T[0:8], SBD[0:8], en="ABLD_n", oe="WDP_n")
    reg(nl, "U_AB1", T[8:16], SBD[8:16], en="ABLD_n", oe="WDP_n")
    reg(nl, "U_BA0", SBD[0:8], T[0:8], en="BALD_n", oe="BAOE_n")
    reg(nl, "U_BA1", SBD[8:16], T[8:16], en="BALD_n", oe="BAOE_n")


def stuck_counter(nl):
    """The stuck-transfer counter (RFC 0027, 4.1; RFC 0037, 5.6): CNT
    counts the bus's consecutive data clocks, whoever's transfer it is.
    At 256 it asserts RESET for 256 clocks (PULSE: CNT counts them, as no
    slave holds WAIT through a reset), and sets STUCK, and OWN if the
    transfer was the IOP's own: event port register 1's bits 14 and 13,
    until a write to its register 3 clears them. The IOP's own data phase
    and stalls ignore WAIT for RESET's first two clocks (PMASK), as a
    slave lets go of it whenever reset reaches it."""
    g = nl.gate
    nl.section("Stuck-transfer counter")
    g("32", ["WAIT", "PULSE"], "STCNT")                # else CNT to 0
    for k in range(2):
        nl.add("163", f"U_STC{k}", CLK="BCLK", CLR="STCNT", LOAD="VCC", ENP="VCC",
               ENT="VCC" if k == 0 else "STC0RC", RCO="STC0RC" if k == 0 else "STC255",
               A="GND", B="GND", C="GND", D="GND")
    g("04", ["PULSE"], "PULSE_n_")
    g("11", ["STC255", "WAIT", "PULSE_n_"], "STSET")
    g("04", ["STC255"], "STC255_n")
    g("08", ["PULSE", "STC255_n"], "PULSTAY")
    g("32", ["STSET", "PULSTAY"], "PULSE_D")
    g("08", ["STUCK", "STKCLR_n"], "STKSTAY")
    g("32", ["STSET", "STKSTAY"], "STUCK_D")
    g("08", ["STSET", "DP"], "OWNSET")
    g("08", ["OWN", "STKCLR_n"], "OWNSTAY")
    g("32", ["OWNSET", "OWNSTAY"], "OWN_D")
    nl.add("175", "U_STK", CLK="BCLK", CLR="RESET_n", **{
        "1D": "PULSE_D", "1Q": "PULSE", "2D": "STUCK_D", "2Q": "STUCK", "3D": "OWN_D", "3Q": "OWN",
        "4D": "PULSE", "4Q": "PULSE1"})
    # RESET's first two clocks
    g("08", ["PULSE", "PULSE2_n"], "PMASK")
    g("00", ["PULSE", "PULSE2_n"], "PMASK_n")
    g("32", ["BRESET", "PULSE"], "BRESETX")


def slave_side(nl):
    """The system bus side as a slave (RFC 0027, 4.2-4.4): the shared RAM
    in region 4 and the doorbells at 0x7400_0000, for the bus's other
    masters. Not yet: the I/O bus's window at 0x7F00_0000.

    An access to the shared RAM takes T for one clock, STAKE, which is
    one the core leaves free: the microinstruction running and the next
    one use T in neither half. It waits for one with WAIT held. A write's
    data is registered at the end of its first data clock and written in
    the T clock, which ends the transfer; a read's data is registered at
    the T clock's end and driven the clock after. A doorbell is set in the write's data clock (RFC 0027's two
    74HC259 would do in 3 chips what these flip-flops do here).

    So a write takes 2 data clocks or more, a read 2 or more: the first
    holds WAIT whatever happens, as the decode comes late in the address
    clock."""
    g = nl.gate
    nl.section("Slave side: decode")
    # in the address clock: region 4, or 0x74, and not the IOP's own
    nl.add("521", "U_SDR4", part="74F521", G="GND", PEQ="SR4_n",
           **{f"P{i}": SBA[28 + i] for i in range(4)}, **{f"Q{i}": "VCC" if i == 2 else "GND" for i in range(4)},
           **{f"P{i}": "GND" for i in range(4, 8)}, **{f"Q{i}": "GND" for i in range(4, 8)})
    nl.add("521", "U_SDDB", part="74F521", G="GND", PEQ="DB74_n",
           **{f"P{i}": SBA[24 + i] for i in range(8)}, **{f"Q{i}": "VCC" if (0x74 >> i) & 1 else "GND" for i in range(8)})
    g("02", ["SB_START_n", "GNTQ"], "SADDR")          # another master's address clock
    g("04", ["SADDR"], "SADDR_n")
    g("02", ["SADDR_n", "SR4_n"], "SNEW")             # a shared RAM access starts
    g("20", ["SADDR", "SB_WRITE_n_", "DB74", "VCC"], "SDB_n")
    g("04", ["SB_WRITE_n"], "SB_WRITE_n_")
    g("04", ["DB74_n"], "DB74")
    g("04", ["SDB_n"], "SDB_D")
    # the address, the byte enables and WRITE, from the address clock
    reg(nl, "U_SSA0", SBA[1:10], bus("SSA", 9), en="SADDR_n")
    reg(nl, "U_SSA1", SBA[10:19], bus("SSA", 9, 9), en="SADDR_n")
    # (each in the polarity it's used in: an inverter after the register
    # would let STAKE through ahead of it)
    for n in ("SB_BE0_n", "SB_BE1_n"):
        g("04", [n], n[:-2] + "_")
    reg(nl, "U_SSA2", [SBA[19], SBA[20], "SB_BE0_", "SB_BE1_", "SWRL", "SB_WRITE_n"],
        ["SSA18", "SSA19", "SBE0Q", "SBE1Q", "SWRQ", "SWRQ_n"], en="SADDR_n")
    # onto the shared RAM's address in STAKE
    ssa = bus("SSA", 20)
    buf(nl, "U_SSAB0", ssa[0:8], SRA[0:8], "STAKE_n")
    buf(nl, "U_SSAB1", ssa[8:16], SRA[8:16], "STAKE_n")
    buf(nl, "U_SSAB2", ssa[16:20], SRA[16:20], "STAKE_n")

    nl.section("Slave side: T")
    # is the next clock free of the core's T? if neither this
    # microinstruction nor the next (predecoded) uses T in either half:
    # then the clock after is free too, which the shared RAM's address,
    # changing hands again, needs
    g("20", ["PDT1_n", "PDT2_n", "PDT3_n", "PDT4_n"], "PDTU_A")      # T 1-4
    g("04", ["PDT5_n"], "PDT5")
    g("27", ["PDTU_A", "PDT5", "PD_T"], "PD_TNONE")                 # neither half
    g("20", ["TDY1_n", "TDY2_n", "TDY3_n", "TDY4_n"], "TU_A")
    g("04", ["TDY5_n"], "TU_B")
    g("27", ["TU_A", "TU_B", "pT"], "TNONE")
    g("08", ["PD_TNONE", "TNONE"], "TFREE")
    g("00", ["PD_TNONE", "TNONE"], "TFREE_n")
    # the state: SD1 is a new access's first data clock, SPEND waits for T
    # (a write always, while its data is registered), STAKE has it, SOUT
    # drives a read's data. Every access holds WAIT in its first data clock
    g("04", ["SB_WRITE_n"], "SWRL")
    g("11", ["SNEW", "SB_WRITE_n", "TFREE"], "STKA")    # a read, at once
    g("08", ["SPEND", "TFREE"], "STKB")
    g("32", ["STKA", "STKB"], "STAKE_D")
    g("32", ["SWRL", "TFREE_n"], "SPA_")
    g("08", ["SNEW", "SPA_"], "SPA")
    g("08", ["SPEND", "TFREE_n"], "SPB")
    g("32", ["SPA", "SPB"], "SPEND_D")
    g("32", ["TFREE_n", "SWRQ_n"], "SWB_")
    g("08", ["SPEND", "SWB_"], "SWB")
    g("32", ["SNEW", "SWB"], "SWAIT_D")
    g("08", ["STAKE", "SWRQ_n"], "SOUT_D")
    nl.add("175", "U_SST", CLK="BCLK", CLR="RESET_n", **{
        "1D": "STAKE_D", "1Q": "STAKE", "1QN": "STAKE_n",
        "2D": "SPEND_D", "2Q": "SPEND",
        "3D": "SOUT_D", "3Q": "SOUT", "3QN": "SOUT_n",
        "4D": "SWAIT_D", "4QN": "SWAIT_n"})
    nl.add("125", "U_SWT", part="74ABT125", **{"1OE": "SWAIT_n", "1A": "GND", "1Y": "SB_WAIT_n",
                                               "2OE": "VCC", "2A": "GND", "3OE": "VCC", "3A": "GND",
                                               "4OE": "VCC", "4A": "GND"})
    # a write's data, registered at the end of its first data clock, onto
    # T in STAKE and written from STAKE's start until BCLK falls (STAKEF is
    # STAKE taken on the falling edge); a read's from T into SRD at STAKE's
    # end, onto D in SOUT
    reg(nl, "U_SWD0", SBD[0:8], T[0:8], en="SD1_n", oe="SDT_n")
    reg(nl, "U_SWD1", SBD[8:16], T[8:16], en="SD1_n", oe="SDT_n")
    g("00", ["STAKE", "SWRQ"], "SDT_n")
    nl.add("74", "U_STKF", **{"1D": "STAKE", "1CLK": "BCLK_n", "1PRE": "VCC", "1CLR": "RESET_n",
                              "1QN": "STAKEF_n", "2D": "GND", "2CLK": "GND", "2PRE": "VCC",
                              "2CLR": "VCC"})
    g("20", ["STAKE", "STAKEF_n", "SWRQ", "SBE0Q"], "SSWEL_n")
    g("20", ["STAKE", "STAKEF_n", "SWRQ", "SBE1Q"], "SSWEH_n")
    g("00", ["STAKE", "SWRQ_n"], "SSOE_n")
    reg(nl, "U_SRD0", T[0:8], SBD[0:8], en="SSOE_n", oe="SOUT_n")
    reg(nl, "U_SRD1", T[8:16], SBD[8:16], en="SSOE_n", oe="SOUT_n")

    nl.section("Doorbells")
    # set in the write's data clock, while BCLK is low (the address
    # register settled); cleared at E2 by the event port's write, doorbell
    # X[3:0]
    nl.add("175", "U_SDBQ", CLK="BCLK", CLR="RESET_n", **{"1D": "SDB_D", "1Q": "SDBQ",
                                                          "2D": "BELLA", "2Q": "BELL",
                                                          "3D": "SNEW", "3QN": "SD1_n", "4D": "GND"})
    dec(nl, "U_DBS0", ["SSA1", "SSA2", "SSA3"], g1="SDBQ", g2a="BCLK", g2b="SSA4",
        y={k: f"DBSET{k}_n" for k in range(8)})
    dec(nl, "U_DBS1", ["SSA1", "SSA2", "SSA3"], g1="SSA4", g2a="BCLK", g2b="SDBQ_n",
        y={k: f"DBSET{k + 8}_n" for k in range(8)})
    g("04", ["SDBQ"], "SDBQ_n")
    dec(nl, "U_DBC0", XQ[0:3], g2a="DBCLR_n", g2b=XQ[3], y={k: f"DBCLR{k}_n" for k in range(8)})
    dec(nl, "U_DBC1", XQ[0:3], g1=XQ[3], g2a="DBCLR_n", y={k: f"DBCLR{k + 8}_n" for k in range(8)})
    for k in range(8):
        pins = {}
        for s_ in (1, 2):
            i = 2 * k + s_ - 1
            pins.update({f"{s_}J": "GND", f"{s_}K": f"DBCLR{i}_n", f"{s_}CLK": "BCLK",
                         f"{s_}PRE": f"DBSET{i}_n", f"{s_}CLR": "RESET_n",
                         f"{s_}Q": f"DB{i}", f"{s_}QN": f"DB{i}_n"})
        nl.add("109", f"U_DB{k}", nocheck=True, **pins)
    # any doorbell, taken into BCLK's time for the condition
    g("30", [f"DB{i}_n" for i in range(8)], "BELLL")
    g("30", [f"DB{i}_n" for i in range(8, 16)], "BELLH")
    g("32", ["BELLL", "BELLH"], "BELLA")


def window(nl):
    """The I/O bus's window from the system bus (RFC 0037, 20): device S's
    register r at 0x7F0S_0000 + 4r, run on the I/O bus side with the
    device's timing, in turns with the core's accesses. A write is posted:
    it is accepted, ending the transfer, unless the last window access is
    still pending (WPEND), and goes on the I/O bus after. A read holds
    WAIT until its data is registered at the strobe's end, then drives it
    for a clock. On the I/O bus side the window's access (WSEL) starts
    from S0 when the core's isn't in its setup, and the core's waits
    through it. Not yet: an access at 4r + 2 reaching nothing, the
    200-clock bound."""
    g = nl.gate
    nl.section("Window")
    nl.add("521", "U_SDWN", part="74F521", G="GND", PEQ="WIN_n",
           **{f"P{i}": SBA[24 + i] for i in range(8)}, **{f"Q{i}": "VCC" if (0x7F >> i) & 1 else "GND" for i in range(8)})
    g("02", ["SADDR_n", "WIN_n"], "WNEW")
    # W1: a transfer waiting to be accepted; W2: a read accepted, waiting
    # for its data; WOUT: the data on D
    g("08", ["W1", "WPEND_n"], "WACC")
    g("04", ["WACC"], "WACC_n")
    g("08", ["W1", "WPEND"], "W1STAY")
    g("32", ["WNEW", "W1STAY"], "W1_D")
    g("08", ["WACC", "SWRQ_n"], "W2A")
    g("08", ["W2", "WOUT_D_n"], "W2B")
    g("32", ["W2A", "W2B"], "W2_D")
    g("11", ["W2", "STBEND", "WSEL"], "WOUT_D")
    g("04", ["WOUT_D"], "WOUT_D_n")
    # WAIT, from the first data clock on: in W1 for a read, or while the
    # last access is pending; in W2. From the state alone: the address
    # clock's decode leaves no time for more behind it
    g("08", ["W1", "SWRQ_n"], "W1R")
    g("27", ["W1STAY", "W1R", "W2"], "WWAIT_n")
    # the I/O side: WPEND from acceptance to the access's hold's end, WSEL
    # while the I/O side runs it
    g("08", ["WSEL", "HLDEND"], "WDONE")
    g("04", ["WDONE"], "WDONE_n")
    g("08", ["WPEND", "WDONE_n"], "WPSTAY")
    g("32", ["WACC", "WPSTAY"], "WPEND_D")
    g("04", ["IOREQ"], "IOREQ_n")
    g("21", ["WPEND", "WSEL_n", "S0", "IOREQ_n"], "WGO")
    g("08", ["WSEL", "WDONE_n"], "WSSTAY")
    g("32", ["WGO", "WSSTAY"], "WSEL_D")
    nl.add("175", "U_WST", CLK="BCLK", CLR="RESET_n", **{
        "1D": "W1_D", "1Q": "W1", "2D": "W2_D", "2Q": "W2",
        "3D": "WOUT_D", "3QN": "WOUT_n", "4D": "GND"})
    nl.add("175", "U_WIO", CLK="BCLK", CLR="RESET_n", **{
        "1D": "WPEND_D", "1Q": "WPEND", "1QN": "WPEND_n", "2D": "WSEL_D", "2Q": "WSEL", "2QN": "WSEL_n",
        "3D": "GND", "4D": "GND"})
    nl.add("125", "U_WWT", part="74ABT125", **{"1OE": "WWAIT_n", "1A": "GND", "1Y": "SB_WAIT_n",
                                               "2OE": "VCC", "2A": "GND", "3OE": "VCC", "3A": "GND",
                                               "4OE": "VCC", "4A": "GND"})
    # the access: register r (A2-A9), device S (A16-A19) and WRITE, and a
    # write's data, taken when it's accepted
    reg(nl, "U_WA0", bus("SSA", 8, 1), bus("WA", 8), en="WACC_n")
    reg(nl, "U_WA1", bus("SSA", 4, 15) + ["SWRQ"], bus("WA", 4, 8) + ["WAWR"], en="WACC_n")
    g("20", ["AWRITE", "IOACT", "WSEL", "VCC"], "WDOE_n")
    reg(nl, "U_WD0", SBD[0:8], IOD[0:8], en="WACC_n", oe="WDOE_n")
    reg(nl, "U_WD1", SBD[8:16], IOD[8:16], en="WACC_n", oe="WDOE_n")
    # a read's data, at the strobe's end, onto D in WOUT
    g("20", ["STBEND", "WSEL", "AWRITE_n", "VCC"], "WRDLD_n")
    reg(nl, "U_WRD0", IOD[0:8], SBD[0:8], en="WRDLD_n", oe="WOUT_n")
    reg(nl, "U_WRD1", IOD[8:16], SBD[8:16], en="WRDLD_n", oe="WOUT_n")


def add_bench(nl, master=False):
    """Around the card on the system bus, for the simulator: the
    backplane's pull-ups and COLD at power-up, an arbiter that grants REQ3 4 clocks after it
    rises (as RFC 0037, 6.2's on an idle bus), and a CPU card's RAM in
    region 0 that answers in 2 data clocks, as the model's does
    (sim/src/system.rs), 1 MB of it; a stuck slave in region 5, which
    holds WAIT until RESET. ATN0-3 are quiet. `master`: a
    scripted second master (M_OUT, M_IN), its script X_M's preload."""
    g = nl.gate
    nl.section("Test bench")
    if master:
        v = nl.add("vector", "X_M", CLK="BCLK", params={"outs": len(M_OUT), "ins": len(M_IN),
                                                         "conds": M_CONDS, "delay_ps": M_DELAY_PS})
        for i, n in enumerate(M_OUT):
            v[f"O{i}"] = n
        for i in range(48):
            v[f"I{i}"] = M_IN[i] if i < len(M_IN) else "GND"
    nl.add("pullup", "X_PU0", P1="SB_WAIT_n", P2="SB_RESET_n", P3="SB_ATN0_n", P4="SB_ATN1_n",
           P5="SB_ATN2_n", P6="SB_ATN3_n", P7="SB_GNT3_n", P8="SB_COLD_n")
    # the backplane's power supply supervisor: COLD at power-up, and RESET
    # with it (RFC 0037, 7)
    nl.add("por", "X_POR", RST="SB_COLD_n", params={"release_ps": POR_PS})
    nl.add("por", "X_PORR", RST="SB_RESET_n", params={"release_ps": POR_PS})
    g("04", ["SB_REQ3_n"], "X_REQ")
    nl.add("175", "X_ARB", CLK="BCLK", CLR="RESET_n", **{
        "1D": "X_REQ", "1Q": "X_G1", "2D": "X_G1R", "2Q": "X_G2", "3D": "X_G2R", "3Q": "X_G3",
        "4D": "GND"})
    g("08", ["X_G1", "X_REQ"], "X_G1R")
    g("08", ["X_G2", "X_REQ"], "X_G2R")
    g("00", ["X_G3", "X_REQ"], "SB_GNT3_n")
    # the RAM: the address clock registered, WAIT in the first data clock,
    # the data in the second
    g("04", ["SB_START_n"], "X_START")
    g("02", ["SB_A28", "SB_A29"], "X_R0A")
    g("02", ["SB_A30", "SB_A31"], "X_R0B")
    g("11", ["X_START", "X_R0A", "X_R0B"], "X_SEL")
    reg(nl, "X_SA0", SBA[1:10], bus("X_SA", 9, 1), en="SB_START_n")
    reg(nl, "X_SA1", SBA[10:19], bus("X_SA", 9, 10), en="SB_START_n")
    reg(nl, "X_SA2", [SBA[19], "SB_WRITE_n", "SB_BE0_n", "SB_BE1_n"],
        ["X_SA19", "X_WR_n", "X_BE0_n", "X_BE1_n"], en="SB_START_n")
    nl.add("175", "X_SDP", CLK="BCLK", CLR="RESET_n", **{
        "1D": "X_SEL", "1Q": "X_D1", "1QN": "X_D1_n", "2D": "X_D1", "2Q": "X_D2", "3D": "GND",
        "4D": "GND"})
    nl.add("125", "X_WAIT", part="74ABT125", **{"1OE": "X_D1_n", "1A": "GND", "1Y": "SB_WAIT_n",
                                                "2OE": "X_STK_n", "2A": "GND", "2Y": "SB_WAIT_n",
                                                "3OE": "VCC", "3A": "GND", "4OE": "VCC", "4A": "GND"})
    # a stuck slave in region 5: it holds WAIT from its address clock
    # until the system bus's RESET
    g("04", ["SB_A31"], "X_A31_n")
    g("04", ["SB_A29"], "X_A29_n")
    g("21", ["X_START", "X_A31_n", "SB_A30", "X_A29_n"], "X_R5A")
    g("08", ["X_R5A", "SB_A28"], "X_SEL5")
    g("32", ["X_SEL5", "X_STK"], "X_STK_D")
    nl.add("74", "X_STKF", **{"1D": "X_STK_D", "1CLK": "BCLK", "1PRE": "VCC", "1CLR": "SB_RESET_n",
                              "1Q": "X_STK", "1QN": "X_STK_n", "2D": "GND", "2CLK": "GND", "2PRE": "VCC",
                              "2CLR": "VCC"})
    g("04", ["X_WR_n"], "X_WR")
    g("00", ["X_D2", "X_WR_n"], "X_OE_n")
    # the write strobe: from data clock 2's start until BCLK falls, as the
    # IOP's own SRAM's (X_D2F is X_D2 taken on the falling edge)
    nl.add("74", "X_D2F", **{"1D": "X_D2", "1CLK": "BCLK_n", "1PRE": "VCC", "1CLR": "RESET_n",
                             "1QN": "X_D2F_n", "2D": "GND", "2CLK": "GND", "2PRE": "VCC", "2CLR": "VCC"})
    g("08", ["X_D2", "X_D2F_n"], "X_WWIN")
    g("20", ["X_WWIN", "X_WR", "X_BE0", "VCC"], "X_WEL_n")
    g("20", ["X_WWIN", "X_WR", "X_BE1", "VCC"], "X_WEH_n")
    g("04", ["X_BE0_n"], "X_BE0")
    g("04", ["X_BE1_n"], "X_BE1")
    for h, side in enumerate("LH"):
        pins = {f"A{i}": f"X_SA{i + 1}" for i in range(19)}
        pins.update({f"IO{i}": SBD[8 * h + i] for i in range(8)})
        nl.add("sram512", f"X_RAM{side}", part="AS7C4096A-12", CE="GND", OE="X_OE_n",
               WE=f"X_WE{side}_n", **pins)
