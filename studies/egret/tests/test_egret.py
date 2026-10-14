"""Egret: the language on the host build of the VM, every program against
its expected output on the host, and a few on the simulated machine with
each build of the VM (the hand-written interpreter loop, the C loop and
the JIT)."""

import unittest

from heron.studies.egret import build
from heron.studies.egret.programs import catalogue


def host(src, inp=b""):
    out, status = build.run_host(src.encode(), inp)
    return out.decode(), status


class Language(unittest.TestCase):
    def run_ok(self, src, expected):
        out, status = host(src)
        self.assertEqual(status, 0, out)
        self.assertEqual(out, expected)

    def test_classes(self):
        self.run_ok("""
class Point
  def init(x, y)
    @x = x
    @y = y
  end
  attr x, y
  def +(other) = Point(@x + other.x, @y + other.y)
  def to_s = "({@x}, {@y})"
end
class Point3 < Point
  def init(x, y, z)
    super(x, y)
    @z = z
  end
  def to_s = super + " z={@z}"
end
print(Point(1, 2) + Point(3, 4), Point3(1, 2, 3), Point3(0, 0, 0).is_a?(Point))
""", "(4, 6) (1, 2) z=3 true\n")

    def test_integers(self):
        self.run_ok("print(2 ** 100, 7 / -2, 7 % -2, -7 / 2, 3 <=> 5, ~5, 1 << 40, 0x7FFFFFFF + 1)\n",
                    "1267650600228229401496703205376 -4 -1 -4 -1 -6 1099511627776 2147483648\n")

    def test_collections(self):
        self.run_ok("""
m = ["a": 1, "b": 2]
m["c"] = 3
print([3, 1, 2].sort, m, (1..<4).to_list, (1..10).select { |n| n % 3 == 0 }.map { |n| n * n })
""", '[1, 2, 3] ["a": 1, "b": 2, "c": 3] [1, 2, 3] [9, 36, 81]\n')

    def test_closures(self):
        self.run_ok("""
def counter
  n = 0
  [{ n += 1 }, { n }]
end
def first_over(xs, k)
  xs.each { |x| if x > k then return x end }
  nil
end
c = counter()
3.times { |i| c[0]() }
print(c[1](), first_over([1, 5, 9], 4), first_over([1], 4))
""", "3 5 nil\n")

    def test_errors(self):
        self.run_ok("""
r = try
  [1, 2][5]
catch e
  "caught: {e.message}"
end
print(r)
""", "caught: index 5 out of range (size 2)\n")
        out, status = host("def f(x) = x.nope\nf(1)\n")
        self.assertNotEqual(status, 0)
        self.assertIn("Int does not understand 'nope'", out)
        self.assertIn("in f (line 1)", out)

    def test_input(self):
        out, status = host("print(gets().strip, read_all().strip)\n__END__\none\ntwo\n")
        self.assertEqual(out, "one two\n")


class Programs(unittest.TestCase):
    def test_host(self):
        for name in catalogue.names():
            prog = catalogue.program(name)
            with self.subTest(name):
                out, status = build.run_host(prog.source, prog.input)
                self.assertEqual(out, prog.expected())


class OnTheMachine(unittest.TestCase):
    """hello for start-up, fib for sends and big integers, closures for
    blocks and non-local return, shapes for polymorphic sends"""
    PROGRAMS = ["hello", "fib", "closures", "shapes"]

    def test_variants(self):
        for variant in build.VARIANTS:
            for name in self.PROGRAMS:
                prog = catalogue.program(name)
                with self.subTest(variant=variant, program=name):
                    out, m = build.run_heron(prog.source, prog.input, variant=variant)
                    self.assertTrue(m.halted)
                    self.assertEqual(out, prog.expected())


if __name__ == "__main__":
    unittest.main()
