"""The fixed-base mode study: its ISAs, the scan, and the nucleus on 1b
with [rT + 4R]. (The simulator's and the assembler's side have their own
tests: cargo test -p v1-isa --test rt.)"""

import unittest

from heron.infra import asm as asmcore
from heron.infra import isas
from heron.studies.fixed_base import experiments, isa, scan
from heron.studies.v1_isa.sim32 import Machine32

PROGRAM = """
        .org 0
        MOV  r11, #data
        MOV  r9, #10
loop:   MOV  r1, [r11 + 8]
        ADD  r1, [r11 + 12]
        ST   r1, [r11 + 16]
        MOV  r2, [r10 + 8]
        DEC  r9
        BNE  loop
        HALT
        .align 4
data:   .word 0, 0, 5, 7, 0
"""


def run(mod, src=PROGRAM):
    a = asmcore.Assembler(mod)
    a.load("t.s", text=src)
    return Machine32(mod, a.assemble()).run()


class TestFixedBase(unittest.TestCase):
    def test_isa(self):
        mod = isa("v1b", 11)
        self.assertEqual(mod.NAME, "v1b+rt11")
        self.assertIs(isas.get("v1b+rt11"), mod)
        self.assertEqual(mod.disassemble([0x11E2])[0], "MOV r1, [r11 + 8]")
        self.assertEqual(mod.disassemble([0x113A, 0x0008])[0], "MOV r1, [r10 + 8]")
        self.assertEqual(isa("v1bx", 14).disassemble([0xF12A])[0], "ADD.T r1, r2")

    def test_the_mode_runs_as_the_scan_says(self):
        base = run(isas.get("v1b"))
        rt = run(isa("v1b", 11))
        self.assertEqual(base.r[1], 12)
        self.assertEqual(rt.r[1], 12)
        s = scan.Scan().add_machine(base)
        # three accesses through r11 and one through r10, ten times each
        self.assertEqual(s.saves(bases={11})["n"], 30)
        self.assertEqual(s.saves(bases={10})["n"], 10)
        self.assertEqual(s.ops(11), {"MOV": 10, "ADD": 10, "ST": 10})
        for c in scan.CONFIGS:
            if c.endswith("separate"):
                self.assertEqual(base.cycles_for(c) - rt.cycles_for(c), s.saves(bases={11})[c])

    def test_the_nucleus_with_rt(self):
        runs = experiments.kernel([6], ["ipc"])
        for (name, banks), r in runs.items():
            # the IPC path reaches the other thread's TCB through r6
            self.assertLess(r[6]["D32-separate"], r[None]["D32-separate"])
            # the scan's count, or a little more: the code is shorter, and a
            # branch that needed a long form may fit a short one
            scanned = r["scan"].saves(bases={6})["D32-separate"] / r["ops"]
            ran = r[None]["D32-separate"] - r[6]["D32-separate"]
            self.assertGreaterEqual(ran, scanned)
            self.assertLessEqual(ran, scanned + 3)


if __name__ == "__main__":
    unittest.main()
