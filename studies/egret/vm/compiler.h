/* The compiler's own declarations: tokens, the syntax tree, variables, and
   the bytecode (which interp.c shares). */

#ifndef COMPILER_H
#define COMPILER_H

#include "egret.h"

/* ---- bytecode ---------------------------------------------------------------

   A stack machine. Operands follow the opcode: b = one byte, w = two bytes
   (little-endian, signed for jumps: relative to the next instruction). */

enum {
    OP_HALT,
    OP_PUSH_NIL, OP_PUSH_TRUE, OP_PUSH_FALSE, OP_PUSH_SELF, OP_PUSH_BSELF,
    OP_PUSH_INT,        /* b: signed */
    OP_PUSH_LIT,        /* b */
    OP_PUSH_LOCAL,      /* b: slot (0 is the receiver, or a block's closure) */
    OP_STORE_LOCAL,     /* b: store the top, keep it */
    OP_POP_LOCAL,       /* b: store the top and pop it */
    OP_PUSH_BOXED, OP_STORE_BOXED,          /* b: a slot holding a Box */
    OP_PUSH_CAPT, OP_STORE_CAPT,            /* b: a closure's captured value */
    OP_PUSH_CAPT_BOXED, OP_STORE_CAPT_BOXED,/* b: a captured Box */
    OP_PUSH_IVAR, OP_STORE_IVAR,            /* b: of self */
    OP_PUSH_BIVAR, OP_STORE_BIVAR,          /* b: of a block's self */
    OP_PUSH_GLOBAL, OP_STORE_GLOBAL,        /* b: a literal, the global's cell address */
    OP_POP, OP_DUP,
    OP_SEND,            /* b: selector literal, b: argument count */
    OP_SEND_SUPER,      /* b, b */
    /* sends with a fast path for SmallInts (or Lists, for AT and AT_PUT) */
    OP_ADD, OP_SUB, OP_MUL, OP_DIV, OP_MOD, OP_LT, OP_LE, OP_GT, OP_GE,
    OP_EQ, OP_AT, OP_AT_PUT,
    OP_BAND, OP_BOR, OP_BXOR, OP_SHL, OP_SHR,
    OP_NOT,
    OP_JUMP,            /* w */
    OP_JUMP_FALSE, OP_JUMP_TRUE,            /* w: pop the condition */
    OP_JUMP_FALSE_OR_POP, OP_JUMP_TRUE_OR_POP,  /* w: keep it if jumping */
    OP_CLOSURE,         /* b: method literal, b: n, then n (kind, index) byte pairs */
    OP_RETURN,          /* from this frame */
    OP_RETURN_NLR,      /* from a block's home method */
    OP_MAKE_LIST,       /* b: elements */
    OP_MAKE_MAP,        /* b: pairs */
    OP_MAKE_RANGE,      /* b: 1 if the end is excluded */
    OP_CONCAT,          /* b: strings */
    OP_RANGE_PREP,      /* b: slot, b: 1 if exclusive. first, last -> slot, slot + 1 */
    OP_RANGE_NEXT,      /* b: slot, w: exit. push the next number or jump */
    OP_ITER_PREP,       /* b: slot. iterable -> slot, slot + 1 */
    OP_ITER_NEXT,       /* b: slot, w: exit */
    OP_TRY,             /* w: the handler */
    OP_END_TRY,
    OP_MAKE_BOX,        /* b: slot */
    OP_INC_LOCAL,       /* b: slot, b: signed step. slot += step for a SmallInt, skipping
                           the 7 bytes of general code that follow (PUSH_LOCAL, PUSH_INT,
                           ADD, POP_LOCAL), which run otherwise */
    NOPCODES
};

/* closure capture kinds */
enum { CK_LOCAL, CK_CAPT };

/* ---- tokens ------------------------------------------------------------------ */

enum {
    T_EOF, T_NEWLINE, T_INT, T_STRING, T_SYMBOL, T_IDENT, T_IVAR,
    /* keywords */
    T_AND, T_ATTR, T_BREAK, T_CATCH, T_CLASS, T_CONTINUE, T_DEF, T_DO, T_ELIF,
    T_ELSE, T_END, T_FALSE, T_FOR, T_IF, T_IN, T_NIL, T_NOT, T_OR, T_RETURN,
    T_SELF, T_SUPER, T_THEN, T_TRUE, T_TRY, T_WHILE,
    /* punctuation */
    T_LPAREN, T_RPAREN, T_LBRACK, T_RBRACK, T_LBRACE, T_RBRACE, T_COMMA,
    T_DOT, T_COLON, T_SEMI, T_ASSIGN, T_EQ, T_NE, T_LT, T_LE, T_GT, T_GE,
    T_CMP, T_PLUS, T_MINUS, T_STAR, T_SLASH, T_PERCENT, T_POW, T_AMP, T_PIPE,
    T_CARET, T_SHL, T_SHR, T_TILDE, T_DOTDOT, T_DOTDOTLT,
    T_PLUS_EQ, T_MINUS_EQ, T_STAR_EQ, T_SLASH_EQ, T_PERCENT_EQ,
    T_AMP_EQ, T_PIPE_EQ, T_CARET_EQ, T_SHL_EQ, T_SHR_EQ,
    NTOKENS
};

typedef struct Lexer {
    const char *src, *p, *end;
    const char *file;
    int line;
    int tok, prev;
    const char *tstart;     /* the token's text */
    unsigned tlen;
    int tline;
    Value tval;             /* T_INT: the number, T_SYMBOL/T_IDENT/T_IVAR: the name */
    int nest[64];           /* the open brackets */
    int depth;
} Lexer;

void lex_init(Lexer *lx, const char *src, unsigned len, int line, const char *file);
int lex_next(Lexer *lx);
const char *tok_name(int t);

/* ---- the syntax tree -------------------------------------------------------- */

enum {
    N_INT, N_LIT, N_NIL, N_TRUE, N_FALSE, N_SELF,
    N_LOCAL,        /* var */
    N_CAPT,         /* var (through capt) */
    N_GLOBAL,       /* n: index */
    N_IVAR,         /* n: index */
    N_ASSIGN,       /* a: target, b: value */
    N_OPASSIGN,     /* a: target, b: value, n: operator token */
    N_SEND,         /* a: receiver (0: self), b: args, sel, n: argc */
    N_SUPER,        /* b: args, n: argc (-1: the same arguments) */
    N_BINOP,        /* a, b, n: token */
    N_INDEX,        /* a: object, b: index */
    N_AND, N_OR, N_NOT,
    N_IF,           /* a: cond, b: then, c: else */
    N_WHILE,        /* a: cond, b: body */
    N_FOR,          /* a: target, b: iterable, c: body */
    N_BREAK, N_CONTINUE,
    N_RETURN,       /* a: value or 0 */
    N_SEQ,          /* a: first statement (linked by next) */
    N_BLOCK,        /* func */
    N_LIST,         /* a: elements, n: count */
    N_MAP,          /* a: keys and values alternating, n: pairs */
    N_RANGE,        /* a, b, n: 1 if exclusive */
    N_INTERP,       /* a: parts, n: count */
    N_TRY,          /* a: body, b: handler, var: the exception's variable (or 0) */
    NNODES
};

struct Func;
struct Var;
struct Capt;

#define NF_BARE  1          /* N_SEND: a bare name, which an assignment makes a variable */
#define NF_PAREN 2          /* N_SEND: had an argument list */

typedef struct Node {
    int kind;
    int line;
    int flags;              /* NF_ */
    struct Node *a, *b, *c;
    struct Node *next;
    Value val;              /* N_INT: the value; N_LIT: the literal; N_SEND: the selector */
    int n;
    struct Var *var;
    struct Capt *capt;
    struct Func *func;
} Node;

typedef struct Var {
    Value name;
    int slot;
    int captured;           /* used by an inner block */
    int nassign;            /* assignments (a parameter starts with none) */
    int assign_in_loop;
    int assign_inner;       /* assigned by an inner block */
    int boxed;              /* decided once the whole method is parsed */
    int is_param;
    int defining;           /* its first assignment's value is being parsed */
    int captured_early;     /* captured while defining (a recursive block) */
    struct Func *func;
    struct Var *next;
} Var;

/* a variable of an outer function that a block uses */
typedef struct Capt {
    Var *var;
    int index;
    int from_kind;          /* CK_LOCAL: the parent's local; CK_CAPT: the parent's capture */
    int from_index;         /* the parent's slot or capture index */
    struct Capt *next;
} Capt;

typedef struct Func {
    struct Func *outer;
    int is_block;
    int toplevel;           /* a top-level statement: its variables are globals */
    Var *vars;
    int nparams;
    int rest;               /* the last parameter takes the rest */
    int nslots;             /* 1 + parameters + locals */
    Capt *capts;
    int ncapts;
    int loop_depth;
    Node *body;
    Value sel;
    Value owner;            /* the class, for ivars and super; nil at top level */
    int class_side;
    int line;
    struct Func *all;       /* every function of the method being compiled */
} Func;

/* parse.c */
void fatal_at(Lexer *lx, int line, const char *msg);
/* compile.c */
Value gen_method(Func *f);
void decide_boxes(Func *all);
Value perm_literal(Value v);

#endif
