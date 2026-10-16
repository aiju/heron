"""The Core optimiser (implementation.md, "The optimiser"). It repeats a
simplifier pass a few times, each after an occurrence analysis:

- a let-bound variable that is an atom, or used once (and not inside a
  lambda unless it's a value), is substituted; one that isn't used goes;
- small non-recursive functions are inlined where they're applied to all
  their arguments: dictionary selectors, instance dictionaries and most
  instance methods among them, so a method of a known instance becomes a
  direct call;
- beta reduction, `let` floated out of applications and case scrutinees,
  case of a known constructor or literal (from a let, an enclosing case,
  or a top-level constructor), case of case (with join points when the
  outer alternatives are big), constant folding;
- specialisation: an overloaded function applied to known dictionaries,
  or a recursive function applied to a known function that it passes on
  unchanged, gets a copy for those arguments, which the next pass
  simplifies (Options.specialise);
- top-level bindings main doesn't reach are dropped.
"""

from . import core as C

INLINE_SIZE = 24        # a function this size or smaller is inlined
CASE_DUP_SIZE = 12      # case of case copies outer alternatives this size or smaller
PASSES = 4             # simplifier passes, and more while specialising makes new copies,
MAX_PASSES = 12        # up to this many


class Options:
    def __init__(self, specialise=True, inline=True):
        self.specialise = specialise
        self.inline = inline


# ---- occurrence analysis

class Occ:
    __slots__ = ("count", "in_lam")

    def __init__(self):
        self.count = 0
        self.in_lam = False


def occurrences(e, occ, depth=0, binder_depth=None):
    """Count the uses of every variable in e: occ[name] = Occ. A use inside
    a lambda deeper than the variable's binding sets in_lam."""
    if binder_depth is None:
        binder_depth = {}
    stack = [(e, depth)]
    while stack:
        e, d = stack.pop()
        t = type(e)
        if t is C.Var:
            o = occ.get(e.name)
            if o is None:
                o = occ[e.name] = Occ()
            o.count += 1
            if d > binder_depth.get(e.name, 0):
                o.in_lam = True
        elif t is C.App:
            stack.append((e.fn, d))
            for a in e.args:
                stack.append((a, d))
        elif t is C.Lam:
            for p in e.params:
                binder_depth[p] = d + 1
            stack.append((e.body, d + 1))
        elif t is C.Let:
            for n, r in e.binds:
                binder_depth[n] = d
                stack.append((r, d))
            stack.append((e.body, d))
        elif t is C.Case:
            stack.append((e.scrut, d))
            binder_depth[e.binder] = d
            for a in e.alts:
                for v in a.vars:
                    binder_depth[v] = d
                stack.append((a.body, d))
            if e.default is not None:
                stack.append((e.default, d))
        elif t is C.Con or t is C.Prim:
            for a in e.args:
                stack.append((a, d))
    return occ


def is_value(e):
    """Evaluating e does no work (it's in weak head normal form or an
    atom): copying it duplicates no work."""
    t = type(e)
    return t is C.Var or t is C.Lit or t is C.Str or t is C.Lam or (
        t is C.Con and all(type(a) in (C.Var, C.Lit) for a in e.args))


def is_atom(e):
    return type(e) is C.Var or type(e) is C.Lit


# ---- dependency analysis of lets

def split_lets(e):
    """Split every recursive let into its strongly connected components,
    in dependency order; a single binding that doesn't refer to itself
    becomes non-recursive."""
    t = type(e)
    if t is C.App:
        return C.App(split_lets(e.fn), [split_lets(a) for a in e.args])
    if t is C.Lam:
        return C.Lam(e.params, split_lets(e.body))
    if t is C.Let:
        binds = [(n, split_lets(r)) for n, r in e.binds]
        body = split_lets(e.body)
        if not e.rec:
            for b in reversed(binds):
                body = C.Let([b], body, False)
            return body
        for comp, rec in components(binds)[::-1]:
            body = C.Let(comp, body, rec)
        return body
    if t is C.Case:
        return C.Case(split_lets(e.scrut), e.binder,
                      [C.Alt(a.con, a.lit, a.vars, split_lets(a.body)) for a in e.alts],
                      None if e.default is None else split_lets(e.default))
    if t is C.Con:
        return C.Con(e.con, [split_lets(a) for a in e.args])
    if t is C.Prim:
        return C.Prim(e.op, [split_lets(a) for a in e.args])
    return e


def components(binds):
    """[(binds, recursive)] in dependency order."""
    names = {n for n, _ in binds}
    deps = {n: [m for m in C.free_vars(r) if m in names] for n, r in binds}
    rhs = dict(binds)
    order = [n for n, _ in binds]
    index, low, on, stack, out = {}, {}, set(), [], []
    counter = [0]

    def visit(n):
        index[n] = low[n] = counter[0]
        counter[0] += 1
        stack.append(n)
        on.add(n)
        for m in deps[n]:
            if m not in index:
                visit(m)
                low[n] = min(low[n], low[m])
            elif m in on:
                low[n] = min(low[n], index[m])
        if low[n] == index[n]:
            comp = []
            while True:
                m = stack.pop()
                on.discard(m)
                comp.append(m)
                if m == n:
                    break
            comp.sort(key=order.index)
            rec = len(comp) > 1 or comp[0] in deps[comp[0]]
            out.append(([(m, rhs[m]) for m in comp], rec))

    for n in order:
        if n not in index:
            visit(n)
    return out


# ---- the simplifier

class Known:
    """What a variable is known to be: a constructor with these
    arguments, or a literal."""
    __slots__ = ("con", "args", "lit")

    def __init__(self, con=None, args=None, lit=None):
        self.con, self.args, self.lit = con, args, lit


class Simplifier:
    def __init__(self, prog, options=None):
        self.prog = prog
        self.options = options or Options()
        self.tops = dict(prog.binds)
        self.order = [n for n, _ in prog.binds]
        self.dict_arity = getattr(prog, "dict_arity", {})
        self.specs = {}             # (name, key) -> name of the specialised copy
        self.spec_of = {}           # specialised name -> original name
        self.rec_specs = set()      # specialised copies of recursive functions
        self.nil = prog.cons["[]"]
        self.cons_ = prog.cons[":"]
        self.true = prog.cons["True"]
        self.false = prog.cons["False"]

    # ---- the program

    def run(self):
        self.prune()
        for name in list(self.tops):
            self.tops[name] = split_lets(self.tops[name])
        passes = 0
        while True:
            self.new_specs = 0
            self.analyse()
            for name in list(self.order):
                if name in self.tops:
                    self.occ = occurrences(self.tops[name], {})
                    self.current = name
                    self.tops[name] = self.simp(self.tops[name], {}, {})
            self.prune()
            passes += 1
            if passes >= MAX_PASSES or (passes >= PASSES and not self.new_specs):
                break
        self.analyse()
        binds = [(n, self.tops[n]) for n in self.order if n in self.tops]
        out = C.Program(binds, self.prog.datas, self.prog.cons, self.prog.main)
        out.dict_arity = self.dict_arity
        return out

    def prune(self):
        """Drop the top-level bindings main doesn't reach."""
        seen = set()
        todo = [self.prog.main]
        while todo:
            n = todo.pop()
            if n in seen or n not in self.tops:
                continue
            seen.add(n)
            todo += C.free_vars(self.tops[n])
        self.tops = {n: e for n, e in self.tops.items() if n in seen}
        self.order = [n for n in self.order if n in seen]

    def analyse(self):
        """Which top-level bindings are recursive, and their arities."""
        names = set(self.tops)
        deps = {n: [m for m in C.free_vars(e) if m in names] for n, e in self.tops.items()}
        self.recursive = set()
        for comp, rec in components(list(self.tops.items())):
            if rec:
                self.recursive.update(n for n, _ in comp)
        # a specialised copy of a recursive function calls the original
        # until it's simplified
        self.recursive |= self.rec_specs
        self.arity = {n: len(e.params) for n, e in self.tops.items() if type(e) is C.Lam}
        self.top_con = {n: e for n, e in self.tops.items() if type(e) is C.Con}
        self.deps = deps

    # ---- expressions

    def simp(self, e, sub, env):
        """Simplify e under the substitution sub (name -> Expr) and the
        knowledge env (name -> Known)."""
        t = type(e)
        if t is C.Var:
            r = sub.get(e.name)
            if r is not None:
                return r if type(r) is C.Var or type(r) is C.Lit else C.clone(r)
            return e
        if t is C.Lit or t is C.Str:
            return e
        if t is C.App:
            return self.simp_app(e, sub, env)
        if t is C.Lam:
            body = self.simp(e.body, sub, env)
            if type(body) is C.Lam:
                return C.Lam(e.params + body.params, body.body)
            return C.Lam(e.params, body)
        if t is C.Let:
            return self.simp_let(e, sub, env)
        if t is C.Case:
            return self.simp_case(e, sub, env)
        if t is C.Con:
            return C.Con(e.con, [self.simp(a, sub, env) for a in e.args])
        if t is C.Prim:
            return self.simp_prim(e.op, [self.simp(a, sub, env) for a in e.args])
        raise AssertionError(e)

    def simp_app(self, e, sub, env):
        f = self.simp(e.fn, sub, env)
        args = [self.simp(a, sub, env) for a in e.args]
        return self.app(f, args, env)

    def app(self, f, args, env):
        """Apply a simplified function to simplified arguments."""
        while True:
            t = type(f)
            if t is C.App:
                args = f.args + args
                f = f.fn
                continue
            if t is C.Let:
                return C.Let(f.binds, self.app(f.body, args, env), f.rec)
            if t is C.Lam:
                return self.beta(f, args, env)
            if t is C.Var and f.name in self.tops:
                g = self.inline_candidate(f.name, len(args))
                if g is not None:
                    return self.beta(C.clone(g), args, env)
                if self.options.specialise:
                    s = self.specialise(f.name, args)
                    if s is not None:
                        f, args = s
                        if not args:
                            return f
            break
        return C.App(f, args)

    def beta(self, lam, args, env):
        n = min(len(lam.params), len(args))
        binds = []
        sub = {}
        for p, a in zip(lam.params[:n], args[:n]):
            if is_atom(a):
                sub[p] = a
            else:
                binds.append((p, a))
        body = lam.body
        if len(lam.params) > n:
            body = C.Lam(lam.params[n:], body)
        if sub:
            body = C.clone(body, sub)
        for p, a in reversed(binds):
            body = C.Let([(p, a)], body, False)
        if len(args) > n:
            body = C.App(body, args[n:])
        # simplify what the beta reduction made: lets of arguments, a known
        # constructor meeting a case
        occ = occurrences(body, {})
        saved = self.occ
        self.occ = occ
        out = self.simp(body, {}, env)
        self.occ = saved
        return out

    def used(self, name):
        """Might name be used? (Yes if the analysis didn't see it.)"""
        o = self.occ.get(name)
        return o is None or o.count > 0

    def inline_candidate(self, name, nargs):
        """The function to inline for a call of `name` with nargs
        arguments, or None."""
        if not self.options.inline:
            return None
        if name in self.recursive or name == self.current:
            return None
        g = self.tops.get(name)
        if type(g) is not C.Lam or nargs < len(g.params):
            return None
        if name.startswith(("$sel_", "$sup_")) or C.size(g) <= INLINE_SIZE:
            return g
        if name.startswith("$d") and type(g.body) is C.Con:
            return g            # an instance dictionary function
        return None

    def simp_let(self, e, sub, env):
        if not e.rec:
            (x, r), = e.binds
            r = self.simp(r, sub, env)
            o = self.occ.get(x)
            if is_atom(r):
                sub = dict(sub)
                sub[x] = r
                return self.simp(e.body, sub, env)
            # a binder the analysis didn't see (made since) is left alone
            if o is not None and o.count == 0:
                return self.simp(e.body, sub, env)
            if o is not None and o.count == 1 and (not o.in_lam or is_value(r)):
                sub = dict(sub)
                sub[x] = r
                return self.simp(e.body, sub, env)
            if type(r) is C.Let and not r.rec:
                # let x = (let y = a in b) in c  ->  let y = a in let x = b in c
                return C.Let(r.binds, self.simp(C.Let([(x, r.body)], e.body, False), sub, env), False)
            if type(r) is C.Con:
                env = dict(env)
                env[x] = Known(con=r.con, args=r.args)
            body = self.simp(e.body, sub, env)
            return C.Let([(x, r)], body, False)
        # recursive: drop what nothing uses
        binds = [(n, self.simp(r, sub, env)) for n, r in e.binds]
        body = self.simp(e.body, sub, env)
        used = C.free_vars(body)
        keep = []
        live = set(used)
        changed = True
        names = {n for n, _ in binds}
        while changed:
            changed = False
            for n, r in binds:
                if n in live and n not in keep:
                    keep.append(n)
                    live |= C.free_vars(r) & names
                    changed = True
        binds = [(n, r) for n, r in binds if n in live]
        if not binds:
            return body
        return C.Let(binds, body, True)

    def simp_case(self, e, sub, env):
        scrut = self.simp(e.scrut, sub, env)
        return self.case(scrut, e, sub, env)

    def case(self, scrut, e, sub, env):
        """Simplify `case scrut of e.binder { e.alts }` with scrut already
        simplified."""
        st = type(scrut)
        if st is C.Let:
            return C.Let(scrut.binds, self.case(scrut.body, e, sub, env), scrut.rec)
        known = None
        if st is C.Con:
            known = Known(con=scrut.con, args=scrut.args)
        elif st is C.Lit:
            known = Known(lit=scrut.value)
        elif st is C.Str:
            if scrut.codes:
                known = Known(con=self.cons_, args=[C.Lit("char", scrut.codes[0]), C.Str(scrut.codes[1:])])
            else:
                known = Known(con=self.nil, args=[])
        elif st is C.Var:
            known = env.get(scrut.name)
            if known is None and scrut.name in self.top_con:
                c = self.top_con[scrut.name]
                known = Known(con=c.con, args=c.args)
        elif st is C.Lam:
            known = Known()     # a function: evaluated, no constructor
        if known is not None:
            r = self.known_case(scrut, known, e, sub, env)
            if r is not None:
                return r
        if st is C.Case and self.case_of_case_ok(scrut, e):
            return self.case_of_case(scrut, e, sub, env)
        if not e.alts and e.default is not None and st is C.Case:
            pass
        alts = []
        for a in e.alts:
            env2 = dict(env)
            k = Known(con=a.con, args=[C.Var(v) for v in a.vars]) if a.con is not None else Known(lit=a.lit)
            env2[e.binder] = k
            if st is C.Var:
                env2[scrut.name] = k
            alts.append(C.Alt(a.con, a.lit, a.vars, self.simp(a.body, sub, env2)))
        default = None
        if e.default is not None:
            env2 = dict(env)
            if not e.alts:
                env2[e.binder] = Known()        # evaluated
                if st is C.Var:
                    env2[scrut.name] = Known()
            default = self.simp(e.default, sub, env2)
        if not alts and default is not None and st is C.Var and scrut.name in env:
            # forcing what is known to be evaluated
            sub2 = {e.binder: scrut}
            return C.clone(default, sub2) if self.used(e.binder) else default
        return C.Case(scrut, e.binder, alts, default)

    def known_case(self, scrut, k, e, sub, env):
        """The case on a scrutinee whose constructor or value is known, or
        None if this can't be decided."""
        alt = None
        if k.con is not None:
            for a in e.alts:
                if a.con is k.con:
                    alt = a
                    break
        elif k.lit is not None:
            for a in e.alts:
                if a.con is None and a.lit == k.lit:
                    alt = a
                    break
        elif e.alts:
            return None
        if alt is None and e.default is None:
            return None
        binds = []
        if type(scrut) is C.Con and any(not is_atom(a) for a in scrut.args) and self.used(e.binder):
            # the arguments once, shared by the binder and the fields
            atoms = []
            for a in scrut.args:
                if is_atom(a):
                    atoms.append(a)
                else:
                    v = C.fresh("arg")
                    binds.append((v, a))
                    atoms.append(C.Var(v))
            scrut = C.Con(scrut.con, atoms)
            k = Known(con=scrut.con, args=atoms)
        if self.used(e.binder):
            if type(scrut) in (C.Var, C.Lit):
                sub = dict(sub)
                sub[e.binder] = scrut
            else:
                binds.append((e.binder, scrut))
        forced = []
        if alt is None:
            body = e.default
        else:
            body = alt.body
            if alt.con is not None:
                for v, a, strict in zip(alt.vars, k.args, alt.con.strict):
                    if not is_atom(a) and type(scrut) is not C.Con:
                        a = C.clone(a)      # the expression lives on elsewhere too
                    if strict and type(scrut) is C.Con:
                        forced.append((v, a))   # the constructor would have forced it
                    elif is_atom(a):
                        sub = dict(sub)
                        sub[v] = a
                    else:
                        binds.append((v, a))
        out = self.simp(body, sub, env)
        for v, a in reversed(binds):
            if self.used(v):
                out = C.Let([(v, a)], out, False)
        for v, a in reversed(forced):
            out = C.Case(a, v, [], out)
        return out

    def case_of_case_ok(self, inner, outer):
        return True

    def case_of_case(self, inner, outer, sub, env):
        """case (case x of p -> a; q -> b) of alts  ->
        case x of p -> case a of alts; q -> case b of alts, with the outer
        alternatives as join points when copying them would cost."""
        branches = len(inner.alts) + (inner.default is not None)
        outer_size = sum(C.size(a.body) for a in outer.alts) + (
            C.size(outer.default) if outer.default is not None else 0)
        joins = []
        alts = outer.alts
        default = outer.default
        if branches > 1 and outer_size > CASE_DUP_SIZE:
            # the outer alternatives' bodies become join points
            new_alts = []
            for a in alts:
                if C.size(a.body) <= 3:
                    new_alts.append(a)
                    continue
                j = C.fresh("j")
                ps = [C.fresh(v) for v in a.vars]
                fvb = C.free_vars(a.body)
                use_b = outer.binder in fvb
                params = ps + ([C.fresh("jb")] if use_b else [])
                s = {v: C.Var(p) for v, p in zip(a.vars, ps)}
                if use_b:
                    s[outer.binder] = C.Var(params[-1])
                body = C.clone(a.body, s)
                if params:
                    joins.append((j, C.Lam(params, body)))
                    call = C.App(C.Var(j), [C.Var(v) for v in a.vars] + ([C.Var(outer.binder)] if use_b else []))
                else:
                    joins.append((j, body))
                    call = C.Var(j)
                new_alts.append(C.Alt(a.con, a.lit, a.vars, call))
            alts = new_alts
            if default is not None and C.size(default) > 3:
                j = C.fresh("j")
                use_b = outer.binder in C.free_vars(default)
                if use_b:
                    p = C.fresh("jb")
                    joins.append((j, C.Lam([p], C.clone(default, {outer.binder: C.Var(p)}))))
                    default = C.App(C.Var(j), [C.Var(outer.binder)])
                else:
                    joins.append((j, default))
                    default = C.Var(j)

        def push(body):
            return C.clone(C.Case(body, outer.binder, alts, default))

        new_inner = C.Case(inner.scrut, inner.binder,
                           [C.Alt(a.con, a.lit, a.vars, push(a.body)) for a in inner.alts],
                           None if inner.default is None else push(inner.default))
        out = new_inner
        for j, r in reversed(joins):
            out = C.Let([(j, r)], out, False)
        occ = occurrences(out, {})
        saved = self.occ
        self.occ = occ
        r = self.simp(out, sub, env)
        self.occ = saved
        return r

    def simp_prim(self, op, args):
        if all(type(a) is C.Lit for a in args) and op != "error":
            v = fold(op, [a.value for a in args])
            if v is not None:
                if op in C.COMPARE:
                    return C.Con(self.true if v else self.false, [])
                return C.Lit("char" if op == "chr" else "int", v)
        return C.Prim(op, args)

    # ---- specialisation

    def specialise(self, name, args):
        """A call of a top-level function with known dictionaries (or a
        known function it passes on unchanged): (the specialised function,
        the remaining arguments), or None."""
        g = self.tops.get(name)
        if type(g) is not C.Lam:
            return None
        n = len(g.params)
        if len(args) < 1:
            return None
        nd = self.dict_arity.get(self.spec_of.get(name, name), 0) if name not in self.spec_of else 0
        positions = []
        for i, a in enumerate(args[:n]):
            if i < nd and self.static_dict(a):
                positions.append(i)
            elif name in self.recursive and self.static_fun(a) and self.invariant(name, g, i):
                positions.append(i)
        if not positions:
            return None
        key = (name, tuple((i, C.show(args[i])) for i in positions))
        spec = self.specs.get(key)
        if spec is None or spec not in self.tops:
            if spec is None:
                if len(self.specs) > 400:
                    return None
                spec = C.fresh(name + "@")
                self.specs[key] = spec
                self.spec_of[spec] = name
                self.new_specs += 1
            keep = [p for i, p in enumerate(g.params) if i not in positions]
            s = {g.params[i]: args[i] for i in positions}
            body = C.clone(g.body, s)
            # fresh names for the parameters too: each copy's own
            self.tops[spec] = C.clone(C.Lam(keep, body)) if keep else body
            if spec not in self.order:
                self.order.insert(self.order.index(name) + 1 if name in self.order else len(self.order), spec)
            if name in self.recursive:
                self.rec_specs.add(spec)
                self.recursive.add(spec)
        rest = [a for i, a in enumerate(args) if i not in positions]
        return C.Var(spec), rest

    def static_dict(self, a):
        """A dictionary known at compile time: a global, or a global
        dictionary function applied to such."""
        if type(a) is C.Var:
            return a.name in self.tops and a.name.startswith("$d")
        if type(a) is C.App and type(a.fn) is C.Var and a.fn.name.startswith("$d"):
            return all(self.static_dict(x) for x in a.args)
        return False

    def static_fun(self, a):
        return type(a) is C.Var and a.name in self.tops and type(self.tops[a.name]) is C.Lam

    def invariant(self, name, g, i):
        """Does g pass its i-th parameter unchanged in every recursive call?"""
        p = g.params[i]
        ok = [True]

        def walk(e):
            t = type(e)
            if t is C.App:
                if type(e.fn) is C.Var and e.fn.name == name:
                    if len(e.args) <= i or not (type(e.args[i]) is C.Var and e.args[i].name == p):
                        ok[0] = False
                walk(e.fn)
                for a in e.args:
                    walk(a)
            elif t is C.Var:
                pass
            elif t is C.Lam:
                walk(e.body)
            elif t is C.Let:
                for _, r in e.binds:
                    walk(r)
                walk(e.body)
            elif t is C.Case:
                walk(e.scrut)
                for a in e.alts:
                    walk(a.body)
                if e.default is not None:
                    walk(e.default)
            elif t is C.Con or t is C.Prim:
                for a in e.args:
                    walk(a)
        walk(g.body)
        # a bare use of the function (not a call) can't be specialised
        return ok[0]


INT_MIN, INT_MAX = -(1 << 29), (1 << 29) - 1


def fold(op, v):
    """Constant folding: the value, or None to leave it to run time (an
    overflow or a division by zero is an error then)."""
    def chk(x):
        return x if INT_MIN <= x <= INT_MAX else None
    if op == "add":
        return chk(v[0] + v[1])
    if op == "sub":
        return chk(v[0] - v[1])
    if op == "mul":
        return chk(v[0] * v[1])
    if op == "neg":
        return chk(-v[0])
    if op in ("ord", "chr"):
        return v[0]
    if op == "eq":
        return v[0] == v[1]
    if op == "ne":
        return v[0] != v[1]
    if op == "lt":
        return v[0] < v[1]
    if op == "le":
        return v[0] <= v[1]
    if op == "gt":
        return v[0] > v[1]
    if op == "ge":
        return v[0] >= v[1]
    if op in ("quot", "rem", "div", "mod") and v[1] != 0:
        x, y = v
        q = abs(x) // abs(y)
        if (x < 0) != (y < 0):
            q = -q
        r = x - q * y
        if op == "quot":
            return chk(q)
        if op == "rem":
            return r
        if r != 0 and (r < 0) != (y < 0):
            q, r = q - 1, r + y
        return chk(q) if op == "div" else r
    if op == "and":
        return v[0] & v[1]
    if op == "or":
        return v[0] | v[1]
    if op == "xor":
        return v[0] ^ v[1]
    return None


def simplify(prog, options=None):
    return Simplifier(prog, options).run()
