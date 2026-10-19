"""RFC 0046's numbers and pictures: `heron pcb_columns report [--write]`.

Writes reports/0046-rfc-column-grid/results.md and the figures next to
it: the demonstration slice placed with each variant of the grid's
parameters, the same slice as the flow's own grid places it (RFC 0023's
slots), and the grid's anatomy, drawn on a few parts by hand.
"""

import math
import os

from heron import ROOT
from heron.infra.pcb import board as B
from heron.infra.pcb import kicadlib
from heron.infra.pcb import place as oldplace
from heron.studies.pcb import cards

from . import demo, draw, footprints
from .grid import ROW, Params, box, dip_footprint
from .placer import GridPlacer, place_decaps

DOC = os.path.join(ROOT, "reports", "0046-rfc-column-grid")

# (name, parameters, card depth or None for the least that fits, tidy, what it shows)
VARIANTS = [
    ("default", Params(), 160.0, True,
     "the defaults: half-columns of 0.5 inch, 0.2 inch between chips both ways, boxes on any row"),
    ("wire-alone", Params(), 160.0, False,
     "the defaults, placed for wire alone: the free room wherever it falls"),
    ("aligned", Params(module=5), 160.0, True,
     "boxes in whole modules of 5 rows, so that they line up across the columns"),
    ("tight", Params(half=4), None, True,
     "half-columns of 0.4 inch, on the least depth that holds the slice"),
    ("roomy", Params(gap=3, module=5, pads="socket-long"), None, True,
     "sockets with long pads, 0.3 inch between chips down the columns, modules of 5 rows, "
     "on the least depth that holds them"),
]
SEEDS = (1, 2, 3, 4)

# design rules for counting tracks: a common fab's standard (0.15 mm
# tracks and gaps) and a relaxed one (0.25 mm)
RULES = (0.15, 0.25)


def _tracks(room, rule):
    """Tracks of width and gap `rule` that pass through `room` mm."""
    return max(0, math.floor((room - rule) / (2 * rule) + 1e-9))


def _fp(name, pads="round"):
    return kicadlib.footprint(dip_footprint(name, pads) if name.startswith("Package_DIP:") else name)


def param_table():
    """The half-column's width and the gap, and what each gives."""
    narrow = {s: _fp("Package_DIP:DIP-14_W7.62mm", s) for s in ("round", "long", "socket-long")}
    pad_w = {s: max(d.w for d in fp.pads) for s, fp in narrow.items()}
    crt_w = {s: fp.courtyard[2] - fp.courtyard[0] for s, fp in narrow.items()}
    crt_end = {s: ((fp.courtyard[3] - fp.courtyard[1]) - 6 * ROW) / 2 for s, fp in narrow.items()}
    rows = ["| Half-column | Column | Narrow DIPs' pins apart | Pad gap: round / long | "
            "Tracks between: 0.15 / 0.25 mm | A narrow DIP in its box | Sockets side by side |",
            "|---|---|---|---|---|---|---|"]
    for h in (4, 5, 6, 7):
        apart = (h - 3) * ROW
        g = {s: apart - pad_w[s] for s in pad_w}
        bx = box(B.Part("X", narrow["round"], {}), Params(half=h))
        off = bx.dx - (h - 3) * ROW / 2
        sits = "centred" if abs(off) < 1e-6 else f"{abs(off) / 25.4:.2f} in left of the middle"
        sits += ", 0.1 in lattice" if bx.pitch[0] == ROW else ", 0.05 in lattice"
        rows.append(
            f"| {h / 10:.1f} in ({h * ROW:.2f} mm) | {2 * h / 10:.1f} in | {(h - 3) / 10:.1f} in | "
            f"{g['round']:.2f} / {g['long']:.2f} mm | "
            f"{_tracks(g['round'], RULES[0])} / {_tracks(g['round'], RULES[1])} | {sits} | "
            f"{'yes' if crt_w['socket-long'] <= h * ROW + 1e-6 else 'no'} |")
    rows += ["", "| Gap | End pins apart | Pad gap | Tracks between: 0.15 / 0.25 mm | "
                 "Courtyards apart: DIP / socket |", "|---|---|---|---|---|"]
    for g in (2, 3, 4):
        apart = g * ROW
        gp = apart - 1.6
        rows.append(f"| {g} rows | {g / 10:.1f} in | {gp:.2f} mm | {_tracks(gp, RULES[0])} / "
                    f"{_tracks(gp, RULES[1])} | {apart - 2 * crt_end['round']:.2f} / "
                    f"{apart - 2 * crt_end['socket-long']:.2f} mm |")
    rows += ["", f"Inside a DIP, between neighbouring pins: {ROW - 1.6:.2f} mm, "
                 f"{_tracks(ROW - 1.6, RULES[0])} track at 0.15 mm, "
                 f"{_tracks(ROW - 1.6, RULES[1])} at 0.25 mm. Long pads are "
                 f"{pad_w['long']:.1f} mm across the column and as tall as round ones "
                 f"({min(d.h for d in narrow['long'].pads):.1f} mm). A DIP's courtyard is "
                 f"{crt_w['round']:.2f} mm wide ({crt_w['long']:.2f} with long pads, "
                 f"{crt_w['socket-long']:.2f} as a socket)."]
    return "\n".join(rows)


PACKAGES = [
    ("DIP-8", "Package_DIP:DIP-8_W7.62mm"),
    ("DIP-14", "Package_DIP:DIP-14_W7.62mm"),
    ("DIP-16", "Package_DIP:DIP-16_W7.62mm"),
    ("DIP-20", "Package_DIP:DIP-20_W7.62mm"),
    ("DIP-24 (0.3 in)", "Package_DIP:DIP-24_W7.62mm"),
    ("DIP-28 (0.3 in)", "Package_DIP:DIP-28_W7.62mm"),
    ("DIP-24 (0.6 in)", "Package_DIP:DIP-24_W15.24mm"),
    ("DIP-28 (0.6 in)", "Package_DIP:DIP-28_W15.24mm"),
    ("DIP-32 (0.6 in)", "Package_DIP:DIP-32_W15.24mm"),
    ("DIP-40 (0.6 in)", "Package_DIP:DIP-40_W15.24mm"),
    ("SOJ-28 (300 mil)", "Package_SO:SOJ-28_7.62x18.415mm_P1.27mm"),
    ("SOJ-36 (400 mil)", "Package_SO:SOJ-36_10.16x23.495mm_P1.27mm"),
    ("SOIC-20 wide", "Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm"),
    ("TSSOP-16", "Package_SO:TSSOP-16_4.4x5mm_P0.65mm"),
    ("PLCC-32 socket", "Package_LCC:PLCC-32_THT-Socket"),
    ("Oscillator, full can", "Oscillator:Oscillator_DIP-14"),
    ("Oscillator, half can", "Oscillator:Oscillator_DIP-8"),
    ("SIP-9 resistor network", "Resistor_THT:R_Array_SIP9"),
]
BOX_PARAMS = [("default", Params()), ("half 0.4 in", Params(half=4)),
              ("half 0.6 in", Params(half=6)), ("gap 3", Params(gap=3)),
              ("modules of 5", Params(module=5))]


def box_table():
    """Each package's box under a few parameter sets: half-columns x rows."""
    head = "| Package | " + " | ".join(n for n, _ in BOX_PARAMS) + " |"
    rows = [head, "|---|" + "---|" * len(BOX_PARAMS)]
    for label, fpname in PACKAGES:
        cells = []
        for _, prm in BOX_PARAMS:
            part = B.Part("X", _fp(fpname), {})
            bx = box(part, prm)
            cells.append(f"{'½' if bx.w == 1 else '1'} × {bx.h}")
        rows.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def fit_table():
    """The slice under each combination of the main parameters: the grid's
    share it needs on 6U x 160, and the least 6U card that holds it."""
    rows = ["| Half-column | Gap | Module | Share of the grid on 6U × 160 | Least depth at 6U |",
            "|---|---|---|---:|---:|"]
    for h in (4, 5, 6):
        for g in (2, 3):
            for m in (1, 5):
                prm = Params(half=h, gap=g, module=m)
                _, need = demo.fits(prm, demo.CARD)
                d = demo.least_depth(prm)
                rows.append(f"| {h / 10:.1f} in | {g} | {m} | {100 * need:.0f}% | "
                            f"{'—' if d is None else f'{d:.0f} mm'} |")
    return "\n".join(rows)


def old_grid(size=demo.CARD, seed=1):
    """The slice as the flow's own grid places it (infra.pcb.place.
    GridPlacer, RFC 0023 and 0026: slots of at least 12.07 x 33 mm for a
    DIP board on four layers, the capacitors beside the through-hole
    chips): (board, placer, chips left over)."""
    b = demo.board(Params(), size, name="columns-flow-grid")
    pl = oldplace.GridPlacer(b, cards.PITCH[("dip", 4)], region=b.region, seed=seed,
                             weights=cards.weights(demo.cpu_netlist()))
    pl.global_place()
    targets = {p.ref: (p.x, p.y) for p in pl.movable}
    left = []
    for order in ("x", "size"):
        for p in pl.movable:
            p.place(*targets[p.ref], p.rot, p.side)
        left = pl.legalize(order=order)
        if not left:
            break
    if not left:
        pl.refine(moves=60000)
        oldplace.place_decaps(b, side="B")
    return b, pl, left


def _wire(b):
    """Half-perimeter wire length of a placed board's signal nets, mm."""
    nets = {}
    for p in b.parts.values():
        if p.kind == "decap":
            continue
        for d in p.pads():
            if d.net and d.net not in ("VCC", "GND"):
                nets.setdefault(d.net, []).append((d.x, d.y))
    total = 0.0
    for pts in nets.values():
        if len(pts) > 1:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            total += max(xs) - min(xs) + max(ys) - min(ys)
    return total


def anatomy(path):
    """The grid on a few parts placed by hand: a column holding a 74181
    and below it two half-columns of narrow DIPs, and a column of other
    packages, with the grid's measures drawn on."""
    footprints.use()
    prm = Params()
    b = B.Board("anatomy", 76.0, 100.0)
    parts = [
        ("U1", "Package_DIP:DIP-24_W15.24mm", "74F181", (0, 0)),
        ("U2", "Package_DIP:DIP-14_W7.62mm", "74F00", (0, 13)),
        ("U3", "Package_DIP:DIP-16_W7.62mm", "74F153", (0, 21)),
        ("U4", "Package_DIP:DIP-20_W7.62mm", "74ABT541", (1, 13)),
        ("U5", "Package_DIP:DIP-14_W7.62mm", "74F04", (1, 24)),
        ("U6", "Package_LCC:PLCC-32_THT-Socket", "SST39SF010A", (2, 0)),
        ("U7", "Package_SO:SOJ-28_7.62x18.415mm_P1.27mm", "AS7C256A", (2, 10)),
        ("U8", "Package_DIP:DIP-16_W7.62mm", "74F161", (3, 10)),
        ("U9", "Oscillator:Oscillator_DIP-14", "50 MHz", (2, 19)),
    ]
    for ref, fp, value, _ in parts:
        b.add(B.Part(ref, fp, {}, value=value))
        b.add(B.Part(f"C{ref}", demo.CAP, {"1": "VCC", "2": "GND"}, value="100n", kind="decap"))
    for ref, _, _, _ in parts:
        p = b.parts[ref]           # VCC on the last pin, for the capacitor's place
        p.nets = {str(max(int(d.number) for d in p.fp.pads if d.number.isdigit())): "VCC"}
    region = (10.0, 11.0, 66.0, 11.0 + 33 * ROW)
    pl = GridPlacer(b, region, prm)
    for ref, _, _, at in parts:
        pl._set(ref, *at)
    pl.commit()
    place_decaps(b)
    lat = pl.lat
    text = draw.svg(b, pl, scale=9.0)
    ann = []
    ink = "#b2462e"

    def dim(x1, y1, x2, y2, label, side="above", size=1.5):
        ann.append(f'<line x1="{x1:.3f}" y1="{y1:.3f}" x2="{x2:.3f}" y2="{y2:.3f}" stroke="{ink}" '
                   f'stroke-width="0.22" marker-start="url(#a)" marker-end="url(#a)"/>')
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        if side == "above":
            ann.append(draw._text(mx, my - 1.4, label, size, ink))
        elif side == "right":
            ann.append(draw._text(mx + 1.2, my, label, size, ink, rotate=True))
        else:
            ann.append(draw._text(mx - 1.2, my, label, size, ink, rotate=True))

    x0, y0 = lat.x, lat.y
    hw = prm.half_mm
    # across the top: the half-columns and the columns
    dim(x0, y0 - 4.6, x0 + 2 * hw, y0 - 4.6, "column, 1.0 in")
    dim(x0 + 2 * hw, y0 - 4.6, x0 + 3 * hw, y0 - 4.6, "half, 0.5 in", size=1.3)
    dim(x0 + 3 * hw, y0 - 4.6, x0 + 4 * hw, y0 - 4.6, "half, 0.5 in", size=1.3)
    # down the left: the 74181's box and the gap to the chip below it
    u1, u2 = b.parts["U1"], b.parts["U2"]
    last = max(d.y for d in u1.pads())
    first = min(d.y for d in u2.pads())
    dim(x0 - 3.2, y0, x0 - 3.2, y0 + 13 * ROW, "box: 13 rows", side="left")
    dim(x0 - 3.2, last, x0 - 3.2, first, "gap, 0.2 in", side="left", size=1.1)
    # down the right: a row
    xr = x0 + 4 * hw + 2.2
    dim(xr, y0 + 10 * ROW, xr, y0 + 11 * ROW, "row, 0.1 in", side="right", size=1.2)
    marker = (f'<defs><marker id="a" viewBox="0 0 6 6" refX="3" refY="3" markerWidth="4" '
              f'markerHeight="4" orient="auto-start-reverse"><path d="M0,0 L6,3 L0,6 z" '
              f'fill="{ink}"/></marker></defs>')
    text = text.replace(">", ">" + marker, 1)
    text = text.replace("</svg>", "\n".join(ann) + "\n</svg>")
    with open(path, "w") as f:
        f.write(text)
    return path


def build_variants(write):
    out = []
    for name, prm, depth, tidy, what in VARIANTS:
        size = (depth or demo.least_depth(prm), demo.CARD[1])
        b, pl, left = demo.place(prm, size, name=f"columns-{name}", tidy=tidy)
        res = demo.summary(b, pl, left)
        res.update(variant=name, what=what)
        out.append(res)
        if write and not left and tidy:
            draw.svg(b, pl, os.path.join(DOC, f"{name}.svg"), scale=4.0)
    b, pl, left = old_grid()
    res = {"variant": "flow", "card": [b.width, b.height], "left_over": left,
           "chips": len(pl.movable), "what": "the flow's own grid (RFC 0023)"}
    if not left:
        res["wire_mm"] = round(_wire(b), 1)
        res["slots"] = [pl.ncol, pl.nrow, round(pl.px, 2), round(pl.py, 2)]
        res["decaps_beside"] = sum(1 for c in b.parts.values() if c.kind == "decap" and c.side == "F")
        if write:
            x0, y0, _, _ = pl.region
            draw.svg(b, None, os.path.join(DOC, "flow.svg"), scale=4.0,
                     slots=(x0, y0, pl.px, pl.py, pl.ncol, pl.nrow))
    out.append(res)
    return out


def seeds_table():
    """The annealing's spread: the defaults placed tidily and for wire
    alone from a few seeds."""
    rows = ["| Module | Placed | " + " | ".join(f"Seed {s}" for s in SEEDS) + " | Mean |",
            "|---|---|" + "---:|" * (len(SEEDS) + 1)]
    for m in (1, 5):
        for tidy in (True, False):
            wires = []
            for seed in SEEDS:
                _, pl, left = demo.place(Params(module=m), seed=seed, tidy=tidy)
                wires.append(pl.wire() / 1000 if not left else float("nan"))
            rows.append(f"| {m} | {'tidily' if tidy else 'for wire alone'} | "
                        + " | ".join(f"{w:.1f} m" for w in wires)
                        + f" | {sum(wires) / len(wires):.2f} m |")
    return "\n".join(rows)


def variants_table(results):
    rows = ["| Variant | Parameters | Card | Grid | Share used | Wire (half-perimeter) | "
            "Holes | Least pad gap |", "|---|---|---|---|---:|---:|---:|---:|"]
    for r in results:
        card = f"6U × {r['card'][0]:.0f}"
        if r["variant"] == "flow":
            nc, nr, px, py = r.get("slots", (0, 0, 0, 0))
            rows.append(f"| flow | RFC 0023's slots, at least 12.07 × 33 mm | {card} | "
                        f"{nc} × {nr} slots of {px} × {py} mm | | "
                        f"{r.get('wire_mm', 0) / 1000:.1f} m | | |")
            continue
        p = r["params"]
        g = r["grid"]
        rows.append(f"| {r['variant']} | half {p['half'] / 10:.1f} in, gap {p['gap']}, "
                    f"module {p['module']}, {p['pads']} pads | {card} | "
                    f"{g['columns']} columns × {g['rows']} rows | {100 * r.get('used', 0):.0f}% | "
                    f"{r.get('wire_mm', 0) / 1000:.1f} m | {r.get('holes', 0)} | "
                    f"{r.get('least_pad_gap', 0):.2f} mm |")
    return "\n".join(rows)


def main(write=False):
    footprints.use()
    os.makedirs(DOC, exist_ok=True)
    results = build_variants(write)
    for r in results:
        print(r["variant"], r["card"], r.get("used"), r.get("wire_mm"), r.get("problems"),
              r.get("left_over"))
    if write:
        anatomy(os.path.join(DOC, "anatomy.svg"))
    text = "\n".join([
        "# RFC 0046: results",
        "",
        "Generated by `heron pcb_columns report --write` "
        "([studies/pcb_columns](../../studies/pcb_columns/README.md)); don't edit by hand.",
        "",
        "## The demonstration slice, placed",
        "",
        f"The draft 1b CPU card's {', '.join(demo.SECTIONS[:-1])} and "
        f"{demo.SECTIONS[-1]} sections: {results[0]['chips']} chips, on a 6U card "
        f"(233.35 mm high) with RFC 0026's mechanics. The wire is the half-perimeter "
        f"length of the signal nets inside the slice; the share is of the grid's cells "
        f"not under an exception.",
        "",
        variants_table(results),
        "",
        "Holes: free cells with a box below them in their half-column. "
        "*wire-alone* is the default placed by annealing the boxes' positions "
        "for wire alone, the free room wherever it falls; the others are "
        "annealed on the columns' stacks, the free room at the bottom.",
        "",
        "## The annealing's spread",
        "",
        "The defaults (and module 5) on 6U × 160 from a few seeds, half-perimeter wire:",
        "",
        seeds_table(),
        "",
        "## Boxes",
        "",
        "Each package's box, half-columns × rows, under the defaults and with one "
        "parameter changed:",
        "",
        box_table(),
        "",
        "## The half-column and the gap",
        "",
        param_table(),
        "",
        "## What fits",
        "",
        "The slice under each combination: the share of a 6U × 160 card's grid its "
        "boxes need, and the least 6U card depth (in steps of 10 mm) at which the "
        "placer finds them all a place.",
        "",
        fit_table(),
        "",
    ])
    if write:
        with open(os.path.join(DOC, "results.md"), "w") as f:
            f.write(text)
    else:
        print(text)
    return 0
