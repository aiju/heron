# The specification language

A small language for writing down an instruction set: its state, how
each instruction is encoded, and what each does. A specification in it is
meant to be read as documentation and run as a model, so it is plain and
explicit, and has nothing an instruction set doesn't need.
[v1b.isa](v1b.isa) is draft 1b written in it; `spec.py` reads and runs
it.

## Values

Every value is a bit vector with a width. A bare number has no width
until it meets a value that has one, and then takes that value's width:
in `x + 1` with a 32-bit `x`, the `1` is 32 bits. A value made only of
numbers is a number (`31 - 3`), and is 32 bits wide when it must become a
value on its own.

A 1-bit value is a condition: `if`, `and`, `or` and `not` take one, and
comparisons make one.

| Expression | Meaning |
|---|---|
| `x[7:0]`, `x[31]` | a slice and a bit (bit 0 is the least significant) |
| `a ++ b` | `a` above `b`: 8 bits ++ 8 bits is 16 bits |
| `zext(x)`, `sext(x)` | zero- or sign-extend to 32 bits; `zext(x, 64)` to 64 |
| `+ - * / %` | modulo 2^width; `/` and `%` are unsigned |
| `& \| ^ ~` | bitwise |
| `<< >>` | shifts; `>>` is logical, the count may have any width |
| `== != < <= > >=` | comparisons, unsigned |
| `and or not` | on conditions |
| `if c then a else b` | a choice in an expression |
| `(a, b, c)` | a tuple, for a function that returns several values |

Built in: `asr(x, n)` (arithmetic shift right), `ror(x, n)` (rotate
right), `sdiv(a, b)` and `srem(a, b)` (signed division rounded toward
zero, and its remainder, which takes the dividend's sign).

Operators bind as in Python: `or`, `and`, `not`, comparisons, `|`, `^`,
`&`, `++`, shifts, `+ -`, `* / %`, then `~` and unary `-`.

## Declarations

```
register r[16] : 32       # an array of registers, 32 bits each
hardwired r[0] = 0        # an entry that always reads as this; writes do nothing
register pc : 32
flag N Z C V              # 1-bit registers
memory mem : 32 -> 8      # 32-bit addresses, 8-bit contents
const SP = 15             # a name for a value
```

```
fn name(a, b):            # a function; `return` gives its value
    ...
```

```
instruction "ADD rd, ea"  0100 dddd mmmm nnnn:
    ...
```

An instruction is its syntax (a string, for the reader), its encoding
and its body. In the encoding `0` and `1` must match, `-` matches either,
and a run of one letter is a field: `dddd` binds `d` to those four bits
in the body. The spaces are for the eye. `when` adds a condition on the
fields: `0000 aaaa bbbb 0101 when a <= b`.

## Statements

| Statement | Meaning |
|---|---|
| `let x = e` | name a value (`let (a, b) = f()` for a tuple) |
| `x := e` | change a local name, a register, a flag, `r[i]` or `mem[a]` |
| `if c: ... elif c: ... else: ...` | |
| `for i in a .. b:` | `i` from `a` to `b`, both included |
| `case e:` with arms `1, 2: ...` and `else: ...` | the first arm whose value equals `e` |
| `return e` | |
| `fault v` | abandon the instruction: enter vector `v` with the instruction's own address |
| `trap v` | abandon it: enter `v` with the next instruction's address |
| `halt` | the machine stops after this instruction |
| `assume c "why"` | if `c` doesn't hold, what happens is outside the specification |
| `decode e:` | run the first instruction whose encoding matches `e`; the block if none does |
| `pass` | nothing |
| `f(x)` | call a function for what it does |

A block is indented under its `:`, or is one statement on the same line.
`#` starts a comment.

## What a specification must define

- `fn step()`: one instruction. It usually fetches a parcel and `decode`s
  it.
- `fn enter(vector, ret)`: what a fault or trap does. After `fault v` or
  `trap v` anywhere in the instruction, what the instruction did so far
  stays done, and `enter(v, ret)` runs with `ret` the program counter
  (the register `pc`) as it was when `step()` began (`fault`) or as it
  is (`trap`).

## Running it

On known values, a specification is an interpreter: `spec.step(state)`
changes the state as one instruction does, and an `assume` that fails
raises `Unspecified`.

On symbolic values (z3 terms), it runs without forking. A statement whose
condition isn't known runs under a *guard*, so that what it changes
becomes "if guard then new else old"; `fault` turns the guard off for the
rest of the instruction. One pass gives the next state as terms over the
starting state, for every path at once, and the conditions under which
the `assume`s hold, which a proof takes as hypotheses.

A memory, and an array of registers, is an object with `read(address)`
and `write(address, value, guard)`: a dictionary when the values are
known, z3 arrays shaped like the hardware's when they aren't (see
`v1b.py`), so that the specification and the hardware read the same
terms.
