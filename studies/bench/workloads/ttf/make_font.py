"""Make the ttf workload's font, sans.ttf: the graphics study's DejaVu Sans
cut down to printable ASCII (studies/graphics/fonts/sans.ttf), with a
`kern` table (format 0) added: the pairs of DejaVu Sans's own kern table
whose two characters are both printable ASCII, in the cut-down font's
glyph numbers. The output is committed; this only needs running again to
change it. It needs DejaVu Sans (fonts-dejavu-core on Debian).

    python3 studies/bench/workloads/ttf/make_font.py [--dejavu FILE]

License: LICENSE.txt (Bitstream Vera; DejaVu's changes are public domain).
"""

import argparse
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "..", "..", "..", "graphics", "fonts", "sans.ttf")
DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
CHARS = range(32, 127)


def tables(data):
    n = struct.unpack(">H", data[4:6])[0]
    out = {}
    for i in range(n):
        tag, _, off, length = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
        out[tag.decode("latin-1")] = data[off:off + length]
    return out


def glyph_map(t):
    """Character to glyph number, from the Windows Unicode format 4 cmap."""
    cm = t["cmap"]
    sub = None
    for i in range(struct.unpack(">H", cm[2:4])[0]):
        pid, eid, off = struct.unpack(">HHI", cm[4 + 8 * i:12 + 8 * i])
        if (pid, eid) == (3, 1) and struct.unpack(">H", cm[off:off + 2])[0] == 4:
            sub = cm[off:]
    segx2 = struct.unpack(">H", sub[6:8])[0]
    out = {}
    for c in CHARS:
        for i in range(0, segx2, 2):
            end = struct.unpack(">H", sub[14 + i:16 + i])[0]
            if end < c:
                continue
            start = struct.unpack(">H", sub[16 + segx2 + i:18 + segx2 + i])[0]
            delta = struct.unpack(">h", sub[16 + 2 * segx2 + i:18 + 2 * segx2 + i])[0]
            ro_at = 16 + 3 * segx2 + i
            ro = struct.unpack(">H", sub[ro_at:ro_at + 2])[0]
            if c < start:
                break
            if ro == 0:
                g = (c + delta) & 0xFFFF
            else:
                at = ro_at + ro + 2 * (c - start)
                g = struct.unpack(">H", sub[at:at + 2])[0]
                g = (g + delta) & 0xFFFF if g else 0
            if g:
                out[c] = g
            break
    return out


def kern_pairs(t):
    """{(left, right): value} from a version 0 kern table's format 0 subtables."""
    k = t["kern"]
    out = {}
    off = 4
    for _ in range(struct.unpack(">H", k[2:4])[0]):
        _, length, coverage = struct.unpack(">HHH", k[off:off + 6])
        if coverage >> 8 == 0 and coverage & 1:         # format 0, horizontal
            n = struct.unpack(">H", k[off + 6:off + 8])[0]
            for i in range(n):
                l, r, v = struct.unpack(">HHh", k[off + 14 + 6 * i:off + 20 + 6 * i])
                out[(l, r)] = v
        off += length
    return out


def kern_table(pairs):
    n = len(pairs)
    p = 1
    while 2 * p <= n:
        p *= 2
    sr, es = 6 * p, p.bit_length() - 1
    body = b"".join(struct.pack(">HHh", l, r, v) for (l, r), v in sorted(pairs.items()))
    sub = struct.pack(">HHHHHHH", 0, 14 + len(body), 1, n, sr, es, 6 * n - sr) + body
    return struct.pack(">HH", 0, 1) + sub


def checksum(b):
    b += b"\0" * (-len(b) % 4)
    return sum(struct.unpack(f">{len(b) // 4}I", b)) & 0xFFFFFFFF


def write_font(tabs):
    """A TrueType file from its tables, in tag order, each on 4 bytes."""
    tags = sorted(tabs)
    n = len(tags)
    p = 1
    while 2 * p <= n:
        p *= 2
    head = struct.pack(">IHHHH", 0x10000, n, 16 * p, p.bit_length() - 1, 16 * n - 16 * p)
    off = 12 + 16 * n
    dirs, body = b"", b""
    for tag in tags:
        b = tabs[tag]
        if tag == "head":
            b = b[:8] + b"\0\0\0\0" + b[12:]             # checkSumAdjustment, set below
        dirs += struct.pack(">4sIII", tag.encode("latin-1"), checksum(b), off + len(body), len(b))
        body += b + b"\0" * (-len(b) % 4)
    font = bytearray(head + dirs + body)
    # checkSumAdjustment: 0xB1B0AFBA minus the whole file's checksum
    hoff = struct.unpack(">I", dirs[16 * tags.index("head") + 8:16 * tags.index("head") + 12])[0]
    adj = (0xB1B0AFBA - checksum(bytes(font))) & 0xFFFFFFFF
    font[hoff + 8:hoff + 12] = struct.pack(">I", adj)
    return bytes(font)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dejavu", default=DEJAVU, help="DejaVuSans.ttf")
    a = ap.parse_args()
    with open(BASE, "rb") as f:
        base = tables(f.read())
    with open(a.dejavu, "rb") as f:
        dv = tables(f.read())
    ours, theirs = glyph_map(base), glyph_map(dv)
    back = {g: c for c, g in theirs.items()}
    pairs = {}
    for (l, r), v in kern_pairs(dv).items():
        if l in back and r in back and back[l] in ours and back[r] in ours:
            pairs[(ours[back[l]], ours[back[r]])] = v
    base["kern"] = kern_table(pairs)
    out = os.path.join(HERE, "sans.ttf")
    with open(out, "wb") as f:
        f.write(write_font(base))
    print(f"{out}: {len(pairs)} kerning pairs")


if __name__ == "__main__":
    main()
