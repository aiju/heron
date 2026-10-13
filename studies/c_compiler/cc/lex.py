"""Tokenizer for C source (preprocessing tokens)."""

import bisect
import re


class CompileError(Exception):
    def __init__(self, msg, tok=None):
        super().__init__(msg)
        self.msg = msg
        self.tok = tok

    def __str__(self):
        if self.tok is not None and self.tok.file:
            return f"{self.tok.file}:{self.tok.line}:{self.tok.col}: error: {self.msg}"
        return f"error: {self.msg}"


class Token:
    __slots__ = ("kind", "text", "file", "line", "col", "bol", "space", "hideset", "value", "origin")

    def __init__(self, kind, text, file=None, line=0, col=0, bol=False, space=False):
        self.kind = kind          # 'id' 'num' 'char' 'str' 'punct' 'eof'
        self.text = text
        self.file = file
        self.line = line
        self.col = col
        self.bol = bol            # first token on its line
        self.space = space        # preceded by whitespace
        self.hideset = frozenset()
        self.value = None
        self.origin = None        # the macro-invocation token this came from

    def copy(self):
        t = Token(self.kind, self.text, self.file, self.line, self.col, self.bol, self.space)
        t.hideset = self.hideset
        t.value = self.value
        t.origin = self.origin
        return t

    def __repr__(self):
        return f"Token({self.kind}, {self.text!r}, {self.line})"


PUNCTS = ["...", "<<=", ">>=", "->", "++", "--", "<<", ">>", "<=", ">=", "==", "!=",
          "&&", "||", "*=", "/=", "%=", "+=", "-=", "&=", "^=", "|=", "##"]

TOKEN_RE = re.compile(r"""
    (?P<nl>\n)
  | (?P<ws>[ \t\r\f\v]+)
  | (?P<lcom>//[^\n]*)
  | (?P<bcom>/\*.*?\*/)
  | (?P<num>\.?[0-9](?:[eEpP][+-]|[0-9A-Za-z_.])*)
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<str>L?"(?:\\.|[^"\\\n])*")
  | (?P<char>L?'(?:\\.|[^'\\\n])*')
  | (?P<punct>""" + "|".join(re.escape(p) for p in PUNCTS) + r"""|[-+*/%&|^~!<>=?:;,.()\[\]{}#])
""", re.VERBOSE | re.DOTALL)


def tokenize(text, filename):
    # line splices: remove them, but remember where they were for line numbers
    splices = []
    if "\\\n" in text:
        parts = text.split("\\\n")
        pos = 0
        for p in parts[:-1]:
            pos += len(p)
            splices.append(pos)
        text = "".join(parts)
    newlines = [m.start() for m in re.finditer("\n", text)]

    def where(pos):
        nl = bisect.bisect_left(newlines, pos)
        line = 1 + nl + bisect.bisect_right(splices, pos)
        start = newlines[nl - 1] + 1 if nl else 0
        return line, pos - start + 1

    toks = []
    pos = 0
    bol = True
    space = False
    n = len(text)
    while pos < n:
        m = TOKEN_RE.match(text, pos)
        if not m:
            line, col = where(pos)
            if text.startswith("/*", pos):
                raise CompileError("unterminated comment", Token("eof", "", filename, line, col))
            raise CompileError(f"stray character {text[pos]!r}", Token("eof", "", filename, line, col))
        kind = m.lastgroup
        if kind == "nl":
            bol = True
            space = False
        elif kind in ("ws", "lcom"):
            space = True
        elif kind == "bcom":
            space = True
        else:
            line, col = where(pos)
            toks.append(Token(kind, m.group(kind), filename, line, col, bol, space))
            bol = False
            space = False
        pos = m.end()
    line, col = where(n)
    toks.append(Token("eof", "", filename, line, col, True, False))
    return toks


ESCAPES = {"n": 10, "t": 9, "r": 13, "a": 7, "b": 8, "f": 12, "v": 11, "e": 27,
           "\\": 92, "'": 39, '"': 34, "?": 63}


def unescape(body, tok):
    """Decode the inside of a string or char literal into a list of byte values."""
    out = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out.append(ord(ch) & 0xFF if ord(ch) < 256 else ord("?"))
            i += 1
            continue
        i += 1
        if i >= len(body):
            raise CompileError("bad escape", tok)
        e = body[i]
        if e in ESCAPES:
            out.append(ESCAPES[e])
            i += 1
        elif e in "01234567":
            j = i
            while j < len(body) and j < i + 3 and body[j] in "01234567":
                j += 1
            out.append(int(body[i:j], 8) & 0xFF)
            i = j
        elif e == "x":
            j = i + 1
            while j < len(body) and body[j] in "0123456789abcdefABCDEF":
                j += 1
            if j == i + 1:
                raise CompileError("\\x needs hex digits", tok)
            out.append(int(body[i + 1:j], 16) & 0xFF)
            i = j
        else:
            raise CompileError(f"unknown escape sequence \\{e}", tok)
    return out
