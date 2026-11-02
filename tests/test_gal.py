"""infra/hw/gal.py: what a 22V10 can't do is recorded, and check() refuses it."""

import unittest

from heron.infra.hw import gal as G
from heron.infra.hw.netlist import Netlist


class TestGalProblems(unittest.TestCase):
    def build(self, oe, ar=None):
        nl = Netlist()
        G.add(nl, "U1", {"Y": ([{"A": 1}], True, False, oe)}, clock="CLK", ar=ar)
        return nl

    def test_one_term_is_fine(self):
        nl = self.build([{"E": 1, "F": 0}], ar=[{"R": 0}])
        self.assertEqual(G.problems(nl), [])
        G.check(nl)

    def test_enable_of_two_terms(self):
        nl = self.build([{"E": 1}, {"F": 1}])
        self.assertEqual(len(G.problems(nl)), 1)
        with self.assertRaises(ValueError):
            G.check(nl)

    def test_reset_of_two_terms(self):
        nl = self.build([{"E": 1}], ar=[{"R": 0}, {"S": 1}])
        self.assertEqual(len(G.problems(nl)), 1)


if __name__ == "__main__":
    unittest.main()
