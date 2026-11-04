"""Makes the inflate workload's archives: `python3 make_data.py` writes
archive-N.bin here for each scale N in workload.py's SIZES.

An archive holds what a system decompresses: text and logs compressed
with zlib and gzip at their usual levels (dynamic Huffman blocks), a
small file stored uncompressed in a zlib stream, a PNG image, and plain
files for the compressor's round trip. Its format is in main.c.

The contents come from an LCG of our own, so they are the same
everywhere. The compressed bytes depend on the zlib that Python links
with, so the archives are committed rather than made at build time;
what they decompress to doesn't.
"""

import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))


class Rng:
    def __init__(self, seed):
        self.s = seed & 0xFFFFFFFF

    def next(self):
        self.s = (self.s * 1103515245 + 12345) & 0xFFFFFFFF
        return self.s >> 8

    def below(self, n):
        return self.next() % n

    def zipf(self, n):
        """0..n-1, small ones far more often, roughly as words in text."""
        x = self.below(1 << 16) / (1 << 16)
        return min(n - 1, int(n ** x) - 1)


WORDS = """the of and to a in is it that was for on are as with his they at be
this from have or by one had not but what all were when we there can an
your which their said if do will each about how up out them then she many
some so these would other into has more her two like him see time could no
make than first been its who now people my made over did down only way find
use may water long little very after words called just where most know get
through back much before go good new write our used me man too any day same
right look think also around another came come work three word must because
does part even place well such here take why things help put years different
away again off went old number great tell men say small every found still
between name should home big give air line set own under read last never us
left end along while might next sound below saw something thought both few
those always looked show large often together asked house world going want
school important until form food keep children feet land side without boy
once animals life enough took sometimes four head above kind began almost
live page got earth need far hand high year mother light parts country father
let night following picture being study second eyes soon times story boys
since white days ever paper hard near sentence better best across during today
others however sure means knew try told young miles sun ways thing whole hear
example heard several change answer room sea against top turned learn point
city play toward five using himself usually machine memory processor register
kernel window screen pixel compiler program file system disk bus clock signal
""".split()


def prose(r, n):
    """Paragraphs of sentences, wrapped at 72 columns, about n bytes."""
    out = []
    while sum(len(p) for p in out) < n:
        sentences = []
        for _ in range(r.below(5) + 2):
            words = [WORDS[r.zipf(len(WORDS))] for _ in range(r.below(14) + 4)]
            if r.below(4) == 0:
                words.insert(r.below(len(words)), str(r.below(2000)))
            s = " ".join(words)
            s = s[0].upper() + s[1:] + (". " if r.below(6) else "? ")
            if r.below(5) == 0:
                k = s.find(" ", len(s) // 2)
                if k > 0:
                    s = s[:k] + "," + s[k:]
            sentences.append(s)
        text, line, lines = "".join(sentences), "", []
        for w in text.split():
            if len(line) + len(w) + 1 > 72:
                lines.append(line)
                line = w
            else:
                line = line + " " + w if line else w
        lines.append(line)
        out.append("\n".join(lines) + "\n\n")
    return "".join(out).encode()[:n]


def log(r, n):
    """A system log: timestamps, levels, subsystems, numbers."""
    subsystems = ["sched", "vm", "disk0", "net", "wsys", "init", "sh", "fs"]
    messages = [
        "task {} started on cpu {}",
        "page fault at {:08x} in task {}",
        "read {} blocks from sector {}",
        "packet {} dropped: queue full ({} waiting)",
        "window {} resized to {}x{}",
        "mounted volume {} with {} free blocks",
        "process {} exited with status {}",
        "cache hit rate {}% over {} lookups",
    ]
    out, t = [], 0              # milliseconds since 09:00
    while sum(len(x) for x in out) < n:
        t += r.below(3000)
        level = ["INFO ", "INFO ", "INFO ", "DEBUG", "WARN ", "ERROR"][r.below(6)]
        k = r.below(len(messages))
        args = [r.below(4096) for _ in range(3)]
        args[0] = r.below(1 << 32) if k == 1 else args[0]
        msg = messages[k].format(*args)
        out.append("2026-11-04 %02d:%02d:%02d.%03d %s [%s] %s\n" % (
            t // 3600000 % 24 + 9, t // 60000 % 60, t // 1000 % 60, t % 1000,
            level, subsystems[r.below(len(subsystems))], msg))
    return "".join(out).encode()[:n]


def table(r, n):
    """Comma-separated records, as a program's data file."""
    out = ["id,name,x,y,width,height,colour,flags\n"]
    i = 0
    while sum(len(x) for x in out) < n:
        out.append("%d,%s%d,%d,%d,%d,%d,#%06x,%s\n" % (
            i, WORDS[r.zipf(len(WORDS))], r.below(100), r.below(640), r.below(480),
            r.below(200) + 8, r.below(150) + 8, r.below(1 << 24),
            "|".join(sorted({["visible", "focused", "dirty", "moved"][r.below(4)]
                              for _ in range(r.below(3) + 1)}))))
        i += 1
    return "".join(out).encode()[:n]


def binary(r, n):
    """Bytes that don't compress: what a stored block holds."""
    return bytes(r.below(256) for _ in range(n))


def picture(r, w, h):
    """An RGB picture of a desktop: a gradient background, windows with
    title bars and text-like marks, a disc, and some noise."""
    px = [[(40 + y * 100 // h, 60 + x * 80 // w, 120 + (x + y) * 60 // (w + h))
           for x in range(w)] for y in range(h)]
    for _ in range(max(2, w * h // 900)):
        x0, y0 = r.below(w * 3 // 4), r.below(h * 3 // 4)
        x1, y1 = min(w, x0 + r.below(w // 2) + 8), min(h, y0 + r.below(h // 2) + 8)
        body = (200 + r.below(56), 200 + r.below(56), 200 + r.below(56))
        title = (r.below(100), r.below(100), 100 + r.below(156))
        for y in range(y0, y1):
            for x in range(x0, x1):
                if x in (x0, x1 - 1) or y in (y0, y1 - 1):
                    px[y][x] = (0, 0, 0)
                elif y < y0 + 5:
                    px[y][x] = title
                elif (y - y0) % 4 != 0 and r.below(3) == 0:
                    px[y][x] = (30, 30, 30)
                else:
                    px[y][x] = body
    cx, cy, rad = w * 2 // 3, h // 3, min(w, h) // 5
    for y in range(h):
        for x in range(w):
            if (x - cx) ** 2 + (y - cy) ** 2 <= rad * rad:
                px[y][x] = (230, 120 + (x - cx), 40)
            if r.below(8) == 0:
                p = px[y][x]
                px[y][x] = tuple(max(0, min(255, c + r.below(9) - 4)) for c in p)
    return px


def png(px):
    """A PNG of an RGB picture, each row with the filter that makes its
    bytes smallest in sum, as libpng chooses."""
    h, w = len(px), len(px[0])
    rows = [bytes(c for p in row for c in p) for row in px]
    bpp, raw, prev = 3, bytearray(), bytes(w * 3)

    def paeth(a, b, c):
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        return a if pa <= pb and pa <= pc else b if pb <= pc else c

    for row in rows:
        best = None
        for f in range(5):
            out = bytearray()
            for x in range(len(row)):
                a = row[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                pred = [0, a, b, (a + b) // 2, paeth(a, b, c)][f]
                out.append((row[x] - pred) & 255)
            cost = sum(v if v < 128 else 256 - v for v in out)
            if best is None or cost < best[0]:
                best = (cost, f, out)
        raw += bytes([best[1]]) + best[2]
        prev = row

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))

    z = zlib.compress(bytes(raw), 6)
    # the stream in IDAT chunks of 4 KB, as encoders split it
    idats = b"".join(chunk(b"IDAT", z[i:i + 4096]) for i in range(0, len(z), 4096))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"tEXt", b"Software\0make_data.py") + idats + chunk(b"IEND", b""))


def gz(data, name):
    """gzip with a file name in the header, as gzip(1) writes it."""
    body = zlib.compressobj(9, zlib.DEFLATED, -15)
    deflated = body.compress(data) + body.flush()
    header = b"\x1f\x8b\x08\x08" + struct.pack("<I", 0) + b"\x02\x03" + name.encode() + b"\0"
    return header + deflated + struct.pack("<II", zlib.crc32(data), len(data))


def entry(kind, name, data):
    return kind.encode() + bytes([len(name)]) + name.encode() + struct.pack("<I", len(data)) + data


# The sizes of the files at each scale: bytes, and the picture's width
# and height. The smallest leaves some out, since every file costs the
# building of its Huffman tables, whatever its size.
SCALES = {
    1: dict(notes=200, stored=32, png=(8, 5), readme=80),
    10: dict(notes=6000, syslog=4000, stored=512, png=(48, 36), csv=3000,
             readme=1500, boot=1000),
    100: dict(notes=60000, syslog=40000, stored=4096, png=(160, 120), csv=25000,
              readme=12000, boot=8000),
}


def archive(scale):
    """The archive at a scale."""
    r, z = Rng(1951 + scale), SCALES[scale]
    makers = [
        ("notes", lambda n: entry("z", "notes.txt.z", zlib.compress(prose(r, n), 9))),
        ("syslog", lambda n: entry("g", "syslog.gz", gz(log(r, n), "syslog"))),
        ("stored", lambda n: entry("z", "stored.z", zlib.compress(binary(r, n), 0))),
        ("png", lambda wh: entry("p", "desktop.png", png(picture(r, *wh)))),
        ("csv", lambda n: entry("z", "windows.csv.z", zlib.compress(table(r, n), 6))),
        ("readme", lambda n: entry("r", "readme.txt", prose(r, n))),
        ("boot", lambda n: entry("r", "boot.log", log(r, n))),
    ]
    return b"".join(make(z[key]) for key, make in makers if key in z)


def write(scales):
    for s in scales:
        with open(os.path.join(HERE, f"archive-{s}.bin"), "wb") as f:
            f.write(archive(s))


if __name__ == "__main__":
    scales = [int(a) for a in sys.argv[1:]] or sorted(SCALES)
    write(scales)
