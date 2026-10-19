"""A placed board as an SVG: the grid, each chip's box, the parts with
their bodies and pads, the capacitors under them, the exceptions off the
grid. For the RFC's figures and for looking at a placement."""

from heron.infra.pcb import kicadlib, sexpr

from .grid import ROW

COLOURS = {
    "board": "#f3f0e6", "edge": "#2b2b2b", "keepout": "#e4dfd0",
    "row": "#e6e1d2", "half": "#cfc7b2", "column": "#a99f86",
    "box_narrow": "#dde7ef", "box_wide": "#f1e2cf", "box_other": "#e0ecd8",
    "box_edge": "#8f9aa3",
    "body": "#34363a", "socket": "#5b5148", "text": "#f6f6f2", "ref": "#b9bcc2",
    "pad": "#c8a24a", "hole": "#f3f0e6", "decap": "#3f69c9",
    "conn": "#8a8d93", "mech": "#9a9a9a", "rats": "#2f8f4a",
}


def _body(fp):
    """The footprint's body outline from its fabrication layer: (x0, y0,
    x1, y1), or None."""
    xs, ys = [], []
    for item in fp.expr:
        if not (isinstance(item, list) and item and item[0] in ("fp_line", "fp_rect", "fp_poly",
                                                                 "fp_circle")):
            continue
        if sexpr.value(item, "layer") != "F.Fab":
            continue
        for key in ("start", "end", "center"):
            e = sexpr.find(item, key)
            if e is not None:
                xs.append(float(e[1]))
                ys.append(float(e[2]))
        pts = sexpr.find(item, "pts")
        if pts is not None:
            for xy in sexpr.find_all(pts, "xy"):
                xs.append(float(xy[1]))
                ys.append(float(xy[2]))
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _rect_on_board(part, r):
    x0, y0, x1, y1 = r
    if part.side == "B":
        y0, y1 = -y1, -y0
    pts = [kicadlib.rotate(x, y, part.rot) for x in (x0, x1) for y in (y0, y1)]
    xs = [part.x + p[0] for p in pts]
    ys = [part.y + p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _f(v):
    return f"{v:.3f}".rstrip("0").rstrip(".")


def _rect(x0, y0, x1, y1, **attrs):
    a = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return f'<rect x="{_f(x0)}" y="{_f(y0)}" width="{_f(x1 - x0)}" height="{_f(y1 - y0)}" {a}/>'


def _text(x, y, s, size, fill, rotate=False, weight="normal"):
    t = f' transform="rotate(-90 {_f(x)} {_f(y)})"' if rotate else ""
    s = s.replace("&", "&amp;").replace("<", "&lt;")
    return (f'<text x="{_f(x)}" y="{_f(y)}" font-size="{_f(size)}" fill="{fill}" '
            f'font-family="DejaVu Sans, Helvetica, Arial, sans-serif" font-weight="{weight}" '
            f'text-anchor="middle" dominant-baseline="central"{t}>{s}</text>')


def _pad(d, out):
    hx, hy = d.extent()
    c = COLOURS["pad"]
    if d.shape == "circle":
        out.append(f'<circle cx="{_f(d.x)}" cy="{_f(d.y)}" r="{_f(hx)}" fill="{c}"/>')
    else:
        r = min(hx, hy) * (1.0 if d.shape == "oval" else 2 * (d.d.rratio or 0.0))
        out.append(_rect(d.x - hx, d.y - hy, d.x + hx, d.y + hy, fill=c, rx=_f(r), ry=_f(r)))
    if d.drill:
        out.append(f'<circle cx="{_f(d.x)}" cy="{_f(d.y)}" r="{_f(d.drill / 2)}" '
                   f'fill="{COLOURS["hole"]}"/>')


def svg(b, pl, path=None, view=None, scale=5.0, labels=True, ratsnest=False, grid=True,
        slots=None):
    """Draw the board, or the part of it `view` = (x0, y0, x1, y1) mm,
    `scale` pixels to the mm. `pl` is its GridPlacer, for the grid and the
    boxes; without one (None) only the parts are drawn, with `slots` =
    (x0, y0, px, py, columns, rows) the slots of the flow's own grid
    (infra.pcb.place.GridPlacer). Returns the SVG's text, and writes it to
    `path` if given."""
    vx0, vy0, vx1, vy1 = view or (0, 0, b.width, b.height)
    W, H = vx1 - vx0, vy1 - vy0
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{round(W * scale)}" '
           f'height="{round(H * scale)}" viewBox="{_f(vx0)} {_f(vy0)} {_f(W)} {_f(H)}">']
    out.append(_rect(0, 0, b.width, b.height, fill=COLOURS["board"]))
    for k in b.keepouts:
        if "footprints" in k["no"]:
            out.append(_rect(k["x0"], k["y0"], k["x1"], k["y1"], fill=COLOURS["keepout"]))
    if slots:
        sx, sy, px, py, nc, nr = slots
        for c in range(nc + 1):
            out.append(f'<line x1="{_f(sx + c * px)}" y1="{_f(sy)}" x2="{_f(sx + c * px)}" '
                       f'y2="{_f(sy + nr * py)}" stroke="{COLOURS["column"]}" stroke-width="0.2"/>')
        for r in range(nr + 1):
            out.append(f'<line x1="{_f(sx)}" y1="{_f(sy + r * py)}" x2="{_f(sx + nc * px)}" '
                       f'y2="{_f(sy + r * py)}" stroke="{COLOURS["column"]}" stroke-width="0.2"/>')
    lat = pl.lat if pl else None
    if grid and lat:
        x1, y1 = lat.x + lat.width, lat.y + lat.height
        for r in range(lat.rows + 1):
            y = lat.y + r * ROW
            out.append(f'<line x1="{_f(lat.x)}" y1="{_f(y)}" x2="{_f(x1)}" y2="{_f(y)}" '
                       f'stroke="{COLOURS["row"]}" stroke-width="0.08"/>')
        for hc in range(lat.halves + 1):
            x = lat.x + hc * pl.p.half_mm
            col = hc % 2 == 0
            out.append(f'<line x1="{_f(x)}" y1="{_f(lat.y)}" x2="{_f(x)}" y2="{_f(y1)}" '
                       f'stroke="{COLOURS["column" if col else "half"]}" '
                       f'stroke-width="{0.25 if col else 0.12}"'
                       f'{"" if col else " stroke-dasharray=\"0.8 0.8\""}/>')
    # the boxes
    for p in (pl.chips if pl else ()):
        if p.ref not in pl.pos:
            continue
        bx = pl.boxes[p.ref]
        x0, y0, x1, y1 = lat.rect(*pl.pos[p.ref], bx.w, bx.h)
        kind = "box_other" if not p.fp.name.startswith("Package_DIP:") else \
            ("box_wide" if bx.w == 2 else "box_narrow")
        out.append(_rect(x0 + 0.35, y0 + 0.35, x1 - 0.35, y1 - 0.35, fill=COLOURS[kind],
                         stroke=COLOURS["box_edge"], stroke_width="0.15", rx="0.6", ry="0.6"))
    # the parts on top
    for p in b.parts.values():
        if p.side != "F" or p.kind == "decap":
            continue
        body = _body(p.fp)
        if p.kind in ("chip", "conn") and body:
            x0, y0, x1, y1 = _rect_on_board(p, body)
            fill = COLOURS["conn"] if p.kind == "conn" else \
                (COLOURS["socket"] if "Socket" in p.fp.name else COLOURS["body"])
            out.append(_rect(x0, y0, x1, y1, fill=fill, rx="0.5", ry="0.5"))
        for d in p.pads():
            _pad(d, out)
        if p.kind == "mech":
            for d in p.pads():
                hx, _ = d.extent()
                out.append(f'<circle cx="{_f(d.x)}" cy="{_f(d.y)}" r="{_f(max(hx, 0.6))}" '
                           f'fill="none" stroke="{COLOURS["mech"]}" stroke-width="0.2"/>')
    # the capacitors: underneath as outlines, on top with their pads
    for p in b.parts.values():
        if p.kind != "decap":
            continue
        x0, y0, x1, y1 = p.courtyard()
        if p.side == "B":
            out.append(_rect(x0, y0, x1, y1, fill="none", stroke=COLOURS["decap"],
                             stroke_width="0.2", stroke_dasharray="0.5 0.3"))
        else:
            out.append(_rect(x0, y0, x1, y1, fill="none", stroke=COLOURS["decap"],
                             stroke_width="0.2"))
            for d in p.pads():
                _pad(d, out)
    if ratsnest:
        from heron.infra.pcb import render
        for (ax, ay), (cx, cy) in render.ratsnest(b):
            out.append(f'<line x1="{_f(ax)}" y1="{_f(ay)}" x2="{_f(cx)}" y2="{_f(cy)}" '
                       f'stroke="{COLOURS["rats"]}" stroke-width="0.12" stroke-opacity="0.45"/>')
    if labels:
        for p in b.parts.values():
            if p.kind != "chip" or p.side != "F":
                continue
            body = _body(p.fp)
            if not body:
                continue
            x0, y0, x1, y1 = _rect_on_board(p, body)
            w, h = x1 - x0, y1 - y0
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            name = p.value or p.ref
            ref = p.ref[2:] if p.ref.startswith("U_") else p.ref
            size = 1.5
            fits = len(name) * size * 0.62 <= w - 0.6
            if not fits:
                size = min(1.5, (w - 0.6) / (len(name) * 0.62))
                fits = size >= 1.1
            if fits:
                out.append(_text(cx, cy - size * 0.55, name, size, COLOURS["text"], weight="bold"))
                out.append(_text(cx, cy + size * 0.75, ref, size * 0.8, COLOURS["ref"]))
            else:
                size = min(1.5, (h - 1.0) / (len(name) * 0.62))
                out.append(_text(cx - size * 0.55, cy, name, size, COLOURS["text"], rotate=True,
                                 weight="bold"))
                out.append(_text(cx + size * 0.75, cy, ref, size * 0.8, COLOURS["ref"],
                                 rotate=True))
    out.append(_rect(0, 0, b.width, b.height, fill="none", stroke=COLOURS["edge"],
                     stroke_width="0.4"))
    out.append("</svg>")
    text = "\n".join(out) + "\n"
    if path:
        with open(path, "w") as f:
            f.write(text)
    return text

