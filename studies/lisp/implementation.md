# The implementation on draft 1b

How the Lisp of [language.md](language.md) runs on the draft 1b machine
([RFC 0004, Part II](../../reports/0004-rfc-draft-1-isa.md#part-ii-draft-1b)). The runtime is 1b assembly in
`rt/`, plus the prelude in Lisp; the compiler, in Lisp, has its own
document ([compiler.md](compiler.md)). It runs on the instruction-level
simulator, with the timing model costing it for the hardware
configurations ([timing-model-v1.md](../v1_isa/timing-model-v1.md)); the
numbers this study quotes are for D32-separate, the configuration the
213-chip 1b hardware has ([report 0012](../../reports/0012-report-draft-1b-hardware.md)).
The runtime also runs on draft 2; [the last section](#on-draft-2) says
what's different there.

## Values

A value is a 32-bit word whose low bits are its tag:

| Low bits | What | Notes |
|---|---|---|
| `...0` | integer (fixnum) | The value shifted left one place: 31 bits, −2³⁰ to 2³⁰ − 1. Adding and subtracting work on the tagged words directly, and the V flag is the overflow check. |
| `..001` | pair | The cell is at p − 1: the car at `[p - 1]`, the cdr at `[p + 3]`. |
| `..011` | other object | At p − 3: a header word, the *call slot* (a code address), then the fields. |
| `..101` | header | Only ever an object's first word: `size << 8 \| type << 3 \| 5`, where size is the number of words after the header (for a string, its bytes). |
| `..111` | forwarding pointer | Only in the old half of the heap, while the collector runs. |

Objects are 8-byte aligned. `nil` is a static object (in `r13` at all
times), `t` is a symbol, and an unbound global holds the word `1`, which
is no Lisp value.

**Free type checks.** The machine traps a misaligned word access, so:

- `car` is `MOV r, [p - 1]`, and that address is a multiple of 4 only if
  `p` is a pair; `cdr` is `[p + 3]`, likewise.
- Calling a procedure jumps through `[p + 1]`, the call slot, which is
  aligned only for an other object. Every other object has a call slot
  too, pointing to an error routine (`not_proc`), so a call checks its
  operand completely for free.

The address-error handler (`trap_addr` in `start.s`) decodes the faulting
instruction: a displacement of −1 or 3 is `not a pair`, 1 is `not a
procedure`, and the base register holds the irritant.

Object types:

| Type | Layout (words) |
|---|---|
| symbol | header, call slot, global value, name (a string), special form index, macro, next in its hash chain, property list |
| string | header (size = bytes), call slot, the bytes |
| vector | header, call slot, the elements |
| primitive | header, code, name |
| compiled closure | header, code, the free variables' values |
| interpreted closure | header, `interp_entry`, parameters, body, environment, shape |
| frame | header, parent, then (name, value) pairs |
| nil, the end-of-file object | header, call slot |

## Memory

| Address | What |
|---|---|
| `0x00000` | vectors, and the words they jump through |
| `0x00100` | the runtime's variables, then jump tables (16-bit addresses reach them) |
| `0x00400` | `nil` and the end-of-file object, then **symbol space**: the static symbols the build generates, then the ones the reader interns. Symbols never move, and 16-bit addresses reach them. |
| `0x08000` | **constant space**: names of interned symbols, and what the compiler needs to stay put: static closures and copies of quoted constants. Never moves, and the collector doesn't scan it. |
| `0x10000` | the runtime's code, its static data and the prelude's text, then **code space**: compiled code, up to `0x2A000` |
| `0x2A000` | the category map: a byte per parcel of code space, saying what it's for ([compiler.md](compiler.md#categories)) |
| `0x35000`, `0x92800` | the two halves of the heap, 374 KB each |
| `0xF0000`–`0xFFFFF` | the stack (64 KB); the stack limit is at `0xF0800` |

## The garbage collector

A Cheney copying collector (`gc.s`). Allocation bumps `r14` and compares
it with a limit in memory; a pair is `ST car, [r14]+`, `ST cdr, [r14]+`,
`LEA p, [r14 - 7]`.

Its roots are found without any maps of the stack:

- **the whole stack**, from `sp` up, word by word;
- **r1–r8** as they were when it was called;
- **symbol space** (the symbols' values, macros and property lists) and a
  small root block.

A root word is updated if it looks like a pointer into the half being
collected, and left alone otherwise. This works because:

- return addresses are even, so they look like integers;
- the runtime's own rule: at any point that can allocate, `r1`–`r8` and
  the stack hold only Lisp values, or raw values that are even or don't
  point into the heap. Byte pointers into strings (which can be odd) live
  in `r9`–`r12`, which the collector doesn't touch, and no raw pointer into
  the heap is kept across an allocation.

## The interpreter

`eval.s` evaluates S-expressions directly, as period Lisps did.

- **Environments** are frames of (name, value) pairs with a parent
  pointer. A symbol that has never been a local variable's name anywhere
  (a bit in its special field, set when a `lambda` or `let` binding it is
  seen) is looked up in its global value cell straight away; this covers
  nearly every reference to a procedure.
- **Special forms** are found by the symbol's special field, an index into
  a jump table. Each checks its whole shape before evaluating anything.
- **Macros** are expanded once: the expansion replaces the call in place.
  Named `let` is rewritten the same way, by a function in the prelude.
- **Calls** evaluate the operator, then the arguments into stack slots,
  and apply: an interpreted closure gets a new frame and its body is
  evaluated as a tail call; anything else gets the calling convention
  below. Tail calls never grow the stack.

## The calling convention

Primitives, compiled code and the interpreter's `interp_entry` all use
one convention:

- `r1` = the procedure, `r2` = the number of arguments;
- arguments 1–6 in `r3`–`r8`; with more than 6, `r3`–`r7` hold 1–5 and `r8`
  a list of the rest;
- the call is `CALL [r1 + 1]` (or `JMP` for a tail call): the call slot;
- the result comes back in `r1`; `r1`–`r12` are not preserved; `r13`
  (nil), `r14` (the heap pointer) and `sp` are.

A procedure checks its own number of arguments.

## The top level and errors

The top level reads a form, evaluates it and reads the next, without
printing the value (programs print what they want to). If the symbol
`%toplevel` is bound to a procedure, the top level calls it on each form
instead of evaluating it; that's how the compiler takes over.

An error prints `error: message: irritants` ([language.md](language.md))
and returns to the top level, which drops the stack and goes on with the
next form. The traps are errors too: an address error from `car`, `cdr` or
a call, and (in v1bx, [report 0018's appendix](../../reports/0018-report-lisp.md#appendix-v1bx-draft-1b-with-a-tagged-register-mode)) a tag check.

The prelude is text in the image, read at start-up as if it came before
the console input. `(%reload-prelude)` reads it again, so that once the
compiler is loaded the prelude is compiled.

## Measuring

The runtime keeps counters for the tools (collections, bytes allocated and
copied), and `(%run-begin)` and `(%run-end)` log the simulator's cycle
counter, so the tools can tell compiled code's running from the compiling
around it (measure.py). `(%save-image)` stops the machine for the tools to
copy memory: the saved image the compiled runs start from
([compiler.md](compiler.md#the-saved-image)).

## On draft 2

`rt_v2/` is the same runtime in draft 2 assembly
([RFC 0028](../../reports/0028-rfc-draft-2-isa.md)): the same values,
memory map, collector and interpreter, ported from `rt/`
([report 0032](../../reports/0032-report-lisp-egret-draft-2.md)). What's
different:

- **The link register.** A call leaves the return address in `r7`. A
  routine that calls nothing returns with `RET` (`JMP r7`); one that calls
  pushes `r7` on entry and returns with `JMP [sp]+`, so its stack is as
  1b's call left it. Inside the interpreter the return address stays on
  the stack, as on 1b: `eval` pushes `r7` when it evaluates a pair, the
  special forms are jumped to with it there, and `apply_stack` pops it
  into `r7` as it jumps to a procedure. An atom is a leaf: `eval` returns
  a constant or a variable's value without touching the stack, or
  checking the stack limit, which only a pair can need.
- **The calling convention.** With `r7` the link, arguments 1–6 are in
  `r6`, `r5`, `r4`, `r3`, `r8` and `r0`: the first four just below `r7`,
  so that `SAVE r(7−n)-r7` keeps n of them and the return address
  together ([report 0033](../../reports/0033-report-lisp-arguments-draft-2.md)).
  With more than 6, `r6`–`r3` and `r8` hold 1–5 and `r0` a list of the
  rest. The rest is as on 1b: `r1` the procedure, `r2` the count,
  `CALL [r1 + 1]`, the result in `r1`; `r0`–`r12` are not preserved.
  The runtime's own registers are 1b's with `r3` and `r6`, `r4` and `r5`
  swapped throughout, so its routines' conventions follow (`cons` takes
  the car in `r6` and the cdr in `r5`); compiled code's inline `cons`
  keeps `r3` and `r4`, and calls `cons_c` when the heap is full.
- **A call's arguments in the interpreter** are on the stack with the
  first highest, just below the procedure (on 1b the first is at `[sp]`),
  so that `RESTORE r(7−n)-r6` loads n of them into their registers and
  `SAVE r(7−n)-r6` stores them.
- **The collector's roots** are `r0`–`r8`, so `r0` keeps the same rule as
  `r1`–`r8`; `r7` holds a return address, which is even and stays as it
  is.
- **Flags.** `MOV` and `POP` don't set the flags on draft 2. The ten
  `MOV`s whose N and Z a branch read became `MOVS`.
- **`r0` is a general register,** so a zero store is `CLR`.
- **The traps** decode draft 2's instructions. An address error's check
  is a word at `[R + d16]`: column 3 of a row that takes a mode, or a
  `JMP`'s or `CALL`'s register byte with mode 3.
- **The tagged feature** uses draft 2's tagged operations (`TADD`,
  `TSUB`, `TCMP`, `TTST`) in the arithmetic primitives as well as in
  compiled code. Their trap reports the error the software checks do: the
  first operand that isn't an integer, or an overflow. Without the
  feature, a check of one operand is `TST r, #1`.
