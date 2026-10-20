"""Device parts that the two-halves machine's netlist (board2.py) takes
from here: the chip types (_types) and part names (PARTS) of the UARTs
with their serial pins, the RAMDAC, the MAX232s, the headers, jumpers,
resistor networks and connectors; the PS/2 ports (ps2); a counter's next
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
    """Schmitt inputs, the receivers on the clock's falling edge (its inverse
    rising), and the frame GALs: P after the parity bit's edge, S after the
    stop bit's, FERR if the stop bit was 0. spare: the 74HCT14's
    other two inverters' pins."""
    nl.add("14", "U_PSS", part="74HCT14", **{"1A": "KCLK", "1Y": "KCLKS", "2A": "KDATA",
                                             "2Y": "KDATS", "3A": "MSCLK", "3Y": "MSCLKS",
                                             "4A": "MSDATA", "4Y": "MSDATS",
                                             **(spare or {"5A": "GND", "6A": "GND"})})
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
        G.add(nl, f"U_{port}F", {
            p: (OR(lit(p), done), True, False),
            s: (OR(lit(s), AND(done, lit(p))), True, False),
            f"{port}_FERR": (OR(lit(f"{port}_FERR"), AND(done, lit(p), lit(s, 0), lit(dat))),
                             True, False),
            # (holding the device off at S would have it send the byte again:
            # it looks at the clock after the stop bit; software can hold it
            # through the control register)
        }, clock=ck, ar=clr)
        # the control and status register, on ADS (a tick into any access
        # of the I/O space): the lines, the byte waiting and the framing
        # error sampled there, so that a read sees them steady (they change
        # with the device's clock); the pulls written from MD4-5
        wsel = AND(lit("PS2CS"), lit("A2"), lit("A1", a1))
        wr = AND(wsel, lit("IOWR_n", 0))
        rd = AND(wsel, lit("IORD_n", 0))
        outs = {}
        for i, (ln, bit) in enumerate(((clk, "MD4"), (dat, "MD5"))):
            q = f"{ln}_PULL"
            outs[q] = (OR(AND(wr, lit(bit)), AND(negate(wr), lit(q))), True, False)
            line = clk if i == 0 else ("KDATA" if port == "KBD" else "MSDATA")
            outs[line] = (ZERO, False, False, lit(q))
        outs["MD0"] = (lit(ck, 0), True, False, rd)
        outs["MD1"] = (lit(dat, 0), True, False, rd)
        outs["MD2"] = (lit(irq), True, False, rd)
        outs["MD3"] = (lit(f"{port}_FERR"), True, False, rd)
        G.add(nl, f"U_{port}C", outs, clock="ADS", ar=lit("RESET_n", 0)).nocheck = True

