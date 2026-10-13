/* sieve: Sieve of Eratosthenes over a byte array, primes below 8192.
   Prints how many there are and the last ten. Like the assembly versions,
   the flags are 0 or 1, so counting is adding them up, and the last ten are
   found by scanning down from the top. */
#include <stdio.h>
#include <string.h>

#define N 8192

static unsigned char flags[N];

int main(void)
{
    int i, j, count = 0, last[10], k;
    memset(flags, 1, N);
    flags[0] = flags[1] = 0;
    for (i = 2; i * i < N; i++)
        if (flags[i])
            for (j = i * i; j < N; j += i)
                flags[j] = 0;
    for (i = 0; i < N; i++)
        count += flags[i];
    printf("primes below 8192: %d\nlast ten:", count);
    for (i = N, k = 10; k > 0;)
        if (flags[--i])
            last[--k] = i;
    for (k = 0; k < 10; k++)
        printf(" %d", last[k]);
    printf("\n");
    return 0;
}
