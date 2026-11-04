"""The grid: half-columns and columns across the board, rows of 0.1 inch
down it (RFC 0046).

- A **row** is 0.1 inch (2.54 mm). Every height on the grid is a whole
  number of rows, and a DIP's pins are a row apart.
- A **half-column** is `half` rows wide (0.5 inch by default) and holds a
  0.3 inch DIP; a **column** is two half-columns side by side and holds a
  0.6 inch DIP. Along its length a column can change between the two: a
  74181 across the whole column, then two stacks of narrow DIPs below it.
- Every part on the grid gets a **box**: one or two half-columns wide
  (two starting on a column's left half), a whole number of rows high,
  starting on a row (on a module, below). The part sits in the middle of
  its box, turned so that its longer side runs down the column and pin 1
  is at the top left. A through-hole part's pins land on the 0.1 inch
  lattice, as near the middle as that allows while its courtyard stays in
  the box; where it can't (a 0.3 inch DIP in a half-column of 0.4 inch),
  on the 0.05 inch lattice.

A DIP's box is its pins' rows plus the gap: `gap` rows from its last pin
to the first pin of the chip below. Any other part's box is the fewest
half-columns, and rows, that hold its courtyard with the room a DIP's
courtyard gets. With `module` > 1 a box's height is rounded up to whole
modules of that many rows and starts on one, so that boxes line up
across the columns.

Parts off the grid (connectors, holes, fiducials) are exceptions: they
keep their own places, and the grid cells under them are blocked.
"""

import math
from dataclasses import dataclass

from heron.infra.pcb import kicadlib

ROW = 2.54              # mm: 0.1 inch
EPS = 1e-6

# A DIP footprint of KiCad's library, in each pad style
DIP_STYLES = {"round": "", "long": "_LongPads", "socket": "_Socket",
              "socket-long": "_Socket_LongPads"}


@dataclass(frozen=True)
class Params:
    """The grid's parameters (RFC 0046, section 2)."""
    half: int = 5           # a half-column's width, in rows (0.1 inch)
    gap: int = 2            # rows from a DIP's last pin to the pin 1 of the DIP below it
    module: int = 1         # box heights are whole modules of this many rows
    pads: str = "round"     # the DIPs' footprints: round, long, socket, socket-long

    def __post_init__(self):
        if self.half < 4:
            raise ValueError("a half-column must be at least 4 rows (0.4 inch) wide")
        if self.gap < 2:
            raise ValueError("two DIPs' end pins must be at least 2 rows (0.2 inch) apart")
        if self.module < 1 or self.pads not in DIP_STYLES:
            raise ValueError(f"bad parameters {self}")

    @property
    def half_mm(self):
        return self.half * ROW

    def label(self):
        return f"h{self.half}-g{self.gap}-m{self.module}-{self.pads}"


def dip_footprint(name, pads):
    """KiCad's DIP footprint `name` (without a pad style) in a pad style."""
    base = name
    for suffix in sorted(DIP_STYLES.values(), key=len, reverse=True):
        if suffix and base.endswith(suffix):
            base = base[:-len(suffix)]
            break
    return base + DIP_STYLES[pads]


def is_dip(fp):
    return fp.name.startswith("Package_DIP:DIP-")


def _pads(fp, rot):
    """The numbered pads' centres and half-sizes, turned by rot: [(number,
    x, y, hx, hy)]."""
    out = []
    for d in fp.pads:
        if not d.number:
            continue
        x, y = kicadlib.rotate(d.x, d.y, rot)
        a = math.radians(rot + d.rot)
        c, s = abs(math.cos(a)), abs(math.sin(a))
        out.append((d.number, x, y, (d.w * c + d.h * s) / 2, (d.w * s + d.h * c) / 2))
    return out


def _courtyard(fp, rot):
    x0, y0, x1, y1 = fp.courtyard
    pts = [kicadlib.rotate(x, y, rot) for x in (x0, x1) for y in (y0, y1)]
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[0] for p in pts), max(p[1] for p in pts))


def orientation(fp):
    """The rotation that puts the footprint's longer side down the column
    and its pin 1 nearest the top left of its pads."""
    best = None
    for rot in (0, 270, 90, 180):
        pads = _pads(fp, rot)
        if not pads:
            return 0
        xs = [p[1] for p in pads]
        ys = [p[2] for p in pads]
        x0, y0, x1, y1 = _courtyard(fp, rot)
        tall = (y1 - y0) >= (x1 - x0) - EPS
        one = [p for p in pads if p[0] == "1"] or pads[:1]
        _, px, py, _, _ = one[0]
        key = (not tall, round(py - min(ys), 3), round(px - min(xs), 3))
        if best is None or key < best[0]:
            best = (key, rot)
    return best[1]


def _on_lattice(pads):
    """Whether every pad is a whole number of rows from pad 1, both ways."""
    one = [p for p in pads if p[0] == "1"] or pads[:1]
    _, x1, y1, _, _ = one[0]
    for _, x, y, _, _ in pads:
        for v in (x - x1, y - y1):
            if abs(v / ROW - round(v / ROW)) > 1e-3:
                return False
    return True


@dataclass
class Box:
    """A part's box: `w` half-columns by `h` rows, the part turned by
    `rot`, its footprint's origin at (dx, dy) mm from the box's top left;
    `pitch` is the lattice its pins are on, across and down (ROW, ROW / 2,
    or None for a part placed by its middle alone)."""
    w: int
    h: int
    rot: float
    dx: float
    dy: float
    pitch: tuple


def _snap(ideal, lo, hi, size):
    """Where pad 1 goes along one axis: `ideal` puts the part in the middle
    of the box (0 to size), lo and hi are its courtyard's ends from pad 1.
    On the 0.1 inch lattice if the courtyard stays in the box there (the
    nearer side first, half a row going up and to the left), else on the
    0.05 inch one (also when the courtyard is too big for the box, which
    the placement's check reports): (position, pitch)."""
    near = math.floor(ideal / ROW + 0.5 - 1e-3)
    far = near + 1 if ideal / ROW > near else near - 1
    half = math.floor(ideal / (ROW / 2) + 0.5 - 1e-3) * ROW / 2
    for v, pitch in ((near * ROW, ROW), (far * ROW, ROW)):
        if v + lo >= -EPS and v + hi <= size + EPS:
            return v, pitch
    return half, ROW / 2


def _dip_clearance(params):
    """The rows' room a DIP's courtyard leaves in its box, mm: what any
    other part gets too."""
    fp = kicadlib.footprint(dip_footprint("Package_DIP:DIP-14_W7.62mm", params.pads))
    x0, y0, x1, y1 = fp.courtyard
    return (6 + params.gap) * ROW - (y1 - y0)


def box(part, params):
    """The box of a part (an infra.pcb Part) on the grid."""
    fp = part.fp
    rot = orientation(fp)
    pads = _pads(fp, rot)
    cx0, cy0, cx1, cy1 = _courtyard(fp, rot)
    xs = [p[1] for p in pads]
    ys = [p[2] for p in pads]
    if is_dip(fp):
        span = max(xs) - min(xs)
        w = 1 if span <= 3 * ROW + EPS else 2
        h = round((max(ys) - min(ys)) / ROW) + params.gap
    else:
        cw = cx1 - cx0
        if cw <= params.half_mm + EPS:
            w = 1
        elif cw <= 2 * params.half_mm + EPS:
            w = 2
        else:
            raise ValueError(f"{part.ref}: {cw:.2f} mm wide, more than a column")
        h = math.ceil((cy1 - cy0 + _dip_clearance(params)) / ROW - EPS)
    h = -(-h // params.module) * params.module
    W, H = w * params.half_mm, h * ROW
    if part.tht and _on_lattice(pads):
        # the pads' middle in the box's, then pad 1 onto the lattice
        one = [p for p in pads if p[0] == "1"] or pads[:1]
        _, px, py, _, _ = one[0]
        ix, pitch_x = _snap((W - (max(xs) - min(xs))) / 2 + (px - min(xs)),
                            cx0 - px, cx1 - px, W)
        iy, pitch_y = _snap((H - (max(ys) - min(ys))) / 2 + (py - min(ys)),
                            cy0 - py, cy1 - py, H)
        return Box(w, h, rot, ix - px, iy - py, (pitch_x, pitch_y))
    return Box(w, h, rot, W / 2 - (cx0 + cx1) / 2, H / 2 - (cy0 + cy1) / 2, (None, None))


class Lattice:
    """The grid on a board: `cols` columns (2 * cols half-columns) and
    `rows` rows, its top left corner at (x, y) on the board. It is the
    largest that fits the region, centred in it, its corner on the board's
    own 0.1 inch grid (from the board's top left corner), so that KiCad's
    grid finds the pins."""

    def __init__(self, region, params):
        self.p = params
        x0, y0, x1, y1 = region
        fw = 2 * params.half_mm
        self.cols = int((x1 - x0 + EPS) // fw)
        self.rows = int((y1 - y0 + EPS) // ROW) // params.module * params.module
        self.x = self._origin(x0, x1, self.cols * fw)
        self.y = self._origin(y0, y1, self.rows * ROW)
        if self.x is None:
            self.cols -= 1
            self.x = self._origin(x0, x1, self.cols * fw)
        if self.y is None:
            self.rows -= params.module
            self.y = self._origin(y0, y1, self.rows * ROW)

    @staticmethod
    def _origin(lo, hi, size):
        ideal = lo + (hi - lo - size) / 2
        for k in sorted(range(math.floor(ideal / ROW) - 2, math.floor(ideal / ROW) + 3),
                        key=lambda k: abs(k * ROW - ideal)):
            if k * ROW >= lo - EPS and k * ROW + size <= hi + EPS:
                return k * ROW
        return None

    @property
    def halves(self):
        return 2 * self.cols

    @property
    def width(self):
        return self.cols * 2 * self.p.half_mm

    @property
    def height(self):
        return self.rows * ROW

    def cell(self, hc, row):
        """The board rectangle of a half-column's row: (x0, y0, x1, y1)."""
        x = self.x + hc * self.p.half_mm
        y = self.y + row * ROW
        return x, y, x + self.p.half_mm, y + ROW

    def rect(self, hc, row, w, h):
        x = self.x + hc * self.p.half_mm
        y = self.y + row * ROW
        return x, y, x + w * self.p.half_mm, y + h * ROW

    def put(self, part, b, hc, row):
        """Place a part in its box with its top left at (hc, row)."""
        x0, y0, _, _ = self.rect(hc, row, b.w, b.h)
        part.place(x0 + b.dx, y0 + b.dy, b.rot)

    def positions(self, b):
        """Every (hc, row) a box may start at: a two-half-column box on a
        column's left half, every box on a module."""
        step = 2 if b.w == 2 else 1
        for hc in range(0, self.halves - b.w + 1, step):
            for row in range(0, self.rows - b.h + 1, self.p.module):
                yield hc, row
