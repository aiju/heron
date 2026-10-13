/* Egret: a small object language for Heron (studies/egret).

   The virtual machine: object model, memory, the compiler and the
   interpreter. The same C builds with gcc on the host and with the
   c_compiler study for draft 1b; both see the same 32-bit values at the
   same addresses, so they behave identically. */

#ifndef EGRET_H
#define EGRET_H

#include <stddef.h>
#include <string.h>

typedef unsigned Value;         /* a tagged 32-bit word */
typedef int SValue;

/* ---- memory -------------------------------------------------------------

   Egret's objects live at fixed addresses of a 1 MB address space. On
   Heron that is RAM itself; on the host it is an array, and P() turns an
   address into a pointer. The map (everything below PERM_LO is the VM's
   own code and C data on Heron):

     0x00020  false, nil, true (three header-only objects, see rt_v1b.s)
     INPUT    the console input: the program, then its own input after __END__
     PERM     classes, methods, bytecode, symbols, literals: never collected
     SCRATCH  the compiler's syntax trees, reset after every statement
     VSTACK   the value stack: receivers, arguments, locals, temporaries
     FRAMES   the frame stack: one record per active method or block
     SEMI     the heap: two semispaces, copied by a Cheney collector
     0xF0000  the C stack, up to the top of RAM */

#ifdef __HERON__
#define MEMBASE ((char *)0)
#else
extern char egret_ram[];
#define MEMBASE egret_ram
#endif

#define P(v)  ((Value *)(MEMBASE + (v)))            /* the words at address v */
#define BP(v) ((unsigned char *)(MEMBASE + (v)))    /* the bytes at address v */
#define V(p)  ((Value)((char *)(p) - MEMBASE))       /* back to an address */

#define RAM_SIZE   0x100000
#define INPUT_LO   0x28000      /* the program's source and input, as read */
#define INPUT_HI   0x30000
#define PERM_LO    0x30000
#define PERM_HI    0x5C000
#define SCRATCH_LO 0x5C000
#define SCRATCH_HI 0x64000
#define VSTACK_LO  0x64000
#define VSTACK_HI  0x6C000
#define FRAMES_LO  0x6C000
#define FRAMES_HI  0x70000
#define SEMI_LO    0x70000
#define SEMI_SIZE  0x40000
#define SEMI_HI    (SEMI_LO + 2 * SEMI_SIZE)

/* ---- values ---------------------------------------------------------------

   A value is a SmallInt, 2n + 1 (31 bits, low bit set), or the address of
   an object (a multiple of 4). */

#define IS_INT(v)   ((v) & 1)
#define INT(v)      ((SValue)(v) >> 1)
#define MKINT(n)    ((((Value)(n)) << 1) | 1)
#define INT_MIN31   (-0x40000000)
#define INT_MAX31   0x3FFFFFFF
#define FITS31(n)   ((n) >= INT_MIN31 && (n) <= INT_MAX31)

#define FALSE_V     ((Value)0x20)
#define NIL         ((Value)0x28)
#define TRUE_V      ((Value)0x30)
#define FALSY(v)    (((v) | 8) == NIL)      /* nil or false */
#define BOOL(c)     ((c) ? TRUE_V : FALSE_V)

/* ---- objects --------------------------------------------------------------

   word 0  the class (during a collection: the new address + 2, forwarded)
   word 1  size << 12 | hash << 2 | format
   then    the fields (format 0: size values) or bytes (format 1: size bytes) */

#define CLASSW(o)   (P(o)[0])
#define HDRW(o)     (P(o)[1])
#define F(o, i)     (P(o)[2 + (i)])
#define BYTES(o)    (BP(o) + 8)
#define SIZE(o)     (HDRW(o) >> 12)
#define IS_BYTES(o) (HDRW(o) & 1)
#define OBJHASH(o)  ((HDRW(o) >> 2) & 0x3FF)
#define HDR(size, hash, fmt) (((Value)(size) << 12) | ((hash) << 2) | (fmt))
#define CLASS_OF(v) (IS_INT(v) ? cls_Int : CLASSW(v))

/* class objects */
enum {
    C_NAME,         /* String */
    C_SUPER,        /* superclass, or nil */
    C_METHODS,      /* method table: an Array of [selector, method] pairs, open addressing */
    C_NMETHODS,     /* SmallInt: methods in the table */
    C_NIVARS,       /* SmallInt: instance variables, the inherited ones included */
    C_IVARS,        /* Array of the instance variables' names (Symbols) */
    C_KIND,         /* SmallInt: what its instances are (K_ below) */
    CLASS_FIELDS
};

/* what a class's instances are, for allocation and printing */
enum { K_OBJECT, K_INT, K_STRING, K_SYMBOL, K_LIST, K_MAP, K_RANGE, K_BLOCK,
       K_CLASS, K_METHOD, K_ARRAY, K_BOX, K_NIL, K_BOOL };

/* compiled methods and blocks: perm objects, so some fields are raw words */
enum {
    M_SEL,          /* selector (Symbol); for a block, its home method's */
    M_OWNER,        /* the class it's defined in (for super), or nil */
    M_CODE,         /* bytecode (a byte object), 0 for a primitive */
    M_LITS,         /* literals (an Array) */
    M_INFO,         /* raw: nargs | nlocals << 8 | flags << 16 */
    M_PRIM,         /* raw: primitive number, 0 if none */
    M_LINES,        /* line table (a byte object), or 0 */
    M_LINE,         /* raw: first source line */
    /* the same again, ready for the interpreter's fast paths */
    M_CODEP,        /* raw: the address of the first bytecode */
    M_LITSP,        /* raw: the address of the first literal */
    M_NLOCALS,      /* raw: locals to clear on entry */
    M_ARITY,        /* raw: nargs for an Egret method without *rest, 0x100 + nargs
                       for a C primitive without *rest, ARITY_SLOW for anything else */
    METHOD_FIELDS
};
#define ARITY_PRIM 0x100
#define ARITY_SLOW 0xFFFF
#define MI_NARGS(i)   ((i) & 0xFF)
#define MI_NLOCALS(i) (((i) >> 8) & 0xFF)
#define MF_REST    0x10000      /* the last parameter takes the extra arguments as a List */
#define MF_BLOCK   0x20000      /* it's a block */
void method_finish(Value m);    /* fills in the raw fields from the others */

/* closures */
enum { CL_METHOD, CL_SELF, CL_HOME, CL_SERIAL, CL_CAPT };

/* lists, ranges and maps */
enum { L_SIZE, L_ITEMS, LIST_FIELDS };          /* items: an Array */
enum { R_FIRST, R_LAST, RANGE_FIELDS };         /* inclusive */
enum { MAP_COUNT, MAP_USED, MAP_KEYS, MAP_VALS, MAP_INDEX, MAP_FIELDS };

/* errors */
enum { E_MESSAGE, ERROR_FIELDS };

/* ---- the frame stack ------------------------------------------------------

   One record per active method or block call, in FRAMES. A record holds
   addresses, so it is the same on both builds. */

typedef struct Frame {
    Value ip;       /* where the frame continues (saved when it calls) */
    Value bp;       /* its receiver slot in the value stack; args, then locals follow */
    Value method;
    Value serial;   /* 0, or a number unique to this activation once a block
                       made in it needs to find it again (non-local return) */
    Value flags;    /* FR_ */
} Frame;
#define FR_CONSTRUCT 1  /* new: return the receiver, not the result of init */
#define FR_BASE      2  /* the interpreter returns to C after this frame */

/* ---- core classes, symbols, globals --------------------------------------- */

extern Value cls_Object, cls_Class, cls_Nil, cls_Bool, cls_Int, cls_String,
    cls_Symbol, cls_List, cls_Map, cls_Range, cls_Block, cls_Method, cls_Array,
    cls_Box, cls_Error;
extern Value main_obj;

#define MAX_GLOBALS 1024
extern Value globals[MAX_GLOBALS];
extern Value global_names[MAX_GLOBALS];
extern int nglobals;
int global_index(Value name);   /* finds or makes a global */

/* the symbols the VM itself uses */
extern Value sym_init, sym_to_s, sym_inspect, sym_call, sym_iter, sym_new,
    sym_eq, sym_hash, sym_cmp;

/* ---- allocation and collection (mem.c) ---------------------------------- */

extern Value hp, hlimit;          /* the heap's allocation pointer and limit */
extern Value perm_hp;
extern Value *vm_sp;              /* the value stack's top, for the collector */
extern Value *vstack;             /* its bottom */
extern unsigned gc_count, gc_words;
extern unsigned alloc_count, alloc_words;

void mem_init(void);
Value alloc_obj(Value cls, unsigned nfields);       /* fields nil */
Value alloc_bytes(Value cls, unsigned nbytes);      /* bytes 0 */
Value perm_obj(Value cls, unsigned nfields);
Value perm_bytes(Value cls, unsigned nbytes);
void gc(unsigned need);
void push_root(Value *r);
void pop_roots(int n);
char *scratch_alloc(unsigned n);   /* zeroed */
char *scratch_mark(void);
void scratch_release(char *mark);

/* ---- objects (object.c) --------------------------------------------------- */

Value intern(const char *s, unsigned n);
Value intern_c(const char *s);
Value make_string(const char *s, unsigned n);
Value make_string_c(const char *s);
Value perm_string(const char *s, unsigned n);
Value make_list(unsigned capacity);
void list_push(Value list, Value v);      /* may collect: list is re-read */
Value make_range(SValue first, SValue last);
Value make_class(Value name, Value super, int kind);
Value class_lookup(Value cls, Value sel);
void class_add_method(Value cls, Value sel, Value m);
Value make_error(const char *msg);
Value make_error_v(Value msg);
int str_eq(Value a, Value b);
unsigned str_hash(Value s);
Value class_name(Value cls);
int is_kind(Value v, int kind);
int is_a(Value v, Value cls);
void boot_classes(void);

/* ---- maps (map.c) ---------------------------------------------------------- */

Value map_new(unsigned cap);
Value map_get(Value map, Value key);      /* 0 if absent */
void map_put(Value map, Value key, Value val);
int map_delete(Value map, Value key);
int value_eq(Value a, Value b);           /* ==, for the built-in values */
unsigned value_hash(Value v);

/* ---- integers (bigint.c) --------------------------------------------------- */

Value int_add(Value a, Value b);
Value int_sub(Value a, Value b);
Value int_mul(Value a, Value b);
Value int_divmod(Value a, Value b, int want_mod);   /* floor division */
Value int_neg(Value a);
int int_cmp(Value a, Value b);
Value int_pow(Value a, Value b);
Value int_to_s(Value a, int base);
Value int_from_s(const unsigned char *s, unsigned n);
Value int_and(Value a, Value b);
Value int_or(Value a, Value b);
Value int_xor(Value a, Value b);
Value int_shl(Value a, SValue n);
Value int_shr(Value a, SValue n);
int is_bigint(Value v);
unsigned big_hash(Value v);

/* ---- the compiler (lex.c, parse.c, compile.c) ------------------------------ */

void compile_init(void);
/* Compiles the next top-level statement of the source into a method; 0 at
   the end of the source. Errors are reported and skipped. */
Value compile_next(void);
void compile_source(const char *src, unsigned len, const char *name);
extern int compile_errors;

/* ---- the interpreter (interp.c) -------------------------------------------- */

void interp_init(void);
/* Runs a method with no arguments on main; returns 1 if it finished, 0 if
   an uncaught error ended it. */
int run_toplevel(Value method);
Value send0(Value rcv, Value sel);

/* primitives: args[0] is the receiver; 0 means failure, with prim_error set */
typedef Value (*PrimFn)(Value *args, int argc);
extern Value prim_error;         /* a message String, or an Error to raise */
Value prim_fail(const char *msg);
Value prim_fail_v(Value err);
void prims_init(void);
/* (sized here too: the C compiler gives an array declared with [] the
   size of its declaration, not of its definition) */
#define MAX_PRIMS 160
extern PrimFn prim_table[MAX_PRIMS];
/* the primitives the interpreter itself carries out */
enum { PR_NONE, PR_NEW, PR_CALL, PR_RAISE, PR_SEND, PR_FIRST_C };

/* ---- output and the platform (main.c) -------------------------------------- */

#ifdef __HERON__
typedef unsigned ejmp_buf[10];      /* r8-r14, sp, the return address (rt_v1b.s) */
int ejsetjmp(ejmp_buf b);
void ejlongjmp(ejmp_buf b, int v);
#else
#include <setjmp.h>
typedef jmp_buf ejmp_buf;
#define ejsetjmp(b) setjmp(b)
#define ejlongjmp(b, v) longjmp(b, v)
#endif

void out_char(int c);
void out_str(const char *s);
void out_bytes(const unsigned char *s, unsigned n);
void out_int(SValue n);
void out_flush(void);
void fatal(const char *msg);
unsigned cycles(void);

/* statistics, for the study's measurements */
typedef struct Stats {
    unsigned bytecodes, sends, cache_misses, prim_calls, block_calls,
        int_fast, int_slow, frames_max, nlr;
} Stats;
extern Stats stats;

#endif
