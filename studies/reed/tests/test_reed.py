"""Reed's netlist: every board builds and checks, the backplane's lines
have one driver each, and every board fits a double Eurocard."""

import unittest

from heron.studies.reed import bus, fields, system


class TestReed(unittest.TestCase):
    def test_machine_checks(self):
        system.check(system.machine(sim=True))

    def test_boards_fit(self):
        for name, s in system.stats().items():
            self.assertLessEqual(s["area"], 70, name)
            self.assertLessEqual(s["packages"], 72, name)

    def test_backplane_pins(self):
        m = bus.pin_map()
        nets = set(m["P1"].values()) | set(m["P2"].values())
        for line in bus.CONTROL:
            self.assertIn(line, nets)
        for n in bus.A + bus.B:
            self.assertIn(n, nets)

    def test_fields_fit_their_parts(self):
        for board, fl in fields.SLICES.items():
            self.assertLessEqual(sum(w for _, w in fl), 8 * fields.PARTS[board], board)


if __name__ == "__main__":
    unittest.main()
