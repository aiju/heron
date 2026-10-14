"""Make the study's fonts from DejaVu Sans and DejaVu Sans Mono (Bitstream
Vera license, see LICENSE.txt). The outputs are committed; this only needs
running again to change them. It needs the DejaVu fonts (the
fonts-dejavu-core package on Debian) and, for the bitmap fonts, Pillow.

    python3 studies/graphics/fonts/make_fonts.py [--dejavu DIR]

- sans.ttf: DejaVu Sans cut down to the printable ASCII characters, with
  the tables a renderer needs (no hinting, kerning or layout tables, and
  the glyphs' hinting instructions removed).
- sans12.txt, mono12.txt: bitmap fonts, DejaVu Sans and DejaVu Sans Mono
  at 12 pixels per em, rendered by FreeType with its hinting and without
  anti-aliasing. The format is described at the top of each file.
"""

import argparse
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
CHARS = range(32, 127)


# ---- reading TrueType ----

def tables(data):
    n = struct.unpack(">H", data[4:6])[0]
    out = {}
    for i in range(n):
        tag, _, off, length = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
        out[tag.decode("latin-1")] = data[off:off + length]
    return out


def cmap_format4(t):
    cm = t["cmap"]
    n = struct.unpack(">H", cm[2:4])[0]
    for i in range(n):
        pid, eid, off = struct.unpack(">HHI", cm[4 + 8 * i:12 + 8 * i])
        if (pid, eid) == (3, 1) and struct.unpack(">H", cm[off:off + 2])[0] == 4:
            return cm[off:]
    raise ValueError("no Windows Unicode format 4 cmap")


def glyph_index(sub, c):
    segx2 = struct.unpack(">H", sub[6:8])[0]
    for i in range(segx2 // 2):
        end = struct.unpack(">H", sub[14 + 2 * i:16 + 2 * i])[0]
        if end < c:
            continue
        start = struct.unpack(">H", sub[16 + segx2 + 2 * i:18 + segx2 + 2 * i])[0]
        delta = struct.unpack(">h", sub[16 + 2 * segx2 + 2 * i:18 + 2 * segx2 + 2 * i])[0]
        ro_pos = 16 + 3 * segx2 + 2 * i
        ro = struct.unpack(">H", sub[ro_pos:ro_pos + 2])[0]
        if c < start:
            return 0
        if ro == 0:
            return (c + delta) & 0xFFFF
        g = struct.unpack(">H", sub[ro_pos + ro + 2 * (c - start):ro_pos + ro + 2 * (c - start) + 2])[0]
        return (g + delta) & 0xFFFF if g else 0
    return 0


def glyph_data(t, gi):
    head = t["head"]
    long_loca = struct.unpack(">h", head[50:52])[0] == 1
    loca = t["loca"]
    if long_loca:
        a, b = struct.unpack(">II", loca[4 * gi:4 * gi + 8])
    else:
        a, b = (2 * x for x in struct.unpack(">HH", loca[2 * gi:2 * gi + 4]))
    return t["glyf"][a:b]


def strip_instructions(g):
    """A simple glyph without its hinting instructions."""
    if not g:
        return g
    nc = struct.unpack(">h", g[:2])[0]
    if nc < 0:
        raise ValueError("composite glyph")
    p = 10 + 2 * nc
    ilen = struct.unpack(">H", g[p:p + 2])[0]
    return g[:p] + b"\0\0" + g[p + 2 + ilen:]


# ---- writing TrueType ----

def checksum(b):
    b = b + b"\0" * (-len(b) % 4)
    return sum(struct.unpack(f">{len(b) // 4}I", b)) & 0xFFFFFFFF


def build_cmap(gids):
    """A format 4 cmap for printable ASCII, glyph i + 1 for character 32 + i."""
    segs = [(32, 126, gids[0] - 32), (0xFFFF, 0xFFFF, 1)]
    segx2 = 2 * len(segs)
    sub = struct.pack(">HHHHHHH", 4, 0, 0, segx2, 4, 1, 0)
    sub += b"".join(struct.pack(">H", e) for _, e, _ in segs) + b"\0\0"
    sub += b"".join(struct.pack(">H", s) for s, _, _ in segs)
    sub += b"".join(struct.pack(">h", d) for _, _, d in segs)
    sub += b"".join(struct.pack(">H", 0) for _ in segs)
    sub = sub[:2] + struct.pack(">H", len(sub)) + sub[4:]
    return struct.pack(">HHHHI", 0, 1, 3, 1, 12) + sub


def build_name(t):
    """The original's English Windows names that say what the font is and
    its license."""
    nm = t["name"]
    count, sto = struct.unpack(">HH", nm[2:6])[0], struct.unpack(">H", nm[4:6])[0]
    recs = []
    for i in range(count):
        pid, eid, lid, nid, ln, off = struct.unpack(">HHHHHH", nm[6 + 12 * i:18 + 12 * i])
        if (pid, eid, lid) == (3, 1, 0x409) and nid in (0, 1, 2, 3, 4, 5, 6, 13, 14):
            s = nm[sto + off:sto + off + ln]
            if nid == 5:
                s = (s.decode("utf-16-be") + "; printable ASCII only, no hinting").encode("utf-16-be")
            recs.append((nid, s))
    head = struct.pack(">HHH", 0, len(recs), 6 + 12 * len(recs))
    strings = b""
    for nid, s in recs:
        head += struct.pack(">HHHHHH", 3, 1, 0x409, nid, len(s), len(strings))
        strings += s
    return head + strings


def subset(src):
    data = open(src, "rb").read()
    t = tables(data)
    sub = cmap_format4(t)
    nh = struct.unpack(">H", t["hhea"][34:36])[0]

    def metrics(gi):
        k = min(gi, nh - 1)
        adv = struct.unpack(">H", t["hmtx"][4 * k:4 * k + 2])[0]
        lsb = struct.unpack(">h", t["hmtx"][4 * nh + 2 * (gi - nh):4 * nh + 2 * (gi - nh) + 2])[0] \
            if gi >= nh else struct.unpack(">h", t["hmtx"][4 * gi + 2:4 * gi + 4])[0]
        return adv, lsb
    old = [0] + [glyph_index(sub, c) for c in CHARS]
    glyf, loca, hmtx = b"", [], b""
    for gi in old:
        loca.append(len(glyf))
        g = strip_instructions(glyph_data(t, gi))
        glyf += g + b"\0" * (-len(g) % 4)
        hmtx += struct.pack(">Hh", *metrics(gi))
    loca.append(len(glyf))
    n = len(old)
    head = bytearray(t["head"])
    head[8:12] = b"\0\0\0\0"                        # checkSumAdjustment, set below
    head[50:52] = struct.pack(">h", 1)              # long loca
    hhea = bytearray(t["hhea"])
    hhea[34:36] = struct.pack(">H", n)
    maxp = bytearray(t["maxp"])
    maxp[4:6] = struct.pack(">H", n)
    maxp[26:28] = b"\0\0"                           # maxSizeOfInstructions
    post = struct.pack(">IiHHIIIII", 0x00030000, 0, 0, 0, 0, 0, 0, 0, 0)
    out = {
        "OS/2": t["OS/2"], "cmap": build_cmap(list(range(1, n))), "glyf": glyf,
        "head": bytes(head), "hhea": bytes(hhea), "hmtx": hmtx,
        "loca": b"".join(struct.pack(">I", x) for x in loca), "maxp": bytes(maxp),
        "name": build_name(t), "post": post,
    }
    tags = sorted(out)
    nt = len(tags)
    es = 1 << (nt.bit_length() - 1)
    font = struct.pack(">IHHHH", 0x00010000, nt, 16 * es, es.bit_length() - 1, 16 * nt - 16 * es)
    off = 12 + 16 * nt
    body = b""
    for tag in tags:
        b = out[tag]
        font += struct.pack(">4sIII", tag.encode(), checksum(b), off + len(body), len(b))
        body += b + b"\0" * (-len(b) % 4)
    font += body
    adj = (0xB1B0AFBA - checksum(font)) & 0xFFFFFFFF
    head_off = 12 + 16 * nt + sum(len(out[x]) + (-len(out[x]) % 4) for x in tags[:tags.index("head")])
    font = font[:head_off + 8] + struct.pack(">I", adj) + font[head_off + 12:]
    return font


# ---- bitmap fonts ----

HEADER = """\
# A bitmap font for the graphics study, made by make_fonts.py from {name}
# at {size} pixels per em, rendered by FreeType with its hinting and without
# anti-aliasing. DejaVu fonts: Bitstream Vera license, see LICENSE.txt.
#
# "font ascent A descent D" gives the line's extent above and below the
# baseline. Each "char C adv A box X Y W H" is followed by H rows of W
# pixels ('#' set); the box's top left is X right of the pen and Y below
# the baseline (negative: above), and the pen then moves A to the right.
"""


def bitmap_font(path, size, name):
    from PIL import Image, ImageDraw, ImageFont
    f = ImageFont.truetype(path, size)
    ascent, descent = f.getmetrics()
    lines = [HEADER.format(name=name, size=size), f"font ascent {ascent} descent {descent}"]
    for c in CHARS:
        ch = chr(c)
        im = Image.new("1", (4 * size, 4 * size), 0)
        d = ImageDraw.Draw(im)
        d.fontmode = "1"
        ox, oy = size, 2 * size                     # the pen, on the baseline
        d.text((ox, oy), ch, font=f, fill=1, anchor="ls")
        adv = round(f.getlength(ch))
        box = im.getbbox()
        if box is None:
            lines.append(f"char {c} adv {adv} box 0 0 0 0")
            continue
        x0, y0, x1, y1 = box
        lines.append(f"char {c} adv {adv} box {x0 - ox} {y0 - oy} {x1 - x0} {y1 - y0}")
        for y in range(y0, y1):
            lines.append("".join("#" if im.getpixel((x, y)) else "." for x in range(x0, x1)))
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--dejavu", default="/usr/share/fonts/truetype/dejavu")
    a = p.parse_args()
    sans = os.path.join(a.dejavu, "DejaVuSans.ttf")
    mono = os.path.join(a.dejavu, "DejaVuSansMono.ttf")
    with open(os.path.join(HERE, "sans.ttf"), "wb") as f:
        f.write(subset(sans))
    with open(os.path.join(HERE, "sans12.txt"), "w") as f:
        f.write(bitmap_font(sans, 12, "DejaVu Sans"))
    with open(os.path.join(HERE, "mono12.txt"), "w") as f:
        f.write(bitmap_font(mono, 12, "DejaVu Sans Mono"))
    for n in ("sans.ttf", "sans12.txt", "mono12.txt"):
        print(f"wrote {n}: {os.path.getsize(os.path.join(HERE, n))} bytes")


if __name__ == "__main__":
    main()
