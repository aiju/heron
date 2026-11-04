/* The benchmark's library for compiled workloads; see bench.h. */
#include <stdio.h>
#include "bench.h"

unsigned bench_hash(unsigned h, const void *p, unsigned n)
{
    const unsigned char *s = p;
    while (n--)
        h = ((h << 5) + h) ^ *s++;
    return h;
}

void bench_report(const char *label, unsigned value)
{
    printf("%s %08x\n", label, value);
}
