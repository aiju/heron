"""The napkin: every board within a double Eurocard, every design timed
on every key instruction, and the RFC's tables up to date."""

import os
import unittest

from heron.studies.cards import napkin


class TestNapkin(unittest.TestCase):
    def test_boards_fit(self):
        for key, (_, boards) in napkin.DESIGNS.items():
            for name, blocks in boards:
                _, area, _, _ = napkin.board_sums(blocks)
                self.assertLessEqual(area, napkin.BUDGET + 0.5, f"design {key}, {name}")
        self.assertLessEqual(napkin.board_sums(napkin.ARITH)[1], napkin.BUDGET + 0.5)

    def test_every_design_times_every_key_instruction(self):
        for key in napkin.DESIGNS:
            r = napkin.recipes(key)
            for ins in napkin.KEY:
                self.assertIn(ins, r, f"design {key}")
                for floor in (4, 5):
                    self.assertGreaterEqual(napkin.cost(r[ins], floor), floor if "(before" not in r[ins][0][0] else 0)

    def test_the_mix_is_mapped(self):
        for name in napkin.MIX:
            if name in ("Bcc", "DBNZ", "LSL", "LSR", "ASR", "ROR"):
                continue
            self.assertIn(name, napkin.KIND)
            self.assertIn(napkin.KIND[name], napkin.recipes("A"))

    def test_the_flash_sets_a_floor_of_five_ticks(self):
        self.assertEqual(napkin.flash_floor(), 5)
        d = dict(napkin.D, flash=45.0)
        self.assertEqual(napkin.flash_floor(d), 4)

    def test_rfc_tables_up_to_date(self):
        if not os.path.exists(napkin.OUT):
            self.skipTest("not written yet")
        with open(napkin.OUT) as f:
            self.assertEqual(f.read(), napkin.tables(), "run heron cards napkin --write")


if __name__ == "__main__":
    unittest.main()
