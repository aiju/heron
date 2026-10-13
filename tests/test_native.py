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

    def test_timing(self):
        self.assertEqual(native.v1.cycles((1, 0, "alu", 1), "D16-overlap"), 3)
        with self.assertRaisesRegex(ValueError, "not a timing key"):
            native.v1.cycles((1, 0, "nope"), "D16-overlap")

    def test_errors(self):
        # MOV r1, [abs32 0x200000]
        m = native.v1.Machine("v1b", bytes([0xF7, 0x11, 0, 0, 0x20, 0]))
        with self.assertRaisesRegex(native.v1.SimError, "unmapped address 00200000"):
            m.run()
