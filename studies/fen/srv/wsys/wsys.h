/* The window system's parts: the window manager (gwm.c, from the Egret
 * desktop's), the keyboard and the mouse (input.c), and the server
 * (main.c). The drawing is the graphics study's library. */

#ifndef WSYS_H
#define WSYS_H

#include "gfx.h"

/* the video card (studies/fen/board/src/video.rs), mapped at VRAM */
#define VRAM ((unsigned char *)0x00800000)
#define VRAM_PA 0x10000000
#define VRAM_PAGES 512
#define VIDEO_REGS ((volatile unsigned *)0x00A00000)
#define VIDEO_REGS_PA 0x1FF00000
#define STRIDE 1024
#define SCREEN_W 640
#define SCREEN_H 480
/* VRAM below the screen: what a menu covers */
#define SAVE_UNDER (VRAM + STRIDE * 512)

/* ---- the window manager (gwm.c) ----

   Windows are numbered 1 to MAXWIN; 0 is the screen itself. What of a
   window comes into view is filled with its background and becomes its
   pending update, which its program gets as an EV_EXPOSE and paints. */

#define MAXWIN 32
#define TITLE_H 18

enum { PART_NONE, PART_CONTENT, PART_TITLE, PART_CLOSE, PART_GROW };

extern Surface screen;
#define MAXFONTS 2
extern Font fonts[MAXFONTS];

void gwm_init(int depth);
int gwm_open(int x0, int y0, int x1, int y1, const char *title, unsigned bg);
void gwm_close(int id);
void gwm_raise(int id);
void gwm_move(int id, int x0, int y0);
void gwm_resize(int id, int w, int h);
void gwm_set_title(int id, const char *title);
int gwm_top(void);
int gwm_exists(int id);
int gwm_hit(int x, int y, int *part);
void gwm_frame(int id, Rect *r);
void gwm_content(int id, Rect *r);
void gwm_scroll(int id, int x0, int y0, int x1, int y1, int dy);
void gwm_invalidate(int id, const Rect *r);
int gwm_next_update(Rect *r);
void gwm_repaint_all(void);
void gwm_outline(const Rect *r);
unsigned gwm_bg(int id);
int gwm_clips(int id, Rect **clips, int *ox, int *oy);
void gwm_paint_clip(int id, const Rect *r);

/* ---- the cursor (main.c): off while anything draws ---- */
void cursor_off(void);

/* ---- input (input.c) ---- */
int input_init(void);
/* what the keyboard and mouse sent since: calls back for each */
void input_poll(void (*key)(int code, int mods, int down),
                void (*mouse)(int dx, int dy, int buttons));

#endif
