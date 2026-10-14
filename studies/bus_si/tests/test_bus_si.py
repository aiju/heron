"""The bus_si study's models and tools. Most need the IBIS files from
ti.com (downloaded once into build/ibis/) and the native engine."""

import os
import tempfile
import time
import unittest

try:
    import numpy as np
except ImportError:
    np = None
if np is not None:
    from heron.infra.si import engine, ibis, runner
    from heron.studies.bus_si import bused, connector, gb

needs_numpy = unittest.skipUnless(np is not None, "the bus_si study needs numpy (pip install numpy)")


def _job(job):
    """For the runner test: sleep, or fail."""
    if job[0] == "sleep":
        time.sleep(job[1])
        return {"slept": job[1]}
    raise ValueError("as asked")


@needs_numpy
class Runner(unittest.TestCase):
    def test_a_stuck_job_is_killed_and_the_rest_run(self):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "log.jsonl")
            jobs = [("sleep", 60), ("sleep", 0.1), ("fail",), ("sleep", 0.2)]
            t0 = time.time()
            recs, n_err, _, complete = runner.run(jobs, _job, log, workers=2, timeout=2, heartbeat=1,
                                                  out=lambda *a, **k: None)
            self.assertLess(time.time() - t0, 20)
            self.assertTrue(complete)
            self.assertEqual(n_err, 2)
            self.assertIn("Timeout", recs[runner.key(("sleep", 60))]["error"])
            self.assertIn("as asked", recs[runner.key(("fail",))]["error"])
            self.assertEqual(recs[runner.key(("sleep", 0.2))]["result"], {"slept": 0.2})
            # a second run finds everything done
            recs, n_err, _, complete = runner.run(jobs, _job, log, workers=2, timeout=2,
                                                  out=lambda *a, **k: None)
            self.assertEqual((n_err, complete), (0, True))


@needs_numpy
class Parser(unittest.TestCase):
    def test_supply_factor(self):
        # a 100 ohm table resistor scaled by s(V(sup)) = V(sup)/2, at 4 V: 50 ohm
        lines = ["V1 a 0 1", "Vs sup 0 4", "R1 a b 100",
                 "B1 b 0 I = pwl(V(sup), 0,0, 4,2)*pwl(V(b), -1,-0.01, 1,0.01)"]
        r = engine.run_native(lines, ["v(b)"], 1e-10)
        self.assertAlmostEqual(float(r["v(b)"][-1]), 1 / 3, places=5)


@needs_numpy
class Connector(unittest.TestCase):
    def test_ground_pins_lower_loop_inductance_and_coupling(self):
        guarded = connector.loop(connector.victim_map(True), ["SEL", "D0"])
        open_ = connector.loop(connector.victim_map(False), ["SEL", "D0"])
        self.assertLess(guarded[0, 0], open_[0, 0])
        k = lambda m: m[0, 1] / np.sqrt(m[0, 0] * m[1, 1])
        self.assertLess(abs(k(guarded)), abs(k(open_)) / 3)

    def test_matches_te_measurement(self):
        near, far = connector.te_check()
        self.assertAlmostEqual(near, 0.700, delta=0.1)
        self.assertAlmostEqual(far, -0.600, delta=0.1)


@needs_numpy
class Ibis(unittest.TestCase):
    def test_offset_waveforms_start_at_zero(self):
        m, _ = ibis.load("cdc329a")
        self.assertTrue(all(w["t"][0] == 0 for w in m.waveforms))

    def test_ramp_only_model(self):
        m, _ = ibis.load("abt16245")
        t, ku, kd = m.coefficients("rising", "typ")
        self.assertAlmostEqual(ku[-1], 1.0, places=3)
        self.assertAlmostEqual(kd[-1], 0.0, places=3)

    def test_break_before_make_has_no_overlap(self):
        m, _ = ibis.load("abt")
        _, ku, kd = m.coefficients("falling", "max", overlap=False)
        self.assertTrue(np.all(ku == 0))


@needs_numpy
class Models(unittest.TestCase):
    def test_calibrated_ground_bounce_near_the_datasheet(self):
        # Fairchild 74ABT245, SOIC: VOLP 0.7 V typical, 1.0 V max
        raw = gb.volp("abt", "soic")["quiet"]
        cal = gb.volp("abt", "soic", overlap=False, alpha=gb.CALIBRATED_ALPHA)["quiet"]
        self.assertGreater(raw, 1.5)
        self.assertGreater(cal, 0.6)
        self.assertLess(cal, 1.1)

    def test_two_cards(self):
        b = bused.Bus.full().with_cards({0, 15})
        w = bused.worst(bused.run(b, ("slot", 0), "typ"))
        self.assertEqual(w["unsettled"], 0)
        self.assertLess(w["add_rise"], 6e-9)
