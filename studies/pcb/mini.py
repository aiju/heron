"""Heron Mini's boards as printed circuit boards (RFC 0041, 28): A4 boards
stacked on standoffs, bottom to top cpu1, cpu2 and io, joined by IDC
ribbon cables; their mechanics, where each cable's headers go, and the
delays of the nets across the stack.

The stack (STACK, bottom to top) and its cables. studies/mini/boards.py
cuts the netlist into the three boards and packs each pair's signals
into 64-way cables (a ground after every signal). Here each cable gets a
site, the same on both its boards, so that it runs straight from one to
the other without a twist:

  - neighbours (cpu1-cpu2, cpu2-io) face each other: a vertical header on
    the top side of the lower board and one on the bottom side of the
    upper, right above it, pin 1 over pin 1; the ribbon makes a U between
    them. cpu1-cpu2's six along the long edges (N and S, three each),
    cpu2-io's two along the east edge (E);
  - cpu1-io skips cpu2: right-angle headers at cpu1's west edge (W),
    the ribbon looping up past cpu2's west edge to the same headers at
    io's.

A board's own outline and holes: 297 x 210 mm, M3 standoffs in the
corners and in the middle (RFC 0026's R14 keep-outs, which the planes
keep out of too), a power connector per board (a 2 x 2 Mini-Fit Jr: two
pins of 5 V, two of ground) just inside the east headers, and three
fiducials a populated side (R21). The rules for a card in a Eurocard
subrack (R7-R13, R22's conveyor edges) don't apply to a stacked board;
an assembly house adds break-off rails to it.

The cables (CABLE_*): a 1.27 mm flat ribbon, 28 AWG, about 100 ohms
with a ground beside each signal, 47.5 pF/m (3M's 3365), so about
4.9 ps/mm. A U between facing headers is the boards' spacing (STANDOFF)
and FOLD_MM more; the loop past a board, twice the spacing and LOOP_MM.

delays() puts the routed boards together: every net of the netlist as
one graph over the boards' copper and the cables, the flight time from
each of its drivers to each of its loads, and its capacitance, as
studies/mini's timing analysis and chip-level simulator take them (see
its docstring). The io board isn't designed yet: its side of a net is
estimated (IO_*).
"""

import json
import math
import os
from collections import defaultdict

from heron import BUILD
from heron.infra.pcb import board as B
from heron.infra.pcb import packages, physical, wires
from heron.studies.mini import boards as mini_boards

from . import cards

WIDTH, HEIGHT = 297.0, 210.0            # A4, landscape: x along 297
STACK = tuple(reversed(mini_boards.STACK))   # bottom to top: cpu1, cpu2, io
STANDOFF = 35.0                         # mm board to board: two mated headers face to face,
                                        # 13 mm each, and room for the ribbon's U
FOLD_MM = 20.0                          # a U between facing headers: the ribbon beyond the spacing
LOOP_MM = 50.0                          # a loop past a board: out of each header and round
CABLE_PS_PER_MM = 4.9                   # 3365-style ribbon: 102 ohms, 47.5 pF/m
CABLE_PF_PER_MM = 0.0475
HEADER_PS = 15                          # a header and its mated socket, each end
HEADER_PF = 1.0

HOLE = "MountingHole:MountingHole_3.2mm_M3"
HOLE_INSET = 5.0                        # mm from the edges to a corner hole's centre
HOLE_KEEP = 4.0                         # R14: nothing within ø8 mm of an M3 hole
POWER = "Connector_Molex:Molex_Mini-Fit_Jr_5566-04A2_2x02_P4.20mm_Vertical"
POWER_PINS = {"1": "GND", "2": "GND", "3": "VCC", "4": "VCC"}
EDGE_GAP = 1.0                          # a header's courtyard from the board's edge
GAP = 2.0                               # between headers, and from the parts' region
VERTICAL = "Connector_IDC:IDC-Header_2x32_P2.54mm_Vertical"
RIGHT_ANGLE = "Connector_IDC:IDC-Header_2x32_P2.54mm_Horizontal"

# the sites of each pair's cables: an edge and the cables along it, in
# order (pin 1 at the edge's start: west on N and S, north on E and W)
SITES = {("cpu1", "cpu2"): [("N", 3), ("S", 3)],
         ("cpu2", "io"): [("E", 2)],
         ("cpu1", "io"): [("W", 2)]}

OUT = os.path.join(BUILD, "pcb")


# ---- the headers ------------------------------------------------------------------------


def pairs():
    """The pairs of boards with cables, lower board first."""
    return list(SITES)


def neighbours(x, y):
    return abs(STACK.index(x) - STACK.index(y)) == 1


def cable_mm(x, y):
    """A cable's length between boards x and y."""
    gap = abs(STACK.index(x) - STACK.index(y)) * STANDOFF
    return gap + (FOLD_MM if neighbours(x, y) else LOOP_MM)


def cable_ps(x, y):
    return round(cable_mm(x, y) * CABLE_PS_PER_MM + 2 * HEADER_PS)


def cable_pf(x, y):
    return cable_mm(x, y) * CABLE_PF_PER_MM + 2 * HEADER_PF


def _header(ref, edge, side, right_angle):
    """A header part turned for its edge and side: its pins along the
    edge from the edge's start, and on the bottom side mirrored across
    the edge (the ribbon's U turns it over), so that pin k is over pin k
    of the header facing it."""
    fp = RIGHT_ANGLE if right_angle else VERTICAL
    p = B.Part(ref, fp, {}, value="IDC 2x32", kind="conn")
    if right_angle:
        # its opening faces out over the edge: pins run along the edge
        rot = {"W": 180, "E": 0, "N": 90, "S": 270}[edge]
    else:
        rot = 90 if edge in ("N", "S") else 0
        if side == "B":
            rot += 180
    p.place(0.0, 0.0, rot, side)
    return p


def _along(edge):
    return WIDTH if edge in ("N", "S") else HEIGHT


def site_parts(board):
    """[(Part, cable {"pair", "index"})]: the board's headers placed at
    their sites, for the cables boards.connectors() makes (refs
    J_<other board>_<n>)."""
    out = []
    for (lo, hi), edges in SITES.items():
        if board not in (lo, hi):
            continue
        other = hi if board == lo else lo
        right_angle = not neighbours(lo, hi)
        side = "F" if (board == lo or right_angle) else "B"
        n = 0
        for edge, count in edges:
            parts = []
            for _ in range(count):
                n += 1
                parts.append(_header(f"J_{other}_{n}", edge, side, right_angle))
            # spread along the edge between the corner holes' keep-outs
            start = HOLE_INSET + HOLE_KEEP + GAP
            span = _along(edge) - 2 * start
            lens = []
            for p in parts:
                x0, y0, x1, y1 = p.courtyard()
                lens.append((x1 - x0) if edge in ("N", "S") else (y1 - y0))
            room = span - sum(lens)
            if room < 0:
                raise ValueError(f"{count} headers don't fit along the {edge} edge")
            gap = room / max(len(parts) - 1, 1) if len(parts) > 1 else 0.0
            pos = start + (room / 2 if len(parts) == 1 else 0.0)
            for p, ln in zip(parts, lens):
                x0, y0, x1, y1 = p.courtyard()
                if edge == "N":
                    dx, dy = pos - x0, EDGE_GAP - y0
                elif edge == "S":
                    dx, dy = pos - x0, HEIGHT - EDGE_GAP - y1
                elif edge == "W":
                    dx, dy = EDGE_GAP - x0, pos - y0
                else:
                    dx, dy = WIDTH - EDGE_GAP - x1, pos - y0
                p.place(p.x + dx, p.y + dy, p.rot, p.side)
                p.fixed = True
                p.edge = edge
                out.append((p, {"pair": (lo, hi), "index": len(out)}))
                pos += ln + gap
    return out


def check_sites():
    """That each cable's headers are the same on its two boards: pin k
    of one over pin k of the other (within the ribbon's U, which turns
    the rows over), or at the same place along the edge for a loop.
    Returns a list of differences."""
    errs = []
    per = {b: {p.ref: p for p, _ in site_parts(b)} for b in STACK}
    for (lo, hi), edges in SITES.items():
        n = sum(c for _, c in edges)
        for i in range(1, n + 1):
            a, b = per[lo][f"J_{hi}_{i}"], per[hi][f"J_{lo}_{i}"]
            pa = {d.number: (d.x, d.y) for d in a.pads() if d.number}
            pb = {d.number: (d.x, d.y) for d in b.pads() if d.number}
            for k in ("1", "2", "63", "64"):
                along = 0 if a.edge in ("N", "S") else 1
                if abs(pa[k][along] - pb[k][along]) > 0.01:
                    errs.append(f"{lo}-{hi}/{i}: pin {k} at {pa[k]} and {pb[k]}")
            # the odd pins' row: the same row for a loop, the other for a U
            odd_a = pa["1"][1 - along] - pa["2"][1 - along]
            odd_b = pb["1"][1 - along] - pb["2"][1 - along]
            if neighbours(lo, hi) and abs(odd_a + odd_b) > 0.01:
                errs.append(f"{lo}-{hi}/{i}: the rows aren't turned over")
    return errs


# ---- a board ------------------------------------------------------------------------------


def holes():
    """The standoffs' holes: the corners and the middle."""
    i = HOLE_INSET
    return [(i, i), (WIDTH - i, i), (i, HEIGHT - i), (WIDTH - i, HEIGHT - i),
            (WIDTH / 2, HEIGHT / 2)]


def power_part():
    """The power connector, just inside the east edge's headers."""
    p = B.Part("J_PWR", POWER, {}, value="Mini-Fit Jr 2x2", kind="conn")
    p.place(0.0, 0.0, 90, "F")
    x0, y0, x1, y1 = p.courtyard()
    east = WIDTH - EDGE_GAP - 9.9 - GAP           # inside a vertical header at the E edge
    p.place(east - x1, HEIGHT / 2 - (y0 + y1) / 2, 90, "F")
    p.fixed = True
    return p


FIDUCIALS = [(24.0, 24.0), (24.0, HEIGHT - 24.0), (WIDTH - 40.0, 24.0)]
FIDUCIAL_KEEP = 1.7                     # its 3 mm clear circle, and its pad's clearance to tracks


def board(name, style="smd", width=WIDTH, height=HEIGHT, layers=6, rules=None, nl=None, cap=None):
    """A board of the stack for studies/pcb's flow, as cards.board() makes
    a card: its parts, its headers at their sites, the power connector,
    the holes and fiducials and their keep-outs, and the region left for
    the parts (b.region)."""
    if (width, height) != (WIDTH, HEIGHT):
        raise ValueError(f"the stack's boards are {WIDTH:g} x {HEIGHT:g} mm")
    nl = nl or mini_boards.netlist(name)
    b = B.Board(f"mini-{name}-{style}", width, height, layers=layers, rules=rules)
    sites = {p.ref: p for p, _ in site_parts(name)}
    conns = []
    for ref, fp, pinmap in nl.connectors:
        conns.append((sites[ref], dict(pinmap)))
    pwr = power_part()
    conns.append((pwr, dict(POWER_PINS)))
    for p in physical.parts(nl, style, connectors=conns, cap=cap):
        b.add(p)
    for i, (x, y) in enumerate(holes()):
        h = B.Part(f"H{i + 1}", HOLE, {}, value="M3", kind="mech")
        h.place(x, y, 0)
        h.fixed = True
        b.add(h)
        k = HOLE_KEEP
        b.add_keepout(x - k, y - k, x + k, y + k, "standoff",
                      no=("tracks", "vias", "footprints", "copperpour"), allow=("mech",))
    sides = ["F"] + (["B"] if style == "smd" or any(p.side == "B" for p, _ in conns) else [])
    n = 0
    for side in sides:
        for x, y in FIDUCIALS:
            n += 1
            fid = B.Part(f"FID{n}", cards.FIDUCIAL, {}, value="fiducial", kind="mech")
            fid.place(x, y, 0, side)
            fid.fixed = True
            b.add(fid)
    for x, y in FIDUCIALS:
        r = FIDUCIAL_KEEP
        b.add_keepout(x - r, y - r, x + r, y + r, "fiducial", allow=("mech",))
    b.pin_maps = [(p.ref, m) for p, m in conns]
    b.netlist = nl
    b.style = style
    # the parts' region: inside the headers along the edges
    x0, y0, x1, y1 = GAP, GAP, width - GAP, height - GAP
    for p, _ in conns:
        e = getattr(p, "edge", None)
        c = p.courtyard()
        if e == "N":
            y0 = max(y0, c[3] + GAP)
        elif e == "S":
            y1 = min(y1, c[1] - GAP)
        elif e == "W":
            x0 = max(x0, c[2] + GAP)
        elif e == "E":
            x1 = min(x1, c[0] - GAP)
    b.region = (x0, y0, x1, y1)
    return b


# ---- the delays across the stack ------------------------------------------------------

# the io board isn't designed: each of its pins on a net is IO_MM of track
# from the net's headers there, and the net has IO_PER_PIN more of track
# for each pin after the first (studies of the routed boards set them)
IO_MM = 120.0
IO_PER_PIN = 25.0
PF_OFF = 8.0                    # a three-state output that's off, on a bus
NS_PER_PF = 0.05                # a load's extra delay over 50 pF, where wires.py has no
                                # figure for the part's family (22V10s, memories, devices)
CLOCKS = mini_boards.CLOCKS


def folder(name, style="smd", layers=6):
    return os.path.join(OUT, f"mini-{name}-{style}-{int(WIDTH)}x{int(HEIGHT)}-{layers}L-F")


def routed(names=("cpu1", "cpu2"), style="smd", layers=6, a=None):
    """{board: (Board read back from its folder, its netlist)} for the
    boards built (`heron pcb build mini-<board>`)."""
    out = {}
    for n in names:
        path = os.path.join(folder(n, style, layers), "board.kicad_pcb")
        if not os.path.exists(path):
            raise FileNotFoundError(f"{path}: build it first (heron pcb build mini-{n})")
        b = B.read_kicad(path)
        b.style = style
        out[n] = (b, mini_boards.board_netlist(n, a))
    return out


def _family_ns(part):
    fam = wires._family(part)
    return wires.NS_PER_PF.get(fam, NS_PER_PF) if fam else NS_PER_PF


def delays(built, a=None):
    """The nets across the stack, from the routed boards `built`
    (routed()) and the cables, the io board's side estimated: {"nets":
    {net: {"boards", "pF", "track_mm" {board: mm}, "cables", "drivers"
    {"ref.pin": {"board", "load_ps", "flight" {"ref.pin": ps}}}}},
    "delays": [[ref, pin, net, ps, the pin's kind]] for the simulation's
    netlist, "net delays" {net: {"driver": ps, "load": ps}} (the most of
    each on the net, for chips another netlist names otherwise), "on"
    {ref: [nets]}: each chip's nets that have delays}. studies/mini/boards.py's pcb_delays() puts them on a
    netlist.

    The back-annotation, as wires.back_annotate()'s but for every driver
    of a bus and every board: each driving pin is late by its load (the
    net's pF over the datasheets' 50, at its family's ns/pF) and its
    flight to its nearest input, or to its farthest bidirectional pin
    if that is later (a bus's other transceivers and memories, which a
    wire element can't sit in front of); each input further along by the
    rest of its flight from the driver that reaches it latest. The clocks
    (CLOCKS) are in "nets" but not in "delays": the timing takes them as
    its reference, each board's through a buffer of matched delay."""
    from heron.studies.mini import parts as mini_parts
    a = a or mini_boards.default()
    nl = a.nl
    sig = mini_boards.signal_nets(nl)
    cross = mini_boards.crossing(a)
    cons = mini_boards.connectors(a)
    # each board's copper, and its pads by logical pin
    copper, pad_of = {}, {}
    for name, (rb, bnl) in built.items():
        copper[name] = wires.copper(rb)
        pad_of[name] = {(r, pin): pad for (r, pad), pin in wires.pins(rb, bnl).items()}
    # the headers' pads by net, per board: [(ref, pad, other board, cable)]
    heads = defaultdict(list)
    for c in cons:
        for pad, net in c["pinmap"].items():
            if net != "GND":
                heads[(c["board"], net)].append((c["ref"], pad, c["to"], c["cable"]))
    out_nets, back, per_net = {}, {}, {}
    for net, pins in sorted(sig.items()):
        boards_on = sorted({a.board_of[r] for r, _ in pins}, key=STACK.index)
        if not set(boards_on) & set(copper):
            continue                    # the io board's own: not designed yet
        bname = {b: (f"BUS.{net}" if net in cross else net) for b in boards_on}
        adj = defaultdict(list)

        def edge(u, v, ps):
            adj[u].append((v, ps))
            adj[v].append((u, ps))
        track_mm, pf = {}, 0.0
        for b in boards_on:
            if b in copper:
                g, length, cap, _ = copper[b]
                for u, vs in g.get(bname[b], {}).items():
                    for v, ps in vs:
                        adj[(b, u)].append(((b, v), ps))
                track_mm[b] = round(length.get(bname[b], 0.0), 1)
                pf += cap.get(bname[b], 0.0)
            else:
                n = sum(1 for r, _ in pins if a.board_of[r] == b)
                track_mm[b] = IO_MM + IO_PER_PIN * max(n - 1, 0)
                pf += track_mm[b] * wires.PF_PER_MM["inner"]
        cables = set()
        for b in boards_on:
            for ref, pad, other, cable in heads.get((b, net), ()):
                if b == STACK[min(STACK.index(b), STACK.index(other))]:
                    lo, hi = b, other
                else:
                    lo, hi = other, b
                here = (b, ("pad", ref, pad)) if b in copper else (b, "hub")
                there_ref = f"J_{b}_{ref.rsplit('_', 1)[1]}"
                there = (other, ("pad", there_ref, pad)) if other in copper else (other, "hub")
                ps = cable_ps(lo, hi)
                if b not in copper:
                    ps += IO_MM * wires.PS_PER_MM["inner"] / 2
                if other not in copper:
                    ps += IO_MM * wires.PS_PER_MM["inner"] / 2
                edge(here, there, ps)
                if cable not in cables:
                    cables.add(cable)
                    pf += cable_pf(lo, hi)

        def node(r, p):
            b = a.board_of[r]
            if b in copper:
                pad = pad_of[b].get((r, p))
                return (b, ("pad", r, pad)) if pad else None
            n = (b, ("pin", r, p))
            if not adj.get(n):
                edge(n, (b, "hub"), IO_MM * wires.PS_PER_MM["inner"] / 2)
            return n
        kinds = {(r, p): nl.refs[r].kind(p) for r, p in pins}
        nodes = {(r, p): node(r, p) for r, p in pins}
        srcs = [k for k in pins if kinds[k] in ("out", "tri", "io")]
        drivers = [k for k in pins if kinds[k] in ("out", "tri")]
        for k, kind in kinds.items():
            pf += {"in": wires.PF_INPUT, "io": wires.PF_IO}.get(kind, 0.0)
        pf += PF_OFF * max(len(drivers) - 1, 0)
        info = {"boards": boards_on, "pF": round(pf, 1), "track_mm": track_mm,
                "cables": sorted(cables), "drivers": {}}
        flights = {}
        for s in srcs:
            if nodes[s] is None:
                continue
            dist = _dijkstra(adj, nodes[s])
            f = {}
            for k in pins:
                if k != s and nodes[k] is not None and nodes[k] in dist:
                    f[k] = round(dist[nodes[k]])
            flights[s] = f
            part = nl.refs[s[0]].part_number(mini_parts.VARIANT)
            load = round(max(pf - wires.DATASHEET_PF, 0.0) * _family_ns(part) * 1000)
            info["drivers"][f"{s[0]}.{s[1]}"] = {
                "board": a.board_of[s[0]], "load_ps": load,
                "flight": {f"{r}.{p}": ps for (r, p), ps in sorted(f.items())}}
        out_nets[net] = info
        # the back-annotation
        base = {}
        for s, f in flights.items():
            ins = [ps for k, ps in f.items() if kinds[k] == "in"]
            ios = [ps for k, ps in f.items() if kinds[k] == "io"]
            base[s] = max(min(ins, default=0), max(ios, default=0))
        worst_drv, worst_load = 0, 0
        for s in flights:
            ps = info["drivers"][f"{s[0]}.{s[1]}"]["load_ps"] + base[s]
            worst_drv = max(worst_drv, ps)
            if net not in CLOCKS and ps > 0:
                back[s] = ps
        for k in pins:
            if kinds[k] != "in":
                continue
            rest = max((f[k] - base[s] for s, f in flights.items() if k in f), default=0)
            worst_load = max(worst_load, rest)
            if net not in CLOCKS and rest >= wires.MIN_WIRE_PS:
                back[k] = rest
        per_net[net] = {"driver": worst_drv, "load": worst_load}
    on = defaultdict(set)
    for net, pins in sig.items():
        if net in per_net:
            for r, _ in pins:
                on[r].add(net)
    return {"nets": out_nets,
            "delays": sorted([r, p, nl.refs[r].conn[p], ps, nl.refs[r].kind(p)]
                             for (r, p), ps in back.items()),
            "net delays": per_net,
            "on": {r: sorted(n) for r, n in sorted(on.items())}}


def _dijkstra(adj, start):
    import heapq
    dist = {start: 0.0}
    heap = [(0.0, 0, start)]
    k = 0
    while heap:
        d, _, u = heapq.heappop(heap)
        if d > dist.get(u, 1e18):
            continue
        for v, ps in adj.get(u, ()):
            nd = d + ps
            if nd < dist.get(v, 1e18):
                dist[v] = nd
                k += 1
                heapq.heappush(heap, (nd, k, v))
    return dist


# ---- what the routed boards say -------------------------------------------------------


def _pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else 0


def clocks(d, built):
    """The clocks as routed, a row per board they're on: their loads
    there, the copper, and the flights from the driver to the loads
    there."""
    rows = []
    for net in CLOCKS:
        info = d["nets"].get(net)
        if not info:
            continue
        for s, drv in info["drivers"].items():
            per = defaultdict(list)
            for k, ps in drv["flight"].items():
                per[mini_boards.default().board_of[k.split(".")[0]]].append(ps)
            for b, fl in per.items():
                if b not in built:
                    continue
                rows.append({"net": net, "board": b, "driver": s, "driver board": drv["board"],
                             "loads": len(fl), "track_mm": info["track_mm"].get(b, 0),
                             "pF": info["pF"], "first_ns": min(fl) / 1000,
                             "last_ns": max(fl) / 1000, "skew_ns": (max(fl) - min(fl)) / 1000})
    return rows


def summary(d, built, results=None):
    """The routed boards and their delays, as Markdown: the generated
    tables of the report on them."""
    a = mini_boards.default()
    nets = d["nets"]
    out = ["# Heron Mini's CPU boards: the routed delays", "",
           "Generated by `heron pcb mini delays --write` (studies/pcb/mini.py) from the",
           "routed boards: don't edit. The delays themselves are in `delays.json`, beside",
           "this file.", ""]
    if results:
        out += ["## The boards", "",
                "| Board | Parts | Chips | Layers | Slot (mm) | Routed | Track (m) | Vias | "
                "DRC errors | Copper opens/shorts | Netlist differences |",
                "|---|---:|---:|---:|---|---|---:|---:|---:|---|---:|"]
        for n, r in results.items():
            out.append(f"| {n} | {r.get('parts')} | {r.get('chips')} | {r.get('layers')} | "
                       f"{' x '.join(str(v) for v in r.get('pitch', []))} | "
                       f"{'yes' if r.get('routed') else 'no'} | {r.get('track_m')} | "
                       f"{r.get('vias')} | {r.get('drc_errors')} | "
                       f"{r.get('copper_opens')}/{r.get('copper_shorts')} | "
                       f"{r.get('netlist_errors')} |")
        out.append("")
    out += ["## The cables", "",
            f"The boards {STANDOFF:g} mm apart; a 1.27 mm ribbon at {CABLE_PS_PER_MM} ps/mm and "
            f"{CABLE_PF_PER_MM * 1000:g} pF/m, {HEADER_PS} ps and {HEADER_PF:g} pF a header.", "",
            "| Boards | Cables | Headers | Length (mm) | Flight (ns) | pF |",
            "|---|---:|---|---:|---:|---:|"]
    for (lo, hi), edges in SITES.items():
        n = sum(c for _, c in edges)
        how = "facing, vertical" if neighbours(lo, hi) else "right-angle, at the edge"
        out.append(f"| {lo}-{hi} | {n} | {how}, {', '.join(e for e, _ in edges)} | "
                   f"{cable_mm(lo, hi):g} | {cable_ps(lo, hi) / 1000:.2f} | {cable_pf(lo, hi):.1f} |")
    out.append("")
    # flights: the latest load of each driver, on its own board and across
    own, across, loads_pf = [], [], []
    worst = []
    for net, info in nets.items():
        if net in CLOCKS:
            continue
        for s, drv in info["drivers"].items():
            f = drv["flight"]
            if not f:
                continue
            here = [ps for k, ps in f.items() if a.board_of[k.split(".")[0]] == drv["board"]]
            there = [ps for k, ps in f.items() if a.board_of[k.split(".")[0]] != drv["board"]]
            if here:
                own.append(max(here))
            if there:
                across.append(max(there))
            worst.append((max(f.values()) + drv["load_ps"], net, s, drv["board"],
                          max(f.values()), drv["load_ps"], len(info["boards"])))
        loads_pf.append(info["pF"])
    out += ["## Flight times", "",
            "Each driver's flight to its latest load (the clocks apart), on its own board and "
            "on the others:", "",
            "| | Drivers | Median (ns) | 90% (ns) | 99% (ns) | Most (ns) |",
            "|---|---:|---:|---:|---:|---:|"]
    for label, xs in (("on its own board", own), ("on another board", across)):
        out.append(f"| {label} | {len(xs)} | {_pct(xs, 0.5) / 1000:.2f} | {_pct(xs, 0.9) / 1000:.2f} | "
                   f"{_pct(xs, 0.99) / 1000:.2f} | {max(xs, default=0) / 1000:.2f} |")
    out += ["", "The latest, with the driver's load:", "",
            "| Net | Driver | On | Boards | Flight (ns) | Load (ns) | Together (ns) |",
            "|---|---|---|---:|---:|---:|---:|"]
    for tot, net, s, b, fl, ld, nb in sorted(worst, reverse=True)[:20]:
        out.append(f"| {net} | {s} | {b} | {nb} | {fl / 1000:.2f} | {ld / 1000:.2f} | {tot / 1000:.2f} |")
    heavy = sorted(((info["pF"], net, info) for net, info in nets.items() if net not in CLOCKS),
                   reverse=True)[:15]
    out += ["", "## The heaviest nets", "",
            "A load's extra delay over the datasheets' 50 pF: 0.05 ns/pF for 74F, 74ABT and "
            "the parts without a figure (22V10s, memories), 0.04 for 74ACT, 0.08 for 74HCT.", "",
            "| Net | Boards | Pins | Track (mm) | pF | Load (ns) |",
            "|---|---|---:|---:|---:|---:|"]
    sig = mini_boards.signal_nets(a.nl)
    for pf, net, info in heavy:
        ld = max((v["load_ps"] for v in info["drivers"].values()), default=0)
        out.append(f"| {net} | {'+'.join(info['boards'])} | {len(sig[net])} | "
                   f"{sum(info['track_mm'].values()):.0f} | {pf:.0f} | {ld / 1000:.1f} |")
    out += ["", "## The clocks", "",
            "Left out of the timing, which takes each board's clock as its reference, as "
            "through a buffer of matched delay on each board (not in the netlist yet). As "
            "routed, one net from its driver; the skew is between the loads on one board:", "",
            "| Clock | Board | Driven from | Loads | Track there (mm) | pF (whole net) | "
            "First load (ns) | Last load (ns) | Skew (ns) |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in clocks(d, built):
        out.append(f"| {r['net']} | {r['board']} | {r['driver']} ({r['driver board']}) | "
                   f"{r['loads']} | {r['track_mm']:.0f} | {r['pF']:.0f} | {r['first_ns']:.2f} | "
                   f"{r['last_ns']:.2f} | {r['skew_ns']:.2f} |")
    out.append("")
    return "\n".join(out)


# ---- density: what fits on A4 --------------------------------------------------------

# the packings tried: (label, style, gaps between courtyards (SMD-THT,
# THT-THT) or None for RFC 0026's, halo, decaps, slot pitches)
PACKINGS = [
    ("SMD, RFC 0026's spacing", "smd", None, 0.8, "under", [(8.25, 14.25)]),
    ("DIP, RFC 0026's spacing", "dip", None, 1.0, "beside", [(11.8, 30.4), (11.8, 15.2)]),
    ("DIP, 1 mm between pads, capacitors under the chips", "dip", (1.0, 0.5), 0.5, "under-all",
     [(10.25, 8.8), (10.25, 13.2)]),
    ("DIP, courtyards touching, capacitors under the chips", "dip", (0.5, 0.0), 0.0, "under-all",
     [(9.75, 7.0), (9.75, 8.8)]),
]


def fit(names=("cpu1", "cpu2")):
    """Whether each board's parts fit on A4 in each packing: [{board,
    packing, pitch, slots, need, unplaced}], the slots free of the
    headers and holes, the slots the parts' blocks need, and how many
    found no block (the grid's own legalisation, without routing)."""
    from heron.infra.pcb import place
    rows = []
    for n in names:
        nl = mini_boards.netlist(n)
        for label, style, gaps, halo, decaps, pitches in PACKINGS:
            cap = packages.FP[style].get("CAP_UNDER") if decaps == "under-all" else None
            b = board(n, style, nl=nl, cap=cap)
            best = None
            for pitch in pitches:
                pl = place.GridPlacer(b, pitch, region=b.region, halo=halo, decaps=decaps,
                                      gaps=gaps, align=decaps != "under-all")
                free = int((pl._blocked() == -1).sum())
                need = sum(pl.spans[p.ref][0] * pl.spans[p.ref][1] for p in pl.movable)
                pl.global_place()
                un = len(pl.legalize())
                r = {"board": n, "packing": label, "pitch": pitch, "slots": free, "need": need,
                     "unplaced": un, "chips": len(pl.movable)}
                if best is None or (un, need / free) < (best["unplaced"], best["need"] / best["slots"]):
                    best = r
            rows.append(best)
    return rows


def fit_table(rows):
    out = ["| Board | Packing | Slot (mm) | Free slots | Slots needed | Share | Without a place |",
           "|---|---|---|---:|---:|---:|---:|"]
    for r in rows:
        out.append(f"| {r['board']} | {r['packing']} | {r['pitch'][0]:g} x {r['pitch'][1]:g} | "
                   f"{r['slots']} | {r['need']} | {r['need'] / r['slots']:.0%} | {r['unplaced']} |")
    return "\n".join(out)


# ---- the commands -----------------------------------------------------------------------

REPORT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "reports", "0044-report-mini-cpu-boards")


def build(names=("cpu1", "cpu2"), style="smd", layers=6, **kw):
    """Build and check the boards: {board: flow.build()'s result}."""
    from . import flow
    out = {}
    for n in names:
        out[n] = flow.build(f"mini-{n}", style, WIDTH, HEIGHT, layers=layers,
                            name=os.path.basename(folder(n, style, layers)), **kw)
    return out


def results(names=("cpu1", "cpu2"), style="smd", layers=6):
    out = {}
    for n in names:
        p = os.path.join(folder(n, style, layers), "result.json")
        if os.path.exists(p):
            with open(p) as f:
                out[n] = json.load(f)
    return out


def write_delays(style="smd", layers=6, report=False):
    """The delays of the routed boards: build/pcb/mini-delays.json (which
    `heron mini hw sta --pcb` and the chip-level runs' --pcb read) and its
    summary beside it; with report, both into report 0044's folder too.
    Returns the paths."""
    built = routed(style=style, layers=layers)
    d = delays(built)
    d = {"generated by": "heron pcb mini delays --write", "style": style, "layers": layers,
         "stack": {"bottom to top": list(STACK), "standoff mm": STANDOFF,
                   "cables": {f"{lo}-{hi}": {"mm": cable_mm(lo, hi), "ps": cable_ps(lo, hi),
                                             "pF": round(cable_pf(lo, hi), 2)}
                              for lo, hi in SITES},
                   "io board": {"mm to a pin": IO_MM, "mm a pin more": IO_PER_PIN}},
         **d}
    text = summary(d, built, results(style=style, layers=layers))
    paths = [mini_boards.PCB_DELAYS, mini_boards.PCB_DELAYS[:-len(".json")] + ".md"]
    if report:
        os.makedirs(REPORT, exist_ok=True)
        paths += [os.path.join(REPORT, "delays.json"), os.path.join(REPORT, "delays.md")]
    for p in paths:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            if p.endswith(".json"):
                json.dump(d, f, indent=0, sort_keys=True)
                f.write("\n")
            else:
                f.write(text)
    return paths


def sta(path=None):
    """The mini's timing analysis with the routed boards' delays and with
    the flat 1.5 ns, each against the plain one, as text."""
    from heron.studies.mini import sta as mini_sta
    path = path or mini_boards.PCB_DELAYS
    nl = mini_sta.build()
    routed_ = mini_boards.pcb_delays(nl, path)
    out = [mini_boards.sta_compare(delays=routed_, what=f"the routed boards' delays ({len(routed_)} "
                                                        "pins; not the clocks)"),
           "", mini_boards.sta_compare()]
    return "\n".join(out)


def main(args):
    if args.action == "build":
        res = build(style=args.style, layers=args.layers)
        for n, r in res.items():
            print(n, json.dumps({k: r.get(k) for k in (
                "routed", "conflicted", "track_m", "vias", "netlist_errors", "keepout_errors",
                "copper_opens", "copper_shorts", "drc_errors", "drc_unconnected",
                "ipc356_errors", "seconds")}))
        return 0 if all(r.get("routed") and not r.get("netlist_errors") for r in res.values()) else 1
    if args.action == "sites":
        errs = check_sites()
        for e in errs:
            print(e)
        print(f"{len(errs)} differences between the boards' headers")
        return 1 if errs else 0
    if args.action == "delays":
        for p in write_delays(args.style, args.layers, report=args.write):
            print(p)
        return 0
    if args.action == "sta":
        print(sta(args.file))
        return 0
    if args.action == "fit":
        print(fit_table(fit()))
        return 0
    return 2
