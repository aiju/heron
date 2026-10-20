"""The board placed on RFC 0046's column grid (place.py): every part in its
package, the connectors on the edges, every chip in a box, nothing
overlapping."""

import unittest

from heron.studies.chibi import place
from heron.studies.pcb_columns import demo, footprints


class Packages(unittest.TestCase):
    def test_plcc28(self):
        nl = place.netlist()
        gal = next(i for i in nl.instances if i.type.name == "22v10")
        fp, pads, _ = place.chip_package(gal)
        self.assertEqual(fp, place.PLCC28)
        self.assertEqual((pads["14"], pads["28"], pads["2"]), ("GND", "VCC", "CLK"))
        self.assertFalse({"1", "8", "15", "22"} & set(pads))


@unittest.skipUnless(footprints.available(place.EXTRA),
                     "needs KiCad's footprints: heron pcb_columns fetch")
class Placed(unittest.TestCase):
    def test_places(self):
        b, pl, left = place.place((340.0, 300.0), moves=3000)
        self.assertEqual(left, [])
        nl = place.netlist()
        refs = {p.ref.split(".")[0] for p in b.parts.values()}
        for inst in nl.instances:
            if inst.type.family != "fixture":
                self.assertIn(inst.ref, refs)
        self.assertEqual(set(pl.pos), {p.ref for p in pl.chips})
        res = demo.check(b, pl)
        self.assertEqual(res["problems"], [])
        for p in b.parts.values():
            x0, y0, x1, y1 = p.courtyard()
            self.assertTrue(x0 >= -1e-6 and y0 >= -1e-6 and x1 <= b.width + 1e-6
                            and y1 <= b.height + 1e-6, p.ref)


if __name__ == "__main__":
    unittest.main()
