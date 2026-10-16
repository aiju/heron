"""The checked kernel to Core (core.py).

- **Patterns** are compiled into nested cases by Wadler's algorithm (The
  Implementation of Functional Programming Languages, chapter 5): the
  variable, constructor and mixture rules, with guards falling through
  to the next equation. What to do when everything fails is let-bound
  where it would be copied, and the optimiser makes it a join point.
- **Classes** become dictionaries: a constructor `D:C` per class whose
  fields are the superclasses' dictionaries, then the methods. A method
  is a selector applied to a dictionary; an instance is a dictionary, or a
  function from its context's dictionaries to one, and its methods are
  functions taking those dictionaries first. A method an instance leaves
  out is the class's default, given the instance's own dictionary.
- **Constructors and primitives** that aren't applied to all their
  arguments are wrapped in lambdas; `seq` is a case.
- **Lazy patterns** (`~p`, and pattern bindings in let and where) bind each
  variable to a selector: `x = case t of p -> x`.
"""

from . import core as C
from . import surface as S
from .typecheck import ConInfo, DataInfo


class Eqn:
    """One equation being matched: its remaining patterns, the bindings
    and forces its patterns made so far, and its right-hand side (a
    function from the fail expression to Core)."""
    __slots__ = ("pats", "binds", "forces", "rhs")

    def __init__(self, pats, rhs, binds=None, forces=None):
        self.pats = list(pats)
        self.rhs = rhs
        self.binds = list(binds or [])
        self.forces = list(forces or [])

    def with_pats(self, pats):
        return Eqn(pats, self.rhs, self.binds, self.forces)

    def build(self, fail):
        body = self.rhs(fail)
        if self.binds:
            body = C.Let(self.binds, body, rec=False)
        for u in reversed(self.forces):
            body = C.Case(C.Var(u), C.fresh("bang"), [], body)
        return body


class Desugarer:
    def __init__(self, prog):
        self.prog = prog
        self.cons = prog.cons
        self.true = prog.cons["True"]
        self.false = prog.cons["False"]
        self.binds = []         # top-level Core bindings
        self.strings = {}       # message -> name of a top-level string
        self.dict_cons = {}     # class name -> ConInfo of its dictionary
        self.dict_arity = {}    # top-level name -> how many of its parameters are dictionaries

    # ---- the program

    def run(self):
        for name, cls in self.prog.classes.items():
            self.class_dict(cls)
        for b in self.prog.tops:
            self.binds += self.binding(b)
        for cls in self.prog.classes.values():
            for m, d in cls.defaults.items():
                self.dict_arity[cls.default_vars[m].name] = len(d.dict_params)
                self.binds.append((cls.default_vars[m].name, self.fun(d)))
        for inst in self.prog.instances:
            self.instance(inst)
        datas = dict(self.prog.datas)
        for c in self.dict_cons.values():
            datas[c.data.name] = c.data
        cons = dict(self.cons)
        for c in self.dict_cons.values():
            cons[c.name] = c
        # instance methods share their instance's parameter names: give every
        # binding fresh ones, so each binder is unique in the program
        binds = [(n, C.clone(e)) for n, e in self.binds]
        out = C.Program(binds, datas, cons, self.prog.main.name)
        out.dict_arity = self.dict_arity
        return out

    def class_dict(self, cls):
        n = len(cls.supers) + len(cls.methods)
        data = DataInfo(f"D:{cls.name}", 1)
        con = ConInfo(f"D:{cls.name}", data, 0, [None] * n, [False] * n, None)
        data.cons.append(con)
        self.dict_cons[cls.name] = con
        for i, s in enumerate(cls.supers):
            self.binds.append((f"$sup_{cls.name}_{i}", self.selector(con, i)))
        for i, m in enumerate(cls.methods):
            self.binds.append((sel_name(cls.name, m), self.selector(con, len(cls.supers) + i)))

    def selector(self, con, i):
        d = C.fresh("d")
        vs = [C.fresh("f") for _ in range(con.arity)]
        return C.Lam([d], C.Case(C.Var(d), C.fresh("b"), [C.Alt(con, None, vs, C.Var(vs[i]))], None))

    def instance(self, inst):
        cls = self.prog.classes[inst.cls]
        ctx = [p.name for p in inst.dict_params]
        for m, d in inst.methods.items():
            if ctx:
                self.dict_arity[inst.method_vars[m].name] = len(ctx)
            self.binds.append((inst.method_vars[m].name, self.fun(d)))

        def this():
            return C.App(C.Var(inst.name), [C.Var(n) for n in ctx]) if ctx else C.Var(inst.name)

        fields = [self.dict_expr(h) for h in inst.super_holes]
        for m in cls.methods:
            if m in inst.methods:
                v = inst.method_vars[m].name
                fields.append(C.App(C.Var(v), [C.Var(n) for n in ctx]) if ctx else C.Var(v))
            elif m in cls.defaults:
                fields.append(C.App(C.Var(cls.default_vars[m].name), [this()]))
            else:
                fields.append(self.error_call(f"no method {m} in the instance {inst.cls} {inst.tycon}"))
        body = C.Con(self.dict_cons[inst.cls], fields)
        if ctx:
            self.dict_arity[inst.name] = len(ctx)
        self.binds.append((inst.name, C.Lam(ctx, body) if ctx else body))

    # ---- dictionaries

    def dict_expr(self, h):
        assert h.resolved is not None, (h.cls, h.where)
        return self.resolved(h.resolved)

    def resolved(self, r):
        kind = r[0]
        if kind == "param":
            p = r[1]
            if p.redirect is not None:
                q, path = p.redirect
                e = C.Var(q.name)
                for c, i in path:
                    e = C.App(C.Var(f"$sup_{c}_{i}"), [e])
                return e
            return C.Var(p.name)
        if kind == "super":
            _, inner, c, i = r
            return C.App(C.Var(f"$sup_{c}_{i}"), [self.resolved(inner)])
        _, inst, subs = r
        if not subs:
            return C.Var(inst.name)
        return C.App(C.Var(inst.name), [self.dict_expr(s) for s in subs])

    # ---- bindings

    def binding(self, b):
        """Core bindings for a DFun or DPatBind: [(name, Expr)], and
        strictness marks for let: a banged variable's name comes back in
        self.strict."""
        if isinstance(b, S.DFun):
            if b.dict_params:
                self.dict_arity[b.vars[0].name] = len(b.dict_params)
            return [(b.vars[0].name, self.fun(b))]
        p = b.pat
        if isinstance(p, S.PBang) and isinstance(p.pat, S.PVar):
            rhs = self.rhs(b.rhs, self.error_call("pattern binding failed"))
            self.strict.append(p.pat.var.name)
            return [(p.pat.var.name, rhs)]
        t = C.fresh("pat")
        out = [(t, self.rhs(b.rhs, self.error_call("pattern binding failed")))]
        for x in pattern_vars(p):
            out.append((x.var.name, self.selector_for(t, p, x)))
        return out

    def selector_for(self, t, p, x):
        """`case t of p -> x`, with fresh names inside."""
        e = self.match([t], [Eqn([p], lambda f, x=x: C.Var(x.var.name))],
                       self.error_call("irrefutable pattern failed"))
        return C.clone(e)

    def fun(self, b):
        clauses = b.clauses
        dicts = [p.name for p in b.dict_params]
        n = len(clauses[0].pats)
        fail = self.error_call(f"pattern match failure in {b.vars[0].src}")
        if n == 0:
            body = self.rhs(clauses[0].rhs, fail)
            return C.Lam(dicts, body) if dicts else body
        us = []
        for i in range(n):
            # reuse a name when every equation has the same variable there
            us.append(C.fresh("a"))
        eqs = [Eqn(c.pats, lambda f, c=c: self.rhs(c.rhs, f)) for c in clauses]
        return C.Lam(dicts + us, self.match(us, eqs, fail))

    def rhs(self, r, fail):
        acc = fail
        for g, e in reversed(r.guards):
            if g is None:
                acc = self.expr(e)
            else:
                acc = self.if_(self.expr(g), self.expr(e), acc)
        if r.decls:
            acc = self.let(r.decls, acc)
        return acc

    def if_(self, c, a, b):
        return C.Case(c, C.fresh("b"), [C.Alt(self.true, None, [], a), C.Alt(self.false, None, [], b)], None)

    def let(self, decls, body):
        saved, self.strict = getattr(self, "strict", []), []
        binds = []
        for d in decls:
            if isinstance(d, (S.DFun, S.DPatBind)):
                binds += self.binding(d)
        strict, self.strict = self.strict, saved
        for x in reversed(strict):
            body = C.Case(C.Var(x), C.fresh("bang"), [], body)
        return C.Let(binds, body, rec=True)

    def error_call(self, msg):
        name = self.strings.get(msg)
        if name is None:
            name = f"$str{len(self.strings) + 1}"
            self.strings[msg] = name
            self.binds.append((name, C.Str([ord(c) for c in msg])))
        return C.Prim("error", [C.Var(name)])

    # ---- expressions

    def expr(self, e):
        if isinstance(e, (S.EApp, S.EVar, S.ECon)):
            args = []
            while isinstance(e, S.EApp):
                args.append(e.arg)
                e = e.fn
            args = [self.expr(a) for a in reversed(args)]
            return self.apply(e, args)
        if isinstance(e, S.ELit):
            if e.kind == "string":
                return C.Str(e.value)
            return C.Lit(e.kind, e.value)
        if isinstance(e, S.ELam):
            if all(isinstance(p, S.PVar) for p in e.pats):
                return C.Lam([p.var.name for p in e.pats], self.expr(e.body))
            us = [C.fresh("a") for _ in e.pats]
            body = self.match(us, [Eqn(e.pats, lambda f: self.expr(e.body))],
                              self.error_call("pattern match failure in a lambda"))
            return C.Lam(us, body)
        if isinstance(e, S.ELet):
            return self.let(e.decls, self.expr(e.body))
        if isinstance(e, S.ECase):
            u = C.fresh("scrut")
            eqs = [Eqn([a.pat], lambda f, a=a: self.rhs(a.rhs, f)) for a in e.alts]
            body = self.match([u], eqs, self.error_call("non-exhaustive case"))
            return C.Let([(u, self.expr(e.scrut))], body, rec=False)
        if isinstance(e, S.ETyped):
            return self.expr(e.expr)
        raise AssertionError(e)

    def apply(self, head, args):
        if isinstance(head, S.ECon):
            return self.saturate(head.con.arity, args, lambda xs: C.Con(head.con, xs))
        if isinstance(head, S.EVar):
            v = head.var
            if v.kind == "prim":
                if v.name == "seq":
                    return self.saturate(2, args, lambda xs: C.Case(xs[0], C.fresh("seq"), [], xs[1]))
                op, n = C.PRIM_OPS[v.name]
                return self.saturate(n, args, lambda xs: C.Prim(op, xs))
            f = self.var_ref(head)
        else:
            f = self.expr(head)
        return C.App(f, args) if args else f

    def saturate(self, n, args, make):
        """make(args) if there are n of them (applying any more to it), else
        a lambda for the missing ones."""
        if len(args) >= n:
            e = make(args[:n])
            return C.App(e, args[n:]) if len(args) > n else e
        ps = [C.fresh("x") for _ in range(n - len(args))]
        return C.Lam(ps, make(args + [C.Var(p) for p in ps]))

    def var_ref(self, e):
        v = e.var
        if v.kind == "method":
            return C.App(C.Var(sel_name(v.cls.name, v.name)), [self.dict_expr(e.dicts[0])])
        base = C.Var(v.name)
        if e.rec:
            ps = v.group.dict_params
            if ps:
                return C.App(base, [C.Var(p.name) for p in ps])
            return base
        if e.dicts:
            return C.App(base, [self.dict_expr(h) for h in e.dicts])
        return base

    # ---- pattern matching

    def match(self, us, eqs, fail):
        """Core that matches the variables us against the equations' patterns,
        in order, and gives `fail` if none matches."""
        if not us:
            out = fail
            for eq in reversed(eqs):
                out = self.share(out, lambda f, eq=eq: eq.build(f))
            return out
        u = us[0]
        for eq in eqs:
            self.normalise(eq, u)
        groups = []
        for eq in eqs:
            k = kind(eq.pats[0])
            if groups and groups[-1][0] == k:
                groups[-1][1].append(eq)
            else:
                groups.append((k, [eq]))
        out = fail
        for k, g in reversed(groups):
            out = self.share(out, lambda f, k=k, g=g: self.match_group(k, us, g, f))
        return out

    def share(self, fail, k):
        """k(fail), let-binding fail first if copying it would cost."""
        if isinstance(fail, C.Var) or (isinstance(fail, C.Prim) and fail.op == "error"
                                       and isinstance(fail.args[0], C.Var)):
            return k(fail)
        f = C.fresh("fail")
        return C.Let([(f, fail)], k(C.Var(f)), rec=False)

    def normalise(self, eq, u):
        """Strip as-patterns and bangs off the first pattern."""
        while True:
            p = eq.pats[0]
            if isinstance(p, S.PAs):
                eq.binds.append((p.var.name, C.Var(u)))
                eq.pats[0] = p.pat
            elif isinstance(p, S.PBang):
                eq.forces.append(u)
                eq.pats[0] = p.pat
            else:
                return

    def match_group(self, k, us, eqs, fail):
        u, rest = us[0], us[1:]
        if k == "var":
            out = []
            for eq in eqs:
                p = eq.pats[0]
                if isinstance(p, S.PVar):
                    eq.binds.append((p.var.name, C.Var(u)))
                elif isinstance(p, S.PLazy):
                    for x in pattern_vars(p.pat):
                        eq.binds.append((x.var.name, self.selector_for(u, p.pat, x)))
                out.append(eq.with_pats(eq.pats[1:]))
            return self.match(rest, out, fail)
        if k == "con":
            data = eqs[0].pats[0].con.data
            alts = []
            seen = []
            for c in data.cons:
                sub = [eq for eq in eqs if eq.pats[0].con is c]
                if not sub:
                    continue
                seen.append(c)
                vs = [C.fresh("f") for _ in range(c.arity)]
                sub_eqs = [eq.with_pats(eq.pats[0].args + eq.pats[1:]) for eq in sub]
                alts.append(C.Alt(c, None, vs, self.match(vs + rest, sub_eqs, fail)))
            default = fail if len(seen) < len(data.cons) else None
            return C.Case(C.Var(u), C.fresh("b"), alts, default)
        # literals
        alts = []
        values = []
        for eq in eqs:
            v = eq.pats[0].value
            if v not in values:
                values.append(v)
        for v in values:
            sub = [eq.with_pats(eq.pats[1:]) for eq in eqs if eq.pats[0].value == v]
            alts.append(C.Alt(None, v, [], self.match(rest, sub, fail)))
        return C.Case(C.Var(u), C.fresh("b"), alts, fail)


def kind(p):
    if isinstance(p, (S.PVar, S.PWild, S.PLazy)):
        return "var"
    if isinstance(p, S.PCon):
        return "con"
    if isinstance(p, S.PLit):
        return "lit"
    raise AssertionError(p)


def pattern_vars(p, out=None):
    """The PVar and PAs nodes of a pattern."""
    if out is None:
        out = []
    if isinstance(p, S.PVar):
        out.append(p)
    elif isinstance(p, S.PCon):
        for a in p.args:
            pattern_vars(a, out)
    elif isinstance(p, S.PAs):
        out.append(p)
        pattern_vars(p.pat, out)
    elif isinstance(p, (S.PLazy, S.PBang)):
        pattern_vars(p.pat, out)
    return out


def sel_name(cls, method):
    return f"$sel_{cls}_{method}"


def desugar(prog):
    """A checked Program (typecheck.py) as a Core Program."""
    d = Desugarer(prog)
    d.strict = []
    return d.run()
