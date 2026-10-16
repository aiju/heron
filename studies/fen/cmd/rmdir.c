/* rmdir dir... */
#include <stdio.h>
#include <string.h>
#include <unistd.h>
int main(int argc, char **argv)
{
    int i, status = 0;
    for (i = 1; i < argc; i++)
        if (rmdir(argv[i]) < 0) {
            fprintf(stderr, "rmdir: %s: %s\n", argv[i], strerror(errno));
            status = 1;
        }
    return status;
}
