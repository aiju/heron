"""The board flow on a small netlist: parts, placement, routing, the board
file there and back, and the checks, including that they catch what they
should. They need KiCad's libraries (footprints and symbols) and are
skipped without them."""

import os
import tempfile
import unittest

from heron.infra.hw.netlist import Netlist
from heron.infra.pcb import board as B
from heron.infra.pcb import check, copper, kicadlib, physical, place, router, sexpr, wires

needs_kicad = unittest.skipUnless(kicadlib.available(), "needs KiCad's libraries")


def small_netlist():
    """A counter whose outputs go through a buffer to a connector-free set
    of gates: enough nets, packages and fan-out to route."""
    nl = Netlist()
    nl.add("const", "X_K", HI="EN")
    nl.add("osc", "U_OSC", OUT="CK", params={"period_ps": 100_000})
    nl.add("163", "U_CNT", CLK="CK", CLR="RST_n", LOAD="VCC", ENP="EN", ENT="EN",
           A="GND", B="GND", C="GND", D="GND", QA="Q0", QB="Q1", QC="Q2", QD="Q3", RCO="CY")
    nl.add("541", "U_BUF", OE1="GND", OE2="GND",
           **{f"A{i + 1}": n for i, n in enumerate(["Q0", "Q1", "Q2", "Q3", "CY", "CK", "GND", "GND"])},
           **{f"Y{i + 1}": f"B{i}" for i in range(6)})
    nl.gate("00", ["B0", "B1"], "N01")
    nl.gate("00", ["B2", "B3"], "N23")
    nl.gate("00", ["N01", "N23"], "ALL")
    nl.gate("04", ["ALL"], "RST_n")
    nl.gate("08", ["B4", "B5"], "OUT")
    nl.finish()
    nl.check()
    return nl


def build(layers=2):
    nl = small_netlist()
    b = B.Board("small", 60.0, 45.0, layers=layers)
    for p in physical.parts(nl, "smd"):
        b.add(p)
    pl = place.Placer(b, halo=1.5)
    pl.global_place()
    assert not pl.legalize()
    pl.refine(moves=2000)
    place.place_decaps(b, side="B")
    b.add_planes()
    return nl, b


class Basics(unittest.TestCase):
    def test_sexpr_round_trip(self):
        text = '(a "b c" 1 2.5 (d (e f) "g\\"h"))'
        e = sexpr.parse(text)
        self.assertEqual(e, ["a", "b c", 1, 2.5, ["d", ["e", "f"], 'g"h']])
        self.assertEqual(sexpr.parse(sexpr.dump(e)), e)

    @needs_kicad
    def test_pinouts_agree_with_kicad(self):
        self.assertEqual(check.check_pinouts(), [])


@needs_kicad
class Flow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nl, cls.board = build(layers=2)
        cls.sol = router.route(cls.board)
        cls.dir = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.dir.name, "small.kicad_pcb")
        cls.board.write(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def read(self):
        return B.read_kicad(self.path)

    def test_routed(self):
        self.assertEqual(self.sol["failed"] + self.sol["unreachable"] + self.sol["conflicted"], [])

    def test_round_trip(self):
        def key(b):
            return sorted((p.part.ref, p.number, round(p.x, 3), round(p.y, 3), str(p.layers), p.net)
                          for p in b.pads())
        self.assertEqual(key(self.read()), key(self.board))

    def test_pads_match_netlist(self):
        self.assertEqual(check.compare(self.nl, self.read(), "smd"), [])

    def test_copper_connects_the_nets(self):
        # two layers, no planes: the supplies are routed like any net
        self.assertEqual(copper.check(self.read()), [])

    def test_compare_catches_a_swap(self):
        b = self.read()
        p = b.parts["U_CNT"]
        p.nets["14"], p.nets["13"] = p.nets["13"], p.nets["14"]      # QA and QB
        errs = check.compare(self.nl, b, "smd")
        self.assertTrue(any("Q0" in e for e in errs) and any("Q1" in e for e in errs), errs)

    def test_compare_catches_an_unexplained_part(self):
        b = self.read()
        b.parts["CU_CNT"].nets["1"] = "CK"
        self.assertTrue(any("CU_CNT" in e for e in check.compare(self.nl, b, "smd")))

    def test_copper_catches_an_open(self):
        b = self.read()
        net = "B4"
        b.tracks = [t for t in b.tracks if t[6] != net]
        self.assertIn(net, " ".join(copper.check(b)))

    def test_copper_catches_a_short(self):
        b = self.read()
        a = next(t for t in b.tracks if t[6] == "Q0")
        c = next(t for t in b.tracks if t[6] == "Q3" and t[0] == a[0])
        b.tracks.append((a[0], a[1], a[2], c[1], c[2], 0.127, "Q0"))
        self.assertTrue(any(e.startswith("short") for e in copper.check(b)))


@needs_kicad
class Keepouts(unittest.TestCase):
    def test_strips_stay_clear(self):
        nl = small_netlist()
        b = B.Board("small", 60.0, 45.0, layers=2)
        for p in physical.parts(nl, "smd"):
            b.add(p)
        # a strip along the top edge, which the parts and tracks keep out of
        b.add_keepout(0, 0, 60, 6, "guide")
        pl = place.Placer(b, region=(3.0, 6.0, 57.0, 42.0), halo=1.5)
        pl.global_place()
        self.assertEqual(pl.legalize(), [])
        pl.refine(moves=2000)
        place.place_decaps(b, side="B")
        b.add_planes()
        sol = router.route(b)
        self.assertEqual(sol["failed"] + sol["unreachable"] + sol["conflicted"], [])
        self.assertEqual(check.keepouts(b), [])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "k.kicad_pcb")
            b.write(path)
            rb = B.read_kicad(path)
        self.assertEqual([(k["name"], k["no"]) for k in rb.keepouts],
                         [("guide", ("tracks", "vias", "footprints"))])
        self.assertEqual(check.keepouts(rb), [])
        # a part moved into the strip is caught
        p = rb.parts["U_CNT"]
        p.place(p.x, 3.0, p.rot, p.side)
        self.assertTrue(any(e.startswith("U_CNT") for e in check.keepouts(rb)))


class Wires(unittest.TestCase):
    def test_each_load_has_its_own_flight_time(self):
        nl = small_netlist()
        insts = {i.ref: i for i in nl.instances}
        # Q0 (QA): the buffer 100 ps along, the connector 400; Q1 (QB): the
        # connector first, the buffer 400 ps along
        w = {"Q0": {"driver": ("U_CNT", "QA"), "length": 60.0, "pF": 10.0,
                    "loads": {("U_BUF", "A1"): 100, ("P1", "a1"): 400}},
             "Q1": {"driver": ("U_CNT", "QB"), "length": 60.0, "pF": 10.0,
                    "loads": {("U_BUF", "A2"): 400, ("P1", "a2"): 100}}}
        extra = wires.back_annotate(nl, w)
        self.assertEqual(extra, {("U_CNT", "QA"): 100, ("U_CNT", "QA", "off"): 300,
                                 ("U_CNT", "QB"): 100, ("U_BUF", "A2"): 300})
        wires.apply(nl, extra)          # no other cards: the connector's is left out
        self.assertEqual(insts["U_CNT"].pin_extra, {"QA": 100, "QB": 100})
        self.assertEqual(insts["U_BUF"].conn["A1"], "Q0")
        far = insts["U_BUF"].conn["A2"]
        wire = {i.ref: i for i in nl.instances}["W~U_BUF~A2"]
        self.assertEqual((wire.conn["A"], wire.conn["Y"], wire.pin_extra), ("Q1", far, {"Y": 300}))


@needs_kicad
class Grid(unittest.TestCase):
    def test_grid_placement(self):
        nl = small_netlist()
        b = B.Board("small", 60.0, 45.0, layers=2)
        for p in physical.parts(nl, "smd"):
            b.add(p)
        pl = place.GridPlacer(b, (8.25, 14.25), halo=0.8)
        pl.global_place()
        self.assertEqual(pl.legalize(), [])
        pl.refine(moves=2000)
        chips = [p for p in b.parts.values() if p.kind == "chip"]
        # every chip the same way round, in its own block of slots, centred
        # across it and at its top (with the room for its capacitor, if that
        # goes beside it)
        self.assertEqual({p.rot for p in chips}, {0})
        x0, y0, _, _ = pl.region
        taken = set()
        for p in chips:
            nc, nr, _, _ = pl.spans[p.ref]
            c, r = pl.where[p.ref]
            bx0, by0, bx1, by1 = pl._box(p)
            self.assertAlmostEqual((bx0 + bx1) / 2, x0 + (c + nc / 2) * pl.px, places=6)
            self.assertAlmostEqual(by0, y0 + r * pl.py + pl.halo / 2, places=6)
            self.assertLessEqual(c + nc, pl.ncol)
            self.assertLessEqual(r + nr, pl.nrow)
            cells = {(c + i, r + j) for i in range(nc) for j in range(nr)}
            self.assertFalse(cells & taken, p.ref)
            taken |= cells


if __name__ == "__main__":
    unittest.main()
