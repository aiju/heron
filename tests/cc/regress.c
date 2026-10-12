/* Regression tests: reduced from programs the random tester (fuzz.py) found
   miscompiled. Flag reuse in a countdown loop whose block had an earlier
   compare dropped. */

#include <stdio.h>
static int sdiv(int a, int b) { return b == 0 || (a == -2147483647 - 1 && b == -1) ? a : a / b; }
static int smod(int a, int b) { return b == 0 || (a == -2147483647 - 1 && b == -1) ? a : a % b; }
static unsigned udiv(unsigned a, unsigned b) { return b ? a / b : a; }
static unsigned umod(unsigned a, unsigned b) { return b ? a % b : a; }
static unsigned hash;
static void mix(unsigned v) { hash = (hash ^ v) * 16777619u + 1; }
struct S { int a; short b; unsigned char c; unsigned d; };
int arr[16];
struct S s, sa[4];
int *p = arr + 4;
static int f0(int a0, int a1)
{
    return (((((a1) && (0)) ^ ((a1) & (127)))) ? (((((a1) > (a1))) < (umod(a1, 256)))) : (((a1) >> ((((a1) <= (8))) & 31))));
}
int main(void)
{
    int i0, i1, i2, i3, k;
    short v0 = -11;
    unsigned short v2 = -14;
    short v3 = -12;
    int v4 = 18;
    char v5 = 16;
    short v6 = 5;
    for (k = 0; k < 16; k++) arr[k] = k * 7 - 30;
    if (((unsigned)(((((udiv(*p, s.a)) - (s.d))) * (((f0(s.b, -9)) ^ (*p))))))) {
        if ((((~(arr[7]))) ^ ((!((!((s.c - s.b)))))))) {
            i2 = 5;
            while (i2-- > 0) {
                sa[(v6) & 3].a ^= ((((((((s.d) | (*p))) <= (((v3) | (v0))))) != ((((arr[2]) * (v2)) ^ smod(s.b, v3))))) - (p[0]));
                v0 &= (!(((((f0(v3, s.d)) - (((v3) == (v5))))) * (((unsigned)(p[2]))))));
            }
        }
    }
    if ((((arr[14] + *p)) - (((udiv(((unsigned short)(-2)), arr[0])) + (((((1994400855) * (arr[4]))) >= (((v4) == (p[1]))))))))) {
    }
    for (k = 0; k < 4; k++) { mix(sa[k].a); mix(sa[k].b); mix(sa[k].c); mix(sa[k].d); }
    printf("%u\n", hash);
    return 0;
}

