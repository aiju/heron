"""The formal study's tools: the specification against the simulator, the
symbolic simulator on known values against the RTL model, and a few
proofs (and one that must fail)."""

import random
import unittest

try:
    import z3  # noqa: F401
except ImportError:
    z3 = None


LANGUAGE = """
register x: u8
register r[4]: u32
flag F
memory mem[u32]: u8
const K = 8'h10
enum Size { Byte, Half }
record Pair { a: u8, b: bool }
proc enter(vector: u32, ret: u32) {
}
"""

MISTAKES = [
    ("state without @", "proc step() {\n x := 1\n}", "write @x"),
    ("a fn changing state", "fn f() -> u8 {\n @x := 1\n return 1\n}\nproc step() {\n}",
     "only a proc"),
    ("a proc in an expression",
     "proc g() -> u8 {\n return 1\n}\nproc step() {\n @x := g() + 1\n}", "inside an expression"),
    ("a value dropped", "fn f() -> u8 {\n return 1\n}\nproc step() {\n f()\n}", "thrown away"),
    ("u8 into u32", "proc step() {\n @r[0] := @x\n}", "a u8 where a u32"),
    ("a number too wide", "proc step() {\n @x := 256\n}", "doesn't fit"),
    ("a sized number of the wrong width", "proc step() {\n @x := 16'h10\n}", "a u16 where a u8"),
    ("a sized number too big", "proc step() {\n @x := 8'h100\n}", "doesn't fit"),
    ("a bit for a bool", "proc step() {\n @F := @x[0]\n}", "a u1 where a bool"),
    ("a bool for a number", "proc step() {\n @x := @x + @F\n}", "a u8 and a bool"),
    ("&& with ||", "proc step() {\n @F := @F && @F || @F\n}", "parentheses"),
    ("& with +", "proc step() {\n @x := @x & 3 + 1\n}", "parentheses"),
    ("<< with +", "proc step() {\n @x := @x << 1 + 1\n}", "parentheses"),
    ("a == b == c", "proc step() {\n @F := @x == @x == @F\n}", "parentheses"),
    ("two parameters of a type, by position",
     "fn f(a: u8, b: u8) -> u8 {\n return a - b\n}\nproc step() {\n @x := f(1, 2)\n}",
     "name its arguments"),
    ("a path without a return", "fn f(a: u8) -> u8 {\n if a == 0 {\n return 1\n }\n}\nproc step() {\n}",
     "without returning"),
    ("a match that misses a value",
     "proc step() {\n match @x[1:0] {\n 0 => @F := true\n 1 => @F := false\n }\n}", "doesn't cover"),
    ("a match that misses a variant",
     "fn f(s: Size) -> u8 {\n return match s { Size.Byte => 1 }\n}\nproc step() {\n}", "doesn't cover"),
    ("a value matched twice",
     "proc step() {\n match @x[0] {\n 0 => @F := true\n 0 => @F := false\n _ => {}\n }\n}", "twice"),
    ("shadowing", "proc step() {\n let a = @x\n if @F {\n let a = @x\n }\n}", "no shadowing"),
    ("a let changed", "proc step() {\n let a = @x\n a := 1\n}", "make it a var"),
    ("a record without a field", "fn f() -> Pair {\n return Pair { a: 1 }\n}\nproc step() {\n}",
     "missing b"),
    ("a slice outside its value", "proc step() {\n @x := @x[8:1]\n}", "slice"),
    ("a shift that leaves nothing", "proc step() {\n @x := @x << 8\n}", "leaves nothing"),
    ("a const without a type", "const J = 3\nproc step() {\n}", "give it a type"),
    ("a local with a global name", "proc step() {\n let K = 1\n}", "global name"),
    ("ordering bools", "proc step() {\n @F := @F < @F\n}", "compares uN"),
    ("a loop over bare numbers", "proc step() {\n for i in 0 ..= 3 {\n }\n}", "give one a type"),
    ("an if on a number", "proc step() {\n if @x {\n }\n}", "a u8 where a bool"),
    ("a fault in a fn", "fn f() -> u8 {\n fault 32'h8\n}\nproc step() {\n}", "only a proc"),
]


@unittest.skipIf(z3 is None, "needs z3 (pip install z3-solver)")
class Spec(unittest.TestCase):
    def test_parses(self):
        from heron.studies.formal import spec2 as S
        sp = S.load("v1b_new.isa")
        self.assertGreater(len(sp.instructions), 50)

    def test_against_simulator(self):
        from heron.studies.formal import isacheck, spec2 as S
        sp = S.load("v1b_new.isa")
        rng = random.Random(3)
        bad = [r for r in (isacheck.run_one(sp, rng) for _ in range(400)) if r]
        self.assertEqual(bad, [])

    def test_language(self):
        from heron.studies.formal import spec2 as S
        sp = S.Spec(LANGUAGE + """
proc step() {
    let a = @x ++ @x[3:0]
    if a[11] == 1 {
        @F := true
    }
    @x := a[7:0] + 8'h10
}
""")
        st = S.State(sp, {"x": S.mk(8, 0x9A), "F": False, "r": [S.mk(32, 0)] * 4},
                     {"mem": S.ConcreteMemory(32, 8)})
        sp.step(st)
        self.assertEqual((st.regs["x"].x, st.regs["F"]), (0xBA, True))

    def test_mistakes_rejected(self):
        """Each slip the language is meant to catch is an error when the
        specification is loaded, saying what is wrong."""
        from heron.studies.formal import spec2 as S
        good = """proc step() {
    let a: u8 = 3
    var b = @x ++ a
    b := b + 1
    @F := b[15] == 1 && (a == 3 || @F)
    @x := b[7:0] & ~K
}"""
        S.Spec(LANGUAGE + good)
        for what, src, want in MISTAKES:
            with self.subTest(what):
                with self.assertRaisesRegex(S.SpecError, want):
                    S.Spec(LANGUAGE + src)


@unittest.skipIf(z3 is None, "needs z3 (pip install z3-solver)")
class Netlist(unittest.TestCase):
    def test_hello_in_lockstep_with_rtl(self):
        from heron.infra import asm as asmcore, isas
        from heron.studies.v1_isa.testing import program_paths
        from heron.studies.v1b_hw.rtl import RTL
        from heron.studies.formal import v1b
        path = program_paths(["hello"], "v1b")[0]
        img = asmcore.assemble_file(isas.get("v1b"), path)
        r, sim = RTL(img), v1b.concrete(img)
        while not r.halted:
            got = v1b.read_regs(sim)
            for k, v in (("R", r.R), ("T", r.T), ("PC", r.PC), ("IR", r.IR), ("MAR", r.MAR),
                         ("N", r.n), ("Z", r.z), ("C", r.c), ("V", r.v)):
                self.assertEqual(got[k], v, f"{k} in cycle {sim.cycle}")
            r.step()
            sim.step()
        self.assertEqual(bytes(sim.models["X_IO"].dev.out), b"Hello, world!\n")
        self.assertEqual(v1b.read_rf(sim, "A"), r.rf)
        self.assertEqual(v1b.read_rf(sim, "B"), r.rf)


@unittest.skipIf(z3 is None, "needs z3 (pip install z3-solver)")
class Proofs(unittest.TestCase):
    def case(self, key):
        from heron.studies.formal import v1b
        return next(c for c in v1b.cases() if c.name() == key)

    def test_nop_mov_add(self):
        from heron.studies.formal import v1b
        for key in ("sys 1 0 0", "ea 1 None 0 None", "ea 4 None 1 3"):
            r = v1b.prove_case(self.case(key))
            self.assertEqual(r.status, "proved", (key, r.paths, r.error))

    def test_reset(self):
        from heron.studies.formal import v1b
        r = v1b.prove_reset()
        self.assertEqual(r.status, "proved", (r.paths, r.error))

    def test_wrong_spec_fails(self):
        """ADD rd, #3 specified as a subtraction: the proof must fail, naming rd."""
        from heron.studies.formal import spec2 as S, v1b
        p = v1b.Prover(self.case("ea 4 None 1 3"))
        right = "    @r[d] := nzcv(add(a: @r[d], b: x, carry: false))"
        src = open(S.HERE + "/v1b_new.isa").read()
        self.assertIn(right, src)
        p.spec = S.Spec(src.replace(right, "    @r[d] := nzcv(add(a: @r[d], b: ~x, carry: true))"))
        r = p.prove()
        self.assertEqual(r.status, "fail")
        self.assertRegex(r.paths[0][2], r"\br([1-9]|1[0-5])\b")     # whichever rd the model picks


@unittest.skipIf(z3 is None, "needs z3 (pip install z3-solver)")
class Generated(unittest.TestCase):
    def test_every_goal_of_rrc_reached(self):
        """RRC's decisions (N and Z, C from bit 0, V cleared): every
        outcome is reached by a generated case, and the simulator agrees."""
        from heron.studies.formal import isacheck, isagen, spec2 as S
        sp = S.load("v1b_new.isa")
        ins = next(i for i in sp.instructions if i.syntax.startswith("RRC"))
        status, cases = isagen.generate(sp, ins, 1, random.Random(2))
        took = set()
        for _, (r, hi, fl, pc, image) in cases:
            self.assertIsNone(isacheck.compare(sp, r, hi, fl, pc, image, record=took))
        reached = {(site, o) for (i, site, o) in took if i == ins.line}
        self.assertTrue(status)
        self.assertEqual({k for k, v in status.items() if v == "missed"} - reached, set())
