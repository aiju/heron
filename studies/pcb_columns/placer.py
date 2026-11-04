"""Placement on the grid: every chip in its box, no two boxes overlapping,
the free room at the bottom of the columns, the wires short.

1. **Targets:** infra's quadratic placement (Placer.global_place), each
   chip spread by its box's area: where it would like to be.
2. **Legal:** the boxes, largest first, each at the free position nearest
   its target; failing that, first fit down the columns.
3. **Annealing on the columns' stacks** (anneal_stacks), on the
   half-perimeter length of the nets at the real pads. The placement is
   each column's boxes in order from its top, each box across the column
   or in its left or right half; stacking them gives every box its row.
   A move swaps two boxes, moves one to another place in any column, or
   moves a narrow one to the other half. The free room is always at the
   bottom of the columns, but for the cells a column's box leaves above
   the shorter of two half-columns, which cost `hole` mm of wire each.

anneal() anneals the boxes' positions instead, for wire alone, the free
room wherever it falls: a box moves to free cells, or changes places with
whatever exactly fills a box of its shape elsewhere (a chip of the same
size, two narrow chips side by side for a wide one, two short ones for a
long one). It is the comparison for what tidiness costs.
"""

import math
import random

from heron.infra.pcb import kicadlib
from heron.infra.pcb.place import Placer, _clear, supply_pads

from .grid import ROW, Lattice, box


class _Targets(Placer):
    """The infra placer's global step, spreading chips by their boxes."""

    def __init__(self, board, region, areas, **kw):
        super().__init__(board, region=region, **kw)
        self.movable = [p for p in self.movable if p.ref in areas]
        self._areas = areas

    def _area(self, p):
        return self._areas[p.ref]


class GridPlacer:
    def __init__(self, board, region, params, weights=None, seed=1, hole=5.0,
                 skip_nets=("VCC", "GND")):
        self.b = board
        self.p = params
        self.region = region
        self.lat = Lattice(region, params)
        self.rng = random.Random(seed)
        self.hole = hole
        self.weights = dict(weights or {})
        self.chips = [p for p in board.parts.values() if p.kind == "chip" and not p.fixed]
        self.boxes = {p.ref: box(p, params) for p in self.chips}
        self.pos = {}
        self.occ = [[None] * self.lat.rows for _ in range(self.lat.halves)]
        self._block()
        self._nets(skip_nets)

    # ---- the grid's cells -------------------------------------------------------------

    def _block(self):
        """Block the cells under the exceptions: keep-outs no part may go
        in, and the parts off the grid (connectors, holes, fiducials) with
        a millimetre round them."""
        rects = [(k["x0"], k["y0"], k["x1"], k["y1"]) for k in self.b.keepouts
                 if "footprints" in k["no"] and "chip" not in k["allow"]]
        for p in self.b.parts.values():
            if p.fixed:
                x0, y0, x1, y1 = p.courtyard()
                rects.append((x0 - 1, y0 - 1, x1 + 1, y1 + 1))
        self.blocked = set()
        for hc in range(self.lat.halves):
            for row in range(self.lat.rows):
                cx0, cy0, cx1, cy1 = self.lat.cell(hc, row)
                for x0, y0, x1, y1 in rects:
                    if cx0 < x1 and x0 < cx1 and cy0 < y1 and y0 < cy1:
                        self.blocked.add((hc, row))
                        self.occ[hc][row] = "#"
                        break

    def _cells(self, hc, row, b):
        for i in range(hc, hc + b.w):
            for j in range(row, row + b.h):
                yield i, j

    def _free(self, hc, row, b, ignore=()):
        for i, j in self._cells(hc, row, b):
            o = self.occ[i][j]
            if o is not None and o not in ignore:
                return False
        return True

    def _set(self, ref, hc, row):
        b = self.boxes[ref]
        if ref in self.pos:
            for i, j in self._cells(*self.pos[ref], b):
                if self.occ[i][j] == ref:
                    self.occ[i][j] = None
        self.pos[ref] = (hc, row)
        for i, j in self._cells(hc, row, b):
            self.occ[i][j] = ref

    # ---- nets ---------------------------------------------------------------------------

    def _nets(self, skip):
        """Each net's pins: (chip ref, x, y from its box's corner) or
        (None, x, y on the board) for a part off the grid."""
        chips = {p.ref for p in self.chips}
        offs = {}
        for p in self.chips:
            b = self.boxes[p.ref]
            self.lat.put(p, b, 0, 0)
            x0, y0 = self.lat.x, self.lat.y
            offs[p.ref] = {d.number: (d.x - x0, d.y - y0) for d in p.pads()}
        nets = {}
        for p in self.b.parts.values():
            if p.kind == "decap" or (p.ref not in chips and not p.fixed):
                continue
            for d in p.pads():
                if not d.net or d.net in skip:
                    continue
                if p.ref in chips:
                    x, y = offs[p.ref][d.number]
                    nets.setdefault(d.net, []).append((p.ref, x, y))
                else:
                    nets.setdefault(d.net, []).append((None, d.x, d.y))
        self.nets = {}
        for n, pins in nets.items():
            ends = {r for r, _, _ in pins if r}
            fixed = sum(1 for r, _, _ in pins if r is None)
            if ends and len(ends) + fixed > 1:
                self.nets[n] = pins
        self.chip_nets = {p.ref: [] for p in self.chips}
        for n, pins in self.nets.items():
            for r in {r for r, _, _ in pins if r}:
                self.chip_nets[r].append(n)

    def _net_len(self, net):
        hw = self.p.half_mm
        xs, ys = [], []
        for r, x, y in self.nets[net]:
            if r is None:
                xs.append(x)
                ys.append(y)
            else:
                hc, row = self.pos[r]
                xs.append(self.lat.x + hc * hw + x)
                ys.append(self.lat.y + row * ROW + y)
        return (max(xs) - min(xs) + max(ys) - min(ys)) * self.weights.get(net, 1.0)

    def wire(self):
        """The nets' half-perimeter length, mm."""
        return sum(self._net_len(n) for n in self.nets)

    def _holes(self, hc):
        """The free cells of a half-column above its lowest box (blocked
        cells aren't free)."""
        col = self.occ[hc]
        n = 0
        free = 0
        for o in col:
            if o is None:
                free += 1
            elif o != "#":
                n += free
                free = 0
        return n

    def holes(self):
        """The free cells with a box below them in their half-column."""
        return sum(self._holes(hc) for hc in range(self.lat.halves))

    # ---- 1, 2: targets and a legal start --------------------------------------------------

    def targets(self):
        areas = {p.ref: self.boxes[p.ref].w * self.p.half_mm * self.boxes[p.ref].h * ROW
                 for p in self.chips}
        lat = self.lat
        t = _Targets(self.b, (lat.x, lat.y, lat.x + lat.width, lat.y + lat.height), areas,
                     weights=self.weights)
        t.global_place()
        out = {}
        for p in self.chips:
            x0, y0, x1, y1 = p.courtyard()
            out[p.ref] = ((x0 + x1) / 2, (y0 + y1) / 2)
        return out

    def legalize(self, targets):
        """Each box, largest first, at the free position whose middle is
        nearest its target. Returns the chips that found no place."""
        hw = self.p.half_mm
        order = sorted(self.chips, key=lambda p: (-self.boxes[p.ref].w * self.boxes[p.ref].h,
                                                  p.ref))
        left = []
        for p in order:
            b = self.boxes[p.ref]
            tx, ty = targets[p.ref]
            best = None
            for hc, row in self.lat.positions(b):
                if not self._free(hc, row, b):
                    continue
                mx = self.lat.x + (hc + b.w / 2) * hw
                my = self.lat.y + (row + b.h / 2) * ROW
                d = (mx - tx) ** 2 + (my - ty) ** 2
                if best is None or d < best[0]:
                    best = (d, hc, row)
            if best is None:
                left.append(p.ref)
            else:
                self._set(p.ref, best[1], best[2])
        return left

    def pack(self):
        """A legal start when legalize() can't find one: first fit, the
        widest and then the longest boxes first, each at the first free
        position going down the columns from the left. Returns the chips
        that found no place."""
        for r in list(self.pos):
            for i, j in self._cells(*self.pos[r], self.boxes[r]):
                self.occ[i][j] = None
            del self.pos[r]
        order = sorted(self.chips, key=lambda p: (-self.boxes[p.ref].w, -self.boxes[p.ref].h,
                                                  p.ref))
        left = []
        for p in order:
            b = self.boxes[p.ref]
            spots = sorted(self.lat.positions(b), key=lambda hr: (hr[0] // 2, hr[1], hr[0]))
            for hc, row in spots:
                if self._free(hc, row, b):
                    self._set(p.ref, hc, row)
                    break
            else:
                left.append(p.ref)
        return left

    # ---- 3: annealing ---------------------------------------------------------------------

    def _move(self, a, hc, row):
        """The chips that change places if `a` goes to (hc, row), as
        {ref: new position}, or None if that move isn't legal."""
        b = self.boxes[a]
        ha, ra = self.pos[a]
        if (hc, row) == (ha, ra):
            return None
        overlap = hc < ha + b.w and ha < hc + b.w and row < ra + b.h and ra < row + b.h
        inside = set()
        for i, j in self._cells(hc, row, b):
            o = self.occ[i][j]
            if o == "#":
                return None
            if o is not None and o != a:
                inside.add(o)
        if overlap:
            return None if inside else {a: (hc, row)}
        moves = {a: (hc, row)}
        dh, dr = ha - hc, ra - row
        for o in inside:
            ob = self.boxes[o]
            oh, orow = self.pos[o]
            if oh < hc or oh + ob.w > hc + b.w or orow < row or orow + ob.h > row + b.h:
                return None           # it sticks out of the box it would leave
            moves[o] = (oh + dh, orow + dr)
        return moves

    def _apply(self, moves):
        for r in moves:
            for i, j in self._cells(*self.pos[r], self.boxes[r]):
                if self.occ[i][j] == r:
                    self.occ[i][j] = None
        for r, (hc, row) in moves.items():
            self.pos[r] = (hc, row)
            for i, j in self._cells(hc, row, self.boxes[r]):
                self.occ[i][j] = r

    def _try(self, moves, t):
        """Make a move if annealing at temperature t accepts it (with t
        None, only say what it would change the wire by)."""
        old = {r: self.pos[r] for r in moves}
        nets = {n for r in moves for n in self.chip_nets[r]}
        before = sum(self._net_len(n) for n in nets)
        self._apply(moves)
        d = sum(self._net_len(n) for n in nets) - before
        if t is not None and (d <= 0 or self.rng.random() < math.exp(-d / t)):
            return d
        self._apply(old)
        return d if t is None else None

    def _candidate(self, a, reach):
        b = self.boxes[a]
        ha, ra = self.pos[a]
        m = self.p.module
        same = self._shapes[(b.w, b.h)]
        if len(same) > 1 and self.rng.random() < 0.3:
            o = self.rng.choice(same)
            return None if o == a else {a: self.pos[o], o: (ha, ra)}
        step = 2 if b.w == 2 else 1
        if reach is None:
            hc = self.rng.randrange(0, self.lat.halves - b.w + 1, step)
            row = self.rng.randrange(0, self.lat.rows - b.h + 1, m)
        else:
            dh = self.rng.randint(-reach, reach) * step
            dr = self.rng.randint(-3 * reach, 3 * reach) * m
            hc, row = ha + dh, ra + dr
            if not (0 <= hc <= self.lat.halves - b.w and 0 <= row <= self.lat.rows - b.h):
                return None
        return self._move(a, hc, row)

    def anneal(self, moves=60000, t0=None):
        """Simulated annealing of the boxes' positions for wire alone, over
        `moves` legal moves, from temperature t0 (by default the mean cost
        of a random move) down to 1/2000 of it. Returns t0."""
        refs = [p.ref for p in self.chips]
        if len(refs) < 2:
            return
        self._shapes = {}
        for r in refs:
            self._shapes.setdefault((self.boxes[r].w, self.boxes[r].h), []).append(r)
        if t0 is None:
            ds = []
            for _ in range(300):
                mv = self._candidate(self.rng.choice(refs), None)
                if mv:
                    ds.append(abs(self._try(mv, None)))
            t0 = (sum(ds) / len(ds)) if ds else 1.0
        t_end = t0 / 2000
        k = tries = 0
        while k < moves and tries < 20 * moves:
            tries += 1
            t = t0 * (t_end / t0) ** (k / moves)
            reach = None if self.rng.random() < 0.15 * t / t0 + 0.02 else \
                max(1, int(4 * (t / t0) ** 0.3))
            mv = self._candidate(self.rng.choice(refs), reach)
            if not mv:
                continue
            k += 1
            self._try(mv, t)
        return t0

    # ---- 3b: annealing on the columns' stacks ---------------------------------------

    def stacks(self):
        """The placement as each column's stack, top to bottom: [[[ref,
        side]]], side 0 or 1 for a box in the left or right half-column, 2
        for one across the column."""
        out = [[] for _ in range(self.lat.cols)]
        for r, (hc, row) in sorted(self.pos.items(), key=lambda kv: (kv[1][1], kv[1][0])):
            out[hc // 2].append([r, 2 if self.boxes[r].w == 2 else hc % 2])
        return out

    def _stack(self, c, items):
        """A column's boxes stacked from its top in their order, each as high
        as the boxes above it in its half-columns and the blocked cells
        allow: ({ref: (hc, row)}, the cost of its rows past the grid's
        bottom and of the cells left free above a box)."""
        m = self.p.module
        tops = [0, 0]
        out = {}
        over = holes = 0
        for r, side in items:
            h = self.boxes[r].h
            halves = (0, 1) if side == 2 else (side,)
            row = max(tops[i] for i in halves)
            while row + h <= self.lat.rows and any(
                    (2 * c + i, j) in self.blocked for i in halves for j in range(row, row + h)):
                row += m
            for i in halves:
                holes += row - tops[i]
                tops[i] = row + h
            out[r] = (2 * c + halves[0], row)
            over += max(0, row + h - self.lat.rows)
        return out, self.over_cost * over + self.hole * holes

    over_cost = 100.0       # mm of wire a row past the grid's bottom costs in the stacks

    def anneal_stacks(self, moves=60000, t0=None):
        """Simulated annealing on the columns' stacks: a box changes places
        with another in the stacks, moves to another place in any stack, or
        a narrow box changes half-column; the stacks then give every box its
        place, so the free room is always at the bottom (C10). A free cell
        above a box (a column's box under two half-columns of different
        heights, or a blocked cell) costs `hole` mm of wire, a row past the
        grid's bottom over_cost; the result has none of those (the start,
        from a legal placement, has none). Returns t0."""
        st = self.stacks()
        where = {r: c for c, items in enumerate(st) for r, _ in items}
        over = [0] * len(st)
        for c, items in enumerate(st):
            pos, over[c] = self._stack(c, items)
            self.pos.update(pos)
        refs = list(where)
        if len(refs) < 2:
            return t0

        def propose():
            a = self.rng.choice(refs)
            ca = where[a]
            new = {ca: [list(x) for x in st[ca]]}
            ia = next(i for i, (r, _) in enumerate(new[ca]) if r == a)
            k = self.rng.random()
            if k < 0.4:                                   # change places with another box
                b = self.rng.choice(refs)
                if b == a:
                    return None
                cb = where[b]
                new.setdefault(cb, [list(x) for x in st[cb]])
                ib = next(i for i, (r, _) in enumerate(new[cb]) if r == b)
                ea, eb = new[ca][ia], new[cb][ib]
                new[ca][ia], new[cb][ib] = eb, ea
                # a narrow box takes the half-column of the one it replaces
                if ea[1] != 2 and eb[1] != 2:
                    ea[1], eb[1] = eb[1], ea[1]
            elif k < 0.85 or self.boxes[a].w == 2:       # move to another place
                e = new[ca].pop(ia)
                cb = self.rng.randrange(len(st))
                new.setdefault(cb, [list(x) for x in st[cb]])
                if e[1] != 2:
                    e[1] = self.rng.randrange(2)
                new[cb].insert(self.rng.randrange(len(new[cb]) + 1), e)
            else:                                         # the other half-column
                new[ca][ia][1] ^= 1
            return new

        def evaluate(new):
            pos, ov = {}, {}
            for c, items in new.items():
                p, ov[c] = self._stack(c, items)
                pos.update(p)
            moved = {r: q for r, q in pos.items() if self.pos[r] != q}
            nets = {n for r in moved for n in self.chip_nets[r]}
            before = sum(self._net_len(n) for n in nets) + sum(over[c] for c in new)
            old = {r: self.pos[r] for r in moved}
            self.pos.update(moved)
            after = sum(self._net_len(n) for n in nets) + sum(ov.values())
            self.pos.update(old)
            return after - before, moved, ov

        if t0 is None:
            ds = []
            for _ in range(300):
                new = propose()
                if new:
                    ds.append(abs(evaluate(new)[0]))
            t0 = (sum(ds) / len(ds)) if ds else 1.0
        t_end = t0 / 2000
        for k in range(moves):
            t = t0 * (t_end / t0) ** (k / moves)
            new = propose()
            if not new:
                continue
            d, moved, ov = evaluate(new)
            if d <= 0 or self.rng.random() < math.exp(-d / t):
                self.pos.update(moved)
                for c, items in new.items():
                    st[c] = items
                    over[c] = ov[c]
                    for r, _ in items:
                        where[r] = c
        for c, items in enumerate(st):
            if max((self.pos[r][1] + self.boxes[r].h for r, _ in items), default=0) > self.lat.rows:
                raise RuntimeError("the stacks ended past the grid's bottom")
        self.occ = [[None if o != "#" else o for o in col] for col in self.occ]
        for r, (hc, row) in self.pos.items():
            for i, j in self._cells(hc, row, self.boxes[r]):
                self.occ[i][j] = r
        return t0

    # ---- the result ---------------------------------------------------------------------------

    def commit(self):
        """Put every chip on the board at its position."""
        for p in self.chips:
            if p.ref in self.pos:
                self.lat.put(p, self.boxes[p.ref], *self.pos[p.ref])

    def run(self, moves=60000, tidy=True):
        """Place the chips: targets, a legal start, then annealing on the
        columns' stacks (with tidy) or of the positions for wire alone.
        Returns the chips that found no place."""
        left = self.legalize(self.targets())
        if left:
            left = self.pack()
        if not left:
            if tidy:
                self.anneal_stacks(moves)
            else:
                self.anneal(moves)
        self.commit()
        return left

    def used(self):
        """The share of the grid's free cells the boxes take."""
        free = self.lat.halves * self.lat.rows - len(self.blocked)
        taken = sum(self.boxes[r].w * self.boxes[r].h for r in self.pos)
        return taken / free if free else 0.0

    def demand(self):
        """The cells the boxes need over the grid's free cells, placed or
        not: more than 1 can't fit."""
        free = self.lat.halves * self.lat.rows - len(self.blocked)
        need = sum(b.w * b.h for b in self.boxes.values())
        return need / free if free else float("inf")



def place_decaps(board, step=0.635):
    """Each chip's capacitor C<ref> under it, on the bottom: on the line
    down its middle, turned along it, at the first spot from its VCC pin
    inwards where the capacitor's pads keep a millimetre from the chip's
    own (for a DIP, level with the VCC pin, between the pin rows)."""
    for c in board.parts.values():
        if c.kind != "decap":
            continue
        chip = board.parts.get(c.ref[1:])
        vcc = supply_pads(chip) if chip else []
        if not vcc:
            continue
        v = vcc[0]
        bx, by = chip.body_centre()
        reach = max(abs(d.x) for d in c.fp.pads)
        sign = 1 if by >= v.y else -1
        spot = (bx, by)
        for k in range(int(abs(by - v.y) / step) + 1):
            t = v.y + sign * k * step
            if all(_clear(chip, bx, t + e, 1.0) for e in (-reach, reach)):
                spot = (bx, t)
                break
        dx, dy = kicadlib.rotate(spot[0], spot[1], chip.rot)
        c.place(chip.x + dx, chip.y + dy, (chip.rot + 90) % 180, "B")
