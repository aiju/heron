"""S-expressions as KiCad writes them: footprints, symbols, boards, and
the Specctra DSN and SES files of autorouters.

parse() gives nested lists of atoms; an atom is a str (quoted strings
unquoted, as Str so a writer can quote them again), an int or a float.
dump() writes them back, one list per line from a given depth.
"""

import re

_TOKEN = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.S)


class Str(str):
    """A string atom that was quoted in the file."""


def _atom(tok):
    try:
        return int(tok)
    except ValueError:
        pass
    try:
        return float(tok)
    except ValueError:
        return tok


def parse(text):
    """The first expression in text, as nested lists."""
    stack, cur = [], None
    pos, n = 0, len(text)
    while pos < n:
        m = _TOKEN.match(text, pos)
        if not m:
            if text[pos:].strip() == "":
                break
            raise ValueError(f"bad s-expression at {pos}: {text[pos:pos + 40]!r}")
        pos = m.end()
        if m.group(1):
            new = []
            if cur is not None:
                cur.append(new)
                stack.append(cur)
            cur = new
        elif m.group(2):
            if not stack:
                return cur
            cur = stack.pop()
        elif m.group(3) is not None:
            cur.append(Str(m.group(3).replace('\\"', '"').replace("\\\\", "\\")))
        else:
            cur.append(_atom(m.group(4)))
    if stack or cur is None:
        raise ValueError("unbalanced s-expression")
    return cur


def load(path):
    with open(path) as f:
        return parse(f.read())


# ---- access ----------------------------------------------------------------

def find(expr, key):
    """The first child list of expr that starts with key, or None."""
    for e in expr:
        if isinstance(e, list) and e and e[0] == key:
            return e
    return None


def find_all(expr, key):
    return [e for e in expr if isinstance(e, list) and e and e[0] == key]


def value(expr, key, default=None):
    """The first value of the child list `key`: (key value ...) -> value."""
    e = find(expr, key)
    return e[1] if e is not None and len(e) > 1 else default


# ---- writing -----------------------------------------------------------------

_BARE = re.compile(r'^[A-Za-z_][A-Za-z0-9_.+\-:/*]*$')


def fmt(atom):
    if isinstance(atom, bool):
        return "yes" if atom else "no"
    if isinstance(atom, float):
        s = f"{atom:.6f}".rstrip("0").rstrip(".")
        return "0" if s in ("-0", "") else s
    if isinstance(atom, int):
        return str(atom)
    if isinstance(atom, Str) or not _BARE.match(atom):
        return '"' + atom.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return atom


def dump(expr, indent=0, flat_depth=2):
    """Text for expr: lists nested deeper than flat_depth below a list that
    holds other lists go on one line each."""
    out = []
    _dump(expr, indent, out, flat_depth)
    return "".join(out)


def _flat(expr):
    return "(" + " ".join(_flat(e) if isinstance(e, list) else fmt(e) for e in expr) + ")"


def _dump(expr, indent, out, flat_depth):
    pad = "\t" * indent
    if flat_depth <= 0 or not any(isinstance(e, list) for e in expr):
        out.append(pad + _flat(expr))
        return
    i = 0
    head = []
    while i < len(expr) and not isinstance(expr[i], list):
        head.append(fmt(expr[i]))
        i += 1
    out.append(pad + "(" + " ".join(head))
    for e in expr[i:]:
        out.append("\n")
        if isinstance(e, list):
            _dump(e, indent + 1, out, flat_depth - 1)
        else:
            out.append("\t" * (indent + 1) + fmt(e))
    out.append("\n" + pad + ")")
