"""The ALU board laid out in blocks (blocks.py), on a 220 mm deep card,
for soldering by hand.

    datapath, four bands of 33.02 mm, byte 0 at the top beside P1:
      [74F181 x 8: 4 x 2] [ZL CLA ALUF ZH] [register file, 4 SOJ-44] [32 SOIC-20: 8 x 4]  |P1
    control, below, beside P2:
      [FLA FLB / WG BUS] [MIR0-3: 2 x 2] [RF GALs, 6 PLCC-28 sockets: 3 x 2] [CS0-3: 2 x 2] [CK UPC0 / RB UPC1 / EB]  |P2

- **The datapath's bands:** each byte's two 74F181s, its GAL, its SRAM
  (one per two bytes of a copy), and its eight bus transceivers,
  latches and registers in two rows of four (LA YA XB XA over LB YB SH
  FA), from the ALU out to the backplane as the data goes. The blocks
  share the band's pitch, 33.02 mm (13 x 0.1 inch: the 74F181's least),
  the SOICs two rows to a band, so each band's parts are in line.
- **The control** is below, beside P2 where the µPC's lines come in:
  the µPC registers, the clock buffer and EB by the connector, the
  control store's sockets, the register file's address and enable
  GALs in sockets, the microinstruction registers, the flags', W's and
  the bus's GALs.
- **The free room** is the top left, beside the datapath.
"""

from . import blocks as K
from . import place as P

SIZE = (220.0, P.CARD[1])
# The rules for a board soldered by hand: 0.15 mm tracks and gaps, 0.6 mm
# vias with 0.3 mm holes. On six layers the ALU routes completely with
# them; at 0.2 mm, 8 nets at the register file's SOJ-44s don't (200
# rounds no better than 60), at 0.25 mm, 172.
RULES = {"track": 0.15, "clearance": 0.15, "via_dia": 0.6, "via_drill": 0.3}
BAND = 33.02
TOP = 10.0          # the datapath's top: below the top guide and the fiducial at the top right
EDGE = 1.0          # mm kept from the region's back edge, the connectors' side


def layout(b):
    """The ALU's blocks, bound to board b and placed: {name: Block}."""
    X0, Y0, X1, Y1 = b.region
    bus = K.Block("bus", [r for k in range(4) for r in (
        [f"U_LA{k}", f"U_YA{k}", f"U_XB{k}", f"U_XA{k}"],
        [f"U_LB{k}", f"U_YB{k}", f"U_SH{k}", f"U_FA{k}"])], pitch=(None, BAND / 2)).bind(b)
    rf = K.Block("rf", [["U_RFA01"], ["U_RFB01"], ["U_RFA23"], ["U_RFB23"]],
                 pitch=(None, BAND)).bind(b)
    side = K.Block("side", [["U_ZL"], ["U_CLA"], ["U_ALUF"], ["U_ZH"]], pitch=(None, BAND)).bind(b)
    alu = K.Block("alu", [[f"U_ALU{2 * k + 1}", f"U_ALU{2 * k}"] for k in range(4)],
                  pitch=(None, BAND)).bind(b)
    bus.at(right=X1 - EDGE, y=TOP)
    rf.left_of(bus, 3.0, align="rows")
    side.left_of(rf, 3.5, align="rows")
    alu.left_of(side, 2.5, align="rows")

    top = max(blk.outline()[3] for blk in (bus, rf, side, alu)) + 3.0
    upc = K.Block("upc", [["U_CK", "U_UPC0"], ["U_RB", "U_UPC1"], [None, "U_EB"]]).bind(b)
    cs = K.Block("cs", [["U_CS0", "U_CS1"], ["U_CS2", "U_CS3"]]).bind(b)
    gal5 = K.Block("gal5", [["U_RAG0", "U_RAG1"], ["U_RBG0", "U_RBG1"], ["U_BYP", "U_RFW"]]).bind(b)
    mir = K.Block("mir", [["U_MIR0", "U_MIR1"], ["U_MIR2", "U_MIR3"]]).bind(b)
    gal7 = K.Block("gal7", [["U_FLA", "U_FLB"], ["U_WG", "U_BUS"]]).bind(b)
    upc.at(right=X1 - EDGE, y=top)
    cs.left_of(upc, 2.5)
    gal5.left_of(cs, 1.0)
    mir.left_of(gal5, 2.5)
    gal7.left_of(mir, 4.0)
    return {blk.name: blk for blk in (bus, rf, side, alu, upc, cs, gal5, mir, gal7)}


def place(name="ALU", size=SIZE, layers=6, rules=None):
    """The ALU board placed by its blocks, for soldering by hand (the -5
    GALs in sockets, RULES unless `rules` says otherwise): (board,
    {name: Block}, problems)."""
    from heron.studies.pcb_columns.placer import place_decaps
    if name != "ALU":
        raise ValueError(f"no block layout for {name} yet")
    b = P.build_board(name, size, gal_sockets=True, layers=layers, hand=True)
    b.name = f"{name.lower()}-blocks-{size[0]:g}x{size[1]:g}"
    b.rules.update(RULES if rules is None else rules)
    bl = layout(b)
    placed = {r for blk in bl.values() for r in blk.refs()}
    chips = {p.ref for p in b.parts.values() if p.kind == "chip"}
    if placed != chips:
        raise ValueError(f"blocks and board differ: {sorted(placed ^ chips)}")
    place_decaps(b)
    P.centre_decaps(b)
    return b, bl, K.check(b, b.region)


def svg(b, bl, path):
    """The placed board as an SVG (pcb_columns' drawing, without its grid),
    each block's cells drawn over it in dashes and its name above it."""
    from heron.studies.pcb_columns import draw
    text = draw.svg(b, None, labels=True, grid=False)
    marks = []
    for blk in bl.values():
        for i, row in enumerate(blk.rows):
            for j, ref in enumerate(row):
                x, y = blk.x + j * blk.pitch[0], blk.y + i * blk.pitch[1]
                marks.append(f'<rect x="{x:.3f}" y="{y:.3f}" width="{blk.pitch[0]:.3f}" '
                             f'height="{blk.pitch[1]:.3f}" fill="none" stroke="#c0623b" '
                             f'stroke-width="0.25" stroke-dasharray="1.2 0.8"/>')
        marks.append(f'<text x="{blk.x + 0.5:.3f}" y="{blk.y - 0.6:.3f}" font-size="2.2" '
                     f'fill="#c0623b" font-family="sans-serif">{blk.name}</text>')
    text = text.replace("</svg>", "\n".join(marks) + "\n</svg>")
    with open(path, "w") as f:
        f.write(text)
    return text


def build(name="ALU", size=SIZE, layers=6):
    """Place by the blocks and write build/reed_pcb/<name>/: board.svg,
    board.kicad_pcb, result.json (the blocks, the spacing check, the
    share of the parts' region the blocks take). Returns (board, blocks,
    result)."""
    import json
    import os
    b, bl, probs = place(name, size, layers)
    d = os.path.join(P.OUT, b.name)
    os.makedirs(d, exist_ok=True)
    X0, Y0, X1, Y1 = b.region
    area = sum((o[2] - o[0]) * (o[3] - o[1]) for o in (blk.outline() for blk in bl.values()))
    res = {"board": name, "name": b.name, "card": list(size), "problems": probs,
           "blocks": {n: {"rows": len(blk.rows), "columns": blk.ncols,
                          "pitch_mm": [round(v, 3) for v in blk.pitch],
                          "outline_mm": [round(v, 2) for v in blk.outline()]}
                      for n, blk in bl.items()},
           "region_mm2": round((X1 - X0) * (Y1 - Y0)), "blocks_mm2": round(area),
           "blocks_share": round(area / ((X1 - X0) * (Y1 - Y0)), 3)}
    svg(b, bl, os.path.join(d, "board.svg"))
    b.write(os.path.join(d, "board.kicad_pcb"))
    with open(os.path.join(d, "result.json"), "w") as f:
        json.dump(res, f, indent=1)
    return b, bl, res
