"""The board behind Heron Mini's CPU in the register-transfer model: the
RAM, the I/O space with its devices and their wait states, the interrupt
line, and the video's fetches from the RAM (RFC 0041).

Addresses (physical: there is no translation):

    0x0000_0000-0x7FFF_FFFF  RAM, 4 MB, repeated
    0x8000_0000 + region << 28, region 0-7: the I/O space, by PA[30:28]

        0  0x8000_0000  CF card, True IDE: CS0 registers at PA[4:2], CS1 with PA[5]
        1  0x9000_0000  expansion port 1
        2  0xA000_0000  expansion port 2
        3  0xB000_0000  82C54 timer (PA[3:2])
        4  0xC000_0000  (free)
        5  0xD000_0000  boot flash, 128K x 8, one byte a word (PA[18:2])
        6  0xE000_0000  UARTs, 16C550, a register a word (PA[4:2]); UART 1 with PA[5]
        7  0xF000_0000  video: registers, palette, the interrupt status; in the
                        simulations, a test card with the program suite's I/O
                        page (draft 1's console, timer and cycle counter) at
                        0xFFFF_FF00

An I/O access holds the CPU's microcycle for the region's wait states
(IO_HOLD, in master-clock ticks): 16 - 2r for region r, the slow devices
low. The 8-bit devices are on the low byte
lane, the CF card on the low half; their registers are a word apart, so
that word, half and byte loads all find them.
"""

from . import video

M32 = 0xFFFFFFFF
RAM_SIZE = 4 << 20
IO_BASE = 0x80000000
SUITE_PAGE = 0xFFFFFF00
# the wait states, per region, in ticks of 19.86 ns: the board's hold
# counter starts at 2r + 1 (the strobe is the hold's ticks but the first,
# and two more). Against the devices' datasheets: the CF card in PIO mode
# 0, 290 ns of strobe; the 82C54, 185 ns from the address; the boot flash,
# 55 ns; the TL16C550C, a 45 ns read
IO_HOLD = {r: 16 - 2 * r for r in range(8)}
R_CF, R_EXP1, R_EXP2, R_PIT, R_BOOT, R_UART, R_LOCAL = 0, 1, 2, 3, 5, 6, 7

# region 7's on-board registers (with PA21 low), by PA[12:10]: the video's
# (video.py), its palette, the interrupt status (a read; a write
# acknowledges the timer), the control register (the speaker, the LEDs)
L_VIDEO, L_PALETTE, L_STATUS, L_CTRL = 0x000, 0x400, 0x800, 0xC00


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
    """The video's registers and its interrupt (video.py has the picture,
    the timing and the layout of its registers). The interrupt is the
    picture's end, a frame every TICKS_FRAME master ticks; line interrupts
    (a descriptor's bit 23) aren't modelled."""

    def __init__(self):
        self.ctrl = 0
        self.palette = [0] * 256
        self.flag = 0
        self.frame = 0

    def write(self, off, v):
        if off < 0x400:
            if off & 4:
                self.flag = 0                       # the acknowledge
            else:
                self.ctrl = v & 7
        elif off < 0x800:
            self.palette[(off - 0x400) >> 2] = v & 0xFFFF

    def frame_tick(self, t):
        """The CPU's time moved to master tick t."""
        f = t // video.TICKS_FRAME
        if f != self.frame:
            self.frame = f
            self.flag = 1

    @property
    def irq(self):
        return bool(self.flag and self.ctrl & 4)


class System:
    """The board: the RAM, the I/O regions, the interrupt line, the video."""

    def __init__(self, ram_size=RAM_SIZE, inp=b"", uart_inp=b"", io_hold=None, boot=b""):
        self.ram = bytearray(ram_size)
        self.mask = ram_size - 1
        self.page = SuitePage(inp)
        self.uarts = [Uart(uart_inp), Uart()]
        self.video = Video()
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
        if region == R_BOOT:
            return self.boot[(pa >> 2) & 0x1FFFF]
        if region == R_UART:
            return self.uarts[(pa >> 5) & 1].read((pa >> 2) & 7)
        if region == R_LOCAL and pa & 0x0FFFFF00 == SUITE_PAGE & 0x0FFFFF00:
            return self.page.read(pa & 0xFF, size, cycle)
        if region == R_LOCAL and not pa & 0x200000 and pa & 0xC00 == L_STATUS:
            return self.status() * 0x01010101
        return 0

    def _io_write(self, region, pa, size, data, cycle):
        if region == R_UART:
            self.uarts[(pa >> 5) & 1].write((pa >> 2) & 7, data & 0xFF)
        elif region == R_LOCAL and pa & 0x0FFFFF00 == SUITE_PAGE & 0x0FFFFF00:
            self.page.write(pa & 0xFF, data, size)
        elif region == R_LOCAL and not pa & 0x200000 and pa & 0xC00 < L_STATUS:
            self.video.write(pa & 0x7FC, data)

    # ---- time ---------------------------------------------------------------

    def status(self):
        """The interrupt status register (board.py's U_ISR): the UARTs, the
        CF card and the timer (not modelled: 0), the video, the expansion
        ports' lines (active low, pulled up), the line."""
        s = (self.uarts[0].irq) | (self.uarts[1].irq << 1) | (self.video.irq << 4)
        s |= 0x60
        return s | (self.irq() << 7)

    def irq(self):
        """The interrupt line (any device requesting)."""
        return self.page.irq or any(u.irq for u in self.uarts) or self.video.irq

    def can_interrupt(self):
        """Something could still raise the interrupt line on its own."""
        return bool(self.page.period) or bool(self.video.ctrl & 4)

    def cycle(self, ticks, hold):
        """A CPU microcycle of `ticks` master ticks, `hold` of them an I/O
        access's wait. The video takes its slots from bank 1 without
        holding the CPU, so only its interrupt follows the time."""
        self.ticks += ticks
        self.video.frame_tick(self.ticks)
        self.page.tick()

    def output(self):
        return bytes(self.page.out)
