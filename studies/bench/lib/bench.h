/* The benchmark's library for compiled workloads: the same functions as
 * lib/util.s, for the C compiler and for gcc on the host (the reference
 * build, with BENCH_HOST defined).
 *
 * A workload's input data is linked in by the harness from its
 * workload.py's data(): each name N there is
 *     extern const unsigned char N[];   extern unsigned N_len;
 * declared by the workload itself.
 */
#ifndef BENCH_H
#define BENCH_H

#define BENCH_HASH0 5381u

/* h = (h * 33) ^ byte for every byte: the results' checksum. */
unsigned bench_hash(unsigned h, const void *p, unsigned n);

/* Writes "label xxxxxxxx\n". */
void bench_report(const char *label, unsigned value);

#endif
