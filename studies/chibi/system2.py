"""The board behind the two-halves machine's model (rtl2.py): the RAM, the
I/O space, the suite's console, as the CPU sees them.

The I/O space (A31 set), by MAR's bits 20-18 (board2.py has the details):

    000  0x8000_0000  UART 0          100  0x8010_0000  the boot flash (byte n at +2n)
    001  0x8004_0000  UART 1          101  0x8014_0000  the slow devices
    010  0x8008_0000  PS/2            110  0x8018_0000  the interrupt controller
    011  0x800C_0000  video control   111  0x801C_0000  the simulation's test fixture
                                                         (the suite's console, 0xFFFF_FF00)

The interrupt controller: +0 the sources pending (bit k: SOURCES[k]),
+2 the vector, 0x40 + 4k for the first source pending, 0x04 if none is
(an interrupt from outside: the test fixture's); +4 ODT's word (0x9000
when ODT is asked for, else 0); +6 the scanline (a write: the target
line, the copper's).
"""

from .system import Console, RAM_SIZE

SOURCES = ["TIRQ", "VIRQ", "U0INT", "U1INT", "KIRQ", "MIRQ", "CFIRQ", "BTNQ"]   # by priority


class System2:
    def __init__(self, inp=b""):
        self.ram = bytearray(RAM_SIZE)
        self.console = Console(inp)
        self.flash = bytes([0xFF]) * 0x20000
        self.video_ctl = 0
        self.palette_bank = 0
        self.target_line = 0
        self.sources = 0             # the board's interrupt sources (none modelled yet)
        self.cffast = 0
        self.halt_req = 0
        self.trace = 0

    def load(self, image):
        for a, b in image.mem.items():
            self.ram[a % RAM_SIZE] = b

    @staticmethod
    def region(a):
        return a >> 18 & 7

    def read16(self, a, io, cycle):
        if not io:
            a = (a % RAM_SIZE) & ~1
            return self.ram[a] | self.ram[a + 1] << 8
        r = self.region(a)
        if r == 7:
            return self.console.read(a, cycle)
        if r == 4:                              # the boot flash, a byte a halfword
            return self.flash[(a >> 1) & 0x1FFFF] | 0xFF00
        if r == 6:
            k = a >> 1 & 3
            if k == 0:
                return self.sources
            if k == 1:
                for i in range(8):
                    if self.sources >> i & 1:
                        return 0x40 + 4 * i
                return 0x04
            if k == 2:
                return 0x9000 if self.odt_req() else 0
            return 0
        return 0xFFFF                           # devices the model doesn't have

    def read_edge(self, a, io, cycle):
        if io and self.region(a) == 7:
            self.console.read_edge(a, cycle)

    def write(self, a, v, lanes, io):
        if not io:
            a = (a % RAM_SIZE) & ~1
            if lanes & 1:
                self.ram[a] = v & 0xFF
            if lanes & 2:
                self.ram[a + 1] = v >> 8 & 0xFF
            return
        r = self.region(a)
        if r == 7:
            self.console.write(a, v, lanes)
        elif r == 3:
            if a & 2:
                self.palette_bank = v & 15
            else:
                self.video_ctl = v
        elif r == 5:
            if a >> 4 & 7 == 3:
                self.cffast = v & 1
        elif r == 6:
            k = a >> 1 & 3
            if k == 2:
                self.trace = v & 1
                self.halt_req = 0
            elif k == 3:
                self.target_line = v & 0x1FF

    def irq(self):
        return int(bool(self.console.flag or self.sources))

    def odt_req(self):
        return int(bool(self.halt_req or self.trace))

    # ---- the timing the clock generator gives

    def f_stretch(self, m):
        """Ticks phase F is longer than three."""
        return 0

    def io_ticks(self, a, mop, m):
        """A half's ticks for an access to the I/O space: five, or a slow
        device's (board2.SLOW: its end, plus one)."""
        if self.region(a) == 5:
            if a >> 6 & 1:
                return 8 if self.cffast else 32
            return 10
        return m.IO_TICKS

    def copreq(self, m):
        return False

    def tick(self, m, ticks):
        """A cycle's end."""
        self.console.tick()
