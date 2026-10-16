/* sort [-rn] [file]: lines in order */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int rev, num;
static int cmp(const void *a, const void *b)
{
    const char *x = *(char *const *)a, *y = *(char *const *)b;
    int c = num ? atoi(x) - atoi(y) : strcmp(x, y);
    return rev ? -c : c;
}
int main(int argc, char **argv)
{
    char **lines = 0, line[1024];
    int n = 0, cap = 0, i = 1;
    FILE *f = stdin;
    while (i < argc && argv[i][0] == '-') {
        rev |= strchr(argv[i], 'r') != 0;
        num |= strchr(argv[i], 'n') != 0;
        i++;
    }
    if (i < argc && !(f = fopen(argv[i], "r"))) {
        fprintf(stderr, "sort: %s: %s\n", argv[i], strerror(errno));
        return 1;
    }
    while (fgets(line, sizeof line, f)) {
        if (n == cap) {
            cap = cap ? 2 * cap : 256;
            lines = realloc(lines, cap * sizeof *lines);
        }
        lines[n++] = strdup(line);
    }
    qsort(lines, n, sizeof *lines, cmp);
    for (i = 0; i < n; i++)
        fputs(lines[i], stdout);
    return 0;
}
