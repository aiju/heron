/* Widgets (wm.h): drawn into a surface in the theme's colours. They keep
   no state: an application draws them as its data says, and hit-tests
   with ui_hit. */

#include <string.h>
#include "wm.h"

int ui_hit(int x, int y, int x0, int y0, int x1, int y1)
{
    return x >= x0 && x < x1 && y >= y0 && y < y1;
}

/* a 3D panel: raised (light top left) or sunken */
void ui_panel(Surface *s, int x0, int y0, int x1, int y1, int sunken)
{
    gfx_fill(s, x0 + 1, y0 + 1, x1 - 1, y1 - 1, th.face, ROP_COPY);
    if (s->bpp == 1) {
        gfx_frame(s, x0, y0, x1, y1, 1, th.frame, ROP_COPY);
        return;
    }
    if (sunken)
        gfx_bevel(s, x0, y0, x1, y1, th.dark, th.light);
    else
        gfx_bevel(s, x0, y0, x1, y1, th.light, th.dark);
}

void ui_button(Surface *s, int x0, int y0, int x1, int y1, const char *label, int pressed)
{
    int w = font_width(font_sans, label);
    gfx_frame(s, x0, y0, x1, y1, 1, th.frame, ROP_COPY);
    if (s->bpp == 1) {
        gfx_fill(s, x0 + 1, y0 + 1, x1 - 1, y1 - 1, pressed ? th.text : th.bg, ROP_COPY);
        font_draw(s, font_sans, (x0 + x1 - w) / 2, (y0 + y1) / 2 + 5, label,
                  pressed ? th.bg : th.text, -1);
        return;
    }
    ui_panel(s, x0 + 1, y0 + 1, x1 - 1, y1 - 1, pressed);
    font_draw(s, font_sans, (x0 + x1 - w) / 2 + pressed, (y0 + y1) / 2 + 5 + pressed, label,
              th.text, -1);
}

void ui_check(Surface *s, int x, int y, const char *label, int on)
{
    gfx_fill(s, x, y, x + 12, y + 12, th.bg, ROP_COPY);
    gfx_frame(s, x, y, x + 12, y + 12, 1, th.frame, ROP_COPY);
    if (on) {
        gfx_line(s, x + 2, y + 6, x + 5, y + 9, th.text, ROP_COPY);
        gfx_line(s, x + 5, y + 9, x + 10, y + 2, th.text, ROP_COPY);
        gfx_line(s, x + 2, y + 5, x + 5, y + 8, th.text, ROP_COPY);
        gfx_line(s, x + 5, y + 8, x + 10, y + 1, th.text, ROP_COPY);
    }
    font_draw(s, font_sans, x + 18, y + 11, label, th.text, -1);
}

/* a text field: the text, its caret before character `caret` (< 0: none) */
void ui_field(Surface *s, int x0, int y0, int x1, int y1, const char *text, int caret, int focus)
{
    int tx = x0 + 4, base = (y0 + y1) / 2 + 5;
    gfx_fill(s, x0 + 1, y0 + 1, x1 - 1, y1 - 1, th.bg, ROP_COPY);
    if (s->bpp == 1 || !focus)
        gfx_frame(s, x0, y0, x1, y1, 1, focus ? th.text : th.dark, ROP_COPY);
    else
        gfx_bevel(s, x0, y0, x1, y1, th.dark, th.light);
    if (focus && s->bpp > 1)
        gfx_frame(s, x0 + 1, y0 + 1, x1 - 1, y1 - 1, 1, th.sel_bg, ROP_COPY);
    gfx_clip(s, x0 + 2, y0 + 2, x1 - 2, y1 - 2);
    font_draw(s, font_sans, tx, base, text, th.text, -1);
    if (caret >= 0 && focus) {
        int cx = tx + font_widthn(font_sans, text, caret);
        gfx_vline(s, cx, base - 11, base + 3, th.text, ROP_COPY);
    }
    gfx_noclip(s);
}

void ui_label(Surface *s, int x, int y, const char *text)
{
    font_draw(s, font_sans, x, y, text, th.text, -1);
}

/* a vertical scroll bar: `shown` of `total` from `first` */
void ui_scrollbar(Surface *s, int x0, int y0, int x1, int y1, int total, int first, int shown)
{
    static const unsigned char grey[8] = {0x55, 0xAA, 0x55, 0xAA, 0x55, 0xAA, 0x55, 0xAA};
    int h = y1 - y0 - 2, t0 = y0 + 1, t1 = y1 - 1;
    if (s->bpp == 1)
        gfx_fill_pat(s, x0, y0, x1, y1, grey, th.text, th.bg);
    else
        gfx_fill(s, x0, y0, x1, y1, th.dark, ROP_COPY);
    gfx_frame(s, x0, y0, x1, y1, 1, th.frame, ROP_COPY);
    if (total > shown && total > 0) {
        t0 = y0 + 1 + h * first / total;
        t1 = y0 + 1 + h * (first + shown) / total;
        if (t1 - t0 < 8)
            t1 = t0 + 8;
        if (t1 > y1 - 1) {
            t0 -= t1 - (y1 - 1);
            t1 = y1 - 1;
        }
    }
    if (s->bpp == 1) {
        gfx_fill(s, x0 + 1, t0, x1 - 1, t1, th.bg, ROP_COPY);
        gfx_frame(s, x0, t0, x1, t1, 1, th.frame, ROP_COPY);
    } else {
        ui_panel(s, x0 + 1, t0, x1 - 1, t1, 0);
    }
}
