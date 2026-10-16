/* mkdir [-p] dir... */
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>

static int parents;

static int make(char *path)
{
    struct stat st;
    if (parents) {
        char *p;
        for (p = path + 1; *p; p++)
            if (*p == '/') {
                *p = 0;
                if (stat(path, &st) < 0)
                    mkdir(path, 0755);
                *p = '/';
            }
        if (stat(path, &st) == 0 && S_ISDIR(st.st_mode))
            return 0;
    }
    if (mkdir(path, 0755) < 0) {
        fprintf(stderr, "mkdir: %s: %s\n", path, strerror(errno));
        return 1;
    }
    return 0;
}

int main(int argc, char **argv)
{
    int i, status = 0;
    if (argc > 1 && !strcmp(argv[1], "-p")) {
        parents = 1;
        argv++;
        argc--;
    }
    for (i = 1; i < argc; i++)
        status |= make(argv[i]);
    return status;
}
