"""The opcode map's page: RFC 0028's map built in, and the explorer
finding nothing wrong with it."""

import json
import os
import re
import subprocess
import tempfile
import unittest

from heron.studies.opcode_map import page

DATA = re.compile(r'<script type="application/json" id="heron-map">(.*?)</script>', re.S)


def built_in(html):
    m = DATA.search(html)
    return json.loads(m.group(1)) if m else None


class TestPage(unittest.TestCase):
    def test_rfc_0028s_map_is_built_in(self):
        html = page.page()
        self.assertTrue(html.startswith("<!doctype html>"))
        b = built_in(html)
        with open(page.MAP) as f:
            self.assertEqual(b["map"], json.load(f))
        self.assertTrue(b["name"].startswith("RFC 0028"))
        self.assertIn("reports/0028-rfc-draft-2-isa/map.json", b["source"])
        self.assertRegex(b["stamp"], r"^[0-9a-f]{16}$")

    def test_the_source_has_no_map(self):
        with open(page.SOURCE) as f:
            self.assertIsNone(built_in(f.read()))

    def test_a_description_cannot_end_the_script(self):
        with open(page.MAP) as f:
            exported = json.load(f)
        exported["state"]["instrs"]["x"] = {"id": "x", "m": "X", "d": "a </script> in a description"}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "map.json")
            with open(path, "w") as f:
                json.dump(exported, f)
            html = page.page(path)
        self.assertEqual(html.count("</script>"), 2)
        self.assertEqual(built_in(html)["map"]["state"]["instrs"]["x"]["d"], "a </script> in a description")

    def test_not_a_map(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "map.json")
            with open(path, "w") as f:
                json.dump({"format": "something else"}, f)
            with self.assertRaises(ValueError):
                page.page(path)


def render(html):
    """The page as headless Chrome draws it, or None without Chrome. The
    explorer loads Preact from a CDN, so this needs the network."""
    from heron.studies.v1_isa.refcard import find_chrome
    chrome = find_chrome()
    if not chrome:
        return None
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "opcode-map.html")
        with open(path, "w") as f:
            f.write(html)
        cmd = [chrome, "--headless", "--disable-gpu", "--virtual-time-budget=10000", "--dump-dom",
               "file://" + path]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            cmd.insert(1, "--no-sandbox")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return r.stdout


def checks(dom):
    """The explorer's checks: [(level, where, message)]."""
    return re.findall(r'<li><span class="lvl (\w+)">[^<]*</span><span class="where">([^<]*)</span><span>([^<]*)</span>', dom)


class TestInBrowser(unittest.TestCase):
    """RFC 0028's map in the explorer: a cell naming an instruction or mode
    the explorer doesn't know is an error among its checks."""

    def draw(self, path=page.MAP):
        dom = render(page.page(path))
        if dom is None:
            self.skipTest("no Chrome or Chromium (CHROME names one)")
        if "cells used" not in dom:
            self.skipTest("the page didn't start: no network for Preact?")
        return dom

    def test_rfc_0028s_map_has_no_errors(self):
        dom = self.draw()
        self.assertIn("RFC 0028", dom)
        self.assertEqual([c for c in checks(dom) if c[0] == "bad"], [])

    def test_an_unknown_instruction_is_an_error(self):
        with open(page.MAP) as f:
            exported = json.load(f)
        exported["state"]["cells"]["root/10"] = {"i": "no-such-instruction", "s": 1}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "map.json")
            with open(path, "w") as f:
                json.dump(exported, f)
            dom = self.draw(path)
        self.assertIn(("bad", "10", "no-such-instruction is no longer defined"), checks(dom))


class TestSite(unittest.TestCase):
    def test_the_site_builds_it(self):
        from heron import site
        app = next(a for a in site.APPS if a["id"] == "opcode-map")
        with tempfile.TemporaryDirectory() as d:
            made = app["build"](d)
            self.assertEqual(made, [f for _, f in app["files"]])
            with open(os.path.join(d, made[0])) as f:
                self.assertIsNotNone(built_in(f.read()))
