"""The board behind the two-halves machine's model (rtl2.py): the RAM, the
I/O space, the suite's console, as the CPU sees them.

The I/O space (A30 set; A31 is ignored), by A20, A16 and A14-A12
(board2.py has the details):

    A20 0                0xFFE0_0000  the boot flash (byte n at +2n)
    A20 1, A16 0         0xFFFE_0000  the expansion port (not built)
    A20 1, A16 1, A14-A12:
        111  0xFFFF_F000  the sound chip; the simulation's test fixture
                          (the suite's console, 0xFFFF_FF00)
        110  0xFFFF_E000  UART 0          010  0xFFFF_A000  the slow devices
        101  0xFFFF_D000  the interrupt   001  0xFFFF_9000  UART 1
                          controller
        100  0xFFFF_C000  video control   000  0xFFFF_8000  (nothing)
        011  0xFFFF_B000  PS/2
    and again at 0xFFFF_0000-0xFFFF_7FFF and below (A19-A17 and A15 are
    ignored)
"""

from .board import TICK_PS
from .system import Console, RAM_SIZE

UCLK_PS = 542535                # the timer's clock (board2.UCLK_PS)

class Uart:
    """UART 0 as ODT uses it: the receiver's buffer and the line status
    (data ready, the transmitter always empty), what's sent kept; the
    divisor latch's accesses (LCR bit 7) go nowhere."""

    def __init__(self, inp=b""):
        self.inp = bytearray(inp)
        self.out = bytearray()
        self.lcr = 0

    def read(self, reg):
        if reg == 0 and not self.lcr & 0x80:
            return self.inp[0] if self.inp else 0
        if reg == 5:
            return 0x60 | (1 if self.inp else 0)
        return self.lcr if reg == 3 else 0

    def read_edge(self, reg):
        if reg == 0 and not self.lcr & 0x80 and self.inp:
            del self.inp[0]

    def write(self, reg, v):
        if reg == 3:
            self.lcr = v & 0xFF
        elif reg == 0 and not self.lcr & 0x80:
            self.out.append(v & 0xFF)


class Ps2Model:
    """A PS/2 device sending bytes as the chip-level simulator's ps2dev does:
    each bit's data a quarter of half_ps before its clock falls, the clock
    low for half_ps and high for half_ps; gap_ps between frames, the first
    at start_ps. What the port's GAL makes of it: E set at each falling
    edge, cleared by the device task's write; IRQ the port's interrupt."""

    def __init__(self, data=b"", half_ps=40_000_000, gap_ps=200_000_000, start_ps=50_000_000):
        self.bits = []                  # (the data's time, the clock's fall, the bit)
        t, q = start_ps, half_ps // 2
        for b in data:
            frame = b << 1 | (1 ^ bin(b).count("1") & 1) << 9 | 1 << 10
            for n in range(11):
                self.bits.append((t, t + q, frame >> n & 1))
                t += 2 * half_ps
            t += gap_ps
        self.i = 0
        self.e = self.irq = 0

    def advance(self, now):
        while self.i < len(self.bits) and self.bits[self.i][1] <= now:
            self.e = 1
            self.i += 1

    def data(self, now):
        bit = 1
        for t, _, b in self.bits[max(0, self.i - 1):self.i + 1]:
            if t <= now:
                bit = b
        if self.i == len(self.bits) and (not self.bits or now >= self.bits[-1][1] + 40_000_000):
            return 1
        return bit


LINE_TICKS = 1600       # the video's line: 200 words of 8 ticks
FRAME_LINES = 525

FLASH, EXP = "flash", "exp"
CON, UART0, IRQC, VIDEO, PS2, SLOWD, UART1 = 7, 6, 5, 4, 3, 2, 1

SOURCES = ["TIRQ", "VIRQ", "U0INT", "U1INT", "KIRQ", "MIRQ", "CFIRQ", "BTNQ"]   # by priority


class System2:
    def __init__(self, inp=b"", uart=b"", kbd=b"", mouse=b""):
        self.ram = bytearray(RAM_SIZE)
        self.console = Console(inp)
        self.uart = Uart(uart)
        self.flash = bytes([0xFF]) * 0x20000
        self.video_ctl = 0
        self.palette_bank = 0
        self.target_line = 0
        self.cen = 0                 # the copper's on
        self.ticks = 0
        self.sources = 0             # the board's interrupt sources (none modelled yet)
        self.cffast = 0
        self.halt_req = 0
        self.trace = 0
        self.ps2 = [Ps2Model(kbd), Ps2Model(mouse, start_ps=70_000_000)]
        self.t1 = None               # the timer's counter 1: (its period in ps, the next pulse)
        self.t1_rw = self.t1_lsb = None
        self.t1_set = False
        self.sreq = 0
        self.dac = []                # the samples written

    def load(self, image):
        for a, b in image.mem.items():
            self.ram[a % RAM_SIZE] = b

    @staticmethod
    def region(a):
        """The device an I/O address selects: FLASH, EXP or a slot (0-7)."""
        if not a >> 20 & 1:
            return FLASH
        if not a >> 16 & 1:
            return EXP
        return a >> 12 & 7

    def read16(self, a, io, cycle):
        if not io:
            a = (a % RAM_SIZE) & ~1
            return self.ram[a] | self.ram[a + 1] << 8
        r = self.region(a)
        if r == CON:
            return self.console.read(a, cycle)
        if r == UART0:
            return self.uart.read(a >> 1 & 7)
        if r == PS2:
            p = self.ps2[a >> 1 & 1]
            now = self.ticks * TICK_PS
            return p.data(now) | p.e << 1 | (self.sreq << 2 if a & 2 else 0)
        if r == FLASH:                          # the boot flash, a byte a halfword
            return self.flash[(a >> 1) & 0x1FFFF] | 0xFF00
        if r == IRQC:
            k = a >> 1 & 3
            if k == 0:
                return self.sources | self.ps2[0].irq << 4 | self.ps2[1].irq << 5
            if k == 1:
                sources = self.sources | self.ps2[0].irq << 4 | self.ps2[1].irq << 5
                for i in range(8):
                    if sources >> i & 1:
                        return 0x40 + 4 * i
                return 0x04
            if k == 2:
                return 0x9000 if self.odt_req() else 0
            return self.line()
        return 0xFFFF                           # devices the model doesn't have

    def read_edge(self, a, io, cycle):
        if io and self.region(a) == CON:
            self.console.read_edge(a, cycle)
        elif io and self.region(a) == UART0:
            self.uart.read_edge(a >> 1 & 7)

    def write(self, a, v, lanes, io):
        if not io:
            a = (a % RAM_SIZE) & ~1
            if lanes & 1:
                self.ram[a] = v & 0xFF
            if lanes & 2:
                self.ram[a + 1] = v >> 8 & 0xFF
            return
        r = self.region(a)
        if r == CON:
            self.console.write(a, v, lanes)
        elif r == UART0:
            if lanes & 1:
                self.uart.write(a >> 1 & 7, v)
        elif r == VIDEO:
            if a & 2:
                self.palette_bank = v & 15
            else:
                self.video_ctl = v
        elif r == PS2:
            p = self.ps2[a >> 1 & 1]
            if a & 4:
                p.irq = v >> 3 & 1
            else:
                p.e = 0
        elif r == SLOWD:
            if a >> 4 & 7 == 3:
                self.cffast = v & 1
            elif a >> 4 & 7 == 2:                   # the PCM's DAC
                self.dac.append(v & 0xFF)
                self.sreq = 0
            elif a >> 4 & 7 == 0:
                self.timer_write(a >> 1 & 3, v & 0xFF)
        elif r == IRQC:
            k = a >> 1 & 3
            if k == 2:
                self.trace = v & 1
                self.halt_req = 0
            elif k == 3:
                self.target_line = v & 0x1FF
                self.cen = v >> 15 & 1

    def timer_write(self, reg, v):
        """The 82C54 as far as counter 1 goes: a control word for it, then
        its count's low and high bytes; OUT1 then pulses once a count. As
        the chip-level simulator's, OUT1 is low from reset to the first
        control word, which makes it rise: SREQ, as each pulse's end does."""
        if reg == 3 and v >> 6 == 1:
            self.t1_rw, self.t1_lsb = v >> 4 & 3, None
            if not self.t1_set:             # OUT1 rises from reset's low: a request
                self.t1_set, self.sreq = True, 1
        elif reg == 1 and self.t1_rw == 3:
            if self.t1_lsb is None:
                self.t1_lsb = v
            else:
                n = (self.t1_lsb | v << 8) or 0x10000
                self.t1_lsb = None
                self.t1 = (n * UCLK_PS, self.ticks * TICK_PS + n * UCLK_PS)

    def dreq(self):
        """The device task's request: SREQ, or a PS/2 port's edge not acked."""
        return bool(self.sreq or any(p.e for p in self.ps2))

    def irq(self):
        sources = self.sources | self.ps2[0].irq << 4 | self.ps2[1].irq << 5
        return int(bool(self.console.flag or sources))

    def odt_req(self):
        return int(bool(self.halt_req or self.trace))

    # ---- the timing the clock generator gives

    def f_stretch(self, m):
        """Ticks phase F is longer than three."""
        return 0

    def io_ticks(self, a, mop, m):
        """A half's ticks for an access to the I/O space: five, or a slow
        device's (board2.SLOW: its end, plus one)."""
        if self.region(a) == SLOWD:
            if a >> 6 & 1:
                return 8 if self.cffast else 32
            return 11
        return m.IO_TICKS

    def line(self):
        """The scanline, as the model has it: from 0 at reset, a line a
        LINE_TICKS (the netlist's counts from the vertical blank)."""
        return self.ticks // LINE_TICKS % FRAME_LINES

    def copreq(self, m):
        return bool(self.cen) and self.line() == self.target_line

    def tick(self, m, ticks):
        """A cycle's end."""
        self.ticks = m.ticks
        self.console.tick()
        now = self.ticks * TICK_PS
        for p in self.ps2:
            p.advance(now)
        if self.t1 and now >= self.t1[1]:
            period, t = self.t1
            while t <= now:
                t += period
            self.t1 = (period, t)
            self.sreq = 1
