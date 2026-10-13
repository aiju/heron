"""Random differential testing of the C compiler against gcc.

Generates small random C programs (integer arithmetic of every width,
arrays, pointers, structs, loops, switches, calls, many live values) that
avoid undefined behaviour other than signed overflow, compiles each with
gcc -fwrapv -funsigned-char and with tmc for drafts 1a and 1b, and compares
the output. tmc's optimiser assumes signed arithmetic doesn't overflow, so
a difference in a program that overflows isn't necessarily a bug.

    python3 tests/cc/fuzz.py [--count N] [--seed S] [--keep DIR]
"""

import argparse
import os
import random
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))

from tmc.cc import driver  # noqa: E402
from tmc.cc.lex import CompileError  # noqa: E402

TYPES = ["int", "unsigned", "short", "unsigned short", "char", "signed char", "unsigned char"]

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
            return str(self.r.randint(0, 20))
        if r < 0.6:
            return str(self.r.randint(-20, -1))
        if r < 0.8:
            return str(self.r.choice([127, 128, 255, 256, 32767, 32768, 65535, 65536, 1000, 4095]))
        return str(self.r.randint(-2 ** 31, 2 ** 31 - 1)) if self.r.random() < 0.5 else \
            f"{self.r.randint(0, 2 ** 32 - 1)}u"

    def var(self):
        return self.pick(self.vars)

    def lvalue(self):
        r = self.r.random()
        if r < 0.65:
            return self.var()
        if r < 0.8:
            return f"arr[({self.expr(1)}) & 15]"
        if r < 0.9:
            return f"s.{self.pick('abcd')}"
        return f"sa[({self.expr(1)}) & 3].{self.pick('abcd')}"

    def expr(self, depth=0):
        r = self.r.random()
        if depth > 3 or r < 0.25:
            if self.pure:
                return self.pick([self.var(), self.var(), self.const()])
            return self.pick([self.var(), self.var(), self.const(), f"arr[{self.r.randint(0, 15)}]",
                              f"s.{self.pick('abcd')}", "*p", f"p[{self.r.randint(-2, 2)}]"])
        if r < 0.65:
            op = self.pick(["+", "-", "*", "&", "|", "^", "<<", ">>", "<", ">", "<=", ">=",
                            "==", "!=", "&&", "||", "+", "-", "*"])
            a, b = self.expr(depth + 1), self.expr(depth + 1)
            if op in ("<<", ">>"):
                return f"(({a}) {op} (({b}) & 31))"
            return f"(({a}) {op} ({b}))"
        if r < 0.72:
            f = self.pick(["sdiv", "smod", "udiv", "umod"])
            return f"{f}({self.expr(depth + 1)}, {self.expr(depth + 1)})"
        if r < 0.8:
            return f"(({self.pick(TYPES)})({self.expr(depth + 1)}))"
        if r < 0.86:
            return f"({self.pick(['-', '~', '!'])}({self.expr(depth + 1)}))"
        if r < 0.92:
            return f"(({self.expr(depth + 1)}) ? ({self.expr(depth + 1)}) : ({self.expr(depth + 1)}))"
        if r < 0.96 and self.nfuncs > 0:
            return f"f{self.r.randint(0, self.nfuncs - 1)}({', '.join(self.expr(depth + 2) for _ in range(self.nargs))})"
        # (no assignments inside expressions: C leaves their order unspecified)
        return f"({self.expr(depth + 1)} {self.pick(['+', '-', '^', '|'])} {self.expr(depth + 1)})"

    def stmt(self, depth):
        r = self.r.random()
        ind = "    " * (depth + 1)
        if depth > 2 or r < 0.45:
            op = self.pick(["=", "=", "+=", "-=", "*=", "&=", "|=", "^=", "<<=", ">>="])
            rhs = self.expr()
            if op in ("<<=", ">>="):
                rhs = f"({rhs}) & 31"
            return f"{ind}{self.lvalue()} {op} {rhs};\n"
        if r < 0.55:
            return f"{ind}{self.lvalue()}{self.pick(['++', '--'])};\n"
        if r < 0.7:
            s = f"{ind}if ({self.expr()}) {{\n" + self.block(depth + 1) + f"{ind}}}"
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
            s = f"{ind}switch (({self.expr()}) & 15) {{\n"
            for c in cases:
                s += f"{ind}case {c}:\n" + self.block(depth + 1)
                if self.r.random() < 0.7:
                    s += f"{ind}    break;\n"
            if self.r.random() < 0.5:
                s += f"{ind}default:\n" + self.block(depth + 1)
            return s + f"{ind}}}\n"
        return f"{ind}p = &arr[2 + (({self.expr()}) & 7)];\n"

    def array_loop(self, depth, ind):
        """Loops that walk arrays by their counter (what strength reduction
        rewrites into pointer loops)."""
        v = f"i{depth}"
        kind = self.r.randint(0, 5)
        lo = self.r.randint(0, 5)
        hi = self.r.randint(lo, 16)
        st = self.r.choice([1, 1, 1, 2, 3])
        if kind == 0:
            return (f"{ind}for ({v} = {lo}; {v} < {hi}; {v} += {st})\n"
                    f"{ind}    arr[{v}] {self.pick(['+=', '^=', '-=', '='])} {self.expr(2)};\n")
        if kind == 1:
            return (f"{ind}for ({v} = {hi - 1}; {v} >= {lo}; {v}--)\n"
                    f"{ind}    mix(arr[{v}] + {v});\n")
        if kind == 2:
            f = self.pick("abcd")
            return (f"{ind}for ({v} = 0; {v} < 4; {v}++) {{\n"
                    f"{ind}    sa[{v}].{f} += {self.expr(2)};\n{ind}    mix(sa[{v}].{f});\n{ind}}}\n")
        if kind == 3:
            return (f"{ind}{{ int *q = arr + {lo}; while (q < arr + {hi}) {{ *q = *q * 3 + {self.expr(2)}; mix(*q++); }} }}\n")
        if kind == 4:
            return (f"{ind}for ({v} = {lo}; {v} != {hi}; {v}++)\n"
                    f"{ind}    {{ bytes[{v}] = {self.expr(2)}; mix(bytes[{v}] + shorts[{v}]); shorts[{v}] -= bytes[{v}]; }}\n")
        return (f"{ind}for ({v} = {lo}; {v} < {hi}; {v}++) {{ int j{depth}; for (j{depth} = 0; j{depth} < 4; j{depth}++) "
                f"grid[j{depth}][{v}] += arr[{v}] ^ j{depth}; mix(grid[{v} & 3][{v}]); }}\n")

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
            self.nfuncs = k                 # only call earlier functions
            self.pure = True
            body = ""
            for j in range(r.randint(0, 3)):
                body += f"    {self.pick(TYPES)} l{j} = {self.expr()};\n"
                self.vars.append(f"l{j}")
            expr = self.expr(1)
            out.append(f"static int f{k}({', '.join(params)})\n{{\n{body}    return {expr};\n}}\n")
        self.nfuncs = total
        self.pure = False
        nv = r.randint(3, 16)
        decls = [(self.pick(TYPES), f"v{j}") for j in range(nv)]
        self.vars = [n for _, n in decls]
        body = "int main(void)\n{\n    int i0, i1, i2, i3, k;\n"
        for t, n in decls:
            body += f"    {t} {n} = {self.const()};\n"
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
    subprocess.run(["gcc", "-w", "-O0", "-fwrapv", "-funsigned-char", "-o", exe, c], check=True)
    return subprocess.run([exe], capture_output=True, timeout=10).stdout, c


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
            want, path = run_gcc(src, tmp)
            for isa in isas:
                try:
                    _, img, _ = driver.build([path], isa, verify_ir=True)
                    m = driver.run_image(img, isa, max_cycles=50_000_000)
                    got = bytes(m.dev.out)
                    err = m.error or (m.traps and str(m.traps[0]))
                except (CompileError, Exception) as e:   # noqa: BLE001
                    got, err = b"", f"{type(e).__name__}: {e}"
                if got != want or err:
                    bad += 1
                    print(f"seed {seed} {isa}: got {got!r} want {want!r} {err or ''}")
                    if args.keep:
                        os.makedirs(args.keep, exist_ok=True)
                        with open(os.path.join(args.keep, f"fuzz{seed}.c"), "w") as f:
                            f.write(src)
            if (n + 1) % 10 == 0:
                print(f"{n + 1} programs, {bad} failures", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
