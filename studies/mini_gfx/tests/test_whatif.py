"""The what-if block instructions (whatif.py) against what they should do,
on the mini's simulator with the extended microcode."""

import random
import unittest

from heron.infra import asm as asmcore
from heron.infra import isas
from heron.studies.mini import sim
from heron.studies.mini_gfx import whatif

SRC, DST, TAB, TAB2 = 0x10000, 0x20000, 0x30000, 0x31000
M32 = 0xFFFFFFFF


def ror(x, n):
    n %= 32
    return ((x >> n) | (x << (32 - n))) & M32 if n else x


def run(op, regs, mem):
    """Set the registers, the memory, clear the condition latch the hard
    way (a CMP equal sets nothing in CL; it's the fix's test), run the
    instruction; the machine."""
    lines = ["        .org 0", "        JMP start", "        .org 0x1C", "start:"]
    lines += [f"        MOV  r{r}, #{v & M32}" for r, v in regs.items()]
    lines += [f"        .half {op:#06x}", "        HALT"]
    a = asmcore.Assembler(isas.get("v2"))
    a.load("t.s", text="\n".join(lines) + "\n")
    m = sim.machine(mc=whatif.extended())
    sim.load(m, a.assemble())
    for addr, data in mem.items():
        m.load(addr, data)
    if m.run(1_000_000) != "halted":
        raise AssertionError("didn't halt")
    return m


def words(m, addr, n):
    b = m.read(addr, 4 * n)
    return [int.from_bytes(b[4 * k:4 * k + 4], "little") for k in range(n)]


def pack(ws):
    return b"".join((w & M32).to_bytes(4, "little") for w in ws)


class WhatIf(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(42)

    def rnd(self, n):
        return [self.rng.getrandbits(32) for _ in range(n)]

    def test_fillx(self):
        d = self.rnd(10)
        m = run(0x04FD, {1: DST + 4, 2: 0x0F0F00FF, 3: 7}, {DST: pack(d)})
        want = d[:1] + [w ^ 0x0F0F00FF for w in d[1:8]] + d[8:]
        self.assertEqual(words(m, DST, 10), want)
        self.assertEqual(m.r[1], DST + 32)

    def test_expandt(self):
        d, tab = self.rnd(6), self.rnd(256)
        src = bytes(self.rng.getrandbits(8) for _ in range(6))
        m = run(0x05FD, {1: DST, 2: SRC, 3: 6, 4: TAB, 5: 0x12345678},
                {DST: pack(d), SRC: src, TAB: pack(tab)})
        want = [x ^ ((x ^ 0x12345678) & tab[b]) for x, b in zip(d, src)]
        self.assertEqual(words(m, DST, 6), want)
        self.assertEqual((m.r[1], m.r[2]), (DST + 24, SRC + 6))

    def test_expand2(self):
        t0, t1 = self.rnd(256), self.rnd(256)
        src = bytes(self.rng.getrandbits(8) for _ in range(10))
        m = run(0x06FD, {1: DST, 2: SRC, 3: 5, 4: TAB, 0: TAB2, 5: 0xF0F0F0F0, 6: 0x01234567},
                {SRC: src, TAB: pack(t0), TAB2: pack(t1)})
        want = [0x01234567 ^ ((t0[src[2 * k]] | t1[src[2 * k + 1]]) & 0xF0F0F0F0)
                for k in range(5)]
        self.assertEqual(words(m, DST, 5), want)

    def test_expand1(self):
        s = self.rnd(5)
        m = run(0x07FD, {1: DST, 2: SRC, 3: 5, 5: 0xAAAA5555, 6: 0x0F0F0F0F}, {SRC: pack(s)})
        self.assertEqual(words(m, DST, 5), [0x0F0F0F0F ^ (w & 0xAAAA5555) for w in s])

    def test_expand8(self):
        tab = self.rnd(512)
        src = bytes(self.rng.getrandbits(8) for _ in range(4))
        m = run(0x08FD, {1: DST, 2: SRC, 3: 4, 4: TAB, 5: 0x3C3C3C3C, 6: 0x11111111},
                {SRC: src, TAB: pack(tab)})
        want = []
        for b in src:
            want += [0x11111111 ^ (tab[2 * b] & 0x3C3C3C3C), 0x11111111 ^ (tab[2 * b + 1] & 0x3C3C3C3C)]
        self.assertEqual(words(m, DST, 8), want)
        self.assertEqual(m.r[1], DST + 32)

    def test_blitn(self):
        for n in range(32):
            s = self.rnd(6)
            lo0 = self.rng.getrandbits(32)
            mask = M32 >> n
            m = run(0x20FD + (n << 8), {1: DST, 2: SRC, 3: 6, 5: lo0, 0: mask}, {SRC: pack(s)})
            lo, want = lo0, []
            for w in s:
                hi = ror(w, n)
                want.append(hi ^ ((lo ^ hi) & mask))
                lo = hi
            self.assertEqual(words(m, DST, 6), want, f"n {n}")
            self.assertEqual(m.r[5], lo, f"n {n}")

    def test_zero_count(self):
        d = self.rnd(4)
        m = run(0x04FD, {1: DST, 2: -1, 3: 0}, {DST: pack(d)})
        self.assertEqual(words(m, DST, 4), d)
        self.assertEqual(m.r[1], DST)
