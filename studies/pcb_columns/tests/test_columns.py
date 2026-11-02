import unittest

from heron.infra.pcb import board as B

from .. import footprints
from ..grid import ROW, Lattice, Params, box, dip_footprint, orientation
from ..placer import GridPlacer

NEEDS = "needs KiCad's footprints (installed, or `heron pcb_columns fetch`)"


def _part(ref, fp, nets=None):
    return B.Part(ref, fp, nets or {})


@unittest.skipUnless(footprints.available(), NEEDS)
class TestBoxes(unittest.TestCase):
    def setUp(self):
        footprints.use()

    def size(self, fp, **kw):
        bx = box(_part("X", fp), Params(**kw))
        return bx.w, bx.h

    def test_dips(self):
        self.assertEqual(self.size("Package_DIP:DIP-14_W7.62mm"), (1, 8))
        self.assertEqual(self.size("Package_DIP:DIP-20_W7.62mm"), (1, 11))
        self.assertEqual(self.size("Package_DIP:DIP-24_W15.24mm"), (2, 13))
        self.assertEqual(self.size("Package_DIP:DIP-24_W15.24mm", gap=3), (2, 14))
        self.assertEqual(self.size("Package_DIP:DIP-14_W7.62mm", module=5), (1, 10))
        self.assertEqual(self.size("Package_DIP:DIP-20_W7.62mm", module=5), (1, 15))

    def test_other_packages(self):
        # a SOJ-28's courtyard fits a half-column, a PLCC socket's doesn't
        self.assertEqual(self.size("Package_SO:SOJ-28_7.62x18.415mm_P1.27mm"), (1, 9))
        self.assertEqual(self.size("Package_LCC:PLCC-32_THT-Socket"), (2, 10))
        self.assertEqual(self.size("Oscillator:Oscillator_DIP-14"), (2, 10))
        self.assertEqual(self.size("Oscillator:Oscillator_DIP-14", half=6), (1, 10))

    def test_orientation(self):
        # the can lies along x in KiCad's library: turned down the column,
        # pin 1 at the top left
        p = _part("X", "Oscillator:Oscillator_DIP-14")
        self.assertEqual(orientation(p.fp), 270)
        p.place(0, 0, 270)
        pads = {d.number: (d.x, d.y) for d in p.pads()}
        self.assertEqual(min(pads.values(), key=lambda xy: (round(xy[1], 3), round(xy[0], 3))),
                         pads["1"])
        self.assertEqual(orientation(_part("Y", "Package_DIP:DIP-16_W7.62mm").fp), 0)

    def test_centred_on_the_lattice(self):
        bx = box(_part("X", "Package_DIP:DIP-14_W7.62mm"), Params())
        self.assertAlmostEqual(bx.dx, ROW)          # pin 1 a row from the box's left
        self.assertAlmostEqual(bx.dy, ROW)          # and from its top
        self.assertEqual(bx.pitch, (ROW, ROW))
        # in a half-column of 0.4 inch a 0.3 inch DIP can't be centred on
        # the 0.1 inch lattice without leaving its box: 0.05 inch it is
        bx = box(_part("X", "Package_DIP:DIP-14_W7.62mm"), Params(half=4))
        self.assertAlmostEqual(bx.dx, ROW / 2)
        self.assertEqual(bx.pitch, (ROW / 2, ROW))

    def test_pad_styles(self):
        self.assertEqual(dip_footprint("Package_DIP:DIP-14_W7.62mm", "long"),
                         "Package_DIP:DIP-14_W7.62mm_LongPads")
        self.assertEqual(dip_footprint("Package_DIP:DIP-14_W7.62mm_Socket", "round"),
                         "Package_DIP:DIP-14_W7.62mm")
        self.assertEqual(dip_footprint("Package_DIP:DIP-14_W7.62mm_LongPads", "socket-long"),
                         "Package_DIP:DIP-14_W7.62mm_Socket_LongPads")

    def test_parameters(self):
        with self.assertRaises(ValueError):
            Params(half=3)
        with self.assertRaises(ValueError):
            Params(gap=1)


class TestLattice(unittest.TestCase):
    def test_lattice(self):
        lat = Lattice((8.0, 5.0, 140.0, 228.35), Params())
        self.assertEqual((lat.cols, lat.rows), (5, 87))
        for v in (lat.x, lat.y):
            self.assertAlmostEqual(v / ROW, round(v / ROW))
        self.assertGreaterEqual(lat.x, 8.0)
        self.assertLessEqual(lat.x + lat.width, 140.0)
        lat = Lattice((8.0, 5.0, 140.0, 228.35), Params(module=5))
        self.assertEqual(lat.rows % 5, 0)


@unittest.skipUnless(footprints.available(), NEEDS)
class TestPlacer(unittest.TestCase):
    def setUp(self):
        footprints.use()

    def board(self, params):
        b = B.Board("t", 80.0, 112.0)
        fps = (["Package_DIP:DIP-24_W15.24mm"] * 2 + ["Package_DIP:DIP-14_W7.62mm"] * 4
               + ["Package_DIP:DIP-16_W7.62mm"] * 3 + ["Package_SO:SOJ-28_7.62x18.415mm_P1.27mm"])
        for i, fp in enumerate(fps):
            # a chain of nets from each chip to the next
            nets = {"1": f"N{i}", "2": f"N{i + 1}"}
            b.add(B.Part(f"U{i}", fp, nets))
        return b

    def check(self, params, tidy=True):
        b = self.board(params)
        pl = GridPlacer(b, (2.0, 2.0, 78.0, 110.0), params, seed=3)
        self.assertEqual(pl.run(moves=3000, tidy=tidy), [])
        cells = set()
        for ref, (hc, row) in pl.pos.items():
            bx = pl.boxes[ref]
            if bx.w == 2:
                self.assertEqual(hc % 2, 0, f"{ref} straddles two columns")
            self.assertEqual(row % params.module, 0)
            mine = {(i, j) for i in range(hc, hc + bx.w) for j in range(row, row + bx.h)}
            self.assertFalse(mine & cells, f"{ref} overlaps")
            cells |= mine
            # every pin of a DIP on the lattice
            if b.parts[ref].fp.name.startswith("Package_DIP:"):
                for d in b.parts[ref].pads():
                    self.assertAlmostEqual((d.x - pl.lat.x) / ROW, round((d.x - pl.lat.x) / ROW))
                    self.assertAlmostEqual((d.y - pl.lat.y) / ROW, round((d.y - pl.lat.y) / ROW))
        return pl

    def test_places(self):
        self.check(Params())
        self.check(Params(module=5))
        self.check(Params(), tidy=False)

    def test_tidy_is_stacked(self):
        # every box as high in its column as the boxes above it allow: the
        # placement is the stacking of its own stacks
        pl = self.check(Params())
        for c, items in enumerate(pl.stacks()):
            pos, _ = pl._stack(c, items)
            for ref, at in pos.items():
                self.assertEqual(pl.pos[ref], at)

    def test_wide_box_swaps_with_two_narrow_ones(self):
        b = self.board(Params())
        pl = GridPlacer(b, (2.0, 2.0, 78.0, 110.0), Params())
        pl._set("U0", 0, 0)          # a 74181's box: two half-columns by 13 rows
        pl._set("U2", 2, 0)          # two DIP-14s side by side: 8 rows each
        pl._set("U3", 3, 0)
        moves = pl._move("U0", 2, 0)
        self.assertEqual(moves, {"U0": (2, 0), "U2": (0, 0), "U3": (1, 0)})
        pl._set("U4", 2, 8)          # a DIP-14 sticking out of the 74181's box below
        self.assertIsNone(pl._move("U0", 2, 0))
