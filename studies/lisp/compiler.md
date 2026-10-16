# The compiler

`compiler.lisp` compiles the language to draft 1b machine code, and with
`compiler_v2.lisp` to draft 2's ([below](#on-draft-2)). It is
written in the language and runs on the machine: loading it replaces the
top level, so every later form is compiled, installed in code space and
run. Its code follows the conventions of
[implementation.md](implementation.md), so compiled code, the interpreter
and the primitives call each other freely.

It is a simple compiler in the style of the early Lisp compilers: one pass
from an AST to instructions, values in a fixed register, everything else
on the stack. It doesn't allocate registers or infer types.

## Using it

```sh
heron lisp run -c studies/lisp/programs/tak.lisp --stats    # compile, then run
heron lisp test -c                                          # every program and test, compiled
```

With `-c`, the machine starts from a *saved image* in which the compiler
has compiled itself and the prelude (below); the program is then the
console input, and every form is compiled as it's read. Without the saved
image, a program can load the compiler itself, as
`machine.compiler_text` writes it:

```lisp
(define cc:*options* '())               ; the features, e.g. (tagged)
;; ... compiler.lisp ...
(define %toplevel cc:toplevel)          ; from here on, forms are compiled
```

`(cc:show 'form)` prints the instructions for a form without installing
them.

## Passes

For each top-level form:

1. **`cc:x`**: the form becomes an AST. Macros are expanded (the same
   expanders as the interpreter's), special forms are checked exactly as
   the interpreter checks them, and variables are resolved to their
   binding.
2. **`cc:free`**: which variables each `lambda` captures. A variable that
   is both captured and assigned gets a *box*, a pair whose car holds its
   value.
3. **`cc:knowns`**: a `letrec`-bound (or named-`let`) variable bound to a
   `lambda` and never assigned is a *known function*. A call to it jumps
   straight to its body, past the argument-count check, and a tail call
   to itself is a jump.
4. **`cc:gen`**: the AST becomes symbolic 1b instructions, each with a
   category (below).
5. **`cc:asm`**: the instructions become parcels; branches that don't
   reach become 2-parcel `Jcc`s.
6. **`cc:install`**: the parcels go into code space, and the static
   closures get their code addresses.

A form becomes a function of no arguments, which the top level calls
between `(%run-begin)` and `(%run-end)` (the measurement marks). A form it
can't compile (a lambda with more than 6 parameters, a quoted constant it
can't copy out of the heap, a global named by a symbol outside symbol
space) goes to the interpreter instead.
Code space is never collected: redefining a function leaves the old code
where it was.

## Code

- **Registers.** An expression's value goes to `r1`. Arguments are
  evaluated left to right into `r3`–`r8` (complex ones onto the stack
  first, then popped into place), `r2` holds the count at a call. `r9` is
  raw scratch.
- **Frames.** A function saves its arguments with `SAVE r3-rN`, then its
  closure if it has free variables; `let` variables and temporaries are
  pushed as they come. Variables are addressed from `sp`, mostly with the
  one-parcel `[sp + 4R]` mode.
- **Closures** are flat: a closure holds the values of its free variables
  (or their boxes). A `lambda` without free variables is a *static
  closure*, made once in constant space at compile time, so making it at
  run time is a constant.
- **Globals** are read and written through the symbol's value cell, at an
  absolute 16-bit address (symbol space is the first 32 KB). A read checks
  for the unbound marker.
- **Calls** go through the call slot, `CALL [r1 + 1]` or `JMP [r1 + 1]` for
  a tail call, so any procedure can be called, and a non-procedure traps.
  Each function checks its argument count and the stack limit on entry.
- **Inline primitives:** `car`, `cdr`, the `c..r` combinations, `cons`,
  `set-car!`, `set-cdr!`, `eq?`, `not`, `null?`, the type predicates,
  `+ - * = < > <= >= zero?`, `vector-ref`, `vector-set!` and
  `vector-length`. They're inlined only while the global still holds the
  primitive it held when the compiler was loaded. `car` and `cdr` are one
  instruction each, checked by the alignment trap; arithmetic checks both
  operands' tags in software (or with `tagged`, in one instruction,
  [report 0018's appendix](../../reports/0018-report-lisp.md#appendix-v1bx-draft-1b-with-a-tagged-register-mode)) and the V flag for overflow.
- **Tests.** An `if` whose test is a comparison or a predicate compiles to
  a compare and a branch, without making `t` or `nil`.
- **Errors** branch to a shared stub at the end of the function, which
  jumps to the runtime's error routine; the errors are the interpreter's,
  with the same messages and irritants.

## Categories

Every instruction the compiler writes carries a category, saying what
it's for. `cc:install` writes one byte per parcel into the category map
(`CATMAP`, beside code space), and the profiles (`heron lisp run -c
--profile`, report.py) break compiled code's cycles down by it:

| Category | What |
|---|---|
| `var` | reading and writing local variables, boxes and closure slots |
| `const` | loading constants (and static closures) |
| `temp` | pushing and popping temporaries; popping a frame |
| `global` | reading and writing global variables |
| `unbound` | the check that a global is bound |
| `call` | setting up a call and making it |
| `entry` | a function's entry: the argument-count and stack checks, saving the arguments |
| `return` | `RET`, popping the frame before it |
| `type` | the integer checks of arithmetic and comparisons |
| `pred` | type predicates (`pair?`, `symbol?`, ...) |
| `arith` | the arithmetic itself |
| `overflow` | the overflow checks |
| `test` | comparisons and branches of `if`, `and`, `or`, `cond` |
| `alloc` | making pairs, closures and boxes |
| `access` | `car`, `cdr`, vector elements and their stores |
| `bounds` | vector type and index checks |
| `stub` | the shared error exits |
| `other` | anything else |

## The saved image

`machine.core()` makes the image once per set of features and keeps it in
`build/lisp/`:

1. the runtime boots and reads the prelude (interpreted);
2. it reads `compiler.lisp`, interpreted, and switches the top level to
   it;
3. it reads `compiler.lisp` again, which is now compiled by the
   interpreted compiler: the compiler compiles itself, form by form,
   replacing the interpreted definitions as it goes;
4. `(%reload-prelude)` reads the prelude again, compiled;
5. `(gc)`, then `(%save-image)` stops the machine, and the tools keep a
   copy of memory. A machine booted from it goes on reading the console.

That takes 1.7 billion cycles (about 20 seconds in the simulator), 1.2
billion of them step 3.

## On draft 2

`compiler_v2.lisp` holds what draft 2 changes. `machine.compiler_source`
puts the draft 2 compiler together: compiler.lisp with each top-level
definition that compiler_v2.lisp also makes replaced by
compiler_v2.lisp's, and its new ones after them. The compiler compiles
itself from that text, so no 1b definition is left in it to be installed
over a draft 2 one; and draft 2 leaves compiler.lisp, the 1b compiler,
as it is (and report 0018's numbers with it).

- **The assembler** writes draft 2's parcels (an opcode byte and a
  register byte, [RFC 0028](../../reports/0028-rfc-draft-2-isa.md)): the
  7-bit constants of `MOV` and `CMP`, `TST` with a constant (the integer
  checks are `TST r, #1`), `[r14 + 4R]`, and with `tagged` the tagged
  operations (`TADD`, `TSUB`, `TCMP`; `TTST r, r` checks one operand and
  is `zero?`). An encoder test checks every form against the assembler
  (tests/test_compiler.py).
- **Registers:** arguments in `r3`, `r4`, `r5`, `r6`, `r8`, `r0`, as the
  runtime's convention has them ([implementation.md](implementation.md#on-draft-2)).
- **The link register.** A function's entry, returns and tail calls are
  placeholders until its code is done (`cc:link`). A function that calls
  anything (a `CALL`, a `BSR` to a known function, a call into the
  runtime) pushes `r7` on entry, below its frame, returns with
  `JMP [sp]+` and restores `r7` before a tail call; a leaf leaves `r7`
  alone and returns with `RET`. An inline `cons` that finds the heap
  full calls the runtime's `cons` (which collects, checks again and makes
  the pair) from a stub that keeps `r7` on the stack itself, so consing
  doesn't make a function a caller. A tail call
  to itself jumps past the push, so a loop doesn't push.
- **`no-leaf`** (a feature, for the measurements) makes every function
  keep its return address on the stack.
