# RFC 0028: the fixed-base mode, measured on 1b

The measurements behind mode E of
[RFC 0028](../0028-rfc-draft-2-isa.md#96-the-addressing-modes)
(**decided**, Emily, 2026-10-15): `[r14 + 4R]`, the first 16 words of
the current object in one parcel, as `[sp + 4R]` gives a stack frame's.
They were made on draft 1b, before draft 2 existed, with the mode added
to 1b as its reserved mode E and a register `rT` of each program's
choosing.

The code is `studies/fixed_base`, with the mode in draft 1b's simulator
and assembler, in [pull request 51](https://github.com/aiju/heron/pull/51),
which was closed without merging: draft 2 has the mode itself. It stays
at
[71e1d0b](https://github.com/aiju/heron/tree/71e1d0b59042aeb61e5ce6c20d788cbf55a9a893/studies/fixed_base),
and the tables in the [appendix](#appendix-the-tables) are a snapshot of
its `heron fixed_base report --write` there.

The question was whether a second fixed-base slot shaped like
`[sp + 4R]` ([RFC 0028, 10.1](../0028-rfc-draft-2-isa.md#101-short-offsets))
is worth column E of the map, then the tagged operations, with the
tagged operations kept under other opcodes. It pays only where software
keeps a struct in a register, so it was measured on the three programs
that keep a "current object": Egret's VM, the Lisp and the kernel
study's nucleus.

## Summary

- **Egret gains about 1%.** Its frame record (`r11`) or its slots (`r9`)
  in rT save 0.6% of the hand-written interpreter's cycles and 1.0% of
  the JIT's, up to 3.3% for richards. Egretica, on the desktop
  ([pull request 35](https://github.com/aiju/heron/pull/35)), gains 0.5%.
- **The Lisp gains nothing as it is.** Its pointers are tagged, so its
  fields are at 4k ± 1, never at multiples of 4. Keeping the current
  closure in rT would save 1.35% (8% for sieve), but only if its tags
  changed.
- **The nucleus gains 3–5% on its message paths,** and its code is 4%
  smaller. A call and reply with half banks takes 279 cycles instead of
  293.
- **Almost every use is a load or a store:** 75–100% of the accesses.
  Most of the rest is `LEA` (Egret's frame pushes and slot addresses) and
  the JIT's returns, `JMP [r11 + nip]`, which the mode gets for free. The
  ALU operations are under 1%. In hand-written code a fifth to a third of
  the loads are tested by the next branch, so in draft 2 they would be
  `MOVS`. So three cells, `MOV`, `MOVS` and `ST`, would get nearly all of
  it.
- **What the measurements suggested:** `MOV`, `MOVS` and the store with
  `[rT + 4R]` in `1E`–`3E`, the tagged operations keeping the rest of
  column E, and `rT = r14`. Draft 2 took the whole column, which keeps
  the mode table orthogonal, with `r14`
  ([RFC 0028, 9.6](../0028-rfc-draft-2-isa.md#96-the-addressing-modes)).

| | Saves, D32-separate | D32-wide | rT |
|---|---:|---:|---|
| Egret, hand-written interpreter (17 programs, geomean) | 0.62% | 0.48% | `r11`, the frame record |
| Egret, JIT | 1.00% | 0.84% | `r11` (or `r9`, the slots: 1.00%, 0.82%) |
| Egret, interpreter loop in C | 0.20% | 0.16% | `r11` (incidental) |
| Egretica's eight lines, interpreter (the desktop) | 0.51% | 0.67% | `r11` |
| Lisp, compiled (12 programs, mean) | 0.00% | 0.00% | none fits |
| …with the closure in rT and tags that allow it (estimate) | 1.35% | 0.96% | the closure |
| Nucleus: a call and reply between processes, half banks | 4.8% | | `r6`, the other thread's TCB |
| Nucleus: yield, preemption, interrupt to a driver, half banks | 2.8–3.1% | | `r6` |

## 1. How it was measured

- **The mode on 1b:** the ISAs `v1b+rtN`, `v1bs+rtN` and `v1bx+rtN` are
  1b, the kernel's v1bs and the Lisp's v1bx with mode E the word at
  `rN + 4R`. The timing model costs it as `[sp + 4R]`: a `[R + d16]`
  access one parcel shorter, a cycle less on D32-separate and 0–1 on
  D32-wide. The assembler picks it for `[rN + 0..60]` words, as it picks
  `[sp + 4R]`. In `v1bx+rtN` the tagged register operations are op F's
  spare functions instead, so the Lisp keeps them.
- **Run:** Egret's whole VM and the nucleus are assembled with the mode
  and run against the same programs, which print what they should. Only
  the encoding changes, so rT is a register the code already keeps a
  struct in. Egret's JIT emits the mode when built with `EGRET_RT`.
- **Scanned:** the simulator counts executions per instruction, so one
  baseline run prices any choice of rT, and any other short form: every
  executed word access `[R + 4..60]`, costed one parcel shorter. The runs
  save what the scans say on D32-separate, or a cycle or two more where
  the shorter code brings a branch within reach of `Bcc`.
- **Counted** as the studies count: Egret's programs less start-up and
  compiling (report 0017), the nucleus per operation (report 0020), the
  Lisp over its compiled forms' running (report 0018), with v1bx's tagged
  operations as the baseline.
- **D32-wide** is averaged over both code alignments for Egret. The
  nucleus's moves by up to ±10% with alignment alone, so its numbers are
  for D32-separate.
- **The desktop:** Egretica and Gadgets are in
  [pull request 35](https://github.com/aiju/heron/pull/35), not on
  `main`. They were scanned at its head, 71eb7db, with the same tool:
  the eight lines of report 0021's bench, and Gadgets running for 20 s.

## 2. Egret

Egret's VM keeps two structs in registers while it runs Egret code:

- **`r11`, the frame record**: `ip`, `bp`, `method`, `serial`, `flags`,
  `nip`, six words at 0–20. A send stores four of them at 4–16 and pushes
  the frame with `LEA r11, [r11 + 24]`; a return loads three, one of them
  (`flags`) only to test it. Popping the frame is `[r11 − 24]`, which the
  mode doesn't reach.
- **`r9`, the frame's slots** (receiver, arguments, locals). The
  hand-written interpreter indexes them by the bytecode's operand
  (`[r9 + r1*4]`), so only the JIT has them at constant offsets.

Measured, every program on every build (the [appendix](#egret) has them all):

| Build, rT | Geomean, D32-separate | D32-wide | Most |
|---|---:|---:|---|
| Interpreter, `r11` | −0.62% | −0.48% | bst −1.8%, richards −1.7%, trees −1.5%, shapes −1.4% |
| JIT, `r11` | −1.00% | −0.84% | richards −3.3%, trees −2.9%, fib −2.5%, bst −1.9% |
| JIT, `r9` | −1.00% | −0.82% | sieve −2.3%, mandel −1.9%, closures −1.8%, life −1.7% |
| C loop, `r11` | −0.20% | −0.16% | bst −0.5%, richards −0.5% |

- **The two registers serve different programs:** `r11` the send-heavy
  object programs, `r9` the loops. A JIT whose frame record and slots
  sat in one 64-byte window (the record just below the receiver, say)
  would get both, about 2%.
- **The operations** through `r11` are `ST` 50%, `MOV` 25%, `LEA` 13% and
  a load tested by the next branch 12% (the return's `flags`, a `MOVS` in
  draft 2) in the interpreter; in the JIT `ST` 55%, `MOV` 23%, `LEA` 11%
  and `JMP [r11 + nip]` 11% (a return); through `r9`, `MOV` 64%, `LEA`
  24%, `ST` 11%. No ALU operation uses them beyond 1%.
- **Instance variables don't benefit.** The interpreter indexes them by
  the bytecode's operand. The JIT loads `self` from the receiver slot and
  then the field, `[r2 + 8 + 4i]`. Keeping `self` in rT instead would
  mean reloading it at every send and return.
- **Most of the VM is C,** where no register holds one struct: the
  compiler, the primitives, bignums, the collector. The C loop gains
  0.2% only because `r11` happens to be a callee-saved register the
  compiler uses for pointers.
- **The desktop** runs the hand-written interpreter, and spends more of
  its time in C (bignums, drawing, primitives). Egretica's eight lines
  gain 0.25–0.79% each, 0.51% together (0.67% on D32-wide). Gadgets
  gains 0.40%.

## 3. The Lisp

The Lisp has nothing for `[rT + 4R]` as it is: through the best single
register, 0.06% of its compiled cycles on average and 0.13% at most.

- **Its pointers are tagged:** a pair's car is `[p − 1]` and its cdr
  `[p + 3]`, an object's call slot `[p + 1]` and its fields
  `[p + 5 + 4i]`. None is a multiple of 4. The alignment trap on those
  odd offsets is how it checks types for free (report 0018).
- **It keeps no struct in a register** across code. `r13` is `nil` and
  `r14` the heap pointer.
- **The current closure is the candidate.** A free variable is read as
  `MOV r, [sp + 4k]` (the closure, from the frame) and
  `MOV r, [r + 5 + 4i]`: three parcels and two instructions, which one
  one-parcel load would replace. Net of setting rT on each entry to a
  function with free variables, that would save 1.35% of compiled cycles
  on average (0.96% on D32-wide). Most programs have no closures in
  their loops; sieve would save 8.0%, closures 2.6%, destruct 2.2%,
  sort 1.7%.
- **It needs the tags to allow it.** rT would have to hold the closure
  less its tag, a raw pointer into the heap. The copying collector finds
  pointers by their tags, and a raw pointer saved on the stack looks
  like an integer, so it wouldn't be updated. Either the Lisp moves to
  pointers whose fields are at multiples of 4 (Egret's representation,
  integers 2n + 1), or the mode subtracts the tag (`[rT + 4R − 3]`). The
  first is tied to RFC 0028's open question of which tag marks an
  integer, and would cost the Lisp its free type checks.
- **Its other two-parcel words** are the runtime's variables at
  0x100–0x13F: 3.5% of compiled instructions. They are almost all the
  heap and stack limit checks, which guard pages would remove anyway
  (reports 0018 and 0020). rT as a pointer to them would save about 0.9%.
- **`MOV`/`ST [R + 4k]` with any base** would do no better: 0.06%.

## 4. The nucleus

Kernel code is mostly loads and stores of control-block fields (report
0020), and the TCB's first 16 words (`T_NEXT` to `T_PT`) fit
`[rT + 4R]` exactly. Measured on D32-separate, with the nucleus as it is:

| Operation | Cycles, half banks | rT = `r6` | rT = `r8` | rT = `r14` |
|---|---:|---:|---:|---:|
| Call and reply between processes | 293 | −4.8% | −2.7% | −0.3% |
| Yield to another process | 207 | −2.9% | 0.0% | −1.0% |
| Timer preemption (nucleus only) | 203 | −2.8% | 0.0% | −0.8% |
| Interrupt to a user-level driver (nucleus only) | 545 | −3.1% | −0.6% | −0.6% |
| `write` through the console server | 479 | −2.9% | −1.7% | −0.2% |

Without banks or with full banks the same operations save 2.1–3.5%
(the [appendix](#the-nucleus)).

- **Which TCB:** in the IPC paths `r6` holds the other thread (the one
  called, or the one replied to), `r8` the current one. The accesses
  through `r6` are loads 67%, loads tested by the next branch (`MOVS` in
  draft 2) 19% and stores 14%. With banks the
  current thread lives in `r14` between traps, but the paths copy it to
  `r8` first, which is why `r14` shows so little.
- **A nucleus written for the mode would get more.** A call and reply
  touches 23 fields at 4–60 in 2–3 TCBs. One rT reaches 12 of them as the
  code stands. Keeping rT on whichever TCB a path works on, and moving
  it between them when the path switches, would reach most of the rest.
  1a's `[r + 4o]` with any base reaches all 23 (7.8%).
- **The code is smaller:** 1,394 bytes of instructions with half banks,
  1,338 with rT = `r6` (−4.0%), and −3.4% to −5.0% across the policies
  with `r6` or `r8`.
- **Context:** these paths are a small part of a whole machine's time.
  Report 0020 puts a call and reply at 98 µs, and timer preemption at
  0.5–0.8% of the machine at 100 Hz. The savings matter where messages
  and interrupts are frequent: every interrupt handed to a user-level
  driver takes 17 cycles less.

## 5. Against the other short form

RFC 0028 10.1's other option is `MOV` and `ST` with `[R + 4k]`, k = 1–4,
any base, in 8 cells. From the scans, the share of cycles each form
would save on D32-separate (Egret: the mean over programs; the nucleus:
a call and reply with half banks, which measured 4.8% where the scan
says 4.1%, the difference being branches that came into reach):

| | `[rT + 4R]`, loads and stores (3 cells) | `[rT + 4R]`, every operation | `MOV`/`ST [R + 4k]`, k = 1–4 (8 cells) | Every `[R + 4..60]` word, any base |
|---|---:|---:|---:|---:|
| Egret, interpreter | 0.54% | 0.62% | 0.85% | 1.86% |
| Egret, JIT (`r11`, `r9`) | 0.75%, 0.87% | 0.97%, 1.00% | 1.66% | 2.84% |
| Egret, C loop | 0.16% | 0.20% | 0.26% | 1.29% |
| Egretica and Gadgets (the desktop) | 0.43% | 0.49% | 0.87% | 2.02% |
| Lisp, compiled | ≤ 0.06% | ≤ 0.06% | 0.06% | 0.06% |
| Nucleus, call and reply (`r6`) | 4.1% | 4.1% | 3.1% | 7.8% |

"Loads and stores" are `MOV`, `MOVS` and the store in draft 2's terms;
"every operation" adds `LEA` and `JMP [rT + 4R]`, and the ALU operations
add 0.01% at most. RFC 0028's `[R + 4k]` would want `MOVS` too, 4 cells
more. Egret's D32-wide figures are in the [appendix](#egret), and rank
the forms the same way.

- **Per cell, `[rT + 4R]` buys more:** three cells get Egret half to two
  thirds of what eight cells of `[R + 4k]` get, and the nucleus more.
- **`[R + 4k]` needs no convention,** works with any base and so in
  compiled C, but reaches only the first four fields beyond 0. The
  nucleus's hot fields are spread over the TCB.
- **Either is small next to 1a's short offsets with any base,** which
  would save about twice as much: the cost of 1b's encoding, which draft
  2 builds on.

## 6. What it would cost in draft 2

- **Cells:** with `MOV`, `ST` and `MOVS`, 3 cells, `1E`–`3E`. `3E` is
  free, `TMOV` and `TTST` move to 2 of the other free cells, and `TADD`,
  `TSUB` and `TCMP` stay in `4E`–`6E`.
  - Without `MOVS`, a field loaded to be tested takes a `TST` after it,
    which costs what `MOVS` with `[R + d16]` does now: 12% (Egret) to 19%
    (the nucleus) of the uses would gain nothing.
  - `LEA rd, [rT + 4R]` would take a fourth cell (`03` is free): Egret
    pushes frames and takes slot addresses with it, 11–24% of its rT
    accesses.
  - The whole column, with the six ALU rows, would take 9 cells: the 4
    free ones in it now, and 5 for the tagged operations moved out. It
    would add almost nothing: the ALU operations are under 1% of the
    accesses.
- **`JMP` and `CALL`** take their mode from the register byte, so
  `JMP [rT + 4R]` (Egret's JIT returns that way) comes with the mode
  number, at no cell. So do `CLR`, `INC` and `DEC` on a field.
- **Hardware:** none. The register file's address multiplexers already
  take a register number from the microinstruction, which is how
  `[sp + 4R]` reaches `sp`, and the immediate unit already makes `4R`.
  The cost is microcode for each cell, as for the `[sp + 4R]` cells.
- **Which register:** the hardware fixes one, so the software has to
  agree on it.
  - It should be callee-saved in the C convention (`r8`–`r14`), so that C
    code called from the VM or the nucleus keeps it and compiled C loses
    nothing.
  - `r14` suits the nucleus, which keeps its current thread there with
    banks; with half or full banks the nucleus's `r14` is its own, apart
    from every thread's.
  - Egret's VM, the JIT and the nucleus are hand-written or generate
    their code, so moving their struct into `r14` is a renaming. Egret's
    `nil` would move to `r11`.
  - A C compiler could give rT to the most-used struct pointer in a
    function; that wasn't measured.

## 7. Conclusions

1. **Worth three cells, not a column.** Loads and stores are 75–100% of
   the accesses through rT, `LEA` and `JMP` most of the rest, and the ALU
   operations under 1%. `MOV`, `MOVS` and the store in `1E`–`3E` take one
   free cell and move two tagged operations; the rest of the tagged
   operations keep column E.
2. **What it saves is modest:** about 1% of Egret's cycles, nothing for
   the Lisp as it stands, 3–5% of the nucleus's message and switch
   paths, and 4% of the nucleus's code. It costs no chips.
3. **It pays only where software keeps a struct in a register.** Egret
   and the nucleus already do; the Lisp would need different tags. A VM
   or kernel written for it, with the hot fields in the first 16 words
   of one struct, would gain more than these numbers, which change only
   the encoding.
4. **If one more cell is going,** `LEA rd, [rT + 4R]` for Egret's
   frame pushes before any ALU operation.
5. **Decided since:** the mode, as mode E with `r14` for every
   operation. **Still open:** the Lisp's tags, which decide whether the
   Lisp can use it ([RFC 0028, 9.6](../0028-rfc-draft-2-isa.md#96-the-addressing-modes)).

## Appendix: the tables

From `heron fixed_base report --write` at
[71e1d0b](https://github.com/aiju/heron/tree/71e1d0b59042aeb61e5ce6c20d788cbf55a9a893/studies/fixed_base);
run before `main` was merged into it, at 67ba1ae, it gave the same
tables. Cycles are the timing model's for D32-separate and D32-wide.

### Egret

Each program's own cycles (less start-up and compiling it, as report 0017 counts them), with the whole VM assembled for 1b with `[rT + 4R]` and the JIT emitting it, against plain 1b. `r11` is the frame record in the hand-written interpreter and the JIT, `r9` the frame's slots. D32-separate, then the geometric means on D32-wide too.

| Program | Interpreter, rT = r11 | JIT, rT = r11 | JIT, rT = r9 | C loop, rT = r11 |
|---|---:|---:|---:|---:|
| bignum | -0.02% | -0.04% | -0.06% | -0.01% |
| bst | -1.79% | -1.93% | -0.49% | -0.53% |
| closures | -0.58% | -0.94% | -1.75% | -0.19% |
| crc | -0.64% | -1.21% | -1.16% | -0.21% |
| fib | -1.17% | -2.47% | -0.99% | -0.36% |
| hello | -0.12% | -0.07% | +0.01% | -0.19% |
| json | -0.63% | -0.97% | -0.37% | -0.22% |
| life | -0.01% | -0.02% | -1.68% | -0.00% |
| mandel | -0.06% | -0.11% | -1.87% | -0.02% |
| matmul | -0.32% | -0.35% | -0.44% | -0.14% |
| queens | -0.29% | -0.54% | -1.26% | -0.09% |
| richards | -1.68% | -3.32% | -0.79% | -0.49% |
| shapes | -1.36% | -1.56% | -0.48% | -0.42% |
| sieve | -0.00% | -0.02% | -2.30% | -0.00% |
| sort | -0.19% | -0.28% | -1.66% | -0.07% |
| trees | -1.50% | -2.88% | -0.75% | -0.45% |
| wordfreq | -0.14% | -0.18% | -0.86% | -0.06% |
| **geomean, D32-separate** | **-0.62%** | **-1.00%** | **-1.00%** | **-0.20%** |
| **geomean, D32-wide** | **-0.48%** | **-0.84%** | **-0.82%** | **-0.16%** |

From the scans of the baseline runs: the cycles each one-parcel form would save, as the mean over the programs, D32-separate / D32-wide. *rT: MOV, ST* is the loads and stores, three cells of draft 2's map (`MOV`, `MOVS` and the store), *+ LEA* a fourth; *every operation* adds the ALU operations and `JMP [rT + 4R]`. *[R + 4k]* is RFC 0028 10.1's other option, `MOV` and `ST` with k = 1–4 and any base; *every [R + 4..60]* is 1a's short offsets, any base and operation.

| Build, rT | rT: MOV, ST | rT: + LEA | rT: every operation | MOV/ST [R + 4k], k = 1–4 | Every [R + 4..60] word |
|---|---:|---:|---:|---:|---:|
| Interpreter, r11 | 0.54% / 0.82% | 0.62% / 0.82% | 0.62% / 0.82% | 0.85% / 1.03% | 1.86% / 1.79% |
| JIT, r11 | 0.75% / 0.36% | 0.86% / 0.54% | 0.97% / 0.63% | 1.66% / 1.20% | 2.84% / 2.22% |
| JIT, r9 | 0.87% / 0.76% | 0.99% / 0.86% | 1.00% / 0.87% | 1.66% / 1.20% | 2.84% / 2.22% |
| C loop, r11 | 0.16% / 0.20% | 0.20% / 0.26% | 0.20% / 0.26% | 0.26% / 0.23% | 1.29% / 1.44% |

Which operations the accesses through rT are. *MOVS* is a load a branch on N or Z follows directly, which reads its flags: in draft 2, where `MOV` leaves the flags alone, it would be `MOVS`.

| Build, rT | Operations |
|---|---:|
| Interpreter, r11 | ST 50%, MOV 25%, LEA 13%, MOVS 12% |
| JIT, r11 | ST 55%, MOV 23%, LEA 11%, JMP 11% |
| JIT, r9 | MOV 64%, LEA 24%, ST 11%, CMP 1% |
| C loop, r11 | ST 79%, LEA 20% |

### The Lisp

Compiled, with v1bx's tagged operations, over the compiled forms' running. *Fields at 4..60:* executed word accesses `[R + 4k]` through the best single register, which `[rT + 4R]` as it is would make one parcel. *Closure in rT:* what keeping the current closure in rT would save, net of setting it on entry (an estimate, `experiments.lisp` at 71e1d0b). *Runtime variables:* executed accesses to the words at 0x100–0x13F, which a globals pointer in rT would reach.

| Program | Fields at 4..60, best register: cycles saved | Free-variable reads, of instructions | Closure in rT, D32-separate | Closure in rT, D32-wide | Runtime variables, of instructions |
|---|---:|---:|---:|---:|---:|
| boyer | 0.06% | 0.01% | 0.00% | 0.00% | 3.43% |
| closures | 0.03% | 4.17% | 2.61% | 1.56% | 4.09% |
| deriv | 0.03% | 0.09% | 0.08% | 0.04% | 5.06% |
| destruct | 0.13% | 3.71% | 2.16% | 1.46% | 3.25% |
| div | 0.07% | 1.36% | 0.02% | -0.54% | 5.30% |
| fib | 0.00% | 0.04% | 0.03% | 0.01% | 3.99% |
| meta | 0.04% | 0.11% | -0.00% | -0.02% | 2.63% |
| nqueens | 0.04% | 0.02% | -0.00% | -0.01% | 2.95% |
| sieve | 0.02% | 7.08% | 8.04% | 6.06% | 2.09% |
| sort | 0.11% | 2.05% | 1.67% | 1.41% | 3.22% |
| strings | 0.13% | 1.98% | 1.63% | 1.56% | 2.10% |
| tak | 0.00% | 0.00% | 0.00% | 0.00% | 4.03% |
| **mean** | **0.06%** | **1.72%** | **1.35%** | **0.96%** | **3.51%** |

### The nucleus

Cycles per operation on D32-separate (the nucleus's own, for the scenarios that only keep it busy), and the change with the nucleus assembled for `[rT + 4R]` as it is. In the IPC paths `r6` is the other thread's TCB, `r8` the current thread's (copied from `r14` with banks), and `r14` the current thread between traps with banks. The last two columns are from the scans: the cycles a short form would save, per operation.

| Scenario, banks | Cycles | rT = r6 | rT = r8 | rT = r14 | MOV/ST [R + 4k], k = 1–4 | Every [R + 4..60] word |
|---|---:|---:|---:|---:|---:|---:|
| yield, none | 257 | -2.33% | -1.17% | +0.00% | 1 (0.4%) | 9 (3.5%) |
| yield, half | 207 | -2.90% | +0.00% | -0.97% | 2 (1.0%) | 8 (3.9%) |
| yield, full | 222 | -2.70% | +0.00% | -0.90% | 3 (1.4%) | 8 (3.6%) |
| ipc, none | 390 | -3.08% | -2.56% | +0.00% | 7 (1.8%) | 25 (6.4%) |
| ipc, half | 293 | -4.78% | -2.73% | -0.34% | 9 (3.1%) | 23 (7.8%) |
| ipc, full | 347 | -3.46% | -2.31% | +0.00% | 11 (3.2%) | 23 (6.6%) |
| preempt, none | 249 | -3.32% | -1.61% | +0.00% | 1 (0.4%) | 11 (4.4%) |
| preempt, half | 203 | -2.81% | +0.00% | -0.84% | 2 (1.0%) | 10 (4.9%) |
| preempt, full | 147 | -3.40% | +0.00% | -1.36% | 2 (1.4%) | 7 (4.8%) |
| irqdrv, none | 640 | -2.66% | -1.25% | +0.00% | 5 (0.8%) | 26 (4.1%) |
| irqdrv, half | 545 | -3.12% | -0.55% | -0.55% | 7 (1.3%) | 24 (4.4%) |
| irqdrv, full | 503 | -2.98% | -0.60% | -0.40% | 8 (1.6%) | 21 (4.2%) |
| wipc, none | 576 | -2.08% | -1.74% | +0.00% | 7 (1.2%) | 25 (4.3%) |
| wipc, half | 479 | -2.92% | -1.67% | -0.21% | 9 (1.9%) | 23 (4.8%) |
| wipc, full | 533 | -2.25% | -1.50% | +0.00% | 11 (2.1%) | 23 (4.3%) |
| wserv1, none | 1249 | -1.60% | -0.64% | +0.00% | 8 (0.6%) | 30 (2.4%) |
| wserv1, half | 1123 | -1.78% | -0.53% | +0.00% | 10 (0.9%) | 28 (2.5%) |
| wserv1, full | 1165 | -1.72% | -0.52% | +0.00% | 12 (1.0%) | 28 (2.4%) |

The nucleus's code, in bytes:

| Banks | 1b | rT = r6 | rT = r8 | rT = r14 |
|---|---:|---:|---:|---:|
| none | 1486 | 1434 (-3.5%) | 1412 (-5.0%) | 1486 (+0.0%) |
| half | 1394 | 1338 (-4.0%) | 1344 (-3.6%) | 1378 (-1.1%) |
| full | 1474 | 1420 (-3.7%) | 1424 (-3.4%) | 1462 (-0.8%) |

The accesses through `r6` are (*MOVS* as for Egret) MOV 67%, MOVS 19%, ST 14%.
