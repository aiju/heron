"""The formal study's tools: the specification against the simulator, the
symbolic simulator on known values against the RTL model, and a few
proofs (and one that must fail)."""

import random
import unittest

try:
    import z3  # noqa: F401
except ImportError:
    z3 = None


@unittest.skipIf(z3 is None, "needs z3 (pip install z3-solver)")
class Spec(unittest.TestCase):
    def test_parses(self):
        from heron.studies.formal import spec as S
        sp = S.load("v1b.isa")
        self.assertGreater(len(sp.instructions), 50)

    def test_against_simulator(self):
        from heron.studies.formal import isacheck, spec as S
        sp = S.load("v1b.isa")
        rng = random.Random(3)
        bad = [r for r in (isacheck.run_one(sp, rng) for _ in range(400)) if r]
        self.assertEqual(bad, [])

    def test_language(self):
        from heron.studies.formal import spec as S
        sp = S.Spec("""
register x : 8
flag F
fn step():
    let a = x ++ x[3:0]
    if a[11] == 1:
        F := 1
    x := a[7:0] + 0x10
fn enter(v, ret):
    pass
""")
        st = S.State(sp, {"x": S.mk(8, 0x9A), "F": S.mk(1, 0)}, {})
        sp.step(st)
        self.assertEqual((st.regs["x"].x, st.regs["F"].x), (0xBA, 1))


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
        from heron.studies.formal import spec as S, v1b
        p = v1b.Prover(self.case("ea 4 None 1 3"))
        src = open(S.HERE + "/v1b.isa").read().replace(
            "    r[d] := add(r[d], x, 0)", "    r[d] := add(r[d], ~x, 1)")
        p.spec = S.Spec(src)
        r = p.prove()
        self.assertEqual(r.status, "fail")
        self.assertRegex(r.paths[0][2], r"\br([1-9]|1[0-5])\b")     # whichever rd the model picks


@unittest.skipIf(z3 is None, "needs z3 (pip install z3-solver)")
class Generated(unittest.TestCase):
    def test_every_goal_of_rrc_reached(self):
        """RRC's decisions (N and Z, C from bit 0, V cleared): every
        outcome is reached by a generated case, and the simulator agrees."""
        from heron.studies.formal import isacheck, isagen, spec as S
        sp = S.load("v1b.isa")
        ins = next(i for i in sp.instructions if i.syntax.startswith("RRC"))
        status, cases = isagen.generate(sp, ins, 1, random.Random(2))
        took = set()
        for _, (r, hi, fl, pc, image) in cases:
            self.assertIsNone(isacheck.compare(sp, r, hi, fl, pc, image, record=took))
        reached = {(site, o) for (i, site, o) in took if i == ins.line}
        self.assertTrue(status)
        self.assertEqual({k for k, v in status.items() if v == "missed"} - reached, set())
