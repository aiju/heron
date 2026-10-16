"""Events to the CPUs (RFC 0040, 4-5): an INT line routed through the
kernel's ring to a CPU, its event in the CPU's ring of events in its own
RAM, masked until the driver says it's served; slow levels held back and
batched; lazy events that raise no level unless the CPU is about to halt
or their deadline passes; fast ones through the CPU card's message
register. A GPIO card's INT is the test's to raise."""

import unittest

from heron.studies.iop import build, layout as L
from heron.studies.iop.run import Session
from heron.studies.iop.tests.test_rings import WAKE, Events as Ring, events, kernel

A, B = 3, 4                  # the GPIO cards' slots: INT 3 and 4


class Events(unittest.TestCase):
    def setUp(self):
        self.s = Session(build.Build(build.DEFAULT_PROGRAM), gpio=[A, B])
        self.s.boot()
        self.k = kernel(self.s)
        events(self.s, self.k)
        self.ring = Ring(self.s)

    def events(self):
        return self.ring.take()

    def route(self, src, level, hold=0, cls=L.SLOW, msg=0, cpu=0):
        got = self.k.do((L.OP_ROUTE, 0, src | (level | cpu << 8) << 16, hold, 1, cls | msg << 8), ms=3)
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
        """Two sources at level 4, held for up to 100 ticks (1 ms): one
        interrupt, both events."""
        self.route(A, 4, hold=100)
        self.route(B, 4, hold=100)
        start = self.s.ms
        self.s.s.gpio_set(A, 1)
        self.s.run_ms(0.4)
        self.s.s.gpio_set(B, 1)
        self.s.run_ms(0.4)
        self.assertEqual(self.irq(), 0)
        self.assertEqual(self.events(), [A, B])
        while not self.irq() and self.s.ms - start < 3:
            self.s.run_ms(0.01)
        self.assertEqual(self.irq(), 1 << 3)
        self.assertAlmostEqual(self.s.ms - start, 1.0, delta=0.1)

    def test_lazy(self):
        """Lazy: the event, and no level; with the wake-me word set, the
        level at once."""
        self.route(A, 4, cls=L.LAZY)
        self.s.s.gpio_set(A, 1)
        self.s.run_ms(0.5)
        self.assertEqual((self.irq(), self.events()), (0, [A]))
        self.s.s.shared_write(WAKE // 2, [1])
        self.k.do((L.OP_UNMASK, 0, A, 0, 2), ms=1)
        self.assertEqual((self.irq(), self.events()), (1 << 3, [A]))

    def test_lazy_deadline(self):
        """A lazy event with a deadline of 50 ticks: its level after 0.5 ms."""
        self.route(B, 4, hold=50, cls=L.LAZY)
        start = self.s.ms
        self.s.s.gpio_set(B, 1)
        self.s.run_ms(0.2)
        self.assertEqual((self.irq(), self.events()), (0, [B]))
        while not self.irq() and self.s.ms - start < 3:
            self.s.run_ms(0.01)
        self.assertEqual(self.irq(), 1 << 3)
        self.assertAlmostEqual(self.s.ms - start, 0.5, delta=0.1)

    def test_fast(self):
        """Fast: {source, the event} in the message register, no ring
        entry; while it's full, the next goes slow."""
        self.route(B, 4, cls=L.FAST, msg=0x5A)
        self.route(A, 4, cls=L.FAST, msg=0x5B)
        self.s.s.gpio_set(B, 1)
        self.s.run_ms(0.05)
        c = self.s.s.cpu()
        self.assertEqual((c["msg"], c["msg_value"], c["irq"]), ("full", 0x5A00_0000 | B, 0))
        self.assertEqual(self.events(), [])
        self.s.s.gpio_set(A, 1)
        self.s.run_ms(0.05)
        self.assertEqual((self.s.s.cpu()["msg_value"], self.irq(), self.events()), (0x5A00_0000 | B, 1 << 3, [A]))
        self.s.s.msg_release()
        self.assertEqual(self.s.s.cpu()["msg"], "free")

    def test_nobody(self):
        """Level 0 routes a source to nobody: masked, and nothing posted."""
        self.route(A, 0)
        self.s.s.gpio_set(A, 1)
        self.s.run_ms(0.2)
        self.assertEqual((self.irq(), self.events()), (0, []))
