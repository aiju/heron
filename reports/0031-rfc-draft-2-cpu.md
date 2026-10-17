---
number: 31
type: rfc
title: Draft 2's CPU
status: open
date: 2026-10-16
context:
  studies: [v2_hw, v2_isa, v1b_hw, v1b_tradeoffs, c_compiler]
  commit: aa9b2f1
depends-on: [14, 24, 27, 28, 29, 37, 40]
---

# RFC 0031: Draft 2's CPU

A CPU card for draft 2: the instruction set of
[RFC 0028](0028-rfc-draft-2-isa.md) with the system architecture of
[RFC 0029](0029-rfc-draft-2-system.md), built on
[RFC 0024](0024-rfc-faster-smaller.md)'s advice, with the interrupts of
[RFC 0040](0040-rfc-interrupts.md) (eight levels, the message register,
the CPU card's timer) and the address map of
[RFC 0037](0037-rfc-system-and-io-bus.md). Part I is the
specification of its microarchitecture, with what isn't decided marked
**open**; Part II is where it comes from, what it measures and what's
left. The study is [studies/v2_hw](../studies/v2_hw/README.md): the
microcode, a register-transfer model checked against the instruction-level
simulator, the boot through the I/O processor, a chip-level netlist of the
CPU's core with static timing analysis, and the measurements in
[performance.md](0031-rfc-draft-2-cpu/performance.md).

This is a first draft, written while the ISA and the system architecture
are still moving. The netlist covers the core, the RAM, the map, the
control store and the interrupt logic, not yet the bus interface, the
slave port or the CPU card's register block (a fixture for the
chip-level simulator); every microinstruction's length comes from its
static timing analysis ([15](#15-the-netlist-and-its-timing)). What RFC
0040's choices cost here, and the alternatives measured for them, are in
[19](#19-the-system-half-what-rfc-0040-costs).

## Contents

- [Part I: Specification](#part-i-specification)
  - [1. Overview](#1-overview)
  - [2. Clock and cycles](#2-clock-and-cycles)
  - [3. Datapath](#3-datapath)
  - [4. Fetch and decode](#4-fetch-and-decode)
  - [5. Memory](#5-memory)
  - [6. The bus, the slave port and the CPU card's registers](#6-the-bus-the-slave-port-and-the-cpu-cards-registers)
  - [7. The instruction cache (open)](#7-the-instruction-cache-open)
  - [8. The microinstruction and the sequencer](#8-the-microinstruction-and-the-sequencer)
  - [9. Exceptions, interrupts and trace](#9-exceptions-interrupts-and-trace)
  - [10. Reset and boot](#10-reset-and-boot)
- [Part II: Discussion](#part-ii-discussion)
  - [11. Where it comes from](#11-where-it-comes-from)
  - [12. How fast](#12-how-fast)
  - [13. The choices](#13-the-choices)
  - [14. The tentative instructions](#14-the-tentative-instructions)
  - [15. The netlist and its timing](#15-the-netlist-and-its-timing)
  - [16. Chips](#16-chips)
  - [17. Faster still](#17-faster-still)
  - [18. How it was checked](#18-how-it-was-checked)
  - [19. The system half: what RFC 0040 costs](#19-the-system-half-what-rfc-0040-costs)
  - [20. Open questions](#20-open-questions)
  - [21. Next steps](#21-next-steps)

## Part I: Specification

### 1. Overview

A microcoded CPU on one card, a master and a slave on the system bus of
[RFC 0014](0014-rfc-system-bus.md). Its parts are RFC 0024's `fast` set:
74F and 74ABT logic, 74F181 ALUs with 74F182 carry lookahead, and 12 ns
SRAM for the control store, the decode table, the register file, the page
map and the card's RAM. The registers, latches and buffers are 16-bit
74ABT parts (74ABT16374, 16823, 16373, 16244), each package two 8- or
9-bit halves with their own clock and enables.

- **Control:** a writable control store of 64K microinstructions of 144
  bits, a decode table of 64K entries, the microinstruction
  register (uIR) and a sequencer ([8](#8-the-microinstruction-and-the-sequencer)).
  The I/O processor fills both at boot ([10](#10-reset-and-boot)).
- **Datapath, 32 bits:** a register file of 256 banks and the
  microcode's own locations, read on two ports and written on one; an A
  bus and a B bus of four byte lanes; the ALU; a result multiplexer that
  shifts right by one, rotates by 8 or 16 and clears bytes; the working
  registers R, T, MAR, MQ and the loop counter LC; the flags
  ([3](#3-datapath)).
- **Fetch:** the PC, a fetch counter FPC, FPC's page as last translated,
  and a prefetch queue of two 32-bit words, filled in cycles that don't
  use memory; the decode reads the queue's head parcel
  ([4](#4-fetch-and-decode)).
- **Memory, 32 bits:** one access a cycle, a fetch or a data access, at
  a virtual address from MAR, FPC or the A bus; RFC 0029's window and page
  map; 2 MB of RAM on the card; everything else over the bus
  ([5](#5-memory), [6](#6-the-bus-the-slave-port-and-the-cpu-cards-registers)).
- **System:** `sr` (S, I, T, M, IPL), the bank and context registers,
  the fault registers, the message level's registers, the interrupt
  logic for the CPU card's eight levels, its message register and the
  NMI, and forced microcode entries for refills, interrupts, trace and
  faults ([9](#9-exceptions-interrupts-and-trace)).

### 2. Clock and cycles

- **Ticks.** A 50 MHz master clock: a tick is 20 ns.
- **Microcycles** are 4 to 19 ticks long. Four lengths, the **length
  classes**, are set with jumpers; each microinstruction's `LCL` field
  picks one of them. A microinstruction's length is what static timing
  analysis of the netlist says it needs; the lengths the suite's profile
  then picks are 4, 5, 6 and 9 ticks ([12](#12-how-fast)).
- **Within a cycle** of K ticks, numbered from 0 (CLK rises entering
  tick 0):
  - the register file is read into latches from the cycle's start and
    written in its last tick: RW is high for the last two ticks (the
    latches hold, the SRAM's address switches to the write address, its
    outputs turn off) and the write strobe is the last tick, so a register
    can be read and written in the same cycle;
  - LATE is high from tick 2 to the end: the store data drives the card's
    data bus only then, and T's latches open only then, once the cycle
    before's reads are off the bus and its decoded controls have settled;
  - the memory write window is open from tick 4 to the tail tick, so that
    a write's address has been translated and checked before it opens: a
    cycle that writes memory is at least 6 ticks;
  - a bus access holds the cycle at tick 3 until the transfer is over
    ([6](#6-the-bus-the-slave-port-and-the-cpu-cards-registers)), so a cycle whose access may go to
    the bus (a data access, or a fetch the decode waits for) is at least
    6 ticks.
- **The clock generator** is RFC 0024's for short cycles (section 6
  there): a tick counter preloaded by the length class, flip-flops for
  the head and tail ticks and the phases above, and the hold. Nothing
  resets its flip-flops, and with 4-tick cycles two pulses could chase
  each other through T1, H0 and H1, each phase two ticks wide and the
  clock's edge inside the register file's write; so H0 loads T1 only
  while H0 is off, which kills a second pulse from any state the
  flip-flops power up in.
- **Reset** (RESET_n) is asserted at once by the power-on reset and
  released at a CLK edge, through two flip-flops: the CPU and the card's
  registers then agree which edge ends it, and the first cycle, the reset
  routine's word 0, starts at the last edge with RESET_n low.

### 3. Datapath

#### 3.1 The register file

- **Two copies,** A and B, each two 64K × 16 SRAMs, written together and
  read separately: copy A drives the A bus, copy B the B bus. Each read
  goes through a latch (a 74ABT16373 half) that closes before the write.
- **Addresses, 15 bits:**
  - `{0, 0, bank[7:0], reg[4:0]}`: the banks of RFC 0029, 5. In each,
    0–15 are `r0`–`r15`; 16–31 are unused, since `HI` and `LO` are `r0`
    and `r1` ([RFC 0028, 9.9](0028-rfc-draft-2-isa.md#99-hi-and-lo-are-r0-and-r1)).
  - `{0, 1, bank[7:0], k[4:0]}`, for constants k = 32–63: the
    microcode's own locations, the G half of each bank: scratch
    (`TMP1`–`TMP3`), constants the reset routine writes into every bank
    (0, all ones, `0x8000_0000`, masks, the `SWI` vectors), and what only
    bank 0's hold: the copies of `ctx`, `bank` and `mapa` that `MFSR`
    reads, `vbr`, and the exceptions' vectors with `vbr` in them.
  - `{1, 0, 0, reg[4:0]}`: the message level's sixteen registers
    ([RFC 0040, 2.4](0040-rfc-interrupts.md#24-banks)), its own
    `r0`–`r15`.
- **The register number** comes from `rd` (IR[15:12]), `R` (IR[11:8]),
  the counter SX, or the microinstruction's constant: `RFA`, `RFB` and
  `RFW` pick it for each port, `RFK` is the read constant and `RFKW` the
  write constant (constants 32 and up are the `G = 1` locations). Each
  register bit and G is one 74F151 per copy, by `RFA` (`RFB`) and RW: the
  read address's four ways and, in the last two ticks, the write address.
- **The bank** is `bank` in user mode and 0 in supervisor mode, for the
  G half too. `UBW` makes a supervisor write use `bank` (`MTUR`); `UBR`
  makes the next cycle's reads use it (`MFUR` sets it in the cycle that
  checks S). The read bank is kept in a register, loaded at every edge
  with what `bank` and S will be, so that it is there when the cycle
  starts. Both copies use the same bank, so its bits are one 74F157 pair
  for both: the read bank, and in the last two ticks the write's.
- **The message level's registers** take the place of bank 0's `r0`–`r15`
  while M is set in supervisor mode, for reads without `UBR` and writes
  without `UBW`; the G locations are the same in both. Their address
  line A14 comes from MB, a flip-flop loaded at every edge with what M
  and S will be and the cycle's `UBR` (as the read bank is), through one
  74F151 per copy with the write's in the last two ticks; a constant read
  takes MB unless it reads G, from a faster copy of `RFK`'s bit 5 beside
  it.
- **Scratch never lives across a change of bank:** where S changes
  partway through a routine (the exception entry), nothing the routine
  writes to the register file before the change is read after it,
  except `SWI`'s vector, which it writes with `UBW` and reads back with
  `UBR`.

#### 3.2 The buses

- **A bus,** one driver: register file copy A; the PC, with `PCK` in
  bit 0; R; R × 2 with a bit shifted in (`SINA`: 0, R[31], C, MQ[31]).
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
  - special sources (`BX`): MQ, `sr` (its bytes 0 and 3, the others 0),
    `fsr`, `far`, the map entry being read, the interrupt's vector offset
    from LT (`0x40` + 4(L − 1), or the NMI's `0x04`), and the CPU card's
    message register as {message, source}, which releases it at the
    cycle's end.
- **Enables:** every driver's enable is one gate after the uIR, a decoded
  one (`BL`, `BX`) through a 74F138 or a 74F151 and a direct one through
  a gate, so that a cycle's drivers come on about when the cycle before's
  go off.

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
| T | 32 | memory data: latched by every read, transparent while it reads (from tick 2) |
| MAR | 32 | data address; loaded from RES, or counts up by 4 (`MARINC`) |
| MQ | 32 | a shift register (74F299): holds, shifts right with R (multiply, `MULFX`), shifts left (divide), or loads from B (`MQM`) |
| S33 | 1 | the divide's partial remainder's sign |
| SGN | 1 | a sign kept for the fill (`LDSGN`) |
| LC | 8 | loop counter: loaded from RES, counts up (`LCINC`); conditions LC = 255 and LC[3:0] = 15 |
| CL | 1 | condition latch (`CLSRC`): RES = 0, the ALU's carry, RES[31:16] = 0, RES[31:15] = 0, or the last two ANDed with CL; kept as four bits, as Z is ([3.5](#35-flags)) |
| SX, EX | 4, 4 | a register number that counts, and where the count stops (`SAVE`, `RESTORE`, `LDM`, `STM`, the indexed modes, `MULFX`) |
| CTX | 7 | the page map context, from RES (`LDCTX`) |
| BANK | 8 | user mode's register bank, from RES (`LDBANK`) |
| FK, FSR, FAR | 1, 8, 32 | the last fault's kind, RFC 0029's `fsr` and `far` |
| IPL | 4 | `sr`'s interrupt priority level ([3.5](#35-flags)) |
| LQ, PEND | 10, 1 | the CPU card's levels, message flag and NMI, registered at every edge; the interrupt decision a cycle later ([9](#9-exceptions-interrupts-and-trace)) |
| LT | 9 | the level taken, its vector offset, NMI and MSGT, held through an interrupt's entry |
| EB, MB | 8, 1 | the read bank and the message level's register select for the cycle, loaded at every edge |

#### 3.5 Flags

The status register `sr` of RFC 0029, 2, with RFC 0040's M: S, I, T, M
in bits 31–28, IPL in 27–24, N, Z, C, V in 3–0.

- **N and Z** (`FNZ`): from RES, N from bit 31, 15 or 7 (`NSEL`); Z
  sticky (Z and RES = 0, for `ADC` and `SBC`); or loaded from the A bus,
  masked by `LFM` (0: NZCV, for `MTSR ccr`; 1: also I, T, M and IPL,
  for `MTSR sr`, which keeps S; 2: also S, for `RTI`). Z is kept as four bits, each a byte
  of RES nonzero, and formed after the register: the cycle that sets it
  ends one compare after RES, and the next starts with the two gates that
  form it, where the branch condition has time to spare.
- **C** (`FC`): a bit of F or A chosen by `CSRC` (for the shifts), the
  ALU's carry, or not CL; `CZERO` clears it.
- **V** (`FV`): 0, 1, A[0], not CL, or the ALU's overflow.
- **I** (`FI`): 1, 0, or A[30]. **S** is set by `SSET` (exception entry)
  or loaded with the flags. **T** is loaded with the flags and cleared
  with S.
- **M** is loaded with the flags, and at an exception's entry set to
  MSGT (an interrupt's: the message level) or cleared (any other).
- **IPL:** a flags load with `LFM` 1 or 2 takes A[27:24]; `LFM` 1
  without a flags load or `SSET` is `SPL`, IPL alone from A[27:24]; an
  interrupt's entry (`SSET` with `LFM` 1) sets it to L, except for the
  NMI, which that acknowledges instead. One 74F157 and a register half.
- **Branch conditions:** the condition of a `Bcc`, `Jcc` or `SETcc`
  comes from the flags and a cc field of IR (`CCB`: IR[15:12], IR[3:0]
  or IR[11:8]).

### 4. Fetch and decode

- **PC** is the address of the next parcel to decode; **FPC** the next
  word to fetch. Both are 74F161 counters loaded from RES.
- **The queue** holds two 32-bit words, Q0 and Q1, each with a valid bit;
  QH, the head parcel, is Q0's low or high half by PC[1].
  - **Two slots and a head pointer:** the words sit in two slots that
    load straight from the card's data bus; Q0 is slot HS and Q1 the
    other, and a shift toggles HS instead of moving a word. A slot loads
    in every cycle its entry is empty (V0 or V1 off), so the word a fetch
    brings is there when its valid bit comes on, and a slot's load
    enable doesn't wait for the decode.
  - **QH is a three-state bus,** driven through 74ABT16244 halves by
    V0, HS and PC1F: the head slot's half, or with the queue empty the
    half of the word this cycle fetches.
- **The fetch's translation.** FOK and FPPN keep FPC's page as last
  translated: set from the map's translation of FPC (as a fetch, checked
  for X) by a refill, or by a cycle that doesn't use the memory port
  while FOK is clear; cleared by a jump and when FPC moves into the next
  page. Code that changes the map, `ctx` or S under the code it runs must
  jump afterwards, as it must for the queue.
- **The prefetch.** In a cycle whose microinstruction doesn't use the
  memory port, with FOK set and Q1 free, the word at FPC is read at the
  kept page, without the map; at the edge it joins the queue and FPC
  moves on. With FOK clear the map translates FPC instead, for the cycles
  after. It reads the card's RAM, and bus space only when it hits in the
  instruction cache ([7](#7-the-instruction-cache-open)).
- **The decode** (`SEQ` 1) is the last cycle of every instruction. The
  decode table, addressed by QH, gives the first microinstruction's
  address and the instruction's length in parcels. If Q0 holds the
  instruction's first parcel and the queue, with the word this cycle
  fetches, the rest, the decode goes ahead: IR ← QH, the parcel is
  consumed, the next cycle runs the instruction's first microinstruction.
- **Forced entries.** Instead of going ahead, the decode goes to:
  1. the trace entry, if T was set when the instruction started;
  2. else the interrupt entry, if an interrupt is pending;
  3. else the refill entry, if the queue doesn't hold the whole next
     instruction as above, or this cycle jumped.
- **The refill** is a decode with a demand fetch: it translates FPC with
  the map, fetches the word, which may go to the bus, and decodes from the
  queue with that word, even with the queue empty. Its fetch fault counts
  only if the decode needs the word.
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
  of the map selects it, by `VAS`, which the microcode derives from `MEM`.
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
- **The card's RAM:** 2 MB (four 512K × 8 SRAMs), repeated through
  region 0 as the CPU sees it ([6](#6-the-bus-the-slave-port-and-the-cpu-cards-registers));
  always selected, its outputs on in any fetch and in a read of region 0. A read
  latches the aligned word into T; the B lanes take the bytes the size and
  address pick. A store puts the A bus on the data lanes from tick 2,
  replicated by size, with byte enables from the size and address. A
  prefetch with FOK reads it at FPPN.
- **Faults.** A misaligned access or a translation fault sets FAULT,
  settled before the write window opens. FAULT cancels the
  cycle: nothing it would load (registers,
  the register file, flags, the PC and the queue, LC, MQ) changes, no
  memory is written, and the next microinstruction is the fault entry
  ([9](#9-exceptions-interrupts-and-trace)). FK gets the kind (0 page
  fault, 1 misaligned), `far` the virtual address and, for a page fault,
  `fsr` the reason. An access nothing answers doesn't fault
  ([6](#6-the-bus-the-slave-port-and-the-cpu-cards-registers)).

### 6. The bus, the slave port and the CPU card's registers

- **Physical addresses** are RFC 0037's
  ([5.1](0037-rfc-system-and-io-bus.md#51-addresses)): the region is
  PA[31:28], 16 regions of 256 MB. The CPU card is in region 0 here: its
  RAM at `0x0000_0000`, its registers at `0x7000_0000`. The window
  reaches physical addresses below 2 GB, so regions 0–7.
- **The master side.** An access outside the card's RAM and its own
  registers is a bus transfer: 32 bits on a 32-bit card, two transfers
  on a 16-bit one. It holds the cycle from tick 3: the request waits for
  the next bus clock edge (60 ns bus clock, three ticks), the transfer
  takes its clocks, and the answer takes 4 ticks to cross back. A
  transfer nothing answers reads what the bus last held and doesn't trap
  ([RFC 0037, 5.6](0037-rfc-system-and-io-bus.md#56-unused-addresses-and-faults)).
- **Its own registers** are on the card's data bus, decoded from
  PA[31:24] = `0x70` (the netlist decodes PA[31:28], its fixture the
  rest): a load or store
  there is an ordinary cycle, without the bus (a bus read holds the
  cycle 11–13 ticks more, a write 14–16). The CPU's writes to them take
  effect at the cycle's end, as the write strobe rises.
- **The slave side,** what other masters see of region 0:

  | Address | |
  |---|---|
  | `0x0000_0000`–`0x0FFF_FFFF` | the card's RAM, repeated |
  | `0x7000_0000` + offset | the card's registers (below) |
  | `0x7080_0000` + `0x2_0000` k | the control store's SRAM k, 64K × 16, halfwords, while the CPU is stopped: k = 0–8 the microinstruction's 16-bit lanes, k = 9 the decode table (**open**, [RFC 0040, 3](0040-rfc-interrupts.md#3-the-cpu-card)) |

  The control store can be written only while RUN is off.
- **The card's registers** ([RFC 0040, 3](0040-rfc-interrupts.md#3-the-cpu-card)),
  words; a 16-bit master reads and writes them as two halfwords, low
  then high:

  | Offset | |
  |---|---|
  | `0x0000` | control. Write: bit 0 RUN, bit 1 RESET (clears the registers below; the reset routine runs when RUN is next set), bit 3 NMI. Read: bit 0 running, bit 1 halted, bit 2 1, bit 3 an NMI pending |
  | `0x1000` | board information (**open**): the region in bits 3–0, log₂ of the RAM's size in MB in 7–4, BCLK's period in ns in 15–8 |
  | `0x2000`, `0x2004`, `0x2008` | the request register: set, clear (the levels whose bits are 1), read; bit L − 1 is level L, 1–8, as the I/O processor's firmware writes it (**open**, RFC 0040 leaves the bits unsaid) |
  | `0x3000` | the message register's claim: a read returns 0 and claims it if it is free, else 1 |
  | `0x3004` | the message, {source in bits 31–24, message in 23–0}, while claimed: a word, or a 16-bit master's low half then high half, whose write completes it |
  | `0x3008`, `0x300C` | release; read the message |
  | `0x4000` | the timer: BCLKs since reset, 32 bits (**open**: or BCLK/4, which 74HC590s can count, [19](#19-the-system-half-what-rfc-0040-costs)). A 16-bit master reads the low half first: the count is latched as that read starts, and the high half comes from the same latch |
  | `0x4004` | write: bit 0 clears the tick, bit 1 the profiling tick |

- **The levels** the card gives the CPU, active low: level L while the
  request register's bit L − 1 is set, and level 6 while the tick is
  set, 7 while the message register is full, 8 while the profiling tick
  is set. The tick is set by each 0→1 edge of the timer's bit n, a jumper
  (**open** which; the profiling tick likewise). Also the message
  register's full flag, the NMI latch, and the message onto the CPU's B
  bus, released at the end of the cycle that reads it; the NMI latch
  clears at the end of the NMI's entry's first cycle.
- **Drawn** only as a fixture of the chip-level simulator (**open**:
  the register block in chips; [19](#19-the-system-half-what-rfc-0040-costs)
  estimates it).

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
| `COND` | 4 | a microbranch condition: LC = 255, R[31], CL, the branch condition or its inverse, MQ[31], LC[3:0] = 15, S, SX = EX, FK[0], FK[1], SX = 15, MQ[0], R[0], MSGT |
| `ARF` `APC` `AR` `AR2` | 1 each | the A bus's driver |
| `PCK` | 1 | bit 0 of the PC on the A bus |
| `SINA` | 2 | the bit into R × 2 |
| `BRF` `BR` | 1 each | register file copy B, R onto B |
| `BL` | 3 | T (word, half, byte) or QH (as is, × 2, upper half, low byte) onto B |
| `BX` | 3 | MQ, `sr`, `fsr`, `far`, the map entry, the interrupt's vector offset, the message register onto B |
| `BS0` `BF1` `BF23` | 1 each | the immediate unit's byte 0, byte 1, bytes 2–3 onto B |
| `RFA` `RFB` `RFW` | 2 each | the register number for each port: `rd`, `R`, SX, constant |
| `RFK` `RFKW` | 6 each | read and write constants (`RFK`'s bit 5, G, stored inverted) |
| `RFWE` | 1 | write the register file |
| `UBR` `UBW` | 1 each | the user's bank for the next cycle's supervisor reads, this cycle's write |
| `LDSX` `LDEX` | 2, 2 | load SX (`rd` or QH[15:12]) or count it; load EX (`R`, QH[11:8]) |
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
| `MEM` `SIZE` | 3, 2 | the memory access (`MEM`'s bit 2 stored inverted, so that a refill is one gate from the uIR) |
| `FNZ` `NSEL` `FC` `CZERO` `CSRC` `FV` `FI` `LFM` `SSET` | 2, 2, 2, 1, 3, 3, 2, 2, 1 | `sr` ([3.5](#35-flags)); `LFM` 1 without a flags load is `SPL`, with `SSET` an interrupt's entry |
| `LDCL` `CLSRC` | 1, 3 | CL |
| `LCL` | 2 | the length class |
| `VAS` `MAPA` | 2, 1 | from `MEM`, filled in by the microcode assembler: the virtual address multiplexer's select (MAR, FPC through the map, the A bus, FPC with the kept page) and a map access's, straight from the uIR |

142 bits of the control store's nine 16-bit lanes; two are free.

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

RFC 0029, 6 and 7, with RFC 0040's interrupts, as the microcode does
them. Every vector is `vbr` plus its offset; `vbr` is special register
15, aligned to 2 KB, `0x8000_0000` after reset.

- **Entering an exception:** `sr` into R and S ← 1, which also clears I
  and T, clears M (except for the message level) and selects bank 0;
  `sp` ← `sp` − 8 and MAR with it; `sr` stored; the saved PC stored and
  the jump to the vector. Where the saved PC is the PC as it is (an
  interrupt, `SWI`, trace) the last cycle stores it straight from the A
  bus as it loads the vector; a fault's, which is less the parcels
  consumed, goes through `TMP1` and R, a cycle more.
- **The vectors:** an exception's is a register file constant with
  `vbr` in it, which `MTSR vbr` rewrites; a level's is `vbr` ORed with
  the offset LT puts on B; `SWI #n`'s is `vbr` + `0x100` + 4n, from one
  of four constants (`vbr` + `0x100` + `0x100`k, for n = 64k to 64k +
  63, in every bank) plus 4(n mod 64), worked out into the bank's `TMP2`
  first (`UBW`) and read back at the jump (`UBR`).
- **Faults:** the fault entry has the number of parcels the instruction
  had consumed, so the saved PC is the instruction's own; FK picks the
  vector: page fault, or address error for a misaligned access. Every
  instruction changes the registers it addresses memory with, the flags
  and the PC only in or after its last access, and FAULT cancels the
  cycle it happens in, so faults are precise.
- **Illegal and privileged instructions** are microcode routines that
  trap from their first cycle. `SWI #n` with n of 128 and up is
  privileged from user mode (RFC 0040, 2.3; **open** the range): its
  first cycle, which works out the vector, also branches on S.
- **Interrupts** ([RFC 0040, 2](0040-rfc-interrupts.md#2-the-cpu)):
  - **Sampled:** the card's levels, its message register's full flag and
    its NMI are registered at every edge (LQ). L is the highest level
    requesting (a 74F148).
  - **Pending** a cycle later: PEND is set if the NMI is, or if I is set
    and L is above IPL. Alongside, LT is loaded with L, the vector's
    offset (`0x40` + 4(L − 1), or `0x04` for the NMI) and MSGT (level 7
    is the highest, a message is waiting, no NMI), in every cycle with I
    set or an NMI, except an exception's first. So it holds what the
    entry was taken for until I is set again.
  - **Taken:** PEND forces the next decode to the interrupt entry. So
    an interrupt is never taken straight after `EI` (I is set at its
    decode's edge), and may be straight after `DI`.
  - **The entry's first cycle** saves `sr` and sets S, as any
    exception's, and also sets IPL to L (not for the NMI) and M to MSGT.
    It branches on MSGT.
- **A level, or the NMI:** the vector is `vbr` | LT's offset, then the
  frame. Six cycles from the forced decode to the decode of the
  handler's first instruction (640 ns). The NMI is acknowledged at the
  end of the entry's first cycle, clearing the card's latch; it leaves
  IPL as it was (**open**).
- **The message level** (RFC 0040, 2.3): with M set, the frame goes on
  the message level's own `sp`. The cycle that stores the PC also reads
  the message register onto B, which releases it; the source goes into
  `r1` and the 24-bit message into `r2`, both the message level's; the
  jump is to `vbr` + `0x100` + 4 × source. Nine cycles (940 ns). A level 8
  interrupt or a trap in its handler enters bank 0 as usual, and `RTI`
  goes back to the message level's registers through M.
- **`SPL #n`** sets IPL to n (privileged).
- **Trace:** TS ← T at every decode that goes ahead; with TS set, the
  next decode is forced to the trace entry, after the instruction.
  Exception entry clears TS with T.
- **`HALT`** loops in a halt microinstruction until an interrupt is
  pending.
- **`RTI`** loads MAR from `sp` in the cycle that checks S, then pops
  `sr` and the PC: five cycles (520 ns).

### 10. Reset and boot

- **At power-up** RUN is off and the control store and decode table hold
  nothing. The I/O processor writes, through the slave port, the
  control store's words that are used, the decode table (through the
  window at `0x7080_0000`), and a boot program for the RAM; then RESET,
  then RUN ([RFC 0027](0027-rfc-io-coprocessor.md)).
- **The reset routine** (control store address 0) sets CTX and BANK to
  0, sets S and clears the rest of `sr`, writes the register file's
  constants into bank 0 and copies those every bank has into banks 1–255
  (one cycle a constant, BANK from LC and `UBW`), sets BANK back to 0,
  sets `vbr` to `0x8000_0000`, and jumps there: physical 0, in the
  window.
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
| 16-bit parts | yes: the registers, latches and buffers ([16](#16-chips)) |
| GALs | no (Emily would rather not) |

Draft 2's own needs added the rest: the register banks, the page map and
the window, precise faults, the forced entries, the decode table for 16-bit
parcels, and the extension parcels read from the queue.

### 12. How fast

All numbers are in [performance.md](0031-rfc-draft-2-cpu/performance.md),
generated by `heron v2_hw report --write`. In short:

- **The suite** (the 18 hand-written programs report 0012 counts, and the
  15 compiled C programs) takes 753 ms on the model, with every cycle as
  long as static timing analysis of the netlist says: 465 ms for the
  hand-written ones (3.03 cycles and 328 ns an instruction) and 288 ms
  for the C ones (2.34 cycles, 263 ns). The length classes are 4, 5, 6
  and 9 ticks; 52% of the cycles take 6.
- **Against draft 1b with the same parts:** the suite's 20 hand-written
  programs take 4.37 million cycles here against 1b's 6.08 million (RFC
  0024): 28% fewer, from fewer instructions (draft 2's) and fewer cycles
  an instruction (the queue and the decode in the last cycle). The
  cycles are longer on average, 108 ns against 97 ns: 52% of them take 6
  ticks (an add that sets the flags, a multiply or divide step, any
  access that may go to the bus). So the time is 473 ms against the
  591 ms of 1b's fast card at microcycle level: 1.25 times as fast.
  Against 1b's fast system at chip level, on the programs that don't
  print, 1.36 times (444 against 602 ms). The exception is mandel, slower
  than on 1b (92 against 82 ms) because of `MULFX`
  ([14](#14-the-tentative-instructions)). Both machines' numbers come
  from static timing analysis of their netlists, at worst-case delays.
- **Where the time goes:** ALU, address and shift work 34%, multiply and
  divide steps 23%, data reads 14%, refills after jumps 9%, extension
  parcels 7%, jumps 6%, data writes 4%, the console's bus transfers 2%.
  The busiest routines are `MULFX` (10%, all of it mandel), the refill
  (9%), `MULS` (8%) and `DIVS` (5%).
- **Code over the bus** takes 2.08 times as long, with the code and data
  on the memory card; with a 256-word instruction cache 1.35 times, and
  with 4096 words 1.34: the rest is the data going over the bus.

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
- **The high half and the remainder go to `r0`** (RFC 0028, 9.9), always
  before `rd`'s result, so that with `rd` = `r0` `rd`'s stays. `DIVS`
  works out the quotient's sign from `rd` and `rs` after the remainder
  is in: with either of them `r0`, the decode table sends it to a routine
  that keeps the remainder in `TMP2` until then, a cycle longer.
- **The register file's constants** (vectors, masks, `0x8000_0000`) are
  written by the reset routine into the register file, so the
  microcode can use a constant wherever it can use a register, without a
  wider immediate unit.
- **Every bank has its own copy of them,** so that the two copies of
  the register file always use the same bank. With the microcode's
  locations stored once, a constant read had to force its copy's bank
  to 0, and each copy needed its own bank bits: a 74F151 per bit per
  copy and eight AND gates. Stored in every bank, the bank bits are one
  74F157 pair for both copies, and the write bank needs no mask: 17
  chips fewer, and the suite 0.5% faster, since the masked bank was on
  the path of constant reads. Software can't tell; the cost is the reset
  routine's copy (0.5 ms), and that scratch must not be live across a
  change of bank, which only the exception entry had to be rearranged
  for.
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
- **The message level's registers are sixteen of their own,** on the
  register file's unused address line A14, rather than a bank: the G
  locations stay shared, so the special registers and the microcode's
  constants need no copies, and no bank is taken from the threads
  ([19](#19-the-system-half-what-rfc-0040-costs) has the bank's costs).
- **The vectors keep `vbr` in them:** each exception's vector and the
  four `SWI` bases are register file constants with `vbr` ORed or added
  in, rewritten by `MTSR vbr` (the `SWI` bases in every bank: a loop of
  255 cycles, rare). A trap's entry then reads its vector as before; only
  a level's needs the OR, with the offset that LT drives onto B.
- **The interrupt decision is a cycle behind the levels:** the card's
  levels are registered at every edge, and PEND a cycle later, so the
  card's outputs and the 74F148 have a whole cycle, and the forced decode
  reads a flip-flop. A level a handler's store clears is out of LQ in the
  second cycle after the store's, before an `EI` straight after the store
  sets I, so a handler isn't entered again for the level it has just
  cleared.
- **The CPU's writes to its own registers take effect at the cycle's
  end,** with the write strobe, and the card's outputs change after the
  edge: the level a store raises is in LQ at the following edge. The
  register-transfer model does the same, so the two match cycle for
  cycle.

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
  saves about 350 microinstructions of the 6,345 (most of them
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

### 15. The netlist and its timing

[studies/v2_hw/cpu.py](../studies/v2_hw/cpu.py) draws the CPU's core in
chips, from the parts of [RFC 0024](0024-rfc-faster-smaller.md)'s `fast`
set: everything in Part I but the bus interface and the slave port. The
control store's write path is tied off (the chip-level simulator preloads
it, as the I/O processor would leave it), and draft 1's I/O page is a
fixture on the card's data bus, answering without a bus transfer; the
same fixture is the CPU card's registers (the request, message and timer
registers and the NMI, [6](#6-the-bus-the-slave-port-and-the-cpu-cards-registers)),
its outputs changing 12 ns after the clock edge that changes them and a
register's read 10 ns after its strobe.

- **Static timing analysis** (`heron v2_hw hw sta`, the case analysis of
  `infra/hw/sta.py`): for each distinct microinstruction, its control
  bits held, and in each state that changes its paths (Q0 empty or not,
  FOK set or not, and for a decode whether a forced entry takes the
  address), the latest arrival at every register's inputs, at the
  register file's latches when they close and its write, at the memory
  write window, and FAULT before the window opens. A three-state bus
  counts from when the drivers of the cycle before turn off. Worst-case
  datasheet delays throughout: 884 microinstructions in 5,404 cases, a few
  seconds.
- **The lengths come from it.** `ticks.json` holds every
  microinstruction's period, and the length classes are picked from
  those ([12](#12-how-fast)). The path estimate (`timing.py`) is kept for
  microinstructions not yet measured and for the levers of
  [17](#17-faster-still). Against it: 5,506 microinstructions take the
  same ticks, 604 fewer, 235 more.
- **The critical paths now:** a decode, 79 ns (4 ticks: the queue's
  head, the decode table, the completeness test, the control store); a
  branch, 88 ns (5); a register file read (37.5 ns), a 32-bit add and the
  register file's write or R, 97–101 ns (5 or 6); an add that sets the
  flags, or a refill, 118 ns (6); a read whose data goes through the ALU
  into the flags, 166 ns (9).

The first netlist, drawn straight from the register-transfer model,
needed 7 to 11 ticks where the estimate said 4 to 6, and not in the
datapath: in the control around it. Each fix changed the design, and
Part I has them:

1. **The prefetch decided from the map.** Whether a word joins the queue
   waited for the map, the window and the slot decode: 85 ns into the
   cycle. FOK and FPPN now keep FPC's page, so a prefetch reads the RAM
   at it and decides from registers. No program's cycle count changed.
2. **The decode from the word being fetched.** With the queue empty, a
   decode took its parcel from the fetch in the same cycle, putting the
   RAM, the decode table and the completeness test in series with the
   control store: 6 ticks for every decode. Now only the refill decodes
   from the word it fetches; any other decode needs its first parcel in
   Q0, and goes to the refill otherwise. That costs 2% more cycles on the
   suite (crc 8%), against every decode at 6 ticks.
3. **The completeness test** was ten gates from the queue's head to the
   control store. The decode table's length now selects a precomputed
   answer in one 74F151, and a jump forces the refill directly.
4. **FAULT came after the write window opened**, a dozen gates after the
   virtual address: no memory write worked. The map's V, W and X now select the fault
   in a 74F151 whose inputs carry the access's kind, LOCAL comes from a
   74F521, and FAULT is two gates after them.
5. **The register file's read address** went through two multiplexers
   and three gates for the bank: the data came at 58 ns. One 74F151 a bit
   and the bank in a register bring it to 37.5 ns; `UBR` moved a cycle
   early for it.
6. **Z and CL** were a tree of gates and a multiplexer after the zero
   detect. Kept as four byte bits, they are formed after the register.
7. **The selects of the virtual address and the map's address** came
   through the `MEM` decoder; `VAS` and `MAPA` now give them straight
   from the uIR, and `MEM` stores its top bit inverted so that a refill
   is one gate.
8. **The decoded B bus enables** were up to four gates deep: the cycle
   before's driver stayed on 25 ns into the next cycle, fighting the new
   one. The chip-level simulator found it (its contention log), and the
   analysis then counted turn-off times. Now every enable is one level.
9. **Two hazards** the simulator found where the analysis can't: T's
   latches opened for a few nanoseconds at the start of the cycle after a
   read and took the new address (now from tick 2); the write window's
   flip-flop toggled in a 4-tick cycle and opened at the next cycle's
   start (now it can't).

Still open:

- **The register file's read latches** close a gate after RW turns the
  SRAM's outputs off. The SRAM may stop driving at once (no minimum for
  tOHZ), so the latches rely on the lines holding their charge for a few
  nanoseconds; bus-hold cells, or closing the latches a gate earlier,
  would remove the doubt.
- **Contention** of up to 6 ns remains where two of the T lanes' enables
  change at once in a read; short, and between drivers built for it.
- **The bus interface:** its hold at tick 3 is as RFC 0024 drew it,
  not yet in this netlist.

### 16. Chips

Counted from the netlist (`heron v2_hw hw bom`), against the estimate
this RFC first gave for the same sections. A 16-bit part counts once: a
half of one (each IS61C6416AL byte, each 8- or 9-bit half of a 74ABT16xxx)
counts ½ where it is used, and pairing the halves makes the core 394
(382 without the simulator's clock and fixtures; 366 before RFC 0040).
A package of gates counts in the section of its first gate, so a change
to the gates can move a chip between sections:

| Section | Netlist | Estimate | |
|---|---:|---:|---|
| Control store, decode table, uIR | 19 | 19 | 10 SRAMs; the uIR is 9 × 74ABT16374 |
| Sequencer, IR, conditions, forced entries, interrupt request | 39½ | 10 | the levels, the 74F148, PEND, LT |
| Clock and reset | 13 | 12 | |
| Register file and its addresses | 41½ | 18 | a 74F151 per register bit and copy, the bank shared; the message level's line; latches and write buffers |
| A bus | 7 | 10 | |
| B bus and immediate unit | 36 | 24 | |
| ALU, its control, MQ | 21 | 14 | |
| Result multiplexer | 18 | 18 | |
| R, T, MAR, LC, SX, EX | 26 | 24 | |
| PC, FPC, the fetch's translation, the queue | 52½ | 28 | |
| Flags, IPL, CL, branch condition | 42 | 12 | |
| Memory: virtual address, map, window, faults, RAM, store data, CTX, BANK | 76½ | 42 | 7 SRAMs |
| **The netlist's core** | **394** | **231** | |
| Bus interface, master | (30) | 30 | not drawn: the estimate |
| Slave port, control store writes, control register | (14) | 14 | not drawn: the estimate |
| CPU card's registers | (17–27) | | not drawn: [19](#19-the-system-half-what-rfc-0040-costs)'s estimate |
| **Total** | **about 460** | **about 275** | |

- **The estimate was low by two thirds** with 8-bit parts: 440 chips.
  The 16-bit parts it assumed take 55 of that back: 41 registers, 52
  buffers, 13 latches and 6 registers with enables are 57 packages of
  74ABT16374, 16823, 16244 and 16373 instead of 112. Ten buffers whose
  outputs need two enables at once stay 74ABT541s (a 16244 has one
  enable per four bits). The rest is real: the register file's
  addressing and two-phase write, the translation and fault logic, and
  gates the timing fixes of
  [15](#15-the-netlist-and-its-timing) duplicate so that late signals
  come in last.
- **What the 16-bit parts cost.** No time: the suite's time didn't
  change. Of the 858 microinstructions measured, 797 are faster (by
  up to 2.5 ns: a 74ABT16374 clocks out in 6.2 ns where a 74ABT377 took
  7.3) and none is slower by more than 0.3 ns or needs another tick.
  Their outputs turn off later (a 16373 in 8.1 ns against a 573's 7.1)
  and a 16244's turn on sooner (4.8 against a 541's 5.9), so the
  register file's latches and the other drivers of the A and B buses
  overlap by up to 3.3 ns as they hand over, where they overlapped
  about 1 ns: the simulator logs about twice the contention (29 µs to
  56 µs in `strings`), the worst still the T lanes' 6 ns. And they come
  only in fine-pitch packages (SSOP and TSSOP, 48 and 56 pins).
- **The queue without multiplexers** (Part I, [4](#4-fetch-and-decode)):
  the 8 × 74F157 of Q0's input and the 8 × 74F153 of the head parcel
  become 74ABT16244 halves onto a three-state QH and a head pointer, 7
  chips fewer. It costs no time: the head parcel arrives sooner (a refill
  is 0.6 ns shorter) and the load enables no longer follow the decode.
  The 16244 turns off as fast as it turns on, which is why the slots
  drive QH through one rather than with their own outputs (a 16823's
  8.7 ns turn-off made a refill 7 ticks); as its drivers hand over at a
  decode, the simulator logs many more overlaps on QH, all under 2 ns
  (58 µs of overlap in `strings`, against 56).
- **The size decode:** a 74F138 decodes `SIZE` into BYTE_n, HALF_n and
  WORD_n, the misalignment test is SIZE1 · (VA0 + VA1 · SIZE0), and a
  half's byte lanes come from NORs of HALF_n. That takes four inverters
  and four 74F08 sections for the 138, one chip fewer, since each of
  those part types drops a package; no microinstruction's timing
  changes. Byte enables from multiplexers (a 74F151 or 153 a pair of
  lanes) would save nothing: they replace about as many gates as they
  cost, and put 1.4 ns more on the write enables.
- **Against draft 1b:** its CPU card as built is 269 chips, with 8-bit
  parts; this one about 460, for a 32-bit memory path, the queue, the
  page map and the window, the register banks and the writable control
  store, the short cycles, and RFC 0040's interrupts and timer.
- **MAR off the A bus:** no microinstruction put MAR on the A bus, so
  its four 74ABT16244 halves went, and its field: 2 chips.
- **SX's load:** `LDSX`'s code for loading SX from `R` was never used, so
  counting SX took that code instead of a field of its own, and SX's
  load multiplexer is one 74F157 instead of two 74F153s: a chip, and
  a second free bit in the microinstruction.
- **Room for microcode:** the control store's SRAMs have 64K words, of
  which the sequencer reaches 8K (`NEXT` is 13 bits): 6,345 are used.
  The two free bits can carry `NEXT[14:13]` into the address's top bits,
  each as two gate levels beside the forced entries' U (`NEXT` and "not
  forced", NORed with U), which the timing analysis put at no tick for
  any microinstruction: 32K words for 2 chips, when the microcode needs
  them.
- **Where to look for fewer:** the register file's
  register bits through two levels again (a few chips, for 7 ns more in
  every register read); the T lanes and QH buffers onto B through
  multiplexers; PEND through a 74F85 (about 1,
  [19](#19-the-system-half-what-rfc-0040-costs)).

### 17. Faster still

What's left after the parts, the queue and the decode in the last cycle
is spread out ([12](#12-how-fast)): no lever is worth more than a few
percent. The first two rows are estimated on the same profile with the
path estimate, not the netlist
([performance.md](0031-rfc-draft-2-cpu/performance.md#what-some-changes-would-buy));
the branch-target adder from the profile:

| Change | Suite's time | Chips (*estimate*) |
|---|---:|---:|
| Z and V from registers: RES and the operands' signs clocked, Z and V worked out after the edge | −1.2% | 4–6 |
| the register file's addresses a cycle early, from the control store's output | +0.1% | about 6 |
| both | −3.2% | about 12 |
| a branch-target adder for `BRA`, `Bcc`, `BSR` and `DBNZ` | −2.9% | 15–20 |
| a tag fault ([14](#14-the-tentative-instructions)) | the tagged operations in 1 cycle | about 2 |
| `MULFX` with a routine per count | mandel −15% or so | none |

- **The 6-tick cycle,** in the netlist: a register file read (37.5 ns:
  the 74F151 address multiplexer, the SRAM, the latch), the 32-bit add
  (51 ns through the 74F182s) and RES (8 ns) make 97 ns, so an add into
  the register file or R is 5 ticks; setting the flags takes a compare
  more, 118 ns, and every access that may go to the bus is 6 by rule.
  The netlist already keeps Z as byte bits, half of the first lever;
  the overflow is still worked out in the cycle. Registering the register
  file's address too would take some 15 ns off every register read, but
  the cycles it shortens are mostly the ones the flags or memory keep at
  6, which is why the two levers save more together than apart.
- **A faster adder:** 74AS181 with a 74AS882 lookahead would roughly
  halve the add, but neither is in the repository's timing data yet.
- **A branch-target adder** (performance.md, *Refills*): about 3% net,
  for some 15–20 chips; not recommended yet.
- **Code over the bus** costs 2.1 times as long without the cache; a
  256-word cache takes most of that back, and a bigger one adds nothing
  on the suite (the rest is data over the bus).

### 18. How it was checked

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
- **The netlist on the chip-level simulator** (`heron v2_hw hw test`):
  every program of the suite, the system tests, `isanotes` and the
  interrupt program run from reset as on the register-transfer model,
  cycle for cycle: the same decodes at the same cycles, output, registers
  (the message level's too), flags, PC and all of the RAM. The system
  tests take every level, nesting, IPL and `SPL`, level 8 and level 7
  from its request bit, a message with its source and its registers, the
  NMI, `vbr` with a second table, the `SWI` range, the board information,
  the timer's count and `HALT` waiting for its tick; the timer ticks on
  the bit a program's `tick-bit` names, in both models. At the length classes static timing
  analysis gives, the simulator, with the same worst-case delays, finds no
  timing violation; at long cycles (`--lengths 10,11,12,14`) they match
  too, which separates logic from timing. Its log of bus contention
  found the turn-off problem of [15](#15-the-netlist-and-its-timing).
  The simulator powers every flip-flop up at random; hello, the system
  tests and the interrupt program also run from six more power-ups (three
  for the interrupt program). They found the clock generator's lock-up
  ([2](#2-clock-and-cycles)): 52 of the 128 states of its flip-flops and
  counter kept two pulses going while the cycles were 4 ticks, so that
  every register file write failed. They also found reset released
  asynchronously: when it rose within a few nanoseconds of a clock edge,
  the card's timer and the CPU disagreed about which edge ended reset,
  and the timer's tick came a cycle off; reset is now released at a CLK
  edge.
- **`ticks.json` is current:** `heron test v2_hw` runs the analysis and
  compares it with the table the microcode uses.

### 19. The system half: what RFC 0040 costs

RFC 0040's choices, and the alternatives it asks about, on this CPU.
Chips in the core are counted from the netlist against `main`'s, which
had one interrupt request; a gate counts as its share of a package.
Cycles are measured on the register-transfer model, nanoseconds at the
lengths static timing analysis gives. What isn't built is estimated from
parts, and says so.

**The core's chips:**

| Feature | Chips | What |
|---|---:|---|
| eight levels, IPL and `SPL` | 10.3 | the levels registered (½), a 74F148 for the highest (1), L = its code + 1 (1), "a level above IPL" and PEND (3.1), LT (1), IPL's register and multiplexer and their control (3.7) |
| `sr` as RFC 0029 lays it out | 1 | bytes 0 and 3 onto B, byte 2 zero |
| the NMI | 1 | the vector offset's gating, the acknowledge, LT's bit; its latch is on the card |
| the message level | 5.8 | MSGT and M (1.4); its sixteen registers (4.4: two 74F151, a 74ABT74, gates) |
| `vbr` | 0 | microcode: constants with `vbr` in them; the offset driver onto B (½) is a level's anyway |
| no bus errors | −0.8 | |
| **in all** | **17.7** | 366 packages to 385 |

Two of [16](#16-chips)'s findings then took three back (MAR off the A
bus, SX's load multiplexer): 382, or 394 with the chip-level simulator's
clock and fixtures.

**Time.** The suite's time is unchanged: 752.97 ms against 753.06 ms
before, with the timing analysis' lengths. Two paths needed care:

- **The message level's registers** first had their select as gates in
  front of the register file's read address, 13 ns onto the critical
  path: 1,000 microinstructions a tick longer and the suite at 813 ms.
  The select is now a flip-flop loaded at every edge, as the read bank
  is, and a constant read's G bit comes from a faster copy beside it;
  808 of the analysis' cases lose 1.5 ns of slack at the control store's
  output, and no microinstruction needs another tick.
- **PEND** is set by a ripple of seven AND gates ("a level above k" for
  each k) and a 74F151 by IPL, 73 ns into the cycle: within the shortest
  class (80 ns), but the longest path in 79 of the analysis' cases. A 74F85 comparing L − 1 with IPL would bring it to about 45 ns
  and save about one chip; it isn't in the chip library yet.

**The entries,** from the forced decode or the instruction's first
microinstruction to the decode of the handler's first instruction:

| Entry | Cycles | ns | Before |
|---|---:|---:|---|
| a level, or the NMI | 6 | 640 | the one request: 6, 640 |
| the message level | 9 | 940 | |
| `SWI` (either range) | 6 | 660 | 7, 740 |
| a fault | 7 | 740 | 7, 740 |
| trace | 5 | 560 | 6, 640 |
| `RTI`, also back into the message level | 5 | 520 | 6, 600 |

`vbr`'s OR would have made a level's entry a cycle longer; storing the
saved PC straight from the A bus (Part I, [9](#9-exceptions-interrupts-and-trace))
took a cycle off every entry that saves the PC as it is, and `RTI` loads
MAR in the cycle that checks S. The control store has 49 words more
(`SPL` 27, `MTSR vbr` 18, the message level's entry 7, the faults' frame
4, now that it no longer shares with the entries that store the PC
straight, the reset routine −4, `RTI`, trace and the interrupt entry −1
each): 6,345.

**Alternatives,** for RFC 0040's choices:

- **Three fixed levels** (the message, the timer and one for the rest),
  still with IPL and `SPL`: about 2.5 chips fewer in the core (the
  74F148, L's incrementer and the compare go; a few gates per source
  come back), and the card's request register becomes one bit
  (*estimate*).
- **Two masks, ARM's IRQ and FIQ,** without IPL: about 4–5 chips for
  all of the interrupt logic, against about 11 (*estimate*).
- **The NMI setting IPL to 8:** about 1 chip (LT's level forced to 8),
  no cycles (*estimate*).
- **The `SWI` range:** `SWI #n` has its own decode entry for every n, so
  the check is a microbranch on S in its first cycle, to a shared
  privilege trap: a word at most, no cycles.
- **The message level's registers,** RFC 0040, 2.4:
  - *sixteen of their own* (built): 4.4 chips, no time. G's constants
    and the special registers are the same; `MTUR` and `MFUR` reach the
    user's bank as before; BANK and CTX don't change; no bank is taken.
  - *bank 255*, forced through the read bank's register: about 2 chips
    of OR gates, no time; but G reads in the message level then read
    bank 255's copy, which lacks `ctx`, `bank`, `mapa`, `vbr` and the
    exceptions' vectors (bank 0's alone), so `MFSR` there reads stale
    copies unless every `MTSR` of one also writes bank 255 (about 4
    cycles each); and a thread loses bank 255.
  - *none*: no chips; the handler saves what it uses, two cycles a
    register there and back.
- **The message onto B** rather than as a load: the register drives the
  CPU's B bus and is released at the end of that cycle; as a load it
  would take MAR set to its address and a memory cycle, a cycle or two
  more, and a write to release it.

**The CPU card's registers** (*estimates* from parts; the chip-level
simulator has them as a fixture):

| Block | Chips | |
|---|---:|---|
| decode: read enables, write strobes | 2 | two 74F138 |
| the NMI bit and its acknowledge | ½ | RUN and RESET are there for the boot |
| board information | 1 | a 74ABT16244 on jumpers |
| request register with RFC 0040's set and clear masks | 4–5 | a register, (q · ¬(clr · d)) + set · d in 16 gates, a read buffer |
| request register as a 74x259, one level a write | 1½ | the level and set or clear in the data; a read buffer |
| message register | 4–6 | 32 bits as two halves with their own strobes (a 16-bit master's low half goes straight in: nothing reads it until the high half sets full), two state bits, read buffers (none if only the CPU reads it) |
| timer counting BCLK/4 (240 ns) | 6 | four 74HC590 on one clock, their enables from the lower stages' carries; a prescaler and the two ticks in 74ABT74s |
| timer counting BCLK (60 ns) | 11 | eight 74F161 and two 74ABT16374 for the snapshot, the ticks |
| the levels ORed, zero for the small registers' upper half | 1¾ | |
| **in all** | **17–27** | the 259 and BCLK/4, to masks and BCLK |

- **The timer's read: a snapshot.** The 74HC590 has an output register
  and three-state outputs, but it can't count BCLK: TI's SN74HC590A
  (SCLS039F) is specified to 16 MHz at 4.5 V over temperature (13 MHz
  for the SN54), against BCLK's 16.7, with CCLK to RCO up to 38 ns and
  CCKEN's setup 25 ns, and the datasheet cascades more than two stages
  by rippling RCO into the next stage's clock. A rippling chain can be
  latched mid-carry, the torn read the snapshot is for. So:
  - *counting BCLK/4*, 240 ns: all four stages on one clock, each
    stage's enable the OR of the lower stages' (active-low) carries, and
    RCLK tied to the counter's clock, which the datasheet allows ("the
    register is one clock pulse behind the counter"): the register always
    holds a settled count, held while a 16-bit master reads its two
    halves. About 6 chips.
  - *counting BCLK*, 60 ns: synchronous 74F161s and a 32-bit register
    for the snapshot, about 11.
  - *reading the high half twice* saves the register, not the counters,
    and needs buffers onto the bus instead, and software.
  The tick's jumper taps the register's outputs, a count behind.
- **The local path** costs the core nothing: it already decodes the I/O
  page on the card's data bus.

### 20. Open questions

1. **Trace after a trapping instruction:** a `SWI` or a fault enters its
   handler with T cleared, so the trace exception comes only when
   `RTI` returns to traced code. Is that what RFC 0029 means?
2. **Changes to the map, `ctx` or S and the queue.** Words already in the
   queue were fetched under the old mapping, and FPC's page was
   translated under it: code that changes the mapping of the code it runs
   must jump afterwards. Say so in RFC 0029?
3. **The instruction cache:** whether to have it, its size, and DMA
   coherence ([7](#7-the-instruction-cache-open)).
4. **The tag fault** ([14](#14-the-tentative-instructions)), if the tagged
   operations stay.
5. **RFC 0040's open points,** as this CPU has them
   ([19](#19-the-system-half-what-rfc-0040-costs) has what each costs):
   1. the message level's registers: sixteen of their own here, or bank
      255;
   2. the NMI leaves IPL as it was here, or sets it to 8;
   3. `vbr` is special register 15 here;
   4. `SWI #128`–`#255` are privileged from user mode here;
   5. the card's register offsets, the control store window at
      `0x7080_0000`, and the board information's layout
      ([6](#6-the-bus-the-slave-port-and-the-cpu-cards-registers));
   6. the request register: set and clear masks (the model), or one level
      a write (a 74x259, about 3 chips fewer);
   7. the timer: a snapshot here, or reading the high half twice; counting
      BCLK (60 ns, about 11 chips) or BCLK/4 (240 ns, about 6, with
      74HC590s); and which bit the tick's jumper picks by default (the
      test programs use bit 10, for speed).
6. **The breakpoint register** (`bkpt`, RFC 0029, 4): not built; it
   would compare the PC at every decode (about 5 chips), and needs a
   special register number now that `vbr` has 15.
7. **`CAS`, `BCOPY` and the FPU's cells** (RFC 0028, RFC 0029): not
   built; illegal here.

### 21. Next steps

1. The bus interface, the slave port and the card's register block in
   the netlist, and the chip-level system: the CPU card on the bus with
   the memory card and the I/O processor, booting from flash, with the
   I/O processor's firmware against this card's registers.
2. The open points of [15](#15-the-netlist-and-its-timing): the register
   file latches' hold, the remaining contention.
3. The kernel of report 0020 ported to draft 2, on this model, for the
   supervisor architecture under real use.
4. PEND through a 74F85, once the chip library has it
   ([19](#19-the-system-half-what-rfc-0040-costs)).
5. Decide the levers of [17](#17-faster-still) and the open questions
   above.
