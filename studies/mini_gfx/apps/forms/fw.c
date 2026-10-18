/* Form widgets (fw.h). */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "fw.h"
#include "video.h"

/* ---- text strips ----

   The strip is STRIP_H rows of linear 1-bit pixels. A glyph of the sans
   font is at most 11 pixels wide, so shifted by 0-7 bits it fits in three
   bytes: strip_init keeps each glyph's rows shifted all eight ways, and
   strip_text ORs a glyph's rows into the strip three bytes at a time (two
   when that shift of it fits), at its pen's byte, with no shift by a
   variable count (a cycle a bit on this machine) and no multiply (tens
   of cycles): the shifts' rows are 16 apart, and the glyph's first row's
   offset in the strip is kept. */

#define STRIP_PITCH (STRIP_MAXW / 32 + 2)
#define STRIP_BYTES (STRIP_PITCH * 4)

static unsigned strip_bits[STRIP_H * STRIP_PITCH];
Bitmap strip = {strip_bits, STRIP_PITCH};

typedef struct {
    unsigned char n, adv;       /* the rows, the advance */
    signed char xoff;
    unsigned char wide;         /* bit s: shifted by s, it needs a third byte */
    unsigned short off;         /* the first row's byte in the strip */
    unsigned *rows;             /* shift s's rows from 16 * s */
} SGlyph;

static SGlyph sg[95];
static int strip_ready;

void strip_init(void)
{
    const Font *f;
    int c, r, b, s;
    if (strip_ready)
        return;
    font_init();
    f = font_sans;
    for (c = 32; c < 127; c++) {
        int gi = c >= f->first && c < f->first + f->count ? c - f->first : '?' - f->first;
        const Glyph *g = &f->glyphs[gi];
        SGlyph *q = &sg[c - 32];
        int top = STRIP_BASE + g->yoff, r0 = top < 0 ? 0 : top, r1 = top + g->h;
        if (r1 > STRIP_H)
            r1 = STRIP_H;
        q->adv = g->adv;
        q->xoff = g->xoff;
        q->off = r0 * STRIP_BYTES;
        q->n = g->w && r1 > r0 ? r1 - r0 : 0;
        q->wide = 0;
        if (!q->n)
            continue;
        q->rows = malloc(8 * 16 * sizeof(unsigned));
        for (r = r0; r < r1; r++) {
            const unsigned *row = f->strike.bits + (r - top) * f->strike.pitch;
            unsigned v = 0;
            for (b = 0; b < g->w; b++) {
                int x = g->sx + b;
                if (row[x >> 5] >> (x & 31) & 1)
                    v |= 1u << b;
            }
            for (s = 0; s < 8; s++) {
                q->rows[16 * s + r - r0] = v << s;
                if (v << s >> 16)
                    q->wide |= 1 << s;
            }
        }
    }
    strip_ready = 1;
}

void strip_begin(int w)
{
    int words = (w + 31) / 32 + 1, r, k;
    unsigned *p = strip_bits;
    if (words > STRIP_PITCH)
        words = STRIP_PITCH;
    for (r = 0; r < STRIP_H; r++) {
        for (k = 0; k < words; k++)
            p[k] = 0;
        p += STRIP_PITCH;
    }
}

static const SGlyph *sglyph(int c)
{
    if (c < 32 || c > 126)
        c = '?';
    return &sg[c - 32];
}

int strip_text(int x, int xmax, const char *s)
{
    unsigned char *base = (unsigned char *)strip_bits;
    int c;
    while ((c = (unsigned char)*s++) != 0) {
        const SGlyph *g = sglyph(c);
        if (x + g->adv > xmax)
            break;
        if (g->n) {
            int px = x + g->xoff, r, sh;
            const unsigned *v;
            unsigned char *b;
            if (px < 0)
                px = 0;
            sh = px & 7;
            v = g->rows + (sh << 4);
            b = base + g->off + (px >> 3);
            if (g->wide >> sh & 1) {
                for (r = g->n; r > 0; r--) {
                    unsigned w = *v++;
                    b[0] |= w;
                    b[1] |= w >> 8;
                    b[2] |= w >> 16;
                    b += STRIP_BYTES;
                }
            } else {
                for (r = g->n; r > 0; r--) {
                    unsigned w = *v++;
                    b[0] |= w;
                    b[1] |= w >> 8;
                    b += STRIP_BYTES;
                }
            }
        }
        x += g->adv;
    }
    return x;
}

int strip_widthn(const char *s, int n)
{
    int w = 0;
    while (n-- > 0 && *s)
        w += sglyph((unsigned char)*s++)->adv;
    return w;
}

int strip_width(const char *s)
{
    return strip_widthn(s, 1 << 30);
}

int strip_index(const char *s, int x)
{
    int i = 0, pen = 0;
    while (s[i]) {
        int a = sglyph((unsigned char)s[i])->adv;
        if (x < pen + a / 2)
            break;
        pen += a;
        i++;
    }
    return i;
}

void strip_cells(int x, const char *s, int n)
{
    unsigned char *b = (unsigned char *)strip_bits + (x >> 3);
    int k, r;
    for (k = 0; k < n && s[k]; k++) {
        int c = (unsigned char)s[k];
        const unsigned char *g;
        unsigned char *p = b + k;
        if (c < 32 || c > 126)
            c = '?';
        g = font_cell8 + 16 * (c - 32);
        for (r = 0; r < 16; r++) {
            *p = g[r];
            p += STRIP_BYTES;
        }
    }
}

/* The strip into a surface when its bits line up with the surface's
   pixels (sx and dx the same in a word's pixels): each destination
   word's pixels from one source unit (a byte at 4 bits a pixel, a half
   at 2, a word at 1), through the format's tables, or as they are where
   the format lets them be: linear 1 bit (L1, F1) is the strip itself, and
   L1's planes at 2 bits are the strip's half twice. The library's C
   kernel does any phase, and calls gfx_xmask for every word; its
   assembly and block kernels only do 4 bits a pixel. */
int fw_put = 2;     /* 0 the library's gfx_expand, 1 this, 2 this where the library has no assembly */

static int put_aligned(Surface *s, int dx, int dy, const Bitmap *b, int sx, int w,
                       unsigned fg, unsigned bg)
{
    const Format *f = s->f;
    int ps = s->pshift, ppw = 1 << ps, last = ppw - 1, x1 = dx + w, r0 = 0, r1 = STRIP_H;
    int w0, n, r, k;
    unsigned lm, rm, bw, fx, v;
    const unsigned *xt;
    if (ppw < 8)
        return 0;
    if (dx < s->clip.x0) {
        sx += s->clip.x0 - dx;
        dx = s->clip.x0;
    }
    if (x1 > s->clip.x1)
        x1 = s->clip.x1;
    if (dy < s->clip.y0)
        r0 = s->clip.y0 - dy;
    if (dy + r1 > s->clip.y1)
        r1 = s->clip.y1 - dy;
    if (dx >= x1 || r0 >= r1)
        return 1;
    if ((sx & last) != (dx & last))
        return 0;
    gfx_xmask(f, 0);            /* the tables */
    xt = f->xt;
    w0 = dx >> ps;
    n = ((x1 - 1) >> ps) - w0;  /* words after the first */
    lm = gfx_from(f, dx & last);
    rm = gfx_before(f, ((x1 - 1) & last) + 1);
    if (!n)
        lm &= rm;
    bw = gfx_solidf(f, bg);
    fx = gfx_solidf(f, fg) ^ bw;
    sx &= ~last;                /* the source's bit under the first word's first pixel */
    for (r = r0; r < r1; r++) {
        unsigned *d = s->bits + (dy + r) * s->pitch + w0;
        const unsigned *row = b->bits + r * b->pitch;
        if (ppw == 8) {
            const unsigned char *p = (const unsigned char *)row + (sx >> 3);
            v = bw ^ (fx & xt[*p++]);
            *d = (*d & ~lm) | (v & lm);
            d++;
            for (k = 1; k < n; k++)
                *d++ = bw ^ (fx & xt[*p++]);
            if (n) {
                v = bw ^ (fx & xt[*p]);
                *d = (*d & ~rm) | (v & rm);
            }
        } else if (ppw == 16) {
            const unsigned short *p = (const unsigned short *)row + (sx >> 4);
            unsigned h;
            if (s->fmt == PF_PL2) {
                h = *p++;
                v = bw ^ (fx & (h | h << 16));
                *d = (*d & ~lm) | (v & lm);
                d++;
                for (k = 1; k < n; k++) {
                    h = *p++;
                    *d++ = bw ^ (fx & (h | h << 16));
                }
                h = *p;
                v = bw ^ (fx & (h | h << 16));
            } else {
                h = *p++;
                v = bw ^ (fx & (xt[h & 255] | xt[256 + (h >> 8)]));
                *d = (*d & ~lm) | (v & lm);
                d++;
                for (k = 1; k < n; k++) {
                    h = *p++;
                    *d++ = bw ^ (fx & (xt[h & 255] | xt[256 + (h >> 8)]));
                }
                h = *p;
                v = bw ^ (fx & (xt[h & 255] | xt[256 + (h >> 8)]));
            }
            if (n)
                *d = (*d & ~rm) | (v & rm);
        } else {
            const unsigned *p = row + (sx >> 5);
            unsigned m;
            if (s->fmt == PF_LIN1) {
                v = bw ^ (fx & *p++);
                *d = (*d & ~lm) | (v & lm);
                d++;
                for (k = 1; k < n; k++)
                    *d++ = bw ^ (fx & *p++);
                v = bw ^ (fx & *p);
            } else {
                m = gfx_xmask(f, *p++);
                v = bw ^ (fx & m);
                *d = (*d & ~lm) | (v & lm);
                d++;
                for (k = 1; k < n; k++) {
                    m = *p++;
                    m = xt[m & 255] | xt[256 + (m >> 8 & 255)] | xt[512 + (m >> 16 & 255)] |
                        xt[768 + (m >> 24)];
                    *d++ = bw ^ (fx & m);
                }
                v = bw ^ (fx & gfx_xmask(f, *p));
            }
            if (n)
                *d = (*d & ~rm) | (v & rm);
        }
    }
    return 1;
}

void bits_put(Surface *s, int dx, int dy, const Bitmap *b, int sx, int w, unsigned fg,
              unsigned bg)
{
    int mine = fw_put == 1;
#ifndef GFX_ASM
    mine |= fw_put == 2;
#else
    mine |= fw_put == 2 && s->bpp < 4;
#endif
    if (mine && put_aligned(s, dx, dy, b, sx, w, fg, bg))
        return;
    gfx_expand(s, dx, dy, b, sx, 0, w, STRIP_H, fg, bg, 1);
}

void strip_put(Surface *s, int dx, int dy, int sx, int w, unsigned fg, unsigned bg)
{
    bits_put(s, dx, dy, &strip, sx, w, fg, bg);
}

/* ---- a table ---- */

static unsigned drawn_mask[2];  /* rows drawn since the last table_select began */

typedef struct RowCache {
    unsigned *bits;             /* STRIP_H rows of cache_words; 0: not drawn yet */
    signed char colour[16];     /* each cell's colour, or -1 */
} RowCache;

int table_cache(Table *t, int n)
{
    t->cache = calloc(n, sizeof(RowCache));
    t->ncache = t->cache ? n : 0;
    t->cache_words = ((t->x & 31) + t->w - TBL_SB_W + 31) / 32;
    return t->ncache;
}

void table_forget(Table *t, int id)
{
    if (id >= 0 && id < t->ncache && t->cache[id].bits) {
        free(t->cache[id].bits);
        t->cache[id].bits = 0;
    }
}

static int rows_w(const Table *t)
{
    return t->w - TBL_SB_W;
}

static int rows_y(const Table *t)
{
    return t->y + TBL_HDR_H;
}

void table_row(Table *t, int i)
{
    Surface *s = &t->win->s;
    int r = t->first + i, y = rows_y(t) + i * TBL_ROW_H, w = rows_w(t), c, x;
    int sel = r == t->sel && !t->banks;
    unsigned fg = sel ? t->sel_fg : t->fg, bg = sel ? t->sel_bg : (r & 1) ? t->bg2 : t->bg;
    int colour[16];
    char buf[48];
    if (i < 64)
        drawn_mask[i >> 5] |= 1u << (i & 31);
    t->drawn++;
    if (r >= t->total) {
        gfx_fill(s, t->x, y, t->x + w, y + TBL_ROW_H, t->bg, ROP_COPY);
        wm_damage(t->win, t->x, y, t->x + w, y + TBL_ROW_H);
        return;
    }
    if (t->glyphs) {
        /* the library's way: a fill, then each cell's glyphs one by one */
        gfx_fill(s, t->x, y, t->x + w, y + TBL_ROW_H, bg, ROP_COPY);
        x = t->x;
        for (c = 0; c < t->ncol; c++) {
            int cw = t->cols[c].w, col = t->cell(t, r, c, buf), tx;
            tx = t->cols[c].right ? x + cw - 4 - font_width(font_sans, buf) : x + 4;
            gfx_clip(s, x + 2, y, x + cw - 2, y + TBL_ROW_H);
            font_draw(s, font_sans, tx, y + STRIP_BASE, buf, col >= 0 && !sel ? col : fg, -1);
            gfx_noclip(s);
            x += cw;
        }
    } else {
        /* the row's text as one strip, expanded once, background and all;
           the strip starts at the row's phase in a word (o), so its bits
           line up with the pixels */
        int o = t->x & 31, id = t->ncache ? t->id(t, r) : -1;
        RowCache *rc = id >= 0 && id < t->ncache ? &t->cache[id] : 0;
        Bitmap bm;
        if (rc && rc->bits) {
            /* drawn before: expanded from the cache */
            t->hits++;
            bm.bits = rc->bits;
            bm.pitch = t->cache_words;
            bits_put(s, t->x, y, &bm, o, w, fg, bg);
            x = 0;
            for (c = 0; c < t->ncol; c++) {
                if (rc->colour[c] >= 0 && !sel)
                    bits_put(s, t->x + x, y, &bm, o + x, t->cols[c].w, rc->colour[c], bg);
                x += t->cols[c].w;
            }
            wm_damage(t->win, t->x, y, t->x + w, y + TBL_ROW_H);
            return;
        }
        strip_begin(o + w);
        x = o;
        for (c = 0; c < t->ncol; c++) {
            int cw = t->cols[c].w;
            colour[c] = t->cell(t, r, c, buf);
            if (t->cellfont) {
                int n = strlen(buf), cells = (cw - 4) / 8, x0;
                if (n > cells)
                    n = cells;
                x0 = t->cols[c].right ? (x + cw - 4 - 8 * n) & ~7 : (x + 7) & ~7;
                strip_cells(x0, buf, n);
            } else if (t->cols[c].right) {
                strip_text(x + cw - 4 - strip_width(buf), x + cw - 3, buf);
            } else {
                strip_text(x + 4, x + cw - 3, buf);
            }
            x += cw;
        }
        strip_put(s, t->x, y, o, w, fg, bg);
        if (rc) {
            /* kept for the next time */
            int k, n = t->cache_words;
            t->misses++;
            rc->bits = malloc(STRIP_H * n * sizeof(unsigned));
            if (rc->bits) {
                for (k = 0; k < STRIP_H; k++)
                    memcpy(rc->bits + k * n, strip_bits + k * STRIP_PITCH, n * sizeof(unsigned));
                for (c = 0; c < t->ncol && c < 16; c++)
                    rc->colour[c] = colour[c];
            }
        }
        /* the cells in a colour of their own: their part of the strip again */
        x = 0;
        for (c = 0; c < t->ncol; c++) {
            if (colour[c] >= 0 && !sel)
                strip_put(s, t->x + x, y, o + x, t->cols[c].w, colour[c], bg);
            x += t->cols[c].w;
        }
    }
    wm_damage(t->win, t->x, y, t->x + w, y + TBL_ROW_H);
}

/* a small triangle: up (the smallest first) or down */
static void arrow(Surface *s, int x, int y, int down, unsigned c)
{
    int k;
    for (k = 0; k < 4; k++)
        gfx_hline(s, x + 3 - k, x + 4 + k, down ? y + 3 - k : y + k, c, ROP_COPY);
}

void table_header(Table *t)
{
    Surface *s = &t->win->s;
    int x = t->x, c, y = t->y;
    for (c = 0; c < t->ncol; c++) {
        int cw = t->cols[c].w, tw = font_width(font_sans, t->cols[c].title);
        int tx = t->cols[c].right ? x + cw - 5 - tw : x + 4;
        ui_panel(s, x, y, x + cw, y + TBL_HDR_H, 0);
        font_draw(s, font_sans, tx, y + 13, t->cols[c].title, th.text, -1);
        if (c == t->sort_col)
            arrow(s, t->cols[c].right ? x + 4 : x + cw - 12, y + 7, t->sort_desc, th.text);
        x += cw;
    }
    ui_panel(s, x, y, t->x + t->w, y + TBL_HDR_H, 0);
    wm_damage(t->win, t->x, y, t->x + t->w, y + TBL_HDR_H);
}

static void sb_rect(const Table *t, int *x0, int *y0, int *x1, int *y1)
{
    *x0 = t->x + rows_w(t);
    *x1 = t->x + t->w;
    *y0 = rows_y(t);
    *y1 = *y0 + t->rows * TBL_ROW_H;
}

void table_scrollbar(Table *t)
{
    int x0, y0, x1, y1;
    sb_rect(t, &x0, &y0, &x1, &y1);
    ui_scrollbar(&t->win->s, x0, y0, x1, y1, t->total, t->first, t->rows);
    wm_damage(t->win, x0, y0, x1, y1);
}

void table_rows(Table *t)
{
    int i;
    for (i = 0; i < t->rows; i++)
        table_row(t, i);
    table_scrollbar(t);
    if (t->banks)
        table_banks_update(t);
}

void table_draw(Table *t)
{
    table_header(t);
    table_rows(t);
}

void table_scroll(Table *t, int f)
{
    Surface *s = &t->win->s;
    int max = t->total - t->rows, d, i, y0 = rows_y(t), w = rows_w(t);
    if (f > max)
        f = max;
    if (f < 0)
        f = 0;
    d = f - t->first;
    if (!d)
        return;
    t->first = f;
    if (d > 0 && d <= t->rows / 2) {
        /* up: the rows that stay copied, the d new ones at the bottom drawn */
        gfx_blit(s, t->x, y0, s, t->x, y0 + d * TBL_ROW_H, w, (t->rows - d) * TBL_ROW_H,
                 ROP_COPY);
        wm_damage(t->win, t->x, y0, t->x + w, y0 + (t->rows - d) * TBL_ROW_H);
        t->copied += t->rows - d;
        for (i = t->rows - d; i < t->rows; i++)
            table_row(t, i);
    } else if (d < 0 && -d <= t->rows / 2) {
        gfx_blit(s, t->x, y0 - d * TBL_ROW_H, s, t->x, y0, w, (t->rows + d) * TBL_ROW_H,
                 ROP_COPY);
        wm_damage(t->win, t->x, y0 - d * TBL_ROW_H, t->x + w, y0 + t->rows * TBL_ROW_H);
        t->copied += t->rows + d;
        for (i = 0; i < -d; i++)
            table_row(t, i);
    } else {
        for (i = 0; i < t->rows; i++)
            table_row(t, i);
    }
    table_scrollbar(t);
    if (t->banks)
        table_banks_update(t);
}

static int shown(const Table *t, int r)
{
    return r >= t->first && r < t->first + t->rows;
}

static int was_drawn(int i)
{
    return i < 64 && (drawn_mask[i >> 5] >> (i & 31) & 1);
}

void table_select(Table *t, int r)
{
    int old = t->sel, f = t->first;
    if (r >= t->total)
        r = t->total - 1;
    if (r < 0)
        r = t->total ? 0 : -1;
    t->sel = r;
    drawn_mask[0] = drawn_mask[1] = 0;
    if (r >= 0) {
        if (r < f)
            f = r;
        else if (r >= f + t->rows)
            f = r - t->rows + 1;
    }
    table_scroll(t, f);
    if (t->banks) {
        table_banks_update(t);
        return;
    }
    /* the old and the new selection's rows, unless the scroll drew them */
    if (old != r && shown(t, old) && !was_drawn(old - t->first))
        table_row(t, old - t->first);
    if (shown(t, r) && !was_drawn(r - t->first))
        table_row(t, r - t->first);
}

static void thumb(const Table *t, int *t0, int *t1)
{
    int x0, y0, x1, y1, h;
    sb_rect(t, &x0, &y0, &x1, &y1);
    h = y1 - y0 - 2;
    *t0 = y0 + 1;
    *t1 = y1 - 1;
    /* as ui_scrollbar draws it */
    if (t->total > t->rows && t->total > 0) {
        *t0 = y0 + 1 + h * t->first / t->total;
        *t1 = y0 + 1 + h * (t->first + t->rows) / t->total;
        if (*t1 - *t0 < 8)
            *t1 = *t0 + 8;
        if (*t1 > y1 - 1) {
            *t0 -= *t1 - (y1 - 1);
            *t1 = y1 - 1;
        }
    }
}

int table_hit(Table *t, int x, int y, int *row, int *col)
{
    int x0, y0, x1, y1, c, cx;
    sb_rect(t, &x0, &y0, &x1, &y1);
    if (ui_hit(x, y, x0, y0, x1, y1)) {
        int t0, t1;
        thumb(t, &t0, &t1);
        return y < t0 ? TH_SB_UP : y >= t1 ? TH_SB_DOWN : TH_SB_THUMB;
    }
    if (ui_hit(x, y, t->x, t->y, x0, t->y + TBL_HDR_H)) {
        cx = t->x;
        for (c = 0; c < t->ncol; c++) {
            if (x < cx + t->cols[c].w) {
                *col = c;
                return TH_HEADER;
            }
            cx += t->cols[c].w;
        }
        return TH_NONE;
    }
    if (ui_hit(x, y, t->x, y0, x0, y1)) {
        *row = t->first + (y - y0) / TBL_ROW_H;
        return *row < t->total ? TH_ROW : TH_NONE;
    }
    return TH_NONE;
}

int table_sb_drag_to(Table *t, int y)
{
    int h = t->rows * TBL_ROW_H - 2;
    return t->total > 0 ? t->drag_first + (y - t->drag_y) * t->total / h : 0;
}

int table_sb_mouse(Table *t, const Event *e, int x, int y)
{
    int row, col;
    if (t->drag) {
        if (!(e->buttons & 1)) {
            t->drag = 0;
            return 1;
        }
        table_scroll(t, table_sb_drag_to(t, y));
        return 1;
    }
    if (!(e->buttons & 1))
        return 0;
    switch (table_hit(t, x, y, &row, &col)) {
    case TH_SB_UP:
        table_scroll(t, t->first - t->rows);
        return 1;
    case TH_SB_DOWN:
        table_scroll(t, t->first + t->rows);
        return 1;
    case TH_SB_THUMB:
        t->drag = 1;
        t->drag_y = y;
        t->drag_first = t->first;
        return 1;
    }
    return 0;
}

/* The selection by palette bank: the rows are drawn in colours 13 (the
   text) on 14 and 12 (the zebra), which bank 0 shows as black on white
   and light grey and bank 1 as the selection's colours; the selected
   row's lines get bank 1 in their descriptors (table 0, the window
   manager's). Nothing else uses 12-14, so nothing else on those lines
   changes colour. */
int table_banks(Table *t, int on)
{
    int n;
    if (!on || wm.screen.bpp != 4) {
        t->banks = 0;
        return 0;
    }
    video_pal_rgb(12, pal16[7][0], pal16[7][1], pal16[7][2]);
    video_pal_rgb(13, 0, 0, 0);
    video_pal_rgb(14, 255, 255, 255);
    for (n = 0; n < 16; n++)
        video_pal(16 + n, vid_palette[n]);
    video_pal(16 + 12, vid_palette[th.sel_bg]);
    video_pal(16 + 14, vid_palette[th.sel_bg]);
    video_pal(16 + 13, vid_palette[th.sel_fg]);
    t->fg = 13;
    t->bg = 14;
    t->bg2 = 12;
    t->banks = 1;
    t->bank_n = 0;
    return 1;
}

void table_banks_update(Table *t)
{
    unsigned *d = video_table(0);
    int y = 0, n = 0, k;
    if (t->sel >= 0 && shown(t, t->sel)) {
        y = t->win->c.y0 + rows_y(t) + (t->sel - t->first) * TBL_ROW_H;
        n = TBL_ROW_H;
        if (y < 0) {
            n += y;
            y = 0;
        }
        if (y + n > vid.h)
            n = vid.h - y;
        if (n < 0)
            n = 0;
    }
    for (k = t->bank_y; k < t->bank_y + t->bank_n; k++)
        d[k] &= ~(15u << 19);
    for (k = y; k < y + n; k++)
        d[k] |= 1u << 19;
    t->bank_y = y;
    t->bank_n = n;
}

/* ---- a form ---- */

static int texty(const Field *f)
{
    return f->type == FT_TEXT || f->type == FT_NUM || f->type == FT_MONEY;
}

static int focusable(const Field *f)
{
    return f->type != FT_BUTTON && f->type != FT_LABEL && !f->nofocus;
}

static void caret_xor(Form *fm)
{
    Field *f = &fm->f[fm->focus];
    int cx = f->x0 + 5 + strip_widthn(f->text, f->caret);
    gfx_vline(&fm->win->s, cx, f->y0 + 3, f->y1 - 3, th.text ^ th.bg, ROP_XOR);
    wm_damage(fm->win, cx, f->y0 + 3, cx + 1, f->y1 - 3);
    fm->caret_on ^= 1;
    fm->blink = wm.frames;
}

static void caret_off(Form *fm)
{
    if (fm->caret_on)
        caret_xor(fm);
}

int fw_field_full;              /* fields redrawn whole on every key (to compare) */

/* a text field after an edit: its text again from pixel `from` (the
   edit's place, in the text) to the end of the longer of the old and the
   new text, the only part that can have changed, and the caret */
static void field_text_from(Form *fm, int i, int from, int old_w)
{
    Field *f = &fm->f[i];
    Surface *s = &fm->win->s;
    int w = f->x1 - f->x0 - 4, new_w = strip_width(f->text), x0, x1, o = (f->x0 + 2) & 31;
    if (fw_field_full) {
        form_field(fm, i);
        return;
    }
    strip_begin(o + w);
    strip_text(o + 3, o + w - 2, f->text);
    x0 = (3 + from - 2) & ~7;       /* a glyph may reach a pixel or two left of its pen */
    if (x0 < 0)
        x0 = 0;
    x1 = 3 + (old_w > new_w ? old_w : new_w) + 2;
    if (x1 > w)
        x1 = w;
    if (x1 > x0) {
        strip_put(s, f->x0 + 2 + x0, f->y0 + 2, o + x0, x1 - x0, th.text, th.bg);
        wm_damage(fm->win, f->x0 + 2 + x0, f->y0 + 2, f->x0 + 2 + x1, f->y0 + 18);
    }
    fm->caret_on = 0;               /* the old one is gone, or was taken off */
    caret_xor(fm);
}

static void box(Surface *s, const Field *f, int focus)
{
    unsigned c = f->err ? th.accent : focus ? th.sel_bg : th.dark;
    gfx_frame(s, f->x0, f->y0, f->x1, f->y1, 1, c, ROP_COPY);
    gfx_frame(s, f->x0 + 1, f->y0 + 1, f->x1 - 1, f->y1 - 1, 1, focus || f->err ? c : th.bg,
              ROP_COPY);
}

void form_field(Form *fm, int i)
{
    Field *f = &fm->f[i];
    Surface *s = &fm->win->s;
    int focus = fm->focus == i, k, w = f->x1 - f->x0 - 4, o = (f->x0 + 2) & 31;
    int bx0 = f->x0, by0 = f->y0, bx1 = f->x1, by1 = f->y1;
    switch (f->type) {
    case FT_TEXT:
    case FT_NUM:
    case FT_MONEY:
        box(s, f, focus);
        strip_begin(o + w);
        strip_text(o + 3, o + w - 2, f->text);
        strip_put(s, f->x0 + 2, f->y0 + 2, o, w, th.text, th.bg);
        if (focus) {
            fm->caret_on = 0;
            caret_xor(fm);
        }
        break;
    case FT_DROP:
        box(s, f, focus);
        strip_begin(o + w);
        strip_text(o + 3, o + w - 18, f->items[f->val]);
        strip_put(s, f->x0 + 2, f->y0 + 2, o, w - 16, focus ? th.sel_fg : th.text,
                  focus ? th.sel_bg : th.bg);
        ui_panel(s, f->x1 - 18, f->y0 + 2, f->x1 - 2, f->y1 - 2, 0);
        arrow(s, f->x1 - 14, f->y0 + 8, 1, th.text);
        break;
    case FT_CHECK:
        ui_check(s, f->x0, f->y0, f->label, f->val);
        bx1 = f->x0 + 22 + font_width(font_sans, f->label);
        by0 = f->y0 - 3;
        by1 = f->y0 + 15;
        gfx_frame(s, f->x0 + 15, by0, bx1, by1, 1, focus ? th.text : th.bg, ROP_COPY);
        break;
    case FT_RADIO:
        bx0 = f->ix[0];
        bx1 = f->x1;
        by0 = f->y0 - 3;
        by1 = f->y0 + 15;
        gfx_fill(s, bx0, by0, bx1, by1, th.bg, ROP_COPY);
        for (k = 0; k < f->nitems; k++) {
            int x = f->ix[k];
            gfx_fill_circle(s, x + 6, f->y0 + 6, 5, th.bg, ROP_COPY);
            gfx_circle(s, x + 6, f->y0 + 6, 5, th.text, ROP_COPY);
            if (k == f->val)
                gfx_fill_circle(s, x + 6, f->y0 + 6, 2, th.text, ROP_COPY);
            font_draw(s, font_sans, x + 15, f->y0 + 11, f->items[k], th.text, -1);
            if (focus && k == f->val)
                gfx_frame(s, x + 13, by0, x + 18 + font_width(font_sans, f->items[k]), by1, 1,
                          th.text, ROP_COPY);
        }
        break;
    case FT_BUTTON:
        ui_button(s, f->x0, f->y0, f->x1, f->y1, f->label, f->pressed);
        break;
    case FT_LABEL:
        gfx_fill(s, f->x0, f->y0, f->x1, f->y1, th.bg, ROP_COPY);
        font_draw(s, font_sans, f->x0, f->y0 + 12, f->text, f->val ? th.accent : th.text, -1);
        break;
    }
    wm_damage(fm->win, bx0, by0, bx1, by1);
}

void form_draw(Form *fm)
{
    int i;
    for (i = 0; i < fm->n; i++) {
        Field *f = &fm->f[i];
        if (f->label && f->type != FT_CHECK && f->type != FT_BUTTON)
            font_draw(&fm->win->s, font_sans, f->lx, f->y0 + 14, f->label, th.text, -1);
        form_field(fm, i);
    }
}

void form_set_text(Field *f, const char *s)
{
    strncpy(f->text, s, sizeof f->text - 1);
    f->text[sizeof f->text - 1] = 0;
    f->len = strlen(f->text);
    f->caret = f->len;
}

const char *form_number(Field *f, int *v)
{
    static char msg[64];
    int i, n = 0;
    if (!f->len) {
        sprintf(msg, "%s: a number, please", f->label);
        return msg;
    }
    for (i = 0; i < f->len; i++) {
        if (f->text[i] < '0' || f->text[i] > '9') {
            sprintf(msg, "%s: digits only, not '%c'", f->label, f->text[i]);
            return msg;
        }
        n = n * 10 + f->text[i] - '0';
        if (n > 999999)
            break;
    }
    if (n < f->lo || n > f->hi) {
        sprintf(msg, "%s: from %d to %d", f->label, f->lo, f->hi);
        return msg;
    }
    *v = n;
    return 0;
}

const char *form_money(Field *f, int *cents)
{
    static char msg[64];
    int i, n = 0, dot = -1;
    for (i = 0; i < f->len; i++) {
        int c = f->text[i];
        if (c == '.' && dot < 0) {
            dot = i;
            continue;
        }
        if (c < '0' || c > '9' || (dot >= 0 && i - dot > 2) || n > 9999999) {
            sprintf(msg, "%s: an amount like 12.50", f->label);
            return msg;
        }
        n = n * 10 + c - '0';
    }
    if (!f->len || dot == f->len - 1) {
        sprintf(msg, "%s: an amount like 12.50", f->label);
        return msg;
    }
    if (dot < 0)
        n *= 100;
    else if (f->len - dot == 2)
        n *= 10;
    *cents = n;
    return 0;
}

static void validate(Form *fm, int i)
{
    Field *f = &fm->f[i];
    int v, err;
    if (f->type == FT_NUM)
        err = form_number(f, &v) != 0;
    else if (f->type == FT_MONEY)
        err = form_money(f, &v) != 0;
    else
        return;
    if (err != f->err) {
        f->err = err;
        form_field(fm, i);
    }
    if (fm->changed)
        fm->changed(fm, -1 - i);    /* validated: the application shows the message */
}

void form_focus(Form *fm, int i)
{
    int old = fm->focus;
    if (i == old)
        return;
    fm->focus = i;
    validate(fm, old);
    form_field(fm, old);
    form_field(fm, i);
}

static void form_next(Form *fm, int dir)
{
    int i = fm->focus, k;
    for (k = 0; k < fm->n; k++) {
        i = (i + dir + fm->n) % fm->n;
        if (focusable(&fm->f[i]))
            break;
    }
    form_focus(fm, i);
}

static void changed(Form *fm, int i)
{
    fm->dirty = 1;
    if (fm->changed)
        fm->changed(fm, i);
}

/* the drop-down's list */
static Form *pop_form;

static void pop_pick(int item)
{
    Form *fm = pop_form;
    Field *f;
    if (!fm)
        return;
    pop_form = 0;
    fm->popup = 0;
    f = &fm->f[fm->focus];
    if (item >= 0 && item != f->val) {
        f->val = item;
        form_field(fm, fm->focus);
        changed(fm, fm->focus);
    }
}

static void open_drop(Form *fm)
{
    Field *f = &fm->f[fm->focus];
    pop_form = fm;
    fm->popup = 1;
    popup_open(fm->win->c.x0 + f->x0, fm->win->c.y0 + f->y1, f->x1 - f->x0, f->items, f->nitems,
               f->val, pop_pick);
}

int form_key(Form *fm, const Event *e)
{
    Field *f = &fm->f[fm->focus];
    int k = e->key, ch = e->ch;
    if (e->type != EV_KEY)
        return FA_NONE;
    if (fm->popup && popup_key(e))
        return FA_USED;
    if (k == K_TAB) {
        form_next(fm, e->mods & M_SHIFT ? -1 : 1);
        return FA_USED;
    }
    if (k == K_ENTER) {
        validate(fm, fm->focus);
        return FA_SAVE;
    }
    if (k == K_ESC)
        return FA_REVERT;
    if (e->mods & M_CTRL)
        return k == 'd' ? FA_DELETE : k == 'n' ? FA_NEW : FA_NONE;
    if (texty(f)) {
        int old_w = strip_width(f->text), caret = f->caret;
        if (k == K_LEFT && f->caret > 0)
            caret--;
        else if (k == K_RIGHT && f->caret < f->len)
            caret++;
        else if (k == K_HOME)
            caret = 0;
        else if (k == K_END)
            caret = f->len;
        else if (k == K_BACKSPACE && f->caret > 0) {
            caret_off(fm);
            memmove(f->text + f->caret - 1, f->text + f->caret, f->len - f->caret + 1);
            f->caret--;
            f->len--;
            field_text_from(fm, fm->focus, strip_widthn(f->text, f->caret), old_w);
            changed(fm, fm->focus);
            return FA_USED;
        } else if (k == K_DEL && f->caret < f->len) {
            caret_off(fm);
            memmove(f->text + f->caret, f->text + f->caret + 1, f->len - f->caret);
            f->len--;
            field_text_from(fm, fm->focus, strip_widthn(f->text, f->caret), old_w);
            changed(fm, fm->focus);
            return FA_USED;
        } else if (ch >= 32 && ch < 127) {
            /* a character, if there's room for it in the text and the box */
            char one[2];
            one[0] = ch;
            one[1] = 0;
            if (f->len >= f->max || f->len >= (int)sizeof f->text - 1 ||
                strip_width(f->text) + strip_width(one) > f->x1 - f->x0 - 10)
                return FA_USED;
            caret_off(fm);
            memmove(f->text + f->caret + 1, f->text + f->caret, f->len - f->caret + 1);
            f->text[f->caret++] = ch;
            f->len++;
            field_text_from(fm, fm->focus, strip_widthn(f->text, f->caret - 1), old_w);
            changed(fm, fm->focus);
            return FA_USED;
        } else {
            return FA_NONE;
        }
        /* the caret moved: off where it was, on where it is */
        if (caret != f->caret) {
            caret_off(fm);
            f->caret = caret;
            caret_xor(fm);
        }
        return FA_USED;
    }
    if (f->type == FT_DROP) {
        if ((k == K_DOWN && f->val < f->nitems - 1) || (k == K_UP && f->val > 0)) {
            f->val += k == K_DOWN ? 1 : -1;
            form_field(fm, fm->focus);
            changed(fm, fm->focus);
            return FA_USED;
        }
        if (k == ' ') {
            open_drop(fm);
            return FA_USED;
        }
    } else if (f->type == FT_CHECK && k == ' ') {
        f->val ^= 1;
        form_field(fm, fm->focus);
        changed(fm, fm->focus);
        return FA_USED;
    } else if (f->type == FT_RADIO) {
        if ((k == K_RIGHT && f->val < f->nitems - 1) || (k == K_LEFT && f->val > 0)) {
            f->val += k == K_RIGHT ? 1 : -1;
            form_field(fm, fm->focus);
            changed(fm, fm->focus);
            return FA_USED;
        }
    }
    return FA_NONE;
}

int form_mouse(Form *fm, const Event *e, int x, int y)
{
    int pressed = e->buttons & ~fm->mb & 1, released = fm->mb & ~e->buttons & 1, i, k;
    fm->mb = e->buttons;
    if (released) {
        for (i = 0; i < fm->n; i++) {
            Field *f = &fm->f[i];
            if (f->type == FT_BUTTON && f->pressed) {
                f->pressed = 0;
                form_field(fm, i);
                if (ui_hit(x, y, f->x0, f->y0, f->x1, f->y1))
                    return FA_BUTTON + i;
            }
        }
        return FA_NONE;
    }
    if (!pressed)
        return FA_NONE;
    for (i = 0; i < fm->n; i++) {
        Field *f = &fm->f[i];
        int x1 = f->x1, y0 = f->y0, y1 = f->y1;
        if (f->type == FT_CHECK) {
            x1 = f->x0 + 22 + font_width(font_sans, f->label);
            y1 = f->y0 + 14;
        } else if (f->type == FT_RADIO) {
            y0 = f->y0 - 3;
            y1 = f->y0 + 15;
        }
        if (!ui_hit(x, y, f->type == FT_RADIO ? f->ix[0] : f->x0, y0, x1, y1))
            continue;
        switch (f->type) {
        case FT_BUTTON:
            f->pressed = 1;
            form_field(fm, i);
            return FA_USED;
        case FT_LABEL:
            return FA_NONE;
        case FT_CHECK:
            form_focus(fm, i);
            f->val ^= 1;
            form_field(fm, i);
            changed(fm, i);
            return FA_USED;
        case FT_RADIO:
            form_focus(fm, i);
            for (k = f->nitems - 1; k > 0 && x < f->ix[k]; k--)
                ;
            if (k != f->val) {
                f->val = k;
                form_field(fm, i);
                changed(fm, i);
            }
            return FA_USED;
        case FT_DROP:
            form_focus(fm, i);
            open_drop(fm);
            return FA_USED;
        default:
            f->caret = strip_index(f->text, x - f->x0 - 5);
            if (fm->focus != i)
                form_focus(fm, i);
            else
                form_field(fm, i);
            return FA_USED;
        }
    }
    return FA_NONE;
}

int form_blink_due(const Form *fm)
{
    return texty(&fm->f[fm->focus]) && wm.focus == fm->win && wm.frames - fm->blink >= 30;
}

void form_tick(Form *fm)
{
    if (form_blink_due(fm))
        caret_xor(fm);
}

/* ---- the popup list ---- */

static Window *pop_win;
static const char **pop_items;
static int pop_n, pop_hot, pop_done;
static void (*pop_cb)(int);

#define POP_H 16

static void pop_draw_item(int k)
{
    Surface *s = &pop_win->s;
    int hot = k == pop_hot;
    strip_begin(s->w);
    strip_text(6, s->w - 2, pop_items[k]);
    strip_put(s, 0, POP_H * k, 0, s->w, hot ? th.sel_fg : th.text, hot ? th.sel_bg : th.bg);
    wm_damage(pop_win, 0, POP_H * k, s->w, POP_H * k + POP_H);
}

static void pop_finish(int item)
{
    void (*cb)(int) = pop_cb;
    pop_done = 1;
    wm_close(pop_win);
    pop_win = 0;
    if (cb)
        cb(item);
}

static void pop_hot_to(int k)
{
    int old = pop_hot;
    if (k == old || k < 0 || k >= pop_n)
        return;
    pop_hot = k;
    if (old >= 0)
        pop_draw_item(old);
    pop_draw_item(k);
}

static void pop_mouse(Window *w, const Event *e, int x, int y)
{
    int k = x >= 0 && x < w->s.w && y >= 0 && y < w->s.h ? y / POP_H : -1;
    if (k >= 0)
        pop_hot_to(k);
    if ((e->buttons & 1) && k >= 0)
        pop_finish(k);
}

static void pop_close(Window *w)
{
    /* closed from outside (a click elsewhere): nothing picked */
    if (!pop_done) {
        void (*cb)(int) = pop_cb;
        pop_done = 1;
        pop_win = 0;
        if (cb)
            cb(-1);
    }
}

void popup_open(int x, int y, int w, const char **items, int n, int cur, void (*pick)(int))
{
    int k;
    if (pop_win)
        pop_finish(-1);
    if (y + POP_H * n > wm.screen.h - 4)
        y = wm.screen.h - 4 - POP_H * n;
    pop_items = items;
    pop_n = n;
    pop_hot = cur;
    pop_cb = pick;
    pop_done = 0;
    pop_win = wm_open(x, y, w, POP_H * n, "", WF_MENU);
    pop_win->mouse = pop_mouse;
    pop_win->close = pop_close;
    for (k = 0; k < n; k++)
        pop_draw_item(k);
}

int popup_is_open(void)
{
    return pop_win != 0;
}

void popup_close(void)
{
    if (pop_win)
        pop_finish(-1);
}

int popup_key(const Event *e)
{
    if (!pop_win || e->type != EV_KEY)
        return 0;
    if (e->key == K_DOWN || e->key == K_UP)
        pop_hot_to(pop_hot + (e->key == K_DOWN ? 1 : -1));
    else if (e->key == K_HOME || e->key == K_END)
        pop_hot_to(e->key == K_HOME ? 0 : pop_n - 1);
    else if (e->key == K_ENTER || e->key == ' ')
        pop_finish(pop_hot);
    else if (e->key == K_ESC)
        pop_finish(-1);
    return 1;
}

/* ---- the modal dialog ---- */

Window *fw_modal;

static struct {
    Window *win;
    char btn[3][16];
    int n, def, pressed, mb, done;
    void (*cb)(int);
} dlg;

#define DLG_W 320
#define DLG_H 96
#define DLG_BW 80

static void dlg_button(int k)
{
    Surface *s = &dlg.win->s;
    int x1 = DLG_W - 10 - (dlg.n - 1 - k) * (DLG_BW + 8), x0 = x1 - DLG_BW, y0 = DLG_H - 34;
    gfx_frame(s, x0 - 2, y0 - 2, x1 + 2, y0 + 26, 1, k == dlg.def ? th.text : th.bg, ROP_COPY);
    ui_button(s, x0, y0, x1, y0 + 24, dlg.btn[k], dlg.pressed == k);
    wm_damage(dlg.win, x0 - 2, y0 - 2, x1 + 2, y0 + 26);
}

static void dlg_finish(int c)
{
    void (*cb)(int) = dlg.cb;
    dlg.done = 1;
    fw_modal = 0;
    wm_close(dlg.win);
    dlg.win = 0;
    if (cb)
        cb(c);
}

static void dlg_key(Window *w, const Event *e)
{
    int old = dlg.def;
    if (e->type != EV_KEY)
        return;
    if (e->key == K_ENTER || e->key == ' ')
        dlg_finish(dlg.def);
    else if (e->key == K_ESC)
        dlg_finish(dlg.n - 1);
    else if (e->key == K_TAB || e->key == K_RIGHT)
        dlg.def = (dlg.def + 1) % dlg.n;
    else if (e->key == K_LEFT)
        dlg.def = (dlg.def + dlg.n - 1) % dlg.n;
    if (dlg.win && old != dlg.def) {
        dlg_button(old);
        dlg_button(dlg.def);
    }
}

static int dlg_hit(int x, int y)
{
    int k;
    for (k = 0; k < dlg.n; k++) {
        int x1 = DLG_W - 10 - (dlg.n - 1 - k) * (DLG_BW + 8), y0 = DLG_H - 34;
        if (ui_hit(x, y, x1 - DLG_BW, y0, x1, y0 + 24))
            return k;
    }
    return -1;
}

static void dlg_mouse(Window *w, const Event *e, int x, int y)
{
    int pressed = e->buttons & ~dlg.mb & 1, released = dlg.mb & ~e->buttons & 1, k;
    dlg.mb = e->buttons;
    if (pressed && (k = dlg_hit(x, y)) >= 0) {
        dlg.pressed = k;
        dlg_button(k);
    } else if (released && dlg.pressed >= 0) {
        k = dlg.pressed;
        dlg.pressed = -1;
        dlg_button(k);
        if (dlg_hit(x, y) == k)
            dlg_finish(k);
    }
}

/* the window manager has no modal windows: this one raises itself
   whenever something else got on top */
static void dlg_tick(Window *w)
{
    if (wm.top != w || wm.focus != w)
        wm_raise(w);
}

static void dlg_close(Window *w)
{
    if (!dlg.done) {
        void (*cb)(int) = dlg.cb;
        dlg.done = 1;
        fw_modal = 0;
        dlg.win = 0;
        if (cb)
            cb(dlg.n - 1);
    }
}

void dialog_open(const char *title, const char *line1, const char *line2, const char *buttons,
                 void (*done)(int choice))
{
    Surface *s;
    const char *p = buttons;
    int k;
    memset(&dlg, 0, sizeof dlg);
    dlg.pressed = -1;
    while (*p && dlg.n < 3) {
        k = 0;
        while (*p && *p != '|' && k < 15)
            dlg.btn[dlg.n][k++] = *p++;
        dlg.n++;
        if (*p == '|')
            p++;
    }
    dlg.cb = done;
    dlg.mb = mouse_buttons;
    dlg.win = wm_open((wm.screen.w - DLG_W) / 2, (wm.screen.h - DLG_H) / 2 - 40, DLG_W, DLG_H,
                      title, WF_TITLE | WF_FIXED);
    dlg.win->key = dlg_key;
    dlg.win->mouse = dlg_mouse;
    dlg.win->tick = dlg_tick;
    dlg.win->close = dlg_close;
    fw_modal = dlg.win;
    s = &dlg.win->s;
    /* a warning sign: a circle with an exclamation mark */
    gfx_fill_circle(s, 26, 26, 14, th.accent, ROP_COPY);
    gfx_fill(s, 25, 16, 28, 30, th.bg, ROP_COPY);
    gfx_fill(s, 25, 32, 28, 35, th.bg, ROP_COPY);
    font_draw(s, font_sans, 52, 22, line1, th.text, -1);
    if (line2)
        font_draw(s, font_sans, 52, 40, line2, th.text, -1);
    for (k = 0; k < dlg.n; k++)
        dlg_button(k);
}

/* ---- horizontal bars ---- */

static const unsigned char pats[8][8] = {
    {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF},
    {0x55, 0xAA, 0x55, 0xAA, 0x55, 0xAA, 0x55, 0xAA},
    {0x11, 0x22, 0x44, 0x88, 0x11, 0x22, 0x44, 0x88},
    {0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00},
    {0x88, 0x44, 0x22, 0x11, 0x88, 0x44, 0x22, 0x11},
    {0x99, 0x99, 0xFF, 0x99, 0x99, 0xFF, 0x99, 0x99},
    {0x33, 0x33, 0x33, 0x33, 0x33, 0x33, 0x33, 0x33},
    {0x81, 0x42, 0x24, 0x18, 0x18, 0x24, 0x42, 0x81},
};
/* at 4 bits, colours that aren't 12-14 (table_banks') */
static const unsigned char bar_colours[8] = {1, 2, 3, 4, 5, 6, 9, 10};

void bars_draw(Surface *s, int x0, int y0, int x1, int y1, const char **labels,
               const int *values, const char **texts, int n, int max)
{
    int k, rh = (y1 - y0) / n, bx = x0 + 92, bw = x1 - 74 - bx;
    gfx_fill(s, x0, y0, x1, y1, th.bg, ROP_COPY);
    for (k = 0; k < n; k++) {
        int y = y0 + k * rh, len = max > 0 ? (int)((long)values[k] / (max / bw + 1)) : 0;
        if (len > bw)
            len = bw;
        font_draw(s, font_sans, x0 + 2, y + rh / 2 + 5, labels[k], th.text, -1);
        if (len > 0) {
            if (s->bpp >= 4)
                gfx_fill(s, bx, y + 3, bx + len, y + rh - 3, bar_colours[k & 7], ROP_COPY);
            else
                gfx_fill_pat(s, bx, y + 3, bx + len, y + rh - 3, pats[k & 7], th.text, th.bg);
            gfx_frame(s, bx, y + 3, bx + len, y + rh - 3, 1, th.text, ROP_COPY);
        }
        font_draw(s, font_sans, x1 - 4 - font_width(font_sans, texts[k]), y + rh / 2 + 5,
                  texts[k], th.text, -1);
    }
    gfx_vline(s, bx - 1, y0, y1, th.text, ROP_COPY);
}
