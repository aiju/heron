"""Running Lisp programs on the draft 1b or the draft 2 simulator.

A program is the console input; the runtime reads and evaluates it form
by form (language.md). The image is built once per ISA and set of
features and kept for the process.
"""

from heron.infra import isas
from heron.studies.v1_isa.sim32 import Machine32, SimError as SimError1
from heron.studies.v1_isa.timing32 import REFERENCE
from heron.studies.v2_isa import sim as sim2

import hashlib
import os
import re

from . import build

_IMAGES = {}
COMPILER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compiler.lisp")
COMPILER_V2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compiler_v2.lisp")


# Switching the top level to the compiler; it compiles the prelude again.
ACTIVATE = b"\n(define %toplevel cc:toplevel)\n"
RELOAD = b"\n(%reload-prelude)\n"


def compiler_source(isa=build.ISA):
    """The compiler's source for an ISA: compiler.lisp for 1b; for draft 2,
    compiler.lisp with each top-level definition that compiler_v2.lisp
    also makes replaced by compiler_v2.lisp's, and its new ones after
    them. The compiler compiles itself from this text, so no 1b definition
    may be left in it to be installed over a draft 2 one."""
    with open(COMPILER, "rb") as f:
        src = f.read()
    if isa == build.ISA:
        return src
    with open(COMPILER_V2, "rb") as f:
        over = f.read()
    return merge_definitions(src, over)


def top_forms(text):
    """[(start, end, name)]: the top-level forms of Lisp source (bytes), and
    the name each defines (None if it isn't a define)."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i:i + 1]
        if c == b";":
            while i < n and text[i:i + 1] != b"\n":
                i += 1
        elif c == b"(":
            start, depth = i, 0
            while True:
                c = text[i:i + 1]
                if c == b'"':
                    i += 1
                    while text[i:i + 1] != b'"':
                        i += 2 if text[i:i + 1] == b"\\" else 1
                elif c == b";":
                    while text[i:i + 1] != b"\n":
                        i += 1
                    continue
                elif c == b"(":
                    depth += 1
                elif c == b")":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            i += 1
            form = text[start:i]
            m = re.match(rb"\(define\s+\(?([^\s()]+)", form)
            out.append((start, i, m.group(1) if m else None))
        else:
            i += 1
    return out


def merge_definitions(src, over):
    """src with over's definitions in place of its own of the same names,
    and over's other forms at the end."""
    mine = {name: (a, b) for a, b, name in top_forms(over) if name}
    theirs = {name for _a, _b, name in top_forms(src) if name}
    out, pos = [], 0
    for a, b, name in top_forms(src):
        if name in mine:
            out.append(src[pos:a])
            ma, mb = mine[name]
            out.append(over[ma:mb])
            pos = b
    out.append(src[pos:])
    rest = [over[a:b] for a, b, name in top_forms(over) if name not in theirs]
    return b"".join(out) + b"\n" + b"\n\n".join(rest) + b"\n"


def compiler_text(bootstrap=False, features=(), isa=build.ISA):
    """What a program is preceded by to be compiled: the compiler's options
    (the features), its source, then the switch to it. bootstrap: the
    compiler's source once more after that, so the compiler compiles
    itself before anything else."""
    src = compiler_source(isa)
    options = b"(define cc:*options* '(" + " ".join(sorted(features)).encode() + b"))\n"
    return options + src + ACTIVATE + (src if bootstrap else b"") + RELOAD


# Features that need the extended instruction set on 1b (v1bx, isa.md);
# draft 2 has its tagged operations already
ISA_FEATURES = {"tagged"}
SimErrors = (SimError1, sim2.SimError)


def isa_name(features, isa=build.ISA):
    if isa == "v2":
        return "v2"
    return "v1bx" if ISA_FEATURES & set(features) else isa


def new_machine(isa, features, boot, inp, reference=REFERENCE):
    """A machine for the ISA (v1b or v2), booted from an image or a Core."""
    if isa == "v2":
        return sim2.Machine(boot, inp=inp, reference=reference)
    return Machine32(isas.get(isa_name(features, isa)), boot, inp=inp, reference=reference)


def image(features=(), isa=build.ISA):
    key = (isa,) + tuple(sorted(features))
    if key not in _IMAGES:
        _IMAGES[key] = build.build(tuple(sorted(features)), isa)
    return _IMAGES[key]


class Run:
    """A finished run: the machine, its output and how it ended."""

    def __init__(self, img, m, error):
        self.image = img
        self.machine = m
        self.output = bytes(m.dev.out)
        self.error = error

    def word(self, name):
        """The 32-bit variable at a runtime symbol."""
        a = self.image.symbols[name]
        return int.from_bytes(self.machine.mem[a:a + 4], "little")

    def stats(self):
        """The runtime's own counters: collections, bytes allocated and copied."""
        hp = self.machine.r[14]
        cur = self.word("cur_start")
        return {
            "gc_count": self.word("gc_count"),
            "allocated": (self.word("gc_alloc") + hp - cur) & 0xFFFFFFFF,
            "copied": self.word("gc_copied"),
            "symbols": (self.word("sym_free") - self.image.symbols["sym_static"]) // 32,
        }


class Core:
    """A saved image: all of memory, as the machine left it at (%save-image).
    Booting from it skips start-up; the runtime goes on where it was."""

    def __init__(self, data):
        self.mem = {a: b for a, b in enumerate(data) if b}


_CORES = {}


def core(features=(), isa=build.ISA):
    """The saved image with the compiler compiled by itself and the prelude
    compiled: a machine booted from it compiles a program straight away.
    Made once per ISA and set of features and kept in build/lisp/ (it
    takes 20 seconds to make), named by a hash of what it was made from."""
    key = (isa,) + tuple(sorted(features))
    if key in _CORES:
        return _CORES[key]
    img = image(features, isa)
    h = hashlib.sha256(repr(sorted(img.mem.items())).encode()
                       + compiler_text(True, features, isa)).hexdigest()[:16]
    tag = "-".join(sorted(features)) or "base"
    if isa != build.ISA:
        tag = f"{isa}-{tag}"
    path = os.path.join(build.BUILD, f"core-{tag}-{h}.bin")
    if os.path.exists(path):
        with open(path, "rb") as f:
            data = f.read()
    else:
        m = new_machine(isa, features, img,
                        compiler_text(True, features, isa) + b"\n(gc)\n(%save-image)\n")
        m.run(max_cycles=20_000_000_000)
        if m.traps or b"error" in bytes(m.dev.out):
            raise RuntimeError("making the image failed: " + bytes(m.dev.out).decode(errors="replace"))
        data = bytes(m.mem)
        os.makedirs(build.BUILD, exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    _CORES[key] = Core(data)
    return _CORES[key]


def start(text, features=(), compiled=False, reference=REFERENCE, isa=build.ISA):
    """A machine about to run a program (bytes): the image's symbols, and the
    machine. compiled: compile the program, starting from the saved image
    with the compiler (core). reference: the configuration whose cycles the
    machine's cycle counter counts."""
    img = image(features, isa)
    boot = core(features, isa) if compiled else img
    return img, new_machine(isa, features, boot, text, reference)


def run(text, features=(), max_cycles=4_000_000_000, trace=None, compiled=False,
        reference=REFERENCE, isa=build.ISA):
    """Run a program (bytes) to the end: a Run."""
    img, m = start(text, features, compiled, reference, isa)
    if trace is not None:
        m.trace = trace
    err = None
    try:
        m.run(max_cycles=max_cycles)
    except SimErrors as e:
        err = str(e)
    if err is None and m.traps:
        # Address errors and tag traps are the runtime's type checks;
        # anything else is a bug.
        for pc, what in m.traps:
            if not ("misaligned" in what or what in ("tag check", "tagged overflow")):
                err = f"trap at {pc:X}: {what}"
                break
    return Run(img, m, err)
