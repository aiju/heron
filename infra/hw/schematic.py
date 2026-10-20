"""Schematics of a netlist, as an interactive page.

    from heron.infra.hw import schematic
    page = schematic.page(nl, "The system", cards={"BP": "Backplane", ...})

A sheet is one section of the design (Netlist.section): its gates, drawn one
by one as logic symbols, and its other chips, drawn as boxes with their
pins. Wires join the pins of a sheet; pins whose nets go elsewhere get a
label that leads to the other end. Numbered nets that run together (D1-D8
of a register to DBUS0-7) are drawn as one bus. The page lays each sheet
out in the browser with ELK (the Eclipse Layout Kernel's layered algorithm,
loaded from a CDN) and lets you follow any net through the whole design.

Rails, constants and pull-up resistors aren't drawn: a pin on a rail says
so in its label, and a net with a pull-up says so when it is selected.
"""

import json
import os
import re
from collections import defaultdict

from . import chips, gal

HERE = os.path.dirname(os.path.abspath(__file__))
ELK_URL = "https://cdn.jsdelivr.net/npm/elkjs@0.9.3/lib/elk.bundled.js"

# gate type -> (function, the output is inverted, Schmitt inputs, open collector)
GATE_FN = {
    "00": ("and", True, False, False), "02": ("or", True, False, False),
    "04": ("buf", True, False, False), "05": ("buf", True, False, True),
    "08": ("and", False, False, False), "10": ("and", True, False, False),
    "11": ("and", False, False, False), "14": ("buf", True, True, False),
    "20": ("and", True, False, False), "21": ("and", False, False, False),
    "27": ("or", True, False, False), "30": ("and", True, False, False),
    "32": ("or", False, False, False), "86": ("xor", False, False, False),
    "132": ("and", True, True, False),
}
RAILS = ("GND", "VCC")
NUM = re.compile(r"^(.*?)(\d+)$")

# geometry (px): the page draws what these sizes promise
PIN = 14                # pitch of a chip's pins
HEAD = 30               # a chip's title
CHIP_W = 150
GATE_W = 46


def _card(ref):
    return ref.split(".", 1)[0] if "." in ref else ""


def _local(name, card):
    return name[len(card) + 1:] if card and name.startswith(card + ".") else name


def _runs(items, key):
    """Split items into runs of consecutive ones with the same key."""
    out = []
    for it in items:
        k = key(it)
        if out and out[-1][0] == k:
            out[-1][1].append(it)
        else:
            out.append((k, [it]))
    return out


def _span(nums):
    nums = sorted(nums)
    if len(nums) == 1:
        return str(nums[0])
    if nums == list(range(nums[0], nums[-1] + 1)):
        return f"{nums[0]}–{nums[-1]}"
    return ",".join(map(str, nums))


def _bus_name(nets, card):
    """BUS0-7 for nets BUS0..BUS7, or None if they aren't one numbered bus."""
    if len(nets) == 1:
        return _local(nets[0], card)
    ms = [NUM.match(_local(n, card)) for n in nets]
    if any(m is None for m in ms) or len({m.group(1) for m in ms}) != 1:
        return None
    return f"{ms[0].group(1)}{_span([int(m.group(2)) for m in ms])}"


def _side(inst, pin, kind):
    """Which side of a chip's box a pin goes on."""
    if kind == "in" or kind == "pull":
        return "W"
    if kind == "io" and inst.type.name == "245" and pin.startswith("A"):
        return "W"
    return "E"


def model(nl, title, cards=None, variant=chips.DEFAULT_VARIANT):
    """The schematic of a netlist as JSON-able data: sheets, symbols with
    their ports, wires on each sheet, and every net's ends."""
    cards = cards or {}
    gate_refs = {g.ref for g in nl.gates}
    insts = {i.ref: i for i in nl.instances}
    drawn = {}                       # symbol id -> symbol
    pin_port = {}                    # (ref, pin) -> (symbol id, port index)

    # what the drawing leaves out: rails, constants, pull-ups
    tied, pulled = {}, set()
    for inst in nl.instances:
        if inst.type.family == "fixture" and inst.type.name == "const":
            for p, n in inst.conn.items():
                tied[n] = "GND" if p == "LO" else "VCC"
        if inst.type.family == "passive":
            pulled.update(inst.conn.values())

    def sheet_of(ref, section):
        card = _card(ref)
        return f"{card}/{section or 'Other'}"

    # gates, one symbol each
    for g in nl.gates:
        inst = insts[g.ref]
        fn, inv, schmitt, oc = GATE_FN[g.typ]
        ins = [(p, inst.conn[p]) for p in g.inputs if inst.conn[p] not in RAILS] or \
              [(g.inputs[0], inst.conn[g.inputs[0]])]
        sid = f"{g.ref}#{g.sec + 1}"
        n_in = len(ins)
        h = max(24, n_in * 12 + 4)
        ports = [{"pin": p, "nets": [n], "kind": "in", "side": "W", "x": 0,
                  "y": round((i + 0.5) * h / n_in, 1)} for i, (p, n) in enumerate(ins)]
        ports.append({"pin": g.output, "nets": [inst.conn[g.output]], "kind": "out", "side": "E",
                      "x": GATE_W, "y": h / 2})
        drawn[sid] = {"id": sid, "kind": "gate", "ref": g.ref, "sec": g.sec + 1,
                      "part": inst.part_number(variant), "fn": fn, "inv": inv,
                      "schmitt": schmitt, "oc": oc, "w": GATE_W, "h": h, "ports": ports,
                      "sheet": sheet_of(g.ref, g.section)}
        for k, (p, n) in enumerate(ins):
            pin_port[(g.ref, p)] = (sid, k)
        pin_port[(g.ref, g.output)] = (sid, len(ports) - 1)

    # other chips, one box each, pins in buses where their nets are a bus
    for inst in nl.instances:
        if inst.ref in gate_refs or inst.type.family in ("fixture", "passive"):
            continue
        card = _card(inst.ref)
        pins = [(p, inst.kind(p), inst.conn[p]) for p, _k in inst.type.pins if p in inst.conn]
        sides = {"W": [], "E": []}
        for p, k, n in pins:
            sides[_side(inst, p, k)].append((p, k, n))
        ports = []
        for side, lst in sides.items():
            def key(t):
                m, nm = NUM.match(t[0]), NUM.match(_local(t[2], card))
                if m is None or nm is None or t[2] in RAILS:
                    return (t[0],)
                return (m.group(1), t[1], nm.group(1))
            for k, run in _runs(lst, key):
                groups = [run] if len(run) > 1 and len(k) == 3 else [[t] for t in run]
                for grp in groups:
                    if len(grp) > 1:
                        m = [NUM.match(t[0]) for t in grp]
                        label = f"{m[0].group(1)}{_span([int(x.group(2)) for x in m])}"
                    else:
                        label = grp[0][0]
                    ports.append({"pin": label, "pins": [t[0] for t in grp],
                                  "nets": [t[2] for t in grp], "kind": grp[0][1], "side": side})
        nw = sum(p["side"] == "W" for p in ports)
        ne = len(ports) - nw
        h = HEAD + PIN * max(nw, ne, 1) + 6
        iw = ie = 0
        for i, p in enumerate(ports):
            if p["side"] == "W":
                p["x"], p["y"] = 0, HEAD + PIN * iw + PIN / 2
                iw += 1
            else:
                p["x"], p["y"] = CHIP_W, HEAD + PIN * ie + PIN / 2
                ie += 1
            for pin in p.get("pins", [p["pin"]]):
                pin_port[(inst.ref, pin)] = (inst.ref, i)
        typ = inst.type
        drawn[inst.ref] = {"id": inst.ref, "kind": "chip", "ref": inst.ref,
                           "part": inst.part_number(variant), "type": typ.name,
                           "desc": gal.equations(inst) if inst.gal else typ.desc or "",
                           "w": CHIP_W, "h": h, "ports": ports,
                           "sheet": sheet_of(inst.ref, inst.section)}

    # every net's ends
    nets = defaultdict(lambda: {"drivers": [], "loads": []})
    for inst in nl.instances:
        for p, n in inst.conn.items():
            if n in RAILS or (inst.ref, p) not in pin_port:
                continue
            sid, k = pin_port[(inst.ref, p)]
            kind = inst.kind(p)
            end = [sid, k, p]
            if kind in ("out", "tri", "io"):
                nets[n]["drivers"].append(end)
            if kind in ("in", "io"):
                nets[n]["loads"].append(end)
    for n, d in nets.items():
        if n in tied:
            d["tied"] = tied[n]
        if n in pulled:
            d["pulled"] = True

    # wires: on each sheet, from each driving port to each loading port,
    # one wire for all the nets the two ports share
    wires = defaultdict(lambda: defaultdict(list))   # sheet -> (from, to) -> nets
    for n, d in nets.items():
        for ds, dk, _ in d["drivers"]:
            for ls, lk, _ in d["loads"]:
                if (ds, dk) == (ls, lk):
                    continue
                if drawn[ds]["sheet"] != drawn[ls]["sheet"]:
                    continue
                a, b = (ds, dk), (ls, lk)
                if a > b and (ls, lk) in [(x[0], x[1]) for x in d["drivers"]]:
                    continue                 # both ends drive (io): one wire
                if n not in wires[drawn[ds]["sheet"]][(a, b)]:
                    wires[drawn[ds]["sheet"]][(a, b)].append(n)
    # labels: a port with a net that has an end on another sheet
    for s in drawn.values():
        for k, p in enumerate(s["ports"]):
            off = []
            for n in p["nets"]:
                if n in RAILS:
                    continue
                ends = nets[n]["drivers"] + nets[n]["loads"]
                if any(drawn[e[0]]["sheet"] != s["sheet"] for e in ends):
                    off.append(n)
            rails = [n for n in p["nets"] if n in RAILS or n in tied]
            card = _card(s["ref"])
            if off:
                p["off"] = _bus_name(off, card) or ", ".join(_local(n, card) for n in off[:3]) + \
                    (" …" if len(off) > 3 else "")
            elif rails and len(rails) == len(p["nets"]):
                vals = {tied.get(n, n) for n in rails}
                p["off"] = vals.pop() if len(vals) == 1 else "rails"
                p["rail"] = True

    sheets = defaultdict(list)
    for s in drawn.values():
        sheets[s["sheet"]].append(s["id"])
    order = list(cards) + sorted({_card(s["ref"]) for s in drawn.values()} - set(cards))
    # sheets in the order the design names its sections, then any others
    named = [f"{p}/{n}" for p, n in nl.sections]
    by_card = defaultdict(list)
    for sh in named + sorted(sheets):
        if sh in sheets and sh not in by_card[sh.split("/", 1)[0]]:
            by_card[sh.split("/", 1)[0]].append(sh)
    chips_in = defaultdict(set)
    for inst in nl.instances:
        if inst.type.family not in ("fixture", "passive"):
            chips_in[_card(inst.ref)].add(inst.ref)
    sheet_list = []
    for card in order:
        for sh in by_card[card]:
            chips_on = {drawn[x]["ref"] for x in sheets[sh]}
            sheet_list.append({"id": sh, "card": card, "name": sh.split("/", 1)[1],
                               "symbols": sheets[sh], "chips": len(chips_on),
                               "wires": [{"from": list(a), "to": list(b), "nets": ns}
                                         for (a, b), ns in wires[sh].items()]})
    return {"title": title,
            "cards": [{"id": c, "name": cards.get(c, c), "chips": len(chips_in[c])} for c in order],
            "sheets": sheet_list, "symbols": drawn,
            "nets": {n: d for n, d in nets.items()}}


def page(nl, title, cards=None, variant=chips.DEFAULT_VARIANT, standalone=False):
    """The viewer as HTML: a fragment (for a page host that adds the
    document around it) or, with standalone, a whole document."""
    with open(os.path.join(HERE, "schematic.html")) as f:
        tpl = f.read()
    data = json.dumps(model(nl, title, cards, variant), separators=(",", ":"))
    body = (tpl.replace("%%TITLE%%", title).replace("%%ELK%%", ELK_URL)
            .replace("%%DATA%%", data.replace("</", "<\\/")))
    if standalone:
        return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1, '
                'viewport-fit=cover">\n</head><body>\n' + body + '\n</body></html>\n')
    return body
