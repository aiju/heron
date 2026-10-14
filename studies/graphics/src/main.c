/* The scenes on the machine: the console input names the scene and the
   depth ("prims 3"). mark() is a HALT, in asm/ISA/mark.s. */

#include <stdio.h>
#include "scenes.h"

int main(void)
{
    char name[32];
    int c, n = 0, depth = 0;
    while ((c = getchar()) != EOF && c != ' ' && n < 31)
        name[n++] = c;
    name[n] = 0;
    while ((c = getchar()) >= '0' && c <= '9')
        depth = depth * 10 + c - '0';
    if (run_scene(name, depth) < 0)
        printf("no scene %s\n", name);
    return 0;
}
