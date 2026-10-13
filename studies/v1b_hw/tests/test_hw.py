"""The draft 1b hardware on the chip-level simulator: a short program
matches the instruction-level and RTL models, cycle for cycle."""

import unittest

from heron.infra.hw import runner
from heron.studies.v1b_hw import machine


class ChipLevel(unittest.TestCase):
    def test_hello(self):
        path = machine.program_paths(["hello"])[0]
        inp = runner.program_input(path)
        img, m = machine.run_isa(path, inp)
        hw = runner.run_hw(machine, img, 340, inp=inp, max_cycles=m.cycles + 1000, trace=(0, 2))
        self.assertEqual(machine.compare(m, hw), [])
        self.assertEqual(hw["violation_total"], 0)
        self.assertEqual(hw["output"], b"Hello, world!\n")
        self.assertEqual([line.split()[0] for line in hw["trace"]], ["0", "1", "2"])
