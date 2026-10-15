"""v1bl, draft 1b with a link register: the simulator, the microcode and
the RTL model, the C compiler's backend, the ported programs and the
estimator against what a port measures."""

import os
import unittest

import heron.studies.link_register  # noqa: F401  (registers v1bl)
from heron.infra import asm as asmcore, isas
from heron.studies.v1_isa.sim32 import Machine32

CALLS = """
        .org 0
        JMP  start
        .org 0x18
start:  LI   sp, #0x100000
        MOV  r9, #tab
        MOV  r10, #0
        CALL [r9]
        CALL [r9 + 4]
        CALL [r9]+
        CALL [r9]+
        CALL -[r9]
        MOV  r2, #tab
        MOV  r3, #1
        CALL [r2 + r3*4]
        CALL [tab]
        CALL [pc + tab]
        CALL #f
        MOV  r9, #f
        CALL r9
        BSR  f
        CALL f
        BSR  g
        ST   r10, [0xFFFFFF00]
        HALT
f:      ADD  r10, #1
        RET
g:      PUSH r7                 ; v1bl: a routine that calls pushes r7...
        BSR  f
        JMP  [sp]+              ; ...and returns popping it
        .align 4
tab:    .word f, f, f
"""


def run(isa, src):
    mod = isas.get(isa)
    img = asmcore.assemble_text(mod, src)
    return img, Machine32(mod, img).run(1_000_000)


class Simulator(unittest.TestCase):
    def test_calls_leave_the_return_address_in_r7(self):
        img, m = run("v1bl", CALLS)
        self.assertEqual(bytes(m.dev.out), bytes([13]))
        self.assertEqual(m.r[15], 0x100000)             # nothing left on the stack
        keys = {k[2] for (_pc, k), _n in m.pc_keys.items()}
        self.assertIn("link", keys)
        self.assertIn("linkm", keys)
        self.assertNotIn("call", keys)

    def test_1b_still_pushes(self):
        src = CALLS.replace("""g:      PUSH r7                 ; v1bl: a routine that calls pushes r7...
        BSR  f
        JMP  [sp]+              ; ...and returns popping it""", """g:      BSR  f
        RET""")
        _img, m = run("v1b", src)
        self.assertEqual(bytes(m.dev.out), bytes([13]))
        self.assertEqual(m.r[15], 0x100000)


class Microcode(unittest.TestCase):
    def test_cycles(self):
        from heron.studies.link_register import hw
        self.assertEqual(hw.cycles((1, 0, "call", "rel", 0)), 5)    # BSR, pushing
        self.assertEqual(hw.cycles((1, 0, "link", "rel", 0)), 3)    # BSR, to r7
        self.assertEqual(hw.cycles((1, 0, "ret")), 5)
        self.assertEqual(hw.cycles((1, 0, "jmp", "reg", 0)), 2)     # v1bl's RET
        self.assertEqual(hw.cycles((1, 0, "link", "reg", 0)), 3)    # CALL r9
        self.assertEqual(hw.cycles((2, 0, "linkm", "rd", 0)), 6)    # CALL [r9 + 8]

    def test_rtl_runs_every_call_mode(self):
        from heron.studies.v1b_hw import ucode as uc
        from heron.studies.v1b_hw.rtl import RTL
        img, m = run("v1bl", CALLS)
        r = RTL(img, mc=uc.built(True))
        r.run(1_000_000)
        self.assertEqual(r.out, bytes(m.dev.out))
        self.assertEqual(list(r.rf[:16]), list(m.r))


class Compiler(unittest.TestCase):
    SRC = r"""
#include <stdio.h>
#include <stdarg.h>
static int leaf(int x) { return x * 3 + 1; }
static int nosave(int x) { return leaf(x) + 1; }
static int saves(int x) { int a = leaf(x); int b = leaf(a); return a + b; }
static int tail(int x) { return leaf(x + 2); }
static int sum(int n, ...)
{
    va_list ap;
    int s = 0;
    va_start(ap, n);
    while (n--)
        s += va_arg(ap, int);
    va_end(ap);
    return s;
}
int main(void)
{
    printf("%d %d %d %d %d\n", leaf(1), nosave(2), saves(3), tail(4), sum(3, 5, 6, 7));
    return 0;
}
"""

    def test_v1bl_backend(self):
        from heron.studies.c_compiler.cc import driver
        u = driver.compile_unit("t.c", "v1bl", text=self.SRC)
        asm = driver.unit_assembly(u, "v1bl")
        body = lambda name: asm.split(f"_{name}:")[1].split("\n\n")[0]
        self.assertNotIn("r7", body("leaf"))                   # a leaf returns through r7
        self.assertIn("ST   r7, -[sp]", body("nosave"))         # no callee-saved: a push
        self.assertIn("JMP  [sp]+", body("nosave"))
        self.assertIn("SAVE r7-r", body("saves"))               # with them
        self.assertNotIn("r7", body("tail"))                    # only a tail call: a leaf
        p = driver.Program("v1bl")
        p.add_file("t.c", text=self.SRC)
        p.add_library()
        img = p.link()
        m = driver.run_image(img, "v1bl")
        self.assertEqual(bytes(m.dev.out), b"4 8 41 19 18\n")


class Programs(unittest.TestCase):
    def test_ported_suite(self):
        from heron.studies.link_register import measure
        from heron.studies.v1_isa import testing
        for name in ("fib", "monitor", "lines", "sort"):
            path = [p for p in measure.asm_paths("v1bl") if p.endswith(f"/{name}.s")][0]
            r = testing.run_program(path, "v1bl")
            self.assertTrue(r["ok"], f"{name}: {r['error']}")

    def test_graphics_kernels_edit(self):
        from heron.studies.link_register import graphics
        for name in graphics.EDITS:
            self.assertIn("SAVE r7-", graphics.kernel(name))


class Estimator(unittest.TestCase):
    def test_against_the_port(self):
        """On fib and queens the estimate is what the port measures."""
        from heron.infra.programs import metadata
        from heron.studies.link_register import estimate, hw, measure
        from heron.studies.v1_isa import testing
        for name in ("fib", "queens"):
            got = {}
            for isa in ("v1b", "v1bl"):
                path = [p for p in measure.asm_paths(isa) if p.endswith(f"/{name}.s")][0]
                mod = isas.get(isa)
                m = Machine32(mod, asmcore.assemble_file(mod, path), inp=metadata(path)["input"])
                if isa == "v1b":
                    counts = estimate.trace(m)
                    est = sum(estimate.delta(counts).values())
                    m = Machine32(mod, asmcore.assemble_file(mod, path), inp=metadata(path)["input"])
                m.run(max_cycles=metadata(path)["max-cycles"])
                got[isa] = hw.total(m.pc_keys)
            self.assertAlmostEqual(est / got["v1b"], got["v1bl"] / got["v1b"] - 1, delta=0.001)


class Egret(unittest.TestCase):
    def test_fib_on_each_build(self):
        from heron.studies.link_register import egret
        from heron.studies.egret.programs import catalogue
        p = catalogue.program("fib")
        for v in egret.VARIANTS:
            m = egret.machine("v1bl", v, p.source, p.input)
            self.assertEqual(bytes(m.dev.out), p.expected(), v)


if __name__ == "__main__":
    unittest.main()
