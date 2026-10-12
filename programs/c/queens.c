/* queens: count the solutions of the 8 queens problem by backtracking with
   bitmasks (bit i = column i), and print the first solution found, which is
   the first in lowest-column-first order. The same algorithm as the
   assembly versions: the free squares of a row are a mask, and x & -x picks
   the lowest one. */
#include <stdio.h>
#include <string.h>

#define N 8

static int count;
static unsigned cur[N], first[N];

static void solve(unsigned *row, unsigned free, unsigned left, unsigned right)
{
    unsigned squares;
    if (free == 0) {                    /* every column used: a solution */
        if (++count == 1)
            memcpy(first, cur, sizeof cur);
        return;
    }
    squares = free & ~left & ~right;
    while (squares) {
        unsigned bit = squares & -squares;
        squares &= ~bit;
        *row = bit;
        solve(row + 1, free & ~bit, (left | bit) << 1, (right | bit) >> 1);
    }
}

int main(void)
{
    int r, c;
    solve(cur, (1u << N) - 1, 0, 0);
    printf("solutions: %d\nfirst:", count);
    for (r = 0; r < N; r++) {
        for (c = 0; !(first[r] & 1u << c); c++)
            ;
        printf(" %d", c + 1);
    }
    printf("\n");
    for (r = 0; r < N; r++) {
        for (c = 0; c < N; c++)
            printf(c ? " %c" : "%c", first[r] & 1u << c ? 'Q' : '.');
        printf("\n");
    }
    return 0;
}
