"""The ALU board placed by hand, as a floorplan: every chip's box on the
column grid of a 220 mm deep card (seven columns, 14 half-columns, 87
rows), by byte slice rather than by annealing.

    half-columns   0-3       4-7          8       9       10   11   12   13
    rows  2-15             ALU1 ALU0     ZL     RFA01    LA0  YA0  XB0  XA0
                                                         LB0  YB0  SH0  FA0
    rows 16-29             ALU3 ALU2     CLA    RFB01    ... byte 1
    rows 30-43             ALU5 ALU4     ALUF   RFA23    ... byte 2
    rows 44-57             ALU7 ALU6     ZH     RFB23    ... byte 3
    rows 58-     FLA FLB   the register  the control store, CS0-3,   CK   UPC0
                 WG  BUS   file's GALs   its MIR0-3 below            RB   UPC1
                                                                          EB

- **The datapath** is four bands of 14 rows, one per byte, byte 0 at the
  top (below the top-right fiducial's two rows) beside P1's first pins (A0 and B0 are a1 and c1). Each band runs
  from the backplane inwards as the data does: the bus transceivers
  (XA, XB from A and B, FA onto A, SH the shift) by the connector, the
  latches and result registers (LA, LB, YA, YB), the register file's
  SOJ-44 (one per two bytes of a copy), then the band's two 74F181s. The
  half-column between the ALUs and the register file has the GALs that
  read F or drive the ALUs: ZL, ZH (whether a half of F is zero), CLA,
  ALUF.
- **The control** is below, beside P2 where the µPC's lines come in: the
  µPC registers and the clock buffer by the connector, the control
  store's four sockets and its microinstruction registers, the register
  file's address and enable GALs under the register file's column, the
  flags' GALs and W's and the bus's to the left.
- **The free room** is the two left columns beside the datapath and the
  bottom rows: about a quarter of the grid in one block.
"""

from heron.studies.pcb_columns.grid import Params
from heron.studies.pcb_columns.placer import GridPlacer, place_decaps

from . import place as P

SIZE = (220.0, P.CARD[1])
TOP = 2             # the first row: rows 0 and 1 of half-column 13 are the top fiducial's

# Each section: (half-column, chip) in order; a chip goes as high in its
# half-columns (both, for a box across a column) as the chips before it
# allow. A section starts below the lowest box of the one above it.
SIDE = ["U_ZL", "U_CLA", "U_ALUF", "U_ZH"]
RF = ["U_RFA01", "U_RFB01", "U_RFA23", "U_RFB23"]


def _byte(k):
    out = [(4, f"U_ALU{2 * k + 1}"), (6, f"U_ALU{2 * k}"), (8, SIDE[k]), (9, RF[k])]
    for hc, top, bottom in ((10, "LA", "LB"), (11, "YA", "YB"), (12, "XB", "SH"),
                            (13, "XA", "FA")):
        out += [(hc, f"U_{top}{k}"), (hc, f"U_{bottom}{k}")]
    return out


CONTROL = [
    (13, "U_UPC0"), (13, "U_UPC1"), (13, "U_EB"),
    (12, "U_CK"), (12, "U_RB"),
    (8, "U_CS0"), (10, "U_CS1"), (8, "U_CS2"), (10, "U_CS3"),
    (8, "U_MIR0"), (9, "U_MIR1"), (10, "U_MIR2"), (11, "U_MIR3"),
    (6, "U_RAG0"), (6, "U_RAG1"), (6, "U_RFW"),
    (4, "U_RBG0"), (4, "U_RBG1"), (4, "U_BYP"),
    (2, "U_FLA"), (3, "U_FLB"), (2, "U_WG"), (3, "U_BUS"),
]
SECTIONS = [_byte(k) for k in range(4)] + [CONTROL]


def alu_floorplan(boxes, halves=14):
    """{ref: (half-column, row)} of every chip on the ALU board, from its
    boxes' sizes ({ref: Box})."""
    fp = {}
    top = TOP
    for section in SECTIONS:
        nxt = [top] * halves
        for hc, ref in section:
            bx = boxes[ref]
            cover = range(hc, hc + bx.w)
            row = max(nxt[h] for h in cover)
            fp[ref] = (hc, row)
            for h in cover:
                nxt[h] = row + bx.h
        top = max(nxt)
    return fp


def place(name="ALU", size=SIZE, params=Params(), gal_sockets=False, layers=4):
    """Place a board by its floorplan: (board, placer, chips left over).
    Raises ValueError where a box doesn't fit its place or two overlap."""
    if name != "ALU":
        raise ValueError(f"no floorplan for {name} yet")
    b = P.build_board(name, size, params, gal_sockets, layers)
    b.name += "-floorplan"
    pl = GridPlacer(b, b.region, params)
    plan = alu_floorplan(pl.boxes, pl.lat.halves)
    refs = {p.ref for p in pl.chips}
    if set(plan) != refs:
        raise ValueError(f"floorplan and board differ: {sorted(set(plan) ^ refs)}")
    for ref, (hc, row) in sorted(plan.items()):
        bx = pl.boxes[ref]
        if hc + bx.w > pl.lat.halves or row + bx.h > pl.lat.rows or (bx.w == 2 and hc % 2):
            raise ValueError(f"{ref}: a {bx.w} x {bx.h} box doesn't fit at {hc}, {row}")
        if not pl._free(hc, row, bx):
            raise ValueError(f"{ref}: its box at {hc}, {row} overlaps another")
        pl._set(ref, hc, row)
    pl.commit()
    place_decaps(b)
    P.centre_decaps(b)
    return b, pl, []


def build(name="ALU", size=SIZE, params=Params(), gal_sockets=False, kicad=True):
    """Place by the floorplan and write it as place.build does."""
    return P.write(name, *place(name, size, params, gal_sockets), kicad=kicad)
