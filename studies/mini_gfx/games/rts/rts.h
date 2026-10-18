/* A real-time strategy scene on Heron Mini's video (RFC 0042): a tile
   map larger than the screen, units that walk a flow field, the mouse
   on the hardware cursor, a selection rectangle, a minimap and a HUD
   with its own palette bank. NOTES.md has what it found.

   The map is drawn once into a world bitmap in bank 1; the line
   descriptors show a window of it, so scrolling costs only the
   descriptors. What changes each frame is the units, drawn by one of
   five redraw strategies (render.c). */

#ifndef RTS_H
#define RTS_H

#include "gfx.h"
#include "video.h"

/* ---- the mode: M0 (640 x 480 x 4) or M1 (320 x 240 x 8, lines doubled) ---- */
extern int mode;                /* a poke: 0 or 1 */
extern int bpp, ppw, pshift;    /* bits a pixel, pixels a word, log2 ppw */
extern int fmt;                 /* the screen's pixel format (gfx.h) */
extern int view_w, view_h;      /* the map's window, in the mode's pixels */
extern int view_words;          /* its words a row */
extern int hud_h;               /* the HUD's rows (M1: not doubled) */
extern int rep;                 /* screen lines a viewport row: 1, or 2 in M1 */
extern int hud_base;            /* the HUD's colours: palette bank 1 in M0, entries 16-31 in M1 */

#define TILE 16                 /* pixels, in both modes */

/* ---- the map (map.c) ---- */
enum {
    T_GRASS, T_GRASS2, T_GRASS3, T_GRASS4, T_SAND, T_SAND2, T_TREE, T_TREE2, T_ROCK, T_ROCK2,
    T_FLOWER, T_WATER,                  /* + 16 shore variants: T_WATER + land sides (NESW) */
    T_BASE = T_WATER + 16,              /* + 9 a team: a 3 x 3 building */
    T_N = T_BASE + 18
};
extern int map_w, map_h;        /* tiles */
extern int world_w, world_h;    /* pixels */
extern int wpitch;              /* the world's words a row */
extern unsigned char *map;      /* the tile of each cell */
extern unsigned char *pass;     /* 1: walkable */
extern unsigned *world[2];      /* the world bitmaps shown (bank 1): one, or two double-buffered */
extern unsigned *clean;         /* the world without units (bank 0), to erase from */
extern int *wrowo;              /* each world row's first word, as an offset */
extern unsigned *tiles;         /* the tiles' pixels: tile k's rows from k * tile_words */
extern int tile_words;          /* a tile's words: 16 rows of TILE / ppw */
extern int base_x[2], base_y[2];

void map_make(unsigned seed);
void world_draw(void);          /* the world bitmaps and the clean copy from the map */
int walkable(int tx, int ty);

/* flow fields: the distance (in steps) of each cell from a target, by a
   breadth-first search spread over frames */
#define NFIELD 8
#define FIELD_FAR 0xFFFF
typedef struct {
    unsigned short *dist;       /* map_w * map_h */
    unsigned short *queue;
    int head, tail;
    int tx, ty;                 /* the target cell */
    int users;                  /* units following it */
    int done;
} Field;
extern Field fields[NFIELD];
int field_new(int tx, int ty);
void field_step(int budget);    /* advance the searches by `budget` cells */

/* ---- art (art.c) ---- */
void palette_init(void);
void tiles_make(void);
/* a unit sprite: per phase (the pixel offset in its first word), h rows
   of n (keep, image) word pairs: dst = (dst & keep) | image */
/* (64 bytes, and Unit 32: the compiler multiplies an index by any other
   size with MULS, tens of cycles) */
typedef struct {
    int h, y0;                  /* rows drawn, and the first's row in the 16-pixel cell */
    unsigned char n[8];
    unsigned *data[8];
    int pad[4];
} Sprite;
#define SPR_W 12                /* a unit's picture: 12 x 12 in a 16 x 16 cell */
#define SPR_H 12
/* type (2) x team (2) x facing (2) x step (2) x selected (2) */
#define SPR_INDEX(ty, tm, f, st, sel) (((((ty) * 2 + (tm)) * 2 + (f)) * 2 + (st)) * 2 + (sel))
extern Sprite sprites[32];
void sprites_make(void);
extern unsigned *cursor_arrow, *cursor_target;
void cursors_make(void);
/* the unit art in the HUD's colours, 1 bit a plane for gfx: draws a unit's icon */
void icon_draw(Surface *s, int x, int y, int type, int team);

/* ---- units (units.c) ---- */
enum { U_WORKER, U_SOLDIER };
typedef struct {
    int x, y;                   /* the feet, in world pixels x 16 */
    int gx, gy;                 /* where it's going, world pixels x 16 */
    short vx, vy;               /* this step's velocity, x 16 */
    short field;                /* the flow field it follows, or -1 */
    short wait;                 /* frames before it looks for its next cell */
    unsigned char type, team, facing, step, sel, moving, hp, pad;
} Unit;
#define MAX_UNITS 320
extern Unit units[MAX_UNITS];
extern int nunits, nsel;
void units_init(int n, int bench);
void units_update(int dt);      /* dt frames */
void units_bench_update(int dt);
void units_command(int wx, int wy);         /* the selected units to world pixel (wx, wy) */
void units_select(int x0, int y0, int x1, int y1, int add);     /* a world rectangle */
void units_stop(void);
void units_scatter(void);
void units_spawn(int n);        /* n idle soldiers round the hall */

/* ---- rendering (render.c) ---- */
enum { S_DIRTY, S_BEAM, S_DOUBLE, S_FULL, S_TILES, S_N };
extern const char *strategy_names[S_N];
extern int strategy;
extern int cam_x, cam_y;        /* the viewport's top left in the world; cam_x on a word */
extern int sel_on, sel_x0, sel_y0, sel_x1, sel_y1;  /* the selection rectangle, world pixels */
extern int tears;               /* S_BEAM: bands the beam overtook; S_DIRTY: units it caught erased */
extern int count_tears;         /* S_DIRTY: look for them (a beam read a unit) */
void render_init(void);
void render_set(int s);         /* switch strategies (between frames) */
/* a frame: waits for the frame's end (and flips) inside; returns frames waited */
int render_frame(void);
extern unsigned t_draw, t_erase, t_bg, t_items;    /* this frame's ticks, by part */

/* ---- the HUD (hud.c) ---- */
extern unsigned *hud;
void hud_init(void);
void hud_info(void);            /* the selection's panel */
void hud_minimap(void);         /* the minimap: the terrain, the units, the view */
void hud_status(const char *s);
void hud_buttons(void);         /* again: the Redraw button names the strategy */
int hud_click(int x, int y, int button);    /* screen coordinates in the HUD: 1 if handled */

/* ---- the kernels (kern.c, kern.s, kern_blk.s) ---- */
/* h rows of n words from s to d; pitches in bytes */
void k_copy_c(unsigned *d, const unsigned *s, int n, int h, int dpitch, int spitch);
void k_copy_asm(unsigned *d, const unsigned *s, int n, int h, int dpitch, int spitch);
void k_copy_blk(unsigned *d, const unsigned *s, int n, int h, int dpitch, int spitch);
/* a pre-shifted sprite: h rows of n (keep, image) pairs from s into d */
void k_sprite_c(unsigned *d, const unsigned *s, int n, int h, int dpitch);
void k_sprite_asm(unsigned *d, const unsigned *s, int n, int h, int dpitch);
/* a tile: 16 rows of n words, contiguous from s */
void k_tile_c(unsigned *d, const unsigned *s, int n, int dpitch);
void k_tile_asm(unsigned *d, const unsigned *s, int n, int dpitch);
void k_tile_blk(unsigned *d, const unsigned *s, int n, int dpitch);
/* the viewport's descriptors: n words from base, step words apart, each written rep times */
void k_desc_c(unsigned *t, unsigned base, int step, int n, int rep);

#ifdef GFX_BLK
#define k_copy k_copy_blk
#define k_sprite k_sprite_asm
#define k_tile k_tile_blk
#elif defined(GFX_ASM)
#define k_copy k_copy_asm
#define k_sprite k_sprite_asm
#define k_tile k_tile_asm
#else
#define k_copy k_copy_c
#define k_sprite k_sprite_c
#define k_tile k_tile_c
#endif

/* ---- the game (rts.c) ---- */
extern int bench;               /* a poke: 1 runs the benchmark */
extern unsigned frame_no;
extern unsigned t_logic, t_hud;
extern unsigned rng_state;
unsigned rnd(void);
int rnd_n(int n);

#endif
