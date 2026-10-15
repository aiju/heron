"""A printed circuit board: parts placed on it, their pads' nets, and the
copper (tracks, vias and zones), written as a KiCad 9 board file.

Coordinates are millimetres, x to the right and y down, as in KiCad. A
part's rotation is in degrees, counter-clockwise as seen from the top; a
part on the bottom (side "B") is mirrored top to bottom about its origin
first, as KiCad flips it, so its rotation is still as seen from the top.

The board file is written directly, without KiCad's own programs: the
footprints come from KiCad's libraries (kicadlib), and KiCad reads the
result. A board read back (read_kicad) has the same parts, nets and
copper, which is what the checks use.
"""

import math
import uuid as _uuid
from collections import defaultdict

from . import kicadlib, sexpr
from .sexpr import Str

# Design rules: millimetres. The default is a common fab's standard
# multilayer process (0.127 mm tracks and gaps, 0.2 mm holes).
RULES = {"track": 0.127, "clearance": 0.127, "via_dia": 0.45, "via_drill": 0.2,
         "power_track": 0.4, "edge_clearance": 0.5, "hole_clearance": 0.25}

# Stackups: the copper layers from top to bottom, each a signal layer or a
# plane of a net.
STACKUPS = {
    2: [("F.Cu", None), ("B.Cu", None)],
    4: [("F.Cu", None), ("In1.Cu", "GND"), ("In2.Cu", "VCC"), ("B.Cu", None)],
    6: [("F.Cu", None), ("In1.Cu", "GND"), ("In2.Cu", None), ("In3.Cu", None),
        ("In4.Cu", "VCC"), ("B.Cu", None)],
    "6s": [("F.Cu", None), ("In1.Cu", None), ("In2.Cu", "GND"), ("In3.Cu", "VCC"),
           ("In4.Cu", None), ("B.Cu", None)],
}

# KiCad 9's layer ids
_CU_IDS = {"F.Cu": 0, "B.Cu": 2, **{f"In{i}.Cu": 2 + 2 * i for i in range(1, 31)}}
_USER_LAYERS = [
    (9, "F.Adhes", "user", "F.Adhesive"), (11, "B.Adhes", "user", "B.Adhesive"),
    (13, "F.Paste", "user"), (15, "B.Paste", "user"),
    (5, "F.SilkS", "user", "F.Silkscreen"), (7, "B.SilkS", "user", "B.Silkscreen"),
    (1, "F.Mask", "user"), (3, "B.Mask", "user"),
    (17, "Dwgs.User", "user", "User.Drawings"), (19, "Cmts.User", "user", "User.Comments"),
    (21, "Eco1.User", "user", "User.Eco1"), (23, "Eco2.User", "user", "User.Eco2"),
    (25, "Edge.Cuts", "user"), (27, "Margin", "user"),
    (31, "F.CrtYd", "user", "F.Courtyard"), (29, "B.CrtYd", "user", "B.Courtyard"),
    (35, "F.Fab", "user"), (33, "B.Fab", "user"),
]


def _flip_layer(name):
    if isinstance(name, str) and name[:2] in ("F.", "B."):
        return ("B." if name[0] == "F" else "F.") + name[2:]
    return name


class Pad:
    """A pad on the board: its part, number, net and shape in board
    coordinates (centre, angle, size), and its copper layers."""

    def __init__(self, part, d):
        self.part, self.d = part, d
        self.number = d.number
        self.net = part.nets.get(d.number)
        ly = -d.y if part.side == "B" else d.y
        dx, dy = kicadlib.rotate(d.x, ly, part.rot)
        self.x, self.y = part.x + dx, part.y + dy
        local = -d.rot if part.side == "B" else d.rot
        self.angle = (part.rot + local) % 360
        self.w, self.h = d.w, d.h
        self.shape = d.shape
        self.drill = d.drill
        if d.kind in ("thru_hole", "np_thru_hole"):
            self.layers = "*"
        else:
            self.layers = [part.side + ".Cu"] if "F.Cu" in d.layers or "B.Cu" in d.layers else []
        self.kind = d.kind

    def on(self, layer):
        return self.layers == "*" or layer in self.layers

    def extent(self):
        """Half-sizes of the pad's bounding box in board axes."""
        a = math.radians(self.angle)
        c, s = abs(math.cos(a)), abs(math.sin(a))
        return (self.w * c + self.h * s) / 2, (self.w * s + self.h * c) / 2


class Part:
    """A part: a footprint, the nets of its pads, and where it is.

    kind: "chip" (a logical instance of the netlist), "decap", "conn",
    "passive", "jumper", "mech"; inst is the netlist instance's reference
    for a chip."""

    def __init__(self, ref, footprint, nets, value="", kind="chip", inst=None, section=None,
                 typ=None):
        self.ref = ref
        self.fp = kicadlib.footprint(footprint) if isinstance(footprint, str) else footprint
        self.nets = dict(nets)
        self.value = value
        self.kind = kind
        self.inst = inst
        self.section = section
        self.typ = typ
        self.x = self.y = 0.0
        self.rot = 0.0
        self.side = "F"
        self.fixed = False

    def place(self, x, y, rot=0.0, side="F"):
        self.x, self.y, self.rot, self.side = x, y, rot % 360, side
        return self

    def pads(self):
        return [Pad(self, d) for d in self.fp.pads]

    def body_centre(self):
        """The middle of the pads' bounding box, in footprint coordinates
        (a DIP footprint's origin is its pin 1)."""
        xs = [d.x for d in self.fp.pads if d.number]
        ys = [d.y for d in self.fp.pads if d.number]
        return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

    def turn(self, rot):
        """Set the rotation, keeping the body's centre where it is."""
        cx, cy = self.body_centre()
        if self.side == "B":
            cy = -cy
        ox, oy = kicadlib.rotate(cx, cy, self.rot)
        nx, ny = kicadlib.rotate(cx, cy, rot)
        self.place(self.x + ox - nx, self.y + oy - ny, rot, self.side)

    def courtyard(self):
        """The courtyard's bounding box in board coordinates."""
        x0, y0, x1, y1 = self.fp.courtyard
        if self.side == "B":
            y0, y1 = -y1, -y0
        pts = [kicadlib.rotate(x, y, self.rot) for x in (x0, x1) for y in (y0, y1)]
        xs = [self.x + p[0] for p in pts]
        ys = [self.y + p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def tht(self):
        return any(d.kind == "thru_hole" for d in self.fp.pads)


class Board:
    def __init__(self, name, width, height, layers=6, rules=None):
        self.name = name
        self.width, self.height = width, height
        self.stackup = list(STACKUPS[layers])
        self.rules = dict(RULES, **(rules or {}))
        self.parts = {}
        self.tracks = []        # (layer, x1, y1, x2, y2, width, net)
        self.vias = []          # (x, y, dia, drill, net)
        self.zones = []         # dict: layer, net, pts, priority, filled (list of polygons)
        self.texts = []         # (layer, x, y, text, size)
        self.holes = []         # mounting holes: (x, y, drill)

    # ---- contents ----------------------------------------------------------------

    def add(self, part):
        if part.ref in self.parts:
            raise ValueError(f"duplicate part {part.ref}")
        self.parts[part.ref] = part
        return part

    @property
    def copper(self):
        return [name for name, _ in self.stackup]

    @property
    def signal_layers(self):
        return [name for name, net in self.stackup if net is None]

    @property
    def planes(self):
        return {name: net for name, net in self.stackup if net is not None}

    def pads(self):
        for p in self.parts.values():
            yield from p.pads()

    def nets(self):
        """net -> [(ref, pad number)]"""
        out = defaultdict(list)
        for p in self.parts.values():
            for num, net in p.nets.items():
                if net:
                    out[net].append((p.ref, num))
        return dict(out)

    def add_planes(self, margin=None):
        """A zone over the whole board on each plane layer."""
        m = self.rules["edge_clearance"] if margin is None else margin
        pts = [(m, m), (self.width - m, m), (self.width - m, self.height - m),
               (m, self.height - m)]
        for layer, net in self.planes.items():
            self.zones.append({"layer": layer, "net": net, "pts": pts, "priority": 0,
                               "filled": None})

    # ---- writing --------------------------------------------------------------------

    def write(self, path):
        """Write the board, and next to it a project file with the design
        rules (KiCad keeps them there, not in the board)."""
        with open(path, "w") as f:
            f.write(self.kicad_text())
        import json
        import os
        r = self.rules
        pro = {
            "board": {"design_settings": {
                "defaults": {}, "diff_pair_dimensions": [], "drc_exclusions": [],
                "rules": {"min_clearance": r["clearance"], "min_track_width": r["track"],
                          "min_via_diameter": r["via_dia"],
                          "min_via_annular_width": round((r["via_dia"] - r["via_drill"]) / 2 - 0.001, 4),
                          "min_through_hole_diameter": r["via_drill"],
                          "min_hole_clearance": r["hole_clearance"],
                          "min_hole_to_hole": r["hole_clearance"],
                          "min_copper_edge_clearance": r["edge_clearance"] - 0.01,
                          "min_silk_clearance": 0.0},
                "rule_severities": {k: "ignore" for k in (
                    "silk_overlap", "silk_over_copper", "silk_edge_clearance", "lib_footprint_issues",
                    "lib_footprint_mismatch", "text_height", "text_thickness")},
                "track_widths": [0.0, r["track"], r["power_track"]],
                "via_dimensions": [{"diameter": 0.0, "drill": 0.0},
                                   {"diameter": r["via_dia"], "drill": r["via_drill"]}]}},
            "net_settings": {"classes": [{
                "name": "Default", "clearance": r["clearance"], "track_width": r["track"],
                "via_diameter": r["via_dia"], "via_drill": r["via_drill"],
                "microvia_diameter": 0.3, "microvia_drill": 0.1, "diff_pair_gap": 0.25,
                "diff_pair_via_gap": 0.25, "diff_pair_width": 0.2, "line_style": 0,
                "wire_width": 6, "bus_width": 12, "pcb_color": "rgba(0, 0, 0, 0.000)",
                "schematic_color": "rgba(0, 0, 0, 0.000)", "priority": 2147483647}],
                "meta": {"version": 4}},
            "meta": {"filename": os.path.basename(path)[:-len(".kicad_pcb")] + ".kicad_pro",
                     "version": 3},
        }
        with open(path[:-len(".kicad_pcb")] + ".kicad_pro", "w") as f:
            json.dump(pro, f, indent=2)

    def kicad_text(self):
        net_ids = {"": 0}
        for net in sorted({n for p in self.parts.values() for n in p.nets.values() if n}
                          | {t[6] for t in self.tracks} | {v[4] for v in self.vias}
                          | {z["net"] for z in self.zones}):
            net_ids[net] = len(net_ids)
        n_cu = len(self.stackup)
        layers = [["layers"]]
        for name, _ in self.stackup:
            layers[0].append([_CU_IDS[name], Str(name), "signal"])
        for entry in _USER_LAYERS:
            layers[0].append([entry[0], Str(entry[1])] + list(entry[2:3])
                             + [Str(e) for e in entry[3:]])
        out = ["kicad_pcb", ["version", 20241229], ["generator", Str("heron")],
               ["generator_version", Str("9.0")],
               ["general", ["thickness", 1.6], ["legacy_teardrops", "no"]],
               ["paper", Str("A2")], layers[0], self._setup(n_cu)]
        for net, i in net_ids.items():
            out.append(["net", i, Str(net)])
        for part in sorted(self.parts.values(), key=lambda p: p.ref):
            out.append(self._footprint(part, net_ids))
        w, h = self.width, self.height
        out.append(["gr_rect", ["start", 0.0, 0.0], ["end", float(w), float(h)],
                    ["stroke", ["width", 0.1], ["type", "default"]], ["fill", "no"],
                    ["layer", Str("Edge.Cuts")], ["uuid", Str(self._uuid("edge"))]])
        for i, (layer, x, y, text, size) in enumerate(self.texts):
            out.append(["gr_text", Str(text), ["at", x, y, 0], ["layer", Str(layer)],
                        ["uuid", Str(self._uuid(f"text{i}"))],
                        ["effects", ["font", ["size", size, size], ["thickness", size / 7]],
                         *([["justify", "mirror"]] if layer.startswith("B.") else [])]])
        for i, (x, y, dia, drill, net) in enumerate(self.vias):
            out.append(["via", ["at", round(x, 4), round(y, 4)], ["size", dia], ["drill", drill],
                        ["layers", Str("F.Cu"), Str("B.Cu")], ["net", net_ids[net]],
                        ["uuid", Str(self._uuid(f"via{i}"))]])
        for i, (layer, x1, y1, x2, y2, width, net) in enumerate(self.tracks):
            out.append(["segment", ["start", round(x1, 4), round(y1, 4)],
                        ["end", round(x2, 4), round(y2, 4)], ["width", width],
                        ["layer", Str(layer)], ["net", net_ids[net]],
                        ["uuid", Str(self._uuid(f"seg{i}"))]])
        for i, z in enumerate(self.zones):
            zone = ["zone", ["net", net_ids[z["net"]]], ["net_name", Str(z["net"])],
                    ["layer", Str(z["layer"])], ["uuid", Str(self._uuid(f"zone{i}"))],
                    ["hatch", "edge", 0.5], ["priority", z.get("priority", 0)],
                    ["connect_pads", ["clearance", self.rules["clearance"]]],
                    ["min_thickness", 0.2], ["filled_areas_thickness", "no"],
                    ["fill", "yes", ["thermal_gap", 0.3], ["thermal_bridge_width", 0.3]],
                    ["polygon", ["pts"] + [["xy", float(x), float(y)] for x, y in z["pts"]]]]
            for poly in z.get("filled") or []:
                zone.append(["filled_polygon", ["layer", Str(z["layer"])],
                             ["pts"] + [["xy", float(x), float(y)] for x, y in poly]])
            out.append(zone)
        out.append(["embedded_fonts", "no"])
        return sexpr.dump(out, flat_depth=3) + "\n"

    def _uuid(self, key):
        return str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"heron:{self.name}:{key}"))

    def _setup(self, n_cu):
        return ["setup", ["pad_to_mask_clearance", 0],
                ["allow_soldermask_bridges_in_footprints", "no"],
                ["tenting", "front", "back"]]

    def _footprint(self, part, net_ids):
        fp = part.fp.expr
        flip = part.side == "B"
        lib = part.fp.name
        out = ["footprint", Str(lib), ["layer", Str(f"{part.side}.Cu")],
               ["uuid", Str(self._uuid(f"fp:{part.ref}"))],
               ["at", round(part.x, 4), round(part.y, 4)] + ([round(part.rot, 3)] if part.rot else [])]
        for item in fp[2:]:
            if not isinstance(item, list) or not item:
                continue
            key = item[0]
            if key in ("version", "generator", "generator_version", "layer", "uuid", "at"):
                continue
            if key == "property":
                item = list(item)
                if item[1] == "Reference":
                    item[2] = Str(part.ref)
                elif item[1] == "Value":
                    item[2] = Str(part.value or part.fp.name.split(":")[-1])
                item = self._place_child(item, part, flip)
            elif key == "pad":
                item = self._place_child(item, part, flip)
                net = part.nets.get(str(item[1]))
                item = [e for e in item if not (isinstance(e, list) and e and e[0] in ("net", "uuid"))]
                if net:
                    item.append(["net", net_ids[net], Str(net)])
                item.append(["uuid", Str(self._uuid(f"pad:{part.ref}:{item[1]}:{len(item)}"))])
            elif key in ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly", "fp_text"):
                item = self._place_child(item, part, flip)
            elif key == "model":
                pass
            out.append(item)
        return out

    @staticmethod
    def _place_child(item, part, flip):
        """A footprint's child item for the board file: on the bottom,
        mirrored (y negated, F/B layers swapped, text mirrored); pads and
        texts get the part's rotation added to their angle."""
        def tr(e):
            if not isinstance(e, list) or not e:
                return e
            k = e[0]
            if k in ("at",) and len(e) >= 3:
                x, y = e[1], e[2]
                ang = e[3] if len(e) > 3 else 0
                if flip:
                    y, ang = -y, -ang
                if item[0] in ("pad", "property", "fp_text"):
                    ang = (ang + part.rot) % 360
                return ["at", x, y] + ([round(ang, 3)] if ang else [])
            if k in ("start", "end", "mid", "center", "xy") and len(e) >= 3 and flip:
                return [k, e[1], -e[2]] + e[3:]
            if k == "layer" and flip:
                return [k, Str(_flip_layer(str(e[1])))]
            if k == "layers" and flip:
                return [k] + [Str(_flip_layer(str(l))) for l in e[1:]]
            if k == "effects" and flip and item[0] in ("property", "fp_text"):
                inner = [tr(x) for x in e]
                j = sexpr.find(inner, "justify")
                if j is None:
                    inner.append(["justify", "mirror"])
                elif "mirror" not in j:
                    j.append("mirror")
                return inner
            return [tr(x) for x in e]
        return [tr(x) for x in item]


# ---- reading a board back ----------------------------------------------------------

def _unplace(item, rot, flip):
    """A footprint child as the board file has it, back in the footprint's
    own coordinates: the inverse of Board._place_child."""
    def tr(e):
        if not isinstance(e, list) or not e:
            return e
        k = e[0]
        if k == "at" and len(e) >= 3:
            x, y = e[1], e[2]
            ang = e[3] if len(e) > 3 else 0
            if item[0] in ("pad", "property", "fp_text"):
                ang = (ang - rot) % 360
            if flip:
                y, ang = -y, (-ang) % 360
            return ["at", x, y] + ([ang] if ang else [])
        if k in ("start", "end", "mid", "center", "xy") and len(e) >= 3 and flip:
            return [k, e[1], -e[2]] + e[3:]
        if k == "layer" and flip:
            return [k, Str(_flip_layer(str(e[1])))]
        if k == "layers" and flip:
            return [k] + [Str(_flip_layer(str(l))) for l in e[1:]]
        if k == "justify" and flip:
            return [x for x in e if x != "mirror"]
        return [tr(x) for x in e]
    return [tr(x) for x in item]


def read_kicad(path):
    """A Board from a .kicad_pcb file: parts with their nets and placement,
    tracks, vias and zones (with their filled polygons if the file has
    them). The footprints are the board file's own copies."""
    e = sexpr.load(path)
    x0 = y0 = 0.0
    x1 = y1 = 100.0
    for g in sexpr.find_all(e, "gr_rect"):
        if sexpr.value(g, "layer") == "Edge.Cuts":
            s, t = sexpr.find(g, "start"), sexpr.find(g, "end")
            x0, y0, x1, y1 = s[1], s[2], t[1], t[2]
    cu = [str(l[1]) for l in sexpr.find(e, "layers")[1:] if str(l[1]).endswith(".Cu")]
    order = ["F.Cu"] + [f"In{i}.Cu" for i in range(1, 31)] + ["B.Cu"]
    cu = [l for l in order if l in cu]
    b = Board(path, x1 - x0, y1 - y0, layers=2)
    b.stackup = [(l, None) for l in cu]
    nets = {int(n[1]): str(n[2]) for n in sexpr.find_all(e, "net")}
    for fp in sexpr.find_all(e, "footprint"):
        at = sexpr.find(fp, "at")
        side = "B" if sexpr.value(fp, "layer") == "B.Cu" else "F"
        ref = None
        for prop in sexpr.find_all(fp, "property"):
            if prop[1] == "Reference":
                ref = str(prop[2])
        rot = float(at[3]) if len(at) > 3 else 0.0
        # undo the board file's placement of the children: back to the
        # footprint's own coordinates, unflipped (the inverse of _place_child)
        local = ["footprint", fp[1]]
        pad_nets = {}
        for item in fp[2:]:
            if not (isinstance(item, list) and item):
                continue
            if item[0] in ("layer", "uuid", "at"):
                continue
            item = _unplace(item, rot, side == "B")
            if item[0] == "pad":
                n = sexpr.find(item, "net")
                if n is not None:
                    pad_nets[str(item[1])] = str(n[2]) if len(n) > 2 else nets[int(n[1])]
            local.append(item)
        f = kicadlib.Footprint(str(fp[1]), local)
        part = Part(ref, f, pad_nets)
        part.place(float(at[1]) - x0, float(at[2]) - y0, rot, side)
        for prop in sexpr.find_all(fp, "property"):
            if prop[1] == "Value":
                part.value = str(prop[2])
        b.parts[ref] = part
    for s in sexpr.find_all(e, "segment"):
        st, en = sexpr.find(s, "start"), sexpr.find(s, "end")
        b.tracks.append((str(sexpr.value(s, "layer")), st[1] - x0, st[2] - y0, en[1] - x0,
                         en[2] - y0, float(sexpr.value(s, "width")), nets[int(sexpr.value(s, "net"))]))
    for v in sexpr.find_all(e, "via"):
        at = sexpr.find(v, "at")
        b.vias.append((at[1] - x0, at[2] - y0, float(sexpr.value(v, "size")),
                       float(sexpr.value(v, "drill")), nets[int(sexpr.value(v, "net"))]))
    for z in sexpr.find_all(e, "zone"):
        layer = sexpr.value(z, "layer")
        pts = [(p[1] - x0, p[2] - y0) for p in sexpr.find_all(sexpr.find(sexpr.find(z, "polygon"), "pts"), "xy")]
        filled = []
        for fpoly in sexpr.find_all(z, "filled_polygon"):
            filled.append([(p[1] - x0, p[2] - y0) for p in sexpr.find_all(sexpr.find(fpoly, "pts"), "xy")])
        b.zones.append({"layer": str(layer), "net": str(sexpr.value(z, "net_name")), "pts": pts,
                        "priority": sexpr.value(z, "priority", 0), "filled": filled})
    return b
