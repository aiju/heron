"""Routing a placed board with infra's grid router, and its checks.

route() takes a placed board (place.py or floorplan.py) through RFC
0023's flow: the supply pads fanned out to the planes (infra/pcb/fanout),
a plane zone on each plane layer, the signal nets routed by the grid
router (infra/pcb/router, the Rust engine in infra/pcbroute), the board
written as KiCad's and drawn.

The checks need no KiCad (it isn't installed where this was written):

1. **netlist**: the board file read back, each net's pads against the
   netlist's pins on that net (count by count: a pin with no pad, or a
   pad on the wrong net, shows), and the rails;
2. **keep-outs**: no part, track or via where the card's mechanics keep
   them out (infra/pcb/check.keepouts);
3. **copper**: the copper's pieces from its geometry (infra/pcb/copper):
   no short, and every signal net one piece. The planes aren't filled
   without KiCad, so the supply nets' opens through them aren't counted;
4. **clearance**: no two pieces of copper of different nets on a layer
   nearer than the rules' clearance (tracks, vias and pads), which
   KiCad's DRC would check.

KiCad's own DRC and its fab netlist (studies/pcb's flow) need KiCad.
"""

import json
import math
import os
import time
from collections import Counter, defaultdict

from heron.infra.pcb import board as B
from heron.infra.pcb import check, copper, fanout, physical, render, router

from . import place as P


def stats(b):
    """The routed copper's numbers: track length per layer, vias."""
    planes = set(b.planes.values())
    per = Counter()
    for (layer, x1, y1, x2, y2, w, net) in b.tracks:
        if net not in planes:
            per[layer] += math.hypot(x2 - x1, y2 - y1)
    vias = sum(1 for v in b.vias if v[4] not in planes)
    return {"track_m": round(sum(per.values()) / 1000, 2),
            "track_m_by_layer": {k: round(v / 1000, 2) for k, v in per.items()},
            "vias": vias, "supply_vias": len(b.vias) - vias}


def route(b, name="ALU", out=None, **params):
    """Fan out, route and write a placed board into `out` (default
    build/reed_pcb/<board's name>-<n>L/): board.kicad_pcb, board.png,
    result.json. Returns the result."""
    t0 = time.time()
    n_cu = len(b.stackup)
    out = out or os.path.join(P.OUT, f"{b.name}-{n_cu}L")
    os.makedirs(out, exist_ok=True)
    res = {"board": name, "name": b.name, "layers": n_cu,
           "stackup": [f"{l}:{n or 'signal'}" for l, n in b.stackup]}
    res["fanout"] = fanout.fanout(b)
    res["fanout_crowded"] = [f"{r}.{n}" for r, n in b.fanout_crowded]
    b.add_planes()
    sol = router.route(b, **params)
    res["nets"] = len({n for n, pads in b.nets().items()
                       if n not in b.planes.values() and len(pads) > 1})
    res["rounds"] = len(sol["rounds"])
    res["unrouted"] = sorted(set(sol["conflicted"]) | set(sol["failed"]) | set(sol["unreachable"]))
    res["routed"] = not res["unrouted"]
    res.update(stats(b))
    res["seconds_route"] = round(time.time() - t0, 1)
    path = os.path.join(out, "board.kicad_pcb")
    b.write(path)
    render.render(b, os.path.join(out, "board.png"), scale=6, labels=False)
    res["checks"] = checks(b, path, name)
    with open(os.path.join(out, "result.json"), "w") as f:
        json.dump(res, f, indent=1)
    return res


# ---- the checks --------------------------------------------------------------------

def netlist_check(path, name):
    """The board file read back against the netlist: for each net, its
    pads' count against the netlist's pins on it (a 16-bit SRAM's two
    halves share their address and control pins: those count once), and
    the supply pins on the rails. Returns a list of errors."""
    rb = B.read_kicad(path)
    nl = P.netlist(name)
    rails = physical.rails(nl)
    want = Counter()
    for ref, insts, conn in P._groups(nl):
        if insts[0].type.family == "fixture":
            continue
        for pin, net in conn.items():
            net = rails.get(net, net)
            if net in ("VCC", "GND"):
                continue                # rails: tied pins, counted with the supplies below
            want[net] += 1
    have = Counter()
    errs = []
    for p in rb.parts.values():
        for num, net in p.nets.items():
            if net and net not in ("VCC", "GND"):
                have[net] += 1
    for net in sorted(set(want) | set(have)):
        if want[net] != have[net]:
            errs.append(f"{net}: {want[net]} pins in the netlist, {have[net]} pads on the board")
    for p in rb.parts.values():
        if p.kind != "chip" and not p.ref.startswith("U_"):
            continue
        part = p.value
        from heron.infra.pcb import packages
        key = P.PINOUT_OF_PART.get(part)
        if key is None:
            continue
        for rail in ("VCC", "GND"):
            for n in packages.pin_numbers(key).get(rail, []):
                if p.nets.get(str(n)) != rail:
                    errs.append(f"{p.ref}.{n}: {p.nets.get(str(n))}, not {rail}")
    return errs


def clearance_check(b, eps=1e-3):
    """Pieces of copper of different nets on a common layer nearer than
    the rules' clearance: [(net, net, distance, x, y)]."""
    r = b.rules
    gap = r["clearance"] - eps
    items = []
    for pad in b.pads():
        if pad.kind == "np_thru_hole" or not pad.number or not pad.layers:
            continue
        items.append((copper.pad_shape(pad), pad.net))
    for (layer, x1, y1, x2, y2, w, net) in b.tracks:
        items.append((copper.Shape("capsule", [layer], x1=x1, y1=y1, x2=x2, y2=y2, r=w / 2), net))
    for (x, y, dia, drill, net) in b.vias:
        items.append((copper.Shape("capsule", "*", x1=x, y1=y, x2=x, y2=y, r=dia / 2), net))
    cell = 2.0
    grid = defaultdict(list)
    for i, (s, _) in enumerate(items):
        x0, y0, x1, y1 = s.box
        for cx in range(int((x0 - gap) // cell), int((x1 + gap) // cell) + 1):
            for cy in range(int((y0 - gap) // cell), int((y1 + gap) // cell) + 1):
                grid[(cx, cy)].append(i)
    seen = set()
    out = []
    for members in grid.values():
        for a in range(len(members)):
            i = members[a]
            si, ni = items[i]
            for j in members[a + 1:]:
                sj, nj = items[j]
                if ni == nj and ni is not None:
                    continue
                if (i, j) in seen:
                    continue
                seen.add((i, j))
                if not copper._share_layer(si, sj):
                    continue
                bi, bj = si.box, sj.box
                if bi[2] + gap < bj[0] or bj[2] + gap < bi[0] or bi[3] + gap < bj[1] \
                        or bj[3] + gap < bi[1]:
                    continue
                d = copper.distance(si, sj) - si.r - sj.r
                if d < gap:
                    x = (bi[0] + bi[2]) / 2
                    y = (bi[1] + bi[3]) / 2
                    out.append((ni, nj, round(d, 3), round(x, 2), round(y, 2)))
    return out


def checks(b, path, name):
    """The four checks (the module's docstring): counts and a sample of each."""
    res = {}
    errs = netlist_check(path, name)
    res["netlist"] = {"errors": len(errs), "sample": errs[:5]}
    errs = check.keepouts(b)
    res["keepouts"] = {"errors": len(errs), "sample": errs[:5]}
    planes = set(b.planes.values())
    errs = copper.check(b)
    shorts = [e for e in errs if e.startswith("short")]
    opens = [e for e in errs if e.startswith("open") and e.split()[1] not in planes]
    res["copper"] = {"shorts": len(shorts), "opens": len(opens), "sample": (shorts + opens)[:5]}
    cl = clearance_check(b)
    pairs = Counter(tuple(sorted((str(a), str(c)))) for a, c, *_ in cl)
    res["clearance"] = {"errors": len(cl), "sample": [list(x) for x in cl[:8]],
                        "nets": [list(k) for k, _ in pairs.most_common(8)]}
    res["passed"] = not (res["netlist"]["errors"] or res["keepouts"]["errors"] or shorts
                         or opens or cl)
    return res
