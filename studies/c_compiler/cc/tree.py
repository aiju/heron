"""Typed syntax tree built by the parser. Every expression node has `ty`
(its C type) and `tok` (for messages)."""


class Node:
    __slots__ = ("tok",)


class Expr(Node):
    __slots__ = ("ty",)
    lvalue = False


class Num(Expr):
    __slots__ = ("value",)

    def __init__(self, value, ty, tok=None):
        self.value, self.ty, self.tok = value, ty, tok


class Str(Expr):
    """A string literal: an array of char. `label` is set by the code generator."""
    __slots__ = ("data", "label")
    lvalue = True

    def __init__(self, data, ty, tok=None):
        self.data, self.ty, self.tok = data, ty, tok
        self.label = None


class Ident(Expr):
    __slots__ = ("sym",)

    def __init__(self, sym, tok=None):
        self.sym, self.ty, self.tok = sym, sym.ty, tok

    @property
    def lvalue(self):
        return self.sym.kind == "var"


class Unary(Expr):
    """op: neg bitnot lnot deref addr"""
    __slots__ = ("op", "e")

    def __init__(self, op, e, ty, tok=None):
        self.op, self.e, self.ty, self.tok = op, e, ty, tok

    @property
    def lvalue(self):
        return self.op == "deref"


class Binary(Expr):
    """op: + - * / % << >> & | ^ == != < > <= >= && || ,
    and padd (ptr + int), psub (ptr - int), pdiff (ptr - ptr). For the
    arithmetic ops both operands already have the result type (except the
    shift count)."""
    __slots__ = ("op", "l", "r")

    def __init__(self, op, l, r, ty, tok=None):
        self.op, self.l, self.r, self.ty, self.tok = op, l, r, ty, tok


class Assign(Expr):
    """l = r, or l op= r. For compound assignment `cty` is the type the
    operation is done in: l is converted to cty, combined with r (already
    converted), and the result converted back to l's type."""
    __slots__ = ("op", "l", "r", "cty")

    def __init__(self, op, l, r, ty, cty=None, tok=None):
        self.op, self.l, self.r, self.ty, self.cty, self.tok = op, l, r, ty, cty, tok


class IncDec(Expr):
    __slots__ = ("e", "delta", "post")

    def __init__(self, e, delta, post, tok=None):
        self.e, self.delta, self.post, self.ty, self.tok = e, delta, post, e.ty, tok


class Cond(Expr):
    __slots__ = ("c", "a", "b")

    def __init__(self, c, a, b, ty, tok=None):
        self.c, self.a, self.b, self.ty, self.tok = c, a, b, ty, tok


class Call(Expr):
    """fn has function or pointer-to-function type; args are converted."""
    __slots__ = ("fn", "args", "fty")

    def __init__(self, fn, args, fty, tok=None):
        self.fn, self.args, self.fty, self.ty, self.tok = fn, args, fty, fty.ret, tok


class Member(Expr):
    __slots__ = ("e", "member")
    lvalue = True

    def __init__(self, e, member, ty, tok=None):
        self.e, self.member, self.ty, self.tok = e, member, ty, tok


class Cast(Expr):
    __slots__ = ("e",)

    def __init__(self, e, ty, tok=None):
        self.e, self.ty, self.tok = e, ty, tok


class Decay(Expr):
    """An array or function used as a value: its address."""
    __slots__ = ("e",)

    def __init__(self, e, ty, tok=None):
        self.e, self.ty, self.tok = e, ty, tok


class VaStart(Expr):
    __slots__ = ()

    def __init__(self, ty, tok=None):
        self.ty, self.tok = ty, tok


# --------------------------------------------------------------------------
# Statements


class Stmt(Node):
    __slots__ = ()


class Compound(Stmt):
    __slots__ = ("items",)

    def __init__(self, items, tok=None):
        self.items, self.tok = items, tok


class Decl(Stmt):
    """A local variable definition with an optional initializer
    (see parse.Initializer)."""
    __slots__ = ("sym", "init")

    def __init__(self, sym, init, tok=None):
        self.sym, self.init, self.tok = sym, init, tok


class ExprStmt(Stmt):
    __slots__ = ("e",)

    def __init__(self, e, tok=None):
        self.e, self.tok = e, tok


class If(Stmt):
    __slots__ = ("c", "then", "els")

    def __init__(self, c, then, els, tok=None):
        self.c, self.then, self.els, self.tok = c, then, els, tok


class While(Stmt):
    __slots__ = ("c", "body")

    def __init__(self, c, body, tok=None):
        self.c, self.body, self.tok = c, body, tok


class DoWhile(Stmt):
    __slots__ = ("body", "c")

    def __init__(self, body, c, tok=None):
        self.body, self.c, self.tok = body, c, tok


class For(Stmt):
    __slots__ = ("init", "c", "step", "body")

    def __init__(self, init, c, step, body, tok=None):
        self.init, self.c, self.step, self.body, self.tok = init, c, step, body, tok


class Switch(Stmt):
    __slots__ = ("e", "body", "cases", "default")

    def __init__(self, e, tok=None):
        self.e, self.tok = e, tok
        self.body = None
        self.cases = []          # Case nodes
        self.default = None


class Case(Stmt):
    __slots__ = ("value", "stmt", "block")

    def __init__(self, value, stmt, tok=None):
        self.value, self.stmt, self.tok = value, stmt, tok
        self.block = None


class Default(Stmt):
    __slots__ = ("stmt", "block")

    def __init__(self, stmt, tok=None):
        self.stmt, self.tok = stmt, tok
        self.block = None


class Break(Stmt):
    __slots__ = ()

    def __init__(self, tok=None):
        self.tok = tok


class Continue(Stmt):
    __slots__ = ()

    def __init__(self, tok=None):
        self.tok = tok


class Return(Stmt):
    __slots__ = ("e",)

    def __init__(self, e, tok=None):
        self.e, self.tok = e, tok


class Goto(Stmt):
    __slots__ = ("label",)

    def __init__(self, label, tok=None):
        self.label, self.tok = label, tok


class Label(Stmt):
    __slots__ = ("label", "stmt")

    def __init__(self, label, stmt, tok=None):
        self.label, self.stmt, self.tok = label, stmt, tok


class Empty(Stmt):
    __slots__ = ()

    def __init__(self, tok=None):
        self.tok = tok
