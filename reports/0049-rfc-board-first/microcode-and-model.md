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

At the `full` size (8-13 million instructions each, RFC 0050's quoted
size), microcycles as the microcode's lengths have them today (5 or 6
ticks) and at the 7 ticks decided for now:

| Workload | Instructions | Microcycles an instruction | As built | At 7 ticks | Full Heron (RFC 0050) |
|---|---:|---:|---:|---:|---:|
| `m6502` | 8,951,070 | 4.82 | 533 ns | 671 ns | 198 ns |
| `gfx_desktop` | 10,772,934 | 4.59 | 529 ns | 638 ns | 273 ns |
| `gfx_sprites` | 9,287,190 | 3.20 | 359 ns | 445 ns | 225 ns |
| `forth` | 7,800,917 | 3.61 | 407 ns | 502 ns | 240 ns |
| `lisp` | 11,110,590 | 2.61 | 294 ns | 363 ns | 183 ns |
| `db` | 11,406,860 | 3.96 | 456 ns | 550 ns | 235 ns |
| `editor` | 10,323,676 | 3.46 | 388 ns | 482 ns | 208 ns |
| `rts` | 7,940,685 | 5.17 | 587 ns | 718 ns | 261 ns |
| `ttf` | 9,314,093 | 3.83 | 436 ns | 532 ns | 228 ns |
| `textutils` | 11,100,385 | 3.48 | 397 ns | 484 ns | 213 ns |
| `cc` | 13,092,144 | 3.55 | 404 ns | 494 ns | 225 ns |
| `inflate` | 9,991,628 | 4.24 | 476 ns | 590 ns | 223 ns |

Full Heron's column is its own model, the optimistic reference point.
The estimate (`estimate.py`'s recipes on each workload's mix) had Reed
at 250-320 ns at 6 ticks: the microcode as written takes 1.2-2x that,
and the difference is the hardware gaps below, not the cycle.

## 5. Where the time goes, and what would help

The microcycles by the instruction that spends them (the entry whose
words they are), the largest per workload, at `full`:

| Workload | |
|---|---|
| `m6502` | `JMP [r + x]` 35%, `MOV` indexed 16%, store indexed 8%, WAITD 7% |
| `gfx_desktop` | `LSL r` 23%, `LSR r` 22%, WAITD 8%, `DBNZ` 8%, `MOV` indexed 5% |
| `gfx_sprites` | WAITD 24%, `DBNZ` 15%, `MOV [r]+` 9%, store `[r]+` 9% |
| `forth` | `JMP [r]+` (NEXT) 34%, WAITD 20%, `PUSH` 7%, `MOV [r]+` 6% |
| `lisp` | WAITD 21%, `Bcc` 16%, `MOV [r + d]` 8%, `J d16` 7% |
| `db` | `MULS r` 30%, `Bcc` 12%, WAITD 12%, `MULS #s16` 5% |
| `editor` | WAITD 15%, `Bcc` 14%, `MOV` indexed 12%, `CMP` indexed 7%, `DBNZ` 6% |
| `rts` | `MULS #s16` 19%, WAITD 9%, `LEA` indexed 8%, `MULS r` 8%, `DIVS` 7% |
| `ttf` | WAITD 12%, `Bcc` 11%, `MULS #s16` 11%, `MOV` indexed 6%, `MULS r` 6% |
| `textutils` | `MULS r` 23%, WAITD 15%, `Bcc` 14%, `LEA` indexed 4% |
| `cc` | WAITD 17%, `Bcc` 13%, `DIVU` 11%, `MULS #s16` 7%, `CALL d16` 6% |
| `inflate` | WAITD 12%, `LSL r` 10%, `LEA` indexed 10%, `Bcc` 8%, `DBNZ` 7% |

By kind, in %:

| Workload | register | memory operand | store, INC/DEC | branch | jump | call | refill | shift | multiply | divide |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `m6502` | 14 | 25 | 8 | 3 | 35 | 0 | 7 | 9 | 0 | 0 |
| `gfx_desktop` | 10 | 15 | 6 | 12 | 0 | 0 | 8 | 48 | 0 | 0 |
| `gfx_sprites` | 8 | 27 | 16 | 18 | 0 | 1 | 24 | 4 | 0 | 2 |
| `forth` | 5 | 18 | 9 | 2 | 34 | 5 | 20 | 1 | 3 | 3 |
| `lisp` | 14 | 24 | 8 | 23 | 4 | 5 | 21 | 2 | 0 | 0 |
| `db` | 13 | 14 | 3 | 14 | 1 | 3 | 12 | 1 | 35 | 3 |
| `editor` | 12 | 37 | 9 | 20 | 0 | 1 | 15 | 1 | 0 | 4 |
| `rts` | 10 | 27 | 4 | 8 | 1 | 1 | 9 | 6 | 28 | 7 |
| `ttf` | 11 | 23 | 7 | 12 | 1 | 2 | 12 | 11 | 18 | 5 |
| `textutils` | 17 | 19 | 3 | 16 | 1 | 3 | 15 | 1 | 23 | 1 |
| `cc` | 15 | 14 | 5 | 17 | 2 | 6 | 17 | 2 | 11 | 11 |
| `inflate` | 10 | 38 | 5 | 15 | 0 | 1 | 12 | 19 | 0 | 0 |

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
- **A taken branch** is 4 microcycles and the refill after it; a jump
  through memory (`JMP [r]+`, Forth's NEXT; a jump table) is the
  operand's words, the load into T0, the jump and its tail, then the
  refill.

## What I'd do

Each is a small piece of hardware, measured here before anything is
built. In the order I'd look at them:

1. **An index dispatch:** the index parcel's s and z bits as a multiway
   jump (or a second decode-table lookup of the parcel), and d8
   sign-extended as an immediate: the indexed modes from 15-25
   microcycles to about 3.
2. **The fetch:** a word fetched ahead whenever MEM is free, and the
   queue's refill after a jump overlapped with the jump's own words
   (WAITD is 7-24% everywhere); and a jump through memory with the load
   straight onto A for PC, a word less (microcode only).
3. **Multiply and divide:** an early-out multiply (stop when MQ's
   remaining bits are 0), two bits a step, or both: multiplies are
   18-35% of db, rts, ttf and textutils.
4. **Shifts:** shifts by a register are 48% of gfx_desktop. A shift by a
   register unrolled through a dispatch on the count, or a
   byte-at-a-time path through the crossbar.
5. **A second K field,** so that a word can read a constant and write a
   temporary: most of the extra words in the indexed modes, `DIVS` and
   the shifts come from it.
