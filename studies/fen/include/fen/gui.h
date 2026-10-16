/* libgui: windows for programs, over the window system's protocol
 * (fen/wsys.h). Drawing is batched per window and sent when the batch
 * fills, the window changes, or the program waits for an event.
 *
 * A program that is a server too (the terminal) receives on gui_port()
 * itself, and calls gui_poll() when a notification with GUI_BIT comes. */

#ifndef FEN_GUI_H
#define FEN_GUI_H

#include <fen/wsys.h>

#define GUI_BIT 0x40000000u

int gui_init(void);                 /* 0, or an error if there's no window system */
int gui_port(void);
int gui_open(int x, int y, int w, int h, const char *title, unsigned bg);
void gui_close(int win);
void gui_title(int win, const char *title);
void gui_raise(int win);

void gui_fill(int win, unsigned colour, int x0, int y0, int x1, int y1);
void gui_frame(int win, unsigned colour, int x0, int y0, int x1, int y1, int t);
void gui_line(int win, unsigned colour, int x0, int y0, int x1, int y1);
void gui_text(int win, unsigned colour, int font, int x, int y, const char *s, int n);
void gui_textbg(int win, unsigned fg, unsigned bg, int font, int x, int y, const char *s, int n);
void gui_ellipse(int win, unsigned colour, int xc, int yc, int a, int b, int filled);
void gui_poly(int win, unsigned colour, const int *xy, int n);
void gui_pixels(int win, int x, int y, int w, int h, const unsigned char *px);
void gui_scroll(int win, int x0, int y0, int x1, int y1, int dy);
void gui_clip(int win, int x0, int y0, int x1, int y1);
void gui_noclip(int win);
void gui_flush(void);

/* the next event: 1, or 0 if there's none and `wait` is 0 */
int gui_event(struct ws_event *e, int wait);
/* after a notification with GUI_BIT on gui_port(): fetch what's waiting */
void gui_poll(void);

struct ws_font *gui_font(int font);
int gui_width(int font, const char *s, int n);

/* screen size */
int gui_screen(int *w, int *h);

#endif
