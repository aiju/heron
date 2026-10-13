/* matmul: C = A * B for 8 x 8 matrices of random numbers -2048..2047
   (xorshift16 seeded with 2024: A's elements in row order, then B's), with
   32-bit sums. Prints row 3 of C, the trace, and checksums. */
#include <stdio.h>

#define N 8

static int a[N][N], b[N][N], c[N][N];
static unsigned x = 2024;

static int next(void)
{
    x ^= (x << 7) & 0xffff;
    x ^= x >> 9;
    x ^= (x << 8) & 0xffff;
    return (int)(x >> 4) - 2048;
}

int main(void)
{
    int i, j, k, trace = 0;
    unsigned total = 0, s1 = 0, s2 = 0;
    for (i = 0; i < N; i++)
        for (j = 0; j < N; j++)
            a[i][j] = next();
    for (i = 0; i < N; i++)
        for (j = 0; j < N; j++)
            b[i][j] = next();
    for (i = 0; i < N; i++)
        for (j = 0; j < N; j++) {
            int sum = 0;
            for (k = 0; k < N; k++)
                sum += a[i][k] * b[k][j];
            c[i][j] = sum;
        }
    printf("row 3:");
    for (j = 0; j < N; j++)
        printf(" %d", c[3][j]);
    for (i = 0; i < N; i++)
        trace += c[i][i];
    for (i = 0; i < N; i++)
        for (j = 0; j < N; j++) {
            unsigned v = c[i][j];
            total += v;
            s1 = (s1 + (v & 0xffff)) & 0xffff;
            s2 = (s2 + s1) & 0xffff;
            s1 = (s1 + (v >> 16)) & 0xffff;
            s2 = (s2 + s1) & 0xffff;
        }
    printf("\ntrace: %d\nchecksum: %08X %04X %04X\n", trace, total, s1, s2);
    return 0;
}
