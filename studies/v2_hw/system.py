"""The memory system behind the draft 2 CPU in the register-transfer
model: address translation (RFC 0029, 3), the CPU card's own RAM, and the
system bus (RFC 0014) with the cards in its slots, each transfer costed in
master-clock ticks.

Physical addresses: the slot is PA[30:27], 16 slots of 128 MB, so that the
supervisor's window (the lower 2 GB) reaches every slot (RFC 0031 proposes
moving RFC 0014's slot bits from A31-A28 to A30-A27). Slot 0 is the CPU
card: its RAM, repeated through the slot.

The cards:
  - MemoryCard: a fast 32-bit card (report 0025's), one data clock for a
    read and two for a write;
  - ConsoleCard: draft 1's I/O page (console, timer, cycle counter: the
    device the program suite was written for) as a simple 16-bit card,
    N data clocks and a recovery clock per transfer.

A bus access holds the CPU's microcycle from its tick 3: the request
waits for the next bus clock edge, the transfer's clocks run, and the
answer crosses back, as on the draft 1b system's CPU card (report 0025,
13): hold = (wait for the edge, 1-3 ticks) + 3 x clocks + 4 ticks.
"""

M32 = 0xFFFFFFFF
TICKS_PER_BCLK = 3          # 60 ns bus clock from the 50 MHz master clock
HOLD_AT = 3                 # the hold starts at this tick of the microcycle
CROSS = 4                   # ticks for the request and the answer to cross
SLOT_SHIFT = 27


class Fault(Exception):
    """A page fault: fsr is the reason (RFC 0029, 3)."""

    def __init__(self, fsr):
        super().__init__(f"page fault, fsr {fsr:02X}")
        self.fsr = fsr


class BusError(Exception):
    """A transfer ended with BERR: an empty slot, or the bus monitor."""


def lanes_of(size, addr):
    """Byte lanes (bits 0-3) of an access."""
    if size == 3:
        return 0b1111
    if size == 2:
        return 0b0011 << (addr & 2)
    return 1 << (addr & 3)


def replicate(size, a):
    """The store data drivers: a word as it is, a half on both halves, a
    byte on all four lanes."""
    if size == 3:
        return a & M32
    if size == 2:
        return (a & 0xFFFF) * 0x10001
    return (a & 0xFF) * 0x01010101


class MemoryCard:
    """A fast 32-bit memory card."""
    width = 32
    simple = False
    read_clocks, write_clocks = 2, 3          # with the address clock

    def __init__(self, size=0x200000):
        self.mem = bytearray(size)
        self.mask = size - 1

    def read16(self, off):
        a = off & self.mask & ~1
        return self.mem[a] | (self.mem[a + 1] << 8)

    def read32(self, off):
        a = off & self.mask & ~3
        return int.from_bytes(self.mem[a:a + 4], "little")

    def write(self, off, value, lanes):
        a = off & self.mask & ~3
        for k in range(4):
            if lanes >> k & 1:
                self.mem[a + k] = (value >> (8 * k)) & 0xFF


class IODev:
    """Draft 1's I/O page seen from a 16-bit bus. Registers are 32 bits,
    read and written a half at a time (RFC 0004); time is the CPU's
    microcycles, which the timer and the cycle counter count."""

    def __init__(self, inp=b""):
        self.inp = bytearray(inp)
        self.pos = 0
        self.out = bytearray()
        self.period = 0
        self.count = 0
        self.flag = 0
        self.last_empty = False
        self.cyc_hi = 0

    def read(self, off, cycle):
        off &= 0xFE
        if off == 0x00:
            if self.pos < len(self.inp):
                self.pos += 1
                self.last_empty = False
                return self.inp[self.pos - 1]
            self.last_empty = True
            return 0xFFFF
        if off == 0x02:
            return 0xFFFF if self.last_empty else 0
        if off == 0x04:
            return 1 if self.pos < len(self.inp) else 2
        if off == 0x08:
            return self.period & 0xFFFF
        if off == 0x0A:
            return self.period >> 16
        if off == 0x0C:
            return self.flag
        if off == 0x10:
            self.cyc_hi = (cycle >> 16) & 0xFFFF
            return cycle & 0xFFFF
        if off == 0x12:
            return self.cyc_hi
        return 0

    def write(self, off, v, lanes):
        off &= 0xFE
        if off == 0x00 and lanes & 1:
            self.out.append(v & 0xFF)
        elif off == 0x08:
            self.period = (self.period & 0xFFFF0000) | (v & 0xFFFF)
            self.count = 0
            if self.period == 0:
                self.flag = 0
        elif off == 0x0A:
            self.period = (self.period & 0xFFFF) | ((v & 0xFFFF) << 16)
            self.count = 0
            if self.period == 0:
                self.flag = 0
        elif off in (0x0C, 0x0E):
            self.flag = 0

    def tick(self):
        if self.period:
            self.count += 1
            if self.count >= self.period:
                self.flag = 1
                self.count = 0


class ConsoleCard:
    """Draft 1's I/O page as a simple 16-bit card in its slot: the registers
    decoded from A7-A0, so they repeat every 256 bytes."""
    width = 16
    simple = True

    def __init__(self, inp=b"", n=6):
        self.dev = IODev(inp)
        self.read_clocks = self.write_clocks = n + 2   # address, N data clocks, recovery

    def read16(self, off, cycle):
        return self.dev.read(off & 0xFF, cycle)

    def write16(self, off, half, lanes):
        self.dev.write(off & 0xFF, half, lanes)


class System:
    """The memory system: translation, the CPU card's RAM, the bus."""

    def __init__(self, ram_size=0x200000, prefetch_bus=False, icache=0, io_local=False):
        self.ram = bytearray(ram_size)
        self.ram_mask = ram_size - 1
        self.map = [0] * (1 << 19)
        self.slots = {}
        self.prefetch_bus = prefetch_bus    # prefetch from bus space in any cycle, not only refills
        self.console = None
        self.bus_transfers = 0
        self.bus_reads = self.bus_writes = self.bus_fetches = 0
        # the instruction cache for code in bus space (RFC 0031, 7): icache
        # words, direct mapped by physical address, a word a line
        self.icache = icache
        self.itag = [None] * icache
        self.idata = [0] * icache
        self.icache_hits = 0
        self.io_local = io_local

    # ---- setup ---------------------------------------------------------

    def add(self, slot, card):
        self.slots[slot] = card
        if isinstance(card, ConsoleCard):
            self.console = card

    def load(self, image, base=0):
        """Put an assembled image's bytes at physical address base."""
        for a, b in image.mem.items():
            self.poke(base + a, b)

    def poke(self, pa, b):
        slot = (pa >> SLOT_SHIFT) & 15
        if slot == 0:
            self.ram[pa & self.ram_mask] = b
        else:
            card = self.slots[slot]
            card.mem[pa & card.mask] = b

    def peek(self, pa):
        slot = (pa >> SLOT_SHIFT) & 15
        if slot == 0:
            return self.ram[pa & self.ram_mask]
        card = self.slots[slot]
        return card.mem[pa & card.mask]

    def identity_map(self, ctx, pages, base=0, flags=0b111):
        """ctx's pages 0..pages-1 onto physical pages base.. (as boot
        software would set the map up)."""
        for p in range(pages):
            self.map[(ctx << 12) | p] = ((base + (p << 12)) & 0xFFFFF000) | flags

    # ---- translation (RFC 0029, 3) --------------------------------------

    def translate(self, va, kind, m):
        """kind 'read', 'write' or 'fetch'; raises Fault."""
        s = m.s
        acc = (0x20 if kind == "write" else 0) | (0x40 if kind == "fetch" else 0) | (s << 7)
        if va & 0x80000000:
            if s:
                return va & 0x7FFFFFFF
            raise Fault(0x10 | acc)
        if va >> 24:
            raise Fault(0x08 | acc)
        e = self.map[(m.CTX << 12) | ((va >> 12) & 0xFFF)]
        if not e & 1:
            raise Fault(0x01 | acc)
        if kind == "write" and not e & 2:
            raise Fault(0x02 | acc)
        if kind == "fetch" and not e & 4:
            raise Fault(0x04 | acc)
        return (e & 0xFFFFF000) | (va & 0xFFF)

    def map_read(self, mar):
        return self.map[(mar >> 12) & 0x7FFFF] & 0xFFFFF007

    def map_write(self, mar, value):
        self.map[(mar >> 12) & 0x7FFFF] = value & 0xFFFFF007

    def is_local(self, pa):
        return not pa & 0x80000000 and (pa >> SLOT_SHIFT) & 15 == 0

    # ---- transfers -------------------------------------------------------

    def _card(self, pa):
        slot = (pa >> SLOT_SHIFT) & 15
        card = self.slots.get(slot)
        if card is None:
            raise BusError()
        return card, pa & ((1 << SLOT_SHIFT) - 1)

    def _hold(self, m, clocks):
        """Ticks a bus access holds the current microcycle."""
        t0 = m.ticks + HOLD_AT
        edge = t0 + 1
        edge += (-edge) % TICKS_PER_BCLK
        self.bus_transfers += 1
        return (edge - t0) + TICKS_PER_BCLK * clocks + CROSS

    def _xfer_hold(self, m, card, clocks):
        """The hold of a transfer with `card`: none for the I/O page when it
        is on the CPU card's own data bus (io_local, as the chip-level
        test fixture is)."""
        if self.io_local and card is self.console:
            return 0
        return self._hold(m, clocks)

    def fetch_is_fast(self, pa):
        """A fetch at pa won't go to the bus: the CPU card's RAM, or a hit
        in the instruction cache."""
        if self.is_local(pa):
            return True
        return bool(self.icache) and self.itag[(pa >> 2) % self.icache] == pa >> 2

    def fetch(self, pa, m):
        """A 32-bit word for the prefetch queue: (word, hold)."""
        if self.is_local(pa):
            a = pa & self.ram_mask & ~3
            return int.from_bytes(self.ram[a:a + 4], "little"), 0
        if self.icache:
            i = (pa >> 2) % self.icache
            if self.itag[i] == pa >> 2:
                self.icache_hits += 1
                return self.idata[i], 0
        self.bus_fetches += 1
        w, h = self._bus_read(pa & ~3, 3, m)
        if self.icache:
            self.itag[i], self.idata[i] = pa >> 2, w
        return w, h

    def read(self, pa, size, va, m):
        """Memory data for a read: the bytes in their lanes. (D, hold)"""
        if self.is_local(pa):
            a = pa & self.ram_mask & ~3
            return int.from_bytes(self.ram[a:a + 4], "little"), 0
        self.bus_reads += 1
        return self._bus_read(pa, size, m)

    def _bus_read(self, pa, size, m):
        card, off = self._card(pa)
        if card.width == 32 and size == 3:
            return card.read32(off), self._xfer_hold(m, card, card.read_clocks)
        if card.simple:
            rd = (lambda o: card.read16(o, m.cycles))
        else:
            rd = card.read16
        if size == 3:
            # a 16-bit card: two transfers, the high half at A1 = 1
            lo = rd(off & ~3)
            hi = rd((off & ~3) | 2)
            return lo | (hi << 16), self._xfer_hold(m, card, 2 * card.read_clocks)
        half = rd(off & ~1)
        return (half * 0x10001) & M32, self._xfer_hold(m, card, card.read_clocks)

    def write(self, pa, size, va, a, m):
        """A store of size `size` with A the A bus. Returns the hold."""
        d = replicate(size, a)
        lanes = lanes_of(size, va)
        if self.is_local(pa):
            base = pa & self.ram_mask & ~3
            for k in range(4):
                if lanes >> k & 1:
                    self.ram[base + k] = (d >> (8 * k)) & 0xFF
            return 0
        self.bus_writes += 1
        if self.icache and self.itag[(pa >> 2) % self.icache] == pa >> 2:
            self.itag[(pa >> 2) % self.icache] = None       # the CPU's own store
        card, off = self._card(pa)
        if card.width == 32 and not card.simple:
            card.write(off, d, lanes)
            return self._xfer_hold(m, card, card.write_clocks)
        if size == 3:
            card.write16(off & ~3, d & 0xFFFF, 0b11)
            card.write16((off & ~3) | 2, d >> 16, 0b11)
            return self._xfer_hold(m, card, 2 * card.write_clocks)
        sh = 16 if off & 2 else 0
        card.write16(off & ~1, (d >> sh) & 0xFFFF, (lanes >> (2 if sh else 0)) & 3)
        return self._xfer_hold(m, card, card.write_clocks)

    # ---- interrupts and time -------------------------------------------

    def irq(self, m):
        return self.console.dev.flag if self.console else 0

    def can_interrupt(self):
        return bool(self.console and (self.console.dev.period or self.console.dev.flag))

    def tick(self, m, ticks):
        if self.console:
            self.console.dev.tick()

    def output(self):
        return bytes(self.console.dev.out) if self.console else b""
