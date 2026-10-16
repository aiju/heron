"""The microassembler against the simulator: the same fields, the same
74181, and the mistakes it refuses."""

import unittest

from heron import native
from heron.studies.iop import uasm


def one(line, pre=""):
    """The word for one line (at address 0)."""
    mc = uasm.assemble([("t", pre + "\n" + line + "\nhere: nop\n")])
    return mc.words[0]


class Encoding(unittest.TestCase):
    def test_fields(self):
        w = one("ip, X <- ip + 1")
        self.assertEqual(native.iop.disassemble(w), "reg As0+c r0 | wb | ld X")
        w = one("F <- [X] | X <- F | dispatch here")
        self.assertEqual(native.iop.disassemble(w), "[X] LsF r0 | ld X | if F15 F else 0001")
        w = one("i0 <- i0 + AC | AB <- io | wr.h AH0 | if lc goto here")
        self.assertEqual(native.iop.disassemble(w), "reg As9 r3 | wb | wr.h AH0 | AB<-dev | if lc 0001")
        self.assertEqual(one("nop"), 0)
        self.assertEqual(native.iop.disassemble(one("ip <- F")), "reg hold r0 | wb")

    def test_alu(self):
        """Every spelling is the function the chip computes."""
        cases = [(0x1234, 0x0F0F), (0, 0), (0xFFFF, 1), (0x8000, 0x8000)]
        model = {
            "A": lambda a, b: a, "A+1": lambda a, b: a + 1, "A-1": lambda a, b: a - 1,
            "A+B": lambda a, b: a + b, "A-B": lambda a, b: a - b, "A+A": lambda a, b: 2 * a,
            "A&B": lambda a, b: a & b, "A|B": lambda a, b: a | b, "A^B": lambda a, b: a ^ b,
            "~A": lambda a, b: ~a, "B": lambda a, b: b, "~B": lambda a, b: ~b, "0": lambda a, b: 0,
            "-1": lambda a, b: -1, "A&~B": lambda a, b: a & ~b, "(A&B)-1": lambda a, b: (a & b) - 1,
            "(A|~B)+1": lambda a, b: (a | ~b) + 1, "~(A^B)": lambda a, b: ~(a ^ b),
            "A-B-1": lambda a, b: a - b - 1, "A+B+1": lambda a, b: a + b + 1,
        }
        for spelling, f in model.items():
            s, m, cin = uasm.FUNCTIONS[spelling]
            for a, b in cases:
                self.assertEqual(native.iop.alu(s, bool(m), bool(cin), a, b)[0], f(a, b) & 0xFFFF,
                                 f"{spelling} on {a:#x}, {b:#x}")

    def test_or_inside_an_expression(self):
        self.assertEqual(uasm.clauses("[X] <- [X] | AC | goto x"), ["[X] <- [X] | AC", "goto x"])


class Errors(unittest.TestCase):
    def bad(self, line, what):
        with self.assertRaises(uasm.AsmError) as e:
            one(line)
        self.assertIn(what, str(e.exception))

    def test_k_twice(self):
        self.bad("F <- #5 + AC | goto here", "K is needed for both")

    def test_reg_and_device(self):
        self.bad("t0 <- t0 + AC | AB <- io", "can't share REG")
        self.bad("F <- ip | pg1 <- F", "can't share REG")

    def test_write_back_to_another_register(self):
        self.bad("ip <- sp + 1", "two registers")
        self.bad("ip <- [X] + 1", "the SRAM's address is X")

    def test_not_a_74181_function(self):
        self.bad("F <- ip + sp", "two sources")
        self.bad("F <- ip * AC", "can't do")
