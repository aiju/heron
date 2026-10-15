"""The register-transfer model in Rust (studies/v1b_hw/rtl, heron.native.v1b_rtl).

It is rtl.py's datapath and sequencer, running the same ROM images, about
a hundred times faster. `rom()` hands it ucode.py's tables; `run()` runs a
whole program on it as rtl.RTL does. The instruction profiles
(studies/v1b_profile) use its shadow, which times each instruction the
instruction-level simulator executes.
"""

from functools import lru_cache

from heron import native
from . import ucode as uc


@lru_cache(maxsize=None)
def rom():
    """The microcode, decode ROM and routine facts as a native Rom."""
    mc = uc.built()
    words = mc.rom()
    names = [name for name, _, _ in uc.FIELDS]
    rows, row_of = [], {}
    index = []
    idle = uc.IDLE
    for a in range(1 << (uc.FAULT_BIT + 3)):
        w = words.get(a, idle)
        if w not in row_of:
            f = uc.unpack(w)
            row_of[w] = len(rows)
            rows.append([f[n] for n in names])
        index.append(row_of[w])
    illegal = [mc.keys[w][0] == "illegal" for w in range(0x10000)]
    return native.v1b_rtl.Rom(names, rows, index, mc.decode_rom(), illegal, mc.irq.addr)


def run(image, inp=b"", max_cycles=50_000_000):
    """Run an assembled image to HALT; the machine (cycles, rf, pc, flags,
    mem, out, pc_cycles())."""
    mem = bytearray(1 << 20)
    for a, b in image.mem.items():
        mem[a] = b
    m = native.v1b_rtl.Machine(rom(), bytes(mem), bytes(inp))
    m.run(max_cycles)
    return m
