/* sleep seconds (tenths too: sleep 0.5) */
#include <stdlib.h>
#include <unistd.h>
#include <fen/sys.h>
int main(int argc, char **argv)
{
    char *dot;
    unsigned s, tenths = 0;
    if (argc < 2)
        return 1;
    s = strtoul(argv[1], &dot, 10);
    if (*dot == '.' && dot[1] >= '0' && dot[1] <= '9')
        tenths = dot[1] - '0';
    sleep(s);
    if (tenths)
        sleep_us(tenths * 100000);
    return 0;
}
