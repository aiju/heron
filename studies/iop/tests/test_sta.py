"""The card's static timing analysis (sta.py): every check meets 60 ns at
the slow corner, in every case."""

import unittest

from heron.studies.iop import sta


class Timing(unittest.TestCase):
    def test_60ns(self):
        a = sta.Analysis()
        res = a.run()
        late = {what: r[0] for what, r in res.items() if r[0] < 0}
        self.assertEqual(late, {})
        self.assertGreater(len(res), 500)


if __name__ == "__main__":
    unittest.main()
