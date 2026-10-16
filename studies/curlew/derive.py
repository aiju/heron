"""`deriving`: the instances a data declaration asks for, written as
Curlew source and parsed like the rest (language.md, "Deriving"). They
use only the prelude's functions and the type's constructors, so they are
checked in the prelude's scope, where a program's definitions can't
capture their names.

- Eq: equal constructors with equal fields.
- Ord: constructors in the order they're declared, then the fields from
  left to right.
- Show: as Haskell shows them, with parentheses where showsPrec's
  precedence needs them.
- Enum, for types whose constructors have no fields: fromEnum, toEnum,
  and enumFrom up to the last constructor.
"""

from . import surface as S
from .lexer import CurlewError

DERIVABLE = ("Eq", "Ord", "Show", "Enum")


def is_op(name):
    return not (name[0].isalpha() or name[0] == "_" or name.startswith("(") or name == "[]")


def con_pat(c, prefix):
    """A pattern for constructor c with variables prefix1, prefix2, ..."""
    vs = [f"{prefix}{i + 1}" for i in range(len(c.fields))]
    if is_op(c.name) and len(vs) == 2:
        return f"({vs[0]} {c.name} {vs[1]})", vs
    if not vs:
        return c.name, vs
    return "(" + " ".join([c.name] + vs) + ")", vs


def type_text(t):
    if isinstance(t, S.TyVar):
        return t.name
    if isinstance(t, S.TyCon):
        return t.name
    return f"({type_text(t.fn)} {type_text(t.arg)})"


def head(d, cls):
    ctx = ", ".join(f"{cls} {v}" for v in d.tvars)
    ty = d.name if not d.tvars else "(" + " ".join([d.name] + d.tvars) + ")"
    return f"instance ({ctx}) => {cls} {ty} where" if ctx else f"instance {cls} {ty} where"


def tag_case(d, var):
    alts = "; ".join(f"{wild_pat(c)} -> {i}" for i, c in enumerate(d.constrs))
    return f"(case {var} of {{ {alts} }})"


def wild_pat(c):
    n = len(c.fields)
    if n == 0:
        return c.name
    if is_op(c.name) and n == 2:
        return f"(_ {c.name} _)"
    return "(" + " ".join([c.name] + ["_"] * n) + ")"


def derive_eq(d):
    lines = [head(d, "Eq")]
    for c in d.constrs:
        p, xs = con_pat(c, "x")
        q, ys = con_pat(c, "y")
        body = " && ".join(f"({x} == {y})" for x, y in zip(xs, ys)) or "True"
        lines.append(f"  {p} == {q} = {body}")
    if len(d.constrs) > 1:
        lines.append("  _ == _ = False")
    return lines


def derive_ord(d):
    lines = [head(d, "Ord")]
    for c in d.constrs:
        p, xs = con_pat(c, "x")
        q, ys = con_pat(c, "y")
        body = "EQ"
        for x, y in reversed(list(zip(xs, ys))):
            if body == "EQ":
                body = f"compare {x} {y}"
            else:
                body = f"(case compare {x} {y} of {{ EQ -> {body}; o -> o }})"
        lines.append(f"  compare {p} {q} = {body}")
    if len(d.constrs) > 1:
        lines.append(f"  compare a b = compare {tag_case(d, 'a')} {tag_case(d, 'b')}")
    return lines


def derive_show(d, fixities):
    lines = [head(d, "Show")]
    for c in d.constrs:
        p, xs = con_pat(c, "x")
        name = c.name
        if not xs:
            shown = f"({name})" if is_op(name) else name
            lines.append(f"  showsPrec _ {p} = showString {quote(shown)}")
        elif is_op(name) and len(xs) == 2:
            _, prec = fixities.get(name, ("l", 9))
            body = (f"showsPrec {prec + 1} {xs[0]} . showString {quote(' ' + name + ' ')} . "
                    f"showsPrec {prec + 1} {xs[1]}")
            lines.append(f"  showsPrec d {p} = showParen (d > {prec}) ({body})")
        else:
            parts = [f"showString {quote(name + ' ')}"]
            for i, x in enumerate(xs):
                if i:
                    parts.append("showChar ' '")
                parts.append(f"showsPrec 11 {x}")
            lines.append(f"  showsPrec d {p} = showParen (d > 10) ({' . '.join(parts)})")
    return lines


def derive_enum(d):
    if any(c.fields for c in d.constrs):
        raise CurlewError(f"Enum can only be derived for a type whose constructors have no fields",
                          d.where)
    lines = [head(d, "Enum")]
    for i, c in enumerate(d.constrs):
        lines.append(f"  fromEnum {c.name} = {i}")
    for i, c in enumerate(d.constrs):
        lines.append(f"  toEnum {i} = {c.name}")
    lines.append(f"  toEnum _ = error \"toEnum: out of range for {d.name}\"")
    lines.append(f"  enumFrom x = enumFromTo x {d.constrs[-1].name}")
    return lines


def quote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def derive(decls, fixities):
    """Source text for every instance the data declarations derive."""
    out = []
    for d in decls:
        if not isinstance(d, S.DData):
            continue
        for cls in d.deriving:
            if cls == "Eq":
                out += derive_eq(d)
            elif cls == "Ord":
                out += derive_ord(d)
            elif cls == "Show":
                out += derive_show(d, fixities)
            elif cls == "Enum":
                out += derive_enum(d)
            else:
                raise CurlewError(f"can't derive {cls} (only {', '.join(DERIVABLE)})", d.where)
            out.append("")
    return "\n".join(out) + "\n"
