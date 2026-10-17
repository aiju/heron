"""The simulator's machines: every one is built from its study and booted
on the engine the browser runs, and must answer as its `check` says, so a
change to a study that breaks its machine shows here. The first run makes
the compiled Lisp's saved images, about 20 seconds each."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from heron import ROOT
from heron.studies.websim import machines as M
from heron.studies.websim import run, web


class Registry(unittest.TestCase):
    def test_machines_are_described(self):
        ids = [m.id for m in M.MACHINES]
        self.assertEqual(len(ids), len(set(ids)))
        for m in M.MACHINES:
            with self.subTest(m.id):
                self.assertRegex(m.id, r"^[a-z0-9-]+$")
                self.assertTrue(m.check, "a machine needs a check")
                self.assertTrue(m.terminal or m.screen)
                if m.terminal:
                    self.assertIn(m.terminal["mode"], ("line", "raw"))
                for _title, path in m.links:
                    self.assertTrue(os.path.exists(os.path.join(ROOT, path)), path)

    def test_a_description_for_the_page(self):
        b = M.Build("plain", {"isa": "v2", "clock_hz": 6e6},
                    [("ram", 0, bytes(5000)), ("console", 0, b"(+ 1 2)\n"), ("ram", 0x10000, bytes(5000))],
                    {"start": 0, "loop": 0x10})
        with tempfile.TemporaryDirectory() as d:
            blobs = web.Blobs(d)
            e = web.describe(M.get("lisp-v2"), b, blobs)
            json.dumps(e)
            # the same bytes are one file; short text goes in the description
            self.assertEqual(e["loads"][0]["blob"], e["loads"][2]["blob"])
            self.assertEqual(e["loads"][1], {"target": "console", "at": 0, "text": "(+ 1 2)\n"})
            self.assertEqual(len(os.listdir(blobs.dir)), 2)


class Machines(unittest.TestCase):
    """Each machine boots and answers, on heron.native.websim."""


def _check(m):
    def test(self):
        run.check(m)
    return test


for _m in M.MACHINES:
    setattr(Machines, "test_" + _m.id.replace("-", "_"), _check(_m))


@unittest.skipUnless(shutil.which("gcc"), "needs gcc")
class EgretAtATerminal(unittest.TestCase):
    """Egret's VM built with EGRET_INTERACTIVE (vm/main.c), on the host:
    where a statement ends, and that it carries on after errors."""

    def test_statements(self):
        from heron.studies.egret import build
        exe = build.host(M.EGRET_DEFINES)
        text = ("1 + 2\n"
                "def sq(n) = n * n\n"
                "class P\n  def init(a)\n    @a = a\n  end\n  attr a\nend\n"
                "P(sq(5)).a\n"
                "for i in 1..2 do\n  print(i)\nend\n"
                "[1,\n 2].map { |x|\n  x * 10 }\n"
                "\"a {\"b\" + \"}\"} c\"\n"
                "nope\n"
                "foo(\n\n"
                "x = 6 *\n 7\n")
        out = subprocess.run([exe], input=text.encode(), capture_output=True, timeout=60).stdout.decode()
        values = [l for l in out.replace("egret> ", "\n").replace("  ...> ", "\n").split("\n") if l]
        self.assertEqual(values[:6], ["=> 3", "=> 25", "1", "2", "=> [10, 20]", '=> "a b} c"'])
        self.assertIn("error: Object does not understand 'nope'", out)
        self.assertIn("expected an expression", out)
        self.assertIn("=> 42", out)
