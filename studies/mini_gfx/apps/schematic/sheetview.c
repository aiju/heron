/* The sheet view (F): the whole sheet drawn once into a bitmap in bank 1,
   and the screen's lines below a top strip pointed into it by the line
   descriptors (D0). A pan rewrites the descriptor table that isn't shown
   and flips TSEL at the next frame: nothing is copied and nothing
   composed. The top strip's lines still come from the window manager's
   framebuffer (a split a frame base, D1, can't make), with the status line
   in it. Edits draw straight into the bitmap that's shown and the overlay
   is XOR'd there; the hardware cursor is the tool's, as on the canvas.

   Across, a pan moves by whole words of the bitmap (16 pixels at 2 bits,
   32 at 1): a descriptor holds a word address, no pixel offset. Zooming
   isn't offered here (the bitmap would be drawn again at the new size).
   F goes back to the windows, the canvas drawn again from the model. */

#include <stdio.h>
#include <string.h>
#include "sch.h"
#include "video.h"
#include "perf.h"

#define TOP 22                  /* the strip from the window manager's screen */
#define SHEET_W 160             /* the sheet, grid steps */
#define SHEET_H 120

static unsigned *pool;          /* bank 1 after the rest, taken once */
static unsigned pool_bytes;
static View saved;
static int sx, sy;              /* the view: sx words across, sy lines down the bitmap */
static int shown;               /* the descriptor table shown */
static int flip;                /* the other table is ready: show it from the next frame */
static int maxx, maxy;
unsigned sheet_pan_ticks, sheet_render_ticks;

/* table t: the strip from the window manager's screen, the rest from the
   bitmap at (sx, sy) */
static void descriptors(int t)
{
    unsigned *d = video_table(t), w, step = V.d.pitch;
    int y;
    for (y = 0; y < TOP; y++)
        d[y] = video_desc(wm.screen.bits + y * wm.screen.pitch, 0);
    w = video_desc(V.d.bits + sy * V.d.pitch + sx, 0);
    for (; y < vid.h; y++) {
        d[y] = w;
        w += step;
    }
}

void sheet_pan(int dx, int dy)
{
    int ppw = 1 << V.d.pshift;
    unsigned t0 = ticks_now();
    /* across: whole words, the rest kept */
    V.pan_rem += dx;
    dx = V.pan_rem >= 0 ? V.pan_rem & ~(ppw - 1) : -(-V.pan_rem & ~(ppw - 1));
    V.pan_rem -= dx;
    sx += dx / ppw;
    sy += dy;
    if (sx < 0) sx = 0;
    if (sx > maxx) sx = maxx;
    if (sy < 0) sy = 0;
    if (sy > maxy) sy = maxy;
    descriptors(!shown);
    flip = 1;
    sheet_pan_ticks = ticks_now() - t0;
}

/* at the start of a frame: the table written for a pan, shown */
void sheet_flip(void)
{
    if (!flip)
        return;
    shown = !shown;
    video_ctrl(shown ? VC_TSEL : 0, VC_TSEL);
    flip = 0;
}

/* the view of the whole sheet: 0 if bank 1 hasn't room */
int sheet_enter(void)
{
    int ppw = 1 << wm.screen.pshift, w, h, pitch;
    unsigned bytes;
    if (!pool) {
        /* the biggest block bank 1 has left, once: vram_alloc can't free */
        for (pool_bytes = 0x180000; pool_bytes >= 0x40000; pool_bytes -= 0x10000)
            if ((pool = vram_alloc(pool_bytes)) != 0)
                break;
        if (!pool)
            return 0;
    }
    w = ZS(GU(SHEET_W));
    h = ZS(GU(SHEET_H));
    if (w < vid.w)
        w = vid.w;
    if (h < vid.h - TOP)
        h = vid.h - TOP;
    pitch = (w + ppw - 1) / ppw + 1;
    bytes = pitch * 4 * h;
    if (bytes > pool_bytes)
        return 0;
    ov_clear();
    saved = V;
    gfx_init(&V.d, pool, w, h, pitch, wm.screen.fmt);
    V.w = w;
    V.h = h;
    /* the same part of the sheet as the canvas showed */
    sx = saved.ox > 0 ? saved.ox / ppw : 0;
    sy = saved.oy > 0 ? saved.oy : 0;
    V.ox = V.oy = 0;
    V.sheet = 1;
    V.pan_rem = 0;
    V.band = BAND_STORE;        /* XOR into the bitmap: it's what's shown */
    maxx = (w - vid.w) / ppw;
    maxy = h - (vid.h - TOP);
    if (sx > maxx) sx = maxx;
    if (sy > maxy) sy = maxy;
    /* the strip: the status line on the window manager's screen */
    gfx_noclip(&wm.screen);
    gfx_fill(&wm.screen, 0, 0, vid.w, TOP, th.face, ROP_COPY);
    gfx_hline(&wm.screen, 0, vid.w, TOP - 1, th.frame, ROP_COPY);
    gfx_sub(&V.status, &wm.screen, 0, 3, vid.w, 3 + STATUS_H);
    view_redraw();
    sheet_render_ticks = V.last_redraw;
    descriptors(!shown);
    flip = 1;
    return 1;
}

void sheet_leave(void)
{
    ov_clear();
    saved.vector = V.vector;
    saved.grid_on = V.grid_on;
    saved.band = V.band;
    V = saved;
    /* the pans used both tables, the window manager's table 0 too: its
       lines go back into the one not shown, shown from the next frame;
       then, if that was table 1, into table 0 and that shown */
    video_lines(!shown, 0, vid.h, wm.screen.bits, wm.screen.pitch * 4, 0);
    video_wait();
    shown = !shown;
    video_ctrl(shown ? VC_TSEL : 0, VC_TSEL);
    if (shown) {
        video_lines(0, 0, vid.h, wm.screen.bits, wm.screen.pitch * 4, 0);
        video_wait();
        video_ctrl(0, VC_TSEL);
        shown = 0;
    }
    flip = 0;
    wm_damage_screen(0, 0, vid.w, vid.h);
    view_redraw();
}

void sheet_view(void)
{
    Event e;
    int ppw, was = 0, panning = 0, px = 0, py = 0, hx, hy;
    const unsigned *cur;
    if (!sheet_enter()) {
        status("the sheet view: no room in bank 1 at this zoom");
        return;
    }
    ppw = 1 << V.d.pshift;
    status("sheet %d x %d drawn in %d ms: arrows and the right button pan, F back", V.w, V.h,
           sheet_render_ticks / 50350);
    perf_frames("_");
    for (;;) {
        video_wait();
        sheet_flip();
        perf_frame_begin();
        while (input_next(&e)) {
            if (e.type == EV_KEY && e.key == 'f')
                goto out;
            if (e.type == EV_KEY) {
                if (e.key != '-' && e.key != '=')
                    sch_key(sch_canvas, &e);
                continue;
            }
            if (e.type != EV_MOUSE)
                continue;
            {
                int pressed = e.buttons & ~was, released = was & ~e.buttons;
                was = e.buttons;
                /* the right button drags the sheet: the bitmap's under the mouse moves with it */
                if (pressed & 2) {
                    panning = 1;
                    px = e.x;
                    py = e.y;
                    continue;
                }
                if (panning) {
                    sheet_pan(px - e.x, py - e.y);
                    px = e.x;
                    py = e.y;
                    if (released & 2)
                        panning = 0;
                    continue;
                }
                if (e.y >= TOP || !(pressed & 1))
                    sch_canvas_event(&e, e.x + sx * ppw, e.y - TOP + sy);
            }
        }
        cur = sch_cursor(&hx, &hy);
        wm_cursor(cur, hx, hy);
        video_cursor_at(mouse_x - hx, mouse_y - hy);
        status_draw();
        perf_frame_end();
    }
out:
    perf_frames("sheet_frame");
    perf_value("sheet_render", sheet_render_ticks);
    perf_value("sheet_pan", sheet_pan_ticks);
    sheet_leave();
}
