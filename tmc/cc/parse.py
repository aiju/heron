"""Parser and type checker for the C subset: preprocessed tokens in, a
typed syntax tree (tmc.cc.tree) out.

Supported: all of C89's statements and operators, int/char/short/long
(signed and unsigned), pointers, arrays, structs, unions, enums, typedefs,
function pointers, variadic functions, static and extern, initializers with
brace elision. Not supported: floating point, bit fields, long long,
old-style (K&R) function definitions. A few C99 conveniences are accepted:
// comments, declarations after statements and in for loops, and
designated initializers.
"""

import re
from .lex import CompileError, Token, unescape
from .cpp import parse_int, char_value
from . import ctype as T
from .ctype import Type, StructInfo, pointer_to, array_of, func_type
from . import tree as N

KEYWORDS = {
    "auto", "break", "case", "char", "const", "continue", "default", "do", "double",
    "else", "enum", "extern", "float", "for", "goto", "if", "int", "long", "register",
    "return", "short", "signed", "sizeof", "static", "struct", "switch", "typedef",
    "union", "unsigned", "void", "volatile", "while", "inline", "__inline", "__inline__",
    "_Bool",
}
TYPE_KEYWORDS = {"void", "char", "short", "int", "long", "signed", "unsigned", "struct",
                 "union", "enum", "const", "volatile", "float", "double", "_Bool"}
STORAGE = {"typedef", "extern", "static", "auto", "register"}
ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "<<=", ">>=", "&=", "^=", "|="}


def norm(v, ty):
    """Wrap an int to a value of integer (or pointer) type ty."""
    bits = 8 * ty.size if ty.is_integer else 32
    v &= (1 << bits) - 1
    if ty.is_integer and not ty.unsigned and v >> (bits - 1):
        v -= 1 << bits
    return v


class NotConstant(Exception):
    pass


class Symbol:
    __slots__ = ("name", "ty", "kind", "storage", "value", "tok", "defined", "init",
                 "is_local", "asm_name", "uid", "ir", "used", "address_taken", "asm_label")
    _uid = 0

    def __init__(self, name, ty, kind, storage, tok=None, is_local=False):
        self.name = name
        self.ty = ty
        self.kind = kind            # var func typedef enumconst
        self.storage = storage      # auto param static extern global
        self.value = None
        self.tok = tok
        self.defined = False
        self.init = None
        self.is_local = is_local
        self.asm_name = name
        Symbol._uid += 1
        self.uid = Symbol._uid
        self.ir = None
        self.used = False
        self.address_taken = False
        self.asm_label = None       # __asm__("name"): the assembler name, as is

    def __repr__(self):
        return f"Symbol({self.name}, {self.ty}, {self.kind})"


class Initializer:
    """Flattened: items are (offset, type, expr) for scalars, or for a whole
    struct initialized from a struct-valued expression."""

    def __init__(self, ty):
        self.ty = ty
        self.items = []


class FunctionDef:
    def __init__(self, sym, params, tok):
        self.sym = sym
        self.params = params        # Symbols
        self.locals = []            # all auto variables, any scope
        self.body = None
        self.tok = tok
        self.labels = {}
        self.gotos = []


class TranslationUnit:
    def __init__(self):
        self.functions = []         # FunctionDef
        self.globals = []           # Symbols with storage global/static/extern (vars)
        self.funcs = {}             # name -> Symbol for every function declared
        self.warnings = []


class Scope:
    def __init__(self, parent):
        self.parent = parent
        self.names = {}
        self.tags = {}


class DeclSpec:
    def __init__(self):
        self.ty = None
        self.storage = None
        self.inline = False


class Parser:
    def __init__(self, tokens):
        for t in tokens:
            if t.kind == "id" and t.text in KEYWORDS:
                t.kind = "kw"
        self.toks = tokens
        self.i = 0
        self.scope = Scope(None)
        self.tu = TranslationUnit()
        self.func = None
        self.switches = []
        self.loops = 0
        self.static_count = 0

    # ---- token helpers ---------------------------------------------------

    def peek(self, k=0):
        j = min(self.i + k, len(self.toks) - 1)
        return self.toks[j]

    def next(self):
        t = self.toks[self.i]
        if t.kind != "eof":
            self.i += 1
        return t

    def at(self, text, k=0):
        t = self.peek(k)
        return t.text == text and t.kind in ("punct", "kw")

    def accept(self, text):
        if self.at(text):
            return self.next()
        return None

    def expect(self, text):
        t = self.peek()
        if not self.at(text):
            got = "end of file" if t.kind == "eof" else repr(t.text)
            raise CompileError(f"expected '{text}', got {got}", t)
        return self.next()

    def error(self, msg, tok=None):
        raise CompileError(msg, tok or self.peek())

    def warn(self, msg, tok=None):
        tok = tok or self.peek()
        self.tu.warnings.append(f"{tok.file}:{tok.line}:{tok.col}: warning: {msg}")

    # ---- scopes ------------------------------------------------------------

    def push_scope(self):
        self.scope = Scope(self.scope)

    def pop_scope(self):
        self.scope = self.scope.parent

    def lookup(self, name):
        s = self.scope
        while s:
            if name in s.names:
                return s.names[name]
            s = s.parent
        return None

    def lookup_tag(self, name):
        s = self.scope
        while s:
            if name in s.tags:
                return s.tags[name]
            s = s.parent
        return None

    def is_typedef_name(self, tok):
        if tok.kind != "id":
            return False
        s = self.lookup(tok.text)
        return s is not None and s.kind == "typedef"

    def is_type_start(self, k=0):
        t = self.peek(k)
        if t.kind == "kw":
            return t.text in TYPE_KEYWORDS or t.text in STORAGE or t.text in ("inline", "__inline", "__inline__")
        return self.is_typedef_name(t)

    # ---- top level ---------------------------------------------------------

    def parse(self):
        while self.peek().kind != "eof":
            if self.accept(";"):
                continue
            self.external_declaration()
        for sym in self.tu.funcs.values():
            if sym.used and not sym.defined and sym.storage == "static":
                self.warn(f"static function {sym.name} is used but never defined", sym.tok)
        return self.tu

    def external_declaration(self):
        start = self.peek()
        spec = self.decl_specifiers()
        if self.accept(";"):
            return
        first = True
        while True:
            name, ty, tok = self.declarator(spec.ty)
            if name is None:
                self.error("declaration needs a name", tok)
            label = self.asm_label()
            if spec.storage == "typedef":
                if label:
                    self.error("a typedef can't have an assembler name", tok)
                self.declare_typedef(name, ty, tok)
            elif ty.is_func:
                if first and self.at("{") and not label:
                    self.function_definition(name, ty, spec, tok)
                    return
                sym = self.declare_function(name, ty, spec.storage, tok)
                self.set_asm_label(sym, label, tok)
            else:
                if spec.storage in ("auto", "register"):
                    self.error("file-scope variable can't be auto or register", tok)
                sym = self.declare_global(name, ty, spec.storage, tok)
                self.set_asm_label(sym, label, tok)
                if self.accept("="):
                    if spec.storage == "extern":
                        self.warn(f"{name} is extern and initialized", tok)
                    init = self.initializer(sym.ty)
                    sym.ty = init.ty
                    if sym.init is not None:
                        self.error(f"{name} is initialized twice", tok)
                    sym.init = init
                    sym.defined = True
                    sym.storage = "static" if sym.storage == "static" else "global"
            first = False
            if self.accept(","):
                continue
            self.expect(";")
            return

    def asm_label(self):
        """GNU C's `__asm__("name")` after a declarator: the name the
        assembler and linker know the symbol by (no `_` added)."""
        t = self.peek()
        if not (t.kind == "id" and t.text in ("__asm__", "__asm", "asm") and self.at("(", 1)):
            return None
        self.next()
        self.expect("(")
        if self.peek().kind != "str":
            self.error("expected the assembler name as a string", self.peek())
        label = self.string_literal().data[:-1].decode("latin-1")
        self.expect(")")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", label):
            self.error(f"{label!r} isn't a valid assembler name", t)
        return label

    def set_asm_label(self, sym, label, tok):
        if label is None:
            return
        if sym.asm_label not in (None, label):
            self.error(f"{sym.name} already has the assembler name {sym.asm_label}", tok)
        if sym.storage == "static":
            self.error(f"{sym.name} is static: an assembler name only makes sense for "
                       "symbols other files see", tok)
        sym.asm_label = label

    def declare_typedef(self, name, ty, tok):
        old = self.scope.names.get(name)
        if old is not None and not (old.kind == "typedef" and T.same_type(old.ty, ty)):
            self.error(f"{name} redeclared as a different kind of symbol", tok)
        self.scope.names[name] = Symbol(name, ty, "typedef", None, tok)

    def declare_function(self, name, ty, storage, tok, local=False):
        sym = self.tu.funcs.get(name)
        if sym is not None:
            if not T.same_type(sym.ty, ty, False):
                self.error(f"conflicting types for {name}: {sym.ty} and {ty}", tok)
            if sym.ty.params is None and ty.params is not None:
                sym.ty = ty
        else:
            g = self.scope
            while g.parent:
                g = g.parent
            old = g.names.get(name)
            if old is not None and old.kind != "func":
                self.error(f"{name} redeclared as a function", tok)
            sym = Symbol(name, ty, "func", "static" if storage == "static" else "global", tok)
            self.tu.funcs[name] = sym
            g.names[name] = sym
        if local:
            self.scope.names[name] = sym
        return sym

    def declare_global(self, name, ty, storage, tok):
        g = self.scope
        while g.parent:
            g = g.parent
        old = g.names.get(name)
        if old is not None:
            if old.kind != "var":
                self.error(f"{name} redeclared as a variable", tok)
            if not T.same_type(old.ty, ty):
                if old.ty.is_array and ty.is_array and T.same_type(old.ty.base, ty.base):
                    if old.ty.length is None:
                        old.ty = ty
                else:
                    self.error(f"conflicting types for {name}: {old.ty} and {ty}", tok)
            if storage != "extern":
                if old.storage == "extern":
                    old.storage = "static" if storage == "static" else "global"
                old.defined = True
            return old
        sym = Symbol(name, ty, "var", storage or "global", tok)
        if storage == "static":
            sym.storage = "static"
        sym.defined = storage != "extern"
        g.names[name] = sym
        self.tu.globals.append(sym)
        return sym

    def function_definition(self, name, ty, spec, tok):
        sym = self.declare_function(name, ty, spec.storage, tok)
        if sym.defined:
            self.error(f"function {name} is defined twice", tok)
        sym.defined = True
        sym.ty = ty
        if ty.params is None:
            ty = func_type(ty.ret, [], False)
            ty.pnames = []
            sym.ty = ty
        if ty.ret.is_array or ty.ret.is_func:
            self.error("functions can't return arrays or functions", tok)
        f = FunctionDef(sym, [], tok)
        self.func = f
        self.push_scope()
        for (pname, ptok), pty in zip(ty.pnames or [], ty.params):
            if pname is None:
                self.error("parameter name omitted in function definition", ptok)
            if not pty.complete:
                self.error(f"parameter {pname} has incomplete type {pty}", ptok)
            p = Symbol(pname, pty, "var", "param", ptok, is_local=True)
            self.scope.names[pname] = p
            f.params.append(p)
        f.body = self.compound(new_scope=False)
        self.pop_scope()
        for label, gtok in f.gotos:
            if label not in f.labels:
                self.error(f"label {label} used but not defined", gtok)
        self.tu.functions.append(f)
        self.func = None

    # ---- declaration specifiers ---------------------------------------------

    def decl_specifiers(self, allow_storage=True):
        spec = DeclSpec()
        counts = {}
        base = None
        const = volatile = False
        tok0 = self.peek()
        while True:
            t = self.peek()
            if t.kind == "kw":
                w = t.text
                if w in STORAGE:
                    if not allow_storage:
                        self.error(f"'{w}' isn't allowed here", t)
                    if spec.storage is not None:
                        self.error("more than one storage class", t)
                    spec.storage = w
                    self.next()
                    continue
                if w in ("inline", "__inline", "__inline__"):
                    spec.inline = True
                    self.next()
                    continue
                if w == "const":
                    const = True
                    self.next()
                    continue
                if w == "volatile":
                    volatile = True
                    self.next()
                    continue
                if w in ("struct", "union"):
                    if base is not None or counts:
                        self.error("two types in one declaration", t)
                    base = self.struct_specifier()
                    continue
                if w == "enum":
                    if base is not None or counts:
                        self.error("two types in one declaration", t)
                    base = self.enum_specifier()
                    continue
                if w in ("float", "double"):
                    self.error("floating point isn't supported", t)
                if w in ("void", "char", "short", "int", "long", "signed", "unsigned", "_Bool"):
                    if base is not None:
                        self.error("two types in one declaration", t)
                    counts[w] = counts.get(w, 0) + 1
                    self.next()
                    continue
                break
            if t.kind == "id" and base is None and not counts and self.is_typedef_name(t):
                base = self.lookup(t.text).ty
                self.next()
                continue
            break
        if base is None:
            base = self.resolve_basic(counts, tok0)
        spec.ty = base.qualified(const, volatile)
        return spec

    def resolve_basic(self, counts, tok):
        c = dict(counts)
        if not c:
            self.warn("type defaults to int", tok)
            return T.INT
        if any(v > 1 for k, v in c.items() if k != "long"):
            self.error("duplicate type specifier", tok)
        if c.get("long", 0) > 1:
            self.error("long long isn't supported", tok)
        signed = c.pop("signed", 0)
        unsigned = c.pop("unsigned", 0)
        if signed and unsigned:
            self.error("both signed and unsigned", tok)
        key = tuple(sorted(c))
        if key == ("void",) and not signed and not unsigned:
            return T.VOID
        if key == ("_Bool",):
            return T.UCHAR
        if key == ("char",):
            return T.UCHAR if unsigned else (T.SCHAR if signed else T.CHAR)
        if key in (("short",), ("int", "short")):
            return T.USHORT if unsigned else T.SHORT
        if key in ((), ("int",)):
            return T.UINT if unsigned else T.INT
        if key in (("long",), ("int", "long")):
            return T.ULONG if unsigned else T.LONG
        self.error("invalid combination of type specifiers", tok)

    def struct_specifier(self):
        kw = self.next()
        is_union = kw.text == "union"
        tag = None
        if self.peek().kind == "id":
            tag = self.next().text
        if self.at("{"):
            info = None
            if tag is not None:
                old = self.scope.tags.get(tag)
                if old is not None:
                    if not isinstance(old, StructInfo) or old.is_union != is_union:
                        self.error(f"{tag} redeclared as a different kind of tag", kw)
                    if old.complete:
                        self.error(f"redefinition of {kw.text} {tag}", kw)
                    info = old
            if info is None:
                info = StructInfo(tag, is_union)
                if tag is not None:
                    self.scope.tags[tag] = info
            self.next()
            members = []
            names = set()
            while not self.accept("}"):
                spec = self.decl_specifiers(allow_storage=False)
                if self.accept(";"):
                    # an anonymous struct/union member (C11): pull its members in
                    if spec.ty.is_struct and spec.ty.info.tag is None:
                        members.append((None, spec.ty))
                        continue
                    self.warn("declaration declares nothing")
                    continue
                while True:
                    name, ty, tok = self.declarator(spec.ty)
                    if self.at(":"):
                        self.error("bit fields aren't supported", tok)
                    if name is None:
                        self.error("member needs a name", tok)
                    if name in names:
                        self.error(f"duplicate member {name}", tok)
                    if ty.is_func:
                        self.error(f"member {name} has function type", tok)
                    if not ty.complete:
                        if ty.is_array and ty.length is None and self.at(";"):
                            ty = array_of(ty.base, 0)       # flexible array member
                        else:
                            self.error(f"member {name} has incomplete type {ty}", tok)
                    names.add(name)
                    members.append((name, ty))
                    if not self.accept(","):
                        break
                self.expect(";")
            T.layout_struct(info, members)
            # flatten anonymous members
            flat = []
            for m in info.members:
                if m.name is None:
                    for sub in m.ty.info.members:
                        flat.append(T.Member(sub.name, sub.ty, m.offset + sub.offset))
                else:
                    flat.append(m)
            info.members = flat
            return Type("struct", info=info)
        if tag is None:
            self.error(f"{kw.text} needs a tag or a body", kw)
        info = self.lookup_tag(tag)
        if info is None or (self.at(";") and tag not in self.scope.tags):
            info = StructInfo(tag, is_union)
            self.scope.tags[tag] = info
        elif not isinstance(info, StructInfo) or info.is_union != is_union:
            self.error(f"{tag} is a different kind of tag", kw)
        return Type("struct", info=info)

    def enum_specifier(self):
        kw = self.next()
        tag = None
        if self.peek().kind == "id":
            tag = self.next().text
        ty = T.INT.copy()
        ty.is_enum = True
        if self.accept("{"):
            if tag is not None:
                self.scope.tags[tag] = "enum"
            val = 0
            while not self.accept("}"):
                t = self.next()
                if t.kind != "id":
                    self.error("enumerator name expected", t)
                if self.accept("="):
                    val = self.const_int()
                if t.text in self.scope.names:
                    self.error(f"{t.text} redeclared", t)
                s = Symbol(t.text, T.INT, "enumconst", None, t)
                s.value = norm(val, T.INT)
                self.scope.names[t.text] = s
                val += 1
                if not self.accept(","):
                    self.expect("}")
                    break
        elif tag is None:
            self.error("enum needs a tag or a body", kw)
        return ty

    # ---- declarators ---------------------------------------------------------

    def declarator(self, ty, abstract=False):
        """Returns (name or None, type, token). With abstract=True the name is
        optional (parameters, type names)."""
        while self.accept("*"):
            const = volatile = False
            while self.peek().kind == "kw" and self.peek().text in ("const", "volatile"):
                if self.next().text == "const":
                    const = True
                else:
                    volatile = True
            ty = pointer_to(ty).qualified(const, volatile)
        tok = self.peek()
        if self.at("(") and self.nested_declarator_follows(abstract):
            start = self.i
            self.next()
            self.declarator(T.INT, abstract)        # skip it to find the suffix
            self.expect(")")
            ty = self.type_suffix(ty)
            end = self.i
            self.i = start + 1
            name, ty, tok = self.declarator(ty, abstract)
            self.expect(")")
            self.i = end
            return name, ty, tok
        name = None
        if self.peek().kind == "id":
            name = self.next().text
        elif not abstract:
            self.error("expected a name in the declaration", tok)
        ty = self.type_suffix(ty)
        return name, ty, tok

    def nested_declarator_follows(self, abstract):
        nxt = self.peek(1)
        if nxt.text in ("*", "(") and nxt.kind == "punct":
            return True
        if nxt.text == "[" and nxt.kind == "punct":
            return abstract
        if nxt.kind == "id" and not self.is_typedef_name(nxt):
            return True
        return False

    def type_suffix(self, ty):
        if self.accept("["):
            if self.accept("]"):
                n = None
            else:
                tok = self.peek()
                n = self.const_int()
                if n < 0:
                    self.error("array size is negative", tok)
                self.expect("]")
            inner = self.type_suffix(ty)
            if inner.is_func:
                self.error("array of functions")
            if not inner.complete and not inner.is_void:
                if inner.is_array:
                    self.error("array of arrays needs all but the first size")
            if inner.is_void:
                self.error("array of void")
            return array_of(inner, n)
        if self.at("("):
            self.next()
            params, names, variadic, proto = self.parameter_list()
            if ty.is_func or ty.is_array:
                self.error("function returning a function or array")
            ft = func_type(ty, params if proto else None, variadic)
            ft.pnames = names
            return ft
        return ty

    def parameter_list(self):
        if self.accept(")"):
            return [], [], False, False
        if self.at("void") and self.at(")", 1):
            self.next()
            self.next()
            return [], [], False, True
        if self.peek().kind == "id" and not self.is_typedef_name(self.peek()):
            self.error("old-style (K&R) parameter lists aren't supported")
        params, names = [], []
        variadic = False
        self.push_scope()       # tags declared in a prototype are local to it
        while True:
            if self.accept("..."):
                variadic = True
                self.expect(")")
                break
            spec = self.decl_specifiers()
            if spec.storage not in (None, "register"):
                self.error("parameters can't have a storage class")
            name, ty, tok = self.declarator(spec.ty, abstract=True)
            if ty.is_array:
                ty = pointer_to(ty.base)
            elif ty.is_func:
                ty = pointer_to(ty)
            if ty.is_void:
                self.error("parameter has type void", tok)
            params.append(ty)
            names.append((name, tok))
            if self.accept(")"):
                break
            self.expect(",")
        self.pop_scope()
        return params, names, variadic, True

    def type_name(self):
        spec = self.decl_specifiers(allow_storage=False)
        name, ty, tok = self.declarator(spec.ty, abstract=True)
        if name is not None:
            self.error("unexpected name in a type", tok)
        return ty

    # ---- initializers --------------------------------------------------------

    def initializer(self, ty):
        if ty.is_array and ty.length is None:
            pass
        elif not ty.complete:
            self.error(f"variable has incomplete type {ty}")
        init = Initializer(ty)
        if self.at("{"):
            self.next()
            ty = self.init_braced(ty, 0, init.items)
        elif ty.is_array and ty.base.kind == "char" and self.peek().kind == "str":
            ty = self.init_string(ty, 0, init.items)
        elif ty.is_array:
            self.error("an array needs a braced initializer")
        else:
            tok = self.peek()
            e = self.assign()
            init.items.append((0, ty, self.convert_assign(e, ty, tok)))
        init.ty = ty
        return init

    def init_string(self, ty, off, items):
        tok = self.peek()
        s = self.string_literal()
        data = s.data
        if ty.length is None:
            ty = array_of(ty.base, len(data))
        n = ty.length
        if len(data) - 1 > n:
            self.warn("initializer string is too long", tok)
        for k in range(min(n, len(data))):
            items.append((off + k, ty.base, N.Num(data[k], T.INT)))
        return ty

    def init_braced(self, ty, off, items):
        """After '{': a braced list for an object of type ty at offset off."""
        if ty.is_array:
            if ty.base.kind == "char" and self.peek().kind == "str":
                ty = self.init_string(ty, off, items)
                self.accept(",")
                self.expect("}")
                return ty
            esz = ty.base.size
            k = 0
            hi = 0
            while not self.at("}"):
                if self.at("["):
                    self.next()
                    k = self.const_int()
                    self.expect("]")
                    self.expect("=")
                    if k < 0 or (ty.length is not None and k >= ty.length):
                        self.error("array designator out of range")
                if ty.length is not None and k >= ty.length:
                    self.error("too many initializers for the array")
                self.init_elem(ty.base, off + k * esz, items)
                k += 1
                hi = max(hi, k)
                if not self.accept(","):
                    break
            self.expect("}")
            if ty.length is None:
                ty = array_of(ty.base, hi)
            return ty
        if ty.is_struct:
            members = ty.info.members
            k = 0
            while not self.at("}"):
                if self.at("."):
                    self.next()
                    t = self.next()
                    for n, m in enumerate(members):
                        if m.name == t.text:
                            k = n
                            break
                    else:
                        self.error(f"no member named {t.text}", t)
                    self.expect("=")
                if k >= len(members) or (ty.info.is_union and k > 0 and not self.at("}") and False):
                    self.error("too many initializers for the struct")
                m = members[k]
                self.init_elem(m.ty, off + m.offset, items)
                k += 1
                if ty.info.is_union:
                    k = len(members)
                if not self.accept(","):
                    break
            self.expect("}")
            return ty
        # scalar in braces
        self.init_elem(ty, off, items)
        self.accept(",")
        self.expect("}")
        return ty

    def init_elem(self, ty, off, items):
        """One element of a braced list (braces around sub-aggregates may be
        left out)."""
        if self.at("{"):
            self.next()
            self.init_braced(ty, off, items)
            return
        if ty.is_array:
            if ty.base.kind == "char" and self.peek().kind == "str":
                self.init_string(ty, off, items)
                return
            esz = ty.base.size
            for k in range(ty.length or 0):
                self.init_elem(ty.base, off + k * esz, items)
                if k + 1 < (ty.length or 0) and self.more_elided():
                    continue
                break
            return
        if ty.is_struct:
            save = self.i
            tok = self.peek()
            e = self.assign()
            if e.ty.is_struct and e.ty.info is ty.info:
                items.append((off, ty, e))
                return
            self.i = save
            members = ty.info.members
            for k, m in enumerate(members):
                self.init_elem(m.ty, off + m.offset, items)
                if ty.info.is_union:
                    break
                if k + 1 < len(members) and self.more_elided():
                    continue
                break
            return
        tok = self.peek()
        e = self.assign()
        items.append((off, ty, self.convert_assign(e, ty, tok)))

    def more_elided(self):
        if self.at(",") and not self.at("}", 1) and not self.at(".", 1) and not self.at("[", 1):
            self.next()
            return True
        return False

    # ---- statements --------------------------------------------------------

    def compound(self, new_scope=True):
        tok = self.expect("{")
        if new_scope:
            self.push_scope()
        items = []
        while not self.accept("}"):
            if self.peek().kind == "eof":
                self.error("unexpected end of file in a block")
            if self.is_type_start() and not (self.peek().kind == "id" and self.at(":", 1)):
                items.extend(self.local_declaration())
            else:
                items.append(self.statement())
        if new_scope:
            self.pop_scope()
        return N.Compound(items, tok)

    def local_declaration(self):
        spec = self.decl_specifiers()
        out = []
        if self.accept(";"):
            return out
        while True:
            name, ty, tok = self.declarator(spec.ty)
            if spec.storage == "typedef":
                self.declare_typedef(name, ty, tok)
            elif ty.is_func:
                if spec.storage not in (None, "extern"):
                    self.error("block-scope function declarations can only be extern", tok)
                self.declare_function(name, ty, "extern", tok, local=True)
            elif spec.storage == "extern":
                g = self.declare_global(name, ty, "extern", tok)
                self.scope.names[name] = g
            elif spec.storage == "static":
                if name in self.scope.names:
                    self.error(f"{name} redeclared in this scope", tok)
                self.static_count += 1
                sym = Symbol(name, ty, "var", "static", tok)
                sym.asm_name = f"{self.func.sym.name}_{name}_{self.static_count}"
                sym.defined = True
                self.scope.names[name] = sym
                if self.accept("="):
                    sym.init = self.initializer(ty)
                    sym.ty = sym.init.ty
                elif not ty.complete:
                    self.error(f"{name} has incomplete type {ty}", tok)
                self.tu.globals.append(sym)
            else:
                if name in self.scope.names:
                    self.error(f"{name} redeclared in this scope", tok)
                sym = Symbol(name, ty, "var", "auto", tok, is_local=True)
                self.scope.names[name] = sym
                init = None
                if self.accept("="):
                    init = self.initializer(ty)
                    sym.ty = init.ty
                if not sym.ty.complete:
                    self.error(f"{name} has incomplete type {sym.ty}", tok)
                self.func.locals.append(sym)
                out.append(N.Decl(sym, init, tok))
            if self.accept(","):
                continue
            self.expect(";")
            return out

    def statement(self):
        t = self.peek()
        if t.kind == "id" and self.at(":", 1):
            self.next()
            self.next()
            if t.text in self.func.labels:
                self.error(f"label {t.text} defined twice", t)
            self.func.labels[t.text] = True
            return N.Label(t.text, self.statement(), t)
        if t.kind == "punct" and t.text == "{":
            return self.compound()
        if t.kind == "punct" and t.text == ";":
            self.next()
            return N.Empty(t)
        if t.kind != "kw":
            e = self.expr()
            self.expect(";")
            return N.ExprStmt(e, t)
        w = t.text
        self.next()
        if w == "if":
            self.expect("(")
            c = self.condition()
            self.expect(")")
            then = self.statement()
            els = self.statement() if self.accept("else") else None
            return N.If(c, then, els, t)
        if w == "while":
            self.expect("(")
            c = self.condition()
            self.expect(")")
            self.loops += 1
            body = self.statement()
            self.loops -= 1
            return N.While(c, body, t)
        if w == "do":
            self.loops += 1
            body = self.statement()
            self.loops -= 1
            self.expect("while")
            self.expect("(")
            c = self.condition()
            self.expect(")")
            self.expect(";")
            return N.DoWhile(body, c, t)
        if w == "for":
            self.expect("(")
            self.push_scope()
            init = None
            if self.is_type_start():
                init = N.Compound(self.local_declaration(), t)
            else:
                if not self.at(";"):
                    init = N.ExprStmt(self.expr(), t)
                self.expect(";")
            c = None if self.at(";") else self.condition()
            self.expect(";")
            step = None if self.at(")") else self.expr()
            self.expect(")")
            self.loops += 1
            body = self.statement()
            self.loops -= 1
            self.pop_scope()
            return N.For(init, c, step, body, t)
        if w == "switch":
            self.expect("(")
            e = self.rvalue(self.expr())
            self.expect(")")
            if not e.ty.is_integer:
                self.error("switch needs an integer", t)
            e = self.convert(e, self.promote(e.ty))
            sw = N.Switch(e, t)
            self.switches.append(sw)
            self.loops += 1
            sw.body = self.statement()
            self.loops -= 1
            self.switches.pop()
            return sw
        if w == "case":
            if not self.switches:
                self.error("case outside a switch", t)
            sw = self.switches[-1]
            v = norm(self.const_int(), sw.e.ty)
            self.expect(":")
            for c in sw.cases:
                if c.value == v:
                    self.error(f"duplicate case value {v}", t)
            c = N.Case(v, None, t)
            sw.cases.append(c)
            c.stmt = self.statement()
            return c
        if w == "default":
            if not self.switches:
                self.error("default outside a switch", t)
            self.expect(":")
            sw = self.switches[-1]
            if sw.default is not None:
                self.error("two defaults in one switch", t)
            d = N.Default(None, t)
            sw.default = d
            d.stmt = self.statement()
            return d
        if w == "break":
            self.expect(";")
            if not self.loops:
                self.error("break outside a loop or switch", t)
            return N.Break(t)
        if w == "continue":
            self.expect(";")
            return N.Continue(t)
        if w == "return":
            rt = self.func.sym.ty.ret
            if self.accept(";"):
                if not rt.is_void:
                    self.warn("return without a value in a function returning a value", t)
                return N.Return(None, t)
            tok = self.peek()
            e = self.expr()
            self.expect(";")
            if rt.is_void:
                if not e.ty.is_void:
                    self.warn("return with a value in a void function", t)
                return N.Return(e, t)
            return N.Return(self.convert_assign(e, rt, tok), t)
        if w == "goto":
            lab = self.next()
            if lab.kind != "id":
                self.error("label expected", lab)
            self.expect(";")
            self.func.gotos.append((lab.text, lab))
            return N.Goto(lab.text, t)
        self.i -= 1
        e = self.expr()
        self.expect(";")
        return N.ExprStmt(e, t)

    def condition(self):
        tok = self.peek()
        e = self.rvalue(self.expr())
        if not e.ty.is_scalar:
            self.error(f"condition has type {e.ty}, not a number or pointer", tok)
        return e

    # ---- expressions: typing helpers --------------------------------------

    def rvalue(self, e):
        """Array and function designators decay to pointers."""
        if e.ty.is_array:
            return N.Decay(e, pointer_to(e.ty.base), e.tok)
        if e.ty.is_func:
            return N.Decay(e, pointer_to(e.ty), e.tok)
        return e

    def promote(self, ty):
        if ty.is_integer and ty.kind in ("char", "short"):
            return T.INT
        if ty.is_enum:
            return T.INT
        return ty.unqualified()

    def arith_type(self, a, b):
        a, b = self.promote(a), self.promote(b)
        if a.kind == "long" or b.kind == "long":
            if a.unsigned or b.unsigned:
                return T.ULONG
            return T.LONG
        if a.unsigned or b.unsigned:
            return T.UINT
        return T.INT

    def convert(self, e, ty):
        if T.same_type(e.ty, ty, False) and e.ty.kind == ty.kind:
            return e
        if isinstance(e, N.Num) and ty.is_scalar:
            return N.Num(norm(e.value, ty), ty, e.tok)
        return N.Cast(e, ty, e.tok)

    def is_null(self, e):
        while isinstance(e, N.Cast) and (e.ty.is_integer or (e.ty.is_pointer and e.ty.base.is_void)):
            e = e.e
        return isinstance(e, N.Num) and e.value == 0

    def convert_assign(self, e, ty, tok):
        """Conversion as if by assignment, with the usual checks."""
        e = self.rvalue(e)
        ty = ty.unqualified()
        if ty.is_struct:
            if not (e.ty.is_struct and e.ty.info is ty.info):
                self.error(f"can't assign {e.ty} to {ty}", tok)
            return e
        if e.ty.is_void:
            self.error("void value used", tok)
        if ty.is_pointer:
            if e.ty.is_pointer:
                a, b = ty.base, e.ty.base
                if not (a.is_void or b.is_void or T.same_type(a, b, False)):
                    self.warn(f"assignment from incompatible pointer type ({e.ty} to {ty})", tok)
            elif e.ty.is_integer:
                if not self.is_null(e):
                    self.warn(f"assignment makes a pointer from an integer", tok)
            else:
                self.error(f"can't convert {e.ty} to {ty}", tok)
        elif ty.is_integer:
            if e.ty.is_pointer:
                self.warn("assignment makes an integer from a pointer", tok)
            elif not e.ty.is_integer:
                self.error(f"can't convert {e.ty} to {ty}", tok)
        elif ty.is_void:
            return e
        return self.convert(e, ty)

    def check_scalar(self, e, what, tok):
        if not e.ty.is_scalar:
            self.error(f"{what} needs a number or pointer, not {e.ty}", tok)

    def check_int(self, e, what, tok):
        if not e.ty.is_integer:
            self.error(f"{what} needs an integer, not {e.ty}", tok)

    def check_lvalue(self, e, tok):
        if not e.lvalue or e.ty.is_array or e.ty.is_func:
            self.error("needs an lvalue (something that can be assigned)", tok)
        if e.ty.const:
            self.error("assignment to a const object", tok)
        if e.ty.is_struct and any(m.ty.const for m in e.ty.info.members):
            self.error("assignment to a struct with const members", tok)

    def make_binary(self, op, l, r, tok):
        l = self.rvalue(l)
        r = self.rvalue(r)
        if op in ("*", "/", "%"):
            self.check_int(l, op, tok)
            self.check_int(r, op, tok)
            ty = self.arith_type(l.ty, r.ty)
            return self.fold(N.Binary(op, self.convert(l, ty), self.convert(r, ty), ty, tok))
        if op in ("&", "|", "^"):
            self.check_int(l, op, tok)
            self.check_int(r, op, tok)
            ty = self.arith_type(l.ty, r.ty)
            return self.fold(N.Binary(op, self.convert(l, ty), self.convert(r, ty), ty, tok))
        if op in ("<<", ">>"):
            self.check_int(l, op, tok)
            self.check_int(r, op, tok)
            ty = self.promote(l.ty)
            return self.fold(N.Binary(op, self.convert(l, ty), self.convert(r, self.promote(r.ty)), ty, tok))
        if op == "+":
            if l.ty.is_integer and r.ty.is_pointer:
                l, r = r, l
            if l.ty.is_pointer:
                self.check_int(r, "pointer +", tok)
                self.check_complete_pointee(l.ty, tok)
                return N.Binary("padd", l, self.convert(r, T.INT if not r.ty.unsigned else T.UINT), l.ty, tok)
            self.check_int(l, op, tok)
            self.check_int(r, op, tok)
            ty = self.arith_type(l.ty, r.ty)
            return self.fold(N.Binary(op, self.convert(l, ty), self.convert(r, ty), ty, tok))
        if op == "-":
            if l.ty.is_pointer and r.ty.is_pointer:
                if not T.same_type(l.ty.base, r.ty.base, False):
                    self.warn("subtracting pointers to different types", tok)
                self.check_complete_pointee(l.ty, tok)
                return N.Binary("pdiff", l, r, T.INT, tok)
            if l.ty.is_pointer:
                self.check_int(r, "pointer -", tok)
                self.check_complete_pointee(l.ty, tok)
                return N.Binary("psub", l, self.convert(r, T.INT if not r.ty.unsigned else T.UINT), l.ty, tok)
            self.check_int(l, op, tok)
            self.check_int(r, op, tok)
            ty = self.arith_type(l.ty, r.ty)
            return self.fold(N.Binary(op, self.convert(l, ty), self.convert(r, ty), ty, tok))
        if op in ("==", "!=", "<", ">", "<=", ">="):
            if l.ty.is_integer and r.ty.is_integer:
                ty = self.arith_type(l.ty, r.ty)
                return self.fold(N.Binary(op, self.convert(l, ty), self.convert(r, ty), T.INT, tok))
            if l.ty.is_pointer and r.ty.is_pointer:
                a, b = l.ty.base, r.ty.base
                if not (a.is_void or b.is_void or T.same_type(a, b, False)):
                    self.warn("comparing pointers to different types", tok)
                return N.Binary(op, l, r, T.INT, tok)
            if l.ty.is_pointer and r.ty.is_integer:
                if not self.is_null(r):
                    self.warn("comparing a pointer with an integer", tok)
                return N.Binary(op, l, self.convert(r, l.ty), T.INT, tok)
            if r.ty.is_pointer and l.ty.is_integer:
                if not self.is_null(l):
                    self.warn("comparing a pointer with an integer", tok)
                return N.Binary(op, self.convert(l, r.ty), r, T.INT, tok)
            self.error(f"can't compare {l.ty} and {r.ty}", tok)
        if op in ("&&", "||"):
            self.check_scalar(l, op, tok)
            self.check_scalar(r, op, tok)
            return self.fold(N.Binary(op, l, r, T.INT, tok))
        raise AssertionError(op)

    def check_complete_pointee(self, ty, tok):
        b = ty.base
        if b.is_func or (not b.complete and not b.is_void):
            self.error(f"arithmetic on a pointer to an incomplete type {b}", tok)

    def fold(self, e):
        """Fold integer constant expressions as they're built."""
        if isinstance(e, N.Binary) and isinstance(e.l, N.Num) and isinstance(e.r, N.Num):
            try:
                return N.Num(self.eval_int(e), e.ty, e.tok)
            except NotConstant:
                return e
        return e

    # ---- expressions: grammar ----------------------------------------------

    def expr(self):
        e = self.assign()
        while self.at(","):
            tok = self.next()
            r = self.assign()
            r = self.rvalue(r)
            e = N.Binary(",", e, r, r.ty, tok)
        return e

    def assign(self):
        l = self.conditional()
        t = self.peek()
        if t.kind == "punct" and t.text in ASSIGN_OPS:
            self.next()
            r = self.assign()
            return self.make_assign(t.text, l, r, t)
        return l

    def make_assign(self, op, l, r, tok):
        self.check_lvalue(l, tok)
        if op == "=":
            return N.Assign(None, l, self.convert_assign(r, l.ty, tok), l.ty.unqualified(), None, tok)
        bop = op[:-1]
        r = self.rvalue(r)
        if l.ty.is_pointer and bop in ("+", "-"):
            self.check_int(r, op, tok)
            self.check_complete_pointee(l.ty, tok)
            return N.Assign("padd" if bop == "+" else "psub", l, self.convert(r, T.INT),
                            l.ty.unqualified(), l.ty.unqualified(), tok)
        self.check_int(l, op, tok)
        self.check_int(r, op, tok)
        if bop in ("<<", ">>"):
            cty = self.promote(l.ty)
            r = self.convert(r, self.promote(r.ty))
        else:
            cty = self.arith_type(l.ty, r.ty)
            r = self.convert(r, cty)
        return N.Assign(bop, l, r, l.ty.unqualified(), cty, tok)

    def conditional(self):
        c = self.binary(0)
        if not self.at("?"):
            return c
        tok = self.next()
        c = self.rvalue(c)
        self.check_scalar(c, "?:", tok)
        a = self.rvalue(self.expr())
        self.expect(":")
        b = self.rvalue(self.conditional())
        if a.ty.is_integer and b.ty.is_integer:
            ty = self.arith_type(a.ty, b.ty)
            a, b = self.convert(a, ty), self.convert(b, ty)
        elif a.ty.is_void or b.ty.is_void:
            ty = T.VOID
        elif a.ty.is_struct and b.ty.is_struct and a.ty.info is b.ty.info:
            ty = a.ty.unqualified()
        elif a.ty.is_pointer and b.ty.is_pointer:
            if a.ty.base.is_void:
                ty = a.ty
            elif b.ty.base.is_void:
                ty = b.ty
            else:
                if not T.same_type(a.ty.base, b.ty.base, False):
                    self.warn("pointer type mismatch in ?:", tok)
                ty = a.ty
            a, b = self.convert(a, ty), self.convert(b, ty)
        elif a.ty.is_pointer and b.ty.is_integer:
            ty = a.ty
            b = self.convert(b, ty)
        elif b.ty.is_pointer and a.ty.is_integer:
            ty = b.ty
            a = self.convert(a, ty)
        else:
            self.error(f"type mismatch in ?: ({a.ty} and {b.ty})", tok)
        if isinstance(c, N.Num) and ty.is_scalar:
            return a if c.value else b
        return N.Cond(c, a, b, ty, tok)

    BINARY = [["||"], ["&&"], ["|"], ["^"], ["&"], ["==", "!="], ["<", ">", "<=", ">="],
              ["<<", ">>"], ["+", "-"], ["*", "/", "%"]]

    def binary(self, level):
        if level == len(self.BINARY):
            return self.cast()
        l = self.binary(level + 1)
        ops = self.BINARY[level]
        while True:
            t = self.peek()
            if t.kind == "punct" and t.text in ops:
                self.next()
                r = self.binary(level + 1)
                l = self.make_binary(t.text, l, r, t)
            else:
                return l

    def cast(self):
        if self.at("(") and self.is_type_start(1):
            tok = self.next()
            ty = self.type_name()
            self.expect(")")
            if self.at("{"):
                self.error("compound literals aren't supported", tok)
            e = self.rvalue(self.cast())
            if ty.is_void:
                return N.Cast(e, T.VOID, tok)
            if not ty.is_scalar:
                self.error(f"can't cast to {ty}", tok)
            if not e.ty.is_scalar:
                self.error(f"can't cast {e.ty} to {ty}", tok)
            out = self.convert(e, ty.unqualified())
            if out is e and not isinstance(e, N.Num):
                out = N.Cast(e, ty.unqualified(), tok)      # a cast is never an lvalue
            return out
        return self.unary()

    def unary(self):
        t = self.peek()
        if t.kind == "punct":
            w = t.text
            if w in ("++", "--"):
                self.next()
                e = self.unary()
                return self.make_incdec(e, 1 if w == "++" else -1, False, t)
            if w in ("+", "-", "~", "!"):
                self.next()
                e = self.rvalue(self.cast())
                if w == "!":
                    self.check_scalar(e, "!", t)
                    if isinstance(e, N.Num):
                        return N.Num(int(e.value == 0), T.INT, t)
                    return N.Unary("lnot", e, T.INT, t)
                self.check_int(e, w, t)
                ty = self.promote(e.ty)
                e = self.convert(e, ty)
                if w == "+":
                    return e
                if isinstance(e, N.Num):
                    v = -e.value if w == "-" else ~e.value
                    return N.Num(norm(v, ty), ty, t)
                return N.Unary("neg" if w == "-" else "bitnot", e, ty, t)
            if w == "*":
                self.next()
                e = self.rvalue(self.cast())
                if not e.ty.is_pointer:
                    self.error(f"can't dereference {e.ty}", t)
                return N.Unary("deref", e, e.ty.base, t)
            if w == "&":
                self.next()
                e = self.cast()
                if isinstance(e, N.Unary) and e.op == "deref":
                    return e.e
                if e.ty.is_func and isinstance(e, N.Ident):
                    return N.Decay(e, pointer_to(e.ty), t)
                if not e.lvalue:
                    self.error("can't take the address of this", t)
                if isinstance(e, N.Ident):
                    e.sym.address_taken = True
                return N.Unary("addr", e, pointer_to(e.ty), t)
        if t.kind == "kw" and t.text == "sizeof":
            self.next()
            if self.at("(") and self.is_type_start(1):
                self.next()
                ty = self.type_name()
                self.expect(")")
            else:
                ty = self.unary().ty
            if ty.is_func or (not ty.complete and not ty.is_void):
                self.error(f"sizeof of incomplete type {ty}", t)
            return N.Num(ty.size, T.UINT, t)
        return self.postfix()

    def make_incdec(self, e, delta, post, tok):
        self.check_lvalue(e, tok)
        if e.ty.is_pointer:
            self.check_complete_pointee(e.ty, tok)
        elif not e.ty.is_integer:
            self.error(f"can't increment {e.ty}", tok)
        return N.IncDec(e, delta, post, tok)

    def postfix(self):
        e = self.primary()
        while True:
            t = self.peek()
            if t.kind != "punct":
                return e
            w = t.text
            if w == "[":
                self.next()
                idx = self.expr()
                self.expect("]")
                p = self.make_binary("+", e, idx, t)
                if not p.ty.is_pointer:
                    self.error("subscript of something that isn't an array or pointer", t)
                e = N.Unary("deref", p, p.ty.base, t)
            elif w == "(":
                self.next()
                e = self.call(e, t)
            elif w == ".":
                self.next()
                e = self.member(e, t)
            elif w == "->":
                self.next()
                p = self.rvalue(e)
                if not p.ty.is_pointer or not p.ty.base.is_struct:
                    self.error(f"-> on {p.ty}, not a pointer to a struct", t)
                e = self.member(N.Unary("deref", p, p.ty.base, t), t)
            elif w in ("++", "--"):
                self.next()
                e = self.make_incdec(e, 1 if w == "++" else -1, True, t)
            else:
                return e

    def member(self, e, tok):
        name = self.next()
        if name.kind != "id":
            self.error("member name expected", name)
        if not e.ty.is_struct:
            self.error(f"member access on {e.ty}, which isn't a struct", tok)
        if not e.ty.info.complete:
            self.error(f"{e.ty} is incomplete", tok)
        m = e.ty.info.member(name.text)
        if m is None:
            self.error(f"{e.ty} has no member {name.text}", name)
        ty = m.ty.qualified(e.ty.const, e.ty.volatile)
        node = N.Member(e, m, ty, tok)
        return node

    def call(self, fn, tok):
        args = []
        if not self.accept(")"):
            while True:
                args.append(self.assign())
                if self.accept(")"):
                    break
                self.expect(",")
        f = self.rvalue(fn)
        if f.ty.is_pointer and f.ty.base.is_func:
            fty = f.ty.base
        else:
            self.error(f"called object has type {fn.ty}, not a function", tok)
        if isinstance(fn, N.Ident) and fn.sym.kind == "func":
            fn.sym.used = True
        out = []
        if fty.params is not None:
            n = len(fty.params)
            if len(args) < n or (len(args) > n and not fty.variadic):
                self.error(f"function takes {n} argument{'s' * (n != 1)}, got {len(args)}", tok)
            for a, pt in zip(args, fty.params):
                out.append(self.convert_assign(a, pt, a.tok))
            rest = args[n:]
        else:
            rest = args
        for a in rest:
            a = self.rvalue(a)
            if a.ty.is_void:
                self.error("void value used as an argument", a.tok)
            if a.ty.is_integer:
                a = self.convert(a, self.promote(a.ty))
            out.append(a)
        if not fty.ret.is_void and not fty.ret.complete:
            self.error(f"calling a function returning incomplete type {fty.ret}", tok)
        return N.Call(f, out, fty, tok)

    def primary(self):
        t = self.peek()
        if t.kind == "punct" and t.text == "(":
            self.next()
            e = self.expr()
            self.expect(")")
            return e
        if t.kind == "num":
            self.next()
            return self.number(t)
        if t.kind == "char":
            self.next()
            return N.Num(norm(char_value(t), T.INT), T.INT, t)
        if t.kind == "str":
            return self.string_literal()
        if t.kind == "id":
            self.next()
            if t.text == "__builtin_va_start":
                self.expect("(")
                self.expect(")")
                if self.func is None or not self.func.sym.ty.variadic:
                    self.error("va_start in a function that isn't variadic", t)
                return N.VaStart(pointer_to(T.CHAR), t)
            if t.text == "__func__":
                name = self.func.sym.name if self.func else ""
                data = name.encode() + b"\0"
                return N.Str(data, array_of(T.CHAR, len(data)), t)
            sym = self.lookup(t.text)
            if sym is None:
                if self.at("("):
                    self.warn(f"implicit declaration of function {t.text}", t)
                    ty = func_type(T.INT, None)
                    g = self.scope
                    self.declare_function(t.text, ty, None, t)
                    sym = self.tu.funcs[t.text]
                else:
                    self.error(f"{t.text} is undeclared", t)
            if sym.kind == "enumconst":
                return N.Num(sym.value, T.INT, t)
            if sym.kind == "typedef":
                self.error(f"unexpected type name {t.text}", t)
            sym.used = True
            return N.Ident(sym, t)
        if t.kind == "eof":
            self.error("unexpected end of file", t)
        self.error(f"unexpected {t.text!r}", t)

    def number(self, t):
        v, u, l, dec = parse_int(t)
        if dec and not u:
            cands = [T.INT, T.LONG, T.ULONG] if not l else [T.LONG, T.ULONG]
        elif not u:
            cands = [T.INT, T.UINT, T.LONG, T.ULONG] if not l else [T.LONG, T.ULONG]
        else:
            cands = [T.UINT, T.ULONG] if not l else [T.ULONG]
        for ty in cands:
            hi = (1 << 32) if ty.unsigned else (1 << 31)
            if v < hi:
                return N.Num(v, ty, t)
        self.warn("integer constant is too large", t)
        return N.Num(norm(v, T.ULONG), T.ULONG, t)

    def string_literal(self):
        t = self.peek()
        data = []
        while self.peek().kind == "str":
            s = self.next()
            body = s.text[2:-1] if s.text.startswith("L") else s.text[1:-1]
            data.extend(unescape(body, s))
        data.append(0)
        return N.Str(bytes(data), array_of(T.CHAR, len(data)), t)

    # ---- constant expressions ------------------------------------------------

    def const_int(self):
        tok = self.peek()
        e = self.conditional()
        try:
            v = self.eval_int(e)
        except NotConstant:
            self.error("integer constant expression expected", tok)
        return v

    def eval_int(self, e):
        return eval_int(e)


def eval_int(e):
    """Evaluate an integer constant expression (raises NotConstant)."""
    if isinstance(e, N.Num):
        return e.value
    if isinstance(e, N.Cast):
        if not (e.ty.is_integer or e.ty.is_pointer):
            raise NotConstant()
        return norm(eval_int(e.e), e.ty)
    if isinstance(e, N.Unary):
        v = eval_int(e.e)
        if e.op == "neg":
            return norm(-v, e.ty)
        if e.op == "bitnot":
            return norm(~v, e.ty)
        if e.op == "lnot":
            return int(v == 0)
        raise NotConstant()
    if isinstance(e, N.Cond):
        return eval_int(e.a) if eval_int(e.c) else eval_int(e.b)
    if isinstance(e, N.Binary):
        op = e.op
        if op == "&&":
            return int(bool(eval_int(e.l)) and bool(eval_int(e.r)))
        if op == "||":
            return int(bool(eval_int(e.l)) or bool(eval_int(e.r)))
        if op in ("padd", "psub", "pdiff", ","):
            raise NotConstant()
        a = eval_int(e.l)
        b = eval_int(e.r)
        ty = e.l.ty
        if op in ("==", "!=", "<", ">", "<=", ">="):
            return int({"==": a == b, "!=": a != b, "<": a < b, ">": a > b,
                        "<=": a <= b, ">=": a >= b}[op])
        if op in ("/", "%"):
            if b == 0:
                raise NotConstant()
            q = abs(a) // abs(b)
            if (a < 0) != (b < 0):
                q = -q
            return norm(q if op == "/" else a - q * b, e.ty)
        if op == "<<":
            return norm(a << (b & 31), e.ty)
        if op == ">>":
            return norm(a >> (b & 31), e.ty)
        v = {"+": a + b, "-": a - b, "*": a * b, "&": a & b, "|": a | b, "^": a ^ b}[op]
        return norm(v, e.ty)
    raise NotConstant()


def parse(tokens):
    return Parser(tokens).parse()
