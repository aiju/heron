"""The Rust engines' Python module (RFC 0015): it builds, and it's the
bindings crate the sources describe."""

import os
import re
import shutil
import unittest

from heron import ROOT, native


@unittest.skipUnless(shutil.which("cargo"), "needs cargo (https://rustup.rs)")
class Native(unittest.TestCase):
    def test_builds_and_loads(self):
        with open(os.path.join(ROOT, "heron", "bindings", "Cargo.toml")) as f:
            version = re.search(r'^version = "(.*)"', f.read(), re.M).group(1)
        self.assertEqual(native.version(), version)
        self.assertFalse(native.stale())


@unittest.skipUnless(shutil.which("cargo"), "needs cargo (https://rustup.rs)")
class Hwsim(unittest.TestCase):
    """The chip-level simulator's bindings; the studies run real machines."""

    def test_netlist_errors(self):
        chip = {"ref": "U1", "model": "nand9", "pins": [], "kinds": [], "nets": []}
        with self.assertRaisesRegex(ValueError, 'U1: unknown model "nand9"'):
            native.hwsim.run({"nets": [], "chips": [chip]}, {"period_ps": 100_000}, {})

    def test_unknown_settings(self):
        with self.assertRaisesRegex(Exception, "unknown field `perod_ps`"):
            native.hwsim.run({"nets": [], "chips": []}, {"perod_ps": 100_000}, {})


@unittest.skipUnless(shutil.which("cargo"), "needs cargo (https://rustup.rs)")
class V1(unittest.TestCase):
    """The draft 1 simulator's bindings; the v1_isa study runs programs."""

    def test_machine(self):
        # MOV r1, #5; ADD r1, #3; HALT, in draft 1b
        m = native.v1.Machine("v1b", bytes([0x15, 0x11, 0x13, 0x41, 0, 0]))
        m.run()
        self.assertEqual((m.r[1], m.instructions, m.halted), (8, 3, True))
        keys = [(pc, k, n) for pc, k, n in m.pc_keys()]
        self.assertEqual(keys[0], (0, (1, 0, "alu", 1), 1))

    def test_resume(self):
        # MOV r1, #5; HALT; ADD r1, #3; HALT, in draft 1b: a HALT as a marker
        m = native.v1.Machine("v1b", bytes([0x15, 0x11, 0, 0, 0x13, 0x41, 0, 0]))
        m.run()
        self.assertEqual((m.r[1], m.pc, m.instructions), (5, 4, 2))
        m.resume()
        m.run()
        self.assertEqual((m.r[1], m.pc, m.instructions, m.halted), (8, 8, 4, True))

    def test_timing(self):
        self.assertEqual(native.v1.cycles((1, 0, "alu", 1), "D16-overlap"), 3)
        with self.assertRaisesRegex(ValueError, "not a timing key"):
            native.v1.cycles((1, 0, "nope"), "D16-overlap")

    def test_errors(self):
        # MOV r1, [abs32 0x200000]
        m = native.v1.Machine("v1b", bytes([0xF7, 0x11, 0, 0, 0x20, 0]))
        with self.assertRaisesRegex(native.v1.SimError, "unmapped address 00200000"):
            m.run()


@unittest.skipUnless(shutil.which("cargo"), "needs cargo (https://rustup.rs)")
class Toolchain(unittest.TestCase):
    """The assembler's bindings; heron.infra.asm wraps them, and the v1_isa
    and c_compiler studies assemble and link real programs."""

    SRC = "        .org 0\nstart:  MOV r1, #5\n        BRA start\n"

    def test_image(self):
        a = native.toolchain.Assembler("v1b", False)
        a.load("t.s", self.SRC)
        out = a.assemble()
        self.assertEqual(out["mem"], [(0, bytes([0x15, 0x11, 0xFE, 0xEE]))])
        self.assertEqual(out["symbols"], [("start", 0)])
        kinds = [(k, name, label, addr, words) for k, name, label, addr, _, words, *_ in a.stmts()]
        self.assertEqual(kinds, [("dir", ".org", None, 0, []), ("label", None, "start", 0, []),
                                 ("insn", "mov", None, 0, [0x1115]), ("insn", "bra", None, 2, [0xEEFE])])
        self.assertIn("0002  EEFE                   BRA start", a.listing())

    def test_object(self):
        a = native.toolchain.Assembler("v1a", True)
        a.load("t.s", "f:      CALL g\n")
        isa, flags, entry, secs, syms, relocs = a.assemble_object("t.o")
        self.assertEqual((isa, [s[0] for s in secs], [s[0] for s in syms]), ("v1a", [".text"], [".text", "f", "g"]))
        self.assertEqual(relocs, [(1, 2, 5, 2, -2)])

    def test_errors(self):
        a = native.toolchain.Assembler("v1b", False)
        a.load("t.s", "        MOV r1, #undefined\n")
        with self.assertRaises(native.toolchain.AsmFailed) as cm:
            a.assemble()
        self.assertEqual(cm.exception.args, ("undefined symbol undefined", ("t.s", 1)))
        with self.assertRaises(FileNotFoundError):
            native.toolchain.Assembler("v1b", False).load(os.path.join(ROOT, "nowhere.s"))
        with self.assertRaisesRegex(ValueError, "no assembler for ISA v9"):
            native.toolchain.Assembler("v9", False)


@unittest.skipUnless(shutil.which("cargo"), "needs cargo (https://rustup.rs)")
class Sisim(unittest.TestCase):
    """The signal-integrity simulator's bindings, through infra/si/engine.py,
    which turns SPICE netlists into its input."""

    def test_open_line(self):
        from heron.infra.si import engine
        # a 1 V step through 50 ohm into 1 ns of open 50 ohm line
        lines = ["V1 s 0 PWL(0 0 1p 1)", "R1 s a 50", "T1 a 0 b 0 Z0=50 TD=1n"]
        r = engine.run_native(lines, ["v(a)", "v(b)"], 3e-9)
        at = lambda p, t: float(r[p][abs(r["time"] - t).argmin()])
        self.assertAlmostEqual(at("v(a)", 1.5e-9), 0.5, places=4)
        self.assertAlmostEqual(at("v(b)", 1.5e-9), 1.0, places=4)
        self.assertAlmostEqual(at("v(a)", 2.5e-9), 1.0, places=4)

    def test_unsupported(self):
        from heron.infra.si import engine
        with self.assertRaisesRegex(ValueError, "doesn't take this element"):
            engine.run_native(["X1 a b sub"], ["v(a)"], 1e-9)
        with self.assertRaisesRegex(RuntimeError, "shorter than the time step"):
            native.sisim.run({"nodes": 3, "lines": [{"end1": [1], "ref1": 0, "end2": [2], "ref2": 0,
                                                      "tv": [[1.0]], "z": [50.0], "delay": [1e-12]}]},
                             {"dt": 5e-12, "tstop": 1e-9, "probes": []})
