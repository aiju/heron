/* Default palettes (video.h): 16 colours in every bank at 4 bits, a
   colour cube at 8, greys at 2, black and white at 1; the cursor's 253-255
   black, white and yellow. */

#include "video.h"

/* the 16: black, the dark and light primaries and secondaries, greys */
const unsigned char pal16[16][3] = {
    {0, 0, 0}, {0, 0, 170}, {0, 150, 0}, {0, 150, 160}, {170, 0, 0}, {160, 0, 160},
    {170, 100, 0}, {192, 192, 192}, {96, 96, 96}, {80, 110, 255}, {80, 230, 80},
    {80, 230, 230}, {255, 90, 90}, {255, 90, 255}, {255, 240, 80}, {255, 255, 255},
};

void video_default_palette(void)
{
    int n, k;
    if (vid.bpp == 8) {
        /* 0-15 the 16, 16-231 a 6 x 6 x 6 cube, 232-252 greys */
        static const unsigned char lv[6] = {0, 51, 102, 153, 204, 255};
        for (n = 0; n < 16; n++)
            video_pal_rgb(n, pal16[n][0], pal16[n][1], pal16[n][2]);
        for (n = 0; n < 216; n++)
            video_pal_rgb(16 + n, lv[n / 36], lv[n / 6 % 6], lv[n % 6]);
        for (n = 0; n < 21; n++)
            video_pal_rgb(232 + n, 8 + 12 * n, 8 + 12 * n, 8 + 12 * n);
    } else {
        int colours = 1 << vid.bpp;
        for (k = 0; k < 256; k += 16)
            for (n = 0; n < 16; n++) {
                int i = n & (colours - 1);
                if (vid.bpp == 4)
                    video_pal_rgb(k + n, pal16[i][0], pal16[i][1], pal16[i][2]);
                else if (vid.bpp == 2)
                    video_pal_rgb(k + n, 85 * i, 85 * i, 85 * i);
                else
                    video_pal_rgb(k + n, 255 * i, 255 * i, 255 * i);
            }
    }
    video_pal(253, rgb565(0, 0, 0));
    video_pal(254, rgb565(255, 255, 255));
    video_pal(255, rgb565(255, 230, 0));
}
