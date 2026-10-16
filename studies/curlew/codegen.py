"""STG to draft 2 assembly (implementation.md, "Code").

Values (32 bits; the two low bits are the tag):

    ...00   an immediate: an Int or Char n as 4n, a constructor without
            fields as 4 * its tag. Always evaluated.
    ...10   a pointer, plus 2, to an evaluated object: a constructor, a
            function closure or a partial application
    ...01   a pointer, plus 1, to an object that may not be evaluated: a
            thunk, an indirection, a CAF
    ...11   never a value: an object's header

So bit 0 says "not evaluated yet", which is what draft 2's tagged
operations check. Objects are 4-byte aligned and at least 2 words:

    pair    [field 0][field 1]: the only constructor with fields of its
            type, with 1 or 2 of them. No header.
    boxed   [header][fields...]: any other constructor with fields
    thunk   [header][free variables...]
    fun     [header][free variables...]
    pap     [header][function][4n][n arguments]
    ind     [header][value]: a thunk after its update

A header is its code's entry address + 1, the entry at 4k + 2; the info
word, at header - 7, holds the kind, the arity or constructor tag, and the
size. Calling through a header jumps to the entry (JMP and CALL clear
bit 0 of the target).

Registers: arguments in r1-r5, r0, r8-r10 (in that order), and the result
in r1; r6 the node (the closure being entered); r7 the link; r12 scratch;
r13 the heap limit less SLACK; r14 the heap pointer; sp. Every register
but r13-r15 is caller-saved. A variable keeps one register while it lives;
around a call the live ones are saved and restored, with SAVE and
RESTORE on a range or with pushes, whichever costs less.

Evaluation checks are inline, `TST r, #1` and a branch to an out-of-line
slow path that saves what's live, enters the thunk and restores: the
common case, an evaluated value, costs a test and a branch not taken,
and a function that only calls on slow paths keeps its return address in
r7 and returns with RET.
"""

from . import stg as G

ARGS = [1, 2, 3, 4, 5, 0, 8, 9, 10]
ALLOC = [6, 5, 4, 3, 2, 1, 8, 9, 10, 11, 0]
SCRATCH, HPLIM, HP, LINK, NODE = 12, 13, 14, 7, 6
SLACK = 1024        # r13 is the heap's end less this; an allocation this big needs one compare

THUNK, FUN, PAP, IND, CON = 1, 2, 3, 4, 5

# profile categories (profile.py, report)
CATS = ("eval", "evalslow", "entry", "update", "alloc", "heapchk", "stkchk", "call", "save",
        "return", "apply", "case", "field", "arith", "ovf", "move", "jump", "error", "gcslow")


class Options:
    def __init__(self, tagged=False, indcheck=True, stack_check=True, one_reg=False,
                 upd_tail=True):
        self.tagged = tagged            # draft 2's tagged operations: TMOV checks, TADD/TSUB
        self.indcheck = indcheck        # a slow path follows an indirection itself
        self.stack_check = stack_check  # check the stack limit (else a guard page would)
        self.one_reg = one_reg          # keep 1 in r11 for a one-parcel TST (software only)
        self.upd_tail = upd_tail        # a thunk's tail call returns straight to the update


def mangle(name):
    out = []
    for c in name:
        if c.isalnum() or c == "_":
            out.append(c)
        else:
            out.append(f"_{ord(c):02x}")
    s = "".join(out)
    return "c_" + s


def word_text(w):
    w &= 0xFFFFFFFF
    return str(w - (1 << 32)) if w & 0x80000000 else str(w)


def imm(atom):
    """An atom that isn't a variable, as an assembler constant. A
    global's label is a Core name, mangled, unless it starts with '=',
    the code generator's own."""
    if isinstance(atom, G.ALit):
        return word_text(atom.word)
    lab = atom.label[1:] if atom.label.startswith("=") else mangle(atom.label)
    return f"{lab} + {atom.tag}"


class State:
    """Where variables are, in one code path."""

    allocs = ALLOC              # the registers variables may have

    def __init__(self, fun_ctx):
        self.regs = {}          # variable -> register
        self.held = {}          # register -> set of variables
        self.fun_ctx = fun_ctx  # r7 holds the return address

    def copy(self):
        s = State(self.fun_ctx)
        s.allocs = self.allocs
        s.regs = dict(self.regs)
        s.held = {r: set(v) for r, v in self.held.items()}
        return s

    def bind(self, var, reg):
        self.unbind(var)
        self.regs[var] = reg
        self.held.setdefault(reg, set()).add(var)

    def unbind(self, var):
        r = self.regs.pop(var, None)
        if r is not None:
            self.held[r].discard(var)
            if not self.held[r]:
                del self.held[r]

    def prune(self, live):
        for v in list(self.regs):
            if v not in live:
                self.unbind(v)

    def busy(self):
        out = set(self.held)
        if self.fun_ctx:
            out.add(LINK)
        return out

    def free(self, avoid=()):
        busy = self.busy() | set(avoid)
        return [r for r in self.allocs if r not in busy]


class Ctx:
    """Where a value goes: 'ret' (r1, then RET), 'upd' (r1, then the
    thunk's update), 'cont' (into reg, then to label, keeping `keep`
    alive)."""

    def __init__(self, kind, label=None, reg=None, keep=frozenset()):
        self.kind, self.label, self.reg, self.keep = kind, label, reg, keep


class CodeGen:
    def __init__(self, prog, options=None):
        self.prog = prog
        self.opt = options or Options()
        self.lines = []             # (text, category)
        self.data = []
        self.cafs = []
        self.queue = []
        self.queued = set()
        self.n = 0
        self.statics = {}           # variable -> atom of a static object it was bound to
        self.fun_labels = {}        # function (global or local closure variable) -> (generic, fast)
        self.trap_sites = []        # (label, live register mask) for the tag trap handler
        self.slow = []              # the current code block's out-of-line code
        self.con_info = {}          # DataInfo name -> label of its constructor info block
        self.joins = {}             # join point -> (label, param registers)
        self.whnf = prog.whnf
        State.allocs = [r for r in ALLOC if not (self.opt.one_reg and r == 11)]

    # ---- output

    def label(self, base="L"):
        self.n += 1
        return f"{base}{self.n}"

    def emit(self, text, cat=None):
        self.lines.append(("        " + text, cat))

    def put_label(self, name):
        self.lines.append((f"{name}:", None))

    def emit_slow(self, text, cat):
        self.slow.append(("        " + text, cat))

    def slow_label(self, name):
        self.slow.append((f"{name}:", None))

    # ---- the program

    def run(self):
        prog = self.prog
        for t in prog.tops:
            if isinstance(t, G.TopFun):
                self.fun_labels[t.name] = (mangle(t.name), mangle(t.name) + "_f")
        for name, f in prog.fun_objs.items():
            lab = self.label("fn_")
            f.label = lab
            self.fun_labels[name] = (lab, lab + "_f")
        for t in prog.tops:
            if isinstance(t, G.TopFun):
                self.top_fun(t)
            elif isinstance(t, G.TopCaf):
                self.caf(mangle(t.name), t.body)
            elif isinstance(t, G.TopCon):
                self.static_con(mangle(t.name), t.con, t.args)
        for s in prog.strings:
            self.static_string(mangle(s.name), s.codes)
        while self.queue:
            kind, obj = self.queue.pop(0)
            if kind == "thunk":
                self.thunk_block(obj.label, obj.fvs, obj.body)
            else:
                self.fun_block(obj)
        return self

    def text(self):
        """The generated assembly, and the category of each line (by its
        line number in the text, 1-based)."""
        out, cats = [], {}
        out.append("; Generated by studies/curlew/codegen.py: don't edit.")
        out.append("")
        out.append("code_start:")
        lines = peephole(self.lines)
        for text, cat in lines:
            out.append(text)
            if cat:
                cats[len(out)] = cat
        out.append("code_end:")
        out.append("")
        out.append("; ---- constructor info blocks")
        for name, lab in self.con_info.items():
            d = self.prog.datas[name]
            out.append("        .align 4")
            out.append(f"{lab}:")
            for c in d.cons:
                out.append(f"        .word {CON} | {c.tag} << 8 | {1 + c.arity} << 16    ; {c.name}")
            out.append("        .word 0, 0")
        out.append("")
        out.append("; ---- static objects")
        out += self.data
        out.append("")
        out.append("; ---- CAFs: static thunks, roots for the collector")
        out.append("        .align 4")
        out.append("caf_start:")
        out += self.cafs
        out.append("caf_end:")
        out.append("")
        out.append("; ---- the tag trap's table: (address, live registers) by address")
        out.append("        .align 4")
        out.append("trap_table:")
        for lab, mask in self.trap_sites:
            out.append(f"        .word {lab}, {mask}")
        out.append("trap_table_end:")
        out.append("")
        out.append(f"MAIN_ATOM = {imm(self.prog.main)}")
        return "\n".join(out) + "\n", cats

    # ---- info tables and entries

    def info(self, entry, kind, arity, size, name=""):
        """An entry point with its info word in front (entry at 4k + 2)."""
        self.lines.append(("        .align 4", None))
        self.lines.append((f"        .word 0             ; {name}", None))
        self.lines.append((f"        .word {kind} | {arity} << 8 | {size} << 16", None))
        self.lines.append(("        .half 0", None))
        self.put_label(entry)

    def hdr(self, entry):
        return f"{entry} + 1"

    def con_hdr(self, con):
        d = con.data
        lab = self.con_info.get(d.name)
        if lab is None:
            lab = self.con_info[d.name] = self.label("ci_")
        return f"{lab} + {4 * con.tag + 7}"

    def finish_block(self):
        self.lines += self.slow
        self.slow = []

    # ---- static data

    def static_con(self, label, con, args):
        r = repr_of(con)
        words = [imm(self.static_atom(a)) for a in args]
        self.data.append("        .align 4")
        if r == "pair":
            if len(words) == 1:
                words.append("0")
            self.data.append(f"{label}: .word {', '.join(words)}")
        else:
            self.data.append(f"{label}: .word {self.con_hdr(con)}{''.join(', ' + w for w in words)}")

    def static_atom(self, a):
        if isinstance(a, G.AVar):
            raise AssertionError(f"a static object refers to {a.name}")
        return a

    def static_string(self, label, codes):
        self.data.append("        .align 4")
        for i, c in enumerate(codes):
            nxt = f"{label}_{i + 1} + 2" if i + 1 < len(codes) else "0"
            name = label if i == 0 else f"{label}_{i}"
            self.data.append(f"{name}: .word {4 * c}, {nxt}")

    def caf(self, label, body):
        entry = label + "_e"
        self.cafs.append(f"{label}: .word {self.hdr(entry)}, 0")
        self.thunk_block(entry, [], body, name=label)

    # ---- code blocks

    def top_fun(self, t):
        generic, fast = self.fun_labels[t.name]
        self.data.append("        .align 4")
        self.data.append(f"{mangle(t.name)}_40clo: .word {self.hdr(generic)}")
        self.function(generic, fast, t.params, t.strict, [], t.body, t.name)

    def fun_block(self, f):
        generic, fast = self.fun_labels[f.name]
        self.function(generic, fast, f.params, f.strict, f.fvs, f.body, f.name)

    def function(self, generic, fast, params, strict, fvs, body, name):
        self.info(generic, FUN, len(params), 1 + len(fvs), name)
        st = State(True)
        for p, r in zip(params, ARGS):
            st.bind(p, r)
        node = "%node"
        if fvs:
            st.bind(node, NODE)
            st.bind(name, NODE)     # a local closure refers to itself through its node
        live = set(params) | ({node, name} if fvs else set())
        for p, s in zip(params, strict):
            if s:
                self.force(st, st.regs[p], live, "entry")
        self.put_label(fast)
        if fvs:
            live = G.free(body, self.prog.joins)
            if name not in live:
                st.unbind(name)
            self.load_fvs(st, fvs, 2, live, "entry")
        self.gen(body, st, Ctx("ret"))
        self.finish_block()

    def thunk_block(self, entry, fvs, body, name=""):
        self.info(entry, THUNK, 0, 1 + max(1, len(fvs)), name)
        self.emit("SAVE r6-r7", "update")
        self.stack_check()
        st = State(False)
        st.bind("%node", NODE)
        self.load_fvs(st, fvs, 1, G.free(body, self.prog.joins), "update")
        self.gen(body, st, Ctx("upd"))
        self.finish_block()

    def load_fvs(self, st, fvs, tag, live, cat):
        """Load a closure's free variables from the node in r6 (tagged
        `tag`) into registers; the node is dead after."""
        todo = [(i, v) for i, v in enumerate(fvs) if v in live]
        regs = st.free(avoid=[NODE])
        last = None
        for i, v in todo:
            if regs:
                r = regs.pop(0)
            else:
                last = (i, v)
                continue
            self.emit(f"MOV  r{r}, [r6 + {4 * i + 4 - tag}]", cat)
            st.bind(v, r)
        if last is not None:
            if len(st.held.get(NODE, ())) > 1:
                raise NotImplementedError("out of registers for free variables")
            i, v = last
            self.emit(f"MOV  r6, [r6 + {4 * i + 4 - tag}]", cat)
            st.unbind("%node")
            st.bind(v, NODE)
        st.unbind("%node")

    def stack_check(self):
        if self.opt.stack_check:
            self.emit("CMP  sp, [stack_limit]", "stkchk")
            self.emit("BLO  rt_stack", "stkchk")

    # ---- atoms

    def resolve(self, a):
        if isinstance(a, G.AVar) and a.name in self.statics:
            return self.statics[a.name]
        return a

    def whnf_atom(self, a):
        a = self.resolve(a)
        if isinstance(a, G.ALit):
            return True
        if isinstance(a, G.AGlobal):
            return a.tag == 2
        return a.name in self.whnf

    def src(self, st, a):
        """An atom as a source operand: 'rN' or '#const'."""
        a = self.resolve(a)
        if isinstance(a, G.AVar):
            return f"r{st.regs[a.name]}"
        return "#" + imm(a)

    def load(self, st, a, reg, cat="move"):
        s = self.src(st, a)
        if s != f"r{reg}":
            self.emit(f"MOV  r{reg}, {s}", cat)

    def to_reg(self, st, a, cat="move"):
        """The register an atom is in, loading it into a new one if it
        isn't a variable (the new register is bound to a temporary)."""
        a = self.resolve(a)
        if isinstance(a, G.AVar):
            return st.regs[a.name]
        r = st.free()[0]
        self.emit(f"MOV  r{r}, #{imm(a)}", cat)
        tmp = self.label("%tmp")
        st.bind(tmp, r)
        return r

    # ---- moving and saving registers

    def pmove(self, st, moves, cat="move"):
        """Parallel move: moves is [(destination register, atom)]."""
        regmoves = []
        consts = []
        for d, a in moves:
            a = self.resolve(a)
            if isinstance(a, G.AVar):
                s = st.regs[a.name]
                if s != d:
                    regmoves.append([d, s])
            else:
                consts.append((d, a))
        while regmoves:
            srcs = {s for _, s in regmoves}
            for m in regmoves:
                if m[0] not in srcs:
                    self.emit(f"MOV  r{m[0]}, r{m[1]}", cat)
                    regmoves.remove(m)
                    break
            else:
                # a cycle: break it through the scratch register
                d, s = regmoves[0]
                self.emit(f"MOV  r{SCRATCH}, r{s}", cat)
                for m in regmoves:
                    if m[1] == s:
                        m[1] = SCRATCH
        for d, a in consts:
            self.emit(f"MOV  r{d}, #{imm(a)}", cat)

    def save(self, regs, cat):
        return plan_save(regs, cat)

    def live_regs(self, st, live):
        out = {st.regs[v] for v in live if v in st.regs}
        if st.fun_ctx:
            out.add(LINK)
        return out

    # ---- evaluation checks

    def force(self, st, reg, live, cat="eval"):
        """Evaluate the value in reg, in place. live: variables live after."""
        saved = self.live_regs(st, live) | {reg}
        if self.opt.tagged:
            lab = self.label("T")
            self.put_label(lab)
            self.emit(f"TMOV r{reg}, r{reg}", cat)
            mask = 0
            for r in saved:
                mask |= 1 << r
            self.trap_sites.append((lab, mask))
            return
        slow, back = self.label("S"), self.label("B")
        if self.opt.one_reg:
            self.emit(f"TST  r{reg}, r11", cat)
        else:
            self.emit(f"TST  r{reg}, #1", cat)
        self.emit(f"BNE  {slow}", cat)
        self.put_label(back)
        self.slow_label(slow)
        if self.opt.indcheck:
            # an indirection needn't be entered
            enter = self.label("S")
            self.emit_slow(f"MOV  r12, [r{reg} - 1]", "evalslow")
            self.emit_slow("CMP  r12, #ind_entry + 1", "evalslow")
            self.emit_slow(f"BNE  {enter}", "evalslow")
            self.emit_slow(f"MOV  r{reg}, [r{reg} + 3]", "evalslow")
            self.emit_slow(f"BRA  {back}", "evalslow")
            self.slow_label(enter)
        code, slots, restore = self.save(saved, "evalslow")
        self.slow += [("        " + t, c) for t, c in code]
        if reg != NODE:
            self.emit_slow(f"MOV  r6, r{reg}", "evalslow")
        self.emit_slow("CALL [r6 - 1]", "evalslow")
        self.emit_slow(f"MOV  [sp + {slots[reg]}], r1", "evalslow")
        self.slow += [("        " + t, c) for t, c in restore]
        self.emit_slow(f"BRA  {back}", "evalslow")

    # ---- expressions

    def gen(self, e, st, ctx):
        live = G.free(e, self.prog.joins) | ctx.keep
        st.prune(live)
        t = type(e)
        if t is G.Ret:
            self.gen_ret(e.atom, st, ctx)
        elif t is G.Call:
            self.gen_call(e, st, ctx)
        elif t is G.Apply:
            self.gen_apply(e, st, ctx)
        elif t is G.PrimOp:
            d = self.dest(st, ctx)
            self.prim(e.op, e.args, st, d)
            self.finish(st, ctx, d)
        elif t is G.Alloc:
            d = self.dest(st, ctx)
            self.alloc(st, [(None, G.ConClo(e.con, e.args))], live, d)
            self.finish(st, ctx, d)
        elif t is G.Let:
            self.gen_let(e, st, ctx)
        elif t is G.Case:
            self.gen_case(e, st, ctx)
        elif t is G.LetJoin:
            self.gen_letjoin(e, st, ctx)
        elif t is G.Jump:
            self.gen_jump(e, st)
        elif t is G.Error:
            self.load(st, e.atom, 1, "error")
            self.emit("JMP  rt_error", "error")
        else:
            raise AssertionError(e)

    def dest(self, st, ctx):
        return ctx.reg if ctx.kind == "cont" else 1

    def finish(self, st, ctx, reg):
        """The value is in reg, evaluated: deliver it."""
        if ctx.kind == "ret":
            if reg != 1:
                self.emit(f"MOV  r1, r{reg}", "return")
            self.emit("RET", "return")
        elif ctx.kind == "upd":
            if reg != 1:
                self.emit(f"MOV  r1, r{reg}", "return")
            self.emit("JMP  upd", "return")
        else:
            if reg != ctx.reg:
                self.emit(f"MOV  r{ctx.reg}, r{reg}", "return")
            self.emit(f"BRA  {ctx.label}", "return")

    def gen_ret(self, a, st, ctx):
        a = self.resolve(a)
        if self.whnf_atom(a):
            d = self.dest(st, ctx)
            self.load(st, a, d, "return")
            self.finish(st, ctx, d)
            return
        if ctx.kind == "cont":
            r = self.to_reg(st, a)
            self.force(st, r, ctx.keep)
            self.finish(st, ctx, r)
            return
        # enter it: it returns to our caller (or to the update)
        self.load(st, a, NODE, "return")
        if ctx.kind == "upd" and not self.opt.upd_tail:
            st.bind("%v", NODE)
            self.force(st, NODE, set())
            self.finish(st, ctx, NODE)
            return
        val = self.label("V")
        self.emit("TST  r6, #1", "return")
        self.emit(f"BEQ  {val}", "return")
        if ctx.kind == "upd":
            self.emit("MOV  r7, #upd", "return")
        self.emit("JMP  [r6 - 1]", "return")
        self.put_label(val)
        self.emit("MOV  r1, r6", "return")
        self.emit("RET" if ctx.kind == "ret" else "JMP  upd", "return")

    def call_target(self, e):
        generic, fast = self.fun_labels[e.fn]
        return fast

    def gen_call(self, e, st, ctx):
        target = self.call_target(e)
        moves = list(zip(ARGS, e.args))
        if e.local is not None:
            moves.append((NODE, G.AVar(e.local)))
        self.do_call(st, ctx, moves, target)

    def gen_apply(self, e, st, ctx):
        n = len(e.args)
        moves = list(zip(ARGS, e.args)) + [(NODE, e.fn)]
        self.do_call(st, ctx, moves, f"ap_{n}", cat="apply")

    def do_call(self, st, ctx, moves, target, cat="call", indirect=False):
        if ctx.kind == "ret":
            self.pmove(st, moves, cat)
            self.emit(f"JMP  {target}", cat)
            return
        if ctx.kind == "upd" and self.opt.upd_tail:
            self.pmove(st, moves, cat)
            self.emit("MOV  r7, #upd", cat)
            self.emit(f"JMP  {target}", cat)
            return
        keep = ctx.keep if ctx.kind == "cont" else set()
        d = self.nontail(st, keep, moves, target, cat)
        if ctx.kind == "upd":
            self.finish(st, ctx, d)
        else:
            self.finish(st, ctx, d)

    def nontail(self, st, live, moves, target, cat="call", dest=None):
        """Call with the live variables saved; the result in a register
        (returned), which isn't one the live variables are in."""
        saved = self.live_regs(st, live)
        code, slots, restore = self.save(saved, "save")
        for t, c in code:
            self.emit(t, c)
        if code:
            self.stack_check()
        self.pmove(st, moves, cat)
        self.emit(f"CALL {target}", cat)
        held = {st.regs[v] for v in live if v in st.regs}
        if dest is None:
            dest = 1 if 1 not in held else st.free(avoid=held | {LINK})[0]
        # a range RESTORE also restores registers between the saved ones:
        # then the result goes into its slot
        if dest in slots:
            self.emit(f"MOV  [sp + {slots[dest]}], r1", "save")
        elif dest != 1:
            self.emit(f"MOV  r{dest}, r1", "move")
        for t, c in restore:
            self.emit(t, c)
        return dest

    # ---- allocation

    def closure_size(self, c):
        if isinstance(c, G.Thunk):
            return 1 + max(1, len(c.fvs))
        if isinstance(c, G.Fun):
            return 1 + len(c.fvs)
        if isinstance(c, G.ConClo):
            return 2 if repr_of(c.con) == "pair" else 1 + len(c.args)
        if isinstance(c, (G.PapClo, G.PapLocal)):
            return 3 + len(c.args)
        raise AssertionError(c)

    def gen_let(self, e, st, ctx):
        items = []
        for x, c in e.binds:
            G.closure_fv(c, self.prog.joins)
            # (a thunk without free variables stays in the heap: as a static
            # CAF, a root forever, it would keep all of what it evaluates to)
            if isinstance(c, G.Fun) and not c.fvs:
                generic, fast = self.fun_labels[c.name]
                lab = generic + "_clo"
                self.data.append("        .align 4")
                self.data.append(f"{lab}: .word {self.hdr(generic)}")
                if id(c) not in self.queued:
                    self.queued.add(id(c))
                    self.queue.append(("fun", c))
                self.statics[x] = G.AGlobal("=" + lab, 2)
            else:
                items.append((x, c))
        if items:
            live = G.free(e.body, self.prog.joins) | ctx.keep
            for x, c in items:
                live |= G.closure_fv(c, self.prog.joins)
            self.alloc(st, items, live - {x for x, _ in items}, None)
        self.gen(e.body, st, ctx)

    def queue_thunk(self, c, label):
        c.label = label
        self.queue.append(("thunk", c))

    def alloc(self, st, items, live, dest):
        """Allocate closures: items [(variable or None, closure)]. A
        variable is bound to its closure; with None, the pointer goes into
        dest. live: variables live across the heap check."""
        sizes = [self.closure_size(c) for _, c in items]
        total = 4 * sum(sizes)
        self.heap_check(st, live, total)
        offs = []
        o = 0
        for s in sizes:
            offs.append(o)
            o += 4 * s
        # the variables' pointers first, so closures can refer to each other;
        # dest's last, since it may hold a field
        def pointer(r, off, c):
            tag = 1 if isinstance(c, G.Thunk) else 2
            if off + tag == 1:
                self.emit(f"INC  r{r}, r14", "alloc")
            else:
                self.emit(f"LEA  r{r}, [r14 + {off + tag}]", "alloc")
        for (x, c), off in zip(items, offs):
            if x is not None:
                free = st.free()
                if not free:
                    raise NotImplementedError("out of registers")
                r = free[0]
                st.bind(x, r)
                pointer(r, off, c)
        for (x, c), off in zip(items, offs):
            self.fill(st, c, off)
        for (x, c), off in zip(items, offs):
            if x is None:
                pointer(dest, off, c)
        self.emit(f"ADD  r14, #{total}", "alloc")

    def heap_check(self, st, live, total):
        gc, back = self.label("G"), self.label("H")
        self.put_label(back)
        if total <= SLACK:
            self.emit("CMP  r14, r13", "heapchk")
        else:
            self.emit("MOV  r12, r14", "heapchk")
            self.emit(f"ADD  r12, #{total - SLACK}", "heapchk")
            self.emit("CMP  r12, r13", "heapchk")
        self.emit(f"BHI  {gc}", "heapchk")
        self.slow_label(gc)
        code, slots, restore = self.save(self.live_regs(st, live), "gcslow")
        self.slow += [("        " + t, c) for t, c in code]
        self.emit_slow(f"MOV  r12, #{total}", "gcslow")
        self.emit_slow("CALL rt_gc", "gcslow")
        self.slow += [("        " + t, c) for t, c in restore]
        self.emit_slow(f"BRA  {back}", "gcslow")

    def store_word(self, st, off, a):
        a = self.resolve(a)
        if isinstance(a, G.AVar):
            self.emit(f"MOV  [r14 + {off}], r{st.regs[a.name]}", "alloc")
        elif isinstance(a, G.ALit) and a.word == 0:
            self.emit(f"CLR  [r14 + {off}]", "alloc")
        else:
            self.emit(f"MOV  r12, #{imm(a)}", "alloc")
            self.emit(f"MOV  [r14 + {off}], r12", "alloc")

    def store_hdr(self, off, hdr):
        self.emit(f"MOV  r12, #{hdr}", "alloc")
        self.emit(f"MOV  [r14 + {off}], r12", "alloc")

    def fill(self, st, c, off):
        if isinstance(c, G.Thunk):
            if c.label is None:
                self.queue_thunk(c, self.label("thk_"))
            self.store_hdr(off, self.hdr(c.label))
            for i, v in enumerate(c.fvs):
                self.store_word(st, off + 4 + 4 * i, G.AVar(v))
            if not c.fvs:
                self.emit(f"CLR  [r14 + {off + 4}]", "alloc")
        elif isinstance(c, G.Fun):
            if id(c) not in self.queued:
                self.queued.add(id(c))
                self.queue.append(("fun", c))
            generic, fast = self.fun_labels[c.name]
            self.store_hdr(off, self.hdr(generic))
            for i, v in enumerate(c.fvs):
                self.store_word(st, off + 4 + 4 * i, G.AVar(v))
        elif isinstance(c, G.ConClo):
            if repr_of(c.con) == "pair":
                self.store_word(st, off, c.args[0])
                if len(c.args) > 1:
                    self.store_word(st, off + 4, c.args[1])
                else:
                    self.emit(f"CLR  [r14 + {off + 4}]", "alloc")
            else:
                self.store_hdr(off, self.con_hdr(c.con))
                for i, a in enumerate(c.args):
                    self.store_word(st, off + 4 + 4 * i, a)
        else:
            fn = (G.AGlobal(c.fn + "@clo", 2) if isinstance(c, G.PapClo) else G.AVar(c.fn))
            self.store_hdr(off, "pap_entry + 1")
            self.store_word(st, off + 4, fn)
            self.store_word(st, off + 8, G.ALit(4 * len(c.args)))
            for i, a in enumerate(c.args):
                self.store_word(st, off + 12 + 4 * i, a)

    # ---- primitives

    def prim(self, op, args, st, d):
        """A primitive on evaluated atoms, its result into register d."""
        if op in ("ord", "chr"):
            self.load(st, args[0], d, "arith")
            return
        if op == "neg":
            self.emit(f"NEG  r{d}, {self.src_reg(st, args[0])}", "arith")
            self.emit(f"BVS  {self.ovf_label()}", "ovf")
            return
        if op in ("eq", "ne", "lt", "le", "gt", "ge"):
            self.compare(st, args)
            self.emit(f"SET{COND[op]} r{d}", "arith")
            self.emit(f"LSL  r{d}, #2", "arith")
            return
        a, b = args
        # d mustn't be b's register unless it's also a's
        bsrc = self.src(st, b)
        asrc = self.src(st, a)
        if bsrc == f"r{d}" and asrc != f"r{d}":
            if op in ("add", "mul", "and", "or", "xor"):
                a, b = b, a
                asrc, bsrc = bsrc, asrc
            else:
                t = SCRATCH
                self.emit(f"MOV  r{t}, {asrc}", "arith")
                self.prim_into(op, t, b, st)
                self.emit(f"MOV  r{d}, r{t}", "arith")
                return
        if asrc != f"r{d}":
            self.emit(f"MOV  r{d}, {asrc}", "arith")
        self.prim_into(op, d, b, st)

    def prim_into(self, op, d, b, st):
        """d <- d op b."""
        bsrc = self.src(st, b)
        if op in ("add", "sub"):
            if self.opt.tagged and bsrc.startswith("r"):
                self.emit(f"T{op.upper()} r{d}, {bsrc}", "arith")
            else:
                self.emit(f"{op.upper()}  r{d}, {bsrc}", "arith")
                self.emit(f"BVS  {self.ovf_label()}", "ovf")
            return
        if op in ("and", "or", "xor"):
            self.emit(f"{op.upper()}  r{d}, {bsrc}", "arith")
            return
        if op == "mul":
            if bsrc.startswith("#"):
                self.emit(f"MULS r{d}, #{word_signed(b) >> 2}", "arith")
            elif bsrc == f"r{d}":
                # x * x: unscale a copy
                self.emit(f"MOV  r12, r{d}", "arith")
                self.emit("ASR  r12, #2", "arith")
                self.emit(f"MULS r{d}, r12", "arith")
            else:
                self.emit(f"ASR  r{d}, #2", "arith")
                self.emit(f"MULS r{d}, {bsrc}", "arith")
            self.emit(f"BVS  {self.ovf_label()}", "ovf")
            return
        if op in ("quot", "rem", "div", "mod"):
            if not bsrc.startswith("r"):
                self.emit(f"MOV  r12, {bsrc}", "arith")
                bsrc = "r12"
            self.emit(f"DIVS r{d}, {bsrc}", "arith")
            if op in ("div", "mod"):
                ok = self.label("D")
                self.emit("MFHI r12", "arith")
                self.emit("TST  r12, r12", "arith")
                self.emit(f"BEQ  {ok}", "arith")
                self.emit(f"XOR  r12, {bsrc}", "arith")
                self.emit(f"BPL  {ok}", "arith")
                if op == "div":
                    self.emit(f"DEC  r{d}", "arith")
                else:
                    self.emit("MFHI r12", "arith")
                    self.emit(f"ADD  r12, {bsrc}", "arith")
                    self.emit("MTHI r12", "arith")
                self.put_label(ok)
            if op in ("rem", "mod"):
                self.emit(f"MFHI r{d}", "arith")
            else:
                self.emit(f"ADD  r{d}, r{d}", "arith")
                self.emit(f"BVS  {self.ovf_label()}", "ovf")
                self.emit(f"ADD  r{d}, r{d}", "arith")
                self.emit(f"BVS  {self.ovf_label()}", "ovf")
            return
        if op == "shl":
            self.emit(f"MOV  r12, {bsrc}", "arith")
            self.emit("ASR  r12, #2", "arith")
            self.emit(f"LSL  r{d}, r12", "arith")
            return
        if op == "shr":
            self.emit(f"MOV  r12, {bsrc}", "arith")
            self.emit("ASR  r12, #2", "arith")
            self.emit(f"ASR  r{d}, r12", "arith")
            self.emit(f"AND  r{d}, #-4", "arith")
            return
        raise AssertionError(op)

    def src_reg(self, st, a):
        s = self.src(st, a)
        if s.startswith("r"):
            return s
        self.emit(f"MOV  r12, {s}", "arith")
        return "r12"

    def ovf_label(self):
        return "rt_overflow"

    def compare(self, st, args):
        """Set the flags for args[0] - args[1]; returns whether the operands
        were swapped."""
        a, b = args
        asrc, bsrc = self.src(st, a), self.src(st, b)
        if not asrc.startswith("r"):
            self.emit(f"MOV  r12, {asrc}", "arith")
            asrc = "r12"
        if self.opt.tagged and bsrc.startswith("r"):
            self.emit(f"TCMP {asrc}, {bsrc}", "arith")
        else:
            self.emit(f"CMP  {asrc}, {bsrc}", "arith")

    # ---- case

    def gen_case(self, e, st, ctx):
        joins = self.prog.joins
        alive = set(ctx.keep)
        for a in e.alts:
            alive |= G.free(a.body, joins) - set(a.vars)
        if e.default is not None:
            alive |= G.free(e.default, joins)
        alive.discard(e.binder)
        s = e.scrut
        t = type(s)
        if t is G.PrimOp and s.op in COND and self.bool_alts(e) and e.binder not in self.used_binder(e):
            self.compare(st, s.args)
            self.branch_bool(e, st, ctx, COND[s.op])
            return
        if t is G.Ret:
            a = self.resolve(s.atom)
            if isinstance(a, G.AVar):
                r = st.regs[a.name]
                if not self.whnf_atom(a):
                    self.force(st, r, alive | {a.name})
                st.bind(e.binder, r)
            else:
                r = self.to_reg(st, a)
                if not self.whnf_atom(a):
                    self.force(st, r, alive)
                st.bind(e.binder, r)
        elif t is G.PrimOp:
            r = st.free()[0]
            self.prim(s.op, s.args, st, r)
            st.bind(e.binder, r)
        elif t is G.Alloc:
            r = st.free()[0]
            self.alloc(st, [(None, G.ConClo(s.con, s.args))], alive | G.free(s, joins), r)
            st.bind(e.binder, r)
        elif t is G.Call or t is G.Apply:
            if t is G.Call:
                target = self.call_target(s)
                moves = list(zip(ARGS, s.args))
                if s.local is not None:
                    moves.append((NODE, G.AVar(s.local)))
                cat = "call"
            else:
                target = f"ap_{len(s.args)}"
                moves = list(zip(ARGS, s.args)) + [(NODE, s.fn)]
                cat = "apply"
            r = self.nontail(st, alive, moves, target, cat)
            st.prune(alive)
            st.bind(e.binder, r)
        else:
            held = {st.regs[v] for v in alive if v in st.regs}
            r = st.free(avoid=held)[0]
            lab = self.label("K")
            self.gen(s, st.copy(), Ctx("cont", lab, r, frozenset(alive)))
            self.put_label(lab)
            st.prune(alive)
            st.bind(e.binder, r)
        self.dispatch(e, st, ctx, st.regs[e.binder])

    def used_binder(self, e):
        joins = self.prog.joins
        out = set()
        for a in e.alts:
            out |= G.free(a.body, joins)
        if e.default is not None:
            out |= G.free(e.default, joins)
        return out

    def bool_alts(self, e):
        return all(a.con is not None and a.con.data.name == "Bool" for a in e.alts)

    def branch_bool(self, e, st, ctx, cond):
        """After a compare: the True alternative if cond holds, else
        False."""
        alts = {a.con.name: a.body for a in e.alts}
        t_body = alts.get("True", e.default)
        f_body = alts.get("False", e.default)
        lab = self.label("F")
        self.emit(f"B{NEGATE[cond]}  {lab}", "case")
        self.gen(t_body, st.copy(), ctx)
        self.put_label(lab)
        self.gen(f_body, st.copy(), ctx)

    def dispatch(self, e, st, ctx, r):
        """Branch on the evaluated value in r."""
        alts = e.alts
        if not alts:
            self.gen(e.default, st, ctx)
            return
        if alts[0].con is None:
            self.dispatch_lits(e, st, ctx, r)
            return
        data = alts[0].con.data
        imms = [c for c in data.cons if c.arity == 0]
        ptrs = [c for c in data.cons if c.arity > 0]
        by_con = {a.con: a for a in alts}
        targets = {}            # constructor -> label
        default_lab = self.label("X") if e.default is not None else None

        def target(c):
            if c in by_con:
                if c not in targets:
                    targets[c] = self.label("A")
                return targets[c]
            return default_lab

        # immediates against pointers
        imm_lab = None
        if imms and ptrs:
            used_imms = [c for c in imms if target(c) is not None]
            if len(imms) == 1:
                w = 4 * imms[0].tag
                self.emit(f"CMP  r{r}, #{w}" if w else f"TST  r{r}, r{r}", "case")
                self.emit(f"BEQ  {target(imms[0])}", "case")
            else:
                imm_lab = self.label("I")
                self.emit(f"TST  r{r}, #2", "case")
                self.emit(f"BEQ  {imm_lab}", "case")
            del used_imms
        # pointers
        if ptrs:
            if len(ptrs) == 1:
                self.emit(f"BRA  {target(ptrs[0])}", "case")
            else:
                self.emit(f"MOV  r12, [r{r} - 2]", "case")
                for c in ptrs[:-1]:
                    self.emit(f"CMP  r12, #{self.con_hdr(c)}", "case")
                    self.emit(f"BEQ  {target(c)}", "case")
                self.emit(f"BRA  {target(ptrs[-1])}", "case")
        if imm_lab is not None or not ptrs:
            if imm_lab is not None:
                self.put_label(imm_lab)
            for c in imms[:-1]:
                w = 4 * c.tag
                self.emit(f"CMP  r{r}, #{w}" if w else f"TST  r{r}, r{r}", "case")
                self.emit(f"BEQ  {target(c)}", "case")
            self.emit(f"BRA  {target(imms[-1])}", "case")
        # the alternative the last branch goes to first, so the branch goes
        order = list(targets.items())
        last = self.lines[-1][0].strip() if self.lines else ""
        if last.startswith("BRA "):
            first = last.split(None, 1)[1]
            order.sort(key=lambda cl: cl[1] != first)
        for c, lab in order:
            a = by_con[c]
            self.put_label(lab)
            s2 = st.copy()
            self.load_fields(s2, a, r)
            self.gen(a.body, s2, ctx)
        if default_lab is not None:
            self.put_label(default_lab)
            self.gen(e.default, st.copy(), ctx)

    def load_fields(self, st, alt, r):
        live = G.free(alt.body, self.prog.joins)
        pair = repr_of(alt.con) == "pair"
        for i, v in enumerate(alt.vars):
            if v not in live:
                continue
            off = (4 * i - 2) if pair else (4 * i + 2)
            d = st.free()[0]
            self.emit(f"MOV  r{d}, [r{r} + {off}]" if off >= 0 else f"MOV  r{d}, [r{r} - {-off}]",
                      "field")
            st.bind(v, d)

    def dispatch_lits(self, e, st, ctx, r):
        labs = []
        for a in e.alts:
            lab = self.label("A")
            w = (4 * a.lit) & 0xFFFFFFFF
            self.emit(f"CMP  r{r}, #{word_text(w)}", "case")
            self.emit(f"BEQ  {lab}", "case")
            labs.append(lab)
        dl = self.label("X")
        self.emit(f"BRA  {dl}", "case")
        for a, lab in zip(e.alts, labs):
            self.put_label(lab)
            self.gen(a.body, st.copy(), ctx)
        self.put_label(dl)
        if e.default is None:
            self.emit("JMP  rt_nomatch", "error")
        else:
            self.gen(e.default, st.copy(), ctx)

    # ---- join points

    def gen_letjoin(self, e, st, ctx):
        joins = self.prog.joins
        jfv = joins[e.name]
        held = {st.regs[v] for v in jfv if v in st.regs}
        avoid = set(held)
        if ctx.kind == "cont":
            avoid |= {st.regs[v] for v in ctx.keep if v in st.regs} | {ctx.reg}
        free = [r for r in st.allocs if r not in avoid and not (st.fun_ctx and r == LINK)]
        params = free[:len(e.params)]
        if len(params) < len(e.params):
            raise NotImplementedError("too many join point parameters")
        lab = self.label("J")
        self.joins[e.name] = (lab, params)
        js = State(st.fun_ctx)
        for v in jfv:
            if v in st.regs:
                js.bind(v, st.regs[v])
        if ctx.kind == "cont":
            for v in ctx.keep:
                if v in st.regs:
                    js.bind(v, st.regs[v])
        for p, r in zip(e.params, params):
            js.bind(p, r)
        self.gen(e.rest, st.copy(), ctx)
        self.put_label(lab)
        self.gen(e.body, js, ctx)

    def gen_jump(self, e, st):
        lab, params = self.joins[e.name]
        self.pmove(st, list(zip(params, e.args)), "jump")
        self.emit(f"BRA  {lab}", "jump")


COND = {"eq": "EQ", "ne": "NE", "lt": "LT", "le": "LE", "gt": "GT", "ge": "GE"}
NEGATE = {"EQ": "NE", "NE": "EQ", "LT": "GE", "GE": "LT", "LE": "GT", "GT": "LE"}


def word_signed(a):
    w = a.word
    return w - (1 << 32) if w & 0x80000000 else w


def repr_of(con):
    """'imm' (no fields), 'pair' (headerless) or 'boxed'."""
    if con.arity == 0:
        return "imm"
    with_fields = [c for c in con.data.cons if c.arity > 0]
    if len(with_fields) == 1 and con.arity <= 2:
        return "pair"
    return "boxed"


def plan_save(regs, cat):
    """Save registers: (code, {register: offset from sp}, restore code),
    code as [(text, category)]. A range costs SAVE and RESTORE, 2 + 2n
    cycles each on D32-separate, and a push 4 and a pop 5. A dead
    register inside the range has its slot cleared (4 cycles): it may hold
    a pointer from before a collection, which the next one mustn't follow.
    (Not the register: the call may still read it, as an argument.)"""
    regs = sorted(set(regs))
    if not regs:
        return [], {}, []
    best = None
    for a in [None] + regs:
        for b in ([None] if a is None else [r for r in regs if r >= a]):
            inside = [r for r in regs if a is not None and a <= r <= b]
            outside = [r for r in regs if r not in inside]
            n = 0 if a is None else b - a + 1
            dead = n - len(inside)
            cost = (4 + 4 * n + 4 * dead if n else 0) + 9 * len(outside)
            if best is None or cost < best[0]:
                best = (cost, a, b, outside)
    _, a, b, outside = best
    code, restore = [], []
    slots = {}
    for r in outside:
        code.append((f"MOV  -[sp], r{r}", cat))
    n = 0
    if a is not None:
        code.append((f"SAVE r{a}-r{b}", cat))
        for r in range(a, b + 1):
            if r not in regs:
                code.append((f"CLR  [sp + {4 * (r - a)}]", cat))
        n = b - a + 1
        for r in range(a, b + 1):
            slots[r] = 4 * (r - a)
        restore.append((f"RESTORE r{a}-r{b}", cat))
    for i, r in enumerate(reversed(outside)):
        slots[r] = 4 * n + 4 * i
    for r in reversed(outside):
        restore.append((f"MOV  r{r}, [sp]+", cat))
    return code, slots, restore


def peephole(lines):
    """Drop a branch to the label that follows it."""
    out = []
    for i, (text, cat) in enumerate(lines):
        t = text.strip()
        if t.startswith(("BRA ", "JMP ")) and i + 1 < len(lines):
            target = t.split(None, 1)[1].strip()
            j = i + 1
            nxt = lines[j][0]
            while nxt.endswith(":") and not nxt.startswith(" "):
                if nxt[:-1] == target:
                    break
                j += 1
                if j >= len(lines):
                    break
                nxt = lines[j][0]
            if nxt.endswith(":") and nxt[:-1] == target:
                continue
        out.append((text, cat))
    return out


def generate(prog, options=None):
    return CodeGen(prog, options).run()
