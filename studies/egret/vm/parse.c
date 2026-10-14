/* The parser: source to syntax trees, one top-level statement, method or
   class at a time, with names resolved as it goes.

   A name is a local variable from its first assignment on (as in Ruby),
   a capture if it's a variable of an enclosing method or block, a global
   if it's Capitalized (or a top-level variable, at the top level), and
   otherwise a message to self. Classes are made while they're parsed, so
   a class exists before the statements after it run. */

#include "compiler.h"

static Lexer main_lexer;
static Lexer *lx = &main_lexer;
static Func *fn;                /* the function being parsed */
static Func *all_funcs;         /* every function of the current method */
static Value cur_class;         /* the class being defined, or 0 */
static int class_is_new;        /* ... by this class statement (so it can take ivars) */
static int no_do;               /* parsing a condition: `do` doesn't start a block */
static ejmp_buf err_jmp;
int compile_errors;

void fatal_at(Lexer *l, int line, const char *msg)
{
    out_str(l && l->file ? l->file : "input");
    out_char(':');
    out_int(line);
    out_str(": error: ");
    out_str(msg);
    out_char('\n');
    compile_errors++;
    ejlongjmp(err_jmp, 1);
}

static void error(const char *msg) { fatal_at(lx, lx->tline, msg); }

static char ebuf[200];

static void errorf(const char *a, const char *b, const char *c)
{
    unsigned n = 0, k;
    const char *parts[3];
    int i;
    parts[0] = a; parts[1] = b; parts[2] = c;
    for (i = 0; i < 3; i++) {
        if (!parts[i])
            continue;
        k = strlen(parts[i]);
        if (n + k >= sizeof ebuf - 1)
            k = sizeof ebuf - 1 - n;
        memcpy(ebuf + n, parts[i], k);
        n += k;
    }
    ebuf[n] = 0;
    error(ebuf);
}

static char namebuf[80];

static const char *sym_text(Value s)
{
    unsigned n = SIZE(s) < 79 ? SIZE(s) : 79;
    memcpy(namebuf, BYTES(s), n);
    namebuf[n] = 0;
    return namebuf;
}

static const char *cur_tok_text(void)
{
    static char buf[24];
    unsigned n;
    if (lx->tok == T_EOF || lx->tok == T_NEWLINE)
        return tok_name(lx->tok);
    n = lx->tlen < 20 ? lx->tlen : 20;
    if (lx->tok == T_STRING)
        return "a string";
    memcpy(buf, lx->tstart, n);
    buf[n] = 0;
    return buf;
}

#define TOK (lx->tok)

static void next(void) { lex_next(lx); }

static int accept(int t)
{
    if (TOK == t) {
        next();
        return 1;
    }
    return 0;
}

static void expect(int t)
{
    if (!accept(t)) {
        static char want[24];
        want[0] = '\'';
        strcpy(want + 1, tok_name(t));
        strcat(want, "' but found '");
        errorf("expected ", want, cur_tok_text());
    }
}

static void skip_nl(void)
{
    while (TOK == T_NEWLINE || TOK == T_SEMI)
        next();
}

static Node *node(int kind)
{
    Node *n = (Node *)scratch_alloc(sizeof(Node));
    n->kind = kind;
    n->line = lx->tline;
    return n;
}

static int is_upper(Value name) { return BYTES(name)[0] >= 'A' && BYTES(name)[0] <= 'Z'; }

static int global_exists(Value name)
{
    int i;
    for (i = 0; i < nglobals; i++)
        if (global_names[i] == name)
            return 1;
    return 0;
}

/* ---- functions and variables ------------------------------------------------ */

static Func *new_func(int is_block)
{
    Func *f = (Func *)scratch_alloc(sizeof(Func));
    f->is_block = is_block;
    f->nslots = 1;
    f->line = lx->tline;
    if (is_block) {
        f->outer = fn;
        f->owner = fn->owner;
        f->sel = fn->sel;
        f->toplevel = fn->toplevel;
        f->class_side = fn->class_side;
    }
    f->all = all_funcs;
    all_funcs = f;
    return f;
}

static Var *find_var(Func *f, Value name)
{
    Var *v;
    for (v = f->vars; v; v = v->next)
        if (v->name == name)
            return v;
    return 0;
}

static Var *new_var(Func *f, Value name)
{
    Var *v = (Var *)scratch_alloc(sizeof(Var));
    v->name = name;
    v->slot = f->nslots++;
    if (f->nslots > 250)
        error("too many variables in one method");
    v->func = f;
    v->next = f->vars;
    f->vars = v;
    return v;
}


/* name in f: CK_LOCAL (a variable of f), CK_CAPT (of an enclosing function,
   captured through every block in between), or -1 */
static int resolve(Func *f, Value name, Var **var, Capt **capt)
{
    Var *v = find_var(f, name), *pv = 0;
    Capt *c, *pc = 0, **tail;
    int k;
    if (v) {
        *var = v;
        return CK_LOCAL;
    }
    if (!f->is_block)
        return -1;
    k = resolve(f->outer, name, &pv, &pc);
    if (k < 0)
        return -1;
    for (tail = &f->capts; (c = *tail) != 0; tail = &c->next)
        if (c->var == pv) {
            *capt = c;
            *var = pv;
            return CK_CAPT;
        }
    c = (Capt *)scratch_alloc(sizeof(Capt));
    c->var = pv;
    c->index = f->ncapts++;
    c->from_kind = k;
    c->from_index = k == CK_LOCAL ? pv->slot : pc->index;
    *tail = c;
    pv->captured = 1;
    if (pv->defining)
        pv->captured_early = 1;
    *capt = c;
    *var = pv;
    return CK_CAPT;
}

/* a variable reference, or 0 if the name isn't a variable */
static Node *name_ref(Value name)
{
    Var *v;
    Capt *c;
    Node *n;
    int k = resolve(fn, name, &v, &c);
    if (k == CK_LOCAL) {
        n = node(N_LOCAL);
        n->var = v;
        return n;
    }
    if (k == CK_CAPT) {
        n = node(N_CAPT);
        n->var = v;
        n->capt = c;
        return n;
    }
    if (is_upper(name) || (fn->toplevel && global_exists(name))) {
        n = node(N_GLOBAL);
        n->n = global_index(name);
        n->val = name;
        return n;
    }
    return 0;
}

/* the target of an assignment to a name that isn't a variable yet */
static Node *define_target(Value name)
{
    Node *n;
    if (is_upper(name) || (fn->toplevel && (!fn->is_block || global_exists(name)))) {
        n = node(N_GLOBAL);
        n->n = global_index(name);
        n->val = name;
        return n;
    }
    n = node(N_LOCAL);
    n->var = new_var(fn, name);
    return n;
}

static void note_assign(Node *t)
{
    if (t->kind == N_LOCAL) {
        t->var->nassign++;
        if (fn->loop_depth)
            t->var->assign_in_loop = 1;
    } else if (t->kind == N_CAPT) {
        t->var->assign_inner = 1;
    }
}

static int ivar_index(Value name)
{
    Value owner = fn->owner, ivars, bigger;
    unsigned i, n;
    if (owner == NIL || !owner || fn->class_side)
        errorf("@", sym_text(name), " outside an instance method");
    ivars = F(owner, C_IVARS);
    n = SIZE(ivars);
    for (i = n; i-- > 0;)
        if (F(ivars, i) == name)
            return i;
    if (owner != cur_class || !class_is_new)
        errorf("can't add @", sym_text(name),
               " to a class defined earlier (give it its instance variables in its first class statement)");
    bigger = perm_obj(cls_Array, n + 1);
    for (i = 0; i < n; i++)
        F(bigger, i) = F(ivars, i);
    F(bigger, n) = name;
    F(owner, C_IVARS) = bigger;
    F(owner, C_NIVARS) = MKINT(n + 1);
    return n;
}

/* ---- expressions --------------------------------------------------------- */

static Node *expr(void);
static Node *statement(void);
static Node *statements(int t1, int t2, int t3);
static Node *block_literal(void);

static Node *append(Node **list, Node *n)
{
    while (*list)
        list = &(*list)->next;
    *list = n;
    return n;
}

/* (args) and a trailing block, if any */
static void call_args(Node *s)
{
    if (TOK == T_LPAREN) {
        next();
        s->flags |= NF_PAREN;
        if (!accept(T_RPAREN)) {
            do {
                append(&s->b, expr());
                s->n++;
            } while (accept(T_COMMA));
            expect(T_RPAREN);
        }
    }
    if (TOK == T_LBRACE || (TOK == T_DO && !no_do)) {
        int saved = no_do;
        no_do = 0;
        append(&s->b, block_literal());
        no_do = saved;
        s->n++;
    }
    if (s->n > 30)
        error("too many arguments");
}

static Node *send_node(Node *rcv, Value sel)
{
    Node *s = node(N_SEND);
    s->a = rcv;
    s->val = sel;
    return s;
}

static char strbuf[4096];

/* A string literal, with escapes and {interpolations}. */
static Node *string_node(void)
{
    const char *s = lx->tstart, *e = s + lx->tlen;
    int raw = lx->tval, line = lx->tline;
    unsigned n = 0;
    Node *parts = 0, *lit;
    int nparts = 0;
    while (s < e) {
        int c = *s++;
        if (c == '\\' && s < e) {
            c = *s++;
            if (raw && c != '\\' && c != '\'') {
                if (n < sizeof strbuf) strbuf[n++] = '\\';
            } else {
                switch (c) {
                case 'n': c = '\n'; break;
                case 't': c = '\t'; break;
                case 'r': c = '\r'; break;
                case '0': c = 0; break;
                case 'e': c = 27; break;
                }
            }
        } else if (c == '\n') {
            line++;
        } else if (c == '{' && !raw) {
            /* an interpolation: flush the text so far, parse the expression */
            const char *start = s;
            int depth = 1;
            Lexer sub, *saved;
            Node *x;
            while (s < e && depth) {
                if (*s == '"' || *s == '\'') {
                    int q = *s++;
                    while (s < e && *s != q) {
                        if (*s == '\\')
                            s++;
                        s++;
                    }
                } else if (*s == '{') {
                    depth++;
                } else if (*s == '}') {
                    depth--;
                }
                s++;
            }
            if (n) {
                lit = node(N_LIT);
                lit->val = perm_string(strbuf, n);
                append(&parts, lit);
                nparts++;
                n = 0;
            }
            lex_init(&sub, start, s - 1 - start, line, lx->file);
            saved = lx;
            lx = &sub;
            next();
            x = expr();
            if (TOK != T_EOF)
                error("expected '}' to end the interpolation");
            lx = saved;
            append(&parts, x);
            nparts++;
            continue;
        }
        if (n >= sizeof strbuf)
            error("string literal too long");
        strbuf[n++] = c;
    }
    next();
    if (n || nparts == 0) {
        lit = node(N_LIT);
        lit->val = perm_string(strbuf, n);
        append(&parts, lit);
        nparts++;
    }
    if (nparts == 1 && parts->kind == N_LIT)
        return parts;
    lit = node(N_INTERP);
    lit->a = parts;
    lit->n = nparts;
    return lit;
}

static Node *list_literal(void)
{
    Node *n;
    next();
    if (accept(T_COLON)) {
        expect(T_RBRACK);
        n = node(N_MAP);
        return n;
    }
    n = node(N_LIST);
    if (accept(T_RBRACK))
        return n;
    append(&n->a, expr());
    if (accept(T_COLON)) {
        n->kind = N_MAP;
        append(&n->a, expr());
        n->n = 1;
        while (accept(T_COMMA)) {
            if (TOK == T_RBRACK)
                break;
            append(&n->a, expr());
            expect(T_COLON);
            append(&n->a, expr());
            n->n++;
        }
    } else {
        n->n = 1;
        while (accept(T_COMMA)) {
            if (TOK == T_RBRACK)
                break;
            append(&n->a, expr());
            n->n++;
        }
    }
    if (n->n > 255)
        error("too many elements in a literal (255 at most)");
    expect(T_RBRACK);
    return n;
}

static void param_list(Func *f, int closer)
{
    do {
        Var *v;
        if (TOK == closer)
            break;
        if (accept(T_STAR))
            f->rest = 1;
        if (TOK != T_IDENT)
            error("expected a parameter name");
        if (find_var(f, lx->tval))
            error("parameter named twice");
        v = new_var(f, lx->tval);
        v->is_param = 1;
        f->nparams++;
        next();
        if (f->rest && TOK != closer)
            error("*rest must be the last parameter");
    } while (accept(T_COMMA));
    expect(closer);
}

static Node *block_literal(void)
{
    int closer = TOK == T_LBRACE ? T_RBRACE : T_END;
    Func *f = new_func(1), *saved = fn;
    Node *n = node(N_BLOCK);
    next();
    fn = f;
    if (accept(T_PIPE))
        param_list(f, T_PIPE);
    f->body = statements(closer, -1, -1);
    expect(closer);
    fn = saved;
    n->func = f;
    return n;
}

static Node *parse_if(void)
{
    Node *n = node(N_IF);
    no_do++;
    n->a = expr();
    no_do--;
    accept(T_THEN);
    n->b = statements(T_ELIF, T_ELSE, T_END);
    if (accept(T_ELIF)) {
        n->c = parse_if();
        return n;
    }
    if (accept(T_ELSE))
        n->c = statements(T_END, -1, -1);
    expect(T_END);
    return n;
}

static Node *loop_body(void)
{
    Node *b;
    fn->loop_depth++;
    b = statements(T_END, -1, -1);
    expect(T_END);
    fn->loop_depth--;
    return b;
}

static Node *loop_target(void)
{
    Node *t;
    if (TOK != T_IDENT)
        error("expected a loop variable");
    t = name_ref(lx->tval);
    if (!t)
        t = define_target(lx->tval);
    if (t->kind != N_LOCAL && t->kind != N_CAPT && t->kind != N_GLOBAL)
        error("bad loop variable");
    next();
    fn->loop_depth++;
    note_assign(t);
    fn->loop_depth--;
    return t;
}

static Node *primary(void)
{
    Node *n;
    Value name;
    switch (TOK) {
    case T_INT:
        if (IS_INT(lx->tval)) {
            n = node(N_INT);
            n->val = lx->tval;
        } else {
            n = node(N_LIT);
            n->val = perm_literal(lx->tval);
        }
        next();
        return n;
    case T_STRING:
        return string_node();
    case T_SYMBOL:
        n = node(N_LIT);
        n->val = lx->tval;
        next();
        return n;
    case T_NIL: next(); return node(N_NIL);
    case T_TRUE: next(); return node(N_TRUE);
    case T_FALSE: next(); return node(N_FALSE);
    case T_SELF: next(); return node(N_SELF);
    case T_IVAR:
        n = node(N_IVAR);
        n->val = lx->tval;
        n->n = ivar_index(lx->tval);
        next();
        return n;
    case T_IDENT:
        name = lx->tval;
        next();
        n = name_ref(name);
        if (n) {
            if (TOK == T_LPAREN) {
                /* calling a block in a variable, or a class: Point(1, 2) */
                Node *s = send_node(n, sym_call);
                call_args(s);
                return s;
            }
            return n;
        }
        n = send_node(0, name);
        call_args(n);
        if (!(n->flags & NF_PAREN) && n->n == 0)
            n->flags |= NF_BARE;
        return n;
    case T_LPAREN:
        next();
        n = expr();
        expect(T_RPAREN);
        return n;
    case T_LBRACK:
        return list_literal();
    case T_LBRACE:
        return block_literal();
    case T_IF:
        next();
        return parse_if();
    case T_WHILE:
        n = node(N_WHILE);
        next();
        no_do++;
        n->a = expr();
        no_do--;
        accept(T_DO);
        n->b = loop_body();
        return n;
    case T_FOR:
        n = node(N_FOR);
        next();
        n->a = loop_target();
        expect(T_IN);
        no_do++;
        n->b = expr();
        no_do--;
        accept(T_DO);
        n->c = loop_body();
        return n;
    case T_TRY:
        n = node(N_TRY);
        next();
        n->a = statements(T_CATCH, T_END, -1);
        if (accept(T_CATCH)) {
            if (TOK == T_IDENT) {
                Node *t = name_ref(lx->tval);
                if (!t)
                    t = define_target(lx->tval);
                note_assign(t);
                n->c = t;
                next();
            }
            n->b = statements(T_END, -1, -1);
        }
        expect(T_END);
        return n;
    case T_SUPER:
        n = node(N_SUPER);
        next();
        if (fn->owner == NIL || !fn->owner)
            error("super outside a method");
        call_args(n);
        if (!(n->flags & NF_PAREN) && n->n == 0)
            n->n = -1;
        return n;
    case T_DEF:
    case T_CLASS:
        error("def and class go at the top level (and def in a class)");
    }
    errorf("expected an expression but found '", cur_tok_text(), "'");
    return 0;
}

static Value method_name_after_dot(void)
{
    Value name;
    if (TOK == T_IDENT)
        name = lx->tval;
    else if (TOK >= T_AND && TOK <= T_WHILE)
        name = intern(lx->tstart, lx->tlen);       /* x.class, x.not ... */
    else
        error("expected a method name after '.'");
    next();
    return name;
}

static Node *postfix(Node *e)
{
    for (;;) {
        if (TOK == T_DOT) {
            Node *s;
            next();
            s = send_node(e, method_name_after_dot());
            call_args(s);
            e = s;
        } else if (TOK == T_LBRACK) {
            Node *x = node(N_INDEX);
            next();
            x->a = e;
            x->b = expr();
            expect(T_RBRACK);
            e = x;
        } else if (TOK == T_LPAREN && e->kind != N_SEND) {
            Node *s = send_node(e, sym_call);
            call_args(s);
            e = s;
        } else {
            return e;
        }
    }
}

static Node *binop(int op, Node *a, Node *b)
{
    Node *n = node(N_BINOP);
    n->n = op;
    n->a = a;
    n->b = b;
    return n;
}

static Node *unary(void);

static Node *power(void)
{
    Node *e = postfix(primary());
    if (TOK == T_POW) {
        int line = lx->tline;
        next();
        e = binop(T_POW, e, unary());
        e->line = line;
    }
    return e;
}

static Node *unary(void)
{
    if (TOK == T_MINUS) {
        Node *e;
        next();
        if (TOK == T_INT && IS_INT(lx->tval)) {
            e = node(N_INT);
            e->val = MKINT(-INT(lx->tval));
            next();
            /* -2 ** 2 is -(2 ** 2), as in Python */
            if (TOK == T_POW) {
                Node *n = node(N_INT);
                n->val = MKINT(-INT(e->val));
                next();
                return send_node(binop(T_POW, postfix(n), unary()), intern_c("neg"));
            }
            return postfix(e);
        }
        e = unary();
        return send_node(e, intern_c("neg"));
    }
    if (TOK == T_TILDE) {
        next();
        return send_node(unary(), intern_c("~"));
    }
    return power();
}

/* the binary operators, loosest first: each level is a list of tokens */
static const int levels[][5] = {
    { T_EQ, T_NE, T_LT, T_LE, -1 },     /* also T_GT, T_GE, T_CMP below */
    { T_DOTDOT, T_DOTDOTLT, -1 },
    { T_PIPE, -1 },
    { T_CARET, -1 },
    { T_AMP, -1 },
    { T_SHL, T_SHR, -1 },
    { T_PLUS, T_MINUS, -1 },
    { T_STAR, T_SLASH, T_PERCENT, -1 },
};
#define NLEVELS 8

static int at_level(int level, int t)
{
    int i;
    if (level == 0 && (t == T_GT || t == T_GE || t == T_CMP))
        return 1;
    for (i = 0; levels[level][i] >= 0; i++)
        if (levels[level][i] == t)
            return 1;
    return 0;
}

static Node *binary(int level)
{
    Node *e;
    if (level == NLEVELS)
        return unary();
    e = binary(level + 1);
    while (at_level(level, TOK)) {
        int op = TOK, line = lx->tline;
        Node *b;
        next();
        b = binary(level + 1);
        if (op == T_DOTDOT || op == T_DOTDOTLT) {
            Node *r = node(N_RANGE);
            r->a = e;
            r->b = b;
            r->n = op == T_DOTDOTLT;
            r->line = line;
            return r;
        }
        if (op == T_NE) {
            Node *x = node(N_NOT);
            x->a = binop(T_EQ, e, b);
            x->a->line = line;
            e = x;
        } else {
            e = binop(op, e, b);
        }
        e->line = line;
    }
    return e;
}

static Node *not_expr(void)
{
    if (TOK == T_NOT) {
        Node *n = node(N_NOT);
        next();
        n->a = not_expr();
        return n;
    }
    return binary(0);
}

static Node *and_expr(void)
{
    Node *e = not_expr();
    while (TOK == T_AND) {
        Node *n = node(N_AND);
        next();
        n->a = e;
        n->b = not_expr();
        e = n;
    }
    return e;
}

static Node *or_expr(void)
{
    Node *e = and_expr();
    while (TOK == T_OR) {
        Node *n = node(N_OR);
        next();
        n->a = e;
        n->b = and_expr();
        e = n;
    }
    return e;
}

static Value setter_name(Value name)
{
    char buf[80];
    unsigned n = SIZE(name) < 78 ? SIZE(name) : 78;
    memcpy(buf, BYTES(name), n);
    buf[n] = '=';
    return intern(buf, n + 1);
}

static Node *expr(void)
{
    Node *lhs = or_expr(), *n;
    int t = TOK, line = lx->tline;
    if (t != T_ASSIGN && !(t >= T_PLUS_EQ && t <= T_SHR_EQ))
        return lhs;
    next();
    if (lhs->kind == N_SEND && (lhs->flags & NF_BARE)) {
        if (t != T_ASSIGN)
            errorf("'", sym_text(lhs->val), "' isn't a variable yet");
        lhs = define_target(lhs->val);
    }
    switch (lhs->kind) {
    case N_LOCAL: case N_CAPT: case N_GLOBAL: case N_IVAR: case N_INDEX:
        break;
    case N_SEND:
        if (lhs->a && lhs->n == 0 && !(lhs->flags & NF_PAREN)) {
            /* obj.x = v is obj.x=(v); obj.x += v reads obj.x first */
            if (t == T_ASSIGN) {
                Node *s = send_node(lhs->a, setter_name(lhs->val));
                s->b = expr();
                s->n = 1;
                s->line = line;
                return s;
            }
            break;
        }
        /* fall through */
    default:
        error("can't assign to this");
    }
    n = node(t == T_ASSIGN ? N_ASSIGN : N_OPASSIGN);
    n->line = line;
    n->a = lhs;
    n->n = t;
    if (lhs->kind == N_LOCAL && lhs->var->nassign == 0 && !lhs->var->is_param) {
        lhs->var->defining = 1;
        n->b = expr();
        lhs->var->defining = 0;
    } else {
        n->b = expr();
    }
    note_assign(lhs);
    return n;
}

static Node *statement(void)
{
    Node *n;
    switch (TOK) {
    case T_RETURN:
        n = node(N_RETURN);
        next();
        if (TOK != T_NEWLINE && TOK != T_SEMI && TOK != T_END && TOK != T_RBRACE
            && TOK != T_EOF && TOK != T_ELSE && TOK != T_ELIF && TOK != T_CATCH)
            n->a = expr();
        return n;
    case T_BREAK:
    case T_CONTINUE:
        if (!fn->loop_depth)
            errorf("'", tok_name(TOK), "' outside a loop");
        n = node(TOK == T_BREAK ? N_BREAK : N_CONTINUE);
        next();
        return n;
    }
    return expr();
}

static int is_end(int t, int t1, int t2, int t3)
{
    return t == t1 || t == t2 || t == t3 || t == T_EOF;
}

static Node *statements(int t1, int t2, int t3)
{
    Node *seq = node(N_SEQ), **tail = &seq->a;
    skip_nl();
    while (!is_end(TOK, t1, t2, t3)) {
        Node *s = statement();
        *tail = s;
        tail = &s->next;
        if (is_end(TOK, t1, t2, t3))
            break;
        if (TOK != T_NEWLINE && TOK != T_SEMI)
            errorf("expected the end of the statement but found '", cur_tok_text(), "'");
        skip_nl();
    }
    return seq;
}

/* ---- methods and classes --------------------------------------------------------- */

static Value def_name(void)
{
    Value name;
    switch (TOK) {
    case T_IDENT:
        name = lx->tval;
        if (lx->p + 1 < lx->end && lx->p[0] == '=' && lx->p[1] == '(') {
            next();
            expect(T_ASSIGN);
            return setter_name(name);
        }
        next();
        return name;
    case T_LBRACK:
        next();
        expect(T_RBRACK);
        if (TOK == T_ASSIGN && lx->p < lx->end && lx->p[0] == '(') {
            next();
            return intern_c("[]=");
        }
        return intern_c("[]");
    case T_PLUS: case T_MINUS: case T_STAR: case T_SLASH: case T_PERCENT: case T_POW:
    case T_EQ: case T_LT: case T_LE: case T_GT: case T_GE: case T_CMP: case T_AMP:
    case T_PIPE: case T_CARET: case T_SHL: case T_SHR: case T_TILDE:
        name = intern_c(tok_name(TOK));
        next();
        return name;
    }
    error("expected a method name");
    return 0;
}

static void finish_method(Func *f, Value target)
{
    Value m;
    decide_boxes(all_funcs);
    m = gen_method(f);
    class_add_method(target, f->sel, m);
}

static void parse_def(Value cls)
{
    Value target = cls, sel;
    Func *f;
    int class_side = 0;
    next();
    if (TOK == T_SELF) {
        next();
        expect(T_DOT);
        class_side = 1;
        target = CLASSW(cls);
    }
    sel = def_name();
    all_funcs = 0;
    fn = 0;
    f = new_func(0);
    f->owner = cls;
    f->sel = sel;
    f->class_side = class_side;
    fn = f;
    if (accept(T_LPAREN))
        param_list(f, T_RPAREN);
    if (accept(T_ASSIGN)) {
        Node *seq = node(N_SEQ);
        seq->a = expr();
        f->body = seq;
    } else {
        f->body = statements(T_END, -1, -1);
        expect(T_END);
    }
    finish_method(f, target);
    fn = 0;
}

/* attr a, b: methods that return @a and @b */
static void parse_attr(Value cls)
{
    next();
    do {
        Func *f;
        Node *seq, *iv;
        if (TOK != T_IDENT)
            error("expected an instance variable name after attr");
        all_funcs = 0;
        fn = 0;
        f = new_func(0);
        f->owner = cls;
        f->sel = lx->tval;
        fn = f;
        iv = node(N_IVAR);
        iv->n = ivar_index(lx->tval);
        seq = node(N_SEQ);
        seq->a = iv;
        f->body = seq;
        finish_method(f, cls);
        fn = 0;
        next();
    } while (accept(T_COMMA));
}

static void parse_class(void)
{
    Value name, super = cls_Object, cls;
    int g;
    char *mark;
    next();
    if (TOK != T_IDENT || !is_upper(lx->tval))
        error("expected a class name (Capitalized)");
    name = lx->tval;
    next();
    if (accept(T_LT)) {
        int sg;
        if (TOK != T_IDENT)
            error("expected the superclass's name");
        sg = global_index(lx->tval);
        super = globals[sg];
        if (!super || IS_INT(super) || INT(F(CLASSW(super), C_KIND)) != K_CLASS)
            errorf("'", sym_text(lx->tval), "' isn't a class");
        if (INT(F(super, C_KIND)) != K_OBJECT)
            errorf("can't subclass ", sym_text(lx->tval), " (only classes of plain objects)");
        next();
    }
    g = global_index(name);
    cls = globals[g];
    if (cls && !IS_INT(cls) && INT(F(CLASSW(cls), C_KIND)) == K_CLASS) {
        class_is_new = 0;
    } else {
        cls = make_class(name, super, K_OBJECT);
        globals[g] = cls;
        class_is_new = 1;
    }
    cur_class = cls;
    mark = scratch_mark();
    skip_nl();
    while (TOK != T_END) {
        if (TOK == T_DEF)
            parse_def(cls);
        else if (TOK == T_ATTR)
            parse_attr(cls);
        else if (TOK == T_EOF)
            error("expected 'end' to close the class");
        else
            error("a class holds only def and attr");
        scratch_release(mark);
        if (TOK != T_END && TOK != T_NEWLINE && TOK != T_SEMI)
            error("expected a newline after the method");
        skip_nl();
    }
    next();
    cur_class = 0;
}

void compile_source(const char *src, unsigned len, const char *name)
{
    lex_init(&main_lexer, src, len, 1, name);
    lx = &main_lexer;
    if (ejsetjmp(err_jmp)) {
        main_lexer.p = main_lexer.end;
        main_lexer.tok = T_EOF;
        return;
    }
    next();
}

Value compile_next(void)
{
    char *mark = scratch_mark();
    Func *f;
    Node *seq;
    Value m;
    lx = &main_lexer;
    if (ejsetjmp(err_jmp)) {
        scratch_release(mark);
        fn = 0;
        cur_class = 0;
        lx = &main_lexer;
        main_lexer.p = main_lexer.end;
        main_lexer.tok = T_EOF;
        return 0;
    }
    for (;;) {
        skip_nl();
        if (TOK == T_EOF)
            return 0;
        if (TOK == T_CLASS) {
            parse_class();
        } else if (TOK == T_DEF) {
            cur_class = cls_Object;
            class_is_new = 0;
            parse_def(cls_Object);
            cur_class = 0;
        } else {
            break;
        }
        scratch_release(mark);
        if (TOK != T_NEWLINE && TOK != T_SEMI && TOK != T_EOF)
            errorf("expected the end of the statement but found '", cur_tok_text(), "'");
    }
    all_funcs = 0;
    fn = 0;
    f = new_func(0);
    f->toplevel = 1;
    f->owner = NIL;
    f->sel = intern_c("<main>");
    fn = f;
    seq = node(N_SEQ);
    seq->a = statement();
    f->body = seq;
    if (TOK != T_NEWLINE && TOK != T_SEMI && TOK != T_EOF)
        errorf("expected the end of the statement but found '", cur_tok_text(), "'");
    decide_boxes(all_funcs);
    m = gen_method(f);
    fn = 0;
    scratch_release(mark);
    return m;
}
