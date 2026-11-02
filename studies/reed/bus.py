"""Reed's backplane: what crosses between boards, and who drives it.

Every board has two DIN 41612 connectors of 96 pins (P1, P2). P1 carries
the buses, each signal beside a ground in row b; P2 the 64 control lines,
the clocks with grounds between them, and the supply.

  A0-A31     the A bus: addresses and results
  B0-B31     the B bus: data, constants, instructions
  control    one driver each (CONTROL): the board named drives it, every
             other board only reads it

A board's netlist names these nets as they are here; system.py joins the
boards by name.
"""

A = [f"A{i}" for i in range(32)]
B = [f"B{i}" for i in range(32)]


def bus(name, n, start=0):
    return [f"{name}{i}" for i in range(start, start + n)]


UPC = bus("UPC", 14)
OP = bus("OP", 8)
RD, RS, RX = bus("RD", 4), bus("RS", 4), bus("RX", 4)
SZ = bus("SZ", 2)

# {line: (driver board, what it is)}
CONTROL = {
    **{n: ("CTRL", "clock") for n in ("MCLK", "MCLKN", "CYC", "WPH", "WRS")},
    **{n: ("CTRL", "the microprogram address") for n in UPC},
    **{n: ("CTRL", "the executing instruction's opcode") for n in OP},
    **{n: ("CTRL", "its register numbers d, s and x") for n in RD + RS + RX},
    "FETCH": ("CTRL", "the queue wants a word, and B is free this cycle"),
    **{n: ("ALU", "flags") for n in ("FN", "FZ", "FC", "FV", "FST")},
    "QIN": ("ALU", "the bit MQ shifts in (the last result's bit 0)"),
    "AERR": ("MEM", "address error: the access is misaligned"),
    "ALE": ("MEM", "MAR loads from A at this cycle's end: the I/O boards latch A too"),
    "IORD_n": ("MEM", "a read in the I/O space this cycle"),
    "IOWR_n": ("MEM", "a write in the I/O space this cycle"),
    **{n: ("MEM", "the access's size: byte, half, word") for n in SZ},
    "MQ0": ("MEM", "MQ's bit 0"),
    "RESET_n": ("IO", "reset (the TL7705A)"),
    "IRQ": ("IO", "an interrupt is pending"),
    "WAIT_IO": ("IO", "hold the cycle: a slow device"),
    "WAIT_V": ("VIDEO", "hold the cycle: the frame buffer is busy"),
    "VIRQ": ("VIDEO", "the frame's interrupt, to the interrupt controller"),
}
CLOCKS = ("MCLK", "MCLKN", "CYC", "WPH", "WRS")
BOARDS = ("CTRL", "ALU", "MEM", "IO", "VIDEO")


def pin_map():
    """{connector: {pin: net}}: P1 the buses (A in row a, B in row c,
    grounds in row b), P2 the control lines in rows a and c, row b grounds
    and the supply (every fourth pin 5 V), the clocks with grounds on both
    sides in their row too."""
    p1 = {}
    for i in range(32):
        p1[f"a{i + 1}"] = A[i]
        p1[f"b{i + 1}"] = "GND"
        p1[f"c{i + 1}"] = B[i]
    p2 = {f"b{i + 1}": ("VCC" if i % 4 == 3 else "GND") for i in range(32)}
    lines = [n for n in CONTROL if n not in CLOCKS]
    # the clocks in row a at 1, 3, 5, 7, 9, a ground between each and the next
    # (and row b's beside each)
    slots = [f"a{i}" for i in range(1, 33)] + [f"c{i}" for i in range(1, 33)]
    for k, clk in enumerate(CLOCKS):
        p2[f"a{1 + 2 * k}"] = clk
        p2[f"a{2 + 2 * k}"] = "GND"
    free = [s for s in slots if s not in p2]
    if len(lines) > len(free):
        raise ValueError(f"{len(lines)} control lines, {len(free)} pins")
    for s, n in zip(free, lines):
        p2[s] = n
    for s in free[len(lines):]:
        p2[s] = None
    return {"P1": p1, "P2": p2}


def connectors(nl):
    """A board's two connectors, every pin on its net (spares on nets of
    their own)."""
    for ref, pins in pin_map().items():
        conn = {}
        for pin, net in pins.items():
            conn[pin] = net if net else f"NC_{ref}_{pin}"
        nl.add("din96", f"J_{ref}", part="DIN 41612 96-pin", **conn)
