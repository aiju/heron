"""C preprocessor: #include, #define (object- and function-like, # and ##,
variadic), #undef, conditionals, #error, and macro expansion with hide sets
(Prosser's algorithm, as in Dave Prosser's C89 notes and chibicc)."""

import os

from .lex import Token, CompileError, tokenize, unescape

INCLUDE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "include")


class Macro:
    def __init__(self, name, body, params=None, variadic=False, builtin=None):
        self.name = name
        self.body = body
        self.params = params          # None for object-like
        self.variadic = variadic
        self.builtin = builtin


class Preprocessor:
    def __init__(self, include_paths=(), defines=None):
        self.include_paths = list(include_paths) + [INCLUDE_DIR]
        self.macros = {}
        self.cond = []                # stack of [included, any_taken, in_else]
        self.once = set()
        self.depth = 0
        for name in ("__FILE__", "__LINE__"):
            self.macros[name] = Macro(name, [], builtin=name)
        for k, v in (defines or {}).items():
            self.define_text(k, v)

    def define_text(self, name, value="1"):
        body = tokenize(str(value), "<command line>")[:-1]
        self.macros[name] = Macro(name, body)

    # ---- entry ----------------------------------------------------------

    def run_file(self, path):
        with open(path, encoding="latin-1") as f:
            text = f.read()
        return self.run(text, path)

    def run(self, text, filename):
        toks = tokenize(text, filename)
        self.stack = list(reversed(toks))   # input, next token at the end
        out = []
        while True:
            tok = self.next()
            if tok.kind == "eof":
                if tok.text == "<end-of-include>":
                    self.depth -= 1
                    continue
                break
            if tok.kind == "punct" and tok.text == "#" and tok.bol and tok.origin is None:
                self.directive(tok)
                continue
            if self.expand(tok):
                continue
            out.append(tok)
        if self.cond:
            raise CompileError("unterminated #if", tok)
        out.append(tok)
        return out

    def next(self):
        return self.stack.pop()

    def peek(self):
        return self.stack[-1]

    def push(self, toks):
        self.stack.extend(reversed(toks))

    def line_tokens(self):
        """The rest of the current line."""
        out = []
        while not self.peek().bol and self.peek().kind != "eof":
            out.append(self.next())
        return out

    # ---- directives -----------------------------------------------------

    def directive(self, hash_tok):
        tok = self.peek()
        if tok.bol or tok.kind == "eof":
            return                          # null directive
        name = self.next().text
        if name == "include":
            self.include(tok)
        elif name == "define":
            self.define(tok)
        elif name == "undef":
            t = self.line_tokens()
            if not t or t[0].kind != "id":
                raise CompileError("macro name expected", tok)
            self.macros.pop(t[0].text, None)
        elif name in ("if", "ifdef", "ifndef"):
            if name == "if":
                val = self.eval_if(self.line_tokens(), tok)
            else:
                t = self.line_tokens()
                if not t or t[0].kind != "id":
                    raise CompileError("macro name expected", tok)
                val = (t[0].text in self.macros) == (name == "ifdef")
            self.cond.append([val, val, False])
            if not val:
                self.skip()
        elif name == "elif":
            if not self.cond or self.cond[-1][2]:
                raise CompileError("#elif without #if", tok)
            top = self.cond[-1]
            rest = self.line_tokens()
            if top[1]:
                top[0] = False
                self.skip()
            else:
                val = self.eval_if(rest, tok)
                top[0] = top[1] = val
                if not val:
                    self.skip()
        elif name == "else":
            self.line_tokens()
            if not self.cond or self.cond[-1][2]:
                raise CompileError("#else without #if", tok)
            top = self.cond[-1]
            top[2] = True
            if top[1]:
                top[0] = False
                self.skip()
            else:
                top[0] = top[1] = True
        elif name == "endif":
            self.line_tokens()
            if not self.cond:
                raise CompileError("#endif without #if", tok)
            self.cond.pop()
        elif name == "error":
            msg = " ".join(t.text for t in self.line_tokens())
            raise CompileError(f"#error {msg}", tok)
        elif name == "warning":
            self.line_tokens()
        elif name in ("pragma", "line", "ident"):
            t = self.line_tokens()
            if name == "pragma" and t and t[0].text == "once":
                self.once.add(tok.file)
        else:
            raise CompileError(f"unknown directive #{name}", tok)

    def skip(self):
        """Skip a false conditional group, up to the #elif/#else/#endif that
        ends it (which is left for directive() to handle)."""
        depth = 0
        while True:
            tok = self.peek()
            if tok.kind == "eof":
                return
            if tok.text == "#" and tok.bol and tok.kind == "punct" and tok.origin is None:
                self.next()
                d = self.peek()
                if d.bol:
                    continue
                if d.text in ("if", "ifdef", "ifndef"):
                    depth += 1
                elif d.text == "endif" or (d.text in ("elif", "else") and depth == 0):
                    if depth == 0:
                        self.stack.append(tok)      # the main loop handles it
                        return
                    depth -= 1
                self.line_tokens()
                continue
            self.next()

    def include(self, tok):
        t = self.peek()
        if t.kind == "str" and not t.bol:
            self.next()
            name = t.text[1:-1]
            self.line_tokens()
            path = self.find_include(name, os.path.dirname(tok.file or "."), True)
        else:
            toks = self.line_tokens()
            toks = self.expand_list(toks)
            if toks and toks[0].kind == "str":
                name = toks[0].text[1:-1]
                path = self.find_include(name, os.path.dirname(tok.file or "."), True)
            elif toks and toks[0].text == "<":
                name = ""
                for x in toks[1:]:
                    if x.text == ">":
                        break
                    name += (" " if x.space and name else "") + x.text
                path = self.find_include(name, None, False)
            else:
                raise CompileError("expected \"file\" or <file>", tok)
        if path is None:
            raise CompileError(f"can't find include file {name}", tok)
        if path in self.once:
            return
        if self.depth > 100:
            raise CompileError("#include nested too deeply", tok)
        with open(path, encoding="latin-1") as f:
            text = f.read()
        toks = tokenize(text, os.path.relpath(path) if not os.path.relpath(path).startswith("..") else path)
        end = toks[-1]
        end.text = "<end-of-include>"
        self.depth += 1
        self.push(toks)

    def find_include(self, name, here, quoted):
        if os.path.isabs(name):
            return name if os.path.exists(name) else None
        dirs = ([here] if quoted and here is not None else []) + self.include_paths
        for d in dirs:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return os.path.abspath(p)
        return None

    def define(self, tok):
        name_tok = self.next()
        if name_tok.kind != "id" or name_tok.bol:
            raise CompileError("macro name expected", tok)
        name = name_tok.text
        nxt = self.peek()
        if nxt.text == "(" and not nxt.space and not nxt.bol:
            self.next()
            params = []
            variadic = False
            while True:
                t = self.next()
                if t.bol or t.kind == "eof":
                    raise CompileError("unterminated macro parameter list", t)
                if t.text == ")" and not params:
                    break
                if t.text == "...":
                    variadic = True
                    if self.next().text != ")":
                        raise CompileError("expected ')' after '...'", t)
                    break
                if t.kind != "id":
                    raise CompileError("parameter name expected", t)
                params.append(t.text)
                t = self.next()
                if t.text == ")":
                    break
                if t.text != ",":
                    raise CompileError("expected ',' or ')'", t)
            body = self.line_tokens()
            self.macros[name] = Macro(name, body, params, variadic)
        else:
            self.macros[name] = Macro(name, self.line_tokens())

    # ---- #if expressions ------------------------------------------------

    def eval_if(self, toks, where):
        # replace defined(X) first, before expansion
        out = []
        i = 0
        while i < len(toks):
            t = toks[i]
            if t.kind == "id" and t.text == "defined":
                if i + 1 < len(toks) and toks[i + 1].text == "(":
                    if i + 3 >= len(toks) or toks[i + 3].text != ")":
                        raise CompileError("bad defined()", t)
                    name = toks[i + 2].text
                    i += 4
                else:
                    if i + 1 >= len(toks):
                        raise CompileError("bad defined", t)
                    name = toks[i + 1].text
                    i += 2
                n = Token("num", "1" if name in self.macros else "0", t.file, t.line, t.col)
                out.append(n)
                continue
            out.append(t)
            i += 1
        out = self.expand_list(out)
        vals = []
        for t in out:
            if t.kind == "id":
                vals.append(Token("num", "0", t.file, t.line, t.col))
            else:
                vals.append(t)
        if not vals:
            raise CompileError("#if with no expression", where)
        p = IfParser(vals, where)
        v, _ = p.expr()
        if p.i != len(vals):
            raise CompileError("junk at the end of #if", vals[p.i])
        return v != 0

    # ---- macro expansion ------------------------------------------------

    def expand_list(self, toks):
        """Fully macro-expand a token list on its own."""
        saved = self.stack
        eof = Token("eof", "", toks[-1].file if toks else None, toks[-1].line if toks else 0, 0)
        self.stack = [eof] + list(reversed(toks))
        out = []
        while True:
            t = self.next()
            if t is eof:
                break
            if self.expand(t):
                continue
            out.append(t)
        self.stack = saved
        return out

    def expand(self, tok):
        """If tok is a macro invocation, push its expansion and return True."""
        if tok.kind != "id" or tok.text in tok.hideset:
            return False
        m = self.macros.get(tok.text)
        if m is None:
            return False
        if m.builtin:
            if m.builtin == "__FILE__":
                t = Token("str", '"' + (tok.file or "").replace("\\", "\\\\") + '"',
                          tok.file, tok.line, tok.col, tok.bol, tok.space)
            else:
                t = Token("num", str(tok.line), tok.file, tok.line, tok.col, tok.bol, tok.space)
            t.origin = tok
            self.push([t])
            return True
        if m.params is None:
            hs = tok.hideset | {m.name}
            body = self.subst_pasting(m, m.body, {})
            out = []
            for k, b in enumerate(body):
                c = b.copy()
                c.hideset = c.hideset | hs
                c.file, c.line, c.col = tok.file, tok.line, tok.col
                c.origin = tok
                if k == 0:
                    c.bol, c.space = tok.bol, tok.space
                else:
                    c.bol = False
                out.append(c)
            self.push(out)
            return True
        # function-like: needs '(' next
        nxt = self.peek()
        if nxt.text != "(" or nxt.kind != "punct":
            return False
        self.next()
        args, rparen = self.read_args(m, tok)
        hs = (tok.hideset & rparen.hideset) | {m.name}
        body = self.subst(m, args)
        out = []
        for k, b in enumerate(body):
            c = b.copy()
            c.hideset = c.hideset | hs
            c.file, c.line, c.col = tok.file, tok.line, tok.col
            c.origin = tok
            if k == 0:
                c.bol, c.space = tok.bol, tok.space
            else:
                c.bol = False
            out.append(c)
        self.push(out)
        return True

    def read_args(self, m, tok):
        args = []
        cur = []
        depth = 0
        while True:
            t = self.next()
            if t.kind == "eof":
                raise CompileError(f"unterminated call of macro {m.name}", tok)
            if t.text == "(" and t.kind == "punct":
                depth += 1
            elif t.text == ")" and t.kind == "punct":
                if depth == 0:
                    args.append(cur)
                    rparen = t
                    break
                depth -= 1
            elif t.text == "," and t.kind == "punct" and depth == 0 and \
                    not (m.variadic and len(args) == len(m.params)):
                args.append(cur)
                cur = []
                continue
            cur.append(t)
        n = len(m.params)
        if n == 0 and len(args) == 1 and not args[0] and not m.variadic:
            args = []
        if m.variadic:
            if len(args) == n:
                args.append([])
            if len(args) != n + 1:
                raise CompileError(f"macro {m.name} needs at least {n} arguments", tok)
        elif len(args) != n:
            raise CompileError(f"macro {m.name} needs {n} arguments, got {len(args)}", tok)
        names = list(m.params) + (["__VA_ARGS__"] if m.variadic else [])
        return dict(zip(names, args)), rparen

    def subst_pasting(self, m, body, args):
        """Object-like macros: only ## needs handling."""
        if not any(t.text == "##" for t in body):
            return body
        return self.subst(m, args)

    def subst(self, m, args):
        body = m.body
        out = []
        i = 0
        expanded = {}

        def exp(name):
            if name not in expanded:
                expanded[name] = self.expand_list(args[name])
            return expanded[name]
        while i < len(body):
            t = body[i]
            # # param
            if t.text == "#" and t.kind == "punct" and m.params is not None:
                if i + 1 < len(body) and body[i + 1].text in args:
                    s = stringify(args[body[i + 1].text], t)
                    s.space = t.space
                    out.append(s)
                    i += 2
                    continue
                raise CompileError("'#' is not followed by a macro parameter", t)
            # x ## y
            if t.text == "##" and t.kind == "punct":
                if not out or i + 1 >= len(body):
                    raise CompileError("'##' at the edge of a macro body", t)
                rhs = body[i + 1]
                if rhs.text in args:
                    arg = args[rhs.text]
                    if rhs.text == "__VA_ARGS__" and out[-1].text == ",":
                        if not arg:                 # GNU: , ## __VA_ARGS__
                            out.pop()
                        out.extend(a.copy() for a in exp(rhs.text))
                    elif arg:
                        out[-1] = paste(out[-1], arg[0])
                        out.extend(a.copy() for a in arg[1:])
                    i += 2
                    continue
                out[-1] = paste(out[-1], rhs)
                i += 2
                continue
            if t.text in args and t.kind == "id":
                arg = args[t.text]
                # param ## ...: insert unexpanded
                if i + 1 < len(body) and body[i + 1].text == "##":
                    if not arg:
                        # empty lhs: the rhs stands alone
                        if i + 2 < len(body):
                            rhs = body[i + 2]
                            if rhs.text in args:
                                out.extend(a.copy() for a in args[rhs.text])
                            else:
                                out.append(rhs.copy())
                            i += 3
                        else:
                            i += 2
                        continue
                    out.extend(a.copy() for a in arg)
                    i += 1
                    continue
                e = [a.copy() for a in exp(t.text)]
                if e:
                    e[0].space = t.space
                out.extend(e)
                i += 1
                continue
            out.append(t.copy())
            i += 1
        return out


def stringify(toks, where):
    s = ""
    for k, t in enumerate(toks):
        if k and t.space:
            s += " "
        if t.kind in ("str", "char"):
            s += t.text.replace("\\", "\\\\").replace('"', '\\"')
        else:
            s += t.text
    return Token("str", '"' + s + '"', where.file, where.line, where.col)


def paste(a, b):
    text = a.text + b.text
    toks = tokenize(text, a.file)
    if len(toks) != 2:
        raise CompileError(f"pasting \"{a.text}\" and \"{b.text}\" doesn't give one token", a)
    t = toks[0]
    t.file, t.line, t.col = a.file, a.line, a.col
    t.bol, t.space = a.bol, a.space
    t.hideset = a.hideset
    return t


def div_trunc(a, b):
    """C's / and % on ints (b != 0): the quotient rounds toward zero."""
    q = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        q = -q
    return q, a - q * b


def wrap32(v, unsigned):
    """v as a 32-bit long or unsigned long."""
    v &= 0xFFFFFFFF
    if not unsigned and v & 0x80000000:
        v -= 1 << 32
    return v


class IfParser:
    """Constant expressions in #if, with C's arithmetic in long and unsigned
    long (32 bits, as in the compiler; there's no long long): every value is
    (v, unsigned), with v in its type's range, and an operation on a signed
    and an unsigned value is unsigned. Division by zero is an error, except
    in an operand that isn't evaluated (after && or || has decided, or the
    arm of ?: not taken)."""

    BIN = [["||"], ["&&"], ["|"], ["^"], ["&"], ["==", "!="], ["<", ">", "<=", ">="],
           ["<<", ">>"], ["+", "-"], ["*", "/", "%"]]

    def __init__(self, toks, where):
        self.toks = toks
        self.i = 0
        self.where = where
        self.skip = 0           # > 0 inside an operand that isn't evaluated

    def peek(self):
        return self.toks[self.i].text if self.i < len(self.toks) else None

    def take(self):
        if self.i >= len(self.toks):
            raise CompileError("unexpected end of #if expression", self.where)
        t = self.toks[self.i]
        self.i += 1
        return t

    def expr(self):
        c = self.binary(0)
        if self.peek() == "?":
            self.take()
            taken = c[0] != 0
            self.skip += not taken
            a = self.expr()
            self.skip -= not taken
            if self.take().text != ":":
                raise CompileError("expected ':' in #if", self.where)
            self.skip += taken
            b = self.expr()
            self.skip -= taken
            u = a[1] or b[1]
            return wrap32((a if taken else b)[0], u), u
        return c

    def binary(self, level):
        if level == len(self.BIN):
            return self.unary()
        v = self.binary(level + 1)
        while self.peek() in self.BIN[level]:
            op = self.take().text
            if op in ("||", "&&"):
                decided = (v[0] != 0) == (op == "||")
                self.skip += decided
                r = self.binary(level + 1)
                self.skip -= decided
                if op == "||":
                    v = int(v[0] != 0 or r[0] != 0), False
                else:
                    v = int(v[0] != 0 and r[0] != 0), False
                continue
            v = self.apply(op, v, self.binary(level + 1))
        return v

    def apply(self, op, a, b):
        (x, xu), (y, yu) = a, b
        if op in ("<<", ">>"):
            # the left operand's type; as in the compiler, the count is taken modulo 32
            return wrap32(x << (y & 31) if op == "<<" else x >> (y & 31), xu), xu
        u = xu or yu
        x, y = wrap32(x, u), wrap32(y, u)
        if op in ("==", "!=", "<", ">", "<=", ">="):
            return int({"==": x == y, "!=": x != y, "<": x < y, ">": x > y,
                        "<=": x <= y, ">=": x >= y}[op]), False
        if op in ("/", "%"):
            if y == 0:
                if self.skip:
                    return 0, u
                raise CompileError("division by zero in #if", self.where)
            q, r = div_trunc(x, y)
            return wrap32(q if op == "/" else r, u), u
        v = {"|": x | y, "^": x ^ y, "&": x & y, "+": x + y, "-": x - y, "*": x * y}[op]
        return wrap32(v, u), u

    def unary(self):
        t = self.take()
        if t.text == "(":
            v = self.expr()
            if self.take().text != ")":
                raise CompileError("missing ')' in #if", t)
            return v
        if t.text in ("-", "+", "~"):
            v, u = self.unary()
            return wrap32({"-": -v, "+": v, "~": ~v}[t.text], u), u
        if t.text == "!":
            return int(self.unary()[0] == 0), False
        if t.kind == "num":
            # long if it fits, else unsigned long (C89's rules with a 32-bit long)
            v, u, _, _ = parse_int(t)
            if v >= 1 << 32:
                raise CompileError(f"integer constant {t.text} is too large for #if", t)
            u = u or v >= 1 << 31
            return wrap32(v, u), u
        if t.kind == "char":
            return wrap32(char_value(t), False), False
        raise CompileError(f"unexpected {t.text!r} in #if", t)


def parse_int(tok):
    """Integer constant -> (value, is_unsigned, is_long, is_decimal)."""
    s = tok.text.lower()
    suffix = ""
    while s and s[-1] in "ul":
        suffix = s[-1] + suffix
        s = s[:-1]
    if suffix.count("u") > 1 or suffix.count("l") > 2:
        raise CompileError(f"bad integer suffix in {tok.text}", tok)
    try:
        if s.startswith("0x"):
            v, dec = int(s[2:], 16), False
        elif s.startswith("0") and len(s) > 1:
            v, dec = int(s, 8), False
        else:
            v, dec = int(s, 10), True
    except ValueError:
        if "." in s or "e" in s:
            raise CompileError("floating-point numbers aren't supported", tok)
        raise CompileError(f"bad number {tok.text}", tok)
    return v, "u" in suffix, "l" in suffix, dec


def char_value(tok):
    body = tok.text
    if body.startswith("L"):
        body = body[1:]
    vals = unescape(body[1:-1], tok)
    if not vals:
        raise CompileError("empty character constant", tok)
    v = 0
    for b in vals:
        v = (v << 8) | b
    # plain char is unsigned on this machine, so '\xff' is 255
    return v
