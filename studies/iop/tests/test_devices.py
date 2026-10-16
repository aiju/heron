"""The I/O cards behind the rings (RFC 0027, 7.2): the CF card's sectors
and the serial lines' line discipline, as a client sees them."""

import unittest

from heron.studies.iop import build, layout as L
from heron.studies.iop.run import Session
from heron.studies.iop.tests.test_rings import SR, kernel

SECTORS = 64


def sector(n):
    """The test image's sector n: its number, then a pattern."""
    return bytes((n + i) & 0xFF if i else n for i in range(512))


class Disk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        image = b"".join(sector(n) for n in range(SECTORS))
        cls.s = Session(build.Build(build.DEFAULT_PROGRAM), disk=image)
        cls.s.boot()
        cls.k = kernel(cls.s)

    def test_read(self):
        got = self.k.do((L.OP_READ, 0x8000, 5, 3 * 512, 1), ms=5)
        self.assertEqual(got, [(1, L.ST_OK, 3 * 512)])
        self.assertEqual(self.s.s.cpu_mem(0x8000, 3 * 512), sector(5) + sector(6) + sector(7))

    def test_read_into_the_shared_ram(self):
        got = self.k.do((L.OP_READ, SR + 0x20000, 9, 2 * 512, 2), ms=5)
        self.assertEqual(got, [(2, L.ST_OK, 2 * 512)])
        halves = self.s.s.shared(0x20000 // 2, 512)
        self.assertEqual(b"".join(h.to_bytes(2, "little") for h in halves), sector(9) + sector(10))

    def test_write(self):
        data = bytes(range(256)) * 4
        self.s.s.cpu_mem_write(0xA000, data)
        got = self.k.do((L.OP_WRITE, 0xA000, 40, 1024, 3), ms=5)
        self.assertEqual(got, [(3, L.ST_OK, 1024)])
        self.assertEqual(self.s.s.disk()[40 * 512:42 * 512], data)

    def test_errors(self):
        got = self.k.do((L.OP_READ, 0x8000, 0, 100, 4), (L.OP_READ, 0x8000, 0x7000, 512, 5), ms=5)
        self.assertEqual(got, [(4, L.ST_ALIGN, 0), (5, L.ST_DEVICE, 0)])


class Lines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = Session(build.Build(build.DEFAULT_PROGRAM), serial=True)
        cls.s.boot()
        cls.k = kernel(cls.s)

    def test_send(self):
        self.s.s.cpu_mem_write(0xB000, b"Hello, line 1\r\n")
        got = self.k.do((L.OP_SEND, 0xB000, 1, 15, 1), ms=5)
        self.assertEqual(got, [(1, L.ST_OK, 15)])
        self.s.run_ms(2)
        self.assertEqual(self.s.s.serial_take(1), b"Hello, line 1\r\n")

    def test_a_line(self):
        """Cooked: echoed, erased, and delivered when Return comes, to a
        receive that was waiting."""
        self.s.s.serial_take(0)
        self.assertEqual(self.k.do((L.OP_RECV, 0xC000, 0, 64, 2)), [])
        self.s.s.serial_send(0, b"ls -x\x08l\r")
        self.s.run_ms(3)
        self.assertEqual(self.k.completions(), [(2, L.ST_OK, 6)])
        self.assertEqual(self.s.s.cpu_mem(0xC000, 6), b"ls -l\n")
        self.assertEqual(self.s.s.serial_take(0), b"ls -x\x08 \x08l\r\n")

    def test_raw(self):
        """Raw, without echo: what has come, to a receive made after it,
        into the shared RAM."""
        self.assertEqual(self.k.do((L.OP_MODE, 0, 1, 0, 3, 3)), [(3, L.ST_OK, 0)])
        self.s.s.serial_take(1)
        self.s.s.serial_send(1, b"\x1b[A")
        self.s.run_ms(2)
        got = self.k.do((L.OP_RECV, SR + 0x30000, 1, 64, 4))
        self.assertEqual(got, [(4, L.ST_OK, 3)])
        h = self.s.s.shared(0x30000 // 2, 2)
        self.assertEqual(b"".join(x.to_bytes(2, "little") for x in h)[:3], b"\x1b[A")
        self.assertEqual(self.s.s.serial_take(1), b"")


class Status(unittest.TestCase):
    def test_ready_and_disk_size(self):
        """The cold start says it's done in the status block, with the CF
        card's size."""
        s = Session(build.Build(build.DEFAULT_PROGRAM), disk=bytes(512 * SECTORS))
        s.boot()
        st = s.s.shared(0, 4)
        self.assertEqual(st[L.S_READY // 2], L.STATUS_READY)
        self.assertEqual(st[L.S_SECTORS // 2] | st[L.S_SECTORS // 2 + 1] << 16, SECTORS)
