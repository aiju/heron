"""bits: bit fields, for instruction encodings, registers and table
entries.

    word 16 "parcel 1"          a word: its width in bits, a label
      15-12 x                   a field: its bits and its name
      11-10 s
      9-8   z
      7-3   = 01110             constant bits
      2-0   "u7 2–0"
      over 15-8 "register byte" a bracket over some bits, or under them
    word 8 beside               the next word to the right of this one

A field called reserved is hatched. .bit N sets the width of a bit in
pixels; .numbers all|edges|none which bit numbers are shown (also a word's
numbers=...).
"""

import re

from .svg import Drawing, Error, lines, textwidth

BOX, NUMS, LEVEL, GROUP, GAP = 28, 14, 15, 17, 14
NAME = 11.5  # the size of names in fields


class Field:
    def __init__(self, hi, lo, name, value):
        self.hi, self.lo, self.name, self.value = hi, lo, name, value


class Word:
    def __init__(self, width, label, beside, numbers, line):
        self.width, self.label, self.beside, self.numbers = width, label, beside, numbers
        self.fields, self.over, self.under, self.line = [], [], [], line


def bitrange(s, ln):
    m = re.fullmatch(r"(\d+)(?:\s*(?:-|–|\.\.|:)\s*(\d+))?", s)
    if not m:
        raise ln.err(f"expected bits such as 15-12 or 7, found {s!r}")
    a, b = int(m.group(1)), int(m.group(2) if m.group(2) is not None else m.group(1))
    return max(a, b), min(a, b)


def parse(text):
    words, opts = [], {"bit": None, "numbers": "edges"}
    for ln in lines(text):
        args, attrs = ln.args(), ln.attrs()
        kind, first = args[0] if args else ("attr", None)
        if kind == "word" and first.startswith("."):
            key = first[1:]
            if key not in opts or len(args) != 2:
                raise ln.err(f"no such setting: {first}")
            opts[key] = float(args[1][1]) if key == "bit" else args[1][1]
        elif kind == "word" and first == "word":
            if len(args) < 2 or not args[1][1].isdigit():
                raise ln.err("a word needs its width in bits: word 16")
            rest = [t for t in args[2:] if t != ("word", "beside")]
            if len(rest) > 1:
                raise ln.err("a word has one label; one with spaces needs quotes")
            label = rest[0][1] if rest else None
            words.append(Word(int(args[1][1]), label, ("word", "beside") in args, attrs.get("numbers"), ln))
        elif not words:
            raise ln.err("a field belongs under a word")
        elif kind == "word" and first in ("over", "under"):
            if len(args) != 3:
                raise ln.err(f'{first} takes bits and a label: {first} 15-8 "register byte"')
            hi, lo = bitrange(args[1][1], ln)
            getattr(words[-1], first).append((hi, lo, args[2][1]))
        else:
            hi, lo = bitrange(first, ln)
            rest = args[1:]
            name = value = None
            if rest and rest[0] != ("word", "="):
                name = rest.pop(0)[1]
            if rest and rest[0] == ("word", "="):
                if len(rest) != 2:
                    raise ln.err("= takes the field's bits: 7-4 = 0111")
                value = rest[1][1].replace("_", "")
                if not re.fullmatch(r"[01x]+", value) or len(value) != hi - lo + 1:
                    raise ln.err(f"{value!r} isn't {hi - lo + 1} bits of 0, 1 or x")
                rest = []
            if rest:
                raise ln.err(f"unexpected {rest[0][1]!r}")
            words[-1].fields.append(Field(hi, lo, name, value))
    for w in words:
        check(w)
    if words and words[0].beside:
        raise words[0].line.err("the first word has nothing to be beside")
    return words, opts


def check(w):
    owner = [None] * w.width
    for f in w.fields:
        if f.hi >= w.width:
            raise w.line.err(f"bit {f.hi} is outside a {w.width}-bit word")
        for b in range(f.lo, f.hi + 1):
            if owner[b] is not None:
                raise w.line.err(f"bit {b} is in two fields")
            owner[b] = f
    gaps = [b for b in range(w.width) if owner[b] is None]
    if gaps:
        raise w.line.err(f"bits {', '.join(map(str, reversed(gaps)))} have no field")
    for hi, lo, _ in w.over + w.under:
        if hi >= w.width:
            raise w.line.err(f"bit {hi} is outside a {w.width}-bit word")
    w.fields.sort(key=lambda f: -f.hi)


def levels(spans, gap=6):
    """Stack (lo, hi, item) spans into levels where none overlap: [[item]]."""
    out = []
    for lo, hi, item in sorted(spans, key=lambda s: s[0]):
        for lev in out:
            if lev[-1][1] + gap <= lo:
                lev.append((lo, hi, item))
                break
        else:
            out.append([(lo, hi, item)])
    return [[item for _, _, item in lev] for lev in out]


def render(text):
    words, opts = parse(text)
    if not words:
        raise Error("no words")
    rows = []
    for w in words:
        if w.beside:
            rows[-1].append(w)
        else:
            rows.append([w])
    bit = opts["bit"] or max(16, min(40, 576 // max(sum(w.width for w in r) for r in rows)))
    gutter = max([textwidth(r[0].label, 12, 600) + 16 for r in rows if r[0].label] + [0])
    d = Drawing()
    y = 0
    for row in rows:
        # where each word goes, and what it puts above and below itself
        x, plans = gutter, []
        for i, w in enumerate(row):
            if i:
                x += GAP + (textwidth(w.label, 12, 600) + 12 if w.label else 0)
            cell = lambda b, x0=x, w=w: x0 + (w.width - 1 - b) * bit
            captions = []
            for f in w.fields:
                fx0, fx1 = cell(f.hi), cell(f.lo) + bit
                f.box = (fx0, fx1)
                text = f.name or ""
                f.reserved = text.lower() == "reserved"
                f.inside = (f.value is None and text and not f.reserved
                            and textwidth(text, NAME, mono=True) <= fx1 - fx0 - 6)
                if text and not f.inside and not f.reserved:
                    cw = textwidth(text, 11)
                    cx = (fx0 + fx1) / 2
                    captions.append((cx - cw / 2, cx + cw / 2, f))
            over = levels([(cell(hi), cell(lo) + bit, (hi, lo, s)) for hi, lo, s in w.over], 0)
            under = levels([(cell(hi), cell(lo) + bit, (hi, lo, s)) for hi, lo, s in w.under], 0)
            plans.append((w, x, cell, levels(captions), over, under))
            x += w.width * bit
        above = max(len(p[4]) for p in plans) * GROUP + NUMS
        below = max(len(p[3]) * LEVEL + len(p[5]) * GROUP for p in plans)
        top = y + above
        for w, x0, cell, caps, over, under in plans:
            draw_word(d, w, x0, top, bit, cell, caps, over, under, opts)
            if w.label:
                d.text(w.label, x0 - (textwidth(w.label, 12, 600) + 12 if w is not row[0] else gutter),
                       top + BOX / 2, "b")
        y = top + BOX + below + GAP + 6
    return d.svg()


def draw_word(d, w, x0, top, bit, cell, caps, over, under, opts):
    x1, bottom = x0 + w.width * bit, top + BOX
    d.rect(x0, top, x1 - x0, BOX, "paper")
    for f in w.fields:
        fx0, fx1 = f.box
        if f.reserved:
            d.rect(fx0, top, fx1 - fx0, BOX, "hatch")
        for b in range(f.lo + 1, f.hi + 1):  # a tick between the field's bits
            bx = cell(b) + bit
            d.line(bx, top, bx, top + 4, "faint")
            d.line(bx, bottom - 4, bx, bottom, "faint")
        if f.value is not None:
            for i, c in enumerate(f.value):
                cx = fx0 + (i + 0.5) * bit
                d.text(c if c != "x" else "–", cx, top + BOX / 2, "m", NAME, "middle", mono=True)
        elif f.inside:
            d.text(f.name, (fx0 + fx1) / 2, top + BOX / 2, "m", NAME, "middle", mono=True)
        elif f.reserved and textwidth("reserved", 10) <= fx1 - fx0 - 8:
            d.text("reserved", (fx0 + fx1) / 2, top + BOX / 2, "xs halo", 10, "middle")
    for f in w.fields[1:]:
        d.line(f.box[0], top, f.box[0], bottom)
    d.rect(x0, top, x1 - x0, BOX, "ink")
    # bit numbers
    numbers = w.numbers or opts["numbers"]
    ny = top - NUMS / 2 - 1
    if numbers == "all":
        for b in range(w.width):
            d.text(str(b), cell(b) + bit / 2, ny, "xs", 10, "middle")
    elif numbers == "edges":
        for f in w.fields:
            d.text(str(f.hi), cell(f.hi) + bit / 2, ny, "xs", 10, "middle")
            if f.lo != f.hi:
                d.text(str(f.lo), cell(f.lo) + bit / 2, ny, "xs", 10, "middle")
    # names that don't fit, under the word on leaders
    for k, lev in enumerate(caps):
        ly = bottom + LEVEL * k + LEVEL - 4
        for f in lev:
            cx = (f.box[0] + f.box[1]) / 2
            d.line(cx, bottom + 1, cx, ly - 6, "faint")
            d.text(f.name, cx, ly, "s", 11, "middle")
    # brackets
    for k, lev in enumerate(over):
        gy = top - NUMS - GROUP * k - 4
        for hi, lo, s in lev:
            a, b = cell(hi) + 2, cell(lo) + bit - 2
            d.path([(a, gy + 4), (a, gy), (b, gy), (b, gy + 4)], "thin")
            d.text(s, (a + b) / 2, gy - 7, "s", 11, "middle")
    for k, lev in enumerate(under):
        gy = bottom + len(caps) * LEVEL + GROUP * k + 5
        for hi, lo, s in lev:
            a, b = cell(hi) + 2, cell(lo) + bit - 2
            d.path([(a, gy - 4), (a, gy), (b, gy), (b, gy - 4)], "thin")
            d.text(s, (a + b) / 2, gy + 7, "s", 11, "middle")
