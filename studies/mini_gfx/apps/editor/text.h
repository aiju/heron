/* Text in cells of 8 x 16 (the library's font_cell), each cell with its
   own colours: the editors' one drawing call. */

#ifndef TEXT_H
#define TEXT_H

#include "gfx.h"

/* how cells are drawn: 0 our own (a cell is a word at 4 bits a pixel,
   half a word at 2, a byte at 1: written whole, a glyph's 16 rows at a
   time), 1 the library's font_cells, a call for each run of one colour */
extern int text_lib;

/* n cells at (x, y), x a multiple of 8: characters t[0..n), attributes
   a[0..n), each its foreground | background << 4 */
void text_cells(Surface *s, int x, int y, const char *t, const unsigned char *a, int n);
/* the caret: a bar 2 pixels wide and 16 high at (x, y), x a multiple of 8,
   XOR'd with colour c (drawn twice, it's gone) */
void text_caret(Surface *s, int x, int y, unsigned c);

#endif
