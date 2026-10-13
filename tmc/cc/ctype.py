"""C types for the 32-bit target: char 8, short 16, int and long 32,
pointers 32 bits. Plain char is unsigned (the machine's byte loads
zero-extend). _Bool is an unsigned char that only ever holds 0 or 1:
converting a value to it gives 1 for anything but 0."""


class StructInfo:
    """Shared by every (qualified) copy of a struct or union type."""

    def __init__(self, tag, is_union):
        self.tag = tag
        self.is_union = is_union
        self.members = None      # list of Member once complete
        self.size = 0
        self.align = 1

    @property
    def complete(self):
        return self.members is not None

    def member(self, name):
        for m in self.members or ():
            if m.name == name:
                return m
        return None


class Member:
    def __init__(self, name, ty, offset):
        self.name = name
        self.ty = ty
        self.offset = offset


class Type:
    """kind: void char short int long ptr array func struct.
    Integer kinds have `unsigned` (and `is_bool` for _Bool, a char); ptr
    and array have `base`; array has `length` (None if unknown); func has
    `ret`, `params` (list of types or None if unprototyped) and `variadic`;
    struct has `info`."""

    __slots__ = ("kind", "unsigned", "base", "length", "ret", "params", "variadic",
                 "info", "const", "volatile", "is_enum", "explicit_signed", "is_bool", "pnames")

    def __init__(self, kind, unsigned=False, base=None, length=None, ret=None, params=None,
                 variadic=False, info=None):
        self.kind = kind
        self.unsigned = unsigned
        self.base = base
        self.length = length
        self.ret = ret
        self.params = params
        self.variadic = variadic
        self.info = info
        self.const = False
        self.volatile = False
        self.is_enum = False
        self.explicit_signed = False
        self.is_bool = False
        self.pnames = None          # func: parameter names and tokens, from the declarator

    def copy(self):
        t = Type(self.kind, self.unsigned, self.base, self.length, self.ret, self.params,
                 self.variadic, self.info)
        t.const, t.volatile, t.is_enum, t.explicit_signed, t.is_bool = \
            self.const, self.volatile, self.is_enum, self.explicit_signed, self.is_bool
        t.pnames = self.pnames
        return t

    def qualified(self, const=False, volatile=False):
        if (const and not self.const) or (volatile and not self.volatile):
            t = self.copy()
            t.const |= const
            t.volatile |= volatile
            return t
        return self

    def unqualified(self):
        if self.const or self.volatile:
            t = self.copy()
            t.const = t.volatile = False
            return t
        return self

    # ---- classification ----

    @property
    def is_integer(self):
        return self.kind in ("char", "short", "int", "long")

    @property
    def is_arith(self):
        return self.is_integer

    @property
    def is_pointer(self):
        return self.kind == "ptr"

    @property
    def is_scalar(self):
        return self.is_integer or self.kind == "ptr"

    @property
    def is_struct(self):
        return self.kind == "struct"

    @property
    def is_func(self):
        return self.kind == "func"

    @property
    def is_array(self):
        return self.kind == "array"

    @property
    def is_void(self):
        return self.kind == "void"

    @property
    def size(self):
        k = self.kind
        if k == "char":
            return 1
        if k == "short":
            return 2
        if k in ("int", "long", "ptr"):
            return 4
        if k == "array":
            return self.base.size * (self.length or 0)
        if k == "struct":
            return self.info.size
        if k == "void":
            return 1                # GNU: sizeof(void) == 1, for void * arithmetic
        return 1

    @property
    def align(self):
        k = self.kind
        if k == "array":
            return self.base.align
        if k == "struct":
            return self.info.align
        if k in ("void", "func"):
            return 1
        return self.size

    @property
    def complete(self):
        if self.kind == "void":
            return False
        if self.kind == "array":
            return self.length is not None
        if self.kind == "struct":
            return self.info.complete
        return True

    @property
    def signed(self):
        return self.is_integer and not self.unsigned

    def __eq__(self, other):
        return isinstance(other, Type) and same_type(self, other)

    def __hash__(self):
        return hash(self.kind)

    def __str__(self):
        return type_name(self)

    __repr__ = __str__


def same_type(a, b, quals=True):
    if a is b:
        return True
    if a.kind != b.kind:
        return False
    if quals and (a.const != b.const or a.volatile != b.volatile):
        return False
    k = a.kind
    if k in ("char", "short", "int", "long"):
        return a.unsigned == b.unsigned and (k != "char" or (a.explicit_signed, a.is_bool)
                                             == (b.explicit_signed, b.is_bool))
    if k == "ptr":
        return same_type(a.base, b.base)
    if k == "array":
        return same_type(a.base, b.base) and (a.length is None or b.length is None or a.length == b.length)
    if k == "struct":
        return a.info is b.info
    if k == "func":
        if not same_type(a.ret, b.ret):
            return False
        if a.params is None or b.params is None:
            return True
        return (len(a.params) == len(b.params) and a.variadic == b.variadic
                and all(same_type(x, y, False) for x, y in zip(a.params, b.params)))
    return True


def type_name(t, inner=""):
    q = ("const " if t.const else "") + ("volatile " if t.volatile else "")
    k = t.kind
    if t.is_bool:
        return f"{q}_Bool{' ' + inner if inner else ''}"
    if k in ("char", "short", "int", "long"):
        sign = "unsigned " if t.unsigned else ("signed " if k == "char" and t.explicit_signed else "")
        return f"{q}{sign}{k}{' ' + inner if inner else ''}"
    if k == "void":
        return f"{q}void{' ' + inner if inner else ''}"
    if k == "struct":
        kw = "union" if t.info.is_union else "struct"
        return f"{q}{kw} {t.info.tag or '<anonymous>'}{' ' + inner if inner else ''}"
    if k == "ptr":
        pq = (" const" if t.const else "") + (" volatile" if t.volatile else "")
        s = f"*{pq.strip()}{' ' if pq else ''}{inner}"
        if t.base.kind in ("array", "func"):
            s = f"({s})"
        return type_name(t.base, s)
    if k == "array":
        return type_name(t.base, f"{inner}[{t.length if t.length is not None else ''}]")
    if k == "func":
        if t.params is None:
            ps = ""
        else:
            ps = ", ".join(type_name(p) for p in t.params) or "void"
            if t.variadic:
                ps += ", ..."
        return type_name(t.ret, f"{inner}({ps})")
    return k


VOID = Type("void")
CHAR = Type("char", unsigned=True)
SCHAR = Type("char")
SCHAR.explicit_signed = True
UCHAR = Type("char", unsigned=True)
UCHAR.explicit_signed = True        # 'unsigned char', distinct spelling from plain char
BOOL = Type("char", unsigned=True)
BOOL.explicit_signed = True
BOOL.is_bool = True
SHORT = Type("short")
USHORT = Type("short", unsigned=True)
INT = Type("int")
UINT = Type("int", unsigned=True)
LONG = Type("long")
ULONG = Type("long", unsigned=True)


def pointer_to(t):
    return Type("ptr", base=t)


def array_of(t, n):
    return Type("array", base=t, length=n)


def func_type(ret, params, variadic=False):
    return Type("func", ret=ret, params=params, variadic=variadic)


def layout_struct(info, members, tok=None):
    """members: list of (name, type). Fills in offsets, size and alignment."""
    out = []
    off = 0
    size = 0
    align = 1
    for name, ty in members:
        a = ty.align
        align = max(align, a)
        if info.is_union:
            out.append(Member(name, ty, 0))
            size = max(size, ty.size)
        else:
            off = (off + a - 1) // a * a
            out.append(Member(name, ty, off))
            off += ty.size
            size = off
    size = (size + align - 1) // align * align
    info.members = out
    info.size = size
    info.align = align
