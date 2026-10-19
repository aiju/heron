"""Chip-level netlist of Heron Mini (RFC 0041): the CPU, its control
store, the 4 MB of RAM in two banks (bank 1 the video's), the I/O space
with its devices, and the video.

build(sim=True) is what the chip-level simulator runs (infra/hwsim's
system run): it has the clock generator (a 50.35 MHz oscillator and a
tick counter, the length classes from the uIR, the I/O hold), a power-on
reset, the devices (io_space) and the video (video). build() has a
fixture in place of the clock generator, and leaves out the I/O space and
the video's own chips, for static timing analysis.

The control store and the boot ROM are flash preloaded with the
microcode and the boot image.

Buses
  ABUS   ALU A input   <- register file copy A (through its latches), PC
                          (bit 0 from PCK), R, R x 2 (+ SINA)
  BBUS   ALU B input   <- register file copy B (latches), R, T by byte
                          lane, QH (4 ways), the immediate unit, MQ, the
                          flags
  F      ALU output (74F181 x 8, 74F182 x 3)
  RES    result bus = F through the shift/rotate multiplexer (74F153 x 16)
  VA     the address <- MAR, FPC, the A bus (74F153 x 13: bits 21-0 and 31-28)
  DB     32-bit memory data <- RAM, the I/O space, store data from the A bus
  QH     the prefetch queue's head parcel
  VD     bank 1's data, to DB through transceivers; B1A its address
  IOD    the devices' 16-bit data bus, IOA their latched address

Clocking. A cycle of K ticks (19.86 ns) runs H0, H1, the count, then the
tail ticks T1 and T2; CLK rises entering H0. The register file is read
early (its latches transparent) and written late: RW is high for the two
tail ticks (the latches hold, the SRAM's address switches to the write
address, its outputs turn off) and the write strobe is T2, the last tick.
An access to the I/O space holds the count at H3 for 16 - 2r ticks
(region r, VA30-28), the devices' strobe from the hold's second tick to
T2. A misaligned data access (FAULT) writes nothing, strobes nothing,
changes no register or flag, keeps its decode or jump from the IR and
the PC, and forces the address error's entry. The video owns bank 1 in
each cycle's T2 and the next H0, and in a hold: a read's data is latched
into T, or a fetch's into its queue slot, before them, and the memory
write window MWIN is open from tick 2 to the tail.

See rtl.py for the register-transfer model this netlist implements, and
ucode.py for the fields.
"""

from heron.infra.hw import gal
from heron.infra.hw.gal import lit
from heron.infra.hw.netlist import Netlist

from . import parts, ucode as uc
from .timing import HEAD, TAIL

TICK_PS = 19_861


def sop(nets, f):
    """A sum of products over nets (LSB first), true where f(bits) is."""
    n = len(nets)
    return gal.when(nets, [c for c in range(1 << n)
                           if f(*[(c >> i) & 1 for i in range(n)])], range(1 << n))


def bus(name, n, start=0):
    return [f"{name}{i}" for i in range(start, start + n)]


def control_nets():
    """Control word bit -> uIR output net (with _n for active-low fields)."""
    nets = {}
    for name, (bit, w, al) in uc._pos.items():
        for i in range(w):
            nets[bit + i] = f"u{name}{i if w > 1 else ''}{'_n' if al >> i & 1 else ''}"
    return nets


UART_HZ = 1_843_200          # the UARTs' and the timer's clock
# the simulations' PS/2 devices: a 16.7 kHz clock, a byte every 0.2 ms
# from 1 ms after power-up
PS2_PARAMS = {"half_ps": 30_000_000, "gap_ps": 200_000_000, "start_ps": 1_000_000_000}
CF_SECTORS = 256             # the simulations' CF card: 128K


# the video timing ROM's bits, registered at each character's end
TIMING_BITS = ["HSYNCQ", "VSYNCQ", "DEQR", "SHLDQ", "EV0", "EV1", "EV2", "FENDQ"]


def preload(k):
    """The tick counter's preload for a cycle of k ticks."""
    p = HEAD + 16 + TAIL - k
    if not 0 <= p <= 15:
        raise ValueError(f"a cycle of {k} ticks is out of range")
    return p


# the clock chip's outputs (RFC 0041, 20): the master clock for VGA, for
# XGA, and the UARTs' and the timer's
XGA_TICK_PS = 15_385          # 65 MHz: XGA's pixel clock


def clock_generator(nl, lengths, xlengths, por_ps):
    """RFC 0024's clock generator for short cycles, with two tail ticks:
    H0 and H1, the count from the preload to 15, T1 and T2. The length
    class from the uIR's LCL field. RW, the register file's write phase
    and the video's, is T1 or T2; the write strobe T2. The master clock
    (MCLK) is the clock chip's 50.35 MHz, or its 65 MHz while the video
    shows an XGA mode (RFC 0042), through a switch that never makes a short
    pulse; the length classes have a table for each (`lengths`,
    `xlengths`), the longer one in force before the clock speeds up and
    until after it slows down."""
    g = nl.gate
    nl.section("Reset")
    nl.add("por", "U_POR", RST="PORST_n", params={"release_ps": por_ps})
    nl.add("pullup", "RN_POR", P1="PORST_n", P4="DBGB_n")
    g("14", ["PORST_n"], "RSTI")
    g("14", ["RSTI"], "RSTA_n")
    # asserted at once, released at a CLK edge
    nl.add("74", "U_RSY", **{"1D": "VCC", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "RSTA_n",
                             "1Q": "RSY1", "2D": "RSY1", "2CLK": "CLK", "2PRE": "VCC",
                             "2CLR": "RSTA_n", "2Q": "RESET_n"})

    nl.section("Clock")
    # the clock chip, from its stored configuration: CLKA 50.35 MHz (VGA's
    # pixel clock twice) and CLKB 65 MHz (XGA's) from a PLL each, CLKC the
    # UARTs' and the timer's 1.8432 MHz, its 14.7456 MHz crystal / 8 (the
    # load capacitors are on the chip). Its serial port (SCLK, SDAT) is
    # for a programmer on a header: reprogramming it is open (RFC 0041,
    # 20). A 3.3 V part (Cypress 38-07186): its own regulator, decoupled,
    # and its inputs no higher, so the serial port's pull-ups and OE
    # (SHUTDOWN/OE, high: on) are on that rail. A blank part's outputs are
    # off: its flash is programmed beforehand
    nl.add("ldo33", "U_V33", OUT="V33")
    nl.add("capbulk", "C_V33", part="10 uF tantalum", A="V33", B="GND")
    nl.add("cap", "C_CLK1", part="100 nF", A="V33", B="GND")
    nl.add("cap", "C_CLK2", part="100 nF", A="V33", B="GND")
    nl.add("rpull", "R_CKSCL", part="4.7 kohm", A="CKSCL", R="V33")
    nl.add("rpull", "R_CKSDA", part="4.7 kohm", A="CKSDA", R="V33")
    nl.add("xtal", "Y_CLK", part="14.7456 MHz crystal", X1="CKXI", X2="CKXO")
    nl.add("cy22393", "U_CLK", CLKA="CLKA", CLKB="CLKB", CLKC="UCLK", SCLK="CKSCL",
           SDAT="CKSDA", S2="GND", OE="V33", XTALIN="CKXI", XTALOUT="CKXO", VDD="V33",
           AVDD="V33",
           params={"a_ps": TICK_PS, "a_phase": TICK_PS, "b_ps": XGA_TICK_PS,
                   "b_phase": XGA_TICK_PS + 3_000, "c_ps": round(1e12 / UART_HZ)})
    # the switch: each clock's enable from two flip-flops on its rising
    # edge (the first a synchroniser), set only once the other's is off
    # (CLKSEL, the video's, from the master clock); a disabled clock held
    # high, so an enable that changes just after a rising edge, while the
    # clock is high, makes no short pulse (74ABT74s: 4.7 ns, against XGA's
    # 7.7 ns half period). Cleared at power-on, then the VGA clock's
    nl.add("04", "U_CKN", **{"1A": "CLKSEL", "1Y": "CLKSEL_n", "2A": "GND", "3A": "GND",
                             "4A": "GND", "5A": "GND", "6A": "GND"})
    nl.add("08", "U_CKA", **{"1A": "CLKSEL_n", "1B": "ENB_n", "1Y": "ENA_D",
                             "2A": "CLKSEL", "2B": "ENA_n", "2Y": "ENB_D",
                             "3A": "MCKA", "3B": "MCKB", "3Y": "MCLK",
                             "4A": "GND", "4B": "GND"})
    nl.add("32", "U_CKO", **{"1A": "CLKA", "1B": "ENA_n", "1Y": "MCKA",
                             "2A": "CLKB", "2B": "ENB_n", "2Y": "MCKB",
                             "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    for side, d, en in (("A", "ENA_D", "ENA"), ("B", "ENB_D", "ENB")):
        nl.add("74", f"U_CKF{side}", part="74ABT74", nocheck=True,
               **{"1D": d, "1CLK": f"CLK{side}", "1PRE": "VCC", "1CLR": "RSTA_n",
                  "1Q": f"EN{side}1", "2D": f"EN{side}1", "2CLK": f"CLK{side}",
                  "2PRE": "VCC", "2CLR": "RSTA_n", "2Q": en, "2QN": f"{en}_n"})

    nl.section("Clock generator")
    # two 22V10s on the master clock. K1: the tick count TC, cleared at T2,
    # preloaded at H1 by the length class and XL, held in an I/O access's
    # hold, its carry TCRCO; T1 after the carry, T2 after T1, H0 after T2,
    # H1 after H0, and CLK, T2 or H0. The preloads are K1's equations, so
    # the length classes are its program: XGA's (`xlengths`) while the
    # video asks for its clock (FAM) or has it (ENB). XL: a parcel consumed
    # with the queue empty comes from the word the cycle fetches, which
    # takes two ticks more (rtl.DEMAND_HOLD). The video's steal (STRETCH,
    # two ticks) holds T2: the register file's strobe and the video's slot
    # longer, CLK's edge later. H0 never stays on two ticks, so a second
    # pulse dies whatever the registers powered up as
    from .rtl import DEMAND_HOLD
    pre = [preload(k) for k in lengths] + [preload(k + DEMAND_HOLD) for k in lengths]
    xpre = [preload(k) for k in xlengths] + [preload(k + DEMAND_HOLD) for k in xlengths]
    TC = bus("TC", 4)
    sel = ["uLCL0", "uLCL1", "uCONSUME", "V0", "FAM", "ENB"]
    k1 = {}
    for b in range(4):
        load = sop(sel, lambda l0, l1, c, v0, fam, enb: (xpre if fam or enb else pre)[
            l0 + 2 * l1 + 4 * (c & (1 - v0))] >> b & 1)
        carry = gal.AND(*[lit(TC[i]) for i in range(b)])
        count = gal.OR(gal.AND(lit(TC[b]), gal.OR(*[lit(TC[i], 0) for i in range(b)])),
                       gal.AND(lit(TC[b], 0), carry))
        k1[TC[b]] = (gal.AND(lit("T2", 0), gal.OR(
            gal.AND(lit("H1"), load),
            gal.AND(lit("H1", 0), lit("HOLD"), lit(TC[b])),
            gal.AND(lit("H1", 0), lit("HOLD", 0), count))), True, False)
    rco = gal.AND(*[lit(t) for t in TC], lit("HOLD", 0))
    k1["TCRCO"] = (rco, False, False)
    k1["T1"] = (rco, True, False)
    k1["T2"] = (gal.OR(lit("T1"), gal.AND(lit("T2"), lit("STRETCH"))), True, False)
    k1["H0"] = (gal.AND(lit("T2"), lit("H0", 0), lit("STRETCH", 0)), True, False)
    k1["H1"] = (lit("H0"), True, False)
    k1["CLK"] = (gal.OR(gal.AND(lit("T2"), lit("STRETCH", 0)), lit("H0")), True, False)
    gal.add(nl, "U_K1", k1, clock="MCLK")
    # K2: H2 and H3 after H1; the write window MID, from tick 2 until H0
    # (J = H1, K-bar = T2_n), and MWIN, MID outside the tail; RW, T1 or T2;
    # LATE from tick 2. The hold: the wait states of an access to the I/O
    # space, from tick 4 for 16 - 2r ticks, r the region (VA[30:28]): the
    # count stops, and its carry, which T1 waits for, is off (a data cycle
    # is 7 ticks or more, so the count is 15 or below). Tick 4, not 3: a
    # read at the A bus has its address from the register file, too late
    # for tick 3. The hold counter, loaded with 2r + 1 until HOLD rises,
    # counts to its carry, HEND registers that, and HOLD falls a tick
    # later. The I/O strobe: from the hold's second tick (J = HOLD) until
    # T2 (K-bar = T1_n), a tick after the read latches close
    rst = lit("RESET_n")
    rw = gal.OR(lit("T1"), lit("T2"))
    gal.add(nl, "U_K2", {
        "H2": (lit("H1"), True, False),
        "H3": (lit("H2"), True, False),
        "MID": (gal.OR(gal.AND(lit("H1"), lit("MID", 0)), gal.AND(lit("T2", 0), lit("MID"))),
                True, False),
        "IOSTB": (gal.AND(rst, gal.OR(gal.AND(lit("HOLD"), lit("IOSTB", 0)),
                                      gal.AND(lit("T1", 0), lit("IOSTB")))), True, False),
        "HOLD": (gal.AND(rst, gal.OR(gal.AND(lit("H3"), lit("IOACC")),
                                     gal.AND(lit("HOLD"), lit("HEND", 0)))), True, False),
        "HEND": (gal.AND(rst, lit("HCRCO")), True, False),
        "RW": (rw, False, False),
        "RW_n": (rw, False, True),
        "MWIN": (gal.AND(lit("MID"), lit("T1", 0), lit("T2", 0)), False, False),
        "LATE": (gal.AND(lit("H0", 0), lit("H1", 0)), False, False)}, clock="MCLK")
    nl.section("Hold")
    # the hold counter: a 22V10 (a 74ACT163's 15 ns to its carry is too
    # slow at 65 MHz), loaded with 2r + 1 while HOLD is low, counting while
    # it's high; HCRCO, its carry, at 15
    HCQ = bus("HCQ", 4)
    load_v = ["VCC", "VA28", "VA29", "VA30"]
    hc = {}
    for b in range(4):
        cnt = gal.OR(gal.AND(lit(HCQ[b]), gal.OR(*[lit(HCQ[i], 0) for i in range(b)])),
                     gal.AND(lit(HCQ[b], 0), *[lit(HCQ[i]) for i in range(b)]))
        ld = gal.ONE if b == 0 else lit(load_v[b])
        hc[HCQ[b]] = (gal.OR(gal.AND(lit("HOLD"), cnt), gal.AND(lit("HOLD", 0), ld)), True, False)
    hc["HCRCO"] = (gal.AND(lit("HOLD"), *[lit(q) for q in HCQ]), False, False)
    gal.add(nl, "U_HC", hc, clock="MCLK")
    nl.section("Clock generator")
    # the timer's interrupt flag, set as OUT0 rises, cleared by a write to
    # the interrupt status
    nl.add("74", "U_TH3", **{"1D": "GND", "1CLK": "GND", "1PRE": "VCC", "1CLR": "VCC",
                             "2D": "VCC", "2CLK": "TOUT0", "2PRE": "VCC", "2CLR": "TCLR_n",
                             "2Q": "TFLAG"})


def video_ram(nl, VA, DB, sim):
    """Bank 1 of the RAM, 0x0020_0000-0x003F_FFFF: the video's. Its own
    address (B1A) and data (VD): the CPU's through buffers, the video's in
    its slots (VSLOT: every cycle's T2 and the next one's H0, when the CPU
    doesn't use the RAM, and an I/O access's hold, when it doesn't use
    bank 1)."""
    g = nl.gate
    nl.section("Video RAM")
    for k in range(3):
        c = nl.add("541", f"U_B1C{k}", OE1="VSLOT", OE2="GND")
        for i in range(8):
            bit = 8 * k + i
            c[f"A{i + 1}"] = VA[2 + bit] if bit < 19 else "GND"
            if bit < 19:
                c[f"Y{i + 1}"] = f"B1A{bit}"
    # the bank is always enabled, its outputs on but in the CPU's writes
    # (outside the video's slots), so neither is on the CPU's read path:
    # onto the data bus through the transceivers when the CPU reads it,
    # written when the bank is chosen (B1OE_n, B1XOE_n and the write
    # enables B1WE_n from the memory's 22V10s)
    if sim:
        # the CPU's writes end within T1, before the video's slot switches
        # the address: the write strobe through fast copies of T1 and T2
        # (the other bank's ends a tick later, through four gates)
        nl.add("74", "U_T1F", **{"1D": "TCRCO", "1CLK": "MCLK", "1PRE": "VCC", "1CLR": "VCC",
                                 "1Q": "T1F", "2D": "T1F", "2CLK": "MCLK", "2PRE": "VCC",
                                 "2CLR": "VCC", "2Q": "T2F"})
        g("32", ["T1F", "T2F"], "RWF")
        # (MID lasts into H0: the video's ownership masks it there)
        g("08", ["MID", "VSLOT_n"], "MIDV")
    for k in range(4):
        x = nl.add("245", f"U_B1X{k}", DIR="MEMWR", OE="B1XOE_n")
        ram = nl.add("sram512", f"U_RAM1{k}", role="fastram", CE="GND", OE="B1OE_n",
                     WE=f"B1WE{k}_n")
        for i in range(19):
            ram[f"A{i}"] = f"B1A{i}"
        for i in range(8):
            ram[f"IO{i}"] = f"VD{8 * k + i}"
            x[f"A{i + 1}"], x[f"B{i + 1}"] = DB[8 * k + i], f"VD{8 * k + i}"
    if not sim:
        nl.add("const", "X_VSLOT", LO="VSLOT", HI="VSLOT_n")
        return
    for k in range(3):
        v = nl.add("541", f"U_B1V{k}", OE1="VSLOT_n", OE2="GND")
        for i in range(8):
            bit = 8 * k + i
            v[f"A{i + 1}"] = f"VAD{bit}" if bit < 19 else "GND"
            if bit < 19:
                v[f"Y{i + 1}"] = f"B1A{bit}"


# the sequencer's codes for the pixel registers (PXR): which loads at an
# edge, and from what. E's: its low nibble from LN (and its high from the
# bank, or with 8 bits a pixel from the shifters), or from the shifters'
# outputs s0-s3; LN from s; O's from s
SEL_HOLD, SEL_LN, SEL_LN8, SEL_S10, SEL_S32 = 0b0000, 0b0001, 0b0010, 0b0011, 0b0100
SEL_S0, SEL_S1, SEL_S2, SEL_S3 = 0b0101, 0b0110, 0b0111, 0b1100
SEL_LNLD, SEL_O32, SEL_O1, SEL_O3 = 0b1000, 0b1001, 0b1010, 0b1011
SEL_E = {SEL_LN, SEL_LN8, SEL_S10, SEL_S32, SEL_S0, SEL_S1, SEL_S2, SEL_S3}
SEL_O = {SEL_O32, SEL_O1, SEL_O3}
# the colour register's codes: hold, E's palette, O's, black
CS_HOLD, CS_E, CS_O, CS_BLANK = 0, 1, 2, 3


def sequence(mode, ph, px, c0, c1, shld, deq, von, ded):
    """The pixel sequencer (video()'s U_VS) for the tick after this one,
    from this one's: the mode (the frame's, 0-7), the pixel phase PH and
    the pixel in the character PX (VGA's tick in the character is 2 PX +
    PH, XGA's PX), the character's low bits, the timing register's SHLD
    and DE, the picture on, DED (DE latched at PX 2). Returns (shift,
    load, SEL, CS): the shifters' S0 and S1, the pixel registers' code and
    the colour register's, for the edge that ends the next tick."""
    from .video import MODES
    if mode not in MODES:
        return 0, 0, SEL_HOLD, CS_BLANK
    fam, bits, double = MODES[mode]
    xga = fam.xga
    t = px if xga else 2 * px + ph               # this tick
    last = 7 if xga else 15
    t1 = 0 if t == last else t + 1               # the next
    # a word's end: the character's (4 and 8 bits), every second
    # character's (2 bits), every fourth's (1 bit), the timing ROM saying
    # whether the line wants a word there (SHLD); M2 also halfway
    load = 0
    if t1 == last:
        load = shld & {4: 1, 8: 1, 2: c0, 1: c0 & c1}[bits]
    if not xga and bits == 8 and not double and t1 == 7:
        load = deq
    if xga:
        shift = t1 % 2 == 1 if bits == 2 else t1 % 4 == 3
        sel = {2: {0: SEL_S10, 1: SEL_O32}, 1: {0: SEL_S0, 1: SEL_O1, 2: SEL_S2, 3: SEL_O3}}[
            bits][t1 % (2 if bits == 2 else 4)]
        cs = CS_E if t1 % 2 == 0 else CS_O
    else:
        if bits == 4:
            shift, sel = t1 % 2 == 1, SEL_LN if t1 % 2 else SEL_LNLD
        elif bits == 8 and double:
            shift = t1 % 4 in (0, 3)
            sel = SEL_LN8 if t1 % 2 else (SEL_LNLD if t1 % 4 == 0 else SEL_HOLD)
        elif bits == 8:
            shift, sel = True, SEL_LN8 if t1 % 2 else SEL_LNLD
        elif bits == 2:
            shift = t1 % 4 == 3
            sel = {1: SEL_S10, 3: SEL_S32}.get(t1 % 4, SEL_HOLD)
        else:
            shift = t1 % 8 == 7
            sel = {1: SEL_S0, 3: SEL_S1, 5: SEL_S2, 7: SEL_S3}.get(t1 % 8, SEL_HOLD)
        cs = CS_E if t1 % 2 else CS_HOLD
    if cs != CS_HOLD:
        # the pixel the colour register takes is the character's but at
        # the next one's first edge, which takes the last character's
        de = (ded if t1 == 1 else deq) and von
        if not de:
            cs = CS_BLANK
    return int(shift or load), int(load), sel, cs


def video(nl, DB, VA, capture=False):
    """The video (RFC 0042): modes M0-M6 from bank 1, the cursor (C1), the
    beam's position (P1) and the second holding register with cycle
    stealing (B1), as video.py describes them; VGA at 50.35 MHz (a pixel
    two master ticks), XGA with the master clock at 65 MHz (a pixel a
    tick), so all of it is on the master clock.

    The fetch: the video owns bank 1 in every cycle's T2 and the next H0,
    and in an I/O access's hold, and reads the word at VAD into a holding
    register at the end of each two ticks it owns it, if one is free: two
    holding registers, a queue (VF). VAD steps as it reads. The shifters
    take the queue's head at a word's end. In a picture's line, a T1 with
    the queue empty steals two ticks: T2 is held (STRETCH), the video's
    slot four ticks. The line before each picture line reads the cursor's
    two words and the line's descriptor (the events, from the timing ROM),
    each by loading VAD and emptying the queue.

    The pixels: four 74F299s, shifter k holding bit k of each of the
    word's nibbles, the first out at Q7. The sequencer (VS) shifts them by
    the mode and gives the pixel registers (PXR, three 22V10s) a code for
    each edge: E's (VGA's every pixel; XGA's even pixels) and O's (XGA's
    odd pixels), each the palette's address for two ticks, so the palette
    is two copies of 256 entries, E's and O's, both written by the CPU. A
    4-bit pixel goes through LN, a nibble register, a tick later; an
    8-bit one is LN's nibble and the shifters' next. The colour register
    (three 22V10s) takes E's or O's colour, or black outside the picture.
    The cursor's pixel overrides the pixel registers' (palette entries
    253-255)."""
    from . import video as vid
    g = nl.gate
    rst = lit("RESET_n")

    nl.section("Video timing")
    # V1: the pixel phase (PH: a VGA pixel's second tick; always 1 in
    # XGA), the pixel in the character (PX, counted at each pixel's end),
    # P7 the character's last pixel, CHE its last tick
    PX = bus("PX", 3)
    last = gal.AND(rst, gal.OR(gal.AND(lit("FAM", 0), lit("P7"), lit("PH", 0)),
                               gal.AND(lit("FAM"), lit(PX[0], 0), lit(PX[1]), lit(PX[2]))))
    # CHE1: the tick before CHE, for the controls registered a tick ahead
    # of the character's end (a 74ACT163's 6.6 ns of setup leaves no room
    # for a 22V10 after CHE at 65 MHz)
    before = gal.AND(rst, gal.OR(gal.AND(lit("FAM", 0), lit(PX[0], 0), lit(PX[1]), lit(PX[2]),
                                         lit("PH")),
                                 gal.AND(lit("FAM"), lit(PX[0]), lit(PX[1], 0), lit(PX[2]))))
    v1 = {"PH": (gal.AND(rst, gal.OR(lit("PH", 0), lit("FAM"))), True, False),
          "P7": (gal.AND(rst, lit(PX[0], 0), lit(PX[1]), lit(PX[2]), lit("PH")), True, False),
          "CHE": (last, True, False), "CHE_n": (last, True, True),
          "CHE1": (before, True, False)}
    for b in range(3):
        carry = gal.AND(lit("PH"), *[lit(PX[i]) for i in range(b)])
        v1[PX[b]] = (gal.AND(rst, gal.OR(
            gal.AND(lit(PX[b]), gal.OR(lit("PH", 0), *[lit(PX[i], 0) for i in range(b)])),
            gal.AND(lit(PX[b], 0), carry))), True, False)
    gal.add(nl, "U_V1", v1, clock="MCLK")
    # V2: the ownership of bank 1, a tick ahead: T2 and H0 follow T1 and
    # T2; the hold's ticks follow HOLD (VSLOT, set in a reset). VT toggles
    # while the video owns bank 1: its second ticks end the slots. The
    # character and line counters' clears and the line's step. The clock:
    # TABX, whether the clock generator uses XGA's lengths, loaded at H1
    # as K1 loads the count; CLKSEL asks for the XGA clock once they are
    # in force, and drops it at once
    EV = ["EV0", "EV1", "EV2"]
    lend = gal.AND(*[lit(e) for e in EV])
    slot = gal.AND(rst, lit("T1", 0), lit("T2", 0), lit("HOLD", 0))
    tx = gal.OR(lit("FAM"), lit("ENB"))
    gal.add(nl, "U_V2", {
        "VSLOT_n": (slot, True, False), "VSLOT": (slot, True, True),
        "VT_n": (gal.AND(rst, lit("VSLOT"), lit("VT_n")), True, True),
        "HCLR_n": (gal.AND(lend, lit("CHE1")), True, True),
        "LINE": (gal.AND(lend, lit("CHE1")), True, False),
        "VCLR_n": (gal.AND(lit("FENDQ"), lend, lit("CHE1")), True, True),
        "TABX": (gal.OR(gal.AND(lit("H1"), tx), gal.AND(lit("H1", 0), lit("TABX"))), True,
                 False),
        "CLKSEL": (gal.AND(lit("FAM"), lit("TABX")), False, False)}, clock="MCLK")
    # the character (0-99, 0-167) and the line (0-524, 0-805)
    H, V = bus("VH", 8), bus("VV", 10) + ["VV10", "VV11"]
    rco = "VCC"
    for k in range(2):
        # (the carries ripple on past the edge after a step, when nothing
        # counts: the simulator's checks are off past the first counter)
        nl.add("163", f"U_VH{k}", part="74ACT163", CLK="MCLK", CLR="HCLR_n", LOAD="VCC",
               nocheck=k > 0,
               ENP="CHE", ENT=rco, A="GND", B="GND", C="GND", D="GND",
               QA=H[4 * k], QB=H[4 * k + 1], QC=H[4 * k + 2], QD=H[4 * k + 3], RCO=f"VHC{k}")
        rco = f"VHC{k}"
    rco = "VCC"
    for k in range(3):
        nl.add("163", f"U_VV{k}", part="74ACT163", CLK="MCLK", CLR="VCLR_n", LOAD="VCC",
               nocheck=k > 0,
               ENP="LINE", ENT=rco, A="GND", B="GND", C="GND", D="GND",
               QA=V[4 * k], QB=V[4 * k + 1], QC=V[4 * k + 2], QD=V[4 * k + 3], RCO=f"VVC{k}")
        rco = f"VVC{k}"
    # the timing ROM, by the family, the line and the character, registered
    # at the character's end: what to do in the next character
    rom = nl.add("flash4", "U_VTIM", role="decode", CE="GND", OE="GND", WE="VCC")
    for i in range(8):
        rom[f"A{i}"] = H[i]
    for i in range(10):
        rom[f"A{8 + i}"] = V[i]
    rom["A18"] = "FAM"
    tr = nl.add("377", "U_VTR", CLK="MCLK", EN="CHE_n")
    for i, q in enumerate(TIMING_BITS):
        tr[f"D{i + 1}"], tr[f"Q{i + 1}"] = f"VTD{i}", q
        rom[f"D{i}"] = f"VTD{i}"

    nl.section("Video registers")
    # region 7, LOC0, by VA[4:2]: 0 the control register (written), 1 the
    # interrupt's acknowledge (any write), 2 the beam (read), 4 the
    # cursor's X (written)
    # (the writes from the I/O strobe itself, IOWR_n's 22V10 left out of
    # the path: at 65 MHz there's no room for two before a register)
    wr_ = gal.AND(lit("MEMWR"), lit("IOSTB"), lit("FAULT", 0), lit("LOC0_n", 0))

    def reg(n):
        return gal.AND(wr_, *[lit(VA[2 + i], n >> i & 1) for i in range(3)])
    gal.add(nl, "U_VDEC", {
        "VCTLW": (reg(0), False, False),
        "ACKW": (reg(1), False, False),
        "XW_n": (reg(4), False, True),
        "BEAMR_n": (sop(["LOC0_n", "IORD_n", VA[2], VA[3], VA[4]],
                        lambda l, r, a2, a3, a4: not l and not r and not a2 and a3 and not a4),
                    False, True)})
    # the control register, loaded through a write's strobe (synchronous
    # to the master clock): bit 0 the picture on, 1 TSEL, 2 the interrupt
    # on, 6-4 the mode, 8 the cursor on
    ctl = {}
    for q, d in (("VON", 0), ("TSEL", 1), ("VIEN", 2), ("MD0", 4), ("MD1", 5), ("MD2", 6),
                 ("CURON", 8)):
        ctl[q] = (gal.AND(rst, gal.OR(gal.AND(lit("VCTLW"), lit(DB[d])),
                                      gal.AND(lit("VCTLW", 0), lit(q)))), True, False)
    gal.add(nl, "U_V3A", ctl, clock="MCLK")
    # the frame's mode (FM), taken from the control register as a frame
    # starts (the last line's last character), and its family (FAM: modes
    # 5 and 6); the interrupt: set at the picture's end and by a line whose
    # descriptor asks; cleared by the acknowledge
    MD, FM = ["MD0", "MD1", "MD2"], ["FM0", "FM1", "FM2"]
    fend = gal.AND(lit("LINE"), lit("FENDQ"))
    nofend = gal.OR(lit("LINE", 0), lit("FENDQ", 0))
    v3 = {}
    for m, f in zip(MD, FM):
        v3[f] = (gal.AND(rst, gal.OR(gal.AND(fend, lit(m)), gal.AND(nofend, lit(f)))), True,
                 False)
    xga_md = sop(MD, lambda a, b, c: a + 2 * b + 4 * c in (5, 6))
    v3["FAM"] = (gal.AND(rst, gal.OR(gal.AND(fend, xga_md), gal.AND(nofend, lit("FAM")))), True,
                 False)
    v3["VIFLAG"] = (gal.AND(rst, gal.OR(fend, gal.AND(lit("DSE_n", 0), lit("HR23")),
                                        gal.AND(lit("VIFLAG"), lit("ACKW", 0)))), True, False)
    v3["VIRQ"] = (gal.AND(lit("VIFLAG"), lit("VIEN")), False, False)
    gal.add(nl, "U_V3B", v3, clock="MCLK")
    # the cursor's X: the beam position (bits 10-3 the character, 2-0 the
    # pixel) it starts XSTART pixels after
    for k in range(2):
        r = nl.add("377", f"U_CX{k}", CLK="MCLK", EN="XW_n")
        for i in range(8):
            bit = 8 * k + i
            r[f"D{i + 1}"] = DB[bit] if bit < 11 else "GND"
            if bit < 11:
                r[f"Q{i + 1}"] = f"XR{bit}"
    # the beam (P1): the line on bits 9-0, the character on 23-16
    for k, srcs, dst in ((0, V[:8], 0), (1, V[8:10] + ["GND"] * 6, 8), (2, H, 16)):
        b = nl.add("541", f"U_BEAM{k}", OE1="BEAMR_n", OE2="GND")
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = srcs[i], DB[dst + i]

    nl.section("Video fetch")
    # VE: the events at a character's end: VAD loaded with a table's
    # address (the cursor's two, the descriptors'), or the descriptor (from
    # the queue's head); the queue emptied. The table's address: the line
    # (bits 9-0), then bit 10 TSEL (the descriptors') or the cursor's
    # second word, bit 11 the cursor's tables
    def ev(*codes):
        return gal.when(EV, list(codes), range(8))
    che = lit("CHE")
    tables = ev(vid.EV_C0LD, vid.EV_C0TK, vid.EV_C1TK)
    # the steal (B1): STRETCH for two ticks from T2 if a picture's line
    # finds the queue empty in T1
    steal = gal.AND(lit("T1"), lit("CNT0", 0), lit("DEQR"))
    che1 = lit("CHE1")
    gal.add(nl, "U_VE", {
        "VADL_n": (gal.AND(che1, ev(vid.EV_C0LD, vid.EV_C0TK, vid.EV_C1TK, vid.EV_DSE)), True,
                   True),
        "VADC_n": (gal.AND(che1, tables), True, True),
        "VADH_n": (gal.AND(che1, ev(vid.EV_DSE)), True, True),
        "VADS": (tables, False, False),
        "B10": (gal.OR(ev(vid.EV_C0TK), gal.AND(ev(vid.EV_C1TK), lit("TSEL"))), False, False),
        "B11": (ev(vid.EV_C0LD, vid.EV_C0TK), False, False),
        "DSE_n": (gal.AND(che1, ev(vid.EV_DSE)), True, True),
        "STRETCH": (gal.AND(rst, gal.OR(steal, gal.AND(lit("STRETCH"), lit("STRX", 0)))), True,
                    False),
        "STRX": (gal.AND(rst, lit("STRETCH"), lit("STRX", 0)), True, False)}, clock="MCLK")
    # VF: the queue (two holding registers, HRA and HRB): its count (0-2),
    # where the next word goes (WP) and the head (RP, RPN: the registers'
    # output enables). A slot's word goes in if there's room; the shifters'
    # load takes the head; an event empties it. The steal: STRETCH for two
    # ticks from T2 if a picture's line finds the queue empty in T1
    fl_ev = (vid.EV_C0LD, vid.EV_C0TK, vid.EV_C1TK, vid.EV_DSE)

    def fifo(che, e0, e1, e2, vslot, vt_n, sld, c0, c1, wp, rp, fen, ch1, fam, r):
        # the count as a thermometer: CNT0 one or more, CNT1 two
        e = e0 + 2 * e1 + 4 * e2
        if e in (5, 6):
            return None                          # no such event
        flush = che and e in fl_ev
        count = 2 if c1 else c0
        # a slot's word, but only if VAD has stood since the slot started,
        # in XGA since a tick before (FEN: from VAD's change the word is 33
        # ns coming, the 74ACT163, the buffer, the RAM; two of XGA's ticks
        # are 30.8). CH1: VAD changed as this tick started
        fetch = int(vslot and not vt_n and not c1 and not flush and fen)
        pop = int(sld and count > 0)
        new = 0 if flush or not r else count + fetch - pop
        keep = r and not flush
        change = flush or fetch
        return {"CNT0": new >= 1, "CNT1": new == 2, "WP": keep and wp ^ fetch,
                "RP": keep and rp ^ pop, "HRA_n": fetch and not wp, "HRB_n": fetch and wp,
                "VADINC": fetch, "CH1": change, "FEN_": change or (fam and ch1)}
    fnets = ["CHE"] + EV + ["VSLOT", "VT_n", "SLD", "CNT0", "CNT1", "WP", "RP", "FEN", "CH1",
                            "FAM", "RESET_n"]
    fvars = {"CNT0": ("WP", "RP", "CH1", "FAM"), "CNT1": ("WP", "RP", "CH1", "FAM"),
             "WP": ("SLD", "CNT0", "RP", "CH1", "FAM"),
             "RP": ("VSLOT", "VT_n", "WP", "FEN", "CH1", "FAM"),
             "HRA_n": ("SLD", "CNT0", "RP", "RESET_n", "CH1", "FAM"),
             "HRB_n": ("SLD", "CNT0", "RP", "RESET_n", "CH1", "FAM"),
             "VADINC": ("SLD", "CNT0", "WP", "RP", "RESET_n", "CH1", "FAM"),
             "CH1": ("SLD", "CNT0", "WP", "RP", "RESET_n", "CH1", "FAM"),
             "FEN_": ("SLD", "CNT0", "WP", "RP", "RESET_n")}

    def ft(name):
        # over the nets the output depends on (fvars: those it doesn't,
        # which is checked: the same for every value of them)
        nets = [n for n in fnets if n not in fvars.get(name, ())]
        rest = [n for n in fnets if n not in nets]

        def f(*b):
            vals = set()
            for k in range(1 << len(rest)):
                v = dict(zip(nets, b), **{n: (k >> i) & 1 for i, n in enumerate(rest)})
                r = fifo(*[v[n] for n in fnets])
                vals.add(None if r is None else int(bool(r[name])))
            if len(vals) > 1:
                raise ValueError(f"U_VF: {name} depends on {rest}")
            return vals.pop()
        return gal.table(nets, f)
    gal.add(nl, "U_VF", {
        "CNT0": (ft("CNT0"), True, False),
        "CNT1": (ft("CNT1"), True, False),
        "WP": (ft("WP"), True, False),
        "RP": (ft("RP"), True, False),
        "RPN": (ft("RP"), True, True),
        "CH1": (ft("CH1"), True, False),
        "FEN": (ft("FEN_"), True, True),
        "HRA_n": (ft("HRA_n"), False, True),
        "HRB_n": (ft("HRB_n"), False, True),
        "VADINC": (ft("VADINC"), False, False)}, clock="MCLK")
    # VAD: loaded with a table's address (VADS: the low twelve bits from
    # the table, the rest cleared) or the descriptor (all from the head),
    # stepped as a word goes into the queue
    VADn = bus("VAD", 19) + ["VAD19"]
    HR = bus("HR", 32)
    for k in range(3):
        m = nl.add("157", f"U_VADM{k}", S="VADS", G="GND")
        for j in range(4):
            bit = 4 * k + j
            tab = f"VV{bit}" if bit < 10 else ("B10" if bit == 10 else "B11")
            m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = HR[bit], tab, f"VADD{bit}"
    rco = "VCC"
    for k in range(5):
        low = k < 3
        # (the carry ripples on past the edge after a step, as the
        # character and line counters' do)
        c = nl.add("163", f"U_VAD{k}", part="74ACT163", CLK="MCLK", nocheck=k > 0,
                   CLR="VCC" if low else "VADC_n", LOAD="VADL_n" if low else "VADH_n",
                   ENP="VADINC", ENT=rco, RCO=f"VADC{k}")
        rco = f"VADC{k}"
        for j, (pin, q) in enumerate(zip("ABCD", ("QA", "QB", "QC", "QD"))):
            bit = 4 * k + j
            c[pin] = f"VADD{bit}" if low else (HR[bit] if bit < 19 else "GND")
            c[q] = VADn[bit]
    # the holding registers: 9-bit registers with a clock enable, onto the
    # head bus (HR) by their output enables
    for side, en, oe in (("A", "HRA_n", "RP"), ("B", "HRB_n", "RPN")):
        for k in range(4):
            r = nl.add("823", f"U_HR{side}{k}", CLK="MCLK", EN=en, CLR="VCC", OE=oe)
            for i in range(8):
                r[f"D{i + 1}"], r[f"Q{i + 1}"] = f"VD{8 * k + i}", HR[8 * k + i]
            r["D9"] = "GND"
    # the line's palette bank, from its descriptor
    ml = nl.add("377", "U_VML", CLK="MCLK", EN="DSE_n")
    for i in range(8):
        ml[f"D{i + 1}"] = HR[19 + i]
        if i < 4:
            ml[f"Q{i + 1}"] = f"VM{i}"

    nl.section("Video output")
    # the shifters: shifter k has bit k of each nibble, nibble 0 at IO7
    S = bus("VP", 4)
    for k in range(4):
        sh = nl.add("299", f"U_VSH{k}", S0="SHIFT", S1="SLD", OE1="VCC", OE2="VCC",
                    MR="RESET_n", CP="MCLK", DS0="GND", DS7="GND", Q7S=S[k])
        for j in range(8):
            sh[f"IO{7 - j}"] = HR[4 * j + k]
    # VS: the sequencer (sequence()), from the frame's mode, the counters
    # and the timing register
    SEL = bus("SEL", 4)
    ins = FM + ["PH"] + PX + ["VH0", "VH1", "SHLDQ", "DEQR", "VON", "DED"]

    def seqf(k):
        def f(fm0, fm1, fm2, ph, p0, p1, p2, c0, c1, shld, deq, von, ded):
            mode = fm0 + 2 * fm1 + 4 * fm2
            from .video import MODES
            if mode in MODES and MODES[mode][0].xga and not ph:
                return None                      # XGA's PH is always 1
            shift, load, sel, cs = sequence(mode, ph, p0 + 2 * p1 + 4 * p2, c0, c1, shld, deq,
                                            von, ded)
            return [shift, load, sel & 1, sel >> 1 & 1, sel >> 2 & 1, sel >> 3 & 1,
                    cs & 1, cs >> 1][k]
        return gal.table(ins, f)
    vs = {"SHIFT": (seqf(0), True, False), "SLD": (seqf(1), True, False)}
    for i in range(4):
        vs[SEL[i]] = (seqf(2 + i), True, False)
    vs["CS0"] = (seqf(6), True, False)
    vs["CS1"] = (seqf(7), True, False)
    # DED: DE latched at PX 2, for the character's last pixel
    px2 = gal.AND(lit(PX[0], 0), lit(PX[1]), lit(PX[2], 0))
    vs["DED"] = (gal.OR(gal.AND(px2, lit("DEQR")), gal.AND(gal.OR(lit(PX[0]), lit(PX[1], 0),
                                                                  lit(PX[2])), lit("DED"))),
                 True, False)
    gal.add(nl, "U_VS", vs, clock="MCLK")

    # the pixel registers. PXE: E's low nibble and LN; PXEH: E's high
    # nibble; PXO: O's. A cursor pixel (CE for E, CO for O; 0 transparent)
    # makes the pixel 252 + it
    def code(*cs):
        return gal.when(SEL, list(cs), range(16))
    s_ = [lit(x) for x in S]
    ce = gal.OR(lit("CE0"), lit("CE1"))
    noce = gal.AND(lit("CE0", 0), lit("CE1", 0))
    pe = {}
    LN = bus("LN", 4)
    PE, PO = bus("PE", 8), bus("PO", 8)
    eload = code(*SEL_E)
    for b in range(4):
        src = {SEL_LN: lit(LN[b]), SEL_LN8: lit(LN[b]),
               SEL_S10: s_[b] if b < 2 else gal.ZERO, SEL_S32: s_[b + 2] if b < 2 else gal.ZERO,
               SEL_S0: s_[0] if b == 0 else gal.ZERO, SEL_S1: s_[1] if b == 0 else gal.ZERO,
               SEL_S2: s_[2] if b == 0 else gal.ZERO, SEL_S3: s_[3] if b == 0 else gal.ZERO}
        cur = gal.ONE if b >= 2 else lit(f"CE{b}")
        val = gal.OR(*[gal.AND(code(c), f) for c, f in src.items()])
        pe[PE[b]] = (gal.OR(gal.AND(eload, ce, cur), gal.AND(eload, noce, val),
                            gal.AND(gal.when(SEL, list(set(range(16)) - SEL_E), range(16)),
                                    lit(PE[b]))), True, False)
        pe[LN[b]] = (gal.OR(gal.AND(code(SEL_LNLD), s_[b]),
                            gal.AND(gal.when(SEL, list(set(range(16)) - {SEL_LNLD}), range(16)),
                                    lit(LN[b]))), True, False)
    gal.add(nl, "U_PXE", pe, clock="MCLK")
    peh = {}
    for b in range(4):
        hb = 4 + b
        val = gal.OR(gal.AND(code(SEL_LN8), s_[b]),
                     gal.AND(code(*(SEL_E - {SEL_LN8})), lit(f"VM{b}")))
        peh[PE[hb]] = (gal.OR(gal.AND(eload, ce), gal.AND(eload, noce, val),
                              gal.AND(gal.when(SEL, list(set(range(16)) - SEL_E), range(16)),
                                      lit(PE[hb]))), True, False)
    gal.add(nl, "U_PXEH", peh, clock="MCLK")
    # O loads on SEL3 with SEL1 or SEL0: 1001 s3 s2, 1010 s1, 1011 s3
    oload = gal.AND(lit(SEL[3]), gal.OR(lit(SEL[1]), lit(SEL[0])))
    nooload = gal.OR(lit(SEL[3], 0), gal.AND(lit(SEL[1], 0), lit(SEL[0], 0)))
    co = gal.OR(lit("CO0"), lit("CO1"))
    noco = gal.AND(lit("CO0", 0), lit("CO1", 0))
    o32 = gal.AND(lit(SEL[1], 0), lit(SEL[0]))
    o1 = gal.AND(lit(SEL[1]), lit(SEL[0], 0))
    o3 = gal.AND(lit(SEL[1]), lit(SEL[0]))
    po = {}
    for b in range(8):
        if b < 4:
            val = {0: gal.OR(gal.AND(o32, s_[2]), gal.AND(o1, s_[1]), gal.AND(o3, s_[3])),
                   1: gal.AND(o32, s_[3])}.get(b, gal.ZERO)
            cur = gal.ONE if b >= 2 else lit(f"CO{b}")
        else:
            val, cur = lit(f"VM{b - 4}"), gal.ONE
        po[PO[b]] = (gal.OR(gal.AND(oload, co, cur), gal.AND(oload, noco, val),
                            gal.AND(nooload, lit(PO[b]))), True, False)
    gal.add(nl, "U_PXO", po, clock="MCLK")

    # the palette: two copies (E, O) of 256 entries of 16 bits, by the
    # pixel registers or, while the CPU writes it (region 7, LOC1:
    # 0xF000_0400 + 4n), its address; both written at once
    g("32", ["LOC1_n", "IOWR_n"], "PWE_n")
    g("04", ["LOC1_n"], "POE_n")
    for side, src in (("E", PE), ("O", PO)):
        for k in range(2):
            m = nl.add("157", f"U_PAM{side}{k}", S="LOC1_n", G="GND")
            for j in range(4):
                bit = 4 * k + j
                m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = VA[2 + bit], src[bit], \
                    f"PA{side}{bit}"
        for k in range(2):
            ram = nl.add("sram", f"U_PAL{side}{k}", role="rf", CE="GND", OE="POE_n", WE="PWE_n")
            for i in range(15):
                ram[f"A{i}"] = f"PA{side}{i}" if i < 8 else "GND"
            b = nl.add("541", f"U_PWD{side}{k}", OE1="LOC1_n", OE2="IOWR_n")
            for i in range(8):
                ram[f"IO{i}"] = f"PD{side}{8 * k + i}"
                b[f"A{i + 1}"], b[f"Y{i + 1}"] = DB[8 * k + i], f"PD{side}{8 * k + i}"
    # the colour register: E's colour, O's, black or as it is (CS); DEO,
    # whether it holds a picture's pixel (for the frame grabber)
    for ref, bits_ in (("U_COL0", range(0, 6)), ("U_COL1", range(6, 11)),
                       ("U_COL2", range(11, 16))):
        cs = {v: gal.AND(lit("CS0", v & 1), lit("CS1", v >> 1)) for v in range(4)}
        outs = {}
        for i in bits_:
            outs[f"RGB{i}"] = (gal.OR(gal.AND(cs[CS_E], lit(f"PDE{i}")),
                                      gal.AND(cs[CS_O], lit(f"PDO{i}")),
                                      gal.AND(cs[CS_HOLD], lit(f"RGB{i}"))), True, False)
        if ref == "U_COL2":
            outs["DEO"] = (gal.OR(cs[CS_E], cs[CS_O], gal.AND(cs[CS_HOLD], lit("DEO"))), True,
                           False)
        gal.add(nl, ref, outs, clock="MCLK")

    nl.section("Cursor")
    # the cursor's shifters: four lanes of 16 bits, E's pixels' low and
    # high bits, O's, each two 74F299s (A then B, B's in after A's), A
    # loaded with the row's first word, B with its second, from the
    # queue's head; cleared while the cursor is off
    LANES = ["CL0", "CL1", "CL2", "CL3"]
    for lane in range(4):
        for half in "AB":
            sh = nl.add("299", f"U_CS{half}{lane}", S0=f"CS{half}S0", S1=f"CS{half}S1",
                        OE1="VCC", OE2="VCC", MR="CURON", CP="MCLK",
                        DS0="GND" if half == "B" else f"CLB{lane}", DS7="GND",
                        Q7S=LANES[lane] if half == "A" else f"CLB{lane}")
            for i in range(8):
                sh[f"IO{7 - i}"] = HR[4 * i + lane]
    # the X compare: the beam (the character, the pixel; in XGA the pixel's
    # bit 0 left out, so the cursor is at an even pixel)
    g("08", [PX[0], "FAM_n"], "CPX0")
    g("08", ["XR0", "FAM_n"], "CXR0")
    g("04", ["FAM"], "FAM_n")
    beam = ["CPX0", PX[1], PX[2]] + H[:5]
    xr = ["CXR0"] + [f"XR{i}" for i in range(1, 8)]
    nl.add("521", "U_CXC0", G="GND", PEQ="CEQA_n", **{f"P{i}": beam[i] for i in range(8)},
           **{f"Q{i}": xr[i] for i in range(8)})
    nl.add("521", "U_CXC1", G="GND", PEQ="CEQB_n",
           **{f"P{i}": H[5 + i] if i < 3 else "GND" for i in range(8)},
           **{f"Q{i}": f"XR{8 + i}" if i < 3 else "GND" for i in range(8)})
    # VC1: ACTIVE, set as the compare matches (at a pixel's second tick in
    # VGA, a pair's in XGA, when the beam has been there two ticks), cleared
    # as the next line's cursor loads; the lanes' loads (C0TK, C1TK, at the
    # character's last tick) and shifts (VGA: after every second pixel, as
    # CPAR, the pixel's parity, says; XGA: every pair, at its odd tick).
    # CHE and the next tick's from the counters, a tick ahead
    cnets = ["FAM", "PH"] + PX + ["CEQA_n", "CEQB_n"] + EV + ["CURON", "ACTIVE", "CPAR"]

    def vc1(fam, ph, p0, p1, p2, qa, qb, e0, e1, e2, on, act, cpar):
        if fam and not ph:
            return None                          # XGA's PH is always 1
        e = e0 + 2 * e1 + 4 * e2
        px = p0 + 2 * p1 + 4 * p2
        odd = p0 if fam else ph                  # this tick ends a pixel (a pair)
        che_now = px == 7 and odd
        che_next = px == 6 if fam else (px == 7 and not ph)
        match = not qa and not qb
        clear = che_now and e == vid.EV_C0LD
        active = on and not clear and (act or (odd and match))
        # CPAR toggles at VGA's even edges (the end of PH 0) while active
        if fam or ph:
            npar = cpar
        else:
            npar = act and not cpar
        # the lanes' shift at the next tick's end: VGA at an even edge with
        # CPAR (this tick PH 1), XGA at an odd one (this tick PX0 0)
        shift = act and ((not fam and ph and cpar) or (fam and not p0))
        lda = che_next and e == vid.EV_C0TK
        ldb = che_next and e == vid.EV_C1TK
        return {"ACTIVE": active, "CPAR": npar, "CSAS1": lda, "CSAS0": lda or shift,
                "CSBS1": ldb, "CSBS0": ldb or shift}

    def ct(name):
        def f(*b):
            r = vc1(*b)
            return None if r is None else int(bool(r[name]))
        return gal.table(cnets, f)
    gal.add(nl, "U_VC1", {n: (ct(n), True, False)
                          for n in ("ACTIVE", "CPAR", "CSAS1", "CSAS0", "CSBS1", "CSBS0")},
            clock="MCLK")
    # VC2: the cursor's pixel for the next E and O loads, registered a tick
    # before them: VGA at the even edges, E's lane or O's by CPAR; XGA at
    # the odd edges, both; 0 while not active
    vga_ld = gal.AND(lit("FAM", 0), lit("PH", 0))
    xga_ld = gal.AND(lit("FAM"), lit(PX[0]))
    hold = gal.OR(gal.AND(lit("FAM", 0), lit("PH")), gal.AND(lit("FAM"), lit(PX[0], 0)))
    vc2 = {}
    for b in range(2):
        e_src = gal.OR(gal.AND(vga_ld, lit("CPAR", 0), lit(LANES[b])),
                       gal.AND(vga_ld, lit("CPAR"), lit(LANES[2 + b])),
                       gal.AND(xga_ld, lit(LANES[b])))
        vc2[f"CE{b}"] = (gal.OR(gal.AND(lit("ACTIVE"), e_src),
                                gal.AND(hold, lit(f"CE{b}"))), True, False)
        vc2[f"CO{b}"] = (gal.OR(gal.AND(lit("ACTIVE"), xga_ld, lit(LANES[2 + b])),
                                gal.AND(gal.OR(lit("FAM", 0), lit(PX[0], 0)), lit(f"CO{b}"))),
                         True, False)
    gal.add(nl, "U_VC2", vc2, clock="MCLK")

    if capture:
        # a frame grabber: the outputs at the middle of each pixel (VGA: as
        # PH rises; XGA: as the master clock falls)
        g("04", ["MCLK"], "MCLK_n")
        g("08", ["MCLK_n", "FAM"], "CAPX")
        g("08", ["PH", "FAM_n"], "CAPV")
        g("32", ["CAPX", "CAPV"], "CAPCLK")
        from .video import CAPTURE
        x = nl.add("vector", "X_VCAP", CLK="CAPCLK", params={"outs": 0, "ins": len(CAPTURE),
                                                             "conds": 1})
        for i in range(48):
            x[f"I{i}"] = CAPTURE[i] if i < len(CAPTURE) else "GND"


def io_space(nl, VA, DB, sim):
    """The devices in the I/O space (system.py has the map): the strobes,
    the devices' latched address, the 16-bit I/O data bus, the devices,
    the on-board registers in region 7 and the interrupt line."""
    g = nl.gate
    if not sim:
        # the static timing analysis leaves the I/O space out: its timing
        # is the hold's, checked with the devices at chip level
        nl.add("const", "X_STUB", LO="IRQ")
        return
    nl.section("I/O")
    # the strobes, the latches' enable, the I/O data bus's enable and the
    # CF card's selects and strobes: a 22V10 on the master clock. The
    # strobes from the hold's second tick to T2; none in an address error,
    # whose access holds the cycle all the same. The devices' address and
    # selects, latched as the strobe starts until the next cycle's tick 1
    # (open for a tick between, while VA still holds): they hold 20 ns
    # after the strobe (the 16C550's and the CF card's tAH), and the
    # expansion ports see them settled. The I/O data bus, 16 bits, for
    # regions 0-6: driven from the data bus for the whole of a write, onto
    # it for a read's strobe. The CF card, region 0, True IDE on the I/O
    # bus's 16 bits: CS0 (the task file) with A5 low, CS1 (the control
    # block) with A5 high. Its strobes start two ticks after the others,
    # for PIO mode 0's 70 ns of address setup (a read at the A bus has its
    # address late); they end with them, at T2 (J = 1 with K-bar = 0
    # toggles them off then)
    rst, ok = lit("RESET_n"), lit("FAULT", 0)
    gal.add(nl, "U_IOG", {
        "IOWR_n": (gal.AND(lit("MEMWR"), lit("IOSTB"), ok), False, True),
        "IORD_n": (gal.AND(lit("READING"), lit("IOSTB"), ok), False, True),
        "IOLE": (gal.OR(lit("IOSTB"), lit("H0")), False, True),
        "XOE_n": (gal.AND(lit("IOR7_n"), gal.OR(gal.AND(lit("IOACC"), lit("MEMWR")),
                                                gal.AND(lit("IOSTB"), lit("READING")))),
                  False, True),
        "CFCS0_n": (gal.OR(lit("IOS0_n"), lit("IOA5")), False, False),
        "CFCS1_n": (gal.OR(lit("IOS0_n"), lit("IOA5", 0)), False, False),
        "CFS2": (gal.AND(rst, gal.OR(gal.AND(lit("IOSTB"), lit("CFS2", 0)),
                                     gal.AND(lit("T1", 0), lit("CFS2")))), True, False),
        "CFS3": (gal.AND(rst, gal.OR(gal.AND(lit("CFS2"), lit("CFS3", 0)),
                                     gal.AND(lit("T1", 0), lit("CFS3")))), True, False),
        "CFRD_n": (gal.AND(lit("READING"), lit("CFS3"), ok), False, True),
        "CFWR_n": (gal.AND(lit("MEMWR"), lit("CFS3"), ok), False, True)}, clock="MCLK")
    al = nl.add("573", "U_IOAL", LE="IOLE", OE="GND")
    sl = nl.add("573", "U_IOSL", LE="IOLE", OE="GND")
    for i in range(8):
        al[f"D{i + 1}"], al[f"Q{i + 1}"] = VA[2 + i], f"IOA{2 + i}"
        sl[f"D{i + 1}"], sl[f"Q{i + 1}"] = f"IOR{i}_n", f"IOS{i}_n"
    g("04", ["IOA5"], "IOA5_n")
    for k in range(2):
        x = nl.add("245", f"U_IOX{k}", DIR="MEMWR", OE="XOE_n")
        rn = nl.add("pullup", f"RN_IOD{k}")
        for i in range(8):
            x[f"A{i + 1}"], x[f"B{i + 1}"] = DB[8 * k + i], f"IOD{8 * k + i}"
            rn[f"P{i + 1}"] = f"IOD{8 * k + i}"

    nl.section("CF card")
    cf = nl.add("cf", "U_CF", CS0="CFCS0_n", CS1="CFCS1_n", IORD="CFRD_n", IOWR="CFWR_n",
                RESET="RESET_n", INTRQ="CFINT", WAKE="CF_WAKE", params={"sectors": CF_SECTORS})
    for i in range(3):
        cf[f"A{i}"] = f"IOA{2 + i}"
    for i in range(16):
        cf[f"D{i}"] = f"IOD{i}"

    nl.section("Expansion ports")
    # regions 1 and 2: each port's select, the latched address A2-A9, the
    # I/O bus, the strobes, reset and an open-collector interrupt request
    # (pulled up here); the connectors aren't in the netlist
    nl.add("pullup", "RN_EXP", P1="EIRQ1_n", P2="EIRQ2_n")

    nl.section("Timer")
    # region 3, an 82C54 counting the UARTs' 1.8432 MHz (the clock chip's
    # CLKC): counter 0 the periodic interrupt (OUT0 rising sets TFLAG),
    # counter 2 the speaker
    t = nl.add("82c54", "U_PIT", A0="IOA2", A1="IOA3", CS="IOS3_n", RD="IORD_n", WR="IOWR_n",
               OUT0="TOUT0", OUT2="TOUT2", CLK0="UCLK", CLK1="UCLK", CLK2="UCLK",
               GATE0="VCC", GATE1="VCC", GATE2="SPKG")
    for i in range(8):
        t[f"D{i}"] = f"IOD{i}"

    nl.section("Boot flash")
    # region 5: a byte a word, so A0 is VA2; programmable in place
    f = nl.add("flash", "U_BOOT", CE="IOS5_n", OE="IORD_n", WE="IOWR_n")
    for i in range(17):
        f[f"A{i}"] = VA[2 + i]
    for i in range(8):
        f[f"D{i}"] = f"IOD{i}"

    nl.section("UARTs")
    # region 6: UART 0 with A5 low, UART 1 with A5 high
    for k, cs0 in enumerate(["IOA5_n", "IOA5"]):
        ua = nl.add("16c550", f"U_UART{k}", CS0=cs0, CS1="VCC", CS2="IOS6_n", RD="IORD_n",
                    WR="IOWR_n", MR="RESET", XIN="UCLK", INTR=f"UINT{k}")
        for i in range(3):
            ua[f"A{i}"] = f"IOA{2 + i}"
        for i in range(8):
            ua[f"D{i}"] = f"IOD{i}"

    nl.section("Keyboard and mouse")
    # region 4: two PS/2 ports (the keyboard, the mouse; RFC 0041, 22). The
    # lines are open-collector, pulled up; Schmitt inverters give each
    # port's clock (its falling edge rising) and its data inverted. A
    # port's 22V10, clocked by its clock, shifts the inverted data in at
    # each falling edge from S0 to S9, all clear: the start bit's 1
    # reaches S9 after ten, and S9 holds them all then, through the stop
    # bit, and holds the clock low (the device waits) until the host
    # clears it, a write to the port (the asynchronous reset). S8-S1 are
    # the byte's bits 0-7, inverted, onto the I/O bus as the port is read.
    # The host sends by software: the control register's bits pull the
    # lines low, the status register reads them. By IOA[3:2]: 0 the
    # keyboard's byte (read; a write clears it), 1 the mouse's, 2 the
    # status (read: bits 0-1 a byte waiting, 2-3 the keyboard's clock and
    # data, 4-5 the mouse's) and the control register (written: bit 0 the
    # keyboard's clock low, 1 its data low, 2 and 3 the mouse's)
    nl.add("pullup", "RN_PS2", P1="KBCLK", P2="KBDAT", P3="MSCLK", P4="MSDAT")
    nl.add("14", "U_PSI", **{"1A": "KBCLK", "1Y": "KCK0", "2A": "KBDAT", "2Y": "KDI0",
                             "3A": "MSCLK", "3Y": "KCK1", "4A": "MSDAT", "4Y": "KDI1",
                             "5A": "DBGB_n", "5Y": "DBGBTN", "6A": "GND"})
    for k in range(2):
        # S8 - S1 are the I/O bus's bits 0-7 (their registers feed back)
        S_ = [f"KS{k}_0"] + [f"IOD{8 - i}" for i in range(1, 9)] + [f"KS{k}_9"]
        sel = sop(["IOS4_n", "IOA2", "IOA3"], lambda s4, a2, a3: not s4 and a2 == k and not a3)
        rd = gal.AND(sel, lit("IORD_n", 0))
        outs = {}
        for i in range(10):
            d = lit(f"KDI{k}") if i == 0 else lit(S_[i - 1])
            nxt = gal.OR(gal.AND(lit(S_[9], 0), d), gal.AND(lit(S_[9]), lit(S_[i])))
            outs[S_[i]] = (nxt, True, False) + ((rd,) if 1 <= i <= 8 else ())
        ar = gal.OR(lit("RESET_n", 0), gal.AND(sel, lit("IOWR_n", 0)))
        gal.add(nl, f"U_PS{k}", outs, clock=f"KCK{k}", ar=ar)
    if sim:
        # the keyboard and the mouse on their cables
        for ref, (clk, dat) in (("X_KBD", ("KBCLK", "KBDAT")), ("X_MOUSE", ("MSCLK", "MSDAT"))):
            nl.add("ps2dev", ref, CLK=clk, DATA=dat, WAKE=f"{ref}_WAKE", params=PS2_PARAMS)
    nl.add("05", "U_PSO", **{"1A": "KS0_9", "1Y": "KBCLK", "2A": "KCC0", "2Y": "KBCLK",
                             "3A": "KCD0", "3Y": "KBDAT", "4A": "KS1_9", "4Y": "MSCLK",
                             "5A": "KCC1", "5Y": "MSCLK", "6A": "KCD1", "6Y": "MSDAT"})
    nl.add("175", "U_PSC", CLK="PSCW", CLR="RESET_n",
           **{"1D": "IOD0", "1Q": "KCC0", "2D": "IOD1", "2Q": "KCD0",
              "3D": "IOD2", "3Q": "KCC1", "4D": "IOD3", "4Q": "KCD1"})
    st = nl.add("541", "U_PSS", OE1="PSST_n", OE2="GND")
    for i, src in enumerate(["KS0_9", "KS1_9", "KBCLK", "KBDAT", "MSCLK", "MSDAT", "GND",
                             "GND"]):
        st[f"A{i + 1}"], st[f"Y{i + 1}"] = src, f"IOD{i}"
    # the ports' status and control decode, their interrupt, and the
    # suite's I/O page's select: a 22V10
    reg2 = sop(["IOS4_n", "IOA2", "IOA3"], lambda s4, a2, a3: not s4 and not a2 and a3)
    gal.add(nl, "U_KBD", {
        "PSST_n": (gal.AND(reg2, lit("IORD_n", 0)), False, True),
        "PSCW": (gal.AND(reg2, lit("IOWR_n", 0)), False, False),
        "KIRQ": (gal.OR(lit("KS0_9"), lit("KS1_9")), False, False),
        "XSEL_n": (gal.OR(lit("IOR7_n"), lit(VA[21], 0)), False, False)})

    nl.section("On-board registers")
    # region 7 with VA21 low, on the data bus: by VA[12:10], 0 the video's
    # registers, 1 the palette, 2 the interrupt status (a read) and the
    # timer's acknowledge (a write), 3 the control register
    nl.add("138", "U_LOCD", A=VA[10], B=VA[11], C=VA[12], G1="VA21_n", G2A="IOR7_n",
           G2B="GND", Y0="LOC0_n", Y1="LOC1_n", Y2="LOC2_n", Y3="LOC3_n")
    st = nl.add("541", "U_ISR", OE1="LOC2_n", OE2="IORD_n")
    for i, src in enumerate(["UINT0", "UINT1", "CFINT", "TFLAG", "VIRQ", "EIRQ1_n", "EIRQ2_n",
                             "IRQ"]):
        st[f"A{i + 1}"], st[f"Y{i + 1}"] = src, DB[i]
    # the timer's acknowledge, the control register's strobe, the speaker,
    # the interrupt line (any device's request): a 22V10
    reqs = ["UINT0", "UINT1", "CFINT", "TFLAG", "VIRQ", "XIRQ", "KIRQ"]
    gal.add(nl, "U_ONB", {
        "TCLR_n": (gal.AND(lit("RESET_n"), gal.OR(lit("LOC2_n"), lit("IOWR_n"))), False, False),
        "CTLW": (gal.OR(lit("LOC3_n"), lit("IOWR_n")), False, False),
        "SPK": (gal.AND(lit("TOUT2"), lit("SPKD")), False, False),
        "IRQ": (gal.OR(*[lit(r) for r in reqs], lit("EIRQ1_n", 0), lit("EIRQ2_n", 0)),
                False, False)})
    # the control register: the speaker's gate and data, two LEDs
    nl.add("175", "U_CTL", CLK="CTLW", CLR="RESET_n",
           **{"1D": DB[0], "1Q": "SPKG", "2D": DB[1], "2Q": "SPKD",
              "3D": DB[2], "3Q": "LED0", "4D": DB[3], "4Q": "LED1"})

    # the suite's I/O page: a test card in region 7 with VA21 high, on the
    # data bus. It takes a read at CLK's edge, so its read strobe lasts the
    # cycle
    nl.section("I/O")
    g("10", ["READING", "LATE", "FAULT_n"], "IORDX_n")
    x = nl.add("iodev_w32", "X_IO", CLK="CLK", IOSEL="XSEL_n", RD="IORDX_n", WR="IOWR_n",
               IRQ="XIRQ")
    for i in range(2, 8):
        x[f"A{i}"] = VA[i]
    for i in range(4):
        x[f"BE{i}"] = f"BE{i}_n"
    for i in range(32):
        x[f"D{i}"] = DB[i]

def build(sim=False, lengths=None, por_ps=2_000_000, capture=False, xlengths=None,
          debug_ps=0):
    """The netlist: for the chip-level simulator (sim) or static timing
    analysis; `lengths` and `xlengths` the length classes' ticks at
    VGA's master clock and XGA's (the microcode's by default); the frame
    grabber (capture); the debug button pressed at debug_ps."""
    nl = Netlist()
    g = nl.gate
    U = control_nets()
    u = {v[1:]: v for v in U.values()}          # u["SEQ0"] -> "uSEQ0", u["ARF_n"] ...
    if lengths is None:
        lengths = uc.built().lengths
    if xlengths is None:
        xlengths = uc.built().xlengths if lengths == uc.built().lengths else lengths
    lengths = tuple(lengths) + (lengths[-1],) * (4 - len(lengths))
    xlengths = tuple(xlengths) + (xlengths[-1],) * (4 - len(xlengths))

    ABUS, BBUS, F, RES = bus("ABUS", 32), bus("BBUS", 32), bus("F", 32), bus("RES", 32)
    VA, DB = bus("VA", 32), bus("DB", 32)
    IR, QH, Y = bus("IR", 16), bus("QH", 16), bus("Y", uc.Y_BITS)
    RQ, TQ = bus("RQ", 32), bus("TQ", 32)
    MAR, PC = bus("MAR", 32), ["GND"] + bus("PC", 31, 1)
    FPC = ["GND", "GND"] + bus("FPC", 20, 2) + ["GND"] * 10
    LC, SX, EX = bus("LC", 8), bus("SX", 4), bus("EX", 4)

    # ---- clock, reset, rails ------------------------------------------------------
    if sim:
        clock_generator(nl, lengths, xlengths, por_ps)
    else:
        # for static timing analysis: the clock generator's outputs as
        # functions of the cycle (CLK's edge at 0), and its other phases
        # as they are in the cycle's first part
        nl.add("tickclk", "X_CLK", CLK="CLK", MWIN="MWIN", LATE="LATE", PHASE="H1", RW="RW",
               RSTB="T2", RESET="RESET_n")
        # RW_n is K2's output, as RW is: high in the read phase, falling as
        # RW rises (sta.py's tail checks)
        nl.add("const", "X_RW_n", HI="RW_n")
        for net in ("T1", "TCRCO", "MCLK", "H0", "H2"):
            nl.add("const", f"X_{net}", LO=net)
        nl.add("const", "X_HOLD", LO="HOLD", HI="HOLD_n")
        nl.add("const", "X_IOSTB", LO="IOSTB")
        nl.add("const", "X_DBG", LO="DBGBTN")
    nl.add("const", "X_RAIL", LO="GND", HI="VCC")
    nl.section("Reset")
    g("04", ["RESET_n"], "RESET")

    # ---- control store -------------------------------------------------------------
    nl.section("Control store")
    YU = ["YU0", "YU1", "YU2"]
    for k in range(uc.WORD_BITS // 8):
        rom = nl.add("flash", f"U_CS{k}", CE="GND", OE="GND", WE="VCC")
        for i in range(17):
            rom[f"A{i}"] = Y[i] if i < uc.Y_BITS else (YU[i - uc.Y_BITS] if i < 16 else "DECGO")
        for i in range(8):
            rom[f"D{i}"] = f"UD{8 * k + i}"
        r = nl.add("574", f"U_UIR{k}", CLK="CLK", OE="GND")
        for i in range(8):
            r[f"D{i + 1}"] = f"UD{8 * k + i}"
            if 8 * k + i in U:
                r[f"Q{i + 1}"] = U[8 * k + i]

    nl.section("Instruction register")
    for half in (0, 1):
        r = nl.add("377", f"U_IR{half}", CLK="CLK", EN="DECGO_n")
        for i in range(8):
            r[f"D{i + 1}"], r[f"Q{i + 1}"] = QH[8 * half + i], IR[8 * half + i]

    # ---- next address ---------------------------------------------------------------
    nl.section("Next address")
    # the condition, by COND: with COND3 low, NEXT0, TC, R31, CL, the
    # branch condition, MQ31, TC4 or the branch condition's complement;
    # with it high, PEND, SX = EX, the debug request, -, SX15, MQ0 or R0. A
    # 22V10
    COND = [u[f"COND{i}"] for i in range(4)]
    gal.add(nl, "U_CNY", {"CONDY": (gal.mux(COND, [
        lit(u["NEXT0"]), lit("TC"), lit(RQ[31]), lit("CLQ"), lit("CONDT"), lit("MQ31"), lit("TC4"),
        lit("CONDT", 0), lit("PEND"), lit("SXEQ_n", 0), lit("DBGQ"), 0, lit("SX15"), lit("MQ0"),
        lit(RQ[0]),
        0]), False, False)})
    for k in range((uc.Y_BITS + 1) // 2):
        m = nl.add("153", f"U_YM{k}", A=u["SEQ0"], B=u["SEQ1"], **{"1G": "YG", "2G": "YG"})
        for sec in (0, 1):
            i = 2 * k + sec
            if i >= uc.Y_BITS:
                for c in range(4):
                    m[f"{sec + 1}C{c}"] = "GND"
                continue
            nxt = "CONDY" if i == 0 else u[f"NEXT{i}"]
            disp = QH[8 + i] if i < 4 else u[f"NEXT{i}"]
            for c, s_ in enumerate([nxt, QH[i], disp, u[f"NEXT{i}"]]):
                m[f"{sec + 1}C{c}"] = s_
            m[f"{sec + 1}Y"] = Y[i]
    # the decode's glue, a 22V10. SEQ 1 decode (DEC, from the uIR), 3 halt;
    # the forced entries (refill 001, interrupt 010), which fill their
    # pages, so that only E and U change; and the decode that goes ahead
    # (DECGO): its first microinstruction at {1, QH}. The first parcel is
    # there: in Q0, or (a refill) in the word it fetches (CANDEC). A decode
    # in a cycle that may jump (LDPC) goes to the refill whether it jumps
    # or not, so that the jump's condition isn't on the control store's
    # address: the refill decodes from the queue if it still holds the
    # instruction. Y's low bits are 0 in a decode that can't have its first
    # parcel (a transparent slot, the data bus moving): the refill's page
    # doesn't care, and the address is stable (YG). Nor in an address error
    # (FAULT), whose page is U = 1LL, LL the parcels its instruction has
    # consumed (the microinstruction's own): the IR, the PC and the next
    # address. The queue's (DECGOQ, in DECGOP) is as if there were none,
    # keeping FAULT off its paths: the fault's microcode ends in a jump,
    # which empties it, and reads nothing from it before. In a reset, Y,
    # YU and YE (DECGO) are 0
    DEC = u["DEC"]
    candec = gal.OR(lit("V0"), lit(u["REF"]))
    nocan = gal.AND(lit("V0", 0), lit(u["REF"], 0))
    goq = gal.AND(lit(DEC), lit("PEND", 0), lit(u["LDPC"], 0), candec)
    decgo = gal.AND(goq, lit("FAULT", 0), lit("RESET", 0))
    uf0 = gal.AND(lit(DEC), lit("PEND", 0), gal.OR(nocan, lit(u["LDPC"])))
    firq = gal.AND(gal.OR(lit(DEC), gal.AND(lit(u["SEQ0"]), lit(u["SEQ1"]))), lit("PEND"))
    ua = [gal.OR(gal.AND(lit("FAULT"), lit(u["LL0"])), gal.AND(lit("FAULT", 0), uf0)),
          gal.OR(gal.AND(lit("FAULT"), lit(u["LL1"])), gal.AND(lit("FAULT", 0), firq)),
          lit("FAULT")]
    seq = {"DECGO": (decgo, False, False), "DECGO_n": (decgo, False, True),
           "DECGOP": (gal.AND(goq, lit("PC1F")), False, False),
           "YG": (gal.OR(gal.AND(lit(DEC), nocan), lit("RESET")), False, False)}
    for i in range(3):
        seq[f"YU{i}"] = (gal.AND(lit("RESET", 0), gal.OR(gal.AND(lit("DECGO"), lit(QH[13 + i])),
                                                         gal.AND(lit("DECGO", 0), ua[i]))),
                         False, False)
    gal.add(nl, "U_SEQ", seq)
    # the branch condition (CONDT, the condition before cc's low bit
    # inverts it) and the jump: LDPC, always / on the branch condition / on
    # not CL; the PC's (PCJ_n) none in an address error (the queue's and
    # FPC's, JUMP, as the decode's). A 22V10
    CC = bus("CC", 4)
    nv = gal.OR(gal.AND(lit("NFLAG"), lit("VFLAG")), gal.AND(lit("NFLAG", 0), lit("VFLAG", 0)))
    condt = gal.mux(CC[1:], [lit("ZFLAG"), lit("CFLAG"), lit("NFLAG"), lit("VFLAG"),
                             gal.AND(lit("CFLAG"), lit("ZFLAG", 0)), nv,
                             gal.AND(lit("ZFLAG", 0), nv), 1])
    bcond = gal.OR(gal.AND(lit("CONDT"), lit(CC[0], 0)), gal.AND(lit("CONDT", 0), lit(CC[0])))
    jump = gal.AND(lit(u["LDPC"]), gal.mux([u["PCCOND0"], u["PCCOND1"]],
                                            [1, bcond, lit("CLQ", 0), 0]))
    gal.add(nl, "U_BRC", {"CONDT": (condt, False, False), "JUMP": (jump, False, False),
                          "JUMP_n": (jump, False, True),
                          "PCJ_n": (gal.AND(jump, lit("FAULT", 0)), False, True)})

    nl.section("Interrupt request")
    # the interrupt line, active high, registered at every edge (IRQQ); a
    # cycle later, with I as it is in the cycle, PEND; or the debug
    # request, whatever I
    nl.add("74", "U_IRQ", nocheck=True,
           **{"1D": "IRQ", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "RESET_n", "1Q": "IRQQ",
              "2D": "PEND_D", "2CLK": "CLK", "2PRE": "VCC", "2CLR": "RESET_n",
              "2Q": "PEND", "2QN": "PEND_n"})
    # the debug button (a push button to ground, a Schmitt inverter: DBGBTN
    # high while it's pressed), synchronised to CLK. A press sets DBGQ,
    # which raises PEND: the interrupt entry's microcode sees DBGQ (COND
    # 10) and takes the debug entry instead. DBGQ clears once the interrupt
    # entry runs (ENT: the interrupt's page, 010, was the address). A 22V10
    if sim:
        nl.add("button", "U_DBGB", OUT="DBGB_n",
               params={"press_ps": debug_ps, "release_ps": debug_ps + 2_000_000_000}
               if debug_ps else {})
    nl.add("74", "U_DBS", nocheck=True,
           **{"1D": "DBGBTN", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "RESET_n", "1Q": "DBS1",
              "2D": "GND", "2CLK": "GND", "2PRE": "VCC", "2CLR": "VCC"})
    gal.add(nl, "U_DBG", {
        "DBS2": (lit("DBS1"), True, False),
        "ENT": (gal.AND(lit("YU0", 0), lit("YU1"), lit("YU2", 0), lit("DECGO", 0)), True, False),
        "DBGQ": (gal.AND(lit("RESET_n"), gal.OR(gal.AND(lit("DBS1"), lit("DBS2", 0)),
                                                gal.AND(lit("DBGQ"), lit("ENT", 0)))), True,
                 False),
        "PEND_D": (gal.OR(gal.AND(lit("IRQQ"), lit("IFLAG")), lit("DBGQ")), False, False)},
        clock="CLK")

    # ---- register file -----------------------------------------------------------
    # two copies of 32 x 32 bits (r0-r15, then the microcode's own), read
    # through latches in the cycle's first part, written in its last tick
    nl.section("Register file")
    # one copy, read twice in a cycle that reads B from it (BRF): the A
    # address until the late phase (H0 and H1 over, as LATE says, but
    # from the clock generator's registers, a GAL sooner), its latches
    # closing then, the B address after;
    # the write address in the tail (RW). The addresses and the A latches'
    # enable from three 22V10s. The address moves on from A only once RLEA
    # has closed the A latches, and from B once RW_n has closed the B
    # latches: a gate's delay after them, for the latches' hold. The SRAMs
    # drive their data until the write's tick (T2), so that the B read has
    # until the B latches close, which is after RW: off at RW, they cut a
    # B read short in a 5-tick cycle, the latches keeping the A read's
    # data. T2 turns them off (tOHZ, 3 ns) as the write buffers come on
    # (a NAND and their enable after it, 2.9 ns at the least)
    g("10", [u["RFWE"], "T2", "FAULT_n"], "RFWE_n")
    g("10", [u["RFWE"], "T2", "FAULT_n"], "RFWB_n")
    AM = bus("RFAM", 5)
    a_ph = lit("RLEA")
    b_ph = gal.AND(lit("RLEA", 0), lit("RW_n"))
    w_ph = gal.AND(lit("RLEA", 0), lit("RW_n", 0))

    def src(sel, i, k):
        rd = [lit(IR[12 + i]), lit(IR[8 + i]), lit(SX[i]), lit(u[f"{k}{i}"])] if i < 4 else \
            [0, 0, 0, lit(u[f"{k}{i}"])]
        return gal.mux([u[f"{sel}0"], u[f"{sel}1"]], rd)

    def addr(i):
        return (gal.OR(gal.AND(a_ph, src("RFA", i, "RFK")), gal.AND(b_ph, src("RFB", i, "RFK")),
                       gal.AND(w_ph, src("RFW", i, "RFKW"))), False, False)
    gal.add(nl, "U_RFG0", {AM[0]: addr(0), AM[1]: addr(1)})
    gal.add(nl, "U_RFG1", {AM[2]: addr(2), AM[3]: addr(3)})
    gal.add(nl, "U_RFG2", {AM[4]: addr(4),
                           "RLEA": (gal.AND(lit("RW", 0), gal.OR(lit("H0"), lit("H1"),
                                                                 lit(u["BRF_n"]))),
                                    False, False)})
    IO = bus("RFAIO", 32)
    for k in range(4):
        ram = nl.add("sram", f"U_RFA{k}", role="rf", CE="GND", OE="T2", WE="RFWE_n")
        for i in range(15):
            ram[f"A{i}"] = AM[i] if i < 5 else "GND"
        for i in range(8):
            ram[f"IO{i}"] = IO[8 * k + i]
        la = nl.add("573", f"U_RLA{k}", LE="RLEA", OE=u["ARF_n"])
        lb = nl.add("573", f"U_RLB{k}", LE="RW_n", OE="BRFE_n")
        buf = nl.add("541", f"U_RWA{k}", OE1="RFWB_n", OE2="RFWB_n")
        for i in range(8):
            la[f"D{i + 1}"], la[f"Q{i + 1}"] = IO[8 * k + i], ABUS[8 * k + i]
            lb[f"D{i + 1}"], lb[f"Q{i + 1}"] = IO[8 * k + i], BBUS[8 * k + i]
            buf[f"A{i + 1}"], buf[f"Y{i + 1}"] = RES[8 * k + i], IO[8 * k + i]

    # ---- A bus -------------------------------------------------------------------
    nl.section("A bus")
    nl.add("153", "U_SINA", A=u["SINA0"], B=u["SINA1"],
           **{"1G": "GND", "2G": "VCC", "1C0": "GND", "1C1": RQ[31], "1C2": "CFLAG",
              "1C3": "MQ31", "1Y": "SINA", "2C0": "GND", "2C1": "GND", "2C2": "GND", "2C3": "GND"})
    R2 = ["SINA"] + RQ[:31]
    PCA = [u["PCK"]] + PC[1:]
    for k in range(4):
        for ref, src, oe in ((f"U_APC{k}", PCA, u["APC_n"]), (f"U_AR{k}", RQ, u["AR_n"]),
                             (f"U_AR2{k}", R2, u["AR2_n"])):
            b = nl.add("541", ref, OE1=oe, OE2=oe)
            for i in range(8):
                b[f"A{i + 1}"], b[f"Y{i + 1}"] = src[8 * k + i], ABUS[8 * k + i]

    # ---- B bus -------------------------------------------------------------------
    nl.section("B bus")
    # the enables straight from the uIR pass a gate, so that they come on
    # about when the decoded ones (below) of the cycle before go off
    for f in ("BRF", "BR", "BF1", "BF23"):
        g("32", [u[f"{f}_n"], "GND"], f"{f}E_n")
    for k in range(4):
        b = nl.add("541", f"U_BR{k}", OE1="BRE_n", OE2="BRE_n")
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = RQ[8 * k + i], BBUS[8 * k + i]
    # T by lanes (BL 1 word, 2 half, 3 byte, moved down to the low lanes by
    # TL, the access's address), and the queue's head (4 as it is, 5 x 2,
    # 6 in the upper half, 7 its low byte)
    bl = nl.add("138", "U_BLD", A=u["BL0"], B=u["BL1"], C=u["BL2"], G1="VCC", G2A="GND", G2B="GND")
    for v, name in ((1, "BLW_n"), (4, "BLQ_n"), (5, "BLQ2_n"), (6, "BLQH_n")):
        bl[f"Y{v}"] = name
    # T's lanes onto B, by BL and TL (a 22V10, from TL as T's latch gives
    # it): the low byte from lane 0 (word, half, byte 0), lane 2 (half 2,
    # byte 2), lane 1 or lane 3 (bytes); the second byte from lane 1 (word,
    # half 0) or lane 3 (half 2); BQ0_n, the queue head's low byte (qh, qhb).
    # And T's latches' enable, transparent while memory is read into them
    # from tick 2 until the tail: from the clock generator's H0 and H1, a
    # 22V10 sooner than LATE's gate (as the register file's A latches)
    BLn = [u["BL0"], u["BL1"], u["BL2"]]

    def lanes(name):
        def f(b0, b1, b2, t0, t1):
            bl_, tl = b0 + 2 * b1 + 4 * b2, t0 + 2 * t1
            return {"BT0_n": bl_ == 1 or (bl_ == 2 and tl < 2) or (bl_ == 3 and tl == 0),
                    "BT1_n": bl_ == 1 or (bl_ == 2 and tl < 2),
                    "BT20_n": (bl_ == 2 and tl >= 2) or (bl_ == 3 and tl == 2),
                    "TH1_n": bl_ == 2 and tl >= 2,
                    "TB1_n": bl_ == 3 and tl == 1,
                    "TB3_n": bl_ == 3 and tl == 3,
                    "BQ0_n": bl_ in (4, 7)}[name]
        return gal.table(BLn + ["TL0", "TL1"], f)
    btl = {n: (lanes(n), False, True)
           for n in ("BT0_n", "BT1_n", "BT20_n", "TH1_n", "TB1_n", "TB3_n", "BQ0_n")}
    btl["TLE"] = (gal.AND(lit("READING"), lit("RW_n"), lit("H0", 0), lit("H1", 0)), False, False)
    gal.add(nl, "U_BTL", btl)
    tb = [TQ[8 * k:8 * k + 8] for k in range(4)]
    QH2 = ["GND"] + QH[:15]
    for ref, src, dst, oe in (("U_BT0", tb[0], 0, "BT0_n"), ("U_BT1", tb[1], 1, "BT1_n"),
                              ("U_BT2", tb[2], 2, "BLW_n"), ("U_BT3", tb[3], 3, "BLW_n"),
                              ("U_BT20", tb[2], 0, "BT20_n"), ("U_BT31", tb[3], 1, "TH1_n"),
                              ("U_BT10", tb[1], 0, "TB1_n"), ("U_BT30", tb[3], 0, "TB3_n"),
                              ("U_BQ0", QH[0:8], 0, "BQ0_n"), ("U_BQ1", QH[8:16], 1, "BLQ_n"),
                              ("U_BQ20", QH2[0:8], 0, "BLQ2_n"), ("U_BQ21", QH2[8:16], 1, "BLQ2_n"),
                              ("U_BQH2", QH[0:8], 2, "BLQH_n"), ("U_BQH3", QH[8:16], 3, "BLQH_n")):
        b = nl.add("541", ref, OE1=oe, OE2=oe)
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = src[i], BBUS[8 * dst + i]

    nl.section("Immediate unit")
    nl.add("151", "U_FILLM", A=u["FSEL0"], B=u["FSEL1"], C=u["FSEL2"], G="GND", Y="FILL",
           D0="GND", D1="VCC", D2="GND", D3=QH[15], D4=QH[7], D5=ABUS[31], D6=ABUS[15],
           D7="SGNQ")
    # byte 0: the constant (V8 1), the fill (2) or LC (3), while BS0
    g("04", [u["V80"]], "V80_n")
    g("04", [u["V81"]], "V81_n")
    g("27", [u["BS0_n"], u["V81"], "GND"], "BSK")
    g("04", ["BSK"], "BSK_n")
    g("20", [u["V81"], "V80_n", "BS0", "VCC"], "BSF_n")
    g("20", [u["V81"], u["V80"], "BS0", "VCC"], "BSL_n")
    g("04", [u["BS0_n"]], "BS0")
    for ref, src, dst, oe in (("U_BSK", [u[f"KONST{i}"] for i in range(8)], 0, "BSK_n"),
                              ("U_BSF", ["FILL"] * 8, 0, "BSF_n"),
                              ("U_BSL", LC, 0, "BSL_n"),
                              ("U_BF1", ["FILL"] * 8, 1, "BF1E_n"),
                              ("U_BF2", ["FILL"] * 8, 2, "BF23E_n"),
                              ("U_BF3", ["FILL"] * 8, 3, "BF23E_n")):
        b = nl.add("541", ref, OE1=oe, OE2=oe)
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = src[i], BBUS[8 * dst + i]

    nl.section("B bus")
    # BX: 1 MQ, 2 the flags word (V C Z N I in byte 0; the immediate unit's
    # zero fill in bytes 1-3). Its bit 0 is stored inverted, so that each
    # is a gate from the uIR, as the other enables are
    g("32", [u["BX0_n"], u["BX1"]], "BXMQ_n")
    g("00", [u["BX0_n"], u["BX1"]], "BXFL_n")
    b = nl.add("541", "U_BFL", OE1="BXFL_n", OE2="BXFL_n")
    for i, src in enumerate(["VFLAG", "CFLAG", "ZFLAG", "NFLAG", "IFLAG", "GND", "GND", "GND"]):
        b[f"A{i + 1}"], b[f"Y{i + 1}"] = src, BBUS[i]

    # ---- MQ ------------------------------------------------------------------------
    nl.section("MQ")
    # 4 x 74F299 on the B bus. Chip k holds bits 8k..8k+7 with I/O n = bit
    # 8k+7-n, so the shift toward Q7 is a right shift of MQ (DS0 in at the
    # top), toward Q0 a left shift (DS7 in at the bottom).

    def mqs(bit):
        return {0: "MQ0", 31: "MQ31"}.get(bit, f"MQS{bit}")
    for k in range(4):
        sr = nl.add("299", f"U_MQ{k}", S0=u["MQM0"], S1=u["MQM1"], OE1="BXMQ_n", OE2="GND",
                    MR="VCC", CP="CLK", Q0S=mqs(8 * k + 7), Q7S=mqs(8 * k))
        for n in range(8):
            sr[f"IO{n}"] = BBUS[8 * k + 7 - n]
        sr["DS0"] = F[0] if k == 3 else mqs(8 * (k + 1))
        sr["DS7"] = "QBIT" if k == 0 else mqs(8 * (k - 1) + 7)

    # ---- ALU control, ALU, result multiplexer (draft 1b's) -----------------------------
    nl.section("ALU control")
    # MS 0: S from the uIR; 1 add if MQ[0]; 2 subtract if MQ[0]; 3 add if
    # S33, else subtract (divide) or pass (MQM 0, the fix-up)
    g("08", ["S33_n", u["MQM1"]], "GSDIV")
    SE = bus("SE", 4)
    for k, (lo, hi), data in ((0, (0, 3), ["MQ0", "GND", "S33Q"]),
                              (1, (1, 2), ["GND", "MQ0", "GSDIV"])):
        m = nl.add("153", f"U_SM{k}", A=u["MS0"], B=u["MS1"], **{"1G": "GND", "2G": "GND"})
        for sec, i in ((1, lo), (2, hi)):
            for c, src in enumerate([u[f"S{i}"]] + data):
                m[f"{sec}C{c}"] = src
            m[f"{sec}Y"] = SE[i]
    nl.add("151", "U_CINM", A=u["CIN0"], B=u["CIN1"], C=u["CIN2"], G="GND", W="CIN_n",
           D0="GND", D1="VCC", D2="CFLAG", D3=ABUS[31], D4="MQ31", D5="SGNQ", D6="MQ0", D7="S33_n")

    nl.section("ALU")
    cn = ["CIN_n", "C4_n", "C8_n", "C12_n", "C16_n", "C20_n", "C24_n", "C28_n"]
    for k in range(8):
        a = nl.add("181", f"U_ALU{k}", M=u["M"], CN=cn[k], P=f"ALUP{k}", G=f"ALUG{k}",
                   **{f"S{i}": SE[i] for i in range(4)})
        for i in range(4):
            a[f"A{i}"], a[f"B{i}"], a[f"F{i}"] = ABUS[4 * k + i], BBUS[4 * k + i], F[4 * k + i]
        if k == 7:
            a["CN4"] = "CARRY_n"
    # the carries C4-C28 in one level: a 22V10 from the 74F181s' P and G
    # (low for propagate and generate) and the carry in (low for a carry),
    # each carry out low for a carry, as three 74F182s gave them in two
    carry, outs = lit("CIN_n", 0), {}
    for k in range(1, 8):
        carry = gal.OR(lit(f"ALUG{k - 1}", 0), gal.AND(lit(f"ALUP{k - 1}", 0), carry))
        outs[f"C{4 * k}_n"] = (carry, False, True)
    gal.add(nl, "U_CLAG", outs)
    g("04", ["CARRY_n"], "C32")
    # overflow: V = (A31 ^ B31 ^ S0) & (A31 ^ F31)
    g("86", [BBUS[31], SE[0]], "VT1")
    g("86", [ABUS[31], "VT1"], "VT2")
    g("86", [ABUS[31], F[31]], "VT3")

    nl.section("Result multiplexer")
    g("04", [u["MQM1"]], "MQM1_n")
    g("08", [u["MQM0"], "MQM1_n"], "MULSTEP")
    nl.add("157", "U_MSGN", S="VT2", G="GND",
           **{"1A": F[31], "1B": ABUS[31], "1Y": "MSIGN",
              "2A": "GND", "2B": "GND", "3A": "GND", "3B": "GND", "4A": "GND", "4B": "GND"})
    nl.add("151", "U_SINM", A=u["SIN0"], B=u["SIN1"], C="MULSTEP", G="GND", Y="SINE",
           D0="GND", D1=F[31], D2="CFLAG", D3=F[0], D4="C32", D5="MSIGN", D6="GND", D7="GND")
    for k in range(16):
        byte = k // 4
        m = nl.add("153", f"U_RES{k}", A=u["RMS0"], B=u["RMS1"],
                   **{"1G": u[f"RZ{byte}"], "2G": u[f"RZ{byte}"]})
        for sec in (0, 1):
            i = 2 * k + sec
            srcs = [F[i], "SINE" if i == 31 else F[i + 1], F[(i + 8) % 32], F[(i + 16) % 32]]
            for c, s in enumerate(srcs):
                m[f"{sec + 1}C{c}"] = s
            m[f"{sec + 1}Y"] = RES[i]

    # ---- registers ------------------------------------------------------------------
    nl.section("R and T")
    for k in range(4):
        r = nl.add("377", f"U_R{k}", CLK="CLK", EN=u["LDR_n"])
        for i in range(8):
            r[f"D{i + 1}"], r[f"Q{i + 1}"] = RES[8 * k + i], RQ[8 * k + i]
    # T, and TL (the access's address bits 1-0): latches, transparent while
    # memory is read into them, from tick 2 until the tail (TLE: U_BTL)
    for k in range(4):
        t = nl.add("573", f"U_T{k}", LE="TLE", OE="GND")
        for i in range(8):
            t[f"D{i + 1}"], t[f"Q{i + 1}"] = DB[8 * k + i], TQ[8 * k + i]
    nl.add("573", "U_TL", LE="TLE", OE="GND", D1=VA[0], Q1="TL0", D2=VA[1], Q2="TL1",
           **{f"D{i}": "GND" for i in range(3, 9)})

    nl.section("MAR")
    # bits 1-0 and 31-28 load; 21-2 load or count by 4 (MARINC); 27-22 aren't
    # kept: the RAM is 4 MB, and the I/O regions repeat
    nl.add("161", "U_MARL", CLK="CLK", CLR="VCC", LOAD=u["LDMAR_n"], ENP="GND", ENT="GND",
           A=RES[0], B=RES[1], C="GND", D="GND", QA=MAR[0], QB=MAR[1])
    counter_chain(nl, "MAR", MAR, RES, 2, 5, u["LDMAR_n"], u["MARINC"])
    nl.add("161", "U_MARH", CLK="CLK", CLR="VCC", LOAD=u["LDMAR_n"], ENP="GND", ENT="GND",
           A=RES[28], B=RES[29], C=RES[30], D=RES[31], QA=MAR[28], QB=MAR[29], QC=MAR[30],
           QD=MAR[31])

    nl.section("Loop counter")
    nl.add("161", "U_LC0", CLK="CLK", CLR="VCC", LOAD=u["LDLC_n"], ENP=u["LCINC"], ENT="VCC",
           A=RES[0], B=RES[1], C=RES[2], D=RES[3], QA=LC[0], QB=LC[1], QC=LC[2], QD=LC[3],
           RCO="TC4")
    nl.add("161", "U_LC1", CLK="CLK", CLR="VCC", LOAD=u["LDLC_n"], ENP=u["LCINC"], ENT="TC4",
           A=RES[4], B=RES[5], C=RES[6], D=RES[7], QA=LC[4], QB=LC[5], QC=LC[6], QD=LC[7],
           RCO="TC")

    nl.section("SX and EX")
    # LDSX: 1 IR[15:12], 3 the queue head's QH[15:12], 2 count
    m = nl.add("157", "U_SXM", S=u["LDSX1"], G="GND")
    for i in range(4):
        m[f"{i + 1}A"], m[f"{i + 1}B"], m[f"{i + 1}Y"] = IR[12 + i], QH[12 + i], f"SXD{i}"
    g("04", [u["LDSX0"]], "SXLD_n")
    g("04", [u["LDSX0"]], "LDSX0_n")
    g("08", [u["LDSX1"], "LDSX0_n"], "SXEN")
    nl.add("161", "U_SX", CLK="CLK", CLR="VCC", LOAD="SXLD_n", ENP="SXEN", ENT="VCC",
           A="SXD0", B="SXD1", C="SXD2", D="SXD3", QA=SX[0], QB=SX[1], QC=SX[2], QD=SX[3])
    m = nl.add("157", "U_EXM", S=u["LDEX1"], G="GND")
    for j in range(4):
        m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = IR[8 + j], QH[12 + j], f"EXD{j}"
    g("02", [u["LDEX0"], u["LDEX1"]], "EXLD_n")
    nl.add("377", "U_EX", CLK="CLK", EN="EXLD_n",
           **{f"D{j + 1}": f"EXD{j}" for j in range(4)},
           **{f"Q{j + 1}": EX[j] for j in range(4)},
           **{f"D{j}": "GND" for j in range(5, 9)})
    nl.add("521", "U_SXEQ", G="GND", PEQ="SXEQ_n",
           **{f"P{i}": SX[i] if i < 4 else "GND" for i in range(8)},
           **{f"Q{i}": EX[i] if i < 4 else "GND" for i in range(8)})
    g("21", SX, "SX15")

    # ---- PC, FPC and the prefetch queue ----------------------------------------------
    nl.section("PC")
    # a decode that goes ahead consumes its first parcel; a cycle that
    # consumes has no data access (the microcode's rules). A consume in a
    # cycle that jumps needn't be masked: the PC loads, and the queue
    # empties, whichever slot is then the head. (Masked, the jump's
    # condition was on the queue slots' flip-flops' path, through SHIFT.)
    g("32", [u["CONSUME"], "DECGO"], "CONSUMEX")
    counter_chain(nl, "PC", PC, RES, 1, 8, "PCJ_n", "CONSUMEX")
    counter_chain(nl, "FPC", FPC, RES, 2, 5, "JUMP_n", "FPCINC")
    # (PC[1] again, PC1F, for the queue's head: in the queue's 22V10)

    nl.section("Prefetch queue")
    # the queue's state, a 22V10 on CLK: V0 and V1, the words it holds; HS,
    # the slot of its head; PC1F, PC[1] again for the head's parcel (the
    # result's bit 1 when the PC loads, else toggled by a consume; 0 in a
    # reset). Their next states are outputs too, for the slots' flip-flops.
    # A fetch: in any cycle without a data access, if Q1 is free; the word
    # goes into the empty slot (Q0's, slot HS, if the queue is empty). The
    # head word is used up when its high parcel is consumed (SHIFT). The
    # queue's words after the edge: n = V0 + V1 + fetched - shifted, none
    # after a jump
    fetched = gal.AND(lit("FETCHCYC"), lit("V1", 0))
    shift = gal.OR(gal.AND(lit(u["CONSUME"]), lit("PC1F")), lit("DECGOP"))
    noshift = gal.OR(gal.AND(lit("DECGOP", 0), lit(u["CONSUME"], 0)),
                     gal.AND(lit("DECGOP", 0), lit("PC1F", 0)))
    v0d = gal.AND(lit("JUMP", 0), gal.OR(lit("V1"), gal.AND(lit("V0"), fetched),
                                          gal.AND(gal.OR(lit("V0"), fetched), noshift)))
    v1d = gal.AND(lit("JUMP", 0), noshift, gal.OR(lit("V1"), gal.AND(lit("V0"), fetched)))
    hsd = gal.OR(gal.AND(lit("HS"), noshift), gal.AND(lit("HS", 0), shift))
    consumex = gal.OR(lit(u["CONSUME"]), lit("DECGO"))
    toggle = gal.OR(gal.AND(lit("PC1F"), lit(u["CONSUME"], 0), lit("DECGO", 0)),
                    gal.AND(lit("PC1F", 0), consumex))
    pc1f = gal.AND(lit("RESET", 0), gal.OR(gal.AND(lit("PCJ_n", 0), lit(RES[1])),
                                           gal.AND(lit("PCJ_n"), toggle)))
    gal.add(nl, "U_QGA", {"V0": (v0d, True, False), "V1": (v1d, True, False),
                          "HS": (hsd, True, False), "PC1F": (pc1f, True, False),
                          "V0_D": (v0d, False, False), "V1_D": (v1d, False, False),
                          "HS_D": (hsd, False, False),
                          "FPCINC": (gal.AND(fetched, lit("JUMP", 0)), False, False)},
            clock="CLK")
    # two slots, latches from the data bus: Q0 is slot HS and Q1 the other.
    # A slot is transparent while it is empty, from the cycle's start (so
    # that a word fetched for the decode, or for a parcel the cycle reads,
    # reaches the head at once) until the tail: QLE, J-K a slot on the
    # master clock, set at the CPU clock's edge (entering H0) if the slot
    # is empty after it, cleared then if not and entering T1 (TCRCO); and
    # the head parcel's three-state bus, slot HS's half by PC1F. A 22V10
    qle = {}
    for k in range(2):
        mine, other = ("V0_D", "V1_D") if k == 0 else ("V1_D", "V0_D")
        empty = gal.OR(gal.AND(lit("HS_D", 0), lit(mine, 0)), gal.AND(lit("HS_D"), lit(other, 0)))
        q = f"QLE{k}"
        qle[q] = (gal.OR(gal.AND(lit("T2"), empty, lit(q, 0)),
                         gal.AND(lit("T2", 0), lit("TCRCO", 0), lit(q)),
                         gal.AND(empty, lit("TCRCO", 0), lit(q))), True, False)
    for sl in range(2):
        for half, pv in (("L", 0), ("H", 1)):
            qle[f"QH{sl}{half}_n"] = (gal.AND(lit("HS", sl), lit("PC1F", pv)), False, True)
    gal.add(nl, "U_QGB", qle, clock="MCLK")
    for sl in range(2):
        QS = bus(f"QS{sl}_", 32)
        for k in range(4):
            lat = nl.add("573", f"U_QS{sl}{k}", LE=f"QLE{sl}", OE="GND")
            oe = f"QH{sl}{'LH'[k >> 1]}_n"
            b = nl.add("541", f"U_QB{sl}{k}", OE1=oe, OE2=oe)
            for i in range(8):
                lat[f"D{i + 1}"], lat[f"Q{i + 1}"] = DB[8 * k + i], QS[8 * k + i]
                b[f"A{i + 1}"], b[f"Y{i + 1}"] = QS[8 * k + i], QH[8 * (k & 1) + i]

    # ---- memory: the address, the RAM, the I/O space ----------------------------------
    nl.section("Memory")
    # the address: MAR, FPC (fetch cycles) or the A bus (a read at the A
    # bus), by VAS, which the microcode derives from MEM; bits 21-0 and
    # 31-28 (27-22 aren't decoded)
    VBITS = list(range(22)) + list(range(28, 32))
    for k in range(13):
        m = nl.add("153", f"U_VAM{k}", A=u["VAS0"], B=u["VAS1"], **{"1G": "GND", "2G": "GND"})
        for sec in (0, 1):
            i = VBITS[2 * k + sec]
            for c, s in enumerate([MAR[i], FPC[i], ABUS[i], "GND"]):
                m[f"{sec + 1}C{c}"] = s
            m[f"{sec + 1}Y"] = VA[i]
    # the access's decode, three 22V10s. MEM: 1 and 6 read, 2 writes; the
    # others are fetch cycles. The size (SIZE: 1 byte, 2 half, 3 word); the
    # byte lanes an access uses, from it and VA[1:0]. An address error
    # (FAULT): a half at an odd address, or a word at one that isn't a
    # multiple of 4, in a data access. It writes no memory, strobes no
    # device, writes no register or flag, keeps its decode or jump from the
    # IR and the PC (the queue's go on), and takes the fault's page. The
    # I/O space: bit 31 of a data access's address (IOACC). The RAM: 4 MB,
    # two banks of four 512K x 8 by VA21 (bank 1, the video's, in
    # video_ram(), written in its window, MIDV, and outside its fast tail,
    # RWF); bank 0's outputs on in a fetch cycle (nothing else drives the
    # data bus then) and in a read of the RAM
    MEM = [u["MEM0"], u["MEM1"], u["MEM2"]]
    SZ = [u["SIZE0"], u["SIZE1"], VA[0], VA[1]]

    def mem(*vs):
        return gal.when(MEM, list(vs), range(8))

    def lane(k):
        def f(s0, s1, a0, a1):
            size, a = s0 + 2 * s1, a0 + 2 * a1
            return (size == 1 and k == a or size == 2 and a0 == 0 and k >> 1 == a1
                    or size == 3 and a == 0)
        return sop(SZ, f)
    acc, wr = mem(1, 2, 6), mem(2)
    fault = gal.AND(acc, sop(SZ, lambda s0, s1, a0, a1: s1 and (a0 or a1 and s0)))
    win = [lit("MIDV"), lit("RWF", 0)] if sim else [lit("MWIN")]
    mw = {"FAULT": (fault, False, False), "FAULT_n": (fault, False, True)}
    for k in range(4):
        mw[f"WE{k}_n"] = (gal.AND(wr, lit(VA[31], 0), lit("MWIN"), lane(k)), False, True)
        mw[f"B1WE{k}_n"] = (gal.AND(wr, lit(VA[21]), lit(VA[31], 0), *win, lane(k)), False, True)
    gal.add(nl, "U_MEMW", mw)
    fetch = mem(0, 3, 4, 5, 7)
    gal.add(nl, "U_MEMC", {
        "READING": (mem(1, 6), False, False), "MEMWR": (wr, False, False),
        "FETCHCYC": (fetch, False, False), "IOACC": (gal.AND(acc, lit(VA[31])), False, False),
        "RAMOE_n": (gal.OR(fetch, gal.AND(mem(1, 6), lit(VA[31], 0))), False, True),
        "CE0_n": (gal.OR(lit(VA[21]), lit(VA[31])), False, False),
        "B1OE_n": (gal.AND(wr, lit("VSLOT_n")), False, False),
        "B1XOE_n": (gal.AND(lit(VA[21]), lit(VA[31], 0), lit("VSLOT_n")), False, True),
        "VA21_n": (lit(VA[21]), False, True)})
    # the store data's enables, by the size, and the lanes for the suite's
    # I/O page
    ms = {"BYTE_n": (sop(SZ[:2], lambda s0, s1: s0 and not s1), False, True),
          "HALF_n": (sop(SZ[:2], lambda s0, s1: s1 and not s0), False, True),
          "WORD": (sop(SZ[:2], lambda s0, s1: s0 and s1), False, False),
          "WORD_n": (sop(SZ[:2], lambda s0, s1: s0 and s1), False, True),
          "SIZE1_n": (lit(u["SIZE1"]), False, True)}
    for k in range(4):
        ms[f"BE{k}_n"] = (lane(k), False, True)
    gal.add(nl, "U_MEMS", ms)
    io = nl.add("138", "U_IORD", A=VA[28], B=VA[29], C=VA[30], G1="IOACC", G2A="GND",
                G2B="GND")
    for v in range(8):
        io[f"Y{v}"] = f"IOR{v}_n"
    for k in range(4):
        ram = nl.add("sram512", f"U_RAM0{k}", role="fastram", CE="CE0_n", OE="RAMOE_n",
                     WE=f"WE{k}_n")
        for i in range(19):
            ram[f"A{i}"] = VA[2 + i]
        for i in range(8):
            ram[f"IO{i}"] = DB[8 * k + i]
    video_ram(nl, VA, DB, sim)
    # store data: the A bus, replicated by size (a write always has one, so
    # SIZE1 is a half or a word)
    nl.section("Store data")
    g("00", ["MEMWR", "LATE"], "SDOE_n")
    a8 = [ABUS[8 * k:8 * k + 8] for k in range(4)]
    for ref, src, dst, oe2 in (("U_SD0", a8[0], 0, "GND"), ("U_SD1", a8[1], 1, "SIZE1_n"),
                               ("U_SDB1", a8[0], 1, "BYTE_n"), ("U_SD2", a8[2], 2, "WORD_n"),
                               ("U_SDB2", a8[0], 2, "WORD"), ("U_SD3", a8[3], 3, "WORD_n"),
                               ("U_SDH3", a8[1], 3, "HALF_n"), ("U_SDB3", a8[0], 3, "BYTE_n")):
        b = nl.add("541", ref, OE1="SDOE_n", OE2=oe2)
        for i in range(8):
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = src[i], DB[8 * dst + i]

    io_space(nl, VA, DB, sim)
    if sim:
        video(nl, DB, VA, capture)

    # ---- flags -------------------------------------------------------------------------
    nl.section("Flags")
    # Z is kept as four bits, each a byte of the result nonzero (NZR, a
    # 74F521's output as it is), and formed after the register. Sticky: Z
    # stays clear once clear. FNZ 3 loads the flags word from the A bus.
    NZR, NZ = bus("NZR", 4), bus("NZ", 4)
    for k in range(4):
        nl.add("521", f"U_Z{k}", G="GND", PEQ=NZR[k],
               **{f"P{i}": RES[8 * k + i] for i in range(8)}, **{f"Q{i}": "GND" for i in range(8)})
    # the register and its next state: two 22V10s on CLK, from the flags
    # code (FLG, a combination of FNZ, NSEL, FC, CZERO, CSRC, FV and FI:
    # ucode.FLAG_TABLE, all 32 codes); an address error (FAULT) holds them
    FLG = [u[f"FLG{i}"] for i in range(5)]
    table = [dict(zip(uc.FLAG_FIELDS, t)) for t in uc.FLAG_TABLE]
    used = range(len(table))

    def when(pred):
        return gal.when(FLG, [c for c, t in enumerate(table) if pred(t)], used)

    def nxt(q, cases):
        """q's next state: held in a fault, else as the cases say:
        (predicate on the fields, sum of products)."""
        f = gal.OR(*[gal.AND(when(p), f) for p, f in cases])
        return (gal.OR(gal.AND(lit("FAULT"), lit(q)), gal.AND(lit("FAULT", 0), f)), True, False)
    zn = gal.OR(*[lit(n) for n in NZ])                  # Z clear
    fa = {}
    for i in range(4):
        sticky = gal.OR(lit(NZR[0]), zn) if i == 0 else lit(NZR[i])
        fa[NZ[i]] = nxt(NZ[i], [(lambda t: t["FNZ"] == 0, lit(NZ[i])),
                                (lambda t: t["FNZ"] == 1, lit(NZR[i])),
                                (lambda t: t["FNZ"] == 2, sticky),
                                (lambda t: t["FNZ"] == 3, lit(ABUS[2], 0) if i == 0 else gal.ZERO)])
    ncases = [(lambda t: t["FNZ"] == 0, lit("NFLAG")), (lambda t: t["FNZ"] == 3, lit(ABUS[3]))]
    for j, r in enumerate((31, 15, 7)):
        ncases.append((lambda t, j=j: t["FNZ"] in (1, 2) and t["NSEL"] == j, lit(RES[r])))
    fa["NFLAG"] = nxt("NFLAG", ncases)
    fa["ZFLAG"] = (gal.AND(*[lit(n, 0) for n in NZ]), False, False)
    gal.add(nl, "U_FLGA", fa, clock="CLK")
    g("86", [F[7], "FILL"], "F7X")
    g("86", [F[15], "FILL"], "F15X")
    # C, from the inverted output: the carry as the ALU gives it (CN4, low
    # for a carry), one gate sooner
    nl.add("151", "U_CSRC", A="CSRC0", B="CSRC1", C="CSRC2", G="GND", Y="CSRCY",
           W="CSRCY_n", D0=ABUS[1], D1=F[0], D2=F[7], D3=F[8], D4=F[15], D5=F[31], D6="F7X",
           D7="F15X")
    # C from the inverted carry and source (low for a carry, one gate
    # sooner); V: FV 7 is VT3 = A31 ^ F31 if the operands' signs allow an
    # overflow (VT2); I: hold, set, clear, or A4 with a flags load
    ok = lambda t: not t["CZERO"]
    fb = {"CFLAG": nxt("CFLAG", [(lambda t: ok(t) and t["FC"] == 0, lit("CFLAG")),
                                 (lambda t: ok(t) and t["FC"] == 1, lit("CSRCY_n", 0)),
                                 (lambda t: ok(t) and t["FC"] == 2, lit("CARRY_n", 0)),
                                 (lambda t: ok(t) and t["FC"] == 3, lit("CLQ", 0))]),
          "VFLAG": nxt("VFLAG", [(lambda t: t["FV"] == 0, lit("VFLAG")),
                                 (lambda t: t["FV"] == 3, lit(ABUS[0])),
                                 (lambda t: t["FV"] == 4, lit("CLQ", 0)),
                                 (lambda t: t["FV"] == 5, gal.ONE),
                                 (lambda t: t["FV"] == 7, gal.AND(lit("VT2"), lit("VT3")))]),
          "IFLAG": nxt("IFLAG", [(lambda t: t["FI"] == 0, lit("IFLAG")),
                                 (lambda t: t["FI"] == 1, gal.ONE),
                                 (lambda t: t["FI"] == 3, lit(ABUS[4]))])}
    # the C source's select, which matters only for FC 1
    csrc = [c for c, t in enumerate(table) if t["FC"] == 1 and not t["CZERO"]]
    for k in range(3):
        fb[f"CSRC{k}"] = (gal.when(FLG, [c for c in csrc if table[c]["CSRC"] >> k & 1], csrc),
                          False, False)
    gal.add(nl, "U_FLGB", fb, clock="CLK")

    nl.section("Condition latches")
    # a 22V10 on CLK. CL, loaded by LDCL from CLSRC: the result zero, the
    # carry, RES[31:16] or RES[31:15] zero, those ANDed with CL, or 1 (NZR,
    # each a byte of the result nonzero, from the flags' 74F521s). SGN,
    # loaded by LDSGN from FILL. The divide step: S33 = R31 ^ C32 ^
    # (subtracting = not S33); the quotient bit is its complement. MQ
    # loads clear S33
    CLS = [u[f"CLSRC{i}"] for i in range(3)]

    def nz(*ks):
        return gal.AND(*[lit(NZR[k], 0) for k in ks])
    hi = nz(2, 3)
    cl = gal.mux(CLS, [nz(0, 1, 2, 3), lit("CARRY_n", 0), hi, gal.AND(lit(RES[15], 0), hi),
                       gal.AND(lit("CLQ"), hi), gal.AND(lit("CLQ"), lit(RES[15], 0), hi), 1, 1])
    ld = lit(u["LDCL"])
    s33 = sop([u["MQM0"], u["MQM1"], RQ[31], "S33Q", "CARRY_n"],
              lambda m0, m1, r, q, c: (r ^ q ^ c) if (not m0 and m1) else (q and not m1))
    gal.add(nl, "U_CLG", {
        "CLQ": (gal.OR(gal.AND(ld, cl), gal.AND(lit(u["LDCL"], 0), lit("CLQ"))), True, False),
        "SGNQ": (gal.OR(gal.AND(lit(u["LDSGN"]), lit("FILL")),
                        gal.AND(lit(u["LDSGN"], 0), lit("SGNQ"))), True, False),
        "S33Q": (s33, True, False), "S33_n": (s33, True, True),
        "QBIT": (sop([RQ[31], "S33Q", "CARRY_n"], lambda r, q, c: r ^ (1 - q) ^ c), False,
                 False)}, clock="CLK")

    nl.section("Branch condition")
    # cc from IR[15:12] (Jcc), IR[3:0] (Bcc) or IR[11:8] (SETcc)
    for k in range(2):
        m = nl.add("153", f"U_CCM{k}", A=u["CCB0"], B=u["CCB1"], **{"1G": "GND", "2G": "GND"})
        for sec in (0, 1):
            i = 2 * k + sec
            for c, s in enumerate([IR[12 + i], IR[i], IR[8 + i], "GND"]):
                m[f"{sec + 1}C{c}"] = s
            m[f"{sec + 1}Y"] = CC[i]

    nl.finish()
    nl.check()
    return nl


def counter_chain(nl, name, q, d, start, n, load_n, inc):
    """A register of 74F161s for bits start.. of q (its count +1 at bit
    `start`), loaded from d (LOAD), counting with `inc`; the count's carry
    looked ahead through AND gates, as on draft 1b's PC."""
    g = nl.gate
    rco = [f"{name}RCO{s}" for s in range(n)]
    enp = [inc]
    for s in range(1, n):
        if s <= 3:
            g("21" if s == 3 else "11" if s == 2 else "08", [inc] + rco[:s], f"{name}E{s}")
        elif s == 4:
            g("21", rco[:4], f"{name}Q4")
            g("08", [inc, f"{name}Q4"], f"{name}E4")
        elif s == 5:
            g("11", [inc, f"{name}Q4", rco[4]], f"{name}E5")
        elif s == 6:
            g("21", [inc, f"{name}Q4", rco[4], rco[5]], f"{name}E6")
        else:
            g("08", [rco[5], rco[6]], f"{name}Q56")
            g("21", [inc, f"{name}Q4", rco[4], f"{name}Q56"], f"{name}E7")
        enp.append(f"{name}E{s}")
    for s in range(n):
        c = nl.add("161", f"U_{name}{s}", CLK="CLK", CLR="VCC", LOAD=load_n, ENP=enp[s],
                   ENT="VCC", RCO=rco[s])
        for j, (dp, qp) in enumerate(zip("ABCD", ("QA", "QB", "QC", "QD"))):
            bit = start + 4 * s + j
            if bit <= 31:
                c[dp], c[qp] = d[bit], q[bit]
            else:
                c[dp] = "GND"


VARIANT = parts.VARIANT
