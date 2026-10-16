/* cat [file...]: files (or standard input) to standard output. */
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static char buf[4096];

static int copy(int fd)
{
    int n;
    while ((n = read(fd, buf, sizeof buf)) > 0)
        if (write(1, buf, n) != n)
            return 1;
    return n < 0;
}

int main(int argc, char **argv)
{
    int i, status = 0;
    if (argc == 1)
        return copy(0);
    for (i = 1; i < argc; i++) {
        int fd = strcmp(argv[i], "-") ? open(argv[i], O_RDONLY) : 0;
        if (fd < 0) {
            fprintf(stderr, "cat: %s: %s\n", argv[i], strerror(errno));
            status = 1;
            continue;
        }
        status |= copy(fd);
        if (fd)
            close(fd);
    }
    return status;
}
