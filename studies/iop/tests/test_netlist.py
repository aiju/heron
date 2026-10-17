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

    def test_window(self):
        """The window onto the I/O bus, against a second master on the
        bench, while ucode/hwwin.uc uses the I/O bus itself: posted writes
        one after another, reads, the shared RAM between; the program's
        own reads as the model's."""
        out, reads, want, regs, model_regs = hw.check_window()
        self.assertEqual(out["violation_total"], 0)
        self.assertEqual(reads, want)
        self.assertEqual(regs, model_regs)

    def test_watchdog(self):
        """The watchdog, its times shortened to 20 us and 2 us:
        ucode/hwwdog.uc kicks it 4 times and stops; COLD starts it again,
        a wait and a COLD later each time."""
        out, n, starts = hw.check_watchdog()
        self.assertEqual(out["violation_total"], 0)
        self.assertGreater(n, 10)
        gaps = {b - a for a, b in zip(starts[1:], starts[2:])}
        self.assertEqual(len(gaps), 1)
        wait = (20_000 + 2_000) // 60           # bus clocks: the wait and COLD
        self.assertTrue(wait < gaps.pop() < wait + 100)

    def test_stuck(self):
        """The stuck-transfer counter: a read from a slave that holds
        WAIT ends after 256 data clocks with RESET, STUCK and OWN set; a
        write to the event port clears them; the bus works after it."""
        out, regs, wait = hw.check_stuck()
        self.assertEqual(out["violation_total"], 0)
        self.assertEqual(regs, [0x6000, 0, 0x1234])
        self.assertTrue(256 < wait < 300)

    def test_cold_start(self):
        """The firmware from power-up to just before the timer's first
        tick, which the two take a few clocks apart: the SRAM's test, the
        dictionary out of the flash, the Forth's cold start."""
        out, diff, n = hw.check(21.0)
        self.assertIsNone(diff)
        self.assertGreater(n, 150_000)
        self.assertEqual(out["violation_total"], 0)


class FastCorner(unittest.TestCase):
    def test_cold_start(self):
        """The same at the parts' minimum delays, where hold times fail
        if they do: the model's microaddresses, at the same clocks."""
        out, diff, n = hw.check(21.0, corner="min")
        self.assertIsNone(diff)
        self.assertGreater(n, 150_000)
        self.assertEqual(out["violation_total"], 0)


if __name__ == "__main__":
    unittest.main()
