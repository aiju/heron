"""Fen: the kernel's own test, and a booted system on the serial console.
Each test boots a machine (a fraction of a second of host time)."""

import unittest

from heron.studies.fen import build, mkfs
from heron.studies.fen.run import Session


class Mkfs(unittest.TestCase):
    def test_an_image_reads_back(self):
        big = bytes(range(256)) * 300            # past the direct and indirect blocks
        img = mkfs.make({"/a/b.txt": b"hello", "/big": big}, size=1 << 20, dirs=["/empty"])
        r = mkfs.Reader(img)
        self.assertEqual(r.read("/a/b.txt"), b"hello")
        self.assertEqual(r.read("/big"), big)
        self.assertEqual(r.listdir("/"), ["a", "big", "dev", "empty"])
        self.assertEqual(r.listdir("/dev"), ["klog", "null", "zero"])


class Kernel(unittest.TestCase):
    def test_ktest(self):
        from heron.studies.fen import cli
        import io
        import contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            status = cli.cmd_ktest(None)
        self.assertEqual(status, 0, out.getvalue())
        self.assertIn("28 passed, 0 failed", out.getvalue())


class Shell(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = Session(serial=True)
        cls.s.boot()

    def run_(self, line):
        return self.s.command(line)

    def test_files(self):
        self.assertEqual(self.run_("cd /tmp; echo one two > f; echo three >> f; cat f"),
                         "one two\nthree\n")
        self.assertEqual(self.run_("wc -l < f"), "      2\n")
        self.run_("mkdir -p a/b; cp f a/b/g; mv a/b/g a/h")
        self.assertEqual(self.run_("ls a | cat"), "b\nh\n")
        self.assertEqual(self.run_("cat a/h"), "one two\nthree\n")
        self.assertIn("No such", self.run_("cat nonesuch").replace("no such", "No such"))
        self.run_("rm -r a f")
        self.assertEqual(self.run_("ls"), "")
        # what's on the card is what the shell made
        self.run_("echo kept > /home/note")
        r = mkfs.Reader(self.s.cf_image())
        self.assertEqual(r.read("/home/note"), b"kept\n")

    def test_pipelines(self):
        self.assertEqual(self.run_("seq 10 | sort -rn | head -3"), "10\n9\n8\n")
        self.assertEqual(self.run_("cat /etc/hello.txt | grep -c Heron"), "1\n")
        self.assertEqual(self.run_("seq 3 | tee /tmp/t | wc -l; cat /tmp/t"), "      3\n1\n2\n3\n")
        # a big write through a pipe (more than its 4 KB)
        self.assertEqual(self.run_("cat /bin/sh | wc -c"),
                         self.run_("wc -c < /bin/sh"))

    def test_lists_and_variables(self):
        self.assertEqual(self.run_("false || echo a && echo b; true && false || echo c"),
                         "a\nb\nc\n")
        self.assertEqual(self.run_("X=5; echo \"x is $X\" '$X'"), "x is 5 $X\n")
        self.assertEqual(self.run_("false; echo $?"), "1\n")
        self.assertEqual(self.run_("ls /etc/*.txt"), "/etc/hello.txt\n")

    def test_processes(self):
        ps = self.run_("ps")
        for name in ("init", "fs", "cons", "sh", "ps"):
            self.assertIn(f" {name}\n", ps)
        self.assertEqual(self.run_("sleep 1 & wait; echo done").split("\n")[-2], "done")

    def test_errors(self):
        self.assertEqual(self.run_("nosuch; echo after"), "sh: nosuch: not found\nafter\n")
        self.assertEqual(self.run_("cat /nonesuch"), "cat: /nonesuch: no such file or directory\n")


if __name__ == "__main__":
    unittest.main()
