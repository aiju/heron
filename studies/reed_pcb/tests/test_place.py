"""Reed's boards on the column grid (place.py): every chip in its package
with its pads' nets, the connectors at the back edge, a placement with
every chip in a box and nothing overlapping."""

import unittest

from heron.infra.pcb import packages
from heron.studies.pcb_columns import demo, footprints
from heron.studies.reed_pcb import place

NEEDS = "needs KiCad's footprints: heron pcb_columns fetch"


class Pinouts(unittest.TestCase):
    def test_22v10_plcc(self):
        p = packages.PINOUTS["22v10_plcc"]
        dip = packages.PINOUTS["22v10"]
        self.assertEqual(len(p), 28)
        self.assertEqual((p[1], p[13], p[27]), ("CLK", "GND", "VCC"))
        self.assertEqual(p[4], "I3")                  # IN/PD: DIP pin 4, PLCC pin 5
        self.assertEqual([p[n - 1] for n in (1, 8, 15, 22)], ["=VCC", "=GND", "=GND", "=GND"])
        self.assertEqual([x for n, x in enumerate(p, 1) if n not in (1, 8, 15, 22)], dip)

    def test_27c010(self):
        p, f = packages.PINOUTS["27c010"], packages.PINOUTS["flash"]
        self.assertEqual(p[0], "=VCC")
        self.assertEqual(p[1:], f[1:])

    def test_sram64k16(self):
        nums = packages.pin_numbers("sram64k16")
        self.assertEqual(len(packages.PINOUTS["sram64k16"]), 44)
        self.assertEqual((nums["VCC"], nums["GND"]), ([11, 34], [12, 33]))
        self.assertEqual({p for p in nums if p.startswith("IO")}, {f"IO{i}" for i in range(16)})
        self.assertEqual({p for p in nums if p[0] == "A"}, {f"A{i}" for i in range(16)})


@unittest.skipUnless(footprints.available(place.EXTRA), NEEDS)
class Board(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = place.build_board("ALU")

    def test_every_chip(self):
        nl = place.netlist("ALU")
        insts = {i.ref for i in nl.instances
                 if i.type.family != "fixture" and i.type.name != "din96"}
        chips = [p for p in self.b.parts.values() if p.kind == "chip"]
        covered = set()
        for p in chips:
            covered |= {p.ref} if p.ref in insts else {p.ref[:-1], p.ref[:-2] + p.ref[-1]}
        self.assertEqual(covered, insts)
        self.assertEqual(len(chips), place.estimate("ALU")[0])

    def test_sram_halves(self):
        p = self.b.parts["U_RFA01"]
        nums = packages.pin_numbers("sram64k16")
        self.assertEqual(p.nets[str(nums["IO0"])], "RAD0")
        self.assertEqual(p.nets[str(nums["IO8"])], "RAD8")
        self.assertEqual(p.nets[str(nums["LB"])], "GND")
        self.assertEqual(p.nets[str(nums["WE"])], "RFWEA_n")

    def test_gal_corners(self):
        p = self.b.parts["U_BYP"]
        self.assertEqual([p.nets.get(n) for n in ("1", "8", "15", "22", "28")],
                         ["VCC", "GND", "GND", "GND", "VCC"])

    def test_connectors_at_the_back(self):
        """On the long edge (233.35 mm), the backplane's: the pads within
        20 mm of it and on the board (the courtyard's mating face hangs
        over the edge), P1 above P2."""
        self.assertGreater(self.b.height, self.b.width)
        ys = {}
        for name in ("P1", "P2"):
            p = self.b.parts[name]
            for d in p.pads():
                if d.number:
                    self.assertTrue(self.b.width - 20 < d.x < self.b.width, (name, d.number))
                    self.assertTrue(0 < d.y < self.b.height, (name, d.number))
            ys[name] = p.y
        self.assertLess(ys["P1"], ys["P2"])
        self.assertEqual(self.b.parts["P1"].nets["a1"], "A0")


@unittest.skipUnless(footprints.available(place.EXTRA), NEEDS)
class Placed(unittest.TestCase):
    def test_places(self):
        b, pl, left = place.place("ALU", moves=2000)
        self.assertEqual(left, [])
        self.assertEqual(demo.check(b, pl)["problems"], [])


if __name__ == "__main__":
    unittest.main()
