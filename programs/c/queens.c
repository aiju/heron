/* queens: count the solutions of the 8 queens problem by backtracking with
   bitmasks, and print the first solution found (lowest column first). */
#include <stdio.h>

#define N 8

static int count;
static int cols[N], first[N];

static void solve(int row, unsigned free, unsigned left, unsigned right)
{
    int c;
    if (row == N) {
        if (count++ == 0) {
            for (c = 0; c < N; c++)
                first[c] = cols[c];
        }
        return;
    }
    for (c = 0; c < N; c++) {
        unsigned bit = 1u << c;
        if ((free & bit) && !(left & bit) && !(right & bit)) {
            cols[row] = c;
            solve(row + 1, free & ~bit, (left | bit) << 1, (right | bit) >> 1);
        }
    }
}

int main(void)
{
    int r, c;
    solve(0, (1u << N) - 1, 0, 0);
    printf("solutions: %d\nfirst:", count);
    for (r = 0; r < N; r++)
        printf(" %d", first[r] + 1);
    printf("\n");
    for (r = 0; r < N; r++) {
        for (c = 0; c < N; c++)
            printf(c ? " %c" : "%c", c == first[r] ? 'Q' : '.');
        printf("\n");
    }
    return 0;
}
