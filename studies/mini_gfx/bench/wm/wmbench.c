/* The window manager's costs, timed with the beam: a full composite of
   the desktop with four windows, a 320 x 200 window moved a pixel at a
   time (each move's composite: the window copied, what it uncovered
   redrawn), raising a covered window, and a character-sized damage (a
   typed letter). The mode and the WM's options come from pokes. */

#include <stdio.h>
#include "wm.h"
#include "video.h"
#include "perf.h"

int wm_mode = 0, wm_options = 0;

static Window *text_window(int x, int y, int w, int h, const char *title)
{
    Window *win = wm_open(x, y, w, h, title, WF_TITLE);
    int k;
    for (k = 0; k * 14 + 20 < h; k++)
        font_draw(&win->s, font_sans, 8, 16 + 14 * k,
                  "Lorem ipsum dolor sit amet, consectetur adipiscing elit sed do.", th.text, -1);
    return win;
}

static void composite(void)
{
    wm_compose();
}

int main(void)
{
    Window *a, *b, *c, *d;
    unsigned t, sum = 0, worst = 0;
    int k;
    wm_init(wm_mode, wm_options);
    a = text_window(40, 40, 320, 200, "One");
    b = text_window(200, 120, 320, 200, "Two");
    c = text_window(80, 260, 300, 150, "Three");
    d = text_window(400, 280, 200, 150, "Four");
    wm_frame();
    /* a full composite: everything damaged */
    wm_damage_screen(0, 0, vid.w, vid.h);
    video_wait();
    perf_start();
    composite();
    perf_end("full");
    /* moving b by a pixel right and down, 16 times */
    for (k = 0; k < 16; k++) {
        wm_move(b, b->c.x0 + 1, b->c.y0 + 1);
        t = video_ticks();
        composite();
        t = video_ticks() - t;
        sum += t;
        if (t > worst)
            worst = t;
    }
    perf_value("move", sum / 16);
    perf_value("move_worst", worst);
    /* moving it by 8 pixels: on whole words at 4 bits */
    sum = 0;
    for (k = 0; k < 8; k++) {
        wm_move(b, b->c.x0 + 8, b->c.y0);
        t = video_ticks();
        composite();
        sum += video_ticks() - t;
    }
    perf_value("move8", sum / 8);
    /* raising a, which b covers */
    wm_raise(a);
    t = video_ticks();
    composite();
    perf_value("raise", video_ticks() - t);
    /* a typed character: 7 x 15 pixels of a's content */
    sum = 0;
    for (k = 0; k < 16; k++) {
        font_draw(&a->s, font_mono, 10 + 7 * k, 180, "x", th.text, th.bg);
        wm_damage(a, 10 + 7 * k, 168, 17 + 7 * k, 183);
        t = video_ticks();
        composite();
        sum += video_ticks() - t;
    }
    perf_value("char", sum / 16);
    rt_shot("wm");
    (void)c;
    (void)d;
    printf("@done\n");
    return 0;
}
