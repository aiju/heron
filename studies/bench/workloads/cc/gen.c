/* The code generator: a function's syntax tree to draft 2 assembly.

   Registers, by the C compiler's convention: arguments in r1-r4 and the
   result in r1; r1-r7 caller-saved (r7 is the link register), r8-r14
   callee-saved; r0 takes a multiply's high half and a divide's
   remainder. Here:

   - r1-r6 are the expression temporaries. An expression is evaluated in
     Sethi-Ullman order: of a binary operator's operands, the one that
     needs more registers goes first, and when neither fits in the
     registers that are free, the right one is spilled to the frame and
     read back as a memory operand.
   - r8-r13 are register variables: the scalar locals and parameters
     whose address is never taken, the most used first (a use in a loop
     counts 8 times one outside it).
   - r0 is scratch, for a divisor or shift count that has to be in a
     register.

   Leaves (constants and scalar variables) and loads are folded into
   operands: `x + a[i]` is one ADD with an indexed memory operand.
   Conditions compile to compares and branches directly, with && and ||
   short-circuited, and loops are rotated, with the test at the bottom.

   The frame, from sp up: locals that live in memory, then spill slots;
   above it the registers SAVE pushed. The prologue is written last,
   once the body has said which registers and how much frame it used. */

#include "cc.h"

#define SP 15
#define TEMPS 0x7e              /* r1-r6 */
#define PROLOGUE 6              /* lines before the body: a blank, the
                                   section, .global, the label, SAVE, SUB */

static int busy;                /* temporaries in use, a bit each */
static int prefer;              /* the register the next temporary
                                   should be, if it is free, or 0 */
static int locals_size;         /* bytes of locals in the frame */
static int spill_top, spill_max;/* spill slots in use; the most at once */
static int nregvars;            /* register variables used: r8 on */
static int nlabels;             /* labels made, for the whole program */
static int ret_label;

#define MAXLOOPS 32
static int break_label[MAXLOOPS], continue_label[MAXLOOPS];
static int nloops;

static int gen(struct node *n);
static int gen_ro(struct node *n);
static void gen_effect(struct node *n);
static void gen_cond(struct node *n, int label, int sense);
static void statement(struct node *n);

/* ---- registers and slots --------------------------------------------- */

static int new_label(void)
{
    return ++nlabels;
}

static int free_temps(void)
{
    int r, n = 0;
    for (r = 1; r <= NTEMPS; r++)
        if (!(busy & 1 << r))
            n++;
    return n;
}

static int alloc_temp(void)
{
    int r = prefer;
    prefer = 0;
    if (r && !(busy & 1 << r)) {
        busy |= 1 << r;
        return r;
    }
    for (r = 1; r <= NTEMPS; r++)
        if (!(busy & 1 << r)) {
            busy |= 1 << r;
            return r;
        }
    error("expression too complex");
    return 1;
}

static void free_reg(int r)
{
    if (r >= 1 && r <= NTEMPS)
        busy &= ~(1 << r);
}

static int is_temp(int r)
{
    return r >= 1 && r <= NTEMPS;
}

static int spill_alloc(void)
{
    int off = locals_size + 4 * spill_top++;
    if (spill_top > spill_max)
        spill_max = spill_top;
    return off;
}

static void spill_free(void)
{
    spill_top--;
}

/* ---- operands -------------------------------------------------------- */

static void op_reg(struct operand *o, int r)
{
    o->kind = O_REG;
    o->reg = r;
    o->slot = -1;
}

static void op_imm(struct operand *o, int v)
{
    o->kind = O_IMM;
    o->off = v;
    o->slot = -1;
}

static void op_mem(struct operand *o, int base, int off, int size)
{
    o->kind = O_MEM;
    o->reg = base;
    o->index = -1;
    o->scale = 1;
    o->off = off;
    o->sym = 0;
    o->size = size;
    o->slot = -1;
}

/* Releases the registers and spill slot an operand held. */
static void free_operand(struct operand *o)
{
    if (o->kind == O_REG) {
        free_reg(o->reg);
    } else if (o->kind == O_MEM) {
        free_reg(o->reg);
        free_reg(o->index);
        if (o->slot >= 0)
            spill_free();
    }
}

static int is_absolute(struct operand *o)
{
    return o->kind == O_MEM && o->sym && o->reg < 0 && o->index < 0;
}

/* Where a variable lives, as an operand. */
static void var_operand(struct sym *s, struct operand *o)
{
    int size = s->type->kind == TY_CHAR ? 1 : 4;
    if (s->reg) {
        op_reg(o, s->reg);
    } else if (s->sclass == SC_GLOBAL) {
        op_mem(o, -1, 0, size);
        o->sym = s->name;
    } else {
        op_mem(o, SP, s->offset, size);
    }
}

/* Constants and scalar variables: operands that need no register. */
static int is_leaf(struct node *n)
{
    return n->kind == N_NUM || (n->kind == N_VAR && is_scalar(n->type));
}

static void leaf_operand(struct node *n, struct operand *o)
{
    if (n->kind == N_NUM)
        op_imm(o, n->val);
    else
        var_operand(n->sym, o);
}

/* ---- Sethi-Ullman numbers -------------------------------------------- */

static int max2(int a, int b)
{
    return a > b ? a : b;
}

/* The registers it takes to evaluate n without spilling. */
static int need(struct node *n)
{
    int k;
    if (n->need >= 0)
        return n->need;
    switch (n->kind) {
    case N_NEG: case N_NOT: case N_BNOT: case N_CAST: case N_DEREF:
        k = need(n->a);
        break;
    case N_BIN:
        if (is_leaf(n->b)) {
            k = need(n->a);
        } else {
            int la = need(n->a), lb = need(n->b);
            k = la == lb ? la + 1 : max2(la, lb);
        }
        break;
    case N_ANDAND: case N_OROR: case N_COMMA:
        k = max2(need(n->a), need(n->b));
        break;
    case N_COND:
        k = max2(need(n->a), max2(need(n->b), need(n->c)) + 1);
        break;
    case N_ASSIGN:
        k = need(n->b);
        if (n->a->kind == N_DEREF)
            k = max2(k, need(n->a->a) + 1);
        if (n->op != '=')
            k = max2(k, 2);
        break;
    case N_PREINC: case N_POSTINC:
        k = n->a->kind == N_DEREF ? need(n->a->a) + 2 : 2;
        break;
    case N_CALL:
        k = NTEMPS + 1;
        break;
    default:
        k = 1;
    }
    if (k > NTEMPS + 1)
        k = NTEMPS + 1;
    n->need = k;
    return k;
}

/* ---- addresses ------------------------------------------------------- */

/* The scale of an index: p + i * s with s 1, 2 or 4. */
static struct node *index_of(struct node *b, int *scale)
{
    if (b->kind == N_BIN && b->op == '*' && b->b->kind == N_NUM &&
        (b->b->val == 2 || b->b->val == 4)) {
        *scale = b->b->val;
        return b->a;
    }
    *scale = 1;
    return b;
}

/* Adds up the constants added to p, and returns what they are added to. */
static struct node *displacement(struct node *p, int *disp)
{
    while (p->kind == N_BIN && p->op == '+' && p->b->kind == N_NUM) {
        *disp += p->b->val;
        p = p->a;
    }
    return p;
}

static int fits_d8(int d)
{
    return d >= -128 && d < 128;
}

/* The memory at the address p computes, folded into an addressing
   mode where it can be: a variable's own place, a register and a
   displacement, or a base, a scaled index and a displacement. */
static void address(struct node *p, struct operand *o, int size)
{
    struct node *base, *index = 0;
    int disp = 0, scale = 1;
    base = displacement(p, &disp);
    if (base->kind == N_BIN && base->op == '+' && free_temps() >= 2) {
        index = index_of(base->b, &scale);
        base = displacement(base->a, &disp);
    }
    if (base->kind == N_ADDR)
        var_operand(base->a->sym, o);
    else
        op_mem(o, gen_ro(base), 0, 4);
    o->size = size;
    o->off += disp;
    if (!index)
        return;
    if (o->reg >= 0 && !fits_d8(o->off)) {
        /* the displacement is too big to go with an index */
        int r = alloc_temp();
        o->size = 4;
        emit("%iLEA %r, %o", r, o);
        free_operand(o);
        op_mem(o, r, 0, size);
    }
    o->index = gen_ro(index);
    o->scale = scale;
}

static int size_of(struct type *t)
{
    return t->kind == TY_CHAR ? 1 : 4;
}

/* n as an operand: a leaf, a load folded into a memory operand, or a
   register. */
static void gen_operand(struct node *n, struct operand *o)
{
    if (is_leaf(n))
        leaf_operand(n, o);
    else if (n->kind == N_DEREF && is_scalar(n->type))
        address(n->a, o, size_of(n->type));
    else
        op_reg(o, gen_ro(n));
}

/* Evaluates both operands of a binary operation: a into a register (a
   temporary the caller may change unless ro is set) and b into an
   operand, in the order that needs fewer registers, spilling b if
   neither order fits. */
static int gen_pair(struct node *a, struct node *b, struct operand *ob, int ro)
{
    int ra, avail = free_temps(), la, lb;
    if (is_leaf(b)) {
        ra = ro ? gen_ro(a) : gen(a);
        leaf_operand(b, ob);
        return ra;
    }
    la = need(a);
    lb = need(b);
    if (lb <= avail - 1 && (la >= lb || la > avail - 1)) {
        ra = ro ? gen_ro(a) : gen(a);
        gen_operand(b, ob);
    } else if (la <= avail - 1) {
        gen_operand(b, ob);
        ra = ro ? gen_ro(a) : gen(a);
    } else {
        int rb = gen_ro(b), slot = spill_alloc();
        emit("%iMOV [sp + %d], %r", slot, rb);
        free_reg(rb);
        ra = ro ? gen_ro(a) : gen(a);
        op_mem(ob, SP, slot, 4);
        ob->slot = slot;
    }
    return ra;
}

/* An operand in a register, for instructions that take no other: r0 is
   the scratch register for it. */
static void in_register(struct operand *o)
{
    if (o->kind == O_REG)
        return;
    emit("%iMOV r0, %o", o);
    free_operand(o);
    op_reg(o, 0);
}

/* ---- expressions ----------------------------------------------------- */

static const char *alu_name(int op)
{
    switch (op) {
    case '+': return "ADD";
    case '-': return "SUB";
    case '&': return "AND";
    case '|': return "OR";
    case '^': return "XOR";
    case P_SHL: return "LSL";
    case P_SHR: return "ASR";
    }
    return "?";
}

/* Applies a binary operator to register rd and operand ob. */
static void apply(int op, int rd, struct operand *ob)
{
    switch (op) {
    case '*':
        if (ob->kind == O_IMM && ob->off > 0 && (ob->off & (ob->off - 1)) == 0) {
            int k = 0;
            while (1 << k != ob->off)
                k++;
            emit("%iLSL %r, #%d", rd, k);
            break;
        }
        if (ob->kind == O_MEM && !is_absolute(ob))
            in_register(ob);
        emit("%iMULS r0:%r, %o", rd, ob);
        break;
    case '/':
    case '%':
        in_register(ob);
        emit("%iDIVS r0:%r, %o", rd, ob);
        if (op == '%')
            emit("%iMOV %r, r0", rd);
        break;
    case P_SHL:
    case P_SHR:
        if (ob->kind == O_IMM) {
            emit("%i%s %r, #%d", alu_name(op), rd, ob->off & 31);
            break;
        }
        in_register(ob);
        emit("%i%s %r, %o", alu_name(op), rd, ob);
        break;
    default:
        emit("%i%s %r, %o", alu_name(op), rd, ob);
    }
}

/* The condition a compare tests: signed for integers, unsigned for
   pointers, and its opposite. */
static const char *cond_name(int op, int is_unsigned, int sense)
{
    static const char *const names[] = {
        /* <     >     <=    >=    ==    !=   */
        "LT", "GT", "LE", "GE", "EQ", "NE",
        "LO", "HI", "LS", "HS", "EQ", "NE",
    };
    static const int inverse[] = { 3, 2, 1, 0, 5, 4 };
    int k;
    switch (op) {
    case '<': k = 0; break;
    case '>': k = 1; break;
    case P_LE: k = 2; break;
    case P_GE: k = 3; break;
    case P_EQ: k = 4; break;
    default: k = 5; break;
    }
    if (!sense)
        k = inverse[k];
    return names[k + (is_unsigned ? 6 : 0)];
}

static int is_compare_op(int op)
{
    return op == '<' || op == '>' || op == P_LE || op == P_GE ||
           op == P_EQ || op == P_NE;
}

/* A compare of n's operands; returns whether it is unsigned. */
static int gen_compare(struct node *n)
{
    struct operand ob;
    int ra = gen_pair(n->a, n->b, &ob, 1);
    emit("%iCMP %r, %o", ra, &ob);
    free_reg(ra);
    free_operand(&ob);
    return is_ptr(n->a->type) || is_ptr(n->b->type);
}

/* A temporary holding n's value: a register variable is copied. */
static int gen(struct node *n)
{
    int r = gen_ro(n);
    if (!is_temp(r)) {
        int t = alloc_temp();
        emit("%iMOV %r, %r", t, r);
        return t;
    }
    return r;
}

/* A register for a call's result, other than those in `avoid`. */
static int result_reg(int avoid)
{
    int r;
    for (r = 1; r <= NTEMPS; r++)
        if (!((busy | avoid) & 1 << r)) {
            busy |= 1 << r;
            return r;
        }
    error("expression too complex");
    return 1;
}

/* Moves argument i from src[i] to r(i+1), all at once: a move waits
   while its destination is still another's source, and a cycle is
   broken through r0. */
static void parallel_move(int *src, int n)
{
    int done[MAXPARAMS], left = n, i, j;
    for (i = 0; i < n; i++)
        done[i] = src[i] == i + 1;
    for (i = 0; i < n; i++)
        if (done[i])
            left--;
    while (left > 0) {
        int progress = 0;
        for (i = 0; i < n; i++) {
            int blocked = 0;
            if (done[i])
                continue;
            for (j = 0; j < n; j++)
                if (!done[j] && j != i && src[j] == i + 1)
                    blocked = 1;
            if (!blocked) {
                emit("%iMOV %r, %r", i + 1, src[i]);
                done[i] = 1;
                left--;
                progress = 1;
            }
        }
        if (!progress) {        /* a cycle: free one destination */
            for (i = 0; done[i]; i++)
                ;
            emit("%iMOV r0, %r", src[i]);
            src[i] = 0;
        }
    }
}

static int gen_call(struct node *n, int want)
{
    int saved = busy & TEMPS, slots[NTEMPS + 1], src[MAXPARAMS];
    int r, i, nargs = 0;
    struct node *a;
    /* the temporaries live across the call go to the frame */
    for (r = 1; r <= NTEMPS; r++)
        if (saved & 1 << r) {
            slots[r] = spill_alloc();
            emit("%iMOV [sp + %d], %r", slots[r], r);
        }
    busy &= ~TEMPS;
    for (a = n->a; a && nargs < MAXPARAMS; a = a->next) {
        prefer = nargs + 1;     /* where it will be passed */
        src[nargs++] = gen_ro(a);
    }
    prefer = 0;
    parallel_move(src, nargs);
    busy &= ~TEMPS;
    emit("%iBSR %n", n->sym->name);
    r = 0;
    if (want) {
        r = result_reg(saved);
        if (r != 1)
            emit("%iMOV %r, r1", r);
    }
    for (i = NTEMPS; i >= 1; i--)
        if (saved & 1 << i) {
            emit("%iMOV %r, [sp + %d]", i, slots[i]);
            spill_free();
        }
    busy |= saved;
    return r;
}

static int gen_assign(struct node *n, int want)
{
    struct node *l = n->a, *v = n->b;
    struct operand ob, ol;
    int r, size = size_of(l->type);
    if (l->kind == N_VAR && l->sym->reg) {
        int rv = l->sym->reg;
        if (n->op == '=' && v->kind == N_BIN && v->a->kind == N_VAR &&
            v->a->sym == l->sym && !is_compare_op(v->op)) {
            /* x = x op e is x op= e */
            gen_operand(v->b, &ob);
            apply(v->op, rv, &ob);
            free_operand(&ob);
        } else if (n->op == '=') {
            gen_operand(v, &ob);
            emit("%iMOV %r, %o", rv, &ob);
            free_operand(&ob);
        } else {
            gen_operand(v, &ob);
            apply(n->op, rv, &ob);
            free_operand(&ob);
        }
        return want ? gen(l) : 0;
    }
    if (n->op == '=') {
        if (v->kind == N_NUM && v->val == 0 && !want) {
            gen_operand(l, &ol);
            emit("%iCLR %o", &ol);
            free_operand(&ol);
            return 0;
        }
        if (l->kind == N_DEREF && need(l->a) > need(v)) {
            address(l->a, &ol, size);
            r = gen_ro(v);
        } else {
            r = gen_ro(v);
            gen_operand(l, &ol);
        }
        emit("%iMOV %o, %r", &ol, r);
        free_operand(&ol);
        if (!want) {
            free_reg(r);
            return 0;
        }
        return is_temp(r) ? r : gen(v);
    }
    /* a compound assignment: load, apply, store back */
    gen_operand(v, &ob);
    gen_operand(l, &ol);
    r = alloc_temp();
    emit("%iMOV %r, %o", r, &ol);
    apply(n->op, r, &ob);
    free_operand(&ob);
    if (size == 1)
        emit("%iZXB %r", r);
    emit("%iMOV %o, %r", &ol, r);
    free_operand(&ol);
    if (!want) {
        free_reg(r);
        return 0;
    }
    return r;
}

static void step(int r, int delta)
{
    if (delta == 1)
        emit("%iINC %r, %r", r, r);
    else if (delta == -1)
        emit("%iDEC %r, %r", r, r);
    else if (delta > 0)
        emit("%iADD %r, #%d", r, delta);
    else
        emit("%iSUB %r, #%d", r, -delta);
}

static int gen_incdec(struct node *n, int want)
{
    struct node *l = n->a;
    struct operand ol;
    int r, old = 0;
    if (l->kind == N_VAR && l->sym->reg) {
        int rv = l->sym->reg;
        if (want && n->kind == N_POSTINC) {
            old = alloc_temp();
            emit("%iMOV %r, %r", old, rv);
        }
        step(rv, n->val);
        if (!want)
            return 0;
        return n->kind == N_POSTINC ? old : gen(l);
    }
    gen_operand(l, &ol);
    if (!want && (n->val == 1 || n->val == -1)) {
        emit("%i%s %o", n->val == 1 ? "INC" : "DEC", &ol);
        free_operand(&ol);
        return 0;
    }
    r = alloc_temp();
    emit("%iMOV %r, %o", r, &ol);
    if (want && n->kind == N_POSTINC) {
        old = alloc_temp();
        emit("%iMOV %r, %r", old, r);
    }
    step(r, n->val);
    emit("%iMOV %o, %r", &ol, r);
    free_operand(&ol);
    if (!want) {
        free_reg(r);
        return 0;
    }
    if (n->kind == N_POSTINC) {
        free_reg(r);
        return old;
    }
    return r;
}

/* A string literal's label, its bytes written out the first time. */
static int string_label(int k)
{
    struct strlit *s = &strings[k];
    if (!s->label) {
        int i;
        char line[128], *p;
        s->label = k + 1;
        data_emit("");
        data_emit("        .section .data.__S%d", s->label);
        data_emit("__S%d:", s->label);
        /* sixteen bytes to a line, as the C compiler writes them */
        for (i = 0; i <= s->len; i += 16) {
            int j;
            p = line;
            for (j = i; j <= s->len && j < i + 16; j++) {
                int c = (unsigned char)s->s[j];
                if (j > i) {
                    *p++ = ',';
                    *p++ = ' ';
                }
                if (c >= 100)
                    *p++ = (char)('0' + c / 100);
                if (c >= 10)
                    *p++ = (char)('0' + c / 10 % 10);
                *p++ = (char)('0' + c % 10);
            }
            *p = 0;
            data_emit("        .byte %s", line);
        }
    }
    return s->label;
}

/* A register holding n's value; a register variable is its own
   register, which the caller must not change. */
static int gen_ro(struct node *n)
{
    struct operand o;
    int r, f, e;
    switch (n->kind) {
    case N_NUM:
        r = alloc_temp();
        emit("%iMOV %r, #%d", r, n->val);
        return r;
    case N_STR:
        r = alloc_temp();
        emit("%iLEA %r, [__S%d]", r, string_label(n->val));
        return r;
    case N_VAR:
        if (n->sym->reg)
            return n->sym->reg;
        var_operand(n->sym, &o);
        r = alloc_temp();
        if (n->type->kind == TY_ARRAY || n->type->kind == TY_STRUCT)
            emit("%iLEA %r, %o", r, &o);
        else
            emit("%iMOV %r, %o", r, &o);
        return r;
    case N_ADDR:
        var_operand(n->a->sym, &o);
        r = alloc_temp();
        emit("%iLEA %r, %o", r, &o);
        return r;
    case N_DEREF:
        address(n->a, &o, size_of(n->type));
        free_operand(&o);
        r = alloc_temp();
        if (is_scalar(n->type))
            emit("%iMOV %r, %o", r, &o);
        else
            emit("%iLEA %r, %o", r, &o);
        return r;
    case N_NEG:
    case N_BNOT:
        r = gen(n->a);
        emit("%i%s %r", n->kind == N_NEG ? "NEG" : "NOT", r);
        return r;
    case N_NOT:
        r = gen(n->a);
        emit("%iCMP %r, #0", r);
        emit("%iSETEQ %r", r);
        return r;
    case N_CAST:
        if (n->type->kind == TY_CHAR && n->a->type->kind != TY_CHAR) {
            r = gen(n->a);
            emit("%iZXB %r", r);
            return r;
        }
        return gen_ro(n->a);
    case N_BIN:
        if (is_compare_op(n->op)) {
            int u = gen_compare(n);
            r = alloc_temp();
            emit("%iSET%s %r", cond_name(n->op, u, 1), r);
            return r;
        }
        r = gen_pair(n->a, n->b, &o, 0);
        apply(n->op, r, &o);
        free_operand(&o);
        return r;
    case N_ANDAND:
    case N_OROR:
        f = new_label();
        e = new_label();
        r = alloc_temp();
        gen_cond(n, f, 0);
        emit("%iMOV %r, #1", r);
        emit("%iBRA %L", e);
        emit("%L:", f);
        emit("%iMOV %r, #0", r);
        emit("%L:", e);
        return r;
    case N_COND: {
        int t;
        f = new_label();
        e = new_label();
        r = alloc_temp();
        gen_cond(n->a, f, 0);
        t = gen_ro(n->b);
        emit("%iMOV %r, %r", r, t);
        free_reg(t);
        emit("%iBRA %L", e);
        emit("%L:", f);
        t = gen_ro(n->c);
        emit("%iMOV %r, %r", r, t);
        free_reg(t);
        emit("%L:", e);
        return r;
    }
    case N_ASSIGN:
        return gen_assign(n, 1);
    case N_PREINC:
    case N_POSTINC:
        return gen_incdec(n, 1);
    case N_CALL:
        if (n->type->kind == TY_VOID)
            error("void value used");
        return gen_call(n, 1);
    case N_COMMA:
        gen_effect(n->a);
        return gen_ro(n->b);
    }
    error("bad expression");
    return alloc_temp();
}

static void gen_effect(struct node *n)
{
    switch (n->kind) {
    case N_ASSIGN:
        gen_assign(n, 0);
        break;
    case N_PREINC:
    case N_POSTINC:
        gen_incdec(n, 0);
        break;
    case N_CALL:
        gen_call(n, 0);
        break;
    case N_COMMA:
        gen_effect(n->a);
        gen_effect(n->b);
        break;
    default:
        free_reg(gen_ro(n));
    }
}

/* Branches to label if n's truth is sense; falls through otherwise. */
static void gen_cond(struct node *n, int label, int sense)
{
    int skip, r;
    switch (n->kind) {
    case N_NUM:
        if ((n->val != 0) == sense)
            emit("%iBRA %L", label);
        return;
    case N_NOT:
        gen_cond(n->a, label, !sense);
        return;
    case N_ANDAND:
    case N_OROR:
        if ((n->kind == N_ANDAND) == sense) {
            skip = new_label();
            gen_cond(n->a, skip, !sense);
            gen_cond(n->b, label, sense);
            emit("%L:", skip);
        } else {
            gen_cond(n->a, label, sense);
            gen_cond(n->b, label, sense);
        }
        return;
    case N_BIN:
        if (is_compare_op(n->op)) {
            int u = gen_compare(n);
            emit("%iB%s %L", cond_name(n->op, u, sense), label);
            return;
        }
        break;
    }
    r = gen_ro(n);
    emit("%iCMP %r, #0", r);
    free_reg(r);
    emit("%iB%s %L", sense ? "NE" : "EQ", label);
}

/* ---- statements ------------------------------------------------------ */

static void loop_push(int brk, int cont)
{
    if (nloops == MAXLOOPS) {
        error("loops nested too deeply");
        return;
    }
    break_label[nloops] = brk;
    continue_label[nloops] = cont;
    nloops++;
}

static void statement(struct node *n)
{
    int top, test, end, r;
    struct node *s;
    busy = 0;
    switch (n->kind) {
    case N_BLOCK:
        for (s = n->a; s; s = s->next)
            statement(s);
        break;
    case N_EXPR:
        gen_effect(n->a);
        break;
    case N_IF:
        end = new_label();
        gen_cond(n->a, end, 0);
        statement(n->b);
        if (n->c) {
            int other = new_label();
            emit("%iBRA %L", other);
            emit("%L:", end);
            statement(n->c);
            end = other;
        }
        emit("%L:", end);
        break;
    case N_WHILE:
        top = new_label();
        test = new_label();
        end = new_label();
        emit("%iBRA %L", test);
        emit("%L:", top);
        loop_push(end, test);
        statement(n->b);
        nloops--;
        emit("%L:", test);
        gen_cond(n->a, top, 1);
        emit("%L:", end);
        break;
    case N_DO:
        top = new_label();
        test = new_label();
        end = new_label();
        emit("%L:", top);
        loop_push(end, test);
        statement(n->b);
        nloops--;
        emit("%L:", test);
        gen_cond(n->a, top, 1);
        emit("%L:", end);
        break;
    case N_FOR:
        top = new_label();
        test = new_label();
        end = new_label();
        r = new_label();        /* where continue goes: the step */
        if (n->a)
            gen_effect(n->a);
        emit("%iBRA %L", test);
        emit("%L:", top);
        loop_push(end, r);
        statement(n->d);
        nloops--;
        emit("%L:", r);
        if (n->c)
            gen_effect(n->c);
        emit("%L:", test);
        if (n->b)
            gen_cond(n->b, top, 1);
        else
            emit("%iBRA %L", top);
        emit("%L:", end);
        break;
    case N_RETURN:
        if (n->a) {
            struct operand o;
            gen_operand(n->a, &o);
            if (o.kind != O_REG || o.reg != 1)
                emit("%iMOV r1, %o", &o);
            free_operand(&o);
        }
        emit("%iBRA %L", ret_label);
        break;
    case N_BREAK:
        if (nloops)
            emit("%iBRA %L", break_label[nloops - 1]);
        break;
    case N_CONTINUE:
        if (nloops)
            emit("%iBRA %L", continue_label[nloops - 1]);
        break;
    case N_EMPTY:
        break;
    }
}

/* ---- functions ------------------------------------------------------- */

/* Chooses the register variables, the most used first (the earlier
   declared on a tie), and gives the rest frame slots. */
static void allocate_locals(struct func *f)
{
    struct sym *cand[64], *s;
    int n = 0, i, j, off = 0;
    for (s = f->locals; s; s = s->local_next) {
        s->reg = 0;
        if (n < 64 && (s->type->kind == TY_INT || s->type->kind == TY_PTR) &&
            !s->addressed && s->uses >= 2)
            cand[n++] = s;
    }
    for (i = 1; i < n; i++) {   /* insertion sort, most used first */
        s = cand[i];
        for (j = i; j > 0 && (cand[j - 1]->uses < s->uses ||
                              (cand[j - 1]->uses == s->uses && cand[j - 1]->order > s->order)); j--)
            cand[j] = cand[j - 1];
        cand[j] = s;
    }
    nregvars = n < NREGVARS ? n : NREGVARS;
    for (i = 0; i < nregvars; i++)
        cand[i]->reg = 8 + i;
    /* the others in the frame, in declaration order: walk the list,
       which is newest first, into an array */
    n = 0;
    for (s = f->locals; s; s = s->local_next)
        if (!s->reg && n < 64)
            cand[n++] = s;
    for (i = n - 1; i >= 0; i--) {
        int a = cand[i]->type->align;
        off = (off + a - 1) & -a;
        cand[i]->offset = off;
        off += cand[i]->type->size;
    }
    locals_size = (off + 3) & ~3;
}

void gen_function(struct func *f)
{
    struct sym *s;
    int frame, first, last, body_end;
    busy = 0;
    spill_top = spill_max = 0;
    nloops = 0;
    ret_label = new_label();
    nlines_fn = PROLOGUE;
    allocate_locals(f);
    /* the parameters arrive in r1-r4 */
    for (s = f->locals; s; s = s->local_next) {
        if (s->sclass != SC_PARAM)
            continue;
        if (s->reg)
            emit("%iMOV %r, %r", s->reg, s->val + 1);
        else
            emit("%iMOV [sp + %d], %r", s->offset, s->val + 1);
    }
    statement(f->body);
    emit("%L:", ret_label);
    frame = locals_size + 4 * spill_max;
    first = f->calls ? 7 : 8;
    last = 7 + nregvars;
    /* the prologue, in the lines left for it */
    body_end = nlines_fn;
    nlines_fn = 0;
    emit("");
    emit("        .section .text.%n", f->sym->name);
    if (!f->sym->is_static)
        emit("        .global %n", f->sym->name);
    else
        lines[nlines_fn++] = 0;
    emit("%n:", f->sym->name);
    if (last >= first)
        emit("%iSAVE %r-%r", first, last);
    else
        lines[nlines_fn++] = 0;
    if (frame)
        emit("%iSUB sp, #%d", frame);
    else
        lines[nlines_fn++] = 0;
    nlines_fn = body_end;
    if (frame)
        emit("%iADD sp, #%d", frame);
    if (last >= first)
        emit("%iRESTORE %r-%r", first, last);
    emit("%iRET");
    npeep += peephole();
    text_flush();
}

/* ---- globals --------------------------------------------------------- */

static void data_value(struct type *t, struct node *v)
{
    if (v->kind == N_STR) {
        if (t->kind == TY_PTR)
            data_emit("        .word __S%d", string_label(v->val));
        else
            error("bad initializer");
    } else if (t->kind == TY_CHAR) {
        data_emit("        .byte %d", v->val & 255);
    } else if (is_scalar(t)) {
        data_emit("        .word %d", v->val);
    } else {
        error("bad initializer");
    }
}

void gen_global(struct sym *s, struct node *init)
{
    struct type *t = s->type;
    struct node *v;
    /* the strings it points to are written out first */
    if (init && init->kind == N_STR && t->kind == TY_PTR)
        string_label(init->val);
    for (v = init && init->kind == N_BLOCK ? init->a : 0; v; v = v->next)
        if (v->kind == N_STR)
            string_label(v->val);
    data_emit("");
    data_emit("        .section .%s._%s", init ? "data" : "bss", s->name->str);
    if (!s->is_static)
        data_emit("        .global %n", s->name);
    if (t->align > 1)
        data_emit("        .align %d", t->align);
    data_emit("%n:", s->name);
    if (!init) {
        data_emit("        .space %d", t->size);
    } else if (t->kind == TY_ARRAY && init->kind == N_STR && t->base == ty_char) {
        struct strlit *str = &strings[init->val];
        int i, n = str->len + 1 < t->size ? str->len + 1 : t->size;
        for (i = 0; i < n; i++)
            data_emit("        .byte %d", (unsigned char)str->s[i]);
        if (t->size > n)
            data_emit("        .space %d", t->size - n);
    } else if (t->kind == TY_ARRAY && init->kind == N_BLOCK) {
        int n = 0;
        for (v = init->a; v && n < t->len; v = v->next, n++)
            data_value(t->base, v);
        if (n < t->len)
            data_emit("        .space %d", (t->len - n) * t->base->size);
    } else if (is_scalar(t) && init->kind != N_BLOCK) {
        data_value(t, init);
    } else {
        error("bad initializer");
        data_emit("        .space %d", t->size);
    }
}

void gen_finish(void)
{
    text_flush();
}
