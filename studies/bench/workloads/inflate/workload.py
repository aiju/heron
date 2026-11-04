"""Decompression, as a system does it for compressed files and images:
the stand-in for gunzip, an archiver and a PNG viewer's decoder.

inflate.h has the outline. The archive linked in (made by make_data.py,
and committed, since the compressed bytes depend on the zlib Python has)
holds text and a log compressed by zlib and gzip at their usual levels,
a table, a file stored uncompressed, and a PNG of a desktop. Each is
inflated (RFC 1951: stored, fixed and dynamic Huffman blocks into a 32 KB
window, with table lookups for short codes, as zlib does) and checked as
its container says: Adler-32 for zlib, CRC-32 and the length for gzip,
each chunk's CRC-32 for PNG, whose rows are then unfiltered (Sub, Up,
Average and Paeth). Two plain files go the other way, through an LZ77
compressor with hash chains and the fixed Huffman codes, as an
archiver's fast levels compress, and back through inflate. The results
are each file's checksum (for a PNG, the CRC-32 of its pixels) and, for
the round trips, the compressed size.

SCALE picks the archive: 100 has seven files, about ten times as big as
10's, which inflate to 24 KB; 1, for the `test` budget, four of them,
about 500 bytes.

Where the time goes, at `small`: half in inflate, most of it in the loop
that decodes a block's symbols and copies its matches; a quarter in the
containers, CRC-32 and Adler-32 over every byte and the PNG unfiltering;
a fifth in the compressor, finding matches along the hash chains and
sending codes. At `test`, the files are so small that building each
block's Huffman tables (and the compressor's fixed ones) takes the most.
"""
import os

TITLE = "inflate: zlib, gzip and PNG files, and deflate and back"
PART = "c"
CATEGORY = "tools"
SOURCES = ["main.c", "inflate.c", "deflate.c", "formats.c"]
SIZES = {"test": {"SCALE": 1}, "small": {"SCALE": 10}, "ref": {"SCALE": 100}}
HERE = os.path.dirname(os.path.abspath(__file__))


def data(p):
    with open(os.path.join(HERE, f"archive-{p['SCALE']}.bin"), "rb") as f:
        return {"archive": f.read()}
