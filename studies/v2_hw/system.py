"""The memory system behind the draft 2 CPU in the register-transfer
model: address translation (RFC 0029, 3), the CPU card (its RAM, and its
registers: RFC 0040, 3), and the system bus (RFC 0037) with the cards on
it, each transfer costed in master-clock ticks.

Physical addresses (RFC 0037, 5.1): seven regions of memory, 256 MB each,
below 0x7000_0000, and registers above, those of the card in region N at
0x7N00_0000. The CPU card is in region 0: its RAM repeats through
0x0000_0000-0x0FFF_FFFF, and the CPU reaches its own registers at
0x7000_0000 locally, without the bus. Here a memory card can sit in region
1, at 0x1000_0000.

The suite's I/O page (draft 1's console, timer and cycle counter: the
device the program suite was written for, RFC 0004) is a test fixture at
the top of the map, where the I/O bus's window is, as a simple 16-bit card.
Nothing else answers: a read returns stale data and nothing traps (RFC
0037, 27).

The cards:
  - MemoryCard: a fast 32-bit card (report 0025's), one data clock for a
    read and two for a write;
  - ConsoleCard: the I/O page, N data clocks and a recovery clock per
    transfer.

A bus access holds the CPU's microcycle from its tick 3: the request
waits for the next bus clock edge, the transfer's clocks run, and the
answer crosses back, as on the draft 1b system's CPU card (report 0025,
13): hold = (wait for the edge, 1-3 ticks) + 3 x clocks + 4 ticks.
"""

M32 = 0xFFFFFFFF
TICKS_PER_BCLK = 3          # 60 ns bus clock from the 50 MHz master clock
HOLD_AT = 3                 # the hold starts at this tick of the microcycle
CROSS = 4                   # ticks for the request and the answer to cross
REGION = 1 << 28            # a memory region (RFC 0037, 5.1)
REGS = 0x70000000           # registers: the card in region N at REGS + N << 24
REGS_SIZE = 1 << 24
IO_WINDOW = 0x7F000000      # the I/O bus's window: here the suite's I/O page
# the CPU card's registers (RFC 0040, 3), offsets from its REGS base
R_CTRL, R_INFO = 0x0000, 0x1000
R_REQ_SET, R_REQ_CLR, R_REQ = 0x2000, 0x2004, 0x2008
R_MSG_CLAIM, R_MSG, R_MSG_REL, R_MSG_READ = 0x3000, 0x3004, 0x3008, 0x300C
R_TIMER, R_TIMER_CLR = 0x4000, 0x4004
# the control store's write window (RFC 0031, 6): SRAM k, 64K x 16, at
# CS_WINDOW + CS_LANE x k, k = 0-8 the microinstruction's 16-bit lanes and
# 9 the decode table, while RUN is off
CS_WINDOW, CS_LANE = 0x800000, 0x20000
# the control register's bits
CTRL_RUN, CTRL_RESET, CTRL_STEP, CTRL_NMI = 1, 2, 4, 8
MSG_FREE, MSG_CLAIMED, MSG_FULL = 0, 1, 2


class Fault(Exception):
    """A page fault: fsr is the reason (RFC 0029, 3)."""

    def __init__(self, fsr):
        super().__init__(f"page fault, fsr {fsr:02X}")
        self.fsr = fsr


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


class CPUCard:
    """The CPU card's registers (RFC 0040, 3; RFC 0037, 9), as any master
    and the CPU itself see them, and its control store window for the I/O
    processor. Words, written whole except the message register, which a
    16-bit master writes low half then high half.

    The timer counts BCLK from reset; the tick is the 0 to 1 edges of
    counter bit tick_bit (a jumper; None: none fitted), the profiling tick
    the same for prof_bit at level 8."""

    def __init__(self, ram_size, region=0, tick_bit=None, prof_bit=None, lanes=10):
        self.ram_size = ram_size
        self.region = region
        self.tick_bit, self.prof_bit = tick_bit, prof_bit
        self.cs = [[0] * 0x10000 for _ in range(lanes)]
        self.run = True              # the RTL model starts it running
        self.reset_req = False
        self.halted = False
        self.reset()

    def reset(self):
        """RESET: the request register clear, the message register free, the
        timer cleared, no NMI."""
        self.req = 0                 # bit L: level L, 1-8
        self.msg_state, self.msg, self.msg_lo = MSG_FREE, 0, None
        self.nmi_latch = 0
        self.count = 0               # BCLKs
        self.tick = self.prof = 0
        self.claims = self.claims_refused = self.messages = 0

    # ---- what the CPU's interrupt logic sees

    def levels(self):
        lv = self.req | (self.tick << 6) | ((self.msg_state == MSG_FULL) << 7) | (self.prof << 8)
        return lv & 0x1FE

    def msg_word(self):
        """The message register on the CPU's B bus: {message, source}."""
        return ((self.msg & 0xFFFFFF) << 8) | (self.msg >> 24)

    def msg_release(self):
        self.msg_state = MSG_FREE

    def nmi_ack(self):
        self.nmi_latch = 0

    def advance(self, bclks):
        """The timer, bclks bus clocks on."""
        old, self.count = self.count, (self.count + bclks) & M32
        for bit, attr in ((self.tick_bit, "tick"), (self.prof_bit, "prof")):
            if bit is not None:
                half = 1 << bit
                if (old + bclks + half) >> (bit + 1) != (old + half) >> (bit + 1):
                    setattr(self, attr, 1)

    # ---- the registers

    def info(self):
        """Board information (a proposal): the region in bits 3-0, the RAM
        size in MB (log2) in 7-4, BCLK's period in ns in 15-8."""
        return (self.region | ((self.ram_size >> 20).bit_length() - 1) << 4
                | (TICKS_PER_BCLK * 20) << 8)

    def read(self, off):
        off &= ~3
        if off == R_CTRL:
            return (int(self.run) | (int(self.halted) << 1) | 4
                    | (self.nmi_latch << 3))
        if off == R_INFO:
            return self.info()
        if off == R_REQ:
            return self.req
        if off == R_MSG_CLAIM:
            self.claims += 1
            if self.msg_state == MSG_FREE:
                self.msg_state = MSG_CLAIMED
                return 0
            self.claims_refused += 1
            return 1
        if off == R_MSG_READ:
            return self.msg
        if off == R_TIMER:
            return self.count
        return 0

    def write(self, off, v, half=None):
        """A word, or with half 0 or 1 a 16-bit master's low or high half."""
        off &= ~3
        if off == R_CTRL:
            if half == 1:
                return
            if v & CTRL_RESET:
                self.reset_req = True
                self.reset()
            if v & CTRL_NMI:
                self.nmi_latch = 1
            self.run = bool(v & CTRL_RUN)
        elif off == R_REQ_SET and half != 1:
            self.req |= v & 0x1FE
        elif off == R_REQ_CLR and half != 1:
            self.req &= ~v & 0x1FE
        elif off == R_MSG:
            if self.msg_state != MSG_CLAIMED:
                return                                   # ignored: free or full
            if half == 0:
                self.msg_lo = v & 0xFFFF
                return
            if half == 1:
                if self.msg_lo is None:
                    return
                v = (v << 16) | self.msg_lo
            self.msg, self.msg_lo = v & M32, None
            self.msg_state = MSG_FULL
            self.messages += 1
        elif off == R_MSG_REL and half != 1:
            self.msg_state, self.msg_lo = MSG_FREE, None
        elif off == R_TIMER_CLR and half != 1:
            if v & 1:
                self.tick = 0
            if v & 2:
                self.prof = 0

    def can_interrupt(self):
        return bool(self.req or self.msg_state == MSG_FULL or self.nmi_latch
                    or self.tick_bit is not None or self.prof_bit is not None
                    or self.tick or self.prof)


class System:
    """The memory system: translation, the CPU card's RAM and registers, the
    bus."""

    def __init__(self, ram_size=0x200000, prefetch_bus=False, icache=0, io_local=False,
                 tick_bit=None, prof_bit=None):
        self.ram = bytearray(ram_size)
        self.ram_mask = ram_size - 1
        self.map = [0] * (1 << 19)
        self.cards = []              # (physical base, size, card) on the bus
        self.card = CPUCard(ram_size, tick_bit=tick_bit, prof_bit=prof_bit)
        self.card_writes = []
        self.prefetch_bus = prefetch_bus    # prefetch from bus space in any cycle, not only refills
        self.console = None
        self.bus_transfers = 0
        self.bus_reads = self.bus_writes = self.bus_fetches = 0
        self.unanswered = 0
        self.stale = 0               # what an unanswered read returns: the last data
        self.ticks_total = 0
        # the instruction cache for code in bus space (RFC 0031, 7): icache
        # words, direct mapped by physical address, a word a line
        self.icache = icache
        self.itag = [None] * icache
        self.idata = [0] * icache
        self.icache_hits = 0
        self.io_local = io_local

    # ---- setup ---------------------------------------------------------

    def add(self, base, card):
        """A card answering from physical base: a region of memory, or the
        I/O page at the top."""
        size = REGION if base < REGS else (1 << 32) - base
        self.cards.append((base, size, card))
        if isinstance(card, ConsoleCard):
            self.console = card

    def load(self, image, base=0):
        """Put an assembled image's bytes at physical address base."""
        for a, b in image.mem.items():
            self.poke(base + a, b)

    def poke(self, pa, b):
        if pa < REGION:
            self.ram[pa & self.ram_mask] = b
        else:
            card, off = self._card(pa)
            card.mem[off & card.mask] = b

    def peek(self, pa):
        if pa < REGION:
            return self.ram[pa & self.ram_mask]
        card, off = self._card(pa)
        return card.mem[off & card.mask]

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
        """The CPU card's RAM."""
        return pa < REGION

    def is_own_reg(self, pa):
        """The CPU card's own registers, which the CPU reaches locally."""
        return REGS <= pa < REGS + REGS_SIZE and pa - REGS < CS_WINDOW

    # ---- transfers -------------------------------------------------------

    def _card(self, pa):
        for base, size, card in self.cards:
            if base <= pa < base + size:
                return card, pa - base
        return None, 0

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
        if self.is_own_reg(pa):
            return self.card.read(pa - REGS), 0
        self.bus_reads += 1
        return self._bus_read(pa, size, m)

    def _bus_read(self, pa, size, m):
        card, off = self._card(pa)
        if card is None:
            # nothing answers: the bus holds what it had, one data clock
            self.unanswered += 1
            return self.stale, self._hold(m, 2)
        if card.width == 32 and size == 3:
            d = card.read32(off)
            self.stale = d
            return d, self._xfer_hold(m, card, card.read_clocks)
        if card.simple:
            rd = (lambda o: card.read16(o, m.cycles))
        else:
            rd = card.read16
        if size == 3:
            # a 16-bit card: two transfers, the high half at A1 = 1
            lo = rd(off & ~3)
            hi = rd((off & ~3) | 2)
            self.stale = lo | (hi << 16)
            return self.stale, self._xfer_hold(m, card, 2 * card.read_clocks)
        half = rd(off & ~1)
        self.stale = (half * 0x10001) & M32
        return self.stale, self._xfer_hold(m, card, card.read_clocks)

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
        if self.is_own_reg(pa):
            self.card_writes.append((pa - REGS, d))       # at the cycle's end
            return 0
        self.bus_writes += 1
        if self.icache and self.itag[(pa >> 2) % self.icache] == pa >> 2:
            self.itag[(pa >> 2) % self.icache] = None       # the CPU's own store
        card, off = self._card(pa)
        if card is None:
            self.unanswered += 1
            return self._hold(m, 2)
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

    # ---- the slave side: what other masters see of the CPU card ---------

    def slave_write16(self, pa, v):
        """A 16-bit master's write into the CPU card: its RAM, its registers,
        its control store window."""
        if pa < REGION:
            a = pa & self.ram_mask & ~1
            self.ram[a] = v & 0xFF
            self.ram[a + 1] = (v >> 8) & 0xFF
            return
        off = pa - REGS
        if not 0 <= off < REGS_SIZE:
            raise ValueError(f"{pa:08X} isn't the CPU card's")
        if off >= CS_WINDOW:
            if self.card.run:
                raise RuntimeError("the control store written while the CPU runs")
            k, a = divmod(off - CS_WINDOW, CS_LANE)
            self.card.cs[k][a >> 1] = v & 0xFFFF
            return
        self.card.write(off, v & 0xFFFF, half=(off >> 1) & 1)

    def slave_read16(self, pa):
        if pa < REGION:
            a = pa & self.ram_mask & ~1
            return self.ram[a] | (self.ram[a + 1] << 8)
        off = pa - REGS
        if off >= CS_WINDOW:
            k, a = divmod(off - CS_WINDOW, CS_LANE)
            return self.card.cs[k][a >> 1]
        w = self.card.read(off) if not off & 2 else self._last_reg_word
        if not off & 2:
            self._last_reg_word = w
        return (w >> 16) & 0xFFFF if off & 2 else w & 0xFFFF

    _last_reg_word = 0

    # ---- interrupts and time -------------------------------------------

    def levels(self):
        return self.card.levels()

    def msg_full(self):
        return self.card.msg_state == MSG_FULL

    def nmi(self):
        return self.card.nmi_latch

    def msg_word(self):
        return self.card.msg_word()

    def msg_release(self):
        self.card.msg_release()

    def nmi_ack(self):
        self.card.nmi_ack()

    def can_interrupt(self):
        return self.card.can_interrupt()

    def edge(self):
        """The CPU's clock edge, after it has sampled the levels: its writes
        to its own registers happen (as the write strobe rises, at the
        cycle's end)."""
        for off, d in self.card_writes:
            self.card.write(off, d)
        self.card_writes.clear()

    def tick(self, m, ticks):
        old = self.ticks_total // TICKS_PER_BCLK
        self.ticks_total += ticks
        self.card.advance(self.ticks_total // TICKS_PER_BCLK - old)
        if self.console:
            self.console.dev.tick()

    def output(self):
        return bytes(self.console.dev.out) if self.console else b""
