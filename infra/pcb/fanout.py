"""Power fanout: every surface pad on a plane's net gets a via and a short
wide track to it, so the planes feed it and the router never sees the
supply nets.

A chip's via goes at its pad's inner end, under the chip's body, if it is
clear there of every pad and via: there it can't meet a neighbour's. If
not (a crowded body), it goes beyond the pad's outer end. A part with two
or four pads has its vias outward from its centre.
"""

import math
from collections import defaultdict

from .copper import _rect_pt_dist, _seg_dist, pad_shape
from .kicadlib import rotate

CELL = 2.0


def _dist(s, x, y):
    """From a point to a pad's copper (a copper.Shape)."""
    if s.kind == "capsule":
        return _seg_dist(s.x1, s.y1, s.x2, s.y2, x, y, x, y) - s.r
    return _rect_pt_dist(s, x, y) - s.r


def fanout(board, gap=0.25):
    """Add the vias and tracks; returns how many pads were fanned out. The
    pads whose via found no clear spot are in board.fanout_crowded (the
    DRC will say more)."""
    planes = set(board.planes.values())
    r = board.rules
    via_r = r["via_dia"] / 2
    # copper a via must keep clear of, bucketed: every pad (a via goes
    # through all layers) and the vias placed so far
    grid = defaultdict(list)

    def bucket(x0, y0, x1, y1, item):
        for cx in range(int(math.floor(x0 / CELL)), int(math.floor(x1 / CELL)) + 1):
            for cy in range(int(math.floor(y0 / CELL)), int(math.floor(y1 / CELL)) + 1):
                grid[(cx, cy)].append(item)

    for part in board.parts.values():
        for pad in part.pads():
            if pad.number and pad.kind != "np_thru_hole":
                s = pad_shape(pad)
                bucket(*s.box, ("pad", s, pad.net))
    for (x, y, dia, drill, net) in board.vias:
        bucket(x, y, x, y, ("via", (x, y, dia / 2), net))

    def clear(x, y, net):
        for cx in range(int(math.floor((x - 1) / CELL)), int(math.floor((x + 1) / CELL)) + 1):
            for cy in range(int(math.floor((y - 1) / CELL)), int(math.floor((y + 1) / CELL)) + 1):
                for kind, s, n in grid.get((cx, cy), ()):
                    if kind == "pad":
                        d = _dist(s, x, y)
                        # no via in or touching a pad; others' pads at a clearance
                        if d < via_r or (n != net and d < via_r + r["clearance"]):
                            return False
                    elif math.hypot(x - s[0], y - s[1]) < via_r + s[2] + r["clearance"]:
                        return False
        return True

    n = 0
    board.fanout_crowded = []
    for part in board.parts.values():
        for pad in part.pads():
            if pad.net not in planes or pad.layers == "*" or not pad.layers:
                continue
            if len(part.fp.pads) <= 4:
                ax, ay = pad.x - part.x, pad.y - part.y
                dd = math.hypot(ax, ay) or 1.0
                ax, ay = ax / dd, ay / dd
                half = abs(ax) * pad.extent()[0] + abs(ay) * pad.extent()[1]
                cands = [(ax, ay, half)]
            else:
                # along the pad's long axis; "out" is away from the body
                a = math.radians(pad.angle)
                ax, ay = math.cos(a), -math.sin(a)
                if pad.h > pad.w:
                    ax, ay = -ay, ax
                half = max(pad.w, pad.h) / 2
                bx, by = part.body_centre()
                ox, oy = rotate(bx, -by if part.side == "B" else by, part.rot)
                if (pad.x - part.x - ox) * ax + (pad.y - part.y - oy) * ay < 0:
                    ax, ay = -ax, -ay
                cands = [(-ax, -ay, half), (ax, ay, half)]       # the inner end first
            spots = [(pad.x + ax * (h + via_r + gap), pad.y + ay * (h + via_r + gap))
                     for ax, ay, h in cands]
            free = [p for p in spots if clear(*p, pad.net)]
            if not free:
                board.fanout_crowded.append((part.ref, pad.number))
            vx, vy = (free or spots)[-1 if not free else 0]
            w = min(r["power_track"], min(pad.w, pad.h))
            board.tracks.append((pad.layers[0], pad.x, pad.y, vx, vy, w, pad.net))
            board.vias.append((vx, vy, r["via_dia"], r["via_drill"], pad.net))
            bucket(vx, vy, vx, vy, ("via", (vx, vy, via_r), pad.net))
            n += 1
    return n
