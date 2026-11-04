/* The parser: recursive descent over the declarations and statements,
   precedence climbing over the binary operators. It type-checks as it
   goes, the way C's own early compilers did: every expression node gets
   its type when it is made, arrays become pointers where C says they do,
   pointer arithmetic is scaled by the size of what is pointed to, and
   constant operands are folded.

   Member access, indexing and pointer arithmetic all come down to
   N_DEREF of an address expression, so the code generator sees only two
   kinds of lvalue: a variable and a dereference. */

#include "cc.h"

int nnodes;
int nfuncs;

static struct func *cur;        /* the function being parsed, or 0 */
static int loop_depth;          /* loops around the current statement */
static int breakable;           /* loops the break could leave */

static struct node *expr(void);
static struct node *assign(void);
static struct node *cast_or_unary(void);
static struct node *statement(void);
static struct type *base_type(int *is_static);
static struct type *declarator(struct type *base, struct name **name);

/* ---- tokens ---------------------------------------------------------- */

static int accept(int kind)
{
    if (tok.kind != kind)
        return 0;
    next();
    return 1;
}

/* The token must be this one: an error if not, and a token skipped
   either way, so a parse with errors still ends. */
static void expect(int kind)
{
    if (tok.kind != kind)
        error("unexpected token");
    if (tok.kind != T_EOF)
        next();
}

static struct name *expect_name(void)
{
    struct name *n = tok.name;
    if (tok.kind != T_ID) {
        error("expected an identifier");
        n = intern("_error", 6);
    }
    if (tok.kind != T_EOF)
        next();
    return n;
}

static int starts_type(int kind)
{
    return kind == K_INT || kind == K_CHAR || kind == K_VOID ||
           kind == K_STRUCT || kind == K_ENUM || kind == K_STATIC;
}

/* ---- nodes ----------------------------------------------------------- */

static struct node *new_node(int kind, struct type *t)
{
    struct node *n = func_alloc(sizeof *n);
    memset(n, 0, sizeof *n);
    n->kind = kind;
    n->type = t;
    n->need = -1;
    n->line = tok.line;
    nnodes++;
    return n;
}

static struct node *num(int v)
{
    struct node *n = new_node(N_NUM, ty_int);
    n->val = v;
    return n;
}

static struct node *unop(int kind, struct node *a, struct type *t)
{
    struct node *n = new_node(kind, t);
    n->a = a;
    return n;
}

static struct node *binop(int op, struct node *a, struct node *b, struct type *t)
{
    struct node *n = new_node(N_BIN, t);
    n->op = op;
    n->a = a;
    n->b = b;
    return n;
}

static int is_lvalue(struct node *n)
{
    return (n->kind == N_VAR || n->kind == N_DEREF) &&
           n->type->kind != TY_ARRAY && n->type->kind != TY_FUNC;
}

/* The address of an lvalue (or of an array, which is its own value). */
static struct node *address_of(struct node *n, struct type *t)
{
    if (n->kind == N_DEREF) {
        n->a->type = t;
        return n->a;
    }
    if (n->kind == N_VAR) {
        n->sym->addressed = 1;
        return unop(N_ADDR, n, t);
    }
    error("cannot take the address");
    return n;
}

/* An expression as a value: an array is the address of its first
   element. */
static struct node *rvalue(struct node *n)
{
    if (n->type->kind == TY_ARRAY)
        return address_of(n, pointer_to(n->type->base));
    if (n->type->kind == TY_FUNC || n->type->kind == TY_STRUCT)
        error("not a value");
    return n;
}

/* ---- the operators --------------------------------------------------- */

static int fold(int op, int a, int b)
{
    switch (op) {
    case '+': return a + b;
    case '-': return a - b;
    case '*': return a * b;
    case '/':
    case '%':
        if (b == 0) {
            error("division by zero");
            return 0;
        }
        return op == '/' ? a / b : a % b;
    case '&': return a & b;
    case '|': return a | b;
    case '^': return a ^ b;
    case P_SHL: return a << (b & 31);
    case P_SHR: return a >> (b & 31);
    case '<': return a < b;
    case '>': return a > b;
    case P_LE: return a <= b;
    case P_GE: return a >= b;
    case P_EQ: return a == b;
    case P_NE: return a != b;
    case P_ANDAND: return a && b;
    case P_OROR: return a || b;
    }
    return 0;
}

static int is_compare(int op)
{
    return op == '<' || op == '>' || op == P_LE || op == P_GE ||
           op == P_EQ || op == P_NE;
}

static int is_zero(struct node *n)
{
    return n->kind == N_NUM && n->val == 0;
}

/* n times the size of what a pointer points to. */
static struct node *scale(struct node *n, struct type *ptr)
{
    int size = ptr->base->size;
    if (size == 0)
        error("arithmetic on a pointer to an incomplete type");
    if (size <= 1)
        return n;
    if (n->kind == N_NUM)
        return num(n->val * size);
    return binop('*', n, num(size), ty_int);
}

static struct node *mk_binary(int op, struct node *a, struct node *b)
{
    struct type *ta, *tb;
    a = rvalue(a);
    b = rvalue(b);
    ta = a->type;
    tb = b->type;
    if (a->kind == N_NUM && b->kind == N_NUM)
        return num(fold(op, a->val, b->val));
    if (op == P_ANDAND || op == P_OROR) {
        struct node *n;
        if (!is_scalar(ta) || !is_scalar(tb))
            error("operands of && and || must be scalars");
        n = new_node(op == P_ANDAND ? N_ANDAND : N_OROR, ty_int);
        n->a = a;
        n->b = b;
        return n;
    }
    if (is_compare(op)) {
        if (is_ptr(ta) && is_ptr(tb)) {
            if (!same_type(ta, tb) && ta->base != ty_void && tb->base != ty_void)
                error("comparison of different pointer types");
        } else if (is_ptr(ta) ? !is_zero(b) : is_ptr(tb) ? !is_zero(a)
                   : !is_integer(ta) || !is_integer(tb)) {
            error("comparison of a pointer and an integer");
        }
        return binop(op, a, b, ty_int);
    }
    if (op == '+') {
        if (is_integer(ta) && is_ptr(tb)) {
            struct node *t = a;
            a = b;
            b = t;
            ta = a->type;
            tb = b->type;
        }
        if (is_ptr(ta) && is_integer(tb))
            return binop('+', a, scale(b, ta), ta);
    } else if (op == '-') {
        if (is_ptr(ta) && is_integer(tb))
            return binop('-', a, scale(b, ta), ta);
        if (is_ptr(ta) && is_ptr(tb)) {
            struct node *d;
            if (!same_type(ta, tb))
                error("subtraction of different pointer types");
            d = binop('-', a, b, ty_int);
            return ta->base->size > 1 ? binop('/', d, num(ta->base->size), ty_int) : d;
        }
    }
    if (!is_integer(ta) || !is_integer(tb)) {
        error("operands must be integers");
        return binop(op, a, b, ty_int);
    }
    /* a constant goes on the right of a commutative operator, where
       the code generator can make it an immediate operand */
    if (a->kind == N_NUM && (op == '+' || op == '*' || op == '&' || op == '|' || op == '^')) {
        struct node *t = a;
        a = b;
        b = t;
    }
    /* identities, which the generated source has plenty of */
    if (b->kind == N_NUM) {
        if (b->val == 0 && (op == '+' || op == '-' || op == '|' || op == '^' ||
                            op == P_SHL || op == P_SHR))
            return a;
        if (b->val == 1 && (op == '*' || op == '/'))
            return a;
    }
    return binop(op, a, b, ty_int);
}

/* Can a value of type `from` be assigned to type `to`? */
static int assignable(struct type *to, struct node *from)
{
    struct type *f = from->type;
    if (is_integer(to))
        return is_integer(f);
    if (is_ptr(to)) {
        if (is_ptr(f))
            return same_type(to, f) || to->base == ty_void || f->base == ty_void;
        return is_zero(from);
    }
    return 0;
}

static struct node *mk_assign(int op, struct node *l, struct node *r)
{
    struct node *n;
    if (!is_lvalue(l)) {
        error("not an lvalue");
        return r;
    }
    if (l->type->kind == TY_STRUCT) {
        error("struct assignment");
        return r;
    }
    r = rvalue(r);
    if (op == '=') {
        if (!assignable(l->type, r))
            error("incompatible types in assignment");
    } else if (is_ptr(l->type) && (op == '+' || op == '-')) {
        if (!is_integer(r->type))
            error("pointer step must be an integer");
        r = scale(r, l->type);
    } else if (!is_integer(l->type) || !is_integer(r->type)) {
        error("operands must be integers");
    }
    n = new_node(N_ASSIGN, l->type);
    n->op = op;
    n->a = l;
    n->b = r;
    return n;
}

static struct node *mk_deref(struct node *p)
{
    p = rvalue(p);
    if (!is_ptr(p->type)) {
        error("dereferencing a non-pointer");
        return p;
    }
    if (p->type->base->kind == TY_VOID)
        error("dereferencing a void pointer");
    return unop(N_DEREF, p, p->type->base);
}

static struct node *mk_member(struct node *s, struct name *field, int arrow)
{
    struct field *f;
    struct node *p;
    if (arrow)
        s = mk_deref(s);
    if (s->type->kind != TY_STRUCT || !s->type->complete) {
        error("member of a non-struct");
        return s;
    }
    f = find_field(s->type, field);
    if (!f) {
        error("no such field");
        return s;
    }
    p = address_of(s, pointer_to(s->type));
    if (f->offset)
        p = binop('+', p, num(f->offset), pointer_to(f->type));
    else
        p->type = pointer_to(f->type);
    return unop(N_DEREF, p, f->type);
}

static struct node *mk_incdec(struct node *l, int delta, int post)
{
    struct node *n;
    if (!is_lvalue(l) || !is_scalar(l->type)) {
        error("++ or -- of a non-scalar");
        return l;
    }
    n = new_node(post ? N_POSTINC : N_PREINC, l->type);
    n->a = l;
    n->val = is_ptr(l->type) ? delta * l->type->base->size : delta;
    return n;
}

static struct node *mk_call(struct sym *f)
{
    struct node *n = new_node(N_CALL, f->type->base), **tail = &n->a;
    struct field *param = f->type->fields;
    int nargs = 0;
    expect('(');
    if (tok.kind != ')') {
        do {
            struct node *a = rvalue(assign());
            if (param) {
                if (!assignable(param->type, a))
                    error("incompatible argument");
                param = param->next;
            }
            *tail = a;
            tail = &a->next;
            nargs++;
        } while (accept(','));
    }
    expect(')');
    if (nargs != f->type->len)
        error("wrong number of arguments");
    n->sym = f;
    n->val = nargs;
    if (cur)
        cur->calls = 1;
    return n;
}

/* ---- expressions ----------------------------------------------------- */

/* A use of a variable, counted for the register allocator: a use in a
   loop counts 8 times one outside it, as in lcc. */
static struct node *var_ref(struct sym *s)
{
    struct node *n = new_node(N_VAR, s->type);
    int d = loop_depth < 3 ? loop_depth : 3;
    n->sym = s;
    s->uses += 1 << (3 * d);
    return n;
}

static struct node *primary(void)
{
    struct node *n;
    struct sym *s;
    switch (tok.kind) {
    case T_NUM:
        n = num(tok.val);
        next();
        return n;
    case T_STR:
        n = new_node(N_STR, pointer_to(ty_char));
        n->val = tok.val;
        next();
        return n;
    case T_ID:
        s = lookup(tok.name, 0);
        if (!s) {
            error("undeclared identifier");
            next();
            return num(0);
        }
        next();
        if (s->kind == S_CONST)
            return num(s->val);
        if (s->kind == S_FUNC) {
            if (tok.kind != '(') {
                error("a function is only called");
                return num(0);
            }
            return mk_call(s);
        }
        return var_ref(s);
    case '(':
        next();
        n = expr();
        expect(')');
        return n;
    }
    error("expected an expression");
    if (tok.kind != T_EOF)
        next();
    return num(0);
}

static struct node *postfix(void)
{
    struct node *n = primary();
    for (;;) {
        if (accept('[')) {
            struct node *i = expr();
            expect(']');
            n = mk_deref(mk_binary('+', n, i));
        } else if (accept('.')) {
            n = mk_member(n, expect_name(), 0);
        } else if (accept(P_ARROW)) {
            n = mk_member(n, expect_name(), 1);
        } else if (accept(P_INC)) {
            n = mk_incdec(n, 1, 1);
        } else if (accept(P_DEC)) {
            n = mk_incdec(n, -1, 1);
        } else {
            return n;
        }
    }
}

/* A type name, in a cast or sizeof: a base type and stars. */
static struct type *type_name(void)
{
    int st;
    struct type *t = base_type(&st);
    while (accept('*'))
        t = pointer_to(t);
    return t;
}

static struct node *unary(void)
{
    struct node *n;
    switch (tok.kind) {
    case '-':
        next();
        n = rvalue(cast_or_unary());
        if (n->kind == N_NUM)
            return num(-n->val);
        if (!is_integer(n->type))
            error("negation of a non-integer");
        return unop(N_NEG, n, ty_int);
    case '!':
        next();
        n = rvalue(cast_or_unary());
        if (n->kind == N_NUM)
            return num(!n->val);
        return unop(N_NOT, n, ty_int);
    case '~':
        next();
        n = rvalue(cast_or_unary());
        if (n->kind == N_NUM)
            return num(~n->val);
        return unop(N_BNOT, n, ty_int);
    case '*':
        next();
        return mk_deref(cast_or_unary());
    case '&':
        next();
        n = cast_or_unary();
        if (n->kind != N_VAR && !is_lvalue(n))
            error("& of a non-lvalue");
        return address_of(n, pointer_to(n->type));
    case P_INC:
        next();
        return mk_incdec(unary(), 1, 0);
    case P_DEC:
        next();
        return mk_incdec(unary(), -1, 0);
    case K_SIZEOF:
        next();
        if (tok.kind == '(' && starts_type(peek())) {
            struct type *t;
            next();
            t = type_name();
            expect(')');
            return num(t->size);
        }
        return num(unary()->type->size);
    }
    return postfix();
}

static struct node *cast_or_unary(void)
{
    if (tok.kind == '(' && starts_type(peek())) {
        struct type *t;
        struct node *n;
        next();
        t = type_name();
        expect(')');
        n = rvalue(cast_or_unary());
        if (!is_scalar(t) || !is_scalar(n->type)) {
            error("cast of a non-scalar");
            return n;
        }
        if (n->kind == N_NUM)
            return t == ty_char ? num(n->val & 255) : n;
        return unop(N_CAST, n, t);
    }
    return unary();
}

/* Binary operators by precedence, loosest first; 0 for anything else. */
static int precedence(int kind)
{
    switch (kind) {
    case P_OROR:  return 1;
    case P_ANDAND: return 2;
    case '|':     return 3;
    case '^':     return 4;
    case '&':     return 5;
    case P_EQ: case P_NE: return 6;
    case '<': case '>': case P_LE: case P_GE: return 7;
    case P_SHL: case P_SHR: return 8;
    case '+': case '-': return 9;
    case '*': case '/': case '%': return 10;
    }
    return 0;
}

static struct node *binary(int prec)
{
    struct node *n = cast_or_unary();
    int p;
    while ((p = precedence(tok.kind)) >= prec) {
        int op = tok.kind;
        next();
        n = mk_binary(op, n, binary(p + 1));
    }
    return n;
}

static struct node *conditional(void)
{
    struct node *c = binary(1), *n, *a, *b;
    if (!accept('?'))
        return c;
    a = rvalue(expr());
    expect(':');
    b = rvalue(conditional());
    c = rvalue(c);
    if (c->kind == N_NUM)
        return c->val ? a : b;
    if (!(is_integer(a->type) && is_integer(b->type)) && !assignable(a->type, b))
        error("the arms of ?: differ in type");
    n = new_node(N_COND, is_ptr(a->type) ? a->type : b->type);
    n->a = c;
    n->b = a;
    n->c = b;
    return n;
}

/* The assignment operators, as the binary operator they apply. */
static int assign_op(int kind)
{
    switch (kind) {
    case '=':     return '=';
    case P_ADDEQ: return '+';
    case P_SUBEQ: return '-';
    case P_MULEQ: return '*';
    case P_DIVEQ: return '/';
    case P_MODEQ: return '%';
    case P_ANDEQ: return '&';
    case P_OREQ:  return '|';
    case P_XOREQ: return '^';
    case P_SHLEQ: return P_SHL;
    case P_SHREQ: return P_SHR;
    }
    return 0;
}

static struct node *assign(void)
{
    struct node *l = conditional();
    int op = assign_op(tok.kind);
    if (!op)
        return l;
    next();
    return mk_assign(op, l, assign());
}

static struct node *expr(void)
{
    struct node *n = assign();
    while (accept(',')) {
        struct node *c = new_node(N_COMMA, 0);
        c->a = n;
        c->b = assign();
        c->type = c->b->type;
        n = c;
    }
    return n;
}

static int const_expr(void)
{
    struct node *n = conditional();
    if (n->kind != N_NUM) {
        error("expected a constant");
        return 0;
    }
    return n->val;
}

/* ---- declarations ---------------------------------------------------- */

static void struct_fields(struct type *t)
{
    struct field **tail = &t->fields;
    if (t->complete)
        error("struct defined twice");
    while (tok.kind != '}' && tok.kind != T_EOF) {
        int st;
        struct type *base = base_type(&st);
        do {
            struct name *n;
            struct field *f = perm_alloc(sizeof *f);
            f->type = declarator(base, &n);
            f->name = n;
            f->next = 0;
            if (f->type->size == 0)
                error("field of incomplete type");
            *tail = f;
            tail = &f->next;
        } while (accept(','));
        expect(';');
    }
    expect('}');
    struct_layout(t);
}

static void enum_body(void)
{
    int v = 0;
    expect('{');
    while (tok.kind == T_ID) {
        struct sym *s = declare(tok.name, S_CONST, ty_int);
        next();
        if (accept('='))
            v = const_expr();
        s->val = v++;
        if (!accept(','))
            break;
    }
    expect('}');
}

static struct type *base_type(int *is_static)
{
    struct type *t = ty_int;
    *is_static = accept(K_STATIC);
    switch (tok.kind) {
    case K_INT:  next(); return ty_int;
    case K_CHAR: next(); return ty_char;
    case K_VOID: next(); return ty_void;
    case K_ENUM:
        next();
        if (tok.kind == T_ID)
            next();             /* the tag names nothing we need */
        if (tok.kind == '{')
            enum_body();
        return ty_int;
    case K_STRUCT: {
        struct name *tag;
        struct sym *s;
        next();
        tag = expect_name();
        s = lookup(tag, 1);
        if (!s || (tok.kind == '{' && s->level != scope_level())) {
            s = declare(tag, S_TAG, new_struct(tag));
        }
        t = s->type;
        if (accept('{'))
            struct_fields(t);
        return t;
    }
    }
    error("expected a type");
    return t;
}

static struct type *params(int *n)
{
    struct field *list = 0, **tail = &list;
    *n = 0;
    if (tok.kind == K_VOID && peek() == ')') {
        next();
        next();
        return func_type(0, 0, 0);
    }
    while (tok.kind != ')' && tok.kind != T_EOF) {
        int st;
        struct field *f = perm_alloc(sizeof *f);
        f->type = declarator(base_type(&st), &f->name);
        if (f->type->kind == TY_ARRAY)
            f->type = pointer_to(f->type->base);
        if (!is_scalar(f->type))
            error("parameters must be scalars");
        f->next = 0;
        *tail = f;
        tail = &f->next;
        if (++*n > MAXPARAMS)
            error("too many parameters");
        if (!accept(','))
            break;
    }
    expect(')');
    return func_type(0, list, *n);
}

/* Stars, a name, and array dimensions or a parameter list. */
static struct type *declarator(struct type *base, struct name **name)
{
    struct type *t = base;
    int dims[8], ndims = 0;
    while (accept('*'))
        t = pointer_to(t);
    *name = expect_name();
    if (tok.kind == '(') {
        int n;
        struct type *f;
        next();
        f = params(&n);
        f->base = t;
        return f;
    }
    while (accept('[')) {
        int d = const_expr();
        if (d <= 0)
            error("array of no elements");
        if (ndims < 8)
            dims[ndims++] = d;
        expect(']');
    }
    while (ndims > 0)
        t = array_of(t, dims[--ndims]);
    if (t->kind == TY_VOID)
        error("void variable");
    return t;
}

/* A global's initializer: a constant, a string, or a list of them in
   braces, as a list of nodes. */
static struct node *initializer(void)
{
    struct node *list, **tail = &list, *n;
    if (tok.kind == T_STR) {
        n = new_node(N_STR, pointer_to(ty_char));
        n->val = tok.val;
        next();
        return n;
    }
    if (!accept('{'))
        return num(const_expr());
    list = 0;
    while (tok.kind != '}' && tok.kind != T_EOF) {
        if (tok.kind == T_STR) {
            n = new_node(N_STR, pointer_to(ty_char));
            n->val = tok.val;
            next();
        } else {
            n = num(const_expr());
        }
        *tail = n;
        tail = &n->next;
        if (!accept(','))
            break;
    }
    expect('}');
    n = new_node(N_BLOCK, 0);
    n->a = list;
    return n;
}

/* ---- statements ------------------------------------------------------ */

static void add_local(struct sym *s)
{
    s->local_next = cur->locals;
    cur->locals = s;
    cur->nlocals++;
}

/* A local declaration: its initializers become assignments, appended to
   the block's statements at *tail. Returns the new tail. */
static struct node **local_decl(struct node **tail)
{
    int st;
    struct type *base = base_type(&st);
    if (st)
        error("static locals are not supported");
    if (tok.kind == ';') {      /* a struct or enum declaration */
        next();
        return tail;
    }
    do {
        struct name *name;
        struct type *t = declarator(base, &name);
        struct sym *s;
        if (t->kind == TY_FUNC || t->size == 0) {
            error("bad local");
            t = ty_int;
        }
        s = declare(name, S_VAR, t);
        add_local(s);
        if (accept('=')) {
            int uses = s->uses;
            struct node *v = var_ref(s), *init;
            s->uses = uses;     /* the initialization isn't a use */
            init = new_node(N_EXPR, 0);
            init->a = mk_assign('=', v, assign());
            *tail = init;
            tail = &init->next;
        }
    } while (accept(','));
    expect(';');
    return tail;
}

static struct node *block(void)
{
    struct node *n = new_node(N_BLOCK, 0), **tail = &n->a;
    expect('{');
    scope_enter();
    while (tok.kind != '}' && tok.kind != T_EOF) {
        if (starts_type(tok.kind)) {
            tail = local_decl(tail);
        } else {
            struct node *s = statement();
            *tail = s;
            tail = &s->next;
        }
    }
    scope_exit();
    expect('}');
    return n;
}

static struct node *condition(void)
{
    struct node *c;
    expect('(');
    c = rvalue(expr());
    expect(')');
    if (!is_scalar(c->type))
        error("condition must be a scalar");
    return c;
}

static struct node *loop_body(void)
{
    struct node *s;
    breakable++;
    s = statement();
    breakable--;
    return s;
}

static struct node *statement(void)
{
    struct node *n;
    switch (tok.kind) {
    case '{':
        return block();
    case K_IF:
        next();
        n = new_node(N_IF, 0);
        n->a = condition();
        n->b = statement();
        if (accept(K_ELSE))
            n->c = statement();
        return n;
    case K_WHILE:
        next();
        n = new_node(N_WHILE, 0);
        loop_depth++;
        n->a = condition();
        n->b = loop_body();
        loop_depth--;
        return n;
    case K_DO:
        next();
        n = new_node(N_DO, 0);
        loop_depth++;
        n->b = loop_body();
        expect(K_WHILE);
        n->a = condition();
        loop_depth--;
        expect(';');
        return n;
    case K_FOR:
        next();
        n = new_node(N_FOR, 0);
        expect('(');
        if (tok.kind != ';')
            n->a = expr();
        expect(';');
        loop_depth++;
        if (tok.kind != ';')
            n->b = rvalue(expr());
        expect(';');
        if (tok.kind != ')')
            n->c = expr();
        expect(')');
        n->d = loop_body();
        loop_depth--;
        return n;
    case K_RETURN: {
        struct type *rt = cur->sym->type->base;
        next();
        n = new_node(N_RETURN, 0);
        if (tok.kind != ';') {
            n->a = rvalue(expr());
            if (rt->kind == TY_VOID || !assignable(rt, n->a))
                error("bad return value");
        } else if (rt->kind != TY_VOID) {
            error("return without a value");
        }
        expect(';');
        return n;
    }
    case K_BREAK:
    case K_CONTINUE:
        n = new_node(tok.kind == K_BREAK ? N_BREAK : N_CONTINUE, 0);
        if (!breakable)
            error("break or continue outside a loop");
        next();
        expect(';');
        return n;
    case ';':
        next();
        return new_node(N_EMPTY, 0);
    }
    n = new_node(N_EXPR, 0);
    n->a = expr();
    expect(';');
    return n;
}

/* ---- the program ----------------------------------------------------- */

static void function(struct sym *s)
{
    struct field *p;
    int i = 0;
    if (s->defined)
        error("function defined twice");
    s->defined = 1;
    cur = func_alloc(sizeof *cur);
    memset(cur, 0, sizeof *cur);
    cur->sym = s;
    scope_enter();
    for (p = s->type->fields; p; p = p->next) {
        struct sym *a = declare(p->name, S_VAR, p->type);
        a->sclass = SC_PARAM;
        a->val = i++;
        add_local(a);
    }
    cur->body = block();
    scope_exit();
    gen_function(cur);
    cur = 0;
    nfuncs++;
}

static void external(void)
{
    int is_static;
    struct type *base = base_type(&is_static);
    if (accept(';'))
        return;                 /* a struct or enum declaration */
    do {
        struct name *name;
        struct type *t = declarator(base, &name);
        struct sym *s;
        if (t->kind == TY_FUNC) {
            s = declare(name, S_FUNC, t);
            s->is_static = is_static;
            if (tok.kind == '{') {
                function(s);
                return;
            }
        } else {
            struct node *init = 0;
            s = declare(name, S_VAR, t);
            s->is_static = is_static;
            if (t->size == 0)
                error("variable of incomplete type");
            if (accept('='))
                init = initializer();
            s->defined = 1;
            gen_global(s, init);
        }
    } while (accept(','));
    expect(';');
}

void parse_program(void)
{
    while (tok.kind != T_EOF) {
        external();
        func_free();
    }
    gen_finish();
}
