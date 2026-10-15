"""The study's checks: the cycle model against draft 1's Rust model and
the 1b hardware, the chip counts, and the fast system at chip level on
one short program."""

import unittest

from heron.studies.v1b_system import programs
from heron.studies.v1b_tradeoffs import breakdown, cycles, fastcard, fastsys


class CycleModel(unittest.TestCase):
    def test_port_matches_rust(self):
        # the six configurations draft 1's model has, on the suite's
        # commonest instructions
        self.assertEqual(cycles.rust_check(), [])

    def test_calibrated(self):
        per, g = cycles.calibration()
        self.assertAlmostEqual(g, 1.0, delta=0.01)
        self.assertTrue(all(0.85 < r < 1.2 for r in per.values()), per)


class Chips(unittest.TestCase):
    def test_system(self):
        by = breakdown.chips_by_section()
        self.assertAlmostEqual(sum(by.values()), 367, delta=0.01)
        self.assertEqual(sum(v[2] for v in breakdown.widebus().values()), 53)

    def test_fast_card(self):
        # in its slot, with the other cards: every net driven, no conflicts
        fastsys.build((4, 4, 5, 6)).check()
        card = fastcard.build((4, 4, 5, 6))
        self.assertEqual(sum(len(r) for r in card.netlist.bom("fast").values()), 265)
        self.assertEqual([fastcard.preload(k) for k in (fastcard.K_MIN, fastcard.K_MAX)], [15, 0])


class FastSystem(unittest.TestCase):
    def test_hello(self):
        # every class 6 ticks long: as long as the longest microinstruction
        # needs, so no length analysis is needed
        path = programs.program_paths(["hello"])[0]
        diffs, hw, _m = fastsys.check(path, max_cycles=3000, lengths_=(6, 6, 6, 6), cls={})
        self.assertEqual(diffs, [])
        self.assertEqual(hw["violation_total"], 0)
        self.assertEqual(hw["output"], b"Hello, world!\n")


if __name__ == "__main__":
    unittest.main()
