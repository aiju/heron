"""The design explorer's hierarchy: every chip and gate of the netlist has
one place in it, and every section is in a unit."""

import unittest

import heron.studies.v2_isa  # noqa: F401
from heron.infra.hw import schematic
from heron.studies.v2_hw import explore, parts


class Hierarchy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        nl, lines = explore.capture()
        cls.nl = nl
        cls.model = schematic.model(nl, "Draft 2 CPU", variant=parts.VARIANT)
        cls.nodes, _ = explore.hierarchy(nl, lines, cls.model)

    def test_every_symbol_once(self):
        seen = [c for n in self.nodes.values() if n["kind"] != "symbol" for c in n["children"]
                if c in self.model["symbols"]]
        self.assertEqual(sorted(seen), sorted(self.model["symbols"]))

    def test_sections_in_units(self):
        units = {s for _, _, _, secs in explore.UNITS for s in secs}
        self.assertEqual({name for _, name in self.nl.sections} - units, set())

    def test_blocks_named(self):
        for n in self.nodes.values():
            if n["kind"] == "block":
                self.assertTrue(n["name"] and len(n["name"]) <= 40, n)
