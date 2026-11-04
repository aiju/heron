/* Types and the symbol table.

   Types are made once and kept for the whole compilation; a pointer type
   is cached in the type it points to, so `pointer_to(t)` is the same
   object every time and types compare by pointer, structs by identity.
   Sizes are Heron's: char 1, int and pointers 4.

   The symbol table is one hash table of chains for every scope. A
   declaration goes at the head of its name's chain and of its scope's
   list; leaving a scope takes its symbols off again, newest first, and
   each is then at the head of its chain, since the symbols of any inner
   scope have already gone. A lookup finds the innermost declaration
   first. Struct tags share the table, told apart by their kind. */

#include "cc.h"

struct type *ty_void, *ty_char, *ty_int, *ty_charp;

static struct type *new_type(int kind, int size, int align, struct type *base)
{
    struct type *t = perm_alloc(sizeof *t);
    memset(t, 0, sizeof *t);
    t->kind = kind;
    t->size = size;
    t->align = align;
    t->base = base;
    return t;
}

struct type *pointer_to(struct type *t)
{
    if (!t->ptr)
        t->ptr = new_type(TY_PTR, 4, 4, t);
    return t->ptr;
}

struct type *array_of(struct type *t, int n)
{
    struct type *a = new_type(TY_ARRAY, t->size * n, t->align, t);
    a->len = n;
    return a;
}

struct type *func_type(struct type *ret, struct field *params, int n)
{
    struct type *f = new_type(TY_FUNC, 0, 1, ret);
    f->fields = params;
    f->len = n;
    return f;
}

struct type *new_struct(struct name *tag)
{
    struct type *t = new_type(TY_STRUCT, 0, 1, 0);
    t->tag = tag;
    return t;
}

/* Gives a struct's fields their offsets, each aligned for its type, and
   the struct its size, a multiple of its alignment. */
void struct_layout(struct type *t)
{
    struct field *f;
    int off = 0, align = 1;
    for (f = t->fields; f; f = f->next) {
        int a = f->type->align;
        off = (off + a - 1) & -a;
        f->offset = off;
        off += f->type->size;
        if (a > align)
            align = a;
    }
    t->size = (off + align - 1) & -align;
    t->align = align;
    t->complete = 1;
}

struct field *find_field(struct type *t, struct name *n)
{
    struct field *f;
    for (f = t->fields; f; f = f->next)
        if (f->name == n)
            return f;
    return 0;
}

int is_integer(struct type *t)
{
    return t->kind == TY_INT || t->kind == TY_CHAR;
}

int is_ptr(struct type *t)
{
    return t->kind == TY_PTR;
}

int is_scalar(struct type *t)
{
    return is_integer(t) || is_ptr(t);
}

int same_type(struct type *a, struct type *b)
{
    while (a->kind == b->kind && (a->kind == TY_PTR || a->kind == TY_ARRAY)) {
        a = a->base;
        b = b->base;
    }
    if (a->kind != b->kind)
        return 0;
    return a->kind != TY_STRUCT || a == b;
}

/* ---- the symbol table ------------------------------------------------ */

#define SYMBUCKETS 256
#define MAXDEPTH   32

static struct sym *buckets[SYMBUCKETS];
static struct sym *scopes[MAXDEPTH];    /* each scope's symbols */
static int level;
int nsyms;

void sym_init(void)
{
    ty_void = new_type(TY_VOID, 0, 1, 0);
    ty_char = new_type(TY_CHAR, 1, 1, 0);
    ty_int = new_type(TY_INT, 4, 4, 0);
    ty_charp = pointer_to(ty_char);
    level = 0;
    scopes[0] = 0;
}

int scope_level(void)
{
    return level;
}

void scope_enter(void)
{
    if (level == MAXDEPTH - 1) {
        error("blocks nested too deeply");
        return;
    }
    scopes[++level] = 0;
}

void scope_exit(void)
{
    struct sym *s;
    for (s = scopes[level]; s; s = s->scope_next) {
        struct sym **pp = &buckets[s->name->hash & (SYMBUCKETS - 1)];
        if (*pp == s) {
            *pp = s->next;
        } else {                /* never, if scopes nest properly */
            while (*pp && *pp != s)
                pp = &(*pp)->next;
            if (*pp)
                *pp = s->next;
        }
    }
    level--;
}

struct sym *lookup(struct name *n, int tag)
{
    struct sym *s;
    for (s = buckets[n->hash & (SYMBUCKETS - 1)]; s; s = s->next)
        if (s->name == n && (s->kind == S_TAG) == tag)
            return s;
    return 0;
}

/* A new symbol in the current scope. A second declaration of a name in
   the same scope is an error, except that a function or a global may be
   declared again with the same type: the first symbol is returned. */
struct sym *declare(struct name *n, int kind, struct type *t)
{
    struct sym *s = lookup(n, kind == S_TAG);
    struct sym **pp;
    if (s && s->level == level) {
        if (level == 0 && s->kind == kind && same_type(s->type, t))
            return s;
        error("redeclared");
        return s;
    }
    s = level == 0 ? perm_alloc(sizeof *s) : func_alloc(sizeof *s);
    memset(s, 0, sizeof *s);
    s->name = n;
    s->kind = kind;
    s->type = t;
    s->level = level;
    s->sclass = level == 0 ? SC_GLOBAL : SC_LOCAL;
    s->order = nsyms++;
    pp = &buckets[n->hash & (SYMBUCKETS - 1)];
    s->next = *pp;
    *pp = s;
    s->scope_next = scopes[level];
    scopes[level] = s;
    return s;
}
