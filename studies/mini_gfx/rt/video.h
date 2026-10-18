/* The video as the programs use it (RFC 0042): a mode, the descriptor
   tables, page flips, the palette, the cursor, bank 1's memory and the
   beam as a clock. */

#ifndef VIDEO_H
#define VIDEO_H

#include "mini.h"

typedef struct {
    int mode;                   /* 0-6: M0-M6 */
    int w, h;                   /* the picture in the mode's own pixels (320 x 480 in M1) */
    int bpp;
    int words;                  /* a line's words */
    int xga;                    /* the 1024 x 768 family */
    int lines, table;           /* lines a frame; T, picture line 0's descriptor */
    int irq_char;               /* the character a descriptor's interrupt comes at */
    unsigned frame_ticks;       /* master ticks a frame */
    unsigned ctrl;              /* what the control register was last written */
} VideoInfo;

extern VideoInfo vid;

/* The mode from the next frame, with the picture and the interrupt on;
   flags: VC_F1, VC_CURSOR, VC_D1. Both descriptor tables are cleared
   (every line shows bank 1's word 0 until set). */
void video_init(int mode, unsigned flags);
void video_ctrl(unsigned set, unsigned clear);

/* The descriptor tables, from picture line 0 (TSEL picks one) */
unsigned *video_table(int t);
/* n lines from y0 in table t: from addr (in bank 1), pitch bytes apart,
   palette bank `bank` */
void video_lines(int t, int y0, int n, const void *addr, int pitch, int bank);
unsigned video_desc(const void *addr, int bank);
/* bank 1's word address of a CPU address in it */
unsigned video_word(const void *p);
/* show table t from the next frame: waits for this frame's end */
void video_show(int t);
/* D1: the frame base */
void video_base(const void *addr, int bank);

/* until the next frame's end; the number of frames waited for since the
   last call (more than 1: a frame was missed) */
int video_wait(void);
/* master ticks since the video started (the frame count and the beam,
   P1); 19.86 ns each */
unsigned video_ticks(void);
/* the line interrupts: a descriptor's bit 23 calls rt_line_hook(y) */
void video_line_irq(int t, int y, int on);

/* the palette: RGB 5:6:5 */
unsigned rgb565(int r, int g, int b);
void video_pal(int n, unsigned c);
void video_pal_rgb(int n, int r, int g, int b);
/* entry n in every palette bank (4, 2 and 1 bits a pixel) */
void video_pal_all(int n, unsigned c);

/* the cursor (C1): 32 x 32, 2 bits a pixel, its rows two words each in
   bank 1; colours 1-3 are palette entries 253-255 */
void video_cursor(const unsigned *image);
void video_cursor_at(int x, int y);

/* bank 1, from after the two descriptor tables, word aligned */
void *vram_alloc(unsigned bytes);
void vram_reset(void);

#endif
