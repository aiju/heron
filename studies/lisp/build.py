"""Build the Lisp system's image: the runtime (rt/*.s), the tables the
build generates (the static symbols, the primitive objects, the special
forms) and the prelude (prelude.lisp), assembled into one absolute image
for the draft 1b simulator.

The runtime sources may contain feature blocks, for the ISA experiments:

    .if NAME            ; kept when feature NAME is on
    ...
    .else
    ...
    .endif

Lines a block drops become empty lines, so the assembler's line numbers
still match the source.
"""

import os
import re

from heron import ROOT
from heron.infra import asm as asmcore
from heron.infra import isas
import heron.studies.v1_isa  # noqa: F401  (registers the ISAs)

HERE = os.path.dirname(os.path.abspath(__file__))
RT = os.path.join(HERE, "rt")
BUILD = os.path.join(ROOT, "build", "lisp")
ISA = "v1b"

# The runtime's sources, in the order they're assembled.
RT_FILES = ["start.s", "gc.s", "read.s", "print.s", "eval.s", "prims.s", "code.s"]

# Special forms: (name, handler). A special form's symbol holds 4 * its
# index here; sf_table maps the index to the handler.
SPECIAL = [
    ("quote", "sf_quote"), ("if", "sf_if"), ("define", "sf_define"),
    ("set!", "sf_set"), ("lambda", "sf_lambda"), ("begin", "sf_begin"),
    ("let", "sf_let"), ("let*", "sf_letstar"), ("letrec", "sf_letrec"),
    ("cond", "sf_cond"), ("and", "sf_and"), ("or", "sf_or"),
    ("defmacro", "sf_defmacro"),
]
MACRO_HANDLER = "sf_macro"      # the index after the special forms

# Primitives: (name, routine). Each gets a static procedure object, and its
# symbol's global value is that object.
PRIMS = [
    ("cons", "p_cons"), ("car", "p_car"), ("cdr", "p_cdr"),
    ("set-car!", "p_setcar"), ("set-cdr!", "p_setcdr"),
    ("caar", "p_caar"), ("cadr", "p_cadr"), ("cdar", "p_cdar"), ("cddr", "p_cddr"),
    ("caddr", "p_caddr"), ("cdddr", "p_cdddr"), ("cadddr", "p_cadddr"),
    ("list", "p_list"), ("length", "p_length"), ("append", "p_append"),
    ("reverse", "p_reverse"), ("memq", "p_memq"), ("assq", "p_assq"),
    ("eq?", "p_eq"), ("equal?", "p_equal"), ("not", "p_not"), ("null?", "p_not"),
    ("pair?", "p_pairp"), ("atom?", "p_atomp"), ("symbol?", "p_symbolp"),
    ("number?", "p_numberp"), ("integer?", "p_numberp"), ("string?", "p_stringp"),
    ("vector?", "p_vectorp"), ("procedure?", "p_procp"), ("eof-object?", "p_eofp"),
    ("+", "p_add"), ("-", "p_sub"), ("*", "p_mul"),
    ("quotient", "p_quotient"), ("remainder", "p_remainder"), ("modulo", "p_modulo"),
    ("=", "p_numeq"), ("<", "p_lt"), (">", "p_gt"), ("<=", "p_le"), (">=", "p_ge"),
    ("zero?", "p_zerop"),
    ("logand", "p_logand"), ("logior", "p_logior"), ("logxor", "p_logxor"), ("ash", "p_ash"),
    ("gensym", "p_gensym"), ("symbol->string", "p_sym2str"), ("string->symbol", "p_str2sym"),
    ("string-length", "p_strlen"), ("string-ref", "p_strref"), ("string=?", "p_streq"),
    ("get", "p_get"), ("put", "p_put"),
    ("make-vector", "p_mkvec"), ("vector-ref", "p_vecref"), ("vector-set!", "p_vecset"),
    ("vector-length", "p_veclen"),
    ("apply", "p_apply"), ("eval", "p_eval"), ("error", "p_error"), ("read", "p_read"),
    ("write", "p_write"), ("display", "p_display"), ("newline", "p_newline"),
    ("write-char", "p_writechar"), ("gc", "p_gc"),
    # for the compiler (code.s)
    ("%code-alloc", "p_codealloc"), ("%code-free", "p_codefree"), ("%poke16", "p_poke16"),
    ("%make-closure", "p_mkclosure"), ("%closure-set!", "p_closet"),
    ("%static-closure", "p_staticclo"),
    ("%address", "p_address"), ("%static-copy", "p_staticcopy"),
    ("%macro", "p_macro"), ("%special?", "p_specialp"), ("%set-macro!", "p_setmacro"),
]

# Runtime routines compiled code calls: the symbol %rt:NAME holds the
# routine's address (an integer).
EXPORTS = [
    ("cons", "cons"), ("alloc", "alloc"), ("gc", "gc"), ("rest", "rt_rest"),
    ("num2", "rt_num2"), ("notnum", "err_notnum"), ("overflow", "err_overflow"),
    ("unbound", "err_unbound"), ("argc", "err_argc"), ("notproc", "err_notproc"),
    ("notvec", "err_notvec"), ("range", "err_range"), ("syntax", "err_syntax"),
    ("div0", "err_div0"), ("notpair", "err_notpair"), ("stack", "err_stack"),
    ("cons-limit", "cons_limit"), ("heap-limit", "heap_limit"), ("stack-limit", "stack_limit"),
    ("nil", "NILV"), ("t", "S_t + 3"),
]

# Other symbols the runtime refers to: (name, label).
SYMBOLS = [
    ("t", "S_t"), ("quasiquote", "S_quasiquote"), ("unquote", "S_unquote"),
    ("unquote-splicing", "S_unquote_splicing"), ("begin", "S_begin"),
    ("%named-let", "S_named_let"), ("%toplevel", "S_toplevel"),
]


def mangle(name):
    """An assembler label for a symbol's name."""
    subst = {"-": "_", "!": "X", "?": "P", "*": "S", "+": "plus", "<": "lt", ">": "gt",
             "=": "eq", "/": "sl", "%": "pc", ":": "_c_"}
    return "S_" + "".join(subst.get(c, c) for c in name)


def symbol_table():
    """[(name, label, special handler or None, primitive routine or None)]"""
    out, seen = [], {}

    def add(name, label=None):
        if name not in seen:
            seen[name] = len(out)
            out.append([name, label or mangle(name), None, None])
        return out[seen[name]]

    for name, h in SPECIAL:
        add(name)[2] = h
    for name, label in SYMBOLS:
        add(name, label)
    for name, r in PRIMS:
        add(name)[3] = r
    for name, label in EXPORTS:
        add("%rt:" + name).append(label)
    labels = [s[1] for s in out]
    assert len(set(labels)) == len(labels), "two symbols mangle to the same label"
    return out


def ascii_bytes(data):
    """.byte lines for some bytes."""
    lines = []
    for i in range(0, len(data), 16):
        lines.append("        .byte " + ", ".join(str(b) for b in data[i:i + 16]))
    return lines


def generate():
    """The generated part of the runtime: tables and static objects."""
    syms = symbol_table()
    out = ["; Generated by studies/lisp/build.py: don't edit.", ""]
    out.append("; ---- special forms")
    for i, (name, h) in enumerate(SPECIAL, 1):
        out.append(f"SF_{mangle(name)[2:].upper()} = {4 * i}")
    out.append(f"SF_MACRO = {4 * (len(SPECIAL) + 1)}")
    out += ["", "; ---- primitive objects", "        .align 8"]
    for name, label, sf, prim, *exp in syms:
        if prim:
            out.append(f"P{label[1:]}: .word H_PRIM, {prim}, {label} + 3, 0")
    out += ["", "; ---- the static symbols' names"]
    for name, label, sf, prim, *exp in syms:
        b = name.encode()
        out.append(f"        .align 8")
        out.append(f"N{label[1:]}: .word {len(b)} << 8 | T_STR << 3 | 5, not_proc")
        out += ascii_bytes(b)
    out += ["        .align 8", "", "; ---- the prelude, read at start-up", "prelude_text:"]
    with open(os.path.join(HERE, "prelude.lisp"), "rb") as f:
        out += ascii_bytes(f.read() + b"\0")
    out += ["        .align 8", "gen_end:", ""]
    out += ["; ---- special form table", "        .org SF_TABLE", "sf_handlers:", "        .word 0"]
    for name, h in SPECIAL:
        out.append(f"        .word {h}")
    out.append(f"        .word {MACRO_HANDLER}")
    out += ["; ---- the static symbols, at the bottom of symbol space", "        .org SYM_BASE",
            "sym_static:"]
    for name, label, sf, prim, *exp in syms:
        value = f"P{label[1:]} + 3" if prim else "UNB"
        if exp:
            value = f"({exp[0]}) << 1"
        if name == "t":
            value = "S_t + 3"
        special = f"SF_{mangle(name)[2:].upper()}" if sf else "0"
        out.append(f"{label}: .word H_SYM, not_proc, {value}, N{label[1:]} + 3, {special}, NILV, 0, NILV")
    out += ["sym_static_end:", ""]
    return "\n".join(out) + "\n"


IF_RE = re.compile(r"^\s*\.(if|else|endif)(?![\w:.])\s*(\S*)")


def preprocess(text, features):
    """Apply the .if/.else/.endif blocks for a set of feature names."""
    out, stack = [], []
    for n, line in enumerate(text.split("\n"), 1):
        m = IF_RE.match(line)
        if m:
            kind, name = m.groups()
            if kind == "if":
                stack.append(name in features)
            elif not stack:
                raise asmcore.AsmError(f".{kind} without .if", None)
            elif kind == "else":
                stack[-1] = not stack[-1]
            else:
                stack.pop()
            out.append("")
        elif all(stack):
            out.append(line)
        else:
            out.append("")
    if stack:
        raise asmcore.AsmError("missing .endif", None)
    return "\n".join(out)


def build(features=()):
    """Assemble the runtime with the given features: the image."""
    isa = isas.get(ISA)
    a = asmcore.Assembler(isa)
    for name in RT_FILES:
        path = os.path.join(RT, name)
        with open(path) as f:
            a.load(path, preprocess(f.read(), set(features)))
    os.makedirs(BUILD, exist_ok=True)
    gen = os.path.join(BUILD, "generated.s")
    text = generate()
    with open(gen, "w") as f:
        f.write(text)
    a.load(gen, text)
    return a.assemble()


if __name__ == "__main__":
    img = build()
    lo, hi = img.extent()
    print(f"image {lo:05X}-{hi - 1:05X}, {img.code_bytes()} bytes of code")
