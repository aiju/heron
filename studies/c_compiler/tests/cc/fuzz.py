"""Random differential testing of the C compiler against gcc.

Generates small random C programs (integer arithmetic of every width,
arrays, pointers, structs, loops, switches, calls, many live values) without
undefined behaviour, compiles each with gcc -funsigned-char and with this
compiler for drafts 1a and 1b, and compares the output. The generator keeps a
bound on each int value: arithmetic that stays in int's range is left signed
(the optimiser assumes signed arithmetic doesn't overflow, and this tests
that), and arithmetic that might overflow is done in unsigned, which wraps.
gcc builds the reference with -fsanitize=undefined, so a program that has
undefined behaviour after all is reported as the generator's fault.

    python3 studies/c_compiler/tests/cc/fuzz.py [--count N] [--seed S] [--keep DIR]
"""

import argparse
import os
import random
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", ".."))     # the repository root

from heron.studies.c_compiler.cc import driver
from heron.studies.c_compiler.cc.lex import CompileError

TYPES = ["int", "unsigned", "short", "unsigned short", "char", "signed char", "unsigned char"]

# Each type's promoted type ("i": int, "u": unsigned) and a bound w on its
# values, which lie in [-2**w, 2**w) (32: no bound). An expression is
# (text, promoted type, bound).
PROMO = {"int": ("i", 32), "unsigned": ("u", 32), "short": ("i", 15), "unsigned short": ("i", 16),
         "char": ("i", 8), "signed char": ("i", 7), "unsigned char": ("i", 8)}
FIELDS = {"a": "int", "b": "short", "c": "unsigned char", "d": "unsigned"}

PRELUDE = r"""
#include <stdio.h>
static int sdiv(int a, int b) { return b == 0 || (a == -2147483647 - 1 && b == -1) ? a : a / b; }
static int smod(int a, int b) { return b == 0 || (a == -2147483647 - 1 && b == -1) ? a : a % b; }
static unsigned udiv(unsigned a, unsigned b) { return b ? a / b : a; }
static unsigned umod(unsigned a, unsigned b) { return b ? a % b : a; }
static unsigned hash;
static void mix(unsigned v) { hash = (hash ^ v) * 16777619u + 1; }
struct S { int a; short b; unsigned char c; unsigned d; };
"""


class Gen:
    def __init__(self, rng):
        self.r = rng
        self.depth = 0
        self.pure = False       # function bodies only see their own variables

    def pick(self, xs):
        return self.r.choice(xs)

    def const(self):
        r = self.r.random()
        if r < 0.4:
            v = self.r.randint(0, 20)
        elif r < 0.6:
            v = self.r.randint(-20, -1)
        elif r < 0.8:
            v = self.r.choice([127, 128, 255, 256, 32767, 32768, 65535, 65536, 1000, 4095])
        elif self.r.random() < 0.5:
            # (not -2**31: 2147483648 is unsigned long here, but a long for gcc)
            v = self.r.randint(-2 ** 31 + 1, 2 ** 31 - 1)
        else:
            return f"{self.r.randint(0, 2 ** 32 - 1)}u", "u", 32
        return str(v), "i", max(v.bit_length(), (-v - 1).bit_length())

    def var(self):
        n = self.pick(self.vars)
        return (n,) + PROMO[self.vtypes[n]]

    def lvalue(self):
        """(text, declared type)"""
        r = self.r.random()
        if r < 0.65:
            n = self.pick(self.vars)
            return n, self.vtypes[n]
        if r < 0.8:
            return f"arr[({self.e(1)}) & 15]", "int"
        f = self.pick("abcd")
        if r < 0.9:
            return f"s.{f}", FIELDS[f]
        return f"sa[({self.e(1)}) & 3].{f}", FIELDS[f]

    def e(self, depth=0):
        return self.expr(depth)[0]

    def expr(self, depth=0):
        r = self.r.random()
        if depth > 3 or r < 0.25:
            if self.pure:
                return self.pick([self.var(), self.var(), self.const()])
            f = self.pick("abcd")
            return self.pick([self.var(), self.var(), self.const(), (f"arr[{self.r.randint(0, 15)}]", "i", 32),
                              (f"s.{f}",) + PROMO[FIELDS[f]], ("*p", "i", 32),
                              (f"p[{self.r.randint(-2, 2)}]", "i", 32)])
        if r < 0.65:
            op = self.pick(["+", "-", "*", "&", "|", "^", "<<", ">>", "<", ">", "<=", ">=",
                            "==", "!=", "&&", "||", "+", "-", "*"])
            return self.binop(op, self.expr(depth + 1), self.expr(depth + 1))
        if r < 0.72:
            f = self.pick(["sdiv", "smod", "udiv", "umod"])
            (a, ta, wa), (b, tb, wb) = self.expr(depth + 1), self.expr(depth + 1)
            wa, wb = (wa if ta == "i" else 32), (wb if tb == "i" else 32)
            # |a / b| <= |a| except INT_MIN / -1; |a % b| <= |a| and < |b|
            w = {"sdiv": min(wa + 1, 32), "smod": min(wa, wb)}.get(f, 32)
            return f"{f}({a}, {b})", "u" if f[0] == "u" else "i", w
        if r < 0.8:
            ty = self.pick(TYPES)
            a, ta, wa = self.expr(depth + 1)
            t, w = PROMO[ty]
            if ty == "int" and ta == "i":
                w = wa
            return f"(({ty})({a}))", t, w
        if r < 0.86:
            op = self.pick(["-", "~", "!"])
            a, ta, wa = self.expr(depth + 1)
            if op == "!":
                return f"(!({a}))", "i", 1
            if ta == "u" or op == "~":
                return f"({op}({a}))", ta, wa
            if wa < 31:
                return f"(-({a}))", "i", wa + 1
            return f"((int)-(unsigned)({a}))", "i", 32         # -INT_MIN overflows
        if r < 0.92:
            c, (a, ta, wa), (b, tb, wb) = self.e(depth + 1), self.expr(depth + 1), self.expr(depth + 1)
            t = "u" if "u" in (ta, tb) else "i"
            return f"(({c}) ? ({a}) : ({b}))", t, max(wa, wb) if t == "i" else 32
        if r < 0.96 and self.nfuncs > 0:
            args = ", ".join(self.e(depth + 2) for _ in range(self.nargs))
            return f"f{self.r.randint(0, self.nfuncs - 1)}({args})", "i", 32
        # (no assignments inside expressions: C leaves their order unspecified)
        return self.binop(self.pick(["+", "-", "^", "|"]), self.expr(depth + 1), self.expr(depth + 1))

    def binop(self, op, x, y):
        """x op y, for expressions x and y; an int + - * or << that might
        overflow is done in unsigned instead."""
        (a, ta, wa), (b, tb, wb) = x, y
        if op in ("<", ">", "<=", ">=", "==", "!=", "&&", "||"):
            return f"(({a}) {op} ({b}))", "i", 1
        if op == "<<":
            if ta == "i":
                return f"((int)((unsigned)({a}) << (({b}) & 31)))", "i", 32
            return f"(({a}) << (({b}) & 31))", "u", 32
        if op == ">>":
            return f"(({a}) >> (({b}) & 31))", ta, wa
        if "u" in (ta, tb):
            return f"(({a}) {op} ({b}))", "u", 32
        if op in ("&", "|", "^"):
            return f"(({a}) {op} ({b}))", "i", max(wa, wb)
        w = max(wa, wb) + 1 if op != "*" else wa + wb + 1
        if w <= 31:
            return f"(({a}) {op} ({b}))", "i", w
        return f"((int)((unsigned)({a}) {op} (unsigned)({b})))", "i", 32

    def compound(self, lv, ty, op, rhs):
        """`lv op= rhs` for + - *, with rhs unsigned where int arithmetic
        might overflow."""
        (b, tb, wb), (ta, wa) = rhs, PROMO[ty]
        if ta == "i" and tb == "i" and (max(wa, wb) + 1 if op != "*=" else wa + wb + 1) > 31:
            b = f"(unsigned)({b})"
        return f"{lv} {op} {b}"

    def stmt(self, depth):
        r = self.r.random()
        ind = "    " * (depth + 1)
        if depth > 2 or r < 0.45:
            op = self.pick(["=", "=", "+=", "-=", "*=", "&=", "|=", "^=", "<<=", ">>="])
            lv, ty = self.lvalue()
            rhs = self.expr()
            if op in ("+=", "-=", "*="):
                return f"{ind}{self.compound(lv, ty, op, rhs)};\n"
            if op == "<<=" and PROMO[ty][0] == "i":
                # (the index expressions in lv have no side effects)
                return f"{ind}{lv} = (unsigned)({lv}) << (({rhs[0]}) & 31);\n"
            if op in ("<<=", ">>="):
                return f"{ind}{lv} {op} ({rhs[0]}) & 31;\n"
            return f"{ind}{lv} {op} {rhs[0]};\n"
        if r < 0.55:
            lv, ty = self.lvalue()
            op = self.pick(["++", "--"])
            if ty == "int":
                return f"{ind}{lv} {op[0]}= 1u;\n"           # INT_MAX + 1 overflows
            return f"{ind}{lv}{op};\n"
        if r < 0.7:
            s = f"{ind}if ({self.e()}) {{\n" + self.block(depth + 1) + f"{ind}}}"
            if self.r.random() < 0.5:
                s += " else {\n" + self.block(depth + 1) + f"{ind}}}"
            return s + "\n"
        if r < 0.8:
            v = f"i{depth}"
            n = self.r.randint(0, 6)
            return (f"{ind}for ({v} = 0; {v} < {n}; {v}++) {{\n" + self.block(depth + 1) +
                    f"{ind}    mix({v});\n{ind}}}\n")
        if r < 0.87:
            v = f"i{depth}"
            return (f"{ind}{v} = {self.r.randint(0, 5)};\n{ind}while ({v}-- > 0) {{\n" +
                    self.block(depth + 1) + f"{ind}}}\n")
        if r < 0.9:
            return self.array_loop(depth, ind)
        if r < 0.95:
            cases = sorted(self.r.sample(range(-3, 12), self.r.randint(1, 6)))
            s = f"{ind}switch (({self.e()}) & 15) {{\n"
            for c in cases:
                s += f"{ind}case {c}:\n" + self.block(depth + 1)
                if self.r.random() < 0.7:
                    s += f"{ind}    break;\n"
            if self.r.random() < 0.5:
                s += f"{ind}default:\n" + self.block(depth + 1)
            return s + f"{ind}}}\n"
        return f"{ind}p = &arr[2 + (({self.e()}) & 7)];\n"

    def array_loop(self, depth, ind):
        """Loops that walk arrays by their counter (what strength reduction
        rewrites into pointer loops)."""
        v = f"i{depth}"
        kind = self.r.randint(0, 5)
        lo = self.r.randint(0, 5)
        hi = self.r.randint(lo, 16)
        st = self.r.choice([1, 1, 1, 2, 3])
        if kind == 0:
            op = self.pick(['+=', '^=', '-=', '='])
            s = self.compound(f"arr[{v}]", "int", op, self.expr(2)) if op in ("+=", "-=") \
                else f"arr[{v}] {op} {self.e(2)}"
            return f"{ind}for ({v} = {lo}; {v} < {hi}; {v} += {st})\n{ind}    {s};\n"
        if kind == 1:
            return (f"{ind}for ({v} = {hi - 1}; {v} >= {lo}; {v}--)\n"
                    f"{ind}    mix((unsigned)arr[{v}] + {v});\n")
        if kind == 2:
            f = self.pick("abcd")
            s = self.compound(f"sa[{v}].{f}", FIELDS[f], "+=", self.expr(2))
            return (f"{ind}for ({v} = 0; {v} < 4; {v}++) {{\n"
                    f"{ind}    {s};\n{ind}    mix(sa[{v}].{f});\n{ind}}}\n")
        if kind == 3:
            return (f"{ind}{{ int *q = arr + {lo}; while (q < arr + {hi}) {{ *q = *q * 3u + ({self.e(2)}); mix(*q++); }} }}\n")
        if kind == 4:
            return (f"{ind}for ({v} = {lo}; {v} != {hi}; {v}++)\n"
                    f"{ind}    {{ bytes[{v}] = {self.e(2)}; mix(bytes[{v}] + shorts[{v}]); shorts[{v}] -= bytes[{v}]; }}\n")
        return (f"{ind}for ({v} = {lo}; {v} < {hi}; {v}++) {{ int j{depth}; for (j{depth} = 0; j{depth} < 4; j{depth}++) "
                f"grid[j{depth}][{v}] += (unsigned)arr[{v}] ^ j{depth}; mix(grid[{v} & 3][{v}]); }}\n")

    def block(self, depth):
        return "".join(self.stmt(depth) for _ in range(self.r.randint(1, 4)))

    def program(self):
        r = self.r
        self.nfuncs = r.randint(1, 3)
        self.nargs = r.randint(1, 6)
        out = [PRELUDE]
        out.append("int arr[16];\nstruct S s, sa[4];\nint *p = arr + 4;\n"
                   "unsigned char bytes[16];\nshort shorts[16];\nint grid[4][16];\n")
        total = self.nfuncs
        for k in range(total):
            params = [f"int a{j}" for j in range(self.nargs)]
            self.vars = [f"a{j}" for j in range(self.nargs)]
            self.vtypes = {n: "int" for n in self.vars}
            self.nfuncs = k                 # only call earlier functions
            self.pure = True
            body = ""
            for j in range(r.randint(0, 3)):
                ty = self.pick(TYPES)
                body += f"    {ty} l{j} = {self.e()};\n"
                self.vars.append(f"l{j}")
                self.vtypes[f"l{j}"] = ty
            expr = self.e(1)
            out.append(f"static int f{k}({', '.join(params)})\n{{\n{body}    return {expr};\n}}\n")
        self.nfuncs = total
        self.pure = False
        nv = r.randint(3, 16)
        decls = [(self.pick(TYPES), f"v{j}") for j in range(nv)]
        self.vars = [n for _, n in decls]
        self.vtypes = {n: t for t, n in decls}
        body = "int main(void)\n{\n    int i0, i1, i2, i3, k;\n"
        for t, n in decls:
            body += f"    {t} {n} = {self.const()[0]};\n"
        body += "    for (k = 0; k < 16; k++) arr[k] = k * 7 - 30;\n"
        body += "    for (k = 0; k < 4; k++) { sa[k].a = k; sa[k].b = -k; sa[k].c = 200 + k; sa[k].d = k * 1000; }\n"
        body += self.block(0)
        body += self.block(0)
        for _, n in decls:
            body += f"    mix({n});\n"
        body += "    for (k = 0; k < 16; k++) { mix(arr[k]); mix(bytes[k]); mix(shorts[k]); mix(grid[k & 3][k]); }\n"
        body += "    mix(s.a); mix(s.b); mix(s.c); mix(s.d); mix(*p);\n"
        body += "    for (k = 0; k < 4; k++) { mix(sa[k].a); mix(sa[k].b); mix(sa[k].c); mix(sa[k].d); }\n"
        body += '    printf("%u\\n", hash);\n    return 0;\n}\n'
        out.append(body)
        return "".join(out)


def run_gcc(src, tmp):
    c = os.path.join(tmp, "p.c")
    exe = os.path.join(tmp, "p")
    with open(c, "w") as f:
        f.write(src)
    subprocess.run(["gcc", "-w", "-O0", "-funsigned-char", "-fsanitize=undefined",
                    "-fno-sanitize-recover=undefined", "-o", exe, c], check=True)
    r = subprocess.run([exe], capture_output=True, timeout=10)
    ub = r.returncode and r.stderr.decode(errors="replace").strip()
    return r.stdout, c, ub


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=50)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--keep", help="save failing programs here")
    ap.add_argument("--isa", action="append")
    args = ap.parse_args()
    isas = args.isa or ["v1a", "v1b"]
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        for n in range(args.count):
            seed = args.seed + n
            src = Gen(random.Random(seed)).program()
            want, path, ub = run_gcc(src, tmp)
            fails = []
            if ub:
                fails.append(f"seed {seed}: the program has undefined behaviour, a bug in fuzz.py: {ub}")
            for isa in isas if not ub else []:
                try:
                    _, img, _ = driver.build([path], isa, verify_ir=True)
                    m = driver.run_image(img, isa, max_cycles=50_000_000)
                    got = bytes(m.dev.out)
                    err = m.error or (m.traps and str(m.traps[0]))
                except (CompileError, Exception) as e:   # noqa: BLE001
                    got, err = b"", f"{type(e).__name__}: {e}"
                if got != want or err:
                    fails.append(f"seed {seed} {isa}: got {got!r} want {want!r} {err or ''}")
            for line in fails:
                print(line)
            bad += len(fails)
            if fails and args.keep:
                os.makedirs(args.keep, exist_ok=True)
                with open(os.path.join(args.keep, f"fuzz{seed}.c"), "w") as f:
                    f.write(src)
            if (n + 1) % 10 == 0:
                print(f"{n + 1} programs, {bad} failures", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
