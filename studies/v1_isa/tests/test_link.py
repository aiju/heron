"""Object files, the assembler's object mode and the linker, for the draft 1
ISAs. (C and assembly linked together is tested in the c_compiler study.)"""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from heron.infra import asm, isas, obj as O, link as L
from heron.studies.v1_isa import testing
from heron.studies.v1_isa.sim32 import Machine32

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

START = """
        .org 0
        JMP  __start
        .org 0x18
__start: LI  sp, #0x100000
        CALL main
        HALT
"""


def assemble(isa, text, name="t.s"):
    a = asm.Assembler(isas.get(isa), relocatable=True)
    a.load(name, text=text)
    return a.assemble_object(name)


def relocs(o):
    """[(section name, offset, kind, symbol, addend)]"""
    return [(o.sections[r.section - 1].name, r.offset, O.RELOC_NAMES[r.kind],
             o.symbols[r.symbol].name, r.addend) for r in o.relocs]


def run(isa, objects, libraries=(), **kw):
    img = L.link(objects, libraries, isa, **kw)
    m = Machine32(isas.get(isa), img)
    m.run(max_cycles=1_000_000)
    return m, img


class Format(unittest.TestCase):
    def test_round_trip(self):
        o = assemble("v1a", "        .global f\nf: LD r1, [x]\n RET\n .data\nx: .word f, 3\n .bss\nb: .space 8\n")
        o2 = O.ObjectFile.from_bytes(o.to_bytes(), "t.o")
        self.assertEqual(o2.to_bytes(), o.to_bytes())
        self.assertEqual([s.name for s in o2.sections], [".text", ".data", ".bss"])
        self.assertTrue(o2.sections[2].nobits)
        self.assertEqual(o2.sections[2].size, 8)
        lib = O.archive_bytes([("a.o", o), ("b.o", o2)])
        with tempfile.NamedTemporaryFile(suffix=".a", delete=False) as f:
            f.write(lib)
        try:
            members = O.read_archive(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual([n for n, _ in members], ["a.o", "b.o"])
        self.assertEqual(members[1][1].to_bytes(), o.to_bytes())

    def test_truncated(self):
        o = assemble("v1a", "        .global f\nf: LD r1, [x]\n RET\n .data\nx: .word f, 3\n")
        obj, lib = o.to_bytes(), O.archive_bytes([("a.o", o), ("b.o", o)])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t")
            for data, read in ((obj, O.read_object), (lib, O.read_archive)):
                for n in range(len(data)):
                    with open(path, "wb") as f:
                        f.write(data[:n])
                    with self.assertRaises(O.ObjError, msg=f"{read.__name__}, {n} bytes"):
                        read(path)
                # and the commands say so
                with open(path, "wb") as f:
                    f.write(data[:-1])
                cmds = [("objdump", path), ("ld", path), ("run", path)]
                if read is O.read_archive:
                    cmds.append(("ar", "-t", path))
                for cmd in cmds:
                    rc, _, err = cli(*cmd)
                    self.assertEqual(rc, 1, cmd)
                    self.assertRegex(err, r"^error: .*: truncated (object file|library)\n", cmd)

    def test_relocation_ranges(self):
        self.assertEqual(O.reloc_value(O.ABS16S, 0x7FFC, 2, 0), b"\xfe\x7f")
        self.assertEqual(O.reloc_value(O.ABS16S, 0xFFFFFF00, 0, 0), b"\x00\xff")   # the I/O page
        with self.assertRaises(ValueError):
            O.reloc_value(O.ABS16S, 0x8000, 0, 0)
        self.assertEqual(O.reloc_value(O.ABS16, 0xFFFF, 0, 0), b"\xff\xff")
        self.assertEqual(O.reloc_value(O.PC16H, 0x100, -2, 0x80), (0x7E // 2).to_bytes(2, "little"))
        with self.assertRaises(ValueError):
            O.reloc_value(O.PC16H, 0x101, 0, 0)
        with self.assertRaises(ValueError):
            O.reloc_value(O.PC16, 0x10000, 0, 0)
        self.assertEqual(O.reloc_value(O.ABS32, 0x12345678, 1, 0), bytes.fromhex("79563412"))


class Assembler(unittest.TestCase):
    SRC = """
        .global main
main:   LEA  r1, msg
        LD   r2, [count]
        LD   r3, [big + 8]
        LI   r4, #msg + 2
        BSR  puts
        BRA  .done
.done:  CALL helper
        RET
helper: RET
        .far big
        .data
count:  .word 5, msg, helper + 2
msg:    .asciz "hi"
"""

    def test_v1a_relocations(self):
        o = assemble("v1a", self.SRC)
        self.assertEqual(relocs(o), [
            (".text", 2, "pc16", "msg", -2),          # PC-relative LEA
            (".text", 6, "abs16s", "count", 0),       # [count]: near, 16 bits
            (".text", 10, "abs32", "big", 8),         # .far: 32 bits
            (".text", 16, "abs16s", "msg", 2),
            (".text", 20, "pc16h", "puts", -2),       # external call
            (".data", 4, "abs32", "msg", 0),
            (".data", 8, "abs32", "helper", 2)])
        # branches inside the section need no relocation, and stay short
        self.assertEqual([s.name for s in o.symbols if not s.defined], ["big", "puts"])

    def test_v1b_relocations(self):
        src = self.SRC.replace("LD   r2, [count]", "MOV  r2, [count]")
        src = src.replace("LD   r3, [big + 8]", "ADD  r3, [big + 8]")
        src = src.replace("LEA  r1, msg", "LEA  r1, [pc + msg]")
        o = assemble("v1b", src + "        .text\n        MOV r5, byte [r6 + msg]\n        CALL [count]\n")
        kinds = [(r[2], r[3], r[4]) for r in relocs(o)]
        self.assertEqual(kinds, [
            ("pc16", "msg", -2), ("abs16s", "count", 0), ("abs32", "big", 8),
            ("abs16s", "msg", 2), ("pc16h", "puts", -2),
            ("abs32", "msg", 0), ("abs32", "helper", 2),
            ("abs16s", "msg", 0), ("abs16s", "count", 0)])

    def test_constants_and_absolute_sections_need_no_relocations(self):
        o = assemble("v1a", START + "main: LI r1, #0x12345\n LD r2, [0xFFFFFF00]\n RET\n")
        self.assertEqual(o.relocs, [])
        self.assertTrue(all(s.absolute for s in o.sections))

    def test_errors(self):
        def err(src, isa="v1a"):
            with self.assertRaises(asm.AsmError) as cm:
                assemble(isa, src)
            return str(cm.exception)
        self.assertIn("can't hold", err("        MVI r1, x\n"))          # 8 bits
        self.assertIn("can't hold", err("        MOV r1, [r2 + r3*4 + x]\n", "v1b"))   # 8 bits
        self.assertIn(".byte needs a constant", err("        .byte x\n"))
        self.assertIn("isn't defined here", err("        .global nowhere\n"))
        self.assertIn("only zeros", err("        .bss\n        .word 1\n"))
        self.assertIn("different sections", err("a: .word 0\n .data\nb: .word a - b\n"))

    def test_exports(self):
        o = assemble("v1a", "a: RET\nb: RET\n.c: RET\n")
        self.assertEqual({s.name for s in o.symbols if s.is_global}, {"a", "b"})
        o = assemble("v1a", "        .global b\na: RET\nb: RET\n")
        self.assertEqual({s.name for s in o.symbols if s.is_global}, {"b"})
        o = assemble("v1a", "        .local a\na: RET\nb: RET\n")
        self.assertEqual({s.name for s in o.symbols if s.is_global}, {"b"})


class Linker(unittest.TestCase):
    def test_two_files(self):
        for isa, load in (("v1a", "LD   r2, [count]"), ("v1b", "MOV  r2, [count]")):
            start = assemble(isa, START, "start.s")
            a = assemble(isa, f"""
main:   {load}
        BSR  bump
        LEA  r3, [table + 4]
        RET
        .data
table:  .word 10, 20
""", "a.s")
            b = assemble(isa, """
        .global count, bump
bump:   ADD  r2, r2
        RET
        .data
count:  .word 21
""", "b.s")
            m, img = run(isa, [start, a, b])
            with self.subTest(isa=isa):
                self.assertEqual(m.r[2], 42)
                self.assertEqual(m.r[3], img.symbols["table"] + 4)
                # near data comes first, then code
                self.assertLess(img.symbols["count"], img.symbols["bump"])

    def test_errors(self):
        start = assemble("v1a", START)
        with self.assertRaises(L.LinkError) as cm:
            L.link([start, assemble("v1a", "main: BSR nothere\n RET\n")])
        self.assertIn("undefined symbol nothere", str(cm.exception))
        with self.assertRaises(L.LinkError) as cm:
            L.link([start, assemble("v1a", "main: RET\n"), assemble("v1a", "main: RET\n")])
        self.assertIn("main is defined in both", str(cm.exception))
        with self.assertRaises(L.LinkError) as cm:
            L.link([start, assemble("v1a", ".org 0x1A\nmain: RET\n")])
        self.assertIn("overlaps", str(cm.exception))

    def test_near_data_out_of_range(self):
        src = "main: LD r1, [x]\n RET\n .data\nx: .word 1\n"
        start = assemble("v1a", START)
        with self.assertRaises(L.LinkError) as cm:
            L.link([start, assemble("v1a", src)], base=0x9000)
        self.assertIn(".far", str(cm.exception))
        m, img = run("v1a", [start, assemble("v1a", "        .far x\n" + src)], base=0x9000)
        self.assertEqual(m.r[1], 1)
        self.assertGreater(img.symbols["x"], 0x8000)

    def test_gc_and_libraries(self):
        start = assemble("v1a", START)
        prog = assemble("v1a", "main: BSR f\n BSR g\n RET\n")
        lib_f = assemble("v1a", "f: MVI r1, 1\n RET\nunused: RET\n .section .text.h\nh: MVI r9, 9\n RET\n")
        lib_g = assemble("v1a", "g: MVI r2, 2\n RET\n")
        lib_x = assemble("v1a", "x: RET\n")
        lib = [("f.o", lib_f), ("g.o", lib_g), ("x.o", lib_x)]
        m, img = run("v1a", [start, prog], [lib])
        self.assertEqual((m.r[1], m.r[2]), (1, 2))
        self.assertNotIn("x", img.symbols)          # x.o isn't loaded
        self.assertNotIn("h", img.symbols)          # .text.h isn't used
        # the program's own definition replaces the library's
        own_g = assemble("v1a", "g: MVI r2, 7\n RET\n")
        m, img = run("v1a", [start, prog, own_g], [lib])
        self.assertEqual((m.r[1], m.r[2]), (1, 7))

    def test_executable_round_trip(self):
        start = assemble("v1b", START)
        prog = assemble("v1b", "main: MOV r1, [x]\n RET\n .bss\nx: .space 4\n .data\ny: .word x\n")
        img = L.link([start, prog])
        exe = O.ObjectFile.from_bytes(img.obj.to_bytes())
        self.assertTrue(exe.executable)
        img2 = L.load_executable(exe)
        self.assertEqual(img2.mem, img.mem)
        self.assertEqual(img2.symbols["main"], img.symbols["main"])
        self.assertEqual(img2.code_bytes(), img.code_bytes())


class HandWrittenPrograms(unittest.TestCase):
    """Every draft 1 program, assembled as a relocatable object file (its
    start code and vectors linked in separately), still works."""

    def test_relocatable_programs(self):
        for isa in ("v1a", "v1b"):
            d = testing.program_dir(isa)
            with open(os.path.join(d, "lib", "start.s")) as f:
                start = assemble(isa, f.read(), "start.s")
            for path in testing.program_paths(None, isa):
                with open(path) as f:
                    text = f.read()
                if '.include "lib/start.s"' not in text:
                    continue
                text = text.replace('.include "lib/start.s"', "")
                name = os.path.basename(path)[:-2]
                with self.subTest(isa=isa, program=name):
                    a = asm.Assembler(isas.get(isa), relocatable=True)
                    a.load(path, text=text)
                    o = a.assemble_object(name + ".o")
                    if name != "hello":
                        self.assertTrue(o.relocs)
                    img = L.link([start, o])
                    meta = testing.metadata(path)
                    m = Machine32(isas.get(isa), img, inp=meta["input"])
                    m.run(max_cycles=meta["max-cycles"])
                    self.assertEqual(bytes(m.dev.out), testing.expected_output(name))


def cli(*argv):
    """heron v1_isa ARGV, in this process: (exit status, stdout, stderr)."""
    from heron.studies.v1_isa.cli import main
    out = io.TextIOWrapper(io.BytesIO(), encoding="latin-1")
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rc = main(list(argv))
        except SystemExit as e:     # argparse errors
            rc = e.code
    out.flush()
    return rc, out.buffer.getvalue().decode("latin-1"), err.getvalue()


class CommandLineISA(unittest.TestCase):
    PROG = "        .org 0\n        JMP  start\n        .org 0x18\nstart:  HALT\n"

    def test_unknown_isa(self):
        for isa in ("v9", "v1common"):
            rc, _, err = cli("--isa", isa, "test")
            self.assertEqual(rc, 2)
            self.assertIn("invalid choice", err)

    def test_isa_must_agree_with_object_files(self):
        with tempfile.TemporaryDirectory() as d:
            o, out = os.path.join(d, "p.o"), os.path.join(d, "p.out")
            assemble("v1b", self.PROG).write(o)
            self.assertEqual(cli("ld", o, "-o", out)[0], 0)      # the ISA comes from the file
            self.assertEqual(cli("--isa", "v1b", "ld", o, "-o", out)[0], 0)
            self.assertEqual(cli("run", out)[0], 0)
            for isa in ("v1a",):
                for cmd in (("ld", o, "-o", out), ("run", out)):
                    rc, _, err = cli("--isa", isa, *cmd)
                    self.assertEqual(rc, 1)
                    self.assertIn(f"error: the object files are for v1b, not {isa}", err)


if __name__ == "__main__":
    unittest.main()
