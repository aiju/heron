"""A Forth system, in hand-written draft 2 assembly, compiling a program
from its source text and running it.

What it stands for: the Forth RFC 0005 calls a likely program for this
machine, the small interactive system (and threaded-code interpreter) a
minicomputer of the 1980s ran. kernel.s is the inner interpreter and the
primitives, compiler.s the outer interpreter, the dictionary and the
compiling words, forth.inc what they share. It's direct-threaded: a
thread's cells are machine-code addresses and NEXT is the one instruction
JMP [r8]+; the top of the data stack is in r11, the return stack is the
machine stack, and a colon definition's code field is CALL r12 (docol).
The dictionary is a hash table of linked headers, a name compared a cell
at a time.

What it does: the outer interpreter reads bench.fs, about 200 lines of
Forth with the size's parameters in front as constants, compiling its
definitions (IF/ELSE/THEN, BEGIN/WHILE/REPEAT, DO/LOOP/+LOOP, RECURSE,
CREATE/DOES>, VARIABLE, CONSTANT, ['], S") and then running them: BYTE's
sieve of Eratosthenes; Fibonacci by recursion and the n queens by
backtracking on bit masks; a quicksort of random numbers through an
EXECUTEd comparison, written out with pictured numeric output; the game of
life on a bordered board; and wc over a generated English text (the
`corpus` data) with a hash table of the words and their counts, sorted
alphabetically and written out as a table. Each job ends in a count or a
checksum that the program reports. reference() does the same jobs in
Python, by the same algorithms.

Where its time goes (`small`): in the inner interpreter, as in any threaded
Forth. NEXT alone is 28% of the instructions, and the time is spread over
the primitives the program uses most, a few instructions each: lit, +,
dovar (variables), swap, docol and exit, zbranch, the loop runtimes, over,
dup, @ and c@ lead, and `dict` in a profile is the code fields of the
words the program defined (their CALL r12 or CALL [r14 + n]). By job:
text about 30%, life 20%, sort 16%, sieve 13%, fib 8%, queens 7%, and
compiling the source (parse_name, find, interpret, number) 6%. The
source is the same at both sizes, so compiling it is three quarters of
the `tiny` size, whose jobs are tiny.
"""

import os

TITLE = "a Forth, compiling and running its program"
PART = "asm"
CATEGORY = "interpreters"
SOURCES = ["kernel.s", "compiler.s"]

# The parameters, and the Forth constants bench.fs knows them by
FORTH_NAMES = {
    "SIEVE": "sieve-size", "FIB": "fib-n",
    "QUEENS": "queens-n", "SORT": "sort-n",
    "LIFE": "life-size", "GENS": "life-gens",
}
SIZES = {
    "tiny": {"SIEVE": 30, "FIB": 5, "QUEENS": 4, "SORT": 5, "LIFE": 3, "GENS": 1,
             "TEXT": 24},
    "small": {"SIEVE": 1500, "FIB": 16, "QUEENS": 7, "SORT": 150, "LIFE": 14, "GENS": 5,
            "TEXT": 1000},
    "full": {"SIEVE": 8000, "FIB": 20, "QUEENS": 8, "SORT": 1000, "LIFE": 24, "GENS": 20, "TEXT": 8000}
}

HERE = os.path.dirname(os.path.abspath(__file__))
M = 0xFFFFFFFF


def source(p):
    """bench.fs with the size's parameters in front, ending in a newline
    and a NUL, as the Forth's outer interpreter expects."""
    with open(os.path.join(HERE, "bench.fs"), "rb") as f:
        text = f.read().rstrip(b"\n") + b"\n"
    head = "".join(f"{p[k]} constant {name}\n" for k, name in FORTH_NAMES.items())
    return head.encode() + text + b"\0"


# ---- the text wc reads ------------------------------------------------------------

VOCABULARY = """
the of and to a in is it that for was on are as with his they at be this
from have or by one had not but what all were when we there can an your
which their said if do will each about how up out them then she many some
so these would other into has more her two like him see time could no
make than first been its who now people my made over did down only way
find use may water long little very after words called just where most
know get through back much before go good new write our used me man too
any day same right look think also around another came come work three
word must because does part even place well such here take why things
help put years different away again off went old number great tell men
say small every found still between name should home big give air line
set own under read last never us left end along while might next sound
below saw something thought both few those always looked show large often
together asked house world going want school important until form food
keep children feet land side without boy once animals life enough took
sometimes four head above kind began almost live page got earth need far
hand high year mother light parts country father let night following
picture being study second eyes soon times story boys since white days
ever paper hard near sentence better best across during today others
however sure means knew try told young miles sun ways thing whole hear
example heard several change answer room sea against top turned learn
point city play toward five using himself usually money seen car morning
machine memory register program stack word number forth interpreter
""".split()


class Random:
    """The program's random numbers: a linear congruential generator's top
    16 bits."""

    def __init__(self, seed):
        self.seed = seed

    def __call__(self):
        self.seed = (self.seed * 1103515245 + 12345) & M
        return self.seed >> 16


def corpus(n):
    """n bytes of English-like text: sentences of words drawn with a skew
    toward the common ones, lines of up to 64 characters, now and then a
    blank line between paragraphs."""
    rnd = Random(2026)
    lines, line = [], ""
    while sum(len(x) + 1 for x in lines) + len(line) < n + 1:
        words = []
        for k in range(4 + rnd() % 11):
            u = rnd()               # u^3 of the vocabulary, u in [0, 1)
            words.append(VOCABULARY[len(VOCABULARY) * u * u * u >> 48])
            if k and rnd() % 9 == 0:
                words[-2] += ","
        words[0] = words[0].capitalize()
        words[-1] += "." if rnd() % 6 else "?"
        for w in words:
            if len(line) + 1 + len(w) > 64:
                lines.append(line)
                line = ""
            line = f"{line} {w}" if line else w
        if rnd() % 7 == 0:
            lines += [line, ""]
            line = ""
    lines.append(line)
    return ("\n".join(lines) + "\n").encode()[:n - 1] + b"\n"


def data(p):
    return {"forth_src": source(p), "corpus": corpus(p["TEXT"])}


# ---- the reference: the program's jobs in Python -------------------------------------

def bhash(h, data):
    for x in data:
        h = ((h * 33) ^ x) & M
    return h


def sieve(size):
    flags = [1] * size
    count = 0
    for i in range(size):
        if flags[i]:
            prime = 2 * i + 3
            for k in range(i + prime, size, prime):
                flags[k] = 0
            count += 1
    return count


def fib(n):
    return n if n < 2 else fib(n - 1) + fib(n - 2)


def queens(n):
    def place(row, cols, rising, falling):
        if row == n:
            return 1
        return sum(place(row + 1, cols | {c}, rising | {row + c}, falling | {row - c})
                   for c in range(n)
                   if c not in cols and row + c not in rising and row - c not in falling)
    return place(0, set(), set(), set())


def life(size, gens):
    stride = size + 2
    rnd = Random(777)
    board = [0] * (stride * stride)
    for y in range(1, size + 1):
        for x in range(1, size + 1):
            board[y * stride + x] = 1 if rnd() & 3 == 0 else 0
    for _ in range(gens):
        new = [0] * len(board)
        for y in range(1, size + 1):
            for x in range(1, size + 1):
                a = y * stride + x
                n = sum(board[a + d] for d in (-stride - 1, -stride, -stride + 1, -1, 1,
                                               stride - 1, stride, stride + 1))
                new[a] = 1 if n == 3 or (board[a] and n == 2) else 0
        board = new
    return bhash(5381, board)


def wc(text):
    counts = {}
    word = b""
    for c in text + b" ":
        c = c + 32 if 65 <= c <= 90 else c
        if 97 <= c <= 122:
            word += bytes([c])
        elif word:
            counts[word] = counts.get(word, 0) + 1
            word = b""
    table = b"".join(w + b" " + str(counts[w]).encode() + b"\n" for w in sorted(counts))
    return {"chars": len(text), "lines": text.count(b"\n"),
            "words": sum(counts.values()), "distinct": len(counts),
            "table": bhash(5381, table)}


def reference(p):
    out = []

    def report(label, value):
        out.append(f"{label} {value & M:08x}\n")

    report("primes", sieve(p["SIEVE"]))
    report("fib", fib(p["FIB"]))
    report("queens", queens(p["QUEENS"]))
    rnd = Random(12345)
    numbers = sorted(rnd() for _ in range(p["SORT"]))
    report("sorted", bhash(5381, b"".join(b"%d " % x for x in numbers)))
    report("life", life(p["LIFE"], p["GENS"]))
    for label, value in wc(corpus(p["TEXT"])).items():
        report(label, value)
    return "".join(out).encode()
