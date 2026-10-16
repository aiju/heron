"""Core to STG, the form the code generator takes (implementation.md,
"STG").

STG is Core in A-normal form, with every allocation explicit:

    atoms   AVar x | ALit word | AGlobal label+tag
    expr    Ret a                       return a's value (evaluating it)
            Call f [a]                  a known function, all its arguments
            Apply a [a]                 an unknown function value
            PrimOp op [a]               on evaluated atoms
            Alloc K [a]                 allocate a constructor and return it
            Let [(x, closure)] e        allocate closures (they may refer to each other)
            Case e x alts default       evaluate e, bind x to its value, branch
            LetJoin j [x] body e        a join point: a label in the same code
            Jump j [a]
            Error a
    closure Thunk fvs e | Fun fvs [x] e | ConClo K [a] | PapClo f [a]

Strict arguments are evaluated before a call, so a call never allocates a
thunk for one; a `let` whose body demands it is evaluated where it stands.
Every variable is unique in the program, and `whnf` holds those known to
be evaluated wherever they're in scope: case binders, strict parameters,
strict fields, and closures that are values (constructors, functions,
partial applications).
"""

from . import core as C
from .lift import join_arity
from .strictness import Analyser, BOTTOM


# ---- atoms

class AVar:
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name


class ALit:
    """An immediate word: an Int or Char n as 4n, a constructor without
    fields as 4 * its tag."""
    __slots__ = ("word",)

    def __init__(self, word):
        self.word = word & 0xFFFFFFFF

    def __repr__(self):
        return f"#{self.word:#x}"


class AGlobal:
    """A static object's address, tagged: 2 evaluated, 1 not (a CAF)."""
    __slots__ = ("label", "tag")

    def __init__(self, label, tag):
        self.label, self.tag = label, tag

    def __repr__(self):
        return f"{self.label}+{self.tag}"


# ---- expressions

class Expr:
    __slots__ = ()


def node(name, *fields):
    def __init__(self, *args):
        for f, a in zip(fields, args):
            setattr(self, f, a)

    def __repr__(self):
        return f"{name}(" + ", ".join(repr(getattr(self, f)) for f in fields) + ")"
    return type(name, (Expr,), {"__slots__": fields + ("_fv",), "__init__": __init__,
                                "__repr__": __repr__, "fields": fields})


Ret = node("Ret", "atom")
Call = node("Call", "fn", "args", "local")      # local: the closure variable for a local function, else None
Apply = node("Apply", "fn", "args")
PrimOp = node("PrimOp", "op", "args")
Alloc = node("Alloc", "con", "args")
Let = node("Let", "binds", "body")
Case = node("Case", "scrut", "binder", "alts", "default")
LetJoin = node("LetJoin", "name", "params", "body", "rest")
Jump = node("Jump", "name", "args")
Error = node("Error", "atom")


class Alt:
    __slots__ = ("con", "lit", "vars", "body")

    def __init__(self, con, lit, vars, body):
        self.con, self.lit, self.vars, self.body = con, lit, vars, body


# ---- closures

class Thunk:
    __slots__ = ("fvs", "body", "label")

    def __init__(self, fvs, body):
        self.fvs, self.body, self.label = fvs, body, None


class Fun:
    __slots__ = ("fvs", "params", "strict", "body", "label", "name")

    def __init__(self, fvs, params, strict, body, name):
        self.fvs, self.params, self.strict, self.body = fvs, params, strict, body
        self.label = None
        self.name = name


class ConClo:
    __slots__ = ("con", "args")

    def __init__(self, con, args):
        self.con, self.args = con, args


class PapClo:
    __slots__ = ("fn", "args")

    def __init__(self, fn, args):
        self.fn, self.args = fn, args


# ---- top-level things

class TopFun:
    def __init__(self, name, params, strict, body):
        self.name, self.params, self.strict, self.body = name, params, strict, body


class TopCaf:
    def __init__(self, name, body):
        self.name, self.body = name, body


class TopCon:
    def __init__(self, name, con, args):
        self.name, self.con, self.args = name, con, args


class TopStr:
    def __init__(self, name, codes):
        self.name, self.codes = name, codes


class Program:
    def __init__(self, tops, strings, whnf, main, cons, datas):
        self.tops = tops            # [TopFun | TopCaf | TopCon]
        self.strings = strings      # [TopStr]
        self.whnf = whnf            # set of variables known to be evaluated
        self.main = main            # the atom of main
        self.cons = cons
        self.datas = datas


# ---- lowering

class Lowerer:
    def __init__(self, prog, options):
        self.prog = prog
        self.options = options
        self.analyser = Analyser(prog)
        self.sigs = self.analyser.run() if options.strictness else {}
        if not options.strictness:
            self.analyser.sigs = {}
        self.whnf = set()
        self.tops = []
        self.strings = {}           # codes (tuple) -> TopStr
        self.globals = {}           # top-level name -> ('fun', arity) | ('caf',) | ('con', ...) | ('str',) | ('imm', word) | ('alias', name)
        self.locals_fun = {}        # local function closure variable -> (arity, strict)
        self.joins = {}             # join point -> number of parameters
        self.join_args = {}         # join point -> [[atom]] of every jump
        self.join_params = {}
        self.static_cons = []       # constant constructors made static objects
        self.fun_objs = {}          # local function closure variable -> its Fun

    def strict_of(self, name, arity):
        sig = self.sigs.get(name)
        if sig is None or sig[0] != arity:
            return [False] * arity
        return [i in sig[1] for i in range(arity)]

    # ---- the program

    def run(self):
        binds = list(self.prog.binds)
        self.core_of = dict(binds)
        # what each top-level name is
        extra = []
        for n, e in binds:
            t = type(e)
            if t is C.Lam:
                self.globals[n] = ("fun", len(e.params))
            elif t is C.Con:
                self.globals[n] = ("con",)
            elif t is C.Str:
                self.globals[n] = ("str",)
            elif t is C.Lit:
                self.globals[n] = ("imm", lit_word(e))
            elif t is C.Var:
                self.globals[n] = ("alias", e.name)
            else:
                self.globals[n] = ("caf",)
        for n, e in binds:
            t = type(e)
            if t is C.Lam:
                strict = self.strict_of(n, len(e.params))
                for p, s in zip(e.params, strict):
                    if s:
                        self.whnf.add(p)
                self.tops.append(TopFun(n, e.params, strict, self.lo(e.body, {})))
            elif t is C.Con:
                args = []
                for a in e.args:
                    x = self.static_atom(a, {})
                    if x is None:
                        caf = C.fresh(n + ".f")
                        self.globals[caf] = ("caf",)
                        extra.append(TopCaf(caf, self.lo(a, {})))
                        x = AGlobal(caf, 1)
                    args.append(x)
                self.tops.append(TopCon(n, e.con, args))
            elif t is C.Str:
                self.string_label(e.codes, n)
            elif t in (C.Lit, C.Var):
                pass
            else:
                self.tops.append(TopCaf(n, self.lo(e, {})))
        self.tops += extra + self.static_cons
        for j, args in self.join_args.items():
            for i, p in enumerate(self.join_params.get(j, [])):
                if all(self.is_whnf(a[i]) for a in args):
                    self.whnf.add(p)
        main = self.global_atom(self.prog.main)
        out = Program(self.tops, list(self.strings.values()), self.whnf, main,
                      self.prog.cons, self.prog.datas)
        out.fun_objs = self.fun_objs
        return out

    def string_label(self, codes, name=None):
        key = tuple(codes)
        s = self.strings.get(key)
        if s is None:
            s = TopStr(name or C.fresh("str"), list(codes))
            self.strings[key] = s
        return s.name

    def resolve(self, name):
        seen = set()
        while self.globals.get(name, ("",))[0] == "alias" and name not in seen:
            seen.add(name)
            name = self.globals[name][1]
        return name

    def global_atom(self, name):
        name = self.resolve(name)
        g = self.globals[name]
        if g[0] == "fun":
            return AGlobal(name + "@clo", 2)
        if g[0] == "caf":
            return AGlobal(name, 1)
        if g[0] == "con":
            e = self.core_of.get(name)
            if e is not None and not e.args:
                return ALit(4 * e.con.tag)
            return AGlobal(name, 2)
        if g[0] == "str":
            e = self.core_of[name]
            if not e.codes:
                return ALit(0)
            return AGlobal(self.string_label(e.codes, name), 2)
        if g[0] == "imm":
            return ALit(g[1])
        raise AssertionError(g)

    def is_whnf(self, a):
        if isinstance(a, ALit):
            return True
        if isinstance(a, AGlobal):
            return a.tag == 2
        return a.name in self.whnf

    def atom(self, e, sub):
        """The atom of a Var, Lit or Str. sub maps variables to atoms."""
        t = type(e)
        if t is C.Var:
            a = sub.get(e.name)
            if a is not None:
                return a
            if e.name in self.globals:
                return self.global_atom(e.name)
            return AVar(e.name)
        if t is C.Lit:
            return ALit(lit_word(e))
        if t is C.Str:
            if not e.codes:
                return ALit(0)
            return AGlobal(self.string_label(e.codes), 2)
        raise AssertionError(e)

    # ---- expressions in tail position

    def lo(self, e, sub):
        t = type(e)
        if t is C.Var and e.name not in sub and self.joins.get(e.name) == 0:
            self.join_args.setdefault(e.name, []).append([])
            return Jump(e.name, [])
        if t in (C.Var, C.Lit, C.Str):
            return Ret(self.atom(e, sub))
        if t is C.App:
            return self.lo_app(e, sub)
        if t is C.Lam:
            v = C.fresh("fn")
            return Let([(v, self.fun_closure(v, e, sub))], Ret(AVar(v)))
        if t is C.Let:
            return self.lo_let(e, sub)
        if t is C.Case:
            return self.lo_case(e, sub)
        if t is C.Con:
            if not e.args:
                return Ret(ALit(4 * e.con.tag))
            return self.atomize_all(e.args, e.con.strict, sub, lambda xs: Alloc(e.con, xs))
        if t is C.Prim:
            if e.op == "error":
                return self.atomize(e.args[0], False, sub, Error)
            return self.atomize_all(e.args, [True] * len(e.args), sub, lambda xs: PrimOp(e.op, xs))
        raise AssertionError(e)

    def lo_app(self, e, sub):
        f = e.fn
        if type(f) is C.Var:
            a = self.atom(f, sub)
            name = a.name if isinstance(a, AVar) else self.global_name(f, sub)
            if name in self.joins:
                n = self.joins[name]

                def jump(xs):
                    self.join_args.setdefault(name, []).append(xs)
                    return Jump(name, xs)
                # a strict parameter is passed evaluated, as to a function
                return self.atomize_all(e.args, self.strict_of(name, n), sub, jump)
            if name in self.globals:
                name = self.resolve(name)
                g = self.globals[name]
                if g[0] == "fun":
                    return self.call(name, g[1], e.args, sub, None)
            elif name in self.locals_fun:
                arity, strict = self.locals_fun[name]
                return self.call(name, arity, e.args, sub, name, strict)
        return self.atomize(f, True, sub, lambda fa: self.atomize_all(
            e.args, [False] * len(e.args), sub, lambda xs: Apply(fa, xs)))

    def call(self, name, arity, args, sub, local, strict=None):
        if strict is None:
            strict = self.strict_of(name, arity)
        if len(args) == arity:
            return self.atomize_all(args, strict, sub, lambda xs: Call(name, xs, local))
        if len(args) < arity:
            v = C.fresh("pap")
            self.whnf.add(v)
            if local is not None:
                # a partial application of a local closure: an unknown call later
                return self.atomize_all(args, [False] * len(args), sub, lambda xs: Let(
                    [(v, PapLocal(local, xs))], Ret(AVar(v))))
            return self.atomize_all(args, [False] * len(args), sub,
                                    lambda xs: Let([(v, PapClo(name, xs))], Ret(AVar(v))))
        r = C.fresh("over")
        self.whnf.add(r)
        first, rest = args[:arity], args[arity:]
        return self.atomize_all(first, strict, sub, lambda xs: Case(
            Call(name, xs, local), r, [], self.atomize_all(
                rest, [False] * len(rest), sub, lambda ys: Apply(AVar(r), ys))))

    def lo_let(self, e, sub):
        if not e.rec:
            (x, r), = e.binds
            n = join_arity(x, r, e.body, False)
            if n is not None:
                return self.join(x, r, n, e.body, sub)
            rt = type(r)
            if rt in (C.Var, C.Lit, C.Str):
                a = self.atom(r, sub)
                sub = dict(sub)
                sub[x] = a
                return self.lo(e.body, sub)
            if rt is C.Con and not r.args:
                sub = dict(sub)
                sub[x] = ALit(4 * r.con.tag)
                return self.lo(e.body, sub)
            if rt is C.Lam:
                clo = self.fun_closure(x, r, sub)
                return Let([(x, clo)], self.lo(e.body, sub))
            if rt is C.Con or (rt is C.App and self.is_pap(r, sub)):
                sub = dict(sub)
                return self.value_closure(x, r, sub, lambda: self.lo(e.body, sub))
            if self.options.strictness and self.demanded(x, e.body):
                self.whnf.add(x)
                return Case(self.lo(r, sub), x, [], self.lo(e.body, sub))
            return Let([(x, Thunk(None, self.lo(r, sub)))], self.lo(e.body, sub))
        if len(e.binds) == 1:
            (x, r), = e.binds
            n = join_arity(x, r, e.body, True)
            if n is not None:
                return self.join(x, r, n, e.body, sub)
        # a recursive group: closures that may refer to each other
        for x, r in e.binds:
            if type(r) is C.Lam:
                self.locals_fun[x] = (len(r.params), self.strict_of(x, len(r.params)))
        binds = []
        pre = []
        for x, r in e.binds:
            rt = type(r)
            if rt is C.Lam:
                binds.append((x, self.fun_closure(x, r, sub)))
            elif rt is C.Con and all(type(a) in (C.Var, C.Lit, C.Str) for a in r.args):
                self.whnf.add(x)
                binds.append((x, ConClo(r.con, [self.atom(a, sub) for a in r.args])))
            else:
                binds.append((x, Thunk(None, self.lo(r, sub))))
        return Let(binds, self.lo(e.body, sub))

    def global_name(self, f, sub):
        """The top-level function a Var names, or None."""
        if f.name in sub:
            return None
        if f.name in self.globals:
            return self.resolve(f.name)
        return None

    def is_pap(self, r, sub):
        f = r.fn
        if type(f) is not C.Var:
            return False
        name = self.global_name(f, sub)
        if name is not None:
            g = self.globals[name]
            return g[0] == "fun" and len(r.args) < g[1]
        return False

    def value_closure(self, x, r, sub, body):
        """let x = K args, or a partial application, then body(): x is
        bound to a closure, or in sub to a static object's atom."""
        self.whnf.add(x)
        if type(r) is C.Con:
            st = self.static_atom(r, sub)
            if st is not None:
                sub[x] = st
                return body()
            return self.atomize_all(r.args, r.con.strict, sub,
                                    lambda xs: Let([(x, ConClo(r.con, xs))], body()))
        name = self.global_name(r.fn, sub)
        return self.atomize_all(r.args, [False] * len(r.args), sub,
                                lambda xs: Let([(x, PapClo(name, xs))], body()))

    def static_atom(self, e, sub):
        """The atom of a constant: a literal, a string, a global, or a
        constructor of constants, made a static object. None if e isn't
        constant."""
        t = type(e)
        if t is C.Lit or t is C.Str:
            return self.atom(e, sub)
        if t is C.Var:
            a = self.atom(e, sub)
            return a if not isinstance(a, AVar) else None
        if t is C.Con:
            if not e.args:
                return ALit(4 * e.con.tag)
            if any(e.con.strict):
                return None
            args = []
            for a in e.args:
                x = self.static_atom(a, sub)
                if x is None:
                    return None
                args.append(x)
            name = C.fresh("static")
            self.globals[name] = ("con",)
            self.static_cons.append(TopCon(name, e.con, args))
            return AGlobal(name, 2)
        return None

    def demanded(self, x, body):
        d = self.analyser.demands(body, {})
        return d is BOTTOM or x in d

    def join(self, x, r, n, body, sub):
        self.joins[x] = n
        if n == 0:
            jb = self.lo(r, sub)
            params = []
        else:
            params = r.params
            jb = self.lo(r.body, sub)
        self.join_params[x] = params
        rest = self.lo(body, sub)
        if x not in self.join_args:
            return rest         # nothing jumps to it
        return LetJoin(x, params, jb, rest)

    def fun_closure(self, x, lam, sub):
        strict = self.strict_of(x, len(lam.params))
        for p, s in zip(lam.params, strict):
            if s:
                self.whnf.add(p)
        self.whnf.add(x)
        self.locals_fun.setdefault(x, (len(lam.params), strict))
        f = Fun(None, lam.params, strict, None, x)
        self.fun_objs[x] = f
        f.body = self.lo(lam.body, sub)
        return f

    def lo_case(self, e, sub):
        scrut = e.scrut
        self.whnf.add(e.binder)
        alt_sub = sub
        if type(scrut) is C.Var:
            a = self.atom(scrut, sub)
            if isinstance(a, AVar):
                # inside the alternatives, the variable is the evaluated binder
                alt_sub = dict(sub)
                alt_sub[a.name] = AVar(e.binder)
                alt_sub[scrut.name] = AVar(e.binder)
            s = Ret(a)
        else:
            s = self.lo(scrut, sub)
        alts = []
        for a in e.alts:
            if a.con is not None:
                for v, strict in zip(a.vars, a.con.strict):
                    if strict:
                        self.whnf.add(v)
            alts.append(Alt(a.con, a.lit, a.vars, self.lo(a.body, alt_sub)))
        default = None if e.default is None else self.lo(e.default, alt_sub)
        return Case(s, e.binder, alts, default)

    # ---- arguments

    def atomize(self, e, strict, sub, k):
        """k(atom) for e: evaluated first if strict, else a closure."""
        t = type(e)
        if t in (C.Var, C.Lit, C.Str):
            a = self.atom(e, sub)
            if strict and not self.is_whnf(a):
                v = C.fresh("ev")
                self.whnf.add(v)
                return Case(Ret(a), v, [], k(AVar(v)))
            return k(a)
        if t is C.Con:
            st = self.static_atom(e, sub)
            if st is not None:
                return k(st)
            v = C.fresh("con")
            return self.value_closure(v, e, sub, lambda: k(AVar(v)))
        if t is C.Lam:
            v = C.fresh("fn")
            return Let([(v, self.fun_closure(v, e, sub))], k(AVar(v)))
        if t is C.App and self.is_pap(e, sub):
            v = C.fresh("pap")
            return self.value_closure(v, e, sub, lambda: k(AVar(v)))
        v = C.fresh("t")
        if strict:
            self.whnf.add(v)
            return Case(self.lo(e, sub), v, [], k(AVar(v)))
        return Let([(v, Thunk(None, self.lo(e, sub)))], k(AVar(v)))

    def atomize_all(self, es, strict, sub, k):
        """k(atoms) for the expressions es. The strict ones are evaluated
        first, left to right; then the rest are made closures right to
        left, so a nested constructor (a list) is built from its tail and
        only one cell of it is live at a time."""
        out = [None] * len(es)
        order = [i for i in range(len(es)) if strict[i]] + [
            i for i in reversed(range(len(es))) if not strict[i]]

        def go(j):
            if j == len(order):
                return k(out)
            i = order[j]

            def put(a):
                out[i] = a
                return go(j + 1)
            return self.atomize(es[i], strict[i], sub, put)
        return go(0)


class PapLocal:
    """A partial application of a local function closure: a PAP whose
    function is the closure variable."""
    __slots__ = ("fn", "args")

    def __init__(self, fn, args):
        self.fn, self.args = fn, args


def lit_word(e):
    return (4 * e.value) & 0xFFFFFFFF


# ---- free variables

def fv_atoms(atoms, out):
    for a in atoms:
        if isinstance(a, AVar):
            out.add(a.name)


def free(e, joins):
    """The free variables of an STG expression (cached); a jump uses its
    join point's free variables too. joins: join name -> its free
    variables."""
    try:
        return e._fv
    except AttributeError:
        pass
    t = type(e)
    out = set()
    if t is Ret:
        fv_atoms([e.atom], out)
    elif t is Call:
        fv_atoms(e.args, out)
        if e.local is not None:
            out.add(e.local)
    elif t is Apply:
        fv_atoms([e.fn] + e.args, out)
    elif t is PrimOp or t is Alloc:
        fv_atoms(e.args, out)
    elif t is Error:
        fv_atoms([e.atom], out)
    elif t is Jump:
        fv_atoms(e.args, out)
        out |= joins.get(e.name, set())
    elif t is Let:
        out |= free(e.body, joins)
        for _, c in e.binds:
            out |= closure_fv(c, joins)
        out -= {x for x, _ in e.binds}
    elif t is Case:
        out |= free(e.scrut, joins)
        inner = set()
        for a in e.alts:
            inner |= free(a.body, joins) - set(a.vars)
        if e.default is not None:
            inner |= free(e.default, joins)
        inner.discard(e.binder)
        out |= inner
    elif t is LetJoin:
        jfv = free(e.body, joins) - set(e.params)
        jfv.discard(e.name)
        joins[e.name] = jfv
        out |= free(e.rest, joins)
    else:
        raise AssertionError(e)
    e._fv = out
    return out


def closure_fv(c, joins):
    if isinstance(c, Thunk):
        if c.fvs is None:
            c.fvs = sorted(free(c.body, joins))
        return set(c.fvs)
    if isinstance(c, Fun):
        if c.fvs is None:
            fv = free(c.body, joins) - set(c.params)
            fv.discard(c.name)      # itself: the closure is the node
            c.fvs = sorted(fv)
        return set(c.fvs)
    if isinstance(c, (ConClo, PapClo)):
        out = set()
        fv_atoms(c.args, out)
        return out
    if isinstance(c, PapLocal):
        out = {c.fn}
        fv_atoms(c.args, out)
        return out
    raise AssertionError(c)


class Options:
    def __init__(self, strictness=True):
        self.strictness = strictness


def lower(prog, options=None):
    """A Core Program (simplified and lifted) as an STG Program."""
    lw = Lowerer(prog, options or Options())
    out = lw.run()
    joins = {}
    for t in out.tops:
        if isinstance(t, (TopFun, TopCaf)):
            free(t.body, joins)
    out.joins = joins
    return out
