"""Join points and lambda lifting, on Core (implementation.md, "Local
functions").

A **join point** is a let-bound function (or a let-bound expression, a
join point without parameters) that is only ever called in tail position
of the let's body, with all its arguments: what pattern-match failure and
case-of-case leave behind, and local loops such as `go` in

    length xs = go xs 0 where go [] n = n; go (_:ys) n = go ys (n + 1)

The code generator makes it a label and its calls jumps (stg.py), so it
costs neither a closure nor a call.

Any other local function that never escapes (every use calls it with all
its arguments) is **lifted** to the top level, with its free variables as
extra parameters in front: a call then passes them in registers, where
a closure would have been allocated. Functions that escape, and those
that would need more than MAX_PARAMS parameters, stay closures.
"""

from . import core as C

MAX_PARAMS = 9      # the argument registers


def is_join(name, arity, body, rhs_body=None):
    """Is every use of name in body (and rhs_body, for a recursive one) a
    call with `arity` arguments in tail position?"""
    return tail_only(name, arity, body) and (rhs_body is None or tail_only(name, arity, rhs_body))


def tail_only(name, arity, e):
    stack = [(e, True)]
    while stack:
        e, tail = stack.pop()
        t = type(e)
        if t is C.Var:
            if e.name == name and not (tail and arity == 0):
                return False
        elif t is C.App:
            if type(e.fn) is C.Var and e.fn.name == name:
                if not tail or len(e.args) != arity or arity == 0:
                    return False
            else:
                stack.append((e.fn, False))
            stack += [(a, False) for a in e.args]
        elif t is C.Lam:
            stack.append((e.body, False))
        elif t is C.Let:
            stack += [(r, False) for _, r in e.binds]
            stack.append((e.body, tail))
        elif t is C.Case:
            stack.append((e.scrut, False))
            stack += [(a.body, tail) for a in e.alts]
            if e.default is not None:
                stack.append((e.default, tail))
        elif t is C.Con or t is C.Prim:
            stack += [(a, False) for a in e.args]
    return True


def join_arity(name, rhs, body, rec):
    """The number of parameters if `let name = rhs in body` binds a join
    point, else None."""
    if type(rhs) is C.Lam:
        n = len(rhs.params)
        if is_join(name, n, body, rhs.body if rec else None):
            return n
        return None
    if not rec and is_join(name, 0, body):
        return 0
    return None


def calls_only(name, arity, e):
    """Is every use of name a call with at least `arity` arguments?"""
    stack = [e]
    while stack:
        e = stack.pop()
        t = type(e)
        if t is C.Var:
            if e.name == name:
                return False
        elif t is C.App:
            if type(e.fn) is C.Var and e.fn.name == name:
                if len(e.args) < arity:
                    return False
            else:
                stack.append(e.fn)
            stack += e.args
        elif t is C.Lam:
            stack.append(e.body)
        elif t is C.Let:
            stack += [r for _, r in e.binds]
            stack.append(e.body)
        elif t is C.Case:
            stack.append(e.scrut)
            stack += [a.body for a in e.alts]
            if e.default is not None:
                stack.append(e.default)
        elif t is C.Con or t is C.Prim:
            stack += e.args
    return True


class Lifter:
    def __init__(self, prog):
        self.prog = prog
        self.globals = {n for n, _ in prog.binds}
        self.new = []

    def run(self):
        binds = []
        for n, e in self.prog.binds:
            binds.append((n, self.lift(e)))
            binds += self.new
            self.new = []
        out = C.Program(binds, self.prog.datas, self.prog.cons, self.prog.main)
        out.dict_arity = getattr(self.prog, "dict_arity", {})
        return out

    def lift(self, e):
        t = type(e)
        if t is C.App:
            return C.App(self.lift(e.fn), [self.lift(a) for a in e.args])
        if t is C.Lam:
            return C.Lam(e.params, self.lift(e.body))
        if t is C.Case:
            return C.Case(self.lift(e.scrut), e.binder,
                          [C.Alt(a.con, a.lit, a.vars, self.lift(a.body)) for a in e.alts],
                          None if e.default is None else self.lift(e.default))
        if t is C.Con:
            return C.Con(e.con, [self.lift(a) for a in e.args])
        if t is C.Prim:
            return C.Prim(e.op, [self.lift(a) for a in e.args])
        if t is not C.Let:
            return e
        binds = [(n, self.lift(r)) for n, r in e.binds]
        body = self.lift(e.body)
        lams = [(n, r) for n, r in binds if type(r) is C.Lam]
        if not lams or len(lams) != len(binds):
            return C.Let(binds, body, e.rec)
        names = [n for n, _ in binds]
        # join points stay where they are
        if len(binds) == 1 and join_arity(names[0], binds[0][1], body, e.rec) is not None:
            return C.Let(binds, body, e.rec)
        everything = [body] + [r.body for _, r in binds]
        for n, r in binds:
            if not all(calls_only(n, len(r.params), x) for x in everything):
                return C.Let(binds, body, e.rec)
        fvs = set()
        for _, r in binds:
            fvs |= C.free_vars(r)
        fvs = sorted(fvs - set(names) - self.globals)
        if len(fvs) + max(len(r.params) for _, r in binds) > MAX_PARAMS:
            return C.Let(binds, body, e.rec)
        new = {n: C.fresh(n.split("~")[0] + "^") for n in names}
        arities = {n: len(r.params) for n, r in binds}

        def rewrite(x):
            return add_args(x, new, [C.Var(v) for v in fvs])
        for n, r in binds:
            lam = C.Lam(fvs + r.params, rewrite(r.body))
            self.new.append((new[n], C.clone(lam)))
            self.globals.add(new[n])
        return rewrite(body)


def add_args(e, new, extra):
    """Calls of the functions in `new` (old name -> new name) become calls
    of the new names with `extra` arguments first."""
    t = type(e)
    if t is C.App:
        if type(e.fn) is C.Var and e.fn.name in new:
            return C.App(C.Var(new[e.fn.name]), [C.Var(x.name) for x in extra] +
                         [add_args(a, new, extra) for a in e.args])
        return C.App(add_args(e.fn, new, extra), [add_args(a, new, extra) for a in e.args])
    if t is C.Lam:
        return C.Lam(e.params, add_args(e.body, new, extra))
    if t is C.Let:
        return C.Let([(n, add_args(r, new, extra)) for n, r in e.binds], add_args(e.body, new, extra), e.rec)
    if t is C.Case:
        return C.Case(add_args(e.scrut, new, extra), e.binder,
                      [C.Alt(a.con, a.lit, a.vars, add_args(a.body, new, extra)) for a in e.alts],
                      None if e.default is None else add_args(e.default, new, extra))
    if t is C.Con:
        return C.Con(e.con, [add_args(a, new, extra) for a in e.args])
    if t is C.Prim:
        return C.Prim(e.op, [add_args(a, new, extra) for a in e.args])
    return e


def lift(prog):
    return Lifter(prog).run()
