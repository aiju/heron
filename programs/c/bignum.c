/* bignum: exact factorials up to 52!, printing 10!, 20!, 30!, 40! and 52!.
   The number is kept in base 10^4 limbs, least significant first, the way
   one would without a 64-bit type. */
#include <stdio.h>

#define LIMBS 20
#define BASE 10000

static unsigned num[LIMBS];
static int len = 1;

static void multiply(unsigned k)
{
    unsigned carry = 0;
    int i;
    for (i = 0; i < len; i++) {
        unsigned v = num[i] * k + carry;
        num[i] = v % BASE;
        carry = v / BASE;
    }
    while (carry) {
        num[len++] = carry % BASE;
        carry /= BASE;
    }
}

int main(void)
{
    int n, i;
    num[0] = 1;
    for (n = 1; n <= 52; n++) {
        multiply(n);
        if ((n % 10 == 0 && n <= 40) || n == 52) {
            printf("%d! = %u", n, num[len - 1]);
            for (i = len - 2; i >= 0; i--)
                printf("%04u", num[i]);
            printf("\n");
        }
    }
    return 0;
}
