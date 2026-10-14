/* Colours per depth, the desktop pattern, icons and the cursor. */

#ifndef THEME_H
#define THEME_H

#include "gfx.h"

/* The palettes: 2 entries at 1 bit per pixel (black, white), 4 greys at
   2, the 16 VGA colours at 4, and xterm's 256 at 8 (the 16, a 6x6x6 cube
   and 24 greys). RGB triples. */
extern const unsigned char palette16[16 * 3];
void theme_rgb(int depth, int c, int *r, int *g, int *b);

/* Colour roles, as pixel values at the current depth. */
extern unsigned c_black, c_white, c_desk, c_desk2, c_frame, c_title, c_title_text,
    c_title_off, c_window, c_text, c_accent, c_shadow, c_light;

void theme_init(int depth);
unsigned theme_pattern(int depth, int row);     /* a word of the desktop pattern */

/* The nearest colour in the palette (at depths 2 and 3). */
unsigned theme_nearest(int depth, int r, int g, int b);
/* A 65-entry ramp from bg to fg for anti-aliased text (coverage 0..64). */
void theme_ramp(int depth, unsigned fg, unsigned bg, unsigned char *ramp);

extern Surface icon, cursor_mask, cursor_image;
#define CURSOR_W 12
#define CURSOR_H 19


#endif
