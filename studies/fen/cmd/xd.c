/* xd [file]: a hex dump */
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv)
{
    FILE *f = stdin;
    unsigned char b[16];
    unsigned off = 0;
    int n, i;
    if (argc > 1 && !(f = fopen(argv[1], "r"))) {
        fprintf(stderr, "xd: %s: %s\n", argv[1], strerror(errno));
        return 1;
    }
    while ((n = fread(b, 1, 16, f)) > 0) {
        printf("%06x ", off);
        for (i = 0; i < 16; i++)
            if (i < n)
                printf(" %02x", b[i]);
            else
                printf("   ");
        printf("  ");
        for (i = 0; i < n; i++)
            putchar(b[i] >= 32 && b[i] < 127 ? b[i] : '.');
        printf("\n");
        off += n;
    }
    return 0;
}
