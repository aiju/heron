"""Figures in Markdown: a figure's source in a comment, or in a fenced
block, and right after it the image that is its SVG.

    <!-- timing
    BCLK 8{:1 +.5:0 +.5}
    -->
    ![An access](0037-rfc-system-and-io-bus/access.svg)

The comment's first word names the language; the image's path, relative
to the document, is where the SVG goes. A fenced block whose info string
is the language (```timing) works the same and shows its source. The
source can't contain -->, which ends a comment.
"""

import os
import re
import subprocess
import textwrap

from heron import ROOT

from . import bits, blocks, grid, maps, timing
from .svg import Error

LANGUAGES = {"timing": timing, "bits": bits, "blocks": blocks, "map": maps, "grid": grid}

FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})[ \t]*([^`\s]*)")
COMMENT = re.compile(r"^[ \t]*<!--[ \t]*(\w+)[ \t]*$")
IMAGE = re.compile(r"^[ \t]*!\[[^\]]*\]\(([^)\s]+\.svg)\)")


class Figure:
    def __init__(self, doc, line, lang, source, svg):
        self.doc, self.line, self.lang, self.source, self.svg = doc, line, lang, source, svg

    def render(self):
        try:
            return LANGUAGES[self.lang].render(self.source)
        except Error as e:
            # the error's line in the document, not in the figure
            msg = re.sub(r"^line (\d+)", lambda m: f"line {int(m.group(1)) + self.line}", str(e))
            raise Error(f"{self.doc}: {msg}") from None

    def __repr__(self):
        return f"{self.doc}:{self.line}: {self.lang} -> {self.svg}"


def figures(doc, text):
    """The figures in a document: doc is its path from the root."""
    lines, out, i = text.split("\n"), [], 0

    def image(j):
        """The SVG of the image on the first line from j that isn't blank."""
        while j < len(lines) and not lines[j].strip():
            j += 1
        m = IMAGE.match(lines[j]) if j < len(lines) else None
        return m and os.path.normpath(os.path.join(os.path.dirname(doc), m.group(1)))

    while i < len(lines):
        f, c = FENCE.match(lines[i]), COMMENT.match(lines[i])
        if f:
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith(f.group(1)):
                j += 1
            svg = f.group(2) in LANGUAGES and image(j + 1)
            if svg:   # a fenced block in a language, then its image
                out.append(Figure(doc, i + 1, f.group(2), textwrap.dedent("\n".join(lines[i + 1:j])), svg))
            i = j + 1
        elif c and c.group(1) in LANGUAGES:
            j = i + 1
            while j < len(lines) and "-->" not in lines[j]:
                j += 1
            if j == len(lines) or lines[j].strip() != "-->":
                raise Error(f"{doc}:{i + 1}: a figure's comment ends with --> on a line of its own")
            svg = image(j + 1)
            if not svg:
                raise Error(f"{doc}:{i + 1}: a figure's comment is followed by its image, an .svg")
            out.append(Figure(doc, i + 1, c.group(1), textwrap.dedent("\n".join(lines[i + 1:j])), svg))
            i = j + 1
        else:
            i += 1
    return out


def documents():
    """Every Markdown file git has or would add, from the root."""
    r = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "*.md"],
                       cwd=ROOT, capture_output=True, text=True, check=True)
    return sorted(p for p in r.stdout.split("\0") if p)


def every(paths=None):
    out = []
    for doc in paths or documents():
        with open(os.path.join(ROOT, doc)) as f:
            out += figures(doc, f.read())
    return out


def stale(figs):
    """The figures whose SVG is missing or isn't what their source draws:
    [(figure, why)]."""
    out = []
    for fig in figs:
        path = os.path.join(ROOT, fig.svg)
        try:
            want = fig.render()
        except Error as e:
            out.append((fig, str(e)))
            continue
        if not os.path.exists(path):
            out.append((fig, "missing"))
            continue
        with open(path) as f:
            if f.read() != want:
                out.append((fig, "out of date"))
    return out


def write(figs):
    """Write every figure's SVG; return the paths that changed."""
    changed = []
    for fig in figs:
        svg = fig.render()
        path = os.path.join(ROOT, fig.svg)
        if os.path.exists(path):
            with open(path) as f:
                if f.read() == svg:
                    continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(svg)
        changed.append(fig.svg)
    return changed
