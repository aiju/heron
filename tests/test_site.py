"""The website (heron site): it builds, every document has a page, the
links between its pages, and to their sections, land, and another branch's
version of a page is marked where it differs from main."""

import os
import posixpath
import re
import tempfile
import unittest
from html.parser import HTMLParser

from heron import ROOT, meta, site

ISA = "reports/0028-rfc-draft-2-isa.md"
EXTRA = "A paragraph that only the test's branch has."


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.urls = set(), []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        for k in ("href", "src"):
            if a.get(k):
                self.urls.append(a[k])


def parse(path):
    p = Links()
    with open(path) as f:
        p.feed(f.read())
    return p


@unittest.skipIf(site.missing(), "needs markdown-it-py and mdit-py-plugins")
class Site(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = cls.tmp.name
        cls.site = site.Site(cls.out)
        with open(os.path.join(ROOT, ISA)) as f:
            text = f.read()
        cls.site.add_version(ISA, "test/a-branch", "0" * 40, "2026-10-16T18:00:00Z", text + "\n" + EXTRA + "\n")
        cls.site.build(apps=False, branches=False)
        cls.pages = {}
        for d, _, files in os.walk(cls.out):
            for f in files:
                if f.endswith(".html"):
                    rel = os.path.relpath(os.path.join(d, f), cls.out).replace(os.sep, "/")
                    cls.pages[rel] = parse(os.path.join(d, f))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_document_has_a_page(self):
        with open(os.path.join(self.out, "index.html")) as f:
            index = f.read()
        for path, fm in meta.reports():
            page = f"reports/{os.path.basename(path)[:-3]}.html"
            self.assertIn(page, self.pages)
            self.assertIn(f'href="{page}"', index)

    def test_versions(self):
        page = "reports/0028-rfc-draft-2-isa.test-a-branch.html"
        self.assertIn(page, self.pages)
        with open(os.path.join(self.out, page)) as f:
            marked = re.findall(r'<p class="rev">([^<]*)', f.read())
        self.assertEqual(marked, [EXTRA])
        with open(os.path.join(self.out, "reports/0028-rfc-draft-2-isa.html")) as f:
            self.assertIn('href="0028-rfc-draft-2-isa.test-a-branch.html"', f.read())

    def test_revision_bars(self):
        def bars(old, new):
            r = self.site.render(ISA, new, "test/a-branch", old)
            return re.findall(r'<p class="rev">([^<]*)</p>', r["html"])
        doc = "---\nnumber: 28\n---\n\n# Title\n\nOne.\n\nTwo.\n\nThree.\n"
        self.assertEqual(bars(doc, doc), [])
        self.assertEqual(bars(doc, doc.replace("Two.", "Two, changed.")), ["Two, changed."])
        self.assertEqual(bars(doc, doc.replace("Two.\n\n", "")), ["Three."])

    def test_links_land(self):
        bad = []
        for page, p in self.pages.items():
            for url in p.urls:
                if url.startswith(("http:", "https:", "mailto:", "//")):
                    continue
                path, _, anchor = url.partition("#")
                target = posixpath.normpath(posixpath.join(posixpath.dirname(page), path)) if path else page
                if path and not os.path.exists(os.path.join(self.out, target)):
                    bad.append(f"{page}: {url} doesn't exist")
                elif anchor and target in self.pages and anchor not in self.pages[target].ids:
                    bad.append(f"{page}: {url} has no such section")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
