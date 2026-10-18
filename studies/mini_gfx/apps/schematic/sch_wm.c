/* The window manager (wm.h): a copy of wm/wm.c for the schematic editor,
   with one addition, wm_cursor (sch.h): the application sets the hardware
   cursor's image and its hotspot, which the study's WM can't (it always
   puts the arrow's top left on the mouse). The rest is unchanged, so the
   measurements stand for the study's WM. NOTES.md has the patch to fold
   back into wm/wm.c. */

#include <stdlib.h>
#include <string.h>
#include "wm.h"
#include "video.h"
#include "perf.h"

WM wm;
Theme th;
void (*wm_desktop_click)(const Event *e);

#define MAXDAMAGE 48
static Rect damage[MAXDAMAGE];
static int ndamage;

/* dragging: the window, the grab point, the outline drawn (outline moves) */
static Window *drag;
static int drag_dx, drag_dy, drag_x, drag_y, outline_on;
static Window *grab;            /* the window a button went down in: it gets the moves */

/* the software cursor: what's under it, where */
static Surface under;
static int cur_x = -100, cur_y = -100, cur_shown;
static unsigned cur_bits[2][32];    /* outline, fill: a word a row */
static Bitmap cur_out = {cur_bits[0], 1}, cur_fill = {cur_bits[1], 1};
/* the hardware cursor: the arrow's image, and the hotspot of the one shown */
static unsigned *arrow_img;
static int hot_x, hot_y;

static const char *arrow[] = {
    ".", "..", ".#.", ".##.", ".###.", ".####.", ".#####.", ".######.", ".#######.",
    ".########.", ".#####.....", ".##.##.", ".#. .##.", "..  .##.", ".    .##.", "     .##.",
    "      ..", 0,
};

/* ---- the theme ---- */

static void theme(int bpp)
{
    static const unsigned char grey50[8] = {0x55, 0xAA, 0x55, 0xAA, 0x55, 0xAA, 0x55, 0xAA};
    static const unsigned char dots[8] = {0x88, 0x00, 0x22, 0x00, 0x88, 0x00, 0x22, 0x00};
    memset(&th, 0, sizeof th);
    if (bpp >= 4) {
        /* the 16 colours of rt/palette.c */
        th.desk_fg = 11; th.desk_bg = 3;
        th.frame = 0;
        th.title_bg = 1; th.title_fg = 15;
        th.title_bg2 = 7; th.title_fg2 = 8;
        th.face = 7; th.light = 15; th.dark = 8; th.shadow = 0;
        th.bg = 15; th.text = 0;
        th.sel_bg = 1; th.sel_fg = 15;
        th.accent = 4; th.accent2 = 2;
        memcpy(th.desk_pat, dots, 8);
    } else if (bpp == 2) {
        /* greys: 0 black, 1 dark, 2 light, 3 white */
        th.desk_fg = 2; th.desk_bg = 1;
        th.frame = 0;
        th.title_bg = 0; th.title_fg = 3;
        th.title_bg2 = 2; th.title_fg2 = 1;
        th.face = 2; th.light = 3; th.dark = 1; th.shadow = 0;
        th.bg = 3; th.text = 0;
        th.sel_bg = 0; th.sel_fg = 3;
        th.accent = 1; th.accent2 = 1;
        memcpy(th.desk_pat, dots, 8);
    } else {
        th.desk_fg = 0; th.desk_bg = 1;
        th.frame = 0;
        th.title_bg = 0; th.title_fg = 1;
        th.title_bg2 = 1; th.title_fg2 = 0;
        th.face = 1; th.light = 1; th.dark = 0; th.shadow = 0;
        th.bg = 1; th.text = 0;
        th.sel_bg = 0; th.sel_fg = 1;
        th.accent = 0; th.accent2 = 0;
        memcpy(th.desk_pat, grey50, 8);
    }
}

/* ---- the stack ---- */

static void unlink(Window *w)
{
    if (w->above)
        w->above->below = w->below;
    else
        wm.top = w->below;
    if (w->below)
        w->below->above = w->above;
    w->above = w->below = 0;
}

static void push_top(Window *w)
{
    w->above = 0;
    w->below = wm.top;
    if (wm.top)
        wm.top->above = w;
    wm.top = w;
}

static void frame_of(Window *w)
{
    int t = w->flags & WF_TITLE ? WM_TITLE_H : 0;
    w->r.x0 = w->c.x0 - WM_BORDER;
    w->r.x1 = w->c.x1 + WM_BORDER;
    w->r.y0 = w->c.y0 - WM_BORDER - t;
    w->r.y1 = w->c.y1 + WM_BORDER;
    if (w->flags & WF_MENU) {
        w->r.x1 += 2;           /* a shadow */
        w->r.y1 += 2;
    }
}

Window *wm_open(int x, int y, int w, int h, const char *title, int flags)
{
    Window *win = calloc(1, sizeof(Window));
    const Format *f = wm.screen.f;
    int ppw = 1 << f->pshift, pitch = (w + ppw - 1) / ppw + 1;
    /* the store needn't be in bank 1: only the video reads there, and the
       CPU is as fast in either */
    void *bits = malloc(pitch * 4 * h);
    if (!bits)
        bits = vram_alloc(pitch * 4 * h);
    gfx_init(&win->s, bits, w, h, pitch, wm.screen.fmt);
    gfx_fill(&win->s, 0, 0, w, h, th.bg, ROP_COPY);
    strncpy(win->title, title ? title : "", sizeof win->title - 1);
    win->flags = flags;
    if (wm.opts & WM_SNAP)
        x &= ~(ppw - 1);
    win->c.x0 = x;
    win->c.y0 = y;
    win->c.x1 = x + w;
    win->c.y1 = y + h;
    frame_of(win);
    push_top(win);
    if (!(flags & WF_MENU)) {
        if (wm.focus)
            wm_damage_screen(wm.focus->r.x0, wm.focus->r.y0, wm.focus->r.x1,
                             wm.focus->c.y0);
        wm.focus = win;
    }
    wm_damage_screen(win->r.x0, win->r.y0, win->r.x1, win->r.y1);
    return win;
}

void wm_close(Window *w)
{
    if (w->close)
        w->close(w);
    wm_damage_screen(w->r.x0, w->r.y0, w->r.x1, w->r.y1);
    unlink(w);
    if (wm.focus == w) {
        Window *n = wm.top;
        while (n && (n->flags & WF_MENU))
            n = n->below;
        wm.focus = n;
        if (n)
            wm_damage_screen(n->r.x0, n->r.y0, n->r.x1, n->c.y0);
    }
    if (grab == w)
        grab = 0;
    if (drag == w)
        drag = 0;
    if ((unsigned)w->s.bits < BANK1)
        free(w->s.bits);
    free(w);
}

void wm_raise(Window *w)
{
    Window *old = wm.focus;
    if (wm.top != w) {
        unlink(w);
        push_top(w);
        wm_damage_screen(w->r.x0, w->r.y0, w->r.x1, w->r.y1);
    }
    if (!(w->flags & WF_MENU) && old != w) {
        wm.focus = w;
        if (old)
            wm_damage_screen(old->r.x0, old->r.y0, old->r.x1, old->c.y0);
        wm_damage_screen(w->r.x0, w->r.y0, w->r.x1, w->c.y0);
    }
}

void wm_move(Window *w, int x, int y)
{
    int dx, dy;
    if (wm.opts & WM_SNAP)
        x &= ~((1 << wm.screen.pshift) - 1);
    dx = x - w->c.x0;
    dy = y - w->c.y0;
    if (!dx && !dy)
        return;
    wm_damage_screen(w->r.x0, w->r.y0, w->r.x1, w->r.y1);
    w->c.x0 += dx; w->c.x1 += dx; w->c.y0 += dy; w->c.y1 += dy;
    frame_of(w);
    wm_damage_screen(w->r.x0, w->r.y0, w->r.x1, w->r.y1);
}

void wm_title(Window *w, const char *title)
{
    strncpy(w->title, title, sizeof w->title - 1);
    wm_damage_screen(w->r.x0, w->r.y0, w->r.x1, w->c.y0);
}

/* ---- damage ---- */

static int overlap(const Rect *a, const Rect *b)
{
    return a->x0 < b->x1 && b->x0 < a->x1 && a->y0 < b->y1 && b->y0 < a->y1;
}

void wm_damage_screen(int x0, int y0, int x1, int y1)
{
    Rect r;
    int i;
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 > wm.screen.w) x1 = wm.screen.w;
    if (y1 > wm.screen.h) y1 = wm.screen.h;
    if (x0 >= x1 || y0 >= y1)
        return;
    r.x0 = x0; r.y0 = y0; r.x1 = x1; r.y1 = y1;
    /* merge with one it overlaps or touches */
    for (i = 0; i < ndamage; i++) {
        Rect *d = &damage[i];
        if (r.x0 <= d->x1 && d->x0 <= r.x1 && r.y0 <= d->y1 && d->y0 <= r.y1) {
            int a1 = (d->x1 - d->x0) * (d->y1 - d->y0) + (x1 - x0) * (y1 - y0);
            Rect u;
            u.x0 = d->x0 < r.x0 ? d->x0 : r.x0;
            u.y0 = d->y0 < r.y0 ? d->y0 : r.y0;
            u.x1 = d->x1 > r.x1 ? d->x1 : r.x1;
            u.y1 = d->y1 > r.y1 ? d->y1 : r.y1;
            /* only if the union isn't much bigger than the two */
            if ((u.x1 - u.x0) * (u.y1 - u.y0) <= a1 + a1 / 4) {
                *d = u;
                return;
            }
        }
    }
    if (ndamage == MAXDAMAGE) {
        /* full: everything into the first */
        for (i = 1; i < ndamage; i++) {
            if (damage[i].x0 < damage[0].x0) damage[0].x0 = damage[i].x0;
            if (damage[i].y0 < damage[0].y0) damage[0].y0 = damage[i].y0;
            if (damage[i].x1 > damage[0].x1) damage[0].x1 = damage[i].x1;
            if (damage[i].y1 > damage[0].y1) damage[0].y1 = damage[i].y1;
        }
        ndamage = 1;
    }
    damage[ndamage++] = r;
}

void wm_damage(Window *w, int x0, int y0, int x1, int y1)
{
    wm_damage_screen(w->c.x0 + x0, w->c.y0 + y0, w->c.x0 + x1, w->c.y0 + y1);
}

void wm_damage_all(Window *w)
{
    wm_damage_screen(w->r.x0, w->r.y0, w->r.x1, w->r.y1);
}

/* ---- composition ---- */

static void draw_frame(Window *w, const Rect *p)
{
    Surface *s = &wm.screen;
    int active = w == wm.focus;
    gfx_clip_rect(s, p);
    if (w->flags & WF_MENU) {
        gfx_frame(s, w->r.x0, w->r.y0, w->r.x1 - 2, w->r.y1 - 2, 1, th.frame, ROP_COPY);
        gfx_fill(s, w->r.x0 + 2, w->r.y1 - 2, w->r.x1, w->r.y1, th.shadow, ROP_COPY);
        gfx_fill(s, w->r.x1 - 2, w->r.y0 + 2, w->r.x1, w->r.y1 - 2, th.shadow, ROP_COPY);
        return;
    }
    gfx_frame(s, w->r.x0, w->r.y0, w->r.x1, w->r.y1, 1, th.frame, ROP_COPY);
    if (w->flags & WF_TITLE) {
        int y0 = w->r.y0 + 1, y1 = w->c.y0 - 1;
        unsigned bg = active ? th.title_bg : th.title_bg2, fg = active ? th.title_fg : th.title_fg2;
        if (p->y0 < y1 + 1) {
            gfx_fill(s, w->r.x0 + 1, y0, w->r.x1 - 1, y1, bg, ROP_COPY);
            gfx_hline(s, w->r.x0 + 1, w->r.x1 - 1, y1, th.frame, ROP_COPY);
            /* the close box */
            gfx_fill(s, w->r.x0 + 5, y0 + 3, w->r.x0 + 16, y0 + 14, fg, ROP_COPY);
            gfx_fill(s, w->r.x0 + 6, y0 + 4, w->r.x0 + 15, y0 + 13, bg, ROP_COPY);
            font_draw(s, font_sans, w->r.x0 + 24, y0 + 13, w->title, fg, -1);
        }
    }
}

static void draw_window(Window *w, const Rect *p)
{
    Rect q;
    if (p->x0 < w->c.x0 || p->x1 > w->c.x1 || p->y0 < w->c.y0 || p->y1 > w->c.y1)
        draw_frame(w, p);
    q.x0 = p->x0 > w->c.x0 ? p->x0 : w->c.x0;
    q.y0 = p->y0 > w->c.y0 ? p->y0 : w->c.y0;
    q.x1 = p->x1 < w->c.x1 ? p->x1 : w->c.x1;
    q.y1 = p->y1 < w->c.y1 ? p->y1 : w->c.y1;
    if (q.x0 < q.x1 && q.y0 < q.y1) {
        gfx_noclip(&wm.screen);
        gfx_blit(&wm.screen, q.x0, q.y0, &w->s, q.x0 - w->c.x0, q.y0 - w->c.y0, q.x1 - q.x0,
                 q.y1 - q.y0, ROP_COPY);
    }
}

#define MAXPIECE 96

static void compose(const Rect *r)
{
    static Rect pieces[MAXPIECE], next[MAXPIECE];
    int n = 1, i, m;
    Window *w;
    pieces[0] = *r;
    for (w = wm.top; w && n; w = w->below) {
        m = 0;
        for (i = 0; i < n; i++) {
            Rect *p = &pieces[i], x;
            if (!overlap(p, &w->r)) {
                if (m < MAXPIECE)
                    next[m++] = *p;
                continue;
            }
            x.x0 = p->x0 > w->r.x0 ? p->x0 : w->r.x0;
            x.y0 = p->y0 > w->r.y0 ? p->y0 : w->r.y0;
            x.x1 = p->x1 < w->r.x1 ? p->x1 : w->r.x1;
            x.y1 = p->y1 < w->r.y1 ? p->y1 : w->r.y1;
            draw_window(w, &x);
            /* what's left of the piece: above, below, left, right */
            if (m + 4 > MAXPIECE)
                continue;
            if (p->y0 < x.y0) {
                next[m] = *p; next[m].y1 = x.y0; m++;
            }
            if (x.y1 < p->y1) {
                next[m] = *p; next[m].y0 = x.y1; m++;
            }
            if (p->x0 < x.x0) {
                next[m].x0 = p->x0; next[m].x1 = x.x0; next[m].y0 = x.y0; next[m].y1 = x.y1; m++;
            }
            if (x.x1 < p->x1) {
                next[m].x0 = x.x1; next[m].x1 = p->x1; next[m].y0 = x.y0; next[m].y1 = x.y1; m++;
            }
        }
        memcpy(pieces, next, m * sizeof(Rect));
        n = m;
    }
    /* the desktop under the rest */
    gfx_noclip(&wm.screen);
    for (i = 0; i < n; i++)
        gfx_fill_pat(&wm.screen, pieces[i].x0, pieces[i].y0, pieces[i].x1, pieces[i].y1,
                     th.desk_pat, th.desk_fg, th.desk_bg);
}

/* ---- the cursor ---- */

static void cursor_shapes(void)
{
    int y, x;
    for (y = 0; arrow[y]; y++)
        for (x = 0; arrow[y][x]; x++) {
            if (arrow[y][x] == '.')
                cur_bits[0][y] |= 1u << x;
            else if (arrow[y][x] == '#')
                cur_bits[1][y] |= 1u << x;
        }
}

static unsigned *cursor_image(void)
{
    unsigned *img = vram_alloc(32 * 8);
    int y, x;
    memset(img, 0, 32 * 8);
    for (y = 0; y < 32; y++)
        for (x = 0; x < 32; x++) {
            unsigned v = cur_bits[0][y] >> x & 1 ? 1 : cur_bits[1][y] >> x & 1 ? 2 : 0;
            img[2 * y + x / 16] |= v << (2 * (x % 16));
        }
    return img;
}

static void soft_hide(void)
{
    if (!cur_shown)
        return;
    gfx_noclip(&wm.screen);
    gfx_blit(&wm.screen, cur_x, cur_y, &under, 0, 0, 16, 20, ROP_COPY);
    cur_shown = 0;
}

static void soft_show(void)
{
    cur_x = mouse_x;
    cur_y = mouse_y;
    gfx_noclip(&wm.screen);
    gfx_blit(&under, 0, 0, &wm.screen, cur_x, cur_y, 16, 20, ROP_COPY);
    gfx_expand(&wm.screen, cur_x, cur_y, &cur_out, 0, 0, 16, 20, 0, 0, 0);
    gfx_expand(&wm.screen, cur_x, cur_y, &cur_fill, 0, 0, 16, 20, (1u << wm.screen.bpp) - 1, 0,
               0);
    cur_shown = 1;
}

/* ---- set-up ---- */

void wm_init(int mode, int opts)
{
    unsigned *fb;
    const Format *f;
    wm.opts = opts;
    font_init();
    input_init();
    vram_reset();
    video_init(mode, (opts & WM_SOFTCURSOR ? 0 : VC_CURSOR) | (opts & WM_F1 ? VC_F1 : 0));
    video_default_palette();
    fb = vram_alloc(vid.words * 4 * vid.h);
    gfx_screen(&wm.screen, fb, vid.words);
    video_lines(0, 0, vid.h, fb, vid.words * 4, 0);
    theme(vid.bpp);
    if (vid.bpp == 1) {
        /* the cursor's colours in 1 bit: black, white */
        video_pal(253, rgb565(0, 0, 0));
        video_pal(254, rgb565(255, 255, 255));
    }
    cursor_shapes();
    if (opts & WM_SOFTCURSOR) {
        f = wm.screen.f;
        gfx_init(&under, vram_alloc(4 * (64 >> f->pshift) * 20), 64, 20, 64 >> f->pshift,
                 wm.screen.fmt);
    } else {
        arrow_img = cursor_image();
        video_cursor(arrow_img);
    }
    wm_damage_screen(0, 0, vid.w, vid.h);
}

/* the hardware cursor's image (32 x 32, 2 bits a pixel, in bank 1) and
   its hotspot, the pixel that is on the mouse; 0 for the arrow */
void wm_cursor(const unsigned *img, int hx, int hy)
{
    if (wm.opts & WM_SOFTCURSOR)
        return;
    VID_CURIMG = video_word(img ? img : arrow_img);
    hot_x = hx;
    hot_y = hy;
}

/* ---- events ---- */

static Window *window_at(int x, int y)
{
    Window *w;
    for (w = wm.top; w; w = w->below)
        if (x >= w->r.x0 && x < w->r.x1 && y >= w->r.y0 && y < w->r.y1)
            return w;
    return 0;
}

static void soft_hide(void);

static void outline(void)
{
    /* XOR'd straight onto the screen: drawn twice, it's gone */
    Window *w = drag;
    soft_hide();
    int x0 = drag_x - (w->c.x0 - w->r.x0), y0 = drag_y - (w->c.y0 - w->r.y0);
    int x1 = x0 + (w->r.x1 - w->r.x0), y1 = y0 + (w->r.y1 - w->r.y0);
    gfx_noclip(&wm.screen);
    gfx_frame(&wm.screen, x0, y0, x1, y1, 2, (1u << wm.screen.bpp) - 1, ROP_XOR);
    outline_on ^= 1;
}

static void close_menus(Window *except)
{
    Window *w = wm.top, *n;
    while (w) {
        n = w->below;
        if ((w->flags & WF_MENU) && w != except)
            wm_close(w);
        w = n;
    }
}

static int buttons_was;

static void mouse_event(const Event *e)
{
    int pressed = e->buttons & ~buttons_was, released = buttons_was & ~e->buttons;
    Window *w;
    buttons_was = e->buttons;
    if (drag) {
        if (wm.opts & WM_OUTLINE) {
            if (outline_on)
                outline();
            drag_x = e->x - drag_dx;
            drag_y = e->y - drag_dy;
            if (released & 1)
                wm_move(drag, drag_x, drag_y);
            else
                outline();
        } else {
            wm_move(drag, e->x - drag_dx, e->y - drag_dy);
        }
        if (released & 1)
            drag = 0;
        return;
    }
    if (grab && !pressed) {
        /* moves and the release go to the window the button went down in */
        if (grab->mouse)
            grab->mouse(grab, e, e->x - grab->c.x0, e->y - grab->c.y0);
        if (!e->buttons)
            grab = 0;
        return;
    }
    w = window_at(e->x, e->y);
    if (!pressed) {
        /* a move with no button: menus follow it */
        if (w && (w->flags & WF_MENU) && w->mouse)
            w->mouse(w, e, e->x - w->c.x0, e->y - w->c.y0);
        return;
    }
    close_menus(w);
    w = window_at(e->x, e->y);
    if (!w) {
        if (wm_desktop_click)
            wm_desktop_click(e);
        return;
    }
    if (!(w->flags & WF_MENU))
        wm_raise(w);
    if ((w->flags & WF_TITLE) && e->y < w->c.y0) {
        if (e->x < w->r.x0 + 18) {
            wm_close(w);
            return;
        }
        if (!(w->flags & WF_FIXED) && (pressed & 1)) {
            drag = w;
            drag_dx = e->x - w->c.x0;
            drag_dy = e->y - w->c.y0;
            drag_x = w->c.x0;
            drag_y = w->c.y0;
            outline_on = 0;
            if (wm.opts & WM_OUTLINE)
                outline();
        }
        return;
    }
    grab = w;
    if (w->mouse)
        w->mouse(w, e, e->x - w->c.x0, e->y - w->c.y0);
}

void wm_frame(void)
{
    Event e;
    Window *w, *n;
    int i;
    video_wait();
    perf_frame_begin();
    while (input_next(&e)) {
        if (e.type == EV_MOUSE)
            mouse_event(&e);
        else if (wm.focus && wm.focus->key)
            wm.focus->key(wm.focus, &e);
    }
    for (w = wm.top; w; w = n) {
        n = w->below;
        if (w->tick)
            w->tick(w);
    }
    if (wm.opts & WM_SOFTCURSOR) {
        if (ndamage || mouse_x != cur_x || mouse_y != cur_y)
            soft_hide();
    } else {
        video_cursor_at(mouse_x - hot_x, mouse_y - hot_y);
    }
    if (outline_on && ndamage) {
        /* the outline is on the screen, not in a store: off while composing */
        outline();
        for (i = 0; i < ndamage; i++)
            compose(&damage[i]);
        outline();
    } else {
        for (i = 0; i < ndamage; i++)
            compose(&damage[i]);
    }
    ndamage = 0;
    if ((wm.opts & WM_SOFTCURSOR) && !cur_shown)
        soft_show();
    perf_frame_end();
    wm.frames++;
}

void wm_run(void)
{
    while (!wm.quit)
        wm_frame();
}

/* ---- menus ---- */

typedef struct {
    const char *items;
    int n, hot;
    void (*pick)(int);
} Menu;

static int menu_item(const Menu *m, int k, char *out)
{
    const char *p = m->items;
    int i = 0, n = 0;
    while (*p && k > 0) {
        if (*p++ == '|')
            k--;
    }
    while (p[i] && p[i] != '|' && n < 40)
        out[n++] = p[i++];
    out[n] = 0;
    return n;
}

static void menu_draw(Window *w)
{
    Menu *m = w->app;
    char buf[48];
    int k;
    gfx_fill(&w->s, 0, 0, w->s.w, w->s.h, th.bg, ROP_COPY);
    for (k = 0; k < m->n; k++) {
        int hot = k == m->hot;
        if (hot)
            gfx_fill(&w->s, 0, 16 * k, w->s.w, 16 * k + 16, th.sel_bg, ROP_COPY);
        menu_item(m, k, buf);
        font_draw(&w->s, font_sans, 8, 16 * k + 12, buf, hot ? th.sel_fg : th.text, -1);
    }
    wm_damage(w, 0, 0, w->s.w, w->s.h);
}

static void menu_mouse(Window *w, const Event *e, int x, int y)
{
    Menu *m = w->app;
    int k = x >= 0 && x < w->s.w && y >= 0 && y < w->s.h ? y / 16 : -1;
    if (k != m->hot) {
        m->hot = k;
        menu_draw(w);
    }
    if (e->buttons & 1 && k >= 0) {
        void (*pick)(int) = m->pick;
        wm_close(w);
        if (pick)
            pick(k);
    }
}

static void menu_close(Window *w)
{
    free(w->app);
}

void wm_menu(int x, int y, const char *items, void (*pick)(int))
{
    Menu *m = calloc(1, sizeof(Menu));
    Window *w;
    char buf[48];
    int k, width = 60;
    const char *p;
    m->items = items;
    m->pick = pick;
    m->hot = -1;
    m->n = 1;
    for (p = items; *p; p++)
        if (*p == '|')
            m->n++;
    for (k = 0; k < m->n; k++) {
        menu_item(m, k, buf);
        if (font_width(font_sans, buf) + 16 > width)
            width = font_width(font_sans, buf) + 16;
    }
    if (x + width > wm.screen.w - 4)
        x = wm.screen.w - 4 - width;
    if (y + 16 * m->n > wm.screen.h - 4)
        y = wm.screen.h - 4 - 16 * m->n;
    w = wm_open(x, y, width, 16 * m->n, "", WF_MENU);
    w->app = m;
    w->mouse = menu_mouse;
    w->close = menu_close;
    menu_draw(w);
}
