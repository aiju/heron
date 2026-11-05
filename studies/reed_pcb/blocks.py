"""Placement by blocks: small grids of parts, each with its own pitch,
placed on the board by hand.

A **block** is a grid of cells, rows by columns, a part (or nothing) in
each; every part sits in the middle of its cell, turned so that its
longer side runs down the board and pin 1 is at the top left (as on
RFC 0046's grid). The cells' pitch, across and down, is the least that
keeps the block's parts apart by the spacing rules below, or more if
asked (so that the bands of several blocks line up), in whole steps of
0.025 inch; with a through-hole part in it, of 0.1 inch, and each
through-hole part's pin 1 on the board's 0.1 inch lattice, so that all
its pins are.

Blocks are then placed by hand: at a point, or beside another block with
a gap (`right_of`, `left_of`, `below`, `above`), aligned on an edge or
with the other block's rows or columns ("rows", "columns": the same
pitch then puts their parts' middles in line).

**Spacing, for soldering by hand** (Emily, 2026-11-05; RFC 0026's R16 is
for machine assembly):

| Between | Least gap |
|---|---|
| two surface-mount ICs | 3 mm pad to pad, 2 mm body to body (the ends without pins) |
| a surface-mount IC and a through-hole part | 3 mm pad to pad |
| two through-hole ICs | 2.54 mm pad to pad |
| two PLCC sockets | none: they may touch, their pins a whole number of 0.1 inch apart |

Courtyards never overlap. check() holds every pair of parts on the top
to these.
"""

import math

from heron.infra.pcb import kicadlib, sexpr
from heron.studies.pcb_columns.grid import orientation

ROW = 2.54
FINE = 0.635            # 0.025 inch: the grid of a surface-mount block's corner and pitch
SMD_PAD_GAP = 3.0
SMD_BODY_GAP = 2.0
THT_PAD_GAP = 2.54
MIXED_PAD_GAP = 3.0


def kind(part):
    """"smd", "socket", "tht" (another through-hole IC) or "conn"."""
    if part.kind == "conn":
        return "conn"
    if "Socket" in part.fp.name:
        return "socket"
    return "smd" if part.fp.smd else "tht"


def _body(fp):
    """The footprint's body (F.Fab), or None: (x0, y0, x1, y1)."""
    xs, ys = [], []
    for item in fp.expr:
        if not (isinstance(item, list) and item and item[0] in ("fp_line", "fp_rect", "fp_poly")):
            continue
        if sexpr.value(item, "layer") != "F.Fab":
            continue
        for key in ("start", "end"):
            e = sexpr.find(item, key)
            if e is not None:
                xs.append(float(e[1]))
                ys.append(float(e[2]))
        pts = sexpr.find(item, "pts")
        if pts is not None:
            for xy in sexpr.find_all(pts, "xy"):
                xs.append(float(xy[1]))
                ys.append(float(xy[2]))
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def extents(part):
    """A part's extents about its origin as placed at rotation part.rot,
    in board axes: {"pads": box, "body": box, "court": box} (x0, y0, x1, y1)."""
    fp, rot = part.fp, part.rot
    out = {}
    pts = []
    for d in fp.pads:
        if not d.number:
            continue
        a = math.radians(rot + d.rot)
        c, s = abs(math.cos(a)), abs(math.sin(a))
        hx, hy = (d.w * c + d.h * s) / 2, (d.w * s + d.h * c) / 2
        x, y = kicadlib.rotate(d.x, d.y, rot)
        pts += [(x - hx, y - hy), (x + hx, y + hy)]
    out["pads"] = _bbox(pts)

    def turned(box):
        x0, y0, x1, y1 = box
        return _bbox([kicadlib.rotate(x, y, rot) for x in (x0, x1) for y in (y0, y1)])
    out["court"] = turned(fp.courtyard)
    body = _body(fp)
    out["body"] = turned(body) if body else out["court"]
    return out


def _bbox(pts):
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[0] for p in pts), max(p[1] for p in pts))


def _span(box, axis):
    return box[2] - box[0] if axis == 0 else box[3] - box[1]


def least_pitch(part, axis):
    """The least pitch (mm) at which two of this part sit side by side
    (axis 0, across) or one above the other (axis 1)."""
    e = extents(part)
    k = kind(part)
    if k == "smd":
        return max(_span(e["pads"], axis) + SMD_PAD_GAP, _span(e["body"], axis) + SMD_BODY_GAP,
                   _span(e["court"], axis))
    if k == "socket":
        return _span(e["court"], axis)
    return max(_span(e["pads"], axis) + THT_PAD_GAP, _span(e["court"], axis))


class Block:
    """A grid of parts. `rows`: lists of references (None for an empty
    cell), top row first; `pitch`: (across, down) in mm, or None for the
    least the parts need (a given pitch must be at least that)."""

    def __init__(self, name, rows, pitch=(None, None)):
        self.name = name
        self.rows = [list(r) for r in rows]
        self.ncols = max(len(r) for r in self.rows)
        self.want = pitch
        self.x = self.y = None          # the top left corner of the cells
        self.parts = {}

    def refs(self):
        return [r for row in self.rows for r in row if r]

    def bind(self, board):
        """Take the parts from the board, turn them, and work out the pitch."""
        self.parts = {r: board.parts[r] for r in self.refs()}
        for p in self.parts.values():
            p.rot = orientation(p.fp)
        tht = any(kind(p) != "smd" for p in self.parts.values())
        self.pitch = []
        for axis in (0, 1):
            least = max(least_pitch(p, axis) for p in self.parts.values())
            step = ROW if tht else FINE
            least = math.ceil(least / step - 1e-6) * step
            want = self.want[axis]
            if want is not None and want < least - 1e-6:
                raise ValueError(f"block {self.name}: pitch {want} mm "
                                 f"{'across' if axis == 0 else 'down'}, less than the {least:.2f} "
                                 "its parts need")
            self.pitch.append(want if want is not None else least)
        self.tht = tht
        return self

    @property
    def width(self):
        return self.ncols * self.pitch[0]

    @property
    def height(self):
        return len(self.rows) * self.pitch[1]

    # an edge of the block is its parts' courtyards' outline, not its cells'
    def outline(self):
        xs0, ys0, xs1, ys1 = [], [], [], []
        for p in self.parts.values():
            x0, y0, x1, y1 = p.courtyard()
            xs0.append(x0)
            ys0.append(y0)
            xs1.append(x1)
            ys1.append(y1)
        return min(xs0), min(ys0), max(xs1), max(ys1)

    def at(self, x=None, y=None, right=None, bottom=None, cells_y=None, cells_x=None):
        """Put the block with its outline's left (or right) edge at x (or
        right), its top (or bottom) at y (or bottom); or its cells' top
        (left) edge at cells_y (cells_x), to line its rows (columns) up
        with another block's of the same pitch."""
        if self.x is None:
            self.x = self.y = 0.0
            self._put()
        x0, y0, x1, y1 = self.outline()
        dx = (x - x0) if x is not None else (right - x1) if right is not None else \
            (cells_x - self.x) if cells_x is not None else 0.0
        dy = (y - y0) if y is not None else (bottom - y1) if bottom is not None else \
            (cells_y - self.y) if cells_y is not None else 0.0
        self.x += dx
        self.y += dy
        self._put()
        return self

    def right_of(self, other, gap, align="top"):
        return self.at(x=other.outline()[2] + gap, **self._align(other, align))

    def left_of(self, other, gap, align="top"):
        return self.at(right=other.outline()[0] - gap, **self._align(other, align))

    def below(self, other, gap, align="left"):
        return self.at(y=other.outline()[3] + gap, **self._align(other, align))

    def above(self, other, gap, align="left"):
        return self.at(bottom=other.outline()[1] - gap, **self._align(other, align))

    def _align(self, other, align):
        x0, y0, x1, y1 = other.outline()
        return {"top": {"y": y0}, "bottom": {"bottom": y1}, "left": {"x": x0},
                "right": {"right": x1}, "rows": {"cells_y": other.y},
                "columns": {"cells_x": other.x}, "none": {}}[align]

    def _put(self):
        """Put every part in the middle of its cell; a through-hole part's
        pin 1 onto the board's 0.1 inch lattice (the nearest point), so
        the block moves as a whole with its pins on the lattice."""
        # the block's corner on the lattice (0.1 inch with a through-hole
        # part, else 0.025 inch), so every cell's is: its pitch is a whole
        # number of steps
        step = ROW if self.tht else FINE
        self.x = round(self.x / step) * step
        self.y = round(self.y / step) * step
        for i, row in enumerate(self.rows):
            for j, ref in enumerate(row):
                if not ref:
                    continue
                p = self.parts[ref]
                e = extents(p)
                cx = self.x + (j + 0.5) * self.pitch[0]
                cy = self.y + (i + 0.5) * self.pitch[1]
                bx, by = (e["court"][0] + e["court"][2]) / 2, (e["court"][1] + e["court"][3]) / 2
                ox, oy = cx - bx, cy - by
                if kind(p) != "smd":
                    one = next(d for d in p.fp.pads if d.number == "1")
                    px, py = kicadlib.rotate(one.x, one.y, p.rot)
                    ox = round((ox + px) / ROW) * ROW - px
                    oy = round((oy + py) / ROW) * ROW - py
                p.place(ox, oy, p.rot)


# ---- the checks ------------------------------------------------------------------------

def _gap(a, b):
    """The gap between two boxes, edge to edge (negative: they overlap
    by that much on both axes)."""
    gx = max(a[0], b[0]) - min(a[2], b[2])
    gy = max(a[1], b[1]) - min(a[3], b[3])
    if gx < 0 and gy < 0:
        return max(gx, gy)
    return math.hypot(max(gx, 0), max(gy, 0))


def _pads_gap(p, q):
    """The least gap between two parts' pads (as boxes), mm."""
    best = float("inf")
    qp = [(d, d.extent()) for d in q.pads() if d.number]
    for d in p.pads():
        if not d.number:
            continue
        hx, hy = d.extent()
        a = (d.x - hx, d.y - hy, d.x + hx, d.y + hy)
        for e, (ex, ey) in qp:
            if abs(e.x - d.x) > 10 or abs(e.y - d.y) > 10:
                continue
            best = min(best, _gap(a, (e.x - ex, e.y - ey, e.x + ex, e.y + ey)))
    return best


def _abs_body(p):
    e = extents(p)["body"]
    return (p.x + e[0], p.y + e[1], p.x + e[2], p.y + e[3])


def check(board, region):
    """Every pair of top-side parts (chips, sockets, connectors) against
    the spacing rules, every part inside the region (connectors aside),
    every through-hole chip's pin 1 on the 0.1 inch lattice. Returns a
    list of problems."""
    probs = []
    parts = [p for p in board.parts.values() if p.side == "F" and p.kind in ("chip", "conn")]
    for i, p in enumerate(parts):
        cp = p.courtyard()
        if p.kind != "conn":
            X0, Y0, X1, Y1 = region
            if cp[0] < X0 - 1e-6 or cp[1] < Y0 - 1e-6 or cp[2] > X1 + 1e-6 or cp[3] > Y1 + 1e-6:
                probs.append(f"{p.ref}: outside the region")
            if kind(p) != "smd":
                one = next(d for d in p.pads() if d.number == "1")
                if any(abs(v / ROW - round(v / ROW)) > 1e-3 for v in (one.x, one.y)):
                    probs.append(f"{p.ref}: pin 1 off the 0.1 inch lattice")
        for q in parts[i + 1:]:
            cq = q.courtyard()
            if _gap(cp, cq) > 12:
                continue
            if _gap(cp, cq) < -1e-6:
                probs.append(f"{p.ref} and {q.ref}: courtyards overlap")
                continue
            kp, kq = kind(p), kind(q)
            if {kp, kq} == {"socket"}:
                continue
            if "smd" in (kp, kq):
                need = SMD_PAD_GAP if kp == kq else MIXED_PAD_GAP
            else:
                need = THT_PAD_GAP
            g = _pads_gap(p, q)
            if g < need - 1e-3:
                probs.append(f"{p.ref} and {q.ref}: pads {g:.2f} mm apart, {need} needed")
            if kp == kq == "smd" and _gap(_abs_body(p), _abs_body(q)) < SMD_BODY_GAP - 1e-3:
                probs.append(f"{p.ref} and {q.ref}: bodies "
                             f"{_gap(_abs_body(p), _abs_body(q)):.2f} mm apart, {SMD_BODY_GAP} needed")
    return probs
