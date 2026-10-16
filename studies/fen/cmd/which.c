/* which program...: where $PATH finds it */
#include <stdio.h>
int __find_program(const char *file, char *out, unsigned size);
int main(int argc, char **argv)
{
    int i, status = 0;
    char path[256];
    for (i = 1; i < argc; i++)
        if (__find_program(argv[i], path, sizeof path) == 0)
            printf("%s\n", path);
        else
            status = 1;
    return status;
}
