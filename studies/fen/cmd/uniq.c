/* uniq [-c]: adjacent lines that repeat, once */
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv)
{
    char prev[1024], line[1024];
    int have = 0, count = 0, c = argc > 1 && !strcmp(argv[1], "-c");
    while (fgets(line, sizeof line, stdin)) {
        if (have && !strcmp(line, prev)) {
            count++;
            continue;
        }
        if (have) {
            if (c)
                printf("%7d ", count);
            fputs(prev, stdout);
        }
        strcpy(prev, line);
        have = 1;
        count = 1;
    }
    if (have) {
        if (c)
            printf("%7d ", count);
        fputs(prev, stdout);
    }
    return 0;
}
