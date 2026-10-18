/* The HUD below the map: the minimap, the selection, three buttons and a
   status line. Its lines' descriptors give it palette bank 1 in M0, so
   its 16 colours are its own; in M1 it uses entries 16-31, and its rows
   aren't doubled (320 x 96, each pixel two wide). It's one buffer, drawn
   only when something in it changes; the minimap every few frames. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rts.h"

unsigned *hud;
static Surface hs;
static int hud_words;
static unsigned *mm_base;       /* the minimap's terrain, in the HUD's format */
static int hrow[128];           /* each HUD row's first word */
static int mm_x, mm_y, mm_sy, mm_words, mm_rows;
static int info_x0, info_x1, btn_x0, btn_x1;
static const char *btn_names[3] = {"Stop", "Scatter", "Redraw"};
/* the units' icons, drawn once on the panel's colour (pixel by pixel they
   cost 5 ms each: selecting ten units took a 66 ms frame) */
static Surface icons[4];

static void icon(int x, int y, int type, int team)
{
    const Surface *ic = &icons[type * 2 + team];
    gfx_blit(&hs, x, y, ic, 0, 0, ic->w, ic->h, ROP_COPY);
}

/* the HUD's colours (art.c's H_*) */
enum {
    H_BLACK, H_DARK, H_MID, H_LIGHT, H_TEXT, H_YELLOW, H_GRASS, H_WATER, H_TREE, H_ROCK, H_SAND,
    H_BLUE, H_RED, H_BROWN, H_GREEN, H_WHITE
};
#define HC(c) (hud_base + (c))

static int tile_colour(int t)
{
    if (t >= T_BASE)
        return t >= T_BASE + 9 ? H_RED : H_BLUE;
    if (t >= T_WATER)
        return H_WATER;
    if (t == T_TREE || t == T_TREE2)
        return H_TREE;
    if (t == T_ROCK || t == T_ROCK2)
        return H_ROCK;
    if (t == T_SAND || t == T_SAND2)
        return H_SAND;
    return H_GRASS;
}

/* the buttons: Stop and Scatter side by side, Redraw below, the status under them */
static void btn_rect(int k, int *x0, int *y0, int *x1, int *y1)
{
    int h = mode ? 24 : 20, mid = (btn_x0 + btn_x1) / 2;
    *y0 = 6 + (k == 2) * (h + 4);
    *y1 = *y0 + h;
    *x0 = k == 1 ? mid + 2 : btn_x0;
    *x1 = k == 0 ? mid - 2 : btn_x1;
}

static void button(int k, int down)
{
    int x0, y0, x1, y1;
    char buf[24];
    btn_rect(k, &x0, &y0, &x1, &y1);
    gfx_fill(&hs, x0, y0, x1, y1, HC(down ? H_DARK : H_MID), ROP_COPY);
    gfx_bevel(&hs, x0, y0, x1, y1, HC(down ? H_BLACK : H_LIGHT), HC(down ? H_LIGHT : H_BLACK));
    if (k == 2 && strategy >= 0)
        sprintf(buf, "Redraw: %s", strategy_names[strategy]);
    else
        strcpy(buf, btn_names[k]);  /* (Redraw before a strategy is set) */
    font_draw(&hs, font_sans, x0 + (mode ? 4 : 8), y1 - (mode ? 8 : 6), buf, HC(H_TEXT), -1);
}

void hud_init(void)
{
    int x, y;
    hud_words = view_words;
    hud = vram_alloc(hud_words * 4 * hud_h);
    for (x = 0; x < 4; x++) {
        int w = mode ? 16 : 24;     /* 12 pixels at 2 x 2, or 1 x 2 in M1 (wide pixels), on whole words */
        gfx_init(&icons[x], malloc(w / ppw * 4 * 24), w, 24, w / ppw, fmt);
        gfx_fill(&icons[x], 0, 0, w, 24, HC(H_DARK), ROP_COPY);
        icon_draw(&icons[x], 0, 0, x >> 1, x & 1);
    }
    for (y = 0; y < hud_h; y++)
        hrow[y] = y * hud_words;
    gfx_init(&hs, hud, view_w, hud_h, hud_words, fmt);
    /* the panel */
    gfx_fill(&hs, 0, 0, view_w, hud_h, HC(H_MID), ROP_COPY);
    gfx_fill(&hs, 0, 0, view_w, 1, HC(H_LIGHT), ROP_COPY);
    gfx_fill(&hs, 0, 1, view_w, 2, HC(H_BLACK), ROP_COPY);
    /* the minimap: a pixel a tile (two rows a tile in M1, whose pixels are wide) */
    mm_sy = mode ? 2 : 1;
    mm_x = ppw;
    mm_y = mode ? 8 : 8;
    mm_words = map_w / ppw;
    mm_rows = map_h * mm_sy;
    mm_base = malloc(mm_words * 4 * mm_rows);
    {
        Surface ms;
        gfx_init(&ms, mm_base, map_w, mm_rows, mm_words, fmt);
        for (y = 0; y < map_h; y++)
            for (x = 0; x < map_w; x++)
                gfx_fill(&ms, x, y * mm_sy, x + 1, (y + 1) * mm_sy,
                         HC(tile_colour(map[y * map_w + x])), ROP_COPY);
    }
    gfx_frame(&hs, mm_x - 2, mm_y - 2, mm_x + map_w + 2, mm_y + mm_rows + 2, 1, HC(H_LIGHT),
              ROP_COPY);
    gfx_frame(&hs, mm_x - 1, mm_y - 1, mm_x + map_w + 1, mm_y + mm_rows + 1, 1, HC(H_BLACK),
              ROP_COPY);
    /* the selection's panel and the buttons */
    info_x0 = mm_x + map_w + (mode ? 6 : 14);
    btn_x1 = view_w - (mode ? 4 : 8);
    btn_x0 = btn_x1 - (mode ? 120 : 150);
    info_x1 = btn_x0 - (mode ? 4 : 12);
    for (x = 0; x < 3; x++)
        button(x, 0);
    hud_info();
    hud_minimap();
}

void hud_info(void)
{
    char buf[48];
    int k, n = 0, x, y0 = 6, y1 = hud_h - 6, scale = mode ? 1 : 2;
    gfx_fill(&hs, info_x0, y0, info_x1, y1, HC(H_DARK), ROP_COPY);
    gfx_bevel(&hs, info_x0, y0, info_x1, y1, HC(H_BLACK), HC(H_LIGHT));
    if (!nsel) {
        font_draw(&hs, font_sans, info_x0 + 8, y0 + 18, "No units selected", HC(H_TEXT), -1);
        font_draw(&hs, font_sans, info_x0 + 8, y0 + 36, mode ? "Drag: select" :
                  "Drag to select, right-click to send", HC(H_LIGHT), -1);
        return;
    }
    if (nsel == 1) {
        for (k = 0; k < nunits && !units[k].sel; k++)
            ;
        icon(info_x0 + 8, y0 + 8, units[k].type, units[k].team);
        font_draw(&hs, font_sans, info_x0 + 12 + 12 * scale, y0 + 18,
                  units[k].type ? "Soldier" : "Worker", HC(H_YELLOW), -1);
        sprintf(buf, "HP %d/100", units[k].hp);
        font_draw(&hs, font_sans, info_x0 + 12 + 12 * scale, y0 + 34, buf, HC(H_TEXT), -1);
        x = info_x0 + 12 + 12 * scale;
        gfx_fill(&hs, x, y0 + 40, x + 100 / (3 - scale), y0 + 44, HC(H_RED), ROP_COPY);
        gfx_fill(&hs, x, y0 + 40, x + units[k].hp / (3 - scale), y0 + 44, HC(H_GREEN),
                 ROP_COPY);
        return;
    }
    sprintf(buf, "%d selected", nsel);
    font_draw(&hs, font_sans, info_x0 + 8, y0 + 16, buf, HC(H_YELLOW), -1);
    /* a row of their icons */
    for (k = 0, x = info_x0 + 8; k < nunits && x + 12 * scale <= info_x1 - 4; k++)
        if (units[k].sel) {
            icon(x, y0 + 22, units[k].type, units[k].team);
            x += 12 * scale + 2;
            n++;
        }
}

/* a dot on the minimap: one word read and written */
static void dot(int x, int y, unsigned c)
{
    const Format *f = hs.f;
    unsigned *w = hud + hrow[y] + (x >> pshift), m = f->pmask[x & (ppw - 1)];
    *w = (*w & ~m) | (f->solid[c] & m);
}

void hud_minimap(void)
{
    int k, x0, y0;
    unsigned blue = HC(H_YELLOW), red = HC(H_RED), white = HC(H_WHITE);
    k_copy(hud + mm_y * hud_words + (mm_x >> pshift), mm_base, mm_words, mm_rows, hud_words * 4,
           mm_words * 4);
    for (k = 0; k < nunits; k++) {
        Unit *u = &units[k];
        int x = mm_x + (u->x >> 8), y = mm_y + ((u->y >> 8) << (mm_sy - 1));
        unsigned c = u->team ? red : u->sel ? white : blue;
        dot(x, y, c);
        if (mm_sy == 2)
            dot(x, y + 1, c);
    }
    x0 = mm_x + cam_x / TILE;
    y0 = mm_y + cam_y / TILE * mm_sy;
    gfx_frame(&hs, x0, y0, x0 + view_w / TILE, y0 + (view_h / TILE) * mm_sy, 1, white,
              ROP_COPY);
}

void hud_buttons(void)
{
    int k;
    for (k = 0; k < 3; k++)
        button(k, 0);
}

void hud_status(const char *s)
{
    int y = mode ? 60 : 52;
    gfx_fill(&hs, btn_x0, y, btn_x1, hud_h - 3, HC(H_MID), ROP_COPY);
    font_draw(&hs, font_sans, btn_x0 + 2, y + 13, s, HC(H_TEXT), -1);
}

/* a click at HUD pixel (x, y): the minimap moves the view (left) or sends
   the selection (right); the buttons */
int hud_click(int x, int y, int button_mask)
{
    int k;
    if (x >= mm_x && x < mm_x + map_w && y >= mm_y && y < mm_y + mm_rows) {
        int tx = x - mm_x, ty = (y - mm_y) / mm_sy;
        if (button_mask & 2) {
            units_command(tx * TILE + TILE / 2, ty * TILE + TILE / 2);
        } else {
            cam_x = tx * TILE - view_w / 2;
            cam_y = ty * TILE - view_h / 2;
        }
        return 1;
    }
    for (k = 0; k < 3; k++) {
        int x0, y0, x1, y1;
        btn_rect(k, &x0, &y0, &x1, &y1);
        if (x >= x0 && x < x1 && y >= y0 && y < y1) {
            if (k == 0)
                units_stop();
            else if (k == 1)
                units_scatter();
            else
                render_set((strategy + 1) % S_N);
            button(k, 0);
            return 1;
        }
    }
    return 0;
}
