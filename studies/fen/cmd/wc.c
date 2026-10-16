/* wc [-lwc] [file...]: lines, words and bytes */
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static int fl, fw, fc;
static unsigned tl, tw, tc;

static void show(unsigned l, unsigned w, unsigned c, const char *name)
{
    if (fl)
        printf("%7u", l);
    if (fw)
        printf("%8u", w);
    if (fc)
        printf("%8u", c);
    if (name)
        printf(" %s", name);
    printf("\n");
}

static int count(int fd, const char *name)
{
    static char buf[4096];
    unsigned l = 0, w = 0, c = 0;
    int n, in = 0, i;
    while ((n = read(fd, buf, sizeof buf)) > 0) {
        c += n;
        for (i = 0; i < n; i++) {
            int ch = buf[i];
            if (ch == '\n')
                l++;
            if (ch == ' ' || ch == '\t' || ch == '\n' || ch == '\r')
                in = 0;
            else if (!in) {
                in = 1;
                w++;
            }
        }
    }
    show(l, w, c, name);
    tl += l;
    tw += w;
    tc += c;
    return n < 0;
}

int main(int argc, char **argv)
{
    int i = 1, status = 0;
    if (argc > 1 && argv[1][0] == '-' && argv[1][1]) {
        fl = strchr(argv[1], 'l') != 0;
        fw = strchr(argv[1], 'w') != 0;
        fc = strchr(argv[1], 'c') != 0;
        i++;
    } else
        fl = fw = fc = 1;
    if (i == argc)
        return count(0, 0);
    for (; i < argc; i++) {
        int fd = open(argv[i], O_RDONLY);
        if (fd < 0) {
            fprintf(stderr, "wc: %s: %s\n", argv[i], strerror(errno));
            status = 1;
            continue;
        }
        status |= count(fd, argv[i]);
        close(fd);
    }
    if (argc - (fl && fw && fc ? 1 : 2) > 1)
        show(tl, tw, tc, "total");
    return status;
}
