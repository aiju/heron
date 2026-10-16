/* date: the time, UTC */
#include <stdio.h>
#include <time.h>
int main(void)
{
    time_t t = time(0);
    fputs(ctime(&t), stdout);
    return 0;
}
