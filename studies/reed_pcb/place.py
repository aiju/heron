"""Reed's boards placed on RFC 0046's column grid (studies/pcb_columns).

A board's netlist (studies/reed, system.board) becomes its parts, each in
the package studies/reed/parts.py gives it (PACKAGES), on a double
Eurocard with RFC 0026's mechanics (studies/pcb's cards.mechanics). The
two DIN 41612 connectors stand at the back edge, the 233.35 mm one, as a
Eurocard has them for a card cage's backplane, off the grid; the grid's
placer anneals the chips. It places only: nothing is routed.

- **Packages** by part number, as parts.PACKAGES names them (FOOTPRINTS
  below). The ATF22V10C-5 is soldered as a PLCC-28 by default, as
  PACKAGES counts its area; `gal_sockets` puts it in a PLCC-28 socket
  instead, which a GAL that may be reprogrammed wants.
- **Pinouts** from infra/pcb/packages.py: a SOIC has its DIP's numbers;
  the 22V10's PLCC-28 is `22v10_plcc`, the AT27C010 `27c010`, the
  IS61C6416 `sram64k16`, whose two bytes the netlist has as two
  instances (U_RFA0 and U_RFA1 are one package, U_RFA01), LB and UB low.
- **Capacitors:** one 0805 under each chip, on the bottom (C12).
- **Not modelled:** bulk capacitors, the supply's entry.
"""

import json
import os
from collections import Counter

from heron import ROOT
from heron.infra.pcb import board as B
from heron.infra.pcb import packages, physical
from heron.studies.pcb import cards
from heron.studies.pcb_columns import demo, footprints
from heron.studies.pcb_columns.grid import Params, dip_footprint
from heron.studies.pcb_columns.placer import GridPlacer, place_decaps

OUT = os.path.join(ROOT, "build", "reed_pcb")
CARD = (160.0, cards.EUROCARD_6U)       # depth across, height down: the connectors on the right

# parts.PACKAGES's package names -> KiCad's footprints
FOOTPRINTS = {
    "SOIC-14": "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm",
    "SOIC-16": "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm",
    "SOIC-20": "Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm",
    "SOIC-24": "Package_SO:SOIC-24W_7.5x15.4mm_P1.27mm",
    "DIP-24": "Package_DIP:DIP-24_W7.62mm",
    "DIP-24W": "Package_DIP:DIP-24_W15.24mm",
    "PLCC-28": "Package_LCC:PLCC-28",
    "PLCC-28 socket": "Package_LCC:PLCC-28_THT-Socket",
    "PLCC-32 socket": "Package_LCC:PLCC-32_THT-Socket",
    "SOJ-36": "Package_SO:SOJ-36_10.16x23.495mm_P1.27mm",
    "SOJ-44": "Package_SO:SOJ-44_10.16x28.575mm_P1.27mm",
}
CAP = "Capacitor_SMD:C_0805_2012Metric"
EXTRA = sorted(set(FOOTPRINTS.values()) - set(footprints.names()))

# pinouts (infra/pcb/packages.py) by part number, where not the chip type's
PINOUT_OF_PART = {"ATF22V10C-5": "22v10_plcc", "AT27C010-45": "27c010",
                  "SST39SF010A-55": "flash", "IS61C6416AL-12": "sram64k16"}
# a type the netlist has as halves of one package: {type: (pins of each
# half that are the package's, by half: {half pin: package pin}), tied pins}
HALVES = {"sram64k": ([{f"IO{i}": f"IO{i}" for i in range(8)},
                       {f"IO{i}": f"IO{i + 8}" for i in range(8)}],
                      {"LB": "GND", "UB": "GND"})}


def netlist(name):
    from heron.studies.reed import system
    return system.board(name, sim=True)


def package(inst, gal_sockets=False):
    """(part number, package name, footprint, pinout key) of a chip."""
    from heron.studies.reed import parts as RP
    part = inst.part_number(RP.VARIANT)
    pkg = RP.PACKAGES[part][0]
    if gal_sockets and pkg == "PLCC-28":
        pkg = "PLCC-28 socket"
    return part, pkg, FOOTPRINTS[pkg], PINOUT_OF_PART.get(part, inst.type.name)


def _pad_nets(pinout, conn, rails):
    """{pad: net} of a package: its logical pins' nets, its supply and tied pins' rails."""
    out = {}
    for n, name in enumerate(packages.PINOUTS[pinout], 1):
        if name in ("VCC", "GND"):
            out[str(n)] = name
        elif name.startswith("=") and name[1:] in ("VCC", "GND"):
            out[str(n)] = name[1:]
        elif name in conn:
            out[str(n)] = rails.get(conn[name], conn[name])
    return out


def _groups(nl):
    """The netlist's chips as packages: [(ref, [instances], conn)], a
    package of halves under its halves' references joined (U_RFA0 and
    U_RFA1: U_RFA01), its conn the package's pins."""
    out = []
    pending = {}
    for inst in nl.instances:
        t = inst.type.name
        if t not in HALVES:
            out.append((inst.ref, [inst], dict(inst.conn)))
            continue
        k = int(inst.ref[-1])
        key = (t, inst.ref[:-1], k // 2)
        pending.setdefault(key, []).append(inst)
        if len(pending[key]) < 2:
            continue
        a, b = sorted(pending.pop(key), key=lambda i: i.ref)
        own, ties = HALVES[t]
        conn = {p: n for p, n in a.conn.items() if p not in own[0]}
        for p, n in b.conn.items():
            if p not in own[1] and conn.get(p) != n:
                raise ValueError(f"{a.ref} and {b.ref}: {p} on {conn.get(p)} and {n}")
        for half, inst2 in zip(own, (a, b)):
            conn.update({half[p]: n for p, n in inst2.conn.items() if p in half})
        conn.update(ties)
        out.append((a.ref + b.ref[-1], [a, b], conn))
    if pending:
        raise ValueError(f"halves without their other half: {sorted(pending)}")
    return out


def connector_part(inst, width, height):
    """A DIN 41612 connector at the back edge, as studies/pcb's cards
    places them on a 6U card: P2's pins' middle 50 mm from the bottom
    edge, P1's 133.35 mm above it, the outer pin row 5.3 mm from the edge,
    the mating face off the edge."""
    name = inst.ref.split("_")[-1]
    yc = height - 50.0 - (133.35 if name == "P1" else 0.0)
    part = B.Part(name, cards.CONNECTOR, {}, value="DIN 41612 C 3x32 male", kind="conn",
                  inst=inst.ref)
    part.place(width - 5.3, yc - 39.37, 270)
    part.fixed = True
    return part


def build_board(name, size=CARD, params=Params(), gal_sockets=False):
    """The board with its parts, the connectors and mechanics in place,
    the chips not yet placed."""
    footprints.use(EXTRA)
    nl = netlist(name)
    rails = physical.rails(nl)
    w, h = size
    tag = ("-sockets" if gal_sockets else "") + ("" if size == CARD else f"-{w:g}x{h:g}")
    b = B.Board(f"{name.lower()}-{params.label()}{tag}", w, h, layers=4)
    b.packages = {}
    for ref, insts, conn in _groups(nl):
        inst = insts[0]
        t = inst.type
        if t.family == "fixture":
            continue
        if t.name == "din96":
            p = connector_part(inst, w, h)
            p.nets = {pad: rails.get(net, net) for pad, net in conn.items()}
            b.add(p)
            continue
        part, pkg, fp, pinout = package(inst, gal_sockets)
        if fp.startswith("Package_DIP:"):
            fp = dip_footprint(fp, params.pads)
        b.add(B.Part(ref, fp, _pad_nets(pinout, conn, rails), value=part, kind="chip",
                     inst=inst.ref, section=inst.section))
        b.packages[ref] = (part, pkg)
        b.add(B.Part(f"C{ref}", CAP, {"1": "VCC", "2": "GND"}, value="100n", kind="decap",
                     section=inst.section))
    b.region = cards.mechanics(b)
    return b


# The stacks' annealing charges a row past the grid's bottom as this much
# wire (mm). The placer's 100 is less than a chip nearer the connectors
# saves on a board this full (the ALU: about 37 m of wire, 94% of the
# grid), and two seeds in four ended past the bottom; as studies/chibi
# found, 10 m keeps them in.
OVER_COST = 10000.0


def place(name, size=CARD, params=Params(), seed=1, moves=60000, gal_sockets=False):
    """Place a board: (board, placer, chips left over)."""
    b = build_board(name, size, params, gal_sockets)
    pl = GridPlacer(b, b.region, params, seed=seed)
    pl.over_cost = OVER_COST
    left = pl.run(moves)
    if not left:
        place_decaps(b)
    return b, pl, left


# ---- what a placement measures ---------------------------------------------------------

# report 0044's and RFC 0049's area unit: a DIP-20's slot soldered by hand;
# a double Eurocard holds about 70 (RFC 0049, B1: about 31,000 mm²)
UNIT_MM2 = 31000.0 / 70


def estimate(name):
    """RFC 0049's estimate of a board: (packages, area units)."""
    from heron.studies.reed import system
    s = system.stats()[name]
    return s["packages"], s["area"]


def summary(name, b, pl, left):
    """The placement's numbers: the grid's (demo.summary's) and the area's
    against RFC 0049's estimate."""
    res = demo.summary(b, pl, left)
    pk, units = estimate(name)
    lat = pl.lat
    grid_mm2 = lat.width * lat.height
    x0, y0, x1, y1 = b.region
    taken = sum(pl.boxes[r].w * pl.lat.p.half_mm * pl.boxes[r].h * 2.54 for r in pl.boxes)
    by_pkg = Counter(pkg for _, pkg in b.packages.values())
    cells = Counter()
    for ref, (_, pkg) in b.packages.items():
        bx = pl.boxes[ref]
        cells[pkg] += bx.w * bx.h
    free = lat.halves * lat.rows - len(pl.blocked)
    res["board"] = name
    res["estimate"] = {"packages": pk, "area_units": round(units, 1),
                       "share_of_70": round(units / 70, 3)}
    res["area"] = {
        "region_mm2": round((x1 - x0) * (y1 - y0)),
        "grid_mm2": round(grid_mm2),
        "boxes_mm2": round(taken),
        "boxes_units": round(taken / UNIT_MM2, 1),
        "grid_free_cells": free,
        "rows_free_at_bottom": _free_rows(pl) if not left else None,
    }
    res["by_package"] = {pkg: {"count": n, "cells": cells[pkg],
                               "share": round(cells[pkg] / free, 3)}
                         for pkg, n in sorted(by_pkg.items(), key=lambda kv: -cells[kv[0]])}
    return res


def _free_rows(pl):
    """Each half-column's free rows at its bottom: [n, ...] left to right."""
    out = []
    for hc in range(pl.lat.halves):
        col = pl.occ[hc]
        n = 0
        for o in reversed(col):
            if o is None:
                n += 1
            else:
                break
        out.append(n)
    return out


def build(name, size=CARD, params=Params(), seed=1, moves=60000, gal_sockets=False,
          kicad=True):
    """Place a board and write it to build/reed_pcb/<name>/: result.json,
    board.svg and board.kicad_pcb."""
    return write(name, *place(name, size, params, seed, moves, gal_sockets), kicad=kicad)


def write(name, b, pl, left, kicad=True):
    """Write a placement to build/reed_pcb/<board's name>/: (board, placer,
    its numbers)."""
    from heron.studies.pcb_columns import draw
    d = os.path.join(OUT, b.name)
    os.makedirs(d, exist_ok=True)
    res = summary(name, b, pl, left)
    if not left:
        draw.svg(b, pl, os.path.join(d, "board.svg"))
        if kicad:
            b.write(os.path.join(d, "board.kicad_pcb"))
    with open(os.path.join(d, "result.json"), "w") as f:
        json.dump(res, f, indent=1)
    return b, pl, res
