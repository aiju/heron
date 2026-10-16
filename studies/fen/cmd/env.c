/* env: the environment */
#include <stdio.h>
extern char **environ;
int main(void)
{
    char **e;
    for (e = environ; e && *e; e++)
        printf("%s\n", *e);
    return 0;
}
