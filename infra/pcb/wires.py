"""What the routed copper adds to the timing: for every net, its length,
the flight time from its driver to each load along the copper, and the
capacitance its driver sees, from which back_annotate() makes extra
delays for the simulator and the timing analysis.

The copper of a net is a graph: track ends, vias and pads are nodes,
tracks and vias are edges. A driver's pad is found from the netlist (an
output or three-state pin); the delay to each load is the shortest path
over the net's copper at the propagation speed of its layer.

Figures (FR-4, a common 1.6 mm six-layer stack, 0.127 mm tracks): about
6.9 ps/mm and 1.3 pF/cm inside (stripline), 5.9 ps/mm and 0.9 pF/cm on the
outer layers (microstrip); 4 pF a CMOS or bipolar input, 8 pF a
bidirectional pin. Datasheet delays are given for 50 pF; each pF more
adds about 0.05 ns to a 74F or 74ABT output and 0.08 ns to a 74HCT one.
"""

import heapq
import math
from collections import defaultdict

PS_PER_MM = {"outer": 5.9, "inner": 6.9}
PF_PER_MM = {"outer": 0.09, "inner": 0.13}
PF_INPUT = 4.0
PF_IO = 8.0
DATASHEET_PF = 50.0
NS_PER_PF = {"74F": 0.05, "74ABT": 0.05, "74ACT": 0.04, "74HCT": 0.08, "74LS": 0.07, "74S": 0.05}
VIA_MM = 1.6


def _family(part_number):
    for fam in ("74ABT", "74ACT", "74HCT", "74LS", "74F", "74S"):
        if part_number.startswith(fam):
            return fam
    return None


def nets(board, nl):
    """{net: {"length": mm, "pF": total, "driver": (ref, pin) or None,
    "loads": {(ref, pad): ps from the driver}}} for every routed net."""
    outer = {"F.Cu", "B.Cu"}
    planes = set(board.planes.values())
    # copper of each net: nodes are points (rounded to a micron), edges carry ps
    graph = defaultdict(lambda: defaultdict(list))
    length = defaultdict(float)
    cap = defaultdict(float)
    vias = defaultdict(list)
    for (x, y, dia, drill, net) in board.vias:
        if net not in planes:
            vias[net].append((round(x, 3), round(y, 3)))
    segs = defaultdict(list)
    for (layer, x1, y1, x2, y2, w, net) in board.tracks:
        if net not in planes:
            segs[(net, layer)].append(((round(x1, 3), round(y1, 3)), (round(x2, 3), round(y2, 3))))
    for (net, layer), ss in segs.items():
        # split every segment where another one ends on it (a T-junction)
        # or a via is on it, so the graph has a node there
        cuts = {p for s in ss for p in s} | set(vias[net])
        kind = "outer" if layer in outer else "inner"
        for (a, b) in ss:
            on = [a, b]
            for q in cuts:
                if q != a and q != b and _on_segment(q, a, b):
                    on.append(q)
            on.sort(key=lambda q: (q[0] - a[0]) ** 2 + (q[1] - a[1]) ** 2)
            for p, q in zip(on, on[1:]):
                L = math.hypot(q[0] - p[0], q[1] - p[1])
                ps = L * PS_PER_MM[kind]
                graph[net][p + (layer,)].append((q + (layer,), ps))
                graph[net][q + (layer,)].append((p + (layer,), ps))
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            length[net] += L
            cap[net] += L * PF_PER_MM[kind]
    layers = board.copper
    for net, pts in vias.items():
        for (x, y) in pts:
            for la, lb in zip(layers, layers[1:]):
                a, b = (x, y, la), (x, y, lb)
                ps = VIA_MM / (len(layers) - 1) * PS_PER_MM["inner"]
                graph[net][a].append((b, ps))
                graph[net][b].append((a, ps))
    # pads: joined to the track ends that touch them
    kind_of = {}
    for inst in nl.instances:
        for pin, net in inst.conn.items():
            kind_of[(inst.ref, pin)] = inst.type.kind(pin)
    from . import packages
    pin_of = {}
    for inst in nl.instances:
        if inst.type.family == "fixture":
            continue
        for pad, name in packages.pad_map(inst.type.name, getattr(board, "style", "smd")).items():
            pin_of[(inst.ref, pad)] = name
    out = {}
    pads_by_net = defaultdict(list)
    for pad in board.pads():
        if pad.net and pad.net not in planes:
            pads_by_net[pad.net].append(pad)
    for net, pads in pads_by_net.items():
        g = graph[net]
        ends = list(g)
        info = {"length": round(length[net], 1), "driver": None, "loads": {}}
        c = cap[net]
        driver = None
        for pad in pads:
            pin = pin_of.get((pad.part.ref, pad.number))
            k = kind_of.get((pad.part.ref, pin))
            if k in ("out", "tri") and driver is None:
                driver = pad
            elif k == "io":
                c += PF_IO
            elif k == "in":
                c += PF_INPUT
        if driver is None:
            # a bidirectional bus: time it from its first transceiver
            driver = next((p for p in pads if kind_of.get(
                (p.part.ref, pin_of.get((p.part.ref, p.number)))) == "io"), None)
        info["pF"] = round(c, 1)
        if driver is not None:
            info["driver"] = (driver.part.ref, pin_of.get((driver.part.ref, driver.number)))
            # the copper nodes on each pad, and the pad itself as a node
            # joining them (a branch may leave from any point of a pad)
            def touching(pad):
                hx, hy = pad.extent()
                return [e for e in ends if abs(e[0] - pad.x) <= hx + 1e-3
                        and abs(e[1] - pad.y) <= hy + 1e-3 and (pad.layers == "*" or e[2] in pad.layers)]
            for pad in pads:
                key = ("pad", pad.part.ref, pad.number)
                for e in touching(pad):
                    g[key].append((e, 0.0))
                    g[e].append((key, 0.0))
            start = ("pad", driver.part.ref, driver.number)
            dist = {start: 0.0}
            heap = [(0.0, 0, start)]
            k = 0
            while heap:
                d, _, e = heapq.heappop(heap)
                if d > dist.get(e, 1e18):
                    continue
                for f, ps in g[e]:
                    nd = d + ps
                    if nd < dist.get(f, 1e18):
                        dist[f] = nd
                        k += 1
                        heapq.heappush(heap, (nd, k, f))
            for pad in pads:
                if pad is driver:
                    continue
                d = dist.get(("pad", pad.part.ref, pad.number))
                if d is not None:
                    info["loads"][(pad.part.ref, pad.number)] = round(d)
        out[net] = info
    return out


def _on_segment(q, a, b, eps=2e-3):
    (x, y), (x1, y1), (x2, y2) = q, a, b
    if min(x1, x2) - eps <= x <= max(x1, x2) + eps and min(y1, y2) - eps <= y <= max(y1, y2) + eps:
        return abs((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)) <= eps * max(
            abs(x2 - x1) + abs(y2 - y1), 1e-9)
    return False


def back_annotate(nl, wires, variant=None):
    """Extra delays for the netlist's drivers: each driving pin gets its
    net's worst flight time plus the extra load over the datasheet's
    50 pF. Returns {(ref, pin): ps}; apply() puts them on a netlist (as
    the simulator's per-pin delays)."""
    from heron.infra.hw import chips
    variant = variant or chips.DEFAULT_VARIANT
    insts = {i.ref: i for i in nl.instances}
    out = {}
    for net, w in wires.items():
        if not w["driver"]:
            continue
        ref, pin = w["driver"]
        if insts[ref].type.kind(pin) == "io":
            continue          # a bus transceiver: its direction decides; left out
        fam = _family(insts[ref].part_number(variant))
        flight = max(w["loads"].values(), default=0)
        load = max(w["pF"] - DATASHEET_PF, 0.0) * NS_PER_PF.get(fam, 0.0) * 1000
        out[(ref, pin)] = int(flight + load)
    return out


def apply(nl, extra, prefix=""):
    """Put back_annotate()'s delays on a netlist (whose chips may carry a
    prefix: a card's chips in the system are CPU.<ref>)."""
    insts = {i.ref: i for i in nl.instances}
    for (ref, pin), ps in extra.items():
        insts[prefix + ref].add_pin_delay(pin, ps)
