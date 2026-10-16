---
number: 38
type: rfc
title: Formal verification of the hardware
status: draft
date: 2026-10-16
context:
  studies: [formal, v1b_hw, v1_isa]
  commit: ce6d92f
---

# RFC 0038: Formal verification of the hardware

A flow for proving that the hardware implements the instruction set,
rather than only testing that it does. The instruction set is written in
a small language made for it, as a specification that runs. The
chip-level netlist runs with symbolic values in its registers, the
specification runs on the same values, and an SMT solver proves the two
agree, one instruction at a time. The study
[studies/formal](../studies/formal/README.md) did this for the draft 1b
hardware ([report 0012](0012-report-draft-1b-hardware.md)), whose netlist
is on `main`.

- [Part I](#part-i-the-flow) is the flow, as rules numbered so that a
  design, a review or an RFC can cite them, like
  [RFC 0026](0026-rfc-pcb-design-rules.md)'s.
- [Part II](#part-ii-the-specification-language) is the specification
  language, written to move to `docs/` unchanged.
- [Part III](#part-iii-results-and-discussion) is what the 1b study did and
  found, and so why the rules are what they are.

What isn't decided is marked **open**. The specification of draft 1b
itself isn't here: it is the study's
([v1b.isa](../studies/formal/v1b.isa)), and where an instruction set's
specification belongs is one of the open questions
([1.5](#15-where-things-live)).

## Summary

SUMMARY

## Contents

- [Part I: The flow](#part-i-the-flow)
  - [1. The rules](#1-the-rules)
- [Part II: The specification language](#part-ii-the-specification-language)
  - [2. The language](#2-the-language)
- [Part III: Results and discussion](#part-iii-results-and-discussion)
  - [3. What was proved, and how](#3-what-was-proved-and-how)
  - [4. Results](#4-results)
  - [5. What the microcode relies on](#5-what-the-microcode-relies-on)
  - [6. What it costs](#6-what-it-costs)
  - [7. Breaking the hardware on purpose](#7-breaking-the-hardware-on-purpose)
  - [8. Draft 2](#8-draft-2)
  - [9. What next](#9-what-next)

## Part I: The flow

### 1. The rules

Terms:

- the **specification** is an instruction set written in the language of
  [Part II](#part-ii-the-specification-language);
- an **instruction boundary** is the clock edge after which the hardware
  starts the next instruction;
- the **abstraction** says which hardware states sit at an instruction
  boundary, and which specification state each stands for;
- a **decode case** is a routine of the decode table with the first
  parcels that select it;
- a **path** is one way through a decode case's microcode, as the
  splits of P4 choose it.

#### 1.1 The specification

- **S1 One for every instruction set.** Every instruction set, a draft or
  the current one, has a specification. It defines every instruction,
  every fault, and the state they act on.
- **S2 Checked against the simulator.** The specification and the
  instruction-level simulator agree on one step from a given state.
  Compare everything: registers, flags, PC, every byte of memory, and
  faults with their stack frames. The cases are of two kinds:
  - **chosen by the specification:** each instruction runs once on
    symbolic inputs, and every outcome of every decision it meets is a
    goal: each arm of an `if` or `match`, each flag set to `true` and to
    `false`, each fault. The solver finds inputs that reach each goal, a few times
    over, with the inputs the goal doesn't decide random (`heron formal
    isagen`, [3.3](#33-the-specification-side));
  - **random:** random states and instructions (`heron formal isacheck`).

  Count coverage on the cases' concrete runs: every outcome the solver
  can reach must be reached. An outcome it proves unreachable is dead
  text, to remove or explain. Run a few cases in the unit tests, and all
  the goals and 100,000 random cases when either side changes. A
  disagreement is a bug in one of the two.
- **S3 What it leaves out, it says.** Behaviour outside the specification
  is an `assume` with its reason: memory that isn't there, the I/O page,
  a fault while entering a fault. A proof holds only where the
  assumptions do.
- **S4 Questions go to the RFC.** Writing a specification finds what an
  RFC's prose doesn't say (1b: which value of `rd` an auto-incrementing
  operand sees, [3.3](#33-the-specification-side)). Each becomes an open
  item in the instruction set's RFC, for Emily. Until she decides, the
  specification follows the simulator.

#### 1.2 The proof

- **P1 The netlist is what is proved.** The same netlist that the
  chip-level simulator and static timing analysis use, not a model of
  it. It runs a clock cycle at a time; that signals settle within the
  cycle is static timing analysis's job.
- **P2 The abstraction is written down** with the hardware: a table of
  what each register holds at an instruction boundary, what may be
  anything, and every invariant the microcode relies on
  ([table 1](#31-what-is-proved) is 1b's).
- **P3 One proof per decode case.** Parcel bits that don't choose the
  routine stay symbolic, so one case covers every register number and
  constant. A routine that serves parcels of many opcodes (illegal
  instructions) is split by opcode.
- **P4 Split only at the control store.** A path splits only where a
  symbolic value reaches the control store's address; everything else
  stays symbolic. The solver decides each split: if only one side is
  possible on the path, there is no split.
- **P5 The goals.** At the end of every path:
  - the architectural state is the specification's: registers, flags,
    memory, PC;
  - the abstraction holds again, its invariants included (both copies of
    anything duplicated);
  - there was no bus contention, and no access the specification leaves
    out;
  - the hardware halts exactly when the specification does.
- **P6 Reset is proved** to reach the first instruction boundary with the
  abstraction's invariants.
- **P7 Make the terms meet.** Give the specification's state the
  hardware's shape (the register file's lanes and addresses, the RAM
  chips), and cut memory addresses where they are loaded (MAR). Both are
  what make the proofs fast enough ([6](#6-what-it-costs)).
- **P8 Budgets.** Every decode case has a time budget (30 minutes on 1b).
  A case that runs out is listed with the results, not dropped, and is
  left to the tests (W4).

#### 1.3 Design for proof

Rules for the hardware, so that the proof stays cheap.

- **D1 Control from the sequencer only.** The control store's address
  depends on data only through the sequencer's condition inputs, its
  dispatch, and the fault and interrupt inputs. Then a decode case has a
  few paths, not thousands. 1b follows this.
- **D2 A defined state after reset.** Everything the abstraction gives a
  value holds it after reset. In particular, the copies of a duplicated
  register file agree (1b's don't: [5](#5-what-the-microcode-relies-on)).
- **D3 The microcode's constants are written down** with their exact
  contents as stored (1b's loop counts are sign-extended:
  [5](#5-what-the-microcode-relies-on)).
- **D4 Data-dependent loops are short.** A microcode loop whose count is
  data splits once per count. Keep such counts to a few dozen (1b's
  shifts by a register and CLZ: 32 and 33 paths).
- **D5 Multiply and divide in one place.** They are out of reach of the
  plain flow ([6](#6-what-it-costs)). Keep each one's step in a single
  microinstruction, so that a proof by loop invariant can be added later
  ([9](#9-what-next)).

#### 1.4 When it runs

- **W1 On a microcode change:** prove the decode cases whose routines
  reach a changed control word (the study's `mutate.affected` finds them).
  For one routine, that is minutes. **Open:** whether a failure blocks
  merging, or only reports.
- **W2 On a netlist change, and in the slow CI:** every decode case
  (hours: [4](#4-results)).
- **W3 When the flow itself changes:** mutation testing, with mistakes
  made by hand and at random ([7](#7-breaking-the-hardware-on-purpose)).
- **W4 What stays with the tests:**
  - timing (static timing analysis);
  - the decode cases over budget, multiply and divide among them;
  - interrupts and the I/O page;
  - the part models' fidelity to hwsim's.

  The chip-level program suite keeps running: it checks everything the
  proof assumes.

#### 1.5 Where things live

- **The language** ([Part II](#part-ii-the-specification-language))
  moves to `docs/` when this RFC is accepted.
- **The tools that depend on no design** move to `infra/`: the
  specification's interpreter (`spec.py`) to `infra/spec/`, the symbolic
  simulator (`logic.py`, `symsim.py`) to `infra/hw/`. They are Python,
  not Rust as [RFC 0015](0015-rfc-languages.md) has the engines: they
  live on z3's Python bindings, and their speed is the solver's.
- **A CPU's abstraction and proof harness** (1b's: `v1b.py`) stay with the
  CPU: its study, or `hw/` for the current design.
- **Open: an instruction set's specification.** The choices:
  1. **With its simulator while it is a draft, then in `isa/`.** Draft 2's
     would be `studies/v2_isa/v2.isa`, and it would move to `isa/` when
     draft 2 becomes the current design. [RFC 0000](0000-rfc-repository-layout.md)
     says `isa/` holds "the current ISA's definition, shared by the tools,
     the hardware and the tests", and a specification that runs is
     exactly that. *Recommended.*
  2. **In the instruction set's RFC,** as a part or an appendix. An RFC
     can carry a specification. But 1b's is about 770 lines and would
     bury the prose, and it has to change with the simulator while the
     draft is still moving.
  3. **In `docs/`.** It is reference, but it is also code the tools run,
     which `docs/` doesn't hold.
- **Open: which is normative,** the specification or the RFC's prose,
  where they differ. Proposed: the specification for what the machine
  does, the prose for why; a difference is a bug in one of them (S4).

## Part II: The specification language

### 2. The language

A language for writing down an instruction set: its state, how each
instruction is encoded, and what each one does. A specification in it is
meant to be read as documentation and run as a model, so it is plain and
has nothing an instruction set doesn't need. It is also strict: a
specification is checked when it is loaded ([2.6](#26-what-is-checked)),
and most slips that would make it say something other than what was
meant are errors, not behaviour.

```
instruction "ADD rd, ea"  0100 dddd mmmm nnnn {
    let x = source(m: m, n: n)              // the EA's value, read first
    @r[d] := nzcv(add(a: @r[d], b: x, carry: false))
}

// a + b + carry in: the sum, the carry out, and whether it overflowed as a
// signed sum. A subtraction is a + ~b + 1, so its carry means "no borrow".
record Sum { value: u32, carry: bool, overflow: bool }

fn add(a: u32, b: u32, carry: bool) -> Sum {
    let wide = zext(a, 33) + zext(b, 33) + zext(bit(carry), 33)
    let x = wide[31:0]
    return Sum {
        value: x,
        carry: bool(wide[32]),
        overflow: a[31] == b[31] && x[31] != a[31],
    }
}

// All four flags from a sum, giving the result to store.
proc nzcv(s: Sum) -> u32 {
    @C := s.carry
    @V := s.overflow
    @N := bool(s.value[31])
    @Z := s.value == 0
    return s.value
}
```

#### 2.1 Text

- `//` starts a comment, to the end of the line.
- Blocks are in braces. A statement ends at the end of its line, at a
  `;`, at the `}` of its block, or at the `,` after a match arm. A line
  that ends in an operator, `(`, `[`, `{` or `,` goes on to the next.
- Numbers are decimal, `0x` hexadecimal or `0b` binary, and `_` may
  separate digits: `0x0010_0000`. A **sized number** is written as in
  Verilog, its width in bits, `'`, a base (`h`, `d` or `b`) and digits:
  `32'h0010_0000`, `8'd255`, `4'b1010`.
- Names are letters, digits and `_`, not starting with a digit.
  `@name` is the machine's state ([2.4](#24-declarations)); a name
  without `@` never is. Strings are in double quotes, on one line.

#### 2.2 Types

| Type | Values |
|---|---|
| `u1` to `u128` | `uN` is N bits, read as an unsigned number |
| `bool` | `true` and `false` |
| an enum | `enum Size { Byte, Half, Word }` has the values `Size.Byte`, `Size.Half` and `Size.Word` |
| a record | `record Sum { value: u32, carry: bool, overflow: bool }`: a value of each field's type |

- **Nothing converts by itself.** The operands of an operation have the
  same type; a value goes only where its own type is wanted. `bit(b)`
  makes a `bool` a `u1` and `bool(x)` a `u1` a `bool`; `zext` and `sext`
  widen.
- **A bare number has no type** until it meets a value that has one, and
  then takes that type: in `x + 1` with `x` a `u32`, the `1` is a `u32`.
  It must fit: in a `uN`, from −2^(N−1) to 2^N − 1, a negative number
  being its two's complement (`~1` in a `u32` is `0xFFFF_FFFE`).
  Arithmetic on bare numbers alone is exact (`31 - 3` is `28`), but a
  bare number can't stand alone where nothing gives it a type: `for i in
  0 ..= 3` is an error, `for i: u5 in 0 ..= 31` isn't.
- **A sized number has its type,** and its value must fit it unsigned:
  `8'h100` is an error.
- **An enum** has only `==`, `!=` and `match`; a record only its fields.
  A record is built with every field named, `Sum { value: x, carry: c,
  overflow: v }`, and read with `s.carry`.

#### 2.3 Expressions

| Expression | Meaning |
|---|---|
| `x[7:0]`, `x[31]` | a slice, and a bit (a `u1`). Bit 0 is the least significant. Slice bounds are numbers; a bit's index may be a value |
| `a ++ b` | `a` above `b`: a `uN` as wide as both. Neither may be a bare number |
| `zext(x, 64)`, `sext(x, 64)` | zero- or sign-extend to that width, which is a number no less than `x`'s |
| `+ - *` | modulo 2^N |
| `/ %` | unsigned. Dividing by zero is undefined: a specification checks first |
| `& \| ^ ~`, unary `-` | bitwise, and negation |
| `<< >>` | shifts. `>>` is logical. The count is any `uN`, or a number less than the width; a count of the width or more gives 0 |
| `< <= > >=` | unsigned comparisons of `uN` values, giving a `bool` |
| `== !=` | equality, on any type but a record |
| `&& \|\| !` | on `bool`s; `&&` and `\|\|` don't evaluate their right side when the left decides |
| `match e { 0 \| 1 => a, _ => b }` | a choice ([2.5](#25-statements) has the rules for arms) |
| `f(x, y)`, `f(a: x, b: y)` | a call, by position or by name; the arguments are evaluated left to right, before it |
| `@pc`, `@r[i]`, `@mem[a]` | a register, an entry of an array of registers, a memory's contents |
| `Sum { value: x, … }`, `s.value`, `Size.Byte` | a record, a field, an enum's value |

Built in:

| Function | Meaning |
|---|---|
| `asr(x, n)` | arithmetic shift right |
| `ror(x, n)` | rotate right |
| `sdiv(a, b)` | signed division, rounded toward zero |
| `srem(a, b)` | its remainder, which takes the dividend's sign |
| `bit(b)`, `bool(x)` | a `bool` as a `u1`, and back |

Operators bind as in Go, loosest first: `||`; `&&`; the comparisons;
`|`; `^`; `&`; `++`; the shifts; `+ -`; `* / %`; the unary `~ - !`;
slices, indexing, fields and calls. Where the order could be misread
it must be written out with parentheses, and anything else is an error:

- `&&` with `||`;
- a comparison of a comparison (`a == b == c`);
- any two different operators from `| ^ & ++ << >>` and the arithmetic
  ones: `x & 3 + 1` and `x << 2 + 1` are errors.

Arithmetic among itself binds as in school, so `a + b * c` needs none.

#### 2.4 Declarations

A specification is a list of declarations, in any order.

```
register r[16]: u32         // an array of registers
hardwired r[0] = 0          // an entry that always reads as this; writing it does nothing
register pc: u32            // a register
flag N, Z, C, V             // bool registers
memory mem[u32]: u8         // 32-bit addresses, 8-bit contents
const SP: u4 = 15           // a name for a value: its type is given,
const RAM_SIZE = 32'h0010_0000      // or its value's
enum Size { Byte, Half, Word }
record Sum { value: u32, carry: bool, overflow: bool }
fn add(a: u32, b: u32, carry: bool) -> Sum { … }
proc push(value: u32) { … }
instruction "ADD rd, ea"  0100 dddd mmmm nnnn { … }
```

- **A `fn` gives a value** from its arguments and the state. It can't
  change the state, `fault`, `trap`, `halt` or `assume`, and calls only
  `fn`s. Its result type is required, and every path through it returns.
- **A `proc` may do anything:** change the state, fault, and give a
  value (`-> T`) or not. It is called only on its own: as a statement,
  or as the whole right side of a `let`, a `:=` or a `return`, so the
  order of what happens is the order of the lines. `@pc + parcel()`
  can't be written; `let d = parcel()` then `@pc + d` can.
- **Arguments** are by position, or by name, `f(a: x, b: y)`. Where two
  parameters have the same type, every argument is by name, so that
  `add(a: @r[d], b: x, carry: false)` can't swap `a` and `b`.
- **A name means one thing.** A parameter, a local or an instruction's
  field can't have a global name, and a local can't hide another.
- **An instruction** is its syntax (a string, for the reader), its
  encoding and its body.
  - The encoding is a string of `0`, `1`, `-` and lower-case letters,
    most significant first; the spaces are for the eye. `0` and `1` must
    match, `-` matches either, and a run of one letter is a field:
    `dddd` binds `d`, a `u4`, in the body.
  - `when` adds a condition on the fields and constants:
    `0000 aaaa bbbb 0101  when 1 <= a && a <= b`.
  - Instructions are tried in the order the specification lists them
    (`decode`, below); the first whose encoding and `when` match runs.

#### 2.5 Statements

| Statement | Meaning |
|---|---|
| `let x = e`, `let x: T = e` | a name for a value, which doesn't change. It is seen to the end of its block |
| `var x = e` | a name that `:=` may change |
| `x := e`, `@pc := e`, `@r[i] := e`, `@mem[a] := e` | a change, seen at once |
| `if c { … } else if c { … } else { … }` | `c` is a `bool` |
| `for i: u5 in a ..= b { … }` | `i` from `a` to `b`, both included. Its type is given, or taken from a bound |
| `match e { … }` | the arm whose pattern equals `e` |
| `return e`, `return` | |
| `fault v` | abandon the instruction, and enter vector `v` with the instruction's own address ([2.7](#27-running-a-specification)) |
| `trap v` | the same, with the next instruction's address |
| `halt` | the machine stops after this instruction |
| `assume c, "why"` | if `c` doesn't hold, what happens is outside the specification |
| `decode p else { … }` | run the first instruction whose encoding matches `p`; the block if none does |
| `f(x)` | a `proc` called for what it does. A value given back can't be dropped |

A match arm is `patterns => body`. The patterns are constants, separated
by `|`, or `_` for anything else; the body is a statement, a block, or
(in a match expression) an expression. The arms must cover every value
of `e`'s type, and no value may be in two arms. A record literal in the
head of an `if`, `match`, `for` or `when` needs parentheses, as the `{`
after it would otherwise read as the record's.

#### 2.6 What is checked

A specification is checked when it is loaded, before it runs. These are
errors:

- a type or width that doesn't match, or a number that doesn't fit;
- a `fn` that changes state, faults or calls a `proc`; a `proc` call
  inside an expression; a value given back and dropped;
- two parameters of one type given by position;
- a `match` that misses a value, or matches one twice;
- a `fn` or `proc` that can end without its value;
- a name that hides another, or state written without `@`;
- operators that need parentheses ([2.3](#23-expressions));
- a `let` changed, a field that isn't the record's, a slice outside its
  value, a shift by a constant that leaves nothing.

#### 2.7 Running a specification

A specification defines two procs:

- `proc step()`, one instruction. It usually fetches a parcel and
  `decode`s it.
- `proc enter(vector: u32, ret: u32)`, what a fault or trap does.

`fault v` and `trap v` end the instruction where they are: what it has
done so far stays done. Then `enter(v, ret)` runs, where `ret` is the
register `pc` as it was when `step()` began (`fault`) or as it is now
(`trap`). If an `assume` doesn't hold, the specification says nothing
about what follows; a run on known values stops there.

**Open:**

- **Interrupts.** A specification has no entry for them yet, and `halt`
  only says the machine stops; 1b's "wait for an interrupt" isn't in it.
- **Signed comparisons.** None has been needed, and `sdiv` covers the one
  signed operation 1b has. Something like `<s` may want adding.
- **Generated documentation:** tables of encodings, and the
  instructions' text, made from the specification.

#### 2.8 Running it on symbols

The interpreter ([spec.py](../studies/formal/spec.py)) runs a
specification on known values or on z3 terms. The semantics are those
above either way; this section is how the symbolic run keeps to them.

- **It never forks.** A statement under a condition it can't decide runs
  under a *guard*: a change becomes "if guard then new else old". A
  `fault` turns the guard off for the rest of the instruction. One pass
  gives the next state for every path at once, and the conditions under
  which the `assume`s hold, which a proof takes as hypotheses.
- **It notes its decisions,** if asked: each arm of an `if` or `match`,
  each flag set to `true` and to `false`, each fault, with the guard
  under which each outcome happens. On known values that says which
  outcome was taken. The right side of `&&` and `||`, and each arm of a
  match expression, runs under the guard where it is evaluated, so a
  symbolic run notes the decisions a run on known values would meet.
  These are the goals of S2's chosen cases.
- **A memory, and an array of registers, may be an object** with
  `read(address)` and `write(address, value, guard)`. On known values that
  is a dictionary. In a proof it is z3 arrays shaped like the hardware's,
  so that both sides read the same terms (P7). Such an object keeps the
  `hardwired` entries itself.

## Part III: Results and discussion

### 3. What was proved, and how

#### 3.1 What is proved

The proof is a commuting diagram, one instruction at a time. For any
hardware state at an instruction boundary, however its values are
chosen:

- the hardware runs, a clock cycle at a time, to the next instruction
  boundary;
- the specification runs one instruction from the state the abstraction
  gives;
- the two end states must again be related by the abstraction.

With reset reaching a boundary in the right state (P6), that is an
induction over a whole run: the hardware does what the specification
says, instruction by instruction, for as long as it runs.

On 1b the boundary is the clock edge that ends a decode cycle: the cycle
whose microinstruction fetches the next instruction's first parcel and
has the decode ROM choose its routine (`SEQ` = decode, `LDIR`). Just
after that edge, the abstraction is:

**Table 1: draft 1b's abstraction**

| Hardware | Is |
|---|---|
| uIR | the control word at the routine the decode ROM gives for IR |
| IR, LEN, SX | the parcel at the specification's `pc`; its length; IR[7:4] |
| PC | `pc + 2` |
| register file entries 0–15, both copies | `r0`–`r15`, with entry 0 = 0 |
| entry 16 | `hi` |
| entries 24 and 25 | the loop counts the microcode keeps there, `0xFFFFFFE1` and `0xFFFFFFE0` |
| the other entries | anything, but the same in both copies |
| N, Z, C, V, I | the specification's flags |
| RAM | the specification's memory, mirrored every 1 MB |
| R, T, MAR, MQ, LC, CL, SGN, S33 | anything |
| the interrupt synchronisers | no interrupt pending |

**Decode cases.** The decode ROM is what turns a parcel into a routine,
so the cases are its routines: 1082 distinct values for the 65,536
parcels.

- For 1075 of them, the parcels that select the routine are a *cube*:
  some bits fixed, the rest free. ADD with a register operand is
  `0100 dddd 0000 nnnn`, eight bits free, so one case covers every
  register pair.
- Six more (Bcc, SETcc and the four Jcc routines) are a cube with a few
  parcels taken out. They carry that as a hypothesis.
- The illegal routine serves parcels of every opcode, and is split into
  15 cases, one per opcode that has illegal parcels (P3).

That is 1096 cases.

#### 3.2 The hardware side

The netlist is the one the chip-level simulator runs, built by
`studies/v1b_hw/cpu.py`. [symsim.py](../studies/formal/symsim.py) runs
it a clock cycle at a time, with values that are either known or z3
terms:

- **A model per part:** the 22 kinds of part in the netlist, from gates
  and multiplexers to the 74181, the 74182, the counters, the 299 shift
  register, static RAM and flash. They are written from hwsim's models,
  without the timing.
- **Two phases a cycle:** the write window, in which a static RAM whose
  write enable is low takes what its data pins carry; then the end of the
  cycle, with the RAMs' new contents showing, when every edge-triggered
  part takes its next state. That is the 1b clock fixture's write window
  (0.5 to 0.875 of the period) reduced to its order of events.
- **Nets evaluated on demand,** and inputs read only when needed. A
  multiplexer with a known select reads only the input it selects; a
  three-state driver's data is read only if it may be enabled. So the
  control signals, which come from ROMs with known contents, stay known,
  and the datapath folds down to the operation the microinstruction
  selects. A loop in the netlist that the control breaks is never
  entered: the A bus feeds the immediate unit's fill bit, which feeds the
  B bus, which the bridge can put on the A bus.
- **Three-state buses:** a net takes the value of the driver that is
  enabled. Two that may be enabled at once are a contention; when the
  enables are symbolic, that is an obligation for the solver to prove
  impossible. With no driver enabled the net floats: a fresh variable,
  so nothing that depends on it can be proven.
- **Memories as z3 arrays,** from 15-bit (register file) or 19-bit (RAM)
  addresses to bytes.

**Case splitting** (P4). A ROM's address must be known. When a symbolic
bit reaches one, the cycle stops, and the solver is asked whether the bit
can be 0 and whether it can be 1 under the path so far. If only one is
possible, that becomes a fact. If both are, the run splits, one path for
each, and the cycle runs again. In 1b the control store's address takes
the branch condition, the indexed mode's dispatch on its extension
parcel, the address-error fault and the interrupt request, so those are
where paths split. The operands, the addresses and the register numbers
stay symbolic: the microcode's control is concrete and the datapath
symbolic, which is what a microcoded machine is built around.

The simulator was checked on known values against the RTL model
(`studies/v1b_hw/rtl.py`), the reference the netlist was built from:
every register, flag and both register file copies agree after every
cycle, on `hello` to the end and on the first 200,000 cycles of the
exercise program, which covers every instruction class.

#### 3.3 The specification side

[v1b.isa](../studies/formal/v1b.isa) is draft 1b in about 770 lines,
545 of them code. It reads like RFC 0004's tables made precise: the
state, then memory, flags and the addressing modes, then each instruction
with its encoding. Its `assume`s are the I/O page's registers, accesses
outside RAM, code outside RAM and a misaligned stack while entering a
fault: each a case where the simulator stops, or does something the
specification doesn't describe.

It was checked against the instruction-level simulator as S2 says, and
the two never disagreed:

- **Random cases** (`heron formal isacheck`): 100,000, which ran every
  instruction and every kind of fault.
- **Cases chosen by the specification** (`heron formal isagen`). Each of
  the 55 instructions runs once on symbolic inputs, noting every decision
  it meets ([2.8](#28-running-it-on-symbols)). Each outcome of each
  decision is a goal: 1284 of them over the 55 instructions. For each
  goal the solver finds inputs, three times. Each time a random half of
  the inputs is first pinned to random values, mostly boundary values
  (0, 1, −1, the sign bit, small numbers), so the inputs the goal doesn't
  decide come out random. Encodings no instruction has are sampled at
  random. The result:
  - 3755 cases in under three minutes;
  - every goal the solver can reach (1245) reached;
  - 39 goals proved impossible.

  For comparison, 20,000 random cases reach 1224 of the 1245.

An impossible goal is an outcome one instruction can't reach in code it
shares with others. LEA can't reach `operand()`'s arms for the updating
modes, because it turns them away first. BSR can't take an address
error: its only possible one is a misaligned stack, and entering the
vector then assumes an aligned one. Over the whole text, only one of
the specification's 220 decision outcomes is reached by no instruction:
the last arm of the `case` in `condition()` can't fall through, because
the `case` is exhaustive.

The language had two versions. The first was untyped and looked like
Python: every value a bit vector, a bare number taking whatever width it
met, a flag a 1-bit value, blocks by indentation, and functions free to
change state. The second, Part II's, came out of Emily's review: braces;
`@` for state; `fn` apart from `proc`; types, with `bool` apart from
`u1`, enums and records; sized numbers; named arguments where a swap
would type-check; and the checks of [2.6](#26-what-is-checked). Draft 1b
was rewritten in it. The rewrite found no mistake in the first text, and
the checker caught one slip in the rewrite (a parameter named like a
function). The solver proved that the two texts say the same
(`heron formal versions`): each instruction (an EA instruction one mode
at a time) runs in both on the same symbolic inputs, and they make the
same assumptions and give the same registers, flags, PC, faults and
halts, with the same writes to memory in the same order. That is 835
comparisons in 69 seconds. Comparing the memories as arrays was too hard
for the solver; comparing the writes is stronger and easy. The text is longer, about 770 lines against 610: the
closing braces, a `let` for each `proc` value used in an expression, and
the named arguments.

Making the coverage count honest took four fixes to the tools. Each would
have reported a goal as missed, or as reached, wrongly:

- an instruction's own parcel has to read back as itself, or the decode
  doesn't fold and every instruction's text is "reached" from every
  other;
- a case aimed at an instruction counts for it even when it decodes as
  illegal (MFSR with n > 1);
- `and` and `or` must note what their right side does only where it is
  evaluated. `c == 14 or condition(c)` never calls `condition` with 14;
- a constant assignment has one outcome, not two.

Writing it found one thing RFC 0004 doesn't say. When the EA's register
is updated (`[rn]+`, `-[rn]`), which value of `rd` does the instruction
see if `rd` is that register? The simulator's answer is that an ALU
operation reads `rd` after the update (`ADD r1, [r1]+` adds the
incremented r1), a load writes `rd` after it (the loaded value wins),
and a store reads `rd` before it. The specification follows, with a
comment. By S4, this is a question for RFC 0004.

#### 3.4 Joining them

For each decode case both sides start from the same symbolic values:
registers, flags, PC, memory and the parcel. The specification runs
first, and the conditions under which its `assume`s hold become
hypotheses. The hardware then explores its paths under them, and at the
end of each the goals of P5 are proved.

**Making the two sides' terms meet** (P7). The first version gave the
specification's registers as a list and read `r[d]` through a 16-way
`if` chain, while the hardware read a z3 array. Proving ADD with
symbolic register numbers took 57 seconds. Then the specification's
register file was given the hardware's shape: four byte-wide arrays,
15-bit addresses, the same simplified index term. A register read became
the same term on both sides, the solver only had to prove the adders
equal, and ADD took 6.6 seconds. Memory had the same treatment from the
start: the specification's bytes live in the arrays of the hardware's
two RAM chips.

The goals are proved a group at a time: registers, the copies, flags,
memory, control, obligations. Each group is checked under the path's
conditions, after z3's simplifier has removed the goals that are already
equal as terms.

#### 3.5 What is trusted

A proof is only as good as what it stands on:

- **The part models.** symsim's are a second implementation of hwsim's,
  checked against the RTL model on known values ([3.2](#32-the-hardware-side)),
  not proved equal to hwsim's.
- **Cycles, not time.** The proof is about the netlist's function, a
  clock cycle at a time. That every signal settles in its cycle is
  static timing analysis's business (`heron v1b_hw hw sta`).
- **The specification,** checked against the simulator by testing, not
  proved equal to it.
- **What is left out:** interrupts (IRQ held low), the I/O page, and
  HALT's wait for an interrupt.
- **z3,** and the Python around it.

### 4. Results

RESULTS

### 5. What the microcode relies on

The abstraction ([table 1](#31-what-is-proved)) is the list of what the
microcode assumes at an instruction boundary. A proof fails until the
list is complete, so writing it was part of the work, and some of it
isn't written anywhere else:

- **The loop counts are sign-extended.** Register file entries 24 and 25
  hold the counts that the multiply, divide and shift loops start from.
  The reset routine writes them as the signed bytes −31 and −32, so they
  are `0xFFFFFFE1` and `0xFFFFFFE0`, not the `0xE1` and `0xE0` of
  `ucode.RF_CONSTS`. Only the low byte is ever loaded into LC, so it
  doesn't matter, but the first reset proof failed on it (D3).
- **Both register file copies must agree, and reset doesn't make them**
  (D2). The A copy feeds the A bus and the B copy the B bus, so
  `ADD r1, r1` adds one copy's r1 to the other's. Every write goes to
  both copies. But reset writes only r0, HI and the two loop counts.
  Until a program writes r1–r15, their two copies hold whatever the RAMs
  powered up with, and an instruction that reads one of them on both
  buses sees two different values. The instruction-level simulator starts
  with every register 0, and so do the chip-level runs (`zero_regs`), so
  no test can see it. **Open:** either RFC 0004 says the registers are
  undefined after reset and programs mustn't read them before writing
  them, or the reset routine clears r1–r15, 15 more cycles at reset.
- **The rest is as expected.** Entry 0 holds 0, entry 16 is HI, and no
  interrupt is pending. Nothing else carries over from one instruction to
  the next: R, T, MAR, MQ, LC, the condition latches and the other
  register file entries can be anything at a boundary. That holds in every
  case proved; the routines that use the scratch entry 17 (`TMP1`) are
  among those over budget.

### 6. What it costs

Simulating is cheap: a few hundred milliseconds a case, most of it
building terms. Nearly all the time goes to the solver, and three things
decided how much:

- **The same term on both sides.** 57 seconds for ADD with a register
  operand before the specification's register file had the hardware's
  shape, 6.6 after ([3.4](#34-joining-them)). The rule generalises:
  wherever the specification and the hardware compute the same thing,
  let them compute it as the same term, and the solver skips it.
- **Cut-points.** A memory operand's address is computed twice: by the
  74181s for MAR, and by the specification's `+`. Every time the solver
  matches a read on one side with a read on the other, it needs the two
  equal, so it proves the ALU's address bits equal to an adder, again and
  again. Now, when MAR is loaded with a symbolic value, one query asks
  whether it equals an address the specification used. If it does, MAR
  takes the specification's term from then on, and both sides read
  memory at the same index. For `XOR rd, [sp + 20]` that took the
  memory goal from over 120 seconds (the solver gave up) to 1.5, and the
  case from 148 seconds, unproved, to 8.7, proved. It is the standard
  trick of equivalence checkers, at the one place it matters most here.
- **One query per group of goals.** One query for all fifteen registers is
  several times faster than fifteen, since the solver proves the value
  written once rather than once per register.
- **The terms as written.** z3's simplifier rewrites `a < 0x10_0000` into
  slices and `<=`, a form the solver handles worse. The second version of
  the interpreter ran it on every condition, and a Jcc case took 229
  seconds where the first version's took 30. It now simplifies only the
  conditions that choose a path (to find the constant ones), and keeps
  values and assumptions as the specification wrote them: 9 seconds
  against the first version's 32, run side by side.

What is still slow, or out of reach:

- **Multiply and divide.** `MULU`, `MULS`, `DIVU`, `DIVS` and `DIVUL` run
  16 or 32 add-and-shift (or subtract-and-shift) steps. The solver has to
  prove 32 steps of the 74181 equal to a 32 × 32-bit multiplication, or to
  a division. That is the textbook hard case for SAT-based equivalence
  checking, and none finished within its budget. Known ways round it:
  - prove one loop step against a specification of one step, and the
    loop's invariant once and for all, by hand or in a proof assistant;
  - use an algebraic multiplier checker, of the kind that verifies 64-bit
    multipliers with Gröbner bases;
  - or leave multiply and divide to the tests (W4).
- **The indexed mode** dispatches on its extension parcel's scale and size
  and on whether its displacement is 0: up to 32 paths, each with its own
  address arithmetic.
- **Loops whose count is data.** A shift by a register and CLZ split once
  per count, 32 or 33 paths, at a few seconds each (D4).

### 7. Breaking the hardware on purpose

MUTANTS

### 8. Draft 2

The draft 2 CPU ([RFC 0031](0031-rfc-draft-2-cpu.md), on its branch) is
the design this would matter for. Most of the flow carries over:

- RFC 0028's instruction set can be written in the language as it is, and
  checked against draft 2's simulator the same way (S1, S2).
- symsim's models of the parts the two netlists share, and the splitting
  at the control store's address (P4). The control store and the decode
  table are SRAMs there, filled by the I/O processor at boot; with the
  boot image's contents they are ROMs to the proof.
- Decode cases, cut-points, goals in groups.

What doesn't:

- **Phases within a cycle.** Draft 2's cycle is 4 to 19 ticks of a
  50 MHz clock:
  - the register file is read through transparent latches (74F573) and
    written in the last tick;
  - T loads through latches late in the cycle;
  - the memory write window opens at tick 4.

  1b's two phases (the write window, then the edge) aren't enough. The
  simulator needs either a sequence of phases per microcycle, with latch
  models, or a step per tick with the clock generator itself in the
  netlist (its tick counter, the length classes from the uIR). The second
  proves the clock generator too, and costs more steps, each cheap.
- **The prefetch queue.** At an instruction boundary the queue holds
  some parcels ahead of the PC, depending on what came before. The
  abstraction must say that what it holds is memory at FPC, and the
  cases split on how full it is.
- **The system architecture.** The page map, supervisor mode, the fault
  registers and the forced microcode entries are in RFC 0029. The
  specification must have them, and translation adds splits (a page fault
  or not) and array reads (the map) to every access.
- **Size:** 456 parts against 1b's 216. The netlist uses eight kinds of
  part that 1b's doesn't: the 573 latches, the 574 registers, a 74x109, a
  138 decoder, a 163 counter, and the oscillator, power-on reset and
  pull-ups of a card that makes its own clock.

None of this looks out of reach, and the multiply and divide will be as
hard as 1b's. The specification is the cheapest step and is useful on
its own: written in this language and checked against the simulator, it
makes RFC 0028 executable and precise. On 1b, writing it found a
question RFC 0004 doesn't answer ([3.3](#33-the-specification-side)).

### 9. What next

In order of what each buys for its cost:

1. **Draft 2's specification**, checked against draft 2's simulator:
   RFC 0028's instruction set, then RFC 0029's system architecture (S1,
   S2). It makes those RFCs executable and precise, and everything else
   here needs it.
2. **Proofs on microcode changes** (W1). A change to the microcode touches
   a few routines, and proving just their decode cases takes minutes. The
   mutants of [section 7](#7-breaking-the-hardware-on-purpose) are the
   mistakes this would catch.
3. **Draft 2's netlist under symbolic simulation:** phases or ticks,
   latches, the prefetch queue and the page map in the abstraction
   ([8](#8-draft-2)).
4. **Multiply and divide,** by a loop invariant proved once, or an
   algebraic multiplier checker (D5). Until then they are the tests' job.
5. **Closing the trusted base:** interrupts and the I/O page in the
   specification and the proof; symsim's part models checked against
   hwsim's on random inputs, or one generated from the other.
