"""From the simulator's netlist to the parts of a board.

The simulator's netlist (infra/hw/netlist.py) has logical pins and no
supplies. A board needs packages, supply pins, and parts the simulator
doesn't model. parts() makes them, with these rules:

- every chip becomes a part with the same reference, in the footprint its
  type has in the board style ("smd" or "dip", packages.py), its pads'
  nets from the pinout: logical pins take their nets, supply pins VCC and
  GND, tied pins (=VCC) their rail, NC pins none;
- test fixtures are not parts; a `const` fixture's outputs are the rails,
  so its nets become VCC and GND;
- a chip's tied pins that need a part (the supervisor's capacitors) get it;
- every chip with a supply pin gets a decoupling capacitor, C<ref>, VCC
  to GND;
- a card's connector pins (nets BUS.<signal>) are pads of the connector
  parts the caller gives, by a pin map.

check.compare() reads a board back and holds it against the netlist with
these same rules, written separately.
"""

from . import packages
from .board import Part

# capacitors for a part's tied pins: (tie name) -> (value, other end)
TIE_PARTS = {"CREF": ("100n", "GND"), "CT": ("100n", "GND")}


def rails(nl):
    """{net: "VCC" or "GND"} for the nets a const fixture drives."""
    out = {}
    for inst in nl.instances:
        if inst.type.name == "const":
            for pin, net in inst.conn.items():
                out[net] = "GND" if pin == "LO" else "VCC"
    return out


def part_number(nl, inst):
    """An instance's part number, in the netlist's parts variant
    (`nl.variant`, if it has one)."""
    v = getattr(nl, "variant", None)
    return inst.part_number(v) if v else inst.part_number()


def parts(nl, style, connectors=(), decouple=True, cap=None):
    """The board's parts for a netlist: [Part]. `connectors` are
    (Part with empty nets, {pad: bus signal}) pairs: pad gets the net
    BUS.<signal> if the netlist has it, or the rail named. `cap`: the
    decoupling capacitors' footprint, if not the style's."""
    alias = rails(nl)
    used = {n for i in nl.instances for n in i.conn.values()}
    out = []
    for inst in nl.instances:
        t = inst.type
        if t.family == "fixture":
            continue
        pn = part_number(nl, inst) if t.family != "osc" else None
        fp = packages.footprint_for(t.name, style, pn)
        nets = {}
        extra = []
        for pad, name in packages.pad_map(t.name, style, pn).items():
            if name in ("VCC", "GND"):
                nets[pad] = name
            elif name == "NC":
                continue
            elif name.startswith("="):
                tie = name[1:]
                if tie in ("VCC", "GND"):
                    nets[pad] = tie
                else:
                    net = f"{inst.ref}.{tie}"
                    nets[pad] = net
                    value, other = TIE_PARTS[tie]
                    extra.append(Part(f"C{inst.ref}.{tie}", packages.FP[style]["CAP"],
                                      {"1": net, "2": other}, value=value, kind="passive",
                                      section=inst.section))
            else:
                net = inst.conn.get(name)
                if net is not None:
                    nets[pad] = alias.get(net, net)
        value = pn if t.family != "osc" else inst.part or "oscillator"
        part = Part(inst.ref, fp, nets, value=value, kind="chip", inst=inst.ref,
                    section=inst.section, typ=packages.pinout_of(t.name, pn))
        out.append(part)
        out += extra
        if decouple and t.family != "passive" and "VCC" in nets.values():
            out.append(Part(f"C{inst.ref}", cap or packages.FP[style]["CAP"], {"1": "VCC", "2": "GND"},
                            value="100n", kind="decap", section=inst.section))
    for part, pins in connectors:
        for pad, sig in pins.items():
            if sig in ("VCC", "GND"):
                part.nets[pad] = sig
            elif f"BUS.{sig}" in used:
                part.nets[pad] = alias.get(f"BUS.{sig}", f"BUS.{sig}")
        out.append(part)
    return out


def bom(board):
    """{value: [refs]} of a board's parts."""
    out = {}
    for p in board.parts.values():
        out.setdefault(p.value, []).append(p.ref)
    return dict(sorted(out.items()))

