/* A first check of the runtime: M0, a palette, stripes, two frames. */
#include <stdio.h>
#include "video.h"

int main(void)
{
    unsigned *fb;
    int x, y, n;
    unsigned t0, t1;
    video_init(0, 0);
    fb = vram_alloc(640 * 480 / 2);
    for (n = 0; n < 16; n++)
        video_pal_rgb(n, n * 17, 255 - n * 17, (n * 50) & 255);
    for (y = 0; y < 480; y++)
        for (x = 0; x < 80; x++)
            fb[y * 80 + x] = 0x11111111u * (((x >> 2) + (y >> 5)) & 15);
    video_lines(0, 0, 480, fb, 320, 0);
    t0 = video_ticks();
    video_wait();
    t1 = video_ticks();
    printf("waited %u ticks\n", t1 - t0);
    rt_mark("drawn");
    rt_shot("hello");
    printf("@done\n");
    return 0;
}
