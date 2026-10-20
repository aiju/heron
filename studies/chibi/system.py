"""The board behind the CPU in the register-transfer model: the RAM, the
I/O space and its devices, as the CPU sees them a cycle at a time.

The address map (A31 set: I/O; MAR holds A20-A0 and A31; the I/O
selects come from MAR's bits 20-18):

    0x0000_0000-0x001F_FFFF   RAM, 2 MB (four 512K x 8 as 1M x 16), and again every 2 MB
    0x8000_0000 + 2n          UART 0's register n (16C550, on MD 7-0)
    0x8004_0000 + 2n          UART 1's
    0x8008_0000               PS/2: +0 the keyboard's byte, +2 the mouse's, +4 and +6
                              their ports' control and status
    0x800C_0000               the video's control register: bit 0 the frame buffer
                              shown, 1 the display on, 2 the frame interrupt enabled
                              (the interrupt at the blank's start; a write clears it)
    0x8010_0000 + 2n          the boot flash's byte n (128K x 8, on MD 7-0)
    0x8018_0000 and up        (0xFFFF_FF00) the program suite's I/O page: a test fixture
                              (draft 1's console, timer and cycle counter, 32-bit
                              registers a half at a time)

The video reads RAM at 0x18_0000 + 512 * line + 2 * word (a line's 160
words of a 256-word stride), 0x1C_0000 for the second buffer.
"""

RAM_SIZE = 0x200000
FB_BASE = (0x180000, 0x1C0000)


class Console:
    """The suite's I/O page as the chip-level fixture `iodev32` has it
    (infra/hwsim/src/models.rs): console data at 0 (reading the low half
    takes a byte; the high half reads FFFF after a read that found none),
    status at 4, the timer's period at 8 and A (in cycles), its flag at C,
    the cycle counter at 10 and 12 (the high half as the low half's read
    left it)."""

    def __init__(self, inp=b""):
        self.inp = bytes(inp)
        self.pos = 0
        self.out = bytearray()
        self.period = 0
        self.count = 0
        self.flag = 0
        self.last_empty = False
        self.cycle_hi = 0

    def read(self, a, cycle):
        a &= 0xFE
        has = self.pos < len(self.inp)
        v = {0x00: self.inp[self.pos] if has else 0xFFFF,
             0x02: 0xFFFF if self.last_empty else 0,
             0x04: 1 if has else 2,
             0x08: self.period & 0xFFFF, 0x0A: self.period >> 16,
             0x0C: self.flag, 0x10: cycle & 0xFFFF, 0x12: self.cycle_hi}.get(a, 0)
        return v

    def read_edge(self, a, cycle):
        """The read's side effects, at the clock edge that ends it."""
        a &= 0xFE
        if a == 0x00:
            if self.pos < len(self.inp):
                self.pos += 1
                self.last_empty = False
            else:
                self.last_empty = True
        elif a == 0x10:
            self.cycle_hi = (cycle >> 16) & 0xFFFF

    def write(self, a, v, lanes):
        a &= 0xFE
        if a == 0x00:
            if lanes & 1:
                self.out.append(v & 0xFF)
        elif a == 0x08:
            self.period = v & 0xFFFF
            self.count = 0
            if v == 0:
                self.flag = 0
        elif a == 0x0A:
            self.period = (self.period & 0xFFFF) | (v & 0xFFFF) << 16
            self.count = 0
            if self.period == 0:
                self.flag = 0
        elif a in (0x0C, 0x0E):
            self.flag = 0

    def tick(self):
        """A CPU clock edge."""
        if self.period > 0:
            self.count += 1
            if self.count >= self.period:
                self.flag = 1
                self.count = 0


class System:
    """RAM and the I/O space. Reads give 16 bits; byte lanes are the
    CPU's (rtl.py)."""

    def __init__(self, inp=b""):
        self.ram = bytearray(RAM_SIZE)
        self.console = Console(inp)
        self.flash = bytes([0xFF]) * 0x20000
        self.video_ctl = 0

    def load(self, image):
        for a, b in image.mem.items():
            self.ram[a % RAM_SIZE] = b

    @staticmethod
    def is_console(a):
        return a >> 19 & 3 == 3

    def read16(self, a, io, cycle):
        if not io:
            a = (a % RAM_SIZE) & ~1
            return self.ram[a] | self.ram[a + 1] << 8
        if self.is_console(a):
            return self.console.read(a, cycle)
        if a >> 19 & 3 == 2:                    # the boot flash, a byte a halfword
            return self.flash[(a >> 1) & 0x1FFFF] | 0xFF00
        return 0xFFFF                           # devices the model doesn't have yet

    def read_edge(self, a, io, cycle):
        if io and self.is_console(a):
            self.console.read_edge(a, cycle)

    def write(self, a, v, lanes, io):
        """lanes: 1 the low byte (even address), 2 the high (odd), 3 both."""
        if not io:
            a = (a % RAM_SIZE) & ~1
            if lanes & 1:
                self.ram[a] = v & 0xFF
            if lanes & 2:
                self.ram[a + 1] = v >> 8 & 0xFF
            return
        if self.is_console(a):
            self.console.write(a, v, lanes)
        elif (a >> 18) & 7 == 3:
            self.video_ctl = v

    def irq(self):
        return self.console.flag

    def tick(self):
        self.console.tick()
