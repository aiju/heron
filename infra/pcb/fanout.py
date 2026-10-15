"""Power fanout: every surface pad on a plane's net gets a via just
beyond its outer end, and a short wide track to it, so the planes feed it
and the router never sees the supply nets."""

import math


def fanout(board, gap=0.25):
    """Add the vias and tracks; returns how many pads were fanned out."""
    planes = set(board.planes.values())
    r = board.rules
    n = 0
    for part in board.parts.values():
        for pad in part.pads():
            if pad.net not in planes or pad.layers == "*" or not pad.layers:
                continue
            layer = pad.layers[0]
            # outward: for a small part, away from its centre; for a
            # chip, from its centre through the pad along the pad's long axis
            if len(part.fp.pads) <= 4:
                ax, ay = pad.x - part.x, pad.y - part.y
                dd = math.hypot(ax, ay) or 1.0
                ax, ay = ax / dd, ay / dd
                half = abs(ax) * max(pad.extent()[0], 0) + abs(ay) * pad.extent()[1]
            else:
                a = math.radians(pad.angle)
                ax, ay = math.cos(a), -math.sin(a)
                if pad.h > pad.w:
                    ax, ay = -ay, ax
                half = max(pad.w, pad.h) / 2
                if (pad.x - part.x) * ax + (pad.y - part.y) * ay < 0:
                    ax, ay = -ax, -ay
            d = half + r["via_dia"] / 2 + gap
            vx, vy = pad.x + ax * d, pad.y + ay * d
            w = min(r["power_track"], min(pad.w, pad.h))
            board.tracks.append((layer, pad.x, pad.y, vx, vy, w, pad.net))
            board.vias.append((vx, vy, r["via_dia"], r["via_drill"], pad.net))
            n += 1
    return n
