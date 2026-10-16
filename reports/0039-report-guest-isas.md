---
number: 39
type: report
title: Other instruction sets in draft 2's microcode store
status: draft
date: 2026-10-16
context:
  studies: [v2_guests, v2_hw, v2_isa, v1_isa, c_compiler]
  commit: a5e63f3
---

# Report 0039: Other instruction sets in draft 2's microcode store

Draft 2's CPU ([RFC 0031](0031-rfc-draft-2-cpu.md)) has a writable control
store and a decode table in RAM, which the I/O processor fills at boot.
So it can be given another instruction set's microcode. How hard is that,
which instruction sets work, which don't, and what small design changes
would make the rest work? And could user processes run different
instruction sets on one machine?

The study ([studies/v2_guests](../studies/v2_guests/README.md)) wrote
microcode for four instruction sets and ran real programs with it on
RFC 0031's register-transfer model:

- **RV32IM**: the C program suite compiled by clang;
- **the 6502**: Klaus Dormann's functional test, decimal mode included,
  and the suite's C compiled by cc65;
- **draft 1b**: its own binaries, the hand-written suite and its
  compiled C;
- **Thumb** (ARMv6-M, the Cortex-M0's): the suite's C compiled by clang.

Every guest has a reference interpreter, and the programs run in
lockstep with it, every register compared after every instruction (1b's
reference is the v1_isa study's simulator). Then it tried three design
changes in a variant of the model, and built a machine on which a
draft 2 kernel time-slices user processes in draft 2 and in Thumb.

Times are the model's: draft 2's cycles with its length classes (4, 5, 6
and 9 ticks of 20 ns), as [RFC 0031's performance.md](0031-rfc-draft-2-cpu/performance.md)
measures native code. The tables are generated:
[performance.md](0039-report-guest-isas/performance.md), by
`heron v2_guests bench --write`.

## Summary

1. **Three instruction sets run on the CPU as it is, with nothing changed
   but the contents of the control store and the decode table.** RV32IM
   runs every C program right, at 9.9 cycles an instruction: 3.7 times
   native draft 2's time for the same programs. The 6502 passes the
   functional test, 30.6 million instructions in 15.4 s, about 2 million
   instructions a second. Draft 1b's binaries run as they are, all 35
   programs, at 1.14 times draft 2's own time (1.16 for compiled C), and
   1.18 times faster than draft 1b's own fast hardware.
2. **Thumb needs one small change, and then runs nearly at native speed.**
   With D1, a decode table that also gives the instruction register to
   load and an immediate, Thumb runs at 2.4 cycles an instruction, each
   in about the time of a draft 2 instruction; it takes 2.6 times draft
   2's time because it executes 2.7 times as many instructions for the
   same C. D1 is two more 64K × 16 SRAMs beside the decode table, a
   16-bit register and its B-bus drivers, and no control bits.
3. **What decides how well a guest fits is where its register numbers
   are.** Draft 2 addresses the register file by IR[15:12], IR[11:8], the
   counter SX (loaded from a nibble of IR or of the head parcel) or a
   constant in the microinstruction. The decode table sees the whole first
   parcel, so a field there can become a constant by giving every value
   its own routine, which is how 1b fits. A register field anywhere else,
   or a third one, costs cycles on every access: RV32's five-bit fields,
   two of them in the second parcel, make every register a register-file
   bank, and that is most of its 9.9 cycles.
4. **The control store's reach is the other limit.** The sequencer
   reaches 8K words of the 64K store. 1b takes 7,856 of them, after its
   loops and dispatch tables were shared to get it from 14,275; draft 2's
   own microcode is 6,235, Thumb's 4,770, RV32's 2,931, the 6502's 795.
   No guest fits beside draft 2's own but the 6502. D3, a 16-bit NEXT
   field, reaches all 64K, and takes the control word's three spare bits.
5. **User processes in different instruction sets work, with two more
   small changes.** D2 adds two status-word bits that select the decode
   table's page; RTI loads them, and exception entry clears them, so the
   kernel always runs draft 2. With D1, D2 and D3, a draft 2 kernel
   of 190 instructions runs a draft 2 process and two compiled Thumb programs, each in
   its own context and bank, switching on the timer and mapping their
   stacks and heaps on demand, and every output is right. The kernel
   doesn't know what instruction set a process runs except to print it:
   a context switch is the same for all of them.
6. **A guest that shares the machine has to follow draft 2's conventions:**
   its registers in the bank's locations 0-15, its scratch draft 2's
   scratch, its constants in the two global locations draft 2 leaves free
   (or in KONST), its system calls draft 2's `SWI`, its faults draft 2's,
   and every instruction restartable after a fault, writing no register
   before its last memory access. Thumb needed four small changes for it
   (one more cycle on `PUSH`); RV32 (all 256 banks), the 6502 (21 global
   constants) and 1b (32 banks of condition tables) couldn't share as they
   are.
7. **Byte-granular instruction sets work by keeping every byte twice.**
   Draft 2 fetches and decodes 16-bit parcels at even addresses. If parcel
   *a* holds guest byte *a* with byte *a* + 1 beside it, the 6502's PC is
   the native PC halved, the decode table sees the opcode and its first
   operand, and a 16-bit operand at any address is one read; a store
   writes two parcels. The same would work for the 8080, Z80 and 8086
   and for bytecodes.
8. **On paper** ([5](#5-other-instruction-sets-on-paper)): MSP430 fits
   draft 2 nearly as it is (its source register is at IR[11:8]); the
   PDP-11 and the 68000 work like Thumb, with D1 (the 68000 also with D3
   and byte-swapped memory); the Z80 and the 8086 like the 6502; AVR and
   ARM's A32 like RV32, slowly; the VAX is possible and not worth it; 64-bit
   instruction sets aren't.

## 1. How a guest is made

A guest is microcode written with draft 2's own microcode assembler
(`studies/v2_hw/ucode.py`: microinstructions, chains, branches, dispatch
tables), placed by draft 2's placer, and timed by its timing model. It
gives:

- **the decode table:** for each of the 65,536 first parcels, a routine
  and the instruction's length in parcels. The guest classifies each
  parcel into a key; every distinct key is a routine. This is where the
  guest's encoding is decoded, for free, once, at boot;
- **the routines;**
- **the forced entries** at draft 2's fixed addresses: the refill (which
  fetches and decodes, as draft 2's), the interrupt, trace and fault
  entries;
- **a reset routine** at address 0, and data the I/O processor writes to
  RAM for it to copy into the register file (tables, constants);
- **a reference interpreter** and a way to read the guest's registers from
  the model, for the lockstep check.

Everything else is draft 2's as it is: the prefetch queue, parcels,
the decode and its 16-way dispatch on the head parcel, the immediate
unit's fields, the register file with its 256 banks of 32 locations and
32 global ones, the ALU, the shifter (by 1, 8 or 16), the multiply and
divide steps, the condition latch, the flags with N from bit 7, 15 or
31, the page map, the bus. The cycle lengths are draft 2's length
classes, chosen for its own microcode; the guests' microinstructions
take their lengths from the static timing analysis where draft 2 has the
same word, and from the timing model's datasheet estimate otherwise.

The guests run on the model, not on the netlist: nothing here has been
checked at chip level.

## 2. The guests

### 2.1 RV32IM, unmodified

RISC-V's 32-bit instructions are two parcels at 4-byte boundaries, so the
fetch works and the decode table sees the first one:

    P1:  15 rs1[0] | 14-12 funct3 | 11-7 rd | 6-0 opcode
    P2:  15-9 funct7 | 8-4 rs2 | 3-0 rs1[4:1]

Nothing about the registers fits. The fields are five bits; two are in
the second parcel, where only SX and the dispatch can look; and an
instruction names three registers. So **every register is a bank**:
x*n* is location 0 of bank *n*. The ALU computes a register number into
BANK, and the next cycle reads that bank (UBR) or writes it (UBW): one
register a cycle, two cycles an operand.

**Fields of the second parcel come from tables in the register file.**
The register file is 256 banks of 32 locations, so location L across the
banks is a 256-entry table indexed by BANK. A byte of P2 into BANK and
one read gives rs2, a slice of an immediate, or LC for a shift, in two
cycles, where a shift would take four or five. The I/O processor puts
the tables in RAM, and the reset routine copies them. The decode table
gives the rest: routines are specialised on rd's and rs1's low bits and
the S- and B-immediates' low bits, which are in P1. RISC-V has no flags,
so draft 2's flags and condition latch are the microcode's scratch; a
branch uses the native branch condition where P1's IR[15:12] happens to be
the right condition code (BEQ, BNE, BLT and BGE when rs1 is even).

The result: all 15 programs right, 9.9 cycles an instruction, 3.7 times
native draft 2 (which executes 6% fewer instructions for the same C).
Where the cycles go, over the 14 programs:

| Instructions | Executed | Share | Cycles each | Share of the cycles | Estimated, with the lookup and SX from B |
|---|---:|---:|---:|---:|---:|
| `MUL` ... `REMU` | 27,386 | 2.1% | 87.1 | 18.8% | 84.1 |
| shifts by a constant (`SLLI` ...) | 115,952 | 9.1% | 19.0 | 17.4% | 17.0 |
| ALU with an immediate (`ADDI` ...) | 313,452 | 24.6% | 6.5 | 16.0% | 3.0 |
| loads | 203,043 | 15.9% | 8.6 | 13.7% | 3.5 |
| ALU, two registers (`ADD` ...) | 294,802 | 23.1% | 5.9 | 13.7% | 3.0 |
| branches | 151,593 | 11.9% | 8.4 | 10.1% | 5.0 |
| stores | 115,197 | 9.0% | 7.2 | 6.6% | 5.0 |
| `JAL`, `JALR` | 33,331 | 2.6% | 8.2 | 2.2% | 4.0 |
| `LUI`, `AUIPC` | 19,259 | 1.5% | 3.4 | 0.5% | 3.4 |
| shifts by a register | 315 | 0.0% | 46.0 | 0.1% | 46.0 |
| the refills after jumps | | | | 0.9% | |
| **all** | 1,274,344 | | **9.93** | | |

Multiply and divide are loops of 32 steps, as draft 2's own are. Then
the shifts: a shift by *n* is *n* one-place steps, 19 cycles for the
average one, because the amount is in P2, where the decode table can't
specialise on it and the 8- and 16-place steps can't be chosen without
testing it. Everything else is getting register numbers and immediates
out of P2: an `ADD` is six cycles, where draft 2's is one or two.

### 2.2 The 6502, unmodified

The 6502's instructions are one to three bytes at any address. **Every
guest byte is kept twice:** the halfword at native address PB + 2*a* holds
P[*a*] = byte *a* | byte *a* + 1 << 8. Then:

- the native PC is PB + 2 × the 6502's PC, and the fetch, the prefetch
  queue and the decode table work as they are: the parcel at the PC is
  {next byte, opcode}, and consuming a parcel moves the 6502 on one byte;
- the decode table sees the opcode and its first operand byte;
- after the decode, the head parcel is the instruction's 16-bit operand,
  already put together, and the immediate unit gives its first byte
  doubled and sign-extended, a branch offset or a zero-page address × 2;
- a 16-bit read at any address (zero-page pointers, `JMP (ind)`, the
  return address) is one aligned halfword read;
- a store writes two halfwords (P[*a*]'s low byte and P[*a* − 1]'s high
  byte), the price of all this.

The page map makes the address arithmetic free: the 128 KB are mapped at
PB and the upper half again below PB, so that an operand sign-extended by
the immediate unit, or a sum of an index register and an operand up to
0x100FF, needs no masking, and code runs on from 0xFFFF to 0. A, X, Y and
S are bank locations; N, Z and C are the CPU's own flags (N from bit 7,
C from bit 8 or the ALU's carry, whose sense for SBC and CMP is the
6502's); V comes from doing ADC and SBC in the top byte, where the ALU's
overflow is the 6502's. Decimal mode is a microcode correction step.

Klaus Dormann's functional test (every documented instruction and mode,
with flags, decimal mode included) passes in lockstep with the reference
interpreter: 30,646,177 instructions in 150 million cycles, 4.9 cycles an
instruction, 15.4 s; about 2 million 6502 instructions a second, which a
real 6502, at three or four cycles an instruction, does at 6 to 8 MHz.
The suite's C, compiled by cc65 with its 16-bit `int`, runs right too
(the eight programs whose output doesn't depend on 32-bit arithmetic
print the suite's output); the microcode is 795 words.

### 2.3 Draft 1b, unmodified

1b's instructions are 16-bit parcels too, and its main format is
`F D M R`: operation, register, mode, and the mode's register or constant.
1b's D is at IR[11:8], draft 2's `r` selector, so it is read and written as
it is. The mode and its register are seen only by the decode table, so
**every routine is specialised on them**: one routine for each operation,
mode and register, 7,502 of them. That fills the control store: 14,275
microinstructions at first, 7,856 of the 8,192 the sequencer reaches once
the multiply, divide and shift loops were shared between routines, the
indexed modes' dispatch tables were shared (with their own copies of the
trap), and the calls shared a tail. SETcc's condition is in IR[7:4],
where the branch-condition logic doesn't look: a table in the register
file (the bank named by the flags byte, location 17 + cc) gives the
answer in two cycles.

All 35 programs (20 hand-written, 15 compiled) run right, in lockstep
with draft 1's simulator, but `interrupts`, whose timer interrupts arrive
at other instructions than the simulator's and which is checked by its
output. On the 18 hand-written programs report 0031 compares, 1b's
binaries take 1.14 times the time of draft 2's own versions (the
compiled C, 1.16 times draft 2's compiled C), and on the 13 that don't
print, 1.18 times less than draft 1b's own fast system
([RFC 0024](0024-rfc-faster-smaller/results.md#the-fast-system)). So
draft 2's CPU could carry 1b's software with it, if that were wanted.

### 2.4 Thumb, with D1

Thumb is the instruction set closest to draft 2's datapath: 16-bit
parcels, little-endian, 32-bit registers, aligned accesses, and flags N,
Z, C, V with the same sense and ARM's condition codes, which are draft 2's.
What doesn't fit is where the fields are: three-bit register numbers at
bits 2-0, 5-3 and 8-6, and immediates of 3, 5, 7, 8 and 11 bits.

**D1** gives the decode table two more 16-bit halves: the IR to load, so
that the destination is at IR[15:12] and a source at IR[11:8], where the
selectors `d` and `r` look (a third register is a constant of the
routine), and the instruction's immediate, already shifted, scaled and
offset as the routine wants it, which BX = 6 (a free code) puts on the
B bus. Then most Thumb instructions are one or two cycles, as draft 2's
are: 2.4 cycles an instruction, 245 ns against draft 2's 257 ns for the
same programs. It takes 2.6 times draft 2's time because Thumb needs 2.7
times as many instructions for the same C: Cortex-M0 code has eight
registers for most things, two-address arithmetic, no scaled or
displaced indexed modes, and short immediates.

Without D1, Thumb would be done as RV32 is, through BANK, at some 6 to 8
cycles an instruction.

## 3. Design changes

Built in the model (`studies/v2_guests/rtlx.py`, a copy of the RTL
model's step with each change marked; with none in use it is draft 2's,
cycle for cycle):

| Change | What | Cost | Who needs it |
|---|---|---|---|
| **D1** a wider decode table | for each first parcel, also the IR to load and a 16-bit immediate (sign-extended, on B by BX = 6) | two 64K × 16 SRAMs, a 16-bit register, B-bus drivers, a mux on the IR's input; no control bits | Thumb (2.4 cycles an instruction against RV32-like 6-8), and on paper the PDP-11 and 68000 |
| **D2** decode table pages | two status-word bits (9-8, ISA) extend the decode table's address, and D1's; RTI loads them, exception entry clears them | 256K-deep decode SRAMs (or four times as many), two flip-flops | user processes in different instruction sets |
| **D3** a 64K-word reachable control store | NEXT 16 bits wide; decode entries stay 13 bits, so routines start in the first 8K and continue anywhere | the control word's three spare bits, three more bits of next-address path | draft 2 beside any guest but the 6502; the 68000, the 8086, the VAX on paper |

Not built, with what they would buy:

| Change | What it would buy | Cost |
|---|---|---|
| A lookup table on the head parcel, on the B bus | RV32's rs1, rs2 and immediates in one cycle each, from the second parcel | a 256K × 16 SRAM, two or three control bits |
| SX loaded from the B bus, five bits wide | a register number the microcode computes addresses the bank directly: 32 registers in one bank, for RV32 and AVR | a mux on SX's input and a fifth bit, one control bit |
| A shift by a count from a register or the head parcel | RV32's and every guest's variable shifts (RV32's biggest cost); also graphics | a barrel shifter, or a rotate by 0-7 beside the byte rotations (RFC 0007's barrel shifter) |

With the first two, and rd as a constant of the routine (the decode
table sees it), an RV32 register-register operation would be three cycles
(SX ← rs1; R ← x[rs1], SX ← rs2, consume; x[rd] ← R op x[rs2] and decode),
an immediate one three, a load three or four, a store five, a branch
about five (the last column of the table in [2.1](#21-rv32im-unmodified)).
By the instruction mix, that is an estimated 6.6 cycles an instruction
against 9.9, with the shifts and multiplies as they are, or about 2.5
times native draft 2's time; with shifts by a count in three cycles, 5.4,
about twice native. Together
they need five or six more control bits, which with D3 means a wider
control word: one more byte-wide SRAM and register.

## 4. User processes in other instruction sets

The mixed machine (`studies/v2_guests/mixed.py`) puts draft 2's microcode
and Thumb's in one control store, 10,958 words up to 0x3A13 (D3), with a
decode table page each (D2) and Thumb's D1 halves on its page. A kernel
in draft 2 code (`sw/mixed/kernel.s`) runs in supervisor mode, in the
window; each process has a context of the page map and a register bank,
its image mapped from 0, a console card of its own mapped at 0xFFF000,
and its bss, heap and stack mapped by the kernel's page-fault handler as
they are touched. The timer switches processes round robin; `SWI #0`
(Thumb's `SVC #0`) ends one.

Draft 2's sieve (hand-written) and Thumb's compiled `queens` and
`wordfreq` run together, about 40 time slices between them, and each
prints what it should (the run is in
[performance.md](0039-report-guest-isas/performance.md#the-mixed-machine)).

What it takes:

- **The decode page goes with the status word.** That is all the CPU
  needs to know about a process's instruction set: RTI into a process
  loads it with the flags, an interrupt or a fault saves it in the pushed
  status word and clears it. The kernel's context switch is the same for
  every process; it reads the bits only to print the process's ISA.
- **The registers stay where draft 2's are.** Thumb's r0-r14 are the
  bank's locations 0-14, so `MFUR`, `MTUR` and the kernel's switch handle
  them as they are; its PC is draft 2's PC and its flags draft 2's.
- **The register file's global locations are draft 2's.** Its microcode
  uses 30 of the 32 for scratch, constants and special registers; Thumb's
  two constants went into the other two, and its other constants into
  KONST (one more cycle on `LDRSB`). The 6502 uses 21 global constants,
  which beside draft 2 would have to move into the process's bank
  (locations 16-31); RV32's registers use all 256 banks, and 1b's
  condition tables 32 of them, so neither could share the machine as it
  is (RV32 could, with SX from the B bus).
- **Traps are draft 2's.** Thumb's `SVC #n` is draft 2's `SWI #n` (its
  microcode jumps into draft 2's trap routine), its undefined encodings
  the illegal-instruction trap; faults go to draft 2's fault entries,
  which save the faulting instruction's own address.
- **Every guest instruction must be restartable** after a page fault:
  no register written before the last memory access. Thumb's `PUSH`
  wrote SP first; it now writes it after its stores, one cycle more. The
  test makes a `PUSH` fault on an unmapped stack page, and it runs again
  right. (`LDM` with its base register in the list can still clobber the
  base before a later load faults, as on ARM, where the base is
  restored; not handled.)

One snag is not the design's: draft 2's tools in this tree have moved on
since the v2_hw microcode was written (RFC 0028's new row 0, RFC 0029's
special register numbers, HI and LO as r0 and r1). The mixed machine's
draft 2 page maps the new row 0 onto the old routines (the decode table is
RAM, so it can), and its draft 2 code uses no multiply or divide. Once
the microcode follows RFC 0028, the mapping is an identity and the
draft 2 process can be compiled C.

## 5. Other instruction sets, on paper

| Instruction set | Verdict | Why |
|---|---|---|
| MSP430 | works unmodified, close to native | 16-bit parcels; the source register is at IR[11:8], draft 2's `r`; the destination (3-0) a constant of the routine: some 3,000 routines, most one or two cycles; word and byte operations' flags from bit 15 and 7 are draft 2's own N selection and carry sources. 16-bit `int` C, as cc65's |
| RV32C | works as RV32 does | the compressed formats' three-bit registers at 4-2 and 9-7, in the first parcel: specialised as 1b's are |
| PDP-11 | works with D1 | 16-bit words, eight registers in three-bit fields at 8-6 and 2-0 with their modes beside them; D1 moves the registers to `d` and `r`, leaving 64 mode pairs per operation; byte and word flags as for MSP430 |
| 68000 | works with D1 and D3, and byte-swapped memory | 16 registers in three-bit fields (with D/A from the opcode): D1; MOVE alone is 3 sizes × 12 × 9 modes: D3; big-endian: memory swapped within halfwords, so fetch and word accesses work, a long is one rotate by 16, and a byte address is flipped (one cycle). The brief extension word's index register is at its bits 15-12, where draft 2's SX can load it from the head parcel |
| Z80, 8080 | works unmodified, as the 6502 | doubled memory; prefix and opcode seen together by the decode table; parity and half-carry from tables in the register file |
| 8086 (real mode) | works unmodified, as the 6502; a big job | doubled memory gives opcode and ModRM to the decode table, and a 16-bit access at any address in one read; segments are an add per access; prefixes need a re-decode; probably more than 8K words: D3 |
| AVR | works as RV32 does, slowly | five-bit register fields, scattered; with SX from the B bus, better |
| ARM A32 | works as RV32 does, slowly | Rn in the second parcel, a condition on every instruction, shifted operands everywhere: the head-parcel lookup and a barrel shifter would be wanted |
| VAX | possible, not worth it | byte-granular (doubled memory), an operand specifier per operand decoded one at a time, hundreds of opcodes: D3 and slow |
| JVM, WebAssembly, other bytecodes | work unmodified, as the 6502 | byte-coded; the stack's top in registers; a few hundred routines |
| 64-bit (RV64, ARM64, x86-64) | not worth it | every register and operation doubled on a 32-bit datapath |

## 6. What the study didn't do

- The guests run on the register-transfer model only; the netlist hasn't
  run them, and their microinstructions' lengths are the timing model's
  where the static timing analysis hasn't measured the same word.
- The guests implement what their programs need: RV32IM without CSRs
  or `FENCE.I`, Thumb without the system registers and exception model of
  ARMv6-M, the 6502 without its own interrupts (`BRK` and `RTI` are
  there), 1b with its interrupts and traps.
- The design changes not built (the head-parcel lookup, SX from the B
  bus, shifts by a count) are estimates.
- The 68000 guest was planned and not written: on paper it is the
  clearest case for D1 and D3 together, and the next one to build.
