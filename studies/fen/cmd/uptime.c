/* uptime: how long since boot, and what the machine is */
#include <stdio.h>
#include <fen/sys.h>
int main(void)
{
    unsigned t = sysinfo(SI_TICKS) / 100;
    printf("up %u:%02u:%02u, a %u.%u MHz draft 2 Heron\n", t / 3600, t / 60 % 60, t % 60,
           sysinfo(SI_CLOCK) / 1000000, sysinfo(SI_CLOCK) / 100000 % 10);
    return 0;
}
