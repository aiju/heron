/* arith: multiply and divide on 16-bit operands, 32-bit add, subtract and
   compare, and 32-bit division, on tables of edge cases. */
#include <stdio.h>

static const unsigned short pairs16[][2] = {
    {0, 0}, {0, 1}, {1, 1}, {1, 0xFFFF}, {0xFFFF, 0xFFFF}, {0x8000, 0xFFFF},
    {0x8000, 0x8000}, {0x8000, 1}, {0x7FFF, 0x7FFF}, {0x7FFF, 0x8000},
    {0xFFFF, 0x8000}, {0xFFFF, 0x8001}, {0xFFFE, 0xFFFF}, {1234, 567},
    {(unsigned short)-1234, 77}, {100, (unsigned short)-7}, {(unsigned short)-100, (unsigned short)-7},
    {(unsigned short)-100, 7}, {12345, 10}, {0x8001, 0x7FFF}, {40000, 3}, {0xFFFF, 0},
};

static const unsigned pairs32[][2] = {
    {0x0000FFFF, 0x00000001}, {0xFFFFFFFF, 0x00000001}, {0x80000000, 0xFFFFFFFF},
    {0x7FFFFFFF, 0x80000000}, {0x12345678, 0x12345678}, {0x00010000, 0x0000FFFF},
    {123456789, 987654321}, {0, 0xFFFFFFFF}, {0xFFFF0000, 0xFFFEFFFF}, {5, 0xFFFFFFFB},
};

static const unsigned divs[][2] = {
    {0xFFFFFFFF, 0xFFFF}, {0xFFFFFFFF, 1}, {123456789, 10}, {1000000, 7},
    {0x12345678, 0x1234}, {0, 5}, {0x80000000, 0x8000}, {0xFFFFFFFE, 0x8001},
    {3000000000u, 60000}, {1, 0xFFFF},
};

static char cmp(unsigned a, unsigned b) { return a < b ? '<' : a == b ? '=' : '>'; }
static char scmp(int a, int b) { return a < b ? '<' : a == b ? '=' : '>'; }

int main(void)
{
    int i;
    printf("16-bit multiply and divide\n");
    for (i = 0; i < (int)(sizeof pairs16 / sizeof pairs16[0]); i++) {
        unsigned a = pairs16[i][0], b = pairs16[i][1];
        short sa = a, sb = b;
        printf("a=%04X b=%04X\n", a, b);
        printf("  umul %08X  smul %d\n", a * b, sa * sb);
        if (b == 0) {
            printf("  divide by zero\n");
            continue;
        }
        printf("  udiv %u r %u  sdiv %d r %d\n", a / b, a % b, (short)(sa / sb), (short)(sa % sb));
    }
    printf("32-bit add, subtract, compare\n");
    for (i = 0; i < (int)(sizeof pairs32 / sizeof pairs32[0]); i++) {
        unsigned a = pairs32[i][0], b = pairs32[i][1];
        printf("%08X %08X  sum %08X  diff %08X  u%c s%c\n", a, b, a + b, a - b,
               cmp(a, b), scmp(a, b));
    }
    printf("32/16 divide\n");
    for (i = 0; i < (int)(sizeof divs / sizeof divs[0]); i++)
        printf("%u / %u = %u r %u\n", divs[i][0], divs[i][1], divs[i][0] / divs[i][1],
               divs[i][0] % divs[i][1]);
    return 0;
}
