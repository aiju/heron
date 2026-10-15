"""KiCad's libraries: footprints (pads, courtyard) and symbols (pin names
and numbers), read from a KiCad installation.

The footprint directory is $KICAD9_FOOTPRINT_DIR (or KICAD_FOOTPRINT_DIR),
else /usr/share/kicad/footprints; symbols likewise. Nothing here needs
KiCad's own programs.
"""

import math
import os

from . import sexpr

_CACHE = {}


def _dir(kind):
    for var in (f"KICAD9_{kind}_DIR", f"KICAD_{kind}_DIR"):
        if os.environ.get(var):
            return os.environ[var]
    return f"/usr/share/kicad/{kind.lower()}s"


def available():
    return os.path.isdir(_dir("FOOTPRINT")) and os.path.isdir(_dir("SYMBOL"))


class PadDef:
    """A footprint's pad, in footprint coordinates (mm, y down)."""

    def __init__(self, e):
        self.number = str(e[1])
        self.kind = e[2]                       # smd, thru_hole, np_thru_hole
        self.shape = e[3]                      # rect, roundrect, circle, oval
        at = sexpr.find(e, "at")
        self.x, self.y = float(at[1]), float(at[2])
        self.rot = float(at[3]) if len(at) > 3 else 0.0
        size = sexpr.find(e, "size")
        self.w, self.h = float(size[1]), float(size[2])
        drill = sexpr.find(e, "drill")
        self.drill = None
        if drill is not None:
            vals = [v for v in drill[1:] if isinstance(v, (int, float))]
            self.drill = float(vals[0]) if vals else None
        self.layers = [str(l) for l in sexpr.find(e, "layers")[1:]]
        self.rratio = float(sexpr.value(e, "roundrect_rratio", 0.0) or 0.0)
        self.expr = e


class Footprint:
    def __init__(self, libname, expr):
        self.name = libname                    # "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm"
        self.expr = expr
        self.pads = [PadDef(p) for p in sexpr.find_all(expr, "pad")]
        self.smd = all(p.kind == "smd" for p in self.pads if p.number)
        xs, ys = [], []
        for item in expr:
            if isinstance(item, list) and item and item[0] in ("fp_line", "fp_rect", "fp_poly") \
                    and sexpr.value(item, "layer") == "F.CrtYd":
                for key in ("start", "end"):
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
            for p in self.pads:
                xs += [p.x - p.w / 2, p.x + p.w / 2]
                ys += [p.y - p.h / 2, p.y + p.h / 2]
        self.courtyard = (min(xs), min(ys), max(xs), max(ys))

    def pads_by_number(self):
        out = {}
        for p in self.pads:
            out.setdefault(p.number, []).append(p)
        return out


def footprint(libname):
    """The footprint "Library:Name" from the KiCad footprint libraries."""
    if libname not in _CACHE:
        lib, name = libname.split(":", 1)
        path = os.path.join(_dir("FOOTPRINT"), f"{lib}.pretty", f"{name}.kicad_mod")
        _CACHE[libname] = Footprint(libname, sexpr.load(path))
    return _CACHE[libname]


# ---- symbols ----------------------------------------------------------------------

def _symbols(lib):
    key = ("sym", lib)
    if key not in _CACHE:
        e = sexpr.load(os.path.join(_dir("SYMBOL"), f"{lib}.kicad_sym"))
        _CACHE[key] = {s[1]: s for s in sexpr.find_all(e, "symbol")}
    return _CACHE[key]


def symbol_pins(libname):
    """[(number, name, electrical type, unit)] of a symbol "Library:Name";
    unit 0 is the pins every unit shares. Only the normal body style is
    read, not the De Morgan alternative."""
    lib, name = libname.split(":", 1)
    syms = _symbols(lib)
    s = syms[name]
    ext = sexpr.value(s, "extends")
    if ext:
        return symbol_pins(f"{lib}:{ext}")
    out = []
    for sub in sexpr.find_all(s, "symbol"):
        unit, style = (int(v) for v in str(sub[1]).rsplit("_", 2)[-2:])
        if style > 1:
            continue
        for pin in sexpr.find_all(sub, "pin"):
            out.append((str(sexpr.value(pin, "number")), str(sexpr.value(pin, "name")),
                        str(pin[1]), unit))
    return out


def rotate(x, y, deg):
    if not deg:
        return x, y
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    # KiCad: positive angles turn counter-clockwise on screen (y down)
    return x * c + y * s, -x * s + y * c
