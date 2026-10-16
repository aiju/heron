"""The backplane and the cards against RFC 0014, with scripted masters
(bfm.py) in place of the CPU card: transfers to each class of card, the
arbiter's rules (7.1), locked sequences (7.3) and the bus monitor (5.6).

A record's entry e is what a master saw at bus clock edge e: the clock
that ends at e. Signals are active low except SEL."""

import unittest

from heron.studies.v1b_system import bfm

MEM, IO, EMPTY = 0x10000000, 0xF0000000, 0x40000000
N = 6                                  # a simple card's data clocks


def phases(rec):
    """The transfers seen in a record: (edge of the address clock, the
    data phase's entries up to and including the end)."""
    out = []
    e = 0
    while e < len(rec):
        if rec[e]["START_n"] == 0:
            ph = []
            for f in range(e + 1, len(rec)):
                ph.append(rec[f])
                if (rec[f]["RDY_n"] == 0 and rec[f]["WAIT_n"] == 1) or rec[f]["BERR_n"] == 0:
                    break
            out.append((e, ph))
            e += len(ph)
        e += 1
    return out


def data(entry):
    return sum(entry[f"D{i}"] << i for i in range(16))


def status(ph, *sigs):
    return [tuple(x[s] for s in sigs) for x in ph]


class Transfers(unittest.TestCase):
    """One master, parked on (slot 0), with each class of card."""

    @classmethod
    def setUpClass(cls):
        m = bfm.Master("M0", 0, clock=True)
        m.wait_reset()
        m.request()
        m.write(MEM + 0x10, 0xBEEF)                # 0: a fast card's write
        m.read(MEM + 0x10)                         # 1: and read
        m.write(MEM + 0x16, 0x1234)                # 2: the upper half (A1)
        m.read(MEM + 0x16)                         # 3
        m.read(MEM + 0x08000000)                   # 4: the memory card's ID
        m.write(MEM + 0x11, 0x5500, size=1)        # 5: an odd byte, on D8-D15
        m.read(MEM + 0x10)                         # 6
        m.write(IO + 0xDC, 0xA5)                   # 7: the UART's scratch register
        m.read(IO + 0xDC)                          # 8
        m.read(EMPTY, end="berr")                  # 9: an empty slot
        m.idle(2)
        cls.m = m
        cls.out = bfm.run([m], clocks=120)
        cls.rec = cls.out.record("M0")
        cls.ph = phases(cls.rec)

    def test_no_violations(self):
        self.assertEqual(self.out.hw["violation_summary"], [])

    def test_all_transfers(self):
        self.assertEqual(len(self.ph), 10)

    def test_fast_write(self):
        # the memory card holds WAIT in the first data clock; RDY and W32
        # in every data clock of a fast 32-bit card
        _, ph = self.ph[0]
        self.assertEqual(status(ph, "DPH_n", "RDY_n", "WAIT_n", "W32_n", "BERR_n"),
                         [(0, 0, 0, 0, 1), (0, 0, 1, 0, 1)])

    def test_fast_read(self):
        _, ph = self.ph[1]
        self.assertEqual(status(ph, "DPH_n", "RDY_n", "WAIT_n", "W32_n", "BERR_n"),
                         [(0, 0, 1, 0, 1)])
        self.assertEqual(data(ph[-1]), 0xBEEF)
        self.assertEqual(data(self.ph[3][1][-1]), 0x1234)

    def test_id_and_bytes(self):
        self.assertEqual(data(self.ph[4][1][-1]), 0x0102)
        self.assertEqual(data(self.ph[6][1][-1]), 0x55EF)

    def test_simple_card(self):
        # N data clocks with DPH, then the recovery clock with RDY only
        for k in (7, 8):
            _, ph = self.ph[k]
            self.assertEqual(status(ph, "DPH_n", "RDY_n", "W32_n"),
                             [(0, 1, 1)] * N + [(1, 0, 1)])
        # the UART's register in D0-D7, the card's ID in D8-D15
        self.assertEqual(data(self.ph[8][1][-1]), 0x10A5)

    def test_empty_slot(self):
        # BERR in the first data clock, no RDY
        _, ph = self.ph[9]
        self.assertEqual(status(ph, "DPH_n", "RDY_n", "BERR_n"), [(0, 1, 0)])

    def test_back_to_back(self):
        # a master may start its next address clock right after the end
        ends = [e + len(ph) for e, ph in self.ph]
        starts = [e for e, _ in self.ph]
        self.assertEqual([s - e for e, s in zip(ends, starts[1:])], [1] * 9)


class Arbitration(unittest.TestCase):
    """Two masters: slot 0 (the main CPU's place, lowest) and slot 7."""

    def owners(self, recs):
        """Per edge, the slots that saw GNT; and per address clock, its
        master: the one that saw GNT at the edge before."""
        grants = [[s for s, r in recs.items() if r[e]["GNT_n"] == 0]
                  for e in range(len(recs[0]))]
        starts = [(e, grants[e - 1]) for e in range(1, len(grants)) if recs[0][e]["START_n"] == 0]
        return grants, starts

    def check_rules(self, recs):
        grants, starts = self.owners(recs)
        busy = [r["START_n"] == 0 or r["DPH_n"] == 0 or r["RDY_n"] == 0 or r["BERR_n"] == 0
                for r in recs[0]]
        for e, g in enumerate(grants):
            self.assertLessEqual(len(g), 1, f"two grants at edge {e}")
        for e, g in starts:
            self.assertEqual(len(g), 1, f"an address clock at edge {e} without a grant")
        for s, r in recs.items():
            for e in range(1, len(r)):
                if r[e]["GNT_n"] == 0 and r[e - 1]["GNT_n"] == 1:
                    # a grant comes in a clock in which no transfer is
                    # under way (it was given at an idle edge)
                    self.assertFalse(busy[e], f"slot {s} granted at edge {e} with the bus busy")
                    self.assertFalse(busy[e - 1], f"slot {s} granted just after a busy edge {e - 1}")
        return grants, starts

    def test_request_on_idle_bus(self):
        # parked on slot 0; slot 7 asks: 4 clocks to its first address
        # clock (RFC 0014 section 7.2 says 3; the arbiter registers REQ
        # before it acts on it)
        m0 = bfm.Master("M0", 0, clock=True)
        m0.wait_reset()
        m7 = bfm.Master("M7", 7)
        m7.wait_reset()
        m7.idle(4)
        m7.request()
        m7.read(MEM)
        m7.release()
        m7.idle(2)
        out = bfm.run([m0, m7], clocks=40)
        r0, r7 = out.record("M0"), out.record("M7")
        req = next(e for e, x in enumerate(r7) if x["REQ_n"] == 0)
        start = next(e for e, x in enumerate(r7) if x["START_n"] == 0)
        self.assertEqual(start - req, 4)
        grants, _ = self.check_rules({0: r0, 7: r7})
        # parked on slot 0 before and after
        self.assertEqual(grants[req], [0])
        self.assertEqual(grants[-1], [0])
        self.assertEqual(out.hw["violation_summary"], [])

    def test_priority_and_withdrawal(self):
        # slot 0 is busy with transfers when slot 7 asks: slot 0 loses the
        # bus after its current transfer, slot 7 gets it on an idle bus,
        # and slot 0 has it back once slot 7 lets go
        m0 = bfm.Master("M0", 0, clock=True)
        m0.wait_reset()
        for i in range(10):
            m0.request()
            m0.read(MEM + 4 * i)
        m0.release()
        m7 = bfm.Master("M7", 7)
        m7.wait_reset()
        m7.idle(6)
        for i in range(3):
            m7.request()
            m7.write(MEM + 0x100 + 2 * i, 0x7000 + i)
        m7.release()
        out = bfm.run([m0, m7], clocks=150)
        recs = {0: out.record("M0"), 7: out.record("M7")}
        grants, starts = self.check_rules(recs)
        who = [g[0] for _, g in starts]
        self.assertEqual(who.count(0), 10)
        self.assertEqual(who.count(7), 3)
        # slot 7's transfers come together, between slot 0's
        first7 = who.index(7)
        self.assertGreater(first7, 0)
        self.assertEqual(who[first7:first7 + 3], [7, 7, 7])
        self.assertEqual(out.hw["violation_summary"], [])

    def test_lock(self):
        # slot 0 holds the bus through a locked read-modify-write although
        # slot 7, higher, asks during it
        m0 = bfm.Master("M0", 0, clock=True)
        m0.wait_reset()
        m0.request()
        m0.lock()
        m0.read(MEM + 0x40, lock=True)
        m0.idle(3)
        m0.write(MEM + 0x40, 0x1111, lock=True)
        m0.step(LOCK_n=1)
        m0.release()
        m7 = bfm.Master("M7", 7)
        m7.wait_reset()
        m7.idle(3)
        m7.request()
        m7.read(MEM + 0x40)
        m7.release()
        out = bfm.run([m0, m7], clocks=60)
        r0, r7 = out.record("M0"), out.record("M7")
        grants, starts = self.check_rules({0: r0, 7: r7})
        self.assertEqual([g[0] for _, g in starts], [0, 0, 7])
        for e in range(1, len(r0)):
            if r0[e]["GNT_n"] == 1 and r0[e - 1]["GNT_n"] == 0:
                self.assertEqual(r0[e - 1]["LOCK_n"], 1, f"withdrawn at edge {e - 1} under LOCK")
        # slot 7 read what the locked write left
        self.assertEqual(data(phases(r7)[-1][1][-1]), 0x1111)
        self.assertEqual(out.hw["violation_summary"], [])


class Monitor(unittest.TestCase):
    def test_wait_timeout(self):
        # a fast card that never lets go of WAIT: the bus monitor ends the
        # transfer with BERR (RFC 0014 section 5.6: WAIT asserted for 256
        # clocks)
        m0 = bfm.Master("M0", 0, clock=True)
        m0.wait_reset()
        m0.request()
        m0.read(0x90000000, end="berr")
        m0.read(MEM)                               # and the bus works after it
        m0.idle(2)
        s9 = bfm.WaitSlave("S9", 9)
        out = bfm.run([m0, s9], clocks=300, cards=("MEM",))
        ph = phases(out.record("M0"))
        _, first = ph[0]
        # WAIT in 256 clocks, then BERR in the next (which still has WAIT)
        self.assertEqual(status(first, "WAIT_n", "BERR_n"), [(0, 1)] * 256 + [(0, 0)])
        self.assertTrue(all(x["DPH_n"] == 0 for x in first))
        _, second = ph[1]
        self.assertEqual(status(second, "RDY_n", "BERR_n"), [(0, 1)])
        self.assertEqual(out.hw["violation_summary"], [])


if __name__ == "__main__":
    unittest.main()
