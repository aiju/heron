"""Reed's netlist: every board builds and checks, the backplane's lines
have one driver each, and every board fits a double Eurocard."""

import unittest

from heron.studies.reed import bus, fields, hw, system


class TestReed(unittest.TestCase):
    def test_machine_checks(self):
        system.check(system.machine(sim=True))

    def test_boards_fit(self):
        for name, s in system.stats().items():
            # (RFC 0049's B1: 70 units of area a board)
            self.assertLessEqual(s["area"], 70, name)

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
            self.assertEqual(m.regs(), list(ref.r[:16]), name)
            self.assertEqual(bytes(m.ram[:0x10000]), bytes(ref.mem[a] for a in range(0x10000)), name)

    def test_model_in_lockstep_with_chip_level(self):
        for name, n, bad in hw.lockstep(["queue"]):
            self.assertGreater(n, 40)
            self.assertEqual(bad, [], name)


class TestMicrocode(unittest.TestCase):
    def test_every_family_against_the_reference(self):
        from heron.studies.reed import fuzz
        res = fuzz.fuzz(n=40, seed=3)
        self.assertEqual({k: v for k, v in res.items() if v}, {})


class TestSystem(unittest.TestCase):
    def test_systest_against_the_reference(self):
        """sw/systest.s: RFC 0029's system half on the model and on draft 2's
        system simulator, the same output, exception log, pages and banks."""
        from heron.studies.reed import systest
        img, ram = systest.image()
        ref, status = systest.run_reference(ram)
        m = systest.run_model(ram)
        self.assertEqual(status, "halted")
        self.assertEqual(m.stopped, "halt")
        self.assertEqual(systest.compare(ref, m), [])

    def test_systest_at_chip_level(self):
        """sw/systest.s at chip level in lockstep with the model, every
        cycle to its HALT: user mode, faults, the page map, the banks."""
        from heron.studies.reed import hw, systest
        img, ram = systest.image()
        n, first = hw.lockstep_image(bytearray(ram), 20_000)
        self.assertGreater(n, 15_000)
        self.assertIsNone(first)

    def test_interrupt_at_chip_level(self):
        """sw/irqtest.s: the timer's interrupt at level 6 through the IO
        board's controller, the same log at chip level as on the model."""
        import os
        from heron.studies.reed import hw, model, systest, ucode
        img, ram = systest.image(os.path.join(os.path.dirname(systest.__file__), "sw", "irqtest.s"))
        prog = ucode.build()
        m = model.Model(bytes(ram), prog=prog)
        self.assertEqual(m.run(400_000), "halt")
        r = hw.run(bytearray(ram), prog, max_cycles=20_000)
        self.assertEqual(r["stopped_at"], "halt")
        log = lambda mem: bytes(mem[0x10000:0x10014])
        self.assertEqual(log(r["ram"]), log(m.ram))
        self.assertEqual(int.from_bytes(log(m.ram)[4:8], "little"), 0x86000006)

    def test_user_interrupts_at_chip_level(self):
        """sw/irquser.s: a user-mode loop in bank 1 with the page map on,
        the timer interrupting it, the same sum at chip level as on the
        model (the interrupts' count is the timer's)."""
        import os
        from heron.studies.reed import hw, model, systest, ucode
        img, ram = systest.image(os.path.join(os.path.dirname(systest.__file__), "sw", "irquser.s"))
        prog = ucode.build()
        m = model.Model(bytes(ram), prog=prog)
        self.assertEqual(m.run(3_000_000), "halt")
        r = hw.run(bytearray(ram), prog, max_cycles=200_000)
        self.assertEqual(r["stopped_at"], "halt")
        word = lambda mem, i: int.from_bytes(bytes(mem[0x10000 + 4 * i:0x10004 + 4 * i]), "little")
        self.assertEqual(word(m.ram, 2), 0x600D)
        self.assertEqual(word(r["ram"], 2), 0x600D)
        self.assertEqual(word(r["ram"], 0), word(m.ram, 0))
        self.assertGreater(word(r["ram"], 1), 10)
