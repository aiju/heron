/* cp from to, or cp file... dir */
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>

static char buf[4096];

static int copy(const char *from, const char *to)
{
    int in = open(from, O_RDONLY), out, n;
    if (in < 0) {
        fprintf(stderr, "cp: %s: %s\n", from, strerror(errno));
        return 1;
    }
    out = open(to, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (out < 0) {
        fprintf(stderr, "cp: %s: %s\n", to, strerror(errno));
        close(in);
        return 1;
    }
    while ((n = read(in, buf, sizeof buf)) > 0)
        if (write(out, buf, n) != n) {
            fprintf(stderr, "cp: %s: %s\n", to, strerror(errno));
            break;
        }
    close(in);
    close(out);
    return n != 0;
}

int main(int argc, char **argv)
{
    struct stat st;
    int i, status = 0;
    if (argc < 3) {
        fprintf(stderr, "usage: cp from to | cp file... dir\n");
        return 2;
    }
    if (stat(argv[argc - 1], &st) == 0 && S_ISDIR(st.st_mode)) {
        for (i = 1; i < argc - 1; i++) {
            char to[512];
            const char *base = strrchr(argv[i], '/');
            snprintf(to, sizeof to, "%s/%s", argv[argc - 1], base ? base + 1 : argv[i]);
            status |= copy(argv[i], to);
        }
        return status;
    }
    if (argc != 3) {
        fprintf(stderr, "cp: %s isn't a directory\n", argv[argc - 1]);
        return 2;
    }
    return copy(argv[1], argv[2]);
}
