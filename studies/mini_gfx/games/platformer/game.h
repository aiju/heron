/* Fennec Run: a side-scrolling platformer on M1 (320 x 240 x 8, each line
   shown twice by the descriptors), to find out what horizontal scrolling,
   parallax and sprites cost on RFC 0042's video. NOTES.md has the
   findings.

   The screen is bands of lines, each a buffer of its own that the line
   descriptors point at:

     lines   0- 15  the HUD, its own buffer
     lines  16- 63  the sky and clouds, scrolling at 1/8 (and drifting)
     lines  64- 95  the mountains, at 1/4
     lines  96-111  the hills, at 1/2
     lines 112-239  the playfield: 8 rows of 16 x 16 tiles, at 1

   A descriptor gives a line's start in whole words, 4 pixels in M1, so
   coarse scrolling is free and the 4 phases within a word are the
   problem: the strategies (scroll.c) are different answers to it. */

#ifndef GAME_H
#define GAME_H

/* ---- the screen ---- */
#define SW 320                  /* the picture in M1's pixels */
#define SH 240                  /* logical lines (each shown twice) */
#define LW 80                   /* a line's words */
#define HUD_Y 0
#define HUD_H 16
#define SKY_Y 16
#define SKY_H 48
#define MTN_Y 64
#define MTN_H 32
#define HILL_Y 96
#define HILL_H 16
#define PF_Y 112                /* the playfield */
#define PF_H 128
#define ROWS 8                  /* tile rows */
#define TS 16                   /* a tile's pixels */
#define TW 4                    /* a tile's words in a line */

/* ---- the level (level.c) ---- */
#define LEVEL_W 240             /* columns */
extern unsigned char level[ROWS][LEVEL_W + 1];  /* tile numbers; a column of empties past the end */
void level_init(void);
int tile_solid(int t);          /* stops the player from every side */
int tile_top(int t);            /* stops the player from above only (planks) */
enum {
    T_EMPTY, T_GRASS, T_GRASS_L, T_GRASS_R, T_DIRT, T_BRICK, T_BLOCK, T_USED, T_COIN,
    T_BUSH_L, T_BUSH_R, T_FLOWER, T_FENCE, T_PLANK, T_STONE, T_SPIKES, T_POLE, T_FLAG,
    T_TREE_TL, T_TREE_TR, T_TREE_ML, T_TREE_MR, T_TREE_BL, T_TREE_BR,
    T_N
};
/* where the level's beetles start: (column, row) */
extern int level_nbugs;
extern signed char level_bug[24][2];

/* ---- the art (art.c) ---- */
/* every image's words in the screen's format, built at the start:
   tile t in tile row r at phase p (0-3, the pixels its left edge is
   shifted left by within a word): 16 lines of 5 words. Word 0 holds the
   tile's first p pixels at the word's end, words 1-3 the next 12, word 4
   the last 4 - p at its start: tile column c's words in a line at phase p
   are then w1, w2, w3, (w4 | w0 of column c + 1). */
#define TIMG_WORDS (16 * 5)
const unsigned *timg(int t, int row, int phase);
/* the playfield's background colour on picture line y (a gradient) */
unsigned pf_bg(int y);

/* a sprite's frame at each phase: h rows of 5 (keep, image) pairs, keep
   the mask of the background's bits the sprite leaves */
typedef struct {
    int h;
    const unsigned *ph[4];      /* phase p: the sprite moved right by p pixels */
} Sprite;
enum { S_FOX_STAND, S_FOX_RUN0, S_FOX_RUN1, S_FOX_RUN2, S_FOX_RUN3, S_FOX_JUMP, S_FOX_FALL,
       S_BUG0, S_BUG1, S_BUG_FLAT, S_BIRD0, S_BIRD1, S_COIN, S_N };
extern Sprite sprites[2][S_N];  /* [0] facing right, [1] left */

/* the parallax bands: a period of BAND_P pixels, 4 phase copies of each
   line BAND_PITCH words wide (the period and a screen's width after it) */
#define BAND_P 512
#define BAND_PITCH (BAND_P / 4 + LW)
extern unsigned *band_sky[4], *band_mtn[4], *band_hill[4];

void art_init(void);
void palette_init(void);
/* a word of 4 pixels in the screen's format (L0 or L1), and a pixel's mask */
unsigned pack4(int c0, int c1, int c2, int c3);
unsigned pix(int p, int c);
extern unsigned pix_mask[4];
/* the cursor's image (C1): the bird, two frames each way */
extern unsigned *bird_cursor[2][2];

/* ---- the kernels: C (kernels.c) and draft 2 (kernels.s) ---- */
/* sprites: h rows from rows[i] (the word under the sprite's first word, 0:
   not drawn), n (keep, image) pairs a row from data, stride words apart */
typedef struct {
    unsigned **rows;
    const unsigned *data;
    int h, n, stride;
    unsigned *save;             /* k_sprite_save: each row's n words first, in order */
} SprJob;

/* a full redraw of tile rows: for each of h lines, 21 tiles' groups from
   tiles[0..21] (each tile's image at the line, + 20 bytes a line) into d,
   pitch words a line; tiles[21] gives only its first word */
typedef struct {
    unsigned *d;
    int pitch, h;
    const unsigned *const *tiles;
} RedrawJob;

void k_copy_c(unsigned *d, const unsigned *s, int n);
void k_shift_c(unsigned *d, const unsigned *s, int n, int p);
void k_sprite_c(const SprJob *j);
void k_sprite_save_c(const SprJob *j);
void k_restore_c(const SprJob *j);
void k_redraw_c(const RedrawJob *j);
void k_copy_asm(unsigned *d, const unsigned *s, int n);
void k_copy_ldm(unsigned *d, const unsigned *s, int n);
void k_copy_blk(unsigned *d, const unsigned *s, int n);
void k_fill_blk(unsigned *d, unsigned v, int n);
void k_shift_asm(unsigned *d, const unsigned *s, int n, int p);
void k_shift_blk(unsigned *d, const unsigned *s, int n, int p);
void k_sprite_asm(const SprJob *j);
void k_sprite_save_asm(const SprJob *j);
void k_restore_asm(const SprJob *j);
void k_redraw_asm(const RedrawJob *j);
void k_desc_asm(unsigned *d, unsigned *const *src, int n);

/* the variant's choice */
#if defined(GFX_BLK)
#define k_copy k_copy_blk
#define k_shift k_shift_blk
#define k_sprite k_sprite_asm
#define k_sprite_save k_sprite_save_asm
#define k_restore k_restore_asm
#define k_redraw k_redraw_asm
#elif defined(GFX_ASM)
#define k_copy k_copy_asm
#define k_shift k_shift_asm
#define k_sprite k_sprite_asm
#define k_sprite_save k_sprite_save_asm
#define k_restore k_restore_asm
#define k_redraw k_redraw_asm
#else
#define k_copy k_copy_c
#define k_shift k_shift_c
#define k_sprite k_sprite_c
#define k_sprite_save k_sprite_save_c
#define k_restore k_restore_c
#define k_redraw k_redraw_c
#endif

/* ---- the strategies (scroll.c) ---- */
enum { SC_COARSE, SC_PRESHIFT, SC_BLIT, SC_REDRAW, SC_N };
extern const char *const sc_names[SC_N];
extern int strategy;
void scroll_init(void);
/* the playfield's lines for the frame being built into table t, the view
   at level pixel x: each line's word (src[y]) and whether the frame owns
   it (a back buffer the sprites may draw into) */
void scroll_frame(int t, int x);
/* a tile changed: the buffers that hold it */
void scroll_tile(int row, int col);
extern unsigned *line_src[SH];  /* every line's first word this frame */
extern unsigned char line_own[SH];

/* ---- timing (platformer.c) ---- */
enum { P_LOGIC, P_SEAM, P_PLAYFIELD, P_DESC, P_LINES, P_SPRITES, P_HUD, P_N };
extern unsigned ptime[P_N];
void pmark(int part);

#endif
