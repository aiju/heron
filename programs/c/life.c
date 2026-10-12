/* life: Conway's Game of Life on a 32 x 16 torus, 20 generations. Prints the
   population of every generation and the final board. */
#include <stdio.h>

#define ROWS 16
#define COLS 32
#define GENS 20

static unsigned char grid[ROWS][COLS], next[ROWS][COLS];

static const unsigned char start[][2] = {
    {0, 1}, {1, 2}, {2, 0}, {2, 1}, {2, 2},                 /* glider */
    {8, 23}, {8, 24}, {8, 25},                              /* blinker */
    {12, 7}, {12, 8}, {12, 9}, {13, 6}, {13, 7}, {13, 8},   /* toad */
    {3, 27}, {3, 28}, {4, 27}, {4, 28},                     /* block */
    {7, 31}, {7, 0}, {7, 1},                                /* blinker across the side seam */
    {15, 20}, {0, 20}, {1, 20},                             /* blinker across the top seam */
};

static int population(void)
{
    int r, c, n = 0;
    for (r = 0; r < ROWS; r++)
        for (c = 0; c < COLS; c++)
            n += grid[r][c];
    return n;
}

static void step(void)
{
    int r, c;
    for (r = 0; r < ROWS; r++) {
        int up = (r + ROWS - 1) % ROWS, down = (r + 1) % ROWS;
        for (c = 0; c < COLS; c++) {
            int left = (c + COLS - 1) % COLS, right = (c + 1) % COLS;
            int n = grid[up][left] + grid[up][c] + grid[up][right]
                  + grid[r][left] + grid[r][right]
                  + grid[down][left] + grid[down][c] + grid[down][right];
            next[r][c] = n == 3 || (n == 2 && grid[r][c]);
        }
    }
    for (r = 0; r < ROWS; r++)
        for (c = 0; c < COLS; c++)
            grid[r][c] = next[r][c];
}

int main(void)
{
    int g, r, c;
    for (g = 0; g < (int)(sizeof start / sizeof start[0]); g++)
        grid[start[g][0]][start[g][1]] = 1;
    printf("population:");
    for (g = 0; g < GENS; g++) {
        printf(" %d", population());
        step();
    }
    printf(" %d\n", population());
    for (r = 0; r < ROWS; r++) {
        for (c = 0; c < COLS; c++)
            putchar(grid[r][c] ? '#' : '.');
        putchar('\n');
    }
    return 0;
}
