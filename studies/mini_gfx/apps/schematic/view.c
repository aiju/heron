/* The canvas (sch.h): the window's store shows the sheet at a zoom and an
   origin. Anything that changes redraws its rectangle from the model
   (view_region: the background, the grid, the wires, the parts, the dots
   and labels that meet it, clipped to it) and damages it, and the window
   manager copies it to the screen at the frame's end.

   While dragging, the rubber bands, the selection rectangle and the ghost
   of what's moving are an overlay drawn in XOR over the sheet: into the
   store and damaged (BAND_STORE), straight onto the screen (BAND_SCREEN,
   when nothing covers the canvas), or not in XOR at all but with the
   sheet redrawn under them each time (BAND_REDRAW): the three ways
   measured against each other.

   Panning copies the store and draws the strips that come into view;
   zooming redraws everything, the symbols' sprites made again at the new
   zoom as they're needed. */

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sch.h"
#include "video.h"

View V;
char status_text[128];
static int status_dirty;

static Surface gt;              /* the grid's row of dots, at the origin's phase */
static int gt_phase = -1, gt_step;

/* the overlay as drawn: shown or not, where, and when it may come back */
static int ov_shown, ov_mode;
static unsigned ov_hold;

/* damage in the drawing area; in the sheet view what's drawn is what's
   shown, and there's nothing to copy */
static void vdamage(int x0, int y0, int x1, int y1)
{
    if (!V.sheet)
        wm_damage(V.win, x0, y0, x1, y1);
}

static int mod(int a, int m)
{
    a %= m;
    return a < 0 ? a + m : a;
}

static int gridstep(int z)
{
    /* at the smallest zoom, a dot every fourth grid step */
    return z == 1 ? 4 * GRID : GRID * z;
}

void view_init(Window *w, int zoom)
{
    int ppw = 1 << w->s.pshift, pitch;
    V.win = w;
    gfx_sub(&V.d, &w->s, 0, 0, w->s.w, w->s.h - STATUS_H);
    gfx_sub(&V.status, &w->s, 0, w->s.h - STATUS_H, w->s.w, w->s.h);
    V.w = V.d.w;
    V.h = V.d.h;
    V.zoom = zoom;
    V.gridstep = gridstep(zoom);
    V.grid_on = 1;
    V.textgen = 1;
    V.layers = LY_ALL;
    V.pan_word = 1;
    pitch = (V.w + 64 + ppw - 1) / ppw + 1;
    gfx_init(&gt, malloc(pitch * 4), V.w + 64, 1, pitch, w->s.fmt);
    view_colours();
}

/* the colours: at 2 bits the palette is the editor's (the window manager's
   greys become its ink, grid, selection and paper) */
void view_colours(void)
{
    Ink k;
    switch (V.d.bpp) {
    case 1:
        k.bg = 1; k.grid = 0; k.wire = 0; k.part = 0; k.text = 0; k.sel = 0; k.hl = 0; k.ones = 1;
        break;
    case 2:
        k.bg = 3; k.grid = 1; k.wire = 0; k.part = 0; k.text = 0; k.sel = 2; k.hl = 2; k.ones = 3;
        video_pal_all(0, rgb565(16, 24, 64));
        video_pal_all(1, rgb565(150, 165, 190));
        video_pal_all(2, rgb565(40, 130, 230));
        video_pal_all(3, rgb565(250, 250, 244));
        break;
    default:
        /* 4 and 8 bits: rt/palette.c's 16 */
        k.bg = 15; k.grid = 7; k.wire = 2; k.part = 4; k.text = 1; k.sel = 9; k.hl = 13;
        k.ones = (1u << V.d.bpp) - 1;
        break;
    }
    /* the cursor's third colour: the selection's, for the ghost of a part */
    video_pal(255, rgb565(40, 130, 230));
    V.ink = k;
    gt_phase = -1;
}

int view_ux(int px)
{
    int v = px + V.ox;
    return V.zoom == 1 ? v : V.zoom == 2 ? v >> 1 : V.zoom == 4 ? v >> 2 : (v < 0 ? v - 2 : v) / 3;
}

int view_uy(int py)
{
    int v = py + V.oy;
    return V.zoom == 1 ? v : V.zoom == 2 ? v >> 1 : V.zoom == 4 ? v >> 2 : (v < 0 ? v - 2 : v) / 3;
}

int snap(int u)
{
    return (u + GRID / 2) & ~(GRID - 1);
}

/* ---- drawing from the model ---- */

static int meets(const Rect *r, int x0, int y0, int x1, int y1)
{
    return r->x0 < x1 && x0 < r->x1 && r->y0 < y1 && y0 < r->y1;
}

static void grid_template(void)
{
    int step = V.gridstep, ph = mod(V.ox, step), x;
    if (gt.w < V.w + 64) {
        int ppw = 1 << V.d.pshift, pitch = (V.w + 64 + ppw - 1) / ppw + 1;
        free(gt.bits);
        gfx_init(&gt, malloc(pitch * 4), V.w + 64, 1, pitch, V.d.fmt);
        gt_phase = -1;
    }
    if (ph == gt_phase && step == gt_step)
        return;
    gt_phase = ph;
    gt_step = step;
    gfx_fill(&gt, 0, 0, gt.w, 1, V.ink.bg, ROP_COPY);
    for (x = mod(-V.ox, step); x < gt.w; x += step)
        gfx_pixel(&gt, x, 0, V.ink.grid, ROP_COPY);
}

/* the grid's rows in a rectangle that is clear: one copy, from the row of
   dots (a source whose rows are all the same, pitch 0) to every
   gridstep'th row (a destination whose pitch is gridstep rows) */
static void draw_grid(int x0, int y0, int x1, int y1)
{
    Surface dst, src;
    int step = V.gridstep, y = y0 + mod(-(y0 + V.oy), step), n;
    if (y >= y1)
        return;
    n = (y1 - 1 - y) / step + 1;
    grid_template();
    dst = V.d;
    dst.bits = V.d.bits + y * V.d.pitch;
    dst.pitch = V.d.pitch * step;
    dst.h = n;
    gfx_noclip(&dst);
    src = gt;
    src.pitch = 0;
    src.h = n;
    gfx_blit(&dst, x0, 0, &src, x0, 0, x1 - x0, n, ROP_COPY);
}

void wire_rect(const Wire *w, Rect *r)
{
    r->x0 = PX(w->x0) - 1;
    r->y0 = PY(w->y0) - 1;
    r->x1 = PX(w->x1) + 2;
    r->y1 = PY(w->y1) + 2;
}

static void draw_wire(const Wire *w)
{
    unsigned c = w->hl ? V.ink.hl : w->sel ? V.ink.sel : V.ink.wire;
    /* at 1 bit a pixel there's no colour: highlighted and selected wires are thick */
    int t = (w->hl || w->sel) && V.d.bpp == 1;
    if (w->x0 == w->x1 && !t)
        sch_vline(&V.d, PX(w->x0), PY(w->y0), PY(w->y1), c, ROP_COPY);
    else
        gfx_fill(&V.d, PX(w->x0) - t, PY(w->y0) - t, PX(w->x1) + 1 + t, PY(w->y1) + 1 + t, c,
                 ROP_COPY);
}

/* the labels: their bitmaps and places for this zoom, and the part's
   rectangle with them, relative to its origin's pixel */
static void label_place(Part *p, int k, int *lx, int *ly)
{
    int x0, y0, x1, y1, w = p->lw[k], h = p->lh, style = symbols[p->type].labels;
    part_box(p, &x0, &y0, &x1, &y1);
    x0 = ZS(x0 - p->x);
    x1 = ZS(x1 - p->x);
    y0 = ZS(y0 - p->y);
    y1 = ZS(y1 - p->y);
    if (style == LS_VALUE_ABOVE) {
        *lx = (x0 + x1) / 2 - w / 2;
        *ly = p->rot == 2 ? y1 + 3 : y0 - h - 2;
    } else if (style == LS_ABOVE || x1 - x0 >= y1 - y0) {
        *lx = (x0 + x1) / 2 - w / 2;
        *ly = k == 0 ? y0 - h - 2 : y1 + 3;
    } else {
        *lx = x1 + 4;
        *ly = k == 0 ? (y0 + y1) / 2 - h - 1 : (y0 + y1) / 2 + 1;
    }
}

typedef struct {
    short lx[2], ly[2];
    short x0, y0, x1, y1;
} Place;

static Place places[MAXPARTS];

void part_labels(Part *p)
{
    int k, big = V.zoom >= 3, style = symbols[p->type].labels;
    Place *pl = &places[p - sh.parts];
    const Sprite *sp;
    if (p->lgen == V.textgen)
        return;
    for (k = 0; k < 2; k++) {
        free(p->lbits[k]);
        p->lbits[k] = 0;
        p->lw[k] = 0;
    }
    for (k = 0; k < 2; k++) {
        TextBm t;
        if (style == LS_NONE || (style == LS_VALUE_ABOVE && k == 0) || (V.zoom == 1 && k == 1))
            continue;
        text_make(&t, k ? p->val : p->ref, big);
        p->lbits[k] = t.bits;
        p->lw[k] = t.w;
        p->lh = t.h;
    }
    sp = sym_sprite(p->type, p->rot, V.zoom);
    pl->x0 = -sp->ox;
    pl->y0 = -sp->oy;
    pl->x1 = pl->x0 + sp->w;
    pl->y1 = pl->y0 + sp->h;
    for (k = 0; k < 2; k++)
        if (p->lbits[k]) {
            int lx, ly;
            label_place(p, k, &lx, &ly);
            pl->lx[k] = lx;
            pl->ly[k] = ly;
            if (lx < pl->x0) pl->x0 = lx;
            if (ly < pl->y0) pl->y0 = ly;
            if (lx + p->lw[k] > pl->x1) pl->x1 = lx + p->lw[k];
            if (ly + p->lh > pl->y1) pl->y1 = ly + p->lh;
        }
    p->lgen = V.textgen;
}

void part_rect(Part *p, Rect *r)
{
    Place *pl = &places[p - sh.parts];
    int X = PX(p->x), Y = PY(p->y);
    part_labels(p);
    r->x0 = X + pl->x0;
    r->y0 = Y + pl->y0;
    r->x1 = X + pl->x1;
    r->y1 = Y + pl->y1;
}

static void draw_part(Part *p)
{
    const Sprite *sp = sym_sprite(p->type, p->rot, V.zoom);
    Place *pl = &places[p - sh.parts];
    int X = PX(p->x), Y = PY(p->y), k;
    unsigned c = p->sel ? V.ink.sel : p->hl ? V.ink.hl : V.ink.part;
    /* at 1 bit, a selected part is drawn in reverse */
    int rev = p->sel && V.d.bpp == 1;
    Bitmap bm;
    if (!(V.layers & LY_PARTS)) {
    } else if (V.vector) {
        if (rev)
            gfx_fill(&V.d, X - sp->ox, Y - sp->oy, X - sp->ox + sp->w, Y - sp->oy + sp->h,
                     V.ink.part, ROP_COPY);
        sym_draw(&V.d, p->type, p->rot, X, Y, V.zoom, rev ? V.ink.bg : c, ROP_COPY);
    } else {
        bm.bits = sp->bits;
        bm.pitch = sp->pitch;
        sch_expand(&V.d, X - sp->ox, Y - sp->oy, &bm, 0, 0, sp->w, sp->h, rev ? V.ink.bg : c,
                   V.ink.part, rev ? XM_OPAQUE : XM_TRANS);
    }
    for (k = 0; k < 2 && (V.layers & LY_LABELS); k++)
        if (p->lbits[k]) {
            bm.bits = p->lbits[k];
            bm.pitch = (p->lw[k] + 31) / 32 + 1;
            sch_expand(&V.d, X + pl->lx[k], Y + pl->ly[k], &bm, 0, 0, p->lw[k], p->lh,
                       V.ink.text, 0, XM_TRANS);
        }
}

void view_draw_part(Part *p)
{
    part_labels(p);
    draw_part(p);
}

static void label_prep(NetLabel *l)
{
    TextBm t;
    if (l->gen == V.textgen)
        return;
    free(l->bits);
    text_make(&t, l->text, V.zoom >= 3);
    l->bits = t.bits;
    l->w = t.w;
    l->h = t.h;
    l->gen = V.textgen;
}

static void label_rect(NetLabel *l, Rect *r)
{
    label_prep(l);
    r->x0 = PX(l->x) - 1;
    r->y0 = PY(l->y) - l->h - 3;
    r->x1 = r->x0 + l->w + 4;
    r->y1 = PY(l->y);
}

static void draw_label(NetLabel *l)
{
    Bitmap bm;
    int x = PX(l->x), y = PY(l->y);
    unsigned c = l->hl ? V.ink.hl : V.ink.text;
    /* a tick up from the wire, the name beside it */
    sch_vline(&V.d, x, y - l->h - 2, y - 1, c, ROP_COPY);
    bm.bits = l->bits;
    bm.pitch = (l->w + 31) / 32 + 1;
    sch_expand(&V.d, x + 2, y - l->h - 2, &bm, 0, 0, l->w, l->h, c, 0, XM_TRANS);
}

static void draw_region(int x0, int y0, int x1, int y1)
{
    Rect r;
    int i, rad;
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 > V.w) x1 = V.w;
    if (y1 > V.h) y1 = V.h;
    if (x0 >= x1 || y0 >= y1)
        return;
    gfx_clip(&V.d, x0, y0, x1, y1);
    if (V.layers & LY_CLEAR)
        gfx_fill(&V.d, x0, y0, x1, y1, V.ink.bg, ROP_COPY);
    if (V.grid_on && (V.layers & LY_GRID))
        draw_grid(x0, y0, x1, y1);
    for (i = 0; i < sh.nwires && (V.layers & LY_WIRES); i++) {
        const Wire *w = &sh.wires[i];
        if (w->hide)
            continue;
        wire_rect(w, &r);
        if (meets(&r, x0, y0, x1, y1))
            draw_wire(w);
    }
    for (i = 0; i < sh.nparts && (V.layers & (LY_PARTS | LY_LABELS)); i++) {
        Part *p = &sh.parts[i];
        if (p->hide)
            continue;
        part_rect(p, &r);
        if (meets(&r, x0, y0, x1, y1))
            draw_part(p);
    }
    rad = V.zoom < 2 ? 1 : V.zoom;
    for (i = 0; i < sh.njunc && (V.layers & LY_DOTS); i++) {
        int x = PX(sh.jx[i]), y = PY(sh.jy[i]);
        if (x + rad >= x0 && x - rad < x1 && y + rad >= y0 && y - rad < y1)
            gfx_fill_circle(&V.d, x, y, rad, V.ink.wire, ROP_COPY);
    }
    for (i = 0; i < sh.nlabels && (V.layers & LY_LABELS); i++) {
        label_rect(&sh.labels[i], &r);
        if (meets(&r, x0, y0, x1, y1))
            draw_label(&sh.labels[i]);
    }
    gfx_noclip(&V.d);
}

/* the overlay is off while the sheet under it is drawn; on the screen it
   stays off until the window manager has copied the store over it */
static int ov_off(void)
{
    if (!ov_shown)
        return 0;
    if (ov_mode == BAND_SCREEN) {
        ov_suspend();
        return 0;
    }
    ov_hide();
    return 1;
}

void view_region(int x0, int y0, int x1, int y1)
{
    int had = ov_off();
    draw_region(x0, y0, x1, y1);
    vdamage(x0 < 0 ? 0 : x0, y0 < 0 ? 0 : y0, x1 > V.w ? V.w : x1, y1 > V.h ? V.h : y1);
    if (had)
        ov_show();
}

void view_redraw(void)
{
    unsigned t0 = ticks_now();
    int had = ov_off();
    draw_region(0, 0, V.w, V.h);
    V.last_redraw = ticks_now() - t0;
    vdamage(0, 0, V.w, V.h);
    if (had)
        ov_show();
}

void view_part(Part *p)
{
    Rect r;
    part_rect(p, &r);
    view_region(r.x0, r.y0, r.x1, r.y1);
}

void view_wire(const Wire *w)
{
    Rect r;
    wire_rect(w, &r);
    /* the dots at its ends */
    view_region(r.x0 - 4, r.y0 - 4, r.x1 + 4, r.y1 + 4);
}

/* ---- panning and zooming ---- */

void view_pan(int dx, int dy)
{
    int ax, ay;
    if (V.sheet) {
        sheet_pan(dx, dy);
        return;
    }
    if (V.pan_word) {
        /* across in whole words, the rest kept for the next: the copy is
           never shifted (in L0's chunky formats a shifted copy is the C
           kernel's four terms a word) */
        int ppw = 1 << V.d.pshift;
        V.pan_rem += dx;
        dx = V.pan_rem >= 0 ? V.pan_rem & ~(ppw - 1) : -(-V.pan_rem & ~(ppw - 1));
        V.pan_rem -= dx;
    }
    ax = dx < 0 ? -dx : dx;
    ay = dy < 0 ? -dy : dy;
    if (!dx && !dy)
        return;
    ov_clear();
    if (ax >= V.w || ay >= V.h) {
        V.ox += dx;
        V.oy += dy;
        view_redraw();
        return;
    }
    gfx_blit(&V.d, dx < 0 ? ax : 0, dy < 0 ? ay : 0, &V.d, dx > 0 ? ax : 0, dy > 0 ? ay : 0,
             V.w - ax, V.h - ay, ROP_COPY);
    V.ox += dx;
    V.oy += dy;
    if (dx > 0)
        draw_region(V.w - ax, 0, V.w, V.h);
    else if (dx < 0)
        draw_region(0, 0, ax, V.h);
    if (dy > 0)
        draw_region(0, V.h - ay, V.w, V.h);
    else if (dy < 0)
        draw_region(0, 0, V.w, ay);
    vdamage(0, 0, V.w, V.h);
}

void view_zoom(int z, int cx, int cy)
{
    if (z < 1)
        z = 1;
    if (z > 4)
        z = 4;
    if (z == V.zoom)
        return;
    ov_clear();
    /* the sheet's point under (cx, cy) stays there */
    V.ox = (cx + V.ox) * z / V.zoom - cx;
    V.oy = (cy + V.oy) * z / V.zoom - cy;
    V.zoom = z;
    V.gridstep = gridstep(z);
    V.textgen++;
    gt_phase = -1;
    sym_flush();
    view_redraw();
}

/* ---- the overlay ---- */

static int obscured(void)
{
    Window *o;
    for (o = V.win->above; o; o = o->above)
        if (o->r.x0 < V.win->r.x1 && V.win->r.x0 < o->r.x1 && o->r.y0 < V.win->r.y1 &&
            V.win->r.y0 < o->r.y1)
            return 1;
    return 0;
}

/* an item's rectangles: what to damage or redraw */
static int ov_rects(const OvItem *it, Rect *r)
{
    switch (it->kind) {
    case OV_HLINE:
        r->x0 = it->x0; r->y0 = it->y0; r->x1 = it->x1 + 1; r->y1 = it->y0 + 1;
        return 1;
    case OV_VLINE:
        r->x0 = it->x0; r->y0 = it->y0; r->x1 = it->x0 + 1; r->y1 = it->y1 + 1;
        return 1;
    case OV_FRAME:
        r[0].x0 = it->x0; r[0].y0 = it->y0; r[0].x1 = it->x1 + 1; r[0].y1 = it->y0 + 1;
        r[1].x0 = it->x0; r[1].y0 = it->y1; r[1].x1 = it->x1 + 1; r[1].y1 = it->y1 + 1;
        r[2].x0 = it->x0; r[2].y0 = it->y0; r[2].x1 = it->x0 + 1; r[2].y1 = it->y1 + 1;
        r[3].x0 = it->x1; r[3].y0 = it->y0; r[3].x1 = it->x1 + 1; r[3].y1 = it->y1 + 1;
        return 4;
    case OV_GHOST:
        r->x0 = it->x0; r->y0 = it->y0;
        r->x1 = it->x0 + V.ghost_w; r->y1 = it->y0 + V.ghost_h;
        return 1;
    default: {
        const Sprite *sp = sym_sprite(it->x1, it->y1, V.zoom);
        r->x0 = it->x0; r->y0 = it->y0;
        r->x1 = it->x0 + sp->w; r->y1 = it->y0 + sp->h;
        return 1;
    }
    }
}

/* the items drawn: in XOR (on s, offset by (ox, oy)), or in the
   selection's colour on the store (REDRAW) */
static void ov_paint(Surface *s, int ox, int oy, int rop)
{
    int i, k;
    unsigned c = rop == ROP_XOR ? V.ink.ones : V.ink.sel;
    int mode = rop == ROP_XOR ? XM_XOR : XM_TRANS;
    Bitmap bm;
    for (i = 0; i < V.nov; i++) {
        const OvItem *it = &V.ov[i];
        switch (it->kind) {
        case OV_HLINE:
            gfx_fill(s, it->x0 + ox, it->y0 + oy, it->x1 + 1 + ox, it->y0 + 1 + oy, c, rop);
            break;
        case OV_VLINE:
            sch_vline(s, it->x0 + ox, it->y0 + oy, it->y1 + oy, c, rop);
            break;
        case OV_FRAME:
            gfx_frame(s, it->x0 + ox, it->y0 + oy, it->x1 + 1 + ox, it->y1 + 1 + oy, 1, c, rop);
            break;
        case OV_SPRITE: {
            const Sprite *sp = sym_sprite(it->x1, it->y1, V.zoom);
            bm.bits = sp->bits;
            bm.pitch = sp->pitch;
            sch_expand(s, it->x0 + ox, it->y0 + oy, &bm, 0, 0, sp->w, sp->h, c, 0, mode);
            break;
        }
        default:
            if (rop == ROP_XOR && V.ghost_blit) {
                /* the ghost as one image: a copy in XOR, shifted to any pixel */
                gfx_blit(s, it->x0 + ox, it->y0 + oy, &V.ghost, 0, 0, V.ghost.w, V.ghost.h,
                         ROP_XOR);
            } else {
                /* the hidden parts and wires themselves, moved */
                int dx = it->x0 - V.ghost_x + ox, dy = it->y0 - V.ghost_y + oy;
                for (k = 0; k < sh.nparts; k++) {
                    Part *p = &sh.parts[k];
                    if (p->hide) {
                        const Sprite *sp = sym_sprite(p->type, p->rot, V.zoom);
                        bm.bits = sp->bits;
                        bm.pitch = sp->pitch;
                        sch_expand(s, PX(p->x) - sp->ox + dx, PY(p->y) - sp->oy + dy, &bm, 0,
                                   0, sp->w, sp->h, c, 0, mode);
                    }
                }
                for (k = 0; k < sh.nwires; k++) {
                    Wire *w = &sh.wires[k];
                    if (w->hide != 1)
                        continue;
                    if (w->x0 == w->x1)
                        sch_vline(s, PX(w->x0) + dx, PY(w->y0) + dy, PY(w->y1) + dy, c, rop);
                    else
                        gfx_fill(s, PX(w->x0) + dx, PY(w->y0) + dy, PX(w->x1) + 1 + dx,
                                 PY(w->y1) + 1 + dy, c, rop);
                }
            }
            break;
        }
    }
}

static void ov_damage(void)
{
    int i, k, n;
    Rect r[4];
    for (i = 0; i < V.nov; i++) {
        n = ov_rects(&V.ov[i], r);
        for (k = 0; k < n; k++)
            vdamage(r[k].x0, r[k].y0, r[k].x1, r[k].y1);
    }
}

void ov_show(void)
{
    if (ov_shown || !V.nov)
        return;
    ov_mode = V.band;
    if (ov_mode == BAND_SCREEN && obscured())
        ov_mode = BAND_STORE;
    if (ov_mode == BAND_SCREEN) {
        Surface *s = &wm.screen;
        gfx_clip(s, V.win->c.x0, V.win->c.y0, V.win->c.x0 + V.w, V.win->c.y0 + V.h);
        ov_paint(s, V.win->c.x0, V.win->c.y0, ROP_XOR);
        gfx_noclip(s);
    } else {
        gfx_clip(&V.d, 0, 0, V.w, V.h);
        ov_paint(&V.d, 0, 0, ov_mode == BAND_REDRAW ? ROP_COPY : ROP_XOR);
        ov_damage();
    }
    ov_shown = 1;
}

void ov_hide(void)
{
    int i, k, n;
    Rect r[4];
    if (!ov_shown)
        return;
    if (ov_mode == BAND_SCREEN) {
        Surface *s = &wm.screen;
        gfx_clip(s, V.win->c.x0, V.win->c.y0, V.win->c.x0 + V.w, V.win->c.y0 + V.h);
        ov_paint(s, V.win->c.x0, V.win->c.y0, ROP_XOR);
        gfx_noclip(s);
    } else if (ov_mode == BAND_STORE) {
        ov_paint(&V.d, 0, 0, ROP_XOR);
        ov_damage();
    } else {
        /* the sheet under each item, from the model */
        ov_shown = 0;
        for (i = 0; i < V.nov; i++) {
            n = ov_rects(&V.ov[i], r);
            for (k = 0; k < n; k++) {
                draw_region(r[k].x0, r[k].y0, r[k].x1, r[k].y1);
                vdamage(r[k].x0, r[k].y0, r[k].x1, r[k].y1);
            }
        }
    }
    ov_shown = 0;
}

void ov_set(const OvItem *items, int n)
{
    ov_hide();
    if (n > MAXOV)
        n = MAXOV;
    memcpy(V.ov, items, n * sizeof(OvItem));
    V.nov = n;
    ov_show();
}

void ov_clear(void)
{
    ov_hide();
    V.nov = 0;
}

/* the overlay on the screen is gone where the store was copied over it:
   it comes back a frame later (ov_tick) */
void ov_suspend(void)
{
    if (ov_shown && ov_mode == BAND_SCREEN) {
        ov_hide();
        ov_hold = wm.frames;
    }
}

void ov_tick(void)
{
    if (V.nov && !ov_shown && wm.frames > ov_hold)
        ov_show();
}

int ov_ell(OvItem *it, int x0, int y0, int x1, int y1, int down_first)
{
    int n = 0;
    /* the corner belongs to one segment: in XOR, drawn twice it would vanish */
    if (!down_first) {
        if (x0 != x1) {
            it[n].kind = OV_HLINE;
            it[n].x0 = x0 < x1 ? x0 : x1;
            it[n].x1 = x0 < x1 ? x1 : x0;
            it[n].y0 = it[n].y1 = y0;
            n++;
        }
        if (y0 != y1 || x0 == x1) {
            int a = y0 < y1 ? y0 + 1 : y1, b = y0 < y1 ? y1 : y0 - 1;
            if (x0 == x1)
                a = y0 < y1 ? y0 : y1, b = y0 < y1 ? y1 : y0;
            it[n].kind = OV_VLINE;
            it[n].x0 = it[n].x1 = x1;
            it[n].y0 = a;
            it[n].y1 = b;
            n++;
        }
    } else {
        if (y0 != y1) {
            it[n].kind = OV_VLINE;
            it[n].x0 = it[n].x1 = x0;
            it[n].y0 = y0 < y1 ? y0 : y1;
            it[n].y1 = y0 < y1 ? y1 : y0;
            n++;
        }
        if (x0 != x1 || y0 == y1) {
            int a = x0 < x1 ? x0 + 1 : x1, b = x0 < x1 ? x1 : x0 - 1;
            if (y0 == y1)
                a = x0 < x1 ? x0 : x1, b = x0 < x1 ? x1 : x0;
            it[n].kind = OV_HLINE;
            it[n].x0 = a;
            it[n].x1 = b;
            it[n].y0 = it[n].y1 = y1;
            n++;
        }
    }
    return n;
}

/* ---- the ghost ---- */

void ghost_free(void)
{
    free(V.ghost.bits);
    V.ghost.bits = 0;
    V.ghost.w = V.ghost.h = 0;
}

static void ghost_alloc(const Rect *r)
{
    int w = r->x1 - r->x0, h = r->y1 - r->y0, ppw = 1 << V.d.pshift;
    /* two spare words a row: a shifted copy reads one past the row */
    int pitch = (w + ppw - 1) / ppw + 2;
    ghost_free();
    gfx_init(&V.ghost, calloc(pitch * h, 4), w, h, pitch, V.d.fmt);
}

static void grow(Rect *r, const Rect *q, int any)
{
    if (!any || q->x0 < r->x0) r->x0 = q->x0;
    if (!any || q->y0 < r->y0) r->y0 = q->y0;
    if (!any || q->x1 > r->x1) r->x1 = q->x1;
    if (!any || q->y1 > r->y1) r->y1 = q->y1;
}

void ghost_make(Rect *r)
{
    int i, any = 0;
    Rect q;
    for (i = 0; i < sh.nparts; i++) {
        Part *p = &sh.parts[i];
        const Sprite *sp;
        if (!p->hide)
            continue;
        sp = sym_sprite(p->type, p->rot, V.zoom);
        q.x0 = PX(p->x) - sp->ox;
        q.y0 = PY(p->y) - sp->oy;
        q.x1 = q.x0 + sp->w;
        q.y1 = q.y0 + sp->h;
        grow(r, &q, any);
        any = 1;
    }
    for (i = 0; i < sh.nwires; i++) {
        Wire *w = &sh.wires[i];
        if (w->hide != 1)
            continue;
        wire_rect(w, &q);
        grow(r, &q, any);
        any = 1;
    }
    if (!any) {
        r->x0 = r->y0 = 0;
        r->x1 = r->y1 = 1;
    }
    V.ghost_x = r->x0;
    V.ghost_y = r->y0;
    V.ghost_w = r->x1 - r->x0;
    V.ghost_h = r->y1 - r->y0;
    if (!V.ghost_blit)
        return;
    ghost_alloc(r);
    for (i = 0; i < sh.nparts; i++) {
        Part *p = &sh.parts[i];
        const Sprite *sp;
        Bitmap bm;
        if (!p->hide)
            continue;
        sp = sym_sprite(p->type, p->rot, V.zoom);
        bm.bits = sp->bits;
        bm.pitch = sp->pitch;
        sch_expand(&V.ghost, PX(p->x) - sp->ox - r->x0, PY(p->y) - sp->oy - r->y0, &bm, 0, 0,
                   sp->w, sp->h, V.ink.ones, 0, XM_TRANS);
    }
    for (i = 0; i < sh.nwires; i++) {
        Wire *w = &sh.wires[i];
        if (w->hide == 1)
            gfx_fill(&V.ghost, PX(w->x0) - r->x0, PY(w->y0) - r->y0, PX(w->x1) + 1 - r->x0,
                     PY(w->y1) + 1 - r->y0, V.ink.ones, ROP_COPY);
    }
}

/* ---- the status line ---- */

void status(const char *fmt, ...)
{
    char buf[128];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    if (strcmp(buf, status_text)) {
        strcpy(status_text, buf);
        status_dirty = 1;
    }
}

void status_draw(void)
{
    int n = strlen(status_text), max = (V.status.w - 8) / 8;
    if (!status_dirty)
        return;
    if (n > max)
        n = max;
    gfx_fill(&V.status, 0, 0, V.status.w, STATUS_H, th.face, ROP_COPY);
    gfx_hline(&V.status, 0, V.status.w, 0, th.dark, ROP_COPY);
    font_cells(&V.status, 4, 0, status_text, n, th.text, -1);
    if (!V.sheet)
        wm_damage(V.win, 0, V.win->s.h - STATUS_H, V.status.w, V.win->s.h);
    status_dirty = 0;
}
