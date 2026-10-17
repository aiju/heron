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
CF_SECTORS = 256             # the simulations' CF card: 128K


# the video timing ROM's bits, registered at each character's end
TIMING_BITS = ["HSYNCQ", "VSYNCQ", "DEQR", "SHLDQ", "DESCQ", "DSEQ", "LENDQ", "FENDQ"]


def preload(k):
    """The tick counter's preload for a cycle of k ticks."""
    p = HEAD + 16 + TAIL - k
    if not 0 <= p <= 15:
        raise ValueError(f"a cycle of {k} ticks is out of range")
    return p


def clock_generator(nl, lengths, por_ps):
    """RFC 0024's clock generator for short cycles, with two tail ticks:
    H0 and H1, the count from the preload to 15, T1 and T2. The length
    class from the uIR's LCL field. RW, the register file's write phase
    and the video's, is T1 or T2; the write strobe T2."""
    g = nl.gate
    nl.section("Reset")
    nl.add("por", "U_POR", RST="PORST_n", params={"release_ps": por_ps})
    nl.add("pullup", "RN_POR", P1="PORST_n")
    g("14", ["PORST_n"], "RSTI")
    g("14", ["RSTI"], "RSTA_n")
    # asserted at once, released at a CLK edge
    nl.add("74", "U_RSY", **{"1D": "VCC", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "RSTA_n",
                             "1Q": "RSY1", "2D": "RSY1", "2CLK": "CLK", "2PRE": "VCC",
                             "2CLR": "RSTA_n", "2Q": "RESET_n"})

    nl.section("Clock generator")
    nl.add("osc", "U_OSC", part="oscillator 50.35 MHz", OUT="MCLK",
           params={"period_ps": TICK_PS, "phase_ps": TICK_PS})
    # two 22V10s on the master clock. K1: the tick count TC, cleared at T2,
    # preloaded at H1 by the length class and XL, held in an I/O access's
    # hold, its carry TCRCO; T1 after the carry, T2 after T1, H0 after T2,
    # H1 after H0, and CLK, T2 or H0. The preloads are K1's equations, so
    # the length classes are its program. XL: a parcel consumed with the
    # queue empty comes from the word the cycle fetches, which takes two
    # ticks more (rtl.DEMAND_HOLD). H0 never stays on two ticks, so a
    # second pulse dies whatever the registers powered up as
    from .rtl import DEMAND_HOLD
    pre = [preload(k) for k in lengths] + [preload(k + DEMAND_HOLD) for k in lengths]
    TC = bus("TC", 4)
    sel = ["uLCL0", "uLCL1", "uCONSUME", "V0"]
    k1 = {}
    for b in range(4):
        load = sop(sel, lambda l0, l1, c, v0: pre[l0 + 2 * l1 + 4 * (c & (1 - v0))] >> b & 1)
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
    k1["T2"] = (lit("T1"), True, False)
    k1["H0"] = (gal.AND(lit("T2"), lit("H0", 0)), True, False)
    k1["H1"] = (lit("H0"), True, False)
    k1["CLK"] = (gal.OR(lit("T2"), lit("H0")), True, False)
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
    nl.add("163", "U_HC", part="74ACT163", CLK="MCLK", CLR="VCC", LOAD="HOLD", ENP="HOLD",
           ENT="HOLD", A="VCC", B="VA28", C="VA29", D="VA30", RCO="HCRCO")
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


def video(nl, DB, VA, capture=False):
    """The video (RFC 0041): 640 x 480 at 4 bits a pixel from bank 1, 800 x
    525 pixel clocks of two master ticks (25.175 MHz). Each line's
    descriptor, word 44 + y of the table at bank 1's word 0 (or 1024 with
    TSEL), gives its first word (bits 18-0, a word address in bank 1), its
    palette bank (22-19) and a line interrupt (23). The pixels, 80 words a
    line, low nibble first; the palette 256 entries of RGB 5:6:5.

    The video's slots: it owns bank 1 in every cycle's T2 and the next H0,
    and in an I/O access's hold, and latches the word at its address (VAD)
    into HR at the end of each two ticks it owned it. VAD steps when the
    shifters take HR, so HR always holds the next word to show (a slot
    every 11 ticks at most, a word every 16)."""
    g = nl.gate
    nl.section("Video timing")
    # two 22V10s on the master clock, cleared in a reset. V1: the pixel
    # phase (PH: the pixel's second tick), the pixel in the character (PX,
    # counted at the end of each pixel), P7 the character's last pixel, CHE
    # its last tick, SLD the shifters' load then, DLD the descriptor
    # address's load
    rst = lit("RESET_n")
    PX = bus("PX", 3)
    last = gal.AND(rst, lit("P7"), lit("PH", 0))
    v1 = {"PH": (gal.AND(rst, lit("PH", 0)), True, False),
          "PH_n": (gal.AND(rst, lit("PH", 0)), True, True),
          "P7": (gal.AND(rst, lit(PX[0], 0), lit(PX[1]), lit(PX[2]), lit("PH")), True, False),
          "CHE": (last, True, False), "CHE_n": (last, True, True),
          "SLD": (gal.AND(last, lit("SHLDQ")), True, False),
          "DLD": (gal.AND(last, lit("DESCQ")), True, False)}
    for b in range(3):
        carry = gal.AND(lit("PH"), *[lit(PX[i]) for i in range(b)])
        v1[PX[b]] = (gal.AND(rst, gal.OR(
            gal.AND(lit(PX[b]), gal.OR(lit("PH", 0), *[lit(PX[i], 0) for i in range(b)])),
            gal.AND(lit(PX[b], 0), carry))), True, False)
    gal.add(nl, "U_V1", v1, clock="MCLK")
    # V2: the ownership, a tick ahead: T2 and H0 follow T1 and T2; the
    # hold's ticks follow HOLD (VSLOT, set in a reset). VT toggles while
    # the video owns bank 1: its second ticks end the slots. DSE (the
    # descriptor's load), DLD_n; the character and line counters' clears
    # and the line's step
    slot = gal.AND(rst, lit("T1", 0), lit("T2", 0), lit("HOLD", 0))
    gal.add(nl, "U_V2", {
        "VSLOT_n": (slot, True, False), "VSLOT": (slot, True, True),
        "VT_n": (gal.AND(rst, lit("VSLOT"), lit("VT_n")), True, True),
        "DSE": (gal.AND(last, lit("DSEQ")), True, False),
        "DSE_n": (gal.AND(last, lit("DSEQ")), True, True),
        "DLD_n": (gal.AND(last, lit("DESCQ")), True, True),
        "HCLR_n": (gal.AND(lit("LENDQ"), lit("CHE")), False, True),
        "LINE": (gal.AND(lit("LENDQ"), lit("CHE")), False, False),
        "VCLR_n": (gal.AND(lit("FENDQ"), lit("LENDQ"), lit("CHE")), False, True)},
        clock="MCLK")
    # the character (0-99) and the line (0-524): line 0-44 the vertical
    # blanking, 45-524 the picture
    H, V = bus("VH", 7) + ["VH7"], bus("VV", 10) + ["VV10", "VV11"]
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
    # the timing ROM, by the character and the line, registered at the
    # character's end: what to do in the next character
    rom = nl.add("flash", "U_VTIM", role="decode", CE="GND", OE="GND", WE="VCC")
    for i in range(7):
        rom[f"A{i}"] = H[i]
    for i in range(10):
        rom[f"A{7 + i}"] = V[i]
    tr = nl.add("377", "U_VTR", CLK="MCLK", EN="CHE_n")
    for i, q in enumerate(TIMING_BITS):
        tr[f"D{i + 1}"], tr[f"Q{i + 1}"] = f"VTD{i}", q
        rom[f"D{i}"] = f"VTD{i}"

    nl.section("Video fetch")
    # VAD: the word the video reads. Loaded with the descriptor's address
    # (DLD: TSEL and the line), then the descriptor (DSE: from HR), stepped
    # as the shifters take a word (SLD)
    VADn = bus("VAD", 19) + ["VAD19"]
    HR = bus("HR", 32)
    g("02", ["DLD", "DSE"], "VADL_n")
    for k in range(3):
        m = nl.add("157", f"U_VADM{k}", S="DESCQ", G="GND")
        for j in range(4):
            bit = 4 * k + j
            tab = f"VV{bit}" if bit < 10 else ("TSEL" if bit == 10 else "GND")
            m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = HR[bit], tab, f"VADD{bit}"
    rco = "VCC"
    for k in range(5):
        low = k < 3
        # (the carry ripples on past the edge after a step, when SLD is
        # low and nothing counts, as the character and line counters' do)
        c = nl.add("163", f"U_VAD{k}", part="74ACT163", CLK="MCLK", nocheck=k > 0,
                   CLR="VCC" if low else "DLD_n", LOAD="VADL_n" if low else "DSE_n",
                   ENP="SLD", ENT=rco, RCO=f"VADC{k}")
        rco = f"VADC{k}"
        for j, (pin, q) in enumerate(zip("ABCD", ("QA", "QB", "QC", "QD"))):
            bit = 4 * k + j
            c[pin] = f"VADD{bit}" if low else (HR[bit] if bit < 19 else "GND")
            c[q] = VADn[bit]
    # HR: the word at VAD, latched at the end of each slot (9-bit registers
    # with a clock enable and three-state outputs, always on: the shifters'
    # parallel inputs are their three-state I/O)
    for k in range(4):
        r = nl.add("823", f"U_HR{k}", CLK="MCLK", EN="VT_n", CLR="VCC", OE="GND")
        for i in range(8):
            r[f"D{i + 1}"], r[f"Q{i + 1}"] = f"VD{8 * k + i}", HR[8 * k + i]
        r["D9"] = "GND"
    # the line's mode, from its descriptor: the palette bank, the line
    # interrupt
    ml = nl.add("377", "U_VML", CLK="MCLK", EN="DSE_n")
    for i in range(8):
        ml[f"D{i + 1}"], ml[f"Q{i + 1}"] = HR[19 + i], f"VM{i}"

    nl.section("Video output")
    # the shifters: shifter k has bit k of each pixel, pixel 0 at IO7; they
    # shift at each pixel's end (S0 = PH) and load from HR at the
    # character's (S1 = SLD)
    P = bus("VP", 4)
    for k in range(4):
        sh = nl.add("299", f"U_VSH{k}", S0="PH", S1="SLD", OE1="VCC", OE2="VCC", MR="RESET_n",
                    CP="MCLK", DS0="GND", DS7="GND", Q7S=P[k])
        for j in range(8):
            sh[f"IO{7 - j}"] = HR[4 * j + k]
    # the palette: 256 entries of 16 bits, by the line's bank and the pixel;
    # the CPU writes it (region 7, LOC1: 0xF000_0400 + 4n)
    PA, PD = bus("PA", 8), bus("PD", 16)
    for k in range(2):
        m = nl.add("157", f"U_PAM{k}", S="LOC1_n", G="GND")
        for j in range(4):
            bit = 4 * k + j
            disp = P[bit] if bit < 4 else f"VM{bit - 4}"
            m[f"{j + 1}A"], m[f"{j + 1}B"], m[f"{j + 1}Y"] = VA[2 + bit], disp, PA[bit]
    g("32", ["LOC1_n", "IOWR_n"], "PWE_n")
    g("04", ["LOC1_n"], "POE_n")
    for k in range(2):
        ram = nl.add("sram", f"U_PAL{k}", role="rf", CE="GND", OE="POE_n", WE="PWE_n")
        for i in range(15):
            ram[f"A{i}"] = PA[i] if i < 8 else "GND"
        b = nl.add("541", f"U_PWD{k}", OE1="LOC1_n", OE2="IOWR_n")
        for i in range(8):
            ram[f"IO{i}"] = PD[8 * k + i]
            b[f"A{i + 1}"], b[f"Y{i + 1}"] = DB[8 * k + i], PD[8 * k + i]
    # the colour, registered at each pixel's end; off (black, the monitor's
    # 75 ohms pulling the DACs down) outside the picture. DE a pixel late,
    # as the colour is
    for k in range(2):
        o = nl.add("574", f"U_RGB{k}", CLK="PH_n", OE="DED_n")
        for i in range(8):
            o[f"D{i + 1}"], o[f"Q{i + 1}"] = PD[8 * k + i], f"RGB{8 * k + i}"
    if capture:
        # a frame grabber: the outputs at the middle of each pixel
        from .video import CAPTURE
        x = nl.add("vector", "X_VCAP", CLK="PH", params={"outs": 0, "ins": len(CAPTURE),
                                                         "conds": 1})
        for i in range(48):
            x[f"I{i}"] = CAPTURE[i] if i < len(CAPTURE) else "GND"

    nl.section("Video registers")
    # region 7, LOC0: 0xF000_0000 the control register (bit 0 the picture
    # on, 1 TSEL, 2 the interrupt on), 0xF000_0004 the interrupt's
    # acknowledge (any write): a 22V10 on the master clock, loading the
    # control register through a write's strobe (synchronous to the master
    # clock). The interrupt: set at the picture's end and by a line whose
    # descriptor asks; cleared by the acknowledge. DE, the colour's output
    # enable: the picture on and in it, a pixel late, as the colour is
    # (registered as PH falls)
    rst = lit("RESET_n")
    wr = [lit("LOC0_n", 0), lit("IOWR_n", 0)]
    ctl = gal.AND(*wr, lit(VA[2], 0))
    noctl = gal.OR(lit("LOC0_n"), lit("IOWR_n"), lit(VA[2]))
    noack = gal.OR(lit("LOC0_n"), lit("IOWR_n"), lit(VA[2], 0))
    v3 = {}
    for i, q in enumerate(["VON", "TSEL", "VIEN"]):
        v3[q] = (gal.AND(rst, gal.OR(gal.AND(ctl, lit(DB[i])), gal.AND(noctl, lit(q)))), True,
                 False)
    v3["VIFLAG"] = (gal.AND(rst, gal.OR(gal.AND(lit("FENDQ"), lit("LINE")),
                                        gal.AND(lit("DSE"), lit("HR23")),
                                        gal.AND(lit("VIFLAG"), noack))), True, False)
    v3["VIRQ"] = (gal.AND(lit("VIFLAG"), lit("VIEN")), False, False)
    ded = gal.AND(rst, gal.OR(gal.AND(lit("PH"), lit("DEQR"), lit("VON")),
                              gal.AND(lit("PH", 0), lit("DED"))))
    v3["DED"] = (ded, True, False)
    v3["DED_n"] = (ded, True, True)
    gal.add(nl, "U_V3", v3, clock="MCLK")


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
    # region 3, an 82C54 counting the UARTs' 1.8432 MHz: counter 0 the
    # periodic interrupt (OUT0 rising sets TFLAG), counter 2 the speaker
    nl.add("osc", "U_UOSC", part="oscillator 1.8432 MHz", OUT="UCLK",
           params={"period_ps": round(1e12 / UART_HZ)})
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
    # the interrupt line (any device's request) and the suite's I/O page's
    # select: a 22V10
    reqs = ["UINT0", "UINT1", "CFINT", "TFLAG", "VIRQ", "XIRQ"]
    gal.add(nl, "U_ONB", {
        "TCLR_n": (gal.AND(lit("RESET_n"), gal.OR(lit("LOC2_n"), lit("IOWR_n"))), False, False),
        "CTLW": (gal.OR(lit("LOC3_n"), lit("IOWR_n")), False, False),
        "SPK": (gal.AND(lit("TOUT2"), lit("SPKD")), False, False),
        "IRQ": (gal.OR(*[lit(r) for r in reqs], lit("EIRQ1_n", 0), lit("EIRQ2_n", 0)),
                False, False),
        "XSEL_n": (gal.OR(lit("IOR7_n"), lit(VA[21], 0)), False, False)})
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

def build(sim=False, lengths=None, por_ps=2_000_000, capture=False):
    nl = Netlist()
    g = nl.gate
    U = control_nets()
    u = {v[1:]: v for v in U.values()}          # u["SEQ0"] -> "uSEQ0", u["ARF_n"] ...
    if lengths is None:
        lengths = uc.built().lengths
    lengths = tuple(lengths) + (lengths[-1],) * (4 - len(lengths))

    ABUS, BBUS, F, RES = bus("ABUS", 32), bus("BBUS", 32), bus("F", 32), bus("RES", 32)
    VA, DB = bus("VA", 32), bus("DB", 32)
    IR, QH, Y = bus("IR", 16), bus("QH", 16), bus("Y", uc.Y_BITS)
    RQ, TQ = bus("RQ", 32), bus("TQ", 32)
    MAR, PC = bus("MAR", 32), ["GND"] + bus("PC", 31, 1)
    FPC = ["GND", "GND"] + bus("FPC", 20, 2) + ["GND"] * 10
    LC, SX, EX = bus("LC", 8), bus("SX", 4), bus("EX", 4)

    # ---- clock, reset, rails ------------------------------------------------------
    if sim:
        clock_generator(nl, lengths, por_ps)
    else:
        # for static timing analysis: the clock generator's outputs as
        # functions of the cycle (CLK's edge at 0), and its other phases
        # as they are in the cycle's first part
        nl.add("tickclk", "X_CLK", CLK="CLK", MWIN="MWIN", LATE="LATE", RW="RW", RSTB="T2",
               RESET="RESET_n")
        g("04", ["RW"], "RW_n")
        for net in ("T1", "TCRCO", "MCLK", "H0", "H1", "H2"):
            nl.add("const", f"X_{net}", LO=net)
        nl.add("const", "X_HOLD", LO="HOLD", HI="HOLD_n")
        nl.add("const", "X_IOSTB", LO="IOSTB")
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
    # with it high, PEND, SX = EX, -, -, SX15, MQ0 or R0. A 22V10
    COND = [u[f"COND{i}"] for i in range(4)]
    gal.add(nl, "U_CNY", {"CONDY": (gal.mux(COND, [
        lit(u["NEXT0"]), lit("TC"), lit(RQ[31]), lit("CLQ"), lit("CONDT"), lit("MQ31"), lit("TC4"),
        lit("CONDT", 0), lit("PEND"), lit("SXEQ_n", 0), 0, 0, lit("SX15"), lit("MQ0"), lit(RQ[0]),
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
    # cycle later, with I as it is in the cycle, PEND
    g("08", ["IRQQ", "IFLAG"], "PEND_D")
    nl.add("74", "U_IRQ", nocheck=True,
           **{"1D": "IRQ", "1CLK": "CLK", "1PRE": "VCC", "1CLR": "RESET_n", "1Q": "IRQQ",
              "2D": "PEND_D", "2CLK": "CLK", "2PRE": "VCC", "2CLR": "RESET_n",
              "2Q": "PEND", "2QN": "PEND_n"})

    # ---- register file -----------------------------------------------------------
    # two copies of 32 x 32 bits (r0-r15, then the microcode's own), read
    # through latches in the cycle's first part, written in its last tick
    nl.section("Register file")
    # one copy, read twice in a cycle that reads B from it (BRF): the A
    # address until LATE, its latches closing then, the B address after;
    # the write address in the tail (RW). The addresses and the A latches'
    # enable from three 22V10s. The address moves on from A only once RLEA
    # has closed the A latches, and from B once RW_n has closed the B
    # latches: a gate's delay after them, for the latches' hold
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
                           "RLEA": (gal.AND(lit("RW", 0), gal.OR(lit("LATE", 0), lit(u["BRF_n"]))),
                                    False, False)})
    IO = bus("RFAIO", 32)
    for k in range(4):
        ram = nl.add("sram", f"U_RFA{k}", role="rf", CE="GND", OE="RW", WE="RFWE_n")
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
    g("04", ["TL0"], "TL0_n")
    g("04", ["TL1"], "TL1_n")
    g("02", ["TL0", "TL1"], "TLB0")
    g("08", ["TL0", "TL1_n"], "TLB1")
    g("08", ["TL0_n", "TL1"], "TLB2")
    g("08", ["TL0", "TL1"], "TLB3")
    #            BL: -  word   half    byte    qh     qh2    qhh    qhb
    for name, ins in (("BT0_n", ["GND", "VCC", "TL1_n", "TLB0", "GND", "GND", "GND", "GND"]),
                      ("BT1_n", ["GND", "VCC", "TL1_n", "GND", "GND", "GND", "GND", "GND"]),
                      ("BT20_n", ["GND", "GND", "TL1", "TLB2", "GND", "GND", "GND", "GND"]),
                      ("TH1_n", ["GND", "GND", "TL1", "GND", "GND", "GND", "GND", "GND"]),
                      ("TB1_n", ["GND", "GND", "GND", "TLB1", "GND", "GND", "GND", "GND"]),
                      ("TB3_n", ["GND", "GND", "GND", "TLB3", "GND", "GND", "GND", "GND"]),
                      ("BQ0_n", ["GND", "GND", "GND", "GND", "VCC", "GND", "GND", "VCC"])):
        nl.add("151", f"U_{name[:-2]}E", A=u["BL0"], B=u["BL1"], C=u["BL2"], G="GND", W=name,
               **{f"D{i}": x for i, x in enumerate(ins)})
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
    # zero fill in bytes 1-3)
    g("00", [u["BX0"], "BX1_n"], "BXMQ_n")
    g("00", ["BX0_n", u["BX1"]], "BXFL_n")
    g("04", [u["BX0"]], "BX0_n")
    g("04", [u["BX1"]], "BX1_n")
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
    # memory is read into them, from tick 2 (LATE) until the tail
    g("11", ["READING", "RW_n", "LATE"], "TLE")
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
    # ucode.FLAG_TABLE); an address error (FAULT) holds them
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
