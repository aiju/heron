"""The system: the IOP boots the draft 2 CPU, which then reaches the IOP's
console through the I/O bus's window, its shared RAM and its doorbells."""

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
        self.assertIn("1234 ok", self.s.command("$100 0 sr@ h.4"))
        self.assertIn(" 1  ok", self.s.command("bells ?"))

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
