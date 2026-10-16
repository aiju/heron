"""Placement: where each part goes.

Three steps, the classic ones for standard cells, with packages as cells:

1. **Global** (global_place): each part a point; minimise the squared
   length of every connection (each net a clique, weighted 1/(k-1)), with
   the fixed parts (connectors) as anchors. A quadratic program: one
   linear solve per axis. Its solution bunches up, so it is spread by
   rank, region by region, until the density matches the board's.
2. **Legal** (legalize): parts, largest first, go to the nearest free spot
   on a grid of sites, with a halo around each part for its escape
   routing.
3. **Detail** (refine): simulated annealing on the half-perimeter wire
   length of the real pads: swap two parts with the same footprint, or
   turn one by 180 degrees.

Then place_decaps puts each chip's decoupling capacitor under it on the
other side, by its VCC pin, or beside it.

With sides="FB" the board is double-sided: a surface-mount part may go on
either side (through-hole parts take both), and the decoupling
capacitors go beside their chips, in room the legalisation keeps for
them at the chip's VCC end.

GridPlacer does the same steps on a grid of slots: rows and columns of
chips, all the same way round, as on the classic TTL boards.
"""

import math
import random
from collections import defaultdict

import numpy as np

from . import kicadlib, packages


DECAP_ROOM = 2.4          # mm kept at a chip's VCC end for a capacitor beside it
# least gaps between courtyards (which reach 0.25 mm past the pads), for
# assembly: 2.5 mm from a through-hole pad to a surface-mount one, 2.54 mm
# between through-hole pads (RFC 0026)
SMD_THT_GAP = 2.0
THT_THT_GAP = 2.04
THT_BOTTOM_CLEAR = 5.0    # no part on the bottom within this of a through-hole pad


class Placer:
    def __init__(self, board, region=None, halo=1.5, grid=0.635, skip_nets=("VCC", "GND"),
                 seed=1, sides="F", decaps="under", weights=None):
        """region: (x0, y0, x1, y1) the parts may use (default: the board
        less 3 mm), its corner moved onto the grid; halo: free space kept
        around each part's courtyard (mm); sides: "F" or "FB"; decaps:
        "under" (on the other side) or "beside" (room kept for them);
        weights: {net: factor} for nets whose length matters more (timing-
        critical ones), in both the global placement and the annealing."""
        self.weights = dict(weights or {})
        self._too_small = {}
        self.b = board
        x0, y0, x1, y1 = region or (3.0, 3.0, board.width - 3.0, board.height - 3.0)
        x0, y0 = math.ceil(x0 / grid) * grid, math.ceil(y0 / grid) * grid
        self.region = (x0, y0, x1, y1)
        self.halo = halo
        self.grid = grid
        self.res = 0.127            # the occupancy map's resolution
        self.sides = sides
        self.decaps = "beside" if sides == "FB" else decaps
        self.rng = random.Random(seed)
        self.skip = set(skip_nets)
        self.movable = [p for p in board.parts.values() if p.kind not in ("decap",) and not p.fixed]
        self.fixed = [p for p in board.parts.values() if p.fixed]
        self._smd = any(not p.tht for p in self.movable)
        self.nets = defaultdict(list)            # net -> [(part, pad number)]
        for p in board.parts.values():
            if p.kind == "decap":
                continue
            for num, net in p.nets.items():
                if net and net not in self.skip:
                    self.nets[net].append((p, num))
        self.nets = {n: v for n, v in self.nets.items() if len({p.ref for p, _ in v}) > 1}

    # ---- 1. global ------------------------------------------------------------------

    def global_place(self):
        idx = {p.ref: i for i, p in enumerate(self.movable)}
        n = len(self.movable)
        A = np.zeros((n, n))
        bx = np.zeros(n)
        by = np.zeros(n)
        for net, pins in self.nets.items():
            parts = {}
            for p, num in pins:
                parts.setdefault(p.ref, p)
            ps = list(parts.values())
            k = len(ps)
            if k < 2:
                continue
            w = 1.0 / (k - 1)
            if k > 12:                  # long nets pull too hard as cliques
                w *= 12.0 / k
            w *= self.weights.get(net, 1.0)
            for a in range(k):
                for c in range(a + 1, k):
                    pa, pc = ps[a], ps[c]
                    ia, ic = idx.get(pa.ref), idx.get(pc.ref)
                    if ia is not None and ic is not None:
                        A[ia, ia] += w
                        A[ic, ic] += w
                        A[ia, ic] -= w
                        A[ic, ia] -= w
                    elif ia is not None or ic is not None:
                        i, f = (ia, pc) if ia is not None else (ic, pa)
                        fx, fy = self._pad_centre(f, net)
                        A[i, i] += w
                        bx[i] += w * fx
                        by[i] += w * fy
        x0, y0, x1, y1 = self.region
        # a weak pull to the middle keeps parts without anchors in place
        A += np.eye(n) * 1e-3
        bx += 1e-3 * (x0 + x1) / 2
        by += 1e-3 * (y0 + y1) / 2
        X = np.linalg.solve(A, bx)
        Y = np.linalg.solve(A, by)
        X, Y = self._spread(X, Y)
        for p, x, y in zip(self.movable, X, Y):
            p.place(float(x), float(y), p.rot, p.side)

    def _pad_centre(self, part, net):
        pts = [(pd.x, pd.y) for pd in part.pads() if pd.net == net]
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

    def _area(self, p):
        x0, y0, x1, y1 = p.fp.courtyard
        m = 2 * self._margin(p)
        a = (x1 - x0 + m) * (y1 - y0 + m)
        if self._beside(p):
            a += DECAP_ROOM * min(x1 - x0, y1 - y0)
        if self.sides == "FB" and not p.tht and p.kind != "conn":
            a /= 2              # half the surface parts go on each side
        return a

    def _spread(self, X, Y):
        """Recursive bisection by area: split the parts at the median of
        their coordinate (by area) along the longer side of the region,
        and give each half a share of the region in proportion."""
        areas = np.array([self._area(p) for p in self.movable])
        out_x, out_y = X.copy(), Y.copy()

        def rec(ids, rx0, ry0, rx1, ry1):
            if len(ids) == 1:
                i = ids[0]
                out_x[i], out_y[i] = (rx0 + rx1) / 2, (ry0 + ry1) / 2
                return
            if rx1 - rx0 >= ry1 - ry0:
                order = sorted(ids, key=lambda i: X[i])
                coord = "x"
            else:
                order = sorted(ids, key=lambda i: Y[i])
                coord = "y"
            tot = areas[order].sum()
            acc, cut = 0.0, 1
            for j, i in enumerate(order):
                acc += areas[i]
                if acc >= tot / 2:
                    cut = max(1, min(len(order) - 1, j + (1 if acc - areas[i] / 2 < tot / 2 else 0)))
                    break
            a, b = order[:cut], order[cut:]
            fa = areas[a].sum() / tot
            if coord == "x":
                xm = rx0 + (rx1 - rx0) * fa
                rec(a, rx0, ry0, xm, ry1)
                rec(b, xm, ry0, rx1, ry1)
            else:
                ym = ry0 + (ry1 - ry0) * fa
                rec(a, rx0, ry0, rx1, ym)
                rec(b, rx0, ym, rx1, ry1)

        rec(list(range(len(self.movable))), *self.region)
        return out_x, out_y

    # ---- 2. legal ---------------------------------------------------------------------

    def legalize(self, order="size"):
        """Move every part to the free spot nearest its target, on the
        placement grid; returns the parts that found none. A summed-area
        table over the occupancy map tests every candidate spot at once.
        order: "size" (largest first) or "x" (left to right, as Tetris)."""
        g, res = self.grid, self.res
        x0, y0, x1, y1 = self.region
        H, W = int((y1 - y0) / res) + 1, int((x1 - x0) / res) + 1
        occ = np.zeros((2, H, W), dtype=np.int32)          # [side][y][x]
        for p in self.fixed:
            self._mark(occ, p, True)
        for kx0, ky0, kx1, ky1 in self._keepouts():
            a = min(max(int(math.floor((kx0 - x0) / res)), 0), W)
            b = min(max(int(math.floor((ky0 - y0) / res)), 0), H)
            c = min(max(int(math.ceil((kx1 - x0) / res)), 0), W)
            d = min(max(int(math.ceil((ky1 - y0) / res)), 0), H)
            if a < c and b < d:
                occ[:, b:d, a:c] = True
        cx = x0 + np.arange(int((x1 - x0) / g) + 1) * g
        cy = y0 + np.arange(int((y1 - y0) / g) + 1) * g
        CX, CY = np.meshgrid(cx, cy)
        if order == "x":
            key = lambda p: (not p.tht, p.x)           # noqa: E731
        else:
            key = lambda p: -self._area(p) * (2 if p.tht else 1)   # noqa: E731
        sat = [None, None]
        stale = [True, True]
        self.unplaced = []
        # a second pass gives what didn't fit half the halo: a little less
        # room for escapes beats no room at all
        todo = [(p, 1.0) for p in sorted(self.movable, key=key)]
        while todo:
            p, halo_k = todo.pop(0)
            tx, ty = p.x, p.y
            if self.sides == "FB" and not p.tht and p.kind != "conn":
                choices = [("F", (0,)), ("B", (1,))]
            else:
                choices = [(p.side, self._sides(p))]
            best = None
            for side, occ_sides in choices:
                p.place(0.0, 0.0, p.rot, side)
                bx0, by0, bx1, by1 = self._box(p)
                h = self._margin(p) * halo_k
                c0 = np.floor((CX + bx0 - h - x0) / res).astype(int)
                c1 = np.ceil((CX + bx1 + h - x0) / res).astype(int)
                r0 = np.floor((CY + by0 - h - y0) / res).astype(int)
                r1 = np.ceil((CY + by1 + h - y0) / res).astype(int)
                ok = (c0 >= 0) & (r0 >= 0) & (c1 <= W) & (r1 <= H)
                c0, c1 = np.clip(c0, 0, W), np.clip(c1, 0, W)
                r0, r1 = np.clip(r0, 0, H), np.clip(r1, 0, H)
                for sd in occ_sides:
                    if stale[sd]:
                        a = np.zeros((H + 1, W + 1), dtype=np.int32)
                        a[1:, 1:] = occ[sd].cumsum(0, dtype=np.int32).cumsum(1, dtype=np.int32)
                        sat[sd] = a
                        stale[sd] = False
                    S = sat[sd]
                    ok &= (S[r1, c1] - S[r0, c1] - S[r1, c0] + S[r0, c0]) == 0
                if not ok.any():
                    continue
                d = np.where(ok, (CX - tx) ** 2 + (CY - ty) ** 2, np.inf)
                k = int(np.argmin(d))
                cand = (float(d.flat[k]) + (0.01 if side == "B" else 0.0),
                        float(CX.flat[k]), float(CY.flat[k]), side)
                if best is None or cand < best:
                    best = cand
            if best is None:
                if halo_k == 1.0:
                    p.place(tx, ty, p.rot, p.side)
                    todo.append((p, 0.5))
                    continue
                self.unplaced.append(p)
                p.place(x1 + 20, y0, p.rot, p.side)
                continue
            p.place(best[1], best[2], p.rot, best[3])
            self._mark(occ, p, True, halo_k)
            for sd in self._sides(p):
                stale[sd] = True
        return self.unplaced

    def _beside(self, p):
        """Whether a chip's capacitor will go beside it."""
        if p.kind != "chip":
            return False
        if self.decaps == "beside" or p.tht:
            return True            # nothing goes under a through-hole part
        cap = self.b.parts.get("C" + p.ref)
        if cap is None:
            return False
        key = (p.fp.name, p.typ)
        if key not in self._too_small:
            self._too_small[key] = under_spot(p, cap, self.b.rules) is None
        return self._too_small[key]

    def _box(self, p):
        """The part's courtyard, with room for its capacitor at its VCC end
        if the capacitor goes beside it."""
        cx0, cy0, cx1, cy1 = p.courtyard()
        if self._beside(p):
            nums = {d.number for d in supply_pads(p)}
            vcc = [d for d in p.pads() if d.number in nums]
            if vcc:
                v = vcc[0]
                mx, my = (cx0 + cx1) / 2, (cy0 + cy1) / 2
                if (cx1 - cx0) > (cy1 - cy0):          # rows along x: ends left/right
                    if v.x > mx:
                        cx1 += DECAP_ROOM
                    else:
                        cx0 -= DECAP_ROOM
                else:
                    if v.y > my:
                        cy1 += DECAP_ROOM
                    else:
                        cy0 -= DECAP_ROOM
        return cx0, cy0, cx1, cy1

    def _cells(self, p, halo):
        g = self.res
        x0, y0, _, _ = self.region
        cx0, cy0, cx1, cy1 = self._box(p)
        return (int(math.floor((cx0 - halo - x0) / g)), int(math.floor((cy0 - halo - y0) / g)),
                int(math.ceil((cx1 + halo - x0) / g)), int(math.ceil((cy1 + halo - y0) / g)))

    def _margin(self, p):
        """The room kept on each side of a part's courtyard: half the halo,
        or around a through-hole part enough for the gaps assembly needs
        (SMD_THT_GAP to a surface-mount part, THT_THT_GAP to another)."""
        if not p.tht:
            return self.halo / 2
        if self._smd:
            return max(SMD_THT_GAP - self.halo / 2, THT_THT_GAP / 2)
        return max(self.halo / 2, THT_THT_GAP / 2)

    def _keepouts(self):
        """The keep-out areas no chip may go in, as (x0, y0, x1, y1)."""
        return [(k["x0"], k["y0"], k["x1"], k["y1"]) for k in getattr(self.b, "keepouts", [])
                if "footprints" in k["no"] and "chip" not in k["allow"]]

    def _sides(self, p):
        return (0, 1) if p.tht or p.kind == "conn" else ((0,) if p.side == "F" else (1,))

    def _mark(self, occ, p, val, halo_k=1.0):
        a, b, c, d = self._cells(p, self._margin(p) * halo_k)
        _, ny, nx = occ.shape
        a, b, c, d = max(a, 0), max(b, 0), min(c, nx), min(d, ny)
        for s in self._sides(p):
            occ[s, b:d, a:c] = val

    # ---- 3. detail --------------------------------------------------------------------

    def hpwl(self):
        return sum(self._net_len(n) for n in self.nets)

    def _net_len(self, net):
        xs, ys = [], []
        for p, num in self.nets[net]:
            x, y = self._pin(p, num)
            xs.append(x)
            ys.append(y)
        return ((max(xs) - min(xs)) + (max(ys) - min(ys))) * self.weights.get(net, 1.0)

    def _pin(self, p, num):
        key = (p.ref, p.x, p.y, p.rot, p.side)
        cache = self._pin_cache.get(key)
        if cache is None:
            cache = {pd.number: (pd.x, pd.y) for pd in p.pads()}
            self._pin_cache[key] = cache
        return cache[num]

    def refine(self, moves=20000, t0=None, rotate=True):
        """Simulated annealing: swaps of same-footprint parts and 180-degree
        turns (not with capacitors beside the chips: their room is at one
        end). Returns (wire length before, after)."""
        self._pin_cache = {}
        rotate = rotate and self.decaps != "beside"
        by_fp = defaultdict(list)
        for p in self.movable:
            by_fp[(p.fp.name, p.side)].append(p)
        if self.sides == "FB":
            by_fp = defaultdict(list)
            for p in self.movable:
                by_fp[(p.fp.name, p.tht)].append(p)
        groups = [g for g in by_fp.values() if len(g) > 1]
        nets_of = defaultdict(set)
        for n, pins in self.nets.items():
            for p, _ in pins:
                nets_of[p.ref].add(n)
        start = cur = self.hpwl()
        t = t0 if t0 is not None else cur / len(self.nets) * 0.5
        cool = (0.01) ** (1.0 / max(moves, 1))
        for _ in range(moves):
            if groups and (not rotate or self.rng.random() < 0.7):
                g = self.rng.choice(groups)
                a, c = self.rng.sample(g, 2)
                affected = nets_of[a.ref] | nets_of[c.ref]
                before = sum(self._net_len(n) for n in affected)
                pa, pc = (a.x, a.y, a.rot, a.side), (c.x, c.y, c.rot, c.side)
                a.place(*pc)
                c.place(*pa)
                after = sum(self._net_len(n) for n in affected)
                if after > before and self.rng.random() >= math.exp((before - after) / t):
                    a.place(*pa)
                    c.place(*pc)
                else:
                    cur += after - before
            elif rotate:
                a = self.rng.choice(self.movable)
                if self._beside(a):
                    continue          # its capacitor's room is at one end
                affected = nets_of[a.ref]
                before = sum(self._net_len(n) for n in affected)
                old = (a.x, a.y, a.rot)
                a.turn((a.rot + 180) % 360)
                after = sum(self._net_len(n) for n in affected)
                if after > before and self.rng.random() >= math.exp((before - after) / t):
                    a.place(*old, a.side)
                else:
                    cur += after - before
            t *= cool
        return start, cur


class GridPlacer(Placer):
    """Placement on a grid of slots, as on the classic TTL boards: rows
    and columns of chips, every chip the same way round (pin 1 at the top
    left), each in a block of whole slots (one for most, two or four for
    the big ones), centred across it and at its top, so the chips of a row
    start on one line. A block more than a slot wide starts on an
    even column (and one more than a slot high on an even row), so a wide
    chip takes the place of two narrow ones and the columns line up.

    pitch: (px, py), the least slot size; the slots grow to fill the region
    evenly. The steps are Placer's: global placement, then legalisation
    onto the slots, then annealing that swaps chips of the same block size
    or moves one to a free block nearby. One side only."""

    def __init__(self, board, pitch, align=True, **kw):
        super().__init__(board, **kw)
        self.align = align
        assert self.sides == "F", "a grid placement is one-sided"
        x0, y0, x1, y1 = self.region
        self.ncol = max(1, int((x1 - x0) / pitch[0] + 1e-6))
        self.nrow = max(1, int((y1 - y0) / pitch[1] + 1e-6))
        self.px = (x1 - x0) / self.ncol
        self.py = (y1 - y0) / self.nrow
        self.spans = {}           # ref -> (columns, rows, x from the block's centre and y from its top to the origin)
        for p in self.movable:
            p.place(0.0, 0.0, 0, "F")
            bx0, by0, bx1, by1 = self._box(p)
            m = self._margin(p)
            nc = max(1, math.ceil((bx1 - bx0 + 2 * m) / self.px - 1e-6))
            nr = max(1, math.ceil((by1 - by0 + 2 * m) / self.py - 1e-6))
            self.spans[p.ref] = (nc, nr, -(bx0 + bx1) / 2, m - by0)
        self.where = {}

    def _area(self, p):
        nc, nr, _, _ = self.spans[p.ref]
        return nc * self.px * nr * self.py

    def _step(self, n):
        """Where a block n slots long may start: every slot, or with
        aligning, every other one for blocks longer than a slot."""
        return 2 if self.align and n > 1 else 1

    def _put(self, p, c, r):
        nc, nr, ox, oy = self.spans[p.ref]
        x0, y0, _, _ = self.region
        p.place(x0 + (c + nc / 2) * self.px + ox, y0 + r * self.py + oy, p.rot, p.side)
        self.where[p.ref] = (c, r)

    def _blocked(self):
        """The slots the fixed parts (connectors) cover, with their margins,
        and the keep-out areas."""
        x0, y0, _, _ = self.region
        occ = np.full((self.nrow, self.ncol), -1, dtype=np.int32)
        boxes = []
        for p in self.fixed:
            cx0, cy0, cx1, cy1 = p.courtyard()
            h = self._margin(p)
            boxes.append((cx0 - h, cy0 - h, cx1 + h, cy1 + h))
        for bx0, by0, bx1, by1 in boxes + self._keepouts():
            c0 = max(0, int(math.floor((bx0 - x0) / self.px + 1e-6)))
            c1 = min(self.ncol, int(math.ceil((bx1 - x0) / self.px - 1e-6)))
            r0 = max(0, int(math.floor((by0 - y0) / self.py + 1e-6)))
            r1 = min(self.nrow, int(math.ceil((by1 - y0) / self.py - 1e-6)))
            if c0 < c1 and r0 < r1:
                occ[r0:r1, c0:c1] = -2
        return occ

    def legalize(self, order="size"):
        """Each chip, largest first, to the free block nearest its global
        position; returns those that found none."""
        x0, y0, _, _ = self.region
        occ = self._blocked()
        self.unplaced = []
        self.where = {}
        idx = {p.ref: i for i, p in enumerate(self.movable)}
        for p in sorted(self.movable, key=lambda p: (-self._area(p), p.x)):
            nc, nr, _, _ = self.spans[p.ref]
            if nc > self.ncol or nr > self.nrow:
                self.unplaced.append(p)
                continue
            free = (occ == -1).astype(np.int32)
            S = np.zeros((self.nrow + 1, self.ncol + 1), dtype=np.int32)
            S[1:, 1:] = free.cumsum(0).cumsum(1)
            R, C = np.mgrid[0:self.nrow - nr + 1, 0:self.ncol - nc + 1]
            ok = (S[R + nr, C + nc] - S[R, C + nc] - S[R + nr, C] + S[R, C]) == nc * nr
            ok &= (C % self._step(nc) == 0) & (R % self._step(nr) == 0)
            if not ok.any():
                self.unplaced.append(p)
                p.place(self.region[2] + 20, y0, p.rot, p.side)
                continue
            cx = x0 + (C + nc / 2) * self.px
            cy = y0 + (R + nr / 2) * self.py
            d = np.where(ok, (cx - p.x) ** 2 + (cy - p.y) ** 2, np.inf)
            k = int(np.argmin(d))
            r, c = int(R.flat[k]), int(C.flat[k])
            occ[r:r + nr, c:c + nc] = idx[p.ref]
            self._put(p, c, r)
        self._occ = occ
        return self.unplaced

    def refine(self, moves=20000, t0=None, rotate=False):
        """Simulated annealing on the slots: a chip to a block within a few
        slots of its own, moving there if the block is free or swapping
        with the chip there if that one's block is the same; now and then
        a swap with a chip of the same block size anywhere. Returns (wire
        length before, after)."""
        self._pin_cache = {}
        occ = self._occ
        idx = {p.ref: i for i, p in enumerate(self.movable)}
        by_span = defaultdict(list)
        for p in self.movable:
            by_span[self.spans[p.ref][:2]].append(p)
        nets_of = defaultdict(set)
        for n, pins in self.nets.items():
            for p, _ in pins:
                nets_of[p.ref].add(n)
        start = cur = self.hpwl()
        t = t0 if t0 is not None else cur / len(self.nets) * 0.5
        cool = (0.01) ** (1.0 / max(moves, 1))
        reach = 4
        for _ in range(moves):
            t *= cool
            a = self.rng.choice(self.movable)
            nc, nr, _, _ = self.spans[a.ref]
            ca, ra = self.where[a.ref]
            b = None
            if self.rng.random() < 0.1:
                b = self.rng.choice(by_span[(nc, nr)])
                if b is a:
                    continue
                c, r = self.where[b.ref]
            else:
                c = ca + self.rng.randint(-reach, reach) * self._step(nc)
                r = ra + self.rng.randint(-reach, reach) * self._step(nr)
                if (c, r) == (ca, ra) or c < 0 or r < 0 or c + nc > self.ncol or r + nr > self.nrow:
                    continue
                others = set(occ[r:r + nr, c:c + nc].flat) - {-1, idx[a.ref]}
                if others:
                    if len(others) > 1 or -2 in others:
                        continue
                    b = self.movable[others.pop()]
                    if self.spans[b.ref][:2] != (nc, nr) or self.where[b.ref] != (c, r):
                        continue
            affected = nets_of[a.ref] | (nets_of[b.ref] if b else set())
            before = sum(self._net_len(n) for n in affected)
            self._put(a, c, r)
            if b:
                self._put(b, ca, ra)
            after = sum(self._net_len(n) for n in affected)
            if after > before and self.rng.random() >= math.exp((before - after) / t):
                self._put(a, ca, ra)
                if b:
                    self._put(b, c, r)
                continue
            if b:
                occ[ra:ra + nr, ca:ca + nc] = idx[b.ref]
            else:
                occ[ra:ra + nr, ca:ca + nc] = -1
            occ[r:r + nr, c:c + nc] = idx[a.ref]
            cur += after - before
        return start, cur


def _clear(chip, x, y, r):
    """Whether a circle of radius r at (x, y), in the chip's footprint
    coordinates, keeps clear of all its pads."""
    for d in chip.fp.pads:
        hw, hh = (d.w / 2, d.h / 2) if d.rot % 180 == 0 else (d.h / 2, d.w / 2)
        dx = max(abs(x - d.x) - hw, 0)
        dy = max(abs(y - d.y) - hh, 0)
        if math.hypot(dx, dy) < r:
            return False
    return True


def supply_pads(part):
    """A chip's supply pins (its pinout's VCC), as footprint pads; for a
    part without a pinout, its pads on the VCC net. Not any pad on VCC: an
    input tied high is on VCC too."""
    if part.typ in packages.PINOUTS:
        nums = {str(n) for n in packages.pin_numbers(part.typ).get("VCC", [])}
        pads = [d for d in part.fp.pads if d.number in nums]
        if pads:
            return pads
    return [d for d in part.fp.pads if part.nets.get(d.number) == "VCC"]


def under_spots(chip, cap, rules):
    """Where a chip's capacitor can go under it, on the other side: [(x, y,
    turn)] in the chip's own coordinates, on the line between its pin rows
    where the capacitor's vias can go clear of the chip's pads and stay
    within its rows, nearest its VCC pin first; empty if nowhere (a chip
    too small)."""
    vcc = supply_pads(chip)
    if not vcc:
        return []
    v = vcc[0]
    bx, by = chip.body_centre()
    xs = [d.x for d in chip.fp.pads if d.number]
    ys = [d.y for d in chip.fp.pads if d.number]
    rows_along_y = (max(ys) - min(ys)) >= (max(xs) - min(xs))
    # the capacitor's pads and vias, along its axis, from its centre
    cpads = [abs(d.x) for d in cap.fp.pads] or [0.8]
    reach = max(cpads) + 0.5 + rules["via_dia"] / 2 + 0.25
    keep = rules["via_dia"] / 2 + rules["clearance"] + 0.05
    lo, hi = (min(ys), max(ys)) if rows_along_y else (min(xs), max(xs))
    found = []
    for k in range(int((hi - lo) / 0.254) + 1):
        t = lo + k * 0.254
        if t - reach < lo or t + reach > hi:
            continue
        pts = [(bx, t - reach), (bx, t + reach)] if rows_along_y else [(t - reach, by), (t + reach, by)]
        if all(_clear(chip, x, y, keep) for x, y in pts):
            found.append((abs(t - (v.y if rows_along_y else v.x)), t))
    found.sort()
    return [(bx, t, 90) if rows_along_y else (t, by, 0) for _, t in found]


def under_spot(chip, cap, rules):
    """The first of under_spots(), or None."""
    spots = under_spots(chip, cap, rules)
    return spots[0] if spots else None


def place_decaps(board, side="B", tht_clear=THT_BOTTOM_CLEAR):
    """Each chip's decoupling capacitor C<ref>. With side "B": on the other
    side, under the chip's body (under_spots), as near its VCC pin as it
    can be while keeping tht_clear from every through-hole pad (selective
    soldering needs the room). A chip too small for that, a chip with no
    such spot, and every chip with side "F" has it beside its end nearest
    its VCC pin, on its own side; board.decaps_beside lists the chips whose
    capacitor went there for want of a spot."""
    r = board.rules
    cell = 2 * tht_clear
    tht = defaultdict(list)
    for p in board.parts.values():
        if p.kind == "decap":
            continue
        for d in p.pads():
            if d.layers == "*":
                hx, hy = d.extent()
                tht[(int(d.x // cell), int(d.y // cell))].append((d.x, d.y, hx, hy))

    def near_tht(cap):
        for d in cap.pads():
            ex, ey = d.extent()
            cx, cy = int(d.x // cell), int(d.y // cell)
            for i in (cx - 1, cx, cx + 1):
                for j in (cy - 1, cy, cy + 1):
                    for (x, y, hx, hy) in tht.get((i, j), ()):
                        dx = max(abs(d.x - x) - ex - hx, 0.0)
                        dy = max(abs(d.y - y) - ey - hy, 0.0)
                        if math.hypot(dx, dy) < tht_clear:
                            return True
        return False

    board.decaps_beside = []
    for c in board.parts.values():
        if c.kind != "decap":
            continue
        chip = board.parts.get(c.ref[1:])
        if chip is None:
            continue
        vcc = supply_pads(chip)
        if not vcc:
            continue
        v = vcc[0]
        bx, by = chip.body_centre()
        xs = [d.x for d in chip.fp.pads if d.number]
        ys = [d.y for d in chip.fp.pads if d.number]
        rows_along_y = (max(ys) - min(ys)) >= (max(xs) - min(xs))
        spots = under_spots(chip, c, r) if side == "B" and not chip.tht else []
        placed = False
        for lx, ly, lrot in spots:
            if chip.side == "B":
                ly = -ly
            dx, dy = kicadlib.rotate(lx, ly, chip.rot)
            c.place(chip.x + dx, chip.y + dy, (chip.rot + lrot) % 180,
                    "B" if chip.side == "F" else "F")
            if not near_tht(c):
                placed = True
                break
        if not placed:
            if spots:
                board.decaps_beside.append(chip.ref)
            # beside the chip (also for a chip too small to have it under)
            x0, y0, x1, y1 = chip.fp.courtyard
            if rows_along_y:
                ly = (y0 - 1.4) if v.y < by else (y1 + 1.4)
                lx, lrot = bx, 0
            else:
                lx = (x0 - 1.4) if v.x < bx else (x1 + 1.4)
                ly, lrot = by, 90
            dx, dy = kicadlib.rotate(lx, -ly if chip.side == "B" else ly, chip.rot)
            rot = (chip.rot + lrot) % 180
            # the capacitor's own body centre goes there (a through-hole
            # footprint's origin is its pin 1)
            ox, oy = c.body_centre()
            ox, oy = kicadlib.rotate(ox, -oy if chip.side == "B" else oy, rot)
            c.place(chip.x + dx - ox, chip.y + dy - oy, rot, chip.side)
