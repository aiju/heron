"""The IO board: the devices, their strobes and waits, the interrupts, the
boot flash, reset.

An access to the I/O space is a load or store whose address has A30 set
(MEM gives IORD_n or IOWR_n for its cycle). This board's part of the
space is A29 clear:

  A28 set      the boot flash (SST39SF010A, a byte per halfword: A17-A1)
  A28 clear    the devices, by A15-A12: 0 UART 0, 1 UART 1, 2 timer
               (82C54), 3 and 4 the CF card's command and control blocks
               (16-bit True IDE), 5 PS/2 and the interrupt controller and
               the DAC (by A13-A12 again within DEVX: see U_IRQ, U_KBD)

The address: U_IA (three 574s) take A when MEM's MAR does (ALE: U_IOT's
gated clock ALEK), and U_IOD decodes it at the same edge into the
selects. The access: U_IOT gives the devices' strobes (IOR_n, IOW_n) from
the cycle's second tick, holds the cycle (WAIT_IO) for the device's class
of access time, and ends a write's strobe as the write phase starts. Data
comes on A (a store's) and goes on B (a load's), each through 541s;
B16-B31 read 0.
"""

from heron.infra.hw import gal as G
from heron.infra.hw.netlist import Netlist

from . import bus as BP
from .common import AND, OR, ONE, ZERO, anyof, bus, clock_buffer, eq, gated_clock, lit, negate, table

IOA, IOD = bus("IOA", 24), bus("IOD", 16)
UCLK_PS = 542535                        # 1.8432 MHz
# the devices' access classes: ticks of WAIT_IO from the strobe's start
CLASS = {"fast": 0, "uart": 1, "slow": 2, "cf": 3}
WAIT_TICKS = {0: 2, 1: 4, 2: 7, 3: 13}


def build(sim=True):
    nl = Netlist()
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")
    ck = clock_buffer(nl, src="CYC")
    nl.section("address and strobes")
    address(nl, ck)
    nl.section("data")
    data(nl)
    nl.section("devices")
    devices(nl, sim)
    nl.section("PS/2")
    ps2(nl)
    nl.section("interrupts and reset")
    interrupts(nl, sim)
    BP.connectors(nl)
    nl.finish()
    return nl


def address(nl, ck):
    for k in range(3):
        nl.add("574", f"U_IA{k}", OE="GND", CLK="ALEK",
               **{f"D{i + 1}": BP.A[8 * k + i] for i in range(8)},
               **{f"Q{i + 1}": IOA[8 * k + i] for i in range(8)})
    # U_IOD, at ALEK: this board's selects and the access's class
    a = BP.A
    mine = AND(lit(a[30]), lit(a[29], 0))
    dev = AND(mine, lit(a[28], 0))

    def slot(n):
        return AND(dev, eq(a[12:16], n))
    sel = {"CS_UART0_n": slot(0), "CS_UART1_n": slot(1), "CS_TMR_n": slot(2), "CS_CF0_n": slot(3),
           "CS_CF1_n": slot(4), "DEVX_n": slot(5), "CS_FLASH_n": AND(mine, lit(a[28]))}
    outs = {n: (e, True, True) for n, e in sel.items()}
    outs["SELIO"] = (mine, True, False)
    # the class: UARTs 1, the timer 2, the CF card 3, the rest (flash, DEVX) 0
    outs["CLS0"] = (OR(slot(0), slot(1), slot(3), slot(4)), True, False)
    outs["CLS1"] = (OR(slot(2), slot(3), slot(4)), True, False)
    G.add(nl, "U_IOD", outs, clock="ALEK")
    # U_IOT, on MCLK: ALEK; the strobes; WAIT_IO from a count of ticks
    outs = {}
    gated_clock(outs, "ALEK", lit("ALE"), clk=ck[1])
    rd = AND(lit("IORD_n", 0), lit("SELIO"))
    wr = AND(lit("IOWR_n", 0), lit("SELIO"))
    acc = OR(rd, wr)
    cnt = ["W0", "W1", "W2", "W3"]
    ins = cnt + ["CLS0", "CLS1"]

    def done(w0, w1, w2, w3, c0, c1):
        return int((w0 | w1 << 1 | w2 << 2 | w3 << 3) >= WAIT_TICKS[c0 | c1 << 1])
    full = table(ins, done)
    for i in range(4):
        # count while the access lasts and isn't done, else 0
        inc = table(cnt, lambda *b, i=i: ((sum(v << k for k, v in enumerate(b)) + 1) >> i) & 1)
        outs[cnt[i]] = (AND(acc, OR(AND(lit("WDONE", 0), inc), AND(lit("WDONE"), lit(cnt[i])))), True, False)
    outs["WDONE"] = (full, False, False)
    outs["WAIT_IO"] = (AND(acc, lit("WDONE", 0)), False, False)
    outs["IOR_n"] = (rd, True, True)
    outs["IOW_n"] = (AND(wr, lit("WPH", 0)), True, True)
    G.add(nl, "U_IOT", outs, clock="MCLK")


def data(nl):
    """Reads onto B (B16-B31 0) while the access lasts, but for the cycle's
    first two ticks (so that the driver is off as the next cycle starts);
    writes from A."""
    G.add(nl, "U_IOB", {
        "IOBOE_n": (AND(lit("IORD_n", 0), lit("SELIO"), lit("CK1", 0)), False, True),
        "IOWOE_n": (AND(lit("IOWR_n", 0), lit("SELIO")), False, True),
    })
    for k in range(2):
        nl.add("541", f"U_DR{k}", OE1="IOBOE_n", OE2="GND",
               **{f"A{i + 1}": IOD[8 * k + i] for i in range(8)},
               **{f"Y{i + 1}": BP.B[8 * k + i] for i in range(8)})
        nl.add("541", f"U_DZ{k}", OE1="IOBOE_n", OE2="GND", **{f"A{i + 1}": "GND" for i in range(8)},
               **{f"Y{i + 1}": BP.B[16 + 8 * k + i] for i in range(8)})
        nl.add("541", f"U_DW{k}", OE1="IOWOE_n", OE2="GND",
               **{f"A{i + 1}": BP.A[8 * k + i] for i in range(8)},
               **{f"Y{i + 1}": IOD[8 * k + i] for i in range(8)})
    nl.add("pullup", "R_IOD0", **{f"P{i + 1}": IOD[i] for i in range(8)})
    nl.add("pullup", "R_IOD1", **{f"P{i + 1}": IOD[8 + i] for i in range(8)})


def devices(nl, sim):
    if sim:
        nl.add("osc", "X_UCLK", OUT="UCLK", params={"period_ps": UCLK_PS, "phase_ps": 0})
    for k in range(2):
        nl.add("16c550s", f"U_UART{k}", CS0="VCC", CS1="VCC", CS2=f"CS_UART{k}_n",
               RD="IOR_n", WR="IOW_n", MR="RESET", XIN="UCLK",
               **{f"D{i}": IOD[i] for i in range(8)}, **{f"A{i}": IOA[1 + i] for i in range(3)},
               SIN=f"RXD{k}", CTS=f"CTS{k}", INTR=f"UINT{k}", SOUT=f"TXD{k}", RTS=f"RTS{k}",
               DTR=f"DTR{k}", OUT1=f"OUT1_{k}", OUT2=f"OUT2_{k}")
        nl.add("max232", f"U_RS{k}", T1IN=f"TXD{k}", T2IN=f"RTS{k}", R1IN=f"P{k}RXD", R2IN=f"P{k}CTS",
               T1OUT=f"P{k}TXD", T2OUT=f"P{k}RTS", R1OUT=f"RXD{k}", R2OUT=f"CTS{k}")
        nl.add("conn", f"J_SER{k}", part="DE-9 male", P0=f"P{k}TXD", P1=f"P{k}RTS", P2=f"P{k}RXD",
               P3=f"P{k}CTS", P4="GND", P5="GND", P6="GND", P7="GND")
    nl.add("82c54", "U_TMR", CS="CS_TMR_n", RD="IOR_n", WR="IOW_n",
           **{f"D{i}": IOD[i] for i in range(8)}, A0=IOA[1], A1=IOA[2],
           CLK0="UCLK", GATE0="VCC", CLK1="UCLK", GATE1="VCC", CLK2="UCLK", GATE2="VCC",
           OUT0="TINT", OUT1="TOUT1", OUT2="SPKR")
    nl.add("flash", "U_BOOT", part="SST39SF010A-55", CE="CS_FLASH_n", OE="IOR_n", WE="IOW_n",
           **{f"A{i}": IOA[1 + i] for i in range(17)}, **{f"D{i}": IOD[i] for i in range(8)})
    nl.add("cf", "U_CF", **{f"D{i}": IOD[i] for i in range(16)}, A0=IOA[1], A1=IOA[2], A2=IOA[3],
           CS0="CS_CF0_n", CS1="CS_CF1_n", IORD="IOR_n", IOWR="IOW_n", RESET="RESET_n",
           INTRQ="CFINT", WAKE="CF_WAKE")
    # sound: the DAC's input latch written at DEVX's +0x3000 (A13-A12 = 3)
    nl.add("dac0832", "U_DAC", **{f"D{i}": IOD[i] for i in range(8)}, CS="DACCS_n", WR1="IOW_n",
           WR2="GND", XFER="GND", ILE="VCC", VOUT="DACOUT")
    nl.add("mcp6002", "U_AMP", IN="DACOUT", OUT="AUDIO", REF="VREF")
    nl.add("conn", "J_AUDIO", part="3.5 mm jack, the speaker's transistor", P0="AUDIO", P1="SPKR",
           P2="GND", P3="GND", P4="GND", P5="GND", P6="GND", P7="GND")


def ps2(nl):
    """Two PS/2 ports. Each a GAL on MCLK (U_KBD, U_MSE) and a 74F299: the
    clock line synchronised (S1, S2), each falling edge a count (C0-C3) of
    the frame's bits, the 299 shifting in the data line for bits 1-8;
    after the stop bit the port's interrupt (KIRQ, MIRQ) until the byte is
    read (DEVX, A13-A12 = 0 or 1, the 299 onto IOD0-IOD7). Sending to a
    device is software's: a write there sets the port's pulls on its clock
    and data lines (IOD4, IOD5), each a GAL output pulling its line low."""
    nl.add("14", "U_PSS", part="74HCT14", **{"1A": "KCLK", "1Y": "KCLK_n", "2A": "KDATA", "2Y": "KDATA_n",
                                             "3A": "MCLKL", "3Y": "MCLKL_n", "4A": "MDATA",
                                             "4Y": "MDATA_n", "5A": "GND", "6A": "GND"})
    nl.add("pullup", "R_PS2", P1="KCLK", P2="KDATA", P3="MCLKL", P4="MDATA")
    for port, a12, clk, data, irq in (("KBD", 0, "KCLK", "KDATA", "KIRQ"),
                                      ("MSE", 1, "MCLKL", "MDATA", "MIRQ")):
        s1, s2, c = f"{port}_S1", f"{port}_S2", [f"{port}_C{i}" for i in range(4)]
        sel = AND(lit("DEVX_n", 0), lit(IOA[13], 0), lit(IOA[12], a12))
        rd = AND(sel, lit("IOR_n", 0))
        wr = AND(sel, lit("IOW_n", 0))
        edge = AND(lit(s1), lit(s2, 0))            # a falling edge (S1 the clock inverted, as the 14 gives it)
        outs = {s1: (lit(f"{clk}_n"), True, False), s2: (lit(s1), True, False)}
        ins = c

        def nxt(*b, i=0):
            v = sum(x << k for k, x in enumerate(b))
            return ((0 if v >= 10 else v + 1) >> i) & 1
        for i in range(4):
            stepped = table(ins, lambda *b, i=i: nxt(*b, i=i))
            outs[c[i]] = (AND(lit("RESET_n"), OR(AND(edge, stepped), AND(negate(edge), lit(c[i])))),
                          True, False)
        in_byte = table(c, lambda *b: int(1 <= sum(x << k for k, x in enumerate(b)) <= 8))
        outs[f"{port}_SH"] = (AND(edge, in_byte), False, False)
        done = AND(edge, eq(c, 10))
        outs[irq] = (AND(lit("RESET_n"), OR(done, AND(lit(irq), negate(rd)))), True, False)
        # the pulls: registered from IOD4 (clock) and IOD5 (data) on a write;
        # each output drives its line low while its register is set
        for line, bit in ((clk, IOD[4]), (data, IOD[5])):
            pull = f"{line}_PULL"
            outs[pull] = (OR(AND(wr, lit(bit)), AND(negate(wr), lit(pull))), True, False)
        G.add(nl, f"U_{port}", outs, clock="MCLK")
        # the lines' open drains: a 541 channel each, its input low, enabled by the pull
        nl.add("299", f"U_{port}SR", S0="GND", S1=f"{port}_SH", OE1="IOR_n", OE2=f"{port}SEL_n",
               MR="RESET_n", CP="MCLK", DS0="GND", DS7=f"{data}_n_INV",
               **{f"IO{i}": IOD[i] for i in range(8)}, Q0S=f"{port}_Q0", Q7S=f"{port}_Q7")
    # the data lines' true sense for the 299s, and the pulls' open drains
    G.add(nl, "U_PSO", {
        "KDATA_n_INV": (lit("KDATA_n", 0), False, False),
        "MDATA_n_INV": (lit("MDATA_n", 0), False, False),
        "KCLK": (ZERO, False, False, lit("KCLK_PULL")),
        "KDATA": (ZERO, False, False, lit("KDATA_PULL")),
        "MCLKL": (ZERO, False, False, lit("MCLKL_PULL")),
        "MDATA": (ZERO, False, False, lit("MDATA_PULL")),
    })
    nl.add("conn", "J_PS2", part="two PS/2 sockets", P0="KCLK", P1="KDATA", P2="MCLKL", P3="MDATA",
           P4="GND", P5="GND", P6="GND", P7="GND")


def interrupts(nl, sim):
    """U_IRQ: IRQ while a source is up; a read at DEVX +0x2000 gives the
    highest one's number (IOD0-IOD2: 0 the timer, 1 the frame, 2 UART 0,
    3 UART 1, 4 the keyboard, 5 the mouse, 6 the CF card, 7 none); the
    UARTs' reset (RESET, high) and the DAC's select."""
    src = ["TINT", "VIRQ", "UINT0", "UINT1", "KIRQ", "MIRQ", "CFINT"]
    sel = AND(lit("DEVX_n", 0), lit(IOA[13]), lit(IOA[12], 0), lit("IOR_n", 0))

    def vec(i):
        def fn(*s):
            for k, v in enumerate(s):
                if v:
                    return (k >> i) & 1
            return (7 >> i) & 1
        return table(src, fn)
    outs = {"IRQ": (OR(*[lit(s) for s in src]), False, False),
            "RESET": (lit("RESET_n", 0), False, False),
            "DACCS_n": (AND(lit("DEVX_n", 0), lit(IOA[13]), lit(IOA[12])), False, True),
            "KBDSEL_n": (AND(lit("DEVX_n", 0), lit(IOA[13], 0), lit(IOA[12], 0)), False, True),
            "MSESEL_n": (AND(lit("DEVX_n", 0), lit(IOA[13], 0), lit(IOA[12])), False, True)}
    for i in range(3):
        outs[IOD[i]] = (vec(i), False, False, sel)
    G.add(nl, "U_IRQ", outs)
    if sim:
        nl.add("por", "U_POR", RST="RESET_n", params={"release_ps": 2_000_000})
    else:
        nl.add("por", "U_POR", RST="RESET_n")
    nl.add("pullup", "R_RST", P1="RESET_n")
