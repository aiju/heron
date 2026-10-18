/* Racer: a pseudo-3D road racer built on the line descriptors (NOTES.md).

   The road is drawn once, at init, into rows wider than the screen: row k
   is the road as flat ground shows it k + 1 lines below the horizon, in
   one copy per pixel phase (the descriptors' start addresses are whole
   words). Each frame the CPU only works out, for each screen line, which
   row it shows, from which pixel, and in which palette bank (the stripes):
   curves are start addresses, hills repeated or skipped rows, the moving
   stripes palette banks. The sky and the mountains are descriptors too.
   Lines with sprites on them get a scratch line, made from the line's
   source (copied, or the road rendered by spans), and the sprites are
   drawn into it. Two descriptor tables and two pools of scratch lines
   make the double buffering. */

#ifndef RACER_H
#define RACER_H

#include "gfx.h"
#include "video.h"

/* ---- the screen ---- */
#define NLINES 480
#define LW 80                   /* a line's words, M0 and M1 */
#define HY 224                  /* the horizon: flat ground's row k is line HY + k */
#define NROWS 256               /* road rows; distance d = k + 1 is 1..256 */
#define HUD_LINES 20            /* the top lines: the speed, the time */
#define SLACK 16                /* words between scratch lines: sprites overhang into them */
#define SPITCH (LW + SLACK)     /* a scratch line's pitch */

/* the mode, as the program starts (mode_sel): M0 640 x 480 x 4 with
   palette banks, or M1 320 x 480 x 8 without */
extern int W, PPW, PS, XS, NPH, M1;
extern const Format *F;

/* options, poked by the harness (main.c) */
extern int mode_sel, soft, prep_copy, sky_irq, autopilot, run_frames;

/* ---- the world ---- */
#define CAM_H 1024              /* the camera's height over the road */
#define PROJ (1 << 19)          /* flat ground at distance d (lines below the horizon) is z = PROJ / d */
#define SEG 256                 /* a segment, a stripe, in world units */
#define TSHIFT 5                /* the track's tables: an entry per 32 units */
#define TLEN 4096               /* entries: 131072 units, 512 segments, a lap */
#define TMASK (TLEN - 1)
#define LAP (TLEN << TSHIFT)
#define ROAD_W 1040             /* the road's half width */
#define NSEG (LAP / SEG)
#define D_CAR 246               /* the player's car stands at distance 246 */
#define NCARS 7

extern short trk_curve[TLEN];   /* each entry's curve: the road's screen x bends by it a step */
extern short trk_height[TLEN];  /* the road's height */
extern int zt[NROWS + 1];       /* PROJ / d */

/* roadside objects: up to two a segment */
typedef struct {
    signed char kind[2];        /* -1: none */
    short x[2];                 /* world x from the road's centre */
    short pad;                  /* 8 bytes: the compiler indexes other sizes with a multiply */
} SegObj;
extern SegObj seg_obj[NSEG];

typedef struct {
    int z, x, speed, kind;
} Car;
extern Car cars[NCARS];

/* the player */
extern int camz, speed, px, steer_vis, lap, lap_frames, best_frames, game_frames;

void track_build(void);
int track_height_at(int z);
int track_curve_at(int z);

/* ---- the projection (track.c), each frame ---- */
/* each line: what it shows, and for a road line its row, its stripe and
   the road's centre (from the screen's, the mode's pixels), one word:
   sx << 16 | row << 8 | stripe << 4 | kind */
enum { LK_BG, LK_ROAD, LK_GRASS, LK_HUD };
extern unsigned line_info[NLINES];
#define LI_KIND(i) ((i) & 15)
#define LI_K(i) (((i) >> 8) & 255)
#define LI_STRIPE(i) (((i) >> 4) & 15)
#define LI_SX(i) ((int)(i) >> 16)
/* each step: its line and the top line of the road nearer it (step_yc[2d],
   [2d + 1]: a word), the road's centre there */
extern short step_yc[2 * (NROWS + 2)], step_sx[NROWS + 2];
extern int road_top;                        /* the top line the road reaches */
/* project into table t's descriptors (road lines, then the rest) */
void project(unsigned *desc);

/* ---- the scene (scene.c) ---- */
/* logical colours; M0's are the palette index in every bank */
enum {
    C_SKY, C_CLOUD, C_CLOUDSH, C_MTN, C_MTNSH, C_SNOW, C_HILL, C_GRASS, C_ROAD, C_RUMBLE,
    C_LANE, C_BLACK, C_RED, C_DRED, C_LGREEN, C_YELLOW, C_N
};
extern unsigned char col_index[C_N];        /* M1: a colour's palette index (road ones: + stripe) */
unsigned colour_word(int c, int stripe);    /* a word of the colour, for a road line's stripe */
void scene_palette(void);
void scene_build(void);                     /* the road rows, the background, the sky */
void scene_bg_desc(unsigned *desc);         /* the background's lines, scrolled */
unsigned road_desc(int k, int sx, int stripe);
/* a road line drawn: C by the span kernel, the assembly overdraws (grass,
   the rumble strips' span, the road's, the lane lines) */
void road_line_c(unsigned *line, int k, int sx, int stripe);
extern int half_w;
extern unsigned road_cw4[2][4];             /* grass, rumble, road, lane: each stripe's colour words */
extern int road_l3[NROWS];
extern unsigned grass_desc;
extern int bg_scroll[2];                    /* the clouds' and the mountains' scroll, 640-unit pixels << 8 */
extern unsigned bank1_used;
void hud_draw(int t, unsigned *desc);
void sky_irq_frame(void);
void sky_line_hook(int y);
extern unsigned sky_irqs;

/* the spans of a road row: its 8 boundaries from the centre c */
void road_bounds(int *b, int k, int c);
extern int road_rw[NROWS], road_rm[NROWS], road_ln[NROWS];

/* ---- sprites (sprites.c) ---- */
extern unsigned *pool[2];              /* the scratch lines, SLACK words in */
extern int pool_lines;
void sprites_build(void);
void sprites_frame(unsigned *desc, int t);  /* place, scratch lines, draw */
void sprites_bench(void);
extern unsigned spr_lines, spr_words, spr_count;

/* ---- kernels: C, and draft 2 assembly (kern.s) ---- */
/* spans: n spans over a line of nw words; b[0..n] the boundaries in
   pixels (b[0] = 0, b[n] = nw * PPW), cw[i] span i's colour word */
void spans_c(unsigned *line, const int *b, const unsigned *cw, int n);
/* a sprite's rows from r0, n of them, into d (pitch words a row) */
void spr_draw_c(unsigned *d, const unsigned *img, int r0, int n);
void copy_line_c(unsigned *d, const unsigned *s);
/* what the assembly reads: the format's from[] and a word's pixels - 1 */
extern const unsigned *span_from;
extern int ppw_mask;
#ifdef GFX_ASM
void spans_asm(unsigned *line, const int *b, const unsigned *cw, int n);
void spr_draw_asm(unsigned *d, const unsigned *img, int r0, int n);
void copy_line_asm(unsigned *d, const unsigned *s);
int project_asm(unsigned *desc);         /* the projection's steps: the road's top line */
void road_line_asm(unsigned *line, int k, int sx, int stripe);
#ifdef GFX_BLK
void road_line_blk(unsigned *line, int k, int sx, int stripe);
#define road_line road_line_blk
void spans_blk(unsigned *line, const int *b, const unsigned *cw, int n);
void spr_draw_blk(unsigned *d, const unsigned *img, int r0, int n);
void copy_line_blk(unsigned *d, const unsigned *s);
#define spans spans_blk
#define spr_draw spr_draw_blk
#define copy_line copy_line_blk
#else
#define road_line road_line_asm
#define spans spans_asm
#define spr_draw spr_draw_asm
#define copy_line copy_line_asm
#endif
#else
#define road_line road_line_c
#define spans spans_c
#define spr_draw spr_draw_c
#define copy_line copy_line_c
#endif

/* ---- timing (main.c) ---- */
enum { T_LOGIC, T_PROJ, T_BG, T_PLACE, T_LINES, T_DRAW, T_HUD, T_N };
void tmark(int part);

#endif
