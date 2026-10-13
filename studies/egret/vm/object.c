/* Objects: symbols, strings, lists, ranges, errors, and classes with their
   method tables. */

#include "egret.h"

Value cls_Object, cls_Class, cls_Nil, cls_Bool, cls_Int, cls_String,
    cls_Symbol, cls_List, cls_Map, cls_Range, cls_Block, cls_Method, cls_Array,
    cls_Box, cls_Error;
Value main_obj;

Value *globals;
Value global_names[MAX_GLOBALS];
int nglobals;

Value sym_init, sym_to_s, sym_inspect, sym_call, sym_iter, sym_new,
    sym_eq, sym_hash, sym_cmp;

/* ---- strings and symbols --------------------------------------------------- */

unsigned str_hash(Value s)
{
    unsigned h = 2166136261u, i, n = SIZE(s);
    unsigned char *b = BYTES(s);
    for (i = 0; i < n; i++)
        h = (h ^ b[i]) * 16777619u;
    return h;
}

int str_eq(Value a, Value b)
{
    unsigned n = SIZE(a);
    return n == SIZE(b) && memcmp(BYTES(a), BYTES(b), n) == 0;
}

Value make_string(const char *s, unsigned n)
{
    Value o = alloc_bytes(cls_String, n);
    memcpy(BYTES(o), s, n);
    return o;
}

Value make_string_c(const char *s) { return make_string(s, strlen(s)); }

Value perm_string(const char *s, unsigned n)
{
    Value o = perm_bytes(cls_String, n);
    memcpy(BYTES(o), s, n);
    return o;
}

#define SYMTAB_SIZE 4096
static Value symtab[SYMTAB_SIZE];
static int nsyms;

Value intern(const char *s, unsigned n)
{
    unsigned h = 2166136261u, i;
    Value sym;
    for (i = 0; i < n; i++)
        h = (h ^ (unsigned char)s[i]) * 16777619u;
    for (i = h & (SYMTAB_SIZE - 1); symtab[i]; i = (i + 1) & (SYMTAB_SIZE - 1)) {
        sym = symtab[i];
        if (SIZE(sym) == n && memcmp(BYTES(sym), s, n) == 0)
            return sym;
    }
    if (nsyms >= SYMTAB_SIZE * 3 / 4)
        fatal("too many symbols");
    sym = perm_bytes(cls_Symbol, n);
    memcpy(BYTES(sym), s, n);
    symtab[i] = sym;
    nsyms++;
    return sym;
}

Value intern_c(const char *s) { return intern(s, strlen(s)); }

/* ---- lists and ranges ------------------------------------------------------- */

Value make_list(unsigned capacity)
{
    Value l = alloc_obj(cls_List, LIST_FIELDS), items;
    push_root(&l);
    items = alloc_obj(cls_Array, capacity < 4 ? 4 : capacity);
    pop_roots(1);
    F(l, L_SIZE) = MKINT(0);
    F(l, L_ITEMS) = items;
    return l;
}

void list_push(Value list, Value v)
{
    unsigned n = INT(F(list, L_SIZE));
    Value items = F(list, L_ITEMS);
    if (n >= SIZE(items)) {
        Value bigger;
        push_root(&list);
        push_root(&v);
        bigger = alloc_obj(cls_Array, 2 * n + 4);
        pop_roots(2);
        items = F(list, L_ITEMS);
        memcpy(&F(bigger, 0), &F(items, 0), 4 * n);
        F(list, L_ITEMS) = items = bigger;
    }
    F(items, n) = v;
    F(list, L_SIZE) = MKINT(n + 1);
}

Value make_range(SValue first, SValue last)
{
    Value r = alloc_obj(cls_Range, RANGE_FIELDS);
    F(r, R_FIRST) = MKINT(first);
    F(r, R_LAST) = MKINT(last);
    return r;
}

Value make_error_v(Value msg)
{
    Value e;
    push_root(&msg);
    e = alloc_obj(cls_Error, INT(F(cls_Error, C_NIVARS)));
    pop_roots(1);
    F(e, E_MESSAGE) = msg;
    return e;
}

Value make_error(const char *msg) { return make_error_v(make_string_c(msg)); }

/* ---- globals -------------------------------------------------------------- */

int global_index(Value name)
{
    int i;
    for (i = 0; i < nglobals; i++)
        if (global_names[i] == name)
            return i;
    if (nglobals >= MAX_GLOBALS)
        fatal("too many globals");
    global_names[nglobals] = name;
    globals[nglobals] = 0;          /* undefined until assigned */
    return nglobals++;
}

/* ---- classes ----------------------------------------------------------------- */

static Value new_table(unsigned cap)
{
    Value t = perm_obj(cls_Array, 2 * cap);
    unsigned i;
    for (i = 0; i < 2 * cap; i++)
        F(t, i) = 0;
    return t;
}

#define SELHASH(s) (((s) >> 3) ^ ((s) >> 11))

Value class_lookup(Value cls, Value sel)
{
    while (cls != NIL && cls) {
        Value t = F(cls, C_METHODS);
        unsigned mask = SIZE(t) / 2 - 1, i;
        for (i = SELHASH(sel) & mask; F(t, 2 * i); i = (i + 1) & mask)
            if (F(t, 2 * i) == sel)
                return F(t, 2 * i + 1);
        cls = F(cls, C_SUPER);
    }
    return 0;
}

static Value class_lookup_here(Value cls, Value sel)
{
    Value t = F(cls, C_METHODS);
    unsigned mask = SIZE(t) / 2 - 1, i;
    for (i = SELHASH(sel) & mask; F(t, 2 * i); i = (i + 1) & mask)
        if (F(t, 2 * i) == sel)
            return F(t, 2 * i + 1);
    return 0;
}

static void table_put(Value t, Value sel, Value m)
{
    unsigned mask = SIZE(t) / 2 - 1, i;
    for (i = SELHASH(sel) & mask; F(t, 2 * i) && F(t, 2 * i) != sel; i = (i + 1) & mask)
        ;
    F(t, 2 * i) = sel;
    F(t, 2 * i + 1) = m;
}

void interp_flush_sel(Value sel);

void class_add_method(Value cls, Value sel, Value m)
{
    Value t = F(cls, C_METHODS);
    unsigned cap = SIZE(t) / 2, n = INT(F(cls, C_NMETHODS));
    if ((n + 1) * 4 > cap * 3) {
        Value bigger = new_table(2 * cap);
        unsigned i;
        for (i = 0; i < cap; i++)
            if (F(t, 2 * i))
                table_put(bigger, F(t, 2 * i), F(t, 2 * i + 1));
        F(cls, C_METHODS) = t = bigger;
    }
    if (!class_lookup_here(cls, sel))
        F(cls, C_NMETHODS) = MKINT(n + 1);
    table_put(t, sel, m);
    interp_flush_sel(sel);
}

Value class_name(Value cls) { return F(cls, C_NAME); }

void method_finish(Value m)
{
    Value info = F(m, M_INFO), prim = F(m, M_PRIM);
    F(m, M_CODEP) = F(m, M_CODE) ? V(BYTES(F(m, M_CODE))) : 0;
    F(m, M_LITSP) = F(m, M_LITS) ? V(&F(F(m, M_LITS), 0)) : 0;
    F(m, M_NLOCALS) = MI_NLOCALS(info);
    if (info & MF_REST)
        F(m, M_ARITY) = ARITY_SLOW;
    else if (!prim)
        F(m, M_ARITY) = MI_NARGS(info);
    else if (prim >= PR_FIRST_C)
        F(m, M_ARITY) = ARITY_PRIM + MI_NARGS(info);
    else
        F(m, M_ARITY) = ARITY_SLOW;
}

static Value new_class_obj(Value meta, Value name, Value super, int kind)
{
    Value c = perm_obj(meta, CLASS_FIELDS);
    F(c, C_NAME) = name;
    F(c, C_SUPER) = super;
    F(c, C_METHODS) = new_table(8);
    F(c, C_NMETHODS) = MKINT(0);
    F(c, C_KIND) = MKINT(kind);
    if (super != NIL) {
        F(c, C_NIVARS) = F(super, C_NIVARS);
        F(c, C_IVARS) = F(super, C_IVARS);
    } else {
        F(c, C_NIVARS) = MKINT(0);
        F(c, C_IVARS) = perm_obj(cls_Array, 0);
    }
    return c;
}

/* A class and its metaclass: the metaclass holds the class methods, and
   inherits from the superclass's metaclass (from Class, at the root). */
Value make_class(Value name, Value super, int kind)
{
    Value meta_super = super == NIL ? cls_Class : CLASSW(super);
    char buf[80];
    unsigned n = SIZE(name) < 60 ? SIZE(name) : 60;
    Value meta, c;
    memcpy(buf, BYTES(name), n);
    memcpy(buf + n, " class", 6);
    meta = new_class_obj(cls_Class, perm_string(buf, n + 6), meta_super, K_CLASS);
    F(meta, C_NIVARS) = MKINT(CLASS_FIELDS);
    c = new_class_obj(meta, name, super, kind);
    return c;
}

int is_a(Value v, Value cls)
{
    Value c = CLASS_OF(v);
    while (c != NIL) {
        if (c == cls)
            return 1;
        c = F(c, C_SUPER);
    }
    return 0;
}

int is_kind(Value v, int kind)
{
    return !IS_INT(v) && INT(F(CLASSW(v), C_KIND)) == kind;
}

/* The core classes. Class and Object come first, by hand, because every
   class needs a metaclass and every metaclass is an instance of Class. */
static Value core_class(const char *name, Value super, int kind)
{
    Value c = make_class(intern_c(name), super, kind);
    globals[global_index(intern_c(name))] = c;
    return c;
}

void boot_classes(void)
{
    Value obj_meta, class_meta;
    globals = &F(perm_obj(0, MAX_GLOBALS), 0);
    memset(globals, 0, 4 * MAX_GLOBALS);
    /* bootstrap: Object, Class and Array exist before any metaclass */
    cls_Array = perm_obj(0, CLASS_FIELDS);
    CLASSW(cls_Array) = 0;
    cls_Symbol = perm_obj(0, CLASS_FIELDS);
    cls_String = perm_obj(0, CLASS_FIELDS);
    cls_Class = perm_obj(0, CLASS_FIELDS);
    cls_Object = perm_obj(0, CLASS_FIELDS);
    obj_meta = perm_obj(cls_Class, CLASS_FIELDS);
    class_meta = perm_obj(cls_Class, CLASS_FIELDS);
    {
        /* fill them in now that Array and Class exist */
        Value cs[5], metas[5];
        int i;
        cs[0] = cls_Object; cs[1] = cls_Class; cs[2] = cls_String;
        cs[3] = cls_Symbol; cs[4] = cls_Array;
        for (i = 0; i < 5; i++) {
            F(cs[i], C_METHODS) = new_table(8);
            F(cs[i], C_NMETHODS) = MKINT(0);
            F(cs[i], C_IVARS) = perm_obj(cls_Array, 0);
            F(cs[i], C_NIVARS) = MKINT(0);
            F(cs[i], C_KIND) = MKINT(K_OBJECT);
        }
        F(cls_Object, C_SUPER) = NIL;
        F(cls_Class, C_SUPER) = cls_Object;
        F(cls_String, C_SUPER) = cls_Object;
        F(cls_Symbol, C_SUPER) = cls_String;
        F(cls_Array, C_SUPER) = cls_Object;
        F(cls_Class, C_NIVARS) = MKINT(CLASS_FIELDS);
        F(cls_Class, C_KIND) = MKINT(K_CLASS);
        F(cls_String, C_KIND) = MKINT(K_STRING);
        F(cls_Symbol, C_KIND) = MKINT(K_SYMBOL);
        F(cls_Array, C_KIND) = MKINT(K_ARRAY);
        for (i = 0; i < 5; i++)
            P(cs[i])[1] = HDR(CLASS_FIELDS, 0, 0);
        /* names, now that symbols can be made */
        F(cls_Object, C_NAME) = intern_c("Object");
        F(cls_Class, C_NAME) = intern_c("Class");
        F(cls_String, C_NAME) = intern_c("String");
        F(cls_Symbol, C_NAME) = intern_c("Symbol");
        F(cls_Array, C_NAME) = intern_c("Array");
        /* metaclasses */
        F(obj_meta, C_NAME) = perm_string("Object class", 12);
        F(obj_meta, C_SUPER) = cls_Class;
        F(obj_meta, C_METHODS) = new_table(8);
        F(obj_meta, C_NMETHODS) = MKINT(0);
        F(obj_meta, C_NIVARS) = MKINT(CLASS_FIELDS);
        F(obj_meta, C_IVARS) = F(cls_Object, C_IVARS);
        F(obj_meta, C_KIND) = MKINT(K_CLASS);
        F(class_meta, C_NAME) = perm_string("Class class", 11);
        F(class_meta, C_SUPER) = obj_meta;
        F(class_meta, C_METHODS) = new_table(8);
        F(class_meta, C_NMETHODS) = MKINT(0);
        F(class_meta, C_NIVARS) = MKINT(CLASS_FIELDS);
        F(class_meta, C_IVARS) = F(cls_Object, C_IVARS);
        F(class_meta, C_KIND) = MKINT(K_CLASS);
        CLASSW(cls_Object) = obj_meta;
        CLASSW(cls_Class) = class_meta;
        for (i = 2; i < 5; i++) {
            Value n = F(cs[i], C_NAME);
            char buf[40];
            unsigned len = SIZE(n);
            memcpy(buf, BYTES(n), len);
            memcpy(buf + len, " class", 6);
            metas[i] = perm_obj(cls_Class, CLASS_FIELDS);
            F(metas[i], C_NAME) = perm_string(buf, len + 6);
            F(metas[i], C_SUPER) = CLASSW(F(cs[i], C_SUPER));
            F(metas[i], C_METHODS) = new_table(8);
            F(metas[i], C_NMETHODS) = MKINT(0);
            F(metas[i], C_NIVARS) = MKINT(CLASS_FIELDS);
            F(metas[i], C_IVARS) = F(cls_Object, C_IVARS);
            F(metas[i], C_KIND) = MKINT(K_CLASS);
            CLASSW(cs[i]) = metas[i];
        }
        /* the symbols made before Symbol had its class word */
        for (i = 0; i < SYMTAB_SIZE; i++)
            if (symtab[i])
                CLASSW(symtab[i]) = cls_Symbol;
        for (i = 0; i < 5; i++)
            globals[global_index(F(cs[i], C_NAME))] = cs[i];
    }
    cls_Nil = core_class("Nil", cls_Object, K_NIL);
    cls_Bool = core_class("Bool", cls_Object, K_BOOL);
    cls_Int = core_class("Int", cls_Object, K_INT);
    {
        /* the generic collection methods live in the prelude, on Collection */
        Value coll = core_class("Collection", cls_Object, K_OBJECT);
        cls_List = core_class("List", coll, K_LIST);
        cls_Map = core_class("Map", coll, K_MAP);
        cls_Range = core_class("Range", coll, K_RANGE);
    }
    cls_Block = core_class("Block", cls_Object, K_BLOCK);
    cls_Method = core_class("Method", cls_Object, K_METHOD);
    cls_Box = core_class("Box", cls_Object, K_BOX);
    cls_Error = core_class("Error", cls_Object, K_OBJECT);
    {
        Value iv = perm_obj(cls_Array, 1);
        F(iv, 0) = intern_c("message");
        F(cls_Error, C_IVARS) = iv;
        F(cls_Error, C_NIVARS) = MKINT(ERROR_FIELDS);
    }
    CLASSW(FALSE_V) = cls_Bool;
    CLASSW(TRUE_V) = cls_Bool;
    CLASSW(NIL) = cls_Nil;
    HDRW(FALSE_V) = HDRW(TRUE_V) = HDRW(NIL) = HDR(0, 0, 0);
    main_obj = perm_obj(cls_Object, 0);

    sym_init = intern_c("init");
    sym_to_s = intern_c("to_s");
    sym_inspect = intern_c("inspect");
    sym_call = intern_c("call");
    sym_iter = intern_c("iter");
    sym_new = intern_c("new");
    sym_eq = intern_c("==");
    sym_hash = intern_c("hash");
    sym_cmp = intern_c("<=>");
}
