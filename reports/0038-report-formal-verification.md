---
number: 38
type: report
title: Formal verification of the hardware, explored
status: draft
date: 2026-10-16
context:
  studies: [formal, v1b_hw, v1_isa]
  commit: ce6d92f
---

# Report 0038: Formal verification of the hardware, explored

Can we prove that the hardware implements the instruction set, rather
than test it? This explores one way: run the chip-level netlist with
symbolic values in its registers, run a specification of the instruction
set the same way, split into cases where the hardware's control depends
on the data, and have an SMT solver prove the two agree. It is tried on
the draft 1b hardware ([report 0012](0012-report-draft-1b-hardware.md)),
whose netlist is on `main`. The aim is to learn how feasible this is, not
to sign the hardware off. The work is in
[studies/formal](../studies/formal/README.md).
[Part I](#part-i-the-method) is the method; [Part II](#part-ii-findings)
is what it found.

## Summary

Being written.

## Part I: The method

### 1. What is proved

The proof is a commuting diagram, one instruction at a time. An
*abstraction* says which hardware states sit at an instruction boundary,
and which instruction set state each one stands for. For any such state,
however its values are chosen:

- the hardware runs, a clock cycle at a time, to the next instruction
  boundary;
- the specification runs one instruction from the abstract state;
- the two end states must again be related by the abstraction.

Together with a proof that reset reaches a boundary with the right state,
that is an induction over a whole run: the hardware does what the
specification says, instruction by instruction, for as long as it runs.

The boundary is the clock edge that ends a decode cycle, the cycle whose
microinstruction fetches the next instruction's first parcel and has the
decode ROM choose its routine (`SEQ` = decode, `LDIR`). Just after that
edge the abstraction says:

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

The decode ROM is what turns a parcel into a routine, so the cases are
its routines: the 1082 distinct values it holds for the 65,536 parcels.
For 1075 of them the parcels that select it are a *cube*: some bits fixed,
the rest free. ADD with a register operand is `0100 dddd 0000 nnnn`,
eight bits free. Those bits stay symbolic, so one case covers every
register pair. The other seven (illegal, Bcc, SETcc, the four Jcc
routines) are a cube with a few parcels taken out, and carry their
membership as a hypothesis.

### 2. The hardware side

The netlist is the one the chip-level simulator runs, built by
`studies/v1b_hw/cpu.py`. [symsim.py](../studies/formal/symsim.py) runs
it a clock cycle at a time, with values that are either known or z3
terms:

- **A model per part:** the 22 kinds of chip in the netlist, from gates
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
  selects. It also means a loop in the netlist that the control breaks is
  never entered: the A bus feeds the immediate unit's fill bit, which
  feeds the B bus, which the bridge can put on the A bus.
- **Three-state buses:** a net takes the value of the driver that is
  enabled. Two that may be enabled at once are a contention; when the
  enables are symbolic, that is an obligation for the solver to prove
  impossible. With no driver enabled the net floats: a fresh variable,
  so nothing that depends on it can be proven.
- **Memories as z3 arrays,** from 15-bit (register file) or 19-bit (RAM)
  addresses to bytes.

**Case splitting.** A ROM's address must be known. When a symbolic bit
reaches one, the cycle stops. The solver is asked whether the bit can be
0 and whether it can be 1 under the path so far. If only one is
possible, that becomes a fact. If both are, the run splits, one path for
each, and the cycle runs again. In 1b the control store's address takes
the branch condition, the indexed mode's dispatch on its extension
parcel, the address-error fault and the interrupt request, so those are
where paths split. Everything else (the operands, the addresses, the
register numbers) stays symbolic data. The heuristic is that the
microcode's control is concrete and the datapath symbolic, which is
what a microcoded machine is built around.

The simulator was checked on known values against the RTL model
(`studies/v1b_hw/rtl.py`), the reference the netlist was built from. Every
register, flag and both register file copies agree after every cycle: on
`hello` to the end, and on the first 200,000 cycles of the exercise
program, which covers every instruction class.

### 3. The specification side

The instruction set is written in a small language made for it,
described in [language.md](../studies/formal/language.md):
[v1b.isa](../studies/formal/v1b.isa) is draft 1b in about 550 lines,
mostly comments. It reads like RFC 0004's tables made precise: the state,
then the addressing modes, then each instruction with its encoding.

```
instruction "ADD rd, ea"  0100 dddd mmmm nnnn:
    let x = source(m, n)
    r[d] := add(r[d], x, 0)

# a + b + carry in, setting all four flags. C is the carry out, so after a
# subtraction (a + ~b + 1) it means "no borrow".
fn add(a, b, cin):
    let sum = zext(a, 33) + zext(b, 33) + zext(cin, 33)
    let x = sum[31:0]
    C := sum[32]
    V := a[31] == b[31] and x[31] != a[31]
    return nz(x)
```

Values are bit vectors; a bare number takes the width of what it meets.
An instruction is its syntax, its encoding (`dddd` binds a field) and its
body. `fault v` abandons the instruction and enters a vector, and
`assume c "why"` marks what the specification leaves out: the I/O
page's registers, accesses outside RAM, a misaligned stack while entering
a fault. Each is a case where the simulator stops or does something the
specification doesn't describe.

The interpreter runs a specification on known values or on z3 terms,
without forking. A statement whose condition isn't known runs under a
guard, so a change becomes "if guard then new else old", and one pass
gives the next state for every path at once.

It was checked against the instruction-level simulator: random states and
random instructions, one step each, everything compared. That is
registers, flags, PC, every byte of memory, faults and their stack
frames. In 100,000 cases, which ran every instruction and every kind of
fault, the two never disagreed. Writing it found one place where the
order of effects matters and RFC 0004 doesn't say what it is: an ALU
operation on an auto-incrementing operand reads `rd` *after* the
increment (`ADD r1, [r1]+` adds the incremented r1), while a store
reads it before.

### 4. Joining them

For each decode case both sides start from the same symbolic values:
registers, flags, PC, memory and the parcel. The specification runs
first, and the conditions under which its `assume`s hold become
hypotheses. The hardware then explores its paths under them. At the end
of each path the goals are:

- the register file's two copies are equal at all 32 entries;
- `r1`–`r15`, `hi`, `r0` = 0 and the loop counts are as the abstraction
  says;
- the flags agree;
- the RAM is the specification's memory;
- the hardware's PC is `pc + 2`, and IR holds the parcel at `pc`;
- no address error in the decode cycle;
- the specification halts exactly when the hardware does;
- no contention, and no access to the I/O page.

**Making the two sides' terms meet.** The first version gave the
specification's registers as a list and read `r[d]` through a 16-way
`if` chain, while the hardware read a z3 array. Proving ADD with
symbolic register numbers took 57 seconds. Giving the specification's
register file the hardware's shape made a register read the same term on
both sides: four byte-wide arrays, 15-bit addresses, the same
simplified index term. The solver then only has to prove the adders
equal, and ADD took 6.6 seconds. Memory was given the same treatment
from the start: the specification's bytes live in the hardware's two RAM
chips' arrays.

The goals are proved a group at a time (registers, copies, flags,
memory, control, obligations), each under the path's conditions, after
z3's simplifier has removed the ones that are already equal as terms.
One query for all fifteen registers is several times faster than fifteen
queries, since the solver proves the written value once.

### 5. What is trusted

A proof here is only as good as what it stands on:

- **The part models.** symsim's models are a second implementation of
  hwsim's, checked against the RTL model on known values (section 2),
  not proved equal to hwsim's.
- **Cycles, not time.** The proof is about the netlist's function at the
  level of clock cycles. That every signal settles within the cycle is
  static timing analysis's business (`heron v1b_hw hw sta`).
- **The specification.** It is checked against the simulator by testing,
  not proved equal to it.
- **What is left out:** interrupts (IRQ held low), the I/O page, and
  HALT's waiting for an interrupt.
- **z3**, and the Python around it.

## Part II: Findings

### 6. Results

RESULTS

### 7. What the microcode relies on

The abstraction in [section 1](#1-what-is-proved) is the list of what
the microcode assumes at an instruction boundary. Writing it down was
part of the work, since a proof fails until it is complete, and some of
it isn't written anywhere else:

- **The loop counts are sign-extended.** Register file entries 24 and 25
  hold the counts the multiply, divide and shift loops start from. The
  reset routine writes them as the signed bytes −31 and −32, so they are
  `0xFFFFFFE1` and `0xFFFFFFE0`, not the `0xE1` and `0xE0` of
  `ucode.RF_CONSTS`. Only their low byte is ever loaded into LC, so it
  doesn't matter, but the first reset proof failed on it.
- **Both register file copies must agree, and reset doesn't make them.**
  The A copy feeds the A bus and the B copy the B bus, so `ADD r1, r1`
  adds one copy's r1 to the other's. Every write goes to both copies.
  But reset writes only r0, HI and the two loop counts. Until a program
  writes r1–r15, their two copies hold whatever the RAMs powered up
  with, and an instruction that reads one of them on both buses sees two
  different values. The instruction-level simulator starts with every
  register 0, and so do the chip-level runs (`zero_regs`), so no test
  can see it. Either RFC 0004 says the registers are undefined after
  reset and programs mustn't read them before writing them, or the reset
  routine clears r1–r15: 15 more cycles at reset.
- **The rest is as expected:** entry 0 holds 0, entry 16 is HI, no
  interrupt is pending, and the scratch entries (17 is `TMP1`) are
  written before they are read. Nothing else carries over from one
  instruction to the next. R, T, MAR, MQ, LC and the condition latches
  can be anything at a boundary.

### 8. What it costs, and what made it cheaper

COSTS

### 9. Breaking the hardware on purpose

MUTANTS

### 10. Draft 2

The draft 2 CPU ([RFC 0031](0031-rfc-draft-2-cpu.md), on its branch) is
the design this would matter for. Most of the method carries over:

- the specification language: RFC 0028's instruction set can be written
  in it as it is, and checked against draft 2's simulator the same way;
- symsim's models of the parts the two netlists share, and the splitting
  at the control store's address. The control store and the decode
  table are SRAMs there, which the I/O processor fills at boot; with the
  boot image's contents they are ROMs to the proof;
- decode cases, cut-points, proving goals in groups.

What doesn't:

- **Phases within a cycle.** Draft 2's cycle is 4 to 19 ticks of a
  50 MHz clock. The register file is read through transparent latches
  (74F573) and written in the last tick; T loads through latches late in
  the cycle; the memory write window opens at tick 4. 1b's two phases
  (write window, then edge) aren't enough. The simulator would need
  either a sequence of phases per microcycle, with latch models, or a
  step per tick with the clock generator itself in the netlist (its tick
  counter, the length classes from the uIR). The second proves the clock
  generator too, and costs more steps, each cheap.
- **The prefetch queue.** At an instruction boundary the queue holds
  some parcels ahead of the PC, depending on what came before. The
  abstraction must say that what it holds is memory at FPC, and the
  cases split on how full it is.
- **The system architecture.** The page map, supervisor mode, the fault
  registers and forced microcode entries are in RFC 0029. The
  specification must have them, and translation adds splits (a page
  fault or not) and array reads (the map) to every access.
- **Size:** 456 parts against 1b's 216, with eight kinds 1b's netlist
  doesn't use: the 573 latches, the 574 registers, a 74x109, a 138
  decoder, a 163 counter, and the oscillator, power-on reset and pull-ups
  of a card that makes its own clock.

None of this looks out of reach, and the multiply and divide will be as
hard as 1b's. The specification is useful on its own and the cheapest
step: written in this language and checked against the simulator, it
makes RFC 0028 executable and precise. On 1b, writing it found one
question RFC 0004 doesn't answer ([3](#3-the-specification-side)).

### 11. What next

NEXT
