"""A board as a PNG: courtyards, pads, tracks by layer and vias, to look
at a placement or a routing without KiCad. Needs Pillow."""

import math

LAYER_COLOURS = {
    "F.Cu": (200, 52, 52), "B.Cu": (60, 90, 220), "In1.Cu": (200, 160, 40),
    "In2.Cu": (60, 170, 80), "In3.Cu": (170, 80, 190), "In4.Cu": (40, 170, 170),
}


def render(board, path, scale=4.0, layers=None, labels=True, ratsnest=None, highlight=()):
    """Draw the board at `scale` pixels per mm. `layers`: the copper
    layers whose tracks to draw (default all). `ratsnest`: a list of
    ((x1, y1), (x2, y2)) lines to draw thin, for unrouted connections."""
    from PIL import Image, ImageDraw, ImageFont
    W, H = int(board.width * scale) + 1, int(board.height * scale) + 1
    img = Image.new("RGB", (W, H), (250, 250, 245))
    d = ImageDraw.Draw(img, "RGBA")

    def P(x, y):
        return x * scale, y * scale

    d.rectangle([0, 0, W - 1, H - 1], outline=(0, 0, 0))
    try:
        font = ImageFont.load_default(size=max(8, int(scale * 1.6)))
    except TypeError:
        font = ImageFont.load_default()
    for p in board.parts.values():
        x0, y0, x1, y1 = p.courtyard()
        fill = (220, 220, 215, 255) if p.side == "F" else (215, 225, 240, 255)
        if p.kind == "decap" or p.kind == "passive":
            fill = (235, 225, 200, 255) if p.side == "F" else (205, 220, 235, 255)
        d.rectangle([P(x0, y0), P(x1, y1)], fill=fill, outline=(150, 150, 150))
    show = layers or board.copper
    for layer in reversed(board.copper):
        if layer not in show:
            continue
        col = LAYER_COLOURS.get(layer, (120, 120, 120))
        for (ly, x1, y1, x2, y2, w, net) in board.tracks:
            if ly != layer:
                continue
            c = (0, 0, 0, 255) if net in highlight else col + (200,)
            d.line([P(x1, y1), P(x2, y2)], fill=c, width=max(1, int(w * scale)))
    for pad in board.pads():
        hx, hy = pad.extent()
        if pad.layers == "*":
            col = (150, 120, 40, 255)
        else:
            col = (190, 40, 40, 255) if pad.part.side == "F" else (40, 70, 200, 255)
        if pad.net in highlight:
            col = (0, 0, 0, 255)
        if pad.shape == "circle":
            d.ellipse([P(pad.x - hx, pad.y - hy), P(pad.x + hx, pad.y + hy)], fill=col)
        else:
            d.rectangle([P(pad.x - hx, pad.y - hy), P(pad.x + hx, pad.y + hy)], fill=col)
    for (x, y, dia, drill, net) in board.vias:
        r = dia / 2
        d.ellipse([P(x - r, y - r), P(x + r, y + r)], fill=(90, 90, 90, 255))
    if ratsnest:
        for (a, b) in ratsnest:
            d.line([P(*a), P(*b)], fill=(0, 120, 0, 90), width=1)
    if labels:
        for p in board.parts.values():
            if p.kind in ("chip", "conn"):
                x0, y0, x1, y1 = p.courtyard()
                d.text(P((x0 + x1) / 2, (y0 + y1) / 2), p.ref, fill=(0, 0, 0), font=font,
                       anchor="mm")
    img.save(path)
    return path


def ratsnest(board):
    """Each net's minimum spanning tree over its pads, as lines."""
    pads = {}
    for pad in board.pads():
        if pad.net and pad.net not in board.planes.values():
            pads.setdefault(pad.net, []).append((pad.x, pad.y))
    out = []
    for net, pts in pads.items():
        if len(pts) < 2:
            continue
        inside = [pts[0]]
        rest = pts[1:]
        while rest:
            best = None
            for i, q in enumerate(rest):
                for p in inside:
                    dd = math.hypot(p[0] - q[0], p[1] - q[1])
                    if best is None or dd < best[0]:
                        best = (dd, i, p)
            _, i, p = best
            q = rest.pop(i)
            inside.append(q)
            out.append((p, q))
    return out
