"""The system: the IOP boots the draft 2 CPU, which then reaches the IOP's
console through the I/O bus's window, its shared RAM and its doorbells."""

import os
import unittest

from heron.studies.iop import build
from heron.studies.iop.run import Session


class Boot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = Session(build.Build(build.DEFAULT_PROGRAM))
        cls.s.boot()
        cls.out = cls.s.command("boot-cpu cpu-wait", timeout_ms=5000)

    def test_hello_through_the_window(self):
        self.assertEqual(self.out, "boot-cpu cpu-wait Hello from the CPU\r\n ok\r\n")

    def test_halted(self):
        c = self.s.s.cpu()
        self.assertTrue(c["run"] and c["halted"])
        self.assertIn("7  ok", self.s.command("cpu? ."))

    def test_shared_ram_and_doorbell(self):
        self.assertIn("1234 ok", self.s.command("$200 0 sr@ h.4"))
        self.assertIn(" 32  ok", self.s.command("bells ?"))

    def test_examine_and_deposit(self):
        """The monitor's e and d on the CPU card's RAM, through its slave port."""
        self.s.command("$BEEF $1000. d")
        self.assertIn("00001000: BEEF", self.s.command("$1000. e"))
        self.assertEqual(self.s.s.cpu_mem(0x1000, 2), b"\xef\xbe")


class ControlStore(unittest.TestCase):
    def test_records_into_the_window(self):
        """Image 0's records go into the CPU card's control store lanes,
        in slices that cross flash pages and records."""
        runs = [(build.CS_BASE + 2 * 0x100, list(range(1, 300))),
                (build.CS_BASE + build.CS_LANE * 3, [0xAAAA, 0x5555]),
                (build.CS_BASE + build.CS_LANE * build.DEC_LANE + 2 * 0xFFF0, list(range(16)))]
        b = build.Build(build.DEFAULT_PROGRAM)
        b.flash = build.flash_image(b.meta, [build.records(runs), build.records(build.ram_runs(b.program))])
        s = Session(b)
        s.boot()
        self.assertIn("Hello from the CPU", s.command("boot-cpu cpu-wait", timeout_ms=5000))
        self.assertEqual(s.s.lane(0)[0x100:0x100 + 299], list(range(1, 300)))
        self.assertEqual(s.s.lane(3)[:3], [0xAAAA, 0x5555, 0])
        self.assertEqual(s.s.lane(build.DEC_LANE)[0xFFF0:], list(range(16)))
        self.assertEqual(s.s.cpu()["lane_errors"], 0)


class Blocks(unittest.TestCase):
    """The block words, as native jobs, through the CPU card's slave port,
    exactly to their ends and across 64 KB on the bus."""

    @classmethod
    def setUpClass(cls):
        cls.s = Session(build.Build(build.DEFAULT_PROGRAM))
        cls.s.boot()

    def mem(self, pa, n):
        return [int.from_bytes(self.s.s.cpu_mem(pa + 2 * i, 2), "little") for i in range(n)]

    def run_(self, line):
        out = self.s.command(line, timeout_ms=5000)
        self.assertTrue(out.endswith(" ok\r\n"), out)

    def test_fill(self):
        self.run_("$1111 $2000. 300 bus-fill $5555 $2002. 101 bus-fill")
        self.assertEqual(self.mem(0x2000, 104), [0x1111] + [0x5555] * 101 + [0x1111] * 2)
        self.run_("$1234 $FFFC. 3 bus-fill")
        self.assertEqual(self.mem(0xFFFC, 4), [0x1234] * 3 + [0])

    def test_move(self):
        self.run_("$7777 $3000. 40 bus-fill $1111 $3000. d $2222 $3048. d")
        self.run_("$3000. $FFF0. 37 bus-move")
        self.assertEqual(self.mem(0xFFF0, 38), [0x1111] + [0x7777] * 35 + [0x2222, 0])

    def test_shared_ram(self):
        self.run_("$ABCD $4000. d $1234 $400C. d")
        after = self.s.s.shared(12, 1)
        self.run_("$4000. $A. 7 bus>sr")
        self.assertEqual(self.s.s.shared(5, 8), self.mem(0x4000, 7) + after)
        self.run_("$A. $5000. 7 sr>bus")
        self.assertEqual(self.mem(0x5000, 8), self.mem(0x4000, 7) + [0])

    def test_bytes(self):
        self.run_("$1122 $6000. d $33 $6001. busc! $44 $6000. busc!")
        self.assertEqual(self.s.s.cpu_mem(0x6000, 2), b"\x44\x33")
        self.assertIn("51 68  ok", self.s.command("$6001. busc@ . $6000. busc@ ."))


class Interrupt(unittest.TestCase):
    def test_cpu_int(self):
        """The IOP raises a level in the CPU card's request register; the
        CPU, waiting in HALT, takes it (sw/irq.s)."""
        s = Session(build.Build(os.path.join(build.HERE, "sw", "irq.s")))
        s.boot()
        s.command("boot-cpu")
        s.run_ms(2)
        self.assertFalse(s.s.cpu()["halted"])
        self.assertEqual(s.command("3 cpu-int cpu-wait", 3000),
                         "3 cpu-int cpu-wait Level 3 from the IOP\r\n ok\r\n")
        self.assertEqual(s.s.cpu()["irq"], 0)
