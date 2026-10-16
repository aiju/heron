"""The draft 2 CPU's netlist: on the chip-level simulator it runs a program
as the RTL model does, cycle for cycle, at the microcode's own length
classes and with no timing violation; and the periods those classes come
from (ticks.json) are what static timing analysis measures now."""

import math
import unittest
from collections import defaultdict

import heron.studies.v2_isa  # noqa: F401
from heron.studies.v2_hw import check as chk, hw, sta, timing, ucode as uc


class ChipLevel(unittest.TestCase):
    def test_hello(self):
        m, out, diffs = hw.check(chk.program_paths(["hello"])[0])
        self.assertEqual(diffs, [])
        self.assertEqual(out["violation_total"], 0)
        self.assertEqual(out["output"], b"Hello, world!\n")

    def test_power_up(self):
        # whatever state the flip-flops come up in (the clock generator's
        # are never reset), the machine runs: hello from other power-ups
        from heron.infra import asm, isas
        from heron.studies.v2_hw import iop
        img = asm.assemble_file(isas.get("v2"), chk.program_paths(["hello"])[0])
        mem = iop.boot_image(img)
        for seed in (2, 3, 4):
            out = hw.run(mem, max_cycles=3000, seed=seed)
            self.assertEqual(out["violation_total"], 0, seed)
            self.assertEqual(out["output"], b"Hello, world!\n", seed)


class Timing(unittest.TestCase):
    def test_every_microinstruction_measured(self):
        self.assertEqual(uc.built().estimated, [])

    def test_table_is_current(self):
        # if this fails, the netlist (or the microcode) changed: run
        # `heron v2_hw hw sta --write`
        ns = defaultdict(float)
        for T, w, *_rest in sta.analyse(force=True):
            self.assertLess(T, math.inf)
            ns[f"{w:x}"] = max(ns[f"{w:x}"], round(T, 1))
        self.assertEqual(dict(ns), timing.measured())
