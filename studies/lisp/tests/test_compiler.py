"""The compiler: its encoder writes what the assembler writes, and code it
compiles on the simulator prints what the reference interpreter prints,
on 1b and with v1bx's tagged mode, and on draft 2 with and without its
tagged operations. (heron lisp test -c runs every program compiled; this
is the quick version, without the saved image.)"""

import unittest

import heron.studies.lisp  # noqa: F401  (registers v1bx)
from heron.infra import asm, isas
from heron.studies.lisp import machine, reference
from heron.studies.v1_isa.sim32 import Machine32
from heron.studies.v2_isa.sim import Machine as Machine2

# every instruction form the compiler writes, with the operands it uses
INSNS = """
((label 1)
 (mov 1 (reg 2)) (mov 1 (imm 0 5)) (mov 1 (imm 65535 65535)) (mov 1 (imm 65535 65520))
 (mov 1 (imm 0 100)) (mov 1 (imm 65535 65000)) (mov 1 (imm 0 40000)) (mov 1 (imm 1 0))
 (mov 1 (imm 18 13398)) (mov 3 (mem 15 8)) (mov 3 (mem 15 60)) (mov 3 (mem 15 64))
 (mov 1 (mem 1 -1)) (mov 1 (mem 1 3)) (mov 1 (mem 2 0)) (st 4 (mem 3 -1)) (st 1 (pdec 15))
 (mov 1 (pinc 15)) (st 3 (pinc 14)) (lea 1 (mem 14 -7)) (mov 9 (byte 1 -3))
 (add 1 (reg 3)) (sub 1 (imm 0 2)) (cmp 1 (reg 13)) (and 9 (imm 0 1)) (or 9 (reg 3))
 (xor 1 (reg 4)) (cmp 14 (abs 260)) (mov 1 (abs 1688)) (st 1 (abs 1688))
 (mov 1 (idx 1 3 2 5 word)) (st 4 (idx 1 3 2 5 word))
 (jmpea (mem 1 1)) (callea (mem 1 1)) (unary neg 1 1) (unary inc 2 3)
 (shift asr 1 1) (shift lsr 9 7) (shift lsl 1 20) (shiftr lsl 1 5) (rr muls 1 3) (rr tst 1 2)
 (save 3 5) (restore 3 8) (ret) (jmpr 9) (nop)
 (lea 9 (pcrel 2))
 (b eq 1) (b ne 2) (b ra 2) (bsr 1) (b lo 1) (b hi 2)
 (rt call 49556) (rt ra 49556)
 (label 2))
"""

# the same, in assembly
ASM = """
L1:     MOV r1, r2
        MOV r1, #5
        MOV r1, #-1
        MOV r1, #-16
        MOV r1, #100
        MOV r1, #-536
        MOV r1, #40000
        MOV r1, #65536
        MOV r1, #1193046
        MOV r3, [sp + 8]
        MOV r3, [sp + 60]
        MOV r3, [sp + 64]
        MOV r1, [r1 + -1]
        MOV r1, [r1 + 3]
        MOV r1, [r2 + 0]
        ST r4, [r3 + -1]
        ST r1, -[sp]
        MOV r1, [sp]+
        ST r3, [r14]+
        LEA r1, [r14 + -7]
        MOV r9, byte [r1 + -3]
        ADD r1, r3
        SUB r1, #2
        CMP r1, r13
        AND r9, #1
        OR r9, r3
        XOR r1, r4
        CMP r14, [260]
        MOV r1, [1688]
        ST r1, [1688]
        MOV r1, [r1 + r3*2 + 5]
        ST r4, [r1 + r3*2 + 5]
        JMP [r1 + 1]
        CALL [r1 + 1]
        NEG r1, r1
        INC r2, r3
        ASR r1, #1
        LSR r9, #7
        LSL r1, #20
        LSL r1, r5
        MULS r1, r3
        TST r1, r2
        SAVE r3-r5
        RESTORE r3-r8
        RET
        JMP r9
        NOP
        LEA r9, [pc + L2]
        BEQ L1
        BNE L2
        BRA L2
        BSR L1
        BLO L1
        BHI L2
        CALL 49556
        JMP 49556
L2:
"""

# every instruction form the draft 2 compiler writes (compiler_v2.lisp)
INSNS_V2 = """
((label 1)
 (mov 1 (reg 2)) (mov 1 (imm 0 5)) (mov 1 (imm 65535 65535)) (mov 1 (imm 65535 65520))
 (mov 1 (imm 0 100)) (cmp 9 (imm 0 21)) (cmp 9 (imm 0 5)) (mov 1 (imm 65535 65000))
 (mov 1 (imm 0 40000)) (mov 1 (imm 1 0)) (mov 1 (imm 18 13398)) (mov 3 (mem 15 8))
 (mov 3 (mem 15 60)) (mov 3 (mem 15 64)) (mov 3 (mem 14 8))
 (mov 1 (mem 1 -1)) (mov 1 (mem 1 3)) (mov 1 (mem 2 0)) (st 4 (mem 3 -1)) (st 1 (pdec 15))
 (mov 1 (pinc 15)) (st 3 (pinc 14)) (lea 1 (mem 14 -7)) (lea 1 (mem 14 8)) (lea 1 (mem 15 8))
 (lea 1 (mem 2 0)) (mov 9 (byte 1 -3))
 (add 1 (reg 3)) (sub 1 (imm 0 2)) (cmp 1 (reg 13)) (and 9 (imm 0 1)) (or 9 (reg 3))
 (xor 1 (reg 4)) (cmp 14 (abs 260)) (mov 1 (abs 1688)) (st 1 (abs 1688))
 (mov 1 (idx 1 3 2 5 word)) (st 4 (idx 1 3 2 5 word))
 (movs 1 (mem 2 0)) (clr (mem 1 4)) (tst 1 (imm 0 1)) (tst 1 (reg 2)) (ttst 1 3)
 (add 1 (tag 3)) (sub 1 (tag 3)) (cmp 1 (tag 3)) (mov 9 (tag 1))
 (jmpea (mem 1 1)) (callea (mem 1 1)) (jmpea (pinc 15)) (unary neg 1 1) (unary inc 2 3)
 (unary sxh 1 2) (shift asr 1 1) (shift lsr 9 7) (shift lsl 1 20) (shiftr lsl 1 5)
 (rr muls 1 3) (rr tst 1 2) (rr divs 1 2)
 (save 3 5) (restore 3 8) (ret) (jmpr 9) (nop)
 (lea 9 (pcrel 2))
 (b eq 1) (b ne 2) (b ra 2) (bsr 1) (b lo 1) (b hi 2)
 (rt call 49556) (rt ra 49556)
 (label 2))
"""

ASM_V2 = """
L1:     MOV r1, r2
        MOV r1, #5
        MOV r1, #-1
        MOV r1, #-16
        MOV r1, #100
        CMP r9, #21
        CMP r9, #5
        MOV r1, #-536
        MOV r1, #40000
        MOV r1, #65536
        MOV r1, #1193046
        MOV r3, [sp + 8]
        MOV r3, [sp + 60]
        MOV r3, [sp + 64]
        MOV r3, [r14 + 8]
        MOV r1, [r1 - 1]
        MOV r1, [r1 + 3]
        MOV r1, [r2]
        MOV [r3 - 1], r4
        PUSH r1
        POP r1
        MOV [r14]+, r3
        LEA r1, [r14 - 7]
        LEA r1, [r14 + 8]
        LEA r1, [sp + 8]
        MOV r1, r2
        MOV r9, byte [r1 - 3]
        ADD r1, r3
        SUB r1, #2
        CMP r1, r13
        AND r9, #1
        OR r9, r3
        XOR r1, r4
        CMP r14, [260]
        MOV r1, [1688]
        MOV [1688], r1
        MOV r1, [r1 + r3*2 + 5]
        MOV [r1 + r3*2 + 5], r4
        MOVS r1, [r2]
        CLR [r1 + 4]
        TST r1, #1
        TST r1, r2
        TTST r1, r3
        TADD r1, r3
        TSUB r1, r3
        TCMP r1, r3
        TMOV r9, r1
        JMP [r1 + 1]
        CALL [r1 + 1]
        JMP [sp]+
        NEG r1, r1
        INC r2, r3
        SXH r1, r2
        ASR r1, #1
        LSR r9, #7
        LSL r1, #20
        LSL r1, r5
        MULS r1, r3
        TST r1, r2
        DIVS r1, r2
        SAVE r3-r5
        RESTORE r3-r8
        RET
        JMP r9
        NOP
        LEA r9, [pc + L2]
        BEQ L1
        BNE L2
        BRA L2
        BSR L1
        BLO L1
        BHI L2
        CALL 49556
        JMP 49556
L2:
"""

BASE = 0x10420


def lisp(text, isa="v1b"):
    """The reference interpreter's output for the compiler, then text."""
    return reference.run(b"(define cc:*options* '())\n" + machine.compiler_source(isa) + text.encode())


class Encoder(unittest.TestCase):

    def check(self, isa, insns, text):
        out = lisp(f"\n(write (car (cc:asm '{insns} {BASE})))\n", isa).decode()
        got = [int(x) for x in out.strip("()\n").split()]
        img = asm.assemble_text(isas.get(isa), f"        .org {BASE}\n" + text)
        end = max(img.mem) + 1
        want = [img.mem.get(a, 0) | img.mem.get(a + 1, 0) << 8 for a in range(BASE, end, 2)]
        self.assertEqual(len(got), len(want))
        for k, (g, w) in enumerate(zip(got, want)):
            self.assertEqual(g, w, f"parcel {k}: {g:04X}, the assembler's {w:04X}")

    def test_same_as_the_assembler(self):
        self.check("v1b", INSNS, ASM)

    def test_draft_2_same_as_the_assembler(self):
        self.check("v2", INSNS_V2, ASM_V2)

    def test_tagged_register(self):
        # v1bx mode E (isa.md): the assembler doesn't know it
        out = lisp("\n(write (car (cc:asm '((mov 9 (tag 1)) (add 1 (tag 3)) (cmp 1 (tag 0))) 0)))\n")
        self.assertEqual(out.decode().strip(), str([0x19E1, 0x41E3, 0x61E0]).replace(",", "")
                         .replace("[", "(").replace("]", ")"))


PROGRAM = b"""
(define (fib n) (if (< n 2) n (+ (fib (- n 1)) (fib (- n 2)))))
(display (fib 15)) (newline)
(define (counter)
  (let ((n 0)) (lambda () (set! n (+ n 1)) n)))
(define c (counter))
(c) (c)
(display (c)) (newline)
(define (rev l) (let loop ((l l) (r '())) (if (null? l) r (loop (cdr l) (cons (car l) r)))))
(display (rev '(1 2 3 (4 5) "six"))) (newline)
(define v (make-vector 3 0))
(vector-set! v 1 'x)
(display v) (newline)
(display (apply list '(1 2 (3 4)))) (newline)
(display (car 5))
(display (+ 'a 1))
(display (+ 1073741823 1))
(display (vector-ref v 3))
(display (undefined-thing))
(display ((lambda (a b) a) 1))
(display "done") (newline)
"""


class Compiled(unittest.TestCase):

    def run_compiled(self, features, isa="v1b"):
        img = machine.image(features, isa)
        inp = machine.compiler_text(False, features, isa) + PROGRAM
        if isa == "v2":
            m = Machine2(img, inp=inp)
        else:
            m = Machine32(isas.get(machine.isa_name(features)), img, inp=inp)
        m.run(max_cycles=1_000_000_000)
        return bytes(m.dev.out)

    def test_1b(self):
        self.assertEqual(self.run_compiled(()), reference.run(PROGRAM))

    def test_tagged(self):
        self.assertEqual(self.run_compiled(("tagged",)), reference.run(PROGRAM))

    def test_draft_2(self):
        self.assertEqual(self.run_compiled((), "v2"), reference.run(PROGRAM))

    def test_draft_2_tagged(self):
        self.assertEqual(self.run_compiled(("tagged",), "v2"), reference.run(PROGRAM))

    def test_draft_2_no_leaf(self):
        self.assertEqual(self.run_compiled(("no-leaf",), "v2"), reference.run(PROGRAM))


class Interpreted(unittest.TestCase):
    """The draft 2 runtime, interpreted: the language tests that reach its
    corners (the reader, the traps' errors, tail calls in every position)."""

    def test_draft_2(self):
        from heron.studies.lisp import testing
        for name in ("core", "errors", "control", "reader"):
            for features in ((), ("tagged",)):
                with self.subTest(name=name, features=features):
                    path = [p for p in testing.program_paths() if p.endswith(f"/{name}.lisp")][0]
                    r, problem = testing.run_program(path, features, isa="v2")
                    self.assertIsNone(problem)


if __name__ == "__main__":
    unittest.main()
