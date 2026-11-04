/* Inflate: RFC 1951's deflate format, decoded.

   The input is read a bit at a time from the low end of a 32-bit bit
   buffer, refilled a byte at a time. Huffman codes are canonical, so a
   table is just the number of codes of each length and the symbols in
   code order; decoding goes through a table indexed by the next few
   bits (9 for literals and lengths, as in zlib), which gives the symbol
   and its length for every code that short at once, and walks the
   counts a bit at a time, as puff does, for the few longer ones.

   A block's codes are decoded with the bit buffer and the window
   position in local variables, as zlib's inflate_fast does, since that
   loop is where the time goes.

   Output goes into a 32 KB window, which is the history that matches
   copy from. Each time it fills it is handed to the sink, and it starts
   again from the beginning, the old bytes still behind it for the
   copies to reach. */

#include <string.h>
#include "inflate.h"

#define MAXBITS   15            /* the longest code */
#define FASTBITS  9             /* the most bits a one-step table takes */
#define NLITLEN   288
#define NDIST     30

struct huffman {
    int fastbits;                       /* the one-step table's index bits */
    unsigned short fast[1 << FASTBITS]; /* length << 9 | symbol, or 0 */
    short count[MAXBITS + 1];           /* codes of each length */
    short symbol[NLITLEN];              /* symbols in canonical order */
};

struct state {
    const unsigned char *in;
    unsigned len, pos;          /* input size; next byte to read */
    unsigned bitbuf;            /* bits not yet used, from the low end */
    int bitcnt;
    int overrun;                /* bytes made up past the end of in */
    unsigned char window[WSIZE];
    unsigned wpos;              /* where the next byte goes */
    unsigned total;             /* bytes made */
    sink_fn sink;
    void *ctx;
};

static struct state s;          /* one inflate at a time */
static struct huffman lencode, distcode;
static struct huffman fixed_len, fixed_dist;
static int fixed_built;

/* The base and extra bits of the lengths (codes 257-285) and distances
   (codes 0-29). */
static const short len_base[29] = {
    3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31,
    35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258
};
static const short len_extra[29] = {
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2,
    3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0
};
static const unsigned short dist_base[30] = {
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193,
    257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145,
    8193, 12289, 16385, 24577
};
static const short dist_extra[30] = {
    0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6,
    7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13
};

/* ---- bits ------------------------------------------------------------ */

/* Tops the bit buffer up to at least 25 bits; past the end of the input
   it reads zeros, and counts them, so a truncated stream is caught
   once it is used. */
static void refill(void)
{
    if (s.pos + 4 <= s.len) {
        while (s.bitcnt <= 24) {
            s.bitbuf |= (unsigned)s.in[s.pos++] << s.bitcnt;
            s.bitcnt += 8;
        }
        return;
    }
    while (s.bitcnt <= 24) {
        unsigned b = 0;
        if (s.pos < s.len)
            b = s.in[s.pos];
        else
            s.overrun++;
        s.pos++;
        s.bitbuf |= b << s.bitcnt;
        s.bitcnt += 8;
    }
}

static unsigned bits(int n)
{
    unsigned v;
    if (s.bitcnt < n)
        refill();
    v = s.bitbuf & ((1u << n) - 1);
    s.bitbuf >>= n;
    s.bitcnt -= n;
    return v;
}

/* Drops the bits up to the next byte boundary, and gives back the
   whole bytes the buffer holds, for a stored block to read directly. */
static void align_to_byte(void)
{
    int drop = s.bitcnt & 7;
    s.bitbuf >>= drop;
    s.bitcnt -= drop;
    s.pos -= s.bitcnt >> 3;
    s.bitbuf = 0;
    s.bitcnt = 0;
}

/* ---- output ---------------------------------------------------------- */

static void put(int b)
{
    s.window[s.wpos++] = (unsigned char)b;
    if (s.wpos == WSIZE) {
        s.sink(s.ctx, s.window, WSIZE);
        s.wpos = 0;
    }
}

/* Copies len bytes from dist back. While neither end wraps round the
   window, it's a straight loop; otherwise a byte at a time with the
   wrap. */
static void copy(unsigned dist, unsigned len)
{
    unsigned from = (s.wpos - dist) & WMASK;
    if (from + len <= WSIZE && s.wpos + len < WSIZE) {
        unsigned char *d = s.window + s.wpos, *f = s.window + from;
        s.wpos += len;
        while (len--)
            *d++ = *f++;
        return;
    }
    while (len--) {
        put(s.window[from]);
        from = (from + 1) & WMASK;
    }
}

/* ---- Huffman codes --------------------------------------------------- */

/* Builds a table from the code lengths of n symbols, with a one-step
   table of fastbits. Returns 0, or -1 if the lengths over-subscribe the
   code (an incomplete code is allowed, as deflate allows one for a
   single distance code). */
static int build(struct huffman *h, const unsigned char *lengths, int n, int fastbits)
{
    short offs[MAXBITS + 1];
    int sym, len, left, ncodes;
    unsigned code;
    for (len = 0; len <= MAXBITS; len++)
        h->count[len] = 0;
    for (sym = 0; sym < n; sym++)
        h->count[lengths[sym]]++;
    h->count[0] = 0;
    left = 1;
    for (len = 1; len <= MAXBITS; len++) {
        left = (left << 1) - h->count[len];
        if (left < 0)
            return -1;
    }
    offs[1] = 0;
    for (len = 1; len < MAXBITS; len++)
        offs[len + 1] = offs[len] + h->count[len];
    ncodes = offs[MAXBITS] + h->count[MAXBITS];
    for (sym = 0; sym < n; sym++)
        if (lengths[sym])
            h->symbol[offs[lengths[sym]]++] = (short)sym;
    /* the one-step table: each short code, reversed, since codes are
       sent from their top bit and the buffer is read from its low one.
       The codes go up in canonical order, so the reversed code is kept
       and stepped as zlib's inflate_table does, adding one at its top
       bit and carrying downwards. */
    h->fastbits = fastbits;
    memset(h->fast, 0, sizeof h->fast[0] << fastbits);
    code = 0;
    for (sym = 0; sym < ncodes; sym++) {
        unsigned step, incr;
        len = lengths[h->symbol[sym]];
        if (len > fastbits)
            break;
        step = 1u << len;
        for (incr = code; incr < (1u << fastbits); incr += step)
            h->fast[incr] = (unsigned short)(len << 9 | h->symbol[sym]);
        incr = 1u << (len - 1);
        while (code & incr)
            incr >>= 1;
        code = incr ? (code & (incr - 1)) + incr : 0;
    }
    return 0;
}

/* The next symbol, for a code longer than the one-step table holds: a
   bit at a time through the counts, from the shortest length. */
static int decode_slow(struct huffman *h)
{
    unsigned code = 0, first = 0, index = 0;
    int len, count;
    if (s.bitcnt < MAXBITS)
        refill();
    for (len = 1; len <= MAXBITS; len++) {
        code |= s.bitbuf & 1;
        s.bitbuf >>= 1;
        s.bitcnt--;
        count = h->count[len];
        if ((int)(code - first) < count)
            return h->symbol[index + (code - first)];
        index += count;
        first += count;
        first <<= 1;
        code <<= 1;
    }
    return -1;
}

/* The next symbol, outside the codes loop (for the code lengths). */
static int decode(struct huffman *h)
{
    unsigned entry;
    if (s.bitcnt < MAXBITS)
        refill();
    entry = h->fast[s.bitbuf & ((1u << h->fastbits) - 1)];
    if (entry) {
        int len = entry >> 9;
        s.bitbuf >>= len;
        s.bitcnt -= len;
        return entry & 511;
    }
    return decode_slow(h);
}

/* ---- blocks ---------------------------------------------------------- */

static int stored(void)
{
    unsigned n, check;
    align_to_byte();
    if (s.pos + 4 > s.len)
        return Z_TRUNCATED;
    n = s.in[s.pos] | s.in[s.pos + 1] << 8;
    check = s.in[s.pos + 2] | s.in[s.pos + 3] << 8;
    s.pos += 4;
    if (n != (~check & 0xffff))
        return Z_BAD_STORED;
    if (s.pos + n > s.len)
        return Z_TRUNCATED;
    s.total += n;
    while (n--)
        put(s.in[s.pos++]);
    return Z_OK;
}

/* The input position, the bit buffer and the window position, between
   the state and the codes loop's locals. */
#define LOAD()  (pos = s.pos, buf = s.bitbuf, cnt = s.bitcnt, w = s.wpos)
#define STORE() (s.pos = pos, s.bitbuf = buf, s.bitcnt = cnt, s.wpos = w)

/* At least n bits in the buffer: straight from the input while four
   bytes are left, else through refill(), which knows about the end. */
#define NEED(n)                                                 \
    if (cnt < (n)) {                                            \
        if (pos + 4 <= len_in) {                                \
            do {                                                \
                buf |= (unsigned)in[pos++] << cnt;              \
                cnt += 8;                                       \
            } while (cnt <= 24);                                \
        } else {                                                \
            STORE();                                            \
            refill();                                           \
            LOAD();                                             \
        }                                                       \
    }
#define TAKE(v, n) (v = buf & ((1u << (n)) - 1), buf >>= (n), cnt -= (n))

/* The next symbol, in the codes loop. */
#define DECODE(sym, h) {                                        \
        unsigned e_;                                            \
        NEED(MAXBITS);                                          \
        e_ = (h)->fast[buf & ((1u << (h)->fastbits) - 1)];      \
        if (e_) {                                               \
            buf >>= e_ >> 9;                                    \
            cnt -= e_ >> 9;                                     \
            sym = e_ & 511;                                     \
        } else {                                                \
            STORE();                                            \
            sym = decode_slow(h);                               \
            LOAD();                                             \
        }                                                       \
    }

/* The symbols of one Huffman-coded block, up to its end code. */
static int codes(struct huffman *lens, struct huffman *dists)
{
    const unsigned char *in = s.in;
    unsigned char *win = s.window;
    unsigned len_in = s.len, pos, buf, w, len, dist, extra, total = s.total;
    int cnt, sym;
    LOAD();
    for (;;) {
        DECODE(sym, lens);
        if (sym < 256) {
            if (sym < 0)
                break;
            win[w++] = (unsigned char)sym;
            total++;
            if (w == WSIZE) {
                s.sink(s.ctx, win, WSIZE);
                w = 0;
            }
            continue;
        }
        if (sym == 256) {
            STORE();
            s.total = total;
            return s.overrun > 4 ? Z_TRUNCATED : Z_OK;
        }
        sym -= 257;
        if (sym >= 29)
            break;
        NEED(len_extra[sym]);
        TAKE(extra, len_extra[sym]);
        len = len_base[sym] + extra;
        DECODE(sym, dists);
        if (sym < 0 || sym >= 30)
            break;
        NEED(dist_extra[sym]);
        TAKE(extra, dist_extra[sym]);
        dist = dist_base[sym] + extra;
        if (dist > total) {
            STORE();
            return Z_BAD_DISTANCE;
        }
        STORE();
        copy(dist, len);
        LOAD();
        total += len;
        if (s.overrun > 4) {
            STORE();
            return Z_TRUNCATED;
        }
    }
    STORE();
    s.total = total;
    return Z_BAD_SYMBOL;
}

static int fixed(void)
{
    if (!fixed_built) {
        unsigned char lengths[NLITLEN];
        int sym;
        for (sym = 0; sym < 144; sym++)
            lengths[sym] = 8;
        for (; sym < 256; sym++)
            lengths[sym] = 9;
        for (; sym < 280; sym++)
            lengths[sym] = 7;
        for (; sym < NLITLEN; sym++)
            lengths[sym] = 8;
        build(&fixed_len, lengths, NLITLEN, 9);
        for (sym = 0; sym < NDIST; sym++)
            lengths[sym] = 5;
        build(&fixed_dist, lengths, NDIST, 5);
        fixed_built = 1;
    }
    return codes(&fixed_len, &fixed_dist);
}

/* The order in which the code length code's lengths are sent. */
static const unsigned char clen_order[19] = {
    16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15
};

static int dynamic(void)
{
    unsigned char lengths[NLITLEN + NDIST];
    int nlen, ndist, ncode, index;
    nlen = bits(5) + 257;
    ndist = bits(5) + 1;
    ncode = bits(4) + 4;
    if (nlen > 286 || ndist > NDIST)
        return Z_BAD_CODES;
    /* the code length code, then the lengths it codes */
    for (index = 0; index < 19; index++)
        lengths[clen_order[index]] = index < ncode ? (unsigned char)bits(3) : 0;
    if (build(&lencode, lengths, 19, 7) != 0)
        return Z_BAD_CODES;
    index = 0;
    while (index < nlen + ndist) {
        int sym = decode(&lencode), len = 0, rep;
        if (sym < 0)
            return Z_BAD_CODES;
        if (sym < 16) {
            lengths[index++] = (unsigned char)sym;
            continue;
        }
        if (sym == 16) {
            if (index == 0)
                return Z_BAD_CODES;
            len = lengths[index - 1];
            rep = 3 + bits(2);
        } else if (sym == 17) {
            rep = 3 + bits(3);
        } else {
            rep = 11 + bits(7);
        }
        if (index + rep > nlen + ndist)
            return Z_BAD_CODES;
        while (rep--)
            lengths[index++] = (unsigned char)len;
    }
    if (lengths[256] == 0)
        return Z_BAD_CODES;     /* no end of block */
    if (build(&lencode, lengths, nlen, 9) != 0 ||
        build(&distcode, lengths + nlen, ndist, 6) != 0)
        return Z_BAD_CODES;
    return codes(&lencode, &distcode);
}

int inflate(const unsigned char *in, unsigned len, unsigned *used,
            unsigned *out, sink_fn sink, void *ctx)
{
    int last, err;
    s.in = in;
    s.len = len;
    s.pos = 0;
    s.bitbuf = 0;
    s.bitcnt = 0;
    s.overrun = 0;
    s.wpos = 0;
    s.total = 0;
    s.sink = sink;
    s.ctx = ctx;
    do {
        int type;
        last = bits(1);
        type = bits(2);
        if (type == 0)
            err = stored();
        else if (type == 1)
            err = fixed();
        else if (type == 2)
            err = dynamic();
        else
            err = Z_BAD_BLOCK;
    } while (!err && !last);
    if (s.wpos)
        sink(ctx, s.window, s.wpos);
    /* the input it used: what was read, less whole bytes still unused */
    align_to_byte();
    *used = s.pos;
    *out = s.total;
    return err;
}
