"""Heron Mini on three boards (boards.py): every chip on a board, the
limits, the connectors, a board's netlist and its export, the boards'
delays on the timing analysis's netlist."""

import os
import tempfile
import unittest
from collections import Counter

import heron.studies.v2_isa  # noqa: F401
from heron.studies.mini import board, boards, parts


class Assignment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = boards.default()

    def test_every_chip_on_a_board(self):
        nl = self.a.nl
        for inst in nl.instances:
            if boards.kind(inst) == "fixture":
                self.assertNotIn(inst.ref, self.a.board_of)
            else:
                self.assertIn(self.a.board_of.get(inst.ref), boards.BOARDS, inst.ref)
        self.assertEqual(self.a.warnings, [])

    def test_limits(self):
        cpu = sum(self.a.packages(b) for b in boards.CPU)
        for b in boards.BOARDS:
            self.assertLessEqual(self.a.packages(b), boards.TARGET, b)
            if b in boards.CPU:
                self.assertGreaterEqual(self.a.packages(b), boards.CPU_BALANCE * cpu - 1, b)

    def test_cpu_on_its_boards(self):
        # a chip of one section (not a gate package) stays in its section's boards
        gates = boards.gate_sections(self.a.nl)
        for ref, b in self.a.board_of.items():
            sec = self.a.nl.refs[ref].section
            if ref not in gates and sec in boards.SECTIONS:
                self.assertIn(b, boards.SECTIONS[sec][1], (ref, sec))

    def test_deterministic(self):
        nl = board.build(sim=True)
        x = boards.assign(nl, chains=1, restarts=3)
        y = boards.assign(nl, chains=1, restarts=3)
        self.assertEqual(x.board_of, y.board_of)

    def test_unknown_sections(self):
        nl = board.build(sim=True)
        nl.refs["U_PIT"].section = "Video sprites"      # a video word: on io
        nl.refs["U_CS0"].section = "Frobnicator"        # where its nets go
        a = boards.assign(nl, chains=1, restarts=2)
        self.assertEqual(a.board_of["U_PIT"], "io")
        self.assertIn(a.start["U_CS0"], boards.CPU)
        self.assertTrue(any("Video sprites" in w for w in a.warnings))
        self.assertTrue(any("Frobnicator" in w for w in a.warnings))
        on = [r for r in nl.refs if boards.kind(nl.refs[r]) != "fixture"]
        self.assertTrue(all(r in a.board_of for r in on))


class Connectors(unittest.TestCase):
    def test_pack(self):
        nets = [f"S{i}" for i in range(70)] + ["CLK"]
        for header, per in ((64, 1), (50, 2), (40, 3)):
            conns = boards.pack(nets, header, per)
            wires = [w for c in conns for w in c]
            self.assertTrue(all(len(c) == header and c[0] == "GND" for c in conns))
            self.assertEqual(Counter(w for w in wires if w != "GND"), Counter(nets))
            for c in conns:
                run = 0
                for k, w in enumerate(c):
                    run = 0 if w == "GND" else run + 1
                    self.assertLessEqual(run, per)
                    if w == "CLK":
                        self.assertEqual((c[k - 1], c[k + 1]), ("GND", "GND"))
        # 32 signals a 64-pin header, with a ground between each
        self.assertEqual([len(boards.pack(nets[:n], 64, 1)) for n in (32, 33, 64, 65)],
                         [1, 2, 2, 3])

    def test_every_crossing_signal_on_a_connector(self):
        a = boards.default()
        cross = boards.crossing(a)
        conns = boards.connectors(a)
        for b in boards.BOARDS:
            on = {n for c in conns if c["board"] == b for n in c["pinmap"].values()} - {"GND"}
            self.assertEqual(on, {n for n, by in cross.items() if b in by}, b)


class Export(unittest.TestCase):
    def test_board_netlists(self):
        a = boards.default()
        refs = set()
        for b in boards.BOARDS:
            nl = boards.netlist(b)
            refs |= set(nl.refs)
            bus = {n[4:] for i in nl.instances for n in i.conn.values() if n.startswith("BUS.")}
            on = {n for _, _, m in nl.connectors for n in m.values()} - {"GND"}
            self.assertEqual(bus, on, b)
        self.assertEqual(refs, set(a.board_of))

    def test_round_trip(self):
        a = boards.default()
        with tempfile.TemporaryDirectory() as d:
            paths = boards.write(a, out_dir=d)
            self.assertTrue(os.path.exists(os.path.join(d, "README.md")))
            for b in boards.BOARDS:
                nl = boards.netlist(b)
                back = boards.load(os.path.join(d, f"{b}.json"))
                self.assertEqual(set(back.refs), set(nl.refs), b)
                for inst in nl.instances:
                    self.assertEqual(back.refs[inst.ref].conn, inst.conn, inst.ref)
                    self.assertEqual(back.refs[inst.ref].type.name, inst.type.name)
                self.assertEqual(back.connectors, nl.connectors, b)
            self.assertEqual(len(paths), len(boards.BOARDS) + 1)


class Delays(unittest.TestCase):
    def test_sta_netlist(self):
        a = boards.default()
        nl = board.build(sim=False)
        where = boards.match(nl, a)
        self.assertEqual(where["X_CLK"], a.board_of["U_K1"])     # the clock generator's stand-in
        conn = {i.ref: dict(i.conn) for i in nl.instances}
        drivers = {}
        for inst in nl.instances:
            for pin, net in inst.conn.items():
                if inst.kind(pin) in ("out", "tri", "io") and inst.ref in where:
                    drivers.setdefault(net, set()).add(where[inst.ref])
        d = boards.add_board_delays(nl, a, ps=1500)
        self.assertTrue(d)
        kinds = set()
        for ref, pin, ps in d:
            inst = nl.refs[ref]
            net = conn[ref][pin]
            self.assertNotIn(net, boards.CLOCKS)
            if inst.kind(pin) == "in":
                # a wire in front of an input on another board than the net's driver
                self.assertEqual(drivers[net] - {where[ref]}, drivers[net])
                w = nl.refs[f"W~{ref}~{pin}"]
                self.assertEqual((w.conn["A"], w.conn["Y"]), (net, inst.conn[pin]))
                self.assertEqual(w.pin_extra["Y"], 1500)
            else:
                # a bus driven from several boards: the driver's delay
                self.assertGreater(len(drivers[net]), 1)
                self.assertEqual(inst.pin_extra[pin], 1500)
            kinds.add(inst.kind(pin) == "in")
        self.assertEqual(kinds, {True, False})
        # the simulator's export carries them
        chips = {c["ref"]: c for c in nl.export(variant=parts.VARIANT)["chips"]}
        for ref, pin, _ in d[:1] + [x for x in d if nl.refs[x[0]].kind(x[1]) != "in"][:1]:
            if nl.refs[ref].kind(pin) == "in":
                ref, pin = f"W~{ref}~{pin}", "Y"
            c = chips[ref]
            self.assertEqual(c["pin_delays"][c["pins"].index(pin)], 1500)


if __name__ == "__main__":
    unittest.main()
