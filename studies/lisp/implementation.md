# The implementation on draft 1b

How the Lisp of [language.md](language.md) runs on the draft 1b machine
([isa-v1b.md](../v1_isa/isa-v1b.md)). Everything here is 1b assembly in
`rt/`, plus the prelude in Lisp. It runs on the instruction-level
simulator, with the timing model costing it for the hardware
configurations ([timing-model-v1.md](../v1_isa/timing-model-v1.md)); the
numbers this study quotes are for D32-separate, the configuration the
213-chip 1b hardware has ([report 0012](../../reports/0012-report-draft-1b-hardware.md)).

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
| `0x00000` | vectors |
| `0x00100` | the runtime's variables, then jump tables (16-bit addresses reach them) |
| `0x00400` | `nil` and the end-of-file object, then **symbol space**: the static symbols the build generates, then the ones the reader interns. Symbols never move, and 16-bit addresses reach them. |
| `0x08000` | the runtime's code, the static data, the prelude's text |
| `0x18000` | **constant space**: names of interned symbols (never moves) |
| `0x20000` | compiled code |
| `0x38000`, `0x94000` | the two halves of the heap, 368 KB each |
| `0xF0000`–`0xFFFFF` | the stack (64 KB) |

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
