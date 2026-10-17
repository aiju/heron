"""map: address maps, a region a line.

    0x0000_0000  "regions 0–3" "CPU or memory cards"   where a region
    0x7000_0000  registers                              starts, and its
    0x7700_0000  free                                   lines of text
    0x8000_0000                                         the end
    group 0x0000_0000 0x7000_0000 memory                a bracket beside

Regions are as high as their text, not as big as they are; high
addresses are at the top (.order down puts them at the bottom). A region
called free, unused or reserved is hatched.
"""

import re

from .svg import Drawing, Error, lines, textwidth

LINE, PAD, WIDTH, GAP = 15, 7, 240, 12
EMPTY = ("free", "unused", "reserved")


def address(s, ln):
    if not re.fullmatch(r"(0x[0-9A-Fa-f_]+|\d+)", s):
        raise ln.err(f"expected an address such as 0x7000_0000, found {s!r}")
    return int(s.replace("_", ""), 0)


def parse(text):
    regions, groups, opts, end = [], [], {"order": "up", "width": WIDTH}, None
    for ln in lines(text):
        args = ln.args()
        kind, first = args[0] if args else (None, None)
        if end is not None and first != "group":
            raise ln.err("nothing but groups comes after the end")
        if kind == "word" and first.startswith("."):
            if first[1:] not in opts or len(args) != 2:
                raise ln.err(f"no such setting: {first}")
            opts[first[1:]] = args[1][1] if first == ".order" else float(args[1][1])
        elif first == "group":
            if len(args) != 4:
                raise ln.err('group takes two addresses and a label: group 0x0 0x7000_0000 memory')
            groups.append((address(args[1][1], ln), address(args[2][1], ln), args[3][1], ln))
        else:
            a = address(first, ln)
            if regions and a <= regions[-1][0]:
                raise ln.err("addresses go up, a region a line")
            if len(args) == 1:
                end = a
            else:
                regions.append((a, [t[1] for t in args[1:]], ln))
    if not regions:
        raise Error("no regions")
    if end is None:
        raise Error("the last line is where the map ends: an address alone")
    return regions, end, groups, opts


def hexa(v, digits):
    """v in hexadecimal, in groups of four digits: 0x7000_0000."""
    s, out = f"{v:0{digits}X}", []
    while s:
        out.insert(0, s[-4:])
        s = s[:-4]
    return "0x" + "_".join(out)


def render(text):
    regions, end, groups, opts = parse(text)
    digits = max(8, len(f"{end - 1:X}"))
    W = max([opts["width"]] + [textwidth(t[0], 12, 600) + 24 for _, t, _ in regions]
            + [textwidth(s, 11) + 24 for _, t, _ in regions for s in t[1:]])
    heights = [len(t) * LINE + 2 * PAD for _, t, _ in regions]
    x0 = textwidth(hexa(0, digits), 11, mono=True) + 12
    # where each boundary is, from the top
    up = opts["order"] != "down"
    order = list(range(len(regions)))[::-1] if up else list(range(len(regions)))
    tops, y = {}, 0
    for i in order:
        tops[i] = y
        y += heights[i]
    H = y
    d = Drawing()

    def edge(a):
        """The height of the boundary at address a."""
        for i, (start, _, _) in enumerate(regions):
            nxt = regions[i + 1][0] if i + 1 < len(regions) else end
            if a == start:
                return tops[i] + (heights[i] if up else 0)
            if a == nxt:
                return tops[i] + (0 if up else heights[i])
        raise Error(f"{hexa(a, digits)} isn't where a region starts or ends")

    for i, (start, text, ln) in enumerate(regions):
        top, h = tops[i], heights[i]
        empty = text[0].lower() in EMPTY
        d.rect(x0, top, W, h, "hatch" if empty else "paper")
        for k, t in enumerate(text):
            ty = top + h / 2 - (len(text) - 1) * LINE / 2 + k * LINE
            if empty:
                d.text(t, x0 + W / 2, ty, "s halo", 11, "middle")
            else:
                d.text(t, x0 + W / 2, ty, "b" if k == 0 else "s", 12 if k == 0 else 11, "middle", 600 if k == 0 else 400)
        d.line(x0, edge(start), x0 + W, edge(start))
    for a in [r[0] for r in regions] + [end]:
        d.text(hexa(a, digits), x0 - 8, edge(a), "m", 11, "end", mono=True)
    d.rect(x0, 0, W, H, "ink")
    # brackets beside: the smallest nearest, further out where they overlap
    spans = []
    for lo, hi, label, ln in groups:
        try:
            ya, yb = sorted((edge(lo), edge(hi)))
        except Error as e:
            raise ln.err(str(e))
        spans.append((ya, yb, label))
    levels = []
    for ya, yb, label in sorted(spans, key=lambda s: s[1] - s[0]):
        k = 0
        while any(not (yb <= pa or ya >= pb) for pa, pb, _ in levels[k] if k < len(levels)) if k < len(levels) else False:
            k += 1
        if k == len(levels):
            levels.append([])
        levels[k].append((ya, yb, label))
    gx = x0 + W + GAP
    for lev in levels:
        for ya, yb, label in lev:
            d.path([(gx - 4, ya + 2), (gx, ya + 2), (gx, yb - 2), (gx - 4, yb - 2)], "thin")
            d.text(label, gx + 6, (ya + yb) / 2, "s", 11)
        gx += max(textwidth(label, 11) for _, _, label in lev) + 22
    return d.svg()
