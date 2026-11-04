/* A small C compiler: the benchmark's stand-in for a toolchain running
   on Heron itself.

   It compiles a subset of C (int, char, void, pointers, arrays, structs,
   enums; functions of up to four parameters; if, while, do, for, break,
   continue and return; C's expressions with their precedence) to draft
   2 assembly text, in the style of the Heron C compiler's output. It is
   a one-pass compiler in the manner of lcc or the early Unix compilers:

   - lex.c:   the lexer, with identifiers interned in a hash table;
   - sym.c:   types, and the symbol table: a hash table with scopes;
   - parse.c: a recursive-descent parser that type-checks as it goes and
              builds each function's syntax tree in an arena;
   - gen.c:   the code generator: register variables chosen by use
              counts, expression temporaries allocated in Sethi-Ullman
              order and spilled to the frame, operands folded into
              draft 2's addressing modes;
   - peep.c:  a peephole optimiser over each function's assembly text,
              as Unix's c2 was;
   - main.c:  the driver, the output buffers and the results.

   A function is parsed, generated, optimised and written out before the
   next one is read, and its arena is then reset, so memory holds one
   function's tree at a time. */

#ifndef CC_H
#define CC_H

#include <stdarg.h>
#include <string.h>

/* ---- limits ---------------------------------------------------------- */

#define NTEMPS     6        /* expression temporaries, r1-r6 */
#define NREGVARS   6        /* register variables, r8-r13 */
#define MAXPARAMS  4        /* all in registers, r1-r4 */
#define MAXLINES   1024     /* assembly lines in one function */
#define MAXSTRINGS 2048     /* string literals in the program */

/* ---- tokens ---------------------------------------------------------- */

/* A token is a character for the one-character punctuators, or one of
   these. */
enum {
    T_EOF = 256, T_ID, T_NUM, T_STR,
    /* keywords */
    K_INT, K_CHAR, K_VOID, K_STRUCT, K_ENUM, K_IF, K_ELSE, K_WHILE, K_DO,
    K_FOR, K_RETURN, K_BREAK, K_CONTINUE, K_SIZEOF, K_STATIC,
    /* the punctuators of two or three characters */
    P_EQ, P_NE, P_LE, P_GE, P_ANDAND, P_OROR, P_SHL, P_SHR, P_INC, P_DEC,
    P_ARROW, P_ADDEQ, P_SUBEQ, P_MULEQ, P_DIVEQ, P_MODEQ, P_ANDEQ, P_OREQ,
    P_XOREQ, P_SHLEQ, P_SHREQ,
    T_LAST
};

/* An identifier, interned: two names are the same if their pointers are. */
struct name {
    struct name *next;          /* in its hash bucket */
    unsigned hash;
    int len;
    int kw;                     /* its keyword's token, or 0 */
    char *str;
};

struct token {
    int kind;
    int val;                    /* a number's value; a string's index */
    struct name *name;          /* an identifier's name */
    int line;
};

struct strlit {
    char *s;
    int len;
    int label;                  /* its label once written out, or 0 */
};

extern struct token tok;
extern struct strlit strings[];
extern int nstrings;
extern int ntokens;
extern int nlines;

void lex_init(const unsigned char *src, unsigned len);
void next(void);
int peek(void);
struct name *intern(const char *s, int len);
const char *tokname(int kind);
unsigned hash_bytes(const char *s, int len);

/* ---- types ----------------------------------------------------------- */

enum { TY_VOID, TY_CHAR, TY_INT, TY_PTR, TY_ARRAY, TY_STRUCT, TY_FUNC };

/* A struct's field, or a function's parameter. */
struct field {
    struct field *next;
    struct name *name;
    struct type *type;
    int offset;
};

struct type {
    int kind;
    int size, align;            /* on Heron: pointers and ints are 4 bytes */
    struct type *base;          /* what a pointer points to, an array's
                                   element, a function's result */
    int len;                    /* an array's length; a function's
                                   number of parameters */
    struct field *fields;       /* a struct's fields; a function's
                                   parameters */
    struct name *tag;           /* a struct's tag */
    struct type *ptr;           /* the pointer to this type, made once */
    int complete;               /* a struct whose fields are known */
};

extern struct type *ty_void, *ty_char, *ty_int, *ty_charp;

struct type *pointer_to(struct type *t);
struct type *array_of(struct type *t, int n);
struct type *func_type(struct type *ret, struct field *params, int n);
struct type *new_struct(struct name *tag);
void struct_layout(struct type *t);
struct field *find_field(struct type *t, struct name *n);
int is_scalar(struct type *t);
int is_integer(struct type *t);
int is_ptr(struct type *t);
int same_type(struct type *a, struct type *b);

/* ---- symbols --------------------------------------------------------- */

enum { S_VAR, S_FUNC, S_CONST, S_TAG };
enum { SC_GLOBAL, SC_LOCAL, SC_PARAM };

struct sym {
    struct sym *next;           /* in its hash bucket */
    struct sym *scope_next;     /* in its scope, newest first */
    struct sym *local_next;     /* in its function's locals */
    struct name *name;
    int kind;                   /* S_* */
    int sclass;                 /* SC_*, for a variable */
    int level;                  /* scope depth: 0 is file scope */
    struct type *type;
    int val;                    /* an enum constant's value; a
                                   parameter's number */
    int offset;                 /* a local's place in the frame */
    int reg;                    /* a register variable's register, or 0 */
    int uses;                   /* uses weighted by loop depth */
    int addressed;              /* its address is taken */
    int defined;                /* a function with a body, or a
                                   global with storage */
    int order;                  /* declaration order, to break ties */
    int is_static;
};

extern int nsyms;

void sym_init(void);
void scope_enter(void);
void scope_exit(void);
int scope_level(void);
struct sym *lookup(struct name *n, int tag);
struct sym *declare(struct name *n, int kind, struct type *t);

/* ---- the syntax tree ------------------------------------------------- */

enum {
    /* expressions */
    N_NUM, N_STR, N_VAR, N_BIN, N_ANDAND, N_OROR, N_COND, N_ASSIGN,
    N_NEG, N_NOT, N_BNOT, N_DEREF, N_ADDR, N_PREINC, N_POSTINC, N_CALL,
    N_CAST, N_COMMA,
    /* statements */
    N_BLOCK, N_IF, N_WHILE, N_DO, N_FOR, N_RETURN, N_BREAK, N_CONTINUE,
    N_EXPR, N_EMPTY
};

struct node {
    int kind;
    int op;                     /* N_BIN's and N_ASSIGN's operator: a
                                   token ('+', P_SHL, ...); '=' for a
                                   plain assignment */
    struct type *type;
    struct node *a, *b, *c, *d; /* operands; a statement's parts */
    struct node *next;          /* in a list: statements, arguments */
    struct sym *sym;            /* N_VAR's variable, N_CALL's function */
    int val;                    /* N_NUM's value, N_STR's string, an
                                   increment's step */
    int need;                   /* registers to evaluate it, or -1 */
    int line;
};

/* A function, parsed, for the code generator. */
struct func {
    struct sym *sym;
    struct node *body;
    struct sym *locals;         /* parameters and locals, newest first */
    int nlocals;
    int calls;                  /* it calls something */
};

extern int nnodes;
extern int nerrors;
extern int nfuncs;

void parse_program(void);
void error(const char *msg);

/* ---- arenas ---------------------------------------------------------- */

void *perm_alloc(int n);        /* for the whole compilation */
void *func_alloc(int n);        /* for one function */
void func_free(void);

/* ---- code generation and output -------------------------------------- */

/* An operand of an instruction, as gen.c folds it. */
enum { O_REG, O_IMM, O_MEM, O_SYM };
struct operand {
    int kind;
    int reg;                    /* O_REG; O_MEM's base, or -1 */
    int index, scale;           /* O_MEM's index register (or -1) */
    int off;                    /* O_IMM's value; O_MEM's displacement */
    struct name *sym;           /* O_MEM's symbol (absolute), or 0; O_SYM */
    int size;                   /* a memory operand's size: 1 or 4 */
    int slot;                   /* the spill slot it reads, or -1 */
};

void gen_function(struct func *f);
void gen_global(struct sym *s, struct node *init);
void gen_finish(void);

/* The current function's assembly, a line at a time. */
extern char *lines[];
extern int nlines_fn;
void emit(const char *fmt, ...);
char *format(char *dst, const char *fmt, va_list ap);
char *keep_line(const char *text);
void data_emit(const char *fmt, ...);
void text_flush(void);

int peephole(void);             /* returns the number of changes */

extern int ninsns, npeep;

#endif
