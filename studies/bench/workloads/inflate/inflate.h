/* Decompression as a system does it for compressed files and images:
   inflate (RFC 1951) in zlib (RFC 1950), gzip (RFC 1952) and PNG
   containers, and the other way, a deflate compressor of the kind an
   archiver has.

   - inflate.c:  the decompressor: a bit reader, canonical Huffman
                 tables with a one-step lookup for short codes, and the
                 three kinds of block, into a 32 KB window that is
                 passed on to a sink as it fills;
   - deflate.c:  the compressor: LZ77 matching through hash chains, and
                 fixed Huffman codes;
   - formats.c:  Adler-32 and CRC-32, and the containers: zlib, gzip and
                 PNG, whose image is unfiltered after it is inflated;
   - main.c:     the archive of files the harness links in, each
                 decompressed and checked, and a round trip through the
                 compressor. */

#ifndef INFLATE_H
#define INFLATE_H

#define WSIZE 32768             /* the window: the farthest a match reaches */
#define WMASK (WSIZE - 1)

/* Where inflated bytes go: called with each full window, and with what
   is left at the end. */
typedef void (*sink_fn)(void *ctx, const unsigned char *p, unsigned n);

/* What can go wrong; 0 is success. */
enum {
    Z_OK, Z_TRUNCATED, Z_BAD_BLOCK, Z_BAD_STORED, Z_BAD_CODES,
    Z_BAD_SYMBOL, Z_BAD_DISTANCE, Z_BAD_HEADER, Z_BAD_CHECK, Z_TOO_BIG
};

/* Inflates the raw deflate data at in, of at most len bytes. Returns a
   Z_ code; *used is the number of input bytes the data took, and *out
   the number of bytes made. */
int inflate(const unsigned char *in, unsigned len, unsigned *used,
            unsigned *out, sink_fn sink, void *ctx);

/* Deflates n bytes into dst (of size cap), with fixed Huffman codes;
   returns the compressed size, or 0 if it doesn't fit. */
unsigned deflate(const unsigned char *src, unsigned n,
                 unsigned char *dst, unsigned cap);

unsigned adler32(unsigned adler, const unsigned char *p, unsigned n);
unsigned crc32(unsigned crc, const unsigned char *p, unsigned n);

/* The containers: each reports the checksum it checked the file
   against (or, if it failed, the Z_ code) and returns the Z_ code. */
int zlib_file(const char *name, const unsigned char *p, unsigned n);
int gzip_file(const char *name, const unsigned char *p, unsigned n);
int png_file(const char *name, const unsigned char *p, unsigned n);

/* Compresses p into zbuf as a zlib stream, inflates that into back, and
   checks that it came back the same: an archiver's round trip. */
int round_trip(const char *name, const unsigned char *p, unsigned len,
               unsigned char *zbuf, unsigned zcap,
               unsigned char *back, unsigned bcap);

unsigned get32be(const unsigned char *p);
unsigned get32le(const unsigned char *p);

#endif
