/* Calls: many arguments, recursion, variadic functions, callee-saved registers. */
#include <stdio.h>
#include <stdarg.h>

static int many(int a, int b, int c, int d, int e, int f, int g, int h)
{
    return a + 2 * b + 3 * c + 4 * d + 5 * e + 6 * f + 7 * g + 8 * h;
}

static int sum(int n, ...)
{
    va_list ap;
    int s = 0;
    va_start(ap, n);
    while (n-- > 0)
        s += va_arg(ap, int);
    va_end(ap);
    return s;
}

static int ack(int m, int n)
{
    if (m == 0)
        return n + 1;
    if (n == 0)
        return ack(m - 1, 1);
    return ack(m - 1, ack(m, n - 1));
}

static void hanoi(int n, int from, int to, int via, int *moves)
{
    if (n == 0)
        return;
    hanoi(n - 1, from, via, to, moves);
    (*moves)++;
    hanoi(n - 1, via, to, from, moves);
}

static int keep(int x)
{
    /* values live across calls */
    int a = x * 3, b = x + 7, c = x ^ 0x55, d = x - 2, e = x * x;
    int r = sum(3, a, b, c);
    r += sum(2, d, e);
    return r + a + b + c + d + e;
}

static unsigned gcd(unsigned a, unsigned b)
{
    while (b) {
        unsigned t = a % b;
        a = b;
        b = t;
    }
    return a;
}

static int isprime(int n)
{
    int d;
    if (n < 2)
        return 0;
    for (d = 2; d * d <= n; d++)
        if (n % d == 0)
            return 0;
    return 1;
}

int main(void)
{
    int i, moves = 0, np = 0;
    printf("many %d\n", many(1, 2, 3, 4, 5, 6, 7, 8));
    printf("many %d\n", many(-1, 20, -300, 4000, -5, 60, -700, 8000));
    printf("sum %d %d %d\n", sum(0), sum(1, 42), sum(5, 1, 2, 3, 4, 5));
    printf("ack %d %d\n", ack(2, 3), ack(3, 3));
    hanoi(10, 1, 3, 2, &moves);
    printf("hanoi %d\n", moves);
    for (i = 0; i < 5; i++)
        printf("keep(%d) = %d\n", i, keep(i));
    printf("gcd %u %u\n", gcd(1071, 462), gcd(4294967295u, 65535));
    for (i = 0; i < 2000; i++)
        np += isprime(i);
    printf("primes %d\n", np);
    printf("%5d|%-5d|%05d|%x|%X|%o|%c|%s|%10s|%-6s|%%\n", 42, 42, 42, 0xbeef, 0xbeef, 8, 'z', "str", "right", "left");
    printf("%+d % d %u %d\n", 5, 5, 4000000000u, -2147483647 - 1);
    return 0;
}
