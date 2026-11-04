"""The VIDEO board: a 2 MB frame buffer of its own, 640 x 480 at 8 bits a
pixel through a palette, VGA's timing from the master clock (a pixel two
ticks: 25.175 MHz).

The CPU's side. This board's part of the I/O space is A29 set: A28 clear
the frame buffer (a word at a time: A20-A2), A28 set its registers (A11-A10:
0 the palette, an entry a word, its index A9-A2; 1 the control register,
whose write acknowledges the frame's interrupt). U_VA latches the address
when MEM's MAR does (ALE, VALEK); U_VDEC decodes it then. A write's data
(on A, a store's) goes into U_VD at the cycle's end and is written in the
next free slot (posted: PW); a write while one is pending holds the cycle
(WAIT_V). A read holds the cycle until a slot has read the word into U_VR
(573 latches), which drive B for the rest of the access.

The frame buffer's slots, by the tick in a 4-pixel word (H2-H0): ticks 7
and 0 the scan's (U_SA's address; the word clocked into U_PX as tick 0
starts, then a byte a pixel onto PIX through U_PXS, a 74F138 on H2-H1),
the rest the CPU's. Some of the slot timing is open: the analysis has no
case for the video's own phase yet.
"""

from heron.infra.hw import gal as G
from heron.infra.hw.netlist import Netlist

from . import bus as BP
from .common import AND, OR, ONE, ZERO, anyof, bus, clock_buffer, eq, gated_clock, lit, negate, table

H, V, SA = bus("H", 12), bus("V", 12), bus("SA", 20)
FBA, FD, VAQ = bus("FBA", 19), bus("FD", 32), bus("VA", 24)
PIX, RR, GG, BB = bus("PIX", 8), bus("PR", 8), bus("PG", 8), bus("PB", 8)
HTOTAL, VTOTAL = 1600, 525


def build(sim=True):
    nl = Netlist()
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")
    vk = clock_buffer(nl, ref="U_CKV", src="MCLK", prefix="VK")
    nl.section("timing")
    timing(nl, vk)
    nl.section("frame buffer")
    frame_buffer(nl, vk)
    nl.section("pixels and palette")
    pixels(nl, vk)
    BP.connectors(nl)
    nl.finish()
    return nl


def counter(nl, prefix, q, clk, enp, clr):
    for k in range(len(q) // 4):
        nl.add("163", f"U_{prefix}{k}", CLK=clk, CLR=clr, LOAD="VCC", ENP=enp,
               ENT="VCC" if k == 0 else f"{prefix}RC{k - 1}",
               A="GND", B="GND", C="GND", D="GND",
               QA=q[4 * k], QB=q[4 * k + 1], QC=q[4 * k + 2], QD=q[4 * k + 3], RCO=f"{prefix}RC{k}")


def timing(nl, vk):
    counter(nl, "HC", H, vk[0], "VCC", "HCLR_n")
    counter(nl, "VC", V, vk[0], "HEND", "VCLR_n")
    h = H[:11]

    def at(n):
        return eq(h, n)
    # U_VT1: the line: sync, the active part, its end; the scan's clock into U_PX
    outs = {
        "HSYNC_n": (OR(at(1311), AND(lit("HSYNC_n", 0), negate(at(1503)))), True, True),
        "HACT": (OR(at(HTOTAL - 1), AND(lit("HACT"), negate(at(1279)))), True, False),
        "HEND": (at(HTOTAL - 1), False, False),
        "HCLR_n": (at(HTOTAL - 1), False, True),
    }
    gated_clock(outs, "PXCK", AND(eq(H[:3], 7), lit("HACT"), lit("VACT")), clk=vk[1], wph=None)
    G.add(nl, "U_VT1", outs, clock=vk[2])
    v = V[:10]
    outs = {
        "VSYNC_n": (OR(AND(lit("HEND"), eq(v, 489)), AND(lit("VSYNC_n", 0), negate(AND(lit("HEND"), eq(v, 491))))),
                    True, True),
        "VACT": (OR(AND(lit("HEND"), eq(v, VTOTAL - 1)), AND(lit("VACT"), negate(AND(lit("HEND"), eq(v, 479))))),
                 True, False),
        "VIRQ": (AND(lit("VACK", 0), OR(AND(lit("HEND"), eq(v, 479)), lit("VIRQ"))), True, False),
        "VCLR_n": (AND(lit("HEND"), eq(v, VTOTAL - 1)), False, True),
    }
    G.add(nl, "U_VT2", outs, clock=vk[2])


def frame_buffer(nl, vk):
    # the scan's address, a word per four pixels, from 0 each frame
    counter(nl, "SA", SA, vk[0], "VSTEP", "VCLR_n")
    for k in range(3):
        n = min(8, 19 - 8 * k)
        nl.add("541", f"U_SAD{k}", OE1="VSLOT_n", OE2="GND",
               **{f"A{i + 1}": SA[8 * k + i] if i < n else "GND" for i in range(8)},
               **{f"Y{i + 1}": FBA[8 * k + i] if i < n else f"SAD_NC{k}{i}" for i in range(8)})
        nl.add("574", f"U_VA{k}", OE="CSLOT_n", CLK="VALEK",
               **{f"D{i + 1}": BP.A[2 + 8 * k + i] for i in range(8)},
               **{f"Q{i + 1}": (FBA[8 * k + i] if 8 * k + i < 19 else VAQ[8 * k + i]) for i in range(8)})
    for lane in range(4):
        nl.add("sram512", f"U_FB{lane}", role="fastram", CE="GND", OE="FBOE_n", WE="FBWE_n",
               **{f"A{i}": FBA[i] for i in range(19)}, **{f"IO{i}": FD[8 * lane + i] for i in range(8)})
        nl.add("574", f"U_VD{lane}", OE="VDOE_n", CLK="VWK",
               **{f"D{i + 1}": BP.A[8 * lane + i] for i in range(8)},
               **{f"Q{i + 1}": FD[8 * lane + i] for i in range(8)})
        nl.add("573", f"U_VR{lane}", OE="VBOE_n", LE="VRLE",
               **{f"D{i + 1}": FD[8 * lane + i] for i in range(8)},
               **{f"Q{i + 1}": BP.B[8 * lane + i] for i in range(8)})
    # U_VDEC, at VALEK: which of this board's parts the access is
    a = BP.A
    mine = AND(lit(a[30]), lit(a[29]))
    G.add(nl, "U_VDEC", {
        "VSELFB": (AND(mine, lit(a[28], 0)), True, False),
        "VSELPAL": (AND(mine, lit(a[28]), lit(a[11], 0), lit(a[10], 0)), True, False),
        "VSELCTL": (AND(mine, lit(a[28]), lit(a[11], 0), lit(a[10])), True, False),
    }, clock="VALEK")
    # U_VAR2, on MCLK: the CPU's side: the gated clocks, the pending write, the waits
    rd = AND(lit("IORD_n", 0), lit("VSELFB"))
    wr = AND(lit("IOWR_n", 0), OR(lit("VSELFB"), lit("VSELPAL")))
    outs = {}
    # (clearing a tick in, which races CYC's rise: open, as the board
    # isn't timed yet and U_VAR2 has no room for the later clear)
    gated_clock(outs, "VALEK", lit("ALE"), clk="CYC", late=False)
    gated_clock(outs, "VWK", wr, clk="CYC", late=False)
    outs.update({
        # pending from the edge VD took the data at (VWK), until written
        "PW": (AND(lit("RESET_n"), OR(AND(lit("ARM_VWK"), lit("CYC")), AND(lit("PW"), lit("WDONE", 0)))),
               True, False),
        "RDP": (AND(rd, OR(lit("RDP"), lit("RDONE", 0))), True, False),
        "WAIT_V": (OR(AND(wr, lit("PW")), AND(rd, lit("RDP", 0))), False, False),
        "VBOE_n": (AND(rd, lit("CYC", 0)), False, True),
        "VACK": (AND(lit("IOWR_n", 0), lit("VSELCTL")), False, False),
    })
    G.add(nl, "U_VAR2", outs, clock=vk[3])
    # U_VAR1, on MCLK: the slots: the scan's at ticks 7 and 0 while a line
    # is shown; else a pending write (two ticks: WE in the second) or a read
    scan = AND(lit("HACT"), lit("VACT"), OR(eq(H[:3], 6), eq(H[:3], 7)))
    cpu = negate(scan)
    outs = {
        "VSLOT_n": (scan, True, True),
        "CSLOT_n": (AND(cpu, OR(lit("PW"), AND(lit("IORD_n", 0), lit("VSELFB")))), True, True),
        "WPH1": (AND(cpu, lit("PW"), lit("WPH1", 0), lit("WDONE", 0)), True, False),
        "WDONE": (AND(lit("PW"), OR(lit("WPH1"), lit("WDONE"))), True, False),
        "FBWE_n": (AND(lit("WPH1"), lit("VSELFB")), True, True),
        "VDOE_n": (AND(cpu, lit("PW")), True, True),
        "FBOE_n": (OR(scan, AND(cpu, lit("PW", 0))), True, True),
        "VRLE": (AND(cpu, lit("PW", 0), lit("IORD_n", 0), lit("VSELFB")), True, False),
        "RDONE": (AND(lit("IORD_n", 0), OR(lit("VRLE"), lit("RDONE"))), True, False),
        "VSTEP": (AND(lit("HACT"), lit("VACT"), eq(H[:3], 7)), False, False),
    }
    G.add(nl, "U_VAR1", outs, clock=vk[4])


def pixels(nl, vk):
    for k in range(4):
        nl.add("574", f"U_PX{k}", OE=f"PXOE{k}_n", CLK="PXCK",
               **{f"D{i + 1}": FD[8 * k + i] for i in range(8)}, **{f"Q{i + 1}": PIX[i] for i in range(8)})
    # a byte a pixel (two ticks), by H2-H1; none during a palette write
    nl.add("138", "U_PXS", A=H[1], B=H[2], C="GND", G1="VCC", G2A="PALW", G2B="GND",
           **{f"Y{i}": f"PXOE{i}_n" if i < 4 else f"PXS_NC{i}" for i in range(8)})
    # the palette: an entry's index from the latched address (A9-A2, on FBA
    # while the CPU's slot writes it), its
    # colours from the posted data (FD: B7-B0 red, B15-B8 green, B23-B16 blue)
    nl.add("541", f"U_PIXI", OE1="PALW_n", OE2="GND",
           **{f"A{i + 1}": FBA[i] for i in range(8)},
           **{f"Y{i + 1}": PIX[i] for i in range(8)})
    for k, col in enumerate((RR, GG, BB)):
        nl.add("sram", f"U_PAL{k}", CE="GND", OE="PALW", WE="PALWE_n",
               **{f"A{i}": PIX[i] if i < 8 else "GND" for i in range(15)},
               **{f"IO{i}": col[i] for i in range(8)})
        nl.add("541", f"U_PALD{k}", OE1="PALW_n", OE2="GND",
               **{f"A{i + 1}": FD[8 * k + i] for i in range(8)}, **{f"Y{i + 1}": col[i] for i in range(8)})
    G.add(nl, "U_PALC", {
        "PALW": (AND(lit("PW"), lit("VSELPAL")), False, False),
        "PALW_n": (AND(lit("PW"), lit("VSELPAL")), False, True),
        "PALWE_n": (AND(lit("PW"), lit("VSELPAL"), lit("WPH1")), False, True),
        "BLANK_n": (AND(lit("HACT"), lit("VACT")), False, False),
    })
    nl.add("adv7125", "U_DAC", **{f"R{i}": RR[i] for i in range(8)}, **{f"G{i}": GG[i] for i in range(8)},
           **{f"B{i}": BB[i] for i in range(8)}, CLK=H[0], BLANK="BLANK_n", SYNC="GND",
           IOR="VGA_R", IOG="VGA_G", IOB="VGA_B")
    nl.add("conn", "J_VGA", part="DE-15 (VGA)", P0="VGA_R", P1="VGA_G", P2="VGA_B", P3="HSYNC_n",
           P4="VSYNC_n", P5="GND", P6="GND", P7="GND")
