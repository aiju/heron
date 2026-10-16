"""Core: the small language the desugarer produces and the optimiser
works on (implementation.md, "Core").

    e ::= x | literal | "string" | e e1 .. en | \\x1 .. xn -> e
        | let [rec] x1 = e1; ... in e
        | case e of b { K x1 .. xn -> e; lit -> e; _ -> e }
        | K e1 .. en          (a saturated constructor)
        | prim e1 .. en       (a saturated primitive)

Every binder's name is unique in the program, so passes can move code
without capturing names; clone() renames when code is copied. A case
names its scrutinee's value (the binder), evaluated.
"""

import itertools


class Expr:
    __slots__ = ()


class Var(Expr):
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


class Lit(Expr):
    """An Int or a Char: kind 'int' or 'char', value an int."""
    __slots__ = ("kind", "value")

    def __init__(self, kind, value):
        self.kind, self.value = kind, value


class Str(Expr):
    """A string literal: a [Char], evaluated."""
    __slots__ = ("codes",)

    def __init__(self, codes):
        self.codes = list(codes)


class App(Expr):
    __slots__ = ("fn", "args")

    def __init__(self, fn, args):
        assert args
        self.fn, self.args = fn, list(args)


class Lam(Expr):
    __slots__ = ("params", "body")

    def __init__(self, params, body):
        assert params
        self.params, self.body = list(params), body


class Let(Expr):
    __slots__ = ("binds", "body", "rec")

    def __init__(self, binds, body, rec=True):
        self.binds, self.body, self.rec = list(binds), body, rec


class Alt:
    """A case alternative: a constructor (con, a ConInfo) with variables
    for its fields, or a literal (lit, an int)."""
    __slots__ = ("con", "lit", "vars", "body")

    def __init__(self, con, lit, vars, body):
        self.con, self.lit, self.vars, self.body = con, lit, list(vars), body


class Case(Expr):
    __slots__ = ("scrut", "binder", "alts", "default")

    def __init__(self, scrut, binder, alts, default):
        self.scrut, self.binder, self.alts, self.default = scrut, binder, list(alts), default


class Con(Expr):
    __slots__ = ("con", "args")

    def __init__(self, con, args):
        assert len(args) == con.arity, (con.name, len(args))
        self.con, self.args = con, list(args)


class Prim(Expr):
    __slots__ = ("op", "args")

    def __init__(self, op, args):
        self.op, self.args = op, list(args)


# primitives: name in the prelude -> (op, arity)
PRIM_OPS = {
    "primIntAdd": ("add", 2), "primIntSub": ("sub", 2), "primIntMul": ("mul", 2),
    "primIntQuot": ("quot", 2), "primIntRem": ("rem", 2), "primIntDiv": ("div", 2),
    "primIntMod": ("mod", 2), "primIntNeg": ("neg", 1),
    "primIntEq": ("eq", 2), "primIntNe": ("ne", 2), "primIntLt": ("lt", 2),
    "primIntLe": ("le", 2), "primIntGt": ("gt", 2), "primIntGe": ("ge", 2),
    "primIntAnd": ("and", 2), "primIntOr": ("or", 2), "primIntXor": ("xor", 2),
    "primIntShl": ("shl", 2), "primIntShr": ("shr", 2),
    "primOrd": ("ord", 1), "primChr": ("chr", 1),
    "error": ("error", 1),
}
COMPARE = {"eq", "ne", "lt", "le", "gt", "ge"}
# strict in every argument, and evaluated results (all of them)
ARITH = {"add", "sub", "mul", "quot", "rem", "div", "mod", "neg", "and", "or", "xor", "shl", "shr",
         "ord", "chr"}


class Names:
    """Fresh names, unique in the program."""

    def __init__(self):
        self.counter = itertools.count(1)

    def fresh(self, base="v"):
        base = base.split("~")[0]
        return f"{base}~{next(self.counter)}"


NAMES = Names()


def fresh(base="v"):
    return NAMES.fresh(base)


class Program:
    """A whole program in Core: top-level bindings in order, and what the
    later passes need to know about constructors."""

    def __init__(self, binds, datas, cons, main):
        self.binds = binds          # [(name, Expr)]
        self.datas = datas          # name -> DataInfo
        self.cons = cons            # name -> ConInfo
        self.main = main            # name


# ---- walking

def free_vars(e, out=None, bound=frozenset()):
    """The free variables of an expression, as a set."""
    if out is None:
        out = set()
    stack = [(e, bound)]
    while stack:
        e, bound = stack.pop()
        t = type(e)
        if t is Var:
            if e.name not in bound:
                out.add(e.name)
        elif t is App:
            stack.append((e.fn, bound))
            for a in e.args:
                stack.append((a, bound))
        elif t is Lam:
            stack.append((e.body, bound | set(e.params)))
        elif t is Let:
            names = {n for n, _ in e.binds}
            inner = bound | names
            for _, r in e.binds:
                stack.append((r, inner if e.rec else bound))
            stack.append((e.body, inner))
        elif t is Case:
            stack.append((e.scrut, bound))
            b2 = bound | {e.binder}
            for a in e.alts:
                stack.append((a.body, b2 | set(a.vars)))
            if e.default is not None:
                stack.append((e.default, b2))
        elif t is Con or t is Prim:
            for a in e.args:
                stack.append((a, bound))
    return out


def size(e):
    """A rough size of an expression, for inlining."""
    t = type(e)
    if t is Var or t is Lit:
        return 1
    if t is Str:
        return 2
    if t is App:
        return size(e.fn) + sum(size(a) for a in e.args)
    if t is Lam:
        return 1 + size(e.body)
    if t is Let:
        return sum(size(r) + 1 for _, r in e.binds) + size(e.body)
    if t is Case:
        return 2 + size(e.scrut) + sum(1 + size(a.body) for a in e.alts) + (
            size(e.default) if e.default is not None else 0)
    if t is Con or t is Prim:
        return 1 + sum(size(a) for a in e.args)
    raise AssertionError(e)


def clone(e, subst=None):
    """A copy with every binder renamed fresh, and free variables replaced
    by subst (name -> Expr)."""
    subst = dict(subst or {})
    return _clone(e, subst)


def _clone(e, s):
    t = type(e)
    if t is Var:
        r = s.get(e.name)
        return Var(e.name) if r is None else (Var(r.name) if type(r) is Var else _copy(r))
    if t is Lit:
        return Lit(e.kind, e.value)
    if t is Str:
        return Str(e.codes)
    if t is App:
        return App(_clone(e.fn, s), [_clone(a, s) for a in e.args])
    if t is Lam:
        s2 = dict(s)
        ps = []
        for p in e.params:
            q = fresh(p)
            s2[p] = Var(q)
            ps.append(q)
        return Lam(ps, _clone(e.body, s2))
    if t is Let:
        s2 = dict(s)
        names = []
        for n, _ in e.binds:
            q = fresh(n)
            s2[n] = Var(q)
            names.append(q)
        rs = [_clone(r, s2 if e.rec else s) for _, r in e.binds]
        return Let(list(zip(names, rs)), _clone(e.body, s2), e.rec)
    if t is Case:
        scrut = _clone(e.scrut, s)
        s2 = dict(s)
        b = fresh(e.binder)
        s2[e.binder] = Var(b)
        alts = []
        for a in e.alts:
            s3 = dict(s2)
            vs = []
            for v in a.vars:
                q = fresh(v)
                s3[v] = Var(q)
                vs.append(q)
            alts.append(Alt(a.con, a.lit, vs, _clone(a.body, s3)))
        d = None if e.default is None else _clone(e.default, s2)
        return Case(scrut, b, alts, d)
    if t is Con:
        return Con(e.con, [_clone(a, s) for a in e.args])
    if t is Prim:
        return Prim(e.op, [_clone(a, s) for a in e.args])
    raise AssertionError(e)


def _copy(e):
    """A substituted expression put in a new place: clone it so binders
    stay unique."""
    if type(e) in (Var, Lit):
        return _clone(e, {})
    return clone(e)


# ---- printing

def show(e, indent=0):
    """Core as text, for debugging."""
    pad = "  " * indent
    t = type(e)
    if t is Var:
        return e.name
    if t is Lit:
        return repr(chr(e.value)) if e.kind == "char" else str(e.value)
    if t is Str:
        return repr("".join(chr(c) for c in e.codes))
    if t is App:
        return f"({show(e.fn, indent)} {' '.join(show(a, indent) for a in e.args)})"
    if t is Lam:
        return f"(\\{' '.join(e.params)} ->\n{pad}  {show(e.body, indent + 1)})"
    if t is Let:
        kw = "let rec" if e.rec else "let"
        bs = "\n".join(f"{pad}  {n} = {show(r, indent + 2)}" for n, r in e.binds)
        return f"{kw}\n{bs}\n{pad}in {show(e.body, indent)}"
    if t is Case:
        lines = [f"case {show(e.scrut, indent)} of {e.binder}"]
        for a in e.alts:
            head = a.con.name + "".join(" " + v for v in a.vars) if a.con is not None else str(a.lit)
            lines.append(f"{pad}  {head} -> {show(a.body, indent + 2)}")
        if e.default is not None:
            lines.append(f"{pad}  _ -> {show(e.default, indent + 2)}")
        return "\n".join(lines)
    if t is Con:
        if not e.args:
            return e.con.name
        return f"[{e.con.name} {' '.join(show(a, indent) for a in e.args)}]"
    if t is Prim:
        return f"<{e.op} {' '.join(show(a, indent) for a in e.args)}>"
    raise AssertionError(e)


def show_program(p):
    return "\n\n".join(f"{n} = {show(e, 1)}" for n, e in p.binds)


def check_scopes(prog):
    """Problems with a program's scoping: a variable used where it isn't
    bound, or a name bound twice. [message]"""
    tops = {n for n, _ in prog.binds}
    seen = set()
    out = []

    def bind(n, where):
        if n in seen:
            out.append(f"{where}: {n} is bound twice")
        seen.add(n)

    def walk(e, scope, where):
        stack = [(e, scope)]
        while stack:
            e, scope = stack.pop()
            t = type(e)
            if t is Var:
                if e.name not in scope and e.name not in tops:
                    out.append(f"{where}: {e.name} isn't bound")
            elif t is App:
                stack.append((e.fn, scope))
                stack += [(a, scope) for a in e.args]
            elif t is Lam:
                for p in e.params:
                    bind(p, where)
                stack.append((e.body, scope | set(e.params)))
            elif t is Let:
                names = {n for n, _ in e.binds}
                for n in names:
                    bind(n, where)
                inner = scope | names
                stack += [(r, inner if e.rec else scope) for _, r in e.binds]
                stack.append((e.body, inner))
            elif t is Case:
                stack.append((e.scrut, scope))
                bind(e.binder, where)
                s2 = scope | {e.binder}
                for a in e.alts:
                    for v in a.vars:
                        bind(v, where)
                    stack.append((a.body, s2 | set(a.vars)))
                if e.default is not None:
                    stack.append((e.default, s2))
            elif t is Con or t is Prim:
                stack += [(a, scope) for a in e.args]

    for n, e in prog.binds:
        walk(e, frozenset(), n)
    return out
