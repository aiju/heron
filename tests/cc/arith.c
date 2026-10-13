/* Integer arithmetic, conversions and comparisons. */
#include <stdio.h>
#include <stdbool.h>

int vals[] = {0, 1, -1, 7, -7, 13, -13, 100, -100, 32767, -32768, 65535,
              2147483647, -2147483647 - 1, 123456789, -987654321};
unsigned uvals[] = {0, 1, 2, 3, 0x7fffffff, 0x80000000u, 0xffffffffu, 1000000007u, 65536, 255};
_Bool bools[] = {0, 1, 2, 256, -1};

static bool to_bool(int x) { return x; }
static int bool_arg(bool b) { return b; }

int main(void)
{
    int i, j, n = sizeof vals / sizeof vals[0];
    int nu = sizeof uvals / sizeof uvals[0];
    unsigned h = 0;
    for (i = 0; i < n; i++) {
        for (j = 0; j < n; j++) {
            int a = vals[i], b = vals[j];
            h = h * 31 + (unsigned)(a + b);
            h = h * 31 + (unsigned)(a - b);
            h = h * 31 + (unsigned)(a * b);
            if (b != 0 && !(a == -2147483647 - 1 && b == -1)) {
                h = h * 31 + (unsigned)(a / b);
                h = h * 31 + (unsigned)(a % b);
            }
            h = h * 31 + (a < b) + 2 * (a <= b) + 4 * (a > b) + 8 * (a >= b) + 16 * (a == b) + 32 * (a != b);
            h = h * 31 + (unsigned)(a & b) + (unsigned)(a | b) * 3 + (unsigned)(a ^ b) * 5;
            h = h * 31 + (unsigned)(a >> (j & 31)) + (unsigned)(a << (i & 31));
        }
        printf("after %d: %u\n", vals[i], h);
    }
    for (i = 0; i < nu; i++) {
        for (j = 0; j < nu; j++) {
            unsigned a = uvals[i], b = uvals[j];
            h = h * 33 + a + b;
            h = h * 33 + a * b;
            h = h * 33 + a - b;
            if (b) {
                h = h * 33 + a / b;
                h = h * 33 + a % b;
            }
            h = h * 33 + (a < b) + 2 * (a <= b) + 4 * (a > b) + 8 * (a >= b);
            h = h * 33 + (a >> (j & 31));
        }
        printf("u %u: %u\n", uvals[i], h);
    }
    /* division by constants */
    for (i = -20; i <= 20; i++) {
        printf("%d: %d %d %d %d %d %d %d %d\n", i, i / 2, i % 2, i / 4, i % 4, i / 8, i % 8, i / 3, i % 7);
        printf("   %u %u %u\n", (unsigned)i / 16, (unsigned)i % 16, (unsigned)i / 10);
    }
    /* conversions */
    for (i = -300; i <= 300; i += 37) {
        signed char sc = i;
        unsigned char uc = i;
        short s = i * 200;
        unsigned short us = i * 200;
        char c = i;
        printf("%d: %d %d %d %d %d\n", i, sc, uc, s, us, c);
    }
    {
        int x = 0x12345678;
        printf("%x %x %x %x\n", (unsigned char)x, (signed char)(x >> 3), (unsigned short)(x >> 4), (short)(x << 4));
        printf("%d %d\n", -7 >> 1, (int)(-7u >> 1));
        printf("%d\n", (int)sizeof(int) + (int)sizeof(short) * 10 + (int)sizeof(char) * 100);
    }
    /* conversions to _Bool: anything but 0 becomes 1 */
    {
        static bool sb = 512;
        unsigned char uc;
        int *p = 0;
        bool b, c;
        printf("%d %d %d %d %d %d\n", bools[0], bools[1], bools[2], bools[3], bools[4], sb);
        for (i = 0; i < n; i++) {
            b = vals[i] & 0xff00;
            c = (bool)((unsigned)vals[i] << 16);
            uc = vals[i];
            printf("%d: %d %d %d %d %d %d\n", vals[i], b, c, (bool)uc, to_bool(vals[i] & 0x100),
                   bool_arg(vals[i] >> 8), b + c);
        }
        b = p;
        c = &uc;
        printf("%d %d", b, c);
        b = 0;
        b += 4;
        c--;
        printf(" %d %d", b, c);
        b++;
        c--;
        printf(" %d %d %d\n", b, c, (int)sizeof(bool));
    }
    return 0;
}
