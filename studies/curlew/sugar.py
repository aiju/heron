"""From the parser's tree to the kernel the type checker takes: operators
resolved by their fixities, the equations of each function grouped, and
the syntactic sugar removed (language.md says what each form means).

The kernel's expressions are EVar, ECon, ELit, EApp, ELam, ELet, ECase
and ETyped; its patterns PVar, PWild, PLit (an Int or a Char), PCon, PAs,
PLazy and PBang; its declarations DSig, DFun, DPatBind, DData, DTypeSyn,
DClass and DInstance.

- `if c then a else b` is a case on True and False.
- `do` is `>>=` and `>>`; a pattern that can fail is an error.
- `[a..b]` and its kin are the Enum methods enumFromTo, ...
- A list comprehension is Wadler's translation, into local functions,
  without building intermediate lists.
- `(e op)` is `(op) e`, and `(op e)` is `\\x -> x op e`.
- `-e` is `negate e`, and `-5` a literal.
- Tuples and lists are their constructors; a string pattern is a list of
  character patterns.
"""

from . import surface as S
from .lexer import CurlewError

DEFAULT_FIXITY = ("l", 9)


class Sugar:
    def __init__(self, fixities):
        self.fixities = fixities
        self.n = 0

    def fresh(self, base="v"):
        self.n += 1
        return f"%{base}{self.n}"

    def fixity(self, name):
        return self.fixities.get(name, DEFAULT_FIXITY)

    # ---- operators (Haskell 2010, 10.6)

    def resolve(self, items, mk_op, mk_neg):
        """items: [x, EOp, x, ...] with ENegOp markers; mk_op(op, l, r),
        mk_neg(x)."""
        toks = list(items)
        pos = 0

        def parse_neg(op1):
            nonlocal pos
            t = toks[pos]
            if isinstance(t, S.ENegOp):
                p1 = op1[1]
                if p1 >= 6:
                    raise CurlewError("a minus sign can't follow an operator of precedence 6 or more", t.where)
                pos += 1
                r = parse_neg(("-", 6, "l"))
                return parse1(op1, mk_neg(r, t.where))
            pos += 1
            return parse1(op1, t)

        def parse1(op1, e1):
            nonlocal pos
            while pos < len(toks):
                op2 = toks[pos]
                fix2, prec2 = self.fixity(op2.name)
                _, prec1, fix1 = op1
                if prec1 == prec2 and (fix1 != fix2 or fix1 == "n"):
                    raise CurlewError(f"can't mix {op1[0]} and {op2.name} without parentheses", op2.where)
                if prec1 > prec2 or (prec1 == prec2 and fix1 == "l"):
                    return e1
                pos += 1
                r = parse_neg((op2.name, prec2, fix2))
                e1 = mk_op(op2, e1, r)
            return e1

        out = parse_neg(("", -1, "n"))
        assert pos == len(toks)
        return out

    # ---- declarations

    def decls(self, decls, top=False):
        """Kernel declarations: equations grouped into DFun."""
        out = []
        for d in decls:
            if isinstance(d, S.DFixity):
                if not top:
                    raise CurlewError("fixity declarations go at the top level", d.where)
                continue
            if isinstance(d, S.DClause):
                rhs = self.rhs(d.rhs)
                pats = [self.pat(p) for p in d.pats]
                clause = S.DClause(d.name, pats, rhs, where=d.where)
                if out and isinstance(out[-1], S.DFun) and out[-1].name == d.name:
                    if len(out[-1].clauses[0].pats) != len(pats):
                        raise CurlewError(f"the equations of {d.name} have different numbers of arguments",
                                          d.where)
                    out[-1].clauses.append(clause)
                else:
                    out.append(S.DFun(d.name, [clause], where=d.where))
            elif isinstance(d, S.DPatBind):
                out.append(S.DPatBind(self.pat(d.pat), self.rhs(d.rhs), where=d.where))
            elif isinstance(d, S.DClass):
                out.append(S.DClass(d.context, d.name, d.tvar, self.decls(d.decls), where=d.where))
            elif isinstance(d, S.DInstance):
                out.append(S.DInstance(d.context, d.cls, d.type, self.decls(d.decls), where=d.where))
            else:
                out.append(d)
        # a name defined twice, not next to each other
        seen = set()
        for d in out:
            if isinstance(d, S.DFun):
                if d.name in seen:
                    raise CurlewError(f"{d.name} is defined twice (its equations must be together)", d.where)
                seen.add(d.name)
        return out

    def rhs(self, r):
        guards = [(None if g is None else self.expr(g), self.expr(e)) for g, e in r.guards]
        return S.Rhs(guards, self.decls(r.decls), where=r.where)

    # ---- expressions

    def expr(self, e):
        w = e.where
        m = getattr(self, "e_" + type(e).__name__)
        return m(e, w)

    def e_EVar(self, e, w):
        return e

    def e_ECon(self, e, w):
        return e

    def e_ELit(self, e, w):
        return e

    def e_EApp(self, e, w):
        return S.EApp(self.expr(e.fn), self.expr(e.arg), where=w)

    def e_ELam(self, e, w):
        return S.ELam([self.pat(p) for p in e.pats], self.expr(e.body), where=w)

    def e_ELet(self, e, w):
        return S.ELet(self.decls(e.decls), self.expr(e.body), where=w)

    def e_EIf(self, e, w):
        return S.ECase(self.expr(e.cond), [
            S.Alt(S.PCon("True", [], where=w), plain(self.expr(e.then)), where=w),
            S.Alt(S.PCon("False", [], where=w), plain(self.expr(e.else_)), where=w),
        ], where=w)

    def e_ECase(self, e, w):
        return S.ECase(self.expr(e.scrut),
                       [S.Alt(self.pat(a.pat), self.rhs(a.rhs), where=a.where) for a in e.alts],
                       where=w)

    def e_EDo(self, e, w):
        stmts = e.stmts
        if not stmts:
            raise CurlewError("an empty do block", w)

        def go(i):
            s = stmts[i]
            last = i == len(stmts) - 1
            if isinstance(s, S.SExpr):
                x = self.expr(s.expr)
                if last:
                    return x
                return app(S.EVar(">>", where=s.where), x, go(i + 1))
            if last:
                raise CurlewError("the last statement of a do block must be an expression", s.where)
            if isinstance(s, S.SLet):
                return S.ELet(self.decls(s.decls), go(i + 1), where=s.where)
            p = self.pat(s.pat)
            rest = go(i + 1)
            if isinstance(p, (S.PVar, S.PWild)):
                lam = S.ELam([p], rest, where=s.where)
            else:
                v = self.fresh()
                lam = S.ELam([S.PVar(v, where=s.where)], S.ECase(S.EVar(v, where=s.where), [
                    S.Alt(p, plain(rest), where=s.where),
                    S.Alt(S.PWild(where=s.where), plain(error_expr("pattern match failure in do", s.where)),
                          where=s.where),
                ], where=s.where), where=s.where)
            return app(S.EVar(">>=", where=s.where), self.expr(s.expr), lam)
        return go(0)

    def e_ETuple(self, e, w):
        return app(S.ECon(S.tuple_con(len(e.items)), where=w), *[self.expr(x) for x in e.items])

    def e_EList(self, e, w):
        out = S.ECon("[]", where=w)
        for x in reversed(e.items):
            out = app(S.ECon(":", where=x.where), self.expr(x), out)
        return out

    def e_ERange(self, e, w):
        if e.then is None and e.end is None:
            return app(S.EVar("enumFrom", where=w), self.expr(e.start))
        if e.then is None:
            return app(S.EVar("enumFromTo", where=w), self.expr(e.start), self.expr(e.end))
        if e.end is None:
            return app(S.EVar("enumFromThen", where=w), self.expr(e.start), self.expr(e.then))
        return app(S.EVar("enumFromThenTo", where=w), self.expr(e.start), self.expr(e.then),
                   self.expr(e.end))

    def e_EComp(self, e, w):
        return self.comp(e.expr, e.quals, lambda: S.ECon("[]", where=w))

    def comp(self, expr, quals, tail):
        """[expr | quals] ++ tail() (Wadler's translation). tail makes a
        new node each time: the type checker annotates nodes in place, so
        no node may appear twice."""
        if not quals:
            return app(S.ECon(":", where=expr.where), self.expr(expr), tail())
        q, rest = quals[0], quals[1:]
        w = q.where
        if isinstance(q, S.SExpr):
            return S.ECase(self.expr(q.expr), [
                S.Alt(S.PCon("True", [], where=w), plain(self.comp(expr, rest, tail)), where=w),
                S.Alt(S.PCon("False", [], where=w), plain(tail()), where=w),
            ], where=w)
        if isinstance(q, S.SLet):
            return S.ELet(self.decls(q.decls), self.comp(expr, rest, tail), where=w)
        # p <- l: let h [] = tail; h (p : us) = [expr | rest] ++ h us; h (_ : us) = h us in h l
        h, us = self.fresh("h"), self.fresh("us")

        def recur():
            return S.EApp(S.EVar(h, where=w), S.EVar(us, where=w), where=w)
        clauses = [
            S.DClause(h, [S.PCon("[]", [], where=w)], plain(tail()), where=w),
            S.DClause(h, [S.PCon(":", [self.pat(q.pat), S.PVar(us, where=w)], where=w)],
                      plain(self.comp(expr, rest, recur)), where=w),
        ]
        if refutable(q.pat):
            clauses.append(S.DClause(h, [S.PCon(":", [S.PWild(where=w), S.PVar(us, where=w)], where=w)],
                                     plain(recur()), where=w))
        return S.ELet([S.DFun(h, clauses, where=w)], S.EApp(S.EVar(h, where=w), self.expr(q.expr), where=w),
                      where=w)

    def e_EInfix(self, e, w):
        items = [x if isinstance(x, (S.EOp, S.ENegOp)) else self.expr(x) for x in e.items]

        def mk_op(op, l, r):
            f = (S.ECon if op.con else S.EVar)(op.name, where=op.where)
            return app(f, l, r)

        def mk_neg(x, where):
            if isinstance(x, S.ELit) and x.kind == "int":
                return S.ELit("int", -x.value, where=where)
            return S.EApp(S.EVar("negate", where=where), x, where=where)
        return self.resolve(items, mk_op, mk_neg)

    def e_ESectionL(self, e, w):
        op = e.op
        f = (S.ECon if op.con else S.EVar)(op.name, where=op.where)
        return S.EApp(f, self.expr(e.expr), where=w)

    def e_ESectionR(self, e, w):
        op = e.op
        f = (S.ECon if op.con else S.EVar)(op.name, where=op.where)
        v = self.fresh()
        return S.ELam([S.PVar(v, where=w)], app(f, S.EVar(v, where=w), self.expr(e.expr)), where=w)

    def e_ETyped(self, e, w):
        return S.ETyped(self.expr(e.expr), e.type, where=w)

    # ---- patterns

    def pat(self, p):
        w = p.where
        if isinstance(p, (S.PVar, S.PWild)):
            return p
        if isinstance(p, S.PLit):
            if p.kind == "string":
                out = S.PCon("[]", [], where=w)
                for c in reversed(p.value):
                    out = S.PCon(":", [S.PLit("char", c, where=w), out], where=w)
                return out
            return p
        if isinstance(p, S.PCon):
            return S.PCon(p.name, [self.pat(a) for a in p.args], where=w)
        if isinstance(p, S.PTuple):
            return S.PCon(S.tuple_con(len(p.items)), [self.pat(x) for x in p.items], where=w)
        if isinstance(p, S.PList):
            out = S.PCon("[]", [], where=w)
            for x in reversed(p.items):
                out = S.PCon(":", [self.pat(x), out], where=x.where)
            return out
        if isinstance(p, S.PAs):
            return S.PAs(p.name, self.pat(p.pat), where=w)
        if isinstance(p, S.PLazy):
            return S.PLazy(self.pat(p.pat), where=w)
        if isinstance(p, S.PBang):
            return S.PBang(self.pat(p.pat), where=w)
        if isinstance(p, S.PInfix):
            items = [x if isinstance(x, S.EOp) else self.pat(x) for x in p.items]

            def mk_op(op, l, r):
                return S.PCon(op.name, [l, r], where=op.where)

            def mk_neg(x, where):
                raise CurlewError("a minus sign in a pattern goes right before a number", where)
            return self.resolve(items, mk_op, mk_neg)
        raise AssertionError(p)


def app(f, *args):
    for a in args:
        f = S.EApp(f, a, where=f.where)
    return f


def plain(e):
    return S.Rhs([(None, e)], [], where=e.where)


def error_expr(msg, where):
    return S.EApp(S.EVar("error", where=where), S.ELit("string", [ord(c) for c in msg], where=where),
                  where=where)


def refutable(p):
    if isinstance(p, (S.PVar, S.PWild, S.PLazy)):
        return False
    if isinstance(p, S.PBang):
        return refutable(p.pat)
    if isinstance(p, S.PAs):
        return refutable(p.pat)
    if isinstance(p, S.PTuple):
        return any(refutable(x) for x in p.items)
    if isinstance(p, S.PCon) and p.name.startswith("(") and p.name.endswith(")") and "," in p.name:
        return any(refutable(x) for x in p.args)
    return True


def fixities(decls):
    out = {}
    for d in decls:
        if isinstance(d, S.DFixity):
            for op in d.ops:
                out[op] = (d.assoc, d.prec)
    return out


def kernel(decls, fixity_table):
    """The kernel of a program's (or the prelude's) declarations."""
    return Sugar(fixity_table).decls(decls, top=True)
