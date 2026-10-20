"""Device parts that the two-halves machine's netlist (board2.py) takes
from here: the chip types (_types) and part names (PARTS) of the UARTs
with their serial pins, the RAMDAC, the MAX232s, the headers, jumpers,
resistor networks and connectors; the PS/2 ports' (ps2); a counter's next
bit (_inc). (The draft netlist that first had them, the first cut's
two-halves variant, is gone: board2.py replaced it.)
"""

from heron.infra.hw import chips, gal as G

from .board import AND, OR, ONE, ZERO, lit, negate

T = chips.T


def _types():
    if "16c550x" in chips.TYPES:
        return
    T("16c550x", "uart16550",
      [(f"D{i}", "io") for i in range(8)] + [(f"A{i}", "in") for i in range(3)]
      + [(p, "in") for p in ("CS0", "CS1", "CS2", "RD", "WR", "MR", "XIN", "SIN", "CTS", "ADS")]
      + [(p, "out") for p in ("INTR", "SOUT", "RTS", "DTR", "OUT1", "OUT2")],
      arcs=[(["RD"], [f"D{i}" for i in range(8)], "RD->D")], family="device",
      desc="TL16C550C with its serial pins (the draft netlist's)")
    T("g171", "passive",
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



def _inc(w, i):
    """Bit i of W + 1."""
    lower = w[:i]
    return OR(AND(lit(w[i], 1), OR(*[lit(b, 0) for b in lower])) if lower else ZERO,
              AND(lit(w[i], 0), [{b: 1 for b in lower}] if lower else ONE))



def ps2(nl, spare=None):
    """The PS/2 ports: Schmitt inputs (a 74HCT14, inverting) and a GAL a
    port on the master clock, for the device task (routines2.device) to
    receive the frames in microcode: S1 and S2 the clock synchronised, E an
    edge (the clock's fall) the task hasn't taken, cleared by a write at
    the port's +0 (the keyboard) or +2 (the mouse); the port's interrupt
    (KIRQ, MIRQ), written at +4 or +6 from MD3, and the lines' pulls from
    MD4 (the clock) and MD5 (the data), each a register driving its line
    low. A read at +0 or +2: MD0 the data line, MD1 E; the mouse's MD2 is
    SREQ, the PCM's request. The keyboard's GAL synchronises the timer's
    OUT1 for U_LCK too (TS). spare: the 74HCT14's other two inverters' pins."""
    nl.add("14", "U_PSS", part="74HCT14", **{"1A": "KCLK", "1Y": "KCLKS", "2A": "KDATA",
                                             "2Y": "KDATS", "3A": "MSCLK", "3Y": "MSCLKS",
                                             "4A": "MSDATA", "4Y": "MSDATS",
                                             **(spare or {"5A": "GND", "6A": "GND"})})
    nl.add("pullup", "R_PS2", P1="KCLK", P2="KDATA", P3="MSCLK", P4="MSDATA")
    for port, clk, data, ck, dat, irq, a1 in (
            ("KBD", "KCLK", "KDATA", "KCLKS", "KDATS", "KIRQ", 0),
            ("MOUSE", "MSCLK", "MSDATA", "MSCLKS", "MSDATS", "MIRQ", 1)):
        s1, s2, e = f"{port}_S1", f"{port}_S2", f"{port}_E"
        dsel = AND(lit("PS2CS"), lit("A2", 0), lit("A1", a1))
        csel = AND(lit("PS2CS"), lit("A2"), lit("A1", a1))
        wr_d, wr_c = AND(dsel, lit("IOWR_n", 0)), AND(csel, lit("IOWR_n", 0))
        rd = AND(dsel, lit("IORD_n", 0))
        outs = {s1: (lit(ck), True, False), s2: (lit(s1), True, False),
                e: (OR(AND(lit(s1), lit(s2, 0)), AND(lit(e), negate(wr_d))), True, False),
                irq: (OR(AND(wr_c, lit("MD3")), AND(negate(wr_c), lit(irq))), True, False),
                "MD0": (lit(dat, 0), False, False, rd),
                "MD1": (lit(e), False, False, rd)}
        # a pull: its register's state is the pin's (low while it pulls)
        for line, bit in ((clk, "MD4"), (data, "MD5")):
            outs[line] = (OR(AND(wr_c, lit(bit)), AND(negate(wr_c), lit(line, 0))), True, True,
                          lit(line, 0))
        if a1:
            outs["MD2"] = (lit("SREQ"), False, False, rd)
        else:
            outs["TS"] = (lit("TOUT1"), True, False)
        G.add(nl, f"U_{port}", outs, clock="MCLK", ar=lit("RESET_n", 0)).nocheck = True
