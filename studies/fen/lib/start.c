/* The C library's start: from crt0's __start, with the startup block the
 * parent (or the kernel) left at START_BLOCK: the arguments, the
 * environment, the descriptors and the working directory. */

#include <stdlib.h>
#include <fen/sys.h>

extern int main(int argc, char **argv, char **envp);
void __fd_inherit(struct fd_desc *d, int n, const char *dir);
void __stdio_init(void);

char **environ;

void __libc_start(struct start_block *b)
{
    environ = b->envp;
    __fd_inherit(b->fds, b->nfds, (const char *)b + b->cwd);
    __stdio_init();
    exit(main(b->argc, b->argv, b->envp));
}
