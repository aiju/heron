"""The figures study's command line: heron figures <command> ...

  write [FILE.md...]    draw every figure in the repository's Markdown, or
                        in these documents, into its SVG
  check [FILE.md...]    only check that every SVG is what its source draws
  list [FILE.md...]     the figures: document, line, language and SVG
  draw FILE [-o OUT]    draw one source file, its language from its
                        extension (.timing, .bits, .blocks, .map), to OUT or
                        FILE.svg
"""

import argparse
import os
import sys

from . import docs
from .svg import Error


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "draw":
        p = argparse.ArgumentParser(prog="heron figures draw")
        p.add_argument("file")
        p.add_argument("-o", "--out")
        a = p.parse_args(rest)
        lang = os.path.splitext(a.file)[1][1:]
        if lang not in docs.LANGUAGES:
            print(f"heron figures: {a.file}: the extension names the language: "
                  f"{', '.join('.' + k for k in docs.LANGUAGES)}", file=sys.stderr)
            return 2
        with open(a.file) as f:
            src = f.read()
        try:
            svg = docs.LANGUAGES[lang].render(src)
        except Error as e:
            print(f"{a.file}: {e}", file=sys.stderr)
            return 1
        with open(a.out or a.file + ".svg", "w") as f:
            f.write(svg)
        return 0
    if cmd not in ("write", "check", "list"):
        print(f"heron figures: no command {cmd!r}\n\n{__doc__.strip()}", file=sys.stderr)
        return 2
    paths = [os.path.relpath(os.path.abspath(p), docs.ROOT) for p in rest] or None
    figs = docs.every(paths)
    if cmd == "list":
        for f in figs:
            print(f)
        return 0
    if cmd == "check":
        bad = docs.stale(figs)
        for fig, why in bad:
            print(f"{fig.doc}:{fig.line}: {fig.svg}: {why}", file=sys.stderr)
        if bad:
            print("heron figures write draws them again", file=sys.stderr)
        return 1 if bad else 0
    try:
        changed = docs.write(figs)
    except Error as e:
        print(e, file=sys.stderr)
        return 1
    for c in changed:
        print(f"wrote {c}")
    print(f"{len(figs)} figures, {len(changed)} changed")
    return 0
