"""Instruction-level simulator for the 32-bit draft 1 machines (1a and 1b).

The simulator itself is Rust (studies/v1_isa/isa, RFC 0015): the decoders,
the semantics and the timing model. This module gives it the interface the
studies use. Every executed instruction records a timing key, so timing32
can work out the cycle count for every hardware configuration from one run.
The machine's own `cycles` counter (used by the timer and the cycle limit)
follows the reference configuration.

I/O page at 0xFFFFFF00 (32-bit registers, see RFC 0004):
  +00  R: console input byte, or -1     W: console output (low byte)
  +04  R: bit 0 = input waiting, bit 1 = end of input
  +08  R/W: timer period in cycles (0 = off)
  +0C  R: timer flag                    W: acknowledge
  +10  R: cycle counter
"""

from collections import Counter

from heron import native
from . import timing32
from .v1common import RAM_SIZE

SimError = native.v1.SimError


class Devices:
    """The console, as the program left it."""

    def __init__(self, m):
        self._m = m

    @property
    def out(self):
        return bytearray(self._m.out)


class Machine32:
    """A draft 1 machine running a program: `isa` is the v1a or v1b
    module, `image` an assembled image, `inp` the console input.

    Registers, flags and memory are read-only views: r, hi, pc, n, z, c,
    v, i, mem. Set `trace` to a function to have it called with the
    machine before every instruction."""

    def __init__(self, isa, image=None, inp=b"", reference=timing32.REFERENCE):
        self.isa = isa
        mem = bytearray(RAM_SIZE)
        if image is not None:
            for addr, b in image.mem.items():
                mem[addr] = b
        self._m = native.v1.Machine(isa.NAME, bytes(mem), bytes(inp), reference)
        self.reference = reference
        self.dev = Devices(self._m)
        self.trace = None
        self._mem = None

    def step(self):
        if self.trace is not None:
            self.trace(self)
        self._mem = None
        self._m.step()

    def run(self, max_cycles=200_000_000):
        self._mem = None
        if self.trace is None:
            self._m.run(max_cycles)
            return self
        while not self.halted:
            self.step()
            if self.cycles > max_cycles:
                raise SimError(f"cycle limit of {max_cycles} reached at pc={self.pc:08X}")
        return self

    def resume(self):
        """Carry on after a HALT (a program can use one to mark a point
        for the tools); run() then continues with the next instruction."""
        self._mem = None
        self._m.resume()

    def parcel(self, addr):
        return self._m.parcel(addr)

    # ---- state ------------------------------------------------------------

    r = property(lambda self: self._m.r)
    hi = property(lambda self: self._m.hi)
    pc = property(lambda self: self._m.pc)
    n = property(lambda self: self._m.n)
    z = property(lambda self: self._m.z)
    c = property(lambda self: self._m.c)
    v = property(lambda self: self._m.v)
    i = property(lambda self: self._m.i)
    halted = property(lambda self: self._m.halted)
    cycles = property(lambda self: self._m.cycles)
    instructions = property(lambda self: self._m.instructions)
    traps = property(lambda self: self._m.traps, doc="(pc, what) for every trap but SWI")
    in_trap = property(lambda self: self._m.in_trap, doc="a trap (SWI too) was taken, and no RTI since")
    irqs = property(lambda self: self._m.irqs)
    min_sp = property(lambda self: self._m.min_sp)
    data_bytes = property(lambda self: self._m.data_bytes)

    @property
    def mem(self):
        """All of RAM (a copy, kept until the machine runs again)."""
        if self._mem is None:
            self._mem = self._m.mem
        return self._mem

    # ---- results ----------------------------------------------------------

    @property
    def pc_keys(self):
        """(instruction address, timing key) -> executions; interrupt entries
        have address None"""
        return Counter({(pc, k): n for pc, k, n in self._m.pc_keys()})

    @property
    def keys(self):
        """timing key -> executions"""
        out = Counter()
        for pc, k, n in self._m.pc_keys():
            out[k] += n
        return out

    @property
    def pc_counts(self):
        """instruction address -> executions (interrupt entries not included)"""
        out = Counter()
        for pc, k, n in self._m.pc_keys():
            if pc is not None:
                out[pc] += n
        return out

    def cycles_for(self, config, shifted=False):
        """Cycles in one configuration. shifted=True costs the program as if
        all its code sat one parcel further on (only the wide fetch cares)."""
        return self._m.cycles_for(config, shifted)

    def cycles_avg(self, config):
        """The wide fetch depends on where loops fall relative to 32-bit
        words; average the two possible code alignments for it."""
        if config.endswith("wide"):
            return (self.cycles_for(config) + self.cycles_for(config, True)) / 2
        return self.cycles_for(config)

    def pc_cycles(self, config):
        """instruction address -> cycles spent there (None: interrupt entries)"""
        return Counter(self._m.pc_cycles(config))

    def all_cycles(self):
        return {c: self.cycles_avg(c) for c in timing32.CONFIG_NAMES}

    def regs_str(self):
        r = self.r
        rs = " ".join(f"r{i}={r[i]:X}" for i in range(1, 16))
        fl = "".join(ch if bit else "-" for ch, bit in
                     zip("NZCVI", (self.n, self.z, self.c, self.v, self.i)))
        return f"pc={self.pc:X} {fl} hi={self.hi:X} {rs}"
