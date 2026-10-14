"""Running a scene on the instruction-level simulator, phase by phase.

The program calls mark_n(name, count) at the end of every phase, which is
a HALT (asm/ISA/mark.s). At each one this records the cycles so far in
every configuration, the instructions, and a CRC-32 of the screen, then
resumes. A phase's cost is the difference from the previous mark.
"""

import os
import zlib
from collections import Counter

from heron.infra import isas
from heron.studies.v1_isa import timing32
from heron.studies.v1_isa.sim32 import Machine32, SimError

SCREEN_W, SCREEN_H = 640, 480
SCENES = ("prims", "text", "wm")
CONFIGS = timing32.CONFIG_NAMES


class Phase:
    def __init__(self, name, count, cycles, instructions, crc, keys=None):
        self.name = name
        self.count = count
        self.cycles = cycles                # {config: cycles}
        self.instructions = instructions
        self.crc = crc
        self.keys = keys                    # Counter((pc, timing key)) with profile=True

    def __repr__(self):
        return f"Phase({self.name!r}, {self.count}, {self.cycles['D16-overlap']:.0f}, {self.crc:08x})"


def cstring(mem, addr):
    end = mem.index(0, addr)
    return mem[addr:end].decode("latin-1")


def screen_bytes(mem, img, depth):
    base = img.symbols["_fb_mem"]
    return mem[base:base + ((SCREEN_W << depth) >> 3) * SCREEN_H]


def run(img, isa, scene, depth, profile=False, screens=None, max_cycles=4_000_000_000):
    """The phases of a scene at a depth: [Phase]. With screens, a function
    called with (phase name, screen bytes) at every mark."""
    m = Machine32(isas.get(isa), img, inp=f"{scene} {depth}\n".encode())
    mark_pc = img.symbols["_mark_n"] + 2        # just after its HALT
    phases = []
    prev_cyc = {c: 0 for c in CONFIGS}
    prev_ins = 0
    prev_keys = Counter()
    while True:
        try:
            m.run(max_cycles=max_cycles)
        except SimError as e:
            raise SimError(f"{scene} at depth {depth} on {isa}: {e}") from None
        if m.traps:
            pc, what = m.traps[0]
            raise SimError(f"{scene} at depth {depth} on {isa}: trap at {pc:X}: {what}")
        if m.pc != mark_pc:
            break
        mem = m.mem
        name = cstring(mem, m.r[1])
        count = m.r[2] - (1 << 32) if m.r[2] & 0x80000000 else m.r[2]
        cyc = m.all_cycles()
        keys = None
        if profile:
            now = m.pc_keys
            keys = now - prev_keys
            prev_keys = now
        scr = screen_bytes(mem, img, depth)
        if screens:
            screens(name, scr)
        phases.append(Phase(name, count, {c: cyc[c] - prev_cyc[c] for c in CONFIGS},
                            m.instructions - prev_ins, zlib.crc32(scr), keys))
        prev_cyc = cyc
        prev_ins = m.instructions
        m.resume()
    out = bytes(m.dev.out)
    if out:
        raise SimError(f"{scene} at depth {depth} on {isa} printed {out!r}")
    return phases


def expected_path(scene, depth):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "expected", f"{scene}-{depth}.txt")


def read_expected(scene, depth):
    """[(name, count, crc)] from the host reference, or None."""
    path = expected_path(scene, depth)
    if not os.path.exists(path):
        return None
    out = []
    with open(path) as f:
        for line in f:
            name, count, crc = line.split()
            out.append((name, int(count), int(crc, 16)))
    return out


def check(phases, scene, depth):
    """Differences from the host reference, as messages ([] if none)."""
    exp = read_expected(scene, depth)
    if exp is None:
        return [f"no expected output for {scene} at depth {depth} (heron graphics expected)"]
    got = [(p.name, p.count, p.crc) for p in phases]
    if got == exp:
        return []
    msgs = []
    if len(got) != len(exp):
        msgs.append(f"{len(got)} phases, expected {len(exp)}")
    for g, e in zip(got, exp):
        if g != e:
            msgs.append(f"phase {g[0]}: count {g[1]} crc {g[2]:08x}, expected {e[0]} {e[1]} {e[2]:08x}")
            break
    return msgs
