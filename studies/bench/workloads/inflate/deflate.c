/* Deflate: a compressor of the kind an archiver has, making RFC 1951
   data with the fixed Huffman codes.

   Matches are found as zlib's faster levels find them: a hash of the
   next three bytes picks a chain of the earlier positions with the same
   hash, the chain is searched (up to MAXCHAIN of them, within the 32 KB
   window) for the longest match, and the longest is taken greedily. The
   positions inside a match go into the chains too, so later matches can
   start there, unless the match is long, when only its first few do. */

#include <string.h>
#include "inflate.h"

#define HBITS      10
#define HSIZE      (1 << HBITS)
#define MAXCHAIN   24           /* candidates tried for a match */
#define MINMATCH   3
#define MAXMATCH   258
#define MAXINSERT  16           /* a longer match isn't put in the chains */

static int head[HSIZE];         /* the latest position of each hash, or -1 */
static int prev[WSIZE];         /* the position before, by position & WMASK */

/* The fixed codes, reversed for sending from the low bit, and the code
   of every length and distance. */
static unsigned short lit_code[288];
static unsigned char lit_bits[288];
static unsigned char len_code[MAXMATCH + 1];   /* length -> code - 257 */
static unsigned char dist_code[512];            /* see dcode() */
static int tables_built;

static const short len_base[29] = {
    3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31,
    35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258
};
static const unsigned char len_extra[29] = {
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2,
    3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0
};
static const unsigned short dist_base[30] = {
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193,
    257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145,
    8193, 12289, 16385, 24577
};
static const unsigned char dist_extra[30] = {
    0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6,
    7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13
};

/* A code of up to 12 bits, reversed, a nibble at a time. */
static unsigned reverse(unsigned code, int len)
{
    static const unsigned char nibble[16] = {
        0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15
    };
    unsigned r = nibble[code & 15] << 8 | nibble[code >> 4 & 15] << 4 | nibble[code >> 8 & 15];
    return r >> (12 - len);
}

/* The code of a distance: below 257 from the first half of dist_code,
   by the distance itself; above, from the second half by the distance
   over 128, since codes there cover multiples of 128. */
static int dcode(unsigned dist)
{
    dist--;
    return dist < 256 ? dist_code[dist] : dist_code[256 + (dist >> 7)];
}

/* The next code of the same length, both reversed: one added at the
   top bit, carrying downwards. */
static unsigned next_reversed(unsigned r, int len)
{
    unsigned incr = 1u << (len - 1);
    while (r & incr)
        incr >>= 1;
    return incr ? (r & (incr - 1)) + incr : 0;
}

static void build_tables(void)
{
    /* the fixed literal/length code, in four runs of consecutive codes:
       0-143 in 8 bits from 0x30, 144-255 in 9 from 0x190, 256-279 in 7
       from 0, 280-287 in 8 from 0xc0 */
    static const short run_end[4] = { 144, 256, 280, 288 };
    static const short run_code[4] = { 0x30, 0x190, 0, 0xc0 };
    static const unsigned char run_bits[4] = { 8, 9, 7, 8 };
    int sym = 0, run, code, n;
    for (run = 0; run < 4; run++) {
        unsigned r = reverse(run_code[run], run_bits[run]);
        for (; sym < run_end[run]; sym++) {
            lit_code[sym] = (unsigned short)r;
            lit_bits[sym] = run_bits[run];
            r = next_reversed(r, run_bits[run]);
        }
    }
    for (code = 0; code < 29; code++)
        for (n = 0; n < 1 << len_extra[code]; n++)
            len_code[len_base[code] + n] = (unsigned char)code;
    len_code[MAXMATCH] = 28;    /* 258 has a code of its own */
    for (code = 0; code < 30; code++) {
        unsigned d = dist_base[code], end = d + (1u << dist_extra[code]);
        for (; d < end && d <= 256; d++)
            dist_code[d - 1] = (unsigned char)code;
        for (; d < end; d += 128)
            dist_code[256 + ((d - 1) >> 7)] = (unsigned char)code;
    }
    tables_built = 1;
}

/* ---- the bits out ---------------------------------------------------- */

static unsigned char *out, *out_end;
static unsigned bitbuf;
static int bitcnt;
static int full;                /* the output didn't fit */

static void send(unsigned value, int n)
{
    bitbuf |= value << bitcnt;
    bitcnt += n;
    while (bitcnt >= 8) {
        if (out < out_end)
            *out++ = (unsigned char)bitbuf;
        else
            full = 1;
        bitbuf >>= 8;
        bitcnt -= 8;
    }
}

static void literal(int c)
{
    send(lit_code[c], lit_bits[c]);
}

static void match(unsigned len, unsigned dist)
{
    int code = len_code[len];
    send(lit_code[257 + code], lit_bits[257 + code]);
    send(len - len_base[code], len_extra[code]);
    code = dcode(dist);
    send(reverse(code, 5), 5);
    send(dist - dist_base[code], dist_extra[code]);
}

/* ---- matching -------------------------------------------------------- */

static unsigned hash(const unsigned char *p)
{
    return ((p[0] << 8) ^ (p[1] << 4) ^ p[2]) & (HSIZE - 1);
}

static void insert(const unsigned char *src, int pos)
{
    unsigned h = hash(src + pos);
    prev[pos & WMASK] = head[h];
    head[h] = pos;
}

/* The longest match for pos among the chain's candidates; its length,
   or 0, and its distance in *dist. */
static unsigned longest(const unsigned char *src, int pos, int n, unsigned *dist)
{
    int cand = head[hash(src + pos)], chain = MAXCHAIN;
    unsigned best = 0, max = n - pos < MAXMATCH ? n - pos : MAXMATCH;
    while (cand >= 0 && cand < pos && pos - cand < WSIZE && chain-- > 0) {
        const unsigned char *a = src + cand, *b = src + pos;
        /* quick rejection: the byte that would make it longer, then the
           first */
        if (a[best] == b[best] && a[0] == b[0]) {
            unsigned len = 1;
            while (len < max && a[len] == b[len])
                len++;
            if (len > best) {
                best = len;
                *dist = pos - cand;
                if (len == max)
                    break;
            }
        }
        cand = prev[cand & WMASK];
    }
    return best >= MINMATCH ? best : 0;
}

unsigned deflate(const unsigned char *src, unsigned n,
                 unsigned char *dst, unsigned cap)
{
    unsigned char *start = dst;
    int pos = 0, i;
    if (!tables_built)
        build_tables();
    memset(head, 0xff, sizeof head);    /* every chain empty: -1 */
    out = dst;
    out_end = dst + cap;
    bitbuf = 0;
    bitcnt = 0;
    full = 0;
    send(1, 1);                 /* the last block */
    send(1, 2);                 /* with the fixed codes */
    while (pos < (int)n) {
        unsigned len = 0, dist = 0;
        if (pos + MINMATCH <= (int)n) {
            len = longest(src, pos, n, &dist);
            insert(src, pos);
        }
        if (len) {
            match(len, dist);
            if (len <= MAXINSERT)
                for (i = 1; i < (int)len && pos + i + MINMATCH <= (int)n; i++)
                    insert(src, pos + i);
            pos += len;
        } else {
            literal(src[pos]);
            pos++;
        }
    }
    literal(256);               /* the end of the block */
    send(0, 7);                 /* out to a byte boundary */
    return full ? 0 : out - start;
}
