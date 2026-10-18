/* The redraw strategies. The map is a world bitmap in bank 1, drawn
   once; the descriptors show a viewport of it, so scrolling rewrites
   400 descriptors and nothing else. What's left is the units:

   S_DIRTY   one world bitmap, shown: each frame erases the units where
             they were (copying the clean world's words back, from bank
             0) and draws them where they are, right after the frame's
             end. Where the beam overtakes the drawing, a unit flickers.
   S_BEAM    the same, but a band of 32 lines at a time, top to bottom,
             each band's erasing and drawing done together: racing the
             beam (P1 counts the bands it caught).
   S_DOUBLE  two world bitmaps, one per descriptor table: draw in the
             one not shown, then flip TSEL. Each erases what it drew two
             frames ago.
   S_FULL    two screen buffers: each frame the viewport is copied whole
             from the clean world, then the units drawn; flip.
   S_TILES   the same, but the viewport built from the tile map tile by
             tile, as a machine without the memory for a world bitmap
             would.

   The screen buffers have a guard band (4 words each side, 16 rows above
   and below) that only the descriptors skip, so a unit half off the
   viewport is drawn without clipping. */

#include <stdlib.h>
#include "rts.h"
#include "mini.h"

const char *strategy_names[S_N] = {"dirty", "beam", "double", "full", "tiles"};
int strategy = -1, cam_x, cam_y;
int sel_on, sel_x0, sel_y0, sel_x1, sel_y1;
int tears, count_tears = 1;
unsigned t_draw, t_erase, t_bg, t_items;

#define GUARD 4
#define GUARDH 16
#define BAND_LINES 32           /* screen lines: 32 rows in M0, 16 in M1 */

static unsigned *scr[2];        /* S_FULL, S_TILES */
static int gw;                  /* their words a row */
static int *srow;               /* each of their rows' offset from the viewport's, from -GUARDH */
static int back;                /* the buffer drawn this frame (S_DOUBLE, S_FULL, S_TILES) */
static int wp4;                 /* the world's pitch in bytes */
static int desc_cam[2][2];      /* the camera each table shows (S_DIRTY, S_BEAM, S_DOUBLE) */
static Surface wsurf[2], ssurf[2];

/* what was drawn in a buffer, to erase: world row y, word col, n words, h rows */
typedef struct {
    int y, col, n, h;
} Dirty;
#define MAX_DIRTY (MAX_UNITS + 4)
static Dirty dirty[2][MAX_DIRTY], rdirty[2][4];
static int ndirty[2], nrdirty[2];

/* the units in order of their feet's y, sorted again each frame (they
   barely move, so an insertion sort costs a pass) */
static unsigned short order[MAX_UNITS];
static int ykey[MAX_UNITS];
static int norder;

/* a unit as drawn: its sprite's data at its phase */
typedef struct {
    short y, col, n, h;
    const unsigned *data;
    int pad;
} Item;
static Item items[MAX_UNITS];
static int nitems;

#define SEL_COLOUR 15           /* white, the map's */

static void sort_units(void)
{
    int k, j;
    if (norder != nunits) {
        for (k = 0; k < nunits; k++)
            order[k] = k;
        norder = nunits;
    }
    for (k = 0; k < norder; k++)
        ykey[k] = units[k].y;
    for (k = 1; k < norder; k++) {
        unsigned o = order[k];
        int y = ykey[o];
        for (j = k; j > 0 && ykey[order[j - 1]] > y; j--)
            order[j] = order[j - 1];
        order[j] = o;
    }
}

/* the units that touch the viewport, as items: their world row and column */
static void make_items_(void);

static void make_items(void)
{
    unsigned t0 = video_ticks();
    make_items_();
    t_items = video_ticks() - t0;
}

static void make_items_(void)
{
    int k, vx0 = cam_x - SPR_W, vx1 = cam_x + view_w, vy0 = cam_y - 16, vy1 = cam_y + view_h;
    sort_units();
    nitems = 0;
    for (k = 0; k < norder; k++) {
        Unit *u = &units[order[k]];
        int fx = u->x >> 4, fy = u->y >> 4, px = fx - 6, py, ph;
        const Sprite *sp;
        Item *it;
        if (px <= vx0 || px >= vx1 || fy <= vy0 || fy - 15 >= vy1)
            continue;
        sp = &sprites[SPR_INDEX(u->type, u->team, u->facing, u->step, u->sel)];
        py = fy - 15 + sp->y0;
        if (py + sp->h <= cam_y || py >= vy1)
            continue;
        ph = px & (ppw - 1);
        it = &items[nitems++];
        it->y = py;
        it->col = px >> pshift;
        it->n = sp->n[ph];
        it->h = sp->h;
        it->data = sp->data[ph];
    }
}

/* the selection rectangle, clipped to the viewport: 0 if none */
static int sel_rect(int *x0, int *y0, int *x1, int *y1)
{
    int a = sel_x0 < sel_x1 ? sel_x0 : sel_x1, b = sel_x0 < sel_x1 ? sel_x1 : sel_x0;
    int c = sel_y0 < sel_y1 ? sel_y0 : sel_y1, d = sel_y0 < sel_y1 ? sel_y1 : sel_y0;
    if (!sel_on)
        return 0;
    b++;
    d++;
    if (a < cam_x)
        a = cam_x;
    if (c < cam_y)
        c = cam_y;
    if (b > cam_x + view_w)
        b = cam_x + view_w;
    if (d > cam_y + view_h)
        d = cam_y + view_h;
    if (b - a < 2 || d - c < 2)
        return 0;
    *x0 = a;
    *y0 = c;
    *x1 = b;
    *y1 = d;
    return 1;
}

/* its four edges as dirty rectangles */
static void sel_dirty(int b, int x0, int y0, int x1, int y1)
{
    Dirty *d = rdirty[b];
    int c0 = x0 >> pshift, c1 = (x1 - 1) >> pshift;
    d[0].y = y0;
    d[0].col = c0;
    d[0].n = c1 - c0 + 1;
    d[0].h = 1;
    d[1] = d[0];
    d[1].y = y1 - 1;
    d[2].y = y0;
    d[2].col = c0;
    d[2].n = 1;
    d[2].h = y1 - y0;
    d[3] = d[2];
    d[3].col = c1;
    nrdirty[b] = 4;
}

/* ---- the descriptors ---- */

/* the viewport's lines in table t from `top`, pitch words a row */
static void desc_view(int t, unsigned *top, int pitch)
{
    k_desc_c(video_table(t), video_word(top), pitch, view_h, rep);
}

static void desc_world(int t, int b)
{
    if (desc_cam[t][0] == cam_x && desc_cam[t][1] == cam_y)
        return;
    desc_view(t, world[b] + wrowo[cam_y] + (cam_x >> pshift), wpitch);
    desc_cam[t][0] = cam_x;
    desc_cam[t][1] = cam_y;
}

/* ---- the world strategies ---- */

static void erase_list(unsigned *w, Dirty *d, int n)
{
    while (n-- > 0) {
        int o = wrowo[d->y] + d->col;
        k_copy(w + o, clean + o, d->n, d->h, wp4, wp4);
        d++;
    }
}

static void erase_world(int b)
{
    erase_list(world[b], rdirty[b], nrdirty[b]);
    nrdirty[b] = 0;
    erase_list(world[b], dirty[b], ndirty[b]);
    ndirty[b] = 0;
}

static void draw_world(int b)
{
    unsigned *w = world[b];
    Dirty *d = dirty[b];
    Item *it = items;
    int k, x0, y0, x1, y1;
    for (k = 0; k < nitems; k++, it++, d++) {
        k_sprite(w + wrowo[it->y] + it->col, it->data, it->n, it->h, wp4);
        d->y = it->y;
        d->col = it->col;
        d->n = it->n;
        d->h = it->h;
    }
    ndirty[b] = nitems;
    if (sel_rect(&x0, &y0, &x1, &y1)) {
        gfx_frame(&wsurf[b], x0, y0, x1, y1, 1, SEL_COLOUR, ROP_COPY);
        sel_dirty(b, x0, y0, x1, y1);
    }
}

/* the beam's position: the frame count (its low bits) x 1024 + the line
   (P1); the frame's end interrupt may be pending, not yet counted */
static int beam_pos(void)
{
    unsigned f, b, st;
    int line;
    do {
        f = rt_frames;
        b = VID_BEAM;
        st = IRQ_STATUS;
    } while (f != rt_frames);
    line = b & 0x3FF;
    if ((st & 16) && line < vid.table)
        f++;
    return (f & 0xFFFFF) << 10 | line;
}

/* whether the beam, going from p0 to p1, fetched any of screen lines
   [l0, l1) (picture lines, which are frame lines vid.table + 1 on) */
static int beam_crossed(int p0, int p1, int l0, int l1)
{
    int f0 = p0 >> 10, a = p0 & 1023, f1 = p1 >> 10, e = p1 & 1023, top = vid.table + 1;
    if (f1 - f0 >= 2)
        return 1;
    if (f1 == f0)
        return a < top + l1 && e >= top + l0;
    return a < top + l1 || e >= top + l0;
}

/* S_DIRTY: everything erased, then everything drawn; units the beam
   passed between the two are counted (they flicker) */
static void dirty_frame(void)
{
    int p0, pm, k;
    unsigned t0 = video_ticks(), t1;
    desc_world(0, 0);
    p0 = beam_pos();
    erase_world(0);
    pm = beam_pos();
    t1 = video_ticks();
    t_erase = t1 - t0;
    draw_world(0);
    t_draw = video_ticks() - t1;
    /* the units the beam passed between their erasing and their drawing:
       shown missing or cut. Both passes go top to bottom, so unit k's
       times are interpolated from the beam at the passes' ends */
    if (count_tears && nitems) {
        int p1 = beam_pos();
        if (p0 >> 10 == p1 >> 10) {
            int f = p0 & ~1023, se = ((pm - p0) << 8) / nitems, sd = ((p1 - pm) << 8) / nitems;
            int e = (p0 & 1023) << 8, d = (pm & 1023) << 8;
            for (k = 0; k < nitems; k++, e += se, d += sd) {
                int l0 = (items[k].y - cam_y) << (rep - 1);
                if (beam_crossed(f | e >> 8, f | d >> 8, l0, l0 + (items[k].h << (rep - 1))))
                    tears++;
            }
        } else {
            for (k = 0; k < nitems; k++) {
                int l0 = (items[k].y - cam_y) << (rep - 1);
                if (beam_crossed(p0, p1, l0, l0 + (items[k].h << (rep - 1))))
                    tears++;
            }
        }
    }
}

/* S_BEAM: band by band, top to bottom, each band's erasing and drawing
   together so the beam never sees a band half done, if it stays behind */
static void erase_part(unsigned *w, const Dirty *d, int r0, int r1)
{
    int o;
    if (r0 < d->y)
        r0 = d->y;
    if (r1 > d->y + d->h)
        r1 = d->y + d->h;
    if (r0 >= r1)
        return;
    o = wrowo[r0] + d->col;
    k_copy(w + o, clean + o, d->n, r1 - r0, wp4, wp4);
}

static void beam_frame(void)
{
    unsigned *w = world[0];
    Dirty *od = dirty[0], *nd;      /* last frame's */
    int nold = ndirty[0], oi = 0, ni = 0, b, k, x0 = 0, y0 = 0, x1 = 0, y1 = 0, rect;
    int band = BAND_LINES >> (rep - 1), nb = (view_h + band - 1) / band;
    unsigned t0 = video_ticks();
    Dirty ord[4];
    int nord = nrdirty[0];
    for (k = 0; k < nord; k++)
        ord[k] = rdirty[0][k];
    desc_world(0, 0);
    rect = sel_rect(&x0, &y0, &x1, &y1);
    nrdirty[0] = 0;
    if (rect)
        sel_dirty(0, x0, y0, x1, y1);
    /* what's above the viewport (not seen): at once */
    while (oi < nold && od[oi].y + od[oi].h <= cam_y - 16) {
        erase_part(w, &od[oi], od[oi].y, od[oi].y + od[oi].h);
        oi++;
    }
    for (b = 0; b < nb; b++) {
        int r0 = cam_y + b * band, r1 = r0 + band, p0 = beam_pos(), j;
        if (b == 0)
            r0 -= 16;                   /* the first band takes what's just above, */
        if (b == nb - 1)
            r1 = cam_y + view_h + 16;   /* the last what's just below */
        for (j = 0; j < nord; j++)
            erase_part(w, &ord[j], r0, r1);
        /* the old items that reach into this band (sorted by y, at most 16 tall) */
        while (oi < nold && od[oi].y + 16 <= r0)
            oi++;
        for (j = oi; j < nold && od[j].y < r1; j++)
            erase_part(w, &od[j], r0, r1);
        while (ni < nitems && items[ni].y + 16 <= r0)
            ni++;
        for (j = ni; j < nitems && items[j].y < r1; j++) {
            Item *it = &items[j];
            int a = it->y > r0 ? it->y : r0, e = it->y + it->h < r1 ? it->y + it->h : r1;
            if (a < e)
                k_sprite(w + wrowo[a] + it->col,
                         a > it->y ? it->data + (a - it->y) * it->n * 2 : it->data, it->n, e - a,
                         wp4);
        }
        if (rect && y0 < r1 && y1 > r0) {
            int a = y0 > r0 ? y0 : r0, e = y1 < r1 ? y1 : r1;
            if (y0 >= r0)
                gfx_fill(&wsurf[0], x0, y0, x1, y0 + 1, SEL_COLOUR, ROP_COPY);
            if (y1 - 1 < r1)
                gfx_fill(&wsurf[0], x0, y1 - 1, x1, y1, SEL_COLOUR, ROP_COPY);
            gfx_fill(&wsurf[0], x0, a, x0 + 1, e, SEL_COLOUR, ROP_COPY);
            gfx_fill(&wsurf[0], x1 - 1, a, x1, e, SEL_COLOUR, ROP_COPY);
        }
        if (beam_crossed(p0, beam_pos(), b * BAND_LINES, (b + 1) * BAND_LINES))
            tears++;
    }
    /* the rest of the old ones (below the viewport, not seen) */
    for (; oi < nold; oi++)
        if (od[oi].y >= cam_y + view_h + 16)
            erase_part(w, &od[oi], od[oi].y, od[oi].y + od[oi].h);
    /* this frame's items are next frame's to erase */
    for (k = 0; k < nitems; k++) {
        nd = &dirty[0][k];
        nd->y = items[k].y;
        nd->col = items[k].col;
        nd->n = items[k].n;
        nd->h = items[k].h;
    }
    ndirty[0] = nitems;
    t_draw = video_ticks() - t0;
    t_erase = 0;
}

/* ---- the screen-buffer strategies ---- */

static unsigned *view_origin(int b) { return scr[b] + GUARDH * gw + GUARD; }

static void full_frame(int b, int from_tiles)
{
    unsigned *o = view_origin(b);
    Item *it = items;
    int k, cw = cam_x >> pshift, x0, y0, x1, y1;
    unsigned t0 = video_ticks(), t1;
    if (!from_tiles) {
        k_copy(o, clean + wrowo[cam_y] + cw, view_words, view_h, gw * 4, wp4);
    } else {
        int tw = TILE / ppw, tx, ty, tx0 = cam_x / TILE, ty0 = cam_y / TILE;
        int tx1 = (cam_x + view_w - 1) / TILE, ty1 = (cam_y + view_h - 1) / TILE;
        for (ty = ty0; ty <= ty1; ty++) {
            const unsigned char *m = map + ty * map_w;
            unsigned *row = o + srow[ty * TILE - cam_y + GUARDH] + ((tx0 * TILE - cam_x) >> pshift);
            for (tx = tx0; tx <= tx1; tx++, row += tw)
                k_tile(row, tiles + m[tx] * tile_words, tw, gw * 4);
        }
    }
    t1 = video_ticks();
    t_bg = t1 - t0;
    for (k = 0; k < nitems; k++, it++)
        k_sprite(o + srow[it->y - cam_y + GUARDH] + it->col - cw, it->data, it->n, it->h, gw * 4);
    if (sel_rect(&x0, &y0, &x1, &y1))
        gfx_frame(&ssurf[b], x0 - cam_x, y0 - cam_y, x1 - cam_x, y1 - cam_y, 1, SEL_COLOUR,
                  ROP_COPY);
    t_draw = video_ticks() - t1;
}

/* ---- setting up and switching ---- */

void render_init(void)
{
    int b, r, rows = view_h + 2 * GUARDH;
    wp4 = wpitch * 4;
    gw = view_words + 2 * GUARD;
    for (b = 0; b < 2; b++) {
        scr[b] = vram_alloc(gw * 4 * rows);
        gfx_init(&wsurf[b], world[b], world_w, world_h, wpitch, fmt);
        gfx_init(&ssurf[b], view_origin(b), view_w, view_h, gw, fmt);
    }
    srow = malloc(rows * sizeof(int));
    for (r = 0; r < rows; r++)
        srow[r] = (r - GUARDH) * gw;
}

void render_set(int s)
{
    int t;
    if (s == strategy)
        return;
    /* the world bitmaps clean again: erase what each still has drawn */
    if (strategy == S_DIRTY || strategy == S_BEAM || strategy == S_DOUBLE) {
        erase_world(0);
        if (strategy == S_DOUBLE)
            erase_world(1);
    }
    ndirty[0] = ndirty[1] = nrdirty[0] = nrdirty[1] = 0;
    strategy = s;
    for (t = 0; t < 2; t++) {
        desc_cam[t][0] = desc_cam[t][1] = -1;
        video_lines(t, view_h * rep, hud_h, hud, view_words * 4, mode ? 0 : 1);
        if (s == S_FULL || s == S_TILES)
            desc_view(t, view_origin(t), gw);
        else
            desc_world(t, s == S_DOUBLE ? t : 0);
    }
    back = 1;
    video_show(0);
}

/* the frame's end, freshly: if the last frame's work ran over, the beam
   is in the picture by now and racing it would lose, so the next one */
static int wait_fresh(void)
{
    int n = video_wait();
    if ((beam_pos() & 1023) > vid.table)
        n += video_wait();
    return n;
}

int render_frame(void)
{
    int n;
    t_bg = t_erase = 0;
    switch (strategy) {
    case S_DIRTY:
        make_items();
        n = wait_fresh();
        dirty_frame();
        return n;
    case S_BEAM:
        make_items();
        n = wait_fresh();
        beam_frame();
        return n;
    case S_DOUBLE: {
        unsigned t0, t1;
        make_items();
        t0 = video_ticks();
        desc_world(back, back);
        erase_world(back);
        t1 = video_ticks();
        t_erase = t1 - t0;
        draw_world(back);
        t_draw = video_ticks() - t1;
        break;
    }
    default:
        make_items();
        full_frame(back, strategy == S_TILES);
        break;
    }
    /* the flip: this buffer from the next frame */
    n = video_wait();
    video_ctrl(back ? VC_TSEL : 0, VC_TSEL);
    back ^= 1;
    return n;
}
