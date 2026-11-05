# Reed: the system half, and a kernel on it

Findings for [RFC 0049](../0049-rfc-board-first.md)'s section 14 (design
A, Reed), from building RFC 0029's system half on Reed, finishing draft 2's
instruction set, and running a small kernel on it (2026-11-05). The code
is [studies/reed](../../studies/reed/README.md): `ucode_sys.py`, the
boards, `model.py`, `systest.py`, `kernel.py`, `sw/`.

Emily asked for exceptions and the system instructions, the rest of the
instruction set, and a kernel, the system's design left to me ("very
malleable"). Part I is what Reed is now, as a specification; Part II how
it's built, what checks it, and what it costs.

## Contents

- [Part I: Reed's system](#part-i-reeds-system)
  - [1. RFC 0029, and how Reed differs](#1-rfc-0029-and-how-reed-differs)
  - [2. Interrupts](#2-interrupts)
  - [3. The address space](#3-the-address-space)
  - [4. What isn't there](#4-what-isnt-there)
- [Part II: Building it](#part-ii-building-it)
  - [5. The hardware](#5-the-hardware)
  - [6. The microcode](#6-the-microcode)
  - [7. The checks](#7-the-checks)
  - [8. Timing](#8-timing)
  - [9. The kernel](#9-the-kernel)
  - [10. What it costs](#10-what-it-costs)
  - [11. Open, and next](#11-open-and-next)

## Part I: Reed's system

### 1. RFC 0029, and how Reed differs

Reed implements [RFC 0029](../0029-rfc-draft-2-system.md)'s system half
as it stands: supervisor and user mode in sr's S, sr's layout (NZCV,
IPL in bits 27-24, T, I, S), the privileged instructions, special
registers 8-15, the supervisor's window, the page map read through `mapa`
and `mapd`, 256 register banks (supervisor mode in bank 0, user mode in
`bank`), precise faults, the vectors at `vbr` plus RFC 0029's offsets, a
frame of the PC then sr pushed on bank 0's sp, and `RTI` popping them.
Every instruction of [RFC 0028](../0028-rfc-draft-2-isa.md) but the
tentative ones (5.10) is there.

Where it differs, each **open** for Emily:

| | RFC 0029 | Reed |
|---|---|---|
| Interrupts | eight levels from the CPU card ([RFC 0040](../0040-rfc-interrupts.md)) | the IO board's sources, each at a fixed level, through its controller; IPL there too ([2](#2-interrupts)) |
| The translated space | 16 MB, contexts of 4096 pages | 4 MB, contexts of 1024 pages; `mapa` = context × 1024 + page |
| The map on | always | while `ctx` has bit 31 set (`MTSR ctx`); off at reset, so the programs that know nothing of it run as they did; RFC 0029's reference ignores bit 31 |
| `mapd` | reads the entry at `mapa` | write only: it reads 0 (the map's SRAMs have no way back onto B) |
| `vbr` | special register 15, if `bkpt` moves | special register 15 (there is no `bkpt`) |
| `far` | the faulting address | its bits 21-0 and 31; bits 30-22 read 0 |
| A supervisor's misaligned access to a device | doesn't happen | the device sees its strobe (the cycle is cancelled, but too late for the I/O space's strobes, [5](#5-the-hardware)) |

### 2. Interrupts

Chibi Heron's scheme ([RFC 0047, 8](../0047-rfc-chibi-heron.md#8-interrupts-and-exceptions)),
fitted to RFC 0029's levels: one request line from the IO board, a vector
per source.

- **Levels:** the video's frame 7, the timer (the 82C54's OUT0) 6, UART 0
  5, UART 1 4, the keyboard 3, the mouse 2, the CF card 1. Level 8 is
  unused. A source holds its request until its handler clears the cause.
- **IPL** is the controller's register: IRQ is up while a source above it
  is. sr's IPL is read from there, and written there by `MTSR sr`, `RTI`,
  `SPL` and an interrupt's entry.
- **Taken** at a decode, while I is set; never straight after `EI`.
- **The entry** reads the controller's vector register (offset in bits
  7-0, the level in bits 27-24), writes it back (IPL = the level), pushes
  the frame (sr with the old IPL) and jumps to `vbr` + 0x3C + 4 × the
  level: RFC 0029's `vbr` + 0x40 + 4(L - 1). If the request has gone, the
  offset is 0x3C's: a vector that should hold an `RTI`.
- **The controller's registers**, at physical 0x4000_5800 (0xC000_5800
  through the window): 0, read the vector, written IPL from bits 27-24 (as
  sr has it); 4, read the CPU's flags (bits 3-0) and IPL (27-24), written
  IPL from bits 3-0 (`SPL`'s).

### 3. The address space

- **The map off** (reset): an address is physical, but for bit 31, which
  is dropped. RAM is 4 MB, repeated; the I/O space is the addresses with
  bit 30 set.
- **The map on:** in user and supervisor mode alike, an address with bit
  31 clear goes through the map's context `ctx`; above 4 MB (bits 30-22
  not all 0) it faults. An address with bit 31 set is the supervisor's
  window onto the physical space, and faults in user mode.
- **A map entry:** the physical page (bits 21-12) and V, W, X, as RFC 0029
  has them.
- **`fsr`** as RFC 0029's bits 0-7, set by page faults only (as draft 2's
  simulator does); `far` by page faults and address errors.

### 4. What isn't there

Trace (T is kept in sr, but no trace exception comes); the non-maskable
interrupt; `bkpt`; a bus error (nothing answers: a read gives what the
bus floats to); the message level's bank and sr's M; `BCOPY` and RFC
0028's tentative instructions, which are illegal; `LEA [r + x]` with a z
of 3 doesn't trap (every other use of it does).

## Part II: Building it

### 5. The hardware

| Board | Packages | Area | What's new |
|---|---:|---:|---|
| CTRL | 72 (72) | 64.4 (64.2) | its microword registers 823s, cleared by KILL_n; RUNOK and the fault's entry; ILEN and PC bit 31 (U_PCL); FFQ and the fetch's fault; CND KILL, FFQ, ILEN0-1, IRQP; CCBO and CCBD to U_IQK |
| ALU | 71 (71) | 69.2 (69.0) | its microword registers 823s; EB, the bank (an 823 on the register file's address bits 13-5); the flags loaded from F (NSZ LOAD); KILL_n on the write strobes; U_RFT folded into U_RAG1 |
| MEM | 81 (66) | 66.8 (52.8) | the page map (two AS7C4096As), the window's bypass and the map's write drivers (four 541s), CTX; U_VA, U_PF, U_MAPC, U_SYS: S, FAULT, KILLQ, KILL_n, FFLT; FAR and FSR (four 823s) |
| IO | 37 (30) | 35.2 (28.6) | the interrupt controller (U_DXS, U_PRI, U_IPL, U_DZG, U_ICR, two 541s); a byte's read gives 0 in bits 15-8 (U_DZB) |
| total | 310 (288) | 276 (255) | |

(In brackets, before.) Every board stays within RFC 0049's 70 units; ALU
has 0.8 left. Three new backplane lines: FAULT (AERR's, renamed),
KILL_n and FFLT; four are still free.

**A cancelled cycle.** A load or store that faults (misaligned, an index
parcel's z of 3, or the page map's reasons) raises FAULT on MEM. The
next address is then 0 (RUNOK low in the next-address GALs); from the
cycle's fourth tick (LATE) KILL_n clears CTRL's and ALU's microword
registers, so that the word does nothing more; KILLQ, FAULT registered,
holds KILL_n through the next cycle as well, whose word was fetched
already. The register file's write strobe doesn't come while KILL_n is
low, and that write is the word before's: so a fault also cancels the
word before its access as far as its result goes, which makes `[r]+` and
`-[r]` precise for free. MEM's own word isn't cleared (FAULT comes from
it); its strobes are gated instead. Word 0 tells a fault's entry from
reset by KILL, which the cancelled cycle before it has. PC moves on as an
instruction starts only in a cycle that isn't cancelled (DEC1K), and
ILEN keeps the executing instruction's length, so a fault's entry takes
the instruction's own address off PC. FAR and FSR latch the address and
why at the faulting cycle's end.

**Why LATE.** At first KILL_n followed FAULT from the cycle's third tick
(CYC low). At chip level a store through the map then ran with A
undriven: FAULT, from the map's SRAMs, was still settling, and its glitch
cleared the ALU's word. From the fourth tick it has settled; a word that
may fault is 7 ticks long ([8](#8-timing)).

**A fetch's fault** (FFLT, the map's) leaves the queue's slot empty and
sets FFQ on CTRL, which stops the fetches; a decode that then finds its
instruction not all there goes to IVEC, the interrupt's entry, which
tells the two apart by CND FFQ (FFQ and not READY, so that an interrupt
due as well goes first).

**What the IO board needed.** Its interrupt controller is new. What was
wrong before, found once software used it (the fourth is MEM's side):
- DEVX's registers were selected by A13-A12, which DEVX's own decode fixes:
  the interrupt controller and the DAC could never be selected. Now by
  A11-A10.
- A byte read from an 8-bit device gave its pulled-up bits 15-8.
- A write's strobe started again in the next cycle's first tick, as MEM's
  IOWR_n reaches the board only then: the timer was written twice. A
  write's strobe now ends at the write phase or when its count is done,
  and can't restart while the access lasts.
- MEM's I/O strobes are gated only by what's settled as the cycle starts
  (KILLQ, and a user's access with the map on), not by FAULT, so that
  WAIT_IO reaches the clock card in time.
- At chip level the VIDEO board's frame interrupt (level 7) comes once a
  frame, whether or not software wants it: a kernel needs its vector,
  which acknowledges it with a write to the video's control register. The
  model has no video, and never takes it.

### 6. The microcode

`ucode_sys.py`, 11,178 words in all now (of 16,384).

- **The special registers** live in the system bank (EB 0x100): sr's S, I
  and T, `vbr`, `bank`, `ctx`, `mapa` (as the page shifted for MAR and the
  context apart), `far`, `fsr`, the controller's address and four
  constants, and the exception's temporaries. A word reaches them by
  switching EB and back; one K a word makes MQ the carrier between banks.
- **The constants** (the microcode's K registers 16-28) are in every bank:
  reset makes bank 0's and the system bank's, and `MTSR bank` a bank's the
  first time it picks it (when its K_M1 isn't -1).
- **An exception's entry:** the saved PC (a fault's less ILEN's parcels)
  and the offset into the system bank, S set (before the window is
  reached), the status register's flags and IPL ORed into sr, the frame
  pushed on bank 0's sp, I and T cleared, the jump to `vbr` + the offset,
  EB 0.
- **Precise faults:** besides the hardware's, `DIVU` and `DIVS` test a zero
  divisor on ST, not the flags; `SAVE` and `RESTORE` move sp after their
  last access (three words more each); `RTI` changes sp only after both
  its loads, and S only after its last access to the window.
- **The rest of the instruction set:** `ADC`, `SBC` (Z only if it was set
  too), `CLZ` (a bit a word: 2 × the count + 4 microcycles), `DIVUL` (the
  restoring divide with the remainder's carry out, five words a bit; r0 ≥
  rs sets V alone), `MOVS` of the special mode's immediates, `MULU` and
  `MULS` of the indexed special modes (the multiply's body now shared, 1,900
  words fewer), and the negative abs24 and d24, sign-extended.

What each costs, in microcycles from the instruction's start to the next's
(the handler's first, for an entry), on the model:

| | Microcycles | At 7 ticks |
|---|---:|---:|
| `SWI` to its handler | 39 | 5.4 µs |
| an interrupt, the decode to its handler | 41 | 5.7 µs |
| a misaligned access to its handler | 51 | 7.1 µs |
| `RTI` | 27 | 3.8 µs |
| `MFSR sr` / `MTSR sr` | 11 / 20 | |
| `MTSR ctx`, `MFUR`, `MTUR` | 9, 9, 11 | |
| `SPL`, `EI`, `DI` | 7 each | |

A page fault's entry adds about 30 microcycles for `fsr` (`far` shifted
by hand); an interrupt's and an I/O access's wait states are the IO
board's.

### 7. The checks

- **Against draft 2's system simulator:** `sw/systest.s` runs the same on
  Reed's model and on draft 2's RFC 0029 machine (`Machine::new_system`,
  reached from Python through a new binding, `heron.native.v2.SysMachine`):
  the output, a log of all 17 exceptions it takes (vector, saved PC, sr,
  `far`, `fsr`), the user's pages and banks 0 and 1. It covers sr and ccr,
  `MTSR sr`, `SPL`, `EI`, `DI`, `SWI`, an illegal instruction, a divide by
  zero, misaligned accesses, the page map, user mode in bank 1 through
  `RTI`, a privilege violation, the window from user mode, a read-only
  page, a fetch from a page without X, and a page fault mapped and retried
  (`heron reed systest`, and a unit test).
- **At chip level,** the same program in lockstep with the model, every
  one of its 15,599 microcycles to its `HALT` (a unit test). Interrupts
  can't be in lockstep (the 82C54's timing isn't the model's), so two
  programs whose results don't depend on when they come: `sw/irqtest.s`,
  the timer's interrupt in supervisor mode (the frame, sr in the handler,
  the status register), and `sw/irquser.s`, a user-mode loop in bank 1
  with the page map on, the timer interrupting it a few hundred times: the
  same at both levels (unit tests).
- **The fuzzer** misaligns a share of its pointers: 405 cases that fault,
  across the memory families (operands, stores, `INC`/`DEC` of memory,
  `LDM` and `STM`), all precise at the address error's vector, as are the
  divide errors. New families for the new instructions; every family
  passes 300 cases.
- **The workloads,** RFC 0050's twelve, still give their output at their
  full size.

### 8. Timing

Static timing (`heron reed sta`) with the system's state: its cases start
with no fault the cycle before, and assume none in the cycle (a fault's
cycle is cancelled; its own timing is what LATE is for). The accesses are
timed twice, the map off and on:

| Kind of microcycle | Before | Now, the map off | The map on |
|---|---:|---:|---:|
| load, pass | 6 | 6 | 7 |
| load, add | 6 | 7 | 7 |
| load byte | 6 | 6 | 7 |
| store | 5 | 5 | 6 |
| fetch | 6 | 6 | 7 |
| load, jump | 6 | 7 | 7 |
| load, index size, MOVS | 6 | 6 | 7 |

The other kinds are as they were (the window's bypass adds a 541 to every
access; the map, its SRAMs). So a word with a load, a store or a fetch is
7 ticks now, which is also what an I/O device's WAIT_IO needs to reach
the clock card in time; the rest 5 or 6. Every cycle at 7, the bound
the times here are quoted at, covers all of it (not a decided length:
[clocking-and-front-end.md, 6](clocking-and-front-end.md#6-the-write-phase-at-6-or-7-ticks)). What the analysis reported before still fails as it did
(the register file's handovers and glitches, deferred with the write
phase); the IO board, still untimed, has small setup failures left
(WAIT_IO at the clock card, -1.2 ns; the timer's address, -2.3 ns).

### 9. The kernel

`sw/kernel.s` is a small preemptive kernel, about 400 lines:

- **Processes in user mode,** four, each in a register bank and a page map
  context of its own, so a switch saves nothing: it rewrites the trap
  frame, sets `bank` and `ctx`, and returns (Fen's design, [report
  0036](../0036-report-fen.md)).
- **The timer** (the 82C54's counter 0 in mode 0, level 6) preempts, round
  robin; its handler writes the count again, which ends the request.
- **System calls** by `SWI`: write a byte, yield, exit, the pid.
- **Demand-zero pages** in each process's data and stack areas: a page
  fault there maps a zeroed page from a pool; any other fault kills the
  process.

Its processes: one counts in a loop the timer cuts into; one prints and
yields; one fills 64 KB of its data area (sixteen demand-zero pages, and
one of stack) and checks it; one tries the kernel's memory through the
window and is killed. The page map's contents are undefined after reset,
so the kernel first clears the processes' contexts (4096 entries, all
invalid). On the model (`heron reed kernel`), 709,000 instructions in
1.69 million microcycles, 209 ms as built:

```
Reed nucleus: 4 processes
1bd
killed process 3 at 0004300e, why 00000010
bbbbbbb
ac
aaa
all done
process 0: page faults 0, preempted yes
process 1: page faults 0, preempted no
process 2: page faults 17, preempted yes
process 3: page faults 0, preempted no
timer ticks: several
```

At chip level (`heron reed kernel --chip`), with its console in RAM (the
UART takes its baud rate's time there, and the timer's interrupts come
when the 82C54 says, so the runs part at once), it halts after 1,729,144
cycles, 236 ms of simulated time (the model, its console in RAM:
1,685,625), with the same results as the model's: each process's state,
how it ended, its exit code or why it was killed, its page faults, the
end's flag and the console's bytes. The only timing violations are the
clock card's WAIT_IO input, 17,988 times at worst −1.2 ns: the IO board's
timing (below), which the run reports apart.

### 10. What it costs

On RFC 0050's workloads at their full size, at 7 ticks, against
[microcode-and-model.md](microcode-and-model.md#6-the-easy-wins-built-2026-11-05)'s
after the easy wins: precise `SAVE` and `RESTORE` and the rest, 0 to 2.3%.

| Workload | Before | Now | |
|---|---:|---:|---:|
| `m6502` | 479 ns | 479 ns | 0.0% |
| `gfx_desktop` | 535 ns | 536 ns | +0.2% |
| `gfx_sprites` | 436 ns | 438 ns | +0.4% |
| `forth` | 456 ns | 457 ns | +0.2% |
| `lisp` | 347 ns | 348 ns | +0.4% |
| `db` | 540 ns | 549 ns | +1.6% |
| `editor` | 412 ns | 415 ns | +0.8% |
| `rts` | 687 ns | 698 ns | +1.6% |
| `ttf` | 506 ns | 511 ns | +1.1% |
| `textutils` | 470 ns | 481 ns | +2.3% |
| `cc` | 489 ns | 499 ns | +2.1% |
| `inflate` | 516 ns | 519 ns | +0.6% |

### 11. Open, and next

- **The differences in section 1**, each Emily's to accept or reject:
  above all the interrupts by source rather than RFC 0040's CPU card, the
  4 MB contexts, and the map's enable in `ctx`.
- **Register banking's microcode registers** (RFC 0049 14.6, 8): banked,
  their constants made per bank, as built; sharing them would need gates
  on the register file's address bits, which ALU has no room for.
- **The bit-31 trap** (14.6, 8): Emily's note was a trap on an address
  with bit 31 clear. As built it's RFC 0029's split: with the map on, bit
  31 clear goes through the map (and traps wherever nothing is mapped:
  with an empty context, every such access), bit 31 set is the
  supervisor's window and traps from user mode. A trap on every
  bit-31-clear access, whatever the map, would be a term in U_PF.
- **The IO board's timing,** which the kernel was the first to lean on.
- **Trace, the NMI and a bus error,** if they're wanted.
