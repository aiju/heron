"""The guests on draft 2's register-transfer model, with nothing from
outside the repository: small programs (tests/asm, assembled once) in
lockstep with the reference interpreters, draft 1b's own suite, the model
with design changes against draft 2's own, and the mixed machine.

The suites compiled with clang and cc65 are `heron v2_guests test ISA`."""

import unittest

from heron.studies.v2_hw.rtl import RTL
from heron.studies.v2_guests import cli, guest as gm, mixed, v1b, v1b_progs
from heron.studies.v2_guests.rtlx import RTLX
from heron.studies.v2_guests.tests import asm_programs


def m6502_image(code):
    img = bytearray(0x10000)
    img[0x400:0x400 + len(code)] = code
    img[0xFFFC:0xFFFE] = (0x0400).to_bytes(2, "little")
    return bytes(img)


class Lockstep(unittest.TestCase):
    """Every instruction's result against the reference interpreter."""

    def check(self, isa, image, out=b"ok\n"):
        res = cli.run_image(isa, "test", image, b"", out, lockstep=True, max_cycles=100_000)
        self.assertIsNone(res["error"])
        self.assertEqual(res["out"], out)
        self.assertGreater(res["instructions"], 20)

    def test_rv32(self):
        self.check("rv32", asm_programs.load("rv32"))

    def test_thumb(self):
        self.check("thumb", asm_programs.load("thumb"))

    def test_m6502(self):
        self.check("m6502", m6502_image(asm_programs.load("m6502")))

    def test_v1b_suite(self):
        """Draft 1b's binaries as they are: some of its suite, in lockstep
        with draft 1's simulator."""
        for name in ("hello", "bignum", "queens", "strings"):
            with self.subTest(name=name):
                res = cli.run("v1b", name, lockstep=True)
                self.assertTrue(res["ok"], res["error"])


class Microcode(unittest.TestCase):
    def test_v1b_fits(self):
        """1b fits the 8K words the unmodified sequencer reaches (the
        forced entries are where draft 2 has them)."""
        mc = v1b.built()
        self.assertLessEqual(max(n.addr for n in mc.nodes if n.fixed is None), 0x1FFF)

    def test_rtlx_is_rtl(self):
        """With no design change in use, the variant model is draft 2's,
        cycle for cycle."""
        mc = v1b.built()
        for name in ("hello", "fib"):
            image, inp, exp = v1b_progs.guest_programs("v1b")[name]()
            runs = [gm.Run(mc, image, inp, rtl=rtl).run() for rtl in (RTL, RTLX)]
            a, b = (r.m for r in runs)
            self.assertEqual((a.cycles, a.ticks, a.instructions, bytes(a.out)),
                             (b.cycles, b.ticks, b.instructions, bytes(b.out)))
            self.assertEqual(bytes(a.out), exp)


class Mixed(unittest.TestCase):
    def test_processes(self):
        """The draft 2 kernel runs a draft 2 process and a Thumb one in
        turn; the Thumb one's first PUSH faults on its stack page, which
        the kernel maps, and runs again."""
        thumb = mixed.Process("push", "thumb", asm_programs.load("thumb_user"), 0,
                              expected=b"ok\n")
        res = mixed.run([mixed.program("sieve", "v2"), thumb], period=5000)
        self.assertTrue(res["ok"], res)
        self.assertIn(b"process 1 (Thumb): exited, time slices 1, pages mapped on demand 1",
                      res["kernel"])
        self.assertIn(b"process 0 (draft 2): exited", res["kernel"])

    def test_store(self):
        """Two decode pages; the microcode needs more than 8K words (D3),
        and every routine starts in the first 8K, which decode entries
        reach."""
        mc = mixed.built()
        self.assertEqual(len(mc.pages), 2)
        self.assertGreater(max(n.addr for n in mc.nodes if n.fixed is None), 0x1FFF)
        self.assertTrue(all(n.addr < 0x2000 for n in mc.entry.values()))


if __name__ == "__main__":
    unittest.main()
