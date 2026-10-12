"""Instruction-level simulator for the 32-bit draft 1 machines (1a and 1b).

The ISA module decodes each instruction once into a closure (see
tmc/isa/v1common.py) that executes it and returns a timing key. The machine
counts the keys, so tmc.timing32 can work out the cycle count for every
hardware configuration from one run. Its own `cycles` counter (used by the
timer and the cycle limit) follows the reference configuration.

I/O page at 0xFFFFFF00 (32-bit registers, see docs/isa-v1.md):
  +00  R: console input byte, or -1     W: console output (low byte)
  +04  R: bit 0 = input waiting, bit 1 = end of input
  +08  R/W: timer period in cycles (0 = off)
  +0C  R: timer flag                    W: acknowledge
  +10  R: cycle counter
"""

from collections import Counter

from . import timing32
from .isa.v1common import (Trap, M32, RAM_SIZE, IO_BASE, IRQ_VECTOR, ILLEGAL_VECTOR,
                           SWI_VECTOR, DIV_VECTOR, ADDR_VECTOR, enter_interrupt)


class SimError(Exception):
    pass


TRAP_NAMES = {ILLEGAL_VECTOR: "illegal instruction", SWI_VECTOR: "SWI",
              DIV_VECTOR: "divide error", ADDR_VECTOR: "address error"}


class Devices:
    def __init__(self, inp=b""):
        self.out = bytearray()
        self.inp = bytearray(inp)
        self.pos = 0
        self.timer_period = 0
        self.timer_next = 0
        self.timer_flag = 0

    def irq(self):
        return self.timer_flag

    def tick(self, cycles):
        if self.timer_period:
            while cycles >= self.timer_next:
                self.timer_flag = 1
                self.timer_next += self.timer_period

    def read(self, reg, cycles):
        if reg == 0x00:
            if self.pos < len(self.inp):
                self.pos += 1
                return self.inp[self.pos - 1]
            return M32
        if reg == 0x04:
            return 1 if self.pos < len(self.inp) else 2
        if reg == 0x08:
            return self.timer_period
        if reg == 0x0C:
            return self.timer_flag
        if reg == 0x10:
            return cycles & M32
        return 0

    def write(self, reg, value, cycles):
        if reg == 0x00:
            self.out.append(value & 0xFF)
        elif reg == 0x08:
            self.timer_period = value
            self.timer_next = cycles + value
            if value == 0:
                self.timer_flag = 0
        elif reg == 0x0C:
            self.timer_flag = 0


class Machine32:
    def __init__(self, isa, image=None, inp=b"", reference=timing32.REFERENCE):
        self.isa = isa
        self.mem = bytearray(RAM_SIZE)
        if image is not None:
            for addr, b in image.mem.items():
                self.mem[addr] = b
        self.dev = Devices(inp)
        self.r = [0] * 16
        self.hi = 0
        self.pc = isa.RESET_VECTOR
        self.n = self.z = self.c = self.v = self.i = 0
        self.halted = False
        self.cycles = 0
        self.instructions = 0
        self.pc_keys = Counter()        # (instruction address, timing key) -> executions
        self.reference = reference
        self._ref = {}
        self.cache = {}                 # pc -> (fn, parcels)
        self.code = bytearray(RAM_SIZE >> 1)   # parcels covered by cached instructions
        self.traps = []                 # (pc, what)
        self.irqs = 0
        self.min_sp = M32
        self.trace = None
        self.data_bytes = 0

    # ---- memory ----------------------------------------------------------

    def parcel(self, addr):
        addr &= M32
        if addr + 1 >= RAM_SIZE:
            raise SimError(f"instruction fetch from {addr:08X}, outside RAM")
        return self.mem[addr] | (self.mem[addr + 1] << 8)

    def _io(self, addr, size, value=None):
        reg = (addr - IO_BASE) & ~3
        shift = 8 * (addr & 3)
        if value is None:
            v = self.dev.read(reg, self.cycles)
            return (v >> shift) & ((1 << (8 * size)) - 1)
        self.dev.write(reg, value, self.cycles)
        return None

    def _bad(self, addr):
        raise SimError(f"access to unmapped address {addr:08X} at pc {self.pc:08X}")

    def rd8(self, a):
        self.data_bytes += 1
        if a < RAM_SIZE:
            return self.mem[a]
        if a >= IO_BASE:
            return self._io(a, 1)
        self._bad(a)

    def rd16(self, a):
        self.data_bytes += 2
        if a & 1:
            raise Trap(ADDR_VECTOR, True, f"misaligned half read at {a:08X}")
        if a < RAM_SIZE:
            return self.mem[a] | (self.mem[a + 1] << 8)
        if a >= IO_BASE:
            return self._io(a, 2)
        self._bad(a)

    def rd32(self, a):
        self.data_bytes += 4
        if a & 3:
            raise Trap(ADDR_VECTOR, True, f"misaligned word read at {a:08X}")
        if a < RAM_SIZE:
            m = self.mem
            return m[a] | (m[a + 1] << 8) | (m[a + 2] << 16) | (m[a + 3] << 24)
        if a >= IO_BASE:
            return self._io(a, 4)
        self._bad(a)

    def wr8(self, a, v):
        self.data_bytes += 1
        if a < RAM_SIZE:
            if self.code[a >> 1]:
                self.flush()
            self.mem[a] = v & 0xFF
        elif a >= IO_BASE:
            self._io(a, 1, v & 0xFF)
        else:
            self._bad(a)

    def wr16(self, a, v):
        self.data_bytes += 2
        if a & 1:
            raise Trap(ADDR_VECTOR, True, f"misaligned half write at {a:08X}")
        if a < RAM_SIZE:
            if self.code[a >> 1]:
                self.flush()
            self.mem[a] = v & 0xFF
            self.mem[a + 1] = (v >> 8) & 0xFF
        elif a >= IO_BASE:
            self._io(a, 2, v & 0xFFFF)
        else:
            self._bad(a)

    def wr32(self, a, v):
        self.data_bytes += 4
        if a & 3:
            raise Trap(ADDR_VECTOR, True, f"misaligned word write at {a:08X}")
        if a < RAM_SIZE:
            if self.code[a >> 1] or self.code[(a >> 1) + 1]:
                self.flush()
            m = self.mem
            m[a] = v & 0xFF
            m[a + 1] = (v >> 8) & 0xFF
            m[a + 2] = (v >> 16) & 0xFF
            m[a + 3] = (v >> 24) & 0xFF
        elif a >= IO_BASE:
            self._io(a, 4, v & M32)
        else:
            self._bad(a)

    def flush(self):
        """A store hit cached code (self-modifying code): forget all decodes."""
        self.cache.clear()
        self.code = bytearray(RAM_SIZE >> 1)

    # ---- execution -------------------------------------------------------

    def decode(self, pc):
        fn, n = self.isa.decode(self, pc)
        self.cache[pc] = (fn, n)
        for i in range(n):
            self.code[((pc >> 1) + i) & ((RAM_SIZE >> 1) - 1)] = 1
        return fn, n

    def ref_cycles(self, key):
        c = self._ref.get(key)
        if c is None:
            c = self._ref[key] = timing32.cycles(key, self.reference)
        return c

    def step(self):
        pc = self.pc
        if self.trace is not None:
            self.trace(self)
        d = self.cache.get(pc)
        if d is None:
            if pc & 1:
                raise SimError(f"odd PC {pc:08X}")
            d = self.decode(pc)
        fn, n = d
        i_before = self.i
        try:
            key = fn(self)
        except Trap as t:
            what = t.why or TRAP_NAMES.get(t.vector, "trap")
            if t.vector != SWI_VECTOR:
                self.traps.append((pc, what))
            ret = pc if t.fault else self.pc
            enter_interrupt(self, t.vector, ret)
            key = (n, pc & 2, "trap")
        self.pc_keys[pc, key] += 1
        self.cycles += self.ref_cycles(key)
        self.instructions += 1
        sp = self.r[15]
        if sp < self.min_sp and sp:
            self.min_sp = sp
        dev = self.dev
        if dev.timer_period:
            dev.tick(self.cycles)
        if self.halted and self.i and (dev.irq() or dev.timer_period):
            if not dev.irq():
                self.cycles = max(self.cycles, dev.timer_next)
                dev.tick(self.cycles)
            self.halted = False
            i_before = 1
        enabled = self.i if key[2] == "rti" else i_before
        if enabled and dev.irq() and not self.halted:
            self.irqs += 1
            enter_interrupt(self, IRQ_VECTOR, self.pc)
            k = (1, 0, "irq")
            self.pc_keys[None, k] += 1
            self.cycles += self.ref_cycles(k)
            dev.tick(self.cycles)

    def run(self, max_cycles=200_000_000):
        while not self.halted:
            self.step()
            if self.cycles > max_cycles:
                raise SimError(f"cycle limit of {max_cycles} reached at pc={self.pc:08X}")
        return self

    # ---- results ---------------------------------------------------------

    @property
    def keys(self):
        """timing key -> executions"""
        out = Counter()
        for (pc, k), n in self.pc_keys.items():
            out[k] += n
        return out

    @property
    def pc_counts(self):
        """instruction address -> executions (interrupt entries not included)"""
        out = Counter()
        for (pc, k), n in self.pc_keys.items():
            if pc is not None:
                out[pc] += n
        return out

    def cycles_for(self, config):
        return sum(cnt * timing32.cycles(k, config) for (pc, k), cnt in self.pc_keys.items())

    def pc_cycles(self, config):
        """instruction address -> cycles spent there (None: interrupt entries)"""
        out = Counter()
        for (pc, k), n in self.pc_keys.items():
            out[pc] += n * timing32.cycles(k, config)
        return out

    def all_cycles(self):
        return {c: self.cycles_for(c) for c in timing32.CONFIG_NAMES}

    def regs_str(self):
        rs = " ".join(f"r{i}={self.r[i]:X}" for i in range(1, 16))
        fl = "".join(ch if bit else "-" for ch, bit in
                     zip("NZCVI", (self.n, self.z, self.c, self.v, self.i)))
        return f"pc={self.pc:X} {fl} hi={self.hi:X} {rs}"
