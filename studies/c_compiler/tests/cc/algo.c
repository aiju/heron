/* Classic algorithms: sieve, quicksort, n-queens, binary search, CRC. */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#define N 5000
char composite[N];
int arr[1000];

static void quicksort(int *a, int lo, int hi)
{
    while (lo < hi) {
        int p = a[(lo + hi) / 2], i = lo, j = hi;
        while (i <= j) {
            while (a[i] < p) i++;
            while (a[j] > p) j--;
            if (i <= j) {
                int t = a[i];
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

static int queens(int n, int row, unsigned cols, unsigned d1, unsigned d2)
{
    int count = 0, c;
    if (row == n)
        return 1;
    for (c = 0; c < n; c++) {
        unsigned bit = 1u << c;
        if ((cols & bit) || (d1 & (1u << (row + c))) || (d2 & (1u << (row - c + n))))
            continue;
        count += queens(n, row + 1, cols | bit, d1 | (1u << (row + c)), d2 | (1u << (row - c + n)));
    }
    return count;
}

static unsigned crc32(const unsigned char *p, int n)
{
    unsigned crc = 0xffffffff;
    int k;
    while (n--) {
        crc ^= *p++;
        for (k = 0; k < 8; k++)
            crc = crc & 1 ? (crc >> 1) ^ 0xedb88320 : crc >> 1;
    }
    return ~crc;
}

static int cmp_int(const void *a, const void *b)
{
    int x = *(const int *)a, y = *(const int *)b;
    return x < y ? -1 : x > y;
}

int main(void)
{
    int i, j, count = 0, last = 0;
    unsigned seed = 12345;
    for (i = 2; i < N; i++) {
        if (composite[i])
            continue;
        count++;
        last = i;
        for (j = i * i; j < N; j += i)
            composite[j] = 1;
    }
    printf("primes below %d: %d, last %d\n", N, count, last);
    for (i = 0; i < 1000; i++) {
        seed = seed * 1103515245 + 12345;
        arr[i] = (int)(seed >> 8) % 10000 - 5000;
    }
    quicksort(arr, 0, 999);
    for (i = 1; i < 1000; i++)
        if (arr[i - 1] > arr[i])
            printf("not sorted at %d\n", i);
    printf("sorted %d %d %d\n", arr[0], arr[500], arr[999]);
    for (i = 0; i < 1000; i++) {
        seed = seed * 1103515245 + 12345;
        arr[i] = (int)(seed >> 8) % 1000;
    }
    qsort(arr, 1000, sizeof(int), cmp_int);
    printf("qsort %d %d %d\n", arr[0], arr[500], arr[999]);
    {
        int key = arr[700];
        int *hit = bsearch(&key, arr, 1000, sizeof(int), cmp_int);
        printf("bsearch %d %d\n", hit != 0, hit ? *hit == key : 0);
    }
    for (i = 4; i <= 8; i++)
        printf("queens(%d) = %d\n", i, queens(i, 0, 0, 0, 0));
    printf("crc %08x\n", crc32((const unsigned char *)"The quick brown fox jumps over the lazy dog", 43));
    return 0;
}
