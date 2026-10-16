"""Strictness analysis (implementation.md, "Strictness"): which parameters
a function surely evaluates whenever its result is evaluated.

demands(e) is the set of variables surely evaluated (to weak head normal
form) when e is; BOTTOM (everything) if e surely fails. A function is
strict in a parameter if its body demands it. Recursive functions start
out strict in everything and are recomputed until nothing changes, the
usual greatest fixed point on this two-point domain.

What the code generator gets from it: a strict parameter is passed
evaluated, so the caller evaluates the argument instead of allocating a
thunk, and the function trusts it; a `let` whose body demands its
variable is evaluated on the spot (stg.py).
"""

from . import core as C


class Bottom:
    """Every variable: the expression surely fails."""

    def __repr__(self):
        return "BOTTOM"


BOTTOM = Bottom()


def union(a, b):
    if a is BOTTOM or b is BOTTOM:
        return BOTTOM
    return a | b


def inter(a, b):
    if a is BOTTOM:
        return b
    if b is BOTTOM:
        return a
    return a & b


def minus(a, names):
    if a is BOTTOM:
        return BOTTOM
    return a - set(names)


class Analyser:
    def __init__(self, prog):
        self.prog = prog
        self.sigs = {}          # function name -> (arity, frozenset of strict parameter indices)

    def run(self):
        """{top-level function: (arity, strict indices)}, and the same for
        every local function (by its unique name)."""
        funs = {n: e for n, e in self.prog.binds if type(e) is C.Lam}
        for n, e in funs.items():
            self.sigs[n] = (len(e.params), frozenset(range(len(e.params))))
        changed = True
        while changed:
            changed = False
            for n, e in funs.items():
                d = self.demands(e.body, {})
                s = frozenset(i for i, p in enumerate(e.params) if d is BOTTOM or p in d)
                if s != self.sigs[n][1]:
                    self.sigs[n] = (len(e.params), s)
                    changed = True
        # a final walk records every local function's signature, wherever
        # it is (demands() only looks where evaluation surely goes)
        for n, e in self.prog.binds:
            self.visit(e)
        return self.sigs

    def visit(self, e):
        stack = [e]
        while stack:
            e = stack.pop()
            t = type(e)
            if t is C.Let:
                if any(type(r) is C.Lam for _, r in e.binds):
                    self.demands(C.Let(e.binds, C.Lit("int", 0), e.rec), {})
                stack += [r for _, r in e.binds]
                stack.append(e.body)
            elif t is C.App:
                stack.append(e.fn)
                stack += e.args
            elif t is C.Lam:
                stack.append(e.body)
            elif t is C.Case:
                stack.append(e.scrut)
                stack += [a.body for a in e.alts]
                if e.default is not None:
                    stack.append(e.default)
            elif t is C.Con or t is C.Prim:
                stack += e.args

    def demands(self, e, env):
        """env: let-bound variable -> what evaluating it demands."""
        t = type(e)
        if t is C.Var:
            out = {e.name}
            d = env.get(e.name)
            if d is not None:
                out = union(out, d)
            return out
        if t is C.Lit or t is C.Str or t is C.Lam:
            return set()
        if t is C.App:
            f = e.fn
            if type(f) is C.Var:
                sig = self.sigs.get(f.name)
                if sig is not None:
                    n, strict = sig
                    if len(e.args) >= n:
                        out = set()
                        for i in strict:
                            out = union(out, self.demands(e.args[i], env))
                        return out
                    return set()
                return self.demands(f, env)
            return self.demands(f, env)
        if t is C.Prim:
            if e.op == "error":
                return BOTTOM
            out = set()
            for a in e.args:
                out = union(out, self.demands(a, env))
            return out
        if t is C.Con:
            out = set()
            for a, s in zip(e.args, e.con.strict):
                if s:
                    out = union(out, self.demands(a, env))
            return out
        if t is C.Case:
            d = self.demands(e.scrut, env)
            branches = None
            for a in e.alts:
                b = minus(self.demands(a.body, env), a.vars + [e.binder])
                branches = b if branches is None else inter(branches, b)
            if e.default is not None:
                b = minus(self.demands(e.default, env), [e.binder])
                branches = b if branches is None else inter(branches, b)
            if branches is None:
                branches = BOTTOM
            return union(d, branches)
        if t is C.Let:
            env = dict(env)
            names = [n for n, _ in e.binds]
            if e.rec:
                # local functions get signatures, by their own fixed point
                funs = [(n, r) for n, r in e.binds if type(r) is C.Lam]
                for n, r in funs:
                    self.sigs[n] = (len(r.params), frozenset(range(len(r.params))))
                changed = True
                while changed:
                    changed = False
                    for n, r in funs:
                        d = self.demands(r.body, env)
                        s = frozenset(i for i, p in enumerate(r.params) if d is BOTTOM or p in d)
                        if s != self.sigs[n][1]:
                            self.sigs[n] = (len(r.params), s)
                            changed = True
                for n, r in e.binds:
                    if type(r) is not C.Lam:
                        self.demands(r, env)     # for the local functions inside
            else:
                (n, r), = e.binds
                if type(r) is C.Lam:
                    d = self.demands(r.body, env)
                    self.sigs[n] = (len(r.params), frozenset(
                        i for i, p in enumerate(r.params) if d is BOTTOM or p in d))
                else:
                    env[n] = self.demands(r, env)
            return minus(self.demands(e.body, env), names)
        raise AssertionError(e)


def analyse(prog):
    return Analyser(prog).run()
