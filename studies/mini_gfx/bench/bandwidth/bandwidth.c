/* The video's bandwidth under load (RFC 0042, 9): in mode bw_mode, a
   workload (bw_work) for 30 frames, while the harness counts the shifter
   loads that found no word (B0, B2) or the ticks stolen (B1). Workloads:
   0 idle (HALT), 1 screen copies (the library, the variant's kernels),
   2 compiled C arithmetic with multiplies and divides, 3 shifted copies,
   4 palette writes (I/O accesses), 5 a loop of taken branches (each
   decode after one fetches its parcel on demand: the longest cycles). Prints the work done, so B1's stolen
   time shows as less of it. */

#include <stdio.h>
#include "gfx.h"
#include "video.h"
#include "perf.h"

int bw_mode = 2, bw_work = 1;

void spin(int n);

static unsigned arith(unsigned n)
{
    unsigned a = 12345, k;
    for (k = 0; k < n; k++)
        a = a * 1103515245u / (k | 1) + k;
    return a;
}

int main(void)
{
    Surface s, src;
    unsigned *fb, *buf, work = 0, f0;
    int k;
    video_init(bw_mode, 0);
    video_default_palette();
    fb = vram_alloc(vid.words * 4 * vid.h);
    buf = vram_alloc(vid.words * 4 * 128);
    gfx_screen(&s, fb, vid.words);
    gfx_init(&src, buf, vid.w, 128, vid.words, s.fmt);
    video_lines(0, 0, vid.h, fb, vid.words * 4, 0);
    for (k = 0; k < 16; k++)
        gfx_fill(&src, k * vid.w / 16, 0, (k + 1) * vid.w / 16, 128, k, ROP_COPY);
    video_wait();
    f0 = rt_frames;
    printf("@mark start 0\n");
    while (rt_frames - f0 < 30) {
        switch (bw_work) {
        case 0:
            video_wait();
            break;
        case 1:
            gfx_blit(&s, 0, (work * 37) % (vid.h - 128), &src, 0, 0, vid.w, 128, ROP_COPY);
            break;
        case 2:
            arith(200);
            break;
        case 3:
            gfx_blit(&s, 3, (work * 37) % (vid.h - 128), &src, 0, 0, vid.w - 3, 128, ROP_COPY);
            break;
        case 4:
            for (k = 0; k < 256; k++)
                VID_PAL(k) = k * 0x0841;
            break;
        default:
            spin(1000);
            break;
        }
        work++;
    }
    printf("@mark end 0\n");
    perf_value("work", work);
    printf("@done\n");
    return 0;
}
