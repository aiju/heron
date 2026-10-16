"""The reference interpreter: Core (straight from the desugarer, before
any optimisation) evaluated lazily in Python. It writes the expected
output of the programs and tests, so it checks the optimiser, the code
generator and the runtime independently of them; the front end they
share (parsing, type checking, desugaring) it doesn't check.

    python3 studies/curlew/reference.py PROGRAM.cw [INPUT]
    python3 studies/curlew/reference.py --write-expected

Ints are 30 bits, and arithmetic that leaves that range is an error
(language.md, "Int"). A run's output is what the program printed, then
on an error a new line and `error: message`.
"""

import os
import sys
import threading

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    __package__ = "heron.studies.curlew"

from . import core as C  # noqa: E402
from . import desugar, frontend  # noqa: E402

INT_MIN, INT_MAX = -(1 << 29), (1 << 29) - 1


class RuntimeErr(Exception):
    pass


class ConVal:
    __slots__ = ("con", "args")

    def __init__(self, con, args):
        self.con, self.args = con, args


class Clo:
    """A function value: a lambda and the values of its free variables."""
    __slots__ = ("lam", "env")

    def __init__(self, lam, env):
        self.lam, self.env = lam, env


class Pap:
    __slots__ = ("fn", "args")

    def __init__(self, fn, args):
        self.fn, self.args = fn, args


class Thunk:
    __slots__ = ("expr", "env", "value", "state")

    def __init__(self, expr, env):
        self.expr, self.env = expr, env
        self.value = None
        self.state = 0          # 0 unevaluated, 1 being evaluated, 2 done


class Interp:
    def __init__(self, prog):
        self.prog = prog
        self.globals = {}
        self.fvs = {}
        self.true = prog.cons["True"]
        self.false = prog.cons["False"]
        self.nil = prog.cons["[]"]
        self.cons_ = prog.cons[":"]
        for name, e in prog.binds:
            self.globals[name] = Thunk(e, {})

    def free(self, e):
        k = id(e)
        r = self.fvs.get(k)
        if r is None:
            r = self.fvs[k] = (e, [n for n in C.free_vars(e) if n not in self.globals])
        return r[1]

    def lookup(self, env, name):
        v = env.get(name)
        if v is None:
            v = self.globals[name]
        return v

    def capture(self, e, env):
        return {n: self.lookup(env, n) for n in self.free(e)}

    def delay(self, e, env):
        t = type(e)
        if t is C.Var:
            return self.lookup(env, e.name)
        if t is C.Lit:
            return e.value
        return Thunk(e, self.capture(e, env))

    def force(self, v):
        while isinstance(v, Thunk):
            if v.state == 2:
                v = v.value
                continue
            if v.state == 1:
                raise RuntimeErr("<<loop>>")
            v.state = 1
            r = self.eval(v.expr, v.env)
            v.value, v.state, v.expr, v.env = r, 2, None, None
            v = r
        return v

    def eval(self, e, env):
        while True:
            t = type(e)
            if t is C.Var:
                return self.force(self.lookup(env, e.name))
            if t is C.Lit:
                return e.value
            if t is C.Str:
                out = ConVal(self.nil, [])
                for c in reversed(e.codes):
                    out = ConVal(self.cons_, [c, out])
                return out
            if t is C.App:
                f = self.eval(e.fn, env)
                args = [self.delay(a, env) for a in e.args]
                # a tail call to a lambda stays in this loop
                while True:
                    if isinstance(f, Clo):
                        n = len(f.lam.params)
                        if len(args) < n:
                            return Pap(f, args)
                        env = dict(f.env)
                        env.update(zip(f.lam.params, args[:n]))
                        if len(args) == n:
                            e = f.lam.body
                            break
                        f = self.eval(f.lam.body, env)
                        args = args[n:]
                    elif isinstance(f, Pap):
                        args = f.args + args
                        f = f.fn
                    else:
                        raise AssertionError(f"applying {f!r}")
                continue
            if t is C.Lam:
                return Clo(e, self.capture(e, env))
            if t is C.Let:
                if e.rec:
                    env = dict(env)
                    thunks = []
                    for n, r in e.binds:
                        th = Thunk(r, None)
                        env[n] = th
                        thunks.append(th)
                    for th in thunks:
                        th.env = self.capture(th.expr, env)
                else:
                    new = [(n, self.delay(r, env)) for n, r in e.binds]
                    env = dict(env)
                    env.update(new)
                e = e.body
                continue
            if t is C.Case:
                v = self.eval(e.scrut, env)
                env = dict(env)
                env[e.binder] = v
                for a in e.alts:
                    if a.con is not None:
                        if v.con is a.con:
                            env.update(zip(a.vars, v.args))
                            e = a.body
                            break
                    elif v == a.lit:
                        e = a.body
                        break
                else:
                    if e.default is None:
                        raise AssertionError("no alternative matched")
                    e = e.default
                continue
            if t is C.Con:
                args = []
                for a, strict in zip(e.args, e.con.strict):
                    x = self.delay(a, env)
                    args.append(self.force(x) if strict else x)
                return ConVal(e.con, args)
            if t is C.Prim:
                return self.prim(e.op, [self.eval(a, env) if e.op != "error" else self.delay(a, env)
                                        for a in e.args])
            raise AssertionError(e)

    def prim(self, op, a):
        if op == "error":
            raise RuntimeErr(self.string(a[0]))
        if op in ("eq", "ne", "lt", "le", "gt", "ge"):
            x, y = a
            r = {"eq": x == y, "ne": x != y, "lt": x < y, "le": x <= y, "gt": x > y, "ge": x >= y}[op]
            return ConVal(self.true if r else self.false, [])
        if op == "ord" or op == "chr":
            return a[0]
        if op == "neg":
            return check(-a[0])
        x, y = a
        if op == "add":
            return check(x + y)
        if op == "sub":
            return check(x - y)
        if op == "mul":
            return check(x * y)
        if op in ("quot", "rem", "div", "mod"):
            if y == 0:
                raise RuntimeErr("divide by zero")
            q = abs(x) // abs(y)
            if (x < 0) != (y < 0):
                q = -q
            r = x - q * y
            if op == "quot":
                return check(q)
            if op == "rem":
                return r
            if r != 0 and (r < 0) != (y < 0):
                q, r = q - 1, r + y
            return check(q) if op == "div" else r
        if op == "and":
            return x & y
        if op == "or":
            return x | y
        if op == "xor":
            return x ^ y
        if op == "shl":
            return wrap(x << (y & 31))
        if op == "shr":
            return x >> min(y & 31, 29)
        raise AssertionError(op)

    def string(self, v):
        out = []
        v = self.force(v)
        while v.con is self.cons_:
            out.append(chr(self.force(v.args[0]) & 0xFF))
            v = self.force(v.args[1])
        return "".join(out)

    def run(self, inp, out):
        """Apply main to the input, writing the output's characters to
        out (a bytearray) as they come."""
        lst = ConVal(self.nil, [])
        for b in reversed(inp):
            lst = ConVal(self.cons_, [b, lst])
        f = self.force(self.globals[self.prog.main])
        v = self.force(Thunk(C.App(C.Var("%main"), [C.Var("%input")]), {"%main": f, "%input": lst}))
        while v.con is self.cons_:
            out.append(self.force(v.args[0]) & 0xFF)
            v = self.force(v.args[1])


def check(x):
    if x < INT_MIN or x > INT_MAX:
        raise RuntimeErr("Int overflow")
    return x


def wrap(x):
    x &= (1 << 30) - 1
    return x - (1 << 30) if x & (1 << 29) else x


def core_of(text):
    return desugar.desugar(frontend.check(text))


def run(text, inp=b""):
    """A program's output (bytes) on the reference interpreter."""
    prog = core_of(text.decode() if isinstance(text, bytes) else text)
    out = bytearray()
    result = {}

    def go():
        try:
            Interp(prog).run(inp, out)
        except RuntimeErr as e:
            out.extend(b"\nerror: " + str(e).encode() + b"\n")
        except RecursionError:
            out.extend(b"\nerror: stack overflow\n")
        except BaseException as e:      # noqa: BLE001  (reported in the caller's thread)
            result["exc"] = e

    old = sys.getrecursionlimit()
    sys.setrecursionlimit(400000)
    threading.stack_size(1 << 29)
    th = threading.Thread(target=go)
    th.start()
    th.join()
    threading.stack_size(0)
    sys.setrecursionlimit(old)
    if "exc" in result:
        raise result["exc"]
    return bytes(out)


def main(argv):
    if argv and argv[0] == "--write-expected":
        from . import testing
        return testing.write_expected()
    with open(argv[0]) as f:
        text = f.read()
    inp = b""
    if len(argv) > 1:
        with open(argv[1], "rb") as f:
            inp = f.read()
    sys.stdout.buffer.write(run(text, inp))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
