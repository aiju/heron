"""Reed's netlist: every board builds and checks, the backplane's lines
have one driver each, and every board fits a double Eurocard."""

import unittest

from heron.studies.reed import bus, fields, hw, system


class TestReed(unittest.TestCase):
    def test_machine_checks(self):
        system.check(system.machine(sim=True))

    def test_boards_fit(self):
        for name, s in system.stats().items():
            self.assertLessEqual(s["area"], 70, name)
            self.assertLessEqual(s["packages"], 72, name)

    def test_backplane_pins(self):
        m = bus.pin_map()
        nets = set(m["P1"].values()) | set(m["P2"].values())
        for line in bus.CONTROL:
            self.assertIn(line, nets)
        for n in bus.A + bus.B:
            self.assertIn(n, nets)

    def test_fields_fit_their_parts(self):
        for board, fl in fields.SLICES.items():
            self.assertLessEqual(sum(w for _, w in fl), 8 * fields.PARTS[board], board)


    def test_microcode_builds(self):
        from heron.studies.reed import ucode
        p = ucode.build()
        imgs = ucode.images(p)
        self.assertEqual(len(imgs), sum(fields.PARTS.values()) + 2)

    def test_smoke_at_chip_level(self):
        """A small program on the whole machine's netlist, against the draft
        2 simulator (hw.smoke)."""
        from heron.studies.reed import hw
        ok, rep = hw.smoke()
        self.assertTrue(ok, rep)


    def test_chip_level_gate(self):
        """Every program at both corners and three seeds (hw.check)."""
        from heron.studies.reed import hw
        ok, lines = hw.check()
        self.assertTrue(ok, "\n".join(lines))


if __name__ == "__main__":
    unittest.main()


class TestModel(unittest.TestCase):
    def test_programs_against_the_reference(self):
        from heron.infra import asm as asmcore, isas
        from heron.studies.reed import model
        for name, text in hw.programs().items():
            img = asmcore.assemble_text(isas.get("v2"), text, name=f"{name}.s")
            m = model.run_image(img, max_cycles=100_000)
            ref = hw.reference(img)
            self.assertEqual(m.stopped, "halt", name)
            self.assertEqual(m.rf[:16], list(ref.r[:16]), name)
            self.assertEqual(bytes(m.ram[:0x10000]), bytes(ref.mem[a] for a in range(0x10000)), name)

    def test_model_in_lockstep_with_chip_level(self):
        for name, n, bad in hw.lockstep(["queue"]):
            self.assertGreater(n, 40)
            self.assertEqual(bad, [], name)
