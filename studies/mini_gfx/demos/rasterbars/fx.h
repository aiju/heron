/* What the demos (rasterbars, plasma, wobble, rotozoom) share: a sine
   table, the interrupt vector taken over by a handler of one's own, the
   CPU left over in a frame, block letters made from the sans font, and a
   random number generator. */

#ifndef FX_H
#define FX_H

#include "gfx.h"

/* sin(2 pi i / 256) * 256, for i = 0..255 (fx_init) */
extern int fx_sin[256];
#define fx_cos(i) fx_sin[((i) + 64) & 255]
void fx_init(void);

/* The interrupt vector (address 4, a JMP rel16) to h; fx_orig is where it
   went before (rt/start.s's entry), for h to go on to what isn't its own */
extern unsigned fx_orig;
void fx_vector(void (*h)(void));
void fx_vector_off(void);

/* The CPU left over: units of a fixed piece of work done until the frame
   ends (fx_idle), and what a frame holds with nothing else to do (fx_calibrate,
   with no line interrupts about) */
extern int fx_idle_base;
int fx_idle(void);
void fx_calibrate(void);
/* the share of the frame used, in tenths of a percent, from units left */
int fx_used(int units);

/* block letters: str in the sans font, each of its pixels a cell x cell
   block at (x, y), bevelled (face, light, dark), gap pixels between */
int fx_logo(Surface *s, int x, int y, const char *str, int cell, int gap, unsigned face,
            unsigned light, unsigned dark);
int fx_logo_width(const char *str, int cell);

/* a colour scaled by level/15 */
unsigned fx_dim(int r, int g, int b, int level);

/* random numbers: 0 .. 2^15 - 1 */
extern unsigned fx_seed;
int fx_rand(void);

#endif
