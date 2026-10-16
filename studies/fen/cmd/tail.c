/* tail [-n N] [file]: the last N (10) lines */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv)
{
    int n = 10, i = 1, k = 0, j;
    FILE *f = stdin;
    char **lines;
    char line[1024];
    if (i + 1 < argc && !strcmp(argv[i], "-n")) {
        n = atoi(argv[i + 1]);
        i += 2;
    } else if (i < argc && argv[i][0] == '-' && argv[i][1]) {
        n = atoi(argv[i] + 1);
        i++;
    }
    if (n <= 0)
        return 0;
    if (i < argc && !(f = fopen(argv[i], "r"))) {
        fprintf(stderr, "tail: %s: %s\n", argv[i], strerror(errno));
        return 1;
    }
    lines = calloc(n, sizeof *lines);
    while (fgets(line, sizeof line, f)) {
        free(lines[k % n]);
        lines[k % n] = strdup(line);
        k++;
    }
    for (j = k > n ? k - n : 0; j < k; j++)
        fputs(lines[j % n], stdout);
    return 0;
}
