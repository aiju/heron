"""The Forth on the IOP, at the console: the interpreter and compiler, the
primitives, tasks, the image flash. One system is booted for the class
(about a tenth of a second of host time)."""

import re
import unittest

from heron import native
from heron.studies.iop import build, layout
from heron.studies.iop.run import Session


class Forth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = build.Build(build.DEFAULT_PROGRAM)
        cls.s = Session(cls.b)
        cls.banner = cls.s.boot()

    def says(self, line, expect, timeout_ms=2000):
        out = self.s.command(line, timeout_ms)
        self.assertTrue(out.startswith(line), out)
        got = out[len(line):].strip()
        self.assertEqual(got, expect, line)

    def test_banner(self):
        self.assertRegex(self.banner.decode(), r"Heron IOP Forth, \d+ cells")

    def test_arithmetic(self):
        self.says("2 3 + .", "5  ok")
        self.says("-5 3 / . -5 3 mod . 7 -2 /mod . .", "-1 -2 -3 1  ok")
        self.says("1000 7 um* d. 1000. 7 um/mod . .", "7000 142 6  ok")
        self.says("$FFFF $FFFF um* d.", "-131071  ok")
        self.says("1 15 lshift u. -1 1 rshift u. 12345 4 rshift . -8 2/ .", "32768 32767 771 -4  ok")
        self.says("3 4 < . 4 3 < . -1 1 < . 1 -1 < . -1 1 u< .", "-1 0 -1 0 0  ok")
        self.says("$1234 swab hex . decimal", "3412  ok")

    def test_stack(self):
        self.says("1 2 3 rot .s", "<3> 2 3 1  ok")
        self.says("2drop drop depth .", "0  ok")
        self.says("1 2 over swap tuck .s 2drop 2drop", "<4> 1 2 1 2  ok")

    def test_definitions(self):
        self.says(": sq dup * ; 7 sq .", "49  ok")
        self.says(": fib dup 2 < if exit then dup 1- recurse swap 2 - recurse + ; 20 fib .", "6765  ok")
        self.says(": t 0 100 0 do i + loop ; t .", "4950  ok")
        self.says(": t2 10 0 ?do i . 3 +loop ; t2", "0 3 6 9  ok")
        self.says(": t3 -10 0 ?do i . -4 +loop ; t3", "0 -4 -8  ok")
        self.says(": t3b 0 8 do i . -4 +loop ; t3b", "8 4 0  ok")
        self.says(": t4 0 0 ?do 1 loop ; t4 depth .", "0  ok")
        self.says(": t5 10 0 do i 3 = if leave then i . loop ; t5", "0 1 2  ok")
        self.says(": t6 2 0 do 2 0 do j 10 * i + . loop loop ; t6", "0 1 10 11  ok")
        self.says(": t7 begin dup . 1- dup 0= until drop ; 3 t7", "3 2 1  ok")
        self.says(": t8 begin dup while dup . 1- repeat drop ; 2 t8", "2 1  ok")

    def test_data(self):
        self.says("variable v 42 v ! v ?", "42  ok")
        self.says("5 constant five : f five 2* ; f .", "10  ok")
        self.says("create tab 1 , 2 , 3 , tab 2 + @ .", "3  ok")
        self.says(": k create , does> @ 3 + ; 39 k forty-two forty-two .", "42  ok")
        self.says(": greet .\" hi there\" ; greet", "hi there ok")
        self.says('s" abc" type', "abc ok")
        self.says("char A .", "65  ok")

    def test_numbers(self):
        self.says("$ff %101 #10 -3 .s 2drop 2drop", "<4> 255 5 10 -3  ok")
        self.says("hex 10 . decimal 10 .", "10 10  ok")
        self.says("100000. d. -1. d.", "100000 -1  ok")

    def test_errors(self):
        self.says("nosuchword", "nosuchword ?")
        self.says("drop", "stack empty")
        self.says("1 .", "1  ok")

    def test_case_insensitive(self):
        self.says("2 DUP + .", "4  ok")

    def test_execute(self):
        self.says(": sq2 dup * ; 6 ' sq2 execute .", "36  ok")
        self.says("1 2 ' + execute .", "3  ok")

    def test_tasks(self):
        self.says("variable n : counter begin 1 n +! pause again ; ' counter 3 spawn", "ok")
        a = int(re.search(r"(\d+)", self.s.command("n ?")[3:]).group(1))
        self.s.run_ms(5)
        b = int(re.search(r"(\d+)", self.s.command("n ?")[3:]).group(1))
        self.assertGreater(b, a + 100)

    def test_ms(self):
        start = self.s.ms
        self.s.command("20 ms")
        self.assertGreater(self.s.ms - start, 20)


class Flash(unittest.TestCase):
    def test_save_and_cold_start(self):
        """Words compiled at the console, saved into the image flash, are
        there after a cold start from it."""
        b = build.Build(build.DEFAULT_PROGRAM)
        s = Session(b)
        s.boot()
        s.command(': saved ." still here" ;')
        self.assertTrue(s.command("save", timeout_ms=5000).endswith(" ok\r\n"))
        s.s = native.iop.System(b.ucode_bytes(), s.s.flash())
        s.boot()
        self.assertIn("still here", s.command("saved"))

    def test_no_image(self):
        """An empty flash: the LEDs say so, and the microcode stops."""
        b = build.Build()
        s = native.iop.System(b.ucode_bytes(), b"")
        self.assertEqual(s.run(int(200e6 / s.bclk_ns)), "stopped")
        self.assertEqual(s.regs()["leds"], 0xE2)


class Microcode(unittest.TestCase):
    def test_sram_test_and_copy(self):
        """At reset the microcode tests the SRAM, which powers up holding
        anything, and copies the dictionary out of the flash."""
        b = build.Build()
        s = native.iop.System(b.ucode_bytes(), b.flash)
        s.breakpoints = [b.mc.labels["next"]]
        self.assertEqual(s.run(int(500e6 / s.bclk_ns)), "break")
        self.assertEqual(s.sram(0, b.meta.here), b.meta.image)
        r = s.regs()
        self.assertEqual(r["bank"], layout.CONSOLE_BANK)
        self.assertEqual(r["leds"], 3)
