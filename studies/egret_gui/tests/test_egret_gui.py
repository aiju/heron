"""The GUI: the simulator's display, keyboard and mouse; the desktop
booting at both depths; the Workspace running code; the apps opening
without errors; Egretica's algebra (on the host) and its notebook; and
snapshots."""

import struct
import unittest

from heron import native
from heron.infra import asm, isas
from heron.studies.egret_gui import host, run, snapshot

# the same program for both: write VRAM, set a palette entry, read an event
DEVICES = """
        .org 0
        LI   r1, #0x01000000
        LI   r2, #0x12345678
        ST   r2, [r1 + 640]
        MOV  r3, byte [r1 + 641]
        ST   r3, [0xFFFFFF00]            ; the console: 0x56
        LI   r2, #7
        ST   r2, [0xFFFFFF30]           ; palette index 7
        LI   r2, #0xABCDEF
        ST   r2, [0xFFFFFF34]
        MOV  r4, [0xFFFFFF20]           ; an event
        ST   r4, [0x100]
        MOV  r4, [0xFFFFFF20]           ; none left: -1
        ST   r4, [0x104]
        MOV  r4, [0xFFFFFF24]           ; the mouse
        ST   r4, [0x108]
        HALT
"""


class Devices(unittest.TestCase):
    def test_display_and_input(self):
        img = asm.assemble_text(isas.get("v1b"), DEVICES)
        ram = bytearray(run.RAM_SIZE)
        for a, b in img.mem.items():
            ram[a] = b
        m = native.v1.Machine("v1b", bytes(ram))
        m.push_event(0x1000_0041)
        m.set_mouse(12, 34, 1)
        m.run()
        self.assertEqual(m.vram[640:644], bytes([0x78, 0x56, 0x34, 0x12]))
        self.assertEqual(m.out, bytes([0x56]))
        self.assertEqual(m.palette[7], 0xABCDEF)
        words = struct.unpack("<3I", m.mem[0x100:0x10C])
        self.assertEqual(words, (0x1000_0041, 0xFFFF_FFFF, 12 | 34 << 16))


def workspace_do(s, code, settle=3):
    """Raise the Workspace (its title bar), add a line of code, do it."""
    s.click(200, 50)
    s.key("end", ["ctrl"])
    s.type("\n" + code)
    s.key("d", ["ctrl"])
    s.run(settle)


class Desktop(unittest.TestCase):
    def setUp(self):
        self.s = run.Session().boot()
        self.s.run(3)

    def test_boots(self):
        self.assertIn("Egret desktop ready", self.s.output)
        self.assertNotIn("error", self.s.output)

    def test_workspace_runs_code(self):
        workspace_do(self.s, "print(6 * 7, \"from the test\")")
        self.assertIn("42 from the test", self.s.output)

    def test_errors_are_caught(self):
        workspace_do(self.s, "Window(\"x\", 10, 10, 50, 50).no_such_method")
        workspace_do(self.s, "print(\"still here\")")
        self.assertIn("still here", self.s.output)

    def test_class_source_with_edits(self):
        # a class's source is its class statement as booted, with what a
        # Workspace changed in place and what it added at the end
        workspace_do(self.s, 'print(class_source(Clock).first, class_source(Clock).last)', 8)
        self.assertIn("class Clock < Window end", self.s.output)
        workspace_do(self.s, 'record_edits("class Clock\\n  def tick(t) = nil\\n  def hello = 1\\nend")')
        workspace_do(self.s, 'c = class_source(Clock); print(c.index("  def tick(t) = nil") != nil, c[-2])', 8)
        self.assertIn("true   def hello = 1", self.s.output)

    def test_apps_open(self):
        for k in ["Browser", "About", "Clock(10, 10)"]:
            workspace_do(self.s, k if "(" in k else f"{k}()")
        self.assertNotIn("error", self.s.output)
        self.assertEqual(len(self.s.output.splitlines()), 1)

    def test_egretica(self):
        # a line worked out and laid out, a plot, and an error, which is
        # the notebook's and not the desktop's
        workspace_do(self.s, 'NB = Notebook(); NB.run("Integrate[x Exp[x], x]"); print("out", OUTS.last)', 8)
        workspace_do(self.s, 'NB.run("Plot[\{Sin[x], Tan[x]\}, \{x, -3, 3\}]"); NB.run("Solve[x^2 =="); print("cells", NB.cells.size)', 15)
        self.assertNotIn("error", self.s.output)
        self.assertIn("out x*E^x - E^x", self.s.output)
        self.assertIn("cells 7", self.s.output)

    def test_gadgets(self):
        # the table runs (out of the Workspace's way): balls go down the
        # ramps and off the trampoline into the bucket; and a new class of
        # part goes in the bin
        workspace_do(self.s, "G = Gadgets(); G.run; G.move_to(300, 420)")
        self.s.run(20)
        workspace_do(self.s, 'print("caught", G.statics.find { |p| p.is_a?(Bucket) }.count)')
        workspace_do(self.s, "class Balloon < Ball; def gravity = -30; end")
        workspace_do(self.s, 'print("bin", G.kinds.last.name)')
        self.assertNotIn("error", self.s.output)
        self.assertNotIn("stopped", self.s.output)
        caught = int(self.s.output.split("caught ")[1].split()[0])
        self.assertGreater(caught, 0)
        self.assertIn("bin Balloon", self.s.output)


# Egretica, on the host: a line typed in, and what it comes to, as it
# prints on one line (or the error)
CAS = [
    ("1/3 + 1/6", "1/2"),
    ("2^100", "1267650600228229401496703205376"),
    ("2 x + 3 x", "5*x"),
    ("(x + 1)^2 - (x + 1)^2", "0"),
    ("Sqrt[8] + Sqrt[2]", "3*sqrt(2)"),
    ("Sqrt[2] Sqrt[3]", "sqrt(6)"),
    ("Sqrt[-4]", "2*I"),
    ("Cos[5 Pi/6]", "-sqrt(3)/2"),
    ("ArcTan[1]", "Pi/4"),
    ("Exp[Log[x]]", "x"),
    ("1.5 x", "3*x/2"),
    ("D[x^2 Sin[x], x]", "x^2*cos(x) + 2*x*sin(x)"),
    ("D[Sqrt[x^2 + 1], x]", "x/sqrt(x^2 + 1)"),
    ("D[x^x, x]", "x^x*(log(x) + 1)"),
    ("D[f[x]^2, x]", "2*f(x)*f'(x)"),
    ("D[x^3, {x, 2}]", "6*x"),
    ("Integrate[x Exp[x], x]", "x*E^x - E^x"),
    ("Integrate[x Cos[x^2], x]", "sin(x^2)/2"),
    ("Integrate[1/(x^2 + x + 1), x]", "2*atan((2*x + 1)/sqrt(3))/sqrt(3)"),
    ("Integrate[Log[x], x]", "x*log(x) - x"),
    ("Integrate[Sin[x]^2, {x, 0, Pi}]", "Pi/2"),
    ("Integrate[x^2 Exp[-x], {x, 0, 1}]", "2 - 5/E"),
    ("Integrate[Exp[x^2], x]", "Integrate(E^(x^2), x)"),
    ("Solve[x^2 - 5 x + 6 == 0, x]", "{{x -> 2}, {x -> 3}}"),
    ("Solve[x^2 + x + 1 == 0, x]", "{{x -> -1/2 - I*sqrt(3)/2}, {x -> -1/2 + I*sqrt(3)/2}}"),
    ("Solve[a x^2 + b x + c == 0, x]",
     "{{x -> (-b - sqrt(b^2 - 4*a*c))/(2*a)}, {x -> (sqrt(b^2 - 4*a*c) - b)/(2*a)}}"),
    ("Solve[Exp[2 x] - 3 Exp[x] + 2 == 0, x]", "{{x -> 0}, {x -> log(2)}}"),
    ("Solve[Sin[x] == 1/2, x]", "{{x -> Pi/6}, {x -> 5*Pi/6}}"),
    ("Solve[x^5 - x - 1 == 0, x]", "{{x -> 1.167303978}}"),
    ("Solve[{x + y == 3, x y == 2}, {x, y}]", "{{x -> 2, y -> 1}, {x -> 1, y -> 2}}"),
    ("Factor[x^6 - 1]", "(x - 1)*(x^2 + x + 1)*(x + 1)*(x^2 - x + 1)"),
    ("Factor[x^3 + y^3]", "(x + y)*(x^2 - x*y + y^2)"),
    ("Factor[x^4 + 4]", "(x^2 - 2*x + 2)*(x^2 + 2*x + 2)"),
    ("Factor[360]", "2^3*3^2*5"),
    ("Expand[(x + y)^3]", "x^3 + 3*x^2*y + 3*x*y^2 + y^3"),
    ("Simplify[Sin[x]^2 + Cos[x]^2]", "1"),
    ("Together[1/x + 1/(x + 1)]", "(2*x + 1)/(x*(x + 1))"),
    ("Apart[1/(x^2 - 1)]", "1/(2*(x - 1)) - 1/(2*(x + 1))"),
    ("N[Pi, 50]", "3.1415926535897932384626433832795028841971693993751"),
    ("N[2^100]", "1.2676506*10^30"),
    ("N[Exp[-20]]", "2.061153616*10^-9"),
    ("N[1 + I]", "1. + 1.*I"),
    ("N[x + Pi]", "x + 3.141592654"),
    ("Series[Exp[x], {x, 0, 5}]", "1 + x + x^2/2 + x^3/6 + x^4/24 + x^5/120 + O(x^6)"),
    ("Series[Tan[x], {x, 0, 7}]", "x + x^3/3 + 2*x^5/15 + 17*x^7/315 + O(x^8)"),
    ("Sum[k^2, {k, 1, n}]", "n*(n + 1)*(2*n + 1)/6"),
    ("Sum[2^k, {k, 0, n}]", "2^(n + 1) - 1"),
    ("Limit[Sin[x]/x, x -> 0]", "1"),
    ("Limit[(1 + 1/x)^x, x -> Infinity]", "E"),
    ("Limit[x Log[x], x -> 0]", "0"),
    ("FactorInteger[2^32 + 1]", "641*6700417"),
    ("Det[{{a, b}, {c, d}}]", "a*d - b*c"),
    ("Inverse[{{1, 2}, {3, 4}}]", "{{-2, 1}, {3/2, -1/2}}"),
    ("Eigenvalues[{{2, 1}, {1, 2}}]", "{1, 3}"),
    ("{{1, 2}, {3, 4}} . {{5}, {6}}", "{{17}, {39}}"),
    ("20!", "2432902008176640000"),
    ("f(x) := x^2 + 1", "f(x) is defined"),
    ("f(3)", "10"),
    ("a = 5", "5"),
    ("a^2 + x", "x + 25"),
    ("x^2 /. x -> 3", "9"),
    ("%", "9"),
    ("1/0", "error: division by zero"),
    ("Solve[x^2 ==", "error: that's not finished"),
]

# integrals checked by differentiating them: the difference from what
# was integrated, worked out at a point or two
INTEGRALS = """x^2 Exp[x] | x Cos[x^2] | Sin[x]^2 | Cos[x]^4 | Sin[2 x] Cos[3 x] | Tan[x]^2
| 1/(x^3 + 1) | x/(x^4 + 1) | (x^2 + 1)/(x^3 - x) | 1/(x (x + 1)^2) | 1/(x^2 + 1)^2 | 1/(x^2 - 2)
| x^2 Log[x] | ArcTan[x] | Exp[x]/(1 + Exp[x]) | Exp[2 x] Cos[3 x] | x Sqrt[x + 1] | Sqrt[1 - x^2]
| 1/Sqrt[x^2 + 1] | Sin[x]^2 Cos[x]^3 | x 2^x | (3 x + 2)^(1/3) | Exp[Sin[x]] Cos[x] | 1/(x Log[x])
| x^3 Cos[2 x] | Exp[x] (x + 1) | 1/(Exp[x] + Exp[-x]) | ArcTan[x]/(1 + x^2)"""


def egret_string(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("{", "\\{").replace("}", "\\}") + '"'


class Algebra(unittest.TestCase):
    def run_cas(self, program):
        out, status = host.run(host.lib("algebra.eg", "calculus.eg", "egretica.eg") + "\n" + program)
        self.assertEqual(status, 0, out)
        return out.splitlines()

    def test_lines(self):
        prog = ["def show(s)", "  try", "    print(calc(s).to_s)", "  catch e",
                '    print("error: " + e.message)', "  end", "end"]
        prog += [f"show({egret_string(line)})" for line, _ in CAS]
        out = self.run_cas("\n".join(prog) + "\n")
        for (line, want), got in zip(CAS, out):
            self.assertEqual(got, want, line)
        self.assertEqual(len(out), len(CAS))

    def test_integrals_differentiate_back(self):
        prog = ["def check(s)",
                '  x = sym("x")',
                "  f = calc(s)",
                "  r = integrate(f, x)",
                '  if r == nil then return print("none " + s) end',
                "  d = sub(deriv(r, x), f)",
                "  good = 0",
                "  for v in [37, 113, -61]",
                "    try",
                "      e = numval(d, 40, Map.new.tap_set(\"x\", (v << 40) / 100))",
                '      if e.abs > (1 << 16) then return print("wrong " + s + ": " + r.to_s) end',
                "      good += 1",
                "    catch err",
                "      nil",
                "    end",
                "  end",
                '  print(if good > 0 then "ok" else "unchecked " + s end)',
                "end"]
        cases = [c.strip() for c in INTEGRALS.split("|")]
        prog += [f"check({egret_string(c)})" for c in cases]
        out = self.run_cas("\n".join(prog) + "\n")
        self.assertEqual(out, ["ok"] * len(cases))


class Snapshots(unittest.TestCase):
    def test_one_bit_boots(self):
        s = run.Session(depth=0).boot()
        s.run(1)
        self.assertNotIn("error", s.output)
        self.assertEqual(s.m.depth, 0)
        # black and white, and both used
        self.assertEqual(set(s.rgb()), {0, 255})

    def test_layout(self):
        snap = snapshot.cold()
        self.assertEqual(snap[:8], b"HERONSNP")
        ram, vram, inp = struct.unpack("<3I", snap[124:136])
        self.assertEqual(len(snap), 1160 + ram + vram + inp)
        self.assertIn(b"DESK.run", snap[-inp:])


if __name__ == "__main__":
    unittest.main()
