"""The benchmark's harness: workloads keep the contract, data and parameters
reach the code, the checks catch what they should, and every workload
runs at its `test` size with its expected output."""

import os
import tempfile
import unittest

from heron.infra import isas
from heron.studies.bench import report, suite
from heron.studies.v2_isa.sim import Machine


def asm_image(text, params=None, data=None):
    """An image from hand-written text, linked as a workload's would be."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "main.s")
        with open(p, "w") as f:
            f.write(text)
        lib = suite._lib_objects()
        objs = [lib["start"], suite.asm_object(p, params or {}), lib["util"]]
        if data:
            objs.append(suite._data_object(data, ""))
        return suite._link(objs)


def run(img, inp=b""):
    m = Machine(img, inp=inp)
    m.run(max_cycles=1_000_000)
    return m


class Contract(unittest.TestCase):
    def test_workloads(self):
        self.assertTrue(suite.names())
        for w in suite.workloads():
            with self.subTest(w.name):
                self.assertIn(w.part, suite.PARTS)
                self.assertEqual(set(w.sizes), set(suite.SIZES))
                self.assertTrue(w.title and w.category)
                self.assertTrue((w.mod.__doc__ or "").strip(), "workload.py needs a docstring")
                for s in w.sources:
                    self.assertTrue(os.path.exists(s), s)
                for size in suite.SIZES:
                    self.assertIsNotNone(w.expected(size), f"no expected/{size}.txt")
                    self.assertLess(len(w.expected(size)), 1024, "results under a kilobyte")


class Harness(unittest.TestCase):
    def test_params_and_data(self):
        img = asm_image("""
                .global main
        main:   PUSH r7
                MOV  r1, #5381
                MOV  r2, #blob
                MOV  r3, [blob_len]
                CALL bench_hash
                ADD  r1, #N
                MOV  r2, r1
                LEA  r1, [.lab]
                CALL bench_report
                JMP  [sp]+
        .lab:   .asciz "hash"
                .align 2
        """, {"N": 7}, {"blob": bytes(range(40))})
        h = 5381
        for b in range(40):
            h = ((h * 33) ^ b) & 0xFFFFFFFF
        self.assertEqual(bytes(run(img).dev.out), f"hash {h + 7:08x}\n".encode())

    def test_error_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "bad.s")
            with open(p, "w") as f:
                f.write("        .global main\nmain:   RET\n        FROB r1\n")
            from heron.infra.asm import AsmError
            with self.assertRaises(AsmError) as e:
                suite.asm_object(p, {"A": 1, "B": 2})
            self.assertEqual(e.exception.where[1], 3)

    def test_tentative(self):
        img = asm_image("""
                .global main
        main:   MOV  r2, #3
                MOV  r3, #4
                MULFX r0:r2, r3, #1
                RET
        """)
        self.assertEqual(suite.tentative(run(img)), {"MULFX"})
        img = asm_image("        .global main\nmain:   ADD r1, r2\n        RET\n")
        self.assertEqual(suite.tentative(run(img)), set())

    def test_host_reference(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "main.c")
            with open(p, "w") as f:
                f.write('#include "bench.h"\nextern const unsigned char blob[];\n'
                        'extern unsigned blob_len;\nint main(void) {\n'
                        '    bench_report("x", bench_hash(BENCH_HASH0, blob, blob_len) + N);\n'
                        '    return 0;\n}\n')
            out = suite.run_host([p], {"N": 1}, {"blob": b"abc"})
        h = 5381
        for b in b"abc":
            h = ((h * 33) ^ b) & 0xFFFFFFFF
        self.assertEqual(out, f"x {h + 1:08x}\n".encode())

    def test_classes(self):
        self.assertEqual(report.klass("MOV [sp+n]"), "load")
        self.assertEqual(report.klass("MOV r"), "ALU, move")
        self.assertEqual(report.klass("ST b[r]"), "store")
        self.assertEqual(report.klass("ADD [r+d]"), "ALU on memory")
        self.assertEqual(report.klass("JMP [r]+"), "call, return")
        self.assertEqual(report.klass("JMP r"), "jump")
        self.assertEqual(report.klass("Bcc"), "branch")
        self.assertEqual(report.klass("DIVU"), "multiply, divide")
        self.assertEqual(report.klass("LEA [r+d]"), "ALU, move")


class Workloads(unittest.TestCase):
    def test_every_workload(self):
        """Every workload at its `test` size, against its expected output."""
        for w in suite.workloads():
            with self.subTest(w.name):
                r = suite.run(w, "test")
                self.assertTrue(r.ok, r.error)


if __name__ == "__main__":
    unittest.main()
