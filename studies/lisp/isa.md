# v1bx: draft 1b with a tagged register mode

An experiment, not a proposal for draft 1b as it stands: draft 1b plus
one addressing mode, to measure what checking integer tags in hardware
is worth to the Lisp. The findings are in
[report 0016](../../reports/0016-report-lisp.md).

Everything not mentioned here is draft 1b
([isa-v1b.md](../v1_isa/isa-v1b.md)). The instruction-level simulator runs
it as the ISA `v1bx` (`studies/v1_isa/isa`, `Isa::V1bx`). The runtime is
assembled as 1b and doesn't use the new mode; the compiler writes it when
it's built with the feature `tagged` (`heron lisp run -c --features
tagged`, `heron lisp test -c --features tagged`).

## Mode E: a tagged register

Draft 1b reserves mode E. In v1bx it is the register `R`, as mode 0, with
a check that both operands are integers in the Lisp's representation
(bit 0 clear):

| Instruction | Does | Traps if |
|---|---|---|
| `MOV.T rd, rs` (`1 d E s`) | `rd ← rs`, sets N and Z | bit 0 of `rs` is set |
| `ADD.T rd, rs` (`4 d E s`) | `rd ← rd + rs`, flags as `ADD` | bit 0 of `rd` or `rs` is set, or the sum overflows |
| `SUB.T rd, rs` (`5 d E s`) | `rd ← rd − rs`, flags as `SUB` | as `ADD.T` |
| `CMP.T rd, rs` (`6 d E s`) | flags of `rd − rs` | bit 0 of `rd` or `rs` is set |
| `AND.T`, `OR.T`, `XOR.T` (`7`–`9 d E s`) | as the plain operation | bit 0 of `rd` or `rs` is set |

`ST`, `LEA`, `JMP` and `CALL` with mode E are illegal instructions, as in
1b. `r0` reads as zero, which is an integer, so `CMP.T r1, r0` checks `r1`
and compares it with 0 (the compiler's `zero?`), and `MOV.T r9, r1` only
checks `r1`.

The trap goes through a new vector, **`0x18`** (after the address error
at `0x14`). It's taken before anything is written, like an address error:
the saved PC is the instruction's own address, and the flags and the
registers are as they were. The handler decodes the instruction to tell
the two cases apart and to find the irritant (`trap_tag` in
[rt/start.s](rt/start.s)): if both operands are integers, an `ADD` or
`SUB` overflowed.

## What the compiler does with it

Without the mode, `(+ a b)` on two values in `r1` and `r3` is

```
        MOV  r9, r1             ; r1 an integer?
        AND  r9, #1
        BNE  not_a_number
        MOV  r9, r3             ; r3 an integer?
        AND  r9, #1
        BNE  not_a_number
        ADD  r1, r3
        BVS  overflow
```

and with it, `ADD.T r1, r3`. `(< a b)` becomes `CMP.T r1, r3` and a
branch, `(zero? a)` `CMP.T r1, r0`, and checking one operand (a vector
index, `(- a)`) `MOV.T r9, r1`.

## What it would cost

Not designed in hardware. On the 1b data path the check is an OR of bit 0
of the A and B buses (the B bus alone for `MOV`), and with the ALU's
overflow for `ADD` and `SUB`. The microcode's 3-bit condition field
(`COND`, [hardware.md](../v1b_hw/hardware.md)) is full, so the check
would go through the condition latch, which has a spare source. That is
about one chip of gates. A register ALU operation writes its result in
its second cycle, together with the next fetch; checking before the write
probably needs one more cycle, which the report counts both ways.
