"""Curlew's lexer: source text to tokens (language.md, "Lexical
structure"). Layout is the parser's job (parse.py); each token carries its
line and column, and whether it's the first on its line, for it."""


class CurlewError(Exception):
    """An error in a program: lexing, parsing, scoping or typing. `where`
    is (line, column) or None."""

    def __init__(self, msg, where=None):
        super().__init__(msg)
        self.msg = msg
        self.where = where

    def __str__(self):
        if self.where:
            return f"{self.where[0]}:{self.where[1]}: {self.msg}"
        return self.msg


RESERVED = {
    "case", "class", "data", "deriving", "do", "else", "if", "in", "infix",
    "infixl", "infixr", "instance", "let", "of", "then", "type", "where", "_",
}
RESERVED_OPS = {"..", "::", "=", "\\", "|", "<-", "->", "@", "~", "=>"}
SYMBOL_CHARS = set("!#$%&*+./<=>?@\\^|-~:")
SPECIAL = set("()[],;`{}")

ESCAPES = {"n": 10, "t": 9, "r": 13, "\\": 92, "'": 39, '"': 34, "0": 0,
           "a": 7, "b": 8, "f": 12, "v": 11}


class Token:
    """kind: 'varid', 'conid', 'varsym', 'consym', 'int', 'char', 'string',
    'special' (one of ( ) [ ] , ; ` { }), 'reserved' (keywords and reserved
    operators), or 'eof'. value: the text, or the literal's value."""
    __slots__ = ("kind", "value", "line", "col", "first")

    def __init__(self, kind, value, line, col, first=False):
        self.kind, self.value, self.line, self.col, self.first = kind, value, line, col, first

    @property
    def where(self):
        return (self.line, self.col)

    def is_(self, kind, value=None):
        return self.kind == kind and (value is None or self.value == value)

    def __repr__(self):
        return f"Token({self.kind}, {self.value!r}, {self.line}:{self.col})"


def lex(text):
    """The tokens of a program (str), ending with an 'eof' token."""
    toks = []
    i, n = 0, len(text)
    line, col = 1, 1
    line_start = True       # no token yet on this line

    def advance(k):
        nonlocal i, line, col
        for _ in range(k):
            if text[i] == "\n":
                line += 1
                col = 1
            elif text[i] == "\t":
                col += 8 - (col - 1) % 8
            else:
                col += 1
            i += 1

    def err(msg):
        raise CurlewError(msg, (line, col))

    def escape():
        """At a backslash in a char or string literal: the character's
        code, consuming the escape."""
        advance(1)
        if i >= n:
            err("unfinished escape")
        c = text[i]
        if c in ESCAPES:
            advance(1)
            return ESCAPES[c]
        if c.isdigit():
            j = i
            while j < n and text[j].isdigit():
                j += 1
            v = int(text[i:j])
            advance(j - i)
            return v
        err(f"unknown escape \\{c}")

    while i < n:
        c = text[i]
        if c == "\n":
            advance(1)
            line_start = True
            continue
        if c in " \t\r\f":
            advance(1)
            continue
        if text.startswith("--", i):
            # a line comment, unless the dashes start an operator like -->
            j = i
            while j < n and text[j] == "-":
                j += 1
            if j >= n or text[j] not in SYMBOL_CHARS:
                while i < n and text[i] != "\n":
                    advance(1)
                continue
        if text.startswith("{-", i):
            depth = 0
            while i < n:
                if text.startswith("{-", i):
                    depth += 1
                    advance(2)
                elif text.startswith("-}", i):
                    depth -= 1
                    advance(2)
                    if depth == 0:
                        break
                else:
                    advance(1)
            else:
                err("unfinished comment")
            continue
        tl, tc, first = line, col, line_start
        line_start = False
        if c.isalpha() or c == "_":
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_'"):
                j += 1
            word = text[i:j]
            advance(j - i)
            if word in RESERVED:
                toks.append(Token("reserved", word, tl, tc, first))
            elif c.isupper():
                toks.append(Token("conid", word, tl, tc, first))
            else:
                toks.append(Token("varid", word, tl, tc, first))
        elif c.isdigit():
            j = i
            if text.startswith(("0x", "0X"), i):
                j = i + 2
                while j < n and text[j] in "0123456789abcdefABCDEF":
                    j += 1
                v = int(text[i + 2:j], 16)
            else:
                while j < n and text[j].isdigit():
                    j += 1
                v = int(text[i:j])
            advance(j - i)
            toks.append(Token("int", v, tl, tc, first))
        elif c == "'":
            advance(1)
            if i >= n:
                err("unfinished character literal")
            if text[i] == "\\":
                v = escape()
            else:
                v = ord(text[i])
                advance(1)
            if i >= n or text[i] != "'":
                err("unfinished character literal")
            advance(1)
            toks.append(Token("char", v, tl, tc, first))
        elif c == '"':
            advance(1)
            chars = []
            while True:
                if i >= n or text[i] == "\n":
                    err("unfinished string")
                if text[i] == '"':
                    advance(1)
                    break
                if text[i] == "\\":
                    if i + 1 < n and text[i + 1] == "&":
                        advance(2)      # \& separates escapes, and is nothing
                        continue
                    chars.append(escape())
                else:
                    chars.append(ord(text[i]))
                    advance(1)
            toks.append(Token("string", chars, tl, tc, first))
        elif c in SPECIAL:
            advance(1)
            toks.append(Token("special", c, tl, tc, first))
        elif c in SYMBOL_CHARS:
            j = i
            while j < n and text[j] in SYMBOL_CHARS:
                j += 1
            sym = text[i:j]
            advance(j - i)
            if sym in RESERVED_OPS:
                toks.append(Token("reserved", sym, tl, tc, first))
            elif sym[0] == ":":
                toks.append(Token("consym", sym, tl, tc, first))
            else:
                toks.append(Token("varsym", sym, tl, tc, first))
        else:
            err(f"unexpected character {c!r}")
    toks.append(Token("eof", None, line + 1, 0, True))
    return toks
