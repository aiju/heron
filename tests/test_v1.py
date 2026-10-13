"""Draft 1a/1b: assembler/disassembler round trip, semantics, timing model,
and `tmc run`."""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from tmc import asm, isa as isas, timing32
from tmc.sim32 import Machine32

V1A = isas.get("v1a")
V1B = isas.get("v1b")

VECTORS = """
        .org 0
        JMP  start
        .org 0x08
        JMP  trap
        .org 0x0C
        JMP  trap
        .org 0x10
        JMP  trap
        .org 0x14
        JMP  trap
        .org 0x40
trap:   MOV  r14, #0x7E
        HALT
start:  LI   sp, #0x100000
"""


def run(isa, body, data=""):
    img = asm.assemble_text(isa, VECTORS + body + "\n        HALT\n" + data)
    m = Machine32(isa, img)
    m.run(max_cycles=100_000)
    return m


def flags(m):
    return "".join(ch if bit else "-" for ch, bit in zip("NZCV", (m.n, m.z, m.c, m.v)))


class RoundTrip(unittest.TestCase):
    def check(self, isa):
        pc = 0x2000
        for w in range(0x10000):
            ws = [w, 0xFF00, 0x0001]
            text, n = isa.disassemble(ws, pc)
            if text.startswith(".half"):
                continue
            img = asm.assemble_text(isa, f"        .org {pc}\n        {text}\n")
            st = [s for s in img.stmts if s.kind == "insn"][0]
            text2, _ = isa.disassemble(st.words + [0, 0], pc)
            self.assertEqual(text2, text, f"{w:04X}")
            self.assertLessEqual(len(st.words), n, text)

    def test_v1a(self):
        self.check(V1A)

    def test_v1b(self):
        self.check(V1B)


class Semantics(unittest.TestCase):
    def both(self, body_a, body_b=None, data=""):
        return run(V1A, body_a, data), run(V1B, body_b or body_a, data)

    def test_add_carry_and_sticky_z(self):
        for m in self.both("""
            LI   r1, #0xFFFFFFFF
            LI   r2, #0
            ADD  r1, #1          ; r1 = 0, C = 1
            ADC  r2, r0          ; r2 = 1; sticky Z: Z was 1, result non-zero -> 0
            MFF  r3
            LI   r4, #0
            LI   r5, #0
            CMP  r4, r0          ; Z = 1, C = 1
            SBC  r5, r0          ; 0 - 0 - 0 = 0: Z stays 1
            MFF  r6
        """):
            self.assertEqual(m.r[1], 0)
            self.assertEqual(m.r[2], 1)
            self.assertEqual(m.r[3] & 0b0100, 0)        # Z clear after ADC
            self.assertEqual(m.r[6] & 0b0100, 0b0100)   # Z still set after SBC

    def test_inc_dec_keep_carry(self):
        for m in self.both("""
            LI   r1, #-1
            ADD  r1, #1          ; C = 1
            DEC  r2, r1          ; r2 = -1, C unchanged
            INC  r2
            MFF  r3
        """):
            self.assertEqual(m.r[2], 0)
            self.assertEqual(m.r[3] & 0b0110, 0b0110)   # Z and C

    def test_addi_keeps_carry(self):
        m = run(V1A, """
            LI   r1, #-1
            ADD  r1, #1
            ADDI r2, 4
            MFF  r3
        """)
        self.assertEqual(m.r[2], 4)
        self.assertEqual(m.r[3] & 0b0010, 0b0010)

    def test_multiply_divide(self):
        for m in self.both("""
            LI   r1, #100000
            LI   r2, #300000
            MULU r1, r2          ; 3e10
            MFHI r3
            LI   r4, #-7
            MOV  r5, #2
            DIVS r4, r5          ; -3 rem -1
            MFHI r6
            LI   r7, #-5
            LI   r8, #3
            MULS r7, r8          ; -15
            MFHI r9
            MTHI r0
            LI   r10, #1000
            MOV  r11, #7
            DIVUL r10, r11       ; HI:r10 = 1000 -> 142 rem 6
            MFHI r12
        """):
            self.assertEqual((m.r[3] << 32) | m.r[1], 30_000_000_000)
            self.assertEqual(m.r[4], (-3) & 0xFFFFFFFF)
            self.assertEqual(m.r[6], (-1) & 0xFFFFFFFF)
            self.assertEqual(m.r[7], (-15) & 0xFFFFFFFF)
            self.assertEqual(m.r[9], 0xFFFFFFFF)
            self.assertEqual((m.r[10], m.r[12]), (142, 6))

    def test_divide_by_zero_traps(self):
        for m in self.both("""
            MOV  r1, #5
            DIVU r1, r0
            MOV  r2, #1
        """):
            self.assertEqual(m.r[14], 0x7E)
            self.assertEqual(m.r[2], 0)
            self.assertEqual(m.traps[0][1], "divide by zero")
            self.assertTrue(m.in_trap)          # the handler halted

    def test_shifts(self):
        for m in self.both("""
            LI   r1, #0x80000001
            MOV  r2, r1
            LSL  r2, #1          ; C = 1
            MFF  r3
            MOV  r4, r1
            ASR  r4, #4
            MOV  r5, r1
            ROR  r5, #4
            MOV  r6, #20
            MOV  r7, r1
            LSR  r7, r6
            MOV  r8, r1
            LSL  r8, #31
        """):
            self.assertEqual(m.r[2], 2)
            self.assertEqual(m.r[3] & 0b0010, 0b0010)
            self.assertEqual(m.r[4], 0xF8000000)
            self.assertEqual(m.r[5], 0x18000000)
            self.assertEqual(m.r[7], 0x800)
            self.assertEqual(m.r[8], 0x80000000)

    def test_unary(self):
        for m in self.both("""
            LI   r1, #0x1234ABCD
            SWAP r2, r1
            SXB  r3, r1
            ZXH  r4, r1
            SXH  r5, r1
            CLZ  r6, r1
            NEG  r7, r1
            NOT  r8, r1
        """):
            self.assertEqual(m.r[2], 0xABCD1234)
            self.assertEqual(m.r[3], 0xFFFFFFCD)
            self.assertEqual(m.r[4], 0xABCD)
            self.assertEqual(m.r[5], 0xFFFFABCD)
            self.assertEqual(m.r[6], 3)
            self.assertEqual(m.r[7], (-0x1234ABCD) & 0xFFFFFFFF)
            self.assertEqual(m.r[8], 0xEDCB5432)

    def test_save_restore_and_calls(self):
        for m in self.both("""
            MOV  r8, #1
            MOV  r9, #2
            MOV  r10, #3
            CALL f
            BSR  f
        """, data="""
f:      SAVE r8-r10
        LD_FIRST
        MOV  r8, #9
        RESTORE r8-r10
        RET
""".replace("LD_FIRST", "")):
            self.assertEqual((m.r[8], m.r[9], m.r[10]), (1, 2, 3))
            self.assertEqual(m.r[15], 0x100000)
            # SAVE puts the lowest register at the lowest address
            self.assertEqual(m.mem[0x100000 - 16:0x100000 - 4],
                             bytes([1, 0, 0, 0, 2, 0, 0, 0, 3, 0, 0, 0]))

    def test_setcc(self):
        for m in self.both("""
            MOV  r1, #3
            CMP  r1, #5
            SETLT r2
            SETGE r3
        """):
            self.assertEqual((m.r[2], m.r[3]), (1, 0))

    def test_misaligned_word_traps(self):
        m = run(V1A, "LI r1, #0x1002\n LD r2, [r1]")
        self.assertEqual(m.traps[0][1][:10], "misaligned")
        m = run(V1B, "LI r1, #0x1002\n MOV r2, [r1]")
        self.assertEqual(m.traps[0][1][:10], "misaligned")

    def test_v1a_loads(self):
        m = run(V1A, """
            LEA  r1, data
            LDSB r2, [r1 + 0]
            LDB  r3, [r1]
            LDSH r4, [r1 + 0]
            LDH  r5, [r1 + 2]
            LD   r6, [r1 + 4]
            LDB  r7, [data + r0]
            STH  r6, [r1 + 8]
            LD   r8, [r1 + 8]
        """, data="        .align 4\ndata: .byte 0x80, 0xFF, 0x34, 0x12\n        .word 0xCAFEF00D, 0\n")
        self.assertEqual(m.r[2], 0xFFFFFF80)
        self.assertEqual(m.r[3], 0x80)
        self.assertEqual(m.r[4], 0xFFFFFF80)
        self.assertEqual(m.r[5], 0x1234)
        self.assertEqual(m.r[6], 0xCAFEF00D)
        self.assertEqual(m.r[7], 0x80)
        self.assertEqual(m.r[8], 0xF00D)

    def test_v1b_modes(self):
        m = run(V1B, """
            LEA  r1, [data]
            MOV  r2, byte [r1]+      ; 0x80, r1 += 1
            MOV  r3, r1
            MOV  r4, [data + 4]
            MOV  r5, #2
            MOV  r6, [r1 + r5*2 + 3] ; data + 1 + 4 + 3 = data + 8
            ST   r4, -[sp]
            MOV  r7, [sp]
            ADD  r7, [sp]            ; 2 * CAFEF00D, 32 bits
            MOV  r8, [sp]+
            ADD  r9, half [data + 2] ; 0x1234
            SUB  r9, #-1             ; +1
            CMP  r9, #0x1235
            SETEQ r10
            LEA  r11, [r1 + r5*8 - 1]
            MOV  r12, [pc + data]
            JMP  [jt + r0]
back:       MOV  r13, #1
        """, data="""
        .align 4
data:   .byte 0x80, 0xFF, 0x34, 0x12
        .word 0xCAFEF00D, 0x55
jt:     .word back
""")
        data = m.r[1] - 1
        self.assertEqual(m.r[2], 0x80)
        self.assertEqual(m.r[3], data + 1)
        self.assertEqual(m.r[4], 0xCAFEF00D)
        self.assertEqual(m.r[6], 0x55)
        self.assertEqual(m.r[7], (2 * 0xCAFEF00D) & 0xFFFFFFFF)
        self.assertEqual(m.r[8], 0xCAFEF00D)
        self.assertEqual(m.r[15], 0x100000)
        self.assertEqual(m.r[10], 1)
        self.assertEqual(m.r[11], data + 1 + 16 - 1)
        self.assertEqual(m.r[12], 0x12348080 & 0xFFFF00FF | 0xFF00)
        self.assertEqual(m.r[13], 1)

    def test_v1b_illegal_modes(self):
        for src in ("ST r1, r2", "ST r1, #3", "LEA r1, [r2]+", "LEA r1, #5", "ADC r1, #1",
                    "MULU r1, [r2]", "MOV r1, half [r2]+", "MOV r1, [r2 + r3*3]"):
            with self.assertRaises(asm.AsmError, msg=src):
                asm.assemble_text(V1B, src)


class Timing(unittest.TestCase):
    def test_reference_values(self):
        cyc = timing32.cycles
        # register ALU op: compute + write-back, next fetch overlapped
        self.assertEqual(cyc((1, 0, "alu", 1), "D32-overlap"), 2)
        self.assertEqual(cyc((1, 0, "alu", 1), "D16-overlap"), 3)
        self.assertEqual(cyc((1, 0, "alu", 1), "D32-separate"), 3)
        # compare: one cycle with the fetch overlapped
        self.assertEqual(cyc((1, 0, "alu", 0), "D32-overlap"), 1)
        # word load on a 16-bit bus: address, two bus cycles, write-back
        self.assertEqual(cyc((1, 0, "ld", "rd", 4, 0), "D32-overlap"), 4)
        self.assertEqual(cyc((1, 0, "ld", "rd", 4, 0), "D32-wide"), 3)
        # a store can't overlap the next fetch without a prefetch buffer
        self.assertEqual(cyc((1, 0, "st", "rd", 4, 0), "D32-overlap"), 4)
        self.assertEqual(cyc((1, 0, "st", "rd", 4, 0), "D32-wide"), 2)
        # taken branch: target, then fetch; not taken: one cycle
        self.assertEqual(cyc((1, 0, "br", 1, 0), "D32-overlap"), 2)
        self.assertEqual(cyc((1, 0, "br", 0, 0), "D32-overlap"), 1)
        # extension parcels: one bus cycle each, unless already buffered
        self.assertEqual(cyc((2, 0, "alu", 1), "D32-overlap"), 3)
        self.assertEqual(cyc((2, 0, "alu", 1), "D32-wide"), 2)


def tmc_run(isa, src, *argv):
    """python3 -m tmc --isa ISA run on src (written to a file) and argv:
    (exit status, console output, stderr)."""
    from tmc.__main__ import main
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.s")
        with open(path, "w") as f:
            f.write(src)
        out, err = io.TextIOWrapper(io.BytesIO()), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(["--isa", isa, "run", path, *argv])
        out.flush()
        return rc, out.buffer.getvalue(), err.getvalue()


class RunCommand(unittest.TestCase):
    """`tmc run`: exit status 1 unless the program halts normally. A trap
    the handler returns from is fine; halting in the handler isn't."""
    PROG = """
        .org 0
        JMP  start
        .org 0x0C
        RTI                     ; SWI: returns to the next instruction
        .org 0x10
        DIVIDE_HANDLER
        .org 0x18
skip:   ST   r1, -[sp]          ; skip the faulting instruction
        MOV  r1, [sp + 8]
        ADD  r1, #2
        ST   r1, [sp + 8]
        MOV  r1, [sp]+
        RTI
start:  LI   sp, #0x100000
        MOV  r1, #97
        ST   r1, byte [0xFFFFFF00]
        SWI  #1
        DIVU r1, r0
        HALT
"""

    def test_trap_handled(self):
        rc, out, err = tmc_run("v1b", self.PROG.replace("DIVIDE_HANDLER", "JMP  skip"))
        self.assertEqual((rc, out), (0, b"a"))
        self.assertIn("divide by zero", err)
        self.assertNotIn("error", err)

    def test_halt_in_trap_handler(self):
        rc, out, err = tmc_run("v1b", self.PROG.replace("DIVIDE_HANDLER", "HALT"))
        self.assertEqual((rc, out), (1, b"a"))
        self.assertIn("error: halted in a trap handler", err)

    def test_no_trap_handler(self):
        # nothing at the SWI vector: a zero parcel is HALT
        for isa in ("v1a", "v1b"):
            rc, _, err = tmc_run(isa, "        .org 0\n        JMP  start\n        .org 0x18\n"
                                      "start:  SWI  #1\n        HALT\n")
            self.assertEqual(rc, 1, isa)
            self.assertIn("error: halted in a trap handler", err)

    def test_cycle_limit(self):
        rc, _, err = tmc_run("v1b", "loop:   BRA  loop\n", "--max-cycles", "1000")
        self.assertEqual(rc, 1)
        self.assertIn("error: cycle limit", err)


if __name__ == "__main__":
    unittest.main()
