/* kill pid...: end processes (a negative pid: a process group) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fen/spawn.h>
int main(int argc, char **argv)
{
    int i, status = 0;
    for (i = 1; i < argc; i++)
        if (kill(atoi(argv[i]), 128 + 15) < 0) {
            fprintf(stderr, "kill: %s: %s\n", argv[i], strerror(errno));
            status = 1;
        }
    return status;
}
