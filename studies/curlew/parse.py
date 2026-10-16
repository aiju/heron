"""Curlew's parser: tokens to the surface syntax tree (surface.py), with
Haskell's layout rule (language.md, "Layout").

Layout: after `let`, `where`, `do` and `of`, a token other than `{` opens
an implicit block at its column. While a block is open, a token that
starts a line at that column starts a new item (a virtual `;`), and one
left of it closes the block (a virtual `}`). A token that can't continue
an item also closes an implicit block (the report's parse-error(t) rule),
which is what ends `let ... in` and `(case ... of ...)`.

Operators are parsed as flat lists (EInfix, PInfix); fixity.py resolves
them once every fixity declaration is known.
"""

from . import surface as S
from .lexer import CurlewError, Token, lex

VSEMI = "vsemi"
VCLOSE = "vclose"
ATOM_START = {"varid", "conid", "int", "char", "string"}


class Parser:
    def __init__(self, toks):
        self.toks = toks
        self.pos = 0
        self.layout = []        # indentation of each open block; 0 for explicit braces
        self.semi_done = -1     # the token a virtual ; was already given for

    # ---- tokens and layout

    def peek(self):
        t = self.toks[self.pos]
        if self.layout and self.layout[-1] > 0 and t.first:
            m = self.layout[-1]
            if t.col < m:
                return Token(VCLOSE, None, t.line, t.col)
            if t.col == m and self.semi_done != self.pos:
                return Token(VSEMI, None, t.line, t.col)
        return t

    def next(self):
        t = self.peek()
        if t.kind == VSEMI:
            self.semi_done = self.pos
        elif t.kind == VCLOSE:
            raise AssertionError("a virtual } is taken by close_block")
        else:
            self.pos += 1
        return t

    def real(self, k=0):
        """The real token k ahead, layout aside."""
        return self.toks[min(self.pos + k, len(self.toks) - 1)]

    def err(self, msg, t=None):
        t = t or self.peek()
        raise CurlewError(msg, t.where)

    def at(self, kind, value=None):
        t = self.peek()
        return t.kind == kind and (value is None or t.value == value)

    def at_special(self, c):
        return self.at("special", c)

    def at_reserved(self, w):
        return self.at("reserved", w)

    def expect(self, kind, value=None, what=None):
        t = self.peek()
        if t.kind != kind or (value is not None and t.value != value):
            self.err(f"expected {what or value or kind}, found {describe(t)}")
        return self.next()

    def expect_special(self, c):
        return self.expect("special", c)

    def expect_reserved(self, w):
        return self.expect("reserved", w)

    def block(self, item, where_ok=True):
        """A block of items (`{ a; b }` or by layout): [results of item()].
        item() may return a list, which is spliced in."""
        out = []
        if self.at_special("{"):
            self.next()
            self.layout.append(0)
            while True:
                while self.at_special(";"):
                    self.next()
                if self.at_special("}"):
                    self.next()
                    break
                r = item()
                out += r if isinstance(r, list) else [r]
                if self.at_special(";"):
                    continue
                if self.at_special("}"):
                    continue
                self.err(f"expected ; or }}, found {describe(self.peek())}")
            self.layout.pop()
            return out
        t = self.real()
        enclosing = next((m for m in reversed(self.layout) if m > 0), 0)
        if t.kind == "eof" or t.col <= enclosing:
            return out          # an empty block
        self.layout.append(t.col)
        self.semi_done = self.pos   # the first item needs no ;
        while True:
            t = self.peek()
            if t.kind == VCLOSE or t.kind == "eof":
                break
            if t.kind == VSEMI and self.cant_start_item(self.real()):
                break           # parse-error(t): `where` after a case's alternatives, say
            if t.kind == VSEMI or t.is_("special", ";"):
                self.next()
                continue
            r = item()
            out += r if isinstance(r, list) else [r]
            t = self.peek()
            if t.kind in (VSEMI, VCLOSE, "eof") or t.is_("special", ";"):
                continue
            break               # parse-error(t): the token closes the block
        self.layout.pop()
        return out

    @staticmethod
    def cant_start_item(t):
        return ((t.kind == "reserved" and t.value in ("where", "then", "else", "of", "in", "|", "=", "->"))
                or (t.kind == "special" and t.value in ")],}"))

    # ---- the program

    def program(self):
        decls = self.block(self.topdecl)
        if not self.at("eof"):
            self.err(f"unexpected {describe(self.peek())}")
        return decls

    def topdecl(self):
        t = self.peek()
        if t.is_("reserved", "data"):
            return self.data_decl()
        if t.is_("reserved", "type"):
            return self.type_syn()
        if t.is_("reserved", "class"):
            return self.class_decl()
        if t.is_("reserved", "instance"):
            return self.instance_decl()
        return self.decl()

    def data_decl(self):
        w = self.next().where
        name = self.expect("conid", what="a type name").value
        tvars = []
        while self.at("varid"):
            tvars.append(self.next().value)
        constrs = []
        if self.at_reserved("="):
            self.next()
            constrs.append(self.constr())
            while self.at_reserved("|"):
                self.next()
                constrs.append(self.constr())
        deriving = []
        if self.at_reserved("deriving"):
            self.next()
            if self.at_special("("):
                self.next()
                if not self.at_special(")"):
                    deriving.append(self.expect("conid", what="a class").value)
                    while self.at_special(","):
                        self.next()
                        deriving.append(self.expect("conid", what="a class").value)
                self.expect_special(")")
            else:
                deriving.append(self.expect("conid", what="a class").value)
        return S.DData(name, tvars, constrs, deriving, where=w)

    def constr(self):
        w = self.peek().where
        if self.at_special("("):
            # an operator constructor in prefix form: (:+) a b
            self.next()
            name = self.expect("consym", what="a constructor operator").value
            self.expect_special(")")
            fields = []
            while self.at_field():
                fields.append(self.field())
            return S.Constr(name, fields, where=w)
        if self.at("conid"):
            name = self.next().value
            fields = []
            while self.at_field():
                fields.append(self.field())
            if self.at("consym"):
                if len(fields) != 0:
                    self.err("an infix constructor needs a single field on each side")
                left = (S.TyCon(name, where=w), False)
                op = self.next().value
                return S.Constr(op, [left, self.field()], where=w)
            return S.Constr(name, fields, where=w)
        left = self.field()
        op = self.expect("consym", what="a constructor").value
        return S.Constr(op, [left, self.field()], where=w)

    def at_field(self):
        t = self.peek()
        return (t.kind in ("conid", "varid") or t.is_("special", "(") or t.is_("special", "[")
                or (t.is_("varsym", "!")))

    def field(self):
        strict = False
        if self.at("varsym", "!"):
            self.next()
            strict = True
        return (self.atype(), strict)

    def type_syn(self):
        w = self.next().where
        name = self.expect("conid", what="a type name").value
        tvars = []
        while self.at("varid"):
            tvars.append(self.next().value)
        self.expect_reserved("=")
        return S.DTypeSyn(name, tvars, self.type_(), where=w)

    def class_decl(self):
        w = self.next().where
        ctx, head = self.context_and_head()
        name, args = split_app(head)
        if not isinstance(name, S.TyCon) or len(args) != 1 or not isinstance(args[0], S.TyVar):
            self.err("a class declaration is `class C a`", self.real())
        decls = []
        if self.at_reserved("where"):
            self.next()
            decls = self.block(self.decl)
        return S.DClass(ctx, name.name, args[0].name, decls, where=w)

    def instance_decl(self):
        w = self.next().where
        ctx, head = self.context_and_head()
        name, args = split_app(head)
        if not isinstance(name, S.TyCon) or len(args) != 1:
            self.err("an instance declaration is `instance C (T a b)`", self.real())
        decls = []
        if self.at_reserved("where"):
            self.next()
            decls = self.block(self.decl)
        return S.DInstance(ctx, name.name, args[0], decls, where=w)

    def context_and_head(self):
        t = self.type_()
        if self.at_reserved("=>"):
            self.next()
            return self.to_context(t), self.type_()
        return [], t

    def to_context(self, t):
        items = t.items if isinstance(t, TupleType) else [t]
        out = []
        for it in items:
            fn, args = split_app(it)
            if not isinstance(fn, S.TyCon) or len(args) != 1:
                self.err("a context is `C a` or `(C a, D b)`")
            out.append((fn.name, args[0]))
        return out

    # ---- declarations

    def decl(self):
        t = self.peek()
        if t.kind == "reserved" and t.value in ("infix", "infixl", "infixr"):
            return self.fixity()
        if t.kind == "varid" or (t.is_("special", "(") and self.real(1).kind in ("varsym", "consym")
                                 and self.real(2).is_("special", ")")):
            # a type signature? x, y :: T
            k = 0
            names = []
            while True:
                if self.real(k).kind == "varid":
                    names.append(self.real(k).value)
                    k += 1
                elif (self.real(k).is_("special", "(") and self.real(k + 1).kind == "varsym"
                      and self.real(k + 2).is_("special", ")")):
                    names.append(self.real(k + 1).value)
                    k += 3
                else:
                    break
                if self.real(k).is_("special", ","):
                    k += 1
                    continue
                break
            if self.real(k).is_("reserved", "::"):
                w = t.where
                self.pos += k + 1
                return S.DSig(names, self.qual_type(), where=w)
        return self.binding()

    def fixity(self):
        t = self.next()
        assoc = {"infixl": "l", "infixr": "r", "infix": "n"}[t.value]
        prec = 9
        if self.at("int"):
            prec = self.next().value
        ops = [self.op_name()]
        while self.at_special(","):
            self.next()
            ops.append(self.op_name())
        return S.DFixity(assoc, prec, ops, where=t.where)

    def op_name(self):
        t = self.peek()
        if t.kind in ("varsym", "consym"):
            return self.next().value
        if t.is_("special", "`"):
            self.next()
            name = self.next()
            if name.kind not in ("varid", "conid"):
                self.err("expected a name in backquotes", name)
            self.expect_special("`")
            return name.value
        self.err(f"expected an operator, found {describe(t)}")

    def binding(self):
        """A function equation or a pattern binding."""
        w = self.peek().where
        items = []
        while True:
            t = self.peek()
            if t.kind in ("varsym", "consym") and not self.is_bang():
                items.append(S.EOp(self.next().value, t.kind == "consym", where=t.where))
            elif t.is_("special", "`"):
                self.next()
                n = self.next()
                self.expect_special("`")
                items.append(S.EOp(n.value, n.kind == "conid", where=n.where))
            elif self.at_apat():
                items.append(self.apat())
            else:
                break
        if not items:
            self.err(f"expected a declaration, found {describe(self.peek())}")
        rhs = self.rhs("=")
        # an infix definition: p1 op p2 = ...
        for i, it in enumerate(items):
            if isinstance(it, S.EOp) and not it.con:
                left = self.pattern_from_items(items[:i])
                right = self.pattern_from_items(items[i + 1:])
                return S.DClause(it.name, [left, right], rhs, where=w)
        first = items[0]
        if isinstance(first, S.PVar) and len(items) > 1 and not any(isinstance(x, S.EOp) for x in items):
            return S.DClause(first.name, items[1:], rhs, where=w)
        if isinstance(first, S.PVar) and len(items) == 1:
            return S.DClause(first.name, [], rhs, where=w)
        if isinstance(first, S.PBang) and isinstance(first.pat, S.PVar) and len(items) == 1:
            # !x = e: a strict binding (only in let and where)
            return S.DPatBind(first, rhs, where=w)
        return S.DPatBind(self.pattern_from_items(items), rhs, where=w)

    def pattern_from_items(self, items):
        """A pattern from apats and constructor operators: C p1 p2, p1 : p2."""
        if not items:
            self.err("missing pattern")
        if any(isinstance(x, S.EOp) for x in items):
            groups, cur, out = [], [], []
            for x in items:
                if isinstance(x, S.EOp):
                    if not x.con:
                        self.err(f"{x.name} isn't a constructor", None)
                    out.append(self.con_app(cur))
                    out.append(x)
                    cur = []
                else:
                    cur.append(x)
            out.append(self.con_app(cur))
            return S.PInfix(out, where=out[0].where)
        return self.con_app(items)

    def con_app(self, items):
        if not items:
            self.err("missing pattern")
        if len(items) == 1:
            return items[0]
        head = items[0]
        if isinstance(head, S.PCon) and not head.args:
            return S.PCon(head.name, items[1:], where=head.where)
        self.err("a pattern applies a constructor", None)

    def rhs(self, eq):
        """`= e [where decls]` or guards `| g = e ...` ([where decls]); eq is
        '=' or '->'."""
        w = self.peek().where
        guards = []
        if self.at_reserved("|"):
            while self.at_reserved("|"):
                self.next()
                g = self.expr()
                self.expect_reserved(eq)
                guards.append((g, self.expr()))
                # guards may continue on the next line at the item's column
        else:
            self.expect_reserved(eq)
            guards.append((None, self.expr()))
        decls = []
        if self.at_reserved("where"):
            self.next()
            decls = self.block(self.decl)
        return S.Rhs(guards, decls, where=w)

    # ---- types

    def qual_type(self):
        t = self.type_()
        if self.at_reserved("=>"):
            self.next()
            return S.Qual(self.to_context(t), self.type_(), where=t.where)
        return S.Qual([], t, where=t.where)

    def type_(self):
        t = self.btype()
        if self.at_reserved("->"):
            self.next()
            return S.fun_type(t, self.type_())
        return t

    def btype(self):
        t = self.atype()
        while self.at_atype():
            t = S.TyApp(t, self.atype(), where=t.where)
        return t

    def at_atype(self):
        t = self.peek()
        return t.kind in ("conid", "varid") or t.is_("special", "(") or t.is_("special", "[")

    def atype(self):
        t = self.next()
        w = t.where
        if t.kind == "conid":
            return S.TyCon(t.value, where=w)
        if t.kind == "varid":
            return S.TyVar(t.value, where=w)
        if t.is_("special", "["):
            if self.at_special("]"):
                self.next()
                return S.TyCon("[]", where=w)
            inner = self.type_()
            self.expect_special("]")
            return S.TyApp(S.TyCon("[]", where=w), inner, where=w)
        if t.is_("special", "("):
            if self.at_special(")"):
                self.next()
                return S.TyCon("()", where=w)
            if self.at_reserved("->"):
                self.next()
                self.expect_special(")")
                return S.TyCon("->", where=w)
            if self.at_special(","):
                n = 1
                while self.at_special(","):
                    self.next()
                    n += 1
                self.expect_special(")")
                return S.TyCon(S.tuple_con(n), where=w)
            items = [self.type_()]
            while self.at_special(","):
                self.next()
                items.append(self.type_())
            self.expect_special(")")
            if len(items) == 1:
                return items[0]
            return TupleType(items, where=w)
        self.err(f"expected a type, found {describe(t)}", t)

    # ---- expressions

    def expr(self):
        e = self.infix_expr()
        if self.at_reserved("::"):
            w = self.next().where
            return S.ETyped(e, self.qual_type(), where=w)
        return e

    def infix_expr(self, section=False):
        """An infix expression as an EInfix (or a single expression). With
        section=True, a trailing operator is allowed, for a left section:
        then it returns (items, op)."""
        w = self.peek().where
        items = []
        while True:
            if self.at("varsym", "-"):
                items.append(S.ENegOp(where=self.next().where))
            e = self.lexpr()
            items.append(e)
            if self.at_op():
                op = self.op()
                if section and self.at_special(")"):
                    return items, op
                items.append(op)
                continue
            break
        if section:
            return items, None
        if len(items) == 1:
            return items[0]
        return S.EInfix(items, where=w)

    def at_op(self):
        t = self.peek()
        return t.kind in ("varsym", "consym") or t.is_("special", "`")

    def op(self):
        t = self.next()
        if t.kind in ("varsym", "consym"):
            return S.EOp(t.value, t.kind == "consym", where=t.where)
        n = self.next()
        if n.kind not in ("varid", "conid"):
            self.err("expected a name in backquotes", n)
        self.expect_special("`")
        return S.EOp(n.value, n.kind == "conid", where=n.where)

    def lexpr(self):
        t = self.peek()
        w = t.where
        if t.is_("reserved", "\\"):
            self.next()
            pats = []
            while not self.at_reserved("->"):
                pats.append(self.apat())
            self.next()
            return S.ELam(pats, self.expr(), where=w)
        if t.is_("reserved", "let"):
            self.next()
            decls = self.block(self.decl)
            self.expect_reserved("in")
            return S.ELet(decls, self.expr(), where=w)
        if t.is_("reserved", "if"):
            self.next()
            c = self.expr()
            self.skip_semi()
            self.expect_reserved("then")
            a = self.expr()
            self.skip_semi()
            self.expect_reserved("else")
            return S.EIf(c, a, self.expr(), where=w)
        if t.is_("reserved", "case"):
            self.next()
            scrut = self.expr()
            self.expect_reserved("of")
            return S.ECase(scrut, self.block(self.alt), where=w)
        if t.is_("reserved", "do"):
            self.next()
            return S.EDo(self.block(self.stmt), where=w)
        return self.fexpr()

    def skip_semi(self):
        if self.at(VSEMI) or self.at_special(";"):
            self.next()

    def alt(self):
        w = self.peek().where
        p = self.pattern()
        return S.Alt(p, self.rhs("->"), where=w)

    def stmt(self):
        w = self.peek().where
        if self.at_reserved("let"):
            save = self.pos, list(self.layout), self.semi_done
            self.next()
            decls = self.block(self.decl)
            if not self.at_reserved("in"):
                return S.SLet(decls, where=w)
            self.pos, self.layout, self.semi_done = save   # a let expression after all
        # pat <- e, or an expression: try the pattern first
        save = self.pos, list(self.layout), self.semi_done
        try:
            p = self.pattern()
            if self.at_reserved("<-"):
                self.next()
                return S.SBind(p, self.expr(), where=w)
        except CurlewError:
            pass
        self.pos, self.layout, self.semi_done = save
        return S.SExpr(self.expr(), where=w)

    def fexpr(self):
        e = self.aexpr()
        while self.at_aexpr():
            a = self.aexpr()
            e = S.EApp(e, a, where=e.where)
        return e

    def at_aexpr(self):
        t = self.peek()
        return t.kind in ATOM_START or t.is_("special", "(") or t.is_("special", "[")

    def aexpr(self):
        t = self.next()
        w = t.where
        if t.kind == "varid":
            return S.EVar(t.value, where=w)
        if t.kind == "conid":
            return S.ECon(t.value, where=w)
        if t.kind in ("int", "char", "string"):
            return S.ELit(t.kind, t.value, where=w)
        if t.is_("special", "("):
            return self.paren(w)
        if t.is_("special", "["):
            return self.bracket(w)
        self.err(f"expected an expression, found {describe(t)}", t)

    def paren(self, w):
        if self.at_special(")"):
            self.next()
            return S.ECon("()", where=w)
        if self.at_special(","):
            n = 1
            while self.at_special(","):
                self.next()
                n += 1
            self.expect_special(")")
            return S.ECon(S.tuple_con(n), where=w)
        # (op) or a right section (op e); (- e) is a negation
        t = self.peek()
        if (t.kind in ("varsym", "consym") or t.is_("special", "`")) and not (
                t.is_("varsym", "-") and not self.real(1).is_("special", ")")):
            op = self.op()
            if self.at_special(")"):
                self.next()
                return (S.ECon if op.con else S.EVar)(op.name, where=op.where)
            e = self.infix_expr()
            self.expect_special(")")
            return S.ESectionR(op, e, where=w)
        items, op = self.infix_expr(section=True)
        if op is not None:
            self.expect_special(")")
            e = items[0] if len(items) == 1 else S.EInfix(items, where=w)
            return S.ESectionL(e, op, where=w)
        e = items[0] if len(items) == 1 else S.EInfix(items, where=w)
        if self.at_reserved("::"):
            self.next()
            e = S.ETyped(e, self.qual_type(), where=w)
        if self.at_special(","):
            es = [e]
            while self.at_special(","):
                self.next()
                es.append(self.expr())
            self.expect_special(")")
            return S.ETuple(es, where=w)
        self.expect_special(")")
        return e

    def bracket(self, w):
        if self.at_special("]"):
            self.next()
            return S.ECon("[]", where=w)
        first = self.expr()
        if self.at_reserved(".."):
            self.next()
            end = None if self.at_special("]") else self.expr()
            self.expect_special("]")
            return S.ERange(first, None, end, where=w)
        if self.at_reserved("|"):
            self.next()
            quals = [self.qual()]
            while self.at_special(","):
                self.next()
                quals.append(self.qual())
            self.expect_special("]")
            return S.EComp(first, quals, where=w)
        items = [first]
        if self.at_special(","):
            self.next()
            second = self.expr()
            if self.at_reserved(".."):
                self.next()
                end = None if self.at_special("]") else self.expr()
                self.expect_special("]")
                return S.ERange(first, second, end, where=w)
            items.append(second)
            while self.at_special(","):
                self.next()
                items.append(self.expr())
        self.expect_special("]")
        return S.EList(items, where=w)

    def qual(self):
        w = self.peek().where
        if self.at_reserved("let"):
            self.next()
            return S.SLet(self.block(self.decl), where=w)
        save = self.pos, list(self.layout), self.semi_done
        try:
            p = self.pattern()
            if self.at_reserved("<-"):
                self.next()
                return S.SBind(p, self.expr(), where=w)
        except CurlewError:
            pass
        self.pos, self.layout, self.semi_done = save
        return S.SExpr(self.expr(), where=w)

    # ---- patterns

    def pattern(self):
        """pat: lpat (conop pat)*, as a PInfix if there are operators."""
        w = self.peek().where
        items = [self.lpat()]
        while self.at("consym") or (self.at_special("`") and self.real(1).kind == "conid"):
            items.append(self.op())
            items.append(self.lpat())
        if len(items) == 1:
            return items[0]
        return S.PInfix(items, where=w)

    def lpat(self):
        t = self.peek()
        if t.is_("varsym", "-") and self.real(1).kind == "int":
            self.next()
            v = self.next().value
            return S.PLit("int", -v, where=t.where)
        if t.kind == "conid":
            self.next()
            args = []
            while self.at_apat():
                args.append(self.apat())
            return S.PCon(t.value, args, where=t.where)
        return self.apat()

    def is_bang(self):
        """A ! right before a pattern: a bang pattern, not an operator."""
        t, n = self.real(), self.real(1)
        return (t.is_("varsym", "!") and n.line == t.line and n.col == t.col + 1
                and (n.kind in ATOM_START or n.is_("special", "(") or n.is_("special", "[")))

    def at_apat(self):
        t = self.peek()
        if t.kind in ATOM_START or t.is_("special", "(") or t.is_("special", "["):
            return True
        if t.is_("reserved", "_") or t.is_("reserved", "~"):
            return True
        return self.is_bang()

    def apat(self):
        t = self.next()
        w = t.where
        if t.kind == "varid":
            if self.at_reserved("@"):
                self.next()
                return S.PAs(t.value, self.apat(), where=w)
            return S.PVar(t.value, where=w)
        if t.kind == "conid":
            return S.PCon(t.value, [], where=w)
        if t.is_("reserved", "_"):
            return S.PWild(where=w)
        if t.kind in ("int", "char", "string"):
            return S.PLit(t.kind, t.value, where=w)
        if t.is_("reserved", "~"):
            return S.PLazy(self.apat(), where=w)
        if t.is_("varsym", "!"):
            return S.PBang(self.apat(), where=w)
        if t.is_("special", "("):
            if self.at_special(")"):
                self.next()
                return S.PCon("()", [], where=w)
            if self.at("varsym") and self.real(1).is_("special", ")"):
                name = self.next().value       # (op), defining an operator in prefix form
                self.next()
                return S.PVar(name, where=w)
            if self.at("consym") and self.real(1).is_("special", ")"):
                name = self.next().value
                self.next()
                args = []
                while self.at_apat():
                    args.append(self.apat())
                return S.PCon(name, args, where=w)
            p = self.pattern()
            if self.at_special(","):
                ps = [p]
                while self.at_special(","):
                    self.next()
                    ps.append(self.pattern())
                self.expect_special(")")
                return S.PTuple(ps, where=w)
            self.expect_special(")")
            return p
        if t.is_("special", "["):
            ps = []
            if not self.at_special("]"):
                ps.append(self.pattern())
                while self.at_special(","):
                    self.next()
                    ps.append(self.pattern())
            self.expect_special("]")
            return S.PList(ps, where=w)
        self.err(f"expected a pattern, found {describe(t)}", t)


class TupleType(S.Node):
    """A parenthesised list of types, before it's known to be a tuple type
    or a context."""
    _fields = ("items",)

    def __init__(self, items, where=None):
        self.items = items
        self.where = where


def split_app(t):
    """A type application's head and arguments."""
    args = []
    while isinstance(t, S.TyApp):
        args.append(t.arg)
        t = t.fn
    return t, args[::-1]


def describe(t):
    if t.kind == "eof":
        return "the end of the program"
    if t.kind == VSEMI:
        return "a new line"
    if t.kind == VCLOSE:
        return "the end of a block"
    if t.kind == "string":
        return "a string"
    return repr(t.value) if t.value is not None else t.kind


def fix_tuple_types(x):
    """Turn every TupleType left in a tree into a tuple type."""
    if isinstance(x, TupleType):
        items = [fix_tuple_types(i) for i in x.items]
        t = S.TyCon(S.tuple_con(len(items)), where=x.where)
        for i in items:
            t = S.TyApp(t, i, where=x.where)
        return t
    if isinstance(x, list):
        return [fix_tuple_types(i) for i in x]
    if isinstance(x, tuple):
        return tuple(fix_tuple_types(i) for i in x)
    if isinstance(x, S.Node):
        for f in x._fields:
            setattr(x, f, fix_tuple_types(getattr(x, f)))
    return x


def parse(text):
    """A program's declarations (surface syntax), operators still flat."""
    p = Parser(lex(text))
    return fix_tuple_types(p.program())
