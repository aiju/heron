/* init: the first process. */

#include <fen/sys.h>
#include <string.h>

static void say(const char *s)
{
    kdebug(s, strlen(s));
}

int main(int argc, char **argv, char **envp)
{
    say("init: hello from user mode\n");
    return 0;
}
