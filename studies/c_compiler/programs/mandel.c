/* mandel: ASCII Mandelbrot set, 48 x 20 characters, at most 16 iterations
   per point, in 8.8 fixed point (1.0 = 256). */
#include <stdio.h>

#define W 48
#define H 20
#define MAXIT 16

int main(void)
{
    static const char palette[] = " .,,::;;--==++*#@";
    int row, col;
    for (row = 0; row < H; row++) {
        int cy = -295 + row * 31;             /* -(31 * 19) / 2, rounded down */
        for (col = 0; col < W; col++) {
            int cx = -563 + col * 16;
            int x = 0, y = 0, it;
            for (it = 0; it < MAXIT; it++) {
                int xx, yy;
                if (x >= 512 || x <= -512 || y >= 512 || y <= -512)
                    break;
                xx = (x * x) >> 8;
                yy = (y * y) >> 8;
                if (xx + yy > 1024)
                    break;
                y = 2 * ((x * y) >> 8) + cy;
                x = xx - yy + cx;
            }
            putchar(palette[it]);
        }
        putchar('\n');
    }
    return 0;
}
