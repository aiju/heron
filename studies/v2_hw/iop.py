"""Booting the draft 2 CPU from the I/O processor (RFC 0027, 8), at the
level of bus transfers.

The control store is SRAM and empty at power-up. A bus master reaches
three things on the CPU card in region 0 (RFC 0037, 5.1; RFC 0031, 6):

    0x0000_0000-0x0FFF_FFFF        the card's RAM (2 MB, repeated)
    0x7000_0000                    the control register: bit 0 RUN, bit 1
                                   RESET (a write of 1 runs the reset
                                   routine when RUN is next set), bit 3 NMI;
                                   read: bit 0 running, bit 1 halted
    0x7080_0000 + 0x2_0000 k       the control store's SRAM k, 64K x 16
                                   (k = 0-8: the microinstruction's 16-bit
                                   lanes, k = 9: the decode table), while
                                   RUN is off

and the other registers of RFC 0040, 3. At power-up RUN is off. The I/O
processor plays records of {bus address, count, halfwords} from its flash
into the card: the microcode's words that are used, all of the decode
table, and a boot program for RAM. Then RESET, RUN.

The boot program here is what a loader would put in front of the
program suite: the reset vector (physical 0, run in the window as
0x8000_0000) jumps to a shim near the top of RAM, which maps context 0's
first megabyte one to one, puts the program's own first parcels back, and
jumps to the program at virtual 0.
"""

from heron.infra import asm as asmcore
from heron.infra import isas

from . import ucode as uc
from .system import CS_LANE, CS_WINDOW, CTRL_RESET, CTRL_RUN, REGS, TICKS_PER_BCLK

LANES = uc.WORD_BITS // 16          # 9
DEC_LANE = LANES                    # SRAM 9: the decode table
CS_BASE = REGS + CS_WINDOW          # 0x7080_0000, for the card in region 0
CTRL = REGS
SHIM_AT = 0x1F0000

# position-independent: assembled at 0, loaded at SHIM_AT
SHIM = """
shim:   CLR  r1
        MTSR 12, r1             ; mapa: context 0, page 0
        MOV  r2, #7             ; physical page 0: X, W, V
        MOV  r3, #256           ; 1 MB
.map:   MTSR 13, r2             ; mapd; mapa moves on by one
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


def control_store(system):
    """The control store as the RTL model takes it: {address: word}, the
    words that were written."""
    cs = system.card.cs
    out = {}
    for a in range(0x10000):
        w = 0
        for k in range(LANES):
            w |= cs[k][a] << (16 * k)
        if w:
            out[a] = w
    return out


def decode_table(system):
    return system.card.cs[DEC_LANE]


class IOP:
    """The I/O processor's side of the boot: records played into the CPU
    card, two microcycles (four bus clocks) per halfword: one to read the
    image flash into its bus register, one to write it (RFC 0027, 4.1)."""
    CLOCKS_PER_HALF = 4

    def __init__(self, system):
        self.sys = system
        self.halfwords = 0
        self.records = 0

    def write(self, addr, halves):
        self.records += 1
        for i, h in enumerate(halves):
            self.sys.slave_write16(addr + 2 * i, h)
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
                self.write(CS_BASE + CS_LANE * k + 2 * s, halves)
        dec = mc.decode_table()
        self.write(CS_BASE + CS_LANE * DEC_LANE, dec)

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
            self.write(s, halves)

    def start(self):
        self.sys.slave_write16(CTRL, CTRL_RESET)              # RESET
        self.sys.slave_write16(CTRL, CTRL_RESET | CTRL_RUN)   # RUN


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
