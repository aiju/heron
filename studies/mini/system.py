"""The board behind Heron Mini's CPU in the register-transfer model: the
RAM, the I/O space with its devices and their wait states, the interrupt
line, and the video's fetches from the RAM (RFC 0041).

Addresses (physical: there is no translation):

    0x0000_0000-0x7FFF_FFFF  RAM, 4 MB, repeated
    0x8000_0000 + region << 28, region 0-7: the I/O space, by PA[30:28]

        0  0x8000_0000  boot flash, 128K x 8, one byte a word (PA[18:2])
        1  0x9000_0000  UART 0, 16C550, a register a word (PA[4:2])
        2  0xA000_0000  UART 1
        3  0xB000_0000  82C54 timer (PA[3:2])
        4  0xC000_0000  CF card, True IDE: CS0 registers at PA[4:2], CS1 with PA[5]
        5  0xD000_0000  video: registers, palette, the interrupt status
        6  0xE000_0000  expansion port 1
        7  0xF000_0000  expansion port 2; in the simulations, a test card with
                        the program suite's I/O page (draft 1's console,
                        timer and cycle counter) at 0xFFFF_FF00

An I/O access holds the CPU's microcycle for the region's wait states
(IO_HOLD, in master-clock ticks). The 8-bit devices are on the low byte
lane, the CF card on the low half; their registers are a word apart, so
that word, half and byte loads all find them.
"""

M32 = 0xFFFFFFFF
RAM_SIZE = 4 << 20
IO_BASE = 0x80000000
SUITE_PAGE = 0xFFFFFF00
# the wait states, per region: the access's strobe and recovery, from the
# devices' datasheets (TL16C550C 45 ns read, 82C54 185 ns from the
# address, the CF card in PIO mode 0, 290 ns of strobe), in ticks of 19.86 ns
IO_HOLD = {0: 4, 1: 4, 2: 4, 3: 11, 4: 16, 5: 2, 6: 8, 7: 2}

# video registers (region 5), offsets
V_CTRL, V_TABLE, V_STATUS, V_IRQ = 0x000, 0x004, 0x008, 0x00C
V_PALETTE = 0x400                    # 256 entries, a word apart: RGB 5:6:5


def replicate(size, a):
    """The store data: a word as it is, a half on both halves, a byte on
    all four lanes."""
    if size == 3:
        return a & M32
    if size == 2:
        return (a & 0xFFFF) * 0x10001
    return (a & 0xFF) * 0x01010101


def lanes_of(size, addr):
    """Byte lanes (bits 0-3) of an access."""
    if size == 3:
        return 0b1111
    if size == 2:
        return 0b0011 << (addr & 2)
    return 1 << (addr & 3)


class SuitePage:
    """Draft 1's I/O page (RFC 0004, 26), as the chip-level simulator's
    32-bit fixture has it: registers of 32 bits, each read as two 16-bit
    halves; time is the CPU's microcycles, which the timer and the cycle
    counter count."""

    def __init__(self, inp=b""):
        self.inp = bytearray(inp)
        self.pos = 0
        self.out = bytearray()
        self.period = 0
        self.count = 0
        self.flag = 0
        self.cyc_hi = 0

    def read(self, off, size, cycle):
        """A read at offset off (bits 7-0): the value on the 32-bit data
        bus, by lanes as the fixture drives it."""
        w = off & 0xFC
        lanes = lanes_of(size, off)
        lo_half, hi_half = bool(lanes & 3), bool(lanes & 12)
        empty = self.pos >= len(self.inp)
        vals = []
        for h, used in ((0, lo_half), (1, hi_half)):
            a = w + 2 * h
            if a == 0x00:
                v = 0xFFFF if empty else self.inp[self.pos]
            elif a == 0x02:
                v = 0xFFFF if empty else 0
            elif a == 0x04:
                v = 1 if not empty else 2
            elif a == 0x08:
                v = self.period & 0xFFFF
            elif a == 0x0A:
                v = self.period >> 16
            elif a == 0x0C:
                v = self.flag
            elif a == 0x10:
                v = cycle & 0xFFFF
            elif a == 0x12:
                v = (cycle >> 16) & 0xFFFF if (lo_half and hi_half) else self.cyc_hi
            else:
                v = 0
            vals.append(v)
        if lo_half and hi_half:
            value = vals[0] | (vals[1] << 16)
        elif lo_half:
            value = vals[0] * 0x10001
        else:
            value = vals[1] * 0x10001
        # side effects, at the end of the read
        if lo_half and w == 0x00 and not empty:
            self.pos += 1
        if lo_half and w == 0x10:
            self.cyc_hi = (cycle >> 16) & 0xFFFF
        return value

    def write(self, off, v, size):
        w = off & 0xFC
        lanes = lanes_of(size, off)
        for h in (0, 1):
            if not lanes & (3 << (2 * h)):
                continue
            a = w + 2 * h
            half = (v >> (16 * h)) & 0xFFFF
            if a == 0x00 and lanes & 1:
                self.out.append(half & 0xFF)
            elif a == 0x08:
                self.period = (self.period & 0xFFFF0000) | half
                self.count = 0
                if self.period == 0:
                    self.flag = 0
            elif a == 0x0A:
                self.period = (self.period & 0xFFFF) | (half << 16)
                self.count = 0
                if self.period == 0:
                    self.flag = 0
            elif a in (0x0C, 0x0E):
                self.flag = 0

    def tick(self):
        """A CPU clock edge."""
        if self.period:
            self.count += 1
            if self.count >= self.period:
                self.flag = 1
                self.count = 0

    @property
    def irq(self):
        return bool(self.flag)


class Uart:
    """A 16C550, as far as programs here use it: transmit, receive with
    the line status register, the receive interrupt."""

    def __init__(self, inp=b""):
        self.inp = bytearray(inp)
        self.pos = 0
        self.out = bytearray()
        self.ier = self.lcr = self.mcr = self.scr = 0
        self.dll = self.dlm = 0

    def read(self, reg):
        dlab = self.lcr & 0x80
        if reg == 0:
            if dlab:
                return self.dll
            if self.pos < len(self.inp):
                self.pos += 1
                return self.inp[self.pos - 1]
            return 0
        if reg == 1:
            return self.dlm if dlab else self.ier
        if reg == 2:
            return 0xC4 if self.irq else 0xC1
        if reg == 3:
            return self.lcr
        if reg == 4:
            return self.mcr
        if reg == 5:
            return 0x60 | (1 if self.pos < len(self.inp) else 0)
        if reg == 6:
            return 0
        return self.scr

    def write(self, reg, v):
        dlab = self.lcr & 0x80
        if reg == 0:
            if dlab:
                self.dll = v
            else:
                self.out.append(v)
        elif reg == 1:
            if dlab:
                self.dlm = v
            else:
                self.ier = v & 0x0F
        elif reg == 3:
            self.lcr = v
        elif reg == 4:
            self.mcr = v
        elif reg == 7:
            self.scr = v

    @property
    def irq(self):
        return bool(self.ier & 1 and self.pos < len(self.inp))


class Video:
    """The video's registers and palette, and its fetches (RFC 0041):
    640 x 480 at 4 bits a pixel, from 800 x 525 pixel clocks of 2 master
    ticks. Each line's descriptor, a word of the table at TB + 4 x line,
    gives the line's address in the RAM (1 KB rows: bits 11-0 the row),
    its first word in the row (19-12), its palette bank (23-20), and in
    bit 31 a line interrupt. The pixels are 80 words a line, fetched in
    the CPU's video slots (the last two ticks of every microcycle and the
    ticks an I/O access holds); this model checks that every word was
    fetched before the display needed it, and counts the slots it used."""

    H_TOTAL, V_TOTAL = 800, 525
    WORDS = 80                       # 640 pixels at 4 bits
    TICKS_WORD = 16                  # 8 pixels of 2 ticks
    LEAD = 32                        # the first word is fetched this early

    def __init__(self, enabled=False):
        self.ctrl = 1 if enabled else 0
        self.table = 0
        self.palette = [0] * 256
        self.irq_pending = 0
        self.irq_enable = 0
        self.underflows = 0
        self.fetches = 0
        self.t = 0                   # master ticks since the frame started
        self.need = None             # the next fetch: (earliest tick, deadline)
        self.line = 0
        self.word = 0

    # the display's schedule: for line y < 480, the descriptor in the line
    # before's blanking, then word j's fetch, due when the shifter takes
    # word j - 1 (or, for word 0, LEAD ticks before the line starts)
    def _schedule(self):
        """(earliest, deadline) of the next fetch, from the line and word."""
        line_ticks = 2 * self.H_TOTAL
        start = self.line * line_ticks
        if self.word < 0:            # the descriptor, in the line before's blanking
            return (start - 2 * 160, start - self.LEAD)
        due = start + self.TICKS_WORD * self.word
        earliest = due - self.TICKS_WORD if self.word else start - self.LEAD
        return (earliest, due)

    def slot(self, t0, t1):
        """A video slot from master tick t0 to t1 (the frame's ticks wrap)."""
        if not self.ctrl & 1:
            return
        frame = 2 * self.H_TOTAL * self.V_TOTAL
        while True:
            if self.need is None:
                if self.line >= 480:
                    return
                self.need = self._schedule()
            earliest, due = self.need
            if t1 - 2 < earliest:
                return
            if t0 > due:
                self.underflows += 1
            self.fetches += 1
            self._advance()
            if t1 - t0 < 4:
                return

    def _advance(self):
        self.need = None
        if self.word == -1:
            self.word = 0
            return
        self.word += 1
        if self.word == self.WORDS:
            self.word = -1
            self.line += 1

    def frame_tick(self, t):
        """The CPU's time moved to master tick t (from the start)."""
        frame = 2 * self.H_TOTAL * self.V_TOTAL
        if t // frame != self.t // frame:
            self.line, self.word, self.need = 0, -1, None
            self.irq_pending |= 1                    # vertical blank, from the frame's end
        self.t = t

    def read(self, off):
        if off == V_CTRL:
            return self.ctrl
        if off == V_TABLE:
            return self.table
        if off == V_STATUS:
            return self.irq_pending
        if off == V_IRQ:
            return self.irq_enable
        if V_PALETTE <= off < V_PALETTE + 0x400:
            return self.palette[(off - V_PALETTE) >> 2]
        return 0

    def write(self, off, v):
        if off == V_CTRL:
            self.ctrl = v & 1
        elif off == V_TABLE:
            self.table = v & 0x3FF000
        elif off == V_STATUS:
            self.irq_pending &= ~v
        elif off == V_IRQ:
            self.irq_enable = v & 3
        elif V_PALETTE <= off < V_PALETTE + 0x400:
            self.palette[(off - V_PALETTE) >> 2] = v & 0xFFFF

    @property
    def irq(self):
        return bool(self.irq_pending & self.irq_enable)

    def render(self, ram):
        """The frame as the display would show it: 480 rows of 640 RGB
        triples (bytes), from the descriptors and the palette."""
        rows = []
        for y in range(480):
            d = int.from_bytes(ram[(self.table + 4 * y) % len(ram):][:4], "little")
            base = ((d & 0xFFF) << 10) + (((d >> 12) & 0xFF) << 2)
            bank = (d >> 20) & 15
            row = bytearray()
            for j in range(self.WORDS):
                a = (base + 4 * j) % len(ram)
                word = int.from_bytes(ram[a:a + 4], "little")
                for k in range(8):
                    c = self.palette[(bank << 4) | ((word >> (4 * k)) & 15)]
                    row += bytes(((c >> 11) << 3, ((c >> 5) & 63) << 2, (c & 31) << 3))
            rows.append(bytes(row))
        return rows


class System:
    """The board: the RAM, the I/O regions, the interrupt line, the video."""

    def __init__(self, ram_size=RAM_SIZE, inp=b"", uart_inp=b"", video=False, io_hold=None,
                 boot=b""):
        self.ram = bytearray(ram_size)
        self.mask = ram_size - 1
        self.page = SuitePage(inp)
        self.uarts = [Uart(uart_inp), Uart()]
        self.video = Video(video)
        self.boot = bytearray(boot) + bytearray(0x20000 - len(boot))
        self.io_hold = dict(IO_HOLD, **(io_hold or {}))
        self.ticks = 0
        self.io_ticks = 0

    def load(self, image, base=0):
        for a, b in image.mem.items():
            self.ram[(base + a) & self.mask] = b

    # ---- the CPU's accesses: (value, hold ticks) -----------------------------

    @staticmethod
    def is_io(pa):
        return bool(pa & IO_BASE)

    def read(self, pa, size, cycle):
        """A read of `size` (1 byte, 2 half, 3 word) at pa: the aligned
        word as the data bus carries it, and the ticks it holds the cycle."""
        if not self.is_io(pa):
            a = pa & self.mask & ~3
            return int.from_bytes(self.ram[a:a + 4], "little"), 0
        region = (pa >> 28) & 7
        hold = self.io_hold[region]
        self.io_ticks += hold
        return self._io_read(region, pa, size, cycle) & M32, hold

    def write(self, pa, size, value, cycle):
        """A store of the A bus's value, replicated by size; the hold."""
        data = replicate(size, value)
        lanes = lanes_of(size, pa)
        if not self.is_io(pa):
            a = pa & self.mask & ~3
            for k in range(4):
                if lanes >> k & 1:
                    self.ram[a + k] = (data >> (8 * k)) & 0xFF
            return 0
        region = (pa >> 28) & 7
        hold = self.io_hold[region]
        self.io_ticks += hold
        self._io_write(region, pa, size, data, cycle)
        return hold

    def fetch(self, pa):
        a = pa & self.mask & ~3
        return int.from_bytes(self.ram[a:a + 4], "little")

    def _io_read(self, region, pa, size, cycle):
        if region == 0:
            return self.boot[(pa >> 2) & 0x1FFFF]
        if region in (1, 2):
            return self.uarts[region - 1].read((pa >> 2) & 7)
        if region == 5:
            return self.video.read(pa & 0xFFC)
        if region == 7 and pa & 0x0FFFFF00 == SUITE_PAGE & 0x0FFFFF00:
            return self.page.read(pa & 0xFF, size, cycle)
        return 0

    def _io_write(self, region, pa, size, data, cycle):
        if region in (1, 2):
            self.uarts[region - 1].write((pa >> 2) & 7, data & 0xFF)
        elif region == 5:
            self.video.write(pa & 0xFFC, data)
        elif region == 7 and pa & 0x0FFFFF00 == SUITE_PAGE & 0x0FFFFF00:
            self.page.write(pa & 0xFF, data, size)

    # ---- time ---------------------------------------------------------------

    def irq(self):
        """The interrupt line (any device requesting)."""
        return self.page.irq or any(u.irq for u in self.uarts) or self.video.irq

    def can_interrupt(self):
        """Something could still raise the interrupt line on its own."""
        return bool(self.page.period) or bool(self.video.irq_enable and self.video.ctrl & 1)

    def cycle(self, ticks, hold):
        """A CPU microcycle of `ticks` master ticks, `hold` of them an I/O
        access's wait: the video's slots in it (its last two ticks, and the
        hold), and the devices' time."""
        t0 = self.ticks
        t1 = t0 + ticks
        v = self.video
        if v.ctrl & 1:
            v.frame_tick(t0)
            if hold:
                v.slot(t1 - 2 - hold, t1 - 2)
            v.slot(t1 - 2, t1)
        self.ticks = t1
        self.page.tick()

    def output(self):
        return bytes(self.page.out)
