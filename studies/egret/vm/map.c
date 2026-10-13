/* Maps: hash tables that keep their keys in insertion order, like
   Python's dicts. The entries are two Arrays, keys and values, in the order
   they were added (a deleted entry's key becomes 0); the index is an open
   addressing table of entry numbers + 1.

   Keys are compared with value_eq: numbers and strings by value, anything
   else by identity. */

#include "egret.h"

int value_eq(Value a, Value b)
{
    if (a == b)
        return 1;
    if (IS_INT(a) || IS_INT(b))
        return 0;
    if (CLASSW(a) == cls_String && CLASSW(b) == cls_String)
        return str_eq(a, b);
    if (is_bigint(a) && is_bigint(b))
        return int_cmp(a, b) == 0;
    return 0;
}

unsigned value_hash(Value v)
{
    if (IS_INT(v))
        return (unsigned)INT(v) * 2654435761u;
    if (CLASSW(v) == cls_String || CLASSW(v) == cls_Symbol)
        return str_hash(v);
    if (is_bigint(v))
        return big_hash(v);
    return OBJHASH(v) * 2654435761u;
}

#define IDX(m) ((unsigned *)BYTES(F(m, MAP_INDEX)))
#define IDXSIZE(m) (SIZE(F(m, MAP_INDEX)) / 4)

static Value new_index(unsigned slots)
{
    return alloc_bytes(cls_Array, 4 * slots);
}

Value map_new(unsigned cap)
{
    Value m = alloc_obj(cls_Map, MAP_FIELDS), t;
    unsigned slots = 8;
    if (cap < 4)
        cap = 4;
    while (slots < 2 * cap)
        slots *= 2;
    push_root(&m);
    F(m, MAP_COUNT) = MKINT(0);
    F(m, MAP_USED) = MKINT(0);
    t = alloc_obj(cls_Array, cap);
    F(m, MAP_KEYS) = t;
    t = alloc_obj(cls_Array, cap);
    F(m, MAP_VALS) = t;
    t = new_index(slots);
    F(m, MAP_INDEX) = t;
    pop_roots(1);
    return m;
}

/* the index slot for key: its entry (slot value > 0), or the empty slot */
static unsigned find(Value m, Value key, unsigned h)
{
    unsigned *idx = IDX(m), mask = IDXSIZE(m) - 1, i;
    Value keys = F(m, MAP_KEYS);
    for (i = h & mask; idx[i]; i = (i + 1) & mask) {
        Value k = F(keys, idx[i] - 1);
        if (k && value_eq(k, key))
            return i;
    }
    return i;
}

Value map_get(Value m, Value key)
{
    unsigned i = find(m, key, value_hash(key));
    unsigned e = IDX(m)[i];
    return e ? F(F(m, MAP_VALS), e - 1) : 0;
}

/* Rebuild with room for at least `cap` entries, dropping deleted ones. */
static void rebuild(Value m, unsigned cap)
{
    Value keys, vals, idx, ok, ov;
    unsigned used = INT(F(m, MAP_USED)), n = 0, i, slots = 8, mask;
    while (slots < 2 * cap)
        slots *= 2;
    push_root(&m);
    keys = alloc_obj(cls_Array, cap);
    push_root(&keys);
    vals = alloc_obj(cls_Array, cap);
    push_root(&vals);
    idx = new_index(slots);
    pop_roots(3);
    mask = slots - 1;
    ok = F(m, MAP_KEYS);
    ov = F(m, MAP_VALS);
    for (i = 0; i < used; i++) {
        Value k = F(ok, i);
        unsigned j;
        if (!k)
            continue;
        F(keys, n) = k;
        F(vals, n) = F(ov, i);
        for (j = value_hash(k) & mask; ((unsigned *)BYTES(idx))[j]; j = (j + 1) & mask)
            ;
        ((unsigned *)BYTES(idx))[j] = n + 1;
        n++;
    }
    F(m, MAP_KEYS) = keys;
    F(m, MAP_VALS) = vals;
    F(m, MAP_INDEX) = idx;
    F(m, MAP_USED) = MKINT(n);
    F(m, MAP_COUNT) = MKINT(n);
}

void map_put(Value m, Value key, Value val)
{
    unsigned h = value_hash(key), i = find(m, key, h), e = IDX(m)[i], used;
    if (e) {
        F(F(m, MAP_VALS), e - 1) = val;
        return;
    }
    used = INT(F(m, MAP_USED));
    if (used >= SIZE(F(m, MAP_KEYS))) {
        unsigned count = INT(F(m, MAP_COUNT));
        push_root(&m);
        push_root(&key);
        push_root(&val);
        rebuild(m, count * 2 + 4);
        pop_roots(3);
        used = INT(F(m, MAP_USED));
        i = find(m, key, h);
    }
    F(F(m, MAP_KEYS), used) = key;
    F(F(m, MAP_VALS), used) = val;
    IDX(m)[i] = used + 1;
    F(m, MAP_USED) = MKINT(used + 1);
    F(m, MAP_COUNT) = MKINT(INT(F(m, MAP_COUNT)) + 1);
}

int map_delete(Value m, Value key)
{
    unsigned i = find(m, key, value_hash(key)), e = IDX(m)[i];
    if (!e)
        return 0;
    /* the index keeps pointing at the dead entry; find() skips key 0 */
    F(F(m, MAP_KEYS), e - 1) = 0;
    F(F(m, MAP_VALS), e - 1) = NIL;
    F(m, MAP_COUNT) = MKINT(INT(F(m, MAP_COUNT)) - 1);
    return 1;
}
