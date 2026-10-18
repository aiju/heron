/* Text alone, for profiling: lines of sans12 and of cells in M0. */
#include <stdio.h>
#include "gfx.h"
#include "video.h"
#include "perf.h"

int main(void)
{
    Surface s;
    unsigned *fb;
    int k;
    static const char line[] = "The quick brown fox jumps over the lazy dog, 0123456789 times.";
    video_init(0, 0);
    video_default_palette();
    font_init();
    fb = vram_alloc(vid.words * 4 * vid.h);
    gfx_screen(&s, fb, vid.words);
    video_lines(0, 0, vid.h, fb, vid.words * 4, 0);
    gfx_fill(&s, 0, 0, 640, 480, 15, ROP_COPY);
    perf_start();
    for (k = 0; k < 30; k++)
        font_draw(&s, font_sans, 5 + k % 7, 14 + 15 * k, line, 0, -1);
    perf_end("sans");
    perf_start();
    for (k = 0; k < 28; k++)
        font_cells(&s, 8 * (k % 3), 16 * k, line, sizeof line - 1, 1, 15);
    perf_end("cells");
    rt_shot("text");
    printf("@done\n");
    return 0;
}
