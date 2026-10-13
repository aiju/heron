/* The code generator: syntax trees to bytecode methods. */

#include "compiler.h"

#define CODE_MAX 16384
#define LITS_MAX 256
#define LINES_MAX 1024
#define LOOPS_MAX 32
#define PATCHES_MAX 64

static unsigned char code[CODE_MAX];
static unsigned ncode;
static Value lits[LITS_MAX];
static unsigned nlits;
static unsigned short lines[2 * LINES_MAX];
static unsigned nlines;
static int last_line;
static Func *gf;                /* the function being generated */
static int try_depth;

typedef struct Loop {
    int cont;                   /* where continue goes */
    int breaks[PATCHES_MAX];
    int nbreaks;
    int try_depth;
} Loop;
static Loop loops[LOOPS_MAX];
static int nloops;

static void gen(Node *n, int want);
static void gen_seq(Node *n, int want);

static void gen_error(int line, const char *msg) { fatal_at(0, line, msg); }

/* ---- literals, boxes ------------------------------------------------------ */

/* A copy of a heap object in the permanent space (a big number literal). */
Value perm_literal(Value v)
{
    Value p;
    if (IS_INT(v) || v < SEMI_LO || v >= SEMI_HI)
        return v;
    p = perm_bytes(CLASSW(v), SIZE(v));
    memcpy(BYTES(p), BYTES(v), SIZE(v));
    return p;
}

void decide_boxes(Func *all)
{
    Func *f;
    Var *v;
    for (f = all; f; f = f->all)
        for (v = f->vars; v; v = v->next) {
            if (!v->captured)
                continue;
            if (v->is_param)
                v->boxed = v->nassign > 0 || v->assign_inner;
            else
                v->boxed = v->nassign > 1 || v->assign_in_loop || v->assign_inner
                           || v->captured_early;
        }
}

/* ---- emitting ----------------------------------------------------------------- */

static void emit(int b)
{
    if (ncode >= CODE_MAX)
        gen_error(gf->line, "method too big");
    code[ncode++] = b;
}

static void emit2(int op, int a)
{
    emit(op);
    emit(a);
}

static void emitw(int w)
{
    emit(w & 0xFF);
    emit((w >> 8) & 0xFF);
}

static int jump_fwd(int op)
{
    emit(op);
    emitw(0);
    return ncode - 2;
}

static void patch_to(int pos, int target)
{
    int off = target - (pos + 2);
    if (off < -32768 || off > 32767)
        gen_error(gf->line, "jump too far");
    code[pos] = off & 0xFF;
    code[pos + 1] = (off >> 8) & 0xFF;
}

static void patch(int pos) { patch_to(pos, ncode); }

static void jump_back(int op, int target)
{
    emit(op);
    emitw(0);
    patch_to(ncode - 2, target);
}

static int lit(Value v)
{
    unsigned i;
    for (i = 0; i < nlits; i++)
        if (lits[i] == v)
            return i;
    if (nlits >= LITS_MAX)
        gen_error(gf->line, "too many constants and message names in one method");
    lits[nlits] = v;
    return nlits++;
}

static void set_line(int line)
{
    if (line == last_line || line == 0)
        return;
    last_line = line;
    if (nlines < LINES_MAX) {
        lines[2 * nlines] = ncode;
        lines[2 * nlines + 1] = line;
        nlines++;
    }
}

/* ---- variables ---------------------------------------------------------------- */

static void load(Node *t)
{
    switch (t->kind) {
    case N_LOCAL:
        emit2(t->var->boxed ? OP_PUSH_BOXED : OP_PUSH_LOCAL, t->var->slot);
        break;
    case N_CAPT:
        emit2(t->var->boxed ? OP_PUSH_CAPT_BOXED : OP_PUSH_CAPT, t->capt->index);
        break;
    case N_GLOBAL:
        emit(OP_PUSH_GLOBAL);
        emitw(t->n);
        break;
    case N_IVAR:
        emit2(gf->is_block ? OP_PUSH_BIVAR : OP_PUSH_IVAR, t->n);
        break;
    default:
        gen_error(t->line, "internal: load");
    }
}

/* store the top of the stack; keep it if want */
static void store(Node *t, int want)
{
    switch (t->kind) {
    case N_LOCAL:
        if (t->var->boxed)
            emit2(OP_STORE_BOXED, t->var->slot);
        else if (!want) {
            emit2(OP_POP_LOCAL, t->var->slot);
            return;
        } else
            emit2(OP_STORE_LOCAL, t->var->slot);
        break;
    case N_CAPT:
        emit2(t->var->boxed ? OP_STORE_CAPT_BOXED : OP_STORE_CAPT, t->capt->index);
        break;
    case N_GLOBAL:
        emit(OP_STORE_GLOBAL);
        emitw(t->n);
        break;
    case N_IVAR:
        emit2(gf->is_block ? OP_STORE_BIVAR : OP_STORE_IVAR, t->n);
        break;
    default:
        gen_error(t->line, "internal: store");
    }
    if (!want)
        emit(OP_POP);
}

static int temp_slot(void)
{
    /* a hidden local of the function being generated */
    int s = gf->nslots++;
    if (gf->nslots > 255)
        gen_error(gf->line, "too many variables in one method");
    return s;
}

static void push_self(void) { emit(gf->is_block ? OP_PUSH_BSELF : OP_PUSH_SELF); }

/* ---- expressions ------------------------------------------------------------------ */

static void send(Value sel, int argc)
{
    emit(OP_SEND);
    emit(lit(sel));
    emit(argc);
}

static void binop(int op, int line)
{
    switch (op) {
    case T_PLUS: emit(OP_ADD); return;
    case T_MINUS: emit(OP_SUB); return;
    case T_STAR: emit(OP_MUL); return;
    case T_SLASH: emit(OP_DIV); return;
    case T_PERCENT: emit(OP_MOD); return;
    case T_LT: emit(OP_LT); return;
    case T_LE: emit(OP_LE); return;
    case T_GT: emit(OP_GT); return;
    case T_GE: emit(OP_GE); return;
    case T_EQ: emit(OP_EQ); return;
    case T_AMP: emit(OP_BAND); return;
    case T_PIPE: emit(OP_BOR); return;
    case T_CARET: emit(OP_BXOR); return;
    case T_SHL: emit(OP_SHL); return;
    case T_SHR: emit(OP_SHR); return;
    case T_POW: case T_CMP:
        send(intern_c(tok_name(op)), 1);
        return;
    }
    gen_error(line, "internal: operator");
}

/* the operator of an op-assignment token (+= is +) */
static int assign_op(int t)
{
    switch (t) {
    case T_PLUS_EQ: return T_PLUS;
    case T_MINUS_EQ: return T_MINUS;
    case T_STAR_EQ: return T_STAR;
    case T_SLASH_EQ: return T_SLASH;
    case T_PERCENT_EQ: return T_PERCENT;
    case T_AMP_EQ: return T_AMP;
    case T_PIPE_EQ: return T_PIPE;
    case T_CARET_EQ: return T_CARET;
    case T_SHL_EQ: return T_SHL;
    case T_SHR_EQ: return T_SHR;
    }
    return T_PLUS;
}

static void gen_opassign(Node *n, int want)
{
    Node *t = n->a;
    int op = assign_op(n->n);
    if (t->kind == N_LOCAL && !t->var->boxed && !want && (op == T_PLUS || op == T_MINUS)
        && n->b->kind == N_INT && INT(n->b->val) >= -127 && INT(n->b->val) <= 127) {
        /* the fast path, then the general code it skips (for anything
           but a SmallInt, or on overflow) */
        int step = op == T_PLUS ? INT(n->b->val) : -INT(n->b->val);
        emit(OP_INC_LOCAL);
        emit(t->var->slot);
        emit(step & 0xFF);
        emit2(OP_PUSH_LOCAL, t->var->slot);
        emit2(OP_PUSH_INT, step & 0xFF);
        emit(OP_ADD);
        emit2(OP_POP_LOCAL, t->var->slot);
        return;
    }
    switch (t->kind) {
    case N_LOCAL: case N_CAPT: case N_GLOBAL: case N_IVAR:
        load(t);
        gen(n->b, 1);
        binop(op, n->line);
        store(t, want);
        return;
    case N_INDEX: {
        int obj = temp_slot(), idx = temp_slot();
        gen(t->a, 1);
        emit2(OP_POP_LOCAL, obj);
        gen(t->b, 1);
        emit2(OP_POP_LOCAL, idx);
        emit2(OP_PUSH_LOCAL, obj);
        emit2(OP_PUSH_LOCAL, idx);
        emit2(OP_PUSH_LOCAL, obj);
        emit2(OP_PUSH_LOCAL, idx);
        emit(OP_AT);
        gen(n->b, 1);
        binop(op, n->line);
        emit(OP_AT_PUT);
        if (!want)
            emit(OP_POP);
        return;
    }
    case N_SEND: {
        int obj = temp_slot();
        char buf[80];
        unsigned len = SIZE(t->val) < 78 ? SIZE(t->val) : 78;
        gen(t->a, 1);
        emit2(OP_POP_LOCAL, obj);
        emit2(OP_PUSH_LOCAL, obj);
        emit2(OP_PUSH_LOCAL, obj);
        send(t->val, 0);
        gen(n->b, 1);
        binop(op, n->line);
        memcpy(buf, BYTES(t->val), len);
        buf[len] = '=';
        send(intern(buf, len + 1), 1);
        if (!want)
            emit(OP_POP);
        return;
    }
    }
    gen_error(n->line, "internal: op-assign");
}

/* jump to the returned patch position if n is false (or true) */
static int gen_cond_jump(Node *n, int if_true)
{
    if (n->kind == N_NOT)
        return gen_cond_jump(n->a, !if_true);
    gen(n, 1);
    return jump_fwd(if_true ? OP_JUMP_TRUE : OP_JUMP_FALSE);
}

static void gen_if(Node *n, int want)
{
    int jelse = gen_cond_jump(n->a, 0), jend;
    gen_seq(n->b, want);
    if (!n->c) {
        if (want) {
            jend = jump_fwd(OP_JUMP);
            patch(jelse);
            emit(OP_PUSH_NIL);
            patch(jend);
        } else {
            patch(jelse);
        }
        return;
    }
    jend = jump_fwd(OP_JUMP);
    patch(jelse);
    if (n->c->kind == N_IF)
        gen_if(n->c, want);
    else
        gen_seq(n->c, want);
    patch(jend);
}

static Loop *push_loop(int line)
{
    Loop *l;
    if (nloops >= LOOPS_MAX)
        gen_error(line, "loops nested too deeply");
    l = &loops[nloops++];
    l->nbreaks = 0;
    l->try_depth = try_depth;
    return l;
}

static void pop_loop(void)
{
    Loop *l = &loops[--nloops];
    int i;
    for (i = 0; i < l->nbreaks; i++)
        patch(l->breaks[i]);
}

static void gen_while(Node *n, int want)
{
    Loop *l = push_loop(n->line);
    int top = ncode, jexit;
    l->cont = top;
    jexit = gen_cond_jump(n->a, 0);
    gen_seq(n->b, 0);
    jump_back(OP_JUMP, top);
    patch(jexit);
    pop_loop();
    if (want)
        emit(OP_PUSH_NIL);
}

static void gen_for(Node *n, int want)
{
    Loop *l;
    int slot = temp_slot(), top, jexit;
    temp_slot();
    if (n->b->kind == N_RANGE) {
        gen(n->b->a, 1);
        gen(n->b->b, 1);
        emit(OP_RANGE_PREP);
        emit(slot);
        emit(n->b->n);
    } else {
        gen(n->b, 1);
        send(sym_iter, 0);
        emit2(OP_ITER_PREP, slot);
    }
    l = push_loop(n->line);
    top = ncode;
    l->cont = top;
    emit(n->b->kind == N_RANGE ? OP_RANGE_NEXT : OP_ITER_NEXT);
    emit(slot);
    emitw(0);
    jexit = ncode - 2;
    store(n->a, 0);
    gen_seq(n->c, 0);
    jump_back(OP_JUMP, top);
    patch(jexit);
    pop_loop();
    if (want)
        emit(OP_PUSH_NIL);
}

static void gen_send(Node *n, int want)
{
    Node *a;
    if (n->a)
        gen(n->a, 1);
    else
        push_self();
    for (a = n->b; a; a = a->next)
        gen(a, 1);
    set_line(n->line);
    send(n->val, n->n);
    if (!want)
        emit(OP_POP);
}

static void gen_super(Node *n, int want)
{
    Node *a;
    int argc = n->n;
    push_self();
    if (argc < 0) {
        Var *v;
        int i;
        if (gf->is_block)
            gen_error(n->line, "a bare super can't be in a block (give it its arguments)");
        argc = gf->nparams;
        for (i = 1; i <= argc; i++)
            for (v = gf->vars; v; v = v->next)
                if (v->slot == i)
                    emit2(v->boxed ? OP_PUSH_BOXED : OP_PUSH_LOCAL, i);
    } else {
        for (a = n->b; a; a = a->next)
            gen(a, 1);
    }
    set_line(n->line);
    emit(OP_SEND_SUPER);
    emit(lit(gf->sel));
    emit(argc);
    if (!want)
        emit(OP_POP);
}

static void gen_closure(Node *n)
{
    Func *f = n->func;
    Capt *c;
    emit(OP_CLOSURE);
    emit(lit(n->val));
    emit(f->ncapts);
    for (c = f->capts; c; c = c->next) {
        emit(c->from_kind);
        emit(c->from_index);
    }
}

static void gen_try(Node *n, int want)
{
    int jhandler = jump_fwd(OP_TRY), jend;
    try_depth++;
    gen_seq(n->a, want);
    try_depth--;
    emit(OP_END_TRY);
    jend = jump_fwd(OP_JUMP);
    patch(jhandler);
    /* the interpreter pushes the error */
    if (n->c)
        store(n->c, 0);
    else
        emit(OP_POP);
    if (n->b)
        gen_seq(n->b, want);
    else if (want)
        emit(OP_PUSH_NIL);
    patch(jend);
}

static void gen(Node *n, int want)
{
    Node *a;
    int k;
    set_line(n->line);
    switch (n->kind) {
    case N_INT:
        if (!want)
            return;
        k = INT(n->val);
        if (k >= -128 && k <= 127)
            emit2(OP_PUSH_INT, k & 0xFF);
        else
            emit2(OP_PUSH_LIT, lit(n->val));
        return;
    case N_LIT:
        if (want)
            emit2(OP_PUSH_LIT, lit(n->val));
        return;
    case N_NIL: if (want) emit(OP_PUSH_NIL); return;
    case N_TRUE: if (want) emit(OP_PUSH_TRUE); return;
    case N_FALSE: if (want) emit(OP_PUSH_FALSE); return;
    case N_SELF: if (want) push_self(); return;
    case N_LOCAL: case N_CAPT: case N_GLOBAL: case N_IVAR:
        if (want)
            load(n);
        return;
    case N_ASSIGN:
        if (n->a->kind == N_INDEX) {
            gen(n->a->a, 1);
            gen(n->a->b, 1);
            gen(n->b, 1);
            set_line(n->line);
            emit(OP_AT_PUT);
            if (!want)
                emit(OP_POP);
            return;
        }
        gen(n->b, 1);
        store(n->a, want);
        return;
    case N_OPASSIGN:
        gen_opassign(n, want);
        return;
    case N_SEND:
        gen_send(n, want);
        return;
    case N_SUPER:
        gen_super(n, want);
        return;
    case N_BINOP:
        gen(n->a, 1);
        gen(n->b, 1);
        set_line(n->line);
        binop(n->n, n->line);
        if (!want)
            emit(OP_POP);
        return;
    case N_INDEX:
        gen(n->a, 1);
        gen(n->b, 1);
        set_line(n->line);
        emit(OP_AT);
        if (!want)
            emit(OP_POP);
        return;
    case N_AND:
    case N_OR:
        gen(n->a, 1);
        k = jump_fwd(n->kind == N_AND ? OP_JUMP_FALSE_OR_POP : OP_JUMP_TRUE_OR_POP);
        gen(n->b, 1);
        patch(k);
        if (!want)
            emit(OP_POP);
        return;
    case N_NOT:
        gen(n->a, 1);
        emit(OP_NOT);
        if (!want)
            emit(OP_POP);
        return;
    case N_IF:
        gen_if(n, want);
        return;
    case N_WHILE:
        gen_while(n, want);
        return;
    case N_FOR:
        gen_for(n, want);
        return;
    case N_BREAK:
    case N_CONTINUE: {
        Loop *l = &loops[nloops - 1];
        int i;
        for (i = try_depth; i > l->try_depth; i--)
            emit(OP_END_TRY);
        if (n->kind == N_CONTINUE) {
            jump_back(OP_JUMP, l->cont);
        } else {
            if (l->nbreaks >= PATCHES_MAX)
                gen_error(n->line, "too many breaks in one loop");
            l->breaks[l->nbreaks++] = jump_fwd(OP_JUMP);
        }
        return;
    }
    case N_RETURN:
        if (n->a)
            gen(n->a, 1);
        else
            emit(OP_PUSH_NIL);
        set_line(n->line);
        if (gf->is_block) {
            emit(OP_RETURN_NLR);
        } else {
            for (k = 0; k < try_depth; k++)
                emit(OP_END_TRY);
            emit(OP_RETURN);
        }
        return;
    case N_SEQ:
        gen_seq(n, want);
        return;
    case N_BLOCK:
        if (want)
            gen_closure(n);
        return;
    case N_LIST:
        for (a = n->a; a; a = a->next)
            gen(a, 1);
        emit2(OP_MAKE_LIST, n->n);
        if (!want)
            emit(OP_POP);
        return;
    case N_MAP:
        for (a = n->a; a; a = a->next)
            gen(a, 1);
        emit2(OP_MAKE_MAP, n->n);
        if (!want)
            emit(OP_POP);
        return;
    case N_RANGE:
        gen(n->a, 1);
        gen(n->b, 1);
        emit2(OP_MAKE_RANGE, n->n);
        if (!want)
            emit(OP_POP);
        return;
    case N_INTERP:
        for (a = n->a; a; a = a->next) {
            gen(a, 1);
            if (a->kind != N_LIT)
                send(sym_to_s, 0);
        }
        emit2(OP_CONCAT, n->n);
        if (!want)
            emit(OP_POP);
        return;
    case N_TRY:
        gen_try(n, want);
        return;
    }
    gen_error(n->line, "internal: unknown node");
}

static void gen_seq(Node *n, int want)
{
    Node *s = n->a;
    if (!s) {
        if (want)
            emit(OP_PUSH_NIL);
        return;
    }
    for (; s; s = s->next)
        gen(s, s->next ? 0 : want);
}

/* ---- functions ------------------------------------------------------------------ */

static void gen_blocks(Node *n);

static Value gen_function(Func *f)
{
    Value m, c, l, ln;
    Var *v;
    unsigned i, nlocals;
    gf = f;
    ncode = 0;
    nlits = 0;
    nlines = 0;
    last_line = -1;
    nloops = 0;
    try_depth = 0;
    set_line(f->line);
    for (v = f->vars; v; v = v->next)
        if (v->boxed)
            emit2(OP_MAKE_BOX, v->slot);
    gen_seq(f->body, 1);
    emit(OP_RETURN);

    m = perm_obj(cls_Method, METHOD_FIELDS);
    F(m, M_SEL) = f->sel;
    /* super starts above the owner: the metaclass, for a class method */
    F(m, M_OWNER) = !f->owner || f->owner == NIL ? NIL : f->class_side ? CLASSW(f->owner) : f->owner;
    c = perm_bytes(cls_Array, ncode);
    memcpy(BYTES(c), code, ncode);
    F(m, M_CODE) = c;
    l = perm_obj(cls_Array, nlits);
    for (i = 0; i < nlits; i++)
        F(l, i) = lits[i];
    F(m, M_LITS) = l;
    nlocals = f->nslots - 1 - f->nparams;
    F(m, M_INFO) = f->nparams | nlocals << 8 | (f->rest ? MF_REST : 0) | (f->is_block ? MF_BLOCK : 0);
    F(m, M_PRIM) = 0;
    ln = perm_bytes(cls_Array, 4 * nlines);
    memcpy(BYTES(ln), lines, 4 * nlines);
    F(m, M_LINES) = ln;
    F(m, M_LINE) = f->line;
    method_finish(m);
    return m;
}

static void gen_blocks(Node *n)
{
    for (; n; n = n->next) {
        if (n->kind == N_BLOCK) {
            gen_blocks(n->func->body);
            n->val = gen_function(n->func);
        } else {
            if (n->a) gen_blocks(n->a);
            if (n->b) gen_blocks(n->b);
            if (n->c) gen_blocks(n->c);
        }
    }
}

Value gen_method(Func *f)
{
    gen_blocks(f->body);
    return gen_function(f);
}
