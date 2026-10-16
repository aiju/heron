/* ps: the processes */
#include <stdio.h>
#include <fen/sys.h>
int main(void)
{
    struct proc_info p[128];
    int n = proc_list(p, 128), i;
    printf("  PID  PPID THR  MEM   TIME  NAME\n");
    for (i = 0; i < n; i++)
        printf("%5d %5d %3d %3dK %3u.%02u  %s%s\n", p[i].pid, p[i].parent, p[i].threads,
               p[i].pages * 4, p[i].ticks / 100, p[i].ticks % 100, p[i].name,
               p[i].state == 2 ? " <zombie>" : "");
    return 0;
}
