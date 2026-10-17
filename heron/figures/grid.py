"""grid: a table drawn as a chart, whose cells can span: an opcode map.

    | | _0 | _1 | _2 |                 the first row: the columns' heads
    | 0_ | ILLEGAL | LDM rb,ra-rc +1 |  then a row a line: its head, its cells
    | 7_ | MVI #u7 ×8 | ↳ | ↳ |         ↳ continues the cell to its left
    | C_ | LSL #n ×2 | ↳ | |            an empty cell is free: hatched

The rows are written as Markdown's, so a table converts by copying it;
the line under the heads (|---|) is skipped, and `backticks` dropped. A
cell's first word is its title; words that start with + or × go small in
its corner. .cell W sets the cells' width in pixels.
"""

import re

from .svg import Drawing, Error, lines, textwidth

LINE, PAD = 13, 4


def parse(text):
    rows, opts = [], {"cell": None}
    for n, raw in enumerate(text.split("\n"), 1):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("."):
            ls = lines(s)[0].args()
            if ls[0][1] != ".cell" or len(ls) != 2:
                raise Error(f"line {n}: no such setting: {ls[0][1]}")
            opts["cell"] = float(ls[1][1])
            continue
        if not s.startswith("|"):
            raise Error(f"line {n}: a row starts with |")
        cells = [c.strip().replace("`", "") for c in s.strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue
        rows.append((n, cells))
    if len(rows) < 2:
        raise Error("a grid is its heads and at least a row")
    heads = rows[0][1][1:]
    body = []
    for n, cells in rows[1:]:
        if len(cells) != len(heads) + 1:
            raise Error(f"line {n}: {len(cells) - 1} cells, but {len(heads)} columns")
        spans = []   # (first column, width, text)
        for k, c in enumerate(cells[1:]):
            if c == "↳":
                if not spans:
                    raise Error(f"line {n}: ↳ continues the cell to its left, and there's none")
                a, w, t = spans[-1]
                spans[-1] = (a, w + 1, t)
            else:
                spans.append((k, 1, c))
        body.append((cells[0], spans))
    return heads, body, opts


def wrap(words, width, size, weight=400):
    """Words into lines no wider than width, where they can be."""
    out = []
    for w in words:
        if out and textwidth(out[-1] + " " + w, size, weight) <= width:
            out[-1] += " " + w
        else:
            out.append(w)
    return out


def render(text):
    heads, body, opts = parse(text)
    cw = opts["cell"] or 58
    hw = max(textwidth(h, 11, 600) for h, _ in body) + 14
    # each cell's lines, and so each row's height
    rows = []
    for head, spans in body:
        cells = []
        for a, w, t in spans:
            words = t.split()
            corner = " ".join(x for x in words if x[0] in "+×")
            words = [x for x in words if x[0] not in "+×"]
            width = w * cw - 2 * PAD
            title = words[:1]
            rest = wrap(words[1:], width, 10)
            cells.append((a, w, title, rest, corner))
        h = max([(len(c[2]) + len(c[3])) * LINE + (LINE if c[4] else 0) + 2 * PAD for c in cells] + [32])
        rows.append((head, cells, h))
    d = Drawing()
    top = 20
    for k, h in enumerate(heads):
        d.text(h, hw + (k + 0.5) * cw, top / 2, "xs", 10, "middle")
    y = top
    for head, cells, h in rows:
        d.text(head, hw - 10, y + h / 2, "b", 11, "end", 600)
        covered = set()
        for a, w, title, rest, corner in cells:
            x = hw + a * cw
            free = not title and not rest and not corner
            d.rect(x, y, w * cw, h, "ink hatch" if free else "ink paper")
            covered.update(range(a, a + w))
            ty = y + PAD + LINE / 2 + (h - 2 * PAD - (len(title) + len(rest)) * LINE - (LINE if corner else 0)) / 2
            for t in title:
                d.text(t, x + w * cw / 2, ty, "b", 11, "middle", 600)
                ty += LINE
            for t in rest:
                d.text(t, x + w * cw / 2, ty, "s", 10, "middle")
                ty += LINE
            if corner:
                d.text(corner, x + w * cw / 2, ty, "xs", 9, "middle")
        y += h
    return d.svg()
