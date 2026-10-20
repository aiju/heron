"""Chibi Heron's board placed on RFC 0046's column grid (studies/pcb_columns).

The two-halves machine's netlist (board2.build(sim=True), without the
simulation's fixtures and its own interrupt button) becomes a board's
parts, each in its package; the chips, the resistor networks and the
jumper blocks go on the grid, the connectors, switches and the logic
analyser's headers along the edges as exceptions (C11), and the grid's
placer anneals the rest. It places only: nothing is routed. The board's
size is open, so `sweep()` tries a few.

- **Packages,** as RFC 0047 has them: the ATF22V10C-5s in PLCC-28
  sockets (the 5 ns part isn't made in DIP), the flashes in PLCC-32
  sockets, the RAM's AS7C4096As in SOJ-36, the register file's
  IS61C6416s in SOJ-44, everything else in DIP from
  its pin count (infra/pcb/packages.py where it knows the type), the
  resistor networks in DIP-16 (eight resistors) or SIP-9 (pull-ups).
  A type nobody has given a package gets a DIP of its pins plus two, its
  pins in order but for the middle and the last (GND, VCC).
- **The edges:** the connectors to the outside (power, VGA, the PS/2 and
  serial ports, the TTL serial headers, the CF card) along the top edge,
  facing out, and on along the right edge when the top is full; the
  logic analyser's headers and the switches along the bottom, then the
  left. PS/2 and the power jack aren't in the netlist yet, and its VGA
  connector is a four-pin stand-in: they are added here on its nets. The
  cells under them are blocked.
- **Not modelled:** the MAX232s' pump capacitors, the TL7705A's two
  capacitors, the bulk capacitors. The oscillators and the TL7705A are
  DIP-8s.
"""

import json
import os

from heron import ROOT
from heron.infra.pcb import board as B
from heron.infra.pcb import kicadlib, packages, sexpr
from heron.studies.pcb_columns import demo, footprints
from heron.studies.pcb_columns.grid import Params, dip_footprint
from heron.studies.pcb_columns.placer import GridPlacer, place_decaps

from . import parts as P

OUT = os.path.join(ROOT, "build", "chibi", "place")
REPORT = os.path.join(ROOT, "reports", "0047-rfc-chibi-heron")

DIP = "Package_DIP:DIP-{n}_W{w}mm"
PLCC28 = "Package_LCC:PLCC-28_THT-Socket"
PLCC32 = "Package_LCC:PLCC-32_THT-Socket"
SOJ36 = "Package_SO:SOJ-36_10.16x23.495mm_P1.27mm"
SOJ44 = "Package_SO:SOJ-44_10.16x28.575mm_P1.27mm"
HDR = "Connector_PinHeader_2.54mm:PinHeader_{r}x{n:02d}_P2.54mm_Vertical"
DB9 = ("Connector_Dsub:DSUB-9_Pins_Horizontal_P2.77x2.84mm_EdgePinOffset4.94mm_Housed_"
       "MountingHolesOffset4.94mm")
VGA = ("Connector_Dsub:DSUB-15-HD_Socket_Horizontal_P2.29x1.90mm_EdgePinOffset3.03mm_Housed_"
       "MountingHolesOffset4.94mm")
CF = "Connector_Card:CF-Card_3M_N7E50-A516xx-30"
JACK = "Connector_BarrelJack:BarrelJack_CUI_PJ-063AH_Horizontal"
BUTTON = "Button_Switch_THT:SW_PUSH_6mm"
HOLE = "MountingHole:MountingHole_3.2mm_M3"
CAP = "Capacitor_SMD:C_0805_2012Metric"
EXTRA = [PLCC28, SOJ44, CF, DB9, VGA, JACK, BUTTON, HOLE] + \
    [HDR.format(r=r, n=n) for r, n in ((1, 6), (2, 4), (2, 16))]

EDGE_MARGIN = 3.0       # mm from the board's edge to the grid's region
CORNER = 9.0            # mm along an edge kept for the corner's mounting hole
EDGE_GAP = 2.0          # mm between two parts' courtyards along an edge
# The stacks' annealing charges a row past the grid's bottom as this much
# wire (mm). The placer's 100 is less than moving one chip nearer the
# buses saves on this board (about 50 m of wire, 107 boxes): the stacks end
# past the bottom at 290 x 290 mm, 78% of the grid. 10 m keeps them in.
OVER_COST = 10000.0

# ---- packages and pins ------------------------------------------------------------

# the PLCC-28's pins 1, 8, 15 and 22 are NC; the others are the DIP-24's in order
_PLCC28 = [k for k in range(1, 29) if k % 7 != 1]

PINOUTS = {
    # MAX232 (TI SLLS047): the pump's capacitors' pins have no net here
    "max232": "NC NC NC NC NC NC T2OUT R2IN R2OUT T2IN T1IN R1OUT R1IN T1OUT GND VCC",
    # the centre-power pinout of 512K x 8 SRAMs in SOJ-36 (AS7C4096A, CY7C1049)
    "sram512": ("A0 A1 A2 A3 A4 CE IO0 IO1 VCC GND IO2 IO3 WE A5 A6 A7 A8 A9 A10 A11 A12 "
                "A13 A14 IO4 IO5 GND VCC IO6 IO7 OE A15 A16 A17 A18 NC NC"),
    "16c550x": " ".join(packages.PINOUTS["16c550"]),
    # 64K x 16 SRAMs in SOJ-44 (IS61C6416, CY7C1021): the netlist's two
    # bytes (sram64k), byte 0's pins IOn, byte 1's IOn' (merged here)
    "sram64k": ("A4 A3 A2 A1 A0 CE IO0 IO1 IO2 IO3 VCC GND IO4 IO5 IO6 IO7 WE A15 A14 A13 A12 "
                "NC NC A11 A10 A9 A8 NC IO0' IO1' IO2' IO3' GND VCC IO4' IO5' IO6' IO7' =GND "
                "=GND OE A7 A6 A5"),
    # DAC0832 (DIP-20): the netlist's two latches, the input latch's pins
    # and the DAC latch's primed; in voltage mode, the output at VREF
    # (VOUT), the reference in at IOUT1 (VREFIN)
    "dac0832in": ("EN CLK GND D4 D3 D2 D1 VOUT' NC GND VREFIN' =GND D8 D7 D6 D5 =GND CLK' "
                  "=VCC VCC"),
    "mcp6002": "REF REF DIV GND IN OUT OUT VCC",
}
PINOUTS = {k: v.split() for k, v in PINOUTS.items()}


def chip_package(inst, gals="plcc"):
    """(footprint, {pad: logical pin or VCC/GND/NC}, whether the infra
    pinout's numbers hold) for a part on the grid. gals="dip": the 22V10s
    in DIP-24 (the -7 part), for comparison."""
    t = inst.type
    name = t.name
    if name == "22v10" and gals == "plcc":
        dip = packages.pad_map("22v10", "dip")
        return PLCC28, {str(_PLCC28[int(k) - 1]): v for k, v in dip.items()}, False
    if name in ("flash", "flash4"):
        return PLCC32, packages.pad_map(name, "dip"), True
    if name == "sram512":
        return SOJ36, _numbered(PINOUTS[name]), False
    if name == "sram64k":
        return SOJ44, _numbered(PINOUTS[name]), False
    if name == "rser8":
        return DIP.format(n=16, w="7.62"), {**{str(i + 1): f"A{i}" for i in range(8)},
                                            **{str(16 - i): f"B{i}" for i in range(8)}}, False
    if name == "jmp4":
        return HDR.format(r=2, n=4), {**{str(2 * i + 1): f"A{i}" for i in range(4)},
                                      **{str(2 * i + 2): f"B{i}" for i in range(4)}}, False
    if name in PINOUTS:
        pins = PINOUTS[name]
        return DIP.format(n=len(pins), w="15.24" if len(pins) > 28 else "7.62"), \
            _numbered(pins), False
    if name in packages.DIP_PACKAGE:
        return packages.footprint_for(name, "dip"), packages.pad_map(name, "dip"), True
    # no pinout: a DIP of its pins and the supplies, its pins in order
    logical = list(t.pins)
    n, w = WIDTHS.get(name, (None, None))
    n = n or max(8, len(logical) + 2 + (len(logical) % 2))
    order = [k for k in range(1, n) if k != n // 2]
    pads = {str(k): pin for k, pin in zip(order, logical)}
    pads.update({str(n // 2): "GND", str(n): "VCC"})
    return DIP.format(n=n, w=w or ("15.24" if n > 28 else "7.62")), pads, False


# the packages of types without a pinout here where the pin count doesn't
# say: (pins, row spacing in mm)
WIDTHS = {"g171": (28, "15.24")}          # IMS G171 (UM70C171): a 0.6 inch DIP-28


def _numbered(pins):
    return {str(i): p for i, p in enumerate(pins, 1)}


def _pin_name(p):
    return p if isinstance(p, str) else p[0]


def _nets(inst, padmap, other=None):
    """The pads' nets; `other`: a 16-bit part's second byte (its pins primed)."""
    out = {}
    for pad, name in padmap.items():
        name = _pin_name(name)
        if name.endswith("'"):
            if other is not None and name[:-1] in other.conn:
                out[pad] = other.conn[name[:-1]]
            continue
        if name in ("VCC", "GND"):
            out[pad] = name
        elif name.startswith("=") and name[1:] in ("VCC", "GND"):
            out[pad] = name[1:]
        elif name in inst.conn:
            out[pad] = inst.conn[name]
    return out


# ---- the edges -----------------------------------------------------------------------

# the CompactFlash socket's pins (CF+ and CompactFlash specification 4.1, True IDE)
CF_PINS = {1: "GND", 2: "D3", 3: "D4", 4: "D5", 5: "D6", 6: "D7", 7: "CS0", 13: "VCC",
           18: "A2", 19: "A1", 20: "A0", 21: "D0", 22: "D1", 23: "D2", 27: "D11", 28: "D12",
           29: "D13", 30: "D14", 31: "D15", 32: "CS1", 34: "IORD", 35: "IOWR", 36: "WAKE",
           37: "INTRQ", 38: "VCC", 41: "RESET", 47: "D8", 48: "D9", 49: "D10", 50: "GND"}
FTDI = {1: "GND", 2: "CTS", 3: "VCC", 4: "TXD", 5: "RXD", 6: "RTS"}
DE9 = {3: "P0", 7: "P1", 2: "P2", 8: "P3", 5: "GND"}             # TXD RTS RXD CTS, as a DTE


def mini_din6():
    """A stand-in for a PS/2 socket (KiCad's library has none): a 6-pin
    mini-DIN of a CUI MD-60S's size, 14 x 13 mm, its mating face +y."""
    pads = [(1, -1.3, 8.5), (2, 1.3, 8.5), (3, -3.5, 8.5), (4, 3.5, 8.5), (5, -3.5, 5.8),
            (6, 3.5, 5.8)]
    text = "(footprint \"MiniDIN-6_standin\" " + " ".join(
        f'(pad "{n}" thru_hole circle (at {x} {y}) (size 1.6 1.6) (drill 0.9) '
        f'(layers "*.Cu" "*.Mask"))' for n, x, y in pads) + \
        ' (pad "S" thru_hole circle (at -6.75 3.8) (size 3 3) (drill 2.2) (layers "*.Cu" "*.Mask"))' \
        ' (pad "S" thru_hole circle (at 6.75 3.8) (size 3 3) (drill 2.2) (layers "*.Cu" "*.Mask"))' \
        ' (fp_rect (start -7 -1) (end 7 12) (layer "F.Fab"))' \
        ' (fp_rect (start -7.25 -1.25) (end 7.25 12.25) (layer "F.CrtYd")))'
    return kicadlib.Footprint("chibi:MiniDIN-6_standin", sexpr.parse(text))


def edge_parts(inst):
    """[(group, Part)] for an instance that goes on an edge, or None:
    "back" for the connectors to the outside, "front" for the debugging
    ones."""
    t, ref, c = inst.type.name, inst.ref, inst.conn
    val = inst.part_number(P.VARIANT)

    def part(r, fp, pins, value=val):
        nets = {str(k): (v if v in ("VCC", "GND") else c.get(v)) for k, v in pins.items()}
        return B.Part(r, fp, {k: v for k, v in nets.items() if v}, value=value, kind="conn",
                      section=inst.section)
    if t == "cf":
        return [("back", part(ref, CF, CF_PINS))]
    if t == "ftdi6":
        return [("back", part(ref, HDR.format(r=1, n=6), FTDI))]
    if t == "hdr32":
        pins = {2 * i + 1: f"S{i}" for i in range(16)}
        pins.update({2 * i + 2: "GND" for i in range(16)})
        return [("front", part(ref, HDR.format(r=2, n=16), pins))]
    if t == "conn" and val.startswith("DE-9"):
        return [("back", part(ref, DB9, DE9))]
    if t == "conn" and val.startswith("DE-15"):
        return []              # a four-pin stand-in: extra_connectors' J_VGA, on its nets
    if t == "conn":            # switches and buttons: a 6 mm button for each contact
        return [("front", part(f"{ref}.{i}", BUTTON, {1: p, 2: "GND"}, value="button"))
                for i, p in enumerate(sorted(c))]
    return None


def extra_connectors(nets):
    """The connectors the netlist doesn't have yet, on its nets: VGA (the
    netlist's J_VGA is a four-pin stand-in, without VSYNC), the two PS/2
    sockets, the power jack. [(group, Part)]."""
    out = []
    if "VGA_R" in nets:
        pins = {1: "VGA_R", 2: "VGA_G", 3: "VGA_B", 13: "HS_n", 14: "VS_n",
                **{k: "GND" for k in (5, 6, 7, 8, 10)}}
        out.append(B.Part("J_VGA", VGA, {str(k): v for k, v in pins.items() if v in nets or
                                         v == "GND"}, value="DE-15 HD female", kind="conn"))
    for ref, clk, dat in (("J_KBD", "KCLK", "KDATA"), ("J_MOUSE", "MSCLK", "MSDATA")):
        if clk in nets:
            out.append(B.Part(ref, mini_din6(), {"1": dat, "3": "GND", "4": "VCC", "5": clk},
                              value="PS/2", kind="conn"))
    out.append(B.Part("J_PWR", JACK, {"1": "VCC", "2": "GND"}, value="5 V", kind="conn"))
    return [("back", p) for p in out]


def _facing(part, outward):
    """The rotation that turns a part's mating side (where its courtyard
    reaches furthest past its pads) towards `outward` (dx, dy), or for a
    part without one, its long side along the edge."""
    best = None
    for rot in (0, 90, 180, 270):
        part.place(0, 0, rot)
        pads = part.pads()
        px = sum(d.x for d in pads) / len(pads)
        py = sum(d.y for d in pads) / len(pads)
        x0, y0, x1, y1 = part.courtyard()
        dx, dy = outward
        if dx:
            out_, in_ = (x1 - px, px - x0) if dx > 0 else (px - x0, x1 - px)
            along = y1 - y0
        else:
            out_, in_ = (y1 - py, py - y0) if dy > 0 else (py - y0, y1 - py)
            along = x1 - x0
        key = (round(out_ - in_) if abs(out_ - in_) > 1.0 else 0, along, -rot)
        if best is None or key > best[0]:
            best = (key, rot)
    return best[1]


class NoRoom(ValueError):
    """The edges can't hold the edge parts."""


def place_edges(b, items):
    """Put the edge parts along the board's edges, in order: "back" along
    the top from the left, then down the right edge; "front" along the
    bottom from the left, then up the left edge. Courtyards flush with the
    edge, EDGE_GAP apart."""
    W, H = b.width, b.height
    edges = {"back": [("top", (0, -1)), ("right", (1, 0))],
             "front": [("bottom", (0, 1)), ("left", (-1, 0))]}
    for group, route in edges.items():
        parts = [p for g, p in items if g == group]
        k = 0
        cur = CORNER
        deep = 0.0
        for p in parts:
            while True:
                if k == len(route):
                    raise NoRoom(f"{p.ref}: no room left on the board's edges")
                name, out = route[k]
                p.place(0, 0, _facing(p, out))
                x0, y0, x1, y1 = p.courtyard()
                w, h = x1 - x0, y1 - y0
                along = w if name in ("top", "bottom") else h
                limit = (W if name in ("top", "bottom") else H) - CORNER
                if cur + along <= limit:
                    break
                k += 1
                cur = deep + EDGE_GAP if k < len(route) else 0
            if name == "top":
                p.place(p.x + cur - x0, p.y - y0, p.rot)
                deep = max(deep, h)
            elif name == "bottom":
                p.place(p.x + cur - x0, p.y + H - y1, p.rot)
                deep = max(deep, h)
            elif name == "right":
                p.place(p.x + W - x1, p.y + cur - y0, p.rot)
            else:
                p.place(p.x - x0, p.y + H - cur - y1, p.rot)
            cur += along + EDGE_GAP
            p.fixed = True
            b.add(p)


# ---- the board -----------------------------------------------------------------------

_NL = {}


# parts the netlist has as two halves (per_package 2), placed as one
MERGED = ("sram64k", "dac0832in", "dac0832out")
SIM_ONLY = ("S_BTNX",)          # the simulation's interrupt button (S_BTN on the board)


def netlist():
    if "nl" not in _NL:
        from . import board2
        _NL["nl"] = board2.build(sim=True)
    return _NL["nl"]


def build_board(size, params=Params(), name=None, gals="plcc"):
    """The board, size = (width, height) mm, with its parts: the edge parts
    and the mounting holes placed, the grid's parts not yet. Raises NoRoom
    where the edges can't hold the edge parts."""
    footprints.use(EXTRA)
    nl = netlist()
    W, H = size
    b = B.Board(name or f"chibi-{W:g}x{H:g}" + ("-dip" if gals == "dip" else ""), W, H, layers=4)
    edge = []
    for inst in nl.instances:
        if inst.type.family == "fixture" or inst.ref in SIM_ONLY:
            continue
        e = edge_parts(inst)
        if e is not None:
            edge += e
            continue
        other = None
        if inst.type.per_package == 2 and inst.type.name in MERGED:
            if not inst.ref.endswith("0"):
                continue                    # the second half: with the first
            other = next(i for i in nl.instances if i.ref == inst.ref[:-1] + "1")
        fp, padmap, infra_pins = chip_package(inst, gals)
        if fp.startswith("Package_DIP:"):
            fp = dip_footprint(fp, params.pads)
        part = B.Part(inst.ref, fp, _nets(inst, padmap, other), value=inst.part_number(P.VARIANT),
                      kind="chip", inst=inst.ref, section=inst.section,
                      typ=inst.type.name if infra_pins else None)
        b.add(part)
        if inst.type.family != "passive":
            b.add(B.Part(f"C{inst.ref}", CAP, {"1": "VCC", "2": "GND"}, value="100n",
                         kind="decap", section=inst.section))
    nets = {n for i in nl.instances for n in i.conn.values()}
    place_edges(b, edge + extra_connectors(nets))
    for i, (x, y) in enumerate(((4, 4), (W - 4, 4), (4, H - 4), (W - 4, H - 4))):
        h = B.Part(f"H{i + 1}", HOLE, {}, value="M3", kind="mech")
        h.place(x, y, 0)
        h.fixed = True
        b.add(h)
    b.region = (EDGE_MARGIN, EDGE_MARGIN, W - EDGE_MARGIN, H - EDGE_MARGIN)
    return b


def place(size, params=Params(), seed=1, moves=60000, name=None, gals="plcc"):
    """Place the board: (board, placer, chips left over)."""
    b = build_board(size, params, name, gals)
    pl = GridPlacer(b, b.region, params, seed=seed)
    pl.over_cost = OVER_COST
    left = pl.run(moves)
    if not left:
        place_decaps(b)
    return b, pl, left


def fits(size, params=Params(), gals="plcc"):
    """(whether every box finds a place, without annealing; the share of
    the grid's free cells the boxes need, None where the edges can't hold
    the connectors)."""
    try:
        b = build_board(size, params, gals=gals)
    except NoRoom:
        return False, None
    pl = GridPlacer(b, b.region, params)
    if pl.demand() > 1:
        return False, pl.demand()
    return (not pl.legalize(pl.targets()) or not pl.pack()), pl.demand()


def least(ratio, use=0.8, params=Params(), gals="plcc", step=5.0, lo=150.0, hi=600.0):
    """The least board of width / height `ratio`, its width in steps of
    `step` mm, whose boxes take at most `use` of the grid's free cells and
    all find a place: (width, height) or None."""
    w = lo
    while w <= hi:
        size = (w, round(w / ratio / step) * step)
        try:
            b = build_board(size, params, gals=gals)
        except NoRoom:
            w += step
            continue
        if GridPlacer(b, b.region, params).demand() <= use and fits(size, params, gals)[0]:
            return size
        w += step
    return None


# ---- the sweep and its report ----------------------------------------------------------

STANDARD = [("Eurocard", (160.0, 100.0)), ("double Eurocard", (233.35, 160.0)),
            ("", (250.0, 200.0)), ("A4", (297.0, 210.0)), ("ATX", (305.0, 244.0))]
RATIOS = [("square", 1.0), ("4:3", 4 / 3), ("3:4", 3 / 4), ("3:2", 1.5)]
USE = 0.8


def _row(label, size, gals, b=None, pl=None, left=(), demand=None):
    r = {"label": label, "size": list(size), "gals": gals, "fits": pl is not None and not left,
         "demand": demand}
    if pl is not None:
        r.update({"chips": len(pl.chips), "demand": round(pl.demand(), 3),
                  "grid": {"columns": pl.lat.cols, "rows": pl.lat.rows,
                           "blocked_cells": len(pl.blocked)}})
    if r["fits"]:
        r.update(demo.summary(b, pl, list(left)))
    return r


def sweep(moves=60000, seed=1, quiet=False):
    """Every size tried: the standard ones, then the least of each shape
    at USE of the grid, and the least 4:3 with the 22V10s in DIP. Returns
    (rows, {label: (board, placer)} of those placed)."""
    rows, placed = [], {}

    def say(r):
        if not quiet:
            print(f"{r['label']}: " + (f"{r['used']:.0%} of the grid, {r['wire_mm'] / 1000:.1f} m"
                                       if r["fits"] else "doesn't fit"), flush=True)

    def run(label, size, gals):
        try:
            b, pl, left = place(size, seed=seed, moves=moves, gals=gals)
        except RuntimeError:            # the annealing left a stack past the grid's bottom
            b = build_board(size, gals=gals)
            pl, left = GridPlacer(b, b.region, Params()), ["all"]
        rows.append(_row(label, size, gals, b, pl, left))
        if not left:
            placed[label] = (b, pl)
        say(rows[-1])
    for name, size in STANDARD:
        label = f"{name} {size[0]:g} × {size[1]:g}".strip()
        ok, need = fits(size)
        if ok:
            run(label, size, "plcc")
            continue
        try:
            b = build_board(size)
            rows.append(_row(label, size, "plcc", b, GridPlacer(b, b.region, Params()), ["all"]))
        except NoRoom:
            rows.append(_row(label, size, "plcc"))
        say(rows[-1])
    for gals, shapes in (("plcc", RATIOS), ("dip", RATIOS[1:2])):
        for name, ratio in shapes:
            size = least(ratio, USE, gals=gals)
            if size is not None:
                run(f"least {name}{', 22V10s in DIP' if gals == 'dip' else ''}, "
                    f"{size[0]:g} × {size[1]:g}", size, gals)
    return rows, placed


def best(rows):
    """The recommended size: the least area among those placed without a
    problem, at USE of the grid or less, with the 22V10s in PLCC."""
    ok = [r for r in rows if r["fits"] and r["gals"] == "plcc" and not r["problems"]
          and r["used"] <= USE + 1e-9]
    return min(ok, key=lambda r: (r["size"][0] * r["size"][1], r["wire_mm"])) if ok else None


def markdown(rows, pick):
    from collections import Counter
    nl = netlist()
    n = sum(1 for i in nl.instances if i.type.family != "fixture" and i.ref not in SIM_ONLY)
    lines = [
        "# Chibi Heron placed on the column grid",
        "",
        "Generated by `heron chibi place --write` ([studies/chibi](../../studies/chibi/README.md)"
        "); don't edit by hand. The placement is [RFC 0046](../0046-rfc-column-grid.md)'s "
        "([studies/pcb_columns](../../studies/pcb_columns/README.md)) with its defaults: "
        "half-columns of 0.5 inch, a gap of 2 rows, module 1, round pads, 60,000 moves of the "
        "stacks' annealing. Nothing is routed.",
        "",
        f"The two-halves machine's netlist's {n} parts: the chips, resistor networks and jumper "
        "blocks on the "
        "grid in RFC 0047's packages (the 22V10s and the flashes in PLCC sockets, the RAM in "
        "SOJ-36, the register file in SOJ-44, the rest in DIP), the connectors, switches and "
        "the logic analyser's headers "
        "along the edges as exceptions, the cells under them blocked. The PS/2 sockets and the "
        "power jack aren't in the netlist yet, and its VGA connector is a four-pin stand-in; "
        "they are added on its nets. The board's size "
        f"is open: the standard sizes, then for each shape the least board, in steps of 5 mm, "
        f"whose boxes take at most {USE:.0%} of the grid's free cells.",
        "",
        "| Board (mm) | Grid | Cells blocked | On the grid | Grid used | Wire | Holes "
        "| Least pad gap |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        if "grid" not in r:
            lines.append(f"| {r['label']} | | | | the connectors don't fit its edges | | | |")
            continue
        g = r["grid"]
        head = (f"| {r['label']} | {g['columns']} columns × {g['rows']} rows | "
                f"{g['blocked_cells']} | {r['chips']} | ")
        if not r["fits"]:
            why = "doesn't fit" if r["demand"] > 1 else "the annealing doesn't fit it"
            lines.append(head + f"{why}: needs {r['demand']:.0%} | | | |")
        else:
            lines.append(head + f"{r['used']:.0%} | {r['wire_mm'] / 1000:.1f} m | {r['holes']} "
                         f"| {r['least_pad_gap']:.2f} mm |")
    lines += ["", "Grid used: the boxes' cells over the grid's cells not under an exception. "
              "Wire: the signal nets' half-perimeter length at the pads, from the annealing's "
              "first seed. Holes: free cells with a box below them in their half-column. Least "
              "pad gap: between two chips' pads, edge to edge.", ""]
    std = [r for r in rows if r["fits"] and not r["label"].startswith("least")]
    if std:
        lines += ["Of the standard sizes, " + ", ".join(
            f"{r['label']} holds it at {r['used']:.0%} of its grid" for r in std) + "."]
    dip = next((r for r in rows if r["fits"] and r["gals"] == "dip"), None)
    same = next((r for r in rows if r["fits"] and r["gals"] == "plcc" and dip
                 and r["label"].startswith(dip["label"].split(",")[0] + ",")), None)
    if dip and same:
        a, b = (r["size"][0] * r["size"][1] for r in (dip, same))
        lines += [f"With the 22V10s in DIP-24 (0.3 inch, as the -7 part comes; RFC 0047 has "
                  f"the -5 in PLCC) the least board of the same shape is {dip['size'][0]:g} × "
                  f"{dip['size'][1]:g} mm, against {same['size'][0]:g} × {same['size'][1]:g} in "
                  f"PLCC-28 sockets: {1 - a / b:.0%} less area."]
    lines += [""]
    if not pick:
        return "\n".join(lines)
    lines += [f"## The least: {pick['size'][0]:g} × {pick['size'][1]:g} mm", "",
              f"![Chibi Heron on {pick['size'][0]:g} × {pick['size'][1]:g} mm with RFC 0046's "
              "defaults: each part in its box (orange: a 0.6 inch DIP across a column; blue: a "
              "0.3 inch DIP in a half-column; green: the PLCC sockets, the SOJs, the resistor "
              "networks' SIPs and the jumper blocks), the connectors along the top edge, the logic "
              "analyser's headers and the switches along the bottom](placement.svg)", "",
              f"The least area among the boards at {USE:.0%} of the grid or less: {pick['chips']} "
              f"parts on a grid of {pick['grid']['columns']} columns × {pick['grid']['rows']} "
              f"rows, {pick['used']:.0%} of it, {pick['wire_mm'] / 1000:.1f} m of wire, "
              f"{len(pick['problems'])} problems in RFC 0046's checks.", "",
              "| Package | Box (half-columns × rows) | Parts | Cells |", "|---|---|---:|---:|"]
    boxes = Counter()
    for x in pick["boxes"]:
        boxes[(x["footprint"], x["half_columns"], x["rows"])] += x["count"]
    cells = sum(w * h * k for (_, w, h), k in boxes.items())
    for (fp, w, h), k in sorted(boxes.items(), key=lambda kv: -kv[0][1] * kv[0][2] * kv[1]):
        lines.append(f"| {fp} | {w} × {h} | {k} | {w * h * k} |")
    gal = sum(w * h * k for (fp, w, h), k in boxes.items() if fp == PLCC28.split(":")[1])
    lines += [f"| **total** | | {sum(boxes.values())} | {cells} |", "",
              f"The 22V10s' PLCC-28 sockets take {gal} of the {cells} cells ({gal / cells:.0%}): "
              "a socket's courtyard, 19 mm square, is wider than a half-column, so each takes a "
              "column (C4), 18 cells where a DIP-24 takes 13.", ""]
    return "\n".join(lines)


def cmd_place(args):
    from heron.studies.pcb_columns import draw
    rows, placed = sweep(moves=args.moves, seed=args.seed)
    pick = best(rows)
    os.makedirs(OUT, exist_ok=True)
    for b, pl in placed.values():
        draw.svg(b, pl, os.path.join(OUT, f"{b.name}.svg"), scale=4.0)
    with open(os.path.join(OUT, "sweep.json"), "w") as f:
        json.dump(rows, f, indent=1)
    md = markdown(rows, pick)
    if args.write:
        os.makedirs(REPORT, exist_ok=True)
        with open(os.path.join(REPORT, "placement.md"), "w") as f:
            f.write(md + "\n")
        if pick:
            b, pl = placed[pick["label"]]
            draw.svg(b, pl, os.path.join(REPORT, "placement.svg"), scale=4.0)
    else:
        print(md)
    print(f"each placement's SVG, and sweep.json, in {os.path.relpath(OUT, ROOT)}/")
    return 0 if pick else 1
