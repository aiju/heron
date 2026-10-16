"""What the figure languages share: the drawing (SVG in the site's colours
and fonts, light and dark), the widths of text, and the lexer of the
line-by-line languages (bits, blocks)."""

import html

# Libre Franklin's advance widths in thousandths of an em, printable ASCII
# from the space, at weights 400 and 600; then the rest the documents use.
_FRANKLIN = {
    400: ("214 244 409 603 605 916 778 240 286 286 380 557 212 381 209 342 688 465 599 641 649 654 661 599 668 "
          "658 209 229 544 557 544 523 834 727 699 707 722 628 601 739 735 290 418 701 602 906 757 764 690 765 "
          "696 641 645 709 707 1045 688 675 631 287 342 287 476 518 285 548 599 542 599 581 379 602 584 239 239 "
          "564 239 906 584 599 597 599 383 512 387 579 547 796 544 530 482 305 261 305 568",
          {"–": 558, "—": 880, "×": 540, "·": 201, "≤": 551, "≥": 551, "±": 557, "µ": 579, "Ω": 767,
           "’": 222, "‘": 222, "“": 398, "”": 399, "…": 749, "°": 464}),
    600: ("209 257 449 603 638 935 818 245 304 304 436 574 239 380 237 357 701 494 628 658 675 669 677 612 678 "
          "675 237 249 566 574 566 532 834 756 715 719 741 645 621 747 746 306 437 729 619 934 758 770 706 772 "
          "713 665 669 717 724 1071 715 715 664 306 357 306 475 535 299 558 606 548 606 584 394 622 592 256 256 "
          "590 257 914 592 599 605 606 411 524 417 588 564 811 575 554 506 345 255 345 595",
          {"–": 575, "—": 899, "×": 564, "·": 232, "≤": 571, "≥": 571, "±": 574, "µ": 588, "Ω": 767,
           "’": 234, "‘": 234, "“": 442, "”": 445, "…": 840, "°": 464}),
}
WIDTHS = {w: (dict(zip(map(chr, range(32, 127)), map(int, a.split()))) | b) for w, (a, b) in _FRANKLIN.items()}


class Error(Exception):
    pass


def textwidth(s, size, weight=400, mono=False):
    """The width of s in pixels: IBM Plex Mono is 0.6 em a character; for
    Libre Franklin, its widths, and 0.6 em for what they don't have."""
    if mono:
        return len(s) * 0.6 * size
    w = WIDTHS[600 if weight >= 600 else 400]
    return sum(w.get(c, 600) for c in s) * size / 1000


def num(v):
    """A coordinate, as short as it can be written."""
    return f"{v:.1f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v))


SANS = "'Libre Franklin','Franklin Gothic Medium','Helvetica Neue',Arial,sans-serif"
MONO = "'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

# The site's colours (heron/site/site.css), light and dark. A figure is an
# <img>, which follows the reader's light or dark setting by itself; every
# rule is under .diagram, so the site can put a figure into its page.
STYLE = f"""
.diagram{{--paper:#FBFAF6;--ink:#171615;--ink-2:#56524B;--ink-3:#8C877D;--rule:#E4E0D8;--spot:#A3195B}}
@media (prefers-color-scheme:dark){{.diagram{{--paper:#141312;--ink:#ECE7DE;--ink-2:#ADA79C;--ink-3:#7E786E;--rule:#2C2926;--spot:#E8609F}}}}
.diagram text{{fill:var(--ink);font-family:{SANS};font-size:12px}}
.diagram .ink{{fill:none;stroke:var(--ink);stroke-width:1.25;stroke-linejoin:round;stroke-linecap:round}}
.diagram .thin{{fill:none;stroke:var(--ink-2);stroke-width:.9}}
.diagram .faint{{fill:none;stroke:var(--ink-3);stroke-width:.7}}
.diagram .dotted{{fill:none;stroke:var(--ink-3);stroke-width:.7;stroke-dasharray:1.5 2}}
.diagram .dashed{{stroke-dasharray:4 3}}
.diagram .bus{{stroke-width:3.2;stroke-linecap:butt}}
.diagram .grid{{stroke:var(--rule);stroke-width:1}}
.diagram .spot{{fill:none;stroke:var(--spot);stroke-width:1.1}}
.diagram .paper{{fill:var(--paper)}}.diagram .hatch{{fill:url(#diagram-hatch)}}.diagram #diagram-hatch line{{stroke:var(--ink-3);stroke-width:.8}}
.diagram .solid{{fill:var(--ink)}}.diagram .solid-2{{fill:var(--ink-2)}}.diagram .solid-spot{{fill:var(--spot)}}
.diagram .b{{font-weight:600}}.diagram .m{{font-family:{MONO};font-size:11.5px}}
.diagram .s{{font-size:11px;fill:var(--ink-2)}}.diagram .xs{{font-size:10px;fill:var(--ink-3)}}.diagram .sp{{fill:var(--spot)}}
.diagram .halo{{paint-order:stroke;stroke:var(--paper);stroke-width:4px;stroke-linejoin:round}}
"""

DEFS = ('<defs><pattern id="diagram-hatch" patternUnits="userSpaceOnUse" width="4" height="4" '
        'patternTransform="rotate(45)"><line x1="2" y1="0" x2="2" y2="4"/></pattern></defs>')


class Drawing:
    """Elements in drawing order, and the box they cover."""

    def __init__(self):
        self.out = []
        self.x0 = self.y0 = float("inf")
        self.x1 = self.y1 = float("-inf")

    def cover(self, x0, y0, x1, y1):
        self.x0, self.y0 = min(self.x0, x0, x1), min(self.y0, y0, y1)
        self.x1, self.y1 = max(self.x1, x0, x1), max(self.y1, y0, y1)

    def line(self, x1, y1, x2, y2, cls="ink"):
        self.cover(x1, y1, x2, y2)
        self.out.append(f'<line class="{cls}" x1="{num(x1)}" y1="{num(y1)}" x2="{num(x2)}" y2="{num(y2)}"/>')

    def path(self, pts, cls="ink", close=False):
        for x, y in pts:
            self.cover(x, y, x, y)
        d = "M" + " L".join(f"{num(x)} {num(y)}" for x, y in pts) + ("Z" if close else "")
        self.out.append(f'<path class="{cls}" d="{d}"/>')

    def curve(self, d, pts, cls):
        for x, y in pts:
            self.cover(x, y, x, y)
        self.out.append(f'<path class="{cls}" d="{d}"/>')

    def rect(self, x, y, w, h, cls="ink paper"):
        self.cover(x, y, x + w, y + h)
        self.out.append(f'<rect class="{cls}" x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}"/>')

    def circle(self, x, y, r, cls="solid"):
        self.cover(x - r, y - r, x + r, y + r)
        self.out.append(f'<circle class="{cls}" cx="{num(x)}" cy="{num(y)}" r="{num(r)}"/>')

    def text(self, s, x, y, cls="", size=12, anchor="start", weight=400, mono=False):
        """s with its middle at height y, starting, centred or ending at x."""
        w = textwidth(s, size, weight, mono)
        left = x - {"start": 0, "middle": w / 2, "end": w}[anchor]
        self.cover(left, y - size * 0.6, left + w, y + size * 0.6)
        a = "" if anchor == "start" else f' text-anchor="{anchor}"'
        c = f' class="{cls}"' if cls else ""
        classes = cls.split()
        usual = 11.5 if "m" in classes else 10 if "xs" in classes else 11 if "s" in classes else 12
        if size != usual:
            c += f' style="font-size:{num(size)}px"'
        self.out.append(f'<text{c} x="{num(x)}" y="{num(y + 0.36 * size)}"{a}>{html.escape(s)}</text>')

    def arrowhead(self, x, y, dx, dy, cls="solid", length=6, width=2.6):
        """A filled arrowhead with its point at x, y, pointing along dx, dy."""
        n = (dx * dx + dy * dy) ** 0.5 or 1
        ux, uy = dx / n, dy / n
        bx, by = x - length * ux, y - length * uy
        self.path([(x, y), (bx - width * uy, by + width * ux), (bx + width * uy, by - width * ux)], cls, close=True)

    def extend(self, other):
        """Draw what other has drawn, over this."""
        self.out += other.out
        if other.out:
            self.cover(other.x0, other.y0, other.x1, other.y1)

    def svg(self, margin=8):
        """The finished SVG, sized to what was drawn."""
        x0, y0 = self.x0 - margin, self.y0 - margin
        w, h = self.x1 - self.x0 + 2 * margin, self.y1 - self.y0 + 2 * margin
        w, h = int(-(-w // 1)), int(-(-h // 1))
        # a background of its own, so that it reads on any page, in either
        # setting, whatever the page's colour
        back = f'<rect class="paper" x="{num(x0)}" y="{num(y0)}" width="{w}" height="{h}"/>'
        return (f'<svg xmlns="http://www.w3.org/2000/svg" class="diagram" viewBox="{num(x0)} {num(y0)} {w} {h}" '
                f'width="{w}" height="{h}"><style>{STYLE.strip()}</style>{DEFS}\n{back}\n'
                + "\n".join(self.out) + "\n</svg>\n")


# ---------------------------------------------------------------- the line languages

class Line:
    """One statement: its line number, indentation and tokens. A token is
    ("word", text), ("str", text) or ("attr", key, value)."""

    def __init__(self, n, indent, toks):
        self.n, self.indent, self.toks = n, indent, toks

    def err(self, msg):
        return Error(f"line {self.n}: {msg}")

    def attrs(self):
        return {t[1]: t[2] for t in self.toks if t[0] == "attr"}

    def args(self):
        return [t for t in self.toks if t[0] != "attr"]


def _string(s, i):
    q, out = s[i], []
    i += 1
    while True:
        if i >= len(s):
            raise Error("a string isn't closed")
        if s[i] == q:
            if s[i + 1:i + 2] == q:  # '' or "" is the quote itself
                out.append(q)
                i += 2
                continue
            return "".join(out), i + 1
        out.append(s[i])
        i += 1


def lines(text):
    """The statements of a line language: one a line, # to the end of the
    line a comment (where a word could start), "..." or '...' a string,
    key=value an attribute."""
    out = []
    for n, raw in enumerate(text.split("\n"), 1):
        s = raw.rstrip()
        indent = len(s) - len(s.lstrip(" \t"))
        toks, i = [], indent
        try:
            while i < len(s):
                c = s[i]
                if c in " \t":
                    i += 1
                elif c == "#":
                    break
                elif c in "\"'":
                    v, i = _string(s, i)
                    toks.append(("str", v))
                else:
                    j = i
                    while j < len(s) and s[j] not in " \t\"'":
                        j += 1
                    w, i = s[i:j], j
                    key, eq, val = w.partition("=")
                    if eq and key.isidentifier():
                        if not val and i < len(s) and s[i] in "\"'":
                            val, i = _string(s, i)
                        toks.append(("attr", key, val))
                    else:
                        toks.append(("word", w))
        except Error as e:
            raise Error(f"line {n}: {e}")
        if toks:
            out.append(Line(n, indent, toks))
    return out
