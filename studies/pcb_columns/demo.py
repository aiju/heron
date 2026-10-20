"""The demonstration board: a slice of the draft 1b CPU card on a double
Eurocard, placed on the grid.

The slice is five of the CPU card's sections (studies/v1b_system), 48
chips: the ALU (eight 74181s and their 74182s), the R and T registers,
the register file, the decode ROMs and the clock generator. It is the
card's own netlist, so the placement has real nets to keep short; the
nets that leave the slice are left out. The packages are those of a board
soldered by hand: DIP where the part is made in DIP, the register file's
fast SRAMs in SOJ (no fast SRAM is made in DIP), the decode flashes in
PLCC sockets and the oscillator a full-size can. Its two DIN 41612
connectors stand at the back edge where a Eurocard has them, off the grid.
"""

import json
import os
from types import SimpleNamespace

from heron import ROOT
from heron.infra.pcb import board as B
from heron.infra.pcb import kicadlib, physical
from heron.studies.pcb import cards

from . import footprints
from .grid import dip_footprint
from .placer import GridPlacer, place_decaps

SECTIONS = ("ALU", "R and T", "Register file", "Decode", "Clock generator")
FOOTPRINTS = {
    "sram": "Package_SO:SOJ-28_7.62x18.415mm_P1.27mm",
    "flash": "Package_LCC:PLCC-32_THT-Socket",
    "osc": "Oscillator:Oscillator_DIP-14",
}
CAP = "Capacitor_SMD:C_0805_2012Metric"
CARD = (160.0, cards.EUROCARD_6U)       # 6U x 160 mm: its depth across, its height down
OUT = os.path.join(ROOT, "build", "pcb_columns")

_NL = {}


def cpu_netlist():
    if "cpu" not in _NL:
        from heron.studies.v1b_system import cpucard
        _NL["cpu"] = cpucard.build().netlist
    return _NL["cpu"]


def netlist(sections=SECTIONS):
    """The slice: the sections' chips, and the fixtures that make the rails."""
    nl = cpu_netlist()
    return SimpleNamespace(instances=[i for i in nl.instances
                                      if i.section in sections or i.type.family == "fixture"])


def board(params, size=CARD, sections=SECTIONS, name=None):
    """The slice's board with its parts, the connectors and the card's
    mechanics (RFC 0026) in place, the chips not yet placed."""
    footprints.use()
    w, h = size
    nl = netlist(sections)
    b = B.Board(name or f"columns-{params.label()}", w, h, layers=4)
    conns = cards.connectors(nl, w, h)
    for p in physical.parts(nl, "dip", connectors=conns):
        if p.kind == "chip":
            fp = FOOTPRINTS.get(p.typ) or p.fp.name
            if fp.startswith("Package_DIP:"):
                fp = dip_footprint(fp, params.pads)
            p.fp = kicadlib.footprint(fp)
        elif p.kind == "decap":
            p.fp = kicadlib.footprint(CAP)
        b.add(p)
    b.region = cards.mechanics(b)
    return b


def place(params, size=CARD, sections=SECTIONS, seed=1, moves=60000, name=None, tidy=True):
    """Place the slice on the grid (with tidy, the free room at the bottom
    of the columns; without, for wire alone): (board, placer, chips left
    over)."""
    b = board(params, size, sections, name)
    pl = GridPlacer(b, b.region, params, weights=cards.weights(cpu_netlist()), seed=seed)
    left = pl.run(moves, tidy=tidy)
    if not left:
        place_decaps(b)
    return b, pl, left


def check(b, pl):
    """What a placement should be: every chip in its box and its pins on
    the lattice, no two parts' courtyards overlapping on a side, each
    part's courtyard inside the card's region for parts. Returns
    {problems: [...], least pad gap between two parts (mm), ...}."""
    probs = []
    lat = pl.lat
    for p in pl.chips:
        bx = pl.boxes[p.ref]
        hc, row = pl.pos[p.ref]
        rx0, ry0, rx1, ry1 = lat.rect(hc, row, bx.w, bx.h)
        x0, y0, x1, y1 = p.courtyard()
        for d in p.pads():
            for v, o, pitch in ((d.x, lat.x, bx.pitch[0]), (d.y, lat.y, bx.pitch[1])):
                if pitch and abs((v - o) / pitch - round((v - o) / pitch)) > 1e-3:
                    probs.append(f"{p.ref}: pad {d.number} off its lattice")
                    break
        if not (rx0 - 1e-6 <= x0 and ry0 - 1e-6 <= y0 and x1 <= rx1 + 1e-6 and y1 <= ry1 + 1e-6):
            probs.append(f"{p.ref}: its courtyard leaves its box")
        X0, Y0, X1, Y1 = b.region
        if x0 < X0 - 1e-6 or y0 < Y0 - 1e-6 or x1 > X1 + 1e-6 or y1 > Y1 + 1e-6:
            probs.append(f"{p.ref}: its courtyard leaves the region")
    parts = [p for p in b.parts.values() if p.kind in ("chip", "decap", "conn")]
    for i, p in enumerate(parts):
        for q in parts[i + 1:]:
            if p.side != q.side:
                continue            # a capacitor under a chip, on the bottom
            a, c = p.courtyard(), q.courtyard()
            if a[0] < c[2] and c[0] < a[2] and a[1] < c[3] and c[1] < a[3]:
                probs.append(f"{p.ref} and {q.ref}: courtyards overlap")
    gap = least_pad_gap(b)
    return {"problems": probs, "least_pad_gap": round(gap, 3)}


def least_pad_gap(b):
    """The least gap between two pads of different chips, edge to edge
    (as their bounding boxes; a round pad counts as its square), mm."""
    pads = [(p.ref, d) for p in b.parts.values() if p.kind == "chip" for d in p.pads()]
    cell = 6.0
    grid = {}
    for ref, d in pads:
        grid.setdefault((int(d.x // cell), int(d.y // cell)), []).append((ref, d))
    best = float("inf")
    for (cx, cy), items in grid.items():
        near = [x for i in (cx - 1, cx, cx + 1) for j in (cy - 1, cy, cy + 1)
                for x in grid.get((i, j), ())]
        for ref, d in items:
            hx, hy = d.extent()
            for ref2, e in near:
                if ref2 == ref:
                    continue
                ex, ey = e.extent()
                gx = abs(d.x - e.x) - hx - ex
                gy = abs(d.y - e.y) - hy - ey
                g = max(gx, gy) if gx < 0 or gy < 0 else (gx * gx + gy * gy) ** 0.5
                best = min(best, g)
    return best


def summary(b, pl, left):
    """The placement's numbers, for results and the command line."""
    from collections import Counter
    sizes = Counter()
    for p in pl.chips:
        bx = pl.boxes[p.ref]
        sizes[(p.fp.name.split(":")[1], bx.w, bx.h)] += 1
    out = {
        "name": b.name, "params": vars(pl.p), "card": [b.width, b.height],
        "grid": {"columns": pl.lat.cols, "half_columns": pl.lat.halves, "rows": pl.lat.rows,
                 "at": [round(pl.lat.x, 3), round(pl.lat.y, 3)],
                 "blocked_cells": len(pl.blocked)},
        "chips": len(pl.chips), "left_over": left,
        "demand": round(pl.demand(), 3),
        "boxes": [{"footprint": fp, "half_columns": w, "rows": h, "count": n}
                  for (fp, w, h), n in sorted(sizes.items(), key=lambda kv: (kv[0][1], kv[0][2]))],
    }
    if not left:
        out["used"] = round(pl.used(), 3)
        out["wire_mm"] = round(pl.wire(), 1)
        out["holes"] = pl.holes()
        out.update(check(b, pl))
    return out


def build(params, size=CARD, seed=1, moves=60000, name=None, kicad=True, tidy=True):
    """Place the slice and write it to build/pcb_columns/<name>/: the KiCad
    board, an SVG of it and result.json."""
    from . import draw
    b, pl, left = place(params, size, seed=seed, moves=moves, name=name, tidy=tidy)
    d = os.path.join(OUT, b.name)
    os.makedirs(d, exist_ok=True)
    res = summary(b, pl, left)
    if not left:
        draw.svg(b, pl, os.path.join(d, "board.svg"))
        if kicad:
            b.write(os.path.join(d, "board.kicad_pcb"))
    with open(os.path.join(d, "result.json"), "w") as f:
        json.dump(res, f, indent=1)
    return b, pl, res


def fits(params, size, sections=SECTIONS):
    """Whether the slice's boxes all find a place on a card (legalisation,
    or packing, without annealing), and the share of the grid they need."""
    b = board(params, size, sections)
    pl = GridPlacer(b, b.region, params, weights=cards.weights(cpu_netlist()))
    if pl.demand() > 1:
        return False, pl.demand()
    ok = not pl.legalize(pl.targets()) or not pl.pack()
    return ok, pl.demand()


def least_depth(params, height=CARD[1], lo=60.0, hi=400.0, step=10.0, sections=SECTIONS):
    """The least card depth, in steps of `step` mm, at which the slice's
    boxes all find a place, or None."""
    d = lo
    while d <= hi + 1e-6:
        ok, need = fits(params, (d, height), sections)
        if ok:
            return d
        d += step
    return None
