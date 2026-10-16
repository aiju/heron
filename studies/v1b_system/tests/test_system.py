"""The system: every program on the instruction-level model of the machine,
and a short one on the whole system at chip level (`heron v1b_system test`
runs them all there, in about 8 minutes)."""

import unittest

from heron.studies.v1b_system import cli, lengths, machine, programs


class InstructionLevel(unittest.TestCase):
    def test_programs(self):
        for path in programs.program_paths():
            name = path.rsplit("/", 1)[1][:-2]
            with self.subTest(name):
                _img, m = programs.run_isa(path)
                self.assertTrue(m.halted)
                self.assertEqual(m.bus_dump("uart"), programs.expected(name))


class ChipLevel(unittest.TestCase):
    def test_hello(self):
        path = programs.program_paths(["hello"])[0]
        diffs, hw, _m = cli.check(path, max_cycles=2000)
        self.assertEqual(diffs, [])
        self.assertEqual(hw["violation_total"], 0)
        self.assertEqual(hw["output"], b"Hello, world!\n")


class Lengths(unittest.TestCase):
    def test_classes(self):
        # four lengths the counter can make, longest last; the 16th ROM
        # holds each microinstruction's class, and the longest wherever the
        # analysis saw no microinstruction (an unused address)
        cls, d = machine.classes()
        ticks = d["lengths"]
        self.assertEqual(ticks, sorted(ticks))
        self.assertTrue(all(lengths.K_MIN <= k <= lengths.K_MAX for k in ticks))
        rom = lengths.class_rom(cls)
        for a, w in lengths.rom_words().items():
            self.assertEqual(rom[a], cls.get(w, 3))


if __name__ == "__main__":
    unittest.main()
