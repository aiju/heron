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
