/* sieve: Sieve of Eratosthenes over a byte array, primes below 8192.
   Prints how many there are and the last ten. */
#include <stdio.h>

#define N 8192

static char flags[N];

int main(void)
{
    int i, j, count = 0, last[10], k;
    for (i = 2; i < N; i++)
        flags[i] = 1;
    for (i = 2; i * i < N; i++)
        if (flags[i])
            for (j = i * i; j < N; j += i)
                flags[j] = 0;
    for (i = 0; i < N; i++) {
        if (flags[i]) {
            last[count % 10] = i;
            count++;
        }
    }
    printf("primes below 8192: %d\nlast ten:", count);
    for (k = 0; k < 10; k++)
        printf(" %d", last[(count + k) % 10]);
    printf("\n");
    return 0;
}
