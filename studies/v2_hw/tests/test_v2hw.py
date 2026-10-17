"""The draft 2 CPU: the microcode builds and keeps its rules, and the
register-transfer model runs programs as the instruction-level simulator
does, boots from the I/O processor, and passes the system tests."""

import os
import unittest

import heron.studies.v2_isa  # noqa: F401
from heron.infra import asm, isas
from heron.infra.programs import metadata
from heron.studies.v2_hw import check, ucode as uc

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def program(name):
    return check.program_paths([name])[0]


class Microcode(unittest.TestCase):
    def test_builds(self):
        mc = uc.built()
        self.assertLess(len(mc.nodes), 1 << uc.Y_BITS)
        self.assertLessEqual(uc.CONTROL_BITS, uc.WORD_BITS)
        self.assertEqual(len(mc.decode_table()), 0x10000)
        self.assertEqual(len(mc.lengths), 4)

    def test_constants_in_every_bank(self):
        # both copies of the register file share the bank address, so the
        # reset routine leaves each bank's G half with the constants (but
        # for the special registers, vbr and the vectors with it: bank 0's)
        from heron.studies.v2_hw import rtl, system
        m = rtl.RTL(system.System())
        check.boot(m)
        for bank in range(256):
            for k, v in uc.CONSTS.items():
                if k not in uc.SPECIAL:
                    self.assertEqual(m.rf[rtl.GLB | bank << 5 | k - uc.G], v, (bank, k))
        self.assertEqual(m.BANK, 0)


class Programs(unittest.TestCase):
    def check(self, name):
        n, diffs, info = check.check_program(program(name))
        self.assertEqual(diffs, [], name)

    def test_suite_programs(self):
        for name in ("hello", "strings", "bst", "sort"):
            self.check(name)

    def test_systest(self):
        self.check("systest")

    def test_isanotes(self):
        self.check("isanotes")

    def test_boot(self):
        img = asm.assemble_file(isas.get("v2"), program("hello"))
        m, iop = check.run_booted(img)
        self.assertEqual(check.compare(check.run_isa(img), m), [])
        self.assertGreater(iop.halfwords, 0x10000)

    def test_bus(self):
        img = asm.assemble_file(isas.get("v2"), program("hello"))
        m = check.run_rtl(img, code_base=check.REGION)
        self.assertEqual(m.out, b"Hello, world!\n")

    def test_icache(self):
        # strings over the bus with a small cache: the same output and
        # registers, fewer bus fetches, less time
        path = program("strings")
        img = asm.assemble_file(isas.get("v2"), path)
        inp = metadata(path)["input"]
        sim = check.run_isa(img, inp)
        plain = check.run_rtl(img, inp, code_base=check.REGION)
        cached = check.run_rtl(img, inp, code_base=check.REGION, icache=64)
        self.assertEqual(check.compare(sim, cached, code_base=check.REGION), [])
        self.assertGreater(cached.sys.icache_hits, 0)
        self.assertLess(cached.sys.bus_fetches, plain.sys.bus_fetches)
        self.assertLess(cached.ticks, plain.ticks)

    def test_icache_store(self):
        # the CPU's own store into a cached word invalidates it
        s = check.System(icache=16)
        s.add(check.REGION, check.MemoryCard())
        pa = check.REGION + 0x40

        class M:
            ticks = cycles = 0
        s.poke(pa, 0x11)
        w, _ = s.fetch(pa, M)
        self.assertEqual(w & 0xFF, 0x11)
        self.assertTrue(s.fetch_is_fast(pa))
        s.write(pa, 1, pa, 0x22, M)
        self.assertFalse(s.fetch_is_fast(pa))
        w, _ = s.fetch(pa, M)
        self.assertEqual(w & 0xFF, 0x22)
