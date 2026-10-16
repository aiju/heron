/* The division helpers the ARM EABI calls (Cortex-M0 has no divide). */

typedef unsigned long long u64;

static unsigned udivmod(unsigned n, unsigned d, unsigned *rem)
{
    unsigned q = 0, r = 0;
    int i;
    if (d == 0) {
        *rem = n;
        return 0xFFFFFFFFu;
    }
    for (i = 31; i >= 0; i--) {
        r = (r << 1) | ((n >> i) & 1);
        if (r >= d) {
            r -= d;
            q |= 1u << i;
        }
    }
    *rem = r;
    return q;
}

unsigned __aeabi_uidiv(unsigned n, unsigned d)
{
    unsigned r;
    return udivmod(n, d, &r);
}

u64 __aeabi_uidivmod(unsigned n, unsigned d)
{
    unsigned r, q = udivmod(n, d, &r);
    return ((u64)r << 32) | q;
}

int __aeabi_idiv(int n, int d)
{
    unsigned r, q = udivmod(n < 0 ? -(unsigned)n : (unsigned)n,
                            d < 0 ? -(unsigned)d : (unsigned)d, &r);
    return (n < 0) != (d < 0) ? -(int)q : (int)q;
}

u64 __aeabi_idivmod(int n, int d)
{
    unsigned r, q = udivmod(n < 0 ? -(unsigned)n : (unsigned)n,
                            d < 0 ? -(unsigned)d : (unsigned)d, &r);
    int qq = (n < 0) != (d < 0) ? -(int)q : (int)q;
    int rr = n < 0 ? -(int)r : (int)r;
    return ((u64)(unsigned)rr << 32) | (unsigned)qq;
}
