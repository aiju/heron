/* The window manager: the Egret desktop's (studies/egret_gui/src/gwm.c, on
   its branch), which is studies/graphics/src/wm.c reworked so that a
   window's content is painted by its program.

   Windows are drawn through their visible regions. Whatever of a
   window's content comes into view (it opens, is raised, something above
   it moves or closes) is filled with the window's background and added to
   its pending update, a rectangle; gwm_next_update hands it to the server,
   which sends it to the program as an EV_EXPOSE. A program can also draw
   in a window at any time: gwm_clips gives the rectangles a drawing
   operation goes through, the visible part of the content, cut down to
   the paint clip if one is set.

   For Fen: the screen is the video card's, with its stride of 1024 bytes,
   and the cursor (main.c) is taken off before anything here draws. */

#include <string.h>
#include "wsys.h"
#include "theme.h"

#define MAXRECT 64

typedef struct {
    int n;
    Rect r[MAXRECT];
} Region;

typedef struct {
    int used;
    Rect frame;
    char title[64];
    unsigned bg;
    Rect upd;                   /* the pending update, in content coordinates */
    Rect pclip;                 /* the paint clip, in content coordinates */
    int has_pclip;
} Win;

Surface screen;
static Rect screen_rect;
static Win wins[MAXWIN + 1];
static void clamp(Rect *r);
static int stack[MAXWIN];       /* bottom to top */
static int nwin;
static int gen = 1;             /* goes up whenever a window moves, opens, closes or rises */

/* ---- regions (as in wm.c) ---- */

static int isect(Rect *a, const Rect *b)  /* a = a within b; is anything left? */
{
    if (a->x0 < b->x0) a->x0 = b->x0;
    if (a->y0 < b->y0) a->y0 = b->y0;
    if (a->x1 > b->x1) a->x1 = b->x1;
    if (a->y1 > b->y1) a->y1 = b->y1;
    return a->x0 < a->x1 && a->y0 < a->y1;
}

static int empty(const Rect *r) { return r->x0 >= r->x1 || r->y0 >= r->y1; }

static void rgn_copy(Region *to, const Region *from)
{
    int i;
    for (i = 0; i < from->n; i++)
        to->r[i] = from->r[i];
    to->n = from->n;
}

static void rgn_rect(Region *g, const Rect *r)
{
    g->n = 0;
    if (!empty(r))
        g->r[g->n++] = *r;
}

static void add(Region *g, int x0, int y0, int x1, int y1)
{
    if (x0 < x1 && y0 < y1 && g->n < MAXRECT) {
        Rect *r = &g->r[g->n++];
        r->x0 = x0; r->y0 = y0; r->x1 = x1; r->y1 = y1;
    }
}

static void rgn_sub(Region *g, const Rect *c)
{
    static Region out;
    Rect a;
    int i, y0, y1;
    out.n = 0;
    for (i = 0; i < g->n; i++) {
        a = g->r[i];
        if (c->x0 >= a.x1 || c->x1 <= a.x0 || c->y0 >= a.y1 || c->y1 <= a.y0) {
            add(&out, a.x0, a.y0, a.x1, a.y1);
            continue;
        }
        y0 = c->y0 > a.y0 ? c->y0 : a.y0;
        y1 = c->y1 < a.y1 ? c->y1 : a.y1;
        add(&out, a.x0, a.y0, a.x1, y0);
        add(&out, a.x0, y0, c->x0, y1);
        add(&out, c->x1, y0, a.x1, y1);
        add(&out, a.x0, y1, a.x1, a.y1);
    }
    rgn_copy(g, &out);
}

static void unite(Rect *a, const Rect *b)
{
    if (empty(b))
        return;
    if (empty(a)) {
        *a = *b;
        return;
    }
    if (b->x0 < a->x0) a->x0 = b->x0;
    if (b->y0 < a->y0) a->y0 = b->y0;
    if (b->x1 > a->x1) a->x1 = b->x1;
    if (b->y1 > a->y1) a->y1 = b->y1;
}

/* ---- windows ---- */

static void content_of(Win *w, Rect *r)
{
    r->x0 = w->frame.x0 + 1;
    r->y0 = w->frame.y0 + 2 + TITLE_H;
    r->x1 = w->frame.x1 - 1;
    r->y1 = w->frame.y1 - 1;
}

static void title_of(Win *w, Rect *r)
{
    r->x0 = w->frame.x0 + 1;
    r->y0 = w->frame.y0 + 1;
    r->x1 = w->frame.x1 - 1;
    r->y1 = w->frame.y0 + 1 + TITLE_H;
}

static void close_of(Win *w, Rect *r)
{
    title_of(w, r);
    r->x0 += 5;
    r->y0 += 4;
    r->x1 = r->x0 + 10;
    r->y1 = r->y0 + 10;
}

int gwm_top(void) { return nwin ? stack[nwin - 1] : 0; }

int gwm_exists(int id) { return id > 0 && id <= MAXWIN && wins[id].used; }

static int level(int id)
{
    int k;
    for (k = 0; k < nwin && stack[k] != id; k++)
        ;
    return k;
}

/* the part of id's frame within r that no window above covers */
static void visible_in(int id, const Rect *r, Region *g)
{
    int k;
    Rect a = wins[id].frame;
    g->n = 0;
    if (!isect(&a, r))
        return;
    rgn_rect(g, &a);
    for (k = level(id) + 1; k < nwin && g->n; k++)
        rgn_sub(g, &wins[stack[k]].frame);
}

static void draw_frame(int id)
{
    Win *w = &wins[id];
    Rect t, c;
    Font *ui = &fonts[0];
    int active = id == gwm_top(), x;
    title_of(w, &t);
    gfx_frame(&screen, w->frame.x0, w->frame.y0, w->frame.x1, w->frame.y1, 1, c_frame, GFX_COPY);
    gfx_fill(&screen, t.x0, t.y0, t.x1, t.y1, active ? c_title : c_title_off, GFX_COPY);
    gfx_fill(&screen, t.x0, t.y1, t.x1, t.y1 + 1, c_frame, GFX_COPY);
    close_of(w, &c);
    gfx_fill(&screen, c.x0, c.y0, c.x1, c.y1, c_window, GFX_COPY);
    gfx_frame(&screen, c.x0, c.y0, c.x1, c.y1, 1, c_frame, GFX_COPY);
    x = (t.x0 + t.x1 - font_width(ui, w->title)) / 2;
    if (x < c.x1 + 6)
        x = c.x1 + 6;
    font_draw(&screen, ui, x, t.y0 + 13, w->title, active ? c_title_text : c_text, 0);
}

/* the part r of window id (which must be visible): the frame drawn, the
   content erased and added to the update */
static void paint_part(int id, const Rect *r)
{
    Win *w = &wins[id];
    Rect c, inner = *r;
    cursor_off();
    content_of(w, &c);
    if (r->x0 < c.x0 || r->y0 < c.y0 || r->x1 > c.x1 || r->y1 > c.y1) {
        gfx_clip_rect(&screen, r);
        draw_frame(id);
        gfx_noclip(&screen);
    }
    if (isect(&inner, &c)) {
        gfx_fill(&screen, inner.x0, inner.y0, inner.x1, inner.y1, w->bg, GFX_COPY);
        inner.x0 -= c.x0;
        inner.x1 -= c.x0;
        inner.y0 -= c.y0;
        inner.y1 -= c.y0;
        unite(&w->upd, &inner);
    }
}

static void paint_desktop(const Rect *r)
{
    unsigned pat[8];
    int k;
    cursor_off();
    for (k = 0; k < 8; k++)
        pat[k] = theme_pattern(screen.depth, k);
    gfx_fill_pat(&screen, r->x0, r->y0, r->x1, r->y1, pat, GFX_COPY);
}

static void repaint(const Region *damage)
{
    static Region g;
    int i, j, k;
    for (i = 0; i < damage->n; i++) {
        rgn_rect(&g, &damage->r[i]);
        for (k = 0; k < nwin && g.n; k++)
            rgn_sub(&g, &wins[stack[k]].frame);
        for (j = 0; j < g.n; j++)
            paint_desktop(&g.r[j]);
        for (k = 0; k < nwin; k++) {
            visible_in(stack[k], &damage->r[i], &g);
            for (j = 0; j < g.n; j++)
                paint_part(stack[k], &g.r[j]);
        }
    }
}

void gwm_repaint_all(void)
{
    Region g;
    rgn_rect(&g, &screen_rect);
    repaint(&g);
}

void gwm_init(int depth)
{
    gfx_init(&screen, VRAM, SCREEN_W, SCREEN_H, STRIDE, depth);
    screen_rect.x0 = screen_rect.y0 = 0;
    screen_rect.x1 = SCREEN_W;
    screen_rect.y1 = SCREEN_H;
    memset(wins, 0, sizeof wins);
    nwin = 0;
    gen++;
    gwm_repaint_all();
}

static void set_title(Win *w, const char *title)
{
    unsigned n = strlen(title);
    if (n > sizeof w->title - 1)
        n = sizeof w->title - 1;
    memcpy(w->title, title, n);
    w->title[n] = 0;
}

/* the title bar of window id again (it became active or inactive) */
static void repaint_title(int id)
{
    static Region g;
    Rect t;
    int i;
    title_of(&wins[id], &t);
    visible_in(id, &t, &g);
    for (i = 0; i < g.n; i++)
        paint_part(id, &g.r[i]);
}

int gwm_open(int x0, int y0, int x1, int y1, const char *title, unsigned bg)
{
    int id, prev = gwm_top();
    Win *w;
    for (id = 1; id <= MAXWIN && wins[id].used; id++)
        ;
    if (id > MAXWIN)
        return 0;
    w = &wins[id];
    memset(w, 0, sizeof *w);
    w->used = 1;
    w->frame.x0 = x0;
    w->frame.y0 = y0;
    w->frame.x1 = x1;
    w->frame.y1 = y1;
    clamp(&w->frame);
    w->bg = bg;
    set_title(w, title);
    stack[nwin++] = id;
    gen++;
    paint_part(id, &w->frame);
    if (prev)
        repaint_title(prev);
    return id;
}

void gwm_set_title(int id, const char *title)
{
    set_title(&wins[id], title);
    repaint_title(id);
}

void gwm_raise(int id)
{
    static Region old, g;
    Rect t;
    Win *w = &wins[id];
    int prev = gwm_top(), k, i;
    if (id == prev)
        return;
    visible_in(id, &screen_rect, &old);
    for (k = level(id); k < nwin - 1; k++)
        stack[k] = stack[k + 1];
    stack[nwin - 1] = id;
    gen++;
    /* what was hidden of it, and its title bar, now active */
    rgn_rect(&g, &w->frame);
    for (i = 0; i < old.n; i++)
        rgn_sub(&g, &old.r[i]);
    title_of(w, &t);
    rgn_sub(&g, &t);
    if (g.n < MAXRECT)
        g.r[g.n++] = t;
    for (i = 0; i < g.n; i++)
        paint_part(id, &g.r[i]);
    if (prev)
        repaint_title(prev);
}

/* A window on the screen, starting on a word (XALIGN pixels): moving one
   then copies whole words, which costs a third of shifting them. */
#define XALIGN 4

static void clamp(Rect *r)
{
    int dx = 0, dy = 0;
    if (r->x1 > SCREEN_W) dx = SCREEN_W - r->x1;
    if (r->y1 > SCREEN_H) dy = SCREEN_H - r->y1;
    if (r->x0 + dx < 0) dx = -r->x0;
    if (r->y0 + dy < 0) dy = -r->y0;
    r->x0 += dx; r->x1 += dx;
    r->y0 += dy; r->y1 += dy;
    dx = r->x0 & (XALIGN - 1);
    r->x0 -= dx; r->x1 -= dx;
}

void gwm_move(int id, int x0, int y0)
{
    static Region dmg;
    Win *w = &wins[id];
    Rect old = w->frame, nw;
    cursor_off();
    gwm_raise(id);
    nw.x0 = x0;
    nw.y0 = y0;
    nw.x1 = x0 + old.x1 - old.x0;
    nw.y1 = y0 + old.y1 - old.y0;
    clamp(&nw);
    if (nw.x0 == old.x0 && nw.y0 == old.y0)
        return;
    gfx_noclip(&screen);
    gfx_blit(&screen, nw.x0, nw.y0, &screen, old.x0, old.y0, old.x1 - old.x0, old.y1 - old.y0, GFX_COPY);
    w->frame = nw;
    gen++;
    rgn_rect(&dmg, &old);
    rgn_sub(&dmg, &nw);
    repaint(&dmg);
}

void gwm_resize(int id, int cw, int ch)
{
    static Region dmg;
    Win *w = &wins[id];
    Rect old;
    gwm_raise(id);
    old = w->frame;
    if (cw < 60) cw = 60;
    if (ch < 20) ch = 20;
    w->frame.x1 = w->frame.x0 + cw + 2;
    w->frame.y1 = w->frame.y0 + ch + TITLE_H + 3;
    if (w->frame.x1 > SCREEN_W) w->frame.x1 = SCREEN_W;
    if (w->frame.y1 > SCREEN_H) w->frame.y1 = SCREEN_H;
    gen++;
    rgn_rect(&dmg, &old);
    rgn_sub(&dmg, &w->frame);
    repaint(&dmg);
    w->upd.x0 = w->upd.x1 = 0;
    paint_part(id, &w->frame);
}

void gwm_close(int id)
{
    static Region dmg;
    int k, active = id == gwm_top();
    rgn_rect(&dmg, &wins[id].frame);
    for (k = level(id); k < nwin - 1; k++)
        stack[k] = stack[k + 1];
    nwin--;
    wins[id].used = 0;
    gen++;
    repaint(&dmg);
    if (active && nwin)
        repaint_title(gwm_top());
}

int gwm_hit(int x, int y, int *part)
{
    int k;
    for (k = nwin - 1; k >= 0; k--) {
        Win *w = &wins[stack[k]];
        Rect r;
        if (x < w->frame.x0 || x >= w->frame.x1 || y < w->frame.y0 || y >= w->frame.y1)
            continue;
        close_of(w, &r);
        if (x >= r.x0 - 2 && x < r.x1 + 2 && y >= r.y0 - 2 && y < r.y1 + 2)
            *part = PART_CLOSE;
        else if (y < w->frame.y0 + 2 + TITLE_H)
            *part = PART_TITLE;
        else if (x >= w->frame.x1 - 12 && y >= w->frame.y1 - 12)
            *part = PART_GROW;
        else
            *part = PART_CONTENT;
        return stack[k];
    }
    *part = PART_NONE;
    return 0;
}

void gwm_frame(int id, Rect *r) { *r = wins[id].frame; }

void gwm_content(int id, Rect *r)
{
    if (id == 0)
        *r = screen_rect;
    else
        content_of(&wins[id], r);
}

unsigned gwm_bg(int id) { return id ? wins[id].bg : c_desk; }

void gwm_invalidate(int id, const Rect *r)
{
    static Region g;
    Rect c, a;
    int i;
    content_of(&wins[id], &c);
    if (r) {
        a = *r;
        a.x0 += c.x0; a.x1 += c.x0;
        a.y0 += c.y0; a.y1 += c.y0;
        if (!isect(&a, &c))
            return;
    } else {
        a = c;
    }
    visible_in(id, &a, &g);
    for (i = 0; i < g.n; i++)
        paint_part(id, &g.r[i]);
}

int gwm_next_update(Rect *r)
{
    int k;
    for (k = nwin - 1; k >= 0; k--) {
        Win *w = &wins[stack[k]];
        if (!empty(&w->upd)) {
            *r = w->upd;
            w->upd.x0 = w->upd.x1 = 0;
            return stack[k];
        }
    }
    return 0;
}

void gwm_paint_clip(int id, const Rect *r)
{
    Win *w = &wins[id];
    if (r) {
        w->pclip = *r;
        w->has_pclip = 1;
    } else {
        w->has_pclip = 0;
    }
}

/* the clips of the last window asked for, while nothing has changed */
static Region clips;
static int clips_id = -1, clips_gen, clips_pc;
static Rect clips_pclip;
static Rect screen_clip;

int gwm_clips(int id, Rect **out, int *ox, int *oy)
{
    Win *w = &wins[id];
    Rect c;
    int i, n;
    if (id == 0) {
        *ox = *oy = 0;
        screen_clip = screen_rect;
        *out = &screen_clip;
        return 1;
    }
    content_of(w, &c);
    *ox = c.x0;
    *oy = c.y0;
    if (id == clips_id && gen == clips_gen && w->has_pclip == clips_pc
        && (!clips_pc || memcmp(&w->pclip, &clips_pclip, sizeof(Rect)) == 0)) {
        *out = clips.r;
        return clips.n;
    }
    if (w->has_pclip) {
        Rect p = w->pclip;
        p.x0 += c.x0; p.x1 += c.x0;
        p.y0 += c.y0; p.y1 += c.y0;
        if (!isect(&c, &p))
            c.x1 = c.x0;
    }
    if (empty(&c))
        clips.n = 0;
    else
        visible_in(id, &c, &clips);
    /* visible_in gives parts of the frame: keep them within the content */
    for (i = n = 0; i < clips.n; i++) {
        Rect a = clips.r[i];
        if (isect(&a, &c))
            clips.r[n++] = a;
    }
    clips.n = n;
    clips_id = id;
    clips_gen = gen;
    clips_pc = w->has_pclip;
    clips_pclip = w->pclip;
    *out = clips.r;
    return clips.n;
}

void gwm_scroll(int id, int x0, int y0, int x1, int y1, int dy)
{
    static Region vis, left, rest;
    static Rect cp[MAXRECT];
    Win *w = &wins[id];
    Rect c, a, t, strip;
    int i, j, n = 0;
    cursor_off();
    content_of(w, &c);
    a.x0 = c.x0 + x0; a.x1 = c.x0 + x1;
    a.y0 = c.y0 + y0; a.y1 = c.y0 + y1;
    if (!isect(&a, &c) || dy == 0)
        return;
    /* an update not painted yet would move with it: paint it all instead */
    if (!empty(&w->upd)) {
        t = a;
        t.x0 -= c.x0; t.x1 -= c.x0;
        t.y0 -= c.y0; t.y1 -= c.y0;
        gwm_invalidate(id, &t);
        return;
    }
    visible_in(id, &a, &vis);
    for (i = 0; i < vis.n; i++)
        isect(&vis.r[i], &a);
    /* copy a visible destination whose source, dy below, is visible too;
       in the order that copies no source before it's used */
    for (i = 0; i < vis.n; i++)
        for (j = 0; j < vis.n && n < MAXRECT; j++) {
            t = vis.r[j];
            t.y0 -= dy;
            t.y1 -= dy;
            if (isect(&t, &vis.r[i]))
                cp[n++] = t;
        }
    for (i = 1; i < n; i++) {
        t = cp[i];
        for (j = i; j > 0 && (dy > 0 ? cp[j - 1].y0 > t.y0 : cp[j - 1].y0 < t.y0); j--)
            cp[j] = cp[j - 1];
        cp[j] = t;
    }
    gfx_noclip(&screen);
    for (i = 0; i < n; i++)
        gfx_blit(&screen, cp[i].x0, cp[i].y0, &screen, cp[i].x0, cp[i].y0 + dy,
                 cp[i].x1 - cp[i].x0, cp[i].y1 - cp[i].y0, GFX_COPY);
    rgn_copy(&left, &vis);
    for (i = 0; i < n; i++)
        rgn_sub(&left, &cp[i]);
    /* the strip the scroll opens is the program's to draw, which it knows:
       filled, not exposed; what couldn't be copied (it was covered) is */
    strip = a;
    if (dy > 0)
        strip.y0 = a.y1 - dy > a.y0 ? a.y1 - dy : a.y0;
    else
        strip.y1 = a.y0 - dy < a.y1 ? a.y0 - dy : a.y1;
    for (i = 0; i < left.n; i++) {
        t = left.r[i];
        if (isect(&t, &strip))
            gfx_fill(&screen, t.x0, t.y0, t.x1, t.y1, w->bg, GFX_COPY);
        rgn_rect(&rest, &left.r[i]);
        rgn_sub(&rest, &strip);
        for (j = 0; j < rest.n; j++)
            paint_part(id, &rest.r[j]);
    }
}

void gwm_outline(const Rect *r)
{
    cursor_off();
    gfx_noclip(&screen);
    gfx_frame(&screen, r->x0, r->y0, r->x1, r->y1, 1, gfx_maxcolor(screen.depth), GFX_XOR);
}
