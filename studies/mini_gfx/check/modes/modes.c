/* The library's pixel formats against the video's (the simulator's
   decoder): in mode test_mode, with F1 if test_f1, palette entry n set to
   n, every pixel (x, y) of every seventh row set to (7x + 3y) mod 2^bpp with gfx_pixel. The
   harness compares the frame with that. */
#include <stdio.h>
#include "gfx.h"
#include "video.h"

int test_mode, test_f1;

int main(void)
{
    Surface s;
    unsigned *fb;
    int x, y, n, max;
    video_init(test_mode, test_f1 ? VC_F1 : 0);
    fb = vram_alloc(vid.words * 4 * vid.h);
    for (n = 0; n < 256; n++)
        video_pal(n, n);
    gfx_screen(&s, fb, vid.words);
    max = (1 << vid.bpp) - 1;
    for (y = 0; y < vid.h; y += 7)
        for (x = 0; x < vid.w; x++)
            gfx_pixel(&s, x, y, (7 * x + 3 * y) & max, ROP_COPY);
    video_lines(0, 0, vid.h, fb, vid.words * 4, 0);
    printf("format %d\n", s.fmt);
    rt_shot("modes");
    printf("@done\n");
    return 0;
}
