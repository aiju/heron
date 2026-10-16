# How Curlew runs

The compiler runs on the host, in Python; what runs on the machine is
the compiled program, the prelude functions it uses and a small runtime in
draft 2 assembly ([RFC 0028](../../reports/0028-rfc-draft-2-isa.md)). The
design follows the STG machine (Peyton Jones, *Implementing lazy
functional languages on stock hardware*, 1992) with pointer tagging
(Marlow, Yakushev and Peyton Jones, *Faster laziness using dynamic
pointer tagging*, 2007), cut down to what a small compiler can do well.

```
program + prelude.cw
  -> parse.py      tokens with layout, a syntax tree
  -> sugar.py      fixity, if/do/ranges/comprehensions/sections removed
  -> typecheck.py  inference; the tree annotated with types and dictionaries
  -> desugar.py    Core: patterns compiled, classes as dictionaries
  -> simplify.py   inlining, specialisation, case of case, ...
  -> lift.py       join points, lambda lifting
  -> stg.py        A-normal form, allocation explicit, strictness used
  -> codegen.py    draft 2 assembly
  -> build.py      assembled with rt/*.s into an image
```

## Values and objects

A value is a 32-bit word whose two low bits are its tag:

| Tag | What |
|---|---|
| `00` | an immediate: an `Int` or `Char` n as 4n, a constructor without fields as 4 × its tag (`[]` and `False` are 0) |
| `10` | a pointer + 2 to an evaluated object: a constructor with fields, a function, a partial application |
| `01` | a pointer + 1 to an object that may not be evaluated: a thunk, an indirection |
| `11` | never a value: an object's header |

So **bit 0 says "not evaluated yet"**. That is the bit draft 2's tagged
operations check: to them, every value a program can use without
evaluating it first is an "integer". An `Int` is 4n so that arithmetic
needs no untagging (`ADD` of two 4n is 4(n + m), and its overflow is a
30-bit overflow), and so that a field of an object at address a + 2 is at
an odd offset from the pointer: `[r + 2]`, `[r + 6]`, ....

Objects are 4-byte aligned, at least 2 words long:

| Object | Layout |
|---|---|
| pair | `[field 0][field 1]`: the only constructor with fields in its type, with 1 or 2 of them (`:`, tuples of 2, `Just`). No header. |
| boxed | `[header][fields...]`: any other constructor with fields |
| thunk | `[header][free variables...]` |
| function | `[header][free variables...]` |
| partial application | `[header][function][4n][n arguments]` |
| indirection | `[header][value]`: a thunk after its update |

A **header** is its code's entry address + 1. The entry is at 4k + 2, so
the header's tag is `11`, and the collector tells a pair (whose first word
is a value) from an object with a header by that. An object's code is
entered with `CALL [r6 - 1]` (a thunk, pointer + 1) or `JMP [r6 - 2]` (a
function, pointer + 2): draft 2's `CALL` and `JMP` clear bit 0 of the
address they load. The **info word** at the entry − 6 (header − 7) holds
the kind (thunk, function, partial application, indirection,
constructor), the arity or the constructor's tag, and the size; the
collector and the general apply read it.

A constructor's header is an address in its type's info block, a word
per constructor, + 3; it is never entered. A constructor without fields that appears as a constant, a
function without free variables and a constant expression are static
objects in the program's data; a top-level thunk (a CAF) is a static
thunk, and a root of the collector.

## Memory

| Address | What |
|---|---|
| `0x0000`–`0x001F` | the vectors |
| `0x0100` | the runtime's variables, where a 16-bit absolute address reaches them |
| `0x0400` | the runtime, the program's code, its static objects and its CAFs |
| `0x30000` | the heap: two halves of 352 KB |
| `0xE0000`–`0x100000` | the stack, 128 KB, growing down |

## The front end

`lexer.py` and `parse.py` read the program with Haskell's layout rule
(the parser makes the virtual semicolons and closing braces as it goes,
so it can close a block where the next token can't continue it).
`sugar.py` resolves operators by their fixities and removes the syntax
that has a translation: `if`, `do`, ranges, list comprehensions (Wadler's
translation, without intermediate lists), sections, tuples and string
patterns. `derive.py` writes the instances `deriving` asks for as source
text, checked like any other. `typecheck.py` infers types binding group by
binding group and records, at every use of an overloaded name, which
dictionaries it takes.

## Core

Core (`core.py`) is a small lambda calculus: variables, literals,
applications, lambdas, `let` (possibly recursive), `case` with
constructor or literal alternatives and a default, saturated constructors
and primitives. `desugar.py` makes it:

- **Patterns** are compiled into nested cases by Wadler's algorithm, with
  guards falling through to the next equation.
- **Classes** become dictionaries: a constructor per class with the
  superclasses' dictionaries and then the methods; an instance is a
  dictionary, or a function from its context's dictionaries to one.
- **Lazy patterns** and pattern bindings bind each variable to a selector.

`reference.py` interprets Core straight from the desugarer, lazily, with
the 30-bit checks; it writes the expected output that the compiled
programs are tested against.

## The optimiser

`simplify.py` runs a simplifier pass a few times, each after an
occurrence analysis. It substitutes atoms and variables used once, drops
dead bindings, inlines small functions applied to all their arguments
(selectors, dictionaries and most instance methods among them, so a
method of a known instance becomes a direct call), and does beta
reduction, let floating, case of a known constructor, case of case (with
join points when the outer alternatives are big) and constant folding.

**Specialisation** gives an overloaded function applied to known
dictionaries, or a recursive function applied to a function it passes on
unchanged (`map f`, `foldr k z`), a copy for those arguments. Without it a
class method called in a loop goes through a dictionary every time:
`wordfreq`, which sorts and compares strings, takes nearly three
times as long (report 0035).

## Strictness

`strictness.py` finds the parameters a function surely evaluates when its
result is evaluated, by abstract interpretation on the two-point domain,
iterated to a fixed point for recursive functions, local ones included.
A strict parameter is passed evaluated: the caller evaluates the argument
(usually it already is) instead of allocating a thunk for it, and the
function needn't check it. A `let` whose body surely evaluates its
variable is evaluated on the spot. `tak` and `nfib` become call-by-value
code; without the analysis they take 4 and 3.5 times as long.

## Local functions

`lift.py` finds **join points**: local functions (and expressions) that
are only called in tail position of the `let`'s body, with all their
arguments, as pattern-match failure, case of case and local loops leave
behind. The code generator makes a join point a label and its calls
jumps with the arguments in registers. Any other local function that
never escapes is **lambda-lifted** to the top level, its free variables
becoming parameters in front of its own; functions that escape stay
closures.

## STG

`stg.py` puts Core into A-normal form with every allocation explicit: a
`let` allocates closures (thunks, functions, constructors, partial
applications), and only `case` evaluates. A call's arguments are atoms; a
strict argument is evaluated first, with a `case`. Every variable is known
to be evaluated or not: case binders, strict parameters, strict fields and
closures that are values are, and their uses need no check.

## Code

`codegen.py` translates each function, thunk and join point into draft 2
code.

- **Registers:** the arguments in `r1`–`r5`, `r0`, `r8`–`r10` (at most
  9), the result in `r1`; `r6` the node, the closure being entered;
  `r7` the return address (the link register); `r12` scratch; `r13` the
  heap's end less 1 KB (`SLACK`); `r14` the heap pointer; `sp`. Every
  register but `r13`–`r15` is caller-saved.
- **Variables** live in one register each while they live. A variable
  live across a call goes into a register near `r7` (`r6`, `r8`, `r5`,
  `r9`, ...), so that the save around a call is one range with the return
  address: `SAVE r6-r7`, `SAVE r5-r8`. The save around a call is a `SAVE`
  of a range or a push per register, whichever costs less; a dead register
  inside a saved range gets its slot cleared with `CLR`, so that the
  collector, which scans the stack, sees no stale pointer.
- **Functions** have two entries. The generic one checks the strict
  parameters, evaluating any that aren't; the fast one, which known calls
  use, trusts them. A function that makes no call keeps its return
  address in `r7` and returns with `RET` (`JMP r7`).
- **Evaluation checks:** before a value is used it is tested,
  `TST r, #1`, and `BNE` goes to an out-of-line slow path. The slow path
  follows an indirection inline; otherwise it saves what's live, enters
  the thunk with `CALL [r6 - 1]` and restores. The common case, an
  evaluated value, costs the test and a branch not taken.
- **Thunks** start with `SAVE r6-r7`, the update frame, and end at `upd`,
  which overwrites the thunk's header with the indirection's and its first
  word with the value. A thunk's tail call goes on with `r7` = `upd`, so
  the callee returns straight to the update.
- **Allocation** is at `r14`, checked against `r13`: one check covers the
  allocations that follow it on a path up to 1 KB, as long as no call or
  evaluation comes between. The stores that fill a new object use mode E,
  `[r14 + 4R]`. The check's slow path saves what's live and calls the
  collector.
- **The stack** is checked against its limit (`CMP sp, [stack_limit]`)
  once on a path, before the first call; what a call saves is popped
  again before the next, and a 1 KB margin covers a frame and the next
  function's first one.
- **case** on a type with immediates and pointers tests the tag; among
  several constructors with fields it compares the header word.
  Comparisons whose result a `case` takes apart branch directly.
- **Unknown calls** go through `ap_N` (N = 1–9, generated by `build.py`):
  a function of arity N is entered at once, and so is the function of a
  partial application that lacks exactly N arguments, with the partial
  application's arguments moved in front. Anything else (too few or too
  many arguments) goes to `ap_slow` in `rt/apply.s`, which builds partial
  applications and applies results to the rest.
- **Arithmetic** on `Int` is on 4n: `ADD`, `SUB`, `NEG` and `BVS` to the
  overflow error, `MULS` of 4n by n (one operand shifted right first),
  `DIVS` of 4n by 4m with the quotient times 4.

## The runtime

- **Start-up** (`rt/start.s`) sets up the heap and the stack and applies
  `main` to the input, a thunk; `put_list` prints the result, evaluating
  it a character at a time.
- **Input** is a thunk that reads a character from the console when it is
  evaluated, and becomes a pair of the character and the next such thunk.
- **Errors** print the output so far, `error:` and the message, and halt.
- **The tag trap** (`rt/apply.s`, with the feature `tagged`): the
  evaluation checks are `TTST r, r`, which traps when bit 0 is set. The
  handler finds the check's address in a hash table that start-up fills
  from the code generator's list of checks, and jumps to that check's own
  slow path, which ends with `RTI` so that the check runs again. An
  address not in the table was a `TADD`, `TSUB` or `TCMP`, and is an
  overflow.

## The collector

`rt/gc.s` is Cheney's copying collector over the two halves. The roots
are the stack (every word that is a pointer into the half being
collected: tag `01` or `10`), the CAFs and the runtime's own. An
indirection is never copied: a pointer to one becomes its value, so a
collection removes every indirection it meets. A copied object's first
word becomes `FWD` (3, a tag no value has) and its second the new value.
