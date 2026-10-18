/* Timing (perf.h). */

#include <stdio.h>
#include "perf.h"
#include "video.h"

static unsigned t0, f0, fsum, fmax, fn;

void perf_start(void)
{
    t0 = video_ticks();
}

unsigned perf_end(const char *name)
{
    unsigned t = video_ticks() - t0;
    printf("@perf %s %u\n", name, t);
    return t;
}

void perf_value(const char *name, unsigned v)
{
    printf("@perf %s %u\n", name, v);
}

void perf_frame_begin(void)
{
    f0 = video_ticks();
}

void perf_frame_end(void)
{
    unsigned t = video_ticks() - f0;
    fsum += t;
    if (t > fmax)
        fmax = t;
    fn++;
}

void perf_frames(const char *name)
{
    printf("@perf %s %u %u %u\n", name, fn ? fsum / fn : 0, fmax, fn);
    fsum = fmax = fn = 0;
}
