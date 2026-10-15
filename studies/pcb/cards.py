"""The system's cards as printed circuit boards: what goes on each, and
its connectors.

A card's netlist (studies/system) names its connector pins BUS.<signal>.
On the board they are the pins of two DIN 41612 type C connectors, P1 and
P2, at the card's back edge, by the reference pin assignment of report
0022 (studies/bus_si/connector.py), which follows RFC 0014's rules.
"""

from heron.infra.pcb import board as B
from heron.infra.pcb import physical
from heron.studies.bus_si import connector
from heron.studies.system import cpucard, iocard, memcard

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
    side), P1 in the upper half and P2 in the lower: [(Part, pin map)]."""
    maps = pin_maps(nl)
    out = []
    for name, yc in (("P1", height * 0.25), ("P2", height * 0.75)):
        if name == "P2" and not uses_p2:
            continue
        part = B.Part(name, CONNECTOR, {}, value="DIN 41612 C 3x32 male", kind="conn")
        # turned so that the mating face (-y in the footprint) points off
        # the right edge; the pins' middle on yc
        part.place(width - 6.5, yc - 39.37, 270)
        part.fixed = True
        out.append((part, maps[name]))
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
    return b
