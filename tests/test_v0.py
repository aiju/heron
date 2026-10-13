"""Draft 0: assembler/disassembler round trip, instruction semantics, and
`tmc run`."""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from tmc import asm
from tmc.isa import v0
from tmc.sim import Machine


def run(src, **kw):
    img = asm.assemble_text(v0, src)
    m = Machine(v0, img, **kw)
    m.run(max_cycles=100000)
    return m


class RoundTrip(unittest.TestCase):
    def test_every_word(self):
        """Disassemble every legal word and assemble it back at the same address."""
        pc = 0x4000
        ext = 0x1234  # doesn't fit in 8 bits, so auto-shortening can't kick in
        bad = []
        for w in range(0x10000):
            text, n = v0.disassemble(w, ext, pc)
            if text.startswith(".word"):
                continue
            src = f".org 0x{pc:X}\n{text}\n"
            img = asm.assemble_text(v0, src)
            words = [img.mem[pc + 2 * i] | (img.mem[pc + 2 * i + 1] << 8)
                     for i in range(n)]
            expect = [w, ext][:n]
            # unused fields assemble as zero
            op = w >> 12
            if op == v0.OP_SYS:
                fn = w & 15
                keep = {2: 0x00F0, 3: 0x00F0, 5: 0x00F0, 11: 0x00F0, 6: 0x0F00, 10: 0x0F00}.get(fn, 0)
                expect[0] = w & (0xF00F | keep)
            elif op == v0.OP_ALUI:
                expect[0] = w & 0xFF0F
            elif op == v0.OP_JCC:
                expect[0] = w & 0xFF00
            if words != expect:
                bad.append((w, text, words))
        self.assertEqual(bad[:5], [])


class Semantics(unittest.TestCase):
    def test_add_flags(self):
        for a, b in [(0x7FFF, 1), (0xFFFF, 1), (0x8000, 0x8000), (5, 7), (0, 0)]:
            m = run(f"LI r1, #{a}\nLI r2, #{b}\nADD r1, r2\nHALT")
            r = a + b
            self.assertEqual(m.r[1], r & 0xFFFF)
            self.assertEqual(m.c, r >> 16)
            sa, sb, sr = a >> 15, b >> 15, (r >> 15) & 1
            self.assertEqual(m.v, int(sa == sb and sr != sa))

    def test_sub_carry_is_not_borrow(self):
        m = run("LI r1, #5\nCMP r1, #7\nHALT")
        self.assertEqual((m.c, m.z, m.n), (0, 0, 1))
        m = run("LI r1, #7\nCMP r1, #5\nHALT")
        self.assertEqual((m.c, m.z), (1, 0))
        m = run("LI r1, #7\nCMP r1, #7\nHALT")
        self.assertEqual((m.c, m.z), (1, 1))

    def test_32bit_add_sub(self):
        m = run("""
            LI r1, #0xFFFF
            LI r2, #0x0001
            LI r3, #0x0001
            LI r4, #0x0000
            ADD r1, r3      ; low
            ADC r2, r4      ; high
            HALT""")
        self.assertEqual((m.r[2], m.r[1]), (2, 0))
        m = run("""
            LI r1, #0x0000
            LI r2, #0x0002
            SUB r1, #1
            SBC r2, #0
            HALT""")
        self.assertEqual((m.r[2], m.r[1]), (1, 0xFFFF))

    def test_branches(self):
        for cc, a, b in [("EQ", 3, 3), ("NE", 3, 4), ("LT", -5 & 0xFFFF, 3), ("GT", 3, -5 & 0xFFFF),
                         ("HI", 0xFFFF, 1), ("LO", 1, 0xFFFF), ("GE", 3, 3), ("LE", 3, 3)]:
            m = run(f"LI r1, #{a}\nLI r2, #{b}\nMVI r3, 0\nCMP r1, r2\nB{cc} .y\nHALT\n.y: MVI r3, 1\nHALT")
            self.assertEqual(m.r[3], 1, cc)

    def test_stack_and_calls(self):
        m = run("""
            LI sp, #0x8000
            LI r1, #11
            CALL f
            BSR g
            HALT
        f:  PUSH r1
            ADDI r1, 1
            POP r2
            RET
        g:  LI r5, #h
            CALL r5
            RET
        h:  MVI r6, 42
            RET""")
        self.assertEqual((m.r[1], m.r[2], m.r[6], m.r[15]), (12, 11, 42, 0x8000))

    def test_bytes_and_shifts(self):
        m = run("""
            LI r1, #buf
            LDB r2, [r1 + 1]
            LD r3, [r1]
            MVI r4, 0x7F
            STB r4, [r1 + 3]
            LD r5, [r1 + 2]
            LI r6, #0x8001
            ASR r7, r6
            SHR r8, r6
            SWAB r9, r6
            SXT r10, r4
            HALT
        buf: .byte 0x34, 0x92, 0, 0
            """)
        self.assertEqual(m.r[2], 0x92)
        self.assertEqual(m.r[3], 0x9234)
        self.assertEqual(m.r[5], 0x7F00)
        self.assertEqual(m.r[7], 0xC000)
        self.assertEqual(m.r[8], 0x4000)
        self.assertEqual(m.r[9], 0x0180)
        self.assertEqual(m.r[10], 0x007F)

    def test_r0_is_zero(self):
        m = run("MVI r0, 5\nADD r1, r0\nHALT")
        self.assertEqual((m.r[0], m.r[1]), (0, 0))

    def test_trap(self):
        m = run("""
            JMP start
            .org 8
            MVI r9, 1
            RTI
        start:
            LI sp, #0x8000
            .word 0xFFFF
            MVI r8, 2
            HALT""")
        self.assertEqual((m.r[9], m.r[8]), (1, 2))
        self.assertFalse(m.in_trap)


def tmc_run(src, *argv):
    """python3 -m tmc run on src (written to a file) and argv: (exit status,
    console output, stderr)."""
    from tmc.__main__ import main
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.s")
        with open(path, "w") as f:
            f.write(src)
        out, err = io.TextIOWrapper(io.BytesIO()), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(["run", path, *argv])
        out.flush()
        return rc, out.buffer.getvalue(), err.getvalue()


class RunCommand(unittest.TestCase):
    """`tmc run`: exit status 1 unless the program halts normally. A trap
    the handler returns from is fine; halting in the handler isn't."""
    VECTORS = "        .org 0\n        JMP  start\n        .org 8\n"
    MAIN = """
start:  LI   sp, #0x8000
        MVI  r1, 'a'
        STB  r1, [0xFF00]
        SWI
        .word 0xB000
        HALT
"""

    def test_trap_handled(self):
        rc, out, err = tmc_run(self.VECTORS + "        RTI\n" + self.MAIN)
        self.assertEqual((rc, out), (0, b"a"))
        self.assertIn("illegal instruction B000", err)
        self.assertNotIn("error", err)

    def test_halt_in_trap_handler(self):
        for main in (self.MAIN, self.MAIN.replace("SWI", "NOP")):
            rc, out, err = tmc_run(self.VECTORS + "        HALT\n" + main)
            self.assertEqual((rc, out), (1, b"a"))
            self.assertIn("error: halted in a trap handler", err)

    def test_no_trap_handler(self):
        # nothing at the trap vector: a zero word is HALT
        rc, _, err = tmc_run("        .org 0\n        JMP  start\n        .org 0x10\n" + self.MAIN)
        self.assertEqual(rc, 1)
        self.assertIn("error: halted in a trap handler", err)

    def test_cycle_limit(self):
        rc, _, err = tmc_run("loop:   BRA  loop\n", "--max-cycles", "1000")
        self.assertEqual(rc, 1)
        self.assertIn("error: cycle limit", err)

    def test_input_from_program(self):
        """Without --input, the program's own `;! input:` line."""
        from tmc import testing
        from tmc.__main__ import main
        path = os.path.join(testing.program_dir("v0"), "rpn.s")
        out = io.TextIOWrapper(io.BytesIO())
        with redirect_stdout(out):
            self.assertEqual(main(["run", path]), 0)
        out.flush()
        self.assertEqual(out.buffer.getvalue(), testing.expected_output("rpn"))


if __name__ == "__main__":
    unittest.main()
