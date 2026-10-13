"""An interpreter for the IR, for debugging the optimiser: run a program's
IR before and after a pass and compare what it prints.

Memory is one flat little-endian bytearray: globals from 0x1000, the stack
growing down from the top; the console register of the I/O page works (no
input). The program brings the C library; exit and abort, which the start
code provides, end it, and a call to any other function it doesn't define
is an error.
"""

from .ir import Const, SymAddr, Slot, Undef, M32
from .passes import fold_binop, fold_unop


class InterpError(Exception):
    pass


class Exit(Exception):
    pass


class Interpreter:
    def __init__(self, functions, data, mem_size=1 << 20, max_steps=50_000_000):
        self.funcs = {f.name: f for f in functions}
        self.mem = bytearray(mem_size)
        self.addr = {}
        a = 0x1000
        for d in data:
            a = (a + d.align - 1) // d.align * d.align
            self.addr[d.name] = a
            a += max(d.size, 1)
        fa = (a + 15) & ~15
        self.addr["_end"] = fa + 16 * len(functions)  # the heap starts at _end
        for f in functions:             # functions get fake addresses for pointers
            self.addr[f.name] = fa
            fa += 16
        self.by_addr = {self.addr[f.name]: f for f in functions}
        for d in data:
            p = self.addr[d.name]
            for kind, v in d.items:
                if kind == "zero":
                    p += v
                elif kind == "bytes":
                    self.mem[p:p + len(v)] = v
                    p += len(v)
                elif kind == "word":
                    self.st(p, 4, self.addr[v.name] + v.offset if isinstance(v, SymAddr) else v)
                    p += 4
                else:
                    n = {"byte": 1, "half": 2}[kind]
                    self.st(p, n, v)
                    p += n
        self.sp = mem_size - 16
        self.out = bytearray()
        self.steps = 0
        self.max_steps = max_steps

    # ---- memory ----

    IO = 0xFFFFFF00

    def ld(self, a, n, signed=False):
        if a >= self.IO:
            if a & ~3 == self.IO:                   # console input: none
                return M32 if n == 4 else (1 << (8 * n)) - 1
            return 0
        if a < 0x100 or a + n > len(self.mem):
            raise InterpError(f"load from {a:#x}")
        v = int.from_bytes(self.mem[a:a + n], "little")
        if signed and v >> (8 * n - 1):
            v -= 1 << (8 * n)
        return v & M32

    def st(self, a, n, v):
        if a >= self.IO:
            if a & ~3 == self.IO:                   # console output
                self.out.append(v & 0xFF)
            return
        if a < 0x100 or a + n > len(self.mem):
            raise InterpError(f"store to {a:#x}")
        self.mem[a:a + n] = (v & ((1 << (8 * n)) - 1)).to_bytes(n, "little")

    # ---- execution ----

    def call(self, name, args, nfixed=None):
        f = self.funcs.get(name)
        if f is None:
            return self.builtin(name, args)
        frame = {}
        base = self.sp
        for s in f.slots:
            self.sp = (self.sp - max(s.size, 1)) & ~max(min(s.align, 4) - 1, 0) & ~3
            frame[s] = self.sp
        varargs = None
        if f.variadic:
            extra = args[len(f.params):]
            self.sp -= 4 * len(extra) + 4
            varargs = self.sp
            for k, v in enumerate(extra):
                self.st(varargs + 4 * k, 4, v)
        env = {}
        for p, v in zip(f.params, args):
            env[p] = v & M32

        def val(v):
            if isinstance(v, Const):
                return v.value
            if isinstance(v, SymAddr):
                if v.name not in self.addr:             # a built-in
                    self.addr[v.name] = 0x10 + 4 * len(self.addr)
                return (self.addr[v.name] + v.offset) & M32
            if isinstance(v, Slot):
                return frame[v]
            if v is Undef:
                return 0
            return env[v]
        prev, b = None, f.entry
        while True:
            phis = b.phis()
            new = {p: val(p.args[p.incoming.index(prev)]) for p in phis}
            env.update(new)
            for i in b.instrs[len(phis):]:
                self.steps += 1
                if self.steps > self.max_steps:
                    raise InterpError("step limit")
                op = i.op
                a = [val(x) for x in i.args]
                if op == "load":
                    env[i] = self.ld(a[0], i.size, i.signed)
                elif op == "store":
                    self.st(a[1], i.size, a[0])
                elif op == "memcpy":
                    self.mem[a[0]:a[0] + i.size] = self.mem[a[1]:a[1] + i.size]
                elif op == "call":
                    target = i.args[0]
                    fname = target.name if isinstance(target, SymAddr) else self.by_addr[a[0]].name
                    r = self.call(fname, a[1:], i.nfixed)
                    if not i.void:
                        env[i] = (r or 0) & M32
                elif op == "vastart":
                    env[i] = varargs
                elif op == "jmp":
                    prev, b = b, i.targets[0]
                    break
                elif op == "br":
                    prev, b = b, i.targets[0 if a[0] else 1]
                    break
                elif op == "switch":
                    dest = i.targets[0]
                    for c, t in zip(i.cases, i.targets[1:]):
                        if c == a[0]:
                            dest = t
                            break
                    prev, b = b, dest
                    break
                elif op == "ret":
                    self.sp = base
                    return a[0] if a else None
                elif op == "unreachable":
                    raise InterpError("reached unreachable")
                elif len(a) == 2:
                    r = fold_binop(op, a[0], a[1])
                    if r is None:
                        raise InterpError(f"{op} {a} (division by zero?)")
                    env[i] = r & M32
                else:
                    env[i] = fold_unop(op, a[0]) & M32

    def builtin(self, name, args):
        if name in ("exit", "abort"):
            raise Exit()
        raise InterpError(f"no function {name}")


def run(functions, data, entry="main"):
    it = Interpreter(functions, data)
    try:
        it.call(entry, [])
    except Exit:
        pass
    return bytes(it.out)
