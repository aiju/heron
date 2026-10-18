/* The measurements (bench = 1): the editor's operations timed one by one
   in ticks of 19.86 ns, as "@perf" lines (measure.py collects them over
   the variants, modes and layouts). What's timed here is the editor's own
   work; the window manager's (copying the damage to the screen, the
   events) is the frames' work around it, from perf_frames.

   - sprites: every symbol's four rotations at the zoom
   - redraw: the whole drawing area from the model, then each layer alone
   - part_*: one part drawn, from its sprite and from its lines
   - text: a label as glyphs (font_draw), put together (text_draw), cached
   - lines: 100 wires across, down, diagonal, and across and down in XOR
   - compose: the whole canvas copied to the screen
   - band_*: a wire's rubber band dragged for 30 frames, in each of the
     overlay's three ways; the editor's work a frame and the frame's
   - move: three parts and their wires dragged for 30 frames
   - pan_*: steps of four grid steps, of one, and down
   - zoom_*: the sprites made again and the redraw, at each zoom
   - stress: four copies of the example (68 parts, 100 wires): junctions,
     a net, the redraw at each zoom */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sch.h"
#include "video.h"
#include "perf.h"

static unsigned t0;

static void t_start(void)
{
    t0 = ticks_now();
}

static unsigned t_end(const char *name)
{
    unsigned t = ticks_now() - t0;
    perf_value(name, t);
    return t;
}

/* what's damaged goes to the screen, and the frames' statistics restart */
static void settle(void)
{
    wm_frame();
    wm_frame();
    perf_frames("_");
}

static Part *find(const char *ref)
{
    int i;
    for (i = 0; i < sh.nparts; i++)
        if (!strcmp(sh.parts[i].ref, ref))
            return &sh.parts[i];
    return 0;
}

static void reset_sheet(void)
{
    sheet_clear();
    example(0, 0, 1);
    junctions();
    view_redraw();
    settle();
}

static void redraws(const char *tag)
{
    static const int ly[6] = {LY_CLEAR, LY_GRID, LY_WIRES, LY_PARTS, LY_LABELS, LY_DOTS};
    static const char *const names[6] = {"clear", "grid", "wires", "parts", "labels", "dots"};
    char name[40];
    int k;
    for (k = 0; k < 6; k++) {
        /* each layer on its own: the region's search of the model included */
        V.layers = ly[k];
        view_redraw();
        sprintf(name, "%s_%s", tag, names[k]);
        perf_value(name, V.last_redraw);
    }
    V.layers = LY_ALL;
    view_redraw();
    settle();
}

static void parts(void)
{
    static const char *const short_names[T_N] = {"res", "cap", "nand", "nor", "inv", "dip14",
                                                 "conn", "led", "gnd", "vcc"};
    char name[40];
    int t, k, vec;
    Part *p;
    for (t = 0; t < T_N; t++) {
        p = part_add(t, 0, 0, 0, "X1", 0);
        sym_sprite(t, 0, V.zoom);
        part_labels(p);
        for (vec = 0; vec < 2; vec++) {
            V.vector = vec;
            V.layers = LY_PARTS;
            t_start();
            for (k = 0; k < 8; k++) {
                /* at eight pixel phases: shifted expansions */
                p->x = 40 + k;
                p->y = 40;
                view_draw_part(p);
            }
            sprintf(name, "part_%s_%s", short_names[t], vec ? "vec" : "spr");
            perf_value(name, (ticks_now() - t0) / 8);
        }
        V.layers = LY_ALL;
        V.vector = 0;
        part_delete(sh.nparts - 1);
    }
    view_redraw();
    settle();
}

static void text(void)
{
    TextBm tb;
    Bitmap bm;
    int k;
    t_start();
    for (k = 0; k < 10; k++)
        font_draw(&V.d, font_sans, 20 + k, 40, "74HC132", V.ink.text, -1);
    perf_value("text_font_draw", (ticks_now() - t0) / 10);
    t_start();
    for (k = 0; k < 10; k++)
        text_draw(&V.d, 20 + k, 60, "74HC132", 1, V.ink.text);
    perf_value("text_once", (ticks_now() - t0) / 10);
    text_make(&tb, "74HC132", 1);
    bm.bits = tb.bits;
    bm.pitch = tb.pitch;
    t_start();
    for (k = 0; k < 10; k++)
        gfx_expand(&V.d, 20 + k, 80, &bm, 0, 0, tb.w, tb.h, V.ink.text, 0, 0);
    perf_value("text_cached", (ticks_now() - t0) / 10);
    text_free(&tb);
    t_start();
    for (k = 0; k < 10; k++)
        text_draw(&V.d, 20 + k, 100, "74HC132", 0, V.ink.text);
    perf_value("text_tiny", (ticks_now() - t0) / 10);
    view_redraw();
    settle();
}

static void lines(void)
{
    int k;
    unsigned c = V.ink.wire;
    t_start();
    for (k = 0; k < 100; k++)
        gfx_fill(&V.d, 20 + k, 10 + k * 5, 220 + k, 11 + k * 5, c, ROP_COPY);
    t_end("lines_across");
    t_start();
    for (k = 0; k < 100; k++)
        gfx_fill(&V.d, 10 + k * 5, 20 + k, 11 + k * 5, 220 + k, c, ROP_COPY);
    t_end("lines_down");
    t_start();
    for (k = 0; k < 100; k++)
        sch_vline(&V.d, 10 + k * 5, 20 + k, 219 + k, c, ROP_COPY);
    t_end("lines_vline");
    t_start();
    for (k = 0; k < 100; k++)
        gfx_line(&V.d, 20 + k, 10 + k * 5, 220 + k, 107 + k * 5, c, ROP_COPY);
    t_end("lines_diagonal");
    t_start();
    for (k = 0; k < 100; k++)
        gfx_fill(&V.d, 20 + k, 10 + k * 5, 220 + k, 11 + k * 5, V.ink.ones, ROP_XOR);
    t_end("lines_across_xor");
    t_start();
    for (k = 0; k < 100; k++)
        gfx_fill(&V.d, 10 + k * 5, 20 + k, 11 + k * 5, 220 + k, V.ink.ones, ROP_XOR);
    t_end("lines_down_xor");
    t_start();
    for (k = 0; k < 100; k++)
        sch_vline(&V.d, 10 + k * 5, 20 + k, 219 + k, V.ink.ones, ROP_XOR);
    t_end("lines_vline_xor");
    view_redraw();
    settle();
}

/* a wire's band dragged across the sheet for 30 frames */
static void band(int mode, const char *tag)
{
    int k, n0 = sh.nwires;
    char name[40];
    unsigned app = 0, worst = 0;
    V.band = mode;
    sch_tool(TOOL_WIRE, 0);
    int x0 = V.w / 8, y0 = V.h - V.h / 6, dx = V.w * 3 / 4 / 30, dy = -(V.h * 2 / 3 / 30);
    sch_mouse(1, x0, y0);
    settle();
    for (k = 1; k <= 30; k++) {
        unsigned t;
        t_start();
        sch_mouse(1, x0 + dx * k, y0 + dy * k);
        t = ticks_now() - t0;
        app += t;
        if (t > worst)
            worst = t;
        wm_frame();
    }
    sprintf(name, "%s_frame", tag);
    perf_frames(name);
    sprintf(name, "%s_app", tag);
    printf("@perf %s %u %u 30\n", name, app / 30, worst);
    sch_mouse(0, x0 + dx * 30, y0 + dy * 30);
    while (sh.nwires > n0)
        wire_delete(sh.nwires - 1);
    junctions();
    view_redraw();
    sch_tool(TOOL_SELECT, 0);
    V.band = BAND_STORE;
    settle();
}

/* R2, D1 and the ground under it dragged 30 frames, the wires on their pins following */
static void move(int mode, const char *tag)
{
    static const char *const refs[3] = {"R2", "D1", "#G6"};
    Part *p;
    Rect r;
    int k, x, y;
    unsigned app = 0, worst = 0;
    char name[40];
    V.band = mode;
    sch_tool(TOOL_SELECT, 0);
    for (k = 0; k < 3; k++)
        if ((p = find(refs[k])) != 0)
            p->sel = 1;
    p = find("R2");
    if (!p)
        return;
    part_rect(p, &r);
    x = PX(p->x) + ZS(8);
    y = PY(p->y);
    sch_mouse(1, x, y);
    settle();
    for (k = 1; k <= 30; k++) {
        unsigned t;
        t_start();
        sch_mouse(1, x + 5 * k, y + 4 * k);
        t = ticks_now() - t0;
        app += t;
        if (t > worst)
            worst = t;
        wm_frame();
    }
    sprintf(name, "%s_frame", tag);
    perf_frames(name);
    sprintf(name, "%s_app", tag);
    printf("@perf %s %u %u 30\n", name, app / 30, worst);
    t_start();
    sch_mouse(0, x + 5 * 30, y + 4 * 30);
    sprintf(name, "%s_drop", tag);
    t_end(name);
    V.band = BAND_STORE;
    reset_sheet();
}

static void pans(void)
{
    int k, step = ZS(4 * GRID), one = ZS(GRID);
    unsigned app;
    app = 0;
    for (k = 0; k < 8; k++) {
        t_start();
        view_pan(k < 4 ? step : -step, 0);
        app += ticks_now() - t0;
        wm_frame();
    }
    perf_value("pan_across_app", app / 8);
    perf_frames("pan_across_frame");
    app = 0;
    for (k = 0; k < 8; k++) {
        t_start();
        view_pan(k < 4 ? one : -one, 0);
        app += ticks_now() - t0;
        wm_frame();
    }
    perf_value("pan_one_app", app / 8);
    perf_frames("pan_one_frame");
    app = 0;
    for (k = 0; k < 8; k++) {
        t_start();
        view_pan(0, k < 4 ? step : -step);
        app += ticks_now() - t0;
        wm_frame();
    }
    perf_value("pan_down_app", app / 8);
    perf_frames("pan_down_frame");
    /* pans across by any number of pixels: shifted copies */
    V.pan_word = 0;
    app = 0;
    for (k = 0; k < 2; k++) {
        t_start();
        view_pan(k < 1 ? one : -one, 0);
        app += ticks_now() - t0;
        wm_frame();
    }
    perf_value("pan_shift_app", app / 2);
    perf_frames("pan_shift_frame");
    V.pan_word = 1;
    /* a drag with the right button: a few pixels a frame, both ways */
    app = 0;
    for (k = 0; k < 16; k++) {
        t_start();
        view_pan(k < 8 ? 5 : -5, k < 8 ? 3 : -3);
        app += ticks_now() - t0;
        wm_frame();
    }
    perf_value("pan_drag_app", app / 16);
    perf_frames("pan_drag_frame");
    settle();
}

static void zooms(void)
{
    static const int seq[6] = {2, 1, 2, 3, 4, 3};
    char name[40];
    int k, z0 = V.zoom;
    for (k = 0; k < 6; k++) {
        unsigned s0 = sprite_ticks;
        t_start();
        view_zoom(seq[k], V.w / 2, V.h / 2);
        sprintf(name, "zoom_%d", seq[k]);
        t_end(name);
        sprintf(name, "zoom_%d_sprites", seq[k]);
        perf_value(name, sprite_ticks - s0);
        sprintf(name, "zoom_%d_redraw", seq[k]);
        view_redraw();
        perf_value(name, V.last_redraw);
        wm_frame();
    }
    perf_frames("zoom_frame");
    view_zoom(z0, V.w / 2, V.h / 2);
    V.ox = V.oy = 0;
    view_redraw();
    settle();
}

static void stress(void)
{
    char buf[200], name[40];
    int z, z0 = V.zoom;
    sheet_clear();
    example(0, 0, 1);
    example(60, 0, 2);
    example(0, 36, 3);
    example(60, 36, 4);
    t_start();
    junctions();
    t_end("stress_junctions");
    t_start();
    net_highlight(GU(18), GU(29), buf, sizeof buf);
    t_end("stress_net");
    net_clear();
    printf("stress: %d parts, %d wires, %d dots\n", sh.nparts, sh.nwires, sh.njunc);
    V.ox = V.oy = 0;
    for (z = 1; z <= 3; z++) {
        view_zoom(z, 0, 0);
        V.ox = V.oy = 0;
        view_redraw();
        view_redraw();
        sprintf(name, "stress_redraw_z%d", z);
        perf_value(name, V.last_redraw);
        V.vector = 1;
        view_redraw();
        sprintf(name, "stress_vector_z%d", z);
        perf_value(name, V.last_redraw);
        V.vector = 0;
        wm_frame();
    }
    rt_shot("bench_stress");
    view_zoom(z0, 0, 0);
    V.ox = V.oy = 0;
    reset_sheet();
}

/* filling and copying 1200 words, ticks a word: the library's kernels (C,
   asm or the block instructions, by the variant), SAVE and RESTORE with sp
   borrowed (spfill.s), and FILL and COPY called directly */
static void blocks(void)
{
    enum { N = 1200 };
    unsigned *a = malloc(4 * (N + 2)), *b = malloc(4 * (N + 2));
    Surface sa, sb;
    int ppw = 1 << V.d.pshift, k, bad = 0;
    gfx_init(&sa, a, N * ppw, 1, N + 1, V.d.fmt);
    gfx_init(&sb, b, N * ppw, 1, N + 1, V.d.fmt);
    t_start();
    gfx_fill(&sa, 0, 0, N * ppw, 1, 1, ROP_COPY);
    perf_value("word_fill_lib", (ticks_now() - t0) * 10 / N);
    t_start();
    sch_fill_save(a, 0x12345678, N);
    perf_value("word_fill_save", (ticks_now() - t0) * 10 / N);
    for (k = 0; k < N; k++)
        bad += a[k] != 0x12345678;
    t_start();
    gfx_blit(&sb, 0, 0, &sa, 0, 0, N * ppw, 1, ROP_COPY);
    perf_value("word_copy_lib", (ticks_now() - t0) * 10 / N);
    for (k = 0; k < N; k++)
        a[k] = k * 2654435761u;
    t_start();
    sch_copy_rs(b, a, N);
    perf_value("word_copy_rs", (ticks_now() - t0) * 10 / N);
    for (k = 0; k < N; k++)
        bad += a[k] != b[k];
#ifdef GFX_BLK
    t_start();
    blk_fill(a, 0, N);
    perf_value("word_fill_blk", (ticks_now() - t0) * 10 / N);
    t_start();
    blk_copy(b, a, N);
    perf_value("word_copy_blk", (ticks_now() - t0) * 10 / N);
#endif
    printf("blocks %s (ticks a word x 10)\n", bad ? "WRONG" : "ok");
    free(a);
    free(b);
}

/* sch_expand against the library's gfx_expand (transparent, opaque) and
   against itself (XOR on a clear surface is the transparent ones; twice
   is nothing), at many phases and widths, in the screen's format */
static int xcheck(void)
{
    static unsigned src[4 * 6];
    Surface a, b;
    Bitmap bm;
    int fmt = V.d.fmt, ppw = 1 << V.d.pshift, pitch = 140 / ppw + 2, k, x, y, bad = 0;
    unsigned seed = 7;
    gfx_init(&a, malloc(pitch * 4 * 6), 140, 6, pitch, fmt);
    gfx_init(&b, malloc(pitch * 4 * 6), 140, 6, pitch, fmt);
    for (k = 0; k < 24; k++) {
        seed = seed * 1103515245u + 12345u;
        src[k] = seed ^ seed >> 13;
    }
    bm.bits = src;
    bm.pitch = 4;
    for (k = 0; k < 60 && !bad; k++) {
        int dx = (k * 7) % 40, sx = (k * 5) % 30, w = 1 + (k * 13) % 90, mode = k % 3;
        unsigned fg = 1 + k % ((1 << V.d.bpp) - 1), bg = 0;
        gfx_fill(&a, 0, 0, 140, 6, V.ink.grid, ROP_COPY);
        gfx_fill(&b, 0, 0, 140, 6, V.ink.grid, ROP_COPY);
        if (mode == XM_XOR) {
            gfx_fill(&a, 0, 0, 140, 6, 0, ROP_COPY);
            gfx_fill(&b, 0, 0, 140, 6, 0, ROP_COPY);
            gfx_expand(&a, dx, 0, &bm, sx, 0, w, 6, fg, 0, 0);
            sch_expand(&b, dx, 0, &bm, sx, 0, w, 6, fg, 0, XM_XOR);
            sch_expand(&b, dx, 0, &bm, sx, 0, w, 6, fg, 0, XM_XOR);
            sch_expand(&b, dx, 0, &bm, sx, 0, w, 6, fg, 0, XM_XOR);
        } else {
            gfx_expand(&a, dx, 0, &bm, sx, 0, w, 6, fg, bg, mode == XM_OPAQUE);
            sch_expand(&b, dx, 0, &bm, sx, 0, w, 6, fg, bg, mode);
        }
        for (y = 0; y < 6; y++)
            for (x = 0; x < 140; x++)
                if (gfx_get(&a, x, y) != gfx_get(&b, x, y) && !bad++)
                    printf("xcheck: case %d (dx %d sx %d w %d mode %d) differs at %d, %d\n", k,
                           dx, sx, w, mode, x, y);
    }
    free(a.bits);
    free(b.bits);
    printf("xcheck %s\n", bad ? "FAILED" : "ok");
    return bad;
}

/* the sheet view: drawing the whole sheet, a pan (the descriptors), a
   wire's band a frame (XOR into the bitmap that's shown, nothing to copy) */
static void sheetbench(void)
{
    int k, ppw = 1 << V.d.pshift, x0, y0;
    unsigned pan = 0, app = 0, worst = 0;
    if (!sheet_enter()) {
        printf("sheet view: no room\n");
        return;
    }
    perf_value("sheet_render", sheet_render_ticks);
    video_wait();
    sheet_flip();
    for (k = 0; k < 16; k++) {
        sheet_pan(k < 8 ? 3 * ppw : 0, k < 8 ? 0 : 48);
        pan += sheet_pan_ticks;
        video_wait();
        sheet_flip();
    }
    perf_value("sheet_pan", pan / 16);
    rt_shot("bench_sheet");
    sch_tool(TOOL_WIRE, 0);
    x0 = V.w / 4;
    y0 = V.h / 2;
    sch_mouse(1, x0, y0);
    for (k = 1; k <= 30; k++) {
        unsigned t;
        video_wait();
        t_start();
        sch_mouse(1, x0 + 11 * k, y0 - 9 * k);
        t = ticks_now() - t0;
        app += t;
        if (t > worst)
            worst = t;
    }
    printf("@perf sheet_band_app %u %u 30\n", app / 30, worst);
    ov_clear();
    sch_tool(TOOL_SELECT, 0);
    sheet_leave();
    settle();
}

/* a full-screen crosshair in software: a line across and one down the
   whole screen at the mouse, XOR'd off and on each frame straight on the
   screen (what a crosshair in the cursor's hardware would save) */
static void crosshair(void)
{
    Surface *s = &wm.screen;
    unsigned ones = (1u << s->bpp) - 1, app = 0;
    int k, x = 0, y = 0;
    gfx_noclip(s);
    settle();
    for (k = 0; k <= 30; k++) {
        int nx = 300 + 9 * k, ny = 200 + 7 * k;
        t_start();
        if (k) {
            gfx_fill(s, 0, y, vid.w, y + 1, ones, ROP_XOR);
            sch_vline(s, x, 0, y - 1, ones, ROP_XOR);
            sch_vline(s, x, y + 1, vid.h - 1, ones, ROP_XOR);
        }
        if (k < 30) {
            gfx_fill(s, 0, ny, vid.w, ny + 1, ones, ROP_XOR);
            sch_vline(s, nx, 0, ny - 1, ones, ROP_XOR);
            sch_vline(s, nx, ny + 1, vid.h - 1, ones, ROP_XOR);
        }
        x = nx;
        y = ny;
        if (k)
            app += ticks_now() - t0;
        wm_frame();
    }
    perf_value("crosshair_app", app / 30);
    settle();
}

/* placing a part: its ghost follows the mouse (moved by hand here, as the
   input would), a NAND in XOR in the store and a ground as the hardware
   cursor; the frame's work, the editor's tick in it. Then the same moves
   with the select tool: no ghost at all. */
static void placing(void)
{
    static const int types[3] = {T_NAND, T_GND, -1};
    static const char *const names[3] = {"place_xor_frame", "place_cursor_frame",
                                         "hover_frame"};
    int t, k;
    for (t = 0; t < 3; t++) {
        if (types[t] >= 0)
            sch_tool(TOOL_PLACE, types[t]);
        else
            sch_tool(TOOL_SELECT, 0);
        mouse_x = sch_canvas->c.x0 + 100;
        mouse_y = sch_canvas->c.y0 + 100;
        settle();
        for (k = 1; k <= 30; k++) {
            mouse_x = sch_canvas->c.x0 + 100 + 13 * k;
            mouse_y = sch_canvas->c.y0 + 100 + 9 * k;
            wm_frame();
        }
        perf_frames(names[t]);
    }
    sch_tool(TOOL_SELECT, 0);
    mouse_x = mouse_y = 0;
    settle();
}

void bench_run(void)
{
    char buf[200];
    int t, r;
    printf("mode %d, %d x %d x %d, format %d, canvas %d x %d, zoom %d\n", vid.mode, vid.w,
           vid.h, vid.bpp, V.d.fmt, V.w, V.h, V.zoom);
    if (bench == 2) {
        /* for --profile: redraws and nothing else */
        for (t = 0; t < 20; t++)
            view_redraw();
        perf_value("redraw", V.last_redraw);
        return;
    }
    xcheck();
    blocks();
    if (bench == 3)
        return;
    settle();
    /* the sprites, all at once */
    t_start();
    for (t = 0; t < T_N; t++)
        for (r = 0; r < 4; r++)
            sym_sprite(t, r, V.zoom);
    t_end("sprites_all");
    view_redraw();
    perf_value("redraw_first", V.last_redraw);
    view_redraw();
    perf_value("redraw", V.last_redraw);
    V.vector = 1;
    view_redraw();
    perf_value("redraw_vector", V.last_redraw);
    V.vector = 0;
    V.grid_on = 0;
    view_redraw();
    perf_value("redraw_nogrid", V.last_redraw);
    V.grid_on = 1;
    view_redraw();
    /* the whole canvas to the screen */
    settle();
    wm_damage(V.win, 0, 0, V.w, V.h);
    wm_frame();
    perf_frames("compose_full");
    settle();
    redraws("layer");
    t_start();
    junctions();
    t_end("junctions");
    t_start();
    net_highlight(GU(18), GU(29), buf, sizeof buf);
    t_end("net");
    printf("%s\n", buf);
    net_clear();
    parts();
    text();
    lines();
    band(BAND_STORE, "band_store");
    band(BAND_SCREEN, "band_screen");
    band(BAND_REDRAW, "band_redraw");
    move(BAND_STORE, "move_store");
    move(BAND_SCREEN, "move_screen");
    move(BAND_REDRAW, "move_redraw");
    crosshair();
    placing();
    pans();
    sheetbench();
    zooms();
    stress();
}
