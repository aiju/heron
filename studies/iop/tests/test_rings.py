"""The rings (RFC 0027, 7): a client's requests in the shared RAM, its
doorbell, the IOP's completions, the windows, the server's requests and
the events and interrupts it posts. The test plays the client, writing
the shared RAM and ringing the doorbells as a CPU would."""

import unittest

from heron.studies.iop import build, layout as L
from heron.studies.iop.run import Session

SR = 0x4000_0000            # the shared RAM, physically
K_CMP = 0x3F_0000           # where these tests keep the kernel's completions, in the CPU's RAM
K_CMPS = 64
EVRING = 0x3F_1000          # and CPU 0's ring of events
EVS = 64
WAKE = 0x40                 # its wake-me word, in the shared RAM


class Client:
    """A client's rings as its driver keeps them (RFC 0040, 5): requests
    in the shared RAM at `req` (a byte offset), completions in the CPU's
    RAM at `cmp`."""

    def __init__(self, s, n, req, nreq, cmp, ncmp):
        self.s, self.n = s, n
        self.req, self.nreq, self.cmp, self.ncmp = req, nreq, cmp, ncmp
        self.head = 0           # requests written
        self.tail = 0           # completions read

    def hw(self, byte, n=1):
        return self.s.s.shared(byte // 2, n)

    def mem(self, pa, n):
        return [int.from_bytes(self.s.s.cpu_mem(pa + 2 * i, 2), "little") for i in range(n)]

    def put(self, op, a=0, b=0, n=0, tag=0, flags=0):
        """A request into the ring (not yet rung)."""
        words = [op, flags, a & 0xFFFF, a >> 16, b & 0xFFFF, b >> 16, n, tag]
        at = self.req + L.RING_ENTRIES + 16 * (self.head % self.nreq)
        self.s.s.shared_write(at // 2, words)
        self.head += 1
        self.s.s.shared_write((self.req + L.RING_HEAD) // 2, [self.head & 0xFFFF])

    def ring(self):
        self.s.s.ring(self.n)

    def handled(self):
        """The events for its completions handled: the completion ring's
        count of them copied to the request ring's."""
        n = self.mem(self.cmp + L.RING_EVENTS, 1)[0]
        self.s.s.shared_write((self.req + L.RING_EVENTS) // 2, [n])

    def completions(self):
        """The completions written since the last call: [(tag, status, result)]."""
        head = self.mem(self.cmp + L.RING_HEAD, 1)[0]
        out = []
        while self.tail & 0xFFFF != head:
            t, st, lo, hi = self.mem(self.cmp + L.RING_ENTRIES + 8 * (self.tail % self.ncmp), 4)
            out.append((t, st, lo | hi << 16))
            self.tail += 1
        self.s.s.cpu_mem_write(self.cmp + L.RING_TAIL, (self.tail & 0xFFFF).to_bytes(2, "little"))
        return out

    def do(self, *requests, ms=2):
        """Requests, rung, and their completions after ms of simulated time."""
        for r in requests:
            self.put(*r)
        self.ring()
        self.s.run_ms(ms)
        return self.completions()


def kernel(s):
    """The kernel's ring, with its completion ring asked for."""
    k = Client(s, 0, L.K_REQ, L.K_REQS, K_CMP, K_CMPS)
    got = k.do((L.OP_CMPRING, K_CMP, 0, K_CMPS, 0xC0))
    assert got == [(0xC0, L.ST_OK, 0)], got
    return k


def events(s, k, cpu=0, ring=EVRING, n=EVS, wake=WAKE):
    """CPU cpu's ring of events, through the kernel's ring."""
    s.s.shared_write(0x3100 // 2, [ring & 0xFFFF, ring >> 16, n, (SR + wake) & 0xFFFF, (SR + wake) >> 16])
    s.s.shared_write(wake // 2, [0])
    got = k.do((L.OP_EVRING, SR + 0x3100, cpu, 0, 0xC1))
    assert got == [(0xC1, L.ST_OK, 0)], got


class Events:
    """A CPU's ring of events, as its handler drains it."""

    def __init__(self, s, ring=EVRING, n=EVS):
        self.s, self.ring, self.n = s, ring, n
        self.tail = 0

    def take(self):
        """The events posted since the last call."""
        head = int.from_bytes(self.s.s.cpu_mem(self.ring + L.RING_HEAD, 2), "little")
        out = []
        while self.tail & 0xFFFF != head:
            at = self.ring + L.RING_ENTRIES + 2 * (self.tail % self.n)
            out.append(int.from_bytes(self.s.s.cpu_mem(at, 2), "little"))
            self.tail += 1
        self.s.s.cpu_mem_write(self.ring + L.RING_TAIL, (self.tail & 0xFFFF).to_bytes(2, "little"))
        return out


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
        self.assertEqual(self.k.hw(L.K_REQ + L.RING_TAIL)[0], self.k.head)

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
    requests it may not make, and its completions' event."""

    @classmethod
    def setUpClass(cls):
        cls.s = s = Session(build.Build(build.DEFAULT_PROGRAM))
        s.boot()
        cls.k = kernel(s)
        events(s, cls.k)
        cls.ev = Events(s)
        # client 1's requests (8) at 0x10000 in the shared RAM, its
        # completions (8) at 0x22000 in the CPU's RAM, in its windows
        req, cmp = 0x10000, 0x22000
        s.s.shared_write(0x3000 // 2, [req & 0xFFFF, (SR + req) >> 16, 8, cmp & 0xFFFF, cmp >> 16, 8])
        s.s.shared_write(req // 2, [0, 0])
        got = cls.k.do((L.OP_WINDOW, 0x20000, 0x21000, 0, 2, 1 | 0 << 8),
                       (L.OP_WINDOW, SR + 0x10400, SR + 0x10800, 0, 3, 1 | 1 << 8),
                       (L.OP_WINDOW, cmp, cmp + 0x100, 0, 4, 1 | 2 << 8),
                       (L.OP_RING, SR + 0x3000, 1, 0, 1), ms=5)
        assert sorted(got) == [(1, 0, 0), (2, 0, 0), (3, 0, 0), (4, 0, 0)], got
        cls.c = Client(s, 1, req, 8, cmp, 8)

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

    def test_completion_ring_in_windows(self):
        """A client's completion ring must be in its windows."""
        got = self.c.do((L.OP_CMPRING, 0x30000, 0, 8, 6), ms=5)
        self.assertEqual(got, [(6, L.ST_WINDOW, 0)])

    def test_event(self):
        """Client 1's completions, routed to CPU 0 at level 3 (slow): an
        event in its ring of events, SRC_RING + 1, and the level; the next
        only once the client has handled it."""
        got = self.k.do((L.OP_ROUTE, 0, (L.SRC_RING + 1) | (3 << 16), 0, 7, L.SLOW), ms=3)
        self.assertEqual(got, [(7, L.ST_OK, 0)])
        self.ev.take()
        self.s.s.irq_clear(0xFF)
        self.assertEqual(self.c.do((L.OP_FILL, 0x20000, 1, 2, 9)), [(9, L.ST_OK, 2)])
        self.assertEqual(self.s.s.cpu()["irq"], 1 << 2)
        self.assertEqual(self.ev.take(), [L.SRC_RING + 1])
        # not handled yet: completions, but no event
        self.s.s.irq_clear(0xFF)
        self.assertEqual(self.c.do((L.OP_FILL, 0x20000, 1, 2, 10)), [(10, L.ST_OK, 2)])
        self.assertEqual((self.s.s.cpu()["irq"], self.ev.take()), (0, []))
        # handled: the next one comes
        self.c.handled()
        self.assertEqual(self.c.do((L.OP_FILL, 0x20000, 1, 2, 11)), [(11, L.ST_OK, 2)])
        self.assertEqual((self.s.s.cpu()["irq"], self.ev.take()), (1 << 2, [L.SRC_RING + 1]))
