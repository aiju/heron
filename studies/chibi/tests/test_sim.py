"""The whole-machine simulator (sim/, sim.py): the engine against draft 2's
simulator and the register-transfer model, the board's device tests, and
the test card (programs/testcard.s)."""

import os
import unittest

import heron.studies.v2_isa  # noqa: F401  (registers the ISA)
from heron.studies.chibi import check, sim, ucode2 as uc
from heron.studies.v2_isa import testing

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROGRAMS = os.path.join(HERE, "programs")


def suite_path(name):
    return next(p for p in testing.program_paths([name]))


class Store(unittest.TestCase):
    def test_vocabulary(self):
        """sim.py names every flag operation and condition ucode2 has."""
        self.assertEqual(sim.FLOPS[:len(uc.FLOPS)], uc.FLOPS)
        self.assertTrue(set(uc.FL_HIGH.values()) <= set(sim.FLOPS))
        self.assertEqual(sim.CONDS, uc.CONDS)
        self.assertEqual(len(uc.IMMS), 32)

    def test_image(self):
        img = sim.default_image()
        self.assertEqual(img[:4], b"CHST")
        self.assertEqual(len(img), 20 + 32 * 6 + 32 * 256 * 6 + uc.CS_WORDS * 32)


class Suite(unittest.TestCase):
    def test_programs(self):
        """Output, registers, flags and RAM as draft 2's simulator has them."""
        for name in ("hello", "strings", "rpn", "fib", "interrupts"):
            _, _, diffs = sim.check_program(suite_path(name))
            self.assertEqual(diffs, [], name)

    def test_against_the_model(self):
        """Every decode at the same cycle, the cycles, the ticks and the
        register file as rtl2.py's."""
        for name in ("hello", "strings"):
            _, _, diffs = sim.check_program(suite_path(name), model=True)
            self.assertEqual(diffs, [], name)

    def test_skipping_idle(self):
        """Skipping HALT's waits changes nothing but the host's time."""
        img = check.assemble(suite_path("interrupts"))
        runs = []
        for skip in (True, False):
            m = sim.Chibi(stretch=False)
            m.load_image(img)
            m.skip_idle = skip
            m.run_until_halt()
            runs.append((m.instructions, m.cycles, m.ticks, m.console_out(), m.regs()))
            self.assertEqual(m.stats()["skipped"] > 0, skip)
        self.assertEqual(runs[0], runs[1])

    def test_stretch(self):
        """Phase F's stretches only come with a task or the display: the
        suite's programs have neither."""
        img = check.assemble(suite_path("fib"))
        ticks = []
        for stretch in (True, False):
            m = sim.Chibi(stretch=stretch)
            m.load_image(img)
            m.run_until_halt()
            ticks.append(m.ticks)
        self.assertEqual(ticks[0], ticks[1])


class Devices(unittest.TestCase):
    """The board's device tests (programs/), with the model's outcomes."""

    def test_device_tests(self):
        for name in sim.DEVICE_TESTS:
            _, diffs = sim.run_device_test(name)
            self.assertEqual(diffs, [], name)

    def test_flash_boot(self):
        """The reset routine copies a program from the boot flash."""
        m = sim.Chibi()
        m.boot_from_flash(check.assemble(suite_path("hello")))
        m.run_until_halt()
        self.assertEqual(m.console_out(), b"Hello, world!\n")


class TestCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        m = cls.m = sim.Chibi(fixture=False)
        m.boot_from_flash(check.assemble(os.path.join(PROGRAMS, "testcard.s")))
        m.render(True)
        m.uart_send(0, b"hi\r")
        m.stop_on_halt = False
        m.run_for(0.5)
        for k in sim.keystrokes("a"):
            m.key(*k)
            m.run_for(0.02)
        m.run_for(1.1 - m.seconds)

    def test_uart(self):
        self.assertEqual(self.m.uart_take(0), b"\r\nChibi Heron test card\r\nhi\r\n1C F0 1C ")

    def test_screen(self):
        rgb = self.m.screen()

        def px(x, y):
            i = 3 * (640 * y + x)
            return tuple(rgb[i:i + 3])
        e = lambda v: (v << 2) | (v >> 4)  # noqa: E731
        vga = [sim_vga[3 * k:3 * k + 3] for k in range(16)]
        for k in range(16):
            self.assertEqual(px(40 * k + 20, 250), tuple(e(v) for v in vga[k]), k)
        self.assertEqual(px(1, 100), (255, 255, 255))          # the border
        self.assertEqual(px(100, 100), tuple(e(v) for v in vga[1]))     # the ground
        self.assertEqual(px(190, 80), (255, 255, 255))          # C's left edge
        self.assertEqual(px(353, 413), (255, 255, 255))         # the 1 of 0001
        self.assertEqual(px(349, 413), tuple(e(v) for v in vga[1]))     # beside it

    def test_frames(self):
        """A frame ends with line 479: 15.25 ms from power-on, then every
        16.68 ms."""
        self.assertEqual(self.m.stats()["frame_count"], 66)

    def test_beep(self):
        """1600 samples of a 1 kHz square at 8 kHz, then the middle."""
        s = self.m.pcm_log()
        self.assertEqual(s[:8], bytes([0xC0] * 4 + [0x40] * 4))
        self.assertEqual(s[:1600], s[:8] * 200)
        self.assertTrue(set(s[1600:]) <= {0x80})


sim_vga = [0, 0, 0, 0, 0, 42, 0, 42, 0, 0, 42, 42, 42, 0, 0, 42, 0, 42, 42, 21, 0, 42, 42, 42,
           21, 21, 21, 21, 21, 63, 21, 63, 21, 21, 63, 63, 63, 21, 21, 63, 21, 63, 63, 63, 21,
           63, 63, 63]


if __name__ == "__main__":
    unittest.main()
