"""A C compiler, compiling a program to draft 2 assembly: the stand-in for
a toolchain running on Heron itself (RFC 0005 and RFC 0015 foresee a C
toolchain on the machine).

The compiler is a one-pass compiler of a subset of C, in the manner of
lcc or the early Unix compilers (cc.h has the outline): a lexer that
interns identifiers in a hash table; a symbol table of hash chains with
scopes; a recursive-descent parser that type-checks as it goes, folds
constants and builds each function's tree in an arena; a code generator
with register variables chosen by weighted use counts, temporaries in
Sethi-Ullman order with spills, and operands folded into draft 2's
addressing modes; and a peephole optimiser over each function's assembly
text, as Unix's c2 was. Its output is assembly in the Heron C compiler's
style, which the repository's assembler takes, and which runs: while it
was written, whole programs from source.py, with a main added, were
compiled, assembled, linked and run on the instruction-level simulator,
and gave what gcc's builds of them give.

The input is C made by source.py, the same every time: the header of a
real program's structs and globals, then modules of string functions,
arithmetic, a binary tree, an output buffer, a tokenizer, a hash table,
sorting, rectangles and bit twiddling, each with its own names,
constants and choices among ways of writing them. LINES is how much of
it is compiled, in whole functions: the instruction budget of a size
makes that 20 lines at `test`, some 250 at `small` and 2,000 at `ref`,
since compiling costs about 5,000 instructions a line. The assembly is
written out a buffer at a time, into the results' checksum. The results are a checksum of the
assembly and counts of tokens, nodes, symbols and lines.

Where the time goes, at `small`: the peephole optimiser takes a quarter
(taking lines apart, matching mnemonics, following labels through a
hash table), formatting and writing out the assembly a fifth, the lexer
a sixth (scanning, skipping blanks, interning), the parser a tenth, the
code generator proper a twentieth, and the C library much of the rest
(memcpy, memset, strlen and strcmp under the others). The checksum of
the output is a tenth: the harness's part, in place of writing a file.
"""

from . import source

TITLE = "a C compiler, compiling C to draft 2 assembly"
PART = "c"
CATEGORY = "tools"
SOURCES = ["main.c", "lex.c", "sym.c", "parse.c", "gen.c", "peep.c"]
SIZES = {"test": {"LINES": 21}, "small": {"LINES": 245}, "ref": {"LINES": 2000}}


def data(p):
    return {"source": source.generate(p["LINES"])}
