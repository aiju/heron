/* sort: quicksort 256 random numbers, insertion-sort 64 more; check that both
   came out sorted and print a checksum and a few of the values. The numbers
   are xorshift16 outputs (seed 12345), compared unsigned. */
#include <stdio.h>

static unsigned rng = 12345;

static unsigned next(void)
{
    unsigned x = rng;
    x ^= (x << 7) & 0xffff;
    x ^= x >> 9;
    x ^= (x << 8) & 0xffff;
    rng = x;
    return x;
}

static void quicksort(unsigned *a, int lo, int hi)
{
    while (lo < hi) {
        unsigned pivot = a[(lo + hi) / 2];
        int i = lo, j = hi;
        while (i <= j) {
            while (a[i] < pivot)
                i++;
            while (a[j] > pivot)
                j--;
            if (i <= j) {
                unsigned t = a[i];
                a[i] = a[j];
                a[j] = t;
                i++;
                j--;
            }
        }
        if (j - lo < hi - i) {
            quicksort(a, lo, j);
            lo = i;
        } else {
            quicksort(a, i, hi);
            hi = j;
        }
    }
}

static void insertion_sort(unsigned *a, int n)
{
    int i, j;
    for (i = 1; i < n; i++) {
        unsigned v = a[i];
        for (j = i; j > 0 && a[j - 1] > v; j--)
            a[j] = a[j - 1];
        a[j] = v;
    }
}

static void report(const unsigned *a, int n)
{
    unsigned s1 = 0, s2 = 0;
    int i;
    for (i = 1; i < n; i++)
        if (a[i - 1] > a[i]) {
            printf("NOT sorted at %d\n", i);
            return;
        }
    for (i = 0; i < n; i++) {
        s1 = (s1 + a[i]) & 0xffff;
        s2 = (s2 + s1) & 0xffff;
    }
    printf("sorted, checksum %04X %04X\n", s1, s2);
}

static unsigned big[256], small[64];

int main(void)
{
    int i;
    for (i = 0; i < 256; i++)
        big[i] = next();
    for (i = 0; i < 64; i++)
        small[i] = next();
    quicksort(big, 0, 255);
    printf("quicksort 256: ");
    report(big, 256);
    printf("  a[0]=%u a[1]=%u a[127]=%u a[128]=%u a[254]=%u a[255]=%u\n",
           big[0], big[1], big[127], big[128], big[254], big[255]);
    insertion_sort(small, 64);
    printf("insertion sort 64: ");
    report(small, 64);
    printf("  a[0]=%u a[31]=%u a[63]=%u\n", small[0], small[31], small[63]);
    return 0;
}
