/* mv from to, or mv file... dir */
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
int main(int argc, char **argv)
{
    struct stat st;
    int i, status = 0;
    if (argc < 3) {
        fprintf(stderr, "usage: mv from to | mv file... dir\n");
        return 2;
    }
    if (stat(argv[argc - 1], &st) == 0 && S_ISDIR(st.st_mode)) {
        for (i = 1; i < argc - 1; i++) {
            char to[512];
            const char *base = strrchr(argv[i], '/');
            snprintf(to, sizeof to, "%s/%s", argv[argc - 1], base ? base + 1 : argv[i]);
            if (rename(argv[i], to) < 0) {
                fprintf(stderr, "mv: %s: %s\n", argv[i], strerror(errno));
                status = 1;
            }
        }
        return status;
    }
    if (rename(argv[1], argv[2]) < 0) {
        fprintf(stderr, "mv: %s: %s\n", argv[1], strerror(errno));
        return 1;
    }
    return 0;
}
