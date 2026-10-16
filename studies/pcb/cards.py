"""The system's cards as printed circuit boards: what goes on each, and
its connectors.

A card's netlist (studies/v1b_system) names its connector pins BUS.<signal>.
On the board they are the pins of two DIN 41612 type C connectors, P1 and
P2, at the card's back edge, by the reference pin assignment of report
0022 (studies/bus_si/connector.py), which follows RFC 0014's rules.
"""

from heron.infra.pcb import board as B
from heron.infra.pcb import physical
from heron.studies.bus_si import connector
from heron.studies.v1b_system import cpucard, iocard, memcard

CONNECTOR = "Connector_DIN:DIN41612_C_3x32_Male_Horizontal_THT"
# the connector's pins span 78.74 mm; with its flanges it is 95 mm long
CONNECTOR_LEN = 95.0


def netlists():
    """The cards' netlists, by name."""
    return {"cpu": cpucard.build().netlist, "mem": memcard.build().netlist,
            "io": iocard.build().netlist}


def pin_maps(nl):
    """P1's and P2's pin maps for a card: {pad: signal}, the signals named
    as the netlist names them (active-low ones end in _n)."""
    used = {n[4:] for i in nl.instances for n in i.conn.values() if n.startswith("BUS.")}
    out = {}
    for name, m in (("P1", connector.p1_map()), ("P2", connector.p2_map())):
        pins = {}
        for pad, sig in m.items():
            if sig in ("VCC", "GND") or sig in used:
                pins[pad] = sig
            elif sig + "_n" in used:
                pins[pad] = sig + "_n"
            else:
                pins[pad] = sig              # a bus line this card doesn't use
        out[name] = pins
    return out


def connectors(nl, width, height, uses_p2=True):
    """The card's connector parts, placed on its right edge (the backplane
    side): [(Part, pin map)]. As on a Eurocard, the outer pin row is 5.3 mm
    from the edge (the mounting holes 2.76 mm); on a card at least 6U
    (233.35 mm) high, P2's middle is 50 mm from the bottom edge and P1's
    133.35 mm above it, otherwise they are a quarter of the height from
    the top and the bottom."""
    maps = pin_maps(nl)
    if height >= EUROCARD_6U - 0.01:
        mids = (("P1", height - 50.0 - 133.35), ("P2", height - 50.0))
    else:
        mids = (("P1", height * 0.25), ("P2", height * 0.75))
    out = []
    for name, yc in mids:
        if name == "P2" and not uses_p2:
            continue
        part = B.Part(name, CONNECTOR, {}, value="DIN 41612 C 3x32 male", kind="conn")
        # turned so that the mating face (-y in the footprint) points off
        # the right edge; the pins' middle on yc
        part.place(width - 5.3, yc - 39.37, 270)
        part.fixed = True
        out.append((part, maps[name]))
    return out


# ---- mechanics (RFC 0026) ----------------------------------------------------

EUROCARD_6U = 233.35
GUIDE_STRIP = 5.0         # the top and bottom edges, in the card guides: no parts, no copper
GUIDE_COPPER = 2.5        # ... and next to the connectors, no copper
FRONT_STRIP = 8.0         # the front edge: the front panel's bracket and handles
CONNECTOR_GAP = 1.6       # the connectors' courtyards to the chips': with the chips' own
                          # margin, 2.5 mm from a through-hole pad to an SMD one
BRACKET_HOLE = "MountingHole:MountingHole_2.7mm_M2.5"
FIDUCIAL = "Fiducial:Fiducial_1mm_Mask3mm"
FIDUCIAL_CLEAR = 1.5      # the clear circle's radius around a fiducial


def mechanics(b):
    """The card's strips, holes and fiducials, on a board with its
    connectors: keep-out strips along the edges (the guided top and bottom
    edges clear of parts and copper, the front edge kept for the front
    panel's bracket, the back edge for the connectors only), the front
    panel's bracket holes as on a Eurocard (M2.5, 3.57 mm from the front
    edge and 5.5 mm from the guided edges, and one in the middle on a card
    taller than 6U), and three fiducials on each side in an L. Returns the
    region left for the parts."""
    w, h = b.width, b.height
    conns = [p for p in b.parts.values() if p.kind == "conn"]
    back = min(p.courtyard()[0] for p in conns) - CONNECTOR_GAP if conns else w - FRONT_STRIP
    b.add_keepout(0, 0, FRONT_STRIP, h, "front edge", allow=("mech",))
    b.add_keepout(FRONT_STRIP, 0, back, GUIDE_STRIP, "top guide")
    b.add_keepout(FRONT_STRIP, h - GUIDE_STRIP, back, h, "bottom guide")
    b.add_keepout(back, 0, w, h, "connector edge", no=("footprints",), allow=("conn", "mech"))
    b.add_keepout(back, 0, w, GUIDE_COPPER, "top guide by the connectors", no=("tracks", "vias"))
    b.add_keepout(back, h - GUIDE_COPPER, w, h, "bottom guide by the connectors",
                  no=("tracks", "vias"))
    holes = [(3.57, 5.5), (3.57, h - 5.5)] + ([(3.57, h / 2)] if h > EUROCARD_6U + 0.01 else [])
    for i, (x, y) in enumerate(holes):
        hole = B.Part(f"H{i + 1}", BRACKET_HOLE, {}, value="M2.5", kind="mech")
        hole.place(x, y, 0)
        hole.fixed = True
        b.add(hole)
    # an L: two along the front edge, one along the top towards the back;
    # the same on the bottom side, for its capacitors
    marks = [(5.0, 15.0), (5.0, h - 15.0), (back - 12.0, 7.0)]
    n = 0
    for side in ("F", "B"):
        for x, y in marks:
            n += 1
            fid = B.Part(f"FID{n}", FIDUCIAL, {}, value="fiducial", kind="mech")
            fid.place(x, y, 0, side)
            fid.fixed = True
            b.add(fid)
    for x, y in marks:
        r = FIDUCIAL_CLEAR
        b.add_keepout(x - r, y - r, x + r, y + r, "fiducial", allow=("mech",))
    return (FRONT_STRIP, GUIDE_STRIP, back, h - GUIDE_STRIP)


# the slots of a grid placement (mm, the least), by style and layers: a
# narrow SOIC or a 0.3" DIP and its capacitor take one, a wide SOIC two
# columns, the tall parts two rows; the sizes that need the least area
# for this card's packages, but for DIP on four layers, whose two signal
# layers need wider channels between the columns and the rows
PITCH = {("smd", 6): (8.25, 14.25), ("smd", 4): (8.25, 14.25),
         ("dip", 6): (11.8, 30.4), ("dip", 4): (12.07, 33.0)}

# The CPU card's 50 MHz clock generator allows one 74F gate between
# flip-flops in a 20 ns tick (report 0025, section 5.1): its wires must be
# short, so its nets weigh more in placement.
CRITICAL_SECTIONS = {"Clock generator", "Bus hold and crossings", "Length class"}
CRITICAL_WEIGHT = 8.0


def weights(nl):
    """{net: weight} for placement: the nets that touch the timing-critical
    sections, but not the broadcast ones (more than six pins: the clock,
    the microcode address), which can't be short anyway. A gate package
    can serve several sections, so a gate's pins take its own section (the
    netlist records each gate's)."""
    size = {}
    for inst in nl.instances:
        for net in inst.conn.values():
            size[net] = size.get(net, 0) + 1
    pin_section = {}
    for g in nl.gates:
        for pin in list(g.inputs) + [g.output]:
            pin_section[(g.ref, pin)] = g.section
    out = {}
    for inst in nl.instances:
        for pin, net in inst.conn.items():
            sec = pin_section.get((inst.ref, pin), inst.section)
            if sec in CRITICAL_SECTIONS and net not in ("VCC", "GND") and size[net] <= 6:
                out[net] = CRITICAL_WEIGHT
    return out


def board(card, style="smd", width=380.0, height=220.0, layers=6, rules=None, nl=None):
    """A card's board with its parts, unplaced but for the connectors."""
    nl = nl or netlists()[card]
    b = B.Board(f"{card}-{style}", width, height, layers=layers, rules=rules)
    conns = connectors(nl, width, height)
    for p in physical.parts(nl, style, connectors=conns):
        b.add(p)
    b.pin_maps = [(p.ref, m) for p, m in conns]
    b.netlist = nl
    b.style = style
    b.region = mechanics(b)
    return b
