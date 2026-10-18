/* The window manager on its own: a few windows (text, the palette, a
   clock, shapes), the desktop's menu, and moves, raises and closes from
   the script; the mode and the WM's options from pokes, so one program
   measures them all. Prints each frame's work at the end. */

#include <stdio.h>
#include <string.h>
#include "wm.h"
#include "video.h"
#include "perf.h"

int wm_mode = 0, wm_options = 0;

static const char *about[] = {
    "Heron Mini's window manager.",
    "",
    "Every window has its own backing store, in the",
    "screen's pixel format; the applications draw",
    "into it whenever they like and say what changed.",
    "The compositor copies the visible parts of what",
    "changed to the screen once a frame, with the",
    "frames and title bars, so moving or raising a",
    "window needs nothing from its application.",
    0,
};

static void about_window(int x, int y)
{
    Window *w = wm_open(x, y, 300, 150, "About", WF_TITLE);
    int k;
    for (k = 0; about[k]; k++)
        font_draw(&w->s, font_sans, 10, 20 + 14 * k, about[k], th.text, -1);
}

static void palette_window(int x, int y)
{
    int n = 1 << wm.screen.bpp, cols = n > 16 ? 16 : n, rows = (n + cols - 1) / cols, k;
    int cw = n > 16 ? 12 : 24;
    Window *w = wm_open(x, y, cols * cw + 8, rows * cw + 8, "Palette", WF_TITLE);
    for (k = 0; k < n; k++)
        gfx_fill(&w->s, 4 + (k % cols) * cw, 4 + (k / cols) * cw, 4 + (k % cols) * cw + cw - 2,
                 4 + (k / cols) * cw + cw - 2, k, ROP_COPY);
}

/* a clock: the frame count as a minute and a second hand */
static const short sin60[60] = {
    0, 105, 208, 309, 407, 500, 588, 669, 743, 809, 866, 914, 951, 978, 995, 1000, 995, 978,
    951, 914, 866, 809, 743, 669, 588, 500, 407, 309, 208, 105, 0, -105, -208, -309, -407,
    -500, -588, -669, -743, -809, -866, -914, -951, -978, -995, -1000, -995, -978, -951,
    -914, -866, -809, -743, -669, -588, -500, -407, -309, -208, -105,
};

static void clock_draw(Window *w)
{
    unsigned secs = wm.frames / 60;
    int s = secs % 60, m = (secs / 60 + 10) % 60, k, cx = 60, cy = 60;
    gfx_fill(&w->s, 0, 0, 120, 120, th.bg, ROP_COPY);
    gfx_circle(&w->s, cx, cy, 55, th.text, ROP_COPY);
    for (k = 0; k < 60; k += 5)
        gfx_line(&w->s, cx + sin60[k] * 48 / 1000, cy - sin60[(k + 15) % 60] * 48 / 1000,
                 cx + sin60[k] * 54 / 1000, cy - sin60[(k + 15) % 60] * 54 / 1000, th.text,
                 ROP_COPY);
    gfx_line(&w->s, cx, cy, cx + sin60[m] * 38 / 1000, cy - sin60[(m + 15) % 60] * 38 / 1000,
             th.text, ROP_COPY);
    gfx_line(&w->s, cx, cy, cx + sin60[s] * 50 / 1000, cy - sin60[(s + 15) % 60] * 50 / 1000,
             th.accent, ROP_COPY);
    wm_damage(w, 0, 0, 120, 120);
}

static unsigned last_sec;

static void clock_tick(Window *w)
{
    if (wm.frames / 60 != last_sec) {
        last_sec = wm.frames / 60;
        clock_draw(w);
    }
}

static void clock_window(int x, int y)
{
    Window *w = wm_open(x, y, 120, 120, "Clock", WF_TITLE);
    w->tick = clock_tick;
    clock_draw(w);
}

/* shapes: a click adds a circle where it was */
static unsigned seed = 1;

static void shapes_mouse(Window *w, const Event *e, int x, int y)
{
    if (!(e->buttons & 1))
        return;
    seed = seed * 1103515245 + 12345;
    gfx_fill_circle(&w->s, x, y, 6 + (seed >> 16) % 20, (seed >> 8) % (1 << w->s.bpp), ROP_COPY);
    gfx_circle(&w->s, x, y, 26, th.text, ROP_XOR);
    wm_damage(w, x - 27, y - 27, x + 28, y + 28);
}

static void shapes_window(int x, int y)
{
    Window *w = wm_open(x, y, 220, 160, "Shapes", WF_TITLE);
    int k;
    w->mouse = shapes_mouse;
    for (k = 0; k < 12; k++)
        gfx_line(&w->s, 0, k * 14, 220, 160 - k * 14, k % (1 << w->s.bpp), ROP_COPY);
}

static void desk_pick(int item)
{
    if (item == 0)
        about_window(80 + 13 * item, 60);
    else if (item == 1)
        palette_window(200, 200);
    else if (item == 2)
        clock_window(400, 100);
    else if (item == 3)
        shapes_window(250, 250);
    else
        wm.quit = 1;
}

static void desk_click(const Event *e)
{
    wm_menu(e->x, e->y, "About|Palette|Clock|Shapes|Quit", desk_pick);
}

int main(void)
{
    wm_init(wm_mode, wm_options);
    wm_desktop_click = desk_click;
    about_window(40, 50);
    palette_window(380, 60);
    clock_window(460, 250);
    shapes_window(120, 260);
    perf_start();
    wm_frame();
    perf_end("first_frame");
    perf_frames("_");
    wm_run();
    perf_frames("frame_work");
    printf("@done\n");
    return 0;
}
