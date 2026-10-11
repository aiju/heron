#!/usr/bin/env python3
"""Reference implementations of the test programs.

Computes the exact console output each program in programs/*.s should
produce and writes it to programs/expected/<name>.txt. This is meant as an
independent check: it never runs the simulator or reads the assembly, it
just does the same job in plain Python (emulating the programs' integer
arithmetic where the exact bits matter, as in mandel).

    python3 programs/reference.py          # regenerate everything
    python3 programs/reference.py sort     # just one
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECTED = os.path.join(HERE, "expected")


# --------------------------------------------------------------------------
# Helpers shared by several programs


def u16(x):
    return x & 0xFFFF


def s16(x):
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


def u32(x):
    return x & 0xFFFFFFFF


def s32(x):
    x &= 0xFFFFFFFF
    return x - 0x100000000 if x & 0x80000000 else x


def tdiv(a, b):
    """Integer division rounding toward zero, remainder with the dividend's sign."""
    q = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        q = -q
    return q, a - q * b


class XorShift16:
    """lib/rand.s: x ^= x << 7; x ^= x >> 9; x ^= x << 8 (16-bit)."""

    def __init__(self, seed=1):
        self.x = seed & 0xFFFF or 1

    def next(self):
        x = self.x
        x ^= (x << 7) & 0xFFFF
        x ^= x >> 9
        x ^= (x << 8) & 0xFFFF
        self.x = x
        return x


def crc16_ccitt(data, crc=0xFFFF):
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


# --------------------------------------------------------------------------
# Programs


def hello():
    return "Hello, world!\n"


def arith():
    out = ["16-bit multiply and divide\n"]
    pairs16 = [
        (0, 0), (0, 1), (1, 1), (1, 0xFFFF), (0xFFFF, 0xFFFF), (0x8000, 0xFFFF),
        (0x8000, 0x8000), (0x8000, 1), (0x7FFF, 0x7FFF), (0x7FFF, 0x8000),
        (0xFFFF, 0x8000), (0xFFFF, 0x8001), (0xFFFE, 0xFFFF), (1234, 567),
        (u16(-1234), 77), (100, u16(-7)), (u16(-100), u16(-7)), (u16(-100), 7),
        (12345, 10), (0x8001, 0x7FFF), (40000, 3), (0xFFFF, 0),
    ]
    for a, b in pairs16:
        out.append(f"a={a:04X} b={b:04X}\n")
        out.append(f"  umul {a * b:08X}  smul {s16(a) * s16(b)}")
        if b == 0:
            out.append("\n  divide by zero\n")
            continue
        q, r = tdiv(s16(a), s16(b))
        out.append(f"\n  udiv {a // b} r {a % b}  sdiv {s16(q)} r {s16(r)}\n")

    out.append("32-bit add, subtract, compare\n")
    pairs32 = [
        (0x0000FFFF, 0x00000001), (0xFFFFFFFF, 0x00000001), (0x80000000, 0xFFFFFFFF),
        (0x7FFFFFFF, 0x80000000), (0x12345678, 0x12345678), (0x00010000, 0x0000FFFF),
        (123456789, 987654321), (0, 0xFFFFFFFF), (0xFFFF0000, 0xFFFEFFFF),
        (5, 0xFFFFFFFB),
    ]

    def cmpch(x, y):
        return "<" if x < y else "=" if x == y else ">"

    for a, b in pairs32:
        out.append(f"{a:08X} {b:08X}  sum {u32(a + b):08X}  diff {u32(a - b):08X}"
                   f"  u{cmpch(a, b)} s{cmpch(s32(a), s32(b))}\n")

    out.append("32/16 divide\n")
    divs = [
        (0xFFFFFFFF, 0xFFFF), (0xFFFFFFFF, 1), (123456789, 10), (1000000, 7),
        (0x12345678, 0x1234), (0, 5), (0x80000000, 0x8000), (0xFFFFFFFE, 0x8001),
        (3000000000, 60000), (1, 0xFFFF),
    ]
    for a, d in divs:
        out.append(f"{a} / {d} = {a // d} r {a % d}\n")
    return "".join(out)


def strings():
    out = []
    q = lambda b: '"' + b.decode("latin-1") + '"'
    hello_s = b"Hello, world!"
    fox = b"The quick brown fox jumps over the lazy dog."
    for t in [b"", b"x", hello_s, fox]:
        out.append(f"strlen({q(t)}) = {len(t)}\n")
    out.append(f'strcpy -> "copy me"\n')

    def strcmp(a, b):
        for x, y in zip(a + b"\0", b + b"\0"):
            if x != y or x == 0:
                return x - y
        return 0

    pairs = [(b"abc", b"abc"), (b"abc", b"abd"), (b"abd", b"abc"), (b"ab", b"abc"),
             (b"abc", b"ab"), (b"", b""), (b"Zebra", b"apple"), (b"\xe9t\xe9", b"abc")]
    for a, b in pairs:
        out.append(f"strcmp({q(a)}, {q(b)}) = {strcmp(a, b)}\n")

    alpha = b"0123456789abcdefghijklmnopqrstuvwxyz"
    for dst, src, n in [(0, 0, 11), (3, 5, 9), (4, 1, 7), (2, 2, 20), (5, 7, 1)]:
        buf = bytearray(b"." * 32)
        buf[dst:dst + n] = alpha[src:src + n]
        out.append("memcpy  " + buf.decode() + "\n")

    buf = bytearray(b"-" * 24)
    buf[3:12] = b"*" * 9
    buf[14:20] = b"#" * 6
    out.append("memset  " + buf.decode() + "\n")

    buf = bytearray(alpha[:11])
    buf[2:8] = bytes(buf[0:6])
    out.append("memmove " + buf.decode() + "\n")
    buf[0:7] = bytes(buf[3:10])
    out.append("memmove " + buf.decode() + "\n")

    out.append(f"reverse {q(hello_s[::-1])}\n")
    out.append(f"upper   {q(fox.upper())}\n")
    paragraph = (b"  It was the best of times, it was the worst of times,\n"
                 b"\tit was the age of wisdom,  it was the age of foolishness,\n"
                 b"it was the epoch of belief, it was the epoch of incredulity, \n"
                 b"it was the season of Light, it was the season of Darkness...\n\n")
    words = len(bytes(c if c > 32 else 32 for c in paragraph).split())
    out.append(f"words in paragraph: {words}\n")
    return "".join(out)


def sieve():
    n = 8192
    flags = [True] * n
    flags[0] = flags[1] = False
    for i in range(2, n):
        if i * i >= n:
            break
        if flags[i]:
            for j in range(i * i, n, i):
                flags[j] = False
    primes = [i for i in range(n) if flags[i]]
    return (f"primes below 8192: {len(primes)}\n"
            "last ten:" + "".join(f" {p}" for p in primes[-10:]) + "\n")


def sort():
    rng = XorShift16(12345)
    big = sorted(rng.next() for _ in range(256))
    small = sorted(rng.next() for _ in range(64))

    def report(a):
        s1 = s2 = 0
        for x in a:
            s1 = (s1 + x) & 0xFFFF
            s2 = (s2 + s1) & 0xFFFF
        return f"sorted, checksum {s1:04X} {s2:04X}\n"

    out = ["quicksort 256: ", report(big)]
    out.append("  " + " ".join(f"a[{i}]={big[i]}" for i in (0, 1, 127, 128, 254, 255)) + "\n")
    out += ["insertion sort 64: ", report(small)]
    out.append("  " + " ".join(f"a[{i}]={small[i]}" for i in (0, 31, 63)) + "\n")
    return "".join(out)


def fib():
    calls = 0

    def rec(n):
        nonlocal calls
        calls += 1
        return n if n < 2 else rec(n - 1) + rec(n - 2)

    f18 = rec(18)
    out = [f"recursive fib(18) = {f18} ({calls} calls)\n"]
    a, b = 0, 1
    for n in range(47):
        out.append(f"fib({n}) = {a}\n")
        a, b = b, a + b
    return "".join(out)


def crc():
    rng = XorShift16(0xACE1)
    buf = b"".join(rng.next().to_bytes(2, "little") for _ in range(512))
    c9 = crc16_ccitt(b"123456789")
    assert c9 == 0x29B1
    c1k = crc16_ccitt(buf)
    return (f'bitwise "123456789": {c9:04X}\n'
            f'table   "123456789": {c9:04X}\n'
            f"bitwise 1 KB buffer: {c1k:04X}\n"
            f"table   1 KB buffer: {c1k:04X}\n")


def mandel():
    # 8.8 fixed point, the same integer steps as mandel.s
    W, H, MAXIT = 48, 20, 16
    X0, XSTEP, YSTEP = -563, 16, 31
    Y0 = -(YSTEP * (H - 1)) // 2
    palette = " .,,::;;--==++*#@"
    out = []
    for row in range(H):
        cy = Y0 + row * YSTEP
        line = []
        for col in range(W):
            cx = X0 + col * XSTEP
            x = y = it = 0
            while it < MAXIT:
                if abs(x) >= 512 or abs(y) >= 512:
                    break
                xx = (x * x) >> 8
                yy = (y * y) >> 8
                if xx + yy > 1024:
                    break
                xy = s16((x * y) >> 8)          # arithmetic shift: rounds down
                x = s16(xx - yy + cx)
                y = s16(2 * xy + cy)
                it += 1
            line.append(palette[it])
        out.append("".join(line) + "\n")
    return "".join(out)


def life():
    rows, cols, gens = 16, 32, 20
    live = {(0, 1), (1, 2), (2, 0), (2, 1), (2, 2),            # glider
            (8, 23), (8, 24), (8, 25),                         # blinker
            (12, 7), (12, 8), (12, 9), (13, 6), (13, 7), (13, 8),  # toad
            (3, 27), (3, 28), (4, 27), (4, 28),                # block
            (7, 31), (7, 0), (7, 1),                           # blinker across the left/right seam
            (15, 20), (0, 20), (1, 20)}                        # blinker across the top/bottom seam
    pops = []
    for _ in range(gens):
        pops.append(len(live))
        new = set()
        for r in range(rows):
            for c in range(cols):
                n = sum(((r + dr) % rows, (c + dc) % cols) in live
                        for dr in (-1, 0, 1) for dc in (-1, 0, 1) if dr or dc)
                if n == 3 or (n == 2 and (r, c) in live):
                    new.add((r, c))
        live = new
    pops.append(len(live))
    out = ["population:" + "".join(f" {p}" for p in pops) + "\n"]
    for r in range(rows):
        out.append("".join("#" if (r, c) in live else "." for c in range(cols)) + "\n")
    return "".join(out)


def queens():
    n = 8
    sols = []

    def place(cols):
        row = len(cols)
        if row == n:
            sols.append(cols)
            return
        for c in range(n):          # lowest column first, like the bitmask search
            if all(c != pc and abs(c - pc) != row - pr for pr, pc in enumerate(cols)):
                place(cols + [c])

    place([])
    first = sols[0]
    out = [f"solutions: {len(sols)}\n", "first:" + "".join(f" {c + 1}" for c in first) + "\n"]
    for c in first:
        out.append(" ".join("Q" if i == c else "." for i in range(n)) + "\n")
    return "".join(out)


def bst():
    rng = XorShift16(0xBEEF)
    keys = [rng.next() for _ in range(100)]
    tree = {}                       # key -> [left, right]; equal keys go right
    root = None
    for k in keys:
        if root is None:
            root = k
            tree[k] = [None, None]
            continue
        node = root
        while True:
            side = 0 if k < node else 1
            if tree[node][side] is None:
                tree[node][side] = k
                tree[k] = [None, None]
                break
            node = tree[node][side]

    def height(n):
        return 0 if n is None else 1 + max(height(tree[n][0]), height(tree[n][1]))

    order = sorted(keys)
    return ("every 10th key in order:" + "".join(f" {k}" for k in order[::10]) + "\n"
            f"visited {len(order)} nodes, in order: yes\n"
            f"height: {height(root)}\n")


def bignum():
    import math
    return "".join(f"{n}! = {math.factorial(n)}\n" for n in (10, 20, 30, 40, 52))


# Console input of rpn.s (its ";! input:" line). Kept here rather than read from
# the .s file so this script never looks at the assembly; if the two drift
# apart, the test fails.
RPN_INPUT = ("3 4 +\n5 1 2 + 4 * + 3 -\n2 3 4 * +\n-7 2 /\n7 -2 /\n-7 -2 /\n"
             "100 7 / 100 7 * -\n1 2 3\n1 +\n9 -\n5 0 /\n5 5 5 - /\n32767 1 +\n"
             "-32768 -1 /\n300 300 *\n-300 300 *\n70000 1 +\n12 abc +\n4x 1\n--5\n-\n"
             "\t 42   -1  \n\n1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16\n"
             "1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17\n2 3 * 4 5 * + 6 /")


def lines_of(text):
    """Lines as lib/console.s gets() returns them (a last line needs no newline)."""
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def rpn():
    out = []
    for line in lines_of(RPN_INPUT):
        assert len(line) < 80
        stack, err = [], None
        for tok in line.replace("\t", " ").split():
            if tok in ("+", "-", "*", "/"):
                if len(stack) < 2:
                    err = "stack underflow"
                    break
                b = stack.pop()
                a = stack.pop()
                if tok == "+":
                    r = a + b
                elif tok == "-":
                    r = a - b
                elif tok == "*":
                    r = a * b
                else:
                    if b == 0:
                        err = "divide by zero"
                        break
                    r = tdiv(a, b)[0]
                stack.append(s16(r))
                continue
            digits = tok[1:] if tok.startswith("-") else tok
            if not digits or not all("0" <= ch <= "9" for ch in digits):
                err = "bad number"
                break
            v = 0
            for ch in digits:
                v = (v * 10 + ord(ch) - 48) & 0xFFFF
            if len(stack) == 16:
                err = "stack overflow"
                break
            stack.append(s16(-v if tok.startswith("-") else v))
        if err:
            res = "error: " + err
        else:
            res = " ".join(str(x) for x in stack) if stack else "(empty)"
        out.append(f"{line} => {res}\n")
    return "".join(out)


# Console input of monitor.s (its ";! input:" line), see RPN_INPUT.
MONITOR_INPUT = ("f 8000 80 2E\nw 8000 1234 ABCD 0 ffff\nb 8008 48 65 6C 6C 6F\n"
                 "s 8010 Hello, monitor!\nd 8000 30\nc 8010 8021 7\nd 8020 10\n"
                 "c 8000 8002 6\nd 8000 10\nr 8000\nr 8011\nx 1234\nd 8000\n"
                 "w 8000 12G4\nd 8000 3 4\nb 8000\n\n  d   803E   5  \n"
                 "b 8050 0 1 7F 80 FF 41 61 20 7E\nd 8050 9\nf 8060 5 41\nd 805E 8\n"
                 "c 8061 8060 4\nd 8060 5\nw 8070 10000 BEEF\nr 8070\nd 8070 0\nr 8072")


def monitor():
    mem = bytearray(0x10000)
    out = []

    def hexnum(tok):
        if not tok or any(c not in "0123456789abcdefABCDEF" for c in tok):
            raise ValueError
        return int(tok, 16) & 0xFFFF

    for line in lines_of(MONITOR_INPUT):
        out.append(f"> {line}\n")
        body = line.lstrip(" \t")
        if not body:
            continue
        cmd, rest = body[0], body[1:]
        try:
            if cmd == "s":
                # the address, then exactly one blank, then the text
                rest = rest.lstrip(" \t")
                end = 0
                while end < len(rest) and rest[end] not in " \t":
                    end += 1
                addr = hexnum(rest[:end])
                for i, ch in enumerate(rest[end + 1:]):
                    mem[(addr + i) & 0xFFFF] = ord(ch)
                continue
            # the command letter needn't be followed by a blank: "d8000 4" works
            args = [hexnum(t) for t in rest.replace("\t", " ").split()]
            if cmd == "w" and len(args) >= 2:
                a = args[0]
                for v in args[1:]:
                    a &= 0xFFFE                  # word accesses ignore bit 0
                    mem[a], mem[a + 1] = v & 0xFF, v >> 8
                    a = (a + 2) & 0xFFFF
            elif cmd == "b" and len(args) >= 2:
                for i, v in enumerate(args[1:]):
                    mem[(args[0] + i) & 0xFFFF] = v & 0xFF
            elif cmd == "f" and len(args) == 3:
                for i in range(args[1]):
                    mem[(args[0] + i) & 0xFFFF] = args[2] & 0xFF
            elif cmd == "c" and len(args) == 3:
                src, dst, n = args
                data = bytes(mem[(src + i) & 0xFFFF] for i in range(n))
                for i in range(n):
                    mem[(dst + i) & 0xFFFF] = data[i]
            elif cmd == "r" and len(args) == 1:
                a = args[0] & 0xFFFE
                out.append(f"{args[0]:04X} = {mem[a] | mem[a + 1] << 8:04X}\n")
            elif cmd == "d" and len(args) == 2:
                a, n = args
                while n:
                    k = min(16, n)
                    chunk = [mem[(a + i) & 0xFFFF] for i in range(k)]
                    text = "".join(chr(b) if 32 <= b <= 0x7E else "." for b in chunk)
                    out.append(f"{a:04X}:" + "".join(f" {b:02X}" for b in chunk)
                               + "   " * (16 - k) + "  " + text + "\n")
                    a, n = (a + k) & 0xFFFF, n - k
            else:
                raise ValueError
        except ValueError:
            out.append("?\n")
    return "".join(out)


def interrupts():
    total = sum(i * i for i in range(1, 1001))
    return ("timer interrupts\n"
            f"sum of squares 1..1000 = {total}\n"
            "interrupted during the sum: yes\n"
            "sleep 10: 10 ticks\n"
            "sleep 25: 25 ticks\n"
            "timer off, tick count unchanged: yes\n"
            "swi: hello from a system call\n"
            "done\n")


def matmul():
    n = 8
    rng = XorShift16(2024)
    vals = [(rng.next() >> 4) - 2048 for _ in range(2 * n * n)]
    a = [vals[i * n:(i + 1) * n] for i in range(n)]
    b = [vals[n * n + i * n:n * n + (i + 1) * n] for i in range(n)]
    c = [[s32(sum(a[i][k] * b[k][j] for k in range(n))) for j in range(n)] for i in range(n)]
    total = s1 = s2 = 0
    for row in c:
        for x in row:
            x = u32(x)
            total += x
            for w in (x & 0xFFFF, x >> 16):
                s1 = (s1 + w) & 0xFFFF
                s2 = (s2 + s1) & 0xFFFF
    return ("row 3:" + "".join(f" {x}" for x in c[3]) + "\n"
            f"trace: {s32(sum(c[i][i] for i in range(n)))}\n"
            f"checksum: {u32(total):08X} {s1:04X} {s2:04X}\n")


PROGRAMS = {
    "hello": hello,
    "arith": arith,
    "strings": strings,
    "sieve": sieve,
    "sort": sort,
    "fib": fib,
    "crc": crc,
    "mandel": mandel,
    "life": life,
    "queens": queens,
    "bst": bst,
    "bignum": bignum,
    "rpn": rpn,
    "monitor": monitor,
    "interrupts": interrupts,
    "matmul": matmul,
}


def main(argv):
    names = argv or list(PROGRAMS)
    os.makedirs(EXPECTED, exist_ok=True)
    for name in names:
        text = PROGRAMS[name]()
        with open(os.path.join(EXPECTED, name + ".txt"), "w", encoding="latin-1", newline="") as f:
            f.write(text)
        print(f"{name:<12} {len(text):>6} bytes")


if __name__ == "__main__":
    main(sys.argv[1:])
