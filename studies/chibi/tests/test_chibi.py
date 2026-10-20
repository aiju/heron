"""Chibi Heron: the two-halves machine's microcode and model against draft
2's simulator, its netlist's 22V10s and timing table, programs at chip
level; and the first cut's."""

import random
import unittest

import heron.studies.v2_isa  # noqa: F401  (registers the ISA)
from heron.infra.hw import gal
from heron.studies.chibi import (board, board2, check, hw, routines, routines2, rtl, sta2,
                                 ucode as uc, ucode2 as uc2)
from heron.studies.v2_isa import testing


class Microcode(unittest.TestCase):
    def test_fields_fit(self):
        self.assertLessEqual(uc.USED_BITS, uc.WORD_BITS)
        self.assertEqual(len(set(uc.AOP_CODE.values())), len(uc.AOPS))
        self.assertEqual(len(set(uc.FL_CODE.values())), len(uc.FLOPS))

    def test_pack(self):
        f = {"DS": uc.DS_RF, "AOP": uc.AOP_CODE["ADD"], "LDL": 1, "JT": 17, "PT": 2}
        self.assertEqual({k: v for k, v in uc.unpack(uc.pack(f)).items() if v}, f)

    def test_page3_entries(self):
        self.assertEqual(routines.ENTRIES["exc"], routines.P3_EXC)
        self.assertEqual(routines.ENTRIES["halt"], routines.P3_HALT)

    def test_alu(self):
        r = random.Random(1)
        for _ in range(2000):
            a, b, c = r.getrandbits(16), r.getrandbits(16), r.getrandbits(1)
            self.assertEqual(rtl.alu181(a, b, 0b1001, 0, c), ((a + b + c) & 0xFFFF, (a + b + c) >> 16))
            d = a + (~b & 0xFFFF) + c
            self.assertEqual(rtl.alu181(a, b, 0b0110, 0, c), (d & 0xFFFF, d >> 16))


class Microcode2(unittest.TestCase):
    """The two-halves machine's control store."""

    def test_fields_fit(self):
        self.assertEqual(uc2.USED_BITS, uc2.WORD_BITS)
        self.assertEqual(len(set(uc2.FL_CODE.values())), len(uc2.FLOPS))
        self.assertLessEqual(len(uc2.IMMS), 32)

    def test_every_opcode(self):
        cs = routines2.control_store()
        self.assertEqual(cs.missing, {})

    def test_ticks_table(self):
        """Every microinstruction timed: rerun heron chibi hw sta --write
        after changing the microcode or the netlist."""
        self.assertEqual(routines2.control_store().untimed, set())

    def test_page3_entries(self):
        self.assertEqual(routines2.ENTRIES["exc"], 9)


class Programs(unittest.TestCase):
    """Programs on the register-transfer model, as the simulator runs them."""

    def check(self, name):
        p = testing.program_paths([name])[0]
        _, m, diffs = check.check_program(p)
        self.assertEqual(diffs, [], name)

    def test_hello(self):
        self.check("hello")

    def test_strings(self):
        self.check("strings")

    def test_bignum(self):
        self.check("bignum")

    def test_first_cut(self):
        p = testing.program_paths(["hello"])[0]
        _, m, diffs = check.check_program(p, first=True)
        self.assertEqual(diffs, [])


class Instructions(unittest.TestCase):
    """The long microcode routines on chosen and random operands, against
    the simulator: registers, flags (read back with MFSR) and memory."""

    def run_snippet(self, body):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.s")
            with open(path, "w") as f:
                f.write(".org 0\n" + body + "\n HALT\n")
            img = check.assemble(path)
        ref = check.run_isa(img, b"")
        m = check.run_rtl(img, b"", max_cycles=100_000)
        return check.compare(ref, m)

    def cases(self, ops, n=12, seed=1):
        r = random.Random(seed)
        edges = [0, 1, 0xFFFFFFFF, 0x80000000, 0x7FFFFFFF, 0xFFFF, 0x10000, 0xFFFFFFF9]
        for k in range(n):
            vals = [edges[(k + i) % len(edges)] if k < len(edges) else r.getrandbits(32)
                    for i in range(3)]
            op = ops[k % len(ops)]
            body = "".join(f" MOV r{i}, #{v}\n" for i, v in enumerate(vals))
            body += f" MOV r5, #{r.getrandbits(4)}\n MTSR ccr, r5\n {op}\n MFSR r4, ccr\n"
            divisor = {"r2": vals[2], "r1": vals[1], "r0": vals[0]}[op[-2:]] if "DIV" in op else 1
            if divisor == 0:
                continue
            self.assertEqual(self.run_snippet(body), [], (op, [hex(v) for v in vals]))

    def test_muls_divs(self):
        self.cases(["MULS r0:r1, r2", "DIVS r0:r1, r2", "MULS r0:r2, r2", "DIVS r0:r1, r0"], 24)

    def test_mula_mulfx(self):
        self.cases(["MULA r0:r1, r1, r2", "MULFX r0:r1, r2, #16", "MULFX r0:r2, r1, #0",
                    "MULFX r0:r0, r2, #31"], 16)

    def test_clz_rev(self):
        self.cases(["CLZ r1, r2", "REV r1, r2", "CLZ r2, r2", "REV r1, r1"], 16)

    def test_new(self):
        """The instructions the first cut hadn't."""
        self.cases(["ADD.B4 r1, r2", "MERGE r1, r2, r0", "FFS r1, r2", "POPC r1, r2",
                    "MULU r0:r1, #1234", "MULS r0:r1, #-1234"], 16)

    def test_tagged(self):
        r = random.Random(2)
        for k in range(10):
            op = ["TMOV", "TADD", "TSUB", "TCMP", "TTST"][k % 5]
            a, b = r.getrandbits(32) & ~(k % 3 != 0), r.getrandbits(32) & ~1
            body = (" JMP 0x40\n.org 0x18\n HALT\n.org 0x40\n"
                    f" MOV r1, #{a}\n MOV r2, #{b}\n {op} r1, r2\n MFSR r4, ccr\n")
            self.assertEqual(self.run_snippet(body), [], (op, hex(a), hex(b)))

    def test_ldm_stm_tables(self):
        r = random.Random(3)
        for k in range(6):
            a, c = sorted((r.randrange(1, 14), r.randrange(1, 14)))
            x = r.randrange(64)
            body = (" MOV r15, #0x3000\n"
                    + "".join(f" MOV r{i}, #{r.getrandbits(32)}\n" for i in range(1, 15))
                    + f" STM r15, r{a}-r{c}\n" + "".join(f" MOV r{i}, #0\n" for i in range(1, 15))
                    + f" LDM r15, r{a}-r{c}\n MOV r3, #{x}\n MOV [0x2000 + r3 * 4], r1\n"
                    " MOV r2, [0x2000 + r3 * 4]\n LEA r5, [0x2000 + r3 * 4]\n")
            self.assertEqual(self.run_snippet(body), [], (a, c, x))


class Netlist(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nl = board.build(sim=True)

    def test_gals_fit(self):
        for inst in self.nl.instances:
            if inst.type.name == "22v10":
                for pin, _reg, _inv, terms in inst.gal:
                    self.assertLessEqual(len(terms), gal.TERMS[int(pin[2:])], inst.ref)

    def test_chips(self):
        n = sum(1 for i in self.nl.instances if i.type.family not in ("fixture", "passive"))
        self.assertLessEqual(n, 120)

    def test_sta_netlist(self):
        board.build(sim=False)


class Netlist2(unittest.TestCase):
    """The two-halves machine's netlist."""

    @classmethod
    def setUpClass(cls):
        cls.nl = board2.build(sim=True)

    def test_gals_fit(self):
        for inst in self.nl.instances:
            if inst.type.name == "22v10":
                for pin, _reg, _inv, terms in inst.gal:
                    self.assertLessEqual(len(terms), gal.TERMS[int(pin[2:])], inst.ref)

    def test_chips(self):
        """The budget: 120 packages, the simulation's own button aside."""
        n = sum(1 for i in self.nl.instances if i.type.family not in ("fixture", "passive")
                and i.ref != "S_BTNX")
        self.assertLessEqual(n, 120)

    def test_sta_netlist(self):
        board2.build(sim=False)
        self.assertGreater(len(sta2.sta_words()), 400)

    def test_ps2_at_chip_level(self):
        import os
        img = check.assemble(os.path.join(hw.HERE, "programs", "ps2.s"))
        out = hw.run(bytes(hw.m_ram(img)), max_cycles=40_000, kbd=b"\x1c\xf0")
        self.assertEqual(out["output"], b"\x1c\xf0")
        self.assertEqual(out["violation_total"], 0)

    def test_hello_at_chip_level(self):
        p = testing.program_paths(["hello"])[0]
        _, out, diffs = hw.run_program(p)
        self.assertEqual(diffs, [])
        self.assertEqual(out["output"], b"Hello, world!\n")
        self.assertEqual(out["violation_total"], 0)


if __name__ == "__main__":
    unittest.main()
