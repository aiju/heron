"""Specctra DSN and SES: the board as an autorouter's input, and its
routes read back. Freerouting (and most commercial autorouters) read DSN
and write SES.

Each placed part is written as its own image, with its pads already
turned and mirrored as they lie on the board, and placed unrotated on the
front: that keeps the two programs' conventions for rotating and flipping
out of it. DSN's y axis points up, so y is negated going out and back.
Nets on plane layers (VCC, GND) are not routed: fanout() gives their
surface pads a via first, written as fixed wiring.
"""

import math
import os
import subprocess

from . import sexpr
from .sexpr import Str

UM = 1000.0          # DSN units (um) per mm


def _c(v):
    return round(v * UM, 1)


def _shape(pad, layer):
    """A pad's shape on one layer, relative to the pad's centre."""
    if pad.shape == "circle":
        return ["circle", layer, _c(pad.w)]
    a = math.radians(pad.angle)
    ca, sa = math.cos(a), math.sin(a)
    pts = []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        lx, ly = sx * pad.w / 2, sy * pad.h / 2
        pts += [_c(lx * ca + ly * sa), _c(-(-lx * sa + ly * ca))]
    return ["polygon", layer, 0] + pts


def write(board, path, protect=(), vias_only_through=True):
    """The board as a DSN file. Nets in `protect` (default: the planes'
    nets) are not routed."""
    protect = set(protect) | set(board.planes.values())
    r = board.rules
    layers = board.copper
    out = ["pcb", Str(board.name),
           ["parser", ["string_quote", Str('"')], ["space_in_quoted_tokens", "on"],
            ["host_cad", Str("heron")], ["host_version", Str("0")]],
           ["resolution", "um", 10], ["unit", "um"]]
    st = ["structure"]
    for i, (name, net) in enumerate(board.stackup):
        st.append(["layer", name, ["type", "power" if net else "signal"],
                   ["property", ["index", i]]])
    w, h = board.width, board.height
    st.append(["boundary", ["path", "pcb", 0, 0, 0, _c(w), 0, _c(w), _c(-h), 0, _c(-h), 0, 0]])
    m = r["edge_clearance"]
    for layer, net in board.planes.items():
        st.append(["plane", net, ["polygon", layer, 0, _c(m), _c(-m), _c(w - m), _c(-m),
                                  _c(w - m), _c(-(h - m)), _c(m), _c(-(h - m))]])
    via = f"Via_{int(r['via_dia'] * 1000)}:{int(r['via_drill'] * 1000)}_um"
    st.append(["via", Str(via)])
    st.append(["rule", ["width", _c(r["track"])], ["clearance", _c(r["clearance"])],
               ["clearance", _c(r["clearance"]), ["type", "default_smd"]],
               ["clearance", _c(r["clearance"] / 4), ["type", "smd_smd"]]])
    out.append(st)
    place = ["placement"]
    lib = ["library"]
    stacks = {}
    for part in sorted(board.parts.values(), key=lambda p: p.ref):
        image = ["image", Str(part.ref)]
        for pad in part.pads():
            if pad.kind == "np_thru_hole" or not pad.number:
                continue
            on = layers if pad.layers == "*" else pad.layers
            if not on:
                continue
            key = (tuple(on), tuple(_shape(pad, "")[2:]), _shape(pad, "")[0])
            if key not in stacks:
                stacks[key] = f"PS{len(stacks)}"
                lib.append(["padstack", stacks[key]]
                           + [["shape", _shape(pad, l)] for l in on] + [["attach", "off"]])
            image.append(["pin", stacks[key], Str(pad.number),
                          _c(pad.x - part.x), _c(-(pad.y - part.y))])
        lib.insert(1, image)
        place.append(["component", Str(part.ref),
                      ["place", Str(part.ref), _c(part.x), _c(-part.y), "front", 0]])
    vps = ["padstack", Str(via)]
    for l in layers:
        vps.append(["shape", ["circle", l, _c(r["via_dia"])]])
    vps.append(["attach", "off"])
    lib.append(vps)
    out.append(place)
    out.append(lib)
    netw = ["network"]
    nets = board.nets()
    for net in sorted(nets):
        pins = [f"{ref}-{num}" for ref, num in sorted(nets[net])]
        netw.append(["net", Str(net), ["pins"] + pins])
    routed = [n for n in sorted(nets) if n not in protect]
    netw.append(["class", "signal"] + [Str(n) for n in routed]
                + [["circuit", ["use_via", Str(via)]],
                   ["rule", ["width", _c(r["track"])], ["clearance", _c(r["clearance"])]]])
    fixed = [n for n in sorted(nets) if n in protect]
    if fixed:
        netw.append(["class", "power"] + [Str(n) for n in fixed]
                    + [["circuit", ["use_via", Str(via)]],
                       ["rule", ["width", _c(r["power_track"])],
                        ["clearance", _c(r["clearance"])]]])
    out.append(netw)
    wiring = ["wiring"]
    for (layer, x1, y1, x2, y2, width, net) in board.tracks:
        wiring.append(["wire", ["path", layer, _c(width), _c(x1), _c(-y1), _c(x2), _c(-y2)],
                       ["net", Str(net)], ["type", "fix" if net in protect else "route"]])
    for (x, y, dia, drill, net) in board.vias:
        wiring.append(["via", Str(via), _c(x), _c(-y), ["net", Str(net)],
                       ["type", "fix" if net in protect else "route"]])
    out.append(wiring)
    with open(path, "w") as f:
        f.write(sexpr.dump(out, flat_depth=3) + "\n")
    return routed


def read_ses(board, path, replace=True):
    """Add the routes of a SES file to the board (replacing its tracks and
    vias of the routed nets)."""
    e = sexpr.load(path)
    routes = sexpr.find(e, "routes")
    res = sexpr.find(routes, "resolution")
    scale = float(res[2]) * UM          # file units per mm
    via_size = {}
    lib = sexpr.find(routes, "library_out")
    if lib is not None:
        for ps in sexpr.find_all(lib, "padstack"):
            for sh in sexpr.find_all(ps, "shape"):
                c = sexpr.find(sh, "circle")
                if c is not None:
                    via_size[str(ps[1])] = c[2] / scale
    netout = sexpr.find(routes, "network_out")
    tracks, vias = [], []
    names = set()
    for net in sexpr.find_all(netout, "net"):
        name = str(net[1])
        names.add(name)
        for wire in sexpr.find_all(net, "wire"):
            p = sexpr.find(wire, "path")
            layer, width = str(p[1]), p[2] / scale
            pts = [v / scale for v in p[3:] if isinstance(v, (int, float))]
            xy = [(pts[i], -pts[i + 1]) for i in range(0, len(pts) - 1, 2)]
            for a, b in zip(xy, xy[1:]):
                tracks.append((layer, a[0], a[1], b[0], b[1], width, name))
        for v in sexpr.find_all(net, "via"):
            dia = via_size.get(str(v[1]), board.rules["via_dia"])
            vias.append((v[2] / scale, -v[3] / scale, dia, board.rules["via_drill"], name))
    if replace:
        board.tracks = [t for t in board.tracks if t[6] not in names]
        board.vias = [v for v in board.vias if v[4] not in names]
    board.tracks += tracks
    board.vias += vias
    return len(tracks), len(vias)


FREEROUTING = os.environ.get("FREEROUTING_JAR", os.path.expanduser(
    "~/freerouting/freerouting/build/libs/freerouting-current-executable.jar"))


def freeroute(dsn, ses, passes=100, threads=None, timeout=None, log=None, extra=()):
    """Run Freerouting on a DSN file; returns its exit code."""
    cmd = ["java", "-jar", FREEROUTING, "-de", dsn, "-do", ses, "-mp", str(passes),
           "--gui.enabled=false"] + list(extra)
    if threads is not None:
        cmd += ["-mt", str(threads)]
    with open(log or os.devnull, "w") as f:
        p = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
    return p.returncode
