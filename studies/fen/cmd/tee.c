/* tee file: standard input to standard output and a file */
#include <stdio.h>
#include <string.h>
#include <unistd.h>
int main(int argc, char **argv)
{
    char buf[1024];
    int n, fd = -1;
    if (argc > 1 && (fd = open(argv[1], O_WRONLY | O_CREAT | O_TRUNC, 0644)) < 0) {
        fprintf(stderr, "tee: %s: %s\n", argv[1], strerror(errno));
        return 1;
    }
    while ((n = read(0, buf, sizeof buf)) > 0) {
        write(1, buf, n);
        if (fd >= 0)
            write(fd, buf, n);
    }
    return 0;
}
