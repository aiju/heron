"""The draft netlist's I/O (board.build(sim=False, halves=True)): what
Emily's second round added, for the parts count and the timing netlist,
not simulated.

The I/O space (A31 set), by MAR's bits 20-18:

    000  0x8000_0000  UART 0          100  0x8010_0000  the boot flash
    001  0x8004_0000  UART 1          101  0x8014_0000  slow devices, by A5-A4:
    010  0x8008_0000  PS/2                 00 the timer (82C54), 01 the CF card
    011  0x800C_0000  video control        (A6: its control block), 10 the palette
    110  0x8018_0000  interrupts      111  0x801C_0000  free (the simulation's
                                           test fixture)

- The slow devices (the CF card, the 82C54, the RAMDAC) sit behind
  U_SLOW, a wait-state machine on the master clock that holds the CPU's
  cycle (HOLD) and times their strobes itself: the CF card at PIO mode 0's
  timing (address 4 ticks before its strobe, the strobe 9 ticks, 3 ticks'
  hold: 18 ticks), the others 12. Their strobes never come from the CPU's.
- The CF card has a bus of its own: 74HCT245s for its data, a 74HCT541
  for its address, selects and strobes (slow edges), series resistors on
  every line at the buffers, the buffers on only while it's accessed;
  16-bit True IDE, the mode every card has.
- The interrupt controller, U_IRQ: the sources' OR (IRQ), their status at
  +0, at +2 a vector, 0x40 + 4 x the highest-priority source, for the
  microcode's interrupt entry; the interrupt button's latch (cleared by a
  write).
- The palette: an IMS G171 (UM70C171) RAMDAC, 256 x 18 bits, the pixel's 4
  bits on its P3-0.
- Each UART: a MAX232 for RS-232 (TX, RX, RTS, CTS), a jumper block between
  it and the UART, and on the UART's side a 6-pin TTL header (FTDI's
  pinout), for a TTL cable with the jumpers off.
- PS/2: the lines through a 74HCT14's Schmitt inputs; per port a third
  22V10 counting the frame's parity and stop edges after the byte, then
  holding the clock low until the byte is read.
- Debugging: three 32-pin headers (16 signals over 16 grounds, 0.1 inch)
  for a Saleae Logic Pro 16 or any analyser with flying leads, through
  100-ohm resistors: the control store's address and the clock; the
  sequencer's other state, the flags and the phase; the D bus.
"""

from heron.infra.hw import chips, gal as G

from . import ucode as uc
from .board import AND, OR, ONE, ZERO, bus, eq, field, lit, negate

T = chips.T


def _types():
    if "16c550x" in chips.TYPES:
        return
    T("16c550x", "uart16550",
      [(f"D{i}", "io") for i in range(8)] + [(f"A{i}", "in") for i in range(3)]
      + [(p, "in") for p in ("CS0", "CS1", "CS2", "RD", "WR", "MR", "XIN", "SIN", "CTS")]
      + [(p, "out") for p in ("INTR", "SOUT", "RTS", "DTR", "OUT1", "OUT2")],
      arcs=[(["RD"], [f"D{i}" for i in range(8)], "RD->D")], family="device",
      desc="TL16C550C with its serial pins (the draft netlist's)")
    T("g171", "ramdac",
      [(f"P{i}", "in") for i in range(8)] + [(f"D{i}", "io") for i in range(8)]
      + [(p, "in") for p in ("RS0", "RS1", "RD", "WR", "PCLK", "BLANK")]
      + [(p, "out") for p in ("IOR", "IOG", "IOB")], family="device",
      desc="IMS G171 RAMDAC: 256 x 18-bit palette, three 6-bit DACs (RD, WR, BLANK active low)")
    T("max232", "passive", [(p, "in") for p in ("T1IN", "T2IN", "R1IN", "R2IN")]
      + [(p, "out") for p in ("T1OUT", "T2OUT", "R1OUT", "R2OUT")], family="device",
      desc="RS-232 driver and receiver, two of each, its charge pump's capacitors on board")
    T("hdr32", "passive", [(f"S{i}", "pull") for i in range(16)], family="passive",
      desc="32-pin 0.1-inch header: 16 signals, a ground beside each")
    T("ftdi6", "passive", [(p, "pull") for p in ("CTS", "TXD", "RXD", "RTS")], family="passive",
      desc="6-pin TTL serial header, FTDI's pinout (GND CTS VCC TXD RXD RTS)")
    T("jmp4", "passive", [(f"A{i}", "pull") for i in range(4)] + [(f"B{i}", "pull") for i in range(4)],
      family="passive", desc="four jumpers, Ai to Bi")
    T("rser8", "passive", [(f"A{i}", "pull") for i in range(8)] + [(f"B{i}", "pull") for i in range(8)],
      family="passive", desc="eight series resistors, Ai to Bi (a network)")
    T("conn", "passive", [(f"P{i}", "pull") for i in range(4)], family="passive",
      desc="a connector, socket or switch (its part names it)")


# the draft's parts: those without timing data are named here (chips.FIXED_PARTS)
PARTS = {"16c550x": "TL16C550C", "g171": "IMS G171", "max232": "MAX232", "hdr32": "header 2x16",
         "ftdi6": "header 1x6", "jmp4": "jumpers 2x4", "rser8": "resistor network x8",
         "conn": "connector", "_r33": "33 ohm x 8", "_r100": "100 ohm x 8", "_db9": "DE-9 male",
         "_btn": "push buttons: interrupt, reset", "_hlt": "push button (SPDT): halt to ODT",
         "_run": "run/step switch and step button"}
chips.FIXED_PARTS.update(PARTS)


def io(nl):
    _types()
    mop = field("MOP")
    rdm, wrm = eq(mop, uc.MOP_RDM), eq(mop, uc.MOP_WRM)
    m = ["MAR18", "MAR19", "MAR20"]

    def sel(v):
        return AND(lit("A31"), eq(m, v))
    G.add(nl, "U_IODEC", {
        "U0CS_n": (sel(0), False, True), "U1CS_n": (sel(1), False, True),
        "PS2CS": (sel(2), False, False), "VCCS": (sel(3), False, False),
        "FLCS_n": (sel(4), False, True), "SLOWCS": (sel(5), False, False),
        "IRQCS": (sel(6), False, False), "CONSEL_n": (sel(7), False, True),
    })
    # the UARTs, RS-232 and TTL
    for k in range(2):
        nl.add("16c550x", f"U_UART{k}", CS0="VCC", CS1="VCC", CS2=f"U{k}CS_n", RD="IORD_n",
               WR="IOWR_n", MR="RESET", XIN="UCLK", INTR=f"U{k}INT", SOUT=f"U{k}TX",
               SIN=f"U{k}RX", RTS=f"U{k}RTS", CTS=f"U{k}CTS",
               **{f"D{i}": f"MD{i}" for i in range(8)}, **{f"A{i}": f"A{i + 1}" for i in range(3)})
        sig = ("TX", "RTS", "RX", "CTS")
        nl.add("jmp4", f"J_SER{k}", **{f"A{i}": f"U{k}{s}" for i, s in enumerate(sig)},
               **{f"B{i}": f"U{k}{s}J" for i, s in enumerate(sig)})
        nl.add("ftdi6", f"J_TTL{k}", TXD=f"U{k}TX", RXD=f"U{k}RX", RTS=f"U{k}RTS", CTS=f"U{k}CTS")
        nl.add("max232", f"U_RS{k}", T1IN=f"U{k}TXJ", T2IN=f"U{k}RTSJ", R1OUT=f"U{k}RXJ",
               R2OUT=f"U{k}CTSJ", T1OUT=f"P{k}TXD", T2OUT=f"P{k}RTS", R1IN=f"P{k}RXD",
               R2IN=f"P{k}CTS")
        nl.add("conn", f"J_DB9{k}", P0=f"P{k}TXD", P1=f"P{k}RTS", P2=f"P{k}RXD", P3=f"P{k}CTS",
               part="DE-9 male")
    nl.add("flash", "U_BOOT", CE="FLCS_n", OE="IORD_n", WE="IOWR_n", part="SST39SF010A-55",
           **{f"A{i}": f"A{i + 1}" for i in range(17)}, **{f"D{i}": f"MD{i}" for i in range(8)})
    nl.add("const", "X_IOK", LO="CONIRQ", HI="UCLK")
    slow_devices(nl, rdm, wrm)
    interrupts(nl)
    odt(nl)
    ps2(nl)
    debug(nl)


def slow_devices(nl, rdm, wrm):
    """U_SLOW: W4-W0 count the access's ticks from its start (SLOWCS and a
    memory operation, out of phase F) until SDONE, at the device's length;
    HOLD holds the CPU's cycle until then; SRD_n and SWR_n are the strobe. U_SLOWD:
    the device selects and gated strobes, the CF buffers' enable and direction."""
    w = bus("W", 5)
    acc = AND(lit("SLOWCS"), OR(rdm, wrm), lit("PHW", 0))
    cf = AND(lit("A5", 0), lit("A4", 1))

    def at(lo, hi):
        """W in [lo, hi), for this device's lengths (the CF's, else the others')"""
        return OR(AND(cf, G.when(w, list(range(lo[0], hi[0])), range(32))),
                  AND(negate(cf), G.when(w, list(range(lo[1], hi[1])), range(32))))
    outs = {}
    done = lit("SDONE")
    for i in range(5):
        outs[w[i]] = (OR(AND(acc, lit("SDONE", 0), _inc(w, i)), AND(acc, done, lit(w[i]))),
                      True, False)
    outs["SDONE"] = (OR(AND(acc, done), AND(acc, cf, eq(w, 18)), AND(acc, negate(cf), eq(w, 12))),
                     True, False)
    outs["HOLD"] = (AND(acc, lit("SDONE", 0)), False, False)
    outs["SRD_n"] = (AND(acc, rdm, at((4, 2), (13, 8))), True, True)
    outs["SWR_n"] = (AND(acc, wrm, at((4, 2), (13, 8))), True, True)
    # the CF buffers' enable: registered, on from the access's second tick to
    # two before its end, so that the buffers' slow turn-off stays off the
    # CPU's paths
    outs["CFOE_n"] = (AND(acc, cf, G.when(w, list(range(1, 16)), range(32))), True, True)
    G.add(nl, "U_SLOW", outs, clock="MCLK", ar=lit("RESET_n", 0))
    dev = {"TMR": (0, 0), "CF": (0, 1), "DAC": (1, 0)}

    def is_(name):
        a5, a4 = dev[name]
        return AND(lit("SLOWCS"), lit("A5", a5), lit("A4", a4))
    G.add(nl, "U_SLOWD", {
        "TMRCS_n": (is_("TMR"), False, True),
        "CFCS0_n": (AND(is_("CF"), lit("A6", 0)), False, True),
        "CFCS1_n": (AND(is_("CF"), lit("A6", 1)), False, True),
        "CFRD_n": (AND(is_("CF"), lit("SRD_n", 0)), False, True),
        "CFWR_n": (AND(is_("CF"), lit("SWR_n", 0)), False, True),
        "CFDIR": (wrm, False, False),
        "DACRD_n": (AND(is_("DAC"), lit("SRD_n", 0)), False, True),
        "DACWR_n": (AND(is_("DAC"), lit("SWR_n", 0)), False, True),
    })
    nl.add("82c54", "U_TMR", CS="TMRCS_n", RD="SRD_n", WR="SWR_n", A0="A1", A1="A2",
           CLK0="UCLK", CLK1="UCLK", CLK2="UCLK", GATE0="VCC", GATE1="VCC", GATE2="VCC",
           OUT0="TIRQ", OUT1="TOUT1", OUT2="SPK", **{f"D{i}": f"MD{i}" for i in range(8)})
    # the CF card's own bus
    for k in range(2):
        nl.add("245", f"U_CFD{k}", DIR="CFDIR", OE="CFOE_n", part="74HCT245",
               **{f"A{i + 1}": f"MD{8 * k + i}" for i in range(8)},
               **{f"B{i + 1}": f"CFB{8 * k + i}" for i in range(8)})
        nl.add("rser8", f"R_CFD{k}", **{f"A{i}": f"CFB{8 * k + i}" for i in range(8)},
               **{f"B{i}": f"CFD{8 * k + i}" for i in range(8)}, part="33 ohm x 8")
    ctl = ["A1", "A2", "A3", "CFCS0_n", "CFCS1_n", "CFRD_n", "CFWR_n", "RESET_n"]
    nl.add("541", "U_CFA", OE1="GND", OE2="GND", part="74HCT541",
           **{f"A{i + 1}": n for i, n in enumerate(ctl)},
           **{f"Y{i + 1}": f"CFX{i}" for i in range(8)})
    nl.add("rser8", "R_CFA", **{f"A{i}": f"CFX{i}" for i in range(8)},
           **{f"B{i}": f"CFY{i}" for i in range(8)}, part="33 ohm x 8")
    nl.add("cf", "J_CF", A0="CFY0", A1="CFY1", A2="CFY2", CS0="CFY3", CS1="CFY4",
           IORD="CFY5", IOWR="CFY6", RESET="CFY7", INTRQ="CFIRQ", WAKE="CFWAKE",
           **{f"D{i}": f"CFD{i}" for i in range(16)})
    nl.add("pullup", "R_CF", P1="CFIRQ")
    # the palette
    nl.add("g171", "U_DAC", RS0="A1", RS1="A2", RD="DACRD_n", WR="DACWR_n", PCLK="PIX",
           BLANK="DEN", IOR="VGA_R", IOG="VGA_G", IOB="VGA_B",
           **{f"P{i}": f"PX{i}" if i < 4 else "GND" for i in range(8)},
           **{f"D{i}": f"MD{i}" for i in range(8)})


def _inc(w, i):
    """Bit i of W + 1."""
    lower = w[:i]
    return OR(AND(lit(w[i], 1), OR(*[lit(b, 0) for b in lower])) if lower else ZERO,
              AND(lit(w[i], 0), [{b: 1 for b in lower}] if lower else ONE))


SOURCES = ["TIRQ", "VIRQ", "U0INT", "U1INT", "KIRQ", "MIRQ", "CFIRQ", "BTNQ"]   # by priority


def interrupts(nl):
    """U_IRQ: IRQ, the sources' status at +0 and the vector at +2 (0x40 +
    4 x the first source pending), BTNQ the button's latch."""
    rd = AND(lit("IRQCS"), lit("IORD_n", 0))
    outs = {"IRQ": (OR(*[lit(s) for s in SOURCES[:-1]], lit("BTNQ")), False, False),
            "BTNQ": (OR(lit("BTN_n", 0), AND(lit("BTNQ"), negate(AND(lit("IRQCS"),
                                                                      lit("IOWR_n", 0))))),
                     False, False)}
    first = []
    for k, s in enumerate(SOURCES):
        first.append(AND(*[lit(x, 0) for x in SOURCES[:k]], lit(s)))
    for i in range(8):
        status = lit(SOURCES[i])
        vec = ONE if i == 6 else (OR(*[first[k] for k in range(8) if (k >> (i - 2)) & 1])
                                  if 2 <= i <= 4 else ZERO)
        outs[f"MD{i}"] = (OR(AND(lit("A1", 0), status), AND(lit("A1"), vec)), False, False, rd)
    G.add(nl, "U_IRQ", outs)
    nl.add("por", "U_BTN", RST="BTN_n")                 # the interrupt button's debouncer
    nl.add("conn", "S_BTN", P0="BTN_n", P1="RESET_n", part="push buttons: interrupt, reset")


def ps2(nl):
    """Schmitt inputs, the receivers on the clock's falling edge (its inverse
    rising), and the frame GALs: P after the parity bit's edge, S (the hold)
    after the stop bit's, FERR if the stop bit was 0."""
    nl.add("14", "U_PSS", part="74HCT14", **{"1A": "KCLK", "1Y": "KCLKS", "2A": "KDATA",
                                             "2Y": "KDATS", "3A": "MSCLK", "3Y": "MSCLKS",
                                             "4A": "MSDATA", "4Y": "MSDATS", "5A": "GND",
                                             "6A": "GND"})
    nl.add("pullup", "R_PS2", P1="KCLK", P2="KDATA", P3="MSCLK", P4="MSDATA")
    for port, clk, ck, dat, irq, a1 in (("KBD", "KCLK", "KCLKS", "KDATS", "KIRQ", 0),
                                        ("MOUSE", "MSCLK", "MSCLKS", "MSDATS", "MIRQ", 1)):
        sel = AND(lit("PS2CS"), lit("A1", a1), lit("A2", 0))
        clr = OR(AND(sel, lit("IOWR_n", 0)), lit("RESET_n", 0))
        done = lit(irq)
        held = [irq] + [f"MD{i}" for i in range(8)]
        outs = {}
        for i in range(9):
            above = lit(dat) if i == 8 else lit(held[i + 1], 0)
            if i == 0:
                outs[irq] = (OR(AND(done, lit(irq)), AND(lit(irq, 0), lit(held[1], 0))), True,
                             False)
            else:
                outs[held[i]] = (OR(AND(done, lit(held[i], 0)), AND(lit(irq, 0), above)), True,
                                 True, AND(sel, lit("IORD_n", 0)))
        G.add(nl, f"U_{port}", outs, clock=ck, ar=clr)
        p, s = f"{port}_P", f"{port}_S"
        rsel = AND(lit("PS2CS"), lit("A2"), lit("A1", a1), lit("IORD_n", 0))
        G.add(nl, f"U_{port}F", {
            p: (OR(lit(p), done), True, False),
            s: (OR(lit(s), AND(done, lit(p))), True, False),
            f"{port}_FERR": (OR(lit(f"{port}_FERR"), AND(done, lit(p), lit(s, 0), lit(dat))),
                             True, False),
            clk: (ZERO, False, False, lit(s)),              # holds the device off
            "MD3": (lit(f"{port}_FERR"), False, False, rsel),
        }, clock=ck, ar=clr)
        wsel = AND(lit("PS2CS"), lit("A2"), lit("A1", a1))
        outs = {}
        for i, (ln, bit) in enumerate(((clk, "MD0"), (dat, "MD1"))):
            q = f"{ln}_PULL"
            outs[q] = (OR(AND(wsel, lit(bit)), AND(negate(wsel), lit(q))), True, False)
            line = clk if i == 0 else ("KDATA" if port == "KBD" else "MSDATA")
            outs[line] = (ZERO, False, False, lit(q))
        outs["MD0"] = (lit(ck, 0), False, False, AND(wsel, lit("IORD_n", 0)))
        outs["MD1"] = (lit(dat, 0), False, False, AND(wsel, lit("IORD_n", 0)))
        outs["MD2"] = (lit(irq), False, False, AND(wsel, lit("IORD_n", 0)))
        G.add(nl, f"U_{port}C", outs, clock="IOWR_n", ar=lit("RESET_n", 0))


DEBUG = [
    ["STEP0", "STEP1", "STEP2", "STEP3", "STEP4"] + [f"OP{i}" for i in range(8)]
    + ["PAGE0", "PAGE1", "CLK0"],
    [f"N{i}" for i in range(4)] + ["HALF", "PHW"] + [f"F_{f}" for f in ("N", "Z", "C", "V", "I",
                                                                        "IC", "ST")]
    + ["IRQP", "LDIR", "HLTQ"],
    [f"D{i}" for i in range(16)],
]


def debug(nl):
    for h, sigs in enumerate(DEBUG):
        for k in range(2):
            nl.add("rser8", f"R_LA{h}{k}", **{f"A{i}": sigs[8 * k + i] for i in range(8)},
                   **{f"B{i}": f"LA{h}_{8 * k + i}" for i in range(8)}, part="100 ohm x 8")
        nl.add("hdr32", f"J_LA{h}", **{f"S{i}": f"LA{h}_{i}" for i in range(16)})
    nl.add("conn", "S_RUN", P0="RUN_n", P1="STEP_n", part="run/step switch and step button")


def odt(nl):
    """ODT's hooks (the console monitor in microcode, on UART 0): U_ODT
    latches the halt button (an SPDT's two contacts) and holds TRACE, both
    requests the I flag doesn't mask (ODTREQ, to U_SYS's IRQP): the halt
    button's until ODT clears it, TRACE's once the instruction after the
    write that sets it has run (U_SYS ORs them into IRQP). At the interrupt controller's +4, MD15-8
    read 0x90 when ODT is asked for (OP 00, N 9 once loaded with
    MOP_LDIRM: ODT's blocks), 0 otherwise; a write there sets TRACE from MD0
    and clears the halt button's latch."""
    wr = AND(lit("IRQCS"), lit("A2"), lit("IOWR_n", 0))
    rd = AND(lit("IRQCS"), lit("A2"), lit("IORD_n", 0))
    outs = {
        "HLTQ": (OR(lit("HLTA_n", 0), AND(lit("HLTQ"), lit("HLTB_n", 0), negate(wr))), False,
                 False),
        "TRACE": (OR(AND(wr, lit("MD0")), AND(negate(wr), lit("TRACE"))), False, False),
    }
    for i in range(8):
        outs[f"MD{8 + i}"] = (OR(lit("HLTQ"), lit("TRACE")) if i in (4, 7) else ZERO, False,
                              False, rd)
    G.add(nl, "U_ODT", outs)
    nl.add("conn", "S_HLT", P0="HLTA_n", P1="HLTB_n", part="push button (SPDT): halt to ODT")
