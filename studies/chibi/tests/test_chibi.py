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

    def test_flat_layout(self):
        """The interrupt's entry at 0x000-0x0FF, every opcode's at 0x100 +
        the opcode, the tasks' entries at DEVICE_BASE and COPPER_BASE and
        their words within TASK_BASE's 128."""
        cs = routines2.control_store()
        self.assertEqual(len({cs.words[a] for a in range(uc2.ENTRY_BASE)}), 1)
        self.assertTrue(cs.where[uc2.COPPER_BASE].startswith("l/copper"))
        self.assertTrue(cs.where[uc2.DEVICE_BASE].startswith("l/device"))
        for a in range(uc2.CS_WORDS):
            if cs.where[a].startswith(("l/copper", "l/device")):
                self.assertGreaterEqual(a, uc2.TASK_BASE)


class DeviceTask(unittest.TestCase):
    """The device task on the model: PCM and both PS/2 ports."""

    def test_pcm(self):
        import os
        img = check.assemble(os.path.join(hw.HERE, "programs", "pcm.s"))
        m = hw.device_model(img)
        self.assertEqual(bytes(m.sys.console.out), b"P")
        self.assertEqual(m.sys.dac, [0x80, 0xC0, 0xFF, 0xC0, 0x80, 0x40, 0x00, 0x40])

    def test_ps2(self):
        """The keyboard's bytes printed, the mouse's frame left at 0x72."""
        import os
        img = check.assemble(os.path.join(hw.HERE, "programs", "ps2.s"))
        m = hw.device_model(img, kbd=b"\x1c\xf0", mouse=b"\xa5")
        self.assertEqual(bytes(m.sys.console.out), b"\x1c\xf0")
        frame = int.from_bytes(m.sys.ram[0x72:0x74], "little")
        self.assertEqual(frame >> 6 & 0xFF, 0xA5)
        self.assertEqual(m.sys.ps2[1].irq, 1)


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

    def cases(self, ops, n=12, seed=1, bits=32):
        r = random.Random(seed)
        edges = [0, 1, 0xFFFFFFFF, 0x80000000, 0x7FFFFFFF, 0xFFFF, 0x10000, 0xFFFFFFF9]
        for k in range(n):
            vals = [edges[(k + i) % len(edges)] if k < len(edges) else r.getrandbits(bits)
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

    def test_short(self):
        """Multiplies by, and divides of, 16-bit values: their 16-step paths."""
        self.cases(["MULU r0:r1, r2", "MULS r0:r1, r2", "DIVU r0:r1, r2", "DIVS r0:r1, r2",
                    "MULA r0:r1, r1, r2", "MULFX r0:r1, r2, #8"], 24, seed=4, bits=16)

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

    def test_tables(self):
        """The special mode's tables (an index parcel, then the address's
        low half) for the read-modify-writes, the jumps and MULU, MULS."""
        r = random.Random(5)
        for op in ("INC [0x2000 + r3 * 4]", "DEC half [0x2000 + r3 * 2]", "CLR byte [0x2000 + r3]",
                   "MULU r0:r1, [0x2000 + r3 * 4]", "MULS r0:r1, [0x2000 + r3 * 4]"):
            x = r.randrange(16)
            body = (" MOV r1, #0x12345\n MOV r3, #{x}\n MOV r4, #{v}\n MOV [0x2000 + r3 * 4], r4\n"
                    " {op}\n MOV r2, [0x2000 + r3 * 4]\n MFSR r4, ccr\n").format(
                        x=x, v=r.getrandbits(32), op=op)
            self.assertEqual(self.run_snippet(body), [], op)
        body = (" MOV r3, #2\n MOV r4, #0x80\n MOV [0x2000 + r3 * 4], r4\n"
                " CALL [0x2000 + r3 * 4]\n HALT\n.org 0x80\n MOV r6, #9\n")
        self.assertEqual(self.run_snippet(body), [])

    def test_precise_traps(self):
        """A jump with a byte operand, and INC with an immediate's special
        operand, are illegal before anything changes, the return address the
        instruction's."""
        for op in (".half 0xA1F0", ".half 0xF321, 0x5678, 0x1234"):   # JMP byte [r1]+; INC, R = 3
            body = (" JMP 0x40\n.org 0x08\n MOV r5, [sp + 4]\n HALT\n.org 0x40\n"
                    f" MOV r1, #0x3000\n MOV sp, #0x1000\n {op}\n")
            self.assertEqual(self.run_snippet(body), [], op)

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


class Odt(unittest.TestCase):
    def test_session(self):
        """ODT's test session on the model: what it prints, the registers and
        memory it leaves (hw odt runs it at chip level)."""
        m = hw.odt_model(check.assemble(hw.ODT_PROGRAM), hw.ODT_KEYS)
        out = bytes(m.sys.uart.out)
        self.assertTrue(m.halted)
        self.assertTrue(out.startswith(b"\n\r00000000\r\n@X?\r\n@2000/CAFEF00D \r\n@"), out)
        self.assertIn(b"@2000/CAFEF00D 11223344\n\r00002004/00000000 \r\n@", out)
        self.assertIn(b"@%2/00000002 \r\n@4G", out)
        self.assertEqual(out.count(b"S\n\r"), 7)
        self.assertEqual([m.reg(i) for i in (1, 2, 3)], [0x5678, 3, 0x11223344])

    def test_illegal(self):
        """Opcode 00 is the illegal instruction's trap, whatever its d (ODT's
        own in the paged store's 9, 14 and 15)."""
        for d in (0, 9, 14, 15):
            body = f" JMP 0x40\n.org 0x08\n MOV r5, #7\n HALT\n.org 0x40\n .half {d << 12:#x}\n"
            self.assertEqual(Instructions.run_snippet(None, body), [], d)


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

    def test_gals_doc(self):
        """gals.md as the netlist has it: rerun heron chibi hw gals --write."""
        from heron.studies.chibi import gals
        with open(gals.PATH) as f:
            self.assertEqual(f.read(), gals.markdown())

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

    def test_sta_engine(self):
        """The static timing engine on a word: its branches reach the
        cycle's end, and at the longest lengths every setup is met."""
        from heron.studies.chibi import sta3
        ex, skip = sta3.netlist()
        w, two, extra = next(k for k in sorted(sta2.sta_words())
                             if dict(k[2]).get("AIO") != 1 and k[1])
        item = (w, two, extra, sta3.MAX_LO, sta3.MAX_HI)
        branches = sta3.run(ex, skip, [item], 1, 0)[item]
        self.assertGreater(len(branches), 1)
        for b in branches:
            self.assertGreater(b["end"], 0)
            self.assertFalse([c for c in b["worst"] if c["check"] == "setup" and c["slack"] < 0
                              and c["event"] > 6], b["label"])

    def test_ps2_at_chip_level(self):
        import os
        img = check.assemble(os.path.join(hw.HERE, "programs", "ps2.s"))
        out = hw.run(bytes(hw.m_ram(img)), max_cycles=40_000, kbd=b"\x1c\xf0")
        self.assertEqual(out["output"], b"\x1c\xf0")
        self.assertEqual(out["violation_total"], 0)

    def test_pcm_at_chip_level(self):
        """The device task plays the buffer at the timer's requests."""
        import os
        img = check.assemble(os.path.join(hw.HERE, "programs", "pcm.s"))
        m = hw.device_model(img)
        out = hw.run(bytes(hw.m_ram(img)), max_cycles=3000)
        self.assertEqual(out["output"], b"P")
        self.assertEqual(hw.outcome_diffs(m, out), [])

    def test_hello_at_chip_level(self):
        p = testing.program_paths(["hello"])[0]
        _, out, diffs = hw.run_program(p)
        self.assertEqual(diffs, [])
        self.assertEqual(out["output"], b"Hello, world!\n")
        self.assertEqual(out["violation_total"], 0)


if __name__ == "__main__":
    unittest.main()
