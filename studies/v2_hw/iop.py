"""Booting the draft 2 CPU from the I/O processor (RFC 0027), at the level
of bus transfers.

The control store is SRAM and empty at power-up. The CPU card's slave
port (RFC 0031, 6) gives a bus master three things in the card's slot:

    offset 0x000_0000-0x3FF_FFFF   the card's RAM (2 MB, repeated)
    offset 0x400_0000 + 0x2_0000 k the control store's SRAM k, 64K x 16
                                   (k = 0-8: the microinstruction's 16-bit
                                   lanes, k = 9: the decode table), while
                                   RUN is off
    offset 0x600_0000              the control register: bit 0 RUN, bit 1
                                   RESET (a write of 1 runs the reset
                                   routine when RUN is next set); read:
                                   bit 0 running, bit 1 halted

At power-up RUN is off. The I/O processor plays records of {bus address,
count, halfwords} from its flash into the slot: the microcode's words that
are used, all of the decode table, and a boot program for RAM. Then
RESET, RUN.

The boot program here is what a loader would put in front of the
program suite: the reset vector (physical 0, run in the window as
0x8000_0000) jumps to a shim near the top of RAM, which maps context 0's
first megabyte one to one, puts the program's own first parcels back, and
jumps to the program at virtual 0.
"""

from heron.infra import asm as asmcore
from heron.infra import isas

from . import ucode as uc
from .system import SLOT_SHIFT, TICKS_PER_BCLK

CS_BASE = 0x4000000
CS_LANE = 0x20000
CTRL = 0x6000000
LANES = uc.WORD_BITS // 16          # 9
DEC_LANE = LANES                    # SRAM 9: the decode table
SHIM_AT = 0x1F0000

# position-independent: assembled at 0, loaded at SHIM_AT
SHIM = """
shim:   CLR  r1
        MTSR 11, r1             ; mapa: context 0, page 0
        MOV  r2, #7             ; physical page 0: X, W, V
        MOV  r3, #256           ; 1 MB
.map:   MTSR 12, r2             ; mapd; mapa moves on by one
        ADD  r2, #0x1000
        DBNZ r3, .map
        MOV  r4, [pc + saved]   ; the program's first six bytes, back
        MOV  [0x80000000], r4
        MOV  r4, half [pc + saved + 4]
        MOV  half [0x80000004], r4
        CLR  r1
        CLR  r2
        CLR  r3
        CLR  r4
        JMP  #0                 ; the program's reset vector, through the map
        .align 4
saved:  .word 0, 0
"""


class CPUCardSlave:
    """The CPU card as a bus slave: what other masters see in slot 0."""

    def __init__(self, system):
        self.sys = system
        self.cs = [[0] * 0x10000 for _ in range(LANES + 1)]
        self.run = False
        self.reset = False
        self.transfers = 0

    def write16(self, off, v):
        self.transfers += 1
        if off < CS_BASE:
            a = off & self.sys.ram_mask & ~1
            self.sys.ram[a] = v & 0xFF
            self.sys.ram[a + 1] = (v >> 8) & 0xFF
        elif off < CTRL:
            if self.run:
                raise RuntimeError("the control store written while the CPU runs")
            k = (off - CS_BASE) // CS_LANE
            self.cs[k][((off - CS_BASE) % CS_LANE) >> 1] = v & 0xFFFF
        else:
            if v & 2:
                self.reset = True
            self.run = bool(v & 1)

    def read16(self, off):
        self.transfers += 1
        if off < CS_BASE:
            a = off & self.sys.ram_mask & ~1
            return self.sys.ram[a] | (self.sys.ram[a + 1] << 8)
        if off < CTRL:
            k = (off - CS_BASE) // CS_LANE
            return self.cs[k][((off - CS_BASE) % CS_LANE) >> 1]
        return int(self.run)

    def rom(self):
        """The control store as the RTL model takes it: {address: word}, the
        words that were written."""
        out = {}
        for a in range(0x10000):
            w = 0
            for k in range(LANES):
                w |= self.cs[k][a] << (16 * k)
            if w != self._blank:
                out[a] = w
        return out

    _blank = 0

    def decode(self):
        return self.cs[DEC_LANE]


class IOP:
    """The I/O processor's side of the boot: records played into the slot,
    two microcycles (four bus clocks) per halfword: one to read the image
    flash into its bus register, one to write it (RFC 0027, 4.2)."""
    CLOCKS_PER_HALF = 4

    def __init__(self, slave, slot=0):
        self.slave = slave
        self.base = slot << SLOT_SHIFT
        self.halfwords = 0
        self.records = 0

    def write(self, addr, halves):
        self.records += 1
        for i, h in enumerate(halves):
            self.slave.write16((addr - self.base) + 2 * i, h)
        self.halfwords += len(halves)

    def ticks(self):
        return self.halfwords * self.CLOCKS_PER_HALF * TICKS_PER_BCLK

    def load_microcode(self, mc):
        """The used words of the control store, a lane at a time, in runs of
        consecutive addresses; and the whole decode table."""
        rom = mc.rom()
        used = sorted(rom)
        runs, start, prev = [], None, None
        for a in used:
            if start is None:
                start = prev = a
            elif a == prev + 1:
                prev = a
            else:
                runs.append((start, prev))
                start = prev = a
        runs.append((start, prev))
        for k in range(LANES):
            for s, e in runs:
                halves = [(rom[a] >> (16 * k)) & 0xFFFF for a in range(s, e + 1)]
                self.write(self.base + CS_BASE + CS_LANE * k + 2 * s, halves)
        dec = mc.decode_table()
        self.write(self.base + CS_BASE + CS_LANE * DEC_LANE, dec)

    def load_ram(self, mem):
        """{physical address: byte}, as halfwords in runs."""
        addrs = sorted({a & ~1 for a in mem})
        runs, start, prev = [], None, None
        for a in addrs:
            if start is None:
                start = prev = a
            elif a == prev + 2:
                prev = a
            else:
                runs.append((start, prev))
                start = prev = a
        if start is not None:
            runs.append((start, prev))
        for s, e in runs:
            halves = [mem.get(a, 0) | (mem.get(a + 1, 0) << 8) for a in range(s, e + 2, 2)]
            self.write(self.base + s, halves)

    def start(self):
        self.slave.write16(CTRL - 0, 0b10)     # RESET
        self.slave.write16(CTRL - 0, 0b11)     # RUN


def boot_image(image):
    """The RAM contents the I/O processor loads for a suite program: the
    program, the shim, and the reset vector pointing at the shim."""
    mem = dict(image.mem)
    shim = asmcore.assemble_text(isas.get("v2"), SHIM, "shim.s")
    smem = {SHIM_AT + a: b for a, b in shim.mem.items()}
    saved = SHIM_AT + shim.symbols["saved"]
    for i in range(6):
        smem[saved + i] = mem.get(i, 0)
    mem.update(smem)
    # the reset vector: JMP to the shim in the window (Jcc, absolute: 6 bytes)
    target = 0x80000000 | SHIM_AT
    jmp = [0xF3, 0xE0, target & 0xFF, (target >> 8) & 0xFF, (target >> 16) & 0xFF, target >> 24]
    for i, b in enumerate(jmp):
        mem[i] = b
    return mem
