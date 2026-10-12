"""Lower the typed C syntax tree to IR.

Every local variable gets a stack slot and every access is a load or store;
mem2reg (tmc.ir.ssa) turns the ones whose address isn't taken into SSA
values. The C-specific parts of the calling convention are handled here, so
backends only see words:

- a struct argument is passed as the address of a copy the caller makes;
- a function returning a struct gets the address of the result as a hidden
  first argument;
- calls to variadic functions are marked (nfixed), and the backend decides
  where the arguments go.

Values of narrow types (char, short) are kept sign- or zero-extended to 32
bits according to their type.
"""

from ..ir import ir
from ..ir.ir import Const, SymAddr, Undef, Builder, Instr, M32
from .lex import CompileError
from . import ctype as T
from . import tree as N
from .parse import NotConstant, norm, eval_int


def load_info(ty):
    if ty.is_pointer:
        return 4, False
    return ty.size, ty.signed


class FuncGen:
    def __init__(self, gen, fd):
        self.gen = gen
        self.fd = fd
        fty = fd.sym.ty
        self.fty = fty
        self.sret = fty.ret.is_struct
        n = len(fd.params) + (1 if self.sret else 0)
        names = (["ret"] if self.sret else []) + [p.name for p in fd.params]
        self.f = ir.Function(fd.sym.asm_name, n, variadic=fty.variadic,
                             returns=not (fty.ret.is_void or self.sret),
                             static=fd.sym.storage == "static", param_names=names)
        self.b = Builder(self.f)
        self.breaks = []
        self.continues = []
        self.labels = {}

    def error(self, msg, tok):
        raise CompileError(msg, tok)

    # ---- function ----------------------------------------------------------

    def run(self):
        f, b, fd = self.f, self.b, self.fd
        entry = f.new_block("entry")
        b.set_block(entry)
        k = 0
        if self.sret:
            self.sret_ptr = f.params[0]
            k = 1
        for p in fd.params:
            pv = f.params[k]
            k += 1
            if p.ty.is_struct:
                p.ir = ("addr", pv)
            else:
                s = f.new_slot(p.ty.size, p.ty.align, p.name)
                b.store(pv, s, p.ty.size)
                p.ir = ("slot", s)
        for v in fd.locals:
            v.ir = ("slot", f.new_slot(v.ty.size, v.ty.align, v.name))
        body = f.new_block("body")
        b.jmp(body)
        b.set_block(body)
        self.stmt(fd.body)
        if not b.terminated:
            if f.returns:
                b.ret(Const(0))
            else:
                b.ret()
        return f

    def new_block(self, hint=""):
        return self.f.new_block(hint)

    def goto_block(self, blk):
        """End the current block with a jump to blk (if it's still open) and
        continue in blk."""
        if not self.b.terminated:
            self.b.jmp(blk)
        self.b.set_block(blk)

    def dead_block(self):
        """Code after a jump: unreachable, removed later."""
        self.b.set_block(self.new_block("dead"))

    def temp_slot(self, ty, name="tmp"):
        return self.f.new_slot(ty.size, max(ty.align, 1), name)

    # ---- statements --------------------------------------------------------

    def stmt(self, s):
        m = getattr(self, "s_" + type(s).__name__)
        m(s)

    def s_Compound(self, s):
        for x in s.items:
            self.stmt(x)

    def s_Empty(self, s):
        pass

    def s_ExprStmt(self, s):
        self.expr(s.e, discard=True)

    def s_Decl(self, s):
        if s.init is None:
            return
        addr = self.var_addr(s.sym)
        self.init_object(addr, s.init)

    def init_object(self, addr, init):
        b = self.b
        ty = init.ty
        items = init.items
        if ty.is_scalar:
            off, ity, e = items[0]
            b.store(self.expr(e), addr, ity.size, volatile=ty.volatile)
            return
        # zero whatever the initializer doesn't cover
        covered = bytearray(ty.size)
        for off, ity, e in items:
            for k in range(off, min(off + ity.size, ty.size)):
                covered[k] = 1
        gaps = covered.count(0)
        if gaps > 64:
            self.memset0(addr, ty.size)
        elif gaps:
            k = 0
            while k < ty.size:
                if covered[k]:
                    k += 1
                    continue
                for w in (4, 2, 1):
                    if k % w == 0 and k + w <= ty.size and not any(covered[k:k + w]) \
                            and ty.align >= w:
                        b.store(Const(0), self.offset(addr, k), w)
                        k += w
                        break
        for off, ity, e in items:
            a = self.offset(addr, off)
            if ity.is_struct:
                src = self.expr(e)
                b.memcpy(a, src, ity.size, ity.align)
            else:
                b.store(self.expr(e), a, ity.size)

    def memset0(self, addr, size):
        sym = self.gen.runtime("memset")
        self.b.call(sym, [addr, Const(0), Const(size)], void=True)

    def offset(self, addr, off):
        if off == 0:
            return addr
        return self.b.binop("add", addr, Const(off))

    def s_If(self, s):
        then = self.new_block("then")
        end = self.new_block("endif")
        els = self.new_block("else") if s.els is not None else end
        self.cond(s.c, then, els)
        self.b.set_block(then)
        self.stmt(s.then)
        if not self.b.terminated:
            self.b.jmp(end)
        if s.els is not None:
            self.b.set_block(els)
            self.stmt(s.els)
            if not self.b.terminated:
                self.b.jmp(end)
        self.b.set_block(end)

    def loop(self, body, brk, cont):
        self.breaks.append(brk)
        self.continues.append(cont)
        self.stmt(body)
        self.breaks.pop()
        self.continues.pop()

    def s_While(self, s):
        head = self.new_block("while")
        body = self.new_block("body")
        end = self.new_block("endwhile")
        self.goto_block(head)
        self.cond(s.c, body, end)
        self.b.set_block(body)
        self.loop(s.body, end, head)
        if not self.b.terminated:
            self.b.jmp(head)
        self.b.set_block(end)

    def s_DoWhile(self, s):
        body = self.new_block("do")
        test = self.new_block("dotest")
        end = self.new_block("enddo")
        self.goto_block(body)
        self.loop(s.body, end, test)
        self.goto_block(test)
        self.cond(s.c, body, end)
        self.b.set_block(end)

    def s_For(self, s):
        if s.init is not None:
            self.stmt(s.init)
        head = self.new_block("for")
        body = self.new_block("forbody")
        step = self.new_block("forstep")
        end = self.new_block("endfor")
        self.goto_block(head)
        if s.c is not None:
            self.cond(s.c, body, end)
        else:
            self.b.jmp(body)
        self.b.set_block(body)
        self.loop(s.body, end, step)
        self.goto_block(step)
        if s.step is not None:
            self.expr(s.step, discard=True)
        self.b.jmp(head)
        self.b.set_block(end)

    def s_Switch(self, s):
        v = self.expr(s.e)
        dispatch = self.b.block
        end = self.new_block("endswitch")
        self.dead_block()
        self.breaks.append(end)
        self.stmt(s.body)
        self.breaks.pop()
        self.goto_block(end)
        default = s.default.block if s.default is not None else end
        cases = [(c.value, c.block) for c in s.cases]
        dispatch.append(Instr("switch", [v], targets=[default] + [blk for _, blk in cases],
                              cases=[cv & M32 for cv, _ in cases]))

    def s_Case(self, s):
        s.block = self.new_block("case")
        self.goto_block(s.block)
        self.stmt(s.stmt)

    def s_Default(self, s):
        s.block = self.new_block("default")
        self.goto_block(s.block)
        self.stmt(s.stmt)

    def s_Break(self, s):
        self.b.jmp(self.breaks[-1])
        self.dead_block()

    def s_Continue(self, s):
        if not self.continues:
            self.error("continue outside a loop", s.tok)
        self.b.jmp(self.continues[-1])
        self.dead_block()

    def s_Return(self, s):
        b = self.b
        if s.e is None:
            b.ret(Const(0) if self.f.returns else None)
        elif self.sret:
            src = self.expr(s.e)
            b.memcpy(self.sret_ptr, src, self.fty.ret.size, self.fty.ret.align)
            b.ret()
        elif not self.f.returns:
            self.expr(s.e, discard=True)
            b.ret()
        else:
            b.ret(self.expr(s.e))
        self.dead_block()

    def label_block(self, name):
        if name not in self.labels:
            self.labels[name] = self.new_block("L_" + name)
        return self.labels[name]

    def s_Goto(self, s):
        self.b.jmp(self.label_block(s.label))
        self.dead_block()

    def s_Label(self, s):
        self.goto_block(self.label_block(s.label))
        self.stmt(s.stmt)

    # ---- conditions --------------------------------------------------------

    def cond(self, e, t, f):
        b = self.b
        if isinstance(e, N.Binary) and e.op == "&&":
            mid = self.new_block("and")
            self.cond(e.l, mid, f)
            b.set_block(mid)
            self.cond(e.r, t, f)
            return
        if isinstance(e, N.Binary) and e.op == "||":
            mid = self.new_block("or")
            self.cond(e.l, t, mid)
            b.set_block(mid)
            self.cond(e.r, t, f)
            return
        if isinstance(e, N.Unary) and e.op == "lnot":
            self.cond(e.e, f, t)
            return
        if isinstance(e, N.Num):
            b.jmp(t if e.value else f)
            return
        v = self.expr(e)
        b.br(v, t, f)

    # ---- addresses ---------------------------------------------------------

    def var_addr(self, sym):
        if sym.ir is not None:
            kind, v = sym.ir
            return v
        return SymAddr(sym.asm_name)

    def addr(self, e):
        """The address of an lvalue (or of a struct-valued expression)."""
        if isinstance(e, N.Ident):
            if e.sym.kind == "func":
                return SymAddr(e.sym.asm_name)
            return self.var_addr(e.sym)
        if isinstance(e, N.Unary) and e.op == "deref":
            return self.expr(e.e)
        if isinstance(e, N.Member):
            return self.offset(self.addr(e.e), e.member.offset)
        if isinstance(e, N.Str):
            return SymAddr(self.gen.string(e.data))
        if e.ty.is_struct:
            return self.expr(e)
        self.error("not an lvalue", e.tok)

    # ---- expressions -------------------------------------------------------

    def load(self, addr, ty):
        if ty.is_struct or ty.is_array or ty.is_func:
            return addr
        size, signed = load_info(ty)
        return self.b.load(addr, size, signed, volatile=ty.volatile)

    def store(self, v, addr, ty):
        self.b.store(v, addr, ty.size if not ty.is_pointer else 4, volatile=ty.volatile)

    def convert(self, v, src, dst):
        """Convert value v from type src to type dst."""
        if dst.is_void:
            return Undef
        if not dst.is_integer or dst.size == 4:
            return v
        dsize, dsigned = dst.size, dst.signed
        if src.is_integer:
            ssize, ssigned = src.size, src.signed
            if ssize < dsize and (not ssigned or dsigned):
                return v
            if ssize == dsize and ssigned == dsigned:
                return v
        if isinstance(v, Const):
            return Const(norm(v.value, dst))
        op = ("sext" if dsigned else "zext") + str(8 * dsize)
        return self.b.unop(op, v)

    def expr(self, e, discard=False):
        m = getattr(self, "e_" + type(e).__name__)
        return m(e, discard) if discard else m(e)

    def e_Num(self, e, discard=False):
        return Const(e.value)

    def e_Str(self, e, discard=False):
        return SymAddr(self.gen.string(e.data))

    def e_Ident(self, e, discard=False):
        if e.sym.kind == "func":
            return SymAddr(e.sym.asm_name)
        return self.load(self.var_addr(e.sym), e.ty)

    def e_Decay(self, e, discard=False):
        return self.addr(e.e)

    def e_VaStart(self, e, discard=False):
        return self.b.emit("vastart", [])

    def e_Cast(self, e, discard=False):
        if e.ty.is_void:
            self.expr(e.e, discard=True)
            return Undef
        v = self.expr(e.e)
        return self.convert(v, e.e.ty, e.ty)

    def e_Unary(self, e, discard=False):
        b = self.b
        if e.op == "addr":
            return self.addr(e.e)
        if e.op == "deref":
            p = self.expr(e.e)
            if e.ty.is_func:
                return p
            return self.load(p, e.ty)
        v = self.expr(e.e)
        if e.op == "neg":
            return b.unop("neg", v)
        if e.op == "bitnot":
            return b.unop("not", v)
        if e.op == "lnot":
            return b.binop("eq", v, Const(0))
        raise AssertionError(e.op)

    ARITH = {"+": "add", "-": "sub", "*": "mul", "&": "and", "|": "or", "^": "xor", "<<": "shl"}
    CMP = {"==": ("eq", "eq"), "!=": ("ne", "ne"), "<": ("lt", "ltu"), ">": ("gt", "gtu"),
           "<=": ("le", "leu"), ">=": ("ge", "geu")}

    def arith(self, op, l, r, ty):
        """Binary operation op on IR values of C type ty (shift counts aside)."""
        b = self.b
        if op in self.ARITH:
            return b.binop(self.ARITH[op], l, r)
        u = ty.unsigned or ty.is_pointer
        if op == "/":
            return b.binop("divu" if u else "divs", l, r)
        if op == "%":
            return b.binop("remu" if u else "rems", l, r)
        if op == ">>":
            return b.binop("shr" if u else "sar", l, r)
        raise AssertionError(op)

    def scaled(self, i, ty):
        size = ty.base.size if not ty.base.is_void else 1
        if size == 1:
            return i
        return self.b.binop("mul", i, Const(size))

    def e_Binary(self, e, discard=False):
        b = self.b
        op = e.op
        if op == ",":
            self.expr(e.l, discard=True)
            return self.expr(e.r, discard)
        if op in ("&&", "||"):
            t = self.new_block("true")
            f = self.new_block("false")
            j = self.new_block("bool")
            self.cond(e, t, f)
            b.set_block(t)
            b.jmp(j)
            b.set_block(f)
            b.jmp(j)
            b.set_block(j)
            p = b.phi()
            p.args = [Const(1), Const(0)]
            p.incoming = [t, f]
            return p
        l = self.expr(e.l)
        r = self.expr(e.r)
        if op == "padd":
            return b.binop("add", l, self.scaled(r, e.l.ty))
        if op == "psub":
            return b.binop("sub", l, self.scaled(r, e.l.ty))
        if op == "pdiff":
            d = b.binop("sub", l, r)
            size = e.l.ty.base.size if not e.l.ty.base.is_void else 1
            if size == 1:
                return d
            if size & (size - 1) == 0:
                return b.binop("sar", d, Const(size.bit_length() - 1))   # exact
            return b.binop("divs", d, Const(size))
        if op in self.CMP:
            ty = e.l.ty
            u = ty.unsigned or ty.is_pointer
            return b.binop(self.CMP[op][1 if u else 0], l, r)
        return self.arith(op, l, r, e.ty)

    def e_Assign(self, e, discard=False):
        b = self.b
        lty = e.l.ty
        if e.op is None:
            if lty.is_struct:
                src = self.expr(e.r)
                dst = self.addr(e.l)
                b.memcpy(dst, src, lty.size, lty.align)
                return dst
            v = self.expr(e.r)
            a = self.addr(e.l)
            self.store(v, a, lty)
            return v
        a = self.addr(e.l)
        old = self.load(a, lty)
        r = self.expr(e.r)
        if e.op in ("padd", "psub"):
            res = b.binop("add" if e.op == "padd" else "sub", old, self.scaled(r, lty))
        else:
            cty = e.cty
            res = self.arith(e.op, self.convert(old, lty, cty), r, cty)
            res = self.convert(res, cty, lty)
        self.store(res, a, lty)
        return res

    def e_IncDec(self, e, discard=False):
        b = self.b
        ty = e.ty
        a = self.addr(e.e)
        old = self.load(a, ty)
        step = e.delta * (ty.base.size if ty.is_pointer and not ty.base.is_void else 1)
        new = b.binop("add", old, Const(step))
        new = self.convert(new, T.INT if not ty.is_pointer else ty, ty)
        self.store(new, a, ty)
        return old if e.post else new

    def e_Cond(self, e, discard=False):
        b = self.b
        t = self.new_block("cthen")
        f = self.new_block("celse")
        j = self.new_block("cend")
        self.cond(e.c, t, f)
        b.set_block(t)
        va = self.expr(e.a, discard or e.ty.is_void)
        ta = b.block
        b.jmp(j)
        b.set_block(f)
        vb = self.expr(e.b, discard or e.ty.is_void)
        tb = b.block
        b.jmp(j)
        b.set_block(j)
        if e.ty.is_void or discard:
            return Undef
        p = b.phi()
        p.args = [va, vb]
        p.incoming = [ta, tb]
        return p

    def e_Member(self, e, discard=False):
        return self.load(self.addr(e), e.ty)

    def e_Call(self, e, discard=False):
        b = self.b
        fty = e.fty
        fn = e.fn
        if isinstance(fn, N.Decay) and isinstance(fn.e, N.Ident) and fn.e.sym.kind == "func":
            callee = SymAddr(fn.e.sym.asm_name)
        else:
            callee = self.expr(fn)
        args = []
        result = None
        if fty.ret.is_struct:
            result = self.temp_slot(fty.ret, "ret")
            args.append(result)
        for a in e.args:
            if a.ty.is_struct:
                src = self.expr(a)
                copy = self.temp_slot(a.ty, "arg")
                b.memcpy(copy, src, a.ty.size, a.ty.align)
                args.append(copy)
            else:
                args.append(self.expr(a))
        nfixed = None
        if fty.variadic:
            nfixed = len(fty.params) + (1 if fty.ret.is_struct else 0)
        void = fty.ret.is_void or fty.ret.is_struct
        c = b.call(callee, args, void=void, nfixed=nfixed)
        if result is not None:
            return result
        return Undef if void else c


class IRGen:
    def __init__(self, tu, module=None, name=""):
        self.tu = tu
        self.module = module or ir.Module()
        self.strings = {}
        self.name = name
        self.runtime_used = set()

    def runtime(self, name):
        self.runtime_used.add(name)
        return SymAddr(name)

    def string(self, data):
        label = self.strings.get(data)
        if label is None:
            label = f"str{len(self.strings)}"
            self.strings[data] = label
            self.module.data.append(ir.GlobalData(label, len(data), 1, [("bytes", data)],
                                                  static=True, readonly=True))
        return label

    def run(self):
        for fd in self.tu.functions:
            f = FuncGen(self, fd).run()
            self.module.functions.append(f)
        for sym in self.tu.globals:
            if sym.storage == "extern" or not sym.defined:
                continue
            self.module.data.append(self.global_data(sym))
        return self.module

    # ---- static data ---------------------------------------------------------

    def global_data(self, sym):
        ty = sym.ty
        if not ty.complete:
            if ty.is_array:
                ty = T.array_of(ty.base, 1)
            else:
                raise CompileError(f"{sym.name} has incomplete type {ty}", sym.tok)
        size = max(ty.size, 1)
        d = ir.GlobalData(sym.asm_name, size, ty.align, static=sym.storage == "static",
                          readonly=ty.const)
        if sym.init is None:
            d.items = [("zero", size)]
            return d
        buf = bytearray(size)
        relocs = {}
        for off, ity, e in sym.init.items:
            if ity.is_struct:
                raise CompileError("a struct initializer must be a braced list here", e.tok)
            try:
                label, val = self.eval_addr(e)
            except NotConstant:
                raise CompileError("initializer is not a constant", e.tok)
            if label is not None:
                if ity.size != 4 or off % 4:
                    raise CompileError("an address in an initializer needs a 4-byte slot", e.tok)
                relocs[off] = SymAddr(label, val)
                continue
            v = val & ((1 << (8 * ity.size)) - 1)
            for k in range(ity.size):
                buf[off + k] = (v >> (8 * k)) & 0xFF
        items = []
        pos = 0
        for off in sorted(relocs):
            if off > pos:
                items.append(("bytes", bytes(buf[pos:off])))
            items.append(("word", relocs[off]))
            pos = off + 4
        if pos < size:
            items.append(("bytes", bytes(buf[pos:])))
        # compress runs of zeros at the end
        if items and items[-1][0] == "bytes":
            data = items[-1][1]
            stripped = data.rstrip(b"\0")
            if len(data) - len(stripped) >= 8:
                items[-1] = ("bytes", stripped)
                items.append(("zero", len(data) - len(stripped)))
                if not stripped:
                    del items[-2]
        d.items = items
        return d

    def eval_addr(self, e):
        """A constant initializer: (label or None, value)."""
        if isinstance(e, N.Num):
            return None, e.value
        if isinstance(e, N.Cast):
            label, v = self.eval_addr(e.e)
            if label is None:
                return None, norm(v, e.ty) if e.ty.is_integer else v
            return label, v
        if isinstance(e, N.Decay):
            return self.lvalue_addr(e.e)
        if isinstance(e, N.Str):
            return self.string(e.data), 0
        if isinstance(e, N.Unary) and e.op == "addr":
            return self.lvalue_addr(e.e)
        if isinstance(e, N.Binary) and e.op in ("padd", "psub"):
            label, v = self.eval_addr(e.l)
            l2, i = self.eval_addr(e.r)
            if l2 is not None:
                raise NotConstant()
            size = e.l.ty.base.size if not e.l.ty.base.is_void else 1
            return label, v + (i if e.op == "padd" else -i) * size
        if isinstance(e, N.Binary) and e.op in ("+", "-"):
            l1, a = self.eval_addr(e.l)
            l2, c = self.eval_addr(e.r)
            if l1 is None and l2 is None:
                return None, norm(a + c if e.op == "+" else a - c, e.ty)
            if l2 is None:
                return l1, a + c if e.op == "+" else a - c
            if l1 is None and e.op == "+":
                return l2, a + c
            raise NotConstant()
        if isinstance(e, N.Ident) and e.sym.kind == "func":
            return e.sym.asm_name, 0
        return None, eval_int(e)

    def lvalue_addr(self, e):
        if isinstance(e, N.Ident):
            if e.sym.kind == "func" or (e.sym.kind == "var" and not e.sym.is_local):
                return e.sym.asm_name, 0
            raise NotConstant()
        if isinstance(e, N.Str):
            return self.string(e.data), 0
        if isinstance(e, N.Member):
            label, v = self.lvalue_addr(e.e)
            return label, v + e.member.offset
        if isinstance(e, N.Unary) and e.op == "deref":
            return self.eval_addr(e.e)
        raise NotConstant()
