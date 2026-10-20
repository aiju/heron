---
number: 47
type: rfc
title: "Chibi Heron: draft 2 on one board of 120 chips"
status: draft
date: 2026-10-20
context:
  studies: [chibi, v2_isa, pcb_columns]
  commit: 65ebcd9
depends-on: [28]
---

# RFC 0047: Chibi Heron: draft 2 on one board of 120 chips

The smallest Heron so far: draft 2's user instruction set
([RFC 0028](0028-rfc-draft-2-isa.md)) on one board, with 2 MB of RAM,
640 × 480 × 4 VGA through a 256-colour palette, a microcoded copper,
two serial ports, PS/2 ports for a keyboard and a mouse, a timer, a
sound chip, a CompactFlash slot, a boot flash and a debugger in
microcode. Heron Mini ([RFC 0041](0041-rfc-heron-mini.md)) does draft 2
in 375 packages; the aim here was 120. It is a fresh design, not a
reduction of the earlier ones; only `infra/` is shared.

Emily's brief: a 16-bit datapath with 32-bit registers, little of the
system architecture beyond interrupts, as few internal buses as can be
(an operand latch on the ALU), no microcode pipelining, no prefetch,
perhaps horizontal microcode, ATF22V10s, DIP but for the 22V10s and the
flashes in socketed PLCC and the RAM, and performance in mind without a
target clock. The design went through a **first cut**, one fixed cycle
of 158.9 ns on 70 packages ([17](#17-the-first-cut)). Then, with Emily's
decisions, came this **two-halves machine**: a microinstruction is a
32-bit operation done as two 16-bit halves, on variable-length cycles
counted in ticks of a 50.35 MHz clock.

The study is [studies/chibi](../studies/chibi/README.md): the microcode,
a register-transfer model checked against draft 2's instruction-level
simulator, a chip-level netlist of every chip on the board, its static
timing analysis, and its placement on [RFC 0046](0046-rfc-column-grid.md)'s
grid. Part I specifies the machine as the netlist builds it; Part II is
what it measures, why it's built so, and what's left for Emily. The
tables are in [performance.md](0047-rfc-chibi-heron/performance.md) and
[placement.md](0047-rfc-chibi-heron/placement.md).

## Summary

- **119 packages:** 118 chips and the CompactFlash socket. 60 of them
  are ATF22V10Cs. The budget's last place is free.
- **It works, at chip level.** The netlist runs the whole program suite
  on the chip-level simulator exactly as the model does: the output,
  the registers, the flags, the RAM, and every instruction fetch at the
  same cycle, with no timing violation. The model in turn runs the
  suite as draft 2's simulator does. ODT, the copper and the PS/2
  keyboard are tested at chip level too.
- **Timing:** static timing analysis with worst-case datasheet delays
  gives every distinct microinstruction its length in ticks. A half
  takes 2 or 3 ticks (an I/O access 5), and phase F 3. The control
  store's length fields are filled from that table.
- **Speed:** the suite takes 3.7 times as long as on the full Heron
  ([RFC 0031](0031-rfc-draft-2-cpu.md)), against 7.7 for the first cut.
  That's 2.07 times faster than the first cut. Ordinary code runs at
  400–570 ns an instruction, about 2 MIPS. A microinstruction averages
  6.45 ticks, 128 ns ([13](#13-how-fast)).

## Contents

- Part I: Specification
  [1. Overview](#1-overview) ·
  [2. Clock and cycle](#2-clock-and-cycle) ·
  [3. Control store and sequencer](#3-control-store-and-sequencer) ·
  [4. Datapath](#4-datapath) ·
  [5. Flags and system state](#5-flags-and-system-state) ·
  [6. Addresses and memory](#6-addresses-and-memory) ·
  [7. The I/O space](#7-the-io-space) ·
  [8. Interrupts and exceptions](#8-interrupts-and-exceptions) ·
  [9. Video and the copper](#9-video-and-the-copper) ·
  [10. Reset and boot](#10-reset-and-boot) ·
  [11. ODT and debugging](#11-odt-and-debugging) ·
  [12. Parts](#12-parts)
- Part II: Discussion
  [13. How fast](#13-how-fast) ·
  [14. Timing](#14-timing) ·
  [15. Why it's built so](#15-why-its-built-so) ·
  [16. How it was checked](#16-how-it-was-checked) ·
  [17. The first cut](#17-the-first-cut) ·
  [18. The board](#18-the-board) ·
  [19. Proposals](#19-proposals) ·
  [20. Open questions](#20-open-questions) ·
  [21. Open tasks](#21-open-tasks)

## Part I: Specification

### 1. Overview

A microcoded CPU with a 16-bit datapath around one internal bus, D, that
does a 32-bit operation as two halves:

- the **register file**: four SRAMs, a pair for the low halves of the
  registers and a pair for the high halves. It holds draft 2's 16
  registers in two banks, 16 microcode temporaries, and a task's private
  bank. It drives D and is written from the result registers;
- the **ALU**: four 74F181s and a 74F182. It takes D as A and the
  **operand latch** L as B. L is four 22V10s, a register for each half,
  loaded from D;
- the **result registers**: four 22V10s, one pair for the low half's
  result and one for the high half's. They can shift the result right a
  bit or extend a byte. Two 74ABT574s keep the last half's result with
  its bytes swapped (SWP), for shifts by 8;
- the **immediate unit**: three 22V10s. It puts 32 constants (and the
  instruction's fields shaped into them) on D, a half at a time;
- **PC** and **MAR**: counters in 22V10s, loaded from the ALU, driving
  the address bus;
- the **memory data bus**, MD, joined to D by two 74ABT245s and a third
  that crosses the bytes. It holds the RAM, the devices and the video's
  buffer.

The control store is horizontal: nine flashes give the 72 bits of a
microinstruction straight to the datapath, without a pipeline register.

### 2. Clock and cycle

The master clock is a 50.35 MHz oscillator (twice VGA's pixel clock); a
**tick** is 19.86 ns. A jumper takes MCLK from an external clock
instead, for debugging. The clock generator is two 22V10s on MCLK:
`U_CGA` (the phase and the tick in it) and `U_CGB` (the clocks and
strobes). A microinstruction's **cycle** has up to three phases:

- **Phase F**, 3 ticks. The control store's outputs settle for the new
  step. The last cycle's results are written: the low half's to the
  register file in tick 1, the high half's in tick 2. The video reads
  the RAM in ticks 1–2. It is 2 ticks longer when the video's buffer is
  empty (a second read, ticks 3–4), and 1 longer when a task starts or
  ends.
- **The low half**, LEN + 1 ticks (LEN a 2-bit field: 1–4). It does to
  the low 16 bits what the microinstruction says.
- **The high half**, HLEN ticks (0: none, so a 16-bit operation). It
  does the same to the high 16 bits: a register read takes the other
  half, a result goes to the other pair, the carry in is the low half's
  carry out, the immediate is the constant's high half, and MAR and PC
  load their high bits.

A half that accesses the I/O space takes 5 ticks, whatever its field
says. The slow devices hold it longer: the timer and the palette 10
ticks, the CF card 8 at PIO mode 4 and 32 at PIO mode 0. The clock
generator ends a half at its count, or once the slow devices let go
(HOLD). CLK0 rises as phase F starts and clocks the sequencer; HCKA ends
the low half, HCKB the high half, HCK either. The clock generator isn't
reset: it runs through reset.

LEN and HLEN are the timing analysis's: each distinct microinstruction
has as many ticks as its paths need ([14](#14-timing)).

### 3. Control store and sequencer

**The control store** is nine SST39SF040s (512K × 8, PLCC-32), addressed
by

$$\{\text{PAGE}_{1:0},\ N_{3:0},\ \text{OP}_{7:0},\ \text{STEP}_{4:0}\}$$

19 bits: a **block** of 32 steps for each opcode, dispatch nibble and
page. The 72-bit word's fields:

| Field | Bits | |
|---|---:|---|
| DS | 3 | D's source: none, register file, memory, immediate, the address bus (PC read back), PC's high bits, the flags word, SWP |
| SZ | 1 | the access is a byte |
| IMMF | 5 | the immediate's format |
| RS, KR, HR | 2, 5, 1 | the register read: K, d or s; the K number; the half |
| WS, KW, HW, WEN | 2, 5, 1, 1 | the register write, the same way |
| AOP | 5 | the ALU's operation (A = D, B = L) |
| SISEL, RM | 2, 2 | the result: as is, shifted right (bit 15 in: 0, C, D15 or the carry out), a byte zero- or sign-extended |
| FL | 5 | the flag operation |
| LDL | 1 | L's half ← D |
| MOP | 3 | memory: none, read at MAR, write at MAR, read at PC, fetch, PC on the bus, load the instruction register from a read at MAR |
| AXP, AXM | 2, 2 | PC's and MAR's halves ← the ALU; MAR + 2 |
| IRN | 3 | the register byte: N ← s, d + 1, s − 1, the index parcel's fields |
| SEQ, CND, JT, PT | 2, 5, 5, 2 | next, jump, end, jump at a task point; the condition; the target step and page |
| HALT | 1 | stopped (an LED, and the simulations' end) |
| LEN, HLEN, HX | 2, 2, 2 | the halves' ticks; the high half's variant: zero-, sign- or immediate-extended, with no access |

**The sequencer.** `U_IRL` and `U_IRH` hold the opcode and the
register byte (d, s). `U_NG` holds the dispatch nibble N, `U_STEP` the
step and page. `U_COND` gives the condition: the flags, IRQP, d ≠ s, A0,
ODT and I. A fetch loads the instruction register and enters page 0's
step 0 of the new block, or page 3's when an interrupt is pending
(IRQP). Pages 1 and 2 of a block are reached only by jumps. Page 3 is
the same in every block: the interrupt entry, HALT's wait, the
exception entry, ODT's entry and reset.

**Tasks.** A task is microcode that runs between two microinstructions
of an instruction, without its help. One task exists: the copper
([9](#9-video-and-the-copper)). At a **task point** (SEQ end, or a jump
marked so: the long loops of multiply, divide, shifts, SAVE and
RESTORE), if COPREQ asks, TASK sets. The sequencer's registers then hold
and let go of the control store's address. `U_TASK`'s step and page,
and two 74ABT541s putting opcode 00 and N 8 on it, take over, from page
1's step 0 (page 0's is the illegal instruction 0x8000's). The task's SEQ
end clears TASK and the instruction goes on where it was. A task uses
its own register bank (RA6 = TASK), ST and the internal carry IC, and
MAR; it puts L back. At a task point MAR and the flags but ST and IC
are dead; L is live. The handover is break before make: the instruction
register's GALs let go as TASK sets and take the address back only once
TASKD (TASK a stage later) has cleared too, and the 541s drive only
once both are set.

### 4. Datapath

**The register file:** four CY7C199C-12 (32K × 8), addressed by
`U_RFA0-2`: the register's number from K, d or s, and its bank. RA6 is TASK (a task's bank), RA7 the
bank bit B for draft 2's 16 registers (not for the temporaries). Phase F
writes the low half's result in tick 1 and the high half's in tick 2
(`RFWL_n`, `RFWH_n` from the clock generator). `U_RFW`'s chip enables
keep out the pair a write doesn't take.

**The ALU** computes D op L, 16 bits, through the 74F182's carry
lookahead. `U_ALUC` decodes its operation, the carry in (0, 1, C, IC, or
in the high half the low half's carry out, HC) and the shift's bit in.
`U_ZERO` detects a zero half. 31 operations: pass A or B, add, subtract
and their carry and IC forms, the logic operations, A + A (with or
without a carry in), increment, decrement, zero, ones, not, and the
sign-dependent EXT and SEXT that the multiply and divide routines use.

**The result registers:** `U_YLO`/`U_YHI` take the low half's result at
HCKA, `U_YBLO`/`U_YBHI` the high half's at HCKB. Each drives D in its
tick of the next phase F for the register file, swapped by the cycle's
HW so that a result can go to either pair. `U_YS0-1` (74ABT574) take
every half's result with its bytes swapped, for the next
microinstruction (DS = SWP).

**The immediate unit** (`U_IMML`, `U_IMMH`, `U_IMMX`): 32 formats, each
a 32-bit value, low half then high half. They are small constants (1, 2,
4, 6, 8, 16, 31, 32, 64, −1), the instruction's 4-bit fields scaled and
signed (Q4, NQ, SC4, B8, DB, SH0, SH1, U7), the vectors, the interrupt
controller's address, and SXST, the high half's sign from ST.

### 5. Flags and system state

`U_FLG` holds N, Z, C and V, and I (interrupts enabled), with two flags
for the microcode: IC, an internal carry, and ST, a test bit. `U_SYS`
holds B (the register bank), BI (the bank interrupts enter), INIT
(reset is over) and IRQP (an interrupt or ODT pending, registered at
every cycle's end). The 5-bit FL field selects one of 28 operations (C
and Z from an add, N and Z, each flag from "not zero", ST from a bit,
the entry's I ← 0 and B ← B | BI, …). Its codes were chosen by annealing
so that each flag's equation fits its macrocell. Each low-half
operation has a high-half form (ADDLO's ADDHI, STZ's ST ← ST ∧ z, …) for
32-bit results.

**The flags word** (read with DS = FLW, written by MTSR): bit 0 V, 1 C,
2 Z, 3 N, 4 I, 5 B, 6 BI, the rest 0. B is an extension of draft 2: a
second bank of r0–r15, so that an interrupt handler (BI set) has its
own registers and stack pointer. Software changes banks by writing the
flags word; the entry saves the flags word and RTI restores it, so B
comes back with the rest.

### 6. Addresses and memory

The address bus has A20–A0 and A31. **PC** (bits 20–1) is three 22V10s
(`U_PCA-C`), **MAR** (bits 20–0 and 31) three more (`U_MARA-C`):
counters that load a half from the ALU at the half's end, PC counting by
2 on a fetch or a read at PC, MAR by 2 when asked. `U_ADC` decodes their
operations and which of them drives the address bus (PC for fetches and
reads at PC, MAR otherwise). In phase F the video drives A20–A1. PC
reads back onto D through two 74ABT541s (bits 15–0) and `U_PCC`'s pins
(bits 20–16).

Draft 2's addresses are 32 bits; the board decodes A20–A0 and A31.
**A31 = 0 is RAM**, 2 MB repeated through the low 2 GB; **A31 = 1 is
the I/O space**.

**The RAM** is four AS7C4096A-12 (512K × 8, SOJ-36), two rows of two
byte lanes, 1M × 16. A20 picks the row: it is row 0's chip enable
directly, and `U_MEMC` inverts it for row 1. A word is two halfword
accesses, at MAR and MAR + 2, one a half. A byte access steers the odd
byte across (`U_XS`) and zero-extends it. `U_MEMC`, on the master
clock, gives the RAM's write enables and the I/O strobes, from a half's
second tick to its end.

**Alignment** is checked where an address is computed, in the
microinstruction that loads MAR: misaligned words and halfwords trap
(address error) before anything changes, and so do odd jump targets.

### 7. The I/O space

I/O devices are 8 or 16 bits on MD, at even addresses, selected by
`U_IODEC` from A31 and MAR's bits 20–18. `IORD_n` and `IOWR_n` run from
the half's second tick to its end. ADS, the same strobes a tick later,
latches the UARTs' address and chip select (the TL16C550C's ADS input):
they hold for the strobe's end while the address bus changes.

| Address | Device |
|---|---|
| 0x0000_0000–0x001F_FFFF | RAM, 2 MB (and its repeats to 0x7FFF_FFFF) |
| 0x8000_0000 + 2n | UART 0's register n (TL16C550C, on MD7–0) |
| 0x8004_0000 + 2n | UART 1's |
| 0x8008_0000 | PS/2: the keyboard's byte (read; a write clears the receiver) |
| 0x8008_0002 | PS/2: the mouse's byte |
| 0x8008_0004 | PS/2: the keyboard port's control and status. Read: bit 0 the clock line, 1 the data line, 2 a byte waiting, 3 a framing error; write: bit 4 pulls the clock low, bit 5 the data |
| 0x8008_0006 | PS/2: the mouse port's |
| 0x800C_0000 | the video's control (write, a halfword): bit 0 the frame buffer shown, 1 the display on, 2 the frame interrupt enabled; any write acknowledges the frame interrupt |
| 0x800C_0002 | the palette bank (write: bits 3–0, the palette's P7–4) |
| 0x8010_0000 + 2n | the boot flash's byte n (SST39SF010A, 128K × 8; writable with its command sequences) |
| 0x8014_0000 + 2n | the timer, an 82C54's register n (OUT0 the timer interrupt, OUT2 the speaker) |
| 0x8014_0010 + 2n | the palette, an IMS G171's register n (write address, colour, mask, read address) |
| 0x8014_0030 | the CF card's timing (write: bit 0, PIO mode 4) |
| 0x8014_0040 + 2n | the CF card's command block register n (16-bit True IDE) |
| 0x8014_0060 + 2n | its control block's |
| 0x8018_0000 | the interrupt controller: the sources pending (read); a write clears the button's latch |
| 0x8018_0002 | the vector (read, a byte): 0x40 + 4k for the first source pending, 0x04 if none |
| 0x8018_0004 | ODT's word (read: 0x9000 while ODT is asked for, else 0); TRACE (write, bit 0); a write clears the halt button's latch |
| 0x8018_0006 | the scanline (read, 9 bits); the copper's target (write: bits 8–0 the line, bit 15 CEN) |
| 0x801C_0000 | the sound chip (write: its register in bits 15–8, the value in 7–0); anywhere in 0x801C_xxxx, but the simulation's console is at its start, so software uses +0x80 |

**The UARTs** have a 1.8432 MHz oscillator. Each has a MAX232 for
RS-232 (TX, RX, RTS, CTS), a jumper block between it and the MAX232,
and a 6-pin TTL header on the UART's side (FTDI's pinout), for a TTL
cable with the jumpers off.

**The slow devices** (the timer, the palette, the CF card) sit behind
`U_SLOW`, a counter on the master clock that holds the half (HOLD) and
times their strobes. The CF card runs at PIO mode 0 from reset, then at
PIO mode 4 once software sets it; at mode 0 the display must be off. It
has a bus of its own: two 74ABT245s for the data, a 74HCT541 for the
address, selects and strobes, series resistors on every line, the
buffers on only during its accesses.

**PS/2.** The lines go through a 74HCT14's Schmitt inputs. Each port has
a receiver, a 22V10 clocked by the port's clock line, which shifts the
data in and then holds the byte and the port's interrupt until a write
clears it. A frame GAL counts the parity and stop edges after it and
records a framing error. The control GAL, on ADS, samples the lines and
the flags a tick into each I/O access, so that a read sees them steady,
and holds the pull-downs that software uses to send (the mouse's
"enable data reporting").

**The sound chip** is a YM2149 (tentative), with three tones, noise and
envelopes. It is written through a posting latch: a write loads two
74ABT574s and toggles PTOG, and `U_PSGC`, on the UARTs' clock, runs the
chip's address and write cycles, 543 ns each. Software leaves 2.2 µs
between writes; the chip isn't read.

### 8. Interrupts and exceptions

Eight sources, in priority order: the timer, the video's frame, UART 0,
UART 1, the keyboard, the mouse, the CF card and the interrupt button
(latched). `U_IRQ` ORs them into IRQ, taken while I is set at the end of
an instruction. The entry reads the vector from the controller:
0x40 + 4k for the first source pending, or 0x04 if none is (in the
simulation, the test fixture's interrupt).

An interrupt, an exception or SWI clears I and sets B to B | BI. It
pushes the flags word and the return address (8 bytes) on sp, in the
new bank, and jumps to the vector:

| Vector | |
|---|---|
| 0x00 | reset |
| 0x04 | interrupt (none pending at the controller) |
| 0x08 | illegal instruction |
| 0x0C | SWI |
| 0x10 | divide by zero |
| 0x14 | address error (a misaligned access, an odd jump target) |
| 0x18 | tag check (the tagged operations) |
| 0x40 + 4k | interrupt source k |

The return address is the next instruction's for an interrupt and SWI,
the trapping instruction's for the others. RTI pops PC and the flags
word, B and BI with it. HALT with I set waits for an interrupt, which
returns after the HALT; with I clear it stops, and the halt button
takes it to ODT.

**Deviations from RFC 0028**, for Emily to accept or reject:
- one interrupt level with vectors per source, not eight levels
  ([RFC 0040](0040-rfc-interrupts.md));
- the register bank bit B;
- the table forms of the special mode's operands for MULU and MULS
  (EC, ED), and the memory modes of the 0x2x memory group, are illegal
  instructions;
- the video's control register must be written as a halfword.

### 9. Video and the copper

640 × 480 at 60 Hz (59.94), 4 bits a pixel, VGA's standard timing,
through an IMS G171 RAMDAC (256 × 18 bits). The four pixel bits are its
P3–0 and the palette bank (`U_PB`, a 74HCT175) is its P7–4, so software
picks one of 16 banks of 16 colours.

The video is decoupled from the CPU's cycle. `U_VQ` divides MCLK by 8
(a word of four pixels every 8 ticks) and keeps a two-word buffer:
`U_VA0-1` load from MD at a video read, `U_VB0-1` from them as the
shifter takes a word. The reads are in phase F's ticks 1–2, and 3–4 when
the clock generator lengthens F because the buffer is empty. `U_VF`
counts the line's 160 words, `U_VH` the words shown and HSYNC, `U_VV`
the line, `U_VS` VSYNC and the frame interrupt, `U_VC` the control
register. `U_SHA-B` shift a word out a pixel each PIX, pixel 0 in bits
3–0. **The frame buffers** are at 0x18_0000 and 0x1C_0000 (control bit
0), 512 bytes a line: line $y$'s pixel $x$ is the nibble at
$\text{base} + 512y + \lfloor x/2 \rfloor$, the low nibble for even $x$.
The display is off after reset.

**The scanline.** `U_LINE` counts the lines as `U_VV` does, readable at
the controller's +6. `U_LCMP` holds the copper's target line. A
74HCT688 compares the two, and `U_LREQ` asks for the copper (COPREQ) for
the whole target line while CEN is set.

**The copper** is a task in microcode. It runs at the next task point
while COPREQ is up and works through a list in RAM. Its place in the
list is the word at COPPTR, 0x60, which software sets to start it. The
list's entries:

| Entry | |
|---|---|
| MOVE | an I/O address (bit 31 set), then a word whose low half is written there |
| WAIT | bits 31 and 30 clear: its low half (CEN in bit 15, the line in bits 8–0) is written at +6, and the task ends |
| JUMP | bit 31 clear, bit 30 set: the list goes on at the word's address |

A WAIT for a line already passed waits for the next frame's. A list for
every frame ends with a WAIT and a JUMP to its start. A MOVE takes about
8 microinstructions, 1–2 µs. The copper starts within the current
instruction's time to its next task point: under a microsecond for
most, longer only for the few long instructions without task points in
their loops.

### 10. Reset and boot

A TL7705A holds RESET_n low at power-up, or while the reset button is
pressed. Reset clears the sequencer to page 3, step 0, the flags, the
devices' registers and the video's control, and resets the UARTs; the
clock generator keeps running. The reset routine:

1. sets INIT;
2. sets UART 0 to 115,200 baud, 8N1, its FIFOs on, DTR and RTS;
3. reads the boot flash: if byte 0 is 0x1F, copies byte 1's count of
   256-byte pages from byte 2 on into RAM at 0;
4. enters the program at 0.

This boot format is tentative. In the simulations the flash is blank
and the RAM preloaded.

### 11. ODT and debugging

**ODT** is a console monitor in microcode, in the spirit of the LSI-11's.
It needs nothing in memory and talks on UART 0, as the program left it.
The halt button enters it at the next instruction's end, as does the
end of a stepped instruction. It is also entered from HALT's wait, or
from a machine stopped by HALT. Its syntax, in hex:

| | |
|---|---|
| `@` | the prompt; on entry ODT prints the PC it stopped at first |
| `a/` | open the word at a: ODT prints it |
| `%n/` | open register n (0–F, in the bank the program was in) |
| `v` CR | write v to what's open, and close it |
| `v` LF | write v, and open the next word |
| CR, LF | the same, without writing |
| `G`, `a G` | go on at the PC ODT stopped at, or go to a |
| `S` | step: one instruction, then back in ODT |
| `?` | what ODT didn't understand |

Letters may be lower case, and every character is echoed. ODT asserts
RTS only while it waits for a character, so a terminal that keeps to
RTS can't overrun it. A word is read and written as two halfwords
(A0 ignored), so devices can be poked.

ODT's microcode is opcode 00's blocks at N 9, 15 and 14 (about 200
microinstructions). Page 3's entry loads the instruction register from
the controller's +4, which reads 0x9000 (opcode 00, N 9) while ODT is
asked for. ODT keeps TRACE on while it runs, so the same read takes it
back to block 9 from the others. It keeps its state in the microcode's
temporaries and puts V, C, Z and N back as it leaves. It leaves by
fetching the next instruction itself, so a step's TRACE is seen only at
that instruction's end.

**Debugging hooks:**
- three 32-pin headers for a Saleae Logic Pro 16 or any analyser with
  flying leads (16 signals, each beside a ground, through 100 Ω): the
  control store's address and the clock; N, the half, phase F, the
  flags, TASK, LDIR and HCK; and D;
- the halt button (an SPDT, latched);
- the reset and interrupt buttons;
- the clock jumper for an external clock.

### 12. Parts

| | Packages | |
|---|---:|---|
| ATF22V10C-5 (PLCC-28, socketed) | 60 | clock generator (2), sequencer and tasks (6), flags and system (2), register file (4), operand latch (4), ALU control and zero (2), result (4), immediate unit (3), bus and sources (2), PC and MAR (7), memory control, I/O decode, slow devices (2), interrupts, ODT, scanline (3), PS/2 (6), sound, video (8) |
| SST39SF040-55 (PLCC-32, socketed) | 9 | the control store |
| SST39SF010A-55 (PLCC-32, socketed) | 1 | the boot flash |
| 74F181, 74F182 | 4, 1 | the ALU |
| CY7C199C-12 | 4 | the register file |
| AS7C4096A-12 (SOJ-36) | 4 | the RAM |
| 74ABT541 | 8 | the clock buffers (2), PC's read-back (2), the flags word, the scanline's read-back, the task's opcode and N |
| 74ABT574 | 8 | the video's buffer (4), SWP (2), the sound chip's latch (2) |
| 74ABT245 | 5 | D to MD (2), the byte crossing, the CF card's data (2) |
| 74HCT541, 74HCT688, 74HCT175, 74HCT14 | 1 each | the CF card's control, the scanline compare, the palette bank, the PS/2 inputs |
| TL16C550C, MAX232 | 2, 2 | the serial ports |
| 82C54, IMS G171, YM2149F | 1 each | timer, palette, sound |
| TL7705A | 1 | reset |
| oscillators | 2 | 50.35 MHz, 1.8432 MHz |
| CompactFlash socket | 1 | |
| **total** | **119** | |

Not counted: resistor networks, decoupling, the connectors (VGA, two
DE-9s, two PS/2 sockets, the sound jack, power), the buttons, jumpers
and headers. The sections: clock 6, control store 17, flags 2, register
file 8, ALU 10, result 5, immediate unit 8, address 7, memory 10, I/O
34, video 12 ([performance.md](0047-rfc-chibi-heron/performance.md#parts)).

## Part II: Discussion

### 13. How fast

The suite on the model, which the netlist matches cycle for cycle
([performance.md](0047-rfc-chibi-heron/performance.md)):

| | Chibi Heron | The full Heron (RFC 0031) | The first cut |
|---|---:|---:|---:|
| the suite (18 programs, not hello or interrupts) | 1738 ms | 465 ms (3.7× faster) | 3599 ms (2.07× slower) |
| per instruction, on average | 1224 ns | | |
| per microinstruction | 6.45 ticks, 128 ns | | 158.9 ns |

Ordinary code (fib, life, sieve, queens, sort, strings, rpn) runs at
400–570 ns an instruction, 1.7–2.7 times the full Heron's time. Where
the time goes:

- **Multiplies and divides** still go a bit a step: MULFX (mandel's
  fixed point) is 30% of the suite's time by itself, at 1258 ticks
  (25 µs) a time. The divides are about 900–1000 ticks. A multiply by a
  number under $2^{16}$, or a divide of one, takes 16 steps instead of
  32; mandel's signed fixed-point operands mostly don't qualify. mandel
  is 6.2× the full Heron, matmul 4.0, bignum 4.4.
- **Shifts and rotates** go a bit a step: sha256's rotates take it to
  8.4×. The hardware for shifts by 8 through SWP is in; the microcode
  doesn't use it yet ([21](#21-open-tasks)).
- **Memory and calls:** `MOV` averages 26 ticks, a `JMP` through a
  table (vm's dispatch) 77, `PUSH` 39.

### 14. Timing

Static timing analysis of the netlist (`heron chibi hw sta`) takes
every distinct microinstruction (623 of them) as a case. Its control
bits are held at their values from the time the flashes give them. The
analysis finds the ticks each half needs to meet every setup: the
registers' at the half's end, `U_MEMC`'s before the half's second tick,
the register file's address and data around its write strobes, and the
RAM's. Phase F is a case of its own, the control bits unknown.
Worst-case delays throughout. It writes the table (`ticks.json`) that
the control store's LEN and HLEN are filled from, and a unit test fails
if a microinstruction isn't in it.

- **Low halves:** 405 of 2 ticks, 218 of 3. **High halves:** 230 of 2,
  115 of 3. **Phase F:** 3 ticks, all its requirements met. No half
  needs more than its field can say, and no I/O half more than 5.
- **The slowest low half** is an ADD that sets the flags: 58.5 ns of
  its 59.6 (3 ticks), from the register file's address at the half's
  start, through its 12 ns access, the ALU, the carry lookahead, to Z.
  The slowest high half (56.8 ns) reads the RAM: MAR, the row's chip
  enable, the RAM's 12 ns, the transceiver, the ALU, N.
- High halves have a floor of 2 ticks (HCK must fall between the
  halves' edges), and an access at MAR one of 3.

The chip-level simulator checks the same, and more: every device's
setup, hold and widths, with the real ticks and the video's reads. Its
runs of the suite report no violation, and no bus driven twice for
longer than the 0.9 ns of a handover.

### 15. Why it's built so

- **Two halves rather than a 32-bit datapath.** A 32-bit ALU, latch and
  result would be about 22 more packages for 1.6×. The halves give
  32-bit operations in one microinstruction, at a 16-bit datapath's
  cost, with the variable ticks giving each half only the time it
  needs. Emily chose this, with variable ticks, over the first cut's
  fixed cycle and over a "system half".
- **Ticks from the timing analysis.** Each microinstruction is as long
  as its paths, not as the slowest: 6.45 ticks on average, against a
  fixed cycle that would need about 9.
- **The video decoupled.** The first cut counted the video in CPU
  cycles, which pinned the cycle to four pixels. Here the video has its
  own count from MCLK and a two-word buffer, and takes phase F's ticks
  1–2. Phase F is 2 ticks longer only when the buffer runs dry.
- **One bus and a latch.** Every operand crosses D. A second read port
  would save a microinstruction on two-register operations, for five or
  six chips; not built.
- **Horizontal and unpipelined.** The flashes drive the datapath
  directly. Phase F covers their settling while the last results are
  written: no microinstruction register, no hazards, no delayed
  branches.
- **22V10s for everything small** ([18](#18-the-board)).
- **2 MB, not 4** ([20](#20-open-questions)).

### 16. How it was checked

- **The model against the simulator** (`heron chibi check`): every
  program of the suite, the output, the registers, the flags and the
  memory as draft 2's simulator leaves them. The unit tests run the long
  routines on chosen and random operands, with aliased registers and
  16-bit operands for the short paths: multiply, divide, MULA, MULFX,
  CLZ, REV, the tagged operations, LDM and STM with their table modes,
  ADD.B4, MERGE, FFS, POPC.
- **The netlist against the model** (`heron chibi hw test`): the
  chip-level simulator runs the netlist with worst-case delays. Its
  22V10s run from their equations, the flashes from the microcode's
  images, and the RAM is preloaded with the program. The output, the
  registers, the flags, the RAM and every instruction fetch (address,
  parcel and cycle) are the model's, for all twenty programs.
- **The board's own devices at chip level:**
  - ODT: a session that opens memory and registers, writes, steps
    through a loop (the flags must survive) and goes on, on the UART
    model with its timing;
  - the copper: its list writing to the console at two lines a frame;
  - the PS/2 receiver: two bytes from the keyboard model.
  Each matches the model's outcome, with no violation.
- **Not checked:** the picture, the palette, the sound chip, the CF
  card, the mouse, UART 1.

### 17. The first cut

The first cut (still in the study: `board.py`, `routines.py`, `rtl.py`,
`sta.py`) was 70 packages: a 16-bit operation a cycle, one fixed cycle
of 158.9 ns (four VGA pixels, the video counted in CPU cycles), 36
22V10s, a 67-bit control word, and none of the devices but the UARTs,
the PS/2 ports and the video's fixed colours. It ran the suite at 7.7
times the full Heron's time. Its static timing needed 147.1 ns. The
two-halves machine spends 49 more packages: on the devices Emily's
decisions added (palette, timer, sound, CF, serial levels, interrupt
controller, ODT, scanline and copper), on the second half of
the register file, latch and results, and on the decoupled video, the
clock generator and SWP.

### 18. The board

**The 22V10s.** Emily's question: doesn't a GAL take more board space
than two smaller DIPs, and need programming?
- **Space.** A PLCC-28 socket's courtyard is about 19 mm square; a
  DIP-24 (0.3 inch) about 32 × 10 mm; two DIP-14s about 2 × 19 × 10 mm.
  So a 22V10 in DIP-24 is smaller than two DIP-14s, and in a PLCC socket
  about the same. On RFC 0046's grid the PLCC sockets take a column
  each, which is what makes them costly.
- **Logic.** Each 22V10 here does what 3–6 74-series chips would: up to
  10 registered or combinational outputs of up to 22 inputs, with output
  enables. The 60 would be some 200–300 chips of 74 logic.
- **Programming** is one cheap universal programmer (an XGecu T48 or
  similar) and a JEDEC file each. The flow doesn't write JEDEC files yet
  ([21](#21-open-tasks)).
- **Speed.** About 20 of the 60 are in the critical paths and need the
  -5 grade, which comes only in PLCC. The rest could be -7 or -10 in
  DIP-24, which would shrink the board
  ([placement.md](0047-rfc-chibi-heron/placement.md)).
- **Recommendation:** keep the 22V10s; make the non-critical ones DIP-24
  (a timing rerun with their delays decides which).

**Placement** on RFC 0046's column grid, no routing
([placement.md](0047-rfc-chibi-heron/placement.md), `heron chibi place
--write`). The least board is 365 × 275 mm (4:3, 79% of its grid,
69.4 m of wire), the least square one 320 × 320; it doesn't fit ATX
(305 × 244). With the 22V10s in DIP-24 the 4:3 board is 345 × 260, 11%
less area. The board's size is open.

### 19. Proposals

These are written up for Emily's decision; none is built.

**Forcing bit 31 (null checks and pointer tagging).** If data addresses
had to have bit 31 set, a null pointer, and any value tagged as a
non-pointer by bit 31 clear, would trap on dereference, for free. What
it would take:
- **The map:** RAM at 0x8000_0000 (A31 = 1, A30 = 0) and the I/O space
  at 0xC000_0000 (A30 = 1), keeping MAR's bit 30 in `U_MARC`'s one
  spare output. `U_IODEC` would then select on A30. Today's map stays
  while the option is off.
- **The check:** in the high half of the microinstruction that loads
  MAR, which already checks alignment. A high-half form of STA4 and
  STF0 that also sets ST when the address's bit 31 is clear sends a bad
  address to the same trap (address error), in the same microinstruction:
  no time. Byte accesses, which have no alignment check, would need a
  flag operation of their own (an FL code is free). Jumps likewise, for
  code addresses.
- **The switch:** a bit in the flags word (bit 7), set by MTSR, so
  existing programs at 0 run unchanged.
- **Cost:** no chips, if `U_FLG`'s ST equation takes the extra term
  (to check); a few microinstructions' flag fields; the linker's base
  address for programs that turn it on.

**Multiply and divide hardware.** MULFX is 30% of the suite, all the
multiplies and divides about 45%.
- **In microcode, free:**
  - short paths for small multipliers and dividends (built);
  - a signed multiply on magnitudes, so that small negative operands
    take the short path too;
  - skipping zero nibbles of the multiplier.
  Perhaps 1.2–1.5× on mandel; not measured.
- **An 8 × 8 multiplier in flash, 2 chips:** two SST39SF010As (128K × 8)
  addressed by D's and L's low bytes give a 16-bit product in one half
  of 3–4 ticks, as a D source (one of DS's codes would have to be
  shared). A 32 × 32 multiply is then 16 partial
  products and their adds, about 50 microinstructions against 200: about
  4× faster multiplies, mandel 2–3× faster, the suite about 1.3×. It
  takes the budget's last place and one more, so something else would
  have to go (the sound chip's latch, say). No help for divides.
- **A multiplier chip:** the 16 × 16 parallel multipliers (IDT7216,
  ADSP-1016) are long out of production, and there are none in DIP.
- **Divides:** a reciprocal table in flash and a Newton step, or SRT
  steps; neither is cheap in microcode on this datapath. I'd leave them.

**Pipelining the control store** ([pipelining.md](0047-rfc-chibi-heron/pipelining.md)).
Phase F is nearly half the machine's time: the flashes settling, and the
register file's writes and the video's read meanwhile. A register for the
executing word (6–8 × 574) alone gains under 10%, since the writes still
need their ticks. With the writes moved into the halves (the four-SRAM
file allows it) and 45 ns flashes (which the flat layout's smaller store
allows), the estimate is about 1.38×, for about 10 packages.

**Small features within the budget** (0 or 1 chip):
- a speaker on the timer's OUT2 (wired, a transistor);
- LEDs for HALT, ODT and the copper (resistors);
- the copper's tricks: palette changes a line (raster bars with a
  line's jitter), split screens, a second frame buffer half-way down;
- booting into ODT when the flash is blank (microcode only), so that a
  bare board can be loaded over the serial line;
- with the last chip: a real-time clock (a DS1307 on two pins of a GAL
  spare, bit-banged), or a second palette bank register for per-line
  colour changes without the copper.

### 20. Open questions

For Emily:

1. **2 vs 3 bits for the half's length field** (LEN is 2 bits now, as
   built; a 3-bit field was worth 1.78× against 1.68× on the suite in
   the exploration).
2. **4 MB?** Four more SRAMs and A21 in PC and MAR: about 5 packages,
   over the budget.
3. **The sound chip** (the YM2149 is tentative).
4. **The boot format** (tentative).
5. **The deviations from RFC 0028** in [8](#8-interrupts-and-exceptions).
6. **The proposals** in [19](#19-proposals): forcing bit 31, the
   multiplier in flash, pipelining the control store, the small features.
7. **The 22V10s' packages** ([18](#18-the-board)).
8. **Parts availability**, to review (the CY7C199C, the 74F181 and
   74F182, the IMS G171, the YM2149F, the TL7705A).

### 21. Open tasks

- **Shifts by 8 through SWP:** the hardware is there; the shift and
  rotate routines still go a bit a step.
- **The task-constraint checker:** a test that the copper's microcode
  keeps to a task's rules and every task point to its (MAR, flags,
  L).
- **JEDEC files** for the 22V10s from their equations.
- **Tests at chip level** of the picture and palette, the sound chip,
  the CF card, the mouse and UART 1.
- **The board:** the non-critical 22V10s in DIP-24, footprints for the
  clock jumper and the sound jack (placed as buttons now), the
  placement again, then routing.
