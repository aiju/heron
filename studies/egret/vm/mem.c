/* Memory: the permanent space, the compiler's scratch space, and the heap,
   two semispaces with a Cheney copying collector.

   Nothing in the permanent space points into the heap: the compiler makes
   only immutable objects there (classes, methods, symbols, literal strings
   and numbers), and the mutable places that can hold heap objects (the
   globals) are roots. So a collection needs no write barrier. */

#include "egret.h"

Value hp, hlimit;
Value perm_hp;
Value *vm_sp;
Value *vstack;
unsigned gc_count, gc_words;
unsigned alloc_count, alloc_words;

static Value cur_lo, cur_hi;            /* the semispace in use */
static char *scratch_base, *scratch_ptr, *scratch_end;
#ifndef __HERON__
static char host_scratch[2 * (SCRATCH_HI - SCRATCH_LO)];
#endif
static unsigned hash_seed = 1;

#define MAX_ROOTS 64
static Value *roots[MAX_ROOTS];
static int nroots;

void push_root(Value *r)
{
    if (nroots >= MAX_ROOTS)
        fatal("too many temporary roots");
    roots[nroots++] = r;
}

void pop_roots(int n) { nroots -= n; }

void mem_init(void)
{
    perm_hp = PERM_LO;
#ifdef __HERON__
    scratch_ptr = scratch_base = (char *)BP(SCRATCH_LO);
    scratch_end = (char *)BP(SCRATCH_HI);
#else
    /* host pointers are twice as big, so the trees are too */
    scratch_ptr = scratch_base = host_scratch;
    scratch_end = host_scratch + sizeof host_scratch;
#endif
    cur_lo = SEMI_LO;
    cur_hi = SEMI_LO + SEMI_SIZE;
    hp = cur_lo;
    hlimit = cur_hi;
    vstack = P(VSTACK_LO);
    vm_sp = vstack - 1;
}

static unsigned next_hash(void)
{
    hash_seed = hash_seed * 1103515245 + 12345;
    return (hash_seed >> 16) & 0x3FF;
}

static unsigned obj_bytes(Value o)
{
    unsigned n = SIZE(o);
    if (IS_BYTES(o))
        return 8 + ((n + 3) & ~3u);
    return 8 + 4 * n;
}

Value alloc_obj(Value cls, unsigned nfields)
{
    unsigned bytes = 8 + 4 * nfields;
    Value o, *f, *end;
    if (hp + bytes > hlimit)
        gc(bytes);
    o = hp;
    hp += bytes;
#ifdef EGRET_STATS
    alloc_count++;
    alloc_words += bytes >> 2;
#endif
    f = P(o);
    f[0] = cls;
    f[1] = HDR(nfields, next_hash(), 0);
    end = f + 2 + nfields;
    for (f += 2; f < end; f++)
        *f = NIL;
    return o;
}

Value alloc_bytes(Value cls, unsigned nbytes)
{
    unsigned bytes = 8 + ((nbytes + 3) & ~3u);
    Value o;
    if (hp + bytes > hlimit)
        gc(bytes);
    o = hp;
    hp += bytes;
#ifdef EGRET_STATS
    alloc_count++;
    alloc_words += bytes >> 2;
#endif
    P(o)[0] = cls;
    P(o)[1] = HDR(nbytes, next_hash(), 1);
    memset(BYTES(o), 0, (nbytes + 3) & ~3u);
    return o;
}

Value perm_obj(Value cls, unsigned nfields)
{
    unsigned bytes = 8 + 4 * nfields, i;
    Value o = perm_hp;
    if (o + bytes > PERM_HI)
        fatal("out of permanent space");
    perm_hp += bytes;
    P(o)[0] = cls;
    P(o)[1] = HDR(nfields, next_hash(), 0);
    for (i = 0; i < nfields; i++)
        F(o, i) = NIL;
    return o;
}

Value perm_bytes(Value cls, unsigned nbytes)
{
    unsigned bytes = 8 + ((nbytes + 3) & ~3u);
    Value o = perm_hp;
    if (o + bytes > PERM_HI)
        fatal("out of permanent space");
    perm_hp += bytes;
    P(o)[0] = cls;
    P(o)[1] = HDR(nbytes, next_hash(), 1);
    memset(BYTES(o), 0, (nbytes + 3) & ~3u);
    return o;
}

char *scratch_alloc(unsigned n)
{
    char *p = scratch_ptr;
    n = (n + 7) & ~7u;
    if ((unsigned)(scratch_end - p) < n)
        fatal("out of compiler space (a statement or method is too big)");
    scratch_ptr += n;
    memset(p, 0, n);
    return p;
}

char *scratch_mark(void) { return scratch_ptr; }
void scratch_release(char *mark) { scratch_ptr = mark; }

/* ---- the collector -------------------------------------------------------- */

static Value from_lo, from_hi;

static Value forward(Value v)
{
    Value w, n;
    unsigned bytes;
    if (IS_INT(v) || v < from_lo || v >= from_hi)
        return v;
    w = CLASSW(v);
    if (w & 2)
        return w - 2;
    bytes = obj_bytes(v);
    n = hp;
    hp += bytes;
    memcpy(P(n), P(v), bytes);
    CLASSW(v) = n + 2;
    return n;
}

void gc(unsigned need)
{
    Value scan, *p;
    int i;
    unsigned before = hp - cur_lo;
    from_lo = cur_lo;
    from_hi = cur_hi;
    cur_lo = from_lo == SEMI_LO ? SEMI_LO + SEMI_SIZE : SEMI_LO;
    cur_hi = cur_lo + SEMI_SIZE;
    hp = cur_lo;
    hlimit = cur_hi;
    gc_count++;

    for (i = 0; i < nglobals; i++)
        globals[i] = forward(globals[i]);
    for (p = vstack; p <= vm_sp; p++)
        *p = forward(*p);
    for (i = 0; i < nroots; i++)
        *roots[i] = forward(*roots[i]);
    prim_error = forward(prim_error);

    for (scan = cur_lo; scan < hp; scan += obj_bytes(scan)) {
        if (!IS_BYTES(scan)) {
            Value *f = &F(scan, 0), *end = f + SIZE(scan);
            for (; f < end; f++)
                *f = forward(*f);
        }
    }
    gc_words += (hp - cur_lo) >> 2;
    (void)before;
    if (hp + need > hlimit)
        fatal("out of memory");
}
