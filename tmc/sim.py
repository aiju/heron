"""Instruction-level simulator.

The Machine owns memory, the I/O page and statistics; the ISA module
supplies `step(m)`. Cycle counts come from a timing function, normally
derived from the microcode (tmc.hw.microcode), so the instruction-level
simulator and the chip-level simulator should agree cycle for cycle.

I/O page (word registers, see docs/isa-v0.md):
  FF00  W: console out (low byte)    R: console in (byte, or 0xFFFF if none)
  FF02  R: bit 0 = console input waiting, bit 1 = end of input
  FF04  W: timer period in cycles (0 = off)
  FF06  R: timer flag               W: acknowledge (clear flag)
  FF08  R: cycle counter bits 15..0 (latches bits 31..16 into FF0A)
  FF0A  R: latched cycle counter bits 31..16
"""

from collections import Counter


class Devices:
    def __init__(self, inp=b""):
        self.out = bytearray()
        self.inp = bytearray(inp)
        self.timer_period = 0
        self.timer_next = 0
        self.timer_flag = 0
        self.cycle_hi_latch = 0

    def irq(self):
        return self.timer_flag

    def tick(self, cycles):
        if self.timer_period:
            while cycles >= self.timer_next:
                self.timer_flag = 1
                self.timer_next += self.timer_period

    def read(self, addr, cycles):
        a = addr & 0xFFFE
        if a == 0xFF00:
            if self.inp:
                return self.inp.pop(0)
            return 0xFFFF
        if a == 0xFF02:
            # bit 0: a byte is waiting; bit 1: end of input (all input is
            # supplied up front in the simulators, so empty means closed)
            return 1 if self.inp else 2
        if a == 0xFF06:
            return self.timer_flag
        if a == 0xFF08:
            self.cycle_hi_latch = (cycles >> 16) & 0xFFFF
            return cycles & 0xFFFF
        if a == 0xFF0A:
            return self.cycle_hi_latch
        return 0

    def write(self, addr, value, cycles):
        a = addr & 0xFFFE
        if a == 0xFF00:
            self.out.append(value & 0xFF)
        elif a == 0xFF04:
            self.timer_period = value
            self.timer_next = cycles + value
            self.timer_flag = 0 if value == 0 else self.timer_flag
        elif a == 0xFF06:
            self.timer_flag = 0


class SimError(Exception):
    pass


class Machine:
    def __init__(self, isa, image=None, inp=b"", timing=None):
        self.isa = isa
        self.mem = bytearray(0x10000)
        if image is not None:
            for addr, b in image.mem.items():
                self.mem[addr] = b
        self.dev = Devices(inp)
        self.r = [0] * 16
        self.pc = isa.RESET_VECTOR
        self.n = self.z = self.c = self.v = self.i = 0
        self.halted = False
        self.cycles = 0
        self.instructions = 0
        self.timing = timing
        self.timing_cache = {}
        self.kinds = Counter()
        self.kind_cycles = Counter()
        self.irqs = 0
        self.illegals = []
        self.min_sp = 0x10000
        self.io_base = isa.IO_BASE
        self.trace = None
        self.fetch_log = None   # list of (cycle of fetch, pc, word) when enabled
        self.reg_written = [True] * 16

    # ---- memory ---------------------------------------------------------

    def rd16(self, addr):
        addr &= 0xFFFE
        if addr >= self.io_base:
            return self.dev.read(addr, self.cycles) & 0xFFFF
        return self.mem[addr] | (self.mem[addr + 1] << 8)

    def wr16(self, addr, v):
        addr &= 0xFFFE
        if addr >= self.io_base:
            self.dev.write(addr, v & 0xFFFF, self.cycles)
            return
        self.mem[addr] = v & 0xFF
        self.mem[addr + 1] = (v >> 8) & 0xFF

    def rd8(self, addr):
        addr &= 0xFFFF
        if addr >= self.io_base:
            v = self.dev.read(addr, self.cycles)
            return (v >> 8) & 0xFF if addr & 1 else v & 0xFF
        return self.mem[addr]

    def wr8(self, addr, v):
        addr &= 0xFFFF
        if addr >= self.io_base:
            self.dev.write(addr, v & 0xFF, self.cycles)
            return
        self.mem[addr] = v & 0xFF

    def illegal(self, w):
        self.illegals.append((self.pc, w))

    # ---- execution ------------------------------------------------------

    def cost(self, w, taken):
        if self.timing is None:
            return 1
        key = (w, taken)
        c = self.timing_cache.get(key)
        if c is None:
            c = self.timing_cache[key] = self.timing(w, taken)
        return c

    def step(self):
        """Execute one instruction, then take an interrupt if one is due.

        Like the hardware, the interrupt check happens at the end of an
        instruction and uses the I flag as it was before the instruction's
        last cycle: an interrupt can't hit the instruction right after EI,
        can still hit right after DI, and is taken right after RTI if the
        restored flags enable it.
        """
        if self.trace is not None:
            self.trace(self)
        if self.fetch_log is not None:
            # the hardware fetches an instruction in the last cycle of the previous one
            self.fetch_log.append((self.cycles - 1, self.pc, self.rd16(self.pc)))
        i_before = self.i
        w, taken = self.isa.step(self)
        c = self.cost(w, taken)
        self.cycles += c
        self.instructions += 1
        k = self.isa.kind(w)
        self.kinds[k] += 1
        self.kind_cycles[k] += c
        sp = self.r[15]
        if sp < self.min_sp and sp != 0:
            self.min_sp = sp
        self.dev.tick(self.cycles)
        if self.halted and self.i and (self.dev.irq() or self.dev.timer_period):
            # HALT with interrupts on waits for an interrupt; one that's
            # already pending is taken at once
            if not self.dev.irq():
                self.cycles = max(self.cycles, self.dev.timer_next)
                self.dev.tick(self.cycles)
            self.halted = False
            i_before = 1
        enabled = self.i if k == "RTI" else i_before
        if enabled and self.dev.irq() and not self.halted:
            self.irqs += 1
            self.isa.enter_interrupt(self, self.isa.IRQ_VECTOR)
            c = self.timing("irq", None) if self.timing else 1
            self.cycles += c
            self.kinds["<irq entry>"] += 1
            self.kind_cycles["<irq entry>"] += c
            self.dev.tick(self.cycles)

    def run(self, max_cycles=50_000_000):
        while not self.halted:
            self.step()
            if self.cycles > max_cycles:
                raise SimError(f"cycle limit of {max_cycles} reached at pc={self.pc:04X}")
        return self

    def regs_str(self):
        rs = " ".join(f"r{i}={self.r[i]:04X}" for i in range(1, 16))
        fl = "".join(ch if bit else "-" for ch, bit in
                     zip("NZCVI", (self.n, self.z, self.c, self.v, self.i)))
        return f"pc={self.pc:04X} {fl} {rs}"
