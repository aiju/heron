"""Types for the type checker: unification variables, constructors,
applications and the quantified variables of schemes; unification and
printing."""

from .lexer import CurlewError


class TV:
    """A unification variable. `level` is the depth of the binding group it
    was made in; a variable deeper than a group's is generalised there."""
    __slots__ = ("ref", "level", "id")
    n = 0

    def __init__(self, level):
        TV.n += 1
        self.ref = None
        self.level = level
        self.id = TV.n


class TC:
    """A type constructor: Int, ->, [], (,), Maybe, ..., or a skolem (a
    signature's type variable while its binding is checked), whose name
    holds a '!'."""
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name

    @property
    def skolem(self):
        return "!" in self.name


class TA:
    __slots__ = ("fn", "arg")

    def __init__(self, fn, arg):
        self.fn, self.arg = fn, arg


class TG:
    """The i-th quantified variable of a scheme."""
    __slots__ = ("i",)

    def __init__(self, i):
        self.i = i


class Scheme:
    """forall n variables. preds => type; preds are [(class, type)]."""
    __slots__ = ("n", "preds", "type")

    def __init__(self, n, preds, type):
        self.n, self.preds, self.type = n, preds, type


INT = TC("Int")
CHAR = TC("Char")
ARROW = TC("->")
LIST = TC("[]")
UNIT = TC("()")


def fn(a, b):
    return TA(TA(ARROW, a), b)


def fns(args, res):
    for a in reversed(args):
        res = fn(a, res)
    return res


def list_of(t):
    return TA(LIST, t)


STRING = list_of(CHAR)


def prune(t):
    while isinstance(t, TV) and t.ref is not None:
        t = t.ref
    return t


def zonk(t):
    """t with every bound variable replaced by what it's bound to."""
    t = prune(t)
    if isinstance(t, TA):
        return TA(zonk(t.fn), zonk(t.arg))
    return t


def spine(t):
    """(head, [arguments]) of a type application."""
    t = prune(t)
    args = []
    while isinstance(t, TA):
        args.append(t.arg)
        t = prune(t.fn)
    return t, args[::-1]


def split_fn(t):
    """(argument, result) of a function type, or None."""
    h, args = spine(t)
    if isinstance(h, TC) and h.name == "->" and len(args) == 2:
        return args
    return None


def ftv(t, out=None):
    """The unbound variables in a type, in order of first appearance."""
    if out is None:
        out = []
    t = prune(t)
    if isinstance(t, TV):
        if t not in out:
            out.append(t)
    elif isinstance(t, TA):
        ftv(t.fn, out)
        ftv(t.arg, out)
    return out


def same(a, b):
    a, b = prune(a), prune(b)
    if a is b:
        return True
    if isinstance(a, TC) and isinstance(b, TC):
        return a.name == b.name
    if isinstance(a, TA) and isinstance(b, TA):
        return same(a.fn, b.fn) and same(a.arg, b.arg)
    return False


class UnifyError(Exception):
    pass


def unify(a, b):
    a, b = prune(a), prune(b)
    if a is b:
        return
    if isinstance(a, TV):
        bind(a, b)
    elif isinstance(b, TV):
        bind(b, a)
    elif isinstance(a, TC) and isinstance(b, TC):
        if a.name != b.name:
            raise UnifyError()
    elif isinstance(a, TA) and isinstance(b, TA):
        unify(a.fn, b.fn)
        unify(a.arg, b.arg)
    else:
        raise UnifyError()


def bind(v, t):
    def walk(x):
        x = prune(x)
        if x is v:
            raise UnifyError("occurs")
        if isinstance(x, TV):
            if x.level > v.level:
                x.level = v.level
        elif isinstance(x, TA):
            walk(x.fn)
            walk(x.arg)
    walk(t)
    v.ref = t


def instantiate(scheme, level, args=None):
    """(preds, type) of a scheme with fresh variables (or `args`) for its
    quantified ones."""
    if args is None:
        args = [TV(level) for _ in range(scheme.n)]

    def inst(t):
        if isinstance(t, TG):
            return args[t.i]
        if isinstance(t, TA):
            return TA(inst(t.fn), inst(t.arg))
        return t
    return [(c, inst(t)) for c, t in scheme.preds], inst(scheme.type)


class Printer:
    """Types as text, naming variables a, b, c, ... consistently."""

    def __init__(self):
        self.names = {}

    def name(self, v):
        if v not in self.names:
            n = len(self.names)
            self.names[v] = chr(ord("a") + n % 26) + (str(n // 26) if n >= 26 else "")
        return self.names[v]

    def show(self, t, prec=0):
        t = prune(t)
        if isinstance(t, TV):
            return self.name(t)
        if isinstance(t, TG):
            return self.name(("g", t.i))
        if isinstance(t, TC):
            return self.name(t.name) if t.skolem else t.name
        h, args = spine(t)
        if isinstance(h, TC):
            if h.name == "->" and len(args) == 2:
                s = f"{self.show(args[0], 1)} -> {self.show(args[1], 0)}"
                return f"({s})" if prec > 0 else s
            if h.name == "[]" and len(args) == 1:
                if isinstance(prune(args[0]), TC) and prune(args[0]).name == "Char":
                    return "String"
                return f"[{self.show(args[0])}]"
            if h.name.startswith("(,") and len(args) == h.name.count(",") + 1:
                return "(" + ", ".join(self.show(a) for a in args) + ")"
        s = " ".join([self.show(h, 2)] + [self.show(a, 2) for a in args])
        return f"({s})" if prec > 1 else s

    def pred(self, c, t):
        return f"{c} {self.show(t, 2)}"


def show_type(t):
    return Printer().show(t)


def type_error(msg, where):
    raise CurlewError(msg, where)
