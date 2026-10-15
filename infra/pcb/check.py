"""Checks that a board is the netlist the simulator runs.

Three links, each checked from independent sources:

1. **Pinouts** (check_pinouts): packages.PINOUTS against KiCad's symbol
   library, a separate transcription of the same datasheets.
2. **Pads** (compare): every pad's net on the board, read back from the
   .kicad_pcb file, against the simulator's netlist through the pinouts,
   as partitions of the pads (names don't matter), with the board's own
   parts (decoupling, connectors, jumpers, series resistors) explained by
   rules.
3. **Copper** (copper.py): the connectivity of the copper itself (tracks,
   vias, pads and filled zones, by geometry), against the pads' nets: no
   net in two pieces, no two nets touching.
"""

from collections import defaultdict

from heron.infra.hw import netlist as hwnl

from . import kicadlib, packages


# ---- 1. pinouts --------------------------------------------------------------------

def _sections(typ):
    """Our pins of a gate package, by section: [(inputs, output)]."""
    n_sec, n_in = hwnl.GATE_SECTIONS[typ]
    letters = "ABCDEFGH"
    out = []
    for s in range(1, n_sec + 1):
        if n_sec > 1:
            out.append(([f"{s}{letters[i]}" for i in range(n_in)], f"{s}Y"))
        else:
            out.append(([letters[i] for i in range(n_in)], "Y"))
    return out


MULTI_UNIT = {"74": 2, "109": 2, "125": 4}
OUTPUT_TYPES = ("output", "open_collector", "tri_state", "open_emitter")


def check_pinouts(types=None):
    """Differences between our pinouts and KiCad's symbols: a list of
    strings, empty if they agree."""
    errs = []
    for typ, sym in sorted(packages.KICAD_SYMBOLS.items()):
        if types is not None and typ not in types:
            continue
        pins = kicadlib.symbol_pins(sym)
        nums = packages.pin_numbers(typ)
        units = defaultdict(list)
        for num, name, et, unit in pins:
            units[unit].append((int(num), name, et))
        supply = {}
        for num, name, et, unit in pins:
            if et == "power_in":
                supply.setdefault(name, []).append(int(num))
        if typ in hwnl.GATE_SECTIONS or typ == "125":
            if typ == "125":
                ours = sorted((sorted([nums[f"{s}OE"], nums[f"{s}A"]]), nums[f"{s}Y"])
                              for s in range(1, 5))
            else:
                ours = sorted((sorted(nums[p] for p in ins), nums[o])
                              for ins, o in _sections(typ))
            theirs = []
            for unit, ps in units.items():
                ins = sorted(n for n, _, et in ps if et == "input")
                outs = [n for n, _, et in ps if et in OUTPUT_TYPES]
                if ins and len(outs) == 1:
                    theirs.append((ins, outs[0]))
            if ours != sorted(theirs):
                errs.append(f"{typ}: gates {ours} but {sym} has {sorted(theirs)}")
        else:
            byname = defaultdict(list)
            for num, name, et, unit in pins:
                key = f"{unit}{name}" if typ in MULTI_UNIT else name
                byname[key].append(int(num))
            for p, n in nums.items():
                if p == "NC" or p.startswith("="):
                    continue
                if p in ("VCC", "GND"):
                    continue
                kn = packages.kicad_pin_name(typ, p)
                if typ in MULTI_UNIT:
                    kn = f"{p[0]}{kn}"
                if byname.get(kn) != [n]:
                    errs.append(f"{typ}: {p} is pin {n}, {sym} has {kn} on {byname.get(kn)}")
        for rail in ("VCC", "GND"):
            names = {"GND": ("GND", "VSS"), "VCC": ("VCC", "VDD")}[rail]
            theirs = sorted(n for nm in names for n in supply.get(nm, []))
            if theirs != sorted(nums.get(rail, [])):
                errs.append(f"{typ}: {rail} on {nums.get(rail)}, {sym} has {theirs}")
    return errs


# ---- 2. pads against the netlist -------------------------------------------------

def expected(nl, style, connectors=()):
    """{(ref, pad): net} that the netlist asks for, through the pinouts:
    a chip's logical pins their nets (a const fixture's nets are the
    rails), its supply and tied pins their rails; and each connector pad
    ((ref, {pad: signal}) pairs) the net BUS.<signal> or a rail. Pads with
    no net are left out."""
    rail = {}
    for inst in nl.instances:
        if inst.type.name == "const":
            for pin, net in inst.conn.items():
                rail[net] = {"LO": "GND", "HI": "VCC"}[pin]
    out = {}
    for inst in nl.instances:
        if inst.type.family == "fixture":
            continue
        for pad, name in packages.pad_map(inst.type.name, style).items():
            if name in ("VCC", "GND", "=VCC", "=GND"):
                out[(inst.ref, pad)] = name.lstrip("=")
            elif name.startswith("="):
                out[(inst.ref, pad)] = f"{inst.ref}.{name[1:]}"
            elif name != "NC" and name in inst.conn:
                net = inst.conn[name]
                out[(inst.ref, pad)] = rail.get(net, net)
    nets = {n for n in out.values()}
    for ref, pins in connectors:
        for pad, sig in pins.items():
            if sig in ("VCC", "GND"):
                out[(ref, pad)] = sig
            elif f"BUS.{sig}" in nets:
                out[(ref, pad)] = rail.get(f"BUS.{sig}", f"BUS.{sig}")
    return out


def compare(nl, board, style, connectors=()):
    """The board's pads against the netlist. Compares the partitions of
    the pads into nets, so names don't matter, except that the rails
    must be called VCC and GND (the planes are). The board's own parts
    must be explained: a decoupling capacitor (C<chip>) from VCC to GND,
    a tie part (C<chip>.<tie>) from the chip's tie net to a rail. Returns
    a list of differences."""
    exp = expected(nl, style, connectors)
    have = {}
    for p in board.parts.values():
        for d in p.fp.pads:
            if d.number and p.nets.get(d.number):
                have[(p.ref, d.number)] = p.nets[d.number]
    errs = []
    chip_refs = {r for r, _ in exp}
    # every pad of the netlist's parts and the connectors
    for ref in sorted(chip_refs):
        if ref not in board.parts:
            errs.append(f"{ref}: not on the board")
    by_exp = defaultdict(set)
    for k, n in exp.items():
        by_exp[n].add(k)
    by_have = defaultdict(set)
    for k, n in have.items():
        if k[0] in chip_refs:
            by_have[n].add(k)
    for net, pads in sorted(by_exp.items()):
        got = {have.get(k) for k in pads}
        if len(got) != 1 or None in got:
            missing = sorted(f"{r}.{p}" for r, p in pads if have.get((r, p)) is None)
            names = sorted(str(g) for g in got if g)
            errs.append(f"net {net}: on the board as {names}"
                        + (f", unconnected {missing[:6]}" if missing else ""))
            continue
        bnet = got.pop()
        if by_have[bnet] != pads:
            extra = sorted(f"{r}.{p}" for r, p in by_have[bnet] - pads)
            errs.append(f"net {net} (board {bnet}) also has {extra[:6]}")
        if net in ("VCC", "GND") and bnet != net:
            errs.append(f"rail {net} is called {bnet} on the board")
    for k, n in sorted(have.items()):
        if k[0] in chip_refs and k not in exp:
            errs.append(f"{k[0]}.{k[1]}: on {n}, the netlist has it unconnected")
    # the board's own parts
    for p in board.parts.values():
        if p.ref in chip_refs:
            continue
        nets = sorted(n for n in p.nets.values() if n)
        if p.ref.startswith("C") and p.ref[1:] in chip_refs:
            if nets != ["GND", "VCC"]:
                errs.append(f"{p.ref}: a decoupling capacitor on {nets}, not VCC and GND")
        elif p.ref.startswith("C") and "." in p.ref and p.ref[1:].rsplit(".", 1)[0] in chip_refs:
            chip, tie = p.ref[1:].rsplit(".", 1)
            if f"{chip}.{tie}" not in nets or not ({"GND", "VCC"} & set(nets)):
                errs.append(f"{p.ref}: a tie capacitor on {nets}")
        else:
            errs.append(f"{p.ref}: a part the netlist doesn't explain (nets {nets[:6]})")
    return errs


# ---- the fab's test netlist ----------------------------------------------------------

def read_ipc356(path):
    """The test points of an IPC-D-356 netlist: [(net, ref, pin, x, y)] in
    mm, board coordinates (y down). Vias have ref "VIA". The format keeps
    14 characters of a net's name and 6 of a reference, so a point is
    matched to a pad by where it is, not by its names."""
    out = []
    unit = 0.00254                      # CUST 0: 0.0001 inch
    with open(path) as f:
        for line in f:
            if line.startswith("P  UNITS"):
                parts = line.split()
                if len(parts) >= 4 and parts[3] == "1":
                    unit = 0.001        # CUST 1: microns
            if not (line.startswith("317") or line.startswith("327")):
                continue
            net = line[3:17].strip()
            ref = line[20:26].strip()
            pin = line[27:31].strip()
            i = line.index("X", 27)
            x = int(line[i + 1:i + 8]) * unit
            y = -int(line[i + 9:i + 16]) * unit
            out.append((net, ref, pin, x, y))
    return out


def compare_ipc356(path, board, tol=0.01):
    """The fab's test netlist against the board: every component test
    point on a pad, and the points' nets the same partition of the pads
    as the board's nets. Returns a list of differences."""
    pads = {}
    for pad in board.pads():
        if pad.number:
            pads.setdefault((round(pad.x / tol), round(pad.y / tol)), []).append(pad)
    errs = []
    ipc_net = {}
    for net, ref, pin, x, y in read_ipc356(path):
        if ref == "VIA" or net == "N/C":           # vias; pads on no net
            continue
        cands = [p for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                 for p in pads.get((round(x / tol) + dx, round(y / tol) + dy), [])]
        cands = [p for p in cands if p.part.ref[:6] == ref and p.number == pin]
        if len(cands) != 1:
            errs.append(f"test point {ref}-{pin} on {net} at ({x:.3f}, {y:.3f}): "
                        f"{len(cands)} pads there")
            continue
        p = cands[0]
        ipc_net[(p.part.ref, p.number)] = net
    by_ipc = defaultdict(set)
    by_board = defaultdict(set)
    for k, n in ipc_net.items():
        by_ipc[n].add(k)
    for p in board.parts.values():
        for num, n in p.nets.items():
            if n and (p.ref, num) in ipc_net:
                by_board[n].add((p.ref, num))
    if sorted(map(sorted, by_ipc.values())) != sorted(map(sorted, by_board.values())):
        board_of = {k: n for n, ks in by_board.items() for k in ks}
        for n, ks in by_ipc.items():
            names = {board_of.get(k) for k in ks}
            if len(names) != 1 or by_board[names.pop()] != ks:
                errs.append(f"test net {n}: on the board as {sorted(str(x) for x in {board_of.get(k) for k in ks})}")
    tested = set(ipc_net)
    size = defaultdict(int)
    for p in board.parts.values():
        for n in p.nets.values():
            size[n] += 1
    for p in board.parts.values():
        for num, n in p.nets.items():
            if n and size[n] > 1 and (p.ref, num) not in tested:
                errs.append(f"{p.ref}.{num} on {n}: no test point")
    return errs
