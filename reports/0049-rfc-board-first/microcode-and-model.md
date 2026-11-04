# Reed: the microcode, the model, and the benchmark

Findings for [RFC 0049](../0049-rfc-board-first.md)'s section 14 (design
A, Reed), from writing the rest of the microcode and a model fast enough
to run whole programs on it (2026-11-04). The code is
[studies/reed](../../studies/reed/README.md): `ucode.py`, `model.py`,
`fuzz.py`.

## 1. The model

`model.py` runs the microcode's images a microcycle at a time with the
netlist's semantics, register for register: the µPC and the control
store's pipeline, the queue, the decode table, the immediates, PC and the
branch adder, the register file (written at the cycle's end, which the
bypass makes the same as the write phase of the next), the 181s exactly
as the chip-level simulator models them, the flags, MAR, MQ, FPC and the
RAM. A bus that two drivers drive, or that something reads while nothing
drives it, is an error.

It is in lockstep with the chip-level simulator: the µPC and PC agree on
every cycle of every test program (`heron reed hw lockstep`, and a unit
test). It runs about 150,000-270,000 microcycles a second, so a
benchmark workload at its full size (10 million instructions) takes a few
minutes.

## 2. What it found in the hardware

**The instruction queue had two bugs,** at chip level too: the four test
programs passed by luck.

- The decode pointer could come round to the executing instruction's
  parcels, still valid until it ended, and decode it again (two 2-parcel
  instructions in a row).
- A 2-parcel instruction executing with a 3-parcel one decoded wants five
  parcels of four. The old logic got past it only by reading a stale
  parcel that the right one was fetched over in time.

The fix: a parcel is held until it's consumed, an instruction's first as
it's decoded and an extension parcel by the word that takes it (CONS on
U_IQE), and AV marks the parcels still to decode, from which READY comes
(U_IQA, which also took U_IQR's FS: CTRL stays at 72 packages). A new
program, `queue`, covers it in the chip-level gate. Slots free sooner, so
the test loops got about 10% faster too.

**Three flag details,** each a GAL change that fits:

- MQSTEP's step without an add was the 181's logic-mode pass, whose carry
  out is garbage; the multiply's shift takes that carry in. It is now A
  in arithmetic mode, carry 0.
- FL code 1, reserved, is now a shift's: N and Z, C the bit shifted out
  (OA's bit 0 on the shift path, the carry out on a left shift), V 0.
- NSZ, two ALU bits: N and Z at the operand's size (bit 7 or 15; the low
  byte or half, U_ZL giving ZB), for a byte's `MOVS`, `INC` and `DEC`.

## 3. The microcode

10,100 words of the 16K, written by field (`ucode.py`): every EA row on
every mode, the indexed and the special modes, stores, `CLR`, `INC`,
`DEC`, `LEA`, `MOV`/`CMP #u7`, the unary row and `SETcc`, shifts by a
constant and by a register, `BIC`, `TST`, `MULU`, `MULS`, `DIVU`, `DIVS`,
branches, jumps and calls through any operand, `DBNZ`, `SAVE`,
`RESTORE`, `LDM` and `STM`. Not yet: `DIVUL`, `ADC`, `SBC`, `CLZ`, the
system instructions and the exceptions; those trap to `unimpl`, as does a
negative abs24 or d24 in the special mode's indexed forms.

`fuzz.py` checks it a random instruction at a time against draft 2's
simulator, registers, flags and memory: every family passes 400 cases
(`heron reed fuzz`, and a unit test with 40).

Three rules of the hardware shaped it:

- **A branch tests flags set two words before it,** not one: a word's
  successor is chosen while the word before it executes.
- **One K a word:** port A's K, port B's K and the write's K are the one
  field, so a word touches one microcode register. MQ serves as a second,
  B-side temporary.
- **No microcode subroutines:** a mode's address words are duplicated for
  every operation that uses them.

## 4. The benchmark

RFC 0050's twelve workloads all run on the model to `HALT` with their
expected output.

At the `tiny` size (about 90,000 instructions each; the full size's
numbers will replace these), microcycles as the microcode's lengths have
them today (5 or 6 ticks) and at the 7 ticks decided for now:

| Workload | Microcycles an instruction | As built | At 7 ticks | Full Heron (RFC 0050) |
|---|---:|---:|---:|---:|
| `m6502` | 4.63 | 514 ns | 643 ns | 198 ns |
| `gfx_desktop` | 3.07 | 349 ns | 427 ns | 273 ns |
| `gfx_sprites` | 3.81 | 431 ns | 529 ns | 225 ns |
| `forth` | 3.37 | 380 ns | 468 ns | 240 ns |
| `lisp` | 2.62 | 295 ns | 364 ns | 183 ns |
| `db` | 2.97 | 338 ns | 413 ns | 235 ns |
| `editor` | 4.42 | 488 ns | 615 ns | 208 ns |
| `rts` | 4.12 | 468 ns | 573 ns | 261 ns |
| `ttf` | 5.09 | 582 ns | 708 ns | 228 ns |
| `textutils` | 3.01 | 339 ns | 418 ns | 213 ns |
| `cc` | 3.52 | 401 ns | 490 ns | 225 ns |
| `inflate` | 3.90 | 438 ns | 542 ns | 223 ns |

Full Heron's column is its own model at `full`, the optimistic reference
point. The estimate (RFC 0049's `estimate.py` on each workload's mix)
had Reed at 250-320 ns at 6 ticks: the microcode as written takes 1.3-2x
that.

## 5. Where the time goes, and what would help

The microcycles by the instruction that spends them (the entry whose
words they are), the six largest per workload, at `tiny`:

| Workload | |
|---|---|
| `m6502` | `JMP [r + x]` 29%, `MOV` indexed 14%, WAITD 8%, store indexed 8% |
| `gfx_desktop` | WAITD 12%, `LSL r` 11%, `Bcc` 9%, `LSR r` 8%, `MOV` indexed 8%, `DBNZ` 6% |
| `gfx_sprites` | WAITD 15%, `DBNZ` 13%, `LSL r` 11%, `LSR r` 9%, `MOV` indexed 7% |
| `forth` | WAITD 20%, `Bcc` 10%, `JMP [r]+` 9%, `CALL d16` 5% |
| `lisp` | WAITD 21%, `Bcc` 16%, `MOV [r + d]` 7%, `J d16` 6% |
| `db` | `Bcc` 18%, WAITD 15%, `MULS r` 11%, `DIVU` 5% |
| `editor` | `MOV` indexed 16%, `CMP` indexed 13%, WAITD 12%, `Bcc` 10% |
| `rts` | WAITD 12%, `MULS #i32` 11%, `Bcc` 11%, `LEA` indexed 7% |
| `ttf` | `MULS r` 21%, `DIVS` 18%, WAITD 9%, `Bcc` 7% |
| `textutils` | `Bcc` 18%, WAITD 17%, `DIVU` 10%, `LEA` indexed 7% |
| `cc` | WAITD 17%, `Bcc` 13%, `DIVU` 9%, `MULS #s16` 6% |
| `inflate` | WAITD 12%, `LSL r` 11%, `LEA` indexed 10%, `Bcc` 10% |

WAITD is the queue empty: after a jump (the refill) or where memory
operands leave no word free to fetch.

- **The indexed modes** take 15-25 microcycles: the index parcel's scale
  and size are tested a bit at a time in the ALU (on ST, so that the
  flags stay), d8 sign-extended in three words, and the sum made through
  MQ, one K a word.
- **Shifts by a register** are a bit a microcycle, two words a bit in the
  loop.
- **Multiply and divide** are a bit at a time: about 70 microcycles for a
  `MULU`, 150-200 for a divide, and `MULS` and `DIVS` more for the
  signs.
- **A taken branch** is 4 microcycles and the refill after it.

## What I'd do

Each is a small piece of hardware, measured here before anything is
built. In the order I'd look at them:

1. **An index dispatch:** the index parcel's s and z bits as a multiway
   jump (or a second decode-table lookup of the parcel), and d8
   sign-extended as an immediate: the indexed modes from 15-25
   microcycles to about 3.
2. **The fetch:** a word fetched ahead whenever MEM is free, and the
   queue's refill after a jump overlapped with the jump's own words.
3. **Multiply and divide:** an early-out multiply (stop when MQ's
   remaining bits are 0), two bits a step, or both.
4. **Shifts:** a shift by a register unrolled through the decode of the
   count, or a byte-at-a-time path through the crossbar.
5. **A second K field,** so that a word can read a constant and write a
   temporary: most of the extra words in the indexed modes, `DIVS` and
   the shifts come from it.
