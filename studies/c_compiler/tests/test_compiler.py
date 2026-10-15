"""The C compiler's parts: preprocessor, diagnostics, IR optimisations and
the code the backends pick for common patterns. (Whole programs are in
test_cc.py.)"""

import re
import unittest

from heron.studies.c_compiler.cc.cpp import Preprocessor
from heron.studies.c_compiler.cc.lex import CompileError
from heron.studies.c_compiler.cc.driver import compile_unit, optimize_unit, build, run_image
from heron.studies.c_compiler.ir.cfg import DomTree, natural_loops


def pp(src):
    toks = Preprocessor().run(src, "t.c")
    return " ".join(t.text for t in toks if t.kind != "eof")


def optimized(src, name="f", isa="v1b"):
    """Function name of src, optimised as the backend for isa gets it."""
    u = compile_unit("t.c", isa, text=src)
    optimize_unit(u, isa, 1, verify_ir=True)
    return u.module.function(name)


def ir_of(src, name="f", isa="v1b"):
    return str(optimized(src, name, isa))


def asm_of(src, isa, func="f"):
    text, _, _ = build_text(src, isa)
    m = re.search(rf"^_{func}:\n(.*?)(?=^_\w+:|\Z)", text, re.S | re.M)
    return m.group(1)


def build_text(src, isa, need_main=False):
    import os
    import tempfile
    from heron.studies.c_compiler.cc.driver import Program
    with tempfile.NamedTemporaryFile("w", suffix=".c", delete=False) as f:
        f.write(src)
        path = f.name
    try:
        return build([path], isa, program=Program(isa, need_main=need_main))
    finally:
        os.unlink(path)


def run_c(src, isa):
    _, img, _ = build_text(src, isa, need_main=True)
    m = run_image(img, isa)
    return bytes(m.dev.out).decode("latin-1")


class Preprocess(unittest.TestCase):
    def test_object_and_function_macros(self):
        self.assertEqual(pp("#define N 4\n#define SQ(x) ((x) * (x))\nSQ(N + 1)"),
                         "( ( 4 + 1 ) * ( 4 + 1 ) )")

    def test_stringify_and_paste(self):
        self.assertEqual(pp('#define S(x) #x\n#define C(a, b) a ## b\nS(a + "b") C(x, 12)'),
                         '"a + \\"b\\"" x12')

    def test_recursion_stops(self):
        # the C standard's example: f(2)(9) is 2*9*g
        self.assertEqual(pp("#define f(a) a*g\n#define g(a) f(a)\nf(2)(9)"), "2 * 9 * g")

    def test_conditionals(self):
        src = """
#define A 2
#if A > 1 && defined(A)
yes1
#elif 1
no
#else
no
#endif
#ifdef B
no
#elif A == 2
yes2
#endif
#if 0
#if 1
no
#endif
#else
yes3
#endif
"""
        self.assertEqual(pp(src), "yes1 yes2 yes3")

    def test_if_arithmetic(self):
        # C's arithmetic in 32-bit long and unsigned long: / and % round
        # toward zero, and a signed operand meeting an unsigned one is
        # converted to unsigned
        src = """
#if -7 / 2 == -3 && -7 % 2 == -1 && 7 % -2 == 1
yes1
#endif
#if -1 > 0u && 0xFFFFFFFF == -1 && (0u - 1) >> 31 == 1 && (1 ? -1 : 0u) > 0
yes2
#endif
#if -16 >> 2 == -4 && 2147483648 > 0 && 0xFFFFFFFF + 1 == 0
yes3
#endif
#if 0 && 1 / 0 || 1 || 1 % 0 || (0 ? 1 / 0 : 1)
yes4
#endif
"""
        self.assertEqual(pp(src), "yes1 yes2 yes3 yes4")
        with self.assertRaises(CompileError):
            pp("#if 1 / 0\n#endif\n")
        with self.assertRaises(CompileError):
            pp("#if 0 || 1 % (2 - 2)\n#endif\n")
        # there's no long long: a constant past 32 bits would wrap silently
        with self.assertRaises(CompileError):
            pp("#if 4294967297 == 1\n#endif\n")

    def test_variadic(self):
        self.assertEqual(pp("#define P(f, ...) g(f, ## __VA_ARGS__)\nP(1) P(1, 2, 3)"),
                         "g ( 1 ) g ( 1 , 2 , 3 )")


class Diagnostics(unittest.TestCase):
    def error(self, src):
        with self.assertRaises(CompileError) as cm:
            compile_unit("t.c", "v1b", text=src)
        return str(cm.exception)

    def test_undeclared(self):
        self.assertIn("t.c:2:", self.error("int f(void) {\n  return x;\n}"))

    def test_type_errors(self):
        self.assertIn("struct", self.error("struct s { int a; } v; int f(void) { return v + 1; }"))
        self.assertIn("lvalue", self.error("int f(void) { 3 = 4; return 0; }"))
        self.assertIn("argument", self.error("int g(int a); int f(void) { return g(1, 2); }"))
        self.assertIn("_Bool", self.error("unsigned _Bool b;"))
        self.assertIn("braced", self.error('_Bool b[] = "ab";'))
        self.assertIn("conflicting", self.error("int a[10];\nint a[20];"))

    def test_unsupported(self):
        self.assertIn("floating", self.error("float x;"))
        self.assertIn("bit field", self.error("struct s { int a : 3; };"))


class Optimizations(unittest.TestCase):
    def test_locals_become_registers(self):
        ir = ir_of("int f(int a, int b) { int t = a; a = b; b = t; return a - b; }")
        self.assertNotIn("load", ir)
        self.assertNotIn("store", ir)

    def test_constant_folding(self):
        ir = ir_of("int f(void) { int x = 6; return x * 7 + (100 >> 2); }")
        self.assertIn("ret 67", ir)

    def test_power_of_two_division(self):
        ir = ir_of("unsigned f(unsigned x) { return x / 8 + x % 16; }")
        self.assertIn("shr", ir)
        self.assertIn("and", ir)
        self.assertNotIn("div", ir)
        self.assertNotIn("rem", ir)

    def test_nonnegative_counter_modulo(self):
        ir = ir_of("int a[32]; int f(void) { int i, s = 0; for (i = 0; i < 100; i++) s += a[(i + 31) % 32]; return s; }")
        self.assertNotIn("rem", ir)
        self.assertNotIn("sar", ir)

    def test_strength_reduction(self):
        ir = ir_of("int a[50]; int f(void) { int i, s = 0; for (i = 0; i < 50; i++) s += a[i]; return s; }")
        self.assertNotIn("shl", ir)
        self.assertIn("ltu", ir)        # the loop tests the pointer

    def test_loop_invariant_motion(self):
        # g[r] (r * 32, a shift) is computed once, before the loop
        f = optimized("int g[8][8]; int f(int r) { int c, s = 0; for (c = 0; c < 8; c++) s += g[r][c]; return s; }")
        loops = natural_loops(DomTree(f))
        self.assertEqual(len(loops), 1)
        body = next(iter(loops.values()))
        self.assertIn("load", [i.op for b in body for i in b.instrs])
        self.assertNotIn("shl", [i.op for b in body for i in b.instrs])
        self.assertIn("shl", [i.op for b in f.blocks if b not in body for i in b.instrs])


class InterpretedIR(unittest.TestCase):
    """The test programs' IR, run by the IR interpreter before and after
    optimisation: checks the optimiser without either backend."""

    def test_programs(self):
        import glob
        import os
        from heron.studies.c_compiler.cc.driver import Program
        from heron.studies.c_compiler.ir.interp import run
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cc")
        for path in sorted(glob.glob(os.path.join(here, "*.c"))):
            name = os.path.basename(path)[:-2]
            with open(os.path.join(here, "expected", name + ".txt"), "rb") as f:
                expected = f.read()
            # draft 2's optimisation also counts loops down (count_down)
            for isa, opt in (("v1b", 0), ("v1b", 1), ("v2", 1)):
                p = Program(isa, opt=opt)
                p.add_file(path)
                p.add_library()
                funcs, data = p.compile()
                with self.subTest(program=name, isa=isa, opt=opt):
                    self.assertEqual(run(funcs, data), expected)


class CodePatterns(unittest.TestCase):
    STRCPY = "void f(char *d, const char *s) { while ((*d++ = *s++) != 0) ; }"

    def test_v1b_autoincrement(self):
        a = asm_of(self.STRCPY, "v1b")
        self.assertIn("byte [r", a)
        self.assertRegex(a, r"MOV\s+r\d+, byte \[r\d+\]\+")
        self.assertRegex(a, r"ST\s+r\d+, byte \[r\d+\]\+")

    def test_v1b_memory_operand(self):
        a = asm_of("int f(int *p, int x) { return x + p[3]; }", "v1b")
        self.assertRegex(a, r"ADD\s+r\d+, \[r\d+ \+ 12\]")

    def test_v1b_indexed_mode(self):
        a = asm_of("int f(int *p, int i) { return p[i]; }", "v1b")
        self.assertRegex(a, r"\[r\d+ \+ r\d+\*4\]")

    def test_v2_autoincrement_and_load_flags(self):
        # the store between the load and the branch leaves the flags alone,
        # so the load sets them: no compare
        a = asm_of(self.STRCPY, "v2")
        self.assertRegex(a, r"MOVS\s+(r\d+), byte \[r\d+\]\+\n\s+MOV\s+byte \[r\d+\]\+, \1\n\s+BNE")
        self.assertNotIn("CMP", a)

    def test_v2_zero_store_is_clr(self):
        a = asm_of("struct s { int a, b; char c; }; void f(struct s *p) { p->a = 0; p->c = 0; }", "v2")
        self.assertRegex(a, r"CLR\s+\[r1\]")
        self.assertRegex(a, r"CLR\s+byte \[r1 \+ 8\]")
        self.assertNotIn("r0", a)

    def test_v2_table_without_base_register(self):
        a = asm_of("int t[100]; int f(int i) { return t[i]; }", "v2")
        self.assertRegex(a, r"MOV\s+r1, \[_t \+ r1\*4\]")

    def test_v2_increment_in_memory(self):
        a = asm_of("int n; unsigned char c[4]; void f(int i) { n++; c[i]--; }", "v2")
        self.assertRegex(a, r"INC\s+\[_n\]")
        self.assertRegex(a, r"DEC\s+byte \[_c \+ r1\]")
        a = asm_of("int n[64]; void f(unsigned char *p) { n[*p]++; }", "v2")
        self.assertRegex(a, r"INC\s+\[_n \+ r\d\*4\]")

    def test_v2_r0_is_allocated(self):
        # eight values live across the loop, all in scratch registers: r1-r7 and r0
        src = ("int f(int *p, int n) { int a = 0, b = 1, c = 2, d = 3, e = 4, g = 5;"
               " while (n--) { a += *p++; b ^= a; c += b; d -= c; e |= d; g += e; }"
               " return a + b + c + d + e + g; }")
        a = asm_of(src, "v2")
        self.assertIn("r0", a)
        self.assertNotIn("SAVE", a)

    def test_v2_dbnz(self):
        # a counter that only counts is counted down to zero, and the loop
        # closes with DBNZ when it's within reach (16 parcels)...
        a = asm_of("unsigned f(unsigned c) { int k; for (k = 0; k < 8; k++)"
                   " c = c & 1 ? c >> 1 ^ 0xA001 : c >> 1; return c; }", "v2")
        self.assertRegex(a, r"MOV\s+(r\d+), #8\n(.*\n)*.*DBNZ \1, \.b\d+")
        self.assertNotIn("CMP", a)
        # ... and with DEC and BNE when it isn't
        body = "; ".join(f"a = a * {k} + (a >> {k})" for k in range(3, 12))
        a = asm_of(f"int f(int a, int n) {{ while (n--) {{ {body}; }} return a; }}", "v2")
        self.assertRegex(a, r"DEC\s+(r\d+), \1\n\s+BNE")
        self.assertNotIn("DBNZ", a)

    def test_three_address_add_uses_lea(self):
        for isa in ("v1a", "v1b", "v2"):
            a = asm_of("int g(int a, int b) { return a - b; }\n"
                       "int f(int x) { return g(x + 1000, x); }", isa)
            self.assertIn("LEA", a)

    def test_v1a_short_immediates(self):
        a = asm_of("int f(int x) { return x == 100 ? 1 : x + 5; }", "v1a")
        self.assertRegex(a, r"ADDI\s+r\d+, 5|LEA\s+r\d+, \[r\d+ \+ 5\]")

    def test_no_frame_for_leaf(self):
        for isa in ("v1b", "v2"):
            a = asm_of("int f(int a, int b) { return a * b + 1; }", isa)
            self.assertNotIn("SAVE", a)
            self.assertNotIn("sp", a)

    def test_jump_table(self):
        src = """int f(int x) { switch (x) { case 0: return 5; case 1: return 7; case 2: return 9;
                 case 3: return 11; case 4: return 2; case 5: return 4; } return 0; }"""
        self.assertIn("JMP  [", asm_of(src, "v1b"))
        self.assertRegex(asm_of(src, "v1a"), r"JMP\s+r\d+")
        self.assertRegex(asm_of(src, "v2"), r"JMP\s+\[pc \+ _f_jt0 \+ r\d+\*4\]")


class Semantics(unittest.TestCase):
    """Small programs whose output doesn't need a reference compiler."""

    def check(self, src, out):
        for isa in ("v1a", "v1b", "v2"):
            self.assertEqual(run_c(src, isa), out, isa)

    def test_char_is_unsigned(self):
        self.check('#include <stdio.h>\nint main(void) { char c = 200; signed char s = 200; '
                   'printf("%d %d %d\\n", c, s, (char)-1 > 0); return 0; }', "200 -56 1\n")

    def test_struct_return_chain(self):
        self.check("""#include <stdio.h>
struct v { int x, y, z; };
static struct v mk(int a) { struct v r; r.x = a; r.y = a * 2; r.z = a * 3; return r; }
static struct v add(struct v a, struct v b) { a.x += b.x; a.y += b.y; a.z += b.z; return a; }
int main(void) { struct v s = add(mk(1), add(mk(2), mk(3))); printf("%d %d %d\\n", s.x, s.y, s.z); return 0; }
""", "6 12 18\n")

    def test_function_pointer_table(self):
        self.check("""#include <stdio.h>
static int inc(int x) { return x + 1; }
static int dbl(int x) { return x * 2; }
static int (*const ops[])(int) = {inc, dbl, inc};
int main(void) { int i, v = 3; for (i = 0; i < 3; i++) v = ops[i](v); printf("%d\\n", v); return 0; }
""", "9\n")

    def test_strength_reduced_value_isnt_an_address(self):
        # k * 7 - 30 becomes a counter of its own, but the loop must still
        # be ended by the address walk, not by comparing that value
        self.check("""#include <stdio.h>
int arr[16];
int main(void) { int k; for (k = 0; k < 16; k++) arr[k] = k * 7 - 30;
printf("%d %d\\n", arr[4], arr[15]); return 0; }""", "-2 75\n")

    def test_countdown_loops(self):
        self.check("""#include <stdio.h>
int main(void) { int n = 5, s = 0; unsigned u = 3; while (n--) s += n; while (u--) s += 100;
printf("%d %d %u\\n", s, n, u); return 0; }""", "310 -1 4294967295\n")

    def test_counted_loops(self):
        # the loop shapes ir.passes.count_down turns into counts down to zero
        self.check("""#include <stdio.h>
volatile int sink;
static int up(void) { int i, n = 0; for (i = 0; i < 8; i++) n += 3; return n; }
static int down(void) { int i, n = 0; for (i = 10; i > 0; i--) n++; return n; }
static int le(void) { int i, n = 0; for (i = -3; i <= 4; i++) n++; return n; }
static int ge(void) { unsigned i; int n = 0; for (i = 9; i >= 2; i--) n++; return n; }
static int ne(int a, int b) { int i, n = 0; for (i = a; i != b; i++) n++; return n; }
static int dowhile(int k) { int n = 0; do n++; while (--k); return n; }
static int once(void) { int i = 5, n = 0; do n++; while (++i < 3); return n; }
static int wn(int k) { int n = 0; while (k--) n += 2; return n; }
static unsigned wrap(void) { unsigned i, n = 0; for (i = 0xFFFFFFF0u; i != 0x10; i++) n++; return n; }
int main(void) { printf("%d %d %d %d %d %d %d\\n", up(), down(), le(), ge(), ne(3, 11), ne(-5, -2), dowhile(6));
printf("%d %d %d %u\\n", once(), wn(7), wn(0), wrap()); return 0; }""", "24 10 8 8 8 3 6\n1 14 0 32\n")

    def test_rotates(self):
        self.check("""#include <stdio.h>
static unsigned rol(unsigned x, int n) { return x << n | x >> (32 - n); }
int main(void) { unsigned x = 0x80000001u; printf("%x %x %x\\n", rol(x, 1), x >> 4 | x << 28, rol(x, 31)); return 0; }""",
                   "3 18000000 c0000000\n")

    def test_extern_array_completed_by_definition(self):
        self.check("""#include <stdio.h>
extern int table[];
int table[100];
int other[4];
int main(void) { int i; other[0] = 7; for (i = 0; i < 4; i++) table[i] = 99;
printf("%d %d\\n", other[0], (int)sizeof(table)); return 0; }""", "7 400\n")

    def test_jump_table_past_32k(self):
        # The table sits in its function's section: 1b and 2 reach it
        # PC-relative, 1a with a 32-bit displacement, wherever that goes.
        from heron.infra import link
        from heron.studies.c_compiler.cc import driver
        src = """#include <stdio.h>
extern void pad(void) __asm__("pad");
volatile int zero;
int f(int x) { switch (x) { case 0: return 5; case 1: return 7; case 2: return 9;
               case 3: return 11; case 4: return 2; } return 0; }
int main(void) { if (zero) pad(); printf("%d %d\\n", f(3), f(9)); return 0; }
"""
        pad = "        .global pad\n        .section .text.pad\npad:    .space 40000\n"
        for isa in ("v1a", "v1b", "v2"):
            objs = [driver.start_object(isa), driver.assemble(isa, pad, "pad.o"),
                    driver.assemble(isa, driver.unit_assembly(compile_unit("t.c", isa, text=src), isa), "t.o")]
            img = link.link(objs, [driver.library(isa)[0]], isa)
            self.assertGreater(img.symbols["_f"], 0x8000, isa)
            self.assertEqual(bytes(run_image(img, isa).dev.out), b"11 0\n", isa)

    def test_licm_out_of_a_new_preheader(self):
        # The inner loop's new preheader lies inside the outer loop: the
        # sext8 hoisted into it must move out with the multiply that uses it
        # (optimized() verifies the IR after every pass)
        src = """int f(int n, int c, int m) { int s = 0, i, k, t = 0;
for (i = 0; i < n; i++) { if (m > i) { k = 0; do { t = (signed char)c; s += k; k++; } while (k < m); s += t * 3; } }
return s; }"""
        optimized(src)
        self.check("#include <stdio.h>\n" + src + '\nint main(void) { printf("%d %d\\n", f(5, 200, 3), f(4, -7, 2)); '
                   "return 0; }", "-495 -40\n")

    def test_spill_pressure(self):
        # more live values than registers
        body = "".join(f"int v{i} = x * {i + 3};\n" for i in range(24))
        total = " + ".join(f"v{i} * v{(i + 5) % 24}" for i in range(24))
        expect = sum((7 * (i + 3)) * (7 * ((i + 5) % 24 + 3)) for i in range(24))
        self.check(f"#include <stdio.h>\nint f(int x) {{ {body} return {total}; }}\n"
                   f"int main(void) {{ printf(\"%d\\n\", f(7)); return 0; }}", f"{expect}\n")


if __name__ == "__main__":
    unittest.main()
