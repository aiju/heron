/* dmesg: the kernel's log */
#include <unistd.h>
#include <fen/sys.h>
int main(void)
{
    static char buf[4096];
    int n = klog(buf, sizeof buf, 0);
    if (n > 0)
        write(1, buf, n);
    return 0;
}
