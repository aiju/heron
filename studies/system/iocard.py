"""The I/O card: a simple card (RFC 0014 section 6) with a 16C550 UART,
an 82C54 timer and a CompactFlash card. See design.md.

Its registers, as offsets in its slot (decoded from A2-A8 only, so they
repeat through the slot; in slot 15 the top 256 bytes, 0xFFFFFF00 up, are
reachable with a sign-extended 16-bit absolute address):

  0x40 + 4n  CF control block (CS1): 0x58 alternate status / device control
  0x80 + 4n  CF task file (CS0), registers 0-7
  0xC0 + 4n  UART registers 0-7
  0xE0 + 4n  timer: counters 0-2, control word at 0xEC
  0x...EE0   (A8 = 0) timer interrupt acknowledge: any write
  any read   the card's ID in bits 8-15

The UART's interrupt is IRQ0, the CF card's IRQ1, the timer's IRQ2: the
timer's OUT0 rising sets a flag that drives IRQ2 until acknowledged.
"""

from heron.infra.hw.netlist import Netlist

from . import bus

HCT, ACT = "74HCT", "74ACT"
CARD_ID = 0x10
UART_HZ = 14_745_600                   # 8 x 1.8432 MHz: 921600 baud at divisor 1
TIMER_HZ = 1_000_000                   # the 82C54 counts microseconds


def build(card_id=CARD_ID, cf_sectors=2048):
    nl = Netlist()
    g = nl.gate
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")
    bus.strap_class(nl, "simple")

    def gh(typ, ins, out):
        return g(typ, ins, out, part=HCT + typ)

    # the strobes: one Schmitt NAND from SEL (RFC 0014 section 6)
    gh("132", ["BUS.WRITE_n", "VCC"], "WRT")
    gh("132", ["BUS.SEL", "BUS.WRITE_n"], "RD_n")
    gh("132", ["BUS.SEL", "WRT"], "WR_n")
    gh("14", ["BUS.RESET_n"], "RSTP")
    gh("14", ["RSTP"], "RSTN")
    gh("14", ["WR_n"], "WRS")
    # data: D0-D7 through one transceiver, the ID on D8-D15 in any read
    gh("08", ["RD_n", "WR_n"], "XOE_n")
    x = nl.add("245", "U_X", part=HCT + "245", DIR="WR_n", OE="XOE_n")
    for i in range(8):
        x[f"A{i + 1}"], x[f"B{i + 1}"] = f"CD{i}", f"BUS.D{i}"
    b = nl.add("541", "U_ID", part=HCT + "541", OE1="RD_n", OE2="GND")
    for i in range(8):
        b[f"A{i + 1}"] = "VCC" if (card_id >> i) & 1 else "GND"
        b[f"Y{i + 1}"] = f"BUS.D{8 + i}"
    # the UART decodes its own select (A7, A6, not A5)
    nl.add("osc", "U_UOSC", part=f"oscillator {UART_HZ / 1e6:g} MHz", OUT="UCLK",
           params={"period_ps": round(1e12 / UART_HZ)})
    u = nl.add("16c550", "U_UART", CS0="BUS.A7", CS1="BUS.A6", CS2="BUS.A5", RD="RD_n",
               WR="WR_n", MR="RSTP", XIN="UCLK", INTR="UINTR")
    for i in range(3):
        u[f"A{i}"] = f"BUS.A{i + 2}"
    for i in range(8):
        u[f"D{i}"] = f"CD{i}"
    # the CF card: CS0 is A6 low, CS1 A7 low
    cf = nl.add("cf", "U_CF", CS0="BUS.A6", CS1="BUS.A7", IORD="RD_n", IOWR="WR_n",
                RESET="RSTN", INTRQ="CFINT", WAKE="CF_WAKE", params={"sectors": cf_sectors})
    for i in range(3):
        cf[f"A{i}"] = f"BUS.A{i + 2}"
    for i in range(8):
        cf[f"D{i}"] = f"CD{i}"
    # the timer at A7 A6 A5 and A8; its acknowledge with A8 low
    g("11", ["BUS.A7", "BUS.A6", "BUS.A5"], "T765", part=ACT + "11")
    g("00", ["T765", "BUS.A8"], "TCS_n", part=ACT + "00")
    gh("04", ["BUS.A8"], "A8_n")
    gh("10", ["T765", "A8_n", "WRS"], "TACK_n")
    gh("08", ["TACK_n", "RSTN"], "TCLR_n")
    nl.add("osc", "U_TOSC", part=f"oscillator {TIMER_HZ / 1e6:g} MHz", OUT="TCLK",
           params={"period_ps": round(1e12 / TIMER_HZ)})
    t = nl.add("82c54", "U_TMR", A0="BUS.A2", A1="BUS.A3", CS="TCS_n", RD="RD_n", WR="WR_n",
               OUT0="TOUT0", **{f"CLK{i}": "TCLK" for i in range(3)},
               **{f"GATE{i}": "VCC" for i in range(3)})
    for i in range(8):
        t[f"D{i}"] = f"CD{i}"
    nl.add("74", "U_TFF", part=HCT + "74",
           **{"1D": "VCC", "1CLK": "TOUT0", "1PRE": "VCC", "1CLR": "TCLR_n", "1Q": "TFLAG",
              "2D": "GND", "2CLK": "GND", "2PRE": "VCC", "2CLR": "VCC"})
    # interrupts: open collector
    gh("05", ["UINTR"], "BUS.IRQ0_n")
    gh("05", ["CFINT"], "BUS.IRQ1_n")
    gh("05", ["TFLAG"], "BUS.IRQ2_n")

    nl.finish()
    return bus.Card("IO", nl)
