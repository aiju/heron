/* A test card in each mode in turn: the mode's colours, lines, circles,
   text in the three fonts, the hardware cursor on the mouse. A key or a
   click moves to the next mode. The library draws the same calls in
   every mode and layout; the card's drawing time is measured. */

#include <stdio.h>
#include <string.h>
#include "gfx.h"
#include "video.h"
#include "input.h"
#include "perf.h"

/* the cursor: an arrow, '.' outline (253), '#' fill (254) */
static const char *arrow[] = {
    ".", "..", ".#.", ".##.", ".###.", ".####.", ".#####.", ".######.", ".#######.",
    ".########.", ".#####.....", ".##.##.", ".#. .##.", "..  .##.", ".    .##.", "     .##.",
    "      ..", 0,
};

static unsigned *cursor_image(void)
{
    unsigned *img = vram_alloc(32 * 8);
    int y, x;
    memset(img, 0, 32 * 8);
    for (y = 0; arrow[y]; y++)
        for (x = 0; arrow[y][x]; x++) {
            unsigned v = arrow[y][x] == '.' ? 1 : arrow[y][x] == '#' ? 2 : 0;
            img[2 * y + x / 16] |= v << (2 * (x % 16));
        }
    return img;
}

static const char *mode_names[7] = {
    "M0 640 x 480 x 4", "M1 320 x 240 x 8", "M2 640 x 480 x 8", "M3 640 x 480 x 2",
    "M4 640 x 480 x 1", "M5 1024 x 768 x 2", "M6 1024 x 768 x 1",
};
static const char *fmt_names[PF_N] = {
    "linear", "linear", "linear", "linear", "L0 chunky", "L0 chunky", "L1 planes", "L1 planes",
    "L1 planes",
};

static void card(Surface *s, int mode)
{
    int w = s->w, h = s->h, colours = 1 << s->bpp, n, x, y, cols, cw;
    unsigned fg = colours - 1, bg = colours > 2 ? (colours == 4 ? 1 : 8) : 0;
    char buf[80];
    if (colours == 16)
        bg = 1;
    if (colours == 256)
        bg = 17;
    gfx_fill(s, 0, 0, w, h, bg, ROP_COPY);
    /* the colours */
    cols = colours > 16 ? 32 : colours;
    cw = (w - 40) / cols;
    for (n = 0; n < colours; n++) {
        x = 20 + (n % cols) * cw;
        y = 60 + (n / cols) * (colours > 16 ? 10 : 40);
        gfx_fill(s, x, y, x + cw - 1, y + (colours > 16 ? 9 : 39), n, ROP_COPY);
    }
    /* a grid and its diagonals, a circle */
    y = colours > 16 ? 150 : 115;
    for (x = 20; x <= w - 20; x += (w - 40) / 8)
        gfx_vline(s, x, y, h - 60, fg, ROP_COPY);
    for (n = y; n <= h - 60; n += (h - 60 - y) / 4)
        gfx_hline(s, 20, w - 19, n, fg, ROP_COPY);
    gfx_line(s, 20, y, w - 20, h - 60, fg, ROP_COPY);
    gfx_line(s, 20, h - 60, w - 20, y, fg, ROP_COPY);
    gfx_fill_circle(s, w / 2, (y + h - 60) / 2, (h - 60 - y) / 3, colours > 2 ? 2 % colours : 0,
                    ROP_COPY);
    gfx_circle(s, w / 2, (y + h - 60) / 2, (h - 60 - y) / 3, fg, ROP_COPY);
    /* text */
    sprintf(buf, "Heron Mini  %s  (%s)", mode_names[mode], fmt_names[s->fmt]);
    font_draw(s, font_sans, 20, 30, buf, fg, -1);
    font_draw(s, font_mono, 20, h - 36, "mono12: The quick brown fox jumps over 13 lazy dogs.",
              fg, -1);
    font_cells(s, 16, h - 28, "cell8: 0123456789 ABCDEFGHIJKLM nopqrstuvwxyz !?#&", 48, fg,
               bg);
}

int mode_order[7] = {0, 1, 2, 3, 4, 5, 6};

int main(void)
{
    Surface s;
    unsigned *fb, *cur;
    Event e;
    int k, mode, f1 = 0;
    char name[32];
    font_init();
    input_init();
    for (k = 0; k < 7; k++) {
        mode = mode_order[k];
        vram_reset();
        video_init(mode, VC_CURSOR | (mode >= 3 && f1 ? VC_F1 : 0));
        video_default_palette();
        cur = cursor_image();
        video_cursor(cur);
        fb = vram_alloc(vid.words * 4 * vid.h);
        if (mode == 1) {
            /* 320 x 240: every line shown twice */
            gfx_init(&s, fb, 320, 240, vid.words, gfx_screen_format());
            for (int y = 0; y < 240; y++) {
                video_lines(0, 2 * y, 1, fb + y * vid.words, 0, 0);
                video_lines(0, 2 * y + 1, 1, fb + y * vid.words, 0, 0);
            }
        } else {
            gfx_screen(&s, fb, vid.words);
            video_lines(0, 0, vid.h, fb, vid.words * 4, 0);
        }
        perf_start();
        card(&s, mode);
        sprintf(name, "card_m%d", mode);
        perf_end(name);
        video_cursor_at(mouse_x, mouse_y);
        sprintf(name, "m%d", mode);
        rt_shot(name);
        /* until a key or a click */
        for (;;) {
            video_wait();
            video_cursor_at(mouse_x, mouse_y);
            if (input_next(&e) && (e.type == EV_KEY || (e.type == EV_MOUSE && e.buttons)))
                break;
        }
    }
    printf("@done\n");
    return 0;
}
