"""Draft 2: the assembler and disassembler round trip, the programs without
a zero register and as relocatable object files, the tables' relocations
through the linker, and `run`. The encodings and the semantics are tested
in Rust (isa/tests/v2.rs)."""

import io
import os
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from heron.infra import asm, isas
from heron.infra import link as L
from heron.studies.v2_isa import testing
from heron.studies.v2_isa.sim import Machine

V2 = isas.get("v2")


def assemble_object(text, name):
    a = asm.Assembler(V2, relocatable=True)
    a.load(name, text=text)
    return a.assemble_object(name)


def run_image(img, inp=b"", max_cycles=1_000_000):
    m = Machine(img, inp=inp)
    m.run(max_cycles=max_cycles)
    return m


class RoundTrip(unittest.TestCase):
    def test_every_first_parcel(self):
        """Every first parcel, with a few patterns of extension parcels:
        what the disassembler prints assembles to no more parcels and
        disassembles the same. The one difference allowed is LEA rd, [rs],
        which is MOV rd, rs."""
        pc = 0x2000
        for ext in ([0xFF00, 0x0001], [0x2A12, 0x8000], [0x3502, 0x0010], [0x7000, 0x1234]):
            for w in range(0x10000):
                text, n = V2.disassemble([w] + ext, pc)
                if text.startswith(".half"):
                    continue
                img = asm.assemble_text(V2, f"        .org {pc}\n        {text}\n")
                st = [s for s in img.stmts if s.kind == "insn"][0]
                text2, _ = V2.disassemble(st.words + [0, 0], pc)
                m = re.fullmatch(r"LEA (\w+), \[(\w+)\]", text)
                if m and text2 == f"MOV {m[1]}, {m[2]}":
                    continue
                self.assertEqual(text2, text, f"{w:04X} {ext}")
                self.assertLessEqual(len(st.words), n, text)

    def test_hex_shows_the_opcode_first(self):
        self.assertEqual(V2.hex_parcels([0x3413, 0x0008]), "13 34 0008")


class Programs(unittest.TestCase):
    def start(self):
        with open(os.path.join(testing.PROGRAMS, "lib", "start.s")) as f:
            return f.read()

    def programs(self):
        """(name, path, text) of every program that includes lib/start.s."""
        for path in testing.program_paths():
            with open(path) as f:
                text = f.read()
            if '.include "lib/start.s"' in text:
                yield os.path.basename(path)[:-2], path, text

    def test_r0_is_not_zero(self):
        """r0 is a general register: every program works with r0 holding
        garbage from the start."""
        start = self.start().replace("__start:", "__start:\n        MOV  r0, #0x5A5A5A5A", 1)
        for name, path, text in self.programs():
            with self.subTest(program=name):
                a = asm.Assembler(V2)
                a.load(path, text=text.replace('.include "lib/start.s"', start))
                meta = testing.metadata(path)
                m = run_image(a.assemble(), meta["input"], meta["max-cycles"])
                self.assertEqual(bytes(m.dev.out), testing.expected_output(name))

    def test_relocatable_programs(self):
        """Every program, assembled as a relocatable object file with its
        start code and vectors linked in separately, still works."""
        start = assemble_object(self.start(), "start.s")
        for name, path, text in self.programs():
            with self.subTest(program=name):
                a = asm.Assembler(V2, relocatable=True)
                a.load(path, text=text.replace('.include "lib/start.s"', ""))
                o = a.assemble_object(name + ".o")
                if name != "hello":
                    self.assertTrue(o.relocs)
                meta = testing.metadata(path)
                m = run_image(L.link([start, o]), meta["input"], meta["max-cycles"])
                self.assertEqual(bytes(m.dev.out), testing.expected_output(name))

    def test_tables_link(self):
        """A table in another file, indexed without a base register and
        PC-relative: the 24-bit relocations."""
        main = """
        .org 0
        JMP  start
        .org 0x40
start:  MOV  sp, #0x100000
        MOV  r2, #2
        MOV  r1, [tab + r2*4]
        MOV  r3, half [pc + tab + r2*2]
        LEA  r4, [tab + r2*4]
        HALT
"""
        data = "        .data\n        .space 0x300\ntab:    .word 0x11, 0x22, 0x33, 0x44\n"
        objs = [assemble_object(main, "main.s"), assemble_object(data, "data.s")]
        kinds = sorted(L.O.RELOC_NAMES[r.kind] for r in objs[0].relocs)
        self.assertEqual(kinds, ["abs24h", "abs24h", "abs24l", "abs24l", "pc24h", "pc24l"])
        img = L.link(objs)
        m = run_image(img)
        tab = img.symbols["tab"]
        self.assertEqual((m.r[1], m.r[3], m.r[4]), (0x33, 0x22, tab + 8))


def cli(*argv):
    """heron v2_isa ARGV, in this process: (exit status, stdout bytes, stderr)."""
    from heron.studies.v2_isa.cli import main
    out, err = io.TextIOWrapper(io.BytesIO()), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rc = main(list(argv))
        except SystemExit as e:     # argparse errors
            rc = e.code
    out.flush()
    return rc, out.buffer.getvalue(), err.getvalue()


def cli_run(src, *argv):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.s")
        with open(path, "w") as f:
            f.write(src)
        return cli("run", path, *argv)


class RunCommand(unittest.TestCase):
    def test_traps(self):
        prog = """
        .org 0
        JMP  start
        .org 0x0C
        RTI                     ; SWI: returns to the next instruction
        .org 0x18
        HALT                    ; tag check
        .org 0x40
start:  MOV  sp, #0x100000
        MOV  r1, #97
        MOV  byte [0xFFFFFF00], r1
        SWI  #1
        MOV  r2, #3
        TADD r1, r2
        HALT
"""
        rc, out, err = cli_run(prog)
        self.assertEqual((rc, out), (1, b"a"))
        self.assertIn("tag check", err)
        self.assertIn("error: halted in a trap handler", err)

    def test_zero_is_illegal(self):
        # nothing at the SWI vector: a zero parcel is ILLEGAL, not HALT
        rc, _, err = cli_run("        .org 0\n        JMP  start\n        .org 0x08\n"
                             "        HALT\n        .org 0x40\n"
                             "start:  MOV  sp, #0x100\n        SWI  #1\n        HALT\n")
        self.assertEqual(rc, 1)
        self.assertIn("trap at pc C: illegal instruction", err)
        self.assertIn("error: halted in a trap handler", err)

    def test_stats_and_dis(self):
        path = os.path.join(testing.PROGRAMS, "sieve.s")
        rc, out, err = cli("run", path, "--stats")
        self.assertEqual(rc, 0)
        self.assertIn("primes below 8192: 1028", out.decode())
        self.assertIn("CLR b[r]", err)
        with tempfile.TemporaryDirectory() as d:
            binary = os.path.join(d, "t.bin")
            self.assertEqual(cli("asm", path, "-o", binary)[0], 0)
            rc, out, _ = cli("dis", binary, "--to", "0x4")
            self.assertEqual(out.decode().split("\n")[0].split(), ["000000", "F2", "E0", "000C", "JMP", "0x1C"])

    def test_object_files_must_be_draft_2(self):
        with tempfile.TemporaryDirectory() as d:
            o = os.path.join(d, "p.o")
            a = asm.Assembler(isas.get("v1b"), relocatable=True)
            a.load("p.s", text="        .org 0\n        HALT\n")
            a.assemble_object("p.o").write(o)
            rc, _, err = cli("run", o)
            self.assertEqual(rc, 1)
            self.assertIn("v1b", err)


if __name__ == "__main__":
    unittest.main()
