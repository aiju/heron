"""The machines on the website's simulator, and how each is made.

A machine is what the simulator (engine/) puts together and the page
shows: a board, the board's parameters, what to load where, and how the
page presents it (a terminal, a screen, help, examples). Each is made here
from its study's own build code, so it follows the study: when a study
changes its memory map or its build, its machine changes with it at the
next build, and the tests (tests/test_websim.py) boot every machine and
check that it answers.

To add a machine: write a function that returns a Machine (the existing
ones are the pattern), and put an entry for it in MACHINES. `check` is
what the tests do with it: steps of ("expect", text) (run until the
terminal has printed it), ("send", text) (type it), ("run", ms)
(simulated time) and ("screen",) (the screen isn't one colour).
"""

import os
import time
from dataclasses import dataclass, field

from heron import ROOT

# Each draft at a clock its hardware might have: the 1b hardware runs at 3
# MHz (report 0012), and draft 2 here at its Fen board's 6 MHz
# (studies/fen/board).
CLOCK = {"v1b": 3e6, "v2": 6e6}
DRAFT = {"v1b": "draft 1b", "v2": "draft 2"}


@dataclass
class Machine:
    """One machine on the page. `make()` builds what it loads; the rest
    is what the page and the tests know of it without building."""
    id: str                         # in the page's address: sim/#lisp-v2
    group: str                      # the menu's heading
    variant: str                    # its line in the menu
    summary: str                    # a sentence for the menu and the page
    make: object                    # () -> Build
    about: str = ""                 # HTML: what it is and how to use it
    terminal: dict = None           # how the terminal works (TERMINALS); None: no terminal
    screen: bool = False
    examples: list = field(default_factory=list)   # [(title, text)], typed at the terminal
    links: list = field(default_factory=list)      # [(title, repository path)]
    check: list = field(default_factory=list)
    speed: float = 1                # the clock's multiple it starts at


@dataclass
class Build:
    board: str
    params: dict
    loads: list                     # [(target, address, bytes)]
    symbols: dict = field(default_factory=dict)    # name -> address, for the debugger


# How the terminal treats what's typed. "line": the machine doesn't echo,
# so the page edits a line and sends it at Return, with a history; with a
# prompt of the page's own when the machine has none (`prompt` when it
# answered the last line, `prompt2` when it waits for more of it). "raw":
# every key goes to the machine as it's typed, and the machine echoes.
LINE = {"mode": "line"}
RAW = {"mode": "raw"}


def ram_bytes(mem):
    """A {address: byte} image as bytes from 0 to its last byte."""
    out = bytearray(max(mem) + 1 if mem else 0)
    for a, b in mem.items():
        out[a] = b
    return bytes(out)


def code_symbols(symbols):
    """The symbols a debugger shows: not local labels."""
    return {n: a for n, a in symbols.items() if not n.startswith(".") and "." not in n[1:]}


def read(path):
    with open(os.path.join(ROOT, path)) as f:
        return f.read()


# ---- the Lisp ----------------------------------------------------------------------

# The runtime's top level only evaluates; at the terminal it prints each
# value too, through the hook the compiler uses (%toplevel). The compiled
# machine's hook is the compiler's, which returns the value.
LISP_REPL = {
    False: "(define (%toplevel form) (write (eval form)) (newline))\n",
    True: "(define %repl-run %toplevel)\n"
          "(define (%toplevel form) (write (%repl-run form)) (newline))\n",
}


def lisp(isa, compiled):
    def make():
        from heron.studies.lisp import machine
        img = machine.image((), isa)
        mem = machine.core((), isa).mem if compiled else img.mem
        return Build("plain", {"isa": isa, "clock_hz": CLOCK[isa]},
                     [("ram", 0, ram_bytes(mem)), ("console", 0, LISP_REPL[compiled].encode())],
                     code_symbols(img.symbols))
    return make


LISP_EXAMPLES = [
    ("Factorial", "(define (fact n) (if (= n 0) 1 (* n (fact (- n 1)))))\n(fact 10)\n"),
    ("Lists", "(define xs '(3 1 4 1 5 9 2 6))\n(map (lambda (x) (* x x)) xs)\n(reverse xs)\n"),
    ("A macro", "(defmacro swap! (a b) (list 'let (list (list 'tmp a)) (list 'set! a b) (list 'set! b 'tmp)))\n"
                "(define p 1)\n(define q 2)\n(swap! p q)\n(list p q)\n"),
    ("tak (programs/tak.lisp)", read("studies/lisp/programs/tak.lisp")),
    ("deriv (programs/deriv.lisp)", read("studies/lisp/programs/deriv.lisp")),
    ("nqueens (programs/nqueens.lisp)", read("studies/lisp/programs/nqueens.lisp")),
]

LISP_ABOUT = """<p>The Lisp study's runtime, written in {draft} assembly: a reader, a printer,
an interpreter and a copying collector{compiled}. Type a form and press Return; the value
is printed after it. Errors abandon the form, as at the runtime's top level.</p>
<p>31-bit integers, pairs, symbols, strings, vectors and closures; <code>define</code>,
<code>lambda</code>, <code>let</code>, <code>cond</code>, <code>defmacro</code> and the rest
are in the study's language.md. ^D ends the input, and the runtime halts.</p>"""


def lisp_machine(isa, compiled):
    mode = "compiled" if compiled else "interpreted"
    return Machine(
        id=f"lisp-{isa}" + ("-compiled" if compiled else ""),
        group="Lisp",
        variant=f"{DRAFT[isa]}, {mode}",
        summary=f"The Lisp study's runtime on {DRAFT[isa]}, {mode}.",
        make=lisp(isa, compiled),
        about=LISP_ABOUT.format(
            draft=DRAFT[isa],
            compiled=(", with its compiler, written in the Lisp, compiled by itself and saved in "
                      "the image: every form typed is compiled to machine code, then run" if compiled else "")),
        terminal={**LINE, "prompt": "> ", "prompt2": "  "},
        examples=LISP_EXAMPLES,
        links=[("The Lisp study", "studies/lisp/README.md"), ("The language", "studies/lisp/language.md"),
               ("Report 0018", "reports/0018-report-lisp.md")]
              + ([("Report 0032", "reports/0032-report-lisp-egret-draft-2.md")] if isa == "v2" else []),
        check=[("send", "(+ 1 2)\n"), ("expect", "3\n"), ("send", "(car 5)\n"), ("expect", "error: not a pair: 5"),
               ("send", "(define (sq x) (* x x))\n(sq 12)\n"), ("expect", "144\n")],
    )


# ---- Egret ---------------------------------------------------------------------------

# The VM built with EGRET_INTERACTIVE reads a statement at a time from the
# console (vm/main.c) instead of a whole program.
EGRET_DEFINES = {"EGRET_INTERACTIVE": "1"}


def egret(isa, variant):
    def make():
        from heron.studies.egret import build
        img = build.heron(isa, EGRET_DEFINES, variant)
        return Build("plain", {"isa": isa, "clock_hz": CLOCK[isa]}, [("ram", 0, ram_bytes(img.mem))],
                     code_symbols(img.symbols))
    return make


EGRET_EXAMPLES = [
    ("Arithmetic", "2 ** 100\n(1..10).select { |n| n % 2 == 0 }.map { |n| n * n }\n"),
    ("A class", "class Point\n  def init(x, y)\n    @x = x\n    @y = y\n  end\n  attr x, y\n"
                "  def +(other) = Point(@x + other.x, @y + other.y)\n  def to_s = \"({@x}, {@y})\"\nend\n"
                "print(Point(1, 2) + Point(3, 4))\n"),
    ("Blocks", "def first_negative(xs)\n  xs.each { |x| if x < 0 then return x end }\n  nil\nend\n"
               "first_negative([3, 1, -4, 1, -5])\n"),
    ("queens (programs/queens.eg)", read("studies/egret/programs/queens.eg")),
    ("fib (programs/fib.eg)", read("studies/egret/programs/fib.eg")),
]

EGRET_ABOUT = """<p>Egret, the study's small object language, between Smalltalk, Ruby and
Python: its compiler, its bytecode interpreter{jit} and its library all run on {draft}. At
the prompt, type a statement; it runs when it's complete, and its value is printed after
<code>=&gt;</code>. A class or a method can take several lines (the prompt is
<code>...&gt;</code> until it's closed); an empty line ends one that isn't.</p>
<p>The VM compiles its prelude when it starts, a second or two at the machine's clock.
^D ends the session. Each statement's code stays in the VM's permanent space, so after
about a thousand statements it's full and the machine stops: Reset starts afresh.</p>"""


def egret_machine(isa, variant):
    jit = variant == "jit"
    return Machine(
        id=f"egret-{isa}" + ("-jit" if jit else ""),
        group="Egret",
        variant=DRAFT[isa] + (", with the JIT" if jit else ""),
        summary=f"Egret's VM on {DRAFT[isa]}" + (" with its JIT to machine code." if jit else ", interpreted."),
        make=egret(isa, variant),
        about=EGRET_ABOUT.format(
            draft=DRAFT[isa],
            jit=(", which compiles each method to machine code the first time it's called,"
                 if jit else " (its loop in hand-written assembly)")),
        terminal=dict(LINE),
        examples=EGRET_EXAMPLES,
        links=[("The Egret study", "studies/egret/README.md"), ("The language", "studies/egret/language.md"),
               ("Report 0017", "reports/0017-report-egret.md")]
              + ([("Report 0032", "reports/0032-report-lisp-egret-draft-2.md")] if isa == "v2" else []),
        check=[("expect", "egret> "), ("send", "1 + 2\n"), ("expect", "=> 3\n"),
               ("send", "def sq(n) = n * n\n"), ("expect", "egret> "),
               ("send", "class P\n  def init(a)\n    @a = a\n  end\n  attr a\nend\n"), ("expect", "egret> "),
               ("send", "P(sq(2 ** 20)).a\n"), ("expect", "=> 1099511627776\n")],
    )


# ---- Fen -----------------------------------------------------------------------------

def fen(serial):
    def make():
        from heron.studies.fen import build
        img, kimg = build.boot_image()
        return Build("fen", {"boot_flags": 1 if serial else 0, "epoch": "now"},
                     [("ram", 0, img), ("cf", 0, build.disk())], code_symbols(kimg.symbols))
    return make


FEN_LINKS = [("The Fen study", "studies/fen/README.md"), ("Report 0036", "reports/0036-report-fen.md"),
             ("RFC 0029: draft 2's system half", "reports/0029-rfc-draft-2-system.md")]

FEN_SERIAL_ABOUT = """<p>Fen, the operating system study's, on draft 2 in system mode: a
message-passing kernel, servers for files, the console and windows, and a shell, all on
the study's board. The terminal is the I/O card's UART, at 115,200 baud; the console
server echoes and edits the line (^U kills it, ^C interrupts, ^D ends the input).</p>
<p>Try <code>ls /bin</code>, <code>ps</code>, <code>cat /etc/hello.txt</code> or
<code>help</code>; pipelines, redirections and <code>&amp;</code> work. The files are on
the CompactFlash card, which lasts until the machine is reset. The kernel's log is in the
Log tab.</p>"""

FEN_DESKTOP_ABOUT = """<p>Fen's desktop: the window system drives the video card, the
PS/2 keyboard and the mouse from user space, and starts a terminal running the shell. Click
the screen to give it the keyboard and the mouse; click on the desktop for the menu of
programs. A window moves by its title bar, grows by its bottom right corner and closes by
its box.</p>
<p>The pointer on the screen is the machine's own, drawn by the window system. Keys are a US
layout.</p>"""


def fen_machine(serial):
    return Machine(
        id="fen-serial" if serial else "fen-desktop",
        group="Fen",
        variant="serial console" if serial else "desktop",
        summary="Fen, an operating system for draft 2, " + ("with its shell on the serial console."
                                                             if serial else "with its window system."),
        make=fen(serial),
        about=FEN_SERIAL_ABOUT if serial else FEN_DESKTOP_ABOUT,
        terminal=dict(RAW),
        screen=not serial,
        examples=[("ls /bin", "ls /bin\r"), ("ps", "ps\r"), ("A pipeline", "ls /bin | sort | head -5\r"),
                  ("help", "help\r")] if serial else [],
        links=FEN_LINKS,
        check=[("expect", "% "), ("send", "echo hello | wc -c\r"), ("expect", "6")] if serial
        else [("run", 3000), ("screen",)],
    )


MACHINES = [
    lisp_machine("v2", False),
    lisp_machine("v2", True),
    lisp_machine("v1b", False),
    lisp_machine("v1b", True),
    egret_machine("v2", "asm"),
    egret_machine("v2", "jit"),
    egret_machine("v1b", "asm"),
    egret_machine("v1b", "jit"),
    fen_machine(True),
    fen_machine(False),
]


def get(mid):
    for m in MACHINES:
        if m.id == mid:
            return m
    raise KeyError(f"no machine {mid!r}: there are {', '.join(m.id for m in MACHINES)}")


def params_now(params):
    """The parameters as text for the engine, with "now" as the time."""
    return [(k, str(int(time.time())) if v == "now" else str(v)) for k, v in params.items()]
