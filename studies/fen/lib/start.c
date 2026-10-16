/* The C library's start: from crt0's __start, with the startup block the
 * parent (or the kernel) left at START_BLOCK. */

#include <fen/sys.h>

extern int main(int argc, char **argv, char **envp);

char **environ;

void __libc_start(struct start_block *b)
{
    environ = b->envp;
    _exit(main(b->argc, b->argv, b->envp));
}
