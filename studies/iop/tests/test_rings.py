"""The rings (RFC 0027, 7): a client's requests in the shared RAM, its
doorbell, the IOP's completions, the windows, the server's requests and
the events and interrupts it posts. The test plays the client, writing
the shared RAM and ringing the doorbells as a CPU would."""

import unittest

from heron.studies.iop import build, layout as L
from heron.studies.iop.run import Session

SR = 0x4000_0000            # the shared RAM, physically


class Client:
    """A client's rings in the shared RAM, as its driver keeps them."""

    def __init__(self, s, n, req, nreq, cmp, ncmp, idx):
        self.s, self.n = s, n
        self.req, self.nreq, self.cmp, self.ncmp, self.idx = req, nreq, cmp, ncmp, idx
        self.head = 0           # requests written
        self.tail = 0           # completions read

    def hw(self, byte, n=1):
        return self.s.s.shared(byte // 2, n)

    def put(self, op, a=0, b=0, n=0, tag=0, flags=0):
        """A request into the ring (not yet rung)."""
        words = [op, flags, a & 0xFFFF, a >> 16, b & 0xFFFF, b >> 16, n, tag]
        self.s.s.shared_write((self.req + 16 * (self.head % self.nreq)) // 2, words)
        self.head += 1
        self.s.s.shared_write((self.idx + L.I_REQHEAD) // 2, [16 * (self.head % self.nreq)])

    def ring(self):
        self.s.s.ring(self.n)

    def completions(self):
        """The completions written since the last call: [(tag, status, result)]."""
        head = self.hw(self.idx + L.I_CMPHEAD)[0] // 8
        out = []
        while self.tail % self.ncmp != head:
            t, st, lo, hi = self.hw(self.cmp + 8 * (self.tail % self.ncmp), 4)
            out.append((t, st, lo | hi << 16))
            self.tail += 1
        self.s.s.shared_write((self.idx + L.I_CMPTAIL) // 2, [8 * (self.tail % self.ncmp)])
        return out

    def do(self, *requests, ms=2):
        """Requests, rung, and their completions after ms of simulated time."""
        for r in requests:
            self.put(*r)
        self.ring()
        self.s.run_ms(ms)
        return self.completions()


def kernel(s):
    return Client(s, 0, L.K_REQ, L.K_REQS, L.K_CMP, L.K_CMPS, L.K_IDX)


class Rings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = Session(build.Build(build.DEFAULT_PROGRAM))
        cls.s.boot()
        cls.k = kernel(cls.s)

    def mem(self, pa, n):
        return [int.from_bytes(self.s.s.cpu_mem(pa + 2 * i, 2), "little") for i in range(n)]

    def poke(self, pa, halves):
        self.s.s.cpu_mem_write(pa, b"".join(h.to_bytes(2, "little") for h in halves))

    def test_copy_fill_zero(self):
        self.poke(0x1000, list(range(100, 140)))
        got = self.k.do((L.OP_COPY, 0x2000, 0x1000, 80, 1),
                        (L.OP_FILL, 0x3000, 0xBEEF, 6, 2),
                        (L.OP_ZERO, 0x1004, 0, 4, 3))
        self.assertEqual(got, [(1, L.ST_OK, 80), (2, L.ST_OK, 6), (3, L.ST_OK, 4)])
        self.assertEqual(self.mem(0x2000, 41), list(range(100, 140)) + [0])
        self.assertEqual(self.mem(0x3000, 4), [0xBEEF] * 3 + [0])
        self.assertEqual(self.mem(0x1000, 5), [100, 101, 0, 0, 104])
        self.assertEqual(self.k.hw(L.K_IDX + L.I_REQTAIL)[0], 16 * (self.k.head % L.K_REQS))

    def test_shared_ram(self):
        """Copies between the CPU's RAM and the shared RAM, within it, and
        a fill there: region 4 is the IOP's own."""
        self.poke(0x5000, [7, 8, 9, 10])
        got = self.k.do((L.OP_COPY, SR + 0x8000, 0x5000, 8, 1),
                        (L.OP_COPY, SR + 0x8010, SR + 0x8000, 8, 2),
                        (L.OP_COPY, 0x5100, SR + 0x8010, 8, 3),
                        (L.OP_FILL, SR + 0x9000, 0x1234, 4, 4))
        self.assertEqual([st for _, st, _ in got], [L.ST_OK] * 4)
        self.assertEqual(self.k.hw(0x8000, 4), [7, 8, 9, 10])
        self.assertEqual(self.k.hw(0x8010, 4), [7, 8, 9, 10])
        self.assertEqual(self.mem(0x5100, 4), [7, 8, 9, 10])
        self.assertEqual(self.k.hw(0x9000, 3)[:2], [0x1234, 0x1234])

    def test_across_64k(self):
        self.poke(0xFFF0, list(range(1, 17)))
        got = self.k.do((L.OP_COPY, 0x2FFF8, 0xFFF0, 32, 9))
        self.assertEqual(got, [(9, L.ST_OK, 32)])
        self.assertEqual(self.mem(0x2FFF8, 16), list(range(1, 17)))

    def test_errors(self):
        got = self.k.do((L.OP_COPY, 0x2001, 0x1000, 8, 1),
                        (7, 0, 0, 0, 2),
                        (L.OP_FILL, 0x2000, 0, 3, 3))
        self.assertEqual(got, [(1, L.ST_ALIGN, 0), (2, L.ST_BADOP, 0), (3, L.ST_ALIGN, 0)])

    def test_server(self):
        """An op the ring job doesn't know goes to the Forth's server, whose
        completions come in the same ring."""
        got = self.k.do((L.OP_NOP, 0, 0, 0, 5), (L.OP_FILL, 0x6000, 1, 2, 6), (99, 0, 0, 0, 7), ms=5)
        self.assertEqual(sorted(got), [(5, L.ST_OK, 0), (6, L.ST_OK, 2), (7, L.ST_BADOP, 0)])

    def test_many(self):
        """More requests than the ring has entries, in rounds."""
        for r in range(3):
            reqs = [(L.OP_FILL, 0x7000 + 2 * i, i + 100 * r, 2, i) for i in range(40)]
            got = self.k.do(*reqs, ms=4)
            self.assertEqual(got, [(i, L.ST_OK, 2) for i in range(40)])
            self.assertEqual(self.mem(0x7000, 40), [i + 100 * r for i in range(40)])


class Clients(unittest.TestCase):
    """A second client, set up through the kernel's ring: its windows, the
    requests it may not make, and its completions' interrupt."""

    @classmethod
    def setUpClass(cls):
        cls.s = s = Session(build.Build(build.DEFAULT_PROGRAM))
        s.boot()
        cls.k = kernel(s)
        # client 1's rings at 0x10000 in the shared RAM (page 1): requests
        # (8) at +0, completions (8) at +0x100, indices at +0x200
        base = 0x10000
        settings = [base & 0xFFFF, SR >> 16 | 1, 8 * 16, (base + 0x100) & 0xFFFF, SR >> 16 | 1, 8 * 8,
                    (base + 0x200) & 0xFFFF, SR >> 16 | 1, 3 | 0 << 8, 0]
        s.s.shared_write(0x3000 // 2, settings)
        s.s.shared_write((base + 0x200) // 2, [0, 0, 0, 0])
        got = cls.k.do((L.OP_RING, SR + 0x3000, 1, 0, 1),
                       (L.OP_WINDOW, 0x20000, 0x21000, 0, 2, 1 | 0 << 8),
                       (L.OP_WINDOW, SR + 0x10400, SR + 0x10800, 0, 3, 1 | 1 << 8), ms=5)
        assert sorted(got) == [(1, 0, 0), (2, 0, 0), (3, 0, 0)], got
        cls.c = Client(s, 1, base, 8, base + 0x100, 8, base + 0x200)

    def test_windows(self):
        got = self.c.do((L.OP_FILL, 0x20000, 5, 0x1000, 1),
                        (L.OP_FILL, 0x20002, 5, 0x1000, 2),
                        (L.OP_COPY, 0x20000, SR + 0x10400, 0x400, 3),
                        (L.OP_COPY, SR + 0x10400, 0x1FFFE, 4, 4),
                        (L.OP_ZERO, SR + 0x107FE, 0, 2, 5))
        self.assertEqual([(t, st) for t, st, _ in got],
                         [(1, L.ST_OK), (2, L.ST_WINDOW), (3, L.ST_OK), (4, L.ST_WINDOW), (5, L.ST_OK)])

    def test_kernel_only(self):
        got = self.c.do((L.OP_ROUTE, 0, 0, 0, 1), ms=5)
        self.assertEqual(got, [(1, L.ST_DENIED, 0)])

    def test_interrupt(self):
        """Client 1's completions raise level 3 on CPU 0, with an event in
        its ring of events: SRC_RING + 1."""
        blk = L.K_EVBLK
        before = self.s.s.shared(blk // 2, 1)[0]
        got = self.c.do((L.OP_FILL, 0x20000, 1, 2, 9))
        self.assertEqual(got, [(9, L.ST_OK, 2)])
        self.assertEqual(self.s.s.cpu()["irq"] & 4, 4)
        head = self.s.s.shared(blk // 2, 1)[0]
        self.assertEqual(head, (before + 2) % (2 * L.K_EVS))
        self.assertEqual(self.s.s.shared((L.K_EVRING + before) // 2, 1)[0], L.SRC_RING + 1)
