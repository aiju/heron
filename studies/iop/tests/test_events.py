"""Events to the CPUs (RFC 0027, 7.3): an INT line routed through the
kernel's ring to a CPU's level, its event in the CPU's ring of events,
masked until the driver says it's served; slow levels held back and
batched; a fast level's mailbox. A GPIO card's INT is the test's to
raise."""

import unittest

from heron.studies.iop import build, layout as L
from heron.studies.iop.run import Session
from heron.studies.iop.tests.test_rings import kernel

A, B = 3, 4                  # the GPIO cards' slots: INT 3 and 4


class Events(unittest.TestCase):
    def setUp(self):
        self.s = Session(build.Build(build.DEFAULT_PROGRAM), gpio=[A, B])
        self.s.boot()
        self.k = kernel(self.s)
        self.seen = self.head()

    def head(self):
        return self.s.s.shared((L.K_EVBLK + L.B_HEAD) // 2, 1)[0]

    def events(self):
        """The events posted since the last call, as the CPU would drain them."""
        out = []
        head = self.head()
        while self.seen != head:
            out.append(self.s.s.shared((L.K_EVRING + self.seen) // 2, 1)[0])
            self.seen = (self.seen + 2) % (2 * L.K_EVS)
        self.s.s.shared_write((L.K_EVBLK + L.B_TAIL) // 2, [self.seen])
        return out

    def route(self, src, level, hold=0, cpu=0):
        got = self.k.do((L.OP_ROUTE, 0, src | (level | cpu << 8) << 16, hold, 1), ms=3)
        self.assertEqual(got, [(1, L.ST_OK, 0)])

    def irq(self):
        return self.s.s.cpu()["irq"]

    def test_routed_and_masked(self):
        self.route(A, 2)
        self.s.s.gpio_set(A, 1)
        self.s.run_ms(0.05)
        self.assertEqual(self.irq(), 1 << 1)
        self.assertEqual(self.events(), [A])
        # masked until served: nothing more while it stays up
        self.s.s.irq_clear(0xFF)
        self.s.run_ms(0.5)
        self.assertEqual((self.irq(), self.events()), (0, []))
        # served: the driver's OP_UNMASK, and it's still up
        self.assertEqual(self.k.do((L.OP_UNMASK, 0, A, 0, 2), ms=1), [(2, L.ST_OK, 0)])
        self.assertEqual((self.irq(), self.events()), (1 << 1, [A]))
        # down, served, and quiet
        self.s.s.gpio_set(A, 0)
        self.s.s.irq_clear(0xFF)
        self.k.do((L.OP_UNMASK, 0, A, 0, 3), ms=1)
        self.assertEqual((self.irq(), self.events()), (0, []))

    def test_slow_held_and_batched(self):
        """Two sources at level 5, held for up to 100 ticks (1 ms): one
        interrupt, both events."""
        self.route(A, 5, hold=100)
        self.route(B, 5, hold=100)
        start = self.s.ms
        self.s.s.gpio_set(A, 1)
        self.s.run_ms(0.4)
        self.s.s.gpio_set(B, 1)
        self.s.run_ms(0.4)
        self.assertEqual(self.irq(), 0)
        self.assertEqual(self.events(), [A, B])
        while not self.irq() and self.s.ms - start < 3:
            self.s.run_ms(0.01)
        self.assertEqual(self.irq(), 1 << 4)
        self.assertAlmostEqual(self.s.ms - start, 1.0, delta=0.1)

    def test_fast_mailbox(self):
        """Level 7 is fast: never held, and its mailbox says why."""
        self.route(B, 7, hold=100)
        self.s.s.gpio_set(B, 1)
        self.s.run_ms(0.05)
        self.assertEqual(self.irq(), 1 << 6)
        self.assertEqual(self.s.s.shared((L.K_EVBLK + L.B_MAIL + 2) // 2, 1)[0], B)

    def test_nobody(self):
        """Level 0 routes a source to nobody: masked, and nothing posted."""
        self.route(A, 0)
        self.s.s.gpio_set(A, 1)
        self.s.run_ms(0.2)
        self.assertEqual((self.irq(), self.events()), (0, []))
