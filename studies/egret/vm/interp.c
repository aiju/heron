/* The interpreter: a bytecode loop over a value stack and a frame stack.

   Every Egret send to an Egret method stays in this loop: it pushes a
   frame and carries on, so the C stack doesn't grow. Primitives are C
   functions called from the loop; the few that need the interpreter
   itself (new, call, raise, send) are carried out here. */

#include "compiler.h"

Stats stats;
Value prim_error;

#ifdef EGRET_STATS
#define COUNT(x) (stats.x++)
#else
#define COUNT(x) ((void)0)
#endif

/* ---- the method cache ------------------------------------------------------- */

#define CACHE_SIZE 1024
typedef struct CacheEntry {
    Value cls, sel, method, pad;
} CacheEntry;
static CacheEntry mcache[CACHE_SIZE];

void interp_flush_cache(void) { memset(mcache, 0, sizeof mcache); }

/* the entry's byte offset is (cls ^ sel) & 0x3FF0: one XOR and one AND */
#define CACHE_INDEX(cls, sel) ((((cls) ^ (sel)) >> 4) & (CACHE_SIZE - 1))

static Value lookup(Value cls, Value sel)
{
    CacheEntry *e = &mcache[CACHE_INDEX(cls, sel)];
    Value m;
    COUNT(cache_misses);
    m = class_lookup(cls, sel);
    if (m) {
        e->cls = cls;
        e->sel = sel;
        e->method = m;
    }
    return m;
}

/* ---- frames, handlers --------------------------------------------------------- */

static Frame *frames, *frames_end;
static Value *vstack_end;
static unsigned serial_counter;
static Frame *vm_fp;            /* the frame below the next interpreter's base */

typedef struct Handler {
    Frame *fp;
    Value *sp;
    unsigned char *ip;
} Handler;
#define MAX_HANDLERS 64
static Handler handlers[MAX_HANDLERS];
static int nhandlers;

/* the selectors of the bytecodes with fast paths */
static Value special[NOPCODES];
#define special_sel(op) (special[op])

void interp_init(void)
{
    static const char *const names[] = { "+", "-", "*", "/", "%", "<", "<=", ">", ">=", "==", "[]", "[]=", "&", "|", "^", "<<", ">>" };
    int i;
    for (i = 0; i <= OP_SHR - OP_ADD; i++)
        special[OP_ADD + i] = intern_c(names[i]);
    frames = (Frame *)P(FRAMES_LO);
    frames_end = (Frame *)P(FRAMES_HI) - 1;
    vstack_end = P(VSTACK_HI) - 64;
    vm_fp = frames;
    vm_fp->method = 0;
    interp_flush_cache();
}

/* ---- errors -------------------------------------------------------------------- */

Value prim_fail(const char *msg)
{
    prim_error = make_string_c(msg);
    return 0;
}

Value prim_fail_v(Value err)
{
    prim_error = err;
    return 0;
}

/* a message from C text and a Symbol or String */
static Value msg3(const char *a, Value s, const char *b)
{
    static char buf[200];
    unsigned n = strlen(a), k = s ? SIZE(s) : 0, m = strlen(b);
    if (k > 100)
        k = 100;
    if (m > 80)
        m = 80;
    memcpy(buf, a, n);
    if (k)
        memcpy(buf + n, BYTES(s), k);
    memcpy(buf + n + k, b, m);
    return make_string(buf, n + k + m);
}

static int line_at(Value m, Value ipaddr)
{
    Value lt = F(m, M_LINES);
    unsigned off = ipaddr - V(BYTES(F(m, M_CODE))), i, n;
    unsigned short *e;
    int line = F(m, M_LINE);
    if (!lt || lt == NIL)
        return line;
    n = SIZE(lt) / 4;
    e = (unsigned short *)BYTES(lt);
    for (i = 0; i < n && e[2 * i] < off; i++)
        line = e[2 * i + 1];
    return line;
}

static void print_where(Value m, Value ipaddr)
{
    Value owner = F(m, M_OWNER), sel = F(m, M_SEL);
    out_str("  in ");
    if (F(m, M_INFO) & MF_BLOCK)
        out_str("a block in ");
    if (owner != NIL && owner != cls_Object) {
        Value n = class_name(owner);
        out_bytes(BYTES(n), SIZE(n));
        out_char('#');
    }
    out_bytes(BYTES(sel), SIZE(sel));
    out_str(" (line ");
    out_int(line_at(m, ipaddr));
    out_str(")\n");
}

static void report(Value err, Frame *fp, unsigned char *ip, Frame *base)
{
    Value msg = err;
    int depth = 0;
    if (!IS_INT(err) && is_a(err, cls_Error))
        msg = F(err, E_MESSAGE);
    out_str("error: ");
    if (!IS_INT(msg) && (CLASSW(msg) == cls_String || CLASSW(msg) == cls_Symbol))
        out_bytes(BYTES(msg), SIZE(msg));
    else {
        Value n = class_name(CLASS_OF(err));
        out_str("a ");
        out_bytes(BYTES(n), SIZE(n));
    }
    out_char('\n');
    print_where(fp->method, V(ip));
    for (fp--; fp >= base; fp--) {
        if (++depth > 12) {
            out_str("  ...\n");
            break;
        }
        print_where(fp->method, fp->ip);
    }
}

/* ---- the interpreter ----------------------------------------------------------- */

#define FIELD(o, i) (P(o)[2 + (i)])
#define LITS(m) (&FIELD(FIELD(m, M_LITS), 0))
#define CODE(m) (BYTES(FIELD(m, M_CODE)))
#define W16(p) ((SValue)(short)((p)[0] | (p)[1] << 8))

/* Runs method m on the receiver and argc arguments at the top of the value
   stack, until it returns. 1 and its result, or 0 after an uncaught error
   (which it reports). */
static int interpret(Value m, int argc, Value *result, int flags)
{
    Value *sp = vm_sp, *bp;
    Frame *fp = vm_fp, *base = vm_fp + 1;
    unsigned char *ip = 0;
    Value *lits;
    Value method;
    Value sel, rcv, cls, info, err, retval;
    int base_handlers = nhandlers;
    int frame_flags = flags | FR_BASE;
    Value *entry_sp = sp - argc - 1;
    unsigned op;

    method = 0;
    lits = 0;
    bp = sp - argc;
    rcv = bp[0];
    goto invoke;

    for (;;) {
#ifdef EGRET_STATS
        stats.bytecodes++;
#endif
        op = *ip++;
#ifdef EGRET_TRACE
        {
            extern void trace_op(Value method, unsigned char *ip, Value *sp, Value *bp);
            trace_op(method, ip - 1, sp, bp);
        }
#endif
        switch (op) {
        case OP_PUSH_NIL: *++sp = NIL; continue;
        case OP_PUSH_TRUE: *++sp = TRUE_V; continue;
        case OP_PUSH_FALSE: *++sp = FALSE_V; continue;
        case OP_PUSH_SELF: *++sp = bp[0]; continue;
        case OP_PUSH_BSELF: *++sp = FIELD(bp[0], CL_SELF); continue;
        case OP_PUSH_INT: *++sp = MKINT((signed char)*ip); ip++; continue;
        case OP_PUSH_LIT: *++sp = lits[*ip++]; continue;
        case OP_PUSH_LOCAL: *++sp = bp[*ip++]; continue;
        case OP_STORE_LOCAL: bp[*ip++] = *sp; continue;
        case OP_POP_LOCAL: bp[*ip++] = *sp--; continue;
        case OP_PUSH_BOXED: *++sp = FIELD(bp[*ip++], 0); continue;
        case OP_STORE_BOXED: FIELD(bp[*ip++], 0) = *sp; continue;
        case OP_PUSH_CAPT: *++sp = FIELD(bp[0], CL_CAPT + *ip++); continue;
        case OP_STORE_CAPT: FIELD(bp[0], CL_CAPT + *ip++) = *sp; continue;
        case OP_PUSH_CAPT_BOXED: *++sp = FIELD(FIELD(bp[0], CL_CAPT + *ip++), 0); continue;
        case OP_STORE_CAPT_BOXED: FIELD(FIELD(bp[0], CL_CAPT + *ip++), 0) = *sp; continue;
        case OP_PUSH_IVAR: *++sp = FIELD(bp[0], *ip++); continue;
        case OP_STORE_IVAR: FIELD(bp[0], *ip++) = *sp; continue;
        case OP_PUSH_BIVAR: *++sp = FIELD(FIELD(bp[0], CL_SELF), *ip++); continue;
        case OP_STORE_BIVAR: FIELD(FIELD(bp[0], CL_SELF), *ip++) = *sp; continue;
        case OP_PUSH_GLOBAL: {
            Value v = globals[ip[0] | ip[1] << 8];
            if (!v) {
                vm_sp = sp;
                err = msg3("", global_names[ip[0] | ip[1] << 8], " isn't defined");
                goto raise_msg;
            }
            ip += 2;
            *++sp = v;
            continue;
        }
        case OP_STORE_GLOBAL:
            globals[ip[0] | ip[1] << 8] = *sp;
            ip += 2;
            continue;
        case OP_POP: sp--; continue;
        case OP_DUP: sp[1] = sp[0]; sp++; continue;

        case OP_SEND:
            sel = lits[ip[0]];
            argc = ip[1];
            ip += 2;
        send:
            rcv = sp[-argc];
            cls = CLASS_OF(rcv);
        lookup: {
            CacheEntry *e = &mcache[CACHE_INDEX(cls, sel)];
            COUNT(sends);
            if (e->cls == cls && e->sel == sel)
                m = e->method;
            else if ((m = lookup(cls, sel)) == 0)
                goto not_understood;
        }
        invoke:
            info = FIELD(m, M_INFO);
            if (MI_NARGS(info) != (unsigned)argc || (info & MF_REST)) {
                if (!(info & MF_REST) || argc < (int)MI_NARGS(info) - 1)
                    goto arity;
                if (!FIELD(m, M_PRIM)) {
                    /* the extra arguments become a List in the last parameter */
                    int extra = argc - (MI_NARGS(info) - 1), i;
                    Value l;
                    vm_sp = sp;
                    push_root(&m);
                    l = make_list(extra);
                    pop_roots(1);
                    for (i = 0; i < extra; i++)
                        FIELD(FIELD(l, L_ITEMS), i) = sp[i - extra + 1];
                    FIELD(l, L_SIZE) = MKINT(extra);
                    sp -= extra;
                    *++sp = l;
                    argc = MI_NARGS(info);
                }
            }
            if (FIELD(m, M_PRIM)) {
                Value p = FIELD(m, M_PRIM), r;
                if (p >= PR_FIRST_C) {
                    COUNT(prim_calls);
                    vm_sp = sp;
                    r = prim_table[p](sp - argc, argc);
                    if (!r) {
                        err = prim_error;
                        prim_error = NIL;
                        goto raise_msg;
                    }
                    sp -= argc;
                    *sp = r;
                    if (frame_flags & FR_BASE) {
                        /* a primitive called straight from C */
                        *result = r;
                        vm_sp = sp - 1;
                        return 1;
                    }
                    continue;
                }
                switch (p) {
                case PR_NEW:
                    /* rcv is a class: make an instance, then send it init */
                    if (INT(FIELD(rcv, C_KIND)) != K_OBJECT) {
                        vm_sp = sp;
                        err = msg3("can't make a ", class_name(rcv), " with new");
                        goto raise_msg;
                    }
                    vm_sp = sp;
                    rcv = alloc_obj(rcv, INT(FIELD(rcv, C_NIVARS)));
                    sp[-argc] = rcv;
                    cls = CLASSW(rcv);
                    sel = sym_init;
                    {
                        CacheEntry *e = &mcache[CACHE_INDEX(cls, sel)];
                        if (e->cls == cls && e->sel == sel)
                            m = e->method;
                        else if ((m = lookup(cls, sel)) == 0)
                            goto not_understood;
                    }
                    frame_flags |= FR_CONSTRUCT;
                    goto invoke;
                case PR_CALL:
                    COUNT(block_calls);
                    m = FIELD(rcv, CL_METHOD);
                    goto invoke;
                case PR_RAISE:
                    err = sp[0];
                    if (!IS_INT(err) && CLASSW(err) == cls_String) {
                        vm_sp = sp;
                        err = make_error_v(err);
                    }
                    sp -= argc;
                    goto raise;
                case PR_SEND: {
                    /* obj.send(:name, args...) */
                    int i;
                    if (argc < 1 || IS_INT(sp[1 - argc]) || CLASSW(sp[1 - argc]) != cls_Symbol) {
                        vm_sp = sp;
                        err = make_string_c("send needs a method name (a Symbol)");
                        goto raise_msg;
                    }
                    sel = sp[1 - argc];
                    for (i = 1 - argc; i < 0; i++)
                        sp[i] = sp[i + 1];
                    sp--;
                    argc--;
                    goto send;
                }
                }
            }
            /* push a frame for an Egret method */
            if (fp >= frames_end || sp + MI_NLOCALS(info) >= vstack_end) {
                vm_sp = sp;
                err = make_string_c("stack overflow (recursion too deep)");
                goto raise_msg;
            }
            if (fp >= base)
                fp->ip = V(ip);
            fp++;
            bp = sp - argc;
            fp->bp = V(bp);
            fp->method = m;
            fp->serial = 0;
            fp->flags = frame_flags;
            frame_flags = 0;
            {
                unsigned n = MI_NLOCALS(info);
                while (n--)
                    *++sp = NIL;
            }
            method = m;
            lits = LITS(m);
            ip = CODE(m);
#ifdef EGRET_STATS
            if ((unsigned)(fp - frames) > stats.frames_max)
                stats.frames_max = fp - frames;
#endif
            continue;

        not_understood: {
            /* does_not_understand(name, args), or an error */
            static Value sym_dnu;
            Value h;
            int i;
            if (!sym_dnu)
                sym_dnu = intern_c("does_not_understand");
            h = class_lookup(cls, sym_dnu);
            if (h && sel != sym_dnu) {
                Value l;
                vm_sp = sp;
                push_root(&h);
                push_root(&sel);
                l = make_list(argc);
                pop_roots(2);
                for (i = 0; i < argc; i++)
                    FIELD(FIELD(l, L_ITEMS), i) = sp[i - argc + 1];
                FIELD(l, L_SIZE) = MKINT(argc);
                sp -= argc;
                *++sp = sel;
                *++sp = l;
                argc = 2;
                m = h;
                goto invoke;
            }
            {
                Value n = class_name(cls);
                static char buf[160];
                unsigned k = SIZE(n) < 60 ? SIZE(n) : 60, j = SIZE(sel) < 60 ? SIZE(sel) : 60;
                memcpy(buf, BYTES(n), k);
                memcpy(buf + k, " does not understand '", 22);
                memcpy(buf + k + 22, BYTES(sel), j);
                buf[k + 22 + j] = '\'';
                vm_sp = sp;
                err = make_string(buf, k + 23 + j);
            }
            goto raise_msg;
        }
        arity: {
            static char buf[160];
            Value n = FIELD(m, M_SEL);
            unsigned k = SIZE(n) < 60 ? SIZE(n) : 60, j;
            const char *a = " takes ";
            memcpy(buf, BYTES(n), k);
            j = k;
            memcpy(buf + j, a, 7);
            j += 7;
            if (info & MF_REST) {
                memcpy(buf + j, "at least ", 9);
                j += 9;
            }
            buf[j++] = '0' + (MI_NARGS(info) - ((info & MF_REST) ? 1 : 0)) % 10;
            memcpy(buf + j, " arguments, not ", 16);
            j += 16;
            if (argc >= 10)
                buf[j++] = '0' + argc / 10;
            buf[j++] = '0' + argc % 10;
            vm_sp = sp;
            err = make_string(buf, j);
            goto raise_msg;
        }

        case OP_SEND_SUPER: {
            Value owner = FIELD(method, M_OWNER);
            sel = lits[ip[0]];
            argc = ip[1];
            ip += 2;
            rcv = sp[-argc];
            cls = FIELD(owner, C_SUPER);
            if (cls == NIL) {
                cls = CLASS_OF(rcv);
                goto not_understood;
            }
            goto lookup;
        }

        /* ---- arithmetic: SmallInts here, anything else as a send ---- */
        case OP_ADD: {
            Value b = sp[0], a = sp[-1], r;
            if (a & b & 1) {
                r = a + (b - 1);
                if ((SValue)((r ^ a) & (r ^ (b - 1))) >= 0) {
                    *--sp = r;
                    COUNT(int_fast);
                    continue;
                }
            }
            static_sel:
            COUNT(int_slow);
            sel = special_sel(op);
            argc = 1;
            goto send;
        }
        case OP_SUB: {
            Value b = sp[0], a = sp[-1], r;
            if (a & b & 1) {
                r = a - (b - 1);
                if ((SValue)((a ^ (b - 1)) & (a ^ r)) >= 0) {
                    *--sp = r;
                    COUNT(int_fast);
                    continue;
                }
            }
            goto static_sel;
        }
        case OP_MUL: {
            Value b = sp[0], a = sp[-1];
            if (a & b & 1) {
                SValue x = INT(a), y = INT(b);
                if ((unsigned)(x + 0x4000) < 0x8000 && (unsigned)(y + 0x4000) < 0x8000) {
                    *--sp = MKINT(x * y);
                    COUNT(int_fast);
                    continue;
                }
            }
            goto static_sel;
        }
        case OP_DIV:
        case OP_MOD: {
            Value b = sp[0], a = sp[-1];
            if (a & b & 1 && b != MKINT(0) && b != MKINT(-1)) {
                SValue x = INT(a), y = INT(b), q = x / y, r = x % y;
                if (r != 0 && (r ^ y) < 0) {
                    q--;
                    r += y;
                }
                *--sp = MKINT(op == OP_DIV ? q : r);
                COUNT(int_fast);
                continue;
            }
            goto static_sel;
        }
        case OP_LT: {
            Value b = sp[0], a = sp[-1];
            if (a & b & 1) {
                *--sp = (SValue)a < (SValue)b ? TRUE_V : FALSE_V;
                continue;
            }
            goto static_sel;
        }
        case OP_LE: {
            Value b = sp[0], a = sp[-1];
            if (a & b & 1) {
                *--sp = (SValue)a <= (SValue)b ? TRUE_V : FALSE_V;
                continue;
            }
            goto static_sel;
        }
        case OP_GT: {
            Value b = sp[0], a = sp[-1];
            if (a & b & 1) {
                *--sp = (SValue)a > (SValue)b ? TRUE_V : FALSE_V;
                continue;
            }
            goto static_sel;
        }
        case OP_GE: {
            Value b = sp[0], a = sp[-1];
            if (a & b & 1) {
                *--sp = (SValue)a >= (SValue)b ? TRUE_V : FALSE_V;
                continue;
            }
            goto static_sel;
        }
        case OP_EQ: {
            Value b = sp[0], a = sp[-1];
            if (a == b) {
                *--sp = TRUE_V;
                continue;
            }
            if (((a | b) & 1) || a - FALSE_V <= TRUE_V - FALSE_V || b - FALSE_V <= TRUE_V - FALSE_V) {
                /* a SmallInt and something else (only a big integer could
                   be equal, and big integers are never SmallInt-sized), or
                   nil, true or false, which are equal only to themselves */
                *--sp = FALSE_V;
                continue;
            }
            goto static_sel;
        }
        case OP_BAND: {
            Value b = sp[0], a = sp[-1];
            if (a & b & 1) {
                *--sp = a & b;
                continue;
            }
            goto static_sel;
        }
        case OP_BOR: {
            Value b = sp[0], a = sp[-1];
            if (a & b & 1) {
                *--sp = a | b;
                continue;
            }
            goto static_sel;
        }
        case OP_BXOR: {
            Value b = sp[0], a = sp[-1];
            if (a & b & 1) {
                *--sp = (a ^ b) | 1;
                continue;
            }
            goto static_sel;
        }
        case OP_SHL: {
            Value b = sp[0], a = sp[-1];
            if (a & b & 1 && b <= MKINT(30)) {
                SValue x = INT(a), n = INT(b), y = (SValue)((unsigned)x << n);
                if ((y >> n) == x && FITS31(y)) {
                    *--sp = MKINT(y);
                    continue;
                }
            }
            goto static_sel;
        }
        case OP_SHR: {
            Value b = sp[0], a = sp[-1];
            if (a & b & 1 && b <= MKINT(31)) {
                *--sp = MKINT(INT(a) >> INT(b));
                continue;
            }
            goto static_sel;
        }
        case OP_AT: {
            Value i = sp[0], a = sp[-1];
            if (IS_INT(i) && !IS_INT(a) && CLASSW(a) == cls_List
                && (unsigned)INT(i) < (unsigned)INT(FIELD(a, L_SIZE))) {
                *--sp = FIELD(FIELD(a, L_ITEMS), INT(i));
                continue;
            }
            goto static_sel;
        }
        case OP_AT_PUT: {
            Value v = sp[0], i = sp[-1], a = sp[-2];
            if (IS_INT(i) && !IS_INT(a) && CLASSW(a) == cls_List
                && (unsigned)INT(i) < (unsigned)INT(FIELD(a, L_SIZE))) {
                FIELD(FIELD(a, L_ITEMS), INT(i)) = v;
                sp -= 2;
                *sp = v;
                continue;
            }
            sel = special_sel(op);
            argc = 2;
            goto send;
        }
        case OP_NOT:
            *sp = FALSY(*sp) ? TRUE_V : FALSE_V;
            continue;

        /* ---- jumps ---- */
        case OP_JUMP:
            ip += 2 + W16(ip);
            continue;
        case OP_JUMP_FALSE:
            if (FALSY(*sp))
                ip += W16(ip);
            ip += 2;
            sp--;
            continue;
        case OP_JUMP_TRUE:
            if (!FALSY(*sp))
                ip += W16(ip);
            ip += 2;
            sp--;
            continue;
        case OP_JUMP_FALSE_OR_POP:
            if (FALSY(*sp))
                ip += W16(ip);
            else
                sp--;
            ip += 2;
            continue;
        case OP_JUMP_TRUE_OR_POP:
            if (!FALSY(*sp))
                ip += W16(ip);
            else
                sp--;
            ip += 2;
            continue;

        /* ---- blocks and returns ---- */
        case OP_CLOSURE: {
            Value bm = lits[ip[0]], c;
            unsigned n = ip[1], i;
            vm_sp = sp;
            c = alloc_obj(cls_Block, CL_CAPT + n);
            FIELD(c, CL_METHOD) = bm;
            if (FIELD(method, M_INFO) & MF_BLOCK) {
                Value outer = bp[0];
                FIELD(c, CL_SELF) = FIELD(outer, CL_SELF);
                FIELD(c, CL_HOME) = FIELD(outer, CL_HOME);
                FIELD(c, CL_SERIAL) = FIELD(outer, CL_SERIAL);
            } else {
                FIELD(c, CL_SELF) = bp[0];
                FIELD(c, CL_HOME) = MKINT(fp - frames);
                if (!fp->serial)
                    fp->serial = MKINT(++serial_counter);
                FIELD(c, CL_SERIAL) = fp->serial;
            }
            for (i = 0; i < n; i++) {
                unsigned k = ip[2 + 2 * i], x = ip[3 + 2 * i];
                FIELD(c, CL_CAPT + i) = k == CK_LOCAL ? bp[x] : FIELD(bp[0], CL_CAPT + x);
            }
            ip += 2 + 2 * n;
            *++sp = c;
            continue;
        }
        case OP_RETURN: {
            unsigned fl;
            retval = *sp;
        do_return:
            fl = fp->flags;
            if (fl & FR_CONSTRUCT)
                retval = bp[0];
            sp = bp;
            *sp = retval;
            fp--;
            if (fl & FR_BASE) {
                *result = retval;
                vm_sp = sp - 1;
                return 1;
            }
            bp = P(fp->bp);
            method = fp->method;
            lits = LITS(method);
            ip = BP(fp->ip);
            continue;
        }
        case OP_RETURN_NLR: {
            Value c = bp[0];
            retval = *sp;
            Frame *home = frames + INT(FIELD(c, CL_HOME));
            COUNT(nlr);
            if (home < base || home > fp || FIELD(c, CL_SERIAL) != home->serial) {
                vm_sp = sp;
                err = make_string_c("return from a block whose method has already returned");
                goto raise_msg;
            }
            while (nhandlers > base_handlers && handlers[nhandlers - 1].fp >= home)
                nhandlers--;
            fp = home;
            bp = P(fp->bp);
            goto do_return;
        }

        /* ---- making objects ---- */
        case OP_MAKE_LIST: {
            int n = *ip++, i;
            Value l;
            vm_sp = sp;
            l = make_list(n);
            for (i = 0; i < n; i++)
                FIELD(FIELD(l, L_ITEMS), i) = sp[1 + i - n];
            FIELD(l, L_SIZE) = MKINT(n);
            sp -= n;
            *++sp = l;
            continue;
        }
        case OP_MAKE_MAP: {
            int n = *ip++, i;
            Value mp;
            vm_sp = sp;
            mp = map_new(n);
            push_root(&mp);
            for (i = 0; i < n; i++)
                map_put(mp, sp[1 + 2 * i - 2 * n], sp[2 + 2 * i - 2 * n]);
            pop_roots(1);
            sp -= 2 * n;
            *++sp = mp;
            continue;
        }
        case OP_MAKE_RANGE: {
            Value a = sp[-1], b = sp[0];
            if (!(a & b & 1)) {
                vm_sp = sp;
                err = make_string_c("a range needs integers");
                goto raise_msg;
            }
            vm_sp = sp;
            *--sp = make_range(INT(a), INT(b) - *ip++);
            continue;
        }
        case OP_CONCAT: {
            int n = *ip++, i;
            unsigned len = 0;
            Value s;
            unsigned char *d;
            for (i = 0; i < n; i++) {
                Value x = sp[1 + i - n];
                if (IS_INT(x) || (CLASSW(x) != cls_String && CLASSW(x) != cls_Symbol)) {
                    vm_sp = sp;
                    err = make_string_c("to_s didn't return a String");
                    goto raise_msg;
                }
                len += SIZE(x);
            }
            vm_sp = sp;
            s = alloc_bytes(cls_String, len);
            d = BYTES(s);
            for (i = 0; i < n; i++) {
                Value x = sp[1 + i - n];
                memcpy(d, BYTES(x), SIZE(x));
                d += SIZE(x);
            }
            sp -= n;
            *++sp = s;
            continue;
        }
        case OP_MAKE_BOX: {
            Value b;
            vm_sp = sp;
            b = alloc_obj(cls_Box, 1);
            FIELD(b, 0) = bp[*ip];
            bp[*ip++] = b;
            continue;
        }

        /* ---- for loops ---- */
        case OP_RANGE_PREP: {
            Value a = sp[-1], b = sp[0];
            unsigned slot = ip[0];
            if (!(a & b & 1)) {
                vm_sp = sp;
                err = make_string_c("for over a range needs integers");
                goto raise_msg;
            }
            bp[slot] = a - 2;
            bp[slot + 1] = ip[1] ? b - 2 : b;
            sp -= 2;
            ip += 2;
            continue;
        }
        case OP_RANGE_NEXT: {
            unsigned slot = ip[0];
            Value i = bp[slot] + 2;
            if ((SValue)i > (SValue)bp[slot + 1]) {
                ip += 3 + W16(ip + 1);
                continue;
            }
            bp[slot] = i;
            *++sp = i;
            ip += 3;
            continue;
        }
        case OP_ITER_PREP: {
            Value it = *sp--;
            unsigned slot = *ip++;
            if (!IS_INT(it) && CLASSW(it) == cls_List) {
                bp[slot] = it;
                bp[slot + 1] = MKINT(0);
            } else if (!IS_INT(it) && CLASSW(it) == cls_Range) {
                bp[slot] = it;
                bp[slot + 1] = FIELD(it, R_FIRST) - 2;
            } else {
                vm_sp = sp;
                err = make_string_c("for: iter must give a List or a Range");
                goto raise_msg;
            }
            continue;
        }
        case OP_ITER_NEXT: {
            unsigned slot = ip[0];
            Value it = bp[slot];
            if (CLASSW(it) == cls_List) {
                Value i = bp[slot + 1];
                if (INT(i) >= INT(FIELD(it, L_SIZE))) {
                    ip += 3 + W16(ip + 1);
                    continue;
                }
                *++sp = FIELD(FIELD(it, L_ITEMS), INT(i));
                bp[slot + 1] = i + 2;
            } else {
                Value i = bp[slot + 1] + 2;
                if ((SValue)i > (SValue)FIELD(it, R_LAST)) {
                    ip += 3 + W16(ip + 1);
                    continue;
                }
                bp[slot + 1] = i;
                *++sp = i;
            }
            ip += 3;
            continue;
        }
        case OP_INC_LOCAL: {
            Value v = bp[ip[0]];
            SValue step = (signed char)ip[1];
            if (IS_INT(v)) {
                Value r = v + 2 * step;
                if (step >= 0 ? (SValue)r >= (SValue)v : (SValue)r < (SValue)v) {
                    bp[ip[0]] = r;
                    ip += 9;
                    continue;
                }
            }
            ip += 2;
            continue;
        }

        /* ---- exceptions ---- */
        case OP_TRY:
            if (nhandlers >= MAX_HANDLERS) {
                vm_sp = sp;
                err = make_string_c("try nested too deeply");
                goto raise_msg;
            }
            handlers[nhandlers].fp = fp;
            handlers[nhandlers].sp = sp;
            handlers[nhandlers].ip = ip + 2 + W16(ip);
            nhandlers++;
            ip += 2;
            continue;
        case OP_END_TRY:
            nhandlers--;
            continue;

        case OP_HALT:
        default:
            vm_sp = sp;
            err = make_string_c("internal: bad bytecode");
            goto raise_msg;
        }

    raise_msg:
        /* err is a message String (or an Error already) */
        vm_sp = sp;
        if (!IS_INT(err) && CLASSW(err) == cls_String)
            err = make_error_v(err);
    raise:
        if (nhandlers > base_handlers) {
            Handler *h = &handlers[--nhandlers];
            fp = h->fp;
            bp = P(fp->bp);
            method = fp->method;
            lits = LITS(method);
            sp = h->sp;
            ip = h->ip;
            *++sp = err;
            continue;
        }
        if (fp < base) {
            /* failed before the first frame: a primitive called from C */
            Value msg = err;
            if (!IS_INT(err) && is_a(err, cls_Error))
                msg = F(err, E_MESSAGE);
            out_str("error: ");
            if (!IS_INT(msg) && CLASSW(msg) == cls_String)
                out_bytes(BYTES(msg), SIZE(msg));
            out_char('\n');
            vm_sp = entry_sp;
            return 0;
        }
        report(err, fp, ip, base);
        vm_sp = entry_sp;
        nhandlers = base_handlers;
        return 0;
    }
}

int run_toplevel(Value method)
{
    Value r;
    *++vm_sp = main_obj;
    return interpret(method, 0, &r, 0);
}

Value send0(Value rcv, Value sel)
{
    Value m = class_lookup(CLASS_OF(rcv), sel), r;
    if (!m)
        return 0;
    *++vm_sp = rcv;
    return interpret(m, 0, &r, 0) ? r : 0;
}

#ifdef EGRET_TRACE
#include <stdio.h>
void trace_op(Value method, unsigned char *ip, Value *sp, Value *bp)
{
    Value sel = FIELD(method, M_SEL);
    fprintf(stderr, "%.*s+%ld op=%d ip1=%d ip2=%d depth=%ld top=%x\n", (int)SIZE(sel), (char *)BYTES(sel),
            (long)(ip - CODE(method)), ip[0], ip[1], ip[2], (long)(sp - bp), sp[0]);
}
#endif
