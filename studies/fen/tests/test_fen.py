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


class IopDisk(unittest.TestCase):
    """The disk behind the I/O processor of studies/iop: the kernel gives
    the file server a ring of the IOP's, and the file server's requests
    move the sectors straight into its cache (srv/fs/ide_iop.c)."""

    @classmethod
    def setUpClass(cls):
        cls.s = Session(serial=True, iop=True)
        cls.s.boot()

    def test_files(self):
        s = self.s
        self.assertIn("IOP: 8192 KB disk", s.log.decode())
        self.assertEqual(s.command("cat /etc/hello.txt | grep -c Heron"), "1\n")
        self.assertEqual(s.command("cat /bin/sh | wc -c"), s.command("wc -c < /bin/sh"))
        s.command("cp /bin/sh /home/sh2; echo kept > /home/note")
        self.assertEqual(s.command("wc < /home/sh2"), s.command("wc < /bin/sh"))
        r = mkfs.Reader(s.cf_image())
        self.assertEqual(r.read("/home/note"), b"kept\n")
        self.assertEqual(r.read("/home/sh2"), r.read("/bin/sh"))


if __name__ == "__main__":
    unittest.main()


class Desktop(unittest.TestCase):
    """The window system, with the keyboard and the mouse."""

    @classmethod
    def setUpClass(cls):
        cls.s = Session(serial=False)
        cls.s.run(3000)

    def test_typing_in_the_terminal(self):
        # the keyboard, wsys, term, the shell and the file server; a click
        # on the terminal first gives it the keyboard
        self.s.click(400, 300)
        self.s.keys("ls /bin > /tmp/bin.txt; echo $? >> /tmp/bin.txt\n")
        self.s.run(1500)
        got = mkfs.Reader(self.s.cf_image()).read("/tmp/bin.txt").decode().split("\n")
        self.assertIn("term", got)
        self.assertIn("wsys", got)
        self.assertEqual(got[-2], "0")

    def test_the_menu_starts_the_clock(self):
        def red():
            rgb = self.s.screen()
            n = 0
            for y in range(40, 300):
                for x in range(30, 260):
                    r, g, b = rgb[3 * (640 * y + x):3 * (640 * y + x) + 3]
                    n += r > 150 and g < 60 and b < 60
            return n
        self.assertEqual(red(), 0)
        # the desktop's menu, from the bottom left corner: Terminal, Clock
        self.s.mouse_to(20, 460)
        self.s.c.mouse(0, 0, 1)
        self.s.run(100)
        self.s.mouse_to(30, 468, 1)
        self.s.c.mouse(0, 0, 0)
        self.s.run(2500)
        self.assertGreater(red(), 10)        # the second hand
