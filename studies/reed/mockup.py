"""A 3D mockup of Reed's boards: each board's packages placed in regular
rows on its double Eurocard, with silkscreen, front panels and the
backplane, drawn in the browser with WebGL (three.js).

    layout()        {board: {chips, groups, front, stats}}: every package
                    of the board's netlist placed once, in mm on the board
                    (X along the 233.35 mm edge, Y from the backplane edge
                    to the front panel)
    write(path)     the viewer (mockup.html) with the layout filled in

The placement is by hand, row by row (ROWS), grouped by what the chips do;
there is no routing. Footprint sizes are the packages' bodies with their
leads, from typical JEDEC outlines.
"""

import json
from pathlib import Path

from . import parts, system

BOARD_W, BOARD_H = 233.35, 160.0
# the placement area: card guides at both long edges, the backplane
# connectors at Y=0, the front panel's bracket at the front
X0, X1 = 7.0, 226.35
Y0, Y1 = 14.0, 149.0

# package: (kind, length along the row, width across it, height), in mm
FOOTPRINTS = {
    "SOIC-20": ("soic", 12.8, 10.3, 2.4, 20),
    "SOIC-16": ("soic", 9.9, 6.0, 1.6, 16),
    "SOIC-14": ("soic", 8.65, 6.0, 1.6, 14),
    "SOIC-8": ("soic", 4.9, 6.0, 1.6, 8),
    "DIP-24": ("dip", 31.75, 9.2, 4.2, 24),
    "DIP-24W": ("dipw", 31.75, 16.8, 4.4, 24),
    "PLCC-28": ("plcc", 12.5, 12.5, 4.2, 28),
    "PLCC-44": ("plcc", 17.5, 17.5, 4.2, 44),
    "PLCC-32 socket": ("plccs", 17.3, 14.7, 7.0, 32),
    "SOJ-44": ("soj", 28.6, 11.2, 3.5, 44),
    "SOJ-36": ("soj", 23.5, 11.2, 3.5, 36),
    "SOJ-28": ("soj", 18.4, 8.5, 3.5, 28),
    "LQFP-48 (0.5 mm): open": ("lqfp", 9.0, 9.0, 1.4, 48),
    "DIP-14 can": ("can", 20.8, 13.2, 5.1, 4),
}
EXTRA_PACKAGES = {"74F138": ("SOIC-16", 0.6)}

# each board's rows, from the backplane connectors to the front panel; a
# row is (mode, [(group label, [refs])]): "grid" spreads its chips evenly
# over the board's width, "pack" keeps each group's chips together and
# spreads the groups, "at" starts each group where its third element says;
# "vgrid" is a grid of chips turned across the row
ROWS = {
    "CTRL": [
        ("grid", [("PC ONTO A", ["PCA0", "PCA1", "PCA2", "PCA3"]),
                  ("IMMEDIATE ONTO B", ["FH0", "PL0", "PH0", "FH1", "PL1", "PH1", "S8", "F9"]),
                  ("", ["XL"])]),
        ("grid", [("INSTRUCTION QUEUE  WORDS 0-1",
                   ["QD00", "QE00", "QD01", "QE01", "QD10", "QE10", "QD11", "QE11"]),
                  ("IMM. HALVES", ["H0", "H1"])]),
        ("grid", [("INSTRUCTION QUEUE  WORDS 2-3",
                   ["QD20", "QE20", "QD21", "QE21", "QD30", "QE30", "QD31", "QE31"]),
                  ("INSTRUCTION REGS", ["NOP", "NRB", "OP", "RB"])]),
        ("grid", [("QUEUE CONTROL", ["IQP", "IQE", "IQR", "IQV", "IQO", "IQK"])]),
        ("grid", [("IMMEDIATE", ["IMMG", "IMMO"]), ("PC", ["PCL"]),
                  ("NEXT ADDRESS", ["NA0", "NA1", "NA2"])]),
        ("pack", [("COND", ["COND"]), ("PC 21-3", ["PC0", "PC1", "PC2", "PC3", "PC4"]),
                  ("µPC / MIR", ["UPC0", "UPC1", "MIR3", "MIR4"]), ("CLOCK GEN", ["CGA"])]),
        ("pack", [("CONTROL STORE", ["CS0", "CS1", "CS2", "CS3", "CS4"]),
                  ("DECODE TABLE", ["DT0", "DT1"])]),
        ("pack", [("CLOCKS  50.35 MHz", ["OSC", "INV", "CKM", "CKN", "CKC", "CK"])]),
    ],
    "ALU": [
        ("grid", [("A BUS IN", ["XA0", "XA1", "XA2", "XA3"]), ("B BUS IN", ["XB0", "XB1", "XB2", "XB3"]),
                  ("F ONTO A", ["FA0", "FA1", "FA2", "FA3"])]),
        ("grid", [("SHIFTER", ["SH0", "SH1", "SH2", "SH3"]), ("RESULT Y_A", ["YA0", "YA1", "YA2", "YA3"]),
                  ("RESULT Y_B", ["YB0", "YB1", "YB2", "YB3"])]),
        ("vgrid", [("ALU  8 x 74F181", [f"ALU{i}" for i in range(8)]),
                   ("CARRY / FUNCTION", ["CLA", "ALUF"])]),
        ("grid", [("FLAGS", ["ZL", "ZH", "FLA", "FLB"]), ("BUS", ["BUS"]), ("WRITE", ["WG"])]),
        ("pack", [("REGISTER FILE  COPY A", ["RFA01", "RFA23"]), ("COPY B", ["RFB01", "RFB23"]),
                  ("ADDRESS / BYPASS", ["RAG0", "RAG1", "RBG0", "RBG1"])]),
        ("pack", [("READ LATCHES A", ["LA0", "LA1", "LA2", "LA3"]), ("READ LATCHES B", ["LB0", "LB1", "LB2", "LB3"]),
                  ("BYPASS", ["BYP", "RFT"])]),
        ("pack", [("CONTROL STORE", ["CS0", "CS1", "CS2", "CS3"]), ("MIR", ["MIR0", "MIR1", "MIR2", "MIR3"]),
                  ("µPC", ["UPC0", "UPC1"]), ("CLK", ["CK"])]),
    ],
    "MEM": [
        ("grid", [("A BUS IN", ["AR0", "AR1", "AR2", "AR3"]), ("LOADS ONTO B", ["MX0", "MX1", "MX2", "MX3"]),
                  ("MQ", ["MQ0", "MQ1", "MQ2", "MQ3"])]),
        ("grid", [("STORE LANES", ["ST00", "ST11", "ST10", "ST22", "ST20", "ST33", "ST31", "ST30"]),
                  ("FPC ONTO RA", ["FPA0", "FPA1", "FPA2"])]),
        ("grid", [("BYTE CROSSBAR  16 x 74F153", ["XB00", "XB01", "XB02", "XB03", "XB10", "XB11", "XB12", "XB13",
                                                  "XB20", "XB21", "XB22", "XB23", "XB30", "XB31", "XB32", "XB33"])]),
        ("grid", [("RAM  4 MB  ROW 0", ["RAM00", "RAM01", "RAM02", "RAM03"]),
                  ("ROW 1", ["RAM10", "RAM11", "RAM12", "RAM13"])]),
        ("pack", [("MAR", ["MAR0", "MAR1", "MAR2"]), ("FPC", ["FPC0", "FPC1", "FPC2", "FPC3", "FPC4"])]),
        ("grid", [("LANES / STROBES", ["LN0", "LN1", "ST", "WE"]), ("CONTROL", ["MC"])]),
        ("pack", [("CONTROL STORE", ["CS0"]), ("µPC / MIR", ["UPC0", "UPC1", "MIR0"]), ("CLK", ["CK"])]),
    ],
    "IO": [
        ("pack", [("A BUS IN", ["DW0", "DW1"]), ("ONTO B", ["DR0", "DR1", "DZ0", "DZ1"]),
                  ("I/O ADDRESS", ["IA0", "IA1", "IA2"]), ("CLK", ["CK"])]),
        ("pack", [("DECODE / STROBES", ["IOD", "IOT", "IOB"]), ("INTERRUPTS", ["IRQ"]),
                  ("RESET", ["POR"])]),
        ("pack", [("BOOT", ["BOOT"]), ("TIMER", ["TMR"]), ("PS/2", ["KBD", "MSE", "PSO"]),
                  ("1.8432 MHz", ["UCLK"])]),
        # under their connectors on the front edge
        ("at", [("PS/2", ["KBDSR", "MSESR", "PSS"], 72.0), ("AUDIO", ["DAC", "AMP"], 116.0),
                ("UART 0", ["UART0", "RS0"], 140.0), ("UART 1", ["UART1", "RS1"], 176.0)]),
    ],
    "VIDEO": [
        ("grid", [("CPU WRITE DATA", ["VD0", "VD1", "VD2", "VD3"]), ("CPU READ DATA", ["VR0", "VR1", "VR2", "VR3"]),
                  ("CPU ADDRESS", ["VA0", "VA1", "VA2"])]),
        ("grid", [("DECODE / ARBITER", ["VDEC", "VAR1", "VAR2"]), ("TIMING", ["VT1", "VT2"]),
                  ("PALETTE", ["PALC"])]),
        ("pack", [("FRAME BUFFER  2 MB", ["FB0", "FB1", "FB2", "FB3"]), ("SCAN ADDR", ["SAD0", "SAD1", "SAD2"])]),
        ("pack", [("SCAN ADDRESS", ["SA0", "SA1", "SA2", "SA3", "SA4"]),
                  ("H / V COUNTERS", ["HC0", "HC1", "HC2", "VC0", "VC1", "VC2"])]),
        ("pack", [("PIXELS", ["PX0", "PX1", "PX2", "PX3", "PXS", "PIXI"]), ("CLK", ["CKV"])]),
        ("pack", [("PALETTE", ["PAL0", "PAL1", "PAL2"]), ("", ["PALD0", "PALD1", "PALD2"]), ("DAC", ["DAC"])]),
    ],
}

# what's on the front edge, through the front panel: (ref, kind, X centre)
FRONT = {
    "CTRL": [],
    "ALU": [],
    "MEM": [],
    "IO": [("CF", "cf", 44.0), ("PS2K", "ps2k", 84.0), ("PS2M", "ps2m", 100.0), ("AUDIO", "jack", 116.0),
           ("SER0", "de9", 144.0), ("SER1", "de9", 180.0), ("RESET", "button", 210.0)],
    "VIDEO": [("VGA", "de15", 120.0)],
}
# the rows' area ends where the front connectors start
FRONT_DEPTH = {"cf": 38.0, "de9": 13.0, "de15": 13.0, "ps2k": 13.5, "ps2m": 13.5, "jack": 12.0, "button": 7.0}
FRONT_WIDTH = {"cf": 43.0, "de9": 31.0, "de15": 31.0, "ps2k": 14.0, "ps2m": 14.0, "jack": 7.0, "button": 6.5}

DESCRIPTION = {
    "CTRL": "clocks, sequencer, its slice of the control store, decode table, instruction queue, PC",
    "ALU": "register file (two copies of 64K x 32), eight 74F181s, the flags",
    "MEM": "4 MB of RAM, the byte crossbar, MAR, FPC, MQ",
    "IO": "two UARTs, timer, CF card, PS/2, audio DAC, boot flash, reset",
    "VIDEO": "2 MB frame buffer, 640 x 480 x 8 through a palette, VGA",
}


def _short(ref):
    return ref[2:] if ref[:2] in ("U_", "X_", "J_") else ref


def packages(name):
    """{short ref: (part, package)} for every package on the board (the
    register file's halves joined: RFA0 and RFA1 are RFA01)."""
    nl = system.board(name, True)
    out = {}
    halves = {}
    for inst in nl.instances:
        if inst.type.name in ("const", "pullup", "din96") or inst.ref.startswith("J_"):
            continue
        part, pkg = system.package_of(inst)
        if pkg is None:
            pkg = EXTRA_PACKAGES.get(part)
        if pkg is None:
            continue
        ref = _short(inst.ref)
        if part in parts.HALVES:
            halves.setdefault(part, []).append(ref)
            continue
        out[ref] = (part, pkg[0])
    for part, refs in halves.items():
        refs.sort()
        for a, b in zip(refs[::2], refs[1::2]):
            out[a + b[-1]] = (part, parts.PACKAGES[part][0])
    return out


def _front_limit(name, x0, x1):
    """The front edge of the row area over X from x0 to x1."""
    y = Y1
    for _, kind, xc in FRONT.get(name, []):
        w = FRONT_WIDTH[kind] / 2 + 2.5
        if xc + w > x0 and xc - w < x1:
            y = min(y, BOARD_H - FRONT_DEPTH[kind] - 6.0)
    return y


def _place_row(mode, groups, pk, y, gap):
    """Place one row's chips; returns (chips, group boxes, width used)."""
    rot = mode == "vgrid"
    items = []
    for gi, (label, refs, *_) in enumerate(groups):
        for ref in refs:
            part, pkg = pk[ref]
            kind, length, width, height, pins = FOOTPRINTS[pkg]
            if rot:
                length, width = width, length
            items.append({"ref": ref, "part": part, "pkg": pkg, "kind": kind, "L": length, "W": width,
                          "H": height, "pins": pins, "rot": rot, "g": gi})
    avail = X1 - X0
    if mode in ("grid", "vgrid"):
        # every chip in a cell of the same pitch, cells spread over the width;
        # a group starts a little apart from the one before
        n = len(items)
        breaks = len(groups) - 1
        extra = 3.0 if breaks else 0.0
        pitch = (avail - breaks * extra) / n
        if pitch < max(i["L"] for i in items) + 2.0:
            raise ValueError(f"row too full: {[i['ref'] for i in items]}")
        x = X0
        for k, it in enumerate(items):
            if k and it["g"] != items[k - 1]["g"]:
                x += extra
            it["x"] = x + pitch / 2
            x += pitch
    elif mode == "at":
        # each group from the X its third element gives
        for gi, (_, _, gx) in enumerate(groups):
            x = gx
            for it in [i for i in items if i["g"] == gi]:
                it["x"] = x + it["L"] / 2
                x += it["L"] + 3.2
        xs = sorted((i["x"] - i["L"] / 2, i["x"] + i["L"] / 2) for i in items)
        if any(b[0] < a[1] + 2.0 for a, b in zip(xs, xs[1:])) or xs[0][0] < X0 or xs[-1][1] > X1:
            raise ValueError(f"row overlaps: {[i['ref'] for i in items]}")
    else:
        inner = 3.2
        widths = []
        for gi in range(len(groups)):
            gs = [i for i in items if i["g"] == gi]
            widths.append(sum(i["L"] for i in gs) + inner * (len(gs) - 1))
        free = avail - sum(widths) - 4.0 * len(groups)
        if free < 0:
            raise ValueError(f"row too full: {[i['ref'] for i in items]}")
        between = min(free / max(len(groups) - 1, 1), 30.0)
        if len(groups) == 1:
            between = 0
        x = X0 + 2.0
        for gi in range(len(groups)):
            for it in [i for i in items if i["g"] == gi]:
                it["x"] = x + it["L"] / 2
                x += it["L"] + inner
            x += between - inner + 4.0
    height = max(i["W"] for i in items)
    for it in items:
        it["y"] = y + height / 2
    boxes = []
    for gi, (label, *_) in enumerate(groups):
        gs = [i for i in items if i["g"] == gi]
        boxes.append({"label": label, "x0": min(i["x"] - i["L"] / 2 for i in gs) - 1.3,
                      "x1": max(i["x"] + i["L"] / 2 for i in gs) + 1.3,
                      "y0": y - 0.9, "y1": y + height + 2.6})
    return items, boxes, height


def layout_board(name):
    pk = packages(name)
    rows = ROWS[name]
    heights = []
    for mode, groups in rows:
        hs = []
        for _, refs, *_ in groups:
            for ref in refs:
                kind, length, width, *_ = FOOTPRINTS[pk[ref][1]]
                hs.append(length if mode == "vgrid" else width)
        heights.append(max(hs))
    limit = min(_front_limit(name, X0, X1), Y1)
    # rows spread over the area, a gap of at least 4.6 mm for the reference
    # designators above a row and the group labels under the next, at most 14
    gap = (limit - Y0 - sum(heights)) / len(rows)
    gap = min(gap, 14.0)
    if gap < 4.6:
        raise ValueError(f"{name}: rows too tall ({gap:.1f} mm gaps)")
    chips, groups = [], []
    y = Y0 + 1.5
    for (mode, gs), h in zip(rows, heights):
        items, boxes, _ = _place_row(mode, gs, pk, y, gap)
        chips += items
        groups += boxes
        y += h + gap
    # rows that run into the front connectors' area: only where none are
    for it in chips:
        if it["y"] + it["W"] / 2 > _front_limit(name, it["x"] - it["L"] / 2, it["x"] + it["L"] / 2) + 1.0:
            raise ValueError(f"{name}: {it['ref']} runs into the front connectors")
    placed = [c["ref"] for c in chips]
    dup = {r for r in placed if placed.count(r) > 1}
    missing = set(pk) - set(placed) - {"CF"}
    unknown = set(placed) - set(pk)
    if dup or missing or unknown:
        raise ValueError(f"{name}: twice {sorted(dup)}, not placed {sorted(missing)}, "
                         f"not on the board {sorted(unknown)}")
    for c in chips:
        c["g"] = groups[[i for i, b in enumerate(groups)
                         if b["x0"] <= c["x"] <= b["x1"] and b["y0"] <= c["y"] <= b["y1"]][0]]["label"]
    for c in chips:
        for k in ("x", "y", "L", "W"):
            c[k] = round(c[k], 2)
    for b in groups:
        for k in ("x0", "x1", "y0", "y1"):
            b[k] = round(b[k], 2)
    return {"chips": chips, "groups": [b for b in groups if b["label"]],
            "front": [{"ref": r, "kind": k, "x": x} for r, k, x in FRONT.get(name, [])]}


def layout():
    st = system.stats()
    out = {}
    for name in system.BUILDERS:
        b = layout_board(name)
        s = st[name]
        b["stats"] = {"packages": s["packages"], "area": round(s["area"], 1), "gals": s["gals"]}
        b["desc"] = DESCRIPTION[name]
        out[name] = b
    return out


def write(path):
    template = (Path(__file__).parent / "mockup.html").read_text()
    data = json.dumps({"board": {"w": BOARD_W, "h": BOARD_H}, "boards": layout()}, separators=(",", ":"))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template.replace("/*LAYOUT*/null", data))
    return path
