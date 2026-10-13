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
