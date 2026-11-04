---
number: 47
type: rfc
title: "Chibi Heron: draft 2 on one board of 111 chips"
status: draft
date: 2026-10-20
context:
  studies: [chibi, v2_isa, pcb_columns]
  commit: 65ebcd9
depends-on: [28]
---

# RFC 0047: Chibi Heron: draft 2 on one board of 111 chips

The smallest Heron so far: draft 2's user instruction set
([RFC 0028](0028-rfc-draft-2-isa.md)) on one board, with 2 MB of RAM,
640 × 480 × 4 VGA through a 256-colour palette, a microcoded copper,
two serial ports, PS/2 ports for a keyboard and a mouse, a timer, PCM
sound, a CompactFlash slot, a boot flash and a debugger in microcode. Heron Mini ([RFC 0041](0041-rfc-heron-mini.md)) does draft 2
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

- **111 packages:** 110 chips and the CompactFlash socket. 52 of them
  are ATF22V10Cs.
- **This revision** (Emily's decisions of the latest round):
  - a rough rule for what's a GAL: decode and state machines; registers,
    counters, muxes and bus drivers are 74 parts. Applied where it's
    free or cheap: the operand latch and the copper's target line are
    74ABT574s. The rest it would change is costed in
    [19](#19-proposals);
  - PCM and the PS/2 receivers in microcode, a second task, the device
    task ([7](#7-the-io-space)): a 574, a DAC0832 and an op-amp instead
    of the YM2149 and its latch's three chips, a 22V10 a PS/2 port
    instead of three;
  - together 9 22V10s and 4 packages fewer (the latch's 574s and the
    GAL that clocks them cost one);
  - the 22V10s' grades: the -7, the -15 and the zero-power CQZ-20 in
    DIP-24, and a search for each GAL's slowest grade
    (`heron chibi hw grades`). Its mix fails at chip level, so every
    22V10 is still the -5 ([18](#18-the-board), **open**).

  The round before:
  - a flat control store, entered at 0x100 + the opcode, every word
    naming the next ([3](#3-control-store-and-sequencer));
  - every instruction and mode of RFC 0028, the special mode's tables
    for CLR, INC, DEC, JMP, CALL, MULU and MULS included;
  - the I/O space at A30, its devices in the top 64 KB
    ([7](#7-the-io-space));
  - no SWP, and the register file in two 64K × 16 SRAMs: 4 packages
    fewer;
  - the control store in SST39SF010As.
- **It works, at chip level,** as far as this draft has run it: seven
  programs of the suite, ODT's session, the copper's test and the device
  task's (PCM and the keyboard) run on the chip-level simulator as the
  model does (the output, the
  registers, the flags, the RAM, and every instruction fetch at the same
  cycle; for the tests of the devices, the outcome), with no timing
  violation. The model runs the whole suite as draft 2's
  simulator does.
- **Timing:** static timing analysis with worst-case datasheet delays
  gives every distinct microinstruction its length in ticks. A half
  takes 2 or 3 ticks (an I/O access 6), and phase F 3. The control
  store's length fields are filled from that table.
- **Speed:** the suite takes 3.8 times as long as on the full Heron
  ([RFC 0031](0031-rfc-draft-2-cpu.md)), against 7.7 for the first cut:
  2.05 times faster than the first cut, and 1.2% slower than the paged
  store. Ordinary code runs at 430–590 ns an instruction, about 2 MIPS.
  A microinstruction averages 6.43 ticks, 128 ns ([13](#13-how-fast)).

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

- the **register file**: two 64K × 16 SRAMs, one for the low halves of
  the registers and one for the high halves. It holds draft 2's 16
  registers in two banks, 16 microcode temporaries, and a task's private
  bank. It drives D and is written from the result registers;
- the **ALU**: four 74F181s and a 74F182. It takes D as A and the
  **operand latch** L as B. L is four 74ABT574s, a register for each
  half, loaded from D;
- the **result registers**: four 22V10s, one pair for the low half's
  result and one for the high half's. They can shift the result right a
  bit or extend a byte;
- the **immediate unit**: three 22V10s. It puts 32 constants (and the
  instruction's fields shaped into them) on D, a half at a time;
- **PC** and **MAR**: counters in 22V10s, loaded from the ALU, driving
  the address bus;
- the **memory data bus**, MD, joined to D by two 74ABT245s and a third
  that crosses the bytes. It holds the RAM, the devices and the video's
  buffer.

The control store is horizontal and flat: nine flashes give the 72 bits
of a microinstruction straight to the datapath, without a pipeline
register, and each word names the next.

### 2. Clock and cycle

The master clock is a 50.35 MHz oscillator (twice VGA's pixel clock); a
**tick** is 19.86 ns. A jumper takes MCLK from an external clock
instead, for debugging. The clock generator is two 22V10s on MCLK:
`U_CGA` (the phase and the tick in it) and `U_CGB` (the clocks and
strobes). A microinstruction's **cycle** has up to three phases:

- **Phase F**, 3 ticks. The control store's outputs settle for the new
  address. The last cycle's results are written: the low half's to the
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

A half that accesses the I/O space takes 6 ticks, whatever its field
says. The slow devices hold it longer: the timer and the palette 11
ticks, the CF card 8 at PIO mode 4 and 32 at PIO mode 0. The clock
generator ends a half at its count, or once the slow devices let go
(HOLD). CLK0 rises as phase F starts and clocks the sequencer; HCKA ends
the low half, HCKB the high half, HCK either. `U_LCK` gives the operand
latch its clocks, LCKA and LCKB (HCKA and HCKB when the word loads L),
and LBOE_n, HALF's complement, for its high half's outputs. The clock generator isn't
reset: it runs through reset.

LEN and HLEN are the timing analysis's: each distinct microinstruction
has as many ticks as its paths need ([14](#14-timing)).

### 3. Control store and sequencer

**The control store** is nine SST39SF010As (128K × 8, PLCC-32), of which
the low 8K words are used: a flat store, addressed by the 13-bit
microprogram counter **µPC**. Every word gives its own next address. The
72-bit word's fields:

| Field | Bits | |
|---|---:|---|
| DS | 3 | D's source: none, register file, memory, immediate, the address bus (PC read back), PC's high bits, the flags word |
| SZ | 1 | the access is a byte |
| IMMF | 5 | the immediate's format |
| RK, HR | 6, 1 | the register read: K 0–31, d (32) or s (33); the half |
| WK, HW | 6, 1 | the register write, the same way (63: none) |
| AOP | 5 | the ALU's operation (A = D, B = L) |
| SISEL, RM | 2, 2 | the result: as is, shifted right (bit 15 in: 0, C, D15 or the carry out), a byte zero- or sign-extended |
| FL | 5 | the flag operation |
| LDL | 1 | L's half ← D |
| MOP | 3 | memory: none, read at MAR, write at MAR, read at PC, fetch, PC on the bus, a read at MAR into d and s (LDIRM) |
| AXP, AXM | 2, 2 | PC's and MAR's halves ← the ALU; MAR + 2 |
| IRN | 2 | the register byte: d + 1, s − 1, s ← the index parcel's x |
| SEQ, CND, JT | 2, 4, 13 | the next address (below): its kind, the condition or the branch's nibble, the target |
| LEN, HLEN, HX | 2, 2, 2 | the halves' ticks; the high half's variant: zero-, sign- or immediate-extended, with no access |

**The next address**, by SEQ:
- **JUMP** (and **JUMPT**, the same at a task point): JT with its bit 0
  XORed with the condition CND (the flags, IRQP, d ≠ s, ODT, I, INIT and
  the rest). So a conditional jump goes to one of a pair, JT or JT ⊕ 1,
  and an unconditional one (CND TRUE) to JT ⊕ 1. There's no incrementer:
  a word that just goes on names its successor.
- **MW**, a 16-way branch: JT with its low 4 bits ORed with a nibble: d,
  s or z (the index parcel's bits 11–8, as it's read), as CND's low bits
  say.
- **END**, the decode: µPC ← 0x100 + the opcode, MD7–0 of the fetch's
  parcel. If an interrupt or ODT is pending (IRQP) it's the opcode
  alone, and 0x000–0x0FF all hold the interrupt's entry. With JT's bit
  12 set, IRQP isn't looked at (ODT's step).

**The sequencer.** `U_UPCL`, `U_UPCM` and `U_UPCH` hold µPC's bits 3–0,
8–4 and 12–9, loaded at CLK0. Reset clears them: µPC 0 is the
interrupt's entry, which goes to the reset routine while INIT is clear.
`U_NG` gives the branch's nibble, `U_IRH` the register byte (d, s, from
the fetch's parcel or LDIRM's read; d + 1, s − 1, s ← x) and `U_COND` the
condition. The opcode isn't kept: once it has given the entry's address,
nothing needs it.

**The layout** is a compiler's (`flat.py`). The routines are written as
for a paged store, in blocks of (page, N, opcode) with N ← s and N ← z as
dispatches, and as named lists with labels (the interrupt's entry,
reset's, the boot, ODT, the copper). The compiler:
- follows each block's control flow from its entries;
- merges the states that do the same with the same successors, so that
  what's alike in every N's block, or every opcode's, is one word;
- makes each dispatch a 16-way branch;
- lays the words out: each opcode's entry at 0x100 + the opcode, a
  condition's two targets as a pair, a branch's sixteen at a multiple of
  16, the tasks' words within their 128 at 0x1F80, a word wanted in two
  places copied.

The store has 4,865 words in use (of 8,192), 609 of them distinct; the
tasks have 100 of their 128.

**Entries that depend on d.** The decode enters at the opcode alone, so
an instruction whose first step depends on d (its mode or condition)
branches on d first: JMP, CALL, CLR, INC, DEC, Jcc, LDM, STM, MFSR,
MULFX and the system group. Where every d's first word is the same, the
branch rides in it; otherwise (all of these, as written) it's a
microinstruction of its own ([13](#13-how-fast)).

**Tasks.** A task is microcode that runs between two microinstructions
of an instruction, without its help. Two tasks exist: the device task
([7](#7-the-io-space)), PCM and PS/2, and the copper
([9](#9-video-and-the-copper)). At a **task point** (SEQ END or JUMPT:
the long loops of multiply, divide, shifts, SAVE and RESTORE), if DREQ or
COPREQ asks, TASK sets. µPC then holds with its outputs off, and
`U_TASK`'s bits 6–0 with `U_TOP`'s ones above them (a 74ABT541) address
the store: from 0x1F80 for the device task, which goes first, or 0x1FC0
for the copper. The task's SEQ END clears TASK and the instruction goes
on where it was. A task uses its own register bank (RA6 = TASK), ST and the
internal carry IC, and MAR; it puts L back. At a task point MAR and the
flags but ST and IC are dead; L is live. The handover is break before
make: µPC's bits 12–7 let go as TASK sets and take the address back only
once TASKD (TASK a stage later) has cleared too, and U_TOP drives only
once both are set. `U_LCK` gives TCHG, TASK changed as the cycle began,
which makes phase F a tick longer.

### 4. Datapath

**The register file:** two IS61C6416AL-12 (64K × 16, SOJ-44, their byte
enables low), addressed by `U_RFA0-2`: the register's number from K, d
or s (RK, WK), and its bank. RA6 is TASK (a task's bank), RA7 the
bank bit B for draft 2's 16 registers (not for the temporaries). Phase F
writes the low half's result in tick 1 and the high half's in tick 2
(`RFWL_n`, `RFWH_n` from the clock generator). `U_RFW`'s chip enables
keep out the SRAM a write doesn't take.

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
HW so that a result can go to either half.

**The immediate unit** (`U_IMML`, `U_IMMH`, `U_IMMX`): 32 formats, each
a 32-bit value, low half then high half. They are small constants (1, 2,
4, 6, 8, 16, 31, 32, 64, −1), the instruction's 4-bit fields scaled and
signed (Q4, NQ, SC4, B8, DB, SH0, SH1, U7), four device addresses (the
interrupt controller's vector, UART 0, the PS/2 ports, the PCM's sample),
and SXST, the high half's sign from ST. The exceptions' vectors and the
boot flash's address are made from them.

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

The address bus has A20–A0, and MAR's bit 30 is AIO. **PC** (bits 20–1)
is three 22V10s (`U_PCA-C`), **MAR** (bits 20–0 and 30) three more
(`U_MARA-C`):
counters that load a half from the ALU at the half's end, PC counting by
2 on a fetch or a read at PC, MAR by 2 when asked. `U_ADC` decodes their
operations and which of them drives the address bus (PC for fetches and
reads at PC, MAR otherwise). In phase F the video drives A20–A1. PC
reads back onto D through two 74ABT541s (bits 15–0) and `U_PCC`'s pins
(bits 20–16).

Draft 2's addresses are 32 bits; the board decodes A20–A0 and A30.
**A30 = 0 is RAM**, 2 MB repeated through the space (at 0x0000_0000, or
0x8000_0000 if bit 31 is ever forced); **A30 = 1 is the I/O space**. A31
is ignored.

**The RAM** is four AS7C4096A-12 (512K × 8, SOJ-36), two rows of two
byte lanes, 1M × 16. A20 picks the row: it is row 0's chip enable
directly, and a spare macrocell of `U_NG` inverts it for row 1. A word is two halfword
accesses, at MAR and MAR + 2, one a half. A byte access steers the odd
byte across (`U_XS`) and zero-extends it. `U_MEMC`, on the master
clock, gives the RAM's write enables from a half's second tick to its
end, and the I/O strobes from its third.

**Alignment** is checked where an address is computed, in the
microinstruction that loads MAR: misaligned words and halfwords trap
(address error) before anything changes, and so do odd jump targets.

### 7. The I/O space

**A30 = 1 is the I/O space** (MAR's bit 30, AIO; A31 is ignored, so that
bit 31 can be forced later). `U_IODEC` decodes it with A20, A16 and
A14–A12:

| Address | |
|---|---|
| 0xFFE0_0000 + 2n | the boot flash's byte n (A20 = 0; SST39SF010A, 128K × 8, writable with its command sequences) |
| 0xFFFE_0000 | the expansion port's 64 KB (A16 = 0): reserved, not decoded yet |
| 0xFFFF_8000–0xFFFF_FFFF | the devices, a 4 KB slot each by A14–A12; they repeat at 0xFFFF_0000 (A15 is ignored), and wherever A20 and A16 are set |

| Slot | Address | Device |
|---|---|---|
| 7 | 0xFFFF_F000 | nothing on the board; in the simulation the suite's test fixture, whose console is at 0xFFFF_FF00 |
| 6 | 0xFFFF_E000 + 2n | UART 0's register n (TL16C550C, on MD7–0) |
| 5 | 0xFFFF_D000 | the interrupt controller: +0 the sources pending (read; a write clears the interrupt button's latch); +2 the vector, 0x40 + 4k for the first source pending, 0x04 if none; +4 ODT's word (read: 0x9000 while ODT is asked for, else 0; write: TRACE in bit 0, the halt button's latch cleared); +6 the scanline (read, 9 bits) and the copper's target (write: bits 8–0 the line, bit 15 CEN) |
| 4 | 0xFFFF_C000 | the video's control (+0, a halfword: bit 0 the frame buffer shown, 1 the display on, 2 the frame interrupt enabled; any write acknowledges the frame interrupt) and the palette bank (+2: bits 3–0, the palette's P7–4) |
| 3 | 0xFFFF_B000 | PS/2, for the device task: +0 the keyboard's port (read: bit 0 the data line, 1 an edge of the clock not yet taken; a write takes it), +2 the mouse's (read: bit 2 too, the PCM's request SREQ); +4 the keyboard port's control (write: bit 3 its interrupt, bit 4 pulls the clock low, bit 5 the data), +6 the mouse port's |
| 2 | 0xFFFF_A000 | the slow devices: +2n the timer's register n (an 82C54: OUT0 the timer interrupt, OUT1 the PCM's sample rate, OUT2 the speaker); +0x10 + 2n the palette's (an IMS G171: write address, colour, mask, read address); +0x20 the PCM's sample (write, bits 7–0; the device task's); +0x30 the CF card's timing (write: bit 0, PIO mode 4); +0x40 + 2n the CF card's command block register n (16-bit True IDE), +0x60 + 2n its control block's |
| 1 | 0xFFFF_9000 + 2n | UART 1's register n |
| 0 | 0xFFFF_8000 | nothing |

**The rules for software:**
- devices are 8 or 16 bits at even addresses, the 8-bit ones on MD7–0;
- access them as halfwords and keep the low byte of an 8-bit device's (a
  byte access at an even address works too);
- a word access is two halfword accesses, at +0 and +2;
- code runs only from RAM (PC has bits 20–1).

The devices are within reach of a 16-bit absolute address,
sign-extended (0xFFFF_8000–0xFFFF_FFFF).

**The strobes.** The slot is decoded from the address bus, which settles
about a tick into the half (MAR's drivers take the bus from the video's
as the half starts). So `IORD_n` and `IOWR_n` run from the half's third
tick to its end (`U_MEMC`'s IOQ, IOACC a tick late, starts them), and an
I/O half is 6 ticks. ADS, the strobes a tick later, latches the UARTs'
address and chip select (the TL16C550C's ADS input): they hold for the
strobe's end while the address bus changes.

**The UARTs** have a 1.8432 MHz oscillator. Each has a MAX232 for
RS-232 (TX, RX, RTS, CTS), a jumper block between it and the MAX232,
and a 6-pin TTL header on the UART's side (FTDI's pinout), for a TTL
cable with the jumpers off.

**The slow devices** (the timer, the palette, the PCM's sample, the CF card) sit behind
`U_SLOW`, a counter on the master clock that holds the half (HOLD) and
times their strobes, counting from IOQ, once the select has settled. The CF card runs at PIO mode 0 from reset, then at
PIO mode 4 once software sets it; at mode 0 the display must be off. It
has a bus of its own: two 74ABT245s for the data, a 74HCT541 for the
address, selects and strobes, series resistors on every line, the
buffers on only during its accesses.

**The device task** is microcode ([3](#3-control-store-and-sequencer))
that does what a PS/2 receiver and a sound chip's bus would: it runs
while DREQ asks, at a task point, ahead of the copper. DREQ is a PS/2
port's clock edge not yet taken, or SREQ, the PCM's request. The task
reads both ports, plays a sample if SREQ asks, takes each port's edge,
and ends: 29 microinstructions, 4.1 µs, for a sample, and about 3 µs for
an edge alone.
Its state is in its own register bank (the task bank's temporaries) and
in RAM:

| Address | |
|---|---|
| 0x64 | PCMPTR: the next sample's address (a byte each) |
| 0x68 | PCMEND: the end of the samples; once PCMPTR meets it, the task plays 0x80, the middle |
| 0x70 | the keyboard's last frame, a halfword: the data in bits 13–6, the parity in 14, the stop bit in 15 |
| 0x72 | the mouse's |

Software leaves 0x60–0x73 to the tasks (the copper's COPPTR is 0x60).

**PS/2.** The lines go through a 74HCT14's Schmitt inputs. Each port
has a 22V10 on the master clock: it synchronises the clock line and
sets E at each falling edge, and holds the port's interrupt and the
lines' pull-downs, which software writes. The device task takes each
edge: it reads the data line, shifts the bit into the frame, and after
the stop bit writes the frame to RAM and sets the port's interrupt.
Software reads the frame and clears the interrupt with a write at +4
(+6). An edge waits for the task at most an instruction's longest
stretch between task points (a few µs; the clock is low for 30–50 µs).
Sending to a device (the mouse's "enable data reporting") is software's,
through the pull-downs, as before; the task doesn't send (**open**: it
could, with a state of its own).

**PCM.** A 74ABT574 (`U_PCM`), a DAC0832 (an 8-bit DAC with two
latches) and an MCP6002 op-amp. The task writes each sample to the 574
(+0x20, an ordinary slow device's write). The DAC's input latch is open
(CS and WR1 low), and its DAC latch's strobe WR2 is the timer's OUT1:
counter 1 in mode 3, a square wave at the sample rate. The DAC latch
follows the 574 while OUT1 is low and holds while it's high. As OUT1
rises, `U_LCK` sets SREQ, and the task's write clears it, so the write
comes while OUT1 is high and the sample comes out as OUT1 falls: at the
timer's steady rate, however late the task wrote it within the half
period. The DAC needs its strobe low for at least 900 ns and its data
held 50 ns after (its datasheet), which OUT1's half period gives at any
rate up to 500 kHz. The DAC works in voltage mode (the reference on
IOUT1, the output at VREF), one op-amp buffering the reference from a
divider and the other the output. The analog side is a sketch
(**open**): the datasheet wants VCC at least 9 V above the reference in
this mode for its stated linearity, and at 5 V it's worse by an amount
to measure; a 12 V supply for the DAC alone would meet it. At 22 kHz the
task takes 9% of the machine (4.1 µs of each 45 µs), at 8 kHz 3.3%. OUT2
still drives the speaker.

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
- the I/O space's rules ([7](#7-the-io-space)): halfword accesses, and
  the video's control register written as a halfword.

Every instruction and mode of RFC 0028 is in the microcode, the special
mode's tables included.

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
the controller's +6. `U_LCMP` (a 574) holds the copper's target line's bits 7–0 and `U_LREQ` its bit 8. A
74HCT688 compares the two, and `U_LREQ` asks for the copper (COPREQ) for
the whole target line while CEN is set.

**The copper** is a task in microcode. It runs at the next task point
while COPREQ is up and works through a list in RAM. Its place in the
list is the word at COPPTR, 0x60, which software sets to start it. The
list's entries:

| Entry | |
|---|---|
| MOVE | an I/O address (bit 31 set: 0xFFFF_xxxx), then a word whose low half is written there |
| WAIT | bits 31 and 30 clear: its low half (CEN in bit 15, the line in bits 8–0) is written at +6, and the task ends |
| JUMP | bit 31 clear, bit 30 set: the list goes on at the word's address (its bits 20–0) |

A WAIT for a line already passed waits for the next frame's. A list for
every frame ends with a WAIT and a JUMP to its start. A MOVE takes about
8 microinstructions, 1–2 µs. The copper starts within the current
instruction's time to its next task point: under a microsecond for
most, longer only for the few long instructions without task points in
their loops.

### 10. Reset and boot

A TL7705A holds RESET_n low at power-up, or while the reset button is
pressed. Reset clears µPC to 0 (the interrupt's entry, which sees INIT
clear), the flags, the devices' registers and the video's control, and
resets the UARTs; the clock generator keeps running. The reset routine:

1. sets INIT;
2. sets UART 0 to 115,200 baud, 8N1, its FIFOs on, DTR and RTS;
3. reads the boot flash (at 0xFFE0_0000 + 2n): if byte 0 is 0x1F,
   copies byte 1's count of 256-byte pages from byte 2 on into RAM at 0;
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

ODT's microcode is one of the compiler's named routines (about 195
microinstructions). The interrupt's entry loads d and s from the
controller's +4 (LDIRM), which reads 0x9000 while ODT is asked for: d 9
and s 0, which ODT counts from to pick a register for `%n/`. ODT keeps
TRACE on while it runs, so that the same read sets them again later. It
keeps its state in the microcode's temporaries and puts V, C, Z and N
back as it leaves. It leaves with a fetch and a decode that skips the
interrupt's check (JT's bit 12), so a step's TRACE is seen only at that
instruction's end.

**Debugging hooks:**
- three 32-pin headers for a Saleae Logic Pro 16 or any analyser with
  flying leads (16 signals, each beside a ground, through 100 Ω): µPC,
  the clock, LDIR and TASK; d, the half, phase F, the flags, IRQP, AIO
  and HCK; and D;
- the halt button (an SPDT, latched);
- the reset and interrupt buttons;
- the clock jumper for an external clock.

### 12. Parts

| | Packages | |
|---|---:|---|
| ATF22V10C-5 (PLCC-28, socketed) | 52 | clock generator (2), sequencer and tasks (7), flags and system (2), register file (4), the latch's clocks and the device requests (`U_LCK`), ALU control, result and zero (5), immediate unit (3), bus and sources (2), PC and MAR (7), memory control, I/O decode, slow devices (2), interrupts, ODT, scanline (2), PS/2 (2), video (8) |
| SST39SF010A-55 (PLCC-32, socketed) | 10 | the control store (9, 8K words of each used), the boot flash |
| 74F181, 74F182 | 4, 1 | the ALU |
| IS61C6416AL-12 (SOJ-44) | 2 | the register file |
| AS7C4096A-12 (SOJ-36) | 4 | the RAM |
| 74ABT541 | 7 | the clock buffers (2), PC's read-back (2), the flags word, the scanline's read-back, the task's address |
| 74ABT574 | 10 | the operand latch (4), the video's buffer (4), the copper's target line, the PCM's sample |
| 74ABT245 | 5 | D to MD (2), the byte crossing, the CF card's data (2) |
| 74HCT541, 74HCT688, 74HCT175, 74HCT14 | 1 each | the CF card's control, the scanline compare, the palette bank, the PS/2 inputs |
| TL16C550C, MAX232 | 2, 2 | the serial ports |
| 82C54, IMS G171 | 1 each | timer, palette |
| DAC0832, MCP6002 | 1 each | PCM: the DAC, the op-amp (the sample's latch is a 574) |
| TL7705A | 1 | reset |
| oscillators | 2 | 50.35 MHz, 1.8432 MHz |
| CompactFlash socket | 1 | |
| **total** | **111** | |

Not counted: resistor networks, decoupling, the connectors (VGA, two
DE-9s, two PS/2 sockets, the sound jack, power), the buttons, jumpers
and headers. The sections: clock 6, control store 17, flags 2, register
file 6, ALU 11, result 5, immediate unit 6, address 7, memory 10, I/O
29, video 12 ([performance.md](0047-rfc-chibi-heron/performance.md#parts)).

## Part II: Discussion

### 13. How fast

The suite on the model, which the netlist matches cycle for cycle
([performance.md](0047-rfc-chibi-heron/performance.md)):

| | Chibi Heron | The full Heron (RFC 0031) | The first cut |
|---|---:|---:|---:|
| the suite (18 programs, not hello or interrupts) | 1758 ms | 465 ms (3.8× faster) | 3599 ms (2.05× slower) |
| per instruction, on average | 1239 ns | | |
| per microinstruction | 6.43 ticks, 128 ns | | 158.9 ns |

Ordinary code (fib, life, sieve, queens, sort, strings, rpn) runs at
430–590 ns an instruction, 1.8–2.7 times the full Heron's time. Where
the time goes:

- **Multiplies and divides** still go a bit a step: MULFX (mandel's
  fixed point) is 30% of the suite's time by itself, at 1258 ticks
  (25 µs) a time. The divides are about 900–1000 ticks. A multiply by a
  number under $2^{16}$, or a divide of one, takes 16 steps instead of
  32; mandel's signed fixed-point operands mostly don't qualify. mandel
  is 6.3× the full Heron, matmul 4.0, bignum 4.4.
- **Shifts and rotates** go a bit a step: sha256's rotates take it to
  8.5×.
- **Memory and calls:** `MOV` averages 26 ticks, a `JMP` through a
  table (vm's dispatch) 82, `PUSH` 39.
- **The flat store's price:** a microinstruction (4 ticks, about 80 ns)
  on every instruction whose first step depends on d: JMP, CALL, CLR,
  INC, DEC (d is the mode), Jcc (the condition), LDM, STM and MTSR (a
  register), MULFX and the system group (a field checked). The paged
  store's decode took d into the address. And an I/O access is a tick
  longer. On the suite that's 1.2%, nearly all of it JMP's; code with
  more calls, returns and indirect jumps pays more. Entering at opcode ×
  16 + d would take it all back ([19](#19-proposals)).

### 14. Timing

Static timing analysis of the netlist (`heron chibi hw sta`) takes
every distinct microinstruction (626 cases, an access at MAR twice: to
the RAM and to the I/O space) as a case. Its control
bits are held at their values from the time the flashes give them. The
analysis finds the ticks each half needs to meet every setup: the
registers' at the half's end, `U_MEMC`'s before the half's second tick
(the UARTs' address and select before their strobe, a tick later),
the register file's address and data around its write strobes, and the
RAM's. Phase F is a case of its own, the control bits unknown.
Worst-case delays throughout. It writes the table (`ticks.json`) that
the control store's LEN and HLEN are filled from, and a unit test fails
if a microinstruction isn't in it.

- **Low halves:** 391 of 2 ticks, 235 of 3. **High halves:** 218 of 2,
  123 of 3. **Phase F:** 3 ticks, all its requirements met. No half
  needs more than its field can say, and no I/O half more than 6.
- **The slowest low half** is an ADD that sets the flags: 58.5 ns of
  its 59.6 (3 ticks), from the register file's address at the half's
  start, through its 12 ns access, the ALU, the carry lookahead, to Z.
  The slowest high half (56.8 ns) reads the RAM: MAR, the row's chip
  enable, the RAM's 12 ns, the transceiver, the ALU, N. The flat
  sequencer, the 16-bit register file SRAMs and the 574s of the operand
  latch left both as they were.
- High halves have a floor of 2 ticks (HCK must fall between the
  halves' edges), and an access at MAR one of 3.

The chip-level simulator checks the same, and more: every device's
setup, hold and widths, with the real ticks and the video's reads. Its
runs report no violation, and no bus driven twice for longer than the
1.0 ns of a handover.

### 15. Why it's built so

- **Two halves rather than a 32-bit datapath.** A 32-bit ALU, latch and
  result would be about 22 more packages for 1.6×. The halves give
  32-bit operations in one microinstruction, at a 16-bit datapath's
  cost, with the variable ticks giving each half only the time it
  needs. Emily chose this, with variable ticks, over the first cut's
  fixed cycle and over a "system half".
- **Ticks from the timing analysis.** Each microinstruction is as long
  as its paths, not as the slowest: 6.43 ticks on average, against a
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
  branches. Emily decided against pipelining for now
  ([pipelining.md](0047-rfc-chibi-heron/pipelining.md) has the
  estimate).
- **A flat store** (Emily's choice). The paged store's address was the
  opcode, the dispatch nibble, a page and a step: the microcode was
  bound to the instruction's encoding and to 32-step blocks, and some
  modes didn't fit (the tables of CLR, INC, DEC, MULU and MULS). Now the
  only tie is that the opcode is the first parcel's low byte; the
  routines are shared where alike, ODT and the copper live anywhere, and
  every word's next address is its own (no incrementer, a jump costs
  nothing). Its price: a few more microinstructions where the first step
  depends on d ([13](#13-how-fast)). The sequencer costs what the paged
  one did: three 22V10s for µPC and one for the nibble, against the
  opcode's, the nibble's and the step's three and a 541. The 13-bit
  jump target fits the 72 bits because the register selects are coded
  together (K, d or s in 6 bits, and "no write" one of them), and PT and
  HALT went.
- **22V10s for decode and state machines** ([18](#18-the-board)).
  Emily's rough rule of this round: GALs for decode and state machines,
  74 parts for registers, counters, muxes and bus drivers. Most of the
  machine's registers are fused with their muxes and decode in one
  22V10 (PC and MAR count, load and drive the bus; the result registers
  shift and extend), and as 74 parts they'd be two to four chips each:
  about 35 packages for the lot ([19](#19-proposals)). Where a GAL was
  only a register, it's a 574 now: the operand latch and the copper's
  target line. The latch's 574s have no enable, so `U_LCK` gates their
  clocks (HCKA's and HCKB's edges, when the word loads L) and also gives
  their high half's enable; its spare macrocells took the device task's
  requests and TCHG, which no longer fit `U_TASK`.
- **Devices in microcode** (Emily's choice of this round). PCM and the
  PS/2 receivers are the device task's. The hardware is only what
  software can't do in time: the timer's steady rate and the DAC's second
  latch for the samples, a synchroniser and an edge flag for each PS/2
  clock. Against it: both stop while ODT runs (it has no task points),
  and tasks don't interrupt each other, so a copper burst longer than a
  sample period (45 µs at 22 kHz, about 40 MOVEs) makes the DAC repeat a
  sample. At a task point the device task goes first.
- **2 MB, not 4** ([20](#20-open-questions)).
- **I/O at A30, decoded from the address bus.** Emily wanted the devices
  in the top 64 KB, the busiest in the top 32 KB, and all of RAM kept;
  A31 is left for forcing ([19](#19-proposals)). The low address bits
  exist only on the bus, which settles a tick into the half, so the
  I/O strobes start a tick later and an I/O half is 6 ticks, not 5. A
  registered copy of A14–A12 would avoid that, but MAR's 22V10s have
  no room for it.
- **No SWP.** The byte-swapped result (two 574s) served only REV and
  ADD.B4, which now shift: REV takes about 22 microinstructions, ADD.B4
  eight more. Emily's call: they don't deserve chips.

### 16. How it was checked

- **The model against the simulator** (`heron chibi check`): every
  program of the suite, the output, the registers, the flags and the
  memory as draft 2's simulator leaves them. The unit tests run the long
  routines on chosen and random operands, with aliased registers and
  16-bit operands for the short paths: multiply, divide, MULA, MULFX,
  CLZ, REV, the tagged operations, LDM and STM with their table modes,
  ADD.B4, MERGE, FFS, POPC, the special mode's tables for INC, DEC, CLR,
  CALL, MULU and MULS, and the illegal operands that must trap before
  anything changes (a jump's byte operand, INC of an immediate).
- **The netlist against the model** (`heron chibi hw test`): the
  chip-level simulator runs the netlist with worst-case delays. Its
  22V10s run from their equations, the flashes from the microcode's
  images, and the RAM is preloaded with the program. The output, the
  registers, the flags, the RAM and every instruction fetch (address,
  parcel and cycle) are the model's. On this revision (the flat store,
  the new I/O map) that's been run for hello, fib, interrupts, monitor,
  queens, rpn and strings; the paged store's netlist ran all twenty.
- **The board's own devices at chip level:**
  - ODT: a session that opens memory and registers, writes, steps
    through a loop (the flags must survive) and goes on, on the UART
    model with its timing;
  - the copper: its list writing to the console at two lines a frame;
  - the device task (`heron chibi hw devices`): eight samples played at
    the timer's rate (the program sees PCMPTR reach PCMEND), and two
    bytes from the keyboard model, received a bit at a time.

  Each matches the model's outcome with no violation. On the model, a
  unit test also has the mouse's frame received while the keyboard's
  are, and checks the samples the DAC was given.
- **Not checked:** the picture, the palette, the DAC's analog side, the
  CF card, the mouse at chip level, UART 1.

### 17. The first cut

The first cut (still in the study: `board.py`, `routines.py`, `rtl.py`,
`sta.py`) was 70 packages: a 16-bit operation a cycle, one fixed cycle
of 158.9 ns (four VGA pixels, the video counted in CPU cycles), 36
22V10s, a 67-bit control word, and none of the devices but the UARTs,
the PS/2 ports and the video's fixed colours. It ran the suite at 7.7
times the full Heron's time. Its static timing needed 147.1 ns. The
two-halves machine spends 40 more packages: on the devices Emily's
decisions added (palette, timer, sound, CF, serial levels, interrupt
controller, ODT, scanline and copper), on the second half of the
latch and results, and on the decoupled video and the clock generator.

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
  enables. The 52 would be some 170–260 chips of 74 logic. Every one's
  pins and equations are in [gals.md](../studies/chibi/gals.md),
  generated from the netlist.
- **Programming** is one cheap universal programmer (an XGecu T48 or
  similar) and a JEDEC file each. The flow doesn't write JEDEC files yet
  ([21](#21-open-tasks)).
- **Grades** (Emily's choice of this round: DIP-24 where the speed
  allows, and slower parts where they're enough, for power). The search
  (`heron chibi hw grades`) gives each 22V10 the slowest grade that
  leaves every microinstruction's ticks as with the -5s, alone and all
  together; the GALs column is its mix:

  | Grade | Package | tPD, tCO, tS (ns) | ICC typical, max (mA) | GALs |
  |---|---|---|---|---:|
  | ATF22V10C-5 | PLCC-28 only | 5, 4, 3 | 85, 130 | 10 |
  | ATF22V10C-7 | DIP-24 | 7.5, 5.5, 3.5 | 85, 130 | 22 |
  | ATF22V10C-15 | DIP-24 | 15, 8, 10 | 65, 115 | 9 |
  | ATF22V10CQZ-20 | DIP-24 | 20, 12, 14 | 40, 80 clocked; µA while its inputs are still | 11 |

  The search keeps the clock generator, the memory's strobes and the
  latch's clocks at -5 (the analysis takes their timing as given), and
  the master clock's GALs at -15 or faster (the CQZ-20's tCO + tS, 26
  ns, is over a tick). It has no case with a task running, so `U_TASK`
  and `U_LREQ`, which give µPC's address and its handover then, are
  -7 at least; the chip-level runs of the copper and the device task
  time them. `U_SLOWD` is -7, not the CQZ-20 the search allows: its
  strobes are the CF card's and the palette's, which nothing times yet.

  **That mix fails at chip level** (**open**): `U_IRH` at -15 misses its
  setup by 3.4 ns on the fetch's parcel, UART 0's select is 7 ns late
  with `U_IODEC` a CQZ-20, and ODT's session goes wrong. The analysis
  misses those paths; until it's found why, every 22V10 is the -5.
- **Power.** The grade alone saves little on these parts: the -5, -7
  and -10 draw the same. The -15 draws a quarter less, and the
  zero-power CQZ-20 half. The search's mix would draw 3.7 A typical,
  6.1 A at most, against 4.4 A and 6.8 A all at -5: 15% less. The
  22V10s are most of the board's current (the rest isn't counted yet).
- **The aim:** the -5s in PLCC-28 sockets, the rest in DIP-24, soldered
  or socketed where an equation may still change; the flashes in PLCC-32
  sockets, as the parts that get reprogrammed. As built, all 52 are the
  -5 in PLCC-28.

**Placement** on RFC 0046's column grid, no routing
([placement.md](0047-rfc-chibi-heron/placement.md), `heron chibi place
--write`). The least board is now 375 × 250 mm (3:2, 79% of its grid,
62.9 m of wire); the least square is still 315 × 315 but looser (73%
against 79%), the least 4:3 360 × 270 (79%). ATX (305 × 244) would need
106% of its grid: nearly. With the 22V10s in DIP-24 the 4:3 board is
340 × 255, 11% less area. The board's size is open: E-ATX (305 × 330) fits with
the non-critical 22V10s in DIP.

### 19. Proposals

These are written up for Emily's decision; none is built.

**Forcing bit 31 (null checks and pointer tagging).** If data addresses
had to have bit 31 set, a null pointer, and any value tagged as a
non-pointer by bit 31 clear, would trap on dereference, for free. What
it would take:
- **The map** is ready for it: A30 selects the I/O space and A31 is
  ignored, so RAM at 0x8000_0000 is the same RAM, and the devices'
  addresses (0xFFFF_xxxx) have bit 31 set already.
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
  4× faster multiplies, mandel 2–3× faster, the suite about 1.3×. At
  111 packages it fits the budget. No help for divides.
- **A multiplier chip:** the 16 × 16 parallel multipliers (IDT7216,
  ADSP-1016) are long out of production, and there are none in DIP.
- **Divides:** a reciprocal table in flash and a Newton step, or SRT
  steps; neither is cheap in microcode on this datapath. I'd leave them.

**Pipelining the control store** ([pipelining.md](0047-rfc-chibi-heron/pipelining.md)):
not now, Emily decided. The estimate, for the record: a register for the
executing word (6–8 × 574) alone gains under 10%; with the register
file's writes moved into the halves and 45 ns flashes (which the flat
store's 8K words allow), about 1.38× for about 10 packages.

**The GAL rule, the rest of the way.** What Emily's rule
([15](#15-why-its-built-so)) would make 74 parts beyond what's built,
each against the 22V10s it replaces:

| GALs | What they do | As 74 parts | Packages |
|---|---|---|---:|
| µPC (`U_UPCL`, `U_UPCM`, `U_UPCH`) | the 13-bit register, its next address (jump, branch, decode) and reset | 2 × 574, 4 × 74F157 (the decode or the jump; reset by forcing 0), the branch's OR and the condition's XOR in gates | +3 to +4 |
| the branch's nibble (`U_NG`) | a 3-way mux | 2 × 74F153 | +1 |
| the register byte (`U_IRH`) | d and s, loaded, d + 1, s − 1, s ← x, d ≠ s | 74F163, 74F169, a 157, a comparator | +3 |
| the register file's addresses (`U_RFA0`–`U_RFA2`) | the write address and the read's mux | a 574, 4 × 74F153 | +2 |
| the result registers (`U_YLO`, `U_YHI`, `U_YBLO`, `U_YBHI`) | registers with the shift, byte extension, zero and fill | 4 × 574, 10 muxes (157s, 153s) | +10 |
| PC and MAR (`U_PCA`–`U_PCC`, `U_MARA`–`U_MARC`) | counters with their loads and bus drivers | 11 × 74F163, 6 × 541 | +11 |
| the video's counters (`U_VF`, `U_VH`, `U_VV`, `U_LINE`) | counters and their decodes | 74HC590s or 163s, the decodes in 22V10s | +2 to +4 |
| the pixel shifter (`U_SHA`, `U_SHB`) | 16 bits shifting 4 a pixel | 4 × 74F166, the blank in a 22V10 | +2 |

All of it: about +35 packages (some 145) and 22V10s down from 52 to
about 25, with slower paths where a mux joins one (the results, µPC)
and a carry chain grows (PC). **My lean:** stop here; take the video's
shifter and counters only if the board's 22V10 count matters more than
4 packages.

- **Entering at 0x1000 + opcode × 16 + d:** the decode does the
  branch on d, so none of the twelve instructions above pays for it
  ([13](#13-how-fast)). Still a fixed decoding; the microcode then also
  relies on d being the first parcel's top nibble. µPC's low 22V10 takes
  MD15–12 instead of MD3–0 (no pins more). The entries are 4K words,
  mostly copies, and the rest of the store about 4.1K: at the edge of 8K.
  A 14-bit µPC is the safe way, its jump target's extra bit found in
  the word or a tenth flash (0 or 1 package).
- **The condition from d**, the smaller fix for Jcc alone: the CND code
  A0 is unused. As "draft 2's condition in d", it would let every Jcc
  share its first word. It needs N, Z, C, V and d in one 22V10 with a
  spare output (no chip if one has room; to check).
- **5-tick I/O halves again:** a registered copy of A14–A12, loaded with
  MAR, so that the select is steady from the half's start: one 22V10
  more (MAR's three are full).

**The expansion port** (0xFFFE_0000, 64 KB, reserved): its select in a
22V10, two 74ABT245s for MD (or one for an 8-bit port) and a 541 for
the address and strobes, a wait line into HOLD, an interrupt line:
about 3 packages and a connector.

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
2. **4 MB?** Four more SRAMs and A21 in PC and MAR: about 5 packages.
3. **The GAL rule:** whether to take it further than the swaps built
   ([19](#19-proposals)'s table).
4. **The boot format** (tentative).
5. **The deviations from RFC 0028** in [8](#8-interrupts-and-exceptions).
6. **The proposals** in [19](#19-proposals): forcing bit 31, the
   multiplier in flash, entering at opcode × 16 + d (or the condition
   from d), 5-tick I/O halves, the small features.
7. **The expansion port:** 64 KB reserved; whether to build its buffers
   now (about 3 packages), and how wide.
8. **The supply:** the 22V10s alone draw 4.4 A typical, 6.8 A at most,
   all at -5 ([18](#18-the-board)); the rest of the board isn't counted
   yet.
9. **Parts availability**, to review (the IS61C6416AL, the 74F181 and
   74F182, the IMS G171, the DAC0832, the TL7705A).
10. **The device task's open parts** ([7](#7-the-io-space)): sending to
    a PS/2 device in the task, and the PCM's analog side (the reference,
    the output's level and filter).

### 21. Open tasks

- **The chip-level suite on this revision**, all of it (this draft ran
  seven programs, ODT's session, the copper's test and the device
  task's).
- **Configurability** (Emily's note): ODT on or off, boot options; a
  jumper read through a spare input would do, the microcode choosing.
- **The task-constraint checker:** a test that the tasks' microcode
  keeps to a task's rules and every task point to its (MAR, flags,
  L).
- **JEDEC files** for the 22V10s from their equations.
- **Tests at chip level** of the picture and palette, the CF card, the
  mouse and UART 1.
- **The board:** the non-critical 22V10s in DIP-24, footprints for the
  clock jumper and the sound jack (placed as buttons now), the
  placement again, then routing.
