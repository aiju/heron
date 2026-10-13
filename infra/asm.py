"""The assembler: source in, an image or an object file out.

    heron v1_isa asm prog.s -o prog.bin -l prog.lst
    heron v1_isa asm -c prog.s -o prog.o

The core handles everything that doesn't depend on the instruction set:
lexing, expressions, labels (including local `.labels`), directives,
includes, and multi-pass size relaxation. Instructions go to the ISA's
encoder, which returns 16-bit parcels.

Size relaxation: an encoder may choose between a short and a long
encoding. In the first pass unknown symbols evaluate to 0 (optimistic, so
short forms get picked); whenever a statement grows it is marked "sticky
long" and never shrinks again, so passes always converge.

Object files (`relocatable=True`, `asm -c`): each section (`.text`,
`.data`, `.bss`, `.section NAME`) has its own location counter starting at
0, and the linker places it. A section that uses `.org` is absolute
instead. Addresses the linker fills in are relocations. Labels outside
`.org` sections are exported unless the file lists its exports with
`.global` (or hides a label with `.local`).

The assembler and the encoders are Rust (infra/toolchain/src/asm/, and
studies/v1_isa/isa/src/asm/ for drafts 1a and 1b), through
heron.native.toolchain; this module gives them the interface the tools
use. An ISA module names its encoder with NAME.
"""

from contextlib import contextmanager

from heron import native
from . import obj as O


class AsmError(Exception):
    def __init__(self, msg, where=None):
        super().__init__(msg)
        self.msg = msg
        self.where = where

    def __str__(self):
        if self.where:
            return f"{self.where[0]}:{self.where[1]}: {self.msg}"
        return self.msg


@contextmanager
def _errors():
    try:
        yield
    except native.toolchain.AsmFailed as e:
        msg, where = e.args
        raise AsmError(msg, where) from None


class Stmt:
    """A statement: a label (kind "label"), a directive ("dir") or an
    instruction ("insn"), with where it came from: (file, line) and the
    source line."""
    __slots__ = ("kind", "name", "label", "addr", "size", "words", "data", "where", "text")

    def __init__(self, kind, name, label, addr, size, words, data, where, text):
        self.kind, self.name, self.label = kind, name, label
        self.addr, self.size, self.words, self.data = addr, size, words, data
        self.where, self.text = where, text


class Assembler:
    def __init__(self, isa, relocatable=False):
        self.isa = isa
        self.relocatable = relocatable
        try:
            self._a = native.toolchain.Assembler(isa.NAME, relocatable)
        except ValueError as e:
            raise AsmError(str(e)) from None

    @property
    def warnings(self):
        return self._a.warnings

    @property
    def symbols(self):
        return dict(self._a.symbols)

    def load(self, path, text=None):
        """Read a source file, or take its text; `path` names it in messages
        and is where .include looks."""
        with _errors():
            self._a.load(path, text)

    def assemble(self):
        """Assemble into an Image."""
        with _errors():
            out = self._a.assemble()
        mem = {}
        for addr, data in out["mem"]:
            for i, b in enumerate(data):
                mem[addr + i] = b
        img = Image(mem, dict(out["symbols"]), [Stmt(*s) for s in self._a.stmts()],
                    self._a.listing)
        img.warnings = self.warnings
        return img

    def assemble_object(self, name="?"):
        """Assemble into an object file (heron.infra.obj.ObjectFile)."""
        with _errors():
            contents = self._a.assemble_object(name)
        return O.ObjectFile.from_contents(contents, name)


class Image:
    """Result of assembly: sparse byte map plus symbols and a listing."""

    def __init__(self, mem, symbols, stmts, listing=None):
        self.mem = mem
        self.symbols = symbols
        self.stmts = stmts
        self._listing = listing
        self.warnings = []

    def to_bytes(self, size=0x10000):
        buf = bytearray(size)
        for a, b in self.mem.items():
            buf[a] = b
        return bytes(buf)

    def extent(self):
        if not self.mem:
            return 0, 0
        return min(self.mem), max(self.mem) + 1

    def code_bytes(self):
        return sum(st.size for st in self.stmts if st.kind == "insn")

    def listing(self):
        return self._listing()


def assemble_file(isa, path):
    a = Assembler(isa)
    a.load(path)
    return a.assemble()


def assemble_text(isa, text, name="<string>"):
    a = Assembler(isa)
    a.load(name, text=text)
    return a.assemble()
