"""The files the text utilities work on, made up by a deterministic
generator: a system log, prose, a C-like source file and a password file.

Words are drawn from fixed vocabularies with Zipf-like frequencies (the
k-th most common word weighted 1/(k + 2.7)), so a word count's top ten
looks like a real text's. Everything comes from one linear congruential
generator, so the files depend only on the sizes asked for.
"""

import bisect


class Rng:
    """The generator: Numerical Recipes' LCG, the top 24 bits used."""

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
    """Words drawn with weight 1/(rank + 2.7), the first word the commonest."""

    def __init__(self, words):
        self.words = words
        self.cum = []
        t = 0.0
        for k in range(len(words)):
            t += 1.0 / (k + 2.7)
            self.cum.append(t)
        self.total = t

    def draw(self, rng):
        x = rng.next() / float(1 << 24) * self.total
        return self.words[min(bisect.bisect_left(self.cum, x), len(self.words) - 1)]


PROSE = Zipf("""
the of and to a in is it that was he for on are as with his they at be this
from have or by one had not but what all were when we there can an your which
their said if do will each about how up out them then she many some so these
would other into has more her two like him see time could no make than first
been its who now people my made over did down only way find use may water long
little very after words called just where most know get through back much go
good new write our me man too any day same right look think also around
another came come work three word must because does part even place well such
here take why things help put years different away again off went old number
great tell men say small every found still between name should home big give
air line set own under read last never us left end along while might next
sound below saw something thought both few those always looked show large
often together asked house world going want school important until form food
keep children feet land side without boy once animals life enough took
sometimes four head above kind began almost live page got earth need far hand
high year mother light parts country father let night following picture being
study second eyes soon times story boys since white days ever paper hard near
sentence better best across during today others however sure means knew try
told young miles sun ways thing whole hear example heard several change answer
room sea against top turned learn point city play toward five using himself
usually machine memory clock board signal register wire chip bus counter
latch gate adder carry shift store load fetch decode cycle microcode heron
river bird marsh reed wader feather grey patient stillness morning tide
""".split())

DAEMONS = [("kernel", 0), ("httpd", 212), ("sshd", 455), ("cron", 97), ("fend", 31),
           ("mail", 640), ("wsys", 77)]
LEVELS = ["INFO"] * 11 + ["WARN"] * 3 + ["ERROR"] * 2 + ["DEBUG"] * 4
PAGES = ["/", "/index.html", "/docs/isa.html", "/docs/bus.html", "/reports/",
         "/reports/0028.html", "/img/heron.png", "/src/fen.tar", "/docs/cpu.html",
         "/blog/2026/03/microcode.html", "/favicon.ico", "/robots.txt"]
USERS = ["emily", "root", "guest", "ada", "brian", "ken", "dennis", "grace", "linus"]
DEVICES = ["disk0", "disk1", "eth0", "tty1", "kbd0", "vid0", "uart2"]


def log(rng, n):
    """n lines of a system log: "Mar 14 09:12:33 heron httpd[212]: INFO ..."."""
    out = []
    t = 9 * 3600 + 12 * 60
    day = 14
    for _ in range(n):
        t += rng.below(40) if rng.below(5) else rng.below(400)
        if t >= 86400:
            t -= 86400
            day += 1
        d, pid = rng.pick(DAEMONS)
        level = rng.pick(LEVELS)
        if d == "httpd":
            code = rng.pick([200] * 12 + [304, 304, 404, 500])
            msg = (f"10.0.{rng.below(4)}.{rng.below(250) + 2} GET {rng.pick(PAGES)} "
                   f"{code} {rng.below(30000) + 120}")
            level = "ERROR" if code == 500 else "WARN" if code == 404 else "INFO"
        elif d == "sshd":
            u = rng.pick(USERS)
            msg = rng.pick([f"accepted key for {u} from 10.0.3.{rng.below(9) + 2}",
                            f"session closed for {u}",
                            f"failed password for {u} from 192.168.{rng.below(5)}.{rng.below(200)}"])
            level = "WARN" if msg.startswith("failed") else "INFO"
        elif d == "kernel":
            dev = rng.pick(DEVICES)
            if level == "ERROR":
                msg = f"{dev}: read failed at block {rng.below(200000)}"
            else:
                msg = rng.pick([f"{dev}: link up, {rng.pick([10, 100])} Mbit",
                                f"{dev}: {rng.below(64) + 1} interrupts coalesced",
                                f"page fault at 0x{rng.next():06x} in pid {rng.below(90) + 10}",
                                f"{dev}: queue depth {rng.below(16)}"])
        elif d == "cron":
            msg = f"({rng.pick(USERS)}) CMD {rng.pick(['backup', 'sync', 'rotate', 'mail -q', 'df'])}"
        else:
            words = " ".join(PROSE.draw(rng) for _ in range(rng.below(6) + 2))
            msg = f"{rng.pick(['job', 'task', 'window', 'queue'])} {rng.below(500)}: {words}"
        clock = f"{t // 3600:02d}:{t // 60 % 60:02d}:{t % 60:02d}"
        out.append(f"Mar {day:02d} {clock} heron {d}[{pid}]: {level} {msg}\n")
    return "".join(out)


def prose(rng, nwords):
    """About nwords words of text in paragraphs, lines filled to 72 columns."""
    out, line, para = [], "", 0
    words = 0
    while words < nwords:
        k = rng.below(13) + 5
        sent = [PROSE.draw(rng) for _ in range(k)]
        words += k
        sent[0] = sent[0].capitalize()
        if k > 9 and rng.below(2):
            sent[k // 2] += ","
        if rng.below(9) == 0:
            sent[-1] += ";"
            sent.append(PROSE.draw(rng))
        sent[-1] += "?" if rng.below(10) == 0 else "."
        for w in sent:
            if len(line) + 1 + len(w) > 72:
                out.append(line + "\n")
                line = ""
            line = line + " " + w if line else w
        para += 1
        if para >= rng.below(5) + 3:
            out.append(line + "\n\n")
            line, para = "", 0
    if line:
        out.append(line + "\n")
    return "".join(out)


IDENTS = Zipf("""
n i p s len buf b c k e x err name next count size line f t r out cap pos v
node list ctx dev flags mode state key val tmp addr data head tail w h y
""".split())
TYPES = ["int", "unsigned", "char *", "struct buf *", "const char *", "void", "struct node *"]
VERBS = ["read", "write", "grow", "find", "insert", "remove", "flush", "parse", "emit",
         "open", "close", "scan", "hash", "copy", "fill", "check", "walk", "free"]
NOUNS = ["buf", "line", "node", "list", "block", "page", "token", "table", "entry",
         "queue", "file", "word", "frame", "cell"]


def _expr(rng, depth=0):
    r = rng.below(6)
    if depth > 1 or r < 2:
        return IDENTS.draw(rng)
    if r == 2:
        return str(rng.pick([0, 1, 2, 4, 8, 16, 32, 255, 1024]))
    if r == 3:
        return f"{IDENTS.draw(rng)}->{IDENTS.draw(rng)}"
    op = rng.pick(["+", "-", "*", "&", "|", "<<", ">>", "==", "!=", "<", ">="])
    return f"{_expr(rng, depth + 1)} {op} {_expr(rng, depth + 1)}"


def _stmts(rng, indent, n, depth):
    out = []
    pad = "    " * indent
    for _ in range(n):
        r = rng.below(10)
        if r < 4 or depth > 2:
            out.append(f"{pad}{IDENTS.draw(rng)} = {_expr(rng)};")
        elif r == 4:
            out.append(f"{pad}{rng.pick(VERBS)}_{rng.pick(NOUNS)}({IDENTS.draw(rng)}, {_expr(rng)});")
        elif r == 5:
            out.append(f"{pad}if ({_expr(rng)})")
            out.append(f"{pad}    return {_expr(rng)};")
        elif r == 6:
            out.append(f"{pad}if ({_expr(rng)}) {{")
            out += _stmts(rng, indent + 1, rng.below(3) + 1, depth + 1)
            out.append(f"{pad}}}")
        elif r == 7:
            v = rng.pick(["i", "k", "j"])
            out.append(f"{pad}for ({v} = 0; {v} < {_expr(rng)}; {v}++) {{")
            out += _stmts(rng, indent + 1, rng.below(3) + 1, depth + 1)
            out.append(f"{pad}}}")
        elif r == 8:
            out.append(f"{pad}/* {' '.join(PROSE.draw(rng) for _ in range(rng.below(6) + 2))} */")
        else:
            out.append(f"{pad}while ({_expr(rng)})")
            out.append(f"{pad}    {IDENTS.draw(rng)}++;")
    return out


def _decl(t, name):
    return t + name if t.endswith("*") else f"{t} {name}"


def source(rng, nfuncs):
    """A C-like file of nfuncs functions, each with a comment."""
    out = ["/* generated: a module of a made-up program */", "#include <stdio.h>",
           "#include \"buf.h\"", ""]
    for _ in range(nfuncs):
        name = f"{rng.pick(VERBS)}_{rng.pick(NOUNS)}"
        out.append(f"/* {name}: {' '.join(PROSE.draw(rng) for _ in range(rng.below(8) + 3))} */")
        args = ", ".join(_decl(rng.pick(TYPES), IDENTS.draw(rng)) for _ in range(rng.below(3) + 1))
        out.append(f"{'static ' if rng.below(2) else ''}{_decl(rng.pick(TYPES), name)}({args})")
        out.append("{")
        out.append(f"    int {IDENTS.draw(rng)}, {IDENTS.draw(rng)} = 0;")
        out += _stmts(rng, 1, rng.below(6) + 3, 0)
        out.append(f"    return {_expr(rng)};")
        out.append("}")
        out.append("")
    return "\n".join(out) + "\n"


FIRST = ["Emily", "Ada", "Brian", "Ken", "Dennis", "Grace", "Linus", "Margaret", "Alan",
         "Barbara", "Edsger", "Frances", "John", "Niklaus", "Radia", "Sophie", "Tony"]
LAST = ["Hopper", "Lovelace", "Kernighan", "Thompson", "Ritchie", "Hamilton", "Turing",
        "Liskov", "Dijkstra", "Allen", "Backus", "Wirth", "Perlman", "Wilson", "Hoare"]


def passwd(rng, n):
    """n lines of a password file: name:x:uid:gid:Full Name:/home/name:/bin/sh."""
    out, seen = [], set()
    uids = list(range(1000, 1000 + 4 * n))
    for i in range(n):
        f, l = rng.pick(FIRST), rng.pick(LAST)
        name = (f[0] + l).lower()
        while name in seen:
            name += str(rng.below(10))
        seen.add(name)
        uid = uids.pop(rng.below(len(uids)))
        shell = rng.pick(["/bin/sh", "/bin/sh", "/bin/rc", "/bin/lisp"])
        out.append(f"{name}:x:{uid}:{100 + rng.below(4)}:{f} {l}:/home/{name}:{shell}\n")
    return "".join(out)


def files(p):
    """The files, by name: p has the lines of the log (LOG), the words of
    the prose (WORDS), the source's functions (FUNCS) and the users of the
    password file (USERS)."""
    rng = Rng(0x48455230)
    return {
        "syslog": log(rng, p["LOG"]).encode(),
        "notes.txt": prose(rng, p["WORDS"]).encode(),
        "main.c": source(rng, p["FUNCS"]).encode(),
        "passwd": passwd(rng, p["USERS"]).encode(),
    }
