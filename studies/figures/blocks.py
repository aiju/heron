"""blocks: block diagrams, laid out by hand on a grid.

    box alu "ALU" "8 × 74LS181" at 20,4      a box: its name, its lines of
    box mux "result mux" right of alu gap 4   text, where it goes
    text "posted writes" right of bif         text without a box
    bus a "A bus" from 0,2 to 40,2            a bus: a thick line
    alu.right -> mux.left "F"                 a wire, and its label
    rfa -> alu                                sides picked by where they are
    mux.right -> 60,8 via 56,8                through points of its own
    frame "the CPU card" around alu mux       a dashed frame
    dot 30,2

A point is x,y in grid units (.unit, 10 pixels), a box's side (alu.left,
alu.top+2: 2 units along the side from its middle), a box (the side that
faces the other end), or a bus (straight across to it). Wires are ->, <-,
<-> or - and go across, then down, then across, or as their ends' sides
say. A box is as big as its text unless width= or height= say.
"""

import re

from .svg import Drawing, Error, lines, textwidth

LINE, PADX, PADY = 15, 9, 6
ARROWS = ("->", "<-", "<->", "-")
SIDES = ("left", "right", "top", "bottom")


class Box:
    def __init__(self, name, text, kind, line, flags, attrs):
        self.name, self.text, self.kind, self.line = name, text, kind, line
        self.flags, self.attrs = flags, attrs
        self.x = self.y = self.w = self.h = None   # in pixels once placed

    def side(self, s, off=0.0):
        """The point on a side, off pixels from its middle."""
        cx, cy = self.x + self.w / 2, self.y + self.h / 2
        m = 4 if self.kind == "text" else 0   # wires stop short of text
        return {"left": (self.x - m, cy + off), "right": (self.x + self.w + m, cy + off),
                "top": (cx + off, self.y - m), "bottom": (cx + off, self.y + self.h + m)}[s]


class Bus:
    def __init__(self, name, label, a, b, line, attrs):
        self.name, self.label, self.a, self.b, self.line, self.attrs = name, label, a, b, line, attrs


class Diagram:
    def __init__(self, text):
        self.unit = 10
        self.boxes, self.buses, self.wires, self.frames, self.dots = {}, {}, [], [], []
        self.order = []
        for ln in lines(text):
            self.statement(ln)

    # parsing
    def statement(self, ln):
        args, attrs = ln.args(), ln.attrs()
        kind, first = args[0] if args else (None, None)
        if any(t == ("word", a) for t in args for a in ARROWS):
            return self.wire(ln, args, attrs)
        if kind == "word" and first.startswith("."):
            if first == ".unit" and len(args) == 2:
                self.unit = float(args[1][1])
                return
            raise ln.err(f"no such setting: {first}")
        if first in ("box", "text"):
            return self.box(ln, args, attrs)
        if first == "bus":
            return self.bus(ln, args, attrs)
        if first == "frame":
            words = [t[1] for t in args[1:] if t[0] == "word"]
            if not words or words[0] != "around":
                raise ln.err('frame takes a label and boxes: frame "label" around a b')
            label = next((t[1] for t in args[1:] if t[0] == "str"), None)
            self.frames.append((label, words[1:], ln, attrs))
            return
        if first == "dot":
            if len(args) != 2:
                raise ln.err("dot takes a point")
            self.dots.append((args[1][1], ln))
            return
        raise ln.err(f"unknown {first!r}")

    def box(self, ln, args, attrs):
        kind = args[0][1]
        i, name = 1, None
        if i < len(args) and args[i][0] == "word" and re.fullmatch(r"[A-Za-z_]\w*", args[i][1]) \
                and args[i][1] not in ("at", "right", "left", "below", "above"):
            name = args[i][1]
            i += 1
        text = []
        while i < len(args) and args[i][0] == "str":
            text.append(args[i][1])
            i += 1
        words = [t[1] for t in args[i:]]
        flags = [w for w in words if w in ("dashed", "bold", "plain")]
        place = [w for w in words if w not in flags]
        b = Box(name or f"_{len(self.order)}", text, kind, ln, flags, attrs)
        b.place = place
        if b.name in self.boxes or b.name in self.buses:
            raise ln.err(f"{b.name} is already a box or bus")
        self.boxes[b.name] = b
        self.order.append(b)
        self.size(b)
        self.locate(b)

    def bus(self, ln, args, attrs):
        words = [t for t in args[1:]]
        if len(words) < 5 or words[0][0] != "word":
            raise ln.err('bus takes a name, a label and its ends: bus a "A bus" from 0,2 to 40,2')
        name = words[0][1]
        label = words[1][1] if words[1][0] == "str" else None
        rest = [t[1] for t in words[2 if label is not None else 1:]]
        if len(rest) != 4 or rest[0] != "from" or rest[2] != "to":
            raise ln.err("a bus goes from a point to a point")
        a, b = self.point(rest[1], ln), self.point(rest[3], ln)
        if a[0] != b[0] and a[1] != b[1]:
            raise ln.err("a bus is straight: across or down")
        self.buses[name] = Bus(name, label, a, b, ln, attrs)

    def wire(self, ln, args, attrs):
        ends, arrows, label, via, i = [], [], None, [], 0
        while i < len(args):
            k, v = args[i]
            if k == "str":
                label = v
            elif v in ARROWS:
                arrows.append(v)
            elif v == "via":
                i += 1
                while i < len(args) and args[i][0] == "word" and re.fullmatch(r"-?[\d.]+,-?[\d.]+", args[i][1]):
                    via.append(self.point(args[i][1], ln))
                    i += 1
                continue
            else:
                ends.append(v)
            i += 1
        if len(ends) != len(arrows) + 1:
            raise ln.err("a wire is ends with arrows between them: a.right -> b.left")
        if via and len(ends) > 2:
            raise ln.err("via is for a wire with two ends")
        for k in range(len(arrows)):
            self.wires.append((ends[k], arrows[k], ends[k + 1], label if len(ends) == 2 else None,
                               via, ln, attrs))

    # placing
    def size(self, b):
        sizes = [(t, 12 if k == 0 and b.kind == "box" and "plain" not in b.flags else 11,
                  600 if (k == 0 and b.kind == "box" and "plain" not in b.flags) or "bold" in b.flags else 400)
                 for k, t in enumerate(b.text)]
        b.lines = sizes
        w = max([textwidth(t, s, wt) for t, s, wt in sizes] + [0])
        u = self.unit
        if b.kind == "box":
            w, h = w + 2 * PADX, len(sizes) * LINE + 2 * PADY
            w, h = -(-w // u) * u, -(-h // u) * u
        else:
            h = len(sizes) * LINE
        b.w = float(b.attrs["width"]) * u if "width" in b.attrs else w
        b.h = float(b.attrs["height"]) * u if "height" in b.attrs else h

    def locate(self, b):
        p, u = b.place, self.unit
        if not p:
            raise b.line.err("where does it go? at x,y, or right of, left of, below or above a box")
        if p[0] == "at" and len(p) == 2:
            x, y = self.point(p[1], b.line)
            b.x, b.y = x, y
            if b.kind == "text":
                b.y -= b.h / 2  # text at a point is centred on it
        elif len(p) >= 2 and p[0] in ("right", "left", "below", "above"):
            p = p[:1] + p[2:] if p[1] == "of" else p   # below a, right of a
            p = p[:1] + ["of"] + p[1:]
            o = self.boxes.get(p[2])
            if o is None or o.x is None:
                raise b.line.err(f"{p[2]} isn't a box above this line")
            gap = 3 * u
            if len(p) == 5 and p[3] == "gap":
                gap = float(p[4]) * u
            elif len(p) != 3:
                raise b.line.err(f"unexpected {' '.join(p[3:])!r}")
            align = b.attrs.get("align", "middle")
            if p[0] in ("right", "left"):
                b.x = o.x + o.w + gap if p[0] == "right" else o.x - gap - b.w
                b.y = {"top": o.y, "bottom": o.y + o.h - b.h}.get(align, o.y + o.h / 2 - b.h / 2)
            else:
                b.y = o.y + o.h + gap if p[0] == "below" else o.y - gap - b.h
                b.x = {"left": o.x, "right": o.x + o.w - b.w}.get(align, o.x + o.w / 2 - b.w / 2)
            if b.kind == "box":  # stay on the grid
                b.x, b.y = round(b.x / u * 2) * u / 2, round(b.y / u * 2) * u / 2
        else:
            raise b.line.err(f"can't place it {' '.join(p)!r}")
        b.x += float(b.attrs.get("dx", 0)) * u
        b.y += float(b.attrs.get("dy", 0)) * u

    def point(self, s, ln, toward=None):
        """A point: (x, y, side or None, bus or None)."""
        u = self.unit
        m = re.fullmatch(r"(-?[\d.]+),(-?[\d.]+)", s)
        if m:
            return (float(m.group(1)) * u, float(m.group(2)) * u)
        raise ln.err(f"expected x,y, found {s!r}")

    def end(self, s, ln):
        """A wire's end, unresolved: ("pt", (x, y)), ("side", box, side, off),
        ("box", box) or ("bus", bus)."""
        m = re.fullmatch(r"([A-Za-z_]\w*)(?:\.(\w+)([+-][\d.]+)?)?", s)
        if m and m.group(1) in self.boxes:
            b = self.boxes[m.group(1)]
            if m.group(2) is None:
                return ("box", b)
            if m.group(2) not in SIDES:
                raise ln.err(f"a box's sides are {', '.join(SIDES)}, not {m.group(2)}")
            return ("side", b, m.group(2), float(m.group(3) or 0) * self.unit, m.group(3) is not None)
        if m and m.group(1) in self.buses and m.group(2) is None:
            return ("bus", self.buses[m.group(1)])
        if m and not re.fullmatch(r"-?[\d.]+", m.group(1)):
            raise ln.err(f"{s} isn't a box or a bus")
        return ("pt", self.point(s, ln))


# ---------------------------------------------------------------- wires

def facing(a, b):
    """The sides of boxes a and b that face each other."""
    ax, ay = a.x + a.w / 2, a.y + a.h / 2
    bx, by = b.x + b.w / 2, b.y + b.h / 2
    gx = max(b.x - (a.x + a.w), a.x - (b.x + b.w))   # the gap across
    gy = max(b.y - (a.y + a.h), a.y - (b.y + b.h))   # and down
    if gx >= gy:
        return ("right", "left") if bx >= ax else ("left", "right")
    return ("bottom", "top") if by >= ay else ("top", "bottom")


def span(box, side):
    if side in ("left", "right"):
        return box.y, box.y + box.h
    return box.x, box.x + box.w


def sidepoint(box, side, k, v):
    """The point on box's side whose coordinate k (0: x, 1: y) is v."""
    p = list(box.side(side))
    p[k] = v
    return tuple(p)


def resolve(e1, e2):
    """The two ends' points and the directions they leave in: 'h', 'v' or None."""
    if e1[0] == "box" and e2[0] == "box":
        s1, s2 = facing(e1[1], e2[1])
        e1, e2 = ("side", e1[1], s1, 0, False), ("side", e2[1], s2, 0, False)
    elif e1[0] == "box" or e2[0] == "box":
        other = e2 if e1[0] == "box" else e1
        box = e1[1] if e1[0] == "box" else e2[1]
        ox, oy = other_point(other)
        cx, cy = box.x + box.w / 2, box.y + box.h / 2
        if ox is None:  # a bus: straight across to it
            s = bus_side(other[1], box)
        elif abs(ox - cx) - box.w / 2 >= abs(oy - cy) - box.h / 2:
            s = "right" if ox > cx else "left"
        else:
            s = "bottom" if oy > cy else "top"
        side = ("side", box, s, 0, False)
        e1, e2 = (side, e2) if e1[0] == "box" else (e1, side)
    p1, d1 = place(e1, e2)
    p2, d2 = place(e2, e1, p1)
    if e1[0] == "bus":
        p1, d1 = place(e1, e2, p2)
    s1, s2 = (e[2] if e[0] == "side" else None for e in (e1, e2))
    return (p1, d1, s1), (p2, d2, s2)


def other_point(e):
    if e[0] == "pt":
        return e[1]
    if e[0] == "side":
        return e[1].side(e[2], e[3])
    return None, None


def bus_side(bus, box):
    (ax, ay), (bx, by) = bus.a, bus.b
    if ay == by:
        return "top" if ay < box.y else "bottom"
    return "left" if ax < box.x else "right"


def place(e, other, known=None):
    """Where end e is, given the other end, and its direction."""
    if e[0] == "pt":
        return e[1], None
    if e[0] == "bus":
        (ax, ay), (bx, by) = e[1].a, e[1].b
        ref = known or other_point(other)
        if ref[0] is None:
            return ((ax + bx) / 2, (ay + by) / 2), None
        if ay == by:
            return (min(max(ref[0], min(ax, bx)), max(ax, bx)), ay), "v"
        return (ax, min(max(ref[1], min(ay, by)), max(ay, by))), "h"
    box, side, off, explicit = e[1], e[2], e[3], e[4]
    d = "h" if side in ("left", "right") else "v"
    if not explicit and other[0] == "side" and not other[4]:
        # two sides that overlap meet straight, in the middle of the overlap
        o = other[1]
        if (side in ("left", "right")) == (other[2] in ("left", "right")):
            lo = max(span(box, side)[0], span(o, other[2])[0])
            hi = min(span(box, side)[1], span(o, other[2])[1])
            if hi - lo >= 4:
                return sidepoint(box, side, 1 if d == "h" else 0, (lo + hi) / 2), d
    if not explicit and other[0] in ("pt", "bus"):
        ref = known or other_point(other)
        if ref[0] is not None:
            lo, hi = span(box, side)
            k = 1 if d == "h" else 0
            if lo + 4 <= ref[k] <= hi - 4:
                return sidepoint(box, side, k, ref[k]), d
    return box.side(side, off), d


def route(end1, end2, via, margin):
    (p1, d1, s1), (p2, d2, s2) = end1, end2
    if s1 is not None and s1 == s2 and not via:
        # two sides that face the same way: around, as a U
        (ax, ay), (bx, by) = p1, p2
        if s1 in ("top", "bottom"):
            y = max(ay, by) + margin if s1 == "bottom" else min(ay, by) - margin
            return [p1, (ax, y), (bx, y), p2]
        x = max(ax, bx) + margin if s1 == "right" else min(ax, bx) - margin
        return [p1, (x, ay), (x, by), p2]
    pts = [p1] + via + [p2]
    out = [p1]
    for i in range(len(pts) - 1):
        (ax, ay), (bx, by) = out[-1], pts[i + 1]
        if abs(ax - bx) < 0.5 or abs(ay - by) < 0.5:
            out.append((bx, by))
            continue
        first = d1 if i == 0 else ("v" if abs(out[-2][1] - ay) < 0.5 else "h")  # turn at a via
        last = d2 if i == len(pts) - 2 else None
        if first == "h" and last == "h":
            mx = (ax + bx) / 2
            out += [(mx, ay), (mx, by), (bx, by)]
        elif first == "v" and last == "v":
            my = (ay + by) / 2
            out += [(ax, my), (bx, my), (bx, by)]
        elif first == "v" or (first is None and last == "h"):
            out += [(ax, by), (bx, by)]
        else:
            out += [(bx, ay), (bx, by)]
    return out


# ---------------------------------------------------------------- drawing

def render(text):
    g = Diagram(text)
    d = Drawing()
    for label, names, ln, attrs in g.frames:
        bs = []
        for n in names:
            if n not in g.boxes:
                raise ln.err(f"{n} isn't a box")
            bs.append(g.boxes[n])
        pad = float(attrs.get("pad", 1)) * g.unit
        x0, y0 = min(b.x for b in bs) - pad, min(b.y for b in bs) - pad - (LINE if label else 0)
        x1, y1 = max(b.x + b.w for b in bs) + pad, max(b.y + b.h for b in bs) + pad
        d.rect(x0, y0, x1 - x0, y1 - y0, "thin dashed")
        if label:
            d.text(label, x0 + 6, y0 + LINE / 2 + 2, "s", 11)
    for bus in g.buses.values():
        (ax, ay), (bx, by) = bus.a, bus.b
        d.line(ax, ay, bx, by, "ink bus")
        if bus.label:
            if ay == by:
                left = min(ax, bx)
                at = bus.attrs.get("label", "start")
                if at == "end":
                    d.text(bus.label, max(ax, bx) + 6, ay, "b", 11)
                else:
                    d.text(bus.label, left, ay - 9, "b", 11)
            else:
                d.text(bus.label, ax, min(ay, by) - 10, "b", 11, "middle")
    for b in g.order:
        if b.kind == "box":
            d.rect(b.x, b.y, b.w, b.h, "ink paper" + (" dashed" if "dashed" in b.flags else ""))
            ty = b.y + b.h / 2 - (len(b.lines) - 1) * LINE / 2
            for k, (t, size, wt) in enumerate(b.lines):
                cls = ("b" if wt >= 600 else "") + (" s" if k and wt < 600 else "")
                d.text(t, b.x + b.w / 2, ty + k * LINE, cls.strip(), size, "middle", wt)
        else:
            anchor = "end" if b.place[0] == "left" else "middle" if b.place[0] in ("above", "below") else "start"
            x = {"start": b.x, "middle": b.x + b.w / 2, "end": b.x + b.w}[anchor]
            for k, (t, size, wt) in enumerate(b.lines):
                d.text(t, x, b.y + LINE / 2 + k * LINE, "b" if wt >= 600 else "s", size, anchor, wt)
    labels = []
    for a, arrow, b, label, via, ln, attrs in g.wires:
        e1, e2 = g.end(a, ln), g.end(b, ln)
        pts = route(*resolve(e1, e2), via, 2 * g.unit)
        pts = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
        d.path(pts, "ink wire" + (" dashed" if "dashed" in attrs.get("style", "") else ""))
        if arrow in ("->", "<->"):
            d.arrowhead(*pts[-1], pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1])
        if arrow in ("<-", "<->"):
            d.arrowhead(*pts[0], pts[0][0] - pts[1][0], pts[0][1] - pts[1][1])
        for e, p, head in ((e1, pts[0], arrow in ("<-", "<->")), (e2, pts[-1], arrow in ("->", "<->"))):
            if e[0] == "bus" and not head:
                d.circle(*p, 2.6)
        if label:
            labels.append((label, pts, attrs.get("place", "middle")))
    for label, pts, at in labels:
        wire_label(d, label, pts, at)
    for s, ln in g.dots:
        d.circle(*g.point(s, ln), 2.6)
    return d.svg(margin=6)


def wire_label(d, label, pts, at):
    if at in ("start", "end"):
        (x, y), (px, py) = (pts[0], pts[1]) if at == "start" else (pts[-1], pts[-2])
        if abs(px - x) < 0.5:   # a vertical end: the label beyond it
            d.text(label, x, y - 9 if py > y else y + 9, "s", 11, "middle")
        else:
            d.text(label, x - 5 if px > x else x + 5, y, "s", 11, "end" if px > x else "start")
        return
    segs = list(zip(pts, pts[1:]))
    (ax, ay), (bx, by) = max(segs, key=lambda s: abs(s[0][0] - s[1][0]) + abs(s[0][1] - s[1][1]))
    if abs(ay - by) < 0.5:
        d.text(label, (ax + bx) / 2, ay - 8, "s halo", 11, "middle")
    else:
        d.text(label, ax + 5, (ay + by) / 2, "s halo", 11, "start")
