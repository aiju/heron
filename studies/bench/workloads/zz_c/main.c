#include <stdio.h>
#include "bench.h"
extern const unsigned char blob[];
extern unsigned blob_len;
int main(void) { bench_report("hash", bench_hash(BENCH_HASH0, blob, blob_len)); printf("N=%d\n", N); return 0; }
