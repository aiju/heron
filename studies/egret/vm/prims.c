/* Primitives: the methods written in C. Each takes the receiver and the
   arguments (args[0] is the receiver) and returns the result, or 0 with
   prim_error set. args points into the value stack, so it stays right
   when a primitive allocates and the collector moves things; a Value
   copied out of it doesn't. */

#include "egret.h"

#define A0 args[0]
#define A1 args[1]
#define A2 args[2]
#define IS_STR(v) (!IS_INT(v) && (CLASSW(v) == cls_String || CLASSW(v) == cls_Symbol))
#define IS_LIST(v) (!IS_INT(v) && CLASSW(v) == cls_List)
#define IS_NUM(v) (IS_INT(v) || is_bigint(v))
#define ITEMS(l) (&F(F(l, L_ITEMS), 0))

static Value chars[256];            /* the one-character strings */

static Value type_error(const char *what, Value v)
{
    static char buf[120];
    Value n = class_name(CLASS_OF(v));
    unsigned a = strlen(what), k = SIZE(n) < 40 ? SIZE(n) : 40;
    memcpy(buf, what, a);
    memcpy(buf + a, ", not a ", 8);
    memcpy(buf + a + 8, BYTES(n), k);
    prim_error = make_string(buf, a + 8 + k);
    return 0;
}

static Value index_error(SValue i, SValue size)
{
    static char buf[80];
    char *p = buf;
    Value s;
    memcpy(p, "index ", 6);
    p += 6;
    s = int_to_s(MKINT(i), 10);
    memcpy(p, BYTES(s), SIZE(s));
    p += SIZE(s);
    memcpy(p, " out of range (size ", 20);
    p += 20;
    s = int_to_s(MKINT(size), 10);
    memcpy(p, BYTES(s), SIZE(s));
    p += SIZE(s);
    *p++ = ')';
    prim_error = make_string(buf, p - buf);
    return 0;
}

/* ---- Object -------------------------------------------------------------------- */

static Value p_identical(Value *args, int argc) { return BOOL(A0 == A1); }
static Value p_class(Value *args, int argc) { return CLASS_OF(A0); }
static Value p_hash(Value *args, int argc) { return MKINT(value_hash(A0) & 0x3FFFFFFF); }
static Value p_is_a(Value *args, int argc) { return BOOL(is_a(A0, A1)); }

static Value p_responds(Value *args, int argc)
{
    if (IS_INT(A1) || CLASSW(A1) != cls_Symbol)
        return type_error("respond_to? needs a Symbol", A1);
    return BOOL(class_lookup(CLASS_OF(A0), A1) != 0);
}

static Value p_ivar(Value *args, int argc)
{
    SValue i;
    if (!IS_INT(A1))
        return type_error("ivar needs an Int", A1);
    i = INT(A1);
    if (IS_INT(A0) || IS_BYTES(A0) || i < 0 || (unsigned)i >= SIZE(A0))
        return prim_fail("no such instance variable");
    return F(A0, i);
}

static Value p_write(Value *args, int argc)
{
    if (!IS_STR(A1))
        return type_error("write needs a String", A1);
    out_bytes(BYTES(A1), SIZE(A1));
    return NIL;
}

/* the program's input: what follows __END__ */
extern const unsigned char *input_data;
extern unsigned input_len, input_pos;

static Value p_gets(Value *args, int argc)
{
    unsigned start = input_pos;
    if (input_pos >= input_len)
        return NIL;
    while (input_pos < input_len && input_data[input_pos] != '\n')
        input_pos++;
    if (input_pos < input_len)
        input_pos++;
    return make_string((const char *)input_data + start, input_pos - start);
}

static Value p_read_all(Value *args, int argc)
{
    unsigned start = input_pos;
    input_pos = input_len;
    return make_string((const char *)input_data + start, input_len - start);
}

static Value p_clock(Value *args, int argc) { return MKINT(cycles() & 0x3FFFFFFF); }

static Value p_exit(Value *args, int argc)
{
    out_flush();
    fatal(0);
    return NIL;
}

static Value p_gc(Value *args, int argc)
{
    gc(0);
    return NIL;
}

static Value p_gc_count(Value *args, int argc) { return MKINT(gc_count); }

/* ---- Class ---------------------------------------------------------------------- */

static Value p_class_name(Value *args, int argc)
{
    Value n = F(A0, C_NAME);
    return make_string((const char *)BYTES(n), SIZE(n));
}

static Value p_superclass(Value *args, int argc) { return F(A0, C_SUPER); }

static Value p_ivars(Value *args, int argc)
{
    Value l, iv;
    unsigned n, i;
    if (INT(F(A0, C_KIND)) != K_OBJECT)
        return make_list(0);
    n = INT(F(A0, C_NIVARS));
    l = make_list(n);
    iv = F(A0, C_IVARS);
    for (i = 0; i < n; i++)
        ITEMS(l)[i] = F(iv, i);
    F(l, L_SIZE) = MKINT(n);
    return l;
}

/* ---- Int ------------------------------------------------------------------------- */

static Value arith_check(Value *args, const char *op)
{
    if (!IS_NUM(A1)) {
        static char buf[40];
        strcpy(buf, "Int ");
        strcat(buf, op);
        strcat(buf, " needs a number");
        return type_error(buf, A1);
    }
    return 1;
}

static Value too_big(void) { return prim_fail("integer too big"); }

static Value p_add(Value *args, int argc)
{
    Value r;
    if (!arith_check(args, "+")) return 0;
    r = int_add(A0, A1);
    return r ? r : too_big();
}

static Value p_sub(Value *args, int argc)
{
    Value r;
    if (!arith_check(args, "-")) return 0;
    r = int_sub(A0, A1);
    return r ? r : too_big();
}

static Value p_mul(Value *args, int argc)
{
    Value r;
    if (!arith_check(args, "*")) return 0;
    if (IS_INT(A0) && IS_INT(A1)) {
        /* the product of two SmallInts, without a 64-bit type */
        SValue x = INT(A0), y = INT(A1);
        unsigned ux = x < 0 ? 0u - (unsigned)x : (unsigned)x;
        unsigned uy = y < 0 ? 0u - (unsigned)y : (unsigned)y;
        if ((ux < 0x8000 && uy < 0x8000) || ux == 0 || (uy <= 0x3FFFFFFFu / ux)) {
            SValue p = (SValue)(ux * uy);
            if ((x < 0) != (y < 0))
                p = -p;
            if (FITS31(p))
                return MKINT(p);
        }
    }
    r = int_mul(A0, A1);
    return r ? r : too_big();
}

static Value p_div(Value *args, int argc)
{
    Value r;
    if (!arith_check(args, "/")) return 0;
    if (A1 == MKINT(0))
        return prim_fail("division by zero");
    r = int_divmod(A0, A1, 0);
    return r ? r : too_big();
}

static Value p_mod(Value *args, int argc)
{
    Value r;
    if (!arith_check(args, "%")) return 0;
    if (A1 == MKINT(0))
        return prim_fail("division by zero");
    r = int_divmod(A0, A1, 1);
    return r ? r : too_big();
}

static Value p_pow(Value *args, int argc)
{
    Value r;
    if (!IS_INT(A1) || INT(A1) < 0)
        return prim_fail("** needs a non-negative Int exponent");
    r = int_pow(A0, A1);
    return r ? r : too_big();
}

static Value p_neg(Value *args, int argc)
{
    Value r = int_neg(A0);
    return r ? r : too_big();
}

static Value p_lt(Value *args, int argc)
{
    if (!arith_check(args, "<")) return 0;
    return BOOL(int_cmp(A0, A1) < 0);
}

static Value p_le(Value *args, int argc)
{
    if (!arith_check(args, "<=")) return 0;
    return BOOL(int_cmp(A0, A1) <= 0);
}

static Value p_gt(Value *args, int argc)
{
    if (!arith_check(args, ">")) return 0;
    return BOOL(int_cmp(A0, A1) > 0);
}

static Value p_ge(Value *args, int argc)
{
    if (!arith_check(args, ">=")) return 0;
    return BOOL(int_cmp(A0, A1) >= 0);
}

static Value p_cmp(Value *args, int argc)
{
    if (!IS_NUM(A1))
        return NIL;
    return MKINT(int_cmp(A0, A1));
}

static Value p_int_eq(Value *args, int argc)
{
    if (!IS_NUM(A1))
        return FALSE_V;
    return BOOL(int_cmp(A0, A1) == 0);
}

static Value p_and(Value *args, int argc)
{
    Value r;
    if (!arith_check(args, "&")) return 0;
    r = int_and(A0, A1);
    return r ? r : too_big();
}

static Value p_or(Value *args, int argc)
{
    Value r;
    if (!arith_check(args, "|")) return 0;
    r = int_or(A0, A1);
    return r ? r : too_big();
}

static Value p_xor(Value *args, int argc)
{
    Value r;
    if (!arith_check(args, "^")) return 0;
    r = int_xor(A0, A1);
    return r ? r : too_big();
}

static Value p_invert(Value *args, int argc)
{
    if (IS_INT(A0))
        return A0 ^ ~1u;
    return int_sub(MKINT(-1), A0);
}

static Value p_shl(Value *args, int argc)
{
    Value r;
    if (!IS_INT(A1))
        return type_error("<< needs an Int", A1);
    if (IS_INT(A0) && INT(A1) >= 0 && INT(A1) < 31) {
        SValue x = INT(A0), n = INT(A1);
        SValue y = (SValue)((unsigned)x << n);
        if ((y >> n) == x && FITS31(y))
            return MKINT(y);
    }
    r = int_shl(A0, INT(A1));
    return r ? r : too_big();
}

static Value p_shr(Value *args, int argc)
{
    Value r;
    if (!IS_INT(A1))
        return type_error(">> needs an Int", A1);
    r = int_shr(A0, INT(A1));
    return r ? r : too_big();
}

static Value p_int_to_s(Value *args, int argc)
{
    int base = 10;
    if (argc == 1) {
        if (!IS_INT(A1) || INT(A1) < 2 || INT(A1) > 36)
            return prim_fail("to_s needs a base from 2 to 36");
        base = INT(A1);
    }
    return int_to_s(A0, base);
}

static Value p_chr(Value *args, int argc)
{
    if (!IS_INT(A0) || INT(A0) < 0 || INT(A0) > 255)
        return prim_fail("chr needs a number from 0 to 255");
    return chars[INT(A0)];
}

static Value p_int_hash(Value *args, int argc) { return MKINT(value_hash(A0) & 0x3FFFFFFF); }

/* ---- String ------------------------------------------------------------------------ */

static Value p_str_size(Value *args, int argc) { return MKINT(SIZE(A0)); }

static Value p_str_add(Value *args, int argc)
{
    Value s;
    unsigned n;
    if (!IS_STR(A1))
        return type_error("String + needs a String", A1);
    n = SIZE(A0);
    s = alloc_bytes(cls_String, n + SIZE(A1));
    memcpy(BYTES(s), BYTES(A0), n);
    memcpy(BYTES(s) + n, BYTES(A1), SIZE(A1));
    return s;
}

static Value p_str_mul(Value *args, int argc)
{
    Value s;
    unsigned n, k, i;
    if (!IS_INT(A1) || INT(A1) < 0)
        return prim_fail("String * needs a non-negative Int");
    n = SIZE(A0);
    k = INT(A1);
    if (n && k > 0x40000 / n)
        return prim_fail("string too long");
    s = alloc_bytes(cls_String, n * k);
    for (i = 0; i < k; i++)
        memcpy(BYTES(s) + i * n, BYTES(A0), n);
    return s;
}

static int str_cmp(Value a, Value b)
{
    unsigned na = SIZE(a), nb = SIZE(b);
    int c = memcmp(BYTES(a), BYTES(b), na < nb ? na : nb);
    if (c)
        return c < 0 ? -1 : 1;
    return na < nb ? -1 : na > nb;
}

static Value p_str_eq(Value *args, int argc)
{
    if (!IS_STR(A1) || CLASSW(A1) == cls_Symbol)
        return FALSE_V;
    return BOOL(str_eq(A0, A1));
}

static Value p_sym_eq(Value *args, int argc) { return BOOL(A0 == A1); }

static Value p_str_cmp(Value *args, int argc)
{
    if (!IS_STR(A1))
        return NIL;
    return MKINT(str_cmp(A0, A1));
}

static Value p_str_lt(Value *args, int argc)
{
    if (!IS_STR(A1)) return type_error("String < needs a String", A1);
    return BOOL(str_cmp(A0, A1) < 0);
}

static Value p_str_le(Value *args, int argc)
{
    if (!IS_STR(A1)) return type_error("String <= needs a String", A1);
    return BOOL(str_cmp(A0, A1) <= 0);
}

static Value p_str_gt(Value *args, int argc)
{
    if (!IS_STR(A1)) return type_error("String > needs a String", A1);
    return BOOL(str_cmp(A0, A1) > 0);
}

static Value p_str_ge(Value *args, int argc)
{
    if (!IS_STR(A1)) return type_error("String >= needs a String", A1);
    return BOOL(str_cmp(A0, A1) >= 0);
}

static Value p_str_hash(Value *args, int argc) { return MKINT(str_hash(A0) & 0x3FFFFFFF); }

/* s[i]: a one-character string; s[a..b]: a substring */
static Value p_str_at(Value *args, int argc)
{
    SValue n = SIZE(A0), i;
    if (!IS_INT(A1) && CLASSW(A1) == cls_Range) {
        SValue a = INT(F(A1, R_FIRST)), b = INT(F(A1, R_LAST));
        if (a < 0) a += n;
        if (b < 0) b += n;
        if (a < 0) a = 0;
        if (b >= n) b = n - 1;
        if (b < a)
            return make_string("", 0);
        return make_string((const char *)BYTES(A0) + a, b - a + 1);
    }
    if (!IS_INT(A1))
        return type_error("a String index must be an Int or a Range", A1);
    i = INT(A1);
    if (i < 0)
        i += n;
    if (i < 0 || i >= n)
        return index_error(INT(A1), n);
    return chars[BYTES(A0)[i]];
}

static Value p_byte_at(Value *args, int argc)
{
    SValue i;
    if (!IS_INT(A1))
        return type_error("byte_at needs an Int", A1);
    i = INT(A1);
    if (i < 0 || (unsigned)i >= SIZE(A0))
        return index_error(i, SIZE(A0));
    return MKINT(BYTES(A0)[i]);
}

static Value p_ord(Value *args, int argc)
{
    if (SIZE(A0) == 0)
        return prim_fail("ord of an empty string");
    return MKINT(BYTES(A0)[0]);
}

static Value p_str_to_s(Value *args, int argc)
{
    if (CLASSW(A0) == cls_Symbol)
        return make_string((const char *)BYTES(A0), SIZE(A0));
    return A0;
}

static Value p_to_sym(Value *args, int argc) { return intern((const char *)BYTES(A0), SIZE(A0)); }

static Value p_to_i(Value *args, int argc)
{
    Value r = int_from_s(BYTES(A0), SIZE(A0));
    return r ? r : NIL;
}

static Value p_str_inspect(Value *args, int argc)
{
    static char buf[2048];
    unsigned n = SIZE(A0), i, k = 0;
    unsigned char *s = BYTES(A0);
    if (CLASSW(A0) == cls_Symbol) {
        buf[k++] = ':';
        for (i = 0; i < n && k < sizeof buf - 2; i++)
            buf[k++] = s[i];
        return make_string(buf, k);
    }
    buf[k++] = '"';
    for (i = 0; i < n && k < sizeof buf - 6; i++) {
        int c = s[i];
        if (c == '"' || c == '\\' || c == '{') {
            buf[k++] = '\\';
            buf[k++] = c;
        } else if (c == '\n') {
            buf[k++] = '\\';
            buf[k++] = 'n';
        } else if (c == '\t') {
            buf[k++] = '\\';
            buf[k++] = 't';
        } else {
            buf[k++] = c;
        }
    }
    buf[k++] = '"';
    return make_string(buf, k);
}

static Value p_chars(Value *args, int argc)
{
    unsigned n = SIZE(A0), i;
    Value l = make_list(n);
    for (i = 0; i < n; i++)
        ITEMS(l)[i] = chars[BYTES(A0)[i]];
    F(l, L_SIZE) = MKINT(n);
    return l;
}

static Value p_upper(Value *args, int argc)
{
    unsigned n = SIZE(A0), i;
    Value s = alloc_bytes(cls_String, n);
    for (i = 0; i < n; i++) {
        int c = BYTES(A0)[i];
        BYTES(s)[i] = c >= 'a' && c <= 'z' ? c - 32 : c;
    }
    return s;
}

static Value p_lower(Value *args, int argc)
{
    unsigned n = SIZE(A0), i;
    Value s = alloc_bytes(cls_String, n);
    for (i = 0; i < n; i++) {
        int c = BYTES(A0)[i];
        BYTES(s)[i] = c >= 'A' && c <= 'Z' ? c + 32 : c;
    }
    return s;
}

static int is_space(int c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r'; }

static Value p_strip(Value *args, int argc)
{
    unsigned a = 0, b = SIZE(A0);
    while (a < b && is_space(BYTES(A0)[a]))
        a++;
    while (b > a && is_space(BYTES(A0)[b - 1]))
        b--;
    return make_string((const char *)BYTES(A0) + a, b - a);
}

/* the position of sub in s at or after start, or -1 */
static SValue find_sub(Value s, Value sub, unsigned start)
{
    unsigned n = SIZE(s), k = SIZE(sub), i;
    if (k > n)
        return -1;
    for (i = start; i + k <= n; i++)
        if (memcmp(BYTES(s) + i, BYTES(sub), k) == 0)
            return i;
    return -1;
}

static Value p_index(Value *args, int argc)
{
    SValue i;
    if (!IS_STR(A1))
        return type_error("index needs a String", A1);
    i = find_sub(A0, A1, 0);
    return i < 0 ? NIL : MKINT(i);
}

static Value p_contains(Value *args, int argc)
{
    if (!IS_STR(A1))
        return type_error("contains? needs a String", A1);
    return BOOL(find_sub(A0, A1, 0) >= 0);
}

static Value p_starts(Value *args, int argc)
{
    unsigned k;
    if (!IS_STR(A1))
        return type_error("starts_with? needs a String", A1);
    k = SIZE(A1);
    return BOOL(k <= SIZE(A0) && memcmp(BYTES(A0), BYTES(A1), k) == 0);
}

static Value p_ends(Value *args, int argc)
{
    unsigned k, n;
    if (!IS_STR(A1))
        return type_error("ends_with? needs a String", A1);
    k = SIZE(A1);
    n = SIZE(A0);
    return BOOL(k <= n && memcmp(BYTES(A0) + n - k, BYTES(A1), k) == 0);
}

/* split on a separator, or on runs of white space without one */
static Value p_split(Value *args, int argc)
{
    Value l = make_list(4), part;
    unsigned n, i = 0;
    push_root(&l);
    if (argc == 0) {
        for (;;) {
            unsigned start;
            n = SIZE(A0);
            while (i < n && is_space(BYTES(A0)[i]))
                i++;
            if (i >= n)
                break;
            start = i;
            while (i < n && !is_space(BYTES(A0)[i]))
                i++;
            part = make_string((const char *)BYTES(A0) + start, i - start);
            list_push(l, part);
        }
    } else {
        SValue j;
        if (!IS_STR(A1) || SIZE(A1) == 0) {
            pop_roots(1);
            return prim_fail("split needs a non-empty String");
        }
        for (;;) {
            j = find_sub(A0, A1, i);
            if (j < 0)
                break;
            part = make_string((const char *)BYTES(A0) + i, j - i);
            list_push(l, part);
            i = j + SIZE(A1);
        }
        part = make_string((const char *)BYTES(A0) + i, SIZE(A0) - i);
        list_push(l, part);
    }
    pop_roots(1);
    return l;
}

static Value p_replace(Value *args, int argc)
{
    /* every occurrence of A1 by A2 */
    Value out;
    unsigned n, k, r, count = 0, i;
    SValue j;
    unsigned char *d;
    if (!IS_STR(A1) || !IS_STR(A2) || SIZE(A1) == 0)
        return prim_fail("replace needs two Strings, the first not empty");
    for (j = find_sub(A0, A1, 0); j >= 0; j = find_sub(A0, A1, j + SIZE(A1)))
        count++;
    n = SIZE(A0);
    k = SIZE(A1);
    r = SIZE(A2);
    out = alloc_bytes(cls_String, n + count * r - count * k);
    d = BYTES(out);
    i = 0;
    for (j = find_sub(A0, A1, 0); j >= 0; j = find_sub(A0, A1, i)) {
        memcpy(d, BYTES(A0) + i, j - i);
        d += j - i;
        memcpy(d, BYTES(A2), r);
        d += r;
        i = j + k;
    }
    memcpy(d, BYTES(A0) + i, n - i);
    return out;
}

/* ---- List -------------------------------------------------------------------------- */

static Value p_list_new(Value *args, int argc)
{
    Value l;
    unsigned n = 0, i;
    if (argc >= 1) {
        if (!IS_INT(A1) || INT(A1) < 0)
            return prim_fail("List.new needs a size");
        n = INT(A1);
    }
    l = make_list(n);
    for (i = 0; i < n; i++)
        ITEMS(l)[i] = argc >= 2 ? A2 : NIL;
    F(l, L_SIZE) = MKINT(n);
    return l;
}

static Value p_list_size(Value *args, int argc) { return F(A0, L_SIZE); }

static Value list_slice(Value l, SValue a, SValue b)
{
    SValue n = INT(F(l, L_SIZE)), i;
    Value r;
    if (a < 0) a += n;
    if (b < 0) b += n;
    if (a < 0) a = 0;
    if (b >= n) b = n - 1;
    if (b < a)
        return make_list(0);
    push_root(&l);
    r = make_list(b - a + 1);
    pop_roots(1);
    for (i = a; i <= b; i++)
        ITEMS(r)[i - a] = ITEMS(l)[i];
    F(r, L_SIZE) = MKINT(b - a + 1);
    return r;
}

static Value p_list_at(Value *args, int argc)
{
    SValue n = INT(F(A0, L_SIZE)), i;
    if (!IS_INT(A1) && CLASSW(A1) == cls_Range)
        return list_slice(A0, INT(F(A1, R_FIRST)), INT(F(A1, R_LAST)));
    if (!IS_INT(A1))
        return type_error("a List index must be an Int or a Range", A1);
    i = INT(A1);
    if (i < 0)
        i += n;
    if (i < 0 || i >= n)
        return index_error(INT(A1), n);
    return ITEMS(A0)[i];
}

static Value p_list_put(Value *args, int argc)
{
    SValue n = INT(F(A0, L_SIZE)), i;
    if (!IS_INT(A1))
        return type_error("a List index must be an Int", A1);
    i = INT(A1);
    if (i < 0)
        i += n;
    if (i < 0 || i >= n)
        return index_error(INT(A1), n);
    ITEMS(A0)[i] = A2;
    return A2;
}

static Value p_push(Value *args, int argc)
{
    list_push(A0, A1);
    return A0;
}

static Value p_pop(Value *args, int argc)
{
    SValue n = INT(F(A0, L_SIZE));
    Value v;
    if (n == 0)
        return prim_fail("pop from an empty List");
    v = ITEMS(A0)[n - 1];
    ITEMS(A0)[n - 1] = NIL;
    F(A0, L_SIZE) = MKINT(n - 1);
    return v;
}

static Value p_insert(Value *args, int argc)
{
    SValue n = INT(F(A0, L_SIZE)), i, k;
    if (!IS_INT(A1))
        return type_error("insert needs an Int position", A1);
    i = INT(A1);
    if (i < 0)
        i += n + 1;
    if (i < 0 || i > n)
        return index_error(INT(A1), n);
    list_push(A0, NIL);
    for (k = n; k > i; k--)
        ITEMS(A0)[k] = ITEMS(A0)[k - 1];
    ITEMS(A0)[i] = A2;
    return A0;
}

static Value p_delete_at(Value *args, int argc)
{
    SValue n = INT(F(A0, L_SIZE)), i, k;
    Value v;
    if (!IS_INT(A1))
        return type_error("delete_at needs an Int", A1);
    i = INT(A1);
    if (i < 0)
        i += n;
    if (i < 0 || i >= n)
        return index_error(INT(A1), n);
    v = ITEMS(A0)[i];
    for (k = i; k < n - 1; k++)
        ITEMS(A0)[k] = ITEMS(A0)[k + 1];
    ITEMS(A0)[n - 1] = NIL;
    F(A0, L_SIZE) = MKINT(n - 1);
    return v;
}

static Value p_list_add(Value *args, int argc)
{
    SValue a, b, i;
    Value l;
    if (!IS_LIST(A1))
        return type_error("List + needs a List", A1);
    a = INT(F(A0, L_SIZE));
    b = INT(F(A1, L_SIZE));
    l = make_list(a + b);
    for (i = 0; i < a; i++)
        ITEMS(l)[i] = ITEMS(A0)[i];
    for (i = 0; i < b; i++)
        ITEMS(l)[a + i] = ITEMS(A1)[i];
    F(l, L_SIZE) = MKINT(a + b);
    return l;
}

static Value p_list_copy(Value *args, int argc) { return list_slice(A0, 0, INT(F(A0, L_SIZE)) - 1); }

static Value p_reverse(Value *args, int argc)
{
    Value l = list_slice(A0, 0, INT(F(A0, L_SIZE)) - 1);
    SValue n = INT(F(l, L_SIZE)), i;
    for (i = 0; i < n / 2; i++) {
        Value t = ITEMS(l)[i];
        ITEMS(l)[i] = ITEMS(l)[n - 1 - i];
        ITEMS(l)[n - 1 - i] = t;
    }
    return l;
}

static Value p_clear(Value *args, int argc)
{
    Value items = make_list(0);
    F(A0, L_ITEMS) = F(items, L_ITEMS);
    F(A0, L_SIZE) = MKINT(0);
    return A0;
}

/* join a list of strings */
static Value p_join(Value *args, int argc)
{
    SValue n = INT(F(A0, L_SIZE)), i;
    unsigned len = 0, k;
    Value s;
    unsigned char *d;
    if (argc == 1 && !IS_STR(A1))
        return type_error("join needs a String", A1);
    k = argc == 1 ? SIZE(A1) : 0;
    for (i = 0; i < n; i++) {
        Value x = ITEMS(A0)[i];
        if (!IS_STR(x))
            return type_error("join needs a List of Strings (use map(to_s))", x);
        len += SIZE(x) + (i ? k : 0);
    }
    s = alloc_bytes(cls_String, len);
    d = BYTES(s);
    for (i = 0; i < n; i++) {
        Value x = ITEMS(A0)[i];
        if (i && k) {
            memcpy(d, BYTES(A1), k);
            d += k;
        }
        memcpy(d, BYTES(x), SIZE(x));
        d += SIZE(x);
    }
    return s;
}

static Value p_self(Value *args, int argc) { return A0; }

/* ---- Map ---------------------------------------------------------------------------- */

static Value p_map_new(Value *args, int argc) { return map_new(4); }
static Value p_map_size(Value *args, int argc) { return F(A0, MAP_COUNT); }

static Value p_map_get(Value *args, int argc)
{
    Value v = map_get(A0, A1);
    return v ? v : NIL;
}

static Value p_map_get_default(Value *args, int argc)
{
    Value v = map_get(A0, A1);
    return v ? v : A2;
}

static Value p_map_put(Value *args, int argc)
{
    map_put(A0, A1, A2);
    return A2;
}

static Value p_map_has(Value *args, int argc) { return BOOL(map_get(A0, A1) != 0); }
static Value p_map_delete(Value *args, int argc) { return BOOL(map_delete(A0, A1)); }

static Value map_list(Value *args, int which)
{
    unsigned used = INT(F(A0, MAP_USED)), i, n = 0;
    Value l = make_list(INT(F(A0, MAP_COUNT)));
    for (i = 0; i < used; i++) {
        Value k = F(F(A0, MAP_KEYS), i);
        if (!k)
            continue;
        ITEMS(l)[n++] = which ? F(F(A0, MAP_VALS), i) : k;
    }
    F(l, L_SIZE) = MKINT(n);
    return l;
}

static Value p_map_keys(Value *args, int argc) { return map_list(args, 0); }
static Value p_map_values(Value *args, int argc) { return map_list(args, 1); }

/* ---- Range, Block ----------------------------------------------------------------- */

static Value p_range_first(Value *args, int argc) { return F(A0, R_FIRST); }
static Value p_range_last(Value *args, int argc) { return F(A0, R_LAST); }

static Value p_block_arity(Value *args, int argc)
{
    return MKINT(MI_NARGS(F(F(A0, CL_METHOD), M_INFO)));
}

/* ---- the table -------------------------------------------------------------------- */

typedef struct PrimDef {
    const char *cls;            /* a class's name; "Name class" for its metaclass */
    const char *sel;
    int nargs;                  /* -1 - n: n or more */
    PrimFn fn;
    int special;
} PrimDef;

static const PrimDef defs[] = {
    { "Object", "same?", 1, p_identical, 0 },
    { "Object", "==", 1, p_identical, 0 },
    { "Object", "class", 0, p_class, 0 },
    { "Object", "hash", 0, p_hash, 0 },
    { "Object", "is_a?", 1, p_is_a, 0 },
    { "Object", "respond_to?", 1, p_responds, 0 },
    { "Object", "ivar", 1, p_ivar, 0 },
    { "Object", "write", 1, p_write, 0 },
    { "Object", "gets", 0, p_gets, 0 },
    { "Object", "read_all", 0, p_read_all, 0 },
    { "Object", "clock", 0, p_clock, 0 },
    { "Object", "exit", 0, p_exit, 0 },
    { "Object", "gc", 0, p_gc, 0 },
    { "Object", "gc_count", 0, p_gc_count, 0 },
    { "Object", "raise", 1, 0, PR_RAISE },
    { "Object", "send", -2, 0, PR_SEND },
    { "Class", "new", -1, 0, PR_NEW },
    { "Class", "call", -1, 0, PR_NEW },
    { "Class", "name", 0, p_class_name, 0 },
    { "Class", "superclass", 0, p_superclass, 0 },
    { "Class", "ivars", 0, p_ivars, 0 },
    { "Block", "call", -1, 0, PR_CALL },
    { "Block", "arity", 0, p_block_arity, 0 },
    { "Int", "+", 1, p_add, 0 },
    { "Int", "-", 1, p_sub, 0 },
    { "Int", "*", 1, p_mul, 0 },
    { "Int", "/", 1, p_div, 0 },
    { "Int", "%", 1, p_mod, 0 },
    { "Int", "**", 1, p_pow, 0 },
    { "Int", "neg", 0, p_neg, 0 },
    { "Int", "<", 1, p_lt, 0 },
    { "Int", "<=", 1, p_le, 0 },
    { "Int", ">", 1, p_gt, 0 },
    { "Int", ">=", 1, p_ge, 0 },
    { "Int", "<=>", 1, p_cmp, 0 },
    { "Int", "==", 1, p_int_eq, 0 },
    { "Int", "&", 1, p_and, 0 },
    { "Int", "|", 1, p_or, 0 },
    { "Int", "^", 1, p_xor, 0 },
    { "Int", "~", 0, p_invert, 0 },
    { "Int", "<<", 1, p_shl, 0 },
    { "Int", ">>", 1, p_shr, 0 },
    { "Int", "to_s", -1, p_int_to_s, 0 },
    { "Int", "chr", 0, p_chr, 0 },
    { "Int", "hash", 0, p_int_hash, 0 },
    { "String", "size", 0, p_str_size, 0 },
    { "String", "+", 1, p_str_add, 0 },
    { "String", "*", 1, p_str_mul, 0 },
    { "String", "==", 1, p_str_eq, 0 },
    { "String", "<=>", 1, p_str_cmp, 0 },
    { "String", "<", 1, p_str_lt, 0 },
    { "String", "<=", 1, p_str_le, 0 },
    { "String", ">", 1, p_str_gt, 0 },
    { "String", ">=", 1, p_str_ge, 0 },
    { "String", "hash", 0, p_str_hash, 0 },
    { "String", "[]", 1, p_str_at, 0 },
    { "String", "byte_at", 1, p_byte_at, 0 },
    { "String", "ord", 0, p_ord, 0 },
    { "String", "to_s", 0, p_str_to_s, 0 },
    { "String", "to_sym", 0, p_to_sym, 0 },
    { "String", "to_i", 0, p_to_i, 0 },
    { "String", "inspect", 0, p_str_inspect, 0 },
    { "String", "chars", 0, p_chars, 0 },
    { "String", "iter", 0, p_chars, 0 },
    { "String", "upper", 0, p_upper, 0 },
    { "String", "lower", 0, p_lower, 0 },
    { "String", "strip", 0, p_strip, 0 },
    { "String", "index", 1, p_index, 0 },
    { "String", "contains?", 1, p_contains, 0 },
    { "String", "starts_with?", 1, p_starts, 0 },
    { "String", "ends_with?", 1, p_ends, 0 },
    { "String", "split", -1, p_split, 0 },
    { "String", "replace", 2, p_replace, 0 },
    { "Symbol", "==", 1, p_sym_eq, 0 },
    { "Symbol", "hash", 0, p_str_hash, 0 },
    { "List class", "new", -1, p_list_new, 0 },
    { "List", "size", 0, p_list_size, 0 },
    { "List", "[]", 1, p_list_at, 0 },
    { "List", "[]=", 2, p_list_put, 0 },
    { "List", "push", 1, p_push, 0 },
    { "List", "<<", 1, p_push, 0 },
    { "List", "pop", 0, p_pop, 0 },
    { "List", "insert", 2, p_insert, 0 },
    { "List", "delete_at", 1, p_delete_at, 0 },
    { "List", "+", 1, p_list_add, 0 },
    { "List", "copy", 0, p_list_copy, 0 },
    { "List", "reverse", 0, p_reverse, 0 },
    { "List", "clear", 0, p_clear, 0 },
    { "List", "join", -1, p_join, 0 },
    { "List", "iter", 0, p_self, 0 },
    { "Map class", "new", 0, p_map_new, 0 },
    { "Map", "size", 0, p_map_size, 0 },
    { "Map", "[]", 1, p_map_get, 0 },
    { "Map", "get", 2, p_map_get_default, 0 },
    { "Map", "[]=", 2, p_map_put, 0 },
    { "Map", "has?", 1, p_map_has, 0 },
    { "Map", "delete", 1, p_map_delete, 0 },
    { "Map", "keys", 0, p_map_keys, 0 },
    { "Map", "values", 0, p_map_values, 0 },
    { "Map", "iter", 0, p_map_keys, 0 },
    { "Range", "first", 0, p_range_first, 0 },
    { "Range", "last", 0, p_range_last, 0 },
    { "Range", "iter", 0, p_self, 0 },
    { 0, 0, 0, 0, 0 }
};

PrimFn prim_table[MAX_PRIMS];
Value egret_blockcall;
static int nprim = PR_FIRST_C;

static Value find_class(const char *name)
{
    unsigned n = strlen(name);
    int meta = n > 6 && strcmp(name + n - 6, " class") == 0;
    Value c = globals[global_index(intern(name, meta ? n - 6 : n))];
    if (!c)
        fatal("prims: no such class");
    return meta ? CLASSW(c) : c;
}

void prims_init(void)
{
    const PrimDef *d;
    int i;
    for (i = 0; i < 256; i++) {
        char c = i;
        chars[i] = perm_string(&c, 1);
    }
    for (d = defs; d->cls; d++) {
        Value cls = find_class(d->cls), m;
        int prim = d->special;
        if (!prim) {
            if (nprim >= MAX_PRIMS)
                fatal("too many primitives");
            prim = nprim++;
            prim_table[prim] = d->fn;
        }
        m = perm_obj(cls_Method, METHOD_FIELDS);
        F(m, M_SEL) = intern_c(d->sel);
        F(m, M_OWNER) = cls;
        F(m, M_CODE) = 0;
        F(m, M_LITS) = 0;
        F(m, M_INFO) = d->nargs >= 0 ? d->nargs : (-d->nargs) | MF_REST;
        F(m, M_PRIM) = prim;
        F(m, M_LINES) = 0;
        F(m, M_LINE) = 0;
        method_finish(m);
        class_add_method(cls, F(m, M_SEL), m);
    }
    egret_blockcall = class_lookup(cls_Block, sym_call);
}
