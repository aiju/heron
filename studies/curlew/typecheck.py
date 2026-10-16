"""Curlew's type checker: Hindley-Milner inference with single-parameter
type classes, over the kernel (sugar.py). It annotates the tree in place
for the desugarer (desugar.py):

- every EVar gets `var` (a Var) and `dicts`, the dictionaries it is
  applied to: Holes, each resolved to a dictionary parameter, a
  superclass of one, or an instance applied to further Holes. A reference
  to a member of the binding group being inferred is monomorphic: it gets
  `rec = True`, and the desugarer passes the group's own parameters.
- every ECon and PCon gets `con` (a ConInfo), every PVar and PAs `var`.
- every DFun and DPatBind gets `vars` (the Vars it defines) and
  `dict_params` (DictParams, the dictionaries it takes).

Binding groups are found by dependency analysis, as Haskell does, with
bindings that have signatures checked on their own. The monomorphism
restriction applies to bindings without arguments or signature. An
ambiguous constraint is defaulted to (), or Int if () has no instance.
"""

from . import surface as S
from .lexer import CurlewError
from .typesys import (TV, TC, TA, TG, Scheme, INT, CHAR, ARROW, LIST, UNIT, STRING, fn, fns,
                      prune, zonk, spine, ftv, same, unify, instantiate, Printer, UnifyError)

MAX_TUPLE = 7


# ---- what the checker knows about names

class Var:
    """A variable: kind 'top' (a top-level binding), 'local', 'method' (a
    class method), 'prim' (a primitive), 'default' (a class's default
    method) or 'imethod' (an instance's method). `name` is unique in the
    program. While its group is inferred it has `mono`, a type; then
    `scheme`."""
    __slots__ = ("name", "src", "kind", "mono", "scheme", "group", "cls", "where", "arity")

    def __init__(self, name, src, kind, mono=None, scheme=None):
        self.name, self.src, self.kind = name, src, kind
        self.mono, self.scheme = mono, scheme
        self.group = None
        self.cls = None
        self.where = None
        self.arity = None

    def __repr__(self):
        return f"Var({self.name})"


class DataInfo:
    def __init__(self, name, nvars):
        self.name, self.nvars = name, nvars
        self.cons = []

    def __repr__(self):
        return f"DataInfo({self.name})"


class ConInfo:
    """A constructor: its tag (its index in the data type), arity, which
    fields are strict, and its scheme."""

    def __init__(self, name, data, tag, fields, strict, scheme):
        self.name, self.data, self.tag = name, data, tag
        self.fields, self.strict, self.scheme = fields, strict, scheme
        self.arity = len(fields)

    def __repr__(self):
        return f"ConInfo({self.name})"


class ClassInfo:
    """A class: its type variable, superclasses (their dictionaries come
    first in this class's dictionary), methods (then their
    implementations), method schemes and default methods."""

    def __init__(self, name, supers, where):
        self.name, self.supers, self.where = name, supers, where
        self.methods = []           # [name]
        self.method_vars = {}       # name -> Var
        self.method_types = {}      # name -> type over TG(0) (the class's variable) and TG(1..)
        self.method_nvars = {}      # name -> number of quantified variables
        self.defaults = {}          # name -> DFun
        self.default_vars = {}      # name -> Var

    def __repr__(self):
        return f"ClassInfo({self.name})"


class InstInfo:
    """An instance C (T a1 .. an) with a context over the ai."""

    def __init__(self, cls, tycon, nvars, head, context, decls, where):
        self.cls, self.tycon, self.nvars = cls, tycon, nvars
        self.head, self.context = head, context     # head: type over TG(i); context: [(class, TG)]
        self.decls, self.where = decls, where
        self.methods = {}           # method name -> DFun
        self.method_vars = {}       # method name -> Var of the implementation
        self.super_holes = []       # Holes for the superclasses' dictionaries
        self.dict_params = []       # the context's dictionaries, as DictParams
        self.name = None            # the dictionary's name

    def __repr__(self):
        return f"InstInfo({self.cls} {self.tycon})"


class DictParam:
    """A dictionary a binding takes, for the predicate (cls, type)."""
    __slots__ = ("name", "cls", "type", "redirect")

    def __init__(self, name, cls, type):
        self.name, self.cls, self.type = name, cls, type
        self.redirect = None    # (DictParam, path): it's a superclass of another parameter

    def __repr__(self):
        return f"DictParam({self.name}: {self.cls})"


class Hole:
    """A dictionary needed for (cls, type). `resolved` becomes one of
    ('param', DictParam), ('super', resolved, class, index) (the index-th
    superclass dictionary of a dictionary of `class`), or ('inst',
    InstInfo, [Hole]) (an instance applied to its context's
    dictionaries)."""
    __slots__ = ("cls", "type", "resolved", "where")

    def __init__(self, cls, type, where):
        self.cls, self.type, self.where = cls, type, where
        self.resolved = None


class Group:
    """A binding group being inferred."""

    def __init__(self):
        self.inferring = True
        self.dict_params = []


class Scope:
    def __init__(self, parent=None, vars=None):
        self.parent = parent
        self.vars = vars or {}

    def lookup(self, name):
        s = self
        while s is not None:
            v = s.vars.get(name)
            if v is not None:
                return v
            s = s.parent
        return None


# ---- primitives: name -> type (language.md, "Primitives")

def _prims():
    a, b = TG(0), TG(1)
    i2 = fns([INT, INT], INT)
    cmp = fns([INT, INT], TC("Bool"))
    out = {
        "primIntAdd": (0, i2), "primIntSub": (0, i2), "primIntMul": (0, i2),
        "primIntQuot": (0, i2), "primIntRem": (0, i2), "primIntDiv": (0, i2), "primIntMod": (0, i2),
        "primIntNeg": (0, fn(INT, INT)),
        "primIntEq": (0, cmp), "primIntNe": (0, cmp), "primIntLt": (0, cmp),
        "primIntLe": (0, cmp), "primIntGt": (0, cmp), "primIntGe": (0, cmp),
        "primIntAnd": (0, i2), "primIntOr": (0, i2), "primIntXor": (0, i2),
        "primIntShl": (0, i2), "primIntShr": (0, i2),
        "primOrd": (0, fn(CHAR, INT)), "primChr": (0, fn(INT, CHAR)),
        "seq": (2, fns([a, b], b)),
        "error": (1, fn(STRING, a)),
    }
    return {k: Scheme(n, [], t) for k, (n, t) in out.items()}


PRIMS = _prims()


class Checker:
    def __init__(self):
        self.types = {}         # type constructor name -> number of arguments
        self.synonyms = {}      # name -> (tvars, surface type)
        self.datas = {}         # name -> DataInfo
        self.cons = {}          # constructor name -> ConInfo
        self.classes = {}       # name -> ClassInfo
        self.instances = {}     # (class, tycon) -> InstInfo
        self.holes = []         # Holes made since the current group started
        self.givens = []        # stack of [DictParam] from signatures and instances
        self.counter = 0
        self.top_names = set()
        self.globals = Scope()
        self.builtin_types()

    def uniq(self, name):
        self.counter += 1
        return f"{name}_{self.counter}"

    def err(self, msg, where):
        raise CurlewError(msg, where)

    # ---- built-in types

    def builtin_types(self):
        for n, k in (("Int", 0), ("Char", 0), ("->", 2)):
            self.types[n] = k
        a = TG(0)
        lst = self.add_data("[]", 1)
        self.add_con(lst, "[]", [], [], LIST_OF_A())
        self.add_con(lst, ":", [a, TA(LIST, a)], [False, False], LIST_OF_A())
        unit = self.add_data("()", 0)
        self.add_con(unit, "()", [], [], UNIT)
        for n in range(2, MAX_TUPLE + 1):
            name = S.tuple_con(n)
            d = self.add_data(name, n)
            res = TC(name)
            for i in range(n):
                res = TA(res, TG(i))
            self.add_con(d, name, [TG(i) for i in range(n)], [False] * n, res)
        for name, sch in PRIMS.items():
            v = Var(name, name, "prim", scheme=sch)
            self.globals.vars[name] = v

    def add_data(self, name, nvars):
        d = DataInfo(name, nvars)
        self.types[name] = nvars
        self.datas[name] = d
        return d

    def add_con(self, d, name, fields, strict, res):
        sch = Scheme(d.nvars, [], fns(fields, res))
        c = ConInfo(name, d, len(d.cons), fields, strict, sch)
        d.cons.append(c)
        self.cons[name] = c
        return c

    # ---- surface types to types

    def conv(self, t, tvs, where=None, new_vars=None):
        """A surface type as a type; tvs maps type variable names to types.
        new_vars: a level, to make a variable for each name not in tvs."""
        if isinstance(t, S.TyVar):
            if t.name not in tvs:
                if new_vars is None:
                    self.err(f"type variable {t.name} isn't bound here", t.where or where)
                tvs[t.name] = TV(new_vars)
            return tvs[t.name]
        h, args = split_tyapp(t)
        if isinstance(h, S.TyCon) and h.name in self.synonyms:
            params, body = self.synonyms[h.name]
            if len(args) < len(params):
                self.err(f"type synonym {h.name} needs {len(params)} arguments", h.where or where)
            inner = {p: self.conv(a, tvs, where, new_vars) for p, a in zip(params, args)}
            out = self.conv(body, inner, where)
            for a in args[len(params):]:
                out = TA(out, self.conv(a, tvs, where, new_vars))
            return out
        if isinstance(h, S.TyCon):
            if h.name not in self.types:
                self.err(f"unknown type {h.name}", h.where or where)
            out = TC(h.name)
        else:
            out = self.conv(h, tvs, where, new_vars)
        for a in args:
            out = TA(out, self.conv(a, tvs, where, new_vars))
        return out

    def scheme_of(self, qual, where, extra=None):
        """A signature as a scheme. extra: type variable names already
        quantified (a class's variable), first."""
        names = list(extra or [])
        for n in surface_tyvars(qual.type):
            if n not in names:
                names.append(n)
        tvs = {n: TG(i) for i, n in enumerate(names)}
        t = self.conv(qual.type, tvs, where)
        preds = []
        for c, ty in qual.context:
            if c not in self.classes:
                self.err(f"unknown class {c}", where)
            preds.append((c, self.conv(ty, tvs, where)))
        return Scheme(len(names), preds, t)

    # ---- declarations of types, classes and instances

    def declare_types(self, decls):
        datas = [d for d in decls if isinstance(d, S.DData)]
        for d in decls:
            if isinstance(d, S.DTypeSyn):
                if d.name in self.types or d.name in self.synonyms:
                    self.err(f"type {d.name} is defined twice", d.where)
                self.synonyms[d.name] = (d.tvars, d.type)
        for d in datas:
            if d.name in self.types or d.name in self.synonyms:
                self.err(f"type {d.name} is defined twice", d.where)
            self.add_data(d.name, len(d.tvars))
        for d in datas:
            info = self.datas[d.name]
            tvs = {n: TG(i) for i, n in enumerate(d.tvars)}
            res = TC(d.name)
            for i in range(len(d.tvars)):
                res = TA(res, TG(i))
            for c in d.constrs:
                if c.name in self.cons:
                    self.err(f"constructor {c.name} is defined twice", c.where)
                fields = [self.conv(t, tvs, c.where) for t, _ in c.fields]
                self.add_con(info, c.name, fields, [s for _, s in c.fields], res)
            if not d.constrs:
                self.err(f"data type {d.name} has no constructors", d.where)

    def declare_classes(self, decls):
        for d in decls:
            if not isinstance(d, S.DClass):
                continue
            if d.name in self.classes:
                self.err(f"class {d.name} is defined twice", d.where)
            supers = []
            for c, t in d.context:
                if not (isinstance(t, S.TyVar) and t.name == d.tvar):
                    self.err("a superclass constrains the class's own variable", d.where)
                if c not in self.classes:
                    self.err(f"unknown class {c} (superclasses come first)", d.where)
                supers.append(c)
            info = ClassInfo(d.name, supers, d.where)
            self.classes[d.name] = info
            for m in d.decls:
                if isinstance(m, S.DSig):
                    if m.qual.context:
                        self.err("a method's type can't have a context of its own", m.where)
                    sch = self.scheme_of(m.qual, m.where, extra=[d.tvar])
                    for name in m.names:
                        if name in info.method_types:
                            self.err(f"method {name} is declared twice", m.where)
                        if self.globals.vars.get(name):
                            self.err(f"{name} is already defined", m.where)
                        info.methods.append(name)
                        info.method_types[name] = sch.type
                        info.method_nvars[name] = sch.n
                        v = Var(name, name, "method",
                                scheme=Scheme(sch.n, [(d.name, TG(0))], sch.type))
                        v.cls = info
                        info.method_vars[name] = v
                        self.globals.vars[name] = v
                        self.top_names.add(name)
            for m in d.decls:
                if isinstance(m, S.DFun):
                    if m.name not in info.method_types:
                        self.err(f"{m.name} isn't a method of {d.name}", m.where)
                    info.defaults[m.name] = m
                    v = Var(f"$dm{d.name}_{m.name}", m.name, "default")
                    info.default_vars[m.name] = v
                elif not isinstance(m, S.DSig):
                    self.err("a class declares methods and their defaults", m.where)

    def declare_instances(self, decls):
        out = []
        for d in decls:
            if not isinstance(d, S.DInstance):
                continue
            if d.cls not in self.classes:
                self.err(f"unknown class {d.cls}", d.where)
            h, args = split_tyapp(d.type)
            if not isinstance(h, S.TyCon) or h.name in self.synonyms:
                self.err("an instance is for a type constructor applied to type variables", d.where)
            names = []
            for a in args:
                if not isinstance(a, S.TyVar) or a.name in names:
                    self.err("an instance is for a type constructor applied to distinct type variables",
                             d.where)
                names.append(a.name)
            if h.name not in self.types:
                self.err(f"unknown type {h.name}", d.where)
            key = (d.cls, h.name)
            if key in self.instances:
                self.err(f"a second instance {d.cls} {h.name}", d.where)
            tvs = {n: TG(i) for i, n in enumerate(names)}
            head = self.conv(d.type, tvs, d.where)
            ctx = []
            for c, t in d.context:
                if c not in self.classes:
                    self.err(f"unknown class {c}", d.where)
                if not (isinstance(t, S.TyVar) and t.name in tvs):
                    self.err("an instance context constrains the instance's type variables", d.where)
                ctx.append((c, tvs[t.name]))
            inst = InstInfo(d.cls, h.name, len(names), head, ctx, d.decls, d.where)
            inst.name = f"$d{d.cls}_{mangle_tycon(h.name)}"
            cls = self.classes[d.cls]
            for m in d.decls:
                if isinstance(m, S.DFun):
                    if m.name not in cls.method_types:
                        self.err(f"{m.name} isn't a method of {d.cls}", m.where)
                    inst.methods[m.name] = m
                    inst.method_vars[m.name] = Var(f"$c{d.cls}_{mangle_tycon(h.name)}_{m.name}", m.name,
                                                   "imethod")
                elif isinstance(m, S.DSig):
                    self.err("an instance has no signatures", m.where)
                else:
                    self.err("an instance defines methods", m.where)
            self.instances[key] = inst
            out.append(inst)
        return out

    # ---- expressions

    def infer(self, e, scope, level):
        m = getattr(self, "i_" + type(e).__name__)
        return m(e, scope, level)

    def i_EVar(self, e, scope, level):
        v = scope.lookup(e.name)
        if v is None:
            self.err(f"{e.name} isn't defined", e.where)
        e.var = v
        e.dicts = []
        e.rec = False
        if v.mono is not None:
            e.rec = v.group is not None and v.group.inferring
            return v.mono
        preds, t = instantiate(v.scheme, level)
        e.dicts = [Hole(c, ty, e.where) for c, ty in preds]
        self.holes += e.dicts
        return t

    def i_ECon(self, e, scope, level):
        c = self.cons.get(e.name)
        if c is None:
            self.err(f"constructor {e.name} isn't defined", e.where)
        e.con = c
        return instantiate(c.scheme, level)[1]

    def i_ELit(self, e, scope, level):
        return {"int": INT, "char": CHAR, "string": STRING}[e.kind]

    def i_EApp(self, e, scope, level):
        tf = self.infer(e.fn, scope, level)
        ta = self.infer(e.arg, scope, level)
        r = TV(level)
        self.unify(tf, fn(ta, r), e.where, lambda p: (
            f"{describe_expr(e.fn)} is applied to {p.show(ta)}, but its type is {p.show(tf)}"))
        return r

    def i_ELam(self, e, scope, level):
        binds = {}
        ts = [self.pat(p, binds, level) for p in e.pats]
        inner = Scope(scope, binds)
        return fns(ts, self.infer(e.body, inner, level))

    def i_ELet(self, e, scope, level):
        inner = self.decls(e.decls, scope, level)
        return self.infer(e.body, inner, level)

    def i_ECase(self, e, scope, level):
        ts = self.infer(e.scrut, scope, level)
        r = TV(level)
        for a in e.alts:
            binds = {}
            tp = self.pat(a.pat, binds, level)
            self.unify(tp, ts, a.where, lambda p: (
                f"this pattern is {p.show(tp)}, but the case is on {p.show(ts)}"))
            self.rhs(a.rhs, Scope(scope, binds), level, r)
        return r

    def i_ETyped(self, e, scope, level):
        t = self.infer(e.expr, scope, level)
        if e.type.context:
            self.err("a type annotation can't have a context", e.where)
        want = self.conv(e.type.type, {}, e.where, new_vars=level)
        self.unify(t, want, e.where, lambda p: f"the expression is {p.show(t)}, not {p.show(want)}")
        return t

    def rhs(self, r, scope, level, result):
        inner = self.decls(r.decls, scope, level) if r.decls else scope
        for g, x in r.guards:
            if g is not None:
                tg = self.infer(g, inner, level)
                self.unify(tg, TC("Bool"), g.where, lambda p: f"a guard is {p.show(tg)}, not Bool")
            tx = self.infer(x, inner, level)
            self.unify(tx, result, x.where, lambda p: (
                f"this is {p.show(tx)}, but it should be {p.show(result)}"))

    def unify(self, a, b, where, msg):
        try:
            unify(a, b)
        except UnifyError as ex:
            p = Printer()
            m = msg(p)
            if ex.args and ex.args[0] == "occurs":
                m += " (an infinite type)"
            self.err(m, where)

    # ---- patterns

    def pat(self, p, binds, level, defined=None):
        """The type of a pattern; binds its variables in `binds`. defined:
        Vars already made for the variables (a pattern binding's)."""
        if isinstance(p, S.PVar):
            return self.bind_var(p, p.name, binds, level, defined)
        if isinstance(p, S.PWild):
            return TV(level)
        if isinstance(p, S.PLit):
            return INT if p.kind == "int" else CHAR
        if isinstance(p, S.PCon):
            c = self.cons.get(p.name)
            if c is None:
                self.err(f"constructor {p.name} isn't defined", p.where)
            if len(p.args) != c.arity:
                self.err(f"{p.name} takes {c.arity} arguments, not {len(p.args)}", p.where)
            p.con = c
            _, t = instantiate(c.scheme, level)
            for a in p.args:
                ta = self.pat(a, binds, level, defined)
                arg, t = split2(t)
                self.unify(ta, arg, a.where, lambda pr: (
                    f"this pattern is {pr.show(ta)}, but {p.name} needs {pr.show(arg)} here"))
            return t
        if isinstance(p, S.PAs):
            t = self.pat(p.pat, binds, level, defined)
            tv = self.bind_var(p, p.name, binds, level, defined)
            self.unify(tv, t, p.where, lambda pr: "an as-pattern's type")
            return t
        if isinstance(p, (S.PLazy, S.PBang)):
            return self.pat(p.pat, binds, level, defined)
        raise AssertionError(p)

    def bind_var(self, p, name, binds, level, defined):
        if name in binds:
            self.err(f"{name} is bound twice in a pattern", p.where)
        if defined is not None:
            v = defined[name]
        else:
            v = Var(self.uniq(name), name, "local", mono=TV(level))
        v.where = p.where
        binds[name] = v
        p.var = v
        return v.mono

    # ---- bindings

    def decls(self, decls, scope, level, top=False, kind="local"):
        """Infer a list of declarations: the scope with their variables."""
        sigs = {}
        for d in decls:
            if isinstance(d, S.DSig):
                for n in d.names:
                    if n in sigs:
                        self.err(f"{n} has two signatures", d.where)
                    sigs[n] = d
        binds = [d for d in decls if isinstance(d, (S.DFun, S.DPatBind))]
        defined = {}
        for b in binds:
            for n in bound_names(b):
                if n in defined:
                    self.err(f"{n} is defined twice", b.where)
                defined[n] = b
        for n, d in sigs.items():
            if n not in defined:
                self.err(f"{n} has a signature but no definition", d.where)
        inner = Scope(scope)
        explicit, implicit = [], []
        for b in binds:
            if isinstance(b, S.DFun) and b.name in sigs:
                v = Var(self.name_for(b.name, top), b.name, "top" if top else "local")
                v.scheme = self.scheme_of(sigs[b.name].qual, sigs[b.name].where)
                v.where = b.where
                inner.vars[b.name] = v
                b.vars = [v]
                explicit.append(b)
            else:
                implicit.append(b)
        # dependency analysis of the implicit bindings
        names = {n: b for b in implicit for n in bound_names(b)}
        deps = {id(b): [] for b in implicit}
        for b in implicit:
            for n in free_vars_binding(b):
                if n in names and names[n] is not b and names[n] not in deps[id(b)]:
                    deps[id(b)].append(names[n])
                elif n in names and names[n] is b:
                    pass
        for group in sccs(implicit, deps):
            self.infer_group(group, inner, level, top, sigs)
        for b in explicit:
            self.check_explicit(b, b.vars[0], inner, level)
        return inner

    def name_for(self, name, top):
        if not top:
            return self.uniq(name)
        if name in self.top_names:
            return self.uniq(name)
        self.top_names.add(name)
        return name

    def infer_group(self, binds, scope, level, top, sigs):
        inner_level = level + 1
        group = Group()
        vars = {}
        for b in binds:
            b.vars = []
            for n in bound_names(b):
                v = Var(self.name_for(n, top), n, "top" if top else "local", mono=TV(inner_level))
                v.group = group
                v.where = b.where
                vars[n] = v
                b.vars.append(v)
                scope.vars[n] = v
        saved, self.holes = self.holes, []
        for b in binds:
            self.infer_binding(b, scope, inner_level, vars)
        holes, self.holes = self.holes, saved
        group.inferring = False
        restricted = any(isinstance(b, S.DPatBind) or not b.clauses[0].pats for b in binds)
        types = [zonk(v.mono) for v in vars.values()]
        free = []
        for t in types:
            ftv(t, free)
        gen = [v for v in free if v.level > level]
        params = []
        deferred = []

        def resolve(h):
            t = prune(h.type)
            head, args = spine(t)
            if isinstance(head, TV):
                if args:
                    self.err(f"can't handle the constraint {Printer().pred(h.cls, t)}", h.where)
                if head.level > level and not restricted and head in gen:
                    for p in params:
                        if p.cls == h.cls and p.type is head:
                            h.resolved = ("param", p)
                            return
                    p = DictParam(self.uniq("$dict" + h.cls), h.cls, head)
                    params.append(p)
                    h.resolved = ("param", p)
                    return
                if head.level > level and not restricted:
                    self.default(h, resolve)   # ambiguous
                    return
                if head.level > level:
                    head.level = level          # the monomorphism restriction: not generalised
                deferred.append(h)
                return
            self.resolve_con(h, head, args, resolve)

        for h in holes:
            resolve(h)
        params = self.simplify_params(params)
        gen = [v for v in gen if v.level > level]
        group.dict_params = params
        index = {v: i for i, v in enumerate(gen)}
        for b in binds:
            b.dict_params = params
        for v in vars.values():
            v.scheme = Scheme(len(gen), [(p.cls, generalize(p.type, index)) for p in params],
                              generalize(zonk(v.mono), index))
            v.mono = None
        self.holes += deferred
        for b in binds:
            if isinstance(b, S.DFun):
                b.vars[0].arity = len(b.clauses[0].pats)
        # signatures on the variables of a pattern binding: checked loosely
        for b in binds:
            if isinstance(b, S.DPatBind):
                for v in b.vars:
                    if v.src in sigs:
                        want = self.scheme_of(sigs[v.src].qual, sigs[v.src].where)
                        _, wt = instantiate(want, level)
                        _, have = instantiate(v.scheme, level)
                        self.unify(have, wt, b.where, lambda p: f"{v.src} doesn't have its signature's type")

    def simplify_params(self, params):
        """Drop a parameter whose dictionary a superclass of another one
        gives, and make it a superclass selection."""
        keep = []
        for p in params:
            via = None
            for q in params:
                if q is not p and q.type is p.type:
                    path = self.super_path(q.cls, p.cls)
                    if path:
                        via = (q, path)
                        break
            if via is None:
                keep.append(p)
            else:
                p.redirect = via
        return keep

    def super_path(self, frm, to):
        """[(class, index)...] from a dictionary of class `frm` to one of
        `to` through superclasses, or None."""
        todo = [(frm, [])]
        seen = set()
        while todo:
            c, path = todo.pop(0)
            if c == to and path:
                return path
            if c in seen:
                continue
            seen.add(c)
            for i, s in enumerate(self.classes[c].supers):
                todo.append((s, path + [(c, i)]))
        return None

    def resolve_con(self, h, head, args, resolve):
        """A hole on a type with a constructor at its head: a given (a
        skolem) or an instance."""
        if head.skolem:
            for givens in reversed(self.givens):
                for p in givens:
                    if same(p.type, head) and not args:
                        if p.cls == h.cls:
                            h.resolved = ("param", p)
                            return
                        path = self.super_path(p.cls, h.cls)
                        if path:
                            r = ("param", p)
                            for c, i in path:
                                r = ("super", r, c, i)
                            h.resolved = r
                            return
            self.err(f"no instance for {Printer().pred(h.cls, h.type)}: add it to the signature's context",
                     h.where)
        inst = self.instances.get((h.cls, head.name))
        if inst is None:
            self.err(f"no instance for {Printer().pred(h.cls, h.type)}", h.where)
        subs = []
        for c, g in inst.context:
            sh = Hole(c, args[g.i], h.where)
            subs.append(sh)
            resolve(sh)
        h.resolved = ("inst", inst, subs)

    def default(self, h, resolve):
        t = prune(h.type)
        for cand in (UNIT, INT):
            if (h.cls, cand.name) in self.instances:
                t.ref = cand
                resolve(h)
                return
        self.err(f"ambiguous type: {Printer().pred(h.cls, h.type)}", h.where)

    def infer_binding(self, b, scope, level, vars):
        if isinstance(b, S.DFun):
            v = vars[b.name]
            for c in b.clauses:
                t = self.clause(c, scope, level)
                self.unify(v.mono, t, c.where, lambda p: (
                    f"the equations of {b.name} disagree: {p.show(v.mono)} and {p.show(t)}"))
        else:
            binds = {}
            tp = self.pat(b.pat, binds, level, defined=vars)
            r = TV(level)
            self.rhs(b.rhs, scope, level, r)
            self.unify(tp, r, b.where, lambda p: f"the pattern is {p.show(tp)}, the value {p.show(r)}")

    def clause(self, c, scope, level):
        binds = {}
        ts = [self.pat(p, binds, level) for p in c.pats]
        r = TV(level)
        self.rhs(c.rhs, Scope(scope, binds), level, r)
        return fns(ts, r)

    def check_explicit(self, b, v, scope, level, givens_extra=None, skolem_args=None, scheme=None):
        """Check a binding against its scheme (a signature's, a method's)."""
        scheme = scheme or v.scheme
        inner = level + 1
        self.counter += 1
        sk = skolem_args or [TC(f"{v.src}!{self.counter}.{i}") for i in range(scheme.n)]
        preds, t = instantiate(scheme, inner, sk)
        params = list(givens_extra or [])
        for c, ty in preds:
            params.append(DictParam(self.uniq("$dict" + c), c, ty))
        self.givens.append(params)
        saved, self.holes = self.holes, []
        for c in b.clauses:
            tc = self.clause(c, scope, inner)
            self.unify(tc, t, c.where, lambda p: (
                f"{v.src} should be {p.show(t)}, but this equation is {p.show(tc)}"))
        holes, self.holes = self.holes, saved
        deferred = []

        def resolve(h):
            ty = prune(h.type)
            head, args = spine(ty)
            if isinstance(head, TV):
                if args:
                    self.err(f"can't handle the constraint {Printer().pred(h.cls, ty)}", h.where)
                if head.level > level:
                    self.default(h, resolve)
                else:
                    deferred.append(h)
                return
            self.resolve_con(h, head, args, resolve)

        for h in holes:
            resolve(h)
        self.givens.pop()
        self.holes += deferred
        b.dict_params = params
        v.arity = len(b.clauses[0].pats)
        return params

    # ---- the program

    def program(self, prelude, program):
        """Check the prelude's and the program's kernels: a Program."""
        allp = prelude + program
        self.declare_types(allp)
        self.declare_classes(prelude)
        pclasses = list(self.classes.values())
        self.declare_classes(program)
        pinsts = self.declare_instances(prelude)
        qinsts = self.declare_instances(program)
        insts = pinsts + qinsts
        pscope = self.decls(prelude, self.globals, 0, top=True)
        # main without a signature has main's type, not something more general
        if not any(isinstance(d, S.DSig) and "main" in d.names for d in program):
            mains = [d for d in program if isinstance(d, S.DFun) and d.name == "main"]
            if mains:
                w = mains[0].where
                string = S.TyApp(S.TyCon("[]", where=w), S.TyCon("Char", where=w), where=w)
                program = [S.DSig(["main"], S.Qual([], S.fun_type(string, string), where=w), where=w)] + program
        scope = self.decls(program, pscope, 0, top=True)
        # the prelude's classes and instances see the prelude, not the program
        for cls in self.classes.values():
            for m, d in cls.defaults.items():
                self.check_default(cls, m, d, pscope if cls in pclasses else scope)
        for inst in insts:
            self.check_instance(inst, pscope if inst in pinsts else scope)
        # what's left is ambiguous at the top level
        holes, self.holes = self.holes, []

        def resolve(h):
            ty = prune(h.type)
            head, args = spine(ty)
            if isinstance(head, TV):
                self.default(h, resolve)
            else:
                self.resolve_con(h, head, args, resolve)
        for h in holes:
            if h.resolved is None:
                resolve(h)
        main = scope.vars.get("main")
        if main is None or main.kind != "top" or main.src != "main":
            self.err("the program has no main", None)
        _, t = instantiate(main.scheme, 0)
        self.unify(t, fn(STRING, STRING), main.where, lambda p: (
            f"main should be String -> String, not {p.show(t)}"))
        tops = [d for d in prelude + program if isinstance(d, (S.DFun, S.DPatBind))]
        return Program(self, tops, insts, main)

    def check_default(self, cls, m, d, scope):
        self.counter += 1
        a = TC(f"{cls.name}!{self.counter}")
        n = cls.method_nvars[m]
        sk = [a] + [TC(f"{m}!{self.counter}.{i}") for i in range(1, n)]
        self_param = DictParam(self.uniq("$self" + cls.name), cls.name, a)
        v = cls.default_vars[m]
        sch = Scheme(n, [], cls.method_types[m])
        d.vars = [v]
        self.check_explicit(d, v, scope, 0, givens_extra=[self_param], skolem_args=sk, scheme=sch)

    def check_instance(self, inst, scope):
        cls = self.classes[inst.cls]
        self.counter += 1
        sk = [TC(f"{inst.tycon}!{self.counter}.{i}") for i in range(inst.nvars)]
        _, head = instantiate(Scheme(inst.nvars, [], inst.head), 0, sk)
        params = [DictParam(self.uniq("$dict" + c), c, sk[g.i]) for c, g in inst.context]
        inst.dict_params = params
        # the superclasses' dictionaries
        self.givens.append(params)
        for s in cls.supers:
            h = Hole(s, head, inst.where)

            def resolve(x):
                hd, args = spine(prune(x.type))
                self.resolve_con(x, hd, args, resolve)
            resolve(h)
            inst.super_holes.append(h)
        self.givens.pop()
        for m, d in inst.methods.items():
            n = cls.method_nvars[m]
            msk = [head] + [TC(f"{m}!{self.counter}.{i}") for i in range(1, n)]
            sch = Scheme(n, [], cls.method_types[m])
            v = inst.method_vars[m]
            d.vars = [v]
            self.check_explicit(d, v, scope, 0, givens_extra=params, skolem_args=msk, scheme=sch)


class Program:
    """The checked program: its top-level bindings (prelude first), data
    types, classes and instances, all annotated for the desugarer."""

    def __init__(self, checker, tops, instances, main):
        self.tops = tops
        self.datas = checker.datas
        self.cons = checker.cons
        self.classes = checker.classes
        self.instances = instances
        self.main = main


def LIST_OF_A():
    return TA(LIST, TG(0))


def split2(t):
    h, args = spine(t)
    if not (isinstance(h, TC) and h.name == "->" and len(args) == 2):
        raise AssertionError("constructor type")
    return args


def generalize(t, index):
    t = prune(t)
    if isinstance(t, TV):
        return TG(index[t]) if t in index else t
    if isinstance(t, TA):
        return TA(generalize(t.fn, index), generalize(t.arg, index))
    return t


def split_tyapp(t):
    args = []
    while isinstance(t, S.TyApp):
        args.append(t.arg)
        t = t.fn
    return t, args[::-1]


def surface_tyvars(t, out=None):
    if out is None:
        out = []
    if isinstance(t, S.TyVar):
        if t.name not in out:
            out.append(t.name)
    elif isinstance(t, S.TyApp):
        surface_tyvars(t.fn, out)
        surface_tyvars(t.arg, out)
    return out


def mangle_tycon(name):
    return {"[]": "List", "()": "Unit", "->": "Fun"}.get(
        name, name if not name.startswith("(,") else f"Tuple{name.count(',') + 1}")


def describe_expr(e):
    if isinstance(e, S.EVar):
        return e.name
    if isinstance(e, S.ECon):
        return e.name
    if isinstance(e, S.EApp):
        return describe_expr(e.fn)
    return "a function"


# ---- names a declaration binds, and the free variables of the kernel

def bound_names(b):
    if isinstance(b, S.DFun):
        return [b.name]
    out = []
    pat_vars(b.pat, out)
    return out


def pat_vars(p, out):
    if isinstance(p, S.PVar):
        out.append(p.name)
    elif isinstance(p, S.PCon):
        for a in p.args:
            pat_vars(a, out)
    elif isinstance(p, S.PAs):
        out.append(p.name)
        pat_vars(p.pat, out)
    elif isinstance(p, (S.PLazy, S.PBang)):
        pat_vars(p.pat, out)
    return out


def free_vars_binding(b):
    out = set()
    if isinstance(b, S.DFun):
        for c in b.clauses:
            bound = set()
            for p in c.pats:
                bound.update(pat_vars(p, []))
            fv_rhs(c.rhs, bound, out)
    else:
        fv_rhs(b.rhs, set(), out)
    return out


def fv_rhs(r, bound, out):
    bound = set(bound)
    if r.decls:
        bound |= decl_names(r.decls)
        for d in r.decls:
            if isinstance(d, (S.DFun, S.DPatBind)):
                for n in free_vars_binding(d):
                    if n not in bound:
                        out.add(n)
    for g, x in r.guards:
        if g is not None:
            fv(g, bound, out)
        fv(x, bound, out)


def decl_names(decls):
    out = set()
    for d in decls:
        if isinstance(d, (S.DFun, S.DPatBind)):
            out.update(bound_names(d))
    return out


def fv(e, bound, out):
    if isinstance(e, S.EVar):
        if e.name not in bound:
            out.add(e.name)
    elif isinstance(e, S.EApp):
        fv(e.fn, bound, out)
        fv(e.arg, bound, out)
    elif isinstance(e, S.ELam):
        b = set(bound)
        for p in e.pats:
            b.update(pat_vars(p, []))
        fv(e.body, b, out)
    elif isinstance(e, S.ELet):
        b = bound | decl_names(e.decls)
        for d in e.decls:
            if isinstance(d, (S.DFun, S.DPatBind)):
                for n in free_vars_binding(d):
                    if n not in b:
                        out.add(n)
        fv(e.body, b, out)
    elif isinstance(e, S.ECase):
        fv(e.scrut, bound, out)
        for a in e.alts:
            fv_rhs(a.rhs, bound | set(pat_vars(a.pat, [])), out)
    elif isinstance(e, S.ETyped):
        fv(e.expr, bound, out)


def sccs(nodes, deps):
    """Strongly connected components of the bindings, dependencies first
    (Tarjan)."""
    index, low, on, stack, out = {}, {}, set(), [], []
    counter = [0]

    def visit(n):
        index[id(n)] = low[id(n)] = counter[0]
        counter[0] += 1
        stack.append(n)
        on.add(id(n))
        for m in deps[id(n)]:
            if id(m) not in index:
                visit(m)
                low[id(n)] = min(low[id(n)], low[id(m)])
            elif id(m) in on:
                low[id(n)] = min(low[id(n)], index[id(m)])
        if low[id(n)] == index[id(n)]:
            comp = []
            while True:
                m = stack.pop()
                on.discard(id(m))
                comp.append(m)
                if m is n:
                    break
            out.append(comp[::-1])

    for n in nodes:
        if id(n) not in index:
            visit(n)
    return out
