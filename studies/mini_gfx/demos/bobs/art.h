/* The bobs' pixel art (art.c), in logical colours that each mode maps to
   its own palette: four ramps of eight shades, dark to light, and a few
   single colours. Each function fills s x s pixels and their mask
   (1: drawn), a byte each. */

#ifndef ART_H
#define ART_H

enum {
    C_RED = 0, C_GOLD = 8, C_CYAN = 16, C_GREEN = 24,
    C_WHITE = 32, C_BLACK, C_OUTLINE, C_MOUTH, C_FEET, C_N
};

void art_ball(int s, unsigned char *pix, unsigned char *mask);
void art_ring(int s, unsigned char *pix, unsigned char *mask);
void art_gem(int s, unsigned char *pix, unsigned char *mask);
void art_critter(int s, unsigned char *pix, unsigned char *mask);

#endif
