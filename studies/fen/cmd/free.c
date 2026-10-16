/* free: the memory */
#include <stdio.h>
#include <fen/sys.h>
int main(void)
{
    unsigned ram = sysinfo(SI_RAM) >> 10, fr = sysinfo(SI_FREE) >> 10;
    printf("RAM %u KB, %u KB used, %u KB free\n", ram, ram - fr, fr);
    return 0;
}
