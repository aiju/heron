/* The checksums and the containers around deflate data.

   - zlib (RFC 1950): a two-byte header, the data, and the Adler-32 of
     what it inflates to;
   - gzip (RFC 1952): a header with flags for the optional fields (a
     file name here), the data, then the CRC-32 and length of the
     original;
   - PNG: chunks, each with a CRC-32; the image's rows, each with a
     filter byte, are one zlib stream split across IDAT chunks. They
     are gathered and inflated, and the rows unfiltered.

   Each file's results go out as it is finished: the checksum it was
   checked against, and the number of bytes it inflated to. */

#include <string.h>
#include "bench.h"
#include "inflate.h"

unsigned get32be(const unsigned char *p)
{
    return (unsigned)p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3];
}

unsigned get32le(const unsigned char *p)
{
    return (unsigned)p[3] << 24 | p[2] << 16 | p[1] << 8 | p[0];
}

/* ---- checksums ------------------------------------------------------- */

/* Adler-32: two sums modulo 65521, the second of the first. The modulo
   waits until the sums could overflow: 5552 bytes, as in zlib. */
unsigned adler32(unsigned adler, const unsigned char *p, unsigned n)
{
    unsigned a = adler & 0xffff, b = adler >> 16;
    while (n > 0) {
        unsigned k = n < 5552 ? n : 5552;
        n -= k;
        while (k--) {
            a += *p++;
            b += a;
        }
        a %= 65521;
        b %= 65521;
    }
    return b << 16 | a;
}

/* The remainders of the reflected CRC-32 polynomial, 0xedb88320, for
   each byte, as zlib keeps them: made once, by
       c = n; 8 times: c = c & 1 ? 0xedb88320 ^ c >> 1 : c >> 1  */
static const unsigned crc_table[256] = {
    0x00000000u, 0x77073096u, 0xee0e612cu, 0x990951bau, 0x076dc419u,
    0x706af48fu, 0xe963a535u, 0x9e6495a3u, 0x0edb8832u, 0x79dcb8a4u,
    0xe0d5e91eu, 0x97d2d988u, 0x09b64c2bu, 0x7eb17cbdu, 0xe7b82d07u,
    0x90bf1d91u, 0x1db71064u, 0x6ab020f2u, 0xf3b97148u, 0x84be41deu,
    0x1adad47du, 0x6ddde4ebu, 0xf4d4b551u, 0x83d385c7u, 0x136c9856u,
    0x646ba8c0u, 0xfd62f97au, 0x8a65c9ecu, 0x14015c4fu, 0x63066cd9u,
    0xfa0f3d63u, 0x8d080df5u, 0x3b6e20c8u, 0x4c69105eu, 0xd56041e4u,
    0xa2677172u, 0x3c03e4d1u, 0x4b04d447u, 0xd20d85fdu, 0xa50ab56bu,
    0x35b5a8fau, 0x42b2986cu, 0xdbbbc9d6u, 0xacbcf940u, 0x32d86ce3u,
    0x45df5c75u, 0xdcd60dcfu, 0xabd13d59u, 0x26d930acu, 0x51de003au,
    0xc8d75180u, 0xbfd06116u, 0x21b4f4b5u, 0x56b3c423u, 0xcfba9599u,
    0xb8bda50fu, 0x2802b89eu, 0x5f058808u, 0xc60cd9b2u, 0xb10be924u,
    0x2f6f7c87u, 0x58684c11u, 0xc1611dabu, 0xb6662d3du, 0x76dc4190u,
    0x01db7106u, 0x98d220bcu, 0xefd5102au, 0x71b18589u, 0x06b6b51fu,
    0x9fbfe4a5u, 0xe8b8d433u, 0x7807c9a2u, 0x0f00f934u, 0x9609a88eu,
    0xe10e9818u, 0x7f6a0dbbu, 0x086d3d2du, 0x91646c97u, 0xe6635c01u,
    0x6b6b51f4u, 0x1c6c6162u, 0x856530d8u, 0xf262004eu, 0x6c0695edu,
    0x1b01a57bu, 0x8208f4c1u, 0xf50fc457u, 0x65b0d9c6u, 0x12b7e950u,
    0x8bbeb8eau, 0xfcb9887cu, 0x62dd1ddfu, 0x15da2d49u, 0x8cd37cf3u,
    0xfbd44c65u, 0x4db26158u, 0x3ab551ceu, 0xa3bc0074u, 0xd4bb30e2u,
    0x4adfa541u, 0x3dd895d7u, 0xa4d1c46du, 0xd3d6f4fbu, 0x4369e96au,
    0x346ed9fcu, 0xad678846u, 0xda60b8d0u, 0x44042d73u, 0x33031de5u,
    0xaa0a4c5fu, 0xdd0d7cc9u, 0x5005713cu, 0x270241aau, 0xbe0b1010u,
    0xc90c2086u, 0x5768b525u, 0x206f85b3u, 0xb966d409u, 0xce61e49fu,
    0x5edef90eu, 0x29d9c998u, 0xb0d09822u, 0xc7d7a8b4u, 0x59b33d17u,
    0x2eb40d81u, 0xb7bd5c3bu, 0xc0ba6cadu, 0xedb88320u, 0x9abfb3b6u,
    0x03b6e20cu, 0x74b1d29au, 0xead54739u, 0x9dd277afu, 0x04db2615u,
    0x73dc1683u, 0xe3630b12u, 0x94643b84u, 0x0d6d6a3eu, 0x7a6a5aa8u,
    0xe40ecf0bu, 0x9309ff9du, 0x0a00ae27u, 0x7d079eb1u, 0xf00f9344u,
    0x8708a3d2u, 0x1e01f268u, 0x6906c2feu, 0xf762575du, 0x806567cbu,
    0x196c3671u, 0x6e6b06e7u, 0xfed41b76u, 0x89d32be0u, 0x10da7a5au,
    0x67dd4accu, 0xf9b9df6fu, 0x8ebeeff9u, 0x17b7be43u, 0x60b08ed5u,
    0xd6d6a3e8u, 0xa1d1937eu, 0x38d8c2c4u, 0x4fdff252u, 0xd1bb67f1u,
    0xa6bc5767u, 0x3fb506ddu, 0x48b2364bu, 0xd80d2bdau, 0xaf0a1b4cu,
    0x36034af6u, 0x41047a60u, 0xdf60efc3u, 0xa867df55u, 0x316e8eefu,
    0x4669be79u, 0xcb61b38cu, 0xbc66831au, 0x256fd2a0u, 0x5268e236u,
    0xcc0c7795u, 0xbb0b4703u, 0x220216b9u, 0x5505262fu, 0xc5ba3bbeu,
    0xb2bd0b28u, 0x2bb45a92u, 0x5cb36a04u, 0xc2d7ffa7u, 0xb5d0cf31u,
    0x2cd99e8bu, 0x5bdeae1du, 0x9b64c2b0u, 0xec63f226u, 0x756aa39cu,
    0x026d930au, 0x9c0906a9u, 0xeb0e363fu, 0x72076785u, 0x05005713u,
    0x95bf4a82u, 0xe2b87a14u, 0x7bb12baeu, 0x0cb61b38u, 0x92d28e9bu,
    0xe5d5be0du, 0x7cdcefb7u, 0x0bdbdf21u, 0x86d3d2d4u, 0xf1d4e242u,
    0x68ddb3f8u, 0x1fda836eu, 0x81be16cdu, 0xf6b9265bu, 0x6fb077e1u,
    0x18b74777u, 0x88085ae6u, 0xff0f6a70u, 0x66063bcau, 0x11010b5cu,
    0x8f659effu, 0xf862ae69u, 0x616bffd3u, 0x166ccf45u, 0xa00ae278u,
    0xd70dd2eeu, 0x4e048354u, 0x3903b3c2u, 0xa7672661u, 0xd06016f7u,
    0x4969474du, 0x3e6e77dbu, 0xaed16a4au, 0xd9d65adcu, 0x40df0b66u,
    0x37d83bf0u, 0xa9bcae53u, 0xdebb9ec5u, 0x47b2cf7fu, 0x30b5ffe9u,
    0xbdbdf21cu, 0xcabac28au, 0x53b39330u, 0x24b4a3a6u, 0xbad03605u,
    0xcdd70693u, 0x54de5729u, 0x23d967bfu, 0xb3667a2eu, 0xc4614ab8u,
    0x5d681b02u, 0x2a6f2b94u, 0xb40bbe37u, 0xc30c8ea1u, 0x5a05df1bu,
    0x2d02ef8du
};

unsigned crc32(unsigned crc, const unsigned char *p, unsigned n)
{
    crc = ~crc;
    while (n--)
        crc = crc_table[(crc ^ *p++) & 0xff] ^ (crc >> 8);
    return ~crc;
}

/* ---- zlib ------------------------------------------------------------ */

struct check {
    unsigned sum;               /* the Adler-32 or CRC-32 so far */
    unsigned n;
    unsigned char *copy;        /* where to keep the output, or 0 */
    unsigned cap;
};

static void adler_sink(void *ctx, const unsigned char *p, unsigned n)
{
    struct check *c = ctx;
    c->sum = adler32(c->sum, p, n);
    if (c->copy && c->n + n <= c->cap)
        memcpy(c->copy + c->n, p, n);
    c->n += n;
}

static void crc_sink(void *ctx, const unsigned char *p, unsigned n)
{
    struct check *c = ctx;
    c->sum = crc32(c->sum, p, n);
    c->n += n;
}

/* Inflates a zlib stream, keeping the output in copy if that isn't 0;
   *n is the size of the output. */
static int zlib_inflate(const unsigned char *p, unsigned len,
                        unsigned char *copy, unsigned cap, unsigned *n)
{
    struct check c;
    unsigned used, out;
    int err;
    if (len < 6 || (p[0] & 15) != 8 || (p[0] >> 4) > 7 ||
        ((p[0] << 8) | p[1]) % 31 != 0 || (p[1] & 0x20))
        return Z_BAD_HEADER;    /* not deflate, or a preset dictionary */
    c.sum = 1;
    c.n = 0;
    c.copy = copy;
    c.cap = cap;
    err = inflate(p + 2, len - 6, &used, &out, adler_sink, &c);
    *n = out;
    if (err)
        return err;
    if (get32be(p + 2 + used) != c.sum)
        return Z_BAD_CHECK;
    return Z_OK;
}

int zlib_file(const char *name, const unsigned char *p, unsigned len)
{
    unsigned n = 0;
    int err = zlib_inflate(p, len, 0, 0, &n);
    bench_report(name, err ? err : get32be(p + len - 4));
    return err;
}

/* Compresses n bytes into a zlib stream; returns its size, or 0. */
static unsigned zlib_compress(const unsigned char *src, unsigned n,
                       unsigned char *dst, unsigned cap)
{
    unsigned size, a;
    if (cap < 6)
        return 0;
    dst[0] = 0x78;              /* deflate, a 32 KB window */
    dst[1] = 0x01;              /* the fastest level; 0x7801 % 31 == 0 */
    size = deflate(src, n, dst + 2, cap - 6);
    if (size == 0)
        return 0;
    a = adler32(1, src, n);
    dst += 2 + size;
    dst[0] = (unsigned char)(a >> 24);
    dst[1] = (unsigned char)(a >> 16);
    dst[2] = (unsigned char)(a >> 8);
    dst[3] = (unsigned char)a;
    return size + 6;
}

/* The round trip reports the size of the compressed stream. */
int round_trip(const char *name, const unsigned char *p, unsigned len,
               unsigned char *zbuf, unsigned zcap,
               unsigned char *back, unsigned bcap)
{
    unsigned zn = zlib_compress(p, len, zbuf, zcap), n = 0;
    int err;
    if (zn == 0)
        return Z_TOO_BIG;
    err = zlib_inflate(zbuf, zn, back, bcap, &n);
    if (!err && (n != len || memcmp(back, p, len) != 0))
        err = Z_BAD_CHECK;
    bench_report(name, err ? err : zn);
    return err;
}

/* ---- gzip ------------------------------------------------------------ */

enum { FTEXT = 1, FHCRC = 2, FEXTRA = 4, FNAME = 8, FCOMMENT = 16 };

int gzip_file(const char *name, const unsigned char *p, unsigned len)
{
    unsigned pos = 10, used, out;
    struct check c;
    int flags, err;
    if (len < 18 || p[0] != 0x1f || p[1] != 0x8b || p[2] != 8)
        return Z_BAD_HEADER;
    flags = p[3];
    if (flags & FEXTRA)
        pos += 2 + (p[pos] | p[pos + 1] << 8);
    if (flags & FNAME)
        while (pos < len && p[pos++] != 0)
            ;
    if (flags & FCOMMENT)
        while (pos < len && p[pos++] != 0)
            ;
    if (flags & FHCRC)
        pos += 2;
    if (pos + 8 > len)
        return Z_TRUNCATED;
    c.sum = 0;
    c.n = 0;
    c.copy = 0;
    err = inflate(p + pos, len - pos - 8, &used, &out, crc_sink, &c);
    if (!err && (get32le(p + pos + used) != c.sum ||
                 get32le(p + pos + used + 4) != out))
        err = Z_BAD_CHECK;
    bench_report(name, err ? err : c.sum);
    return err;
}

/* ---- PNG ------------------------------------------------------------- */

#define MAXIDAT  (48 * 1024)
#define MAXIMAGE (64 * 1024)

static unsigned char idat[MAXIDAT];         /* the zlib stream, gathered */
static unsigned char image[MAXIMAGE];       /* the rows, with their filter bytes */

static const unsigned char png_signature[8] = { 137, 80, 78, 71, 13, 10, 26, 10 };

static int paeth(int a, int b, int c)
{
    int p = a + b - c;
    int pa = p > a ? p - a : a - p;
    int pb = p > b ? p - b : b - p;
    int pc = p > c ? p - c : c - p;
    if (pa <= pb && pa <= pc)
        return a;
    return pb <= pc ? b : c;
}

/* Undoes the filters in place. Each row is a filter byte, then stride
   bytes; a filter predicts each byte from the byte bpp before it (a),
   the byte above (b) and the one before that (c). */
static int unfilter(unsigned char *rows, int height, int stride, int bpp)
{
    unsigned char *prev = 0;
    int y, x;
    for (y = 0; y < height; y++) {
        unsigned char *row = rows + y * (stride + 1) + 1;
        int filter = row[-1];
        switch (filter) {
        case 0:
            break;
        case 1:                 /* Sub */
            for (x = bpp; x < stride; x++)
                row[x] = (unsigned char)(row[x] + row[x - bpp]);
            break;
        case 2:                 /* Up */
            if (prev)
                for (x = 0; x < stride; x++)
                    row[x] = (unsigned char)(row[x] + prev[x]);
            break;
        case 3:                 /* Average */
            for (x = 0; x < stride; x++) {
                int a = x >= bpp ? row[x - bpp] : 0, b = prev ? prev[x] : 0;
                row[x] = (unsigned char)(row[x] + ((a + b) >> 1));
            }
            break;
        case 4:                 /* Paeth */
            for (x = 0; x < stride; x++) {
                int a = x >= bpp ? row[x - bpp] : 0, b = prev ? prev[x] : 0;
                int c = prev && x >= bpp ? prev[x - bpp] : 0;
                row[x] = (unsigned char)(row[x] + paeth(a, b, c));
            }
            break;
        default:
            return Z_BAD_HEADER;
        }
        prev = row;
    }
    return Z_OK;
}

int png_file(const char *name, const unsigned char *p, unsigned len)
{
    unsigned pos = 8, nidat = 0, width = 0, height = 0, n = 0, crc = 0;
    int bpp = 0, err = Z_OK, y, stride;
    if (len < 8 || memcmp(p, png_signature, 8) != 0)
        return Z_BAD_HEADER;
    /* the chunks: length, type, data and the CRC of type and data */
    while (pos + 12 <= len && !err) {
        unsigned size = get32be(p + pos);
        const unsigned char *type = p + pos + 4, *data = p + pos + 8;
        if (pos + 12 + size > len)
            return Z_TRUNCATED;
        if (crc32(0, type, size + 4) != get32be(data + size))
            return Z_BAD_CHECK;
        if (memcmp(type, "IHDR", 4) == 0) {
            int depth = data[8], color = data[9];
            width = get32be(data);
            height = get32be(data + 4);
            /* 8-bit grey, RGB, grey and alpha, or RGBA, not interlaced */
            bpp = color == 0 ? 1 : color == 2 ? 3 : color == 4 ? 2 : color == 6 ? 4 : 0;
            if (depth != 8 || bpp == 0 || data[12] != 0)
                return Z_BAD_HEADER;
        } else if (memcmp(type, "IDAT", 4) == 0) {
            if (nidat + size > MAXIDAT)
                return Z_TOO_BIG;
            memcpy(idat + nidat, data, size);
            nidat += size;
        } else if (memcmp(type, "IEND", 4) == 0) {
            break;
        }
        pos += 12 + size;
    }
    stride = width * bpp;
    if (bpp == 0 || (stride + 1) * height > MAXIMAGE)
        return Z_TOO_BIG;
    err = zlib_inflate(idat, nidat, image, MAXIMAGE, &n);
    if (!err && n != (stride + 1) * height)
        err = Z_BAD_CHECK;
    if (!err)
        err = unfilter(image, height, stride, bpp);
    /* the pixels' CRC, row by row, past the filter bytes */
    for (y = 0; !err && y < (int)height; y++)
        crc = crc32(crc, image + y * (stride + 1) + 1, stride);
    bench_report(name, err ? err : crc);
    return err;
}
