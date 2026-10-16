"""The surface syntax tree, as the parser makes it (parse.py). Every node
has `where`, (line, column), for error messages."""


class Node:
    """A node. `_fields` names its children; the passes after the parser
    add attributes of their own (the type checker's annotations)."""
    _fields = ()

    def __repr__(self):
        fields = ", ".join(f"{k}={getattr(self, k)!r}" for k in self._fields)
        return f"{type(self).__name__}({fields})"


def node(name, *fields):
    """A node class with these fields; the constructor takes them in order,
    then `where`."""
    def __init__(self, *args, where=None):
        assert len(args) == len(fields), (name, args)
        for f, a in zip(fields, args):
            setattr(self, f, a)
        self.where = where
    return type(name, (Node,), {"_fields": fields, "__init__": __init__})


# ---- expressions
EVar = node("EVar", "name")                 # a variable, or an operator as a value
ECon = node("ECon", "name")                 # a constructor
ELit = node("ELit", "kind", "value")        # kind: 'int', 'char', 'string' (a list of codes)
EApp = node("EApp", "fn", "arg")
ELam = node("ELam", "pats", "body")
ELet = node("ELet", "decls", "body")
EIf = node("EIf", "cond", "then", "else_")
ECase = node("ECase", "scrut", "alts")
EDo = node("EDo", "stmts")
ETuple = node("ETuple", "items")
EList = node("EList", "items")
ERange = node("ERange", "start", "then", "end")     # then, end: None if absent
EComp = node("EComp", "expr", "quals")
EInfix = node("EInfix", "items")            # [expr, EOp, expr, ...] and ENegOp, before fixities
EOp = node("EOp", "name", "con")            # an operator in an EInfix; con: a constructor
ENegOp = node("ENegOp")                     # prefix minus in an EInfix
ESectionL = node("ESectionL", "expr", "op")  # (e op)
ESectionR = node("ESectionR", "op", "expr")  # (op e)
ETyped = node("ETyped", "expr", "type")

# statements of do, qualifiers of comprehensions
SBind = node("SBind", "pat", "expr")        # pat <- e
SLet = node("SLet", "decls")
SExpr = node("SExpr", "expr")

Alt = node("Alt", "pat", "rhs")
# guards: [(condition, expr)], or [(None, expr)] for a plain right-hand side
Rhs = node("Rhs", "guards", "decls")

# ---- patterns
PVar = node("PVar", "name")
PWild = node("PWild")
PLit = node("PLit", "kind", "value")        # 'int' (maybe negative), 'char', 'string'
PCon = node("PCon", "name", "args")
PTuple = node("PTuple", "items")
PList = node("PList", "items")
PAs = node("PAs", "name", "pat")
PLazy = node("PLazy", "pat")
PBang = node("PBang", "pat")
PInfix = node("PInfix", "items")            # [pat, EOp, pat, ...], before fixities

# ---- types
TyVar = node("TyVar", "name")
TyCon = node("TyCon", "name")               # Int, ->, [], (,), (,,), (), ...
TyApp = node("TyApp", "fn", "arg")
Qual = node("Qual", "context", "type")      # context: [(class, type)]

# ---- declarations
DSig = node("DSig", "names", "qual")
DClause = node("DClause", "name", "pats", "rhs")   # one equation of a function
DPatBind = node("DPatBind", "pat", "rhs")
DFun = node("DFun", "name", "clauses")      # the equations of one function, grouped
Constr = node("Constr", "name", "fields")   # fields: [(type, strict)]
DData = node("DData", "name", "tvars", "constrs", "deriving")
DTypeSyn = node("DTypeSyn", "name", "tvars", "type")
DClass = node("DClass", "context", "name", "tvar", "decls")
DInstance = node("DInstance", "context", "cls", "type", "decls")
DFixity = node("DFixity", "assoc", "prec", "ops")   # assoc: 'l', 'r', 'n'


def fun_type(a, b):
    return TyApp(TyApp(TyCon("->"), a), b)


def tuple_con(n):
    return "(" + "," * (n - 1) + ")"
