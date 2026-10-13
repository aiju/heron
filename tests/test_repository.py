"""The repository's own rules (RFC 0000): front matter, the reports index,
links between documents, and what infra may depend on."""

import os
import re
import subprocess
import unittest

from heron import ROOT, meta

LINK = re.compile(r"\]\(([^)\s]+)\)")


def tracked(pattern):
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", pattern],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [os.path.join(ROOT, p) for p in out.split()]


def anchors(path):
    """GitHub's anchors for a Markdown file's headings."""
    out = set()
    with open(path) as f:
        for line in f:
            if line.startswith("#"):
                t = line.lstrip("#").strip().lower()
                out.add(re.sub(r"[^\w\- ]", "", t).replace(" ", "-"))
    return out


class Repository(unittest.TestCase):
    def test_front_matter(self):
        self.assertEqual(meta.problems(), [])

    def test_index_is_current(self):
        with open(meta.INDEX) as f:
            self.assertEqual(f.read(), meta.index(), "run `heron reports`")

    def test_links(self):
        bad = []
        for path in tracked("*.md"):
            with open(path) as f:
                text = f.read()
            for target in LINK.findall(text):
                if re.match(r"[a-z]+:", target):
                    continue
                p, _, anchor = target.partition("#")
                dest = os.path.normpath(os.path.join(os.path.dirname(path), p)) if p else path
                rel = os.path.relpath(path, ROOT)
                if not os.path.exists(dest):
                    bad.append(f"{rel}: {target} doesn't exist")
                elif anchor and dest.endswith(".md") and anchor not in anchors(dest):
                    bad.append(f"{rel}: {target} has no such heading")
        self.assertEqual(bad, [])

    def test_infra_doesnt_depend_on_studies(self):
        bad = []
        for path in tracked("infra/*.py"):
            with open(path) as f:
                for n, line in enumerate(f, 1):
                    if re.match(r"\s*(from|import)\s+heron\.studies", line):
                        bad.append(f"{os.path.relpath(path, ROOT)}:{n}: {line.strip()}")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
