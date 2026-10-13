/* The graphics side of a window manager.

   There's no backing store: what's on the screen is all there is, and a
   window's content is drawn again by its paint function whenever part of
   it comes into view. Each window is drawn through its visible region,
   the part of its frame no window above covers, kept as a list of
   rectangles; drawing anything is one pass per rectangle, with the
   screen's clip rectangle set to it.

   Moving the top window copies it to its new place and paints only what
   it uncovered; raising a window paints only what was hidden of it;
   scrolling copies what's visible both before and after, and paints the
   rest. */

#include "wm.h"
#include "theme.h"

#define MAXWIN 8

static Surface *scr;
static Font *ui;
static Window wins[MAXWIN];
static Window *stack[MAXWIN];           /* bottom to top */
static int nwin;

/* ---- regions ---- */

static int isect(Rect *a, const Rect *b)  /* a = a within b; is anything left? */
{
    if (a->x0 < b->x0) a->x0 = b->x0;
    if (a->y0 < b->y0) a->y0 = b->y0;
    if (a->x1 > b->x1) a->x1 = b->x1;
    if (a->y1 > b->y1) a->y1 = b->y1;
    return a->x0 < a->x1 && a->y0 < a->y1;
}

/* only the rectangles in use: a Region is 64 of them */
static void rgn_copy(Region *to, const Region *from)
{
    int i;
    for (i = 0; i < from->n; i++)
        to->r[i] = from->r[i];
    to->n = from->n;
}

void rgn_rect(Region *g, const Rect *r)
{
    g->n = 0;
    if (r->x0 < r->x1 && r->y0 < r->y1)
        g->r[g->n++] = *r;
}

static void add(Region *g, int x0, int y0, int x1, int y1)
{
    if (x0 < x1 && y0 < y1 && g->n < MAXRECT) {
        Rect *r = &g->r[g->n++];
        r->x0 = x0; r->y0 = y0; r->x1 = x1; r->y1 = y1;
    }
}

/* Each rectangle that the cut overlaps becomes up to four: the bands
   above and below the cut, and the pieces left and right of it. */
void rgn_sub(Region *g, const Rect *c)
{
    Region out;
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

void rgn_and(Region *g, const Rect *r)
{
    int i, n = 0;
    for (i = 0; i < g->n; i++) {
        Rect a = g->r[i];
        if (isect(&a, r))
            g->r[n++] = a;
    }
    g->n = n;
}

/* ---- windows ---- */

static Rect screen_rect;

void wm_init(Surface *screen, Font *font)
{
    scr = screen;
    ui = font;
    nwin = 0;
    screen_rect.x0 = screen_rect.y0 = 0;
    screen_rect.x1 = screen->w;
    screen_rect.y1 = screen->h;
}

Window *wm_open(int x0, int y0, int x1, int y1, const char *title,
                void (*paint)(Window *, Surface *, const Rect *), void *data)
{
    Window *w = &wins[nwin];
    w->frame.x0 = x0;
    w->frame.y0 = y0;
    w->frame.x1 = x1;
    w->frame.y1 = y1;
    w->title = title;
    w->paint = paint;
    w->data = data;
    stack[nwin++] = w;
    return w;
}

Window *wm_top(void)
{
    return nwin ? stack[nwin - 1] : 0;
}

void wm_content(Window *w, Rect *r)
{
    r->x0 = w->frame.x0 + 1;
    r->y0 = w->frame.y0 + 2 + TITLE_H;
    r->x1 = w->frame.x1 - 1;
    r->y1 = w->frame.y1 - 1;
}

static void title_rect(Window *w, Rect *r)
{
    r->x0 = w->frame.x0 + 1;
    r->y0 = w->frame.y0 + 1;
    r->x1 = w->frame.x1 - 1;
    r->y1 = w->frame.y0 + 1 + TITLE_H;
}

static int level(Window *w)
{
    int k;
    for (k = 0; k < nwin && stack[k] != w; k++)
        ;
    return k;
}

/* the part of w's frame (or of r, within it) that no window above covers */
static void visible_in(Window *w, const Rect *r, Region *g)
{
    int k;
    Rect a = w->frame;
    g->n = 0;
    if (!isect(&a, r))
        return;
    rgn_rect(g, &a);
    for (k = level(w) + 1; k < nwin && g->n; k++)
        rgn_sub(g, &stack[k]->frame);
}

void wm_visible(Window *w, Region *g)
{
    visible_in(w, &screen_rect, g);
}

/* the frame, title bar and border, through the screen's clip */
static void draw_frame(Window *w)
{
    Rect t;
    int active = w == wm_top(), x;
    unsigned tc = active ? c_title_text : c_text;
    title_rect(w, &t);
    gfx_frame(scr, w->frame.x0, w->frame.y0, w->frame.x1, w->frame.y1, 1, c_frame, GFX_COPY);
    gfx_fill(scr, t.x0, t.y0, t.x1, t.y1, active ? c_title : c_title_off, GFX_COPY);
    gfx_fill(scr, t.x0, t.y1, t.x1, t.y1 + 1, c_frame, GFX_COPY);
    /* the close box */
    gfx_fill(scr, t.x0 + 5, t.y0 + 4, t.x0 + 15, t.y0 + 14, c_window, GFX_COPY);
    gfx_frame(scr, t.x0 + 5, t.y0 + 4, t.x0 + 15, t.y0 + 14, 1, c_frame, GFX_COPY);
    x = (t.x0 + t.x1 - font_width(ui, w->title)) / 2;
    font_draw(scr, ui, x, t.y0 + 13, w->title, tc, 0);
}

/* the part r of w (which must be visible) */
static void paint_part(Window *w, const Rect *r)
{
    Rect c, inner = *r;
    wm_content(w, &c);
    gfx_clip_rect(scr, r);
    if (r->x0 < c.x0 || r->y0 < c.y0 || r->x1 > c.x1 || r->y1 > c.y1)
        draw_frame(w);
    if (isect(&inner, &c)) {
        gfx_clip_rect(scr, &inner);
        w->paint(w, scr, &c);
    }
    gfx_noclip(scr);
}

/* ---- the desktop: a pattern with icons on it ---- */

static const char *const icon_names[3] = { "Disk", "Documents", "Trash" };

static void paint_desktop(const Rect *r)
{
    unsigned pat[8];
    int k, y;
    for (k = 0; k < 8; k++)
        pat[k] = theme_pattern(scr->depth, k);
    gfx_clip_rect(scr, r);
    gfx_fill_pat(scr, r->x0, r->y0, r->x1, r->y1, pat, GFX_COPY);
    for (k = 0, y = 400; k < 3; k++, y -= 56) {
        if (r->x0 >= 90 || r->y1 <= y || r->y0 >= y + 34)
            continue;
        gfx_fill(scr, 30, y, 50, y + 20, c_window, GFX_COPY);
        gfx_expand(scr, 32, y + 2, &icon, 0, 0, 16, 16, c_black, 0, 0);
        gfx_fill(scr, 40 - font_width(ui, icon_names[k]) / 2 - 2, y + 22,
                 40 + font_width(ui, icon_names[k]) / 2 + 2, y + 36, c_window, GFX_COPY);
        font_draw(scr, ui, 40 - font_width(ui, icon_names[k]) / 2, y + 33, icon_names[k], c_text, 0);
    }
    gfx_noclip(scr);
}

void wm_repaint(const Region *damage)
{
    Region g;
    int i, j, k;
    for (i = 0; i < damage->n; i++) {
        rgn_rect(&g, &damage->r[i]);
        for (k = 0; k < nwin && g.n; k++)
            rgn_sub(&g, &stack[k]->frame);
        for (j = 0; j < g.n; j++)
            paint_desktop(&g.r[j]);
        for (k = 0; k < nwin; k++) {
            visible_in(stack[k], &damage->r[i], &g);
            for (j = 0; j < g.n; j++)
                paint_part(stack[k], &g.r[j]);
        }
    }
}

void wm_paint_all(void)
{
    Region g;
    rgn_rect(&g, &screen_rect);
    wm_repaint(&g);
}

void wm_raise(Window *w)
{
    Region old, g;
    Rect t;
    Window *prev = wm_top();
    int k, i;
    if (w == prev)
        return;
    wm_visible(w, &old);
    for (k = level(w); k < nwin - 1; k++)
        stack[k] = stack[k + 1];
    stack[nwin - 1] = w;
    /* what was hidden of w, and its title bar, now active */
    rgn_rect(&g, &w->frame);
    for (i = 0; i < old.n; i++)
        rgn_sub(&g, &old.r[i]);
    title_rect(w, &t);
    rgn_sub(&g, &t);
    if (g.n < MAXRECT)
        g.r[g.n++] = t;
    for (i = 0; i < g.n; i++)
        paint_part(w, &g.r[i]);
    /* the old top window's title bar, now inactive */
    title_rect(prev, &t);
    visible_in(prev, &t, &g);
    for (i = 0; i < g.n; i++)
        paint_part(prev, &g.r[i]);
}

void wm_move(Window *w, int dx, int dy)
{
    Region dmg;
    Rect old = w->frame, nw = w->frame;
    int ww = old.x1 - old.x0, hh = old.y1 - old.y0;
    if (old.x0 + dx < 0) dx = -old.x0;
    if (old.y0 + dy < 0) dy = -old.y0;
    if (old.x1 + dx > scr->w) dx = scr->w - old.x1;
    if (old.y1 + dy > scr->h) dy = scr->h - old.y1;
    nw.x0 += dx;
    nw.x1 += dx;
    nw.y0 += dy;
    nw.y1 += dy;
    gfx_noclip(scr);
    gfx_blit(scr, nw.x0, nw.y0, scr, old.x0, old.y0, ww, hh, GFX_COPY);
    w->frame = nw;
    rgn_rect(&dmg, &old);
    rgn_sub(&dmg, &nw);
    wm_repaint(&dmg);
}

void wm_close(Window *w)
{
    Region dmg;
    int k, active = w == wm_top();
    rgn_rect(&dmg, &w->frame);
    for (k = level(w); k < nwin - 1; k++)
        stack[k] = stack[k + 1];
    nwin--;
    if (active && nwin) {                     /* the next window down becomes active */
        Rect t;
        title_rect(wm_top(), &t);
        rgn_sub(&dmg, &t);
        if (dmg.n < MAXRECT)
            dmg.r[dmg.n++] = t;
    }
    wm_repaint(&dmg);
}

void wm_scroll(Window *w, int dy)
{
    Region vis, left;
    Rect c, cp[MAXRECT], t;
    int i, j, n = 0;
    wm_content(w, &c);
    wm_visible(w, &vis);
    rgn_and(&vis, &c);
    /* what can be copied: a visible destination whose source, dy below,
       is visible too; top to bottom, so no copy overwrites a source
       another still needs */
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
        for (j = i; j > 0 && cp[j - 1].y0 > t.y0; j--)
            cp[j] = cp[j - 1];
        cp[j] = t;
    }
    gfx_noclip(scr);
    for (i = 0; i < n; i++)
        gfx_blit(scr, cp[i].x0, cp[i].y0, scr, cp[i].x0, cp[i].y0 + dy,
                 cp[i].x1 - cp[i].x0, cp[i].y1 - cp[i].y0, GFX_COPY);
    /* and the rest is painted */
    rgn_copy(&left, &vis);
    for (i = 0; i < n; i++)
        rgn_sub(&left, &cp[i]);
    for (i = 0; i < left.n; i++)
        paint_part(w, &left.r[i]);
}

void wm_outline(const Rect *r)
{
    gfx_noclip(scr);
    gfx_frame(scr, r->x0, r->y0, r->x1, r->y1, 1, gfx_maxcolor(scr->depth), GFX_XOR);
}

/* ---- the cursor ---- */

static unsigned under_bits[CURSOR_H * 4];       /* 12 pixels at up to 8 bits: 3 words a row */
static Surface under;
static int cur_x, cur_y, cur_on;

void cursor_show(int x, int y)
{
    if (cur_on)
        cursor_hide();
    gfx_init(&under, under_bits, CURSOR_W, CURSOR_H, 16, scr->depth);
    gfx_noclip(scr);
    gfx_blit(&under, 0, 0, scr, x, y, CURSOR_W, CURSOR_H, GFX_COPY);
    gfx_expand(scr, x, y, &cursor_mask, 0, 0, CURSOR_W, CURSOR_H, c_black, 0, 0);
    gfx_expand(scr, x, y, &cursor_image, 0, 0, CURSOR_W, CURSOR_H, c_white, 0, 0);
    cur_x = x;
    cur_y = y;
    cur_on = 1;
}

void cursor_hide(void)
{
    if (!cur_on)
        return;
    gfx_noclip(scr);
    gfx_blit(scr, cur_x, cur_y, &under, 0, 0, CURSOR_W, CURSOR_H, GFX_COPY);
    cur_on = 0;
}

void cursor_move(int x, int y)
{
    cursor_hide();
    cursor_show(x, y);
}
