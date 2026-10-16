/* seq [first] last */
#include <stdio.h>
#include <stdlib.h>
int main(int argc, char **argv)
{
    int a = 1, b, i;
    if (argc < 2)
        return 1;
    b = atoi(argv[argc - 1]);
    if (argc > 2)
        a = atoi(argv[1]);
    for (i = a; i <= b; i++)
        printf("%d\n", i);
    return 0;
}
