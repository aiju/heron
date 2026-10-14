#!/usr/bin/env python3
"""The reference interpreter for the Lisp of language.md.

An independent implementation of the language in plain Python (standard
library only). It computes the exact bytes each program prints, which the
runtime on the machine must reproduce: programs/expected/NAME.txt and
tests/lisp/expected/NAME.txt. The prelude's macros and procedures are
native here; only their observable behaviour has to match the prelude's.

The console input is the program text itself: the top level reads forms
from it one at a time and evaluates them, and `(read)` reads the next datum
after the form being evaluated. --input-file appends a file's contents to
the console input, after the program.

    python3 studies/lisp/reference.py PROG.lisp [--input-file F]
    python3 studies/lisp/reference.py --write-expected     # every program and test

Choices the spec leaves open, so the machine can match them:

- Whitespace is any byte up to 32 (space and control characters).
- In a string, `\\n` is a newline and `\\` followed by any other byte is
  that byte.
- The reader stops at the first error, leaving the input just after what it
  has read (after the bad token, or the `)` it rejected): an out-of-range
  literal inside a list is `overflow`, then the rest of the list is read as
  top-level forms. In a list, a `.` token makes the next datum the tail
  (`(. x)` is `x`); if the next character after it (past whitespace) isn't
  `)`, that character is consumed and the error is `bad syntax` with no
  irritant. Outside a list, `.` is a symbol.
- A form that isn't a proper list, call or special form, is `bad syntax`
  (the form), found before anything in it is evaluated. Special forms check
  their whole shape first: `(quote x)`, `(if c a [b])`, `(define sym e)`,
  `(set! sym e)`, parameter lists of symbols, `let` bindings of exactly
  `(sym init)`, `cond` clauses that are non-empty lists.
- Bodies may be empty: `(lambda (x))` returns nil.
- `let*` is nested `let`s; `letrec` evaluates and assigns each init in turn.
- `set!` of a variable with no binding and no global value sets the global.
- Arithmetic folds left to right, checking each argument when it gets to it
  and each partial result for overflow: `(+ 1073741823 1 -1)` is `overflow`.
- `not a list` reports the whole list argument. `map` and `for-each` check
  the list first, then apply `f` to the elements in order (so `(map 5 nil)`
  is nil); `for-each` returns nil. `apply` checks `f`, then the list, and
  calls `f` as a tail call. `assq`/`assoc` on an element that isn't a pair:
  `not a pair` (the element). `list-tail` with `k` <= 0 returns the list.
- Errors from `cadr` and the like report the value that wasn't a pair at
  the step that failed.
- `(error msg x...)` displays `msg` whatever its type.
- `write-char` writes the low 8 bits of its argument.
- Macro names have no value as variables. The prelude's macros don't use
  `gensym`, so a program's first `(gensym)` is always `g1`.
- An error line is printed where the output is; no newline is added first.
"""

import os
import re
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))

FIX_MIN = -(1 << 30)
FIX_MAX = (1 << 30) - 1


# --------------------------------------------------------------------------
# Data


class LispError(Exception):
    """An error in the program: `msg` is bytes for the runtime's own errors,
    or the Lisp value given to `error`. `fatal` ends the program."""

    def __init__(self, msg, irritants=(), fatal=False):
        super().__init__(msg)
        self.msg = msg
        self.irritants = list(irritants)
        self.fatal = fatal


class Symbol:
    __slots__ = ("name", "value", "plist", "sf", "macro", "string")

    def __init__(self, name):
        self.name = name          # bytes
        self.value = UNBOUND      # the global value
        self.plist = []           # [[key, value]], for get/put
        self.sf = 0               # special-form code, or 0
        self.macro = None         # a Closure, for defmacro
        self.string = None        # symbol->string's string


class Pair:
    __slots__ = ("car", "cdr")

    def __init__(self, car, cdr):
        self.car = car
        self.cdr = cdr


class LStr:
    """A string: immutable bytes, compared by identity with eq?."""
    __slots__ = ("b",)

    def __init__(self, b):
        self.b = b


class Prim:
    __slots__ = ("name", "fn", "lo", "hi", "kind")

    def __init__(self, name, fn, lo, hi, kind):
        self.name, self.fn, self.lo, self.hi, self.kind = name, fn, lo, hi, kind


class Closure:
    __slots__ = ("params", "rest", "body", "env")

    def __init__(self, params, rest, body, env):
        self.params = params      # tuple of Symbols
        self.rest = rest          # Symbol or None
        self.body = body          # a proper Lisp list of forms
        self.env = env            # a frame (dict) or None for the global scope


class _Unique:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name


UNBOUND = _Unique("UNBOUND")
MISSING = _Unique("MISSING")
END = _Unique("END")              # the top level's end of input
EOF = _Unique("EOF")              # the end-of-file object

# Environments: a frame is a dict {Symbol: value}, with its parent frame
# under the key None; the global scope is None (values live in Symbol.value).

(IF, QUOTE, DEFINE, SET, LAMBDA, BEGIN, LET, LETSTAR, LETREC, COND, AND, OR,
 DEFMACRO, QUASIQUOTE, WHEN, UNLESS, DO, CASE) = range(1, 19)

SPECIAL = {b"if": IF, b"quote": QUOTE, b"define": DEFINE, b"set!": SET,
           b"lambda": LAMBDA, b"begin": BEGIN, b"let": LET, b"let*": LETSTAR,
           b"letrec": LETREC, b"cond": COND, b"and": AND, b"or": OR,
           b"defmacro": DEFMACRO,
           # the prelude's macros, native here
           b"quasiquote": QUASIQUOTE, b"when": WHEN, b"unless": UNLESS,
           b"do": DO, b"case": CASE}

SYMTAB = {}


def intern(name):
    s = SYMTAB.get(name)
    if s is None:
        s = SYMTAB[name] = Symbol(name)
        s.sf = SPECIAL.get(name, 0)
    return s


T = intern(b"t")
S_QUOTE = intern(b"quote")
S_QUASIQUOTE = intern(b"quasiquote")
S_UNQUOTE = intern(b"unquote")
S_UNQUOTE_SPLICING = intern(b"unquote-splicing")


def pylist(items, tail=None):
    """A Lisp list of a Python sequence."""
    r = tail
    for v in reversed(items):
        r = Pair(v, r)
    return r


def to_py(x):
    """A proper Lisp list as a Python list, or None if it isn't one."""
    out = []
    while type(x) is Pair:
        out.append(x.car)
        x = x.cdr
    return out if x is None else None


def proper(x):
    while type(x) is Pair:
        x = x.cdr
    return x is None


def eq(a, b):
    return a is b or (type(a) is int and type(b) is int and a == b)


def equal(a, b):
    while True:
        if a is b or (type(a) is int and type(b) is int and a == b):
            return True
        ta = type(a)
        if ta is not type(b):
            return False
        if ta is Pair:
            if not equal(a.car, b.car):
                return False
            a, b = a.cdr, b.cdr
            continue
        if ta is LStr:
            return a.b == b.b
        return False


def is_proc(x):
    t = type(x)
    return t is Prim or t is Closure


# --------------------------------------------------------------------------
# Per-run state


class State:
    out = bytearray()
    reader = None
    gensyms = 0


def reset(text):
    for name, s in SYMTAB.items():
        s.value = UNBOUND
        s.plist = []
        s.macro = None
        s.sf = SPECIAL.get(name, 0)
    T.value = T
    for name, p in PRIMS.items():
        intern(name).value = p
    State.out = bytearray()
    State.reader = Reader(text)
    State.gensyms = 0


# --------------------------------------------------------------------------
# The reader

DELIM = frozenset(b"()'`,\";")
INT_RE = re.compile(rb"[+-]?[0-9]+")


def eoi():
    return LispError(b"unexpected end of input", fatal=True)


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def skip(self):
        """Skip whitespace and comments; False at the end of the input."""
        d, p, n = self.data, self.pos, len(self.data)
        while p < n:
            c = d[p]
            if c <= 32:
                p += 1
            elif c == 59:  # ;
                while p < n and d[p] != 10:
                    p += 1
            else:
                break
        self.pos = p
        return p < n

    def read_top(self):
        """The next form for the top level, or END."""
        if not self.skip():
            return END
        return self.datum()

    def read(self):
        """(read): the next datum, or the end-of-file object."""
        if not self.skip():
            return EOF
        return self.datum()

    def need(self):
        if not self.skip():
            raise eoi()
        return self.datum()

    def datum(self):
        d = self.data
        p = self.pos
        c = d[p]
        if c == 40:  # (
            self.pos = p + 1
            return self.read_list()
        if c == 41:  # )
            self.pos = p + 1
            raise LispError(b"unexpected )")
        if c == 39:  # '
            self.pos = p + 1
            return Pair(S_QUOTE, Pair(self.need(), None))
        if c == 96:  # `
            self.pos = p + 1
            return Pair(S_QUASIQUOTE, Pair(self.need(), None))
        if c == 44:  # ,
            if p + 1 < len(d) and d[p + 1] == 64:  # ,@
                self.pos = p + 2
                return Pair(S_UNQUOTE_SPLICING, Pair(self.need(), None))
            self.pos = p + 1
            return Pair(S_UNQUOTE, Pair(self.need(), None))
        if c == 34:  # "
            return self.read_string()
        return self.read_token()

    def is_dot(self):
        d, p = self.data, self.pos
        if d[p] != 46:
            return False
        return p + 1 >= len(d) or d[p + 1] <= 32 or d[p + 1] in DELIM

    def read_list(self):
        items = []
        tail = None
        d = self.data
        while True:
            if not self.skip():
                raise eoi()
            if d[self.pos] == 41:
                self.pos += 1
                break
            if self.is_dot():
                self.pos += 1
                tail = self.need()
                if not self.skip():
                    raise eoi()
                self.pos += 1
                if d[self.pos - 1] != 41:
                    raise LispError(b"bad syntax")
                break
            items.append(self.datum())
        return pylist(items, tail)

    def read_string(self):
        d, p, n = self.data, self.pos + 1, len(self.data)
        buf = bytearray()
        while True:
            if p >= n:
                self.pos = p
                raise eoi()
            c = d[p]
            p += 1
            if c == 34:
                break
            if c == 92:  # backslash
                if p >= n:
                    self.pos = p
                    raise eoi()
                c = d[p]
                p += 1
                if c == 110:
                    c = 10
            buf.append(c)
        self.pos = p
        return LStr(bytes(buf))

    def read_token(self):
        d, p, n = self.data, self.pos, len(self.data)
        start = p
        while p < n and d[p] > 32 and d[p] not in DELIM:
            p += 1
        self.pos = p
        tok = d[start:p]
        if INT_RE.fullmatch(tok):
            digits = tok.lstrip(b"+-").lstrip(b"0")
            if len(digits) > 10:
                raise LispError(b"overflow")
            v = int(tok)
            if v < FIX_MIN or v > FIX_MAX:
                raise LispError(b"overflow")
            return v
        if tok == b"nil":
            return None
        return intern(tok)


# --------------------------------------------------------------------------
# The printer


def escape(b):
    return b.replace(b"\\", b"\\\\").replace(b'"', b'\\"').replace(b"\n", b"\\n")


def pr(x, write, out):
    t = type(x)
    if t is int:
        out += str(x).encode()
    elif x is None:
        out += b"nil"
    elif t is Symbol:
        out += x.name
    elif t is Pair:
        out += b"("
        pr(x.car, write, out)
        x = x.cdr
        while type(x) is Pair:
            out += b" "
            pr(x.car, write, out)
            x = x.cdr
        if x is not None:
            out += b" . "
            pr(x, write, out)
        out += b")"
    elif t is LStr:
        if write:
            out += b'"' + escape(x.b) + b'"'
        else:
            out += x.b
    elif t is list:
        out += b"#("
        for i, v in enumerate(x):
            if i:
                out += b" "
            pr(v, write, out)
        out += b")"
    elif t is Prim or t is Closure:
        out += b"#<procedure>"
    elif x is EOF:
        out += b"#<eof>"
    else:
        raise AssertionError(f"can't print {x!r}")


def to_bytes(x, write=True):
    out = bytearray()
    pr(x, write, out)
    return bytes(out)


def error_line(e):
    out = bytearray(b"error: ")
    if isinstance(e.msg, bytes):
        out += e.msg
    else:
        pr(e.msg, False, out)
    if e.irritants:
        out += b": "
        for i, v in enumerate(e.irritants):
            if i:
                out += b" "
            pr(v, True, out)
    out += b"\n"
    return bytes(out)


# --------------------------------------------------------------------------
# The evaluator


def bad(form):
    return LispError(b"bad syntax", [form])


def make_closure(params, body, env, form):
    ps = []
    p = params
    while type(p) is Pair:
        s = p.car
        if type(s) is not Symbol:
            raise bad(form)
        ps.append(s)
        p = p.cdr
    if p is not None and type(p) is not Symbol:
        raise bad(form)
    if not proper(body):
        raise bad(form)
    return Closure(tuple(ps), p, body, env)


def bindings(b, form):
    """A let's binding list: ([var], [init])."""
    vs, inits = [], []
    while type(b) is Pair:
        e = b.car
        if (type(e) is not Pair or type(e.car) is not Symbol or type(e.cdr) is not Pair
                or e.cdr.cdr is not None):
            raise bad(form)
        vs.append(e.car)
        inits.append(e.cdr.car)
        b = b.cdr
    if b is not None:
        raise bad(form)
    return vs, inits


def bind(f, args):
    params = f.params
    n = len(params)
    if f.rest is None:
        if len(args) != n:
            raise LispError(b"wrong number of arguments")
        env = dict(zip(params, args))
    else:
        if len(args) < n:
            raise LispError(b"wrong number of arguments")
        env = dict(zip(params, args))
        env[f.rest] = pylist(args[n:])
    env[None] = f.env
    return env


def eval_body(body, env):
    if body is None:
        return None
    while body.cdr is not None:
        ev(body.car, env)
        body = body.cdr
    return ev(body.car, env)


def apply_proc(f, args):
    """Apply f to a Python list of arguments (not a tail call)."""
    while True:
        tf = type(f)
        if tf is Closure:
            return eval_body(f.body, bind(f, args))
        if tf is Prim:
            n = len(args)
            if n < f.lo or (f.hi >= 0 and n > f.hi):
                raise LispError(b"wrong number of arguments")
            k = f.kind
            if k == 0:
                return f.fn(*args)
            if k == 1:
                f, args = apply_args(args)
                continue
            return ev(args[0], None)
        raise LispError(b"not a procedure", [f])


def apply_args(args):
    g, lst = args
    if not is_proc(g):
        raise LispError(b"not a procedure", [g])
    a = to_py(lst)
    if a is None:
        raise LispError(b"not a list", [lst])
    return g, a


def macro_args(x, lo, hi):
    """The operands of a prelude macro call, checked like a lambda's."""
    a = to_py(x.cdr)
    if a is None:
        raise bad(x)
    if len(a) < lo or (hi >= 0 and len(a) > hi):
        raise LispError(b"wrong number of arguments")
    return a


def qq(x):
    """The expansion of `x: conses, appends and quotes."""
    if type(x) is not Pair:
        return Pair(S_QUOTE, Pair(x, None))
    a = x.car
    if a is S_UNQUOTE:
        return car(cdr(x))
    if type(a) is Pair and a.car is S_UNQUOTE_SPLICING:
        return Pair(P_APPEND, Pair(car(cdr(a)), Pair(qq(x.cdr), None)))
    return Pair(P_CONS, Pair(qq(a), Pair(qq(x.cdr), None)))


def ev(x, env):
    while True:
        tx = type(x)
        if tx is Symbol:
            e = env
            while e is not None:
                if x in e:
                    return e[x]
                e = e[None]
            v = x.value
            if v is UNBOUND:
                raise LispError(b"unbound variable", [x])
            return v
        if tx is not Pair:
            return x
        op = x.car
        if type(op) is Symbol:
            code = op.sf
            if code:
                if code == IF:
                    r = x.cdr
                    if type(r) is Pair:
                        r2 = r.cdr
                        if type(r2) is Pair:
                            r3 = r2.cdr
                            if r3 is None:
                                if ev(r.car, env) is not None:
                                    x = r2.car
                                    continue
                                return None
                            if type(r3) is Pair and r3.cdr is None:
                                x = r2.car if ev(r.car, env) is not None else r3.car
                                continue
                    raise bad(x)
                if code == QUOTE:
                    r = x.cdr
                    if type(r) is not Pair or r.cdr is not None:
                        raise bad(x)
                    return r.car
                if code == COND:
                    r = x.cdr
                    c = r
                    while type(c) is Pair:
                        cl = c.car
                        if type(cl) is not Pair or not proper(cl):
                            raise bad(x)
                        c = c.cdr
                    if c is not None:
                        raise bad(x)
                    while r is not None:
                        cl = r.car
                        v = ev(cl.car, env)
                        if v is not None:
                            break
                        r = r.cdr
                    else:
                        return None
                    body = cl.cdr
                    if body is None:
                        return v
                    while body.cdr is not None:
                        ev(body.car, env)
                        body = body.cdr
                    x = body.car
                    continue
                if code == LET:
                    r = x.cdr
                    if type(r) is not Pair:
                        raise bad(x)
                    b = r.car
                    if type(b) is Symbol:
                        # named let
                        name = b
                        r = r.cdr
                        if type(r) is not Pair:
                            raise bad(x)
                        vs, inits = bindings(r.car, x)
                        body = r.cdr
                        if not proper(body):
                            raise bad(x)
                        outer = {None: env}
                        clo = Closure(tuple(vs), None, body, outer)
                        outer[name] = clo
                        new = {None: outer}
                        for v, i in zip(vs, inits):
                            new[v] = ev(i, env)
                    else:
                        vs, inits = bindings(b, x)
                        body = r.cdr
                        if not proper(body):
                            raise bad(x)
                        new = {None: env}
                        for v, i in zip(vs, inits):
                            new[v] = ev(i, env)
                    env = new
                    if body is None:
                        return None
                    while body.cdr is not None:
                        ev(body.car, env)
                        body = body.cdr
                    x = body.car
                    continue
                if code == BEGIN:
                    body = x.cdr
                    if not proper(body):
                        raise bad(x)
                    if body is None:
                        return None
                    while body.cdr is not None:
                        ev(body.car, env)
                        body = body.cdr
                    x = body.car
                    continue
                if code == AND:
                    r = x.cdr
                    if not proper(r):
                        raise bad(x)
                    if r is None:
                        return T
                    while r.cdr is not None:
                        if ev(r.car, env) is None:
                            return None
                        r = r.cdr
                    x = r.car
                    continue
                if code == OR:
                    r = x.cdr
                    if not proper(r):
                        raise bad(x)
                    if r is None:
                        return None
                    while r.cdr is not None:
                        v = ev(r.car, env)
                        if v is not None:
                            return v
                        r = r.cdr
                    x = r.car
                    continue
                if code == LAMBDA:
                    r = x.cdr
                    if type(r) is not Pair:
                        raise bad(x)
                    return make_closure(r.car, r.cdr, env, x)
                if code == SET:
                    r = x.cdr
                    if type(r) is not Pair or type(r.car) is not Symbol:
                        raise bad(x)
                    r2 = r.cdr
                    if type(r2) is not Pair or r2.cdr is not None:
                        raise bad(x)
                    s = r.car
                    v = ev(r2.car, env)
                    e = env
                    while e is not None:
                        if s in e:
                            e[s] = v
                            return v
                        e = e[None]
                    s.value = v
                    return v
                if code == DEFINE:
                    r = x.cdr
                    if type(r) is not Pair:
                        raise bad(x)
                    target = r.car
                    if type(target) is Symbol:
                        r2 = r.cdr
                        if type(r2) is not Pair or r2.cdr is not None:
                            raise bad(x)
                        target.value = ev(r2.car, env)
                        return target
                    if type(target) is Pair and type(target.car) is Symbol:
                        target.car.value = make_closure(target.cdr, r.cdr, env, x)
                        return target.car
                    raise bad(x)
                if code == LETSTAR:
                    r = x.cdr
                    if type(r) is not Pair:
                        raise bad(x)
                    vs, inits = bindings(r.car, x)
                    body = r.cdr
                    if not proper(body):
                        raise bad(x)
                    for v, i in zip(vs, inits):
                        env = {None: env, v: ev(i, env)}
                    if body is None:
                        return None
                    while body.cdr is not None:
                        ev(body.car, env)
                        body = body.cdr
                    x = body.car
                    continue
                if code == LETREC:
                    r = x.cdr
                    if type(r) is not Pair:
                        raise bad(x)
                    vs, inits = bindings(r.car, x)
                    body = r.cdr
                    if not proper(body):
                        raise bad(x)
                    new = {None: env}
                    for v in vs:
                        new[v] = None
                    env = new
                    for v, i in zip(vs, inits):
                        new[v] = ev(i, new)
                    if body is None:
                        return None
                    while body.cdr is not None:
                        ev(body.car, env)
                        body = body.cdr
                    x = body.car
                    continue
                if code == DEFMACRO:
                    r = x.cdr
                    if type(r) is not Pair or type(r.car) is not Symbol or type(r.cdr) is not Pair:
                        raise bad(x)
                    name = r.car
                    name.macro = make_closure(r.cdr.car, r.cdr.cdr, env, x)
                    name.sf = 0
                    return name
                if code == QUASIQUOTE:
                    a = macro_args(x, 1, 1)
                    x = qq(a[0])
                    continue
                if code == WHEN or code == UNLESS:
                    a = macro_args(x, 1, -1)
                    if (ev(a[0], env) is None) == (code == WHEN):
                        return None
                    body = x.cdr.cdr
                    if body is None:
                        return None
                    while body.cdr is not None:
                        ev(body.car, env)
                        body = body.cdr
                    x = body.car
                    continue
                if code == DO:
                    a = macro_args(x, 2, -1)
                    specs = to_py(a[0])
                    if specs is None:
                        raise bad(x)
                    vs, inits, steps = [], [], []
                    for s in specs:
                        sl = to_py(s)
                        if sl is None or len(sl) not in (2, 3) or type(sl[0]) is not Symbol:
                            raise bad(x)
                        vs.append(sl[0])
                        inits.append(sl[1])
                        steps.append(sl[2] if len(sl) == 3 else sl[0])
                    test = a[1]
                    if type(test) is not Pair or not proper(test):
                        raise bad(x)
                    body = x.cdr.cdr.cdr
                    vals = [ev(i, env) for i in inits]
                    while True:
                        frame = dict(zip(vs, vals))
                        frame[None] = env
                        if ev(test.car, frame) is not None:
                            break
                        b = body
                        while b is not None:
                            ev(b.car, frame)
                            b = b.cdr
                        vals = [ev(s, frame) for s in steps]
                    env = frame
                    body = test.cdr
                    if body is None:
                        return None
                    while body.cdr is not None:
                        ev(body.car, env)
                        body = body.cdr
                    x = body.car
                    continue
                if code == CASE:
                    a = macro_args(x, 1, -1)
                    for cl in a[1:]:
                        if (type(cl) is not Pair or not proper(cl)
                                or (cl.car is not T and not proper(cl.car))):
                            raise bad(x)
                    k = ev(a[0], env)
                    for cl in a[1:]:
                        data = cl.car
                        if data is T:
                            break
                        while data is not None:
                            if eq(k, data.car):
                                break
                            data = data.cdr
                        else:
                            continue
                        break
                    else:
                        return None
                    body = cl.cdr
                    if body is None:
                        return None
                    while body.cdr is not None:
                        ev(body.car, env)
                        body = body.cdr
                    x = body.car
                    continue
                raise AssertionError(code)
            m = op.macro
            if m is not None:
                a = to_py(x.cdr)
                if a is None:
                    raise bad(x)
                x = apply_proc(m, a)
                continue
        # a call
        r = x.cdr
        a = r
        while type(a) is Pair:
            a = a.cdr
        if a is not None:
            raise bad(x)
        if type(op) is Symbol:  # inline: the operator is usually a variable
            e = env
            while e is not None:
                if op in e:
                    f = e[op]
                    break
                e = e[None]
            else:
                f = op.value
                if f is UNBOUND:
                    raise LispError(b"unbound variable", [op])
        else:
            f = ev(op, env)
        args = []
        while r is not None:
            a = r.car
            ta = type(a)
            if ta is Symbol:  # inline variable lookup, the commonest operand
                e = env
                while e is not None:
                    if a in e:
                        args.append(e[a])
                        break
                    e = e[None]
                else:
                    v = a.value
                    if v is UNBOUND:
                        raise LispError(b"unbound variable", [a])
                    args.append(v)
            elif ta is Pair:
                args.append(ev(a, env))
            else:
                args.append(a)
            r = r.cdr
        while True:
            tf = type(f)
            if tf is Closure:
                params = f.params
                n = len(params)
                if f.rest is None:
                    if len(args) != n:
                        raise LispError(b"wrong number of arguments")
                    if n == 1:
                        env = {params[0]: args[0], None: f.env}
                    elif n == 2:
                        env = {params[0]: args[0], params[1]: args[1], None: f.env}
                    elif n == 3:
                        env = {params[0]: args[0], params[1]: args[1], params[2]: args[2], None: f.env}
                    else:
                        env = dict(zip(params, args))
                        env[None] = f.env
                else:
                    if len(args) < n:
                        raise LispError(b"wrong number of arguments")
                    env = dict(zip(params, args))
                    env[f.rest] = pylist(args[n:])
                    env[None] = f.env
                body = f.body
                if body is None:
                    return None
                while body.cdr is not None:
                    ev(body.car, env)
                    body = body.cdr
                x = body.car
                break
            if tf is Prim:
                n = len(args)
                if n < f.lo or (f.hi >= 0 and n > f.hi):
                    raise LispError(b"wrong number of arguments")
                k = f.kind
                if k == 0:
                    return f.fn(*args)
                if k == 1:
                    f, args = apply_args(args)
                    continue
                x = args[0]
                env = None
                break
            raise LispError(b"not a procedure", [f])


# --------------------------------------------------------------------------
# Primitives

PRIMS = {}


def prim(name, lo, hi=None, kind=0):
    def deco(fn):
        PRIMS[name.encode()] = Prim(name, fn, lo, lo if hi is None else hi, kind)
        return fn
    return deco


def num(x):
    if type(x) is not int:
        raise LispError(b"not a number", [x])
    return x


def fix(v):
    if v < FIX_MIN or v > FIX_MAX:
        raise LispError(b"overflow")
    return v


def lstr(x):
    if type(x) is not LStr:
        raise LispError(b"not a string", [x])
    return x.b


def sym(x):
    if type(x) is not Symbol:
        raise LispError(b"not a symbol", [x])
    return x


def vec(x):
    if type(x) is not list:
        raise LispError(b"not a vector", [x])
    return x


def truth(b):
    return T if b else None


# Pairs and lists

@prim("cons", 2)
def p_cons(a, b):
    return Pair(a, b)


@prim("car", 1)
def car(x):
    if type(x) is not Pair:
        raise LispError(b"not a pair", [x])
    return x.car


@prim("cdr", 1)
def cdr(x):
    if type(x) is not Pair:
        raise LispError(b"not a pair", [x])
    return x.cdr


@prim("set-car!", 2)
def p_set_car(p, x):
    if type(p) is not Pair:
        raise LispError(b"not a pair", [p])
    p.car = x
    return x


@prim("set-cdr!", 2)
def p_set_cdr(p, x):
    if type(p) is not Pair:
        raise LispError(b"not a pair", [p])
    p.cdr = x
    return x


def _compose(name):
    ops = name[1:-1][::-1]  # applied right to left: cadr is car of cdr

    def fn(x):
        for o in ops:
            x = car(x) if o == "a" else cdr(x)
        return x
    prim(name, 1)(fn)


for _n in ("caar", "cadr", "cdar", "cddr", "caddr", "cdddr", "cadddr"):
    _compose(_n)


@prim("list", 0, -1)
def p_list(*a):
    return pylist(a)


@prim("length", 1)
def p_length(lst):
    n = 0
    x = lst
    while type(x) is Pair:
        n += 1
        x = x.cdr
    if x is not None:
        raise LispError(b"not a list", [lst])
    return n


@prim("append", 0, -1)
def p_append(*ls):
    if not ls:
        return None
    items = []
    for lst in ls[:-1]:
        x = lst
        while type(x) is Pair:
            items.append(x.car)
            x = x.cdr
        if x is not None:
            raise LispError(b"not a list", [lst])
    return pylist(items, ls[-1])


@prim("reverse", 1)
def p_reverse(lst):
    r = None
    x = lst
    while type(x) is Pair:
        r = Pair(x.car, r)
        x = x.cdr
    if x is not None:
        raise LispError(b"not a list", [lst])
    return r


@prim("list-tail", 2)
def p_list_tail(lst, k):
    num(k)
    while k > 0:
        if type(lst) is not Pair:
            raise LispError(b"not a pair", [lst])
        lst = lst.cdr
        k -= 1
    return lst


@prim("list-ref", 2)
def p_list_ref(lst, k):
    return car(p_list_tail(lst, k))


@prim("last-pair", 1)
def p_last_pair(lst):
    if type(lst) is not Pair:
        raise LispError(b"not a pair", [lst])
    while type(lst.cdr) is Pair:
        lst = lst.cdr
    return lst


def _mem(same):
    def fn(a, lst):
        x = lst
        while type(x) is Pair:
            if same(a, x.car):
                return x
            x = x.cdr
        if x is not None:
            raise LispError(b"not a list", [lst])
        return None
    return fn


def _ass(same):
    def fn(a, al):
        x = al
        while type(x) is Pair:
            e = x.car
            if type(e) is not Pair:
                raise LispError(b"not a pair", [e])
            if same(a, e.car):
                return e
            x = x.cdr
        if x is not None:
            raise LispError(b"not a list", [al])
        return None
    return fn


prim("memq", 2)(_mem(eq))
prim("member", 2)(_mem(equal))
prim("assq", 2)(_ass(eq))
prim("assoc", 2)(_ass(equal))


@prim("map", 2)
def p_map(f, lst):
    items = to_py(lst)
    if items is None:
        raise LispError(b"not a list", [lst])
    return pylist([apply_proc(f, [v]) for v in items])


@prim("for-each", 2)
def p_for_each(f, lst):
    items = to_py(lst)
    if items is None:
        raise LispError(b"not a list", [lst])
    for v in items:
        apply_proc(f, [v])
    return None


# Predicates and equality

prim("eq?", 2)(lambda a, b: truth(eq(a, b)))
prim("equal?", 2)(lambda a, b: truth(equal(a, b)))
prim("not", 1)(lambda x: truth(x is None))
prim("null?", 1)(lambda x: truth(x is None))
prim("pair?", 1)(lambda x: truth(type(x) is Pair))
prim("atom?", 1)(lambda x: truth(type(x) is not Pair))
prim("symbol?", 1)(lambda x: truth(type(x) is Symbol))
prim("number?", 1)(lambda x: truth(type(x) is int))
prim("integer?", 1)(lambda x: truth(type(x) is int))
prim("string?", 1)(lambda x: truth(type(x) is LStr))
prim("vector?", 1)(lambda x: truth(type(x) is list))
prim("procedure?", 1)(lambda x: truth(is_proc(x)))
prim("list?", 1)(lambda x: truth(proper(x)))
prim("eof-object?", 1)(lambda x: truth(x is EOF))


# Arithmetic

@prim("+", 0, -1)
def p_add(*a):
    if len(a) == 2:
        x, y = a
        if type(x) is not int:
            raise LispError(b"not a number", [x])
        if type(y) is not int:
            raise LispError(b"not a number", [y])
        s = x + y
        if s < FIX_MIN or s > FIX_MAX:
            raise LispError(b"overflow")
        return s
    s = 0
    for v in a:
        if type(v) is not int:
            raise LispError(b"not a number", [v])
        s += v
        if s < FIX_MIN or s > FIX_MAX:
            raise LispError(b"overflow")
    return s


@prim("*", 0, -1)
def p_mul(*a):
    s = 1
    for v in a:
        if type(v) is not int:
            raise LispError(b"not a number", [v])
        s *= v
        if s < FIX_MIN or s > FIX_MAX:
            raise LispError(b"overflow")
    return s


@prim("-", 1, -1)
def p_sub(n, *a):
    num(n)
    if len(a) == 1:
        y = a[0]
        if type(y) is not int:
            raise LispError(b"not a number", [y])
        s = n - y
        if s < FIX_MIN or s > FIX_MAX:
            raise LispError(b"overflow")
        return s
    if not a:
        return fix(-n)
    s = n
    for v in a:
        if type(v) is not int:
            raise LispError(b"not a number", [v])
        s -= v
        if s < FIX_MIN or s > FIX_MAX:
            raise LispError(b"overflow")
    return s


def _divide(n, m):
    num(n)
    num(m)
    if m == 0:
        raise LispError(b"division by zero")
    q = abs(n) // abs(m)
    return -q if (n < 0) != (m < 0) else q


@prim("quotient", 2)
def p_quotient(n, m):
    return fix(_divide(n, m))


@prim("remainder", 2)
def p_remainder(n, m):
    q = _divide(n, m)
    return n - m * q


@prim("modulo", 2)
def p_modulo(n, m):
    num(n)
    num(m)
    if m == 0:
        raise LispError(b"division by zero")
    return n % m  # Python's % takes the sign of m


@prim("=", 2)
def p_num_eq(a, b):
    if type(a) is not int:
        raise LispError(b"not a number", [a])
    if type(b) is not int:
        raise LispError(b"not a number", [b])
    return T if a == b else None


@prim("<", 2)
def p_lt(a, b):
    if type(a) is not int:
        raise LispError(b"not a number", [a])
    if type(b) is not int:
        raise LispError(b"not a number", [b])
    return T if a < b else None


@prim(">", 2)
def p_gt(a, b):
    if type(a) is not int:
        raise LispError(b"not a number", [a])
    if type(b) is not int:
        raise LispError(b"not a number", [b])
    return T if a > b else None


@prim("<=", 2)
def p_le(a, b):
    if type(a) is not int:
        raise LispError(b"not a number", [a])
    if type(b) is not int:
        raise LispError(b"not a number", [b])
    return T if a <= b else None


@prim(">=", 2)
def p_ge(a, b):
    if type(a) is not int:
        raise LispError(b"not a number", [a])
    if type(b) is not int:
        raise LispError(b"not a number", [b])
    return T if a >= b else None


prim("zero?", 1)(lambda n: truth(num(n) == 0))
prim("abs", 1)(lambda n: fix(abs(num(n))))
prim("min", 2)(lambda a, b: min(num(a), num(b)))
prim("max", 2)(lambda a, b: max(num(a), num(b)))
# Python's bitwise operators on negative ints act on two's complement, so
# results of in-range operands stay in range.
prim("logand", 2)(lambda a, b: num(a) & num(b))
prim("logior", 2)(lambda a, b: num(a) | num(b))
prim("logxor", 2)(lambda a, b: num(a) ^ num(b))


@prim("ash", 2)
def p_ash(n, k):
    num(n)
    num(k)
    if k >= 0:
        if n == 0:
            return 0
        if k > 31:
            raise LispError(b"overflow")
        return fix(n << k)
    if k < -31:
        k = -31
    return n >> -k


# Symbols and strings

@prim("gensym", 0)
def p_gensym():
    State.gensyms += 1
    return Symbol(b"g%d" % State.gensyms)


@prim("symbol->string", 1)
def p_symbol_string(s):
    sym(s)
    if s.string is None:
        s.string = LStr(s.name)
    return s.string


@prim("string->symbol", 1)
def p_string_symbol(s):
    return intern(lstr(s))


@prim("string-length", 1)
def p_string_length(s):
    return len(lstr(s))


@prim("string-ref", 2)
def p_string_ref(s, k):
    b = lstr(s)
    num(k)
    if not 0 <= k < len(b):
        raise LispError(b"index out of range", [k])
    return b[k]


@prim("string=?", 2)
def p_string_eq(a, b):
    return truth(lstr(a) == lstr(b))


@prim("get", 2)
def p_get(s, key):
    for e in sym(s).plist:
        if eq(e[0], key):
            return e[1]
    return None


@prim("put", 3)
def p_put(s, key, value):
    for e in sym(s).plist:
        if eq(e[0], key):
            e[1] = value
            return value
    s.plist.append([key, value])
    return value


# Vectors

@prim("make-vector", 2)
def p_make_vector(n, fill):
    num(n)
    if n < 0:
        raise LispError(b"index out of range", [n])
    return [fill] * n


@prim("vector-ref", 2)
def p_vector_ref(v, k):
    vec(v)
    num(k)
    if not 0 <= k < len(v):
        raise LispError(b"index out of range", [k])
    return v[k]


@prim("vector-set!", 3)
def p_vector_set(v, k, x):
    vec(v)
    num(k)
    if not 0 <= k < len(v):
        raise LispError(b"index out of range", [k])
    v[k] = x
    return x


@prim("vector-length", 1)
def p_vector_length(v):
    return len(vec(v))


# Control and the system

prim("apply", 2, kind=1)(None)
prim("eval", 1, kind=2)(None)


@prim("error", 1, -1)
def p_error(msg, *irritants):
    raise LispError(msg, irritants)


@prim("read", 0)
def p_read():
    return State.reader.read()


@prim("write", 1)
def p_write(x):
    pr(x, True, State.out)
    return None


@prim("display", 1)
def p_display(x):
    pr(x, False, State.out)
    return None


@prim("newline", 0)
def p_newline():
    State.out.append(10)
    return None


@prim("write-char", 1)
def p_write_char(n):
    State.out.append(num(n) & 255)
    return None


@prim("gc", 0)
def p_gc():
    return None


P_CONS = PRIMS[b"cons"]
P_APPEND = PRIMS[b"append"]


# --------------------------------------------------------------------------
# The top level


def _run(text):
    reset(text)
    reader = State.reader
    out = State.out
    while True:
        try:
            x = reader.read_top()
            if x is END:
                break
            ev(x, None)
        except LispError as e:
            out += error_line(e)
            if e.fatal:
                break
    return bytes(out)


def run(text: bytes) -> bytes:
    """Run a program (the whole console input) and return what it prints."""
    if isinstance(text, str):
        text = text.encode()
    result = []

    def go():
        try:
            result.append(_run(text))
        except BaseException as e:  # noqa: BLE001  (handed to the caller)
            result.append(e)

    sys.setrecursionlimit(max(sys.getrecursionlimit(), 200000))
    old = threading.stack_size(256 * 1024 * 1024)
    try:
        t = threading.Thread(target=go)
        t.start()
    finally:
        threading.stack_size(old)
    t.join()
    if isinstance(result[0], BaseException):
        raise result[0]
    return result[0]


DIRS = [os.path.join(HERE, "programs"), os.path.join(HERE, "tests", "lisp")]


def programs():
    """Every program with an expected output: [(path, expected path)]."""
    out = []
    for d in DIRS:
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith(".lisp"):
                    out.append((os.path.join(d, f), os.path.join(d, "expected", f[:-5] + ".txt")))
    return out


def write_expected():
    for path, exp in programs():
        with open(path, "rb") as f:
            text = f.read()
        t0 = time.time()
        out = run(text)
        dt = time.time() - t0
        os.makedirs(os.path.dirname(exp), exist_ok=True)
        with open(exp, "wb") as f:
            f.write(out)
        print(f"wrote {os.path.relpath(exp)} ({len(out)} bytes, {dt:.2f} s)", file=sys.stderr)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    usage = "usage: reference.py PROG.lisp [--input-file F] | --write-expected"
    if argv and argv[0] in ("-h", "--help"):
        print(usage)
        return 0
    if argv == ["--write-expected"]:
        write_expected()
        return 0
    prog, extra = None, b""
    i = 0
    while i < len(argv):
        if argv[i] == "--input-file" and i + 1 < len(argv):
            with open(argv[i + 1], "rb") as f:
                extra = f.read()
            i += 2
        elif prog is None and not argv[i].startswith("--"):
            prog = argv[i]
            i += 1
        else:
            prog = None
            break
    if prog is None:
        print(usage, file=sys.stderr)
        return 2
    with open(prog, "rb") as f:
        text = f.read()
    sys.stdout.buffer.write(run(text + extra))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
