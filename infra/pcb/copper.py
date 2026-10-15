"""The connectivity of a board's copper, from its geometry alone.

Every piece of copper is a shape on one or more layers: a pad (a
rectangle, a circle or an oval, on its layers, or all of them if plated
through), a track (a segment with a width), a via (a circle on every
layer) and a zone's filled polygons. Two pieces that touch on a common
layer are connected. Union-find over all of them gives the pieces of
copper, and each piece's pads; nets play no part in it.

connectivity() returns the pads of each piece; check() compares them with
the nets the board file gives its pads: a net in more than one piece is
open, a piece with pads of two nets a short. The zones must be filled
(fill_zones() does it with KiCad's own filler, if KiCad is installed).
"""

import math
from collections import defaultdict

CELL = 2.0          # spatial hash cell (mm)


class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        p = self.p
        while p[a] != a:
            p[a] = p[p[a]]
            a = p[a]
        return a

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[b] = a


# ---- shapes: everything is a "capsule" (a segment with a radius) or a
# rotated rectangle; distance tests between them --------------------------------

def _seg_dist(ax, ay, bx, by, cx, cy, dx, dy):
    """Distance between segments AB and CD."""
    def pt_seg(px, py, x1, y1, x2, y2):
        vx, vy = x2 - x1, y2 - y1
        L = vx * vx + vy * vy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - x1) * vx + (py - y1) * vy) / L))
        return math.hypot(px - x1 - t * vx, py - y1 - t * vy)

    def cross(ox, oy, px, py, qx, qy):
        return (px - ox) * (qy - oy) - (py - oy) * (qx - ox)

    d1, d2 = cross(ax, ay, bx, by, cx, cy), cross(ax, ay, bx, by, dx, dy)
    d3, d4 = cross(cx, cy, dx, dy, ax, ay), cross(cx, cy, dx, dy, bx, by)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 != 0 and d2 != 0:
        return 0.0
    return min(pt_seg(ax, ay, cx, cy, dx, dy), pt_seg(bx, by, cx, cy, dx, dy),
               pt_seg(cx, cy, ax, ay, bx, by), pt_seg(dx, dy, ax, ay, bx, by))


class Shape:
    """A capsule (segment x1,y1-x2,y2 swept by radius r) or a rotated
    rectangle (centre, half sizes, angle) swept by its corner radius r
    (a rounded rectangle; 0 for a plain one), on a set of layers ("*":
    all). A rectangle's hw and hh are its inner rectangle's."""

    def __init__(self, kind, layers, **kw):
        self.kind = kind
        self.layers = layers
        self.r = 0.0
        self.__dict__.update(kw)
        if kind == "capsule":
            self.box = (min(self.x1, self.x2) - self.r, min(self.y1, self.y2) - self.r,
                        max(self.x1, self.x2) + self.r, max(self.y1, self.y2) + self.r)
        else:
            a = math.radians(self.angle)
            c, s = math.cos(a), math.sin(a)
            self.ux, self.uy = c, -s          # the rectangle's axes (KiCad: y down)
            self.vx, self.vy = s, c
            ex = abs(self.hw * c) + abs(self.hh * s) + self.r
            ey = abs(self.hw * s) + abs(self.hh * c) + self.r
            self.box = (self.cx - ex, self.cy - ey, self.cx + ex, self.cy + ey)

    def on(self, layer):
        return self.layers == "*" or layer in self.layers

    def corners(self):
        out = []
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            out.append((self.cx + sx * self.hw * self.ux + sy * self.hh * self.vx,
                        self.cy + sx * self.hw * self.uy + sy * self.hh * self.vy))
        return out

    def contains(self, x, y, margin=0.0):
        if self.kind == "capsule":
            return _seg_dist(self.x1, self.y1, self.x2, self.y2, x, y, x, y) <= self.r + margin
        return _rect_pt_dist(self, x, y) <= self.r + margin


def distance(a, b):
    """The distance between the cores of two shapes: a capsule's segment,
    a rectangle's inner rectangle (0 if they overlap)."""
    if a.kind == "capsule" and b.kind == "capsule":
        return _seg_dist(a.x1, a.y1, a.x2, a.y2, b.x1, b.y1, b.x2, b.y2)
    if a.kind == "capsule":
        a, b = b, a
    ca = a.corners()
    if b.kind == "capsule":
        if a.contains_core(b.x1, b.y1) or a.contains_core(b.x2, b.y2):
            return 0.0
        return min(_seg_dist(*ca[i], *ca[(i + 1) % 4], b.x1, b.y1, b.x2, b.y2) for i in range(4))
    if any(b.contains_core(x, y) for x, y in ca) or any(a.contains_core(x, y) for x, y in b.corners()):
        return 0.0
    cb = b.corners()
    return min(_seg_dist(*ca[i], *ca[(i + 1) % 4], *cb[j], *cb[(j + 1) % 4])
               for i in range(4) for j in range(4))


def touch(a, b, eps=1e-4):
    """Whether two shapes overlap (or touch)."""
    return distance(a, b) <= a.r + b.r + eps


def _contains_core(self, x, y):
    return _rect_pt_dist(self, x, y) <= 1e-9


Shape.contains_core = _contains_core


def _rect_pt_dist(rect, x, y):
    dx, dy = x - rect.cx, y - rect.cy
    u = abs(dx * rect.ux + dy * rect.uy) - rect.hw
    v = abs(dx * rect.vx + dy * rect.vy) - rect.hh
    return math.hypot(max(u, 0), max(v, 0))


def pad_shape(pad):
    """The copper of a pad: a circle or an oval as a capsule, anything
    else as its rectangle."""
    layers = pad.layers
    if pad.shape in ("circle", "oval"):
        a = math.radians(pad.angle)
        c, s = math.cos(a), -math.sin(a)
        if pad.shape == "circle" or abs(pad.w - pad.h) < 1e-6:
            r = pad.w / 2
            return Shape("capsule", layers, x1=pad.x, y1=pad.y, x2=pad.x, y2=pad.y, r=r)
        if pad.w > pad.h:
            half, r, ux, uy = (pad.w - pad.h) / 2, pad.h / 2, c, s
        else:
            half, r, ux, uy = (pad.h - pad.w) / 2, pad.w / 2, -s, c
        return Shape("capsule", layers, x1=pad.x - ux * half, y1=pad.y - uy * half,
                     x2=pad.x + ux * half, y2=pad.y + uy * half, r=r)
    rr = pad.d.rratio * min(pad.w, pad.h) if pad.shape == "roundrect" else 0.0
    return Shape("rect", layers, cx=pad.x, cy=pad.y, hw=pad.w / 2 - rr, hh=pad.h / 2 - rr,
                 angle=pad.angle, r=rr)


# ---- zones: filled polygons ----------------------------------------------------------

class Poly:
    """A filled polygon on a layer, with its edges bucketed by row for
    point-in-polygon tests and by cell for distance tests."""

    def __init__(self, layer, pts, net):
        self.layer, self.pts, self.net = layer, pts, net
        self.rows = defaultdict(list)
        self.cells = defaultdict(list)
        n = len(pts)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        self.box = (min(xs), min(ys), max(xs), max(ys))
        for i in range(n):
            (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % n]
            for r in range(int(math.floor(min(y1, y2) / CELL)), int(math.floor(max(y1, y2) / CELL)) + 1):
                self.rows[r].append((x1, y1, x2, y2))
            for cx in range(int(math.floor(min(x1, x2) / CELL)), int(math.floor(max(x1, x2) / CELL)) + 1):
                for cy in range(int(math.floor(min(y1, y2) / CELL)), int(math.floor(max(y1, y2) / CELL)) + 1):
                    self.cells[(cx, cy)].append((x1, y1, x2, y2))

    def inside(self, x, y):
        c = False
        for (x1, y1, x2, y2) in self.rows.get(int(math.floor(y / CELL)), ()):
            if (y1 > y) != (y2 > y):
                xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                if xi > x:
                    c = not c
        return c

    def touches(self, shape):
        x0, y0, x1, y1 = shape.box
        if x1 < self.box[0] or x0 > self.box[2] or y1 < self.box[1] or y0 > self.box[3]:
            return False
        if shape.kind == "capsule":
            if self.inside(shape.x1, shape.y1):
                return True
        else:
            if self.inside(shape.cx, shape.cy):
                return True
        seen = set()
        for cx in range(int(math.floor(x0 / CELL)), int(math.floor(x1 / CELL)) + 1):
            for cy in range(int(math.floor(y0 / CELL)), int(math.floor(y1 / CELL)) + 1):
                for e in self.cells.get((cx, cy), ()):
                    if e in seen:
                        continue
                    seen.add(e)
                    edge = Shape("capsule", "*", x1=e[0], y1=e[1], x2=e[2], y2=e[3], r=0.0)
                    if touch(edge, shape):
                        return True
        return False


# ---- connectivity ----------------------------------------------------------------------

def connectivity(board):
    """The pieces of copper: a list of sets of (ref, pad number), one per
    piece that has pads, and the number of pieces without any (floating
    copper)."""
    items = []          # (shape, pad key or None)
    for pad in board.pads():
        if pad.kind == "np_thru_hole" or not pad.number or not pad.layers:
            continue
        items.append((pad_shape(pad), (pad.part.ref, pad.number)))
    for (layer, x1, y1, x2, y2, w, net) in board.tracks:
        items.append((Shape("capsule", [layer], x1=x1, y1=y1, x2=x2, y2=y2, r=w / 2), None))
    for (x, y, dia, drill, net) in board.vias:
        items.append((Shape("capsule", "*", x1=x, y1=y, x2=x, y2=y, r=dia / 2), None))
    polys = []
    for z in board.zones:
        for pts in z.get("filled") or []:
            polys.append(Poly(z["layer"], pts, z["net"]))
    n = len(items)
    uf = _UF(n + len(polys))
    grid = defaultdict(list)
    for i, (s, _) in enumerate(items):
        x0, y0, x1, y1 = s.box
        for cx in range(int(math.floor(x0 / CELL)), int(math.floor(x1 / CELL)) + 1):
            for cy in range(int(math.floor(y0 / CELL)), int(math.floor(y1 / CELL)) + 1):
                grid[(cx, cy)].append(i)
    done = set()
    for cell, members in grid.items():
        for a in range(len(members)):
            i = members[a]
            si = items[i][0]
            for b in range(a + 1, len(members)):
                j = members[b]
                if (i, j) in done:
                    continue
                done.add((i, j))
                sj = items[j][0]
                if not _share_layer(si, sj):
                    continue
                bi, bj = si.box, sj.box
                if bi[2] < bj[0] or bj[2] < bi[0] or bi[3] < bj[1] or bj[3] < bi[1]:
                    continue
                if touch(si, sj):
                    uf.union(i, j)
    for k, poly in enumerate(polys):
        for i, (s, _) in enumerate(items):
            if s.on(poly.layer) and poly.touches(s):
                uf.union(n + k, i)
    pieces = defaultdict(set)
    roots = set()
    for i, (s, key) in enumerate(items):
        r = uf.find(i)
        roots.add(r)
        if key is not None:
            pieces[r].add(key)
    floating = len(roots) - len(pieces)
    return list(pieces.values()), floating


def _share_layer(a, b):
    if a.layers == "*" or b.layers == "*":
        return True
    return bool(set(a.layers) & set(b.layers))


def check(board):
    """Opens and shorts: the copper's pieces against the pads' nets.
    Returns a list of strings, empty if every net is one piece and no
    piece has two nets."""
    pieces, floating = connectivity(board)
    net_of = {}
    for p in board.parts.values():
        for d in p.fp.pads:
            if d.number:
                net_of[(p.ref, d.number)] = p.nets.get(d.number)
    errs = []
    by_net = defaultdict(list)
    for i, piece in enumerate(pieces):
        nets = {net_of.get(k) for k in piece}
        named = {n for n in nets if n}
        if len(named) > 1 or (named and None in nets and len(piece) > 1):
            show = sorted(named | ({"(no net)"} if None in nets else set()))
            errs.append(f"short: {', '.join(show[:6])}{' ...' if len(show) > 6 else ''}")
        for n in named:
            by_net[n].append(i)
    for net, idx in sorted(by_net.items()):
        if len(idx) > 1:
            sizes = sorted((len(pieces[i]) for i in idx), reverse=True)
            errs.append(f"open: {net} is in {len(idx)} pieces (pads {sizes})")
    return errs


def fill_zones(path, out=None):
    """Fill the zones of a board file with KiCad's own filler (pcbnew's
    Python module, KiCad 9 or 10) and save it."""
    import pcbnew
    b = pcbnew.LoadBoard(path)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(out or path, b)
