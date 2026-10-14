/* Integers: SmallInts, and big integers when a result doesn't fit in 31
   bits. Every result that fits is a SmallInt again, so a number has one
   representation.

   A big integer is a byte object of class Int: a sign byte, padding, then
   16-bit limbs, least significant first, with no leading zero limb. 16-bit
   limbs because the C compiler has no 64-bit type: a limb product fits in
   32 bits. (The hardware's MULU and DIVUL would take 32-bit limbs.) */

#include "egret.h"

typedef unsigned short Limb;

#define BIG_HDR 4                         /* sign byte and padding */
#define NLIMBS(b) ((SIZE(b) - BIG_HDR) / 2)
#define LIMBS(b) ((Limb *)(BYTES(b) + BIG_HDR))
#define SIGN(b) (BYTES(b)[0])             /* 1 if negative */

int is_bigint(Value v) { return !IS_INT(v) && CLASSW(v) == cls_Int; }

/* A number unpacked for arithmetic: sign and magnitude in C memory. */
#define MAXL 1100
typedef struct {
    int neg;
    unsigned n;
    Limb d[MAXL];
} Num;

static Num na, nb, nr, nq;

static void unpack(Value v, Num *x)
{
    if (IS_INT(v)) {
        SValue i = INT(v);
        unsigned u;
        x->neg = i < 0;
        u = i < 0 ? 0u - (unsigned)i : (unsigned)i;
        x->n = 0;
        while (u) {
            x->d[x->n++] = u & 0xFFFF;
            u >>= 16;
        }
    } else {
        x->neg = SIGN(v);
        x->n = NLIMBS(v);
        memcpy(x->d, LIMBS(v), 2 * x->n);
    }
}

static void trim(Num *x)
{
    while (x->n && x->d[x->n - 1] == 0)
        x->n--;
    if (x->n == 0)
        x->neg = 0;
}

static Value pack(Num *x)
{
    Value b;
    trim(x);
    if (x->n <= 2) {
        unsigned u = x->n ? x->d[0] : 0;
        if (x->n == 2)
            u |= (unsigned)x->d[1] << 16;
        if (!x->neg && u <= INT_MAX31)
            return MKINT(u);
        if (x->neg && u <= 0x40000000u)
            return MKINT(0 - u);
    }
    if (x->n > MAXL - 2)
        return 0;
    b = alloc_bytes(cls_Int, BIG_HDR + 2 * x->n);
    SIGN(b) = x->neg;
    memcpy(LIMBS(b), x->d, 2 * x->n);
    return b;
}

static int mag_cmp(Num *a, Num *b)
{
    unsigned i;
    if (a->n != b->n)
        return a->n < b->n ? -1 : 1;
    for (i = a->n; i-- > 0;)
        if (a->d[i] != b->d[i])
            return a->d[i] < b->d[i] ? -1 : 1;
    return 0;
}

static void mag_add(Num *a, Num *b, Num *r)
{
    unsigned i, carry = 0, n = a->n > b->n ? a->n : b->n;
    for (i = 0; i < n; i++) {
        unsigned s = carry + (i < a->n ? a->d[i] : 0) + (i < b->n ? b->d[i] : 0);
        r->d[i] = s & 0xFFFF;
        carry = s >> 16;
    }
    r->d[n] = carry;
    r->n = n + 1;
}

/* |a| >= |b| */
static void mag_sub(Num *a, Num *b, Num *r)
{
    unsigned i;
    int borrow = 0;
    for (i = 0; i < a->n; i++) {
        int s = (int)a->d[i] - (i < b->n ? b->d[i] : 0) - borrow;
        borrow = s < 0;
        r->d[i] = s & 0xFFFF;
    }
    r->n = a->n;
}

static void add_signed(Num *a, Num *b, Num *r)
{
    if (a->neg == b->neg) {
        mag_add(a, b, r);
        r->neg = a->neg;
    } else if (mag_cmp(a, b) >= 0) {
        mag_sub(a, b, r);
        r->neg = a->neg;
    } else {
        mag_sub(b, a, r);
        r->neg = b->neg;
    }
}

static int too_big(Num *a, Num *b) { return a->n + b->n + 2 > MAXL; }

Value int_add(Value a, Value b)
{
    unpack(a, &na);
    unpack(b, &nb);
    if (too_big(&na, &nb))
        return 0;
    add_signed(&na, &nb, &nr);
    return pack(&nr);
}

Value int_sub(Value a, Value b)
{
    unpack(a, &na);
    unpack(b, &nb);
    if (too_big(&na, &nb))
        return 0;
    nb.neg = !nb.neg && nb.n;
    add_signed(&na, &nb, &nr);
    return pack(&nr);
}

Value int_neg(Value a)
{
    unpack(a, &na);
    na.neg = !na.neg && na.n;
    return pack(&na);
}

Value int_mul(Value a, Value b)
{
    unsigned i, j;
    unpack(a, &na);
    unpack(b, &nb);
    if (too_big(&na, &nb))
        return 0;
    nr.n = na.n + nb.n;
    memset(nr.d, 0, 2 * nr.n);
    for (i = 0; i < na.n; i++) {
        unsigned carry = 0, x = na.d[i];
        if (x == 0)
            continue;
        for (j = 0; j < nb.n; j++) {
            unsigned t = x * nb.d[j] + nr.d[i + j] + carry;
            nr.d[i + j] = t & 0xFFFF;
            carry = t >> 16;
        }
        for (j = i + nb.n; carry; j++) {
            unsigned t = nr.d[j] + carry;
            nr.d[j] = t & 0xFFFF;
            carry = t >> 16;
        }
    }
    nr.neg = na.neg != nb.neg;
    return pack(&nr);
}

/* nq = |na| / |nb|, nr = |na| % |nb|: shift-and-subtract by limbs for a
   one-limb divisor, bit by bit otherwise (slow, but rare and simple). */
static void mag_divmod(void)
{
    unsigned i;
    if (nb.n == 1) {
        unsigned rem = 0, d = nb.d[0];
        for (i = na.n; i-- > 0;) {
            unsigned cur = (rem << 16) | na.d[i];
            nq.d[i] = cur / d;
            rem = cur % d;
        }
        nq.n = na.n;
        nr.d[0] = rem;
        nr.n = 1;
        return;
    }
    nq.n = na.n;
    memset(nq.d, 0, 2 * nq.n);
    nr.n = 0;
    for (i = na.n * 16; i-- > 0;) {
        /* nr = nr * 2 + bit i of na */
        unsigned k, carry = (na.d[i / 16] >> (i % 16)) & 1;
        for (k = 0; k < nr.n; k++) {
            unsigned t = ((unsigned)nr.d[k] << 1) | carry;
            nr.d[k] = t & 0xFFFF;
            carry = t >> 16;
        }
        if (carry)
            nr.d[nr.n++] = carry;
        if (mag_cmp(&nr, &nb) >= 0) {
            Num *t = &nr;
            mag_sub(t, &nb, t);
            trim(t);
            nq.d[i / 16] |= 1 << (i % 16);
        }
    }
}

/* Floor division and modulo, as in Python: the remainder has the sign of
   the divisor. 0 if b is zero. */
Value int_divmod(Value a, Value b, int want_mod)
{
    int neg_a, neg_b;
    unpack(a, &na);
    unpack(b, &nb);
    if (nb.n == 0)
        return 0;
    neg_a = na.neg;
    neg_b = nb.neg;
    mag_divmod();
    trim(&nr);
    trim(&nq);
    nq.neg = neg_a != neg_b;
    nr.neg = neg_a;
    if (nr.n && neg_a != neg_b) {
        /* floor: q -= 1, r += b */
        Num one;
        one.neg = 0;
        one.n = 1;
        one.d[0] = 1;
        if (want_mod) {
            Num t = nr;
            nb.neg = neg_b;
            add_signed(&t, &nb, &nr);
        } else {
            Num t = nq;
            one.neg = 1;
            add_signed(&t, &one, &nq);
        }
    }
    return pack(want_mod ? &nr : &nq);
}

int int_cmp(Value a, Value b)
{
    int c;
    if (IS_INT(a) && IS_INT(b))
        return INT(a) < INT(b) ? -1 : INT(a) > INT(b);
    unpack(a, &na);
    unpack(b, &nb);
    if (na.neg != nb.neg)
        return na.neg ? -1 : 1;
    c = mag_cmp(&na, &nb);
    return na.neg ? -c : c;
}

Value int_pow(Value a, Value b)
{
    Value r = MKINT(1);
    SValue e;
    if (!IS_INT(b) || INT(b) < 0)
        return 0;
    e = INT(b);
    push_root(&a);
    push_root(&r);
    while (e) {
        if (e & 1) {
            r = int_mul(r, a);
            if (!r)
                break;
        }
        e >>= 1;
        if (e) {
            a = int_mul(a, a);
            if (!a) {
                r = 0;
                break;
            }
        }
    }
    pop_roots(2);
    return r;
}

/* Decimal (or another base) digits, by repeated division by a power of
   the base that fits a limb. */
Value int_to_s(Value a, int base)
{
    static char buf[MAXL * 5 + 4];
    char *p = buf + sizeof buf;
    unsigned chunk = base == 10 ? 10000 : base == 16 ? 0x1000 : base, digits;
    int neg;
    if (IS_INT(a)) {
        SValue i = INT(a);
        unsigned u = i < 0 ? 0u - (unsigned)i : (unsigned)i;
        neg = i < 0;
        do {
            unsigned d = u % base;
            *--p = d < 10 ? '0' + d : 'a' + d - 10;
            u /= base;
        } while (u);
    } else {
        unsigned i;
        digits = base == 10 ? 4 : base == 16 ? 3 : 1;
        unpack(a, &na);
        neg = na.neg;
        while (na.n) {
            unsigned rem = 0;
            for (i = na.n; i-- > 0;) {
                unsigned cur = (rem << 16) | na.d[i];
                na.d[i] = cur / chunk;
                rem = cur % chunk;
            }
            trim(&na);
            for (i = 0; i < digits && (na.n || rem); i++) {
                unsigned d = rem % base;
                *--p = d < 10 ? '0' + d : 'a' + d - 10;
                rem /= base;
            }
        }
    }
    if (neg)
        *--p = '-';
    return make_string(p, buf + sizeof buf - p);
}

Value int_from_s(const unsigned char *s, unsigned n)
{
    unsigned i;
    int neg = 0;
    Num *x = &nr;
    if (n && (s[0] == '-' || s[0] == '+')) {
        neg = s[0] == '-';
        s++;
        n--;
    }
    if (n == 0)
        return 0;
    x->neg = 0;
    x->n = 0;
    for (i = 0; i < n; i++) {
        unsigned carry = s[i] - '0', k;
        if (s[i] < '0' || s[i] > '9')
            return 0;
        for (k = 0; k < x->n; k++) {
            unsigned t = x->d[k] * 10u + carry;
            x->d[k] = t & 0xFFFF;
            carry = t >> 16;
        }
        if (carry) {
            if (x->n >= MAXL - 2)
                return 0;
            x->d[x->n++] = carry;
        }
    }
    x->neg = neg;
    return pack(x);
}

/* Bitwise operations, with negative numbers in two's complement (as
   Python does): a negative x is ~(|x| - 1), so each operation is one on
   magnitudes, maybe complemented. */
static void mag_dec(Num *x)
{
    unsigned i;
    for (i = 0; i < x->n; i++) {
        if (x->d[i]--)
            break;
    }
}

static void mag_inc(Num *x)
{
    unsigned i;
    for (i = 0; i < x->n; i++)
        if (++x->d[i])
            return;
    x->d[x->n++] = 1;
}

static Value bitwise(Value a, Value b, int op)
{
    unsigned i, n;
    int ia, ib, neg;
    unpack(a, &na);
    unpack(b, &nb);
    ia = na.neg;
    ib = nb.neg;
    if (ia) mag_dec(&na);
    if (ib) mag_dec(&nb);
    n = na.n > nb.n ? na.n : nb.n;
    for (i = 0; i < n; i++) {
        unsigned x = i < na.n ? na.d[i] : 0, y = i < nb.n ? nb.d[i] : 0, r;
        if (ia) x = ~x & 0xFFFF;
        if (ib) y = ~y & 0xFFFF;
        r = op == 0 ? x & y : op == 1 ? x | y : x ^ y;
        nr.d[i] = r;
    }
    nr.n = n;
    /* the result's sign: what the infinite run of high bits gives */
    neg = op == 0 ? ia && ib : op == 1 ? ia || ib : ia != ib;
    if (neg) {
        /* r holds the low bits of a negative number: its magnitude is ~r + 1 */
        for (i = 0; i < n; i++)
            nr.d[i] = ~nr.d[i] & 0xFFFF;
        trim(&nr);
        mag_inc(&nr);
    }
    nr.neg = neg;
    return pack(&nr);
}

Value int_and(Value a, Value b)
{
    if (IS_INT(a) && IS_INT(b))
        return a & b;
    return bitwise(a, b, 0);
}

Value int_or(Value a, Value b)
{
    if (IS_INT(a) && IS_INT(b))
        return a | b;
    return bitwise(a, b, 1);
}

Value int_xor(Value a, Value b)
{
    if (IS_INT(a) && IS_INT(b))
        return (a ^ b) | 1;
    return bitwise(a, b, 2);
}

Value int_shl(Value a, SValue n)
{
    Value p;
    if (n < 0)
        return int_shr(a, -n);
    if (n > 16 * (MAXL - 4))
        return 0;
    push_root(&a);
    p = int_pow(MKINT(2), MKINT(n));
    pop_roots(1);
    return p ? int_mul(a, p) : 0;
}

Value int_shr(Value a, SValue n)
{
    Value p;
    if (n < 0)
        return int_shl(a, -n);
    if (IS_INT(a))
        return MKINT(n > 30 ? (INT(a) < 0 ? -1 : 0) : INT(a) >> n);
    push_root(&a);
    p = int_pow(MKINT(2), MKINT(n));
    pop_roots(1);
    return p ? int_divmod(a, p, 0) : 0;
}

unsigned big_hash(Value v)
{
    unsigned h = SIGN(v), i, n = NLIMBS(v);
    for (i = 0; i < n; i++)
        h = h * 31 + LIMBS(v)[i];
    return h;
}
