/* The scenes on the host, built with gcc: the reference the machine's
   screens are checked against (heron graphics expected), and a quick way
   to look at them.

       host SCENE DEPTH [DIR]

   prints a line per mark: its name, count and the CRC-32 of the screen;
   with DIR, also writes the screen at each mark as DIR/NN-name.ppm. */

#include <stdio.h>
#include <stdlib.h>
#include "scenes.h"
#include "theme.h"

extern Surface screen;

static const char *dir;
static int marks;
static unsigned crctab[256];

static unsigned crc32(const unsigned char *p, int n)
{
    unsigned c = ~0u;
    int i, k;
    if (crctab[1] == 0)
        for (i = 0; i < 256; i++) {
            c = i;
            for (k = 0; k < 8; k++)
                c = c & 1 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            crctab[i] = c;
        }
    c = ~0u;
    for (i = 0; i < n; i++)
        c = crctab[(c ^ p[i]) & 255] ^ (c >> 8);
    return ~c;
}

static void dump(const char *name)
{
    char path[512];
    FILE *f;
    int x, y, r, g, b;
    snprintf(path, sizeof path, "%s/%02d-%s.ppm", dir, marks, name);
    f = fopen(path, "wb");
    if (!f) {
        perror(path);
        exit(1);
    }
    fprintf(f, "P6\n%d %d\n255\n", screen.w, screen.h);
    for (y = 0; y < screen.h; y++)
        for (x = 0; x < screen.w; x++) {
            theme_rgb(screen.depth, gfx_get(&screen, x, y), &r, &g, &b);
            fputc(r, f);
            fputc(g, f);
            fputc(b, f);
        }
    fclose(f);
}

void mark_n(const char *name, int count)
{
    printf("%s %d %08x\n", name, count, crc32(screen.bits, screen.pitch * screen.h));
    if (dir)
        dump(name);
    marks++;
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: host SCENE DEPTH [DIR]\n");
        return 2;
    }
    dir = argc > 3 ? argv[3] : 0;
    if (run_scene(argv[1], atoi(argv[2])) < 0) {
        fprintf(stderr, "no scene %s\n", argv[1]);
        return 2;
    }
    return 0;
}
