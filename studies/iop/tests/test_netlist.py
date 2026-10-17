"""The card's netlist (card.py) at chip level, against the model (hw.py):
the same microaddress and AC at every E2, and no timing violations."""

import unittest

from heron.studies.iop import hw


class Netlist(unittest.TestCase):
    def test_bus(self):
        """A microcode program of its own (ucode/hwtest.uc): the system
        bus, the shared RAM, the swap register, the I/O bus."""
        out, diff, n, _, want, got = hw.check_ucode("hwtest.uc")
        self.assertIsNone(diff)
        self.assertGreater(n, 60)
        self.assertEqual(out["violation_total"], 0)
        self.assertEqual(got["regs"][8:16], want["regs"][8:16])
        self.assertEqual(got["ram"], want["ram"])

    def test_slave(self):
        """The slave side, against a second master on the bench: the
        shared RAM written and read while the core uses T, a doorbell."""
        out, reads, regs = hw.check_slave()
        self.assertEqual(out["violation_total"], 0)
        self.assertEqual(reads, [0x3333, 0x1111, 0xAB34] + [0x100 + i for i in range(8)])
        self.assertEqual(regs[:3], [8, 0x1111, 0x2222])

    def test_cold_start(self):
        """The firmware from power-up to just before the timer's first
        tick, which the two take a few clocks apart: the SRAM's test, the
        dictionary out of the flash, the Forth's cold start."""
        out, diff, n = hw.check(21.0)
        self.assertIsNone(diff)
        self.assertGreater(n, 150_000)
        self.assertEqual(out["violation_total"], 0)


if __name__ == "__main__":
    unittest.main()
