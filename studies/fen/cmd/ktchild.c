/* ktchild: ktest's child, which calls its parent's server and exits 7. */
#include <fen/sys.h>
int main(void)
{
    msg_t m;
    int port = name_lookup("ktest");
    m.w[0] = 1;
    m.w[1] = 41;
    if (port > 0 && ipc_call(port, &m) == 42)
        return 7;
    return 1;
}
