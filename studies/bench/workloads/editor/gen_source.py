"""The file the editor edits: a made-up C module, written by a
deterministic generator so the workload doesn't depend on any real file
in the repository.

It has what C's colouring has to cope with: block comments over several
lines, // comments, string and character literals with escapes, decimal
and hex numbers, preprocessor lines, keywords; indentation by tabs, which
the editor expands; and now and then a line longer than the window, which
it clips. The functions come one after another from one generator, so a
smaller file is the start of a larger one.
"""

import bisect


class Rng:
    """Numerical Recipes' LCG, the top 24 bits used."""

    def __init__(self, seed):
        self.s = seed & 0xFFFFFFFF

    def next(self):
        self.s = (self.s * 1664525 + 1013904223) & 0xFFFFFFFF
        return self.s >> 8

    def below(self, n):
        return self.next() % n

    def pick(self, seq):
        return seq[self.below(len(seq))]


class Zipf:
    """Words drawn with weight 1/(rank + 2), the first the commonest."""

    def __init__(self, words):
        self.words = words.split()
        self.cum = []
        t = 0.0
        for k in range(len(self.words)):
            t += 1.0 / (k + 2)
            self.cum.append(t)

    def draw(self, rng):
        x = rng.next() / float(1 << 24) * self.cum[-1]
        return self.words[min(bisect.bisect_left(self.cum, x), len(self.words) - 1)]


VARS = Zipf("len n i p buf count k dev q s err pos size off t flags v head next "
            "base mask w rx tx id val tail bit page slot line")
FIELDS = Zipf("len count next head tail flags state base size id mask data prev "
              "owner refs timeout irq lock")
WORDS = Zipf("the a of to is and it in for this that we be on if not when one with by "
             "its from at so but as all then are buffer queue device interrupt lock "
             "count entry caller ring free full empty first last slot page frame "
             "register cycle retry error must never only before after held")
NOUNS = ["ring", "queue", "slot", "page", "frame", "dev", "port", "chan", "buf", "irq",
         "timer", "table"]
VERBS = ["init", "reset", "push", "pop", "take", "give", "scan", "flush", "start", "stop",
         "find", "drain", "claim", "post", "wait", "poll"]
TYPES = ["int", "unsigned", "struct ring *", "char *", "const char *", "unsigned char",
         "struct dev *", "short"]


def _sentence(rng, lo, hi):
    w = [WORDS.draw(rng) for _ in range(lo + rng.below(hi - lo + 1))]
    w[0] = w[0].capitalize()
    return " ".join(w) + "."


def _decl(t, name):
    return t + name if t.endswith("*") else f"{t} {name}"


def _num(rng):
    r = rng.below(5)
    if r == 0:
        return f"0x{rng.below(1 << 16):04x}"
    if r == 1:
        return str(1 << rng.below(12))
    return str(rng.below(100))


def _expr(rng, depth=0):
    r = rng.below(8)
    if depth > 1 or r < 3:
        return VARS.draw(rng)
    if r == 3:
        return _num(rng)
    if r == 4:
        return f"{VARS.draw(rng)}->{FIELDS.draw(rng)}"
    if r == 5:
        return f"{rng.pick(VERBS)}_{rng.pick(NOUNS)}({VARS.draw(rng)})"
    op = rng.pick(["+", "-", "&", "|", "<<", ">>", "==", "!=", "<", ">=", "&&", "||"])
    return f"{_expr(rng, depth + 1)} {op} {_expr(rng, depth + 1)}"


def _block(rng, ind, n, depth):
    out = []
    tab = "\t" * ind
    for _ in range(n):
        r = rng.below(16)
        if depth > 2:
            r = rng.below(5)
        if r < 4:
            out.append(f"{tab}{VARS.draw(rng)} = {_expr(rng)};")
        elif r == 4:
            out.append(f"{tab}{VARS.draw(rng)}->{FIELDS.draw(rng)} {rng.pick(['=', '+=', '|=', '&= ~'])}"
                       f" {_expr(rng)};")
        elif r == 5:
            out.append(f"{tab}if ({_expr(rng)})")
            out.append(f"{tab}\treturn {rng.pick(['-1', '0', VARS.draw(rng), '-EAGAIN'])};")
        elif r == 6:
            out.append(f"{tab}if ({_expr(rng)}) {{")
            out += _block(rng, ind + 1, 1 + rng.below(3), depth + 1)
            if rng.below(2):
                out.append(f"{tab}}} else {{")
                out += _block(rng, ind + 1, 1 + rng.below(2), depth + 1)
            out.append(f"{tab}}}")
        elif r == 7:
            v = rng.pick(["i", "k", "j"])
            out.append(f"{tab}for ({v} = 0; {v} < {_expr(rng, 1)}; {v}++) {{")
            out += _block(rng, ind + 1, 1 + rng.below(3), depth + 1)
            out.append(f"{tab}}}")
        elif r == 8:
            out.append(f"{tab}/* {_sentence(rng, 3, 9)} */")
        elif r == 9:
            out.append(f"{tab}printk(\"{rng.pick(NOUNS)}%d: {' '.join(WORDS.draw(rng) for _ in range(rng.below(4) + 1))}"
                       f" %x\\n\", {VARS.draw(rng)}, {VARS.draw(rng)});")
        elif r == 10:
            # a long call, wider than the window
            args = ", ".join(_expr(rng, 1) for _ in range(4 + rng.below(4)))
            out.append(f"{tab}{VARS.draw(rng)} = {rng.pick(VERBS)}_{rng.pick(NOUNS)}_locked({args});"
                       f" // {_sentence(rng, 2, 6)}")
        elif r == 11:
            out.append(f"{tab}switch ({VARS.draw(rng)}) {{")
            for _ in range(2 + rng.below(3)):
                c = rng.pick(["'a'", "'\\n'", "'\\0'", "'\\''", _num(rng)])
                out.append(f"{tab}case {c}:")
                out += _block(rng, ind + 1, 1 + rng.below(2), depth + 1)
                out.append(f"{tab}\tbreak;")
            out.append(f"{tab}default:")
            out.append(f"{tab}\treturn -1;")
            out.append(f"{tab}}}")
        elif r == 12:
            out.append(f"{tab}while ({_expr(rng)})")
            out.append(f"{tab}\t{VARS.draw(rng)}++;")
        elif r == 13:
            out.append(f"{tab}/*")
            for _ in range(1 + rng.below(3)):
                out.append(f"{tab} * {_sentence(rng, 4, 10)}")
            out.append(f"{tab} */")
        else:
            out.append(f"{tab}{rng.pick(VERBS)}_{rng.pick(NOUNS)}({VARS.draw(rng)}, {_expr(rng)});")
    return out


def _function(rng):
    name = f"{rng.pick(NOUNS)}_{rng.pick(VERBS)}"
    out = ["/*", f" * {name}: {_sentence(rng, 4, 10)}"]
    for _ in range(rng.below(3)):
        out.append(f" * {_sentence(rng, 5, 12)}")
    out.append(" */")
    args = ", ".join(_decl(rng.pick(TYPES), VARS.draw(rng)) for _ in range(1 + rng.below(3)))
    out.append(f"{'static ' if rng.below(3) else ''}{_decl(rng.pick(TYPES), name)}({args})")
    out.append("{")
    out.append(f"\tint {VARS.draw(rng)}, {VARS.draw(rng)} = 0;")
    out.append(f"\tunsigned {VARS.draw(rng)} = {_num(rng)};")
    out.append("")
    out += _block(rng, 1, 4 + rng.below(6), 0)
    out.append(f"\treturn {_expr(rng)};")
    out.append("}")
    out.append("")
    return out


def _struct(rng):
    name = rng.pick(NOUNS)
    out = [f"struct {name} {{"]
    for _ in range(3 + rng.below(5)):
        f = FIELDS.draw(rng)
        out.append(f"\t{_decl(rng.pick(TYPES), f)};{' ' * (1 + rng.below(8))}/* {_sentence(rng, 2, 6)} */")
    out.append("};")
    out.append("")
    return out


def source(nfuncs):
    """A C module of nfuncs functions, with a header, defines and structs
    among them."""
    rng = Rng(0x45444954)
    out = ["/*", " * ring.c: buffers in rings, for the serial ports and the disk queue.",
           " *", " * Generated for the editor benchmark; it is not meant to compile.", " */",
           "", "#include <stddef.h>", "#include \"ring.h\"", "#include \"dev.h\"", ""]
    for k in range(6):
        out.append(f"#define {rng.pick(NOUNS).upper()}_{rng.pick(['MAX', 'MASK', 'SHIFT', 'BASE'])}{k}\t{_num(rng)}")
    out.append("")
    out.append("static const char *const names[] = {")
    out.append("\t" + ", ".join(f"\"{rng.pick(NOUNS)}{k}\"" for k in range(8)) + ",")
    out.append("};")
    out.append("")
    for k in range(nfuncs):
        if k % 5 == 0:
            out += _struct(rng)
        out += _function(rng)
    return ("\n".join(out) + "\n").encode()
