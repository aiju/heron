/* Outline fonts at a size, through a glyph cache, and drawing kerned
   strings with them. Follows studies/graphics/src/font.c, whose fonts
   each kept their own 95 glyphs; here every font shares one cache, as a
   desktop's text service would: a hash table on (font, glyph) whose
   bitmaps live in one arena, emptied whole when it fills.

   A string is laid out in 24.8: each glyph's advance, plus the kerning
   between it and the one before; a glyph is drawn at the pen rounded to
   a whole pixel. Drawing is one gfx_ramp (anti-aliased) or gfx_expand
   (plain) per glyph, the kernels called directly when the glyph is
   inside the clip rectangle, as most are. */

#include <stdlib.h>
#include <string.h>
#include "gfx.h"

/* ---- the glyph cache ---- */

#define CACHE_SLOTS 512                 /* a power of two, a quarter full or less */
#define ARENA_BYTES (32 * 1024)
#define EMPTY 0xFFFFFFFFu

typedef struct {
    unsigned key;                       /* font id << 16 | glyph, or EMPTY */
    Glyph g;
} Slot;

static Slot slots[CACHE_SLOTS];
static unsigned char *arena;
static int arena_used, cache_used;
static int next_id;
int cache_hits, cache_misses, cache_bytes, cache_flushes;

/* the scratch buffer a glyph is rasterised into before it's kept */
#define SCRATCH 16384
static unsigned scratch[SCRATCH / 4];

static void cache_flush(void)
{
    int i;
    for (i = 0; i < CACHE_SLOTS; i++)
        slots[i].key = EMPTY;
    arena_used = 0;
    cache_used = 0;
}

void cache_init(void)
{
    arena = malloc(ARENA_BYTES);
    cache_flush();
    cache_hits = cache_misses = cache_bytes = cache_flushes = 0;
}

/* Fibonacci hashing: the key times 2^32 / phi, its top bits */
static int slot_of(unsigned key)
{
    return (key * 2654435769u) >> 23;   /* 9 bits: CACHE_SLOTS */
}

static Glyph *cache_get(Font *f, int gi)
{
    unsigned key = (unsigned)f->id << 16 | gi;
    int i = slot_of(key), n;
    Slot *s;
    for (;;) {
        s = &slots[i];
        if (s->key == key) {
            cache_hits++;
            return &s->g;
        }
        if (s->key == EMPTY)
            break;
        i = (i + 1) & (CACHE_SLOTS - 1);
    }
    /* a miss: rasterise it, and keep its bits in the arena */
    cache_misses++;
    n = ttf_render(f->ttf, gi, f->size, f->aa, (unsigned char *)scratch, SCRATCH, &s->g);
    if (n < 0) {
        memset(&s->g, 0, sizeof s->g);  /* too big: drawn as nothing */
        n = 0;
    }
    n = (n + 3) & ~3;                   /* the next glyph's bitmap on a word */
    if (arena_used + n > ARENA_BYTES || 4 * (cache_used + 1) > CACHE_SLOTS) {
        /* full: start again, and find the slot afresh */
        Glyph g = s->g;
        cache_flush();
        cache_flushes++;
        for (i = slot_of(key); slots[i].key != EMPTY; i = (i + 1) & (CACHE_SLOTS - 1))
            ;
        s = &slots[i];
        s->g = g;
    }
    s->key = key;
    cache_used++;
    if (n) {
        s->g.bits = arena + arena_used;
        memcpy(s->g.bits, scratch, n);
        arena_used += n;
        cache_bytes += n;
    } else {
        s->g.bits = 0;
    }
    return &s->g;
}

/* ---- fonts ---- */

void font_open(Font *f, TTF *t, int size, int aa)
{
    int c;
    memset(f, 0, sizeof *f);
    f->ttf = t;
    f->size = size;
    f->aa = aa;
    f->id = ++next_id;
    f->ascent = (t->ascent * size + t->upem / 2) / t->upem;
    f->descent = (-t->descent * size + t->upem / 2) / t->upem;
    f->height = f->ascent + f->descent + (t->linegap * size + t->upem / 2) / t->upem;
    for (c = 0; c < 96; c++)
        f->gidx[c] = -1;
}

/* the glyph of character c, from the cmap the first time */
static int glyph_of(Font *f, int c)
{
    int k = c >= 32 && c < 127 ? c - 32 : 95;
    if (f->gidx[k] < 0)
        f->gidx[k] = ttf_glyph_index(f->ttf, k < 95 ? c : '?');
    return f->gidx[k];
}

Glyph *font_glyph(Font *f, int c)
{
    return cache_get(f, glyph_of(f, c));
}

int font_width(Font *f, const char *str, int n)
{
    int pen = 0, prev = -1, gi;
    Glyph *g;
    while (n-- > 0) {
        gi = glyph_of(f, (unsigned char)*str++);
        g = cache_get(f, gi);
        if (prev >= 0)
            pen += ttf_kern(f->ttf, prev, gi, f->size);
        pen += g->adv8;
        prev = gi;
    }
    return (pen + 128) >> 8;
}

int font_draw(Surface *s, Font *f, int x, int y, const char *str, int n, unsigned fg,
              const unsigned char *ramp)
{
    ExpandJob j;
    RampJob rj;
    Glyph *g;
    Surface gs;
    unsigned char *row = s->bits + y * s->pitch;
    int d = s->depth, gx, gy, bit, lead, last, gi, prev = -1, pen = x << 8;
    rj.dpitch = s->pitch;
    rj.ramp = ramp;
    rj.depth = d;
    j.dpitch = s->pitch;
    j.spitch = 4;
    j.fg = gfx_pat(d, fg);
    j.slast = 0;
    while (n-- > 0) {
        gi = glyph_of(f, (unsigned char)*str++);
        g = cache_get(f, gi);
        if (prev >= 0)
            pen += ttf_kern(f->ttf, prev, gi, f->size);
        prev = gi;
        gx = ((pen + 128) >> 8) + g->xoff;
        gy = y + g->yoff;
        pen += g->adv8;
        if (!g->w || !g->bits)
            continue;
        if (f->aa) {
            if (gx >= s->cx0 && gy >= s->cy0 && gx + g->w <= s->cx1 && gy + g->h <= s->cy1) {
                bit = gx << d;
                rj.d = (unsigned *)(row + g->yoff * s->pitch) + (bit >> 5);
                rj.lead = (bit & 31) >> d;
                rj.n = ((bit & 31) + (g->w << d) - 1) >> 5;
                rj.c = g->bits;
                rj.cpitch = g->w;
                rj.w = g->w;
                rj.h = g->h;
                ramp_rows(&rj);
            } else {
                gfx_ramp(s, gx, gy, g->bits, g->w, g->w, g->h, ramp);
            }
            continue;
        }
        if (gx >= s->cx0 && gy >= s->cy0 && gx + g->w <= s->cx1 && gy + g->h <= s->cy1 &&
            g->w <= 32) {
            /* a bitmap of one word a row: the kernel, set up here */
            bit = gx << d;
            lead = (bit & 31) >> d;
            last = lead + g->w - 1;
            j.d = (unsigned *)(row + g->yoff * s->pitch) + (bit >> 5);
            j.s = (const unsigned *)g->bits;
            j.h = g->h;
            j.soff = -lead;
            j.nch = (last >> 5) + 1;
            j.cfirst = ~0u << lead;
            j.clast = ~0u >> (31 - (last & 31));
            if (j.nch == 1)
                j.cfirst &= j.clast;
            expand_rows(&j);
        } else {
            gfx_init(&gs, g->bits, g->w, g->h, ((g->w + 31) >> 5) << 2, 0);
            gfx_expand(s, gx, gy, &gs, 0, 0, g->w, g->h, fg);
        }
    }
    return (pen + 128) >> 8;
}
