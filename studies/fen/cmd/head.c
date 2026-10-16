/* head [-n N] [file]: the first N (10) lines */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv)
{
    int n = 10, c;
    FILE *f = stdin;
    char line[1024];
    int i = 1;
    if (i + 1 < argc && !strcmp(argv[i], "-n")) {
        n = atoi(argv[i + 1]);
        i += 2;
    } else if (i < argc && argv[i][0] == '-' && argv[i][1]) {
        n = atoi(argv[i] + 1);
        i++;
    }
    if (i < argc && !(f = fopen(argv[i], "r"))) {
        fprintf(stderr, "head: %s: %s\n", argv[i], strerror(errno));
        return 1;
    }
    for (c = 0; c < n && fgets(line, sizeof line, f); c++)
        fputs(line, stdout);
    return 0;
}
