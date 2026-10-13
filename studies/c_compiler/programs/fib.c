/* fib: recursive fib(18), counting the calls, then fib(0) to fib(46)
   iteratively. */
#include <stdio.h>

static int calls;

static int fib(int n)
{
    calls++;
    if (n < 2)
        return n;
    return fib(n - 1) + fib(n - 2);
}

int main(void)
{
    unsigned a = 0, b = 1, t;
    int n, f;
    f = fib(18);
    printf("recursive fib(18) = %d (%d calls)\n", f, calls);
    for (n = 0; n < 47; n++) {
        printf("fib(%d) = %u\n", n, a);
        t = a + b;
        a = b;
        b = t;
    }
    return 0;
}
