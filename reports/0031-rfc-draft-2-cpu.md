---
number: 31
type: rfc
title: Draft 2's CPU
status: draft
date: 2026-10-16
context:
  studies: [v2_hw, v2_isa, v1b_hw, v1b_tradeoffs, c_compiler]
  commit: dd84baa
depends-on: [14, 24, 27, 28, 29]
---

# RFC 0031: Draft 2's CPU

A CPU card for draft 2: the instruction set of
[RFC 0028](0028-rfc-draft-2-isa.md) with the system architecture of
[RFC 0029](0029-rfc-draft-2-system.md), built on
[RFC 0024](0024-rfc-faster-smaller.md)'s advice. Part I is the
specification of its microarchitecture, with what isn't decided marked
**open**; Part II is where it comes from, what it measures and what's
left. The study is [studies/v2_hw](../studies/v2_hw/README.md): the
microcode, a register-transfer model checked against the instruction-level
simulator, a timing estimate, the boot through the I/O processor, and the
measurements in [performance.md](0031-rfc-draft-2-cpu/performance.md).

This is a first draft, written while the ISA and the system architecture
are still moving: there is no netlist yet, and its times come from a path
estimate rather than static timing analysis.

## Contents

- [Part I: Specification](#part-i-specification)
  - [1. Overview](#1-overview)
  - [2. Clock and cycles](#2-clock-and-cycles)
  - [3. Datapath](#3-datapath)
  - [4. Fetch and decode](#4-fetch-and-decode)
  - [5. Memory](#5-memory)
  - [6. The bus and the slave port](#6-the-bus-and-the-slave-port)
  - [7. The instruction cache (open)](#7-the-instruction-cache-open)
  - [8. The microinstruction and the sequencer](#8-the-microinstruction-and-the-sequencer)
  - [9. Exceptions, interrupts and trace](#9-exceptions-interrupts-and-trace)
  - [10. Reset and boot](#10-reset-and-boot)
- [Part II: Discussion](#part-ii-discussion)
  - [11. Where it comes from](#11-where-it-comes-from)
  - [12. How fast](#12-how-fast)
  - [13. The choices](#13-the-choices)
  - [14. The tentative instructions](#14-the-tentative-instructions)
  - [15. Chips](#15-chips)
  - [16. Faster still](#16-faster-still)
  - [17. How it was checked](#17-how-it-was-checked)
  - [18. Open questions](#18-open-questions)
  - [19. Next steps](#19-next-steps)

## Part I: Specification

### 1. Overview

A microcoded CPU on one card, a master and a slave on the system bus of
[RFC 0014](0014-rfc-system-bus.md). Its parts are RFC 0024's `fast` set:
74F and 74ABT logic, 74F181 ALUs with 74F182 carry lookahead, and 12 ns
SRAM for the control store, the decode table, the register file, the page
map and the card's RAM.

- **Control:** a writable control store of 64K microinstructions of 144
  bits (141 used), a decode table of 64K entries, the microinstruction
  register (uIR) and a sequencer ([8](#8-the-microinstruction-and-the-sequencer)).
  The I/O processor fills both at boot ([10](#10-reset-and-boot)).
- **Datapath, 32 bits:** a register file of 256 banks and the
  microcode's own locations, read on two ports and written on one; an A
  bus and a B bus of four byte lanes; the ALU; a result multiplexer that
  shifts right by one, rotates by 8 or 16 and clears bytes; the working
  registers R, T, MAR, MQ and the loop counter LC; the flags
  ([3](#3-datapath)).
- **Fetch:** the PC, a fetch counter FPC and a prefetch queue of two
  32-bit words, filled in cycles that don't use memory; the decode reads
  the queue's head parcel ([4](#4-fetch-and-decode)).
- **Memory, 32 bits:** one access a cycle, a fetch or a data access, at
  a virtual address from MAR, FPC or the A bus; RFC 0029's window and page
  map; 2 MB of RAM on the card; everything else over the bus
  ([5](#5-memory), [6](#6-the-bus-and-the-slave-port)).
- **System:** the S, I and T flags, the bank and context registers, the
  fault registers, and forced microcode entries for refills, interrupts,
  trace and faults ([9](#9-exceptions-interrupts-and-trace)).

### 2. Clock and cycles

- **Ticks.** A 50 MHz master clock: a tick is 20 ns.
- **Microcycles** are 4 to 19 ticks long. Four lengths, the **length
  classes**, are set with jumpers; each microinstruction's `LCL` field
  picks one of them. The lengths the suite's profile picks are 4, 5, 6
  and 8 ticks ([12](#12-how-fast)).
- **Within a cycle:**
  - the register file is read into latches early in the cycle and
    written in its last tick, so a register can be read and written in
    the same cycle;
  - the memory write strobe is open from tick 3 to the last tick, so a
    cycle that writes memory is at least 5 ticks;
  - a bus access holds the cycle at tick 3 until the transfer is over
    ([6](#6-the-bus-and-the-slave-port)), so a cycle whose access may go to
    the bus (a data access, or a fetch the decode waits for) is at least
    6 ticks.
- **The clock generator** is RFC 0024's for short cycles (section 6
  there): a tick counter, the length compare, the write strobe and the
  hold.

### 3. Datapath

#### 3.1 The register file

- **Two copies,** A and B, each two 64K × 16 SRAMs, written together and
  read separately: copy A drives the A bus, copy B the B bus. Each read
  goes through a latch (74ABT573) that closes before the write.
- **Addresses, 14 bits:** `{G, bank[7:0], reg[4:0]}`.
  - `G = 0`: the banks of RFC 0029, 5. In each, 0–15 are `r0`–`r15`, 16 is
    `HI` and 17 is `LO`.
  - `G = 1`: the microcode's own locations: scratch (`TMP1`–`TMP3`),
    constants the reset routine writes (0, all ones, `0x8000_0000`, the
    vectors, masks), and the copies of `ctx`, `bank` and `mapa` that
    `MFSR` reads.
- **The register number** comes from `rd` (IR[15:12]), `R` (IR[11:8]),
  the counter SX, or the microinstruction's constant: `RFA`, `RFB` and
  `RFW` pick it for each port, `RFK` is the read constant and `RFKW` the
  write constant (constants 32 and up are the `G = 1` locations).
- **The bank** is `bank` in user mode and 0 in supervisor mode; `UBR` and
  `UBW` make a supervisor read or write use `bank` (`MFUR`, `MTUR`).

#### 3.2 The buses

- **A bus,** one driver: register file copy A; the PC, with `PCK` in
  bit 0; R; R × 2 with a bit shifted in (`SINA`: 0, R[31], C, MQ[31]);
  MAR.
- **B bus,** four byte lanes, one driver each:
  - register file copy B, or R: all four lanes;
  - T, by the access's size and address: the word, or its half or byte
    moved down to the low lanes (`BL`);
  - the queue's head parcel QH (`BL`): as it is, × 2 (a branch offset),
    in the upper half, or its low byte;
  - the immediate unit: byte 0 from `V8` (the branch offset × 2, the
    microinstruction's constant `KONST`, the fill byte, LC, the parcel's
    quick constant q, −(q + 1), the 7-bit constant `{IR[11:8], IR[2:0]}`,
    or 4q), and bytes 1–3 all copies of a fill bit (`FSEL`: 0, 1, IR[15],
    QH[15], QH[7], A[31], A[15], SGN);
  - special sources (`BX`): MQ, the flags word, `fsr`, `far`, the map
    entry being read.

#### 3.3 The ALU and the result

- **ALU:** eight 74F181 with two levels of 74F182. Its function (`S`,
  `M`) and carry in (`CIN`: 0, 1, C, A[31], MQ[31], SGN, MQ[0], not S33)
  come from the microinstruction, or, in a multiply or divide step
  (`MS`), from the step logic: add or pass on MQ[0] (unsigned multiply),
  subtract or pass on MQ[0] (the signed multiply's last step), add or
  subtract on S33 (non-restoring divide).
- **The result multiplexer** (`RMS`): the ALU's output F; F shifted right
  by one with a bit in (`SIN`: 0, F[31], C, F[0]; in a multiply step the
  carry out, or the sum's true sign); F rotated by 8; F rotated by 16.
  `RZ` then clears any of its four bytes. Its output is RES.
- **RES** goes to the register file, R, MAR, PC and FPC, LC, the flags,
  CL, CTX and BANK, and a zero detect.

#### 3.4 Registers

| Register | Bits | |
|---|---:|---|
| R | 32 | accumulator; loaded from RES (`LDR`) |
| T | 32 | memory data: latched by every read, transparent while it reads |
| MAR | 32 | data address; loaded from RES, or counts up by 4 (`MARINC`) |
| MQ | 32 | a shift register (74F299): holds, shifts right with R (multiply, `MULFX`), shifts left (divide), or loads from B (`MQM`) |
| S33 | 1 | the divide's partial remainder's sign |
| SGN | 1 | a sign kept for the fill (`LDSGN`) |
| LC | 8 | loop counter: loaded from RES, counts up (`LCINC`); conditions LC = 255 and LC[3:0] = 15 |
| CL | 1 | condition latch (`CLSRC`): RES = 0, the ALU's carry, RES[31:16] = 0, RES[31:15] = 0, or the last two ANDed with CL |
| SX, EX | 4, 4 | a register number that counts, and where the count stops (`SAVE`, `RESTORE`, `LDM`, `STM`, the indexed modes, `MULFX`) |
| CTX | 7 | the page map context, from RES (`LDCTX`) |
| BANK | 8 | user mode's register bank, from RES (`LDBANK`) |
| FK, FSR, FAR | 2, 8, 32 | the last fault's kind, RFC 0029's `fsr` and `far` |

#### 3.5 Flags

The flags word of RFC 0029, 2: V, C, Z, N, I, S, T.

- **N and Z** (`FNZ`): from RES, N from bit 31, 15 or 7 (`NSEL`); Z
  sticky (Z and RES = 0, for `ADC` and `SBC`); or loaded from the A bus,
  masked by `LFM` (NZCV for `MTSR flags` in user mode; also I and T in
  supervisor mode; also S for `RTI`).
- **C** (`FC`): a bit of F or A chosen by `CSRC` (for the shifts), the
  ALU's carry, or not CL; `CZERO` clears it.
- **V** (`FV`): 0, 1, A[0], not CL, or the ALU's overflow.
- **I** (`FI`): 1, 0, or A[4]. **S** is set by `SSET` (exception entry)
  or loaded with the flags. **T** is loaded with the flags and cleared
  with S.
- **Branch conditions:** the condition of a `Bcc`, `Jcc` or `SETcc`
  comes from the flags and a cc field of IR (`CCB`: IR[15:12], IR[3:0]
  or IR[11:8]).

### 4. Fetch and decode

- **PC** is the address of the next parcel to decode; **FPC** the next
  word to fetch. Both are 74F161 counters loaded from RES.
- **The queue** holds two 32-bit words, Q0 and Q1, each with a valid bit;
  QH, the head parcel, is Q0's low or high half by PC[1].
- **The fetch.** In a cycle whose microinstruction doesn't use the memory
  port, if Q1 is free, the word at FPC is translated (as a fetch, checked
  for X) and read; at the edge it joins the queue and FPC moves on. It
  reads the card's RAM in any such cycle, and bus space only when the
  decode waits for it (a refill), or when it hits in the instruction
  cache ([7](#7-the-instruction-cache-open)).
- **The decode** (`SEQ` 1) is the last cycle of every instruction. The
  decode table, addressed by QH, gives the first microinstruction's
  address and the instruction's length in parcels. If the queue, with
  the word this cycle fetches, holds the whole instruction, the decode
  goes ahead: IR ← QH, the parcel is consumed, the next cycle runs the
  instruction's first microinstruction. A fetch fault counts only if the
  decode needs the word.
- **Forced entries.** Instead of going ahead, the decode goes to:
  1. the trace entry, if T was set when the instruction started;
  2. else the interrupt entry, if an interrupt is pending;
  3. else the refill entry, if the queue doesn't hold the whole next
     instruction or this cycle jumped.
- **The refill** is a decode with a demand fetch: it fetches the word at
  FPC, which may go to the bus, and decodes from it as the queue would.
- **Extension parcels** are read from QH by the instruction's later
  cycles, each consuming its parcel (`CONSUME`). No cycle both consumes
  and decodes, or consumes in a data access.
- **A jump** (`LDPC`, or `PCCOND` with a branch condition or not CL)
  loads PC and FPC from RES and empties the queue; a decode in the same
  cycle is forced to the refill.

### 5. Memory

- **One access a cycle** (`MEM`): read, write, fetch, map read, map
  write, or a read at the A bus. Size (`SIZE`): byte, half or word.
- **The virtual address** comes from MAR for reads, writes and map
  accesses, from FPC for fetches, and from the A bus for a read at the A
  bus (an addressing mode whose address is a register, `[R]` and `[R]+`,
  without a cycle to load MAR). A three-way multiplexer (74F153) in front
  of the map selects it.
- **Translation,** RFC 0029, 3: an address with bit 31 set is, in
  supervisor mode, physical `va & 0x7FFF_FFFF` (the window); one below
  16 MB is looked up in the page map at `{CTX, va[23:12]}`. Anything else
  faults. The map is 512K entries of 23 bits (three 512K × 8 SRAMs):
  the physical page, X, W and V.
- **Map accesses** (supervisor mode only) read or write the entry at
  MAR[30:12], the map's address being `mapa << 12`; the entry goes onto
  B, or comes from B.
- **Alignment.** A half at an odd address or a word at an address that
  isn't a multiple of 4 is an address error.
- **The card's RAM:** 2 MB (four 512K × 8 SRAMs), in slot 0
  ([6](#6-the-bus-and-the-slave-port)). A read latches the aligned word into T;
  the B lanes take the bytes the size and address pick. A store puts the
  A bus on the data lanes, replicated by size, with byte enables from the
  size and address.
- **Faults.** A misaligned access, a translation fault or a bus error
  sets FAULT. FAULT cancels the cycle: nothing it would load (registers,
  the register file, flags, the PC and the queue, LC, MQ) changes, no
  memory is written, and the next microinstruction is the fault entry
  ([9](#9-exceptions-interrupts-and-trace)). FK gets the kind (0 page fault, 1
  misaligned, 2 bus error), `far` the virtual address and, for a page
  fault, `fsr` the reason.

### 6. The bus and the slave port

- **Physical addresses:** the slot is PA[30:27], 16 slots of 128 MB, so
  the window reaches all of them; slot 0 is the CPU card. This moves RFC
  0014's slot bits from A31–A28 (**open**, [18](#18-open-questions)).
- **The master side.** An access outside the card's RAM is a bus
  transfer: 32 bits on a 32-bit card, two transfers on a 16-bit one. It
  holds the cycle from tick 3: the request waits for the next bus clock
  edge (60 ns bus clock, three ticks), the transfer takes its clocks, and
  the answer takes 4 ticks to cross back. A transfer nothing answers is a
  bus error.
- **The slave side,** what other masters see in slot 0:

  | Offset | |
  |---|---|
  | `0x000_0000`–`0x3FF_FFFF` | the card's RAM, repeated |
  | `0x400_0000` + `0x2_0000` k | the control store's SRAM k, 64K × 16, while the CPU is stopped: k = 0–8 the microinstruction's 16-bit lanes, k = 9 the decode table |
  | `0x600_0000` | the control register: bit 0 RUN, bit 1 RESET (written as 1, the reset routine runs when RUN is next set); read: bit 0 running, bit 1 halted |

  The control store can be written only while RUN is off.

### 7. The instruction cache (open)

An option for code in bus space, which otherwise fetches only on demand
([4](#4-fetch-and-decode)).

- **Organisation:** N words, direct mapped by physical address, a word a
  line; a tag and valid bit per line. A fetch from bus space that hits
  takes no bus transfer and may happen in any cycle without memory, as a
  fetch from the card's RAM does; one that misses fetches over the bus
  and fills the line.
- **Coherence:** the CPU's own stores to bus space invalidate the line
  they hit. Stores by other masters (DMA into code, the I/O processor) are
  **open**: snooping the bus's writes, or a flush.
- **Cacheability:** fetches only; I/O space is never fetched from in
  practice, so nothing marks pages uncacheable (**open**).

### 8. The microinstruction and the sequencer

#### 8.1 The control store

- **Pipelined** as in draft 1b: the control store is addressed with the
  next microinstruction's address, and its output is clocked into the
  uIR at every edge.
- **The address,** 16 bits, `{U[2:0], Y[12:0]}`:

  | U | Y | |
  |---|---|---|
  | `000` | the sequencer's next address | |
  | `001` | 0 | refill |
  | `010` | 0 | interrupt entry |
  | `011` | 0 | trace entry |
  | `1LL` | 0 | fault entry; LL is the number of parcels the instruction has consumed |

- **The decode table,** 64K × 16: `Y | LEN << 13`, for every first
  parcel.

#### 8.2 The fields

| Field | Bits | |
|---|---:|---|
| `NEXT` | 13 | the next address, or its upper bits for a branch or dispatch |
| `SEQ` | 2 | 0 next or branch, 1 decode, 2 dispatch, 3 halt |
| `COND` | 4 | a microbranch condition: LC = 255, R[31], CL, the branch condition or its inverse, MQ[31], LC[3:0] = 15, S, SX = EX, FK[0], FK[1], SX = 15, MQ[0], R[0] |
| `ARF` `APC` `AR` `AR2` `AMAR` | 1 each | the A bus's driver |
| `PCK` | 1 | bit 0 of the PC on the A bus |
| `SINA` | 2 | the bit into R × 2 |
| `BRF` `BR` | 1 each | register file copy B, R onto B |
| `BL` | 3 | T (word, half, byte) or QH (as is, × 2, upper half, low byte) onto B |
| `BX` | 3 | MQ, flags, `fsr`, `far`, the map entry onto B |
| `BS0` `BF1` `BF23` | 1 each | the immediate unit's byte 0, byte 1, bytes 2–3 onto B |
| `RFA` `RFB` `RFW` | 2 each | the register number for each port: `rd`, `R`, SX, constant |
| `RFK` `RFKW` | 6 each | read and write constants |
| `RFWE` | 1 | write the register file |
| `UBR` `UBW` | 1 each | the user's bank for a supervisor read, write |
| `LDSX` `SXINC` `LDEX` | 2, 1, 2 | load SX (`rd`, `R`, QH[15:12]), count it; load EX (`R`, QH[11:8]) |
| `S` `M` `CIN` | 4, 1, 3 | the ALU's function and carry in |
| `MQM` `MS` | 2, 2 | MQ's mode; the step logic (unsigned multiply, signed multiply's last step, divide, the divide's fix-up) |
| `RMS` `RZ` `SIN` | 2, 4, 2 | the result multiplexer, the bytes it clears, the bit a shift brings in |
| `V8` `FSEL` `KONST` `LDSGN` | 3, 3, 8, 1 | the immediate unit; load SGN from the fill bit |
| `LDR` `LDMAR` `MARINC` | 1 each | R, MAR |
| `LDPC` `PCCOND` | 1, 2 | jump: always, on the branch condition, on not CL |
| `CONSUME` | 1 | consume the head parcel |
| `LDLC` `LCINC` | 1 each | LC |
| `CCB` | 2 | where the branch condition's cc comes from |
| `LDCTX` `LDBANK` | 1 each | CTX, BANK from RES |
| `MEM` `SIZE` | 3, 2 | the memory access |
| `FNZ` `NSEL` `FC` `CZERO` `CSRC` `FV` `FI` `LFM` `SSET` | 2, 2, 2, 1, 3, 3, 2, 2, 1 | the flags ([3.5](#35-flags)) |
| `LDCL` `CLSRC` | 1, 3 | CL |
| `LCL` | 2 | the length class |

141 bits; the control store's nine 16-bit lanes leave three spare.

#### 8.3 The sequencer

- **Next or branch** (`SEQ` 0): Y = `NEXT`, or `{NEXT[12:1], cond}` when
  `COND` is set. A condition is evaluated as the cycle starts, from
  registers, so it reflects the cycle before.
- **Decode** (`SEQ` 1): [4](#4-fetch-and-decode).
- **Dispatch** (`SEQ` 2): Y = `{NEXT[12:4], QH[11:8]}`, the cycle
  consuming the parcel: the indexed modes' scale and size, and
  `MULFX`'s source register.
- **Halt** (`SEQ` 3): Y = `NEXT` (the same microinstruction), until an
  interrupt is pending; then the interrupt entry.
- **Forced:** FAULT overrides all of these with the fault entry.

### 9. Exceptions, interrupts and trace

RFC 0029, 6 and 7, as the microcode does them.

- **Entering an exception:** the flags word into `TMP1`; R ← the saved
  PC and S ← 1, which also clears I and T and selects bank 0; `sp` ← `sp`
  − 8 and MAR with it; the PC and then the flags word stored; the jump to
  the vector, from a constant in the register file. Five cycles, then the
  refill at the vector.
- **Faults:** the fault entry has the number of parcels the instruction
  had consumed, so the saved PC is the instruction's own; FK picks the
  vector: page fault, or address error for a misaligned access or a bus
  error. Every instruction changes the registers it addresses memory
  with, the flags and the PC only in or after its last access, and FAULT
  cancels the cycle it happens in, so faults are precise.
- **Illegal and privileged instructions** are microcode routines that
  trap from their first cycle; `SWI #n` computes its vector.
- **Interrupts:** the request is synchronised at every edge; it is
  pending if it was requested in the cycle before and I is set. A
  pending interrupt forces the next decode to the interrupt entry. So an
  interrupt is never taken straight after `EI` (I is set at its decode's
  edge), and may be straight after `DI`.
- **Trace:** TS ← T at every decode that goes ahead; with TS set, the
  next decode is forced to the trace entry, after the instruction.
  Exception entry clears TS with T.
- **`HALT`** loops in a halt microinstruction until an interrupt is
  pending.

### 10. Reset and boot

- **At power-up** RUN is off and the control store and decode table hold
  nothing. The I/O processor writes, through the slave port, the
  control store's words that are used, the decode table, and a boot
  program for the RAM; then RESET, then RUN.
- **The reset routine** (control store address 0) writes the register
  file's constants, sets S and clears the other flags, sets CTX and
  BANK to 0, and jumps to the reset vector, `0x8000_0000`: physical 0, in
  the window.
- **The boot program** sets up what the operating system needs (the map
  at least) and jumps to it.

## Part II: Discussion

### 11. Where it comes from

Draft 1b's CPU ([report 0012](0012-report-draft-1b-hardware.md)) and its
system ([report 0025](0025-report-draft-1b-system.md)) are the starting
point: the A and B buses, the 74181 ALU with the result multiplexer's
shifts, MQ for multiply and divide, R and T, the microinstruction's style
and its shift planner (reused as it is). What RFC 0024 recommended, and
what became of it:

| RFC 0024 | Here |
|---|---|
| fast parts (74F, 74ABT, 74F181/182, 12 ns SRAM) | yes |
| the clock generator for short cycles, 4–19 ticks | yes, with four length classes |
| the control store in 12 ns SRAM, with a loader | yes, written by the I/O processor through the slave port ([RFC 0027](0027-rfc-io-coprocessor.md)) |
| overlapped fetch: the next opcode in an instruction's last cycle | yes: every instruction's last cycle decodes from the queue |
| 32-bit memory and a two-parcel prefetch buffer | yes: a two-word (four-parcel) queue, filled in cycles that don't use memory |
| a register file written in the second half of any cycle | yes: read early through latches, written in the last tick, in every cycle |
| multiplies that stop early | yes, by operand size: 16 steps when both fit in 16 signed bits |
| 16-bit parts | assumed in the chip count ([15](#15-chips)) |
| GALs | no (Emily would rather not) |

Draft 2's own needs added the rest: the register banks, the page map and
the window, precise faults, the forced entries, the decode table for 16-bit
parcels, and the extension parcels read from the queue.

### 12. How fast

All numbers are in [performance.md](0031-rfc-draft-2-cpu/performance.md),
generated by `heron v2_hw report --write`. In short:

PERF_SUMMARY

### 13. The choices

- **The decode table** maps a whole first parcel (16 bits) to a
  microaddress: 64K × 16, one SRAM. Draft 2's register byte carries a
  mode in some cells and constants in others, so a table indexed by the
  opcode alone would need a second level; a full table costs nothing but
  the SRAM, and lets the instruction's length come with it, which the
  decode needs to know whether the queue holds the whole instruction. Its
  entries are generated with the microcode: 1,985 entry points, one per
  distinct behaviour, for the 65,536 parcels.
- **Decode from the queue, in the last cycle.** RFC 0024's overlapped
  fetch. The decode is the instruction's last cycle, doing that cycle's
  work too, so an instruction like `ADD rd, rs` is one cycle.
- **The queue is two words.** Two 32-bit words hold four parcels: the
  longest instruction (three parcels, such as `MOV rd, #imm32` and
  `JMP abs32`) wherever it starts. A deeper queue would only fetch further ahead of
  jumps.
- **No prefetch from bus space without a cache.** A bus fetch holds the
  CPU for the whole transfer, and a word fetched ahead is thrown away at
  the next jump. Prefetching over the bus in every free cycle
  (`--prefetch-bus` in `heron v2_hw run`) is only 1–2% faster than
  fetching when the decode needs the word (queens 27.5 against 28.0 ms,
  sieve 36.5 against 36.7), for a third more bus fetches, which
  other masters would wait for; so it fetches on demand. The cache
  changes that ([7](#7-the-instruction-cache-open)).
- **Reads at the A bus.** `[R]` and `[R]+` take their address straight
  from a register: with the A bus as a third source of the virtual
  address (8 more chips: three-way multiplexers instead of two-way), a
  `MOV rd, [R]` is one cycle and `[R]+` saves its MAR cycle. Measured:
  −3% of the suite's time, most of it the byte loop of `vm` (`MOV mA`,
  `[R]+` byte) and the string programs.
- **Multiply and divide** are draft 1b's: a bit a step through MQ, the
  multiply in 16 steps when both operands fit in 16 signed bits (the
  early stop of RFC 0024 in its cheapest form, a test of the operands'
  upper bits). R:MQ also shifts right as one 64-bit register, which
  `MULFX` uses.
- **The register file's constants** (vectors, masks, `0x8000_0000`) are
  written by the reset routine into locations outside the banks, so the
  microcode can use a constant wherever it can use a register, without a
  wider immediate unit.
- **`ctx`, `bank` and `mapa` are kept twice:** in registers for the
  hardware (CTX, BANK; `mapa` as MAR's upper bits when the map is
  accessed) and in the register file for `MFSR`. `mapa` is kept as
  `mapa << 12`, the form the map access needs, so `MTSR mapa` shifts it
  (seven cycles) and `MFSR mapa` shifts it back; both are rare.
- **Faults cancel the cycle.** FAULT stops every load in the cycle it's
  found, which is what makes RFC 0029's precise faults cheap: the
  microcode only has to make each instruction's changes to its address
  registers, flags and PC in or after its last access. `[R]+` updates R in
  the access cycle; the update is cancelled with it.
- **Bus errors** use the address error vector, since RFC 0029 has no
  vector for them yet (**open** there).

### 14. The tentative instructions

What each of RFC 0028's tentative instructions costs here, and what
hardware would make it cheaper. Cycles are for the instruction alone,
measured on the register-transfer model; microinstructions are the
control store words its routines take (a word shared with another routine
is counted once, under one of them).

| Instruction | Cycles | Microinstructions | Hardware it uses | Faster with |
|---|---|---:|---|---|
| `ADD.B4` | 6 | 6 | none: masks and an add | 1 cycle with the carry cut at byte boundaries, 2 chips, but a gate in the carry path that every add pays for (+4–5 ns) |
| `FFS` | 4 + index; 3 for 0 | 6 | none: a shift loop on R[0] | 1 cycle with a priority encoder onto B (74F148s, about 6 chips), which would serve `CLZ` too (now 4 + its result) |
| `POPC` | 4 + 2 × bits set | 5 | none: x & (x − 1) | a population count tree: about 15 chips, not worth it |
| `REV` | 4 | 3 | the rotations and byte clears | 1 cycle with a byte-reversed way into the result multiplexer (4 chips) |
| `MULA` | 39 | 10 | the multiply | about 25 with `MULS`'s 16-step path (microcode only) |
| `MERGE` | 3 | 3 | none | it has three operands; the ALU takes two |
| `MULFX` | 29 + n with 16-bit operands, 43 + n otherwise | 294 | the multiply; MQ shifting right with R | fewer words with a second counted register number (a routine per source register now) |
| `TMOV` | 3 | 3 | none | 1 cycle with a tag fault (below) |
| `TTST`, `TCMP` | 4 | 4 | none | 1 |
| `TADD`, `TSUB` | 9 | 9 | none: a trial add finds overflow | 1 |

- **A tag fault** would make every tagged operation one cycle: bit 0 of
  the A and B buses (and, for `TADD` and `TSUB`, the ALU's overflow)
  raising FAULT like a memory fault, with its own kind for the tag
  vector. FAULT already cancels the cycle, so the operation can do its
  work and trap in the same cycle. About 2 chips.
- **None of them needs datapath hardware** as specified here: each is
  microcode on what the other instructions need. Dropping all of them
  saves about 350 microinstructions of the 6,235 (most of them
  `MULFX`'s) and nothing else.
- **What they buy** is RFC 0028's to measure (9.8 there). One finding
  here: `MULFX r1, r2, #8` takes 37 cycles with 16-bit operands, where
  `MULS r1, r2` and `ASR r1, #8` together take 28. Its count is in a
  register field, so it shifts a bit a cycle, where a constant shift is
  planned (rotations and masks, 3 cycles for 8). A routine per count, as
  the constant shifts have, would bring it to about 28 cycles, at the
  cost of the source register: it would then need a counted register
  number, as SX gives the destination. As it stands, `MULFX` is worth
  having only for products that need 64 bits.

### 15. Chips

A rough count, by section, from the datapath's widths and its sources; the
netlist will replace it. 16-bit parts (74ABT16xxx registers, buffers and
transceivers) are assumed where RFC 0024 counted them as pairable.

| Section | Chips | |
|---|---:|---|
| Control store and decode table | 10 | 64K × 16 SRAMs |
| uIR | 9 | 141 bits, 74ABT16823 |
| Sequencer, conditions, forced entries | 10 | |
| Clock and length classes | 12 | RFC 0024's clock generator |
| Register file | 4 | 64K × 16 SRAMs, two copies |
| Register file addresses and read latches | 14 | |
| A bus | 10 | |
| B bus: T lanes, QH, immediate unit, special sources | 24 | |
| ALU and its control | 14 | 8 × 74F181, 3 × 74F182 |
| Result multiplexer | 18 | |
| R, T, MAR, MQ, LC, SX, EX, CL, S33, SGN | 24 | |
| PC, FPC, the queue, IR | 28 | |
| Flags and branch condition | 12 | |
| Virtual address multiplexer, map, window | 22 | 3 map SRAMs |
| RAM and store data | 10 | 4 SRAMs |
| Faults, FSR, FAR, CTX, BANK | 10 | |
| Bus interface, master | 30 | as 1b's |
| Slave port, control store writes, control register | 14 | |
| **Total** | **about 275** | |

About as many as 1b's CPU card as built (269, with no 16-bit parts), and
about 50 more than 1b redrawn with 16-bit parts (RFC 0024: 44 fewer), for
a 32-bit memory, the queue, the page map, the register banks and the
writable control store. *Estimate*, good to perhaps 15%, to be redone
from the netlist.

### 16. Faster still

The suite's time goes, in order: multiply and divide steps, the cycles
that compute (ALU, address and shift work, most of them 6 ticks), the
refills after jumps, extension parcels, branches, data accesses. Levers,
measured or estimated on the same profile
([performance.md](0031-rfc-draft-2-cpu/performance.md#what-some-changes-would-buy)):

WHATIF_SUMMARY

- **The 6-tick cycle** is the register file read (37 ns: the address
  multiplexer, the SRAM, the latch), the 32-bit add (51 ns through the
  74F182s) and the write's setup: 100.5 ns, just over 5 ticks. Taking the
  register file's address multiplexer out of the cycle (its address
  registered beside the uIR, computed from the control store's output)
  and the zero and overflow detection out of the flag cycles would bring
  most of them to 5 ticks.
- **A faster adder:** 74AS181 with a 74AS882 lookahead would roughly
  halve the add, but neither is in the repository's timing data yet.
- **A branch-target adder** (performance.md, *Refills*): about 2% net,
  for some 15–20 chips; not recommended yet.
- **Code over the bus** costs 2–3× without the cache; a 256-word cache
  takes most of that back (the rest is data over the bus).

### 17. How it was checked

- **Against the instruction-level simulator** (`heron v2_hw check`):
  every program of draft 2's suite, the 15 compiled C programs, the
  supervisor tests in `sw/systest.s`, and a generated exercise program
  (`exercise.py`: every ALU operation and mode on chosen values, the
  flags, multiply, divide, shifts, the tentative instructions) give the
  same output and registers; `--lockstep` compares the registers after
  every instruction. The suite also runs with its code and data over the
  bus (`--bus`), with and without the cache, and booted through the I/O
  processor (`heron v2_hw boot`).
- **The rules the hardware relies on** are checked by the model at every
  cycle: one driver per bus lane, nothing floating used, no parcel
  consumed from an empty queue, no consume in a decode or a data access.
- **`MOVS` of a byte or half** takes N from the operand's bit 7 or 15
  (RFC 0028, 5.1); `sw/isanotes.s` checks it on its own as well.
- **The exercise program runs in user mode** on this model, so that the
  flags words it saves are the same as the simulator's apart from S.

### 18. Open questions

1. **The slot bits.** RFC 0014 puts the slot in A31–A28; RFC 0029's
   window reaches only the lower 2 GB of physical space. Here the slot is
   A30–A27 (16 slots of 128 MB) so the window reaches every slot.
2. **A vector for bus errors** (RFC 0029, 3, open there): here they use
   the address error vector.
3. **Trace after a trapping instruction:** a `SWI` or a fault enters its
   handler with T cleared, so the trace exception comes only when
   `RTI` returns to traced code. Is that what RFC 0029 means?
4. **Changes to the map or `ctx` and the queue.** Words already in the
   queue were fetched under the old mapping: code that changes the
   mapping of the code it runs must jump afterwards. Say so in RFC 0029?
5. **The instruction cache:** whether to have it, its size, and DMA
   coherence ([7](#7-the-instruction-cache-open)).
6. **The tag fault** ([14](#14-the-tentative-instructions)), if the tagged
   operations stay.
7. **Interrupt priority levels** (RFC 0029, 7): one request here.
8. **The breakpoint register** (`bkpt`, RFC 0029, 4): not built; it
   would compare the PC at every decode (about 5 chips).
9. **`CAS` and the FPU's cells** (RFC 0028): not built; illegal here.

### 19. Next steps

1. The netlist and static timing analysis, as `v1b_hw` has: the timing
   estimate here becomes a measurement, and the chip count a count.
2. The chip-level system: the CPU card on the bus with the memory card
   and the I/O processor, booting from flash.
3. The kernel of report 0020 ported to draft 2, on this model, for the
   supervisor architecture under real use.
4. Decide the levers of [16](#16-faster-still) and the open questions
   above.
