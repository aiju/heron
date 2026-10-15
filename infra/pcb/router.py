"""Routing a board with the grid router (infra/pcbroute, heron.native).

route() hands it the board's signal layers, every pad and every piece of
fixed copper (the power fanout) as obstacles, and the nets that aren't on a
plane; the routes come back as the board's tracks and vias. The grid's
pitch is the track width plus the clearance.
"""

from . import copper


def _shape(s, layers, net, pad):
    if s.kind == "capsule":
        d = {"kind": "capsule", "x1": s.x1, "y1": s.y1, "x2": s.x2, "y2": s.y2, "r": s.r}
    else:
        d = {"kind": "rect", "cx": s.cx, "cy": s.cy, "hw": s.hw + s.r, "hh": s.hh + s.r,
             "angle": s.angle, "rr": s.r}
    d.update(layers=layers, net=net, pad=pad)
    return d


DEFAULTS = {"iterations": 60, "via_cost": 6.0, "wrong_way": 4.0, "pres_fac": 0.5, "hweight": 1.3,
            "pres_mult": 1.5, "hist_fac": 0.4, "window": 10.0}


def problem(board, dirs=None, layer_cost=None, skip=(), **params):
    """The routing problem for a board: a dict for heron.native.pcbroute."""
    r = board.rules
    sig = board.signal_layers
    li = {name: i for i, name in enumerate(sig)}
    planes = set(board.planes.values()) | set(skip)
    nets = sorted(n for n, pads in board.nets().items() if n not in planes and len(pads) > 1)
    net_id = {n: i for i, n in enumerate(nets)}
    shapes = []
    net_pads = [[] for _ in nets]
    for pad in board.pads():
        if pad.kind == "np_thru_hole":
            # a bare hole: keep copper the hole clearance away from its edge
            hole = (pad.drill or pad.w) / 2 + r["hole_clearance"] - r["clearance"]
            shapes.append({"kind": "capsule", "x1": pad.x, "y1": pad.y, "x2": pad.x, "y2": pad.y,
                           "r": hole, "layers": [], "net": -1, "pad": False})
            continue
        if not pad.number:
            continue
        if pad.layers == "*":
            layers = []
        else:
            layers = [li[l] for l in pad.layers if l in li]
            if not layers:
                continue
        nid = net_id.get(pad.net, -1)
        shapes.append(_shape(copper.pad_shape(pad), layers, nid, nid >= 0))
        if nid >= 0:
            net_pads[nid].append(len(shapes) - 1)
    for (layer, x1, y1, x2, y2, w, net) in board.tracks:
        if layer in li:
            shapes.append({"kind": "capsule", "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                           "r": w / 2, "layers": [li[layer]], "net": net_id.get(net, -1),
                           "pad": False})
    for (x, y, dia, drill, net) in board.vias:
        shapes.append({"kind": "capsule", "x1": x, "y1": y, "x2": x, "y2": y, "r": dia / 2,
                       "layers": [], "net": net_id.get(net, -1), "pad": False})
    if dirs is None:
        # outer layers any way, inner layers alternating
        dirs = [0 if l in ("F.Cu", "B.Cu") else (1 if k % 2 else 2) for k, l in enumerate(sig)]
    if layer_cost is None:
        layer_cost = [1.5 if l == "F.Cu" else 1.0 for l in sig]
    p = dict(DEFAULTS)
    p.update(width=board.width, height=board.height, pitch=r["track"] + r["clearance"],
             layers=len(sig), dirs=dirs, layer_cost=layer_cost, track=r["track"],
             clearance=r["clearance"], via_dia=r["via_dia"], edge=r["edge_clearance"],
             shapes=shapes, nets=[{"name": n, "pads": net_pads[i]} for i, n in enumerate(nets)])
    p.update(params)
    return p


def route(board, verbose=False, **params):
    """Route the board's signal nets in place: their tracks and vias are
    replaced by the router's. Returns the router's solution (a dict:
    per-round statistics, and the nets it could not finish)."""
    from heron import native
    prob = problem(board, verbose=verbose, **params)
    sol = native.pcbroute.route(prob)
    sig = board.signal_layers
    r = board.rules
    names = {n["name"] for n in prob["nets"]}
    board.tracks = [t for t in board.tracks if t[6] not in names]
    board.vias = [v for v in board.vias if v[4] not in names]
    for net in sol["nets"]:
        for (l, x1, y1, x2, y2) in net["segments"]:
            board.tracks.append((sig[l], x1, y1, x2, y2, r["track"], net["name"]))
        for (x, y) in net["vias"]:
            board.vias.append((x, y, r["via_dia"], r["via_drill"], net["name"]))
    return sol
