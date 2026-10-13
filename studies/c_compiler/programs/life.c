/* life: Conway's Game of Life on a 32 x 16 torus, 20 generations. Prints the
   population of every generation and the final board. The same algorithm
   as the assembly versions: each grid has a one-cell border that is filled
   from the opposite edges before every generation, so the neighbours are
   at fixed offsets and need no wrap-around arithmetic. */
#include <stdio.h>
#include <string.h>

#define ROWS 16
#define COLS 32
#define W (COLS + 2)                    /* bytes per stored row */
#define GENS 20

static unsigned char grid_a[(ROWS + 2) * W], grid_b[(ROWS + 2) * W];

static const unsigned char start[][2] = {
    {0, 1}, {1, 2}, {2, 0}, {2, 1}, {2, 2},                 /* glider */
    {8, 23}, {8, 24}, {8, 25},                              /* blinker */
    {12, 7}, {12, 8}, {12, 9}, {13, 6}, {13, 7}, {13, 8},   /* toad */
    {3, 27}, {3, 28}, {4, 27}, {4, 28},                     /* block */
    {7, 31}, {7, 0}, {7, 1},                                /* blinker across the side seam */
    {15, 20}, {0, 20}, {1, 20},                             /* blinker across the top seam */
};

static void wrap(unsigned char *g)
{
    unsigned char *row;
    int r;
    for (r = 1, row = g + W; r <= ROWS; r++, row += W) {
        row[0] = row[COLS];
        row[COLS + 1] = row[1];
    }
    memcpy(g, g + ROWS * W, W);
    memcpy(g + (ROWS + 1) * W, g + W, W);
}

/* One generation from cur into next; returns the new population. */
static int step(const unsigned char *cur, unsigned char *next)
{
    int r, c, pop = 0;
    for (r = 1; r <= ROWS; r++) {
        const unsigned char *p = cur + r * W + 1;
        unsigned char *q = next + r * W + 1;
        for (c = 0; c < COLS; c++, p++) {
            int n = p[-W - 1] + p[-W] + p[-W + 1] + p[-1] + p[1]
                  + p[W - 1] + p[W] + p[W + 1];
            int alive = (n | *p) == 3;      /* 3 neighbours, or 2 and alive */
            *q++ = alive;
            pop += alive;
        }
    }
    return pop;
}

int main(void)
{
    unsigned char *cur = grid_a, *next = grid_b, *t;
    int g, r, c, pop = 0;
    for (g = 0; g < (int)(sizeof start / sizeof start[0]); g++) {
        grid_a[(start[g][0] + 1) * W + start[g][1] + 1] = 1;
        pop++;
    }
    printf("population:");
    for (g = 0; g < GENS; g++) {
        printf(" %d", pop);
        wrap(cur);
        pop = step(cur, next);
        t = cur;
        cur = next;
        next = t;
    }
    printf(" %d\n", pop);
    for (r = 1; r <= ROWS; r++) {
        for (c = 1; c <= COLS; c++)
            putchar(cur[r * W + c] ? '#' : '.');
        putchar('\n');
    }
    return 0;
}
