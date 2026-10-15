"""C and assembly linked together, through the object files and linker in
infra and the draft 1 and 2 assemblers (the v1_isa and v2_isa studies test
those on their own)."""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from heron.infra import asm, obj as O
from heron.studies.v1_isa import testing
from heron.studies.v2_isa import testing as testing_v2


def assemble(isa, text, name="t.s"):
    from heron.infra import isas
    a = asm.Assembler(isas.get(isa), relocatable=True)
    a.load(name, text=text)
    return a.assemble_object(name)


INTEROP_C = r"""
extern void print_u32(unsigned n) __asm__("print_u32");
extern int asm_sum(int *p, int n) __asm__("asm_sum");
extern int twice(int x) __asm__("twice");
extern int scale;

int twice(int x) { return 2 * x + scale; }

int main(void)
{
    int a[4] = {1, 2, 3, 4};
    print_u32(asm_sum(a, 4));
    putchar('\n');
    return 0;
}
"""

INTEROP_S = {
    "v1a": """
        .global asm_sum, _scale
asm_sum:
        SAVE r8-r10
        MOV  r8, r1
        MOV  r9, r2
        MVI  r10, 0
.loop:  LD   r1, [r8]
        ADDI r8, 4
        CALL twice
        ADD  r10, r1
        DEC  r9, r9
        BNE  .loop
        MOV  r1, r10
        RESTORE r8-r10
        RET
        .data
_scale: .word 5
""",
    "v1b": """
        .global asm_sum, _scale
asm_sum:
        SAVE r8-r10
        MOV  r8, r1
        MOV  r9, r2
        MOV  r10, #0
.loop:  MOV  r1, [r8]+
        CALL twice
        ADD  r10, r1
        DEC  r9, r9
        BNE  .loop
        MOV  r1, r10
        RESTORE r8-r10
        RET
        .data
_scale: .word 5
""",
    "v2": """
        .global asm_sum, _scale
asm_sum:
        SAVE r7-r10             ; r7: the return address, which CALL twice overwrites
        MOV  r8, r1
        MOV  r9, r2
        CLR  r10
.loop:  MOV  r1, [r8]+
        CALL twice
        ADD  r10, r1
        DBNZ r9, .loop
        MOV  r1, r10
        RESTORE r7-r10
        RET
        .data
_scale: .word 5
"""}


def print_routines(isa):
    """The hand-written programs' print routines."""
    d = testing_v2.PROGRAMS if isa == "v2" else testing.program_dir(isa)
    return os.path.join(d, "lib", "print.s")


class CAndAssembly(unittest.TestCase):
    def test_interop(self):
        from heron.studies.c_compiler.cc import driver
        from heron.infra.objtools import assemble_object
        for isa in ("v1a", "v1b", "v2"):
            with self.subTest(isa=isa):
                p = driver.Program(isa)
                p.add_file("main.c", text=INTEROP_C)
                p.add_object(assemble(isa, INTEROP_S[isa], "sum.s"))
                p.add_object(assemble_object(isa, print_routines(isa)))
                p.add_library()
                img = p.link()
                m = driver.run_image(img, isa)
                self.assertEqual(bytes(m.dev.out), b"40\n")     # 2 * (1 + 2 + 3 + 4) + 4 * 5

    def test_command_line(self):
        from heron.studies.c_compiler.cli import main as cc_main
        from heron.studies.v1_isa.cli import main
        with tempfile.TemporaryDirectory() as d:
            c = os.path.join(d, "main.c")
            s = os.path.join(d, "sum.s")
            with open(c, "w") as f:
                f.write(INTEROP_C)
            with open(s, "w") as f:
                f.write(INTEROP_S["v1b"])
            print_s = os.path.join(testing.program_dir("v1b"), "lib", "print.s")
            out = io.TextIOWrapper(io.BytesIO(), encoding="latin-1")
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                self.assertEqual(cc_main(["cc", "--isa", "v1b", "-c", c, "-o", os.path.join(d, "main.o")]), 0)
                self.assertEqual(main(["--isa", "v1b", "asm", "-c", s]), 0)
                self.assertEqual(main(["--isa", "v1b", "asm", "-c", print_s, "-o", os.path.join(d, "print.o")]), 0)
                self.assertEqual(cc_main(["cc", "--isa", "v1b", os.path.join(d, "main.o"),
                                       os.path.join(d, "sum.o"), os.path.join(d, "print.o"),
                                       "-o", os.path.join(d, "prog.out")]), 0)
                self.assertEqual(main(["run", os.path.join(d, "prog.out")]), 0)
                self.assertEqual(main(["objdump", "-d", os.path.join(d, "main.o")]), 0)
            out.flush()
            text = out.buffer.getvalue().decode("latin-1")
            self.assertIn("40\n", text)
            self.assertIn("pc16h", text)

    def test_command_line_v2(self):
        from heron.studies.c_compiler.cli import main as cc_main
        from heron.studies.v2_isa.cli import main
        with tempfile.TemporaryDirectory() as d:
            c = os.path.join(d, "main.c")
            s = os.path.join(d, "sum.s")
            with open(c, "w") as f:
                f.write(INTEROP_C)
            with open(s, "w") as f:
                f.write(INTEROP_S["v2"])
            out = io.TextIOWrapper(io.BytesIO(), encoding="latin-1")
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                self.assertEqual(cc_main(["cc", "--isa", "v2", "-c", c, "-o", os.path.join(d, "main.o")]), 0)
                self.assertEqual(main(["asm", "-c", s]), 0)
                self.assertEqual(main(["asm", "-c", print_routines("v2"), "-o", os.path.join(d, "print.o")]), 0)
                self.assertEqual(cc_main(["cc", "--isa", "v2", os.path.join(d, "main.o"),
                                       os.path.join(d, "sum.o"), os.path.join(d, "print.o"),
                                       "-o", os.path.join(d, "prog.out")]), 0)
                self.assertEqual(main(["run", os.path.join(d, "prog.out")]), 0)
                self.assertEqual(cc_main(["cc", "--isa", "v2", c, s, print_routines("v2"), "--run"]), 0)
            out.flush()
            self.assertEqual(out.buffer.getvalue().decode("latin-1"), "40\n40\n")


class CommandLine(unittest.TestCase):
    def test_cc_defaults_to_v1b(self):
        with tempfile.TemporaryDirectory() as d:
            c, o = os.path.join(d, "t.c"), os.path.join(d, "t.o")
            with open(c, "w") as f:
                f.write("int main() { return 0; }\n")
            from heron.studies.c_compiler.cli import main as cc_main
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(cc_main(["cc", "-c", c, "-o", o]), 0)
            self.assertEqual(O.read_object(o).isa, "v1b")


if __name__ == "__main__":
    unittest.main()
