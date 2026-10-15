---
number: 6
type: rfc
title: Instruction set ideas
status: open
date: 2026-10-14
context:
  studies: [v1_isa, v1b_hw, c_compiler, lisp, egret, graphics, kernel]
  commit: 2f81658
---

# RFC 0006: Instruction set ideas

An ideas RFC: a scratchpad of instruction-set ideas, each with its own
status ([RFC 0000](0000-rfc-repository-layout.md#ideas-rfcs)). The
evidence is in the reports each item links to.

| Status | Meaning |
|---|---|
| **adopted** | It's in draft 1 |
| **measured** | It has numbers behind it |
| **recommended** | Suggested for draft 2 |
| **decided** | Emily chose it; not built yet |
| **open** | Discussed, not decided |
| **not recommended** | The evidence is against it; Emily hasn't decided |
| **rejected** | Decided against, with the reason, so it isn't proposed again without new evidence |

Cycle shares come from the draft 1 timing model
([timing-model-v1.md](../studies/v1_isa/timing-model-v1.md)) unless they
say otherwise.

## 1. Adopted in draft 1

These came from the draft 0 evaluation
([report 0001](0001-report-draft-0-evaluation.md)); draft 1 has them
([isa-v1.md](../studies/v1_isa/isa-v1.md)):

| Proposal | Evidence or reason |
|---|---|
| Hardware `MULU`/`MULS`/`DIVU`/`DIVS`, `HI` register for the high half and remainder, `DIVUL` 64/32 | Software multiply/divide was 61–80% of cycles in mandel, matmul, bignum, interrupts |
| `HI` as the multiply/divide shift register (instead of `MULH`/`REM`) | One divide gives quotient and remainder; the product isn't computed twice |
| `INC`/`DEC` (and 1a `ADDI`) set only N and Z | Overwriting C forced the shape of the multiply loop and caused a flag bug |
| `SAVE ra-rb` / `RESTORE ra-rb` | `PUSH`/`POP` were 34% of queens' cycles and 21% of fib's |
| `SWI #n` with its own vector | The shared trap vector meant decoding `[PC − 2]` |
| `SETcc` | Programs had no set-on-condition; Life used a `NEG`/`ADC` trick |
| Shifts by n (immediate or register), `ROR` | Draft 0 shifted one bit per instruction; `SWAB`+`ZXT` were shifts by 8 in disguise |
| `CLZ`, `SWAP` (halves), `SXB`/`ZXB`/`SXH`/`ZXH` | Normalising, bitmaps, halfword work |
| Sticky Z for `ADC`/`SBC` | A 64-bit compare needs only one branch |
| `MFSR`/`MTSR` special registers (flags, `HI`) | Generalises `MFF`/`MTF` |
| PC-relative `LEA` and addressing | Position-independent code; replaces most `MOV r, #address` |
| Halfword and sign-extending loads | 32-bit machine |
| Immediate kinds: signed 16, unsigned 16, 16 shifted left 16, 32 | Most constants still fit 2 parcels |
| Jumps and calls with 16-bit PC-relative displacements, 32-bit absolute form | Absolute 32-bit targets would be 3 parcels |
| Vectors 4 bytes apart: reset, IRQ, illegal, SWI, divide error, address error | |
| Word accesses 4-aligned, halfwords 2-aligned; misaligned accesses trap | |
| One escape opcode kept free (1a's op F) | Future growth, floating point. 1b has no whole opcode left ([3.1](#31-room-left-in-1bs-encoding)) |

## 2. 1a against 1b, and the base for draft 2

**measured.** Both encodings were specified, built and measured on 20
programs ([report 0004](0004-report-draft-1-evaluation.md)).

- **1a, RISC-like:** load/store, register-register ALU, short and long
  load/store forms, 8-bit immediates.
- **1b, CISC-like** (IBM 360 RX / 68000 / x86 style): every main
  instruction is `F D M R`, one register plus one addressing mode out of 14:
  - register, quick constant (−16…15), `[R]`, `[R + d16]`, `[sp + 4R]`;
  - indexed `[R + Rx·s + d8]`, `[R]+`, `-[R]`;
  - byte and half variants;
  - PC-relative and absolute addresses, 16/32-bit constants.
  - At most one memory operand per instruction, which keeps faults
    restartable. Size is part of the mode. Indirect `JMP`/`CALL [mem]`.
  - Before 1b, measured on draft 0: 4.5% of draft 0's instructions were a
    load whose value fed the next ALU operation, and 97% of those loads
    were bytes, so memory operands need zero-extending byte forms.

Every study since has compared the two or used 1b:

| Workload | Cycles, 1b / 1a | Where 1b gains, or doesn't | Report |
|---|---:|---|---|
| The 20 hand-written programs | 0.90–0.93 | Auto-increment above all; the VM's table dispatch (−24%) and Life's memory operands (−16%). Register-bound programs are within 3% | [0004](0004-report-draft-1-evaluation.md) |
| The 15 programs in compiled C | 0.94–0.95 | Auto-increment in pointer loops. Memory operands save a cycle each; 4-bit constants cost the compiler more than a person | [0011](0011-report-c-compiler.md) |
| Graphics: assembly kernels / compiled C | 0.95 / 0.97 | Copies (−30% along rows) and anti-aliased text, by auto-increment; the rest is the same | [0019](0019-report-graphics.md) |
| Egret's interpreter | 1b only | Auto-increment is 21–37% of the loop's instructions, `JMP [r + r*4]` 7–14% | [0017](0017-report-egret.md) |
| The Lisp | 1b only | `CALL [r1 + 1]` through a code word, auto-increment for pushes, pops and `cons`; its stack slots are one parcel in both |  [0018](0018-report-lisp.md) |
| Kernel routines | 0.93 unrolled | 1b is 1–3 cycles faster calling through tables, and PC-relative data is free. 1a's one-parcel `[r + 4o]` would suit control-block fields | [0020](0020-report-operating-system.md#the-rest) |

- **Draft 2 builds on 1b.** **decided** (Emily, 2026-10-15). It's where
  most of the work since draft 1 has gone: the 213-chip hardware
  ([report 0012](0012-report-draft-1b-hardware.md)), the Lisp, Egret and
  the kernel study's v1bs. Section 3 collects what a 1b-based draft 2
  would change.
- **Draft 2 on 1a.** Report 0004 recommended it. That recommendation is
  withdrawn: it was based on faulty numbers (Emily, 2026-10-14).
  Section 4 keeps what 1a would have wanted, for the record.

## 3. For a draft 2 built on 1b

### 3.1 Room left in 1b's encoding

Every opcode of the `F D M R` format is taken
([isa-v1b.md](../studies/v1_isa/isa-v1b.md)). What's left:

- **Op A, `A c k R`:** the long jumps and calls use only k = 0 and 1 with
  R = 0, and everything else traps, so about 4,064 encodings are free:
  nearly a whole opcode. With `c` as a register, k = 8–F and R give each
  register a 7-bit field, enough for one one-parcel instruction with a
  constant up to 127 (`MOV rd, #'a'`, say), with k = 2–7 left over.
  Report 0004 counted only the modes and special forms when it called
  1b's encoding full.
- **Mode E,** the one reserved mode. The Lisp's v1bx uses it for a tagged
  register operand ([section 6](#6-for-dynamic-languages)).
- **Mode F's R = D–F,** three special operands.
- **The indexed mode's size z = 3.**
- **Op B, `B k M R`:** k = 0 and 1 are `JMP ea` and `CALL ea`; the other
  14 values are free, each with every mode.
- **Op F's register functions 9–E,** six of them.
- **The unary group's functions C–F,** four.
- **The shift group's count kind 3,** four forms (one per shift).
- **The system group's functions E–F.** v1bs takes them for `MFUR` and
  `MTUR` ([report 0020](0020-report-operating-system.md)).
- **Modes an instruction can't use,** which trap today: `ST` with a
  register or a constant, `LEA` with a register, a constant or an
  auto-increment mode.

That is room for register-only and `ea`-taking instructions, and for one
or two one-parcel forms with a short constant in op A. A new addressing
mode for every instruction has only mode E, which the Lisp's tagged
operand wants too; wider constants for every ALU instruction would need
bits in `F D M R` itself.

### 3.2 1b's gaps

From [report 0004](0004-report-draft-1-evaluation.md), the program
writers' notes ([report 0003](0003-report-draft-1-programming-notes.md))
and the later studies:

| Gap | What it costs | Status |
|---|---|---|
| Constants are 4 bits in one parcel: characters, masks, 16–255 take an extension parcel | 13% of 1b's operands in the hand-written source are 16-bit constants that 1a mostly fits in one parcel. Executed, 5.6% of compiled 1b operands are 16- or 32-bit constants, against 1.0% in the hand-written code ([report 0011](0011-report-c-compiler.md)). One-parcel 8-bit constants for every instruction have no room in `F D M R`; op A has room for one form with a 7-bit constant ([3.1](#31-room-left-in-1bs-encoding)) | **open** |
| No one-parcel `[r + small offset]` | Struct fields: bst's `inorder` and `height` are 3–5% slower than on 1a; a cycle per control-block field in kernel code ([report 0020](0020-report-operating-system.md#the-rest)) | **open** |
| No immediate `TST`/`BIC`/`MUL`/`DIV` (op F is register-only) | Constants need registers, and so callee-saved registers across calls | **open** |
| No byte or half auto-decrement, no half auto-increment | Backwards loops (`memmove`, `reverse`) | **open** |
| The indexed mode's displacement is 8 bits | A table's address needs a register of its own ([report 0019](0019-report-graphics.md#smaller-things)) | **open** |
| `[label + reg]` reaches only ±32 KB | 1b has no 32-bit displacement form | **open** |
| `POP` is `MOV r, [sp]+`, which sets N and Z | It can't sit between a test and its branch; `RESTORE r-r` can ([3.4](#34-which-movs-set-the-flags)) | **open** |
| No store-immediate | Zero is stored as `ST r0, ea` ([3.3](#33-r0-as-a-general-register)); `CLR ea` in op B would replace it | **open** |
| No memory increment (`INC [mem]`, `ADD [mem], r`) | fib's call counter is 30% of its time; a timer interrupt handler is a load, an add and a store. Memory-destination ALU operations in general were 0.4% of draft 0's instructions ([section 7](#7-not-recommended-and-rejected)) | **recommended** ([report 0004](0004-report-draft-1-evaluation.md#recommendations-for-draft-2)) |
| `CALL [r]+` and `CALL -[r]` move the register before pushing the return address, so a fault on the push can't be restarted | Found by the kernel study ([report 0020](0020-report-operating-system.md#what-was-hard)). The microcode should push first, or draft 2 drops the form (crc uses it) | **recommended** |

### 3.3 `r0` as a general register

**measured**, open. Only for a draft 2 built on 1b. In draft 1, `r0` reads
as zero in both encodings. In 1a it carries its weight: `[r0 + disp]` is
1a's only absolute address. 1b's encoding already covers the usual reasons
for a zero register: `#0` is a one-parcel constant (mode 1), absolute
addresses have their own modes (F4–F9) and `NEG` is a unary op. The idea is
to make `r0` a 15th general register.

- **What `r0` does in 1b now.** Every use in the 1b code (the programs,
  compiled C, the kernel and the Lisp runtime) is one of these:
  - **Storing zero:** `ST r0, ea`, since 1b has no store-immediate. That's
    13 of the 16 uses in the hand-written programs, 16 of the 24 in
    compiled C (the other 8 are `MOV rX, r0`, the same as `MOV rX, #0`),
    and 52 in the kernel and the Lisp runtime.
  - **A zero for instructions that only take registers:** `ADC r5, r0`
    (bignum), `SBC r6, r0` (sort), `MTHI r0` before a `DIVUL` chain, the
    kernel's `MTUR r1, r0` and `MTSR mapd, r0`, and the Lisp's
    `CMP.T r1, r0`.
  - **A zero in the hardware:** `NEG` and the multiply and divide routines
    read `r0` onto the A bus. A hidden register-file entry that the reset
    routine zeroes, like the loop constants at 24 and 25, would do the same.
  - **Unused:** `MOV r0, ea` tests a memory operand without a scratch
    register.

  Executed, it's 0.99% of the hand-written programs' instructions, and 92%
  of that is one store in sieve's inner loop.
- **What it costs:**
  - one register: 14 general registers instead of 15;
  - 5 OR gates, a microinstruction bit (`WR0`) and a reset step in the 1b
    hardware;
  - encodings: with `R = r0`, modes 2, 6, 7, 8, A and B are useless, and
    3, 9 and C duplicate the absolute modes.
- **Measured** on the 15 C programs for 1b, with the compiler patched two
  ways at `b6ffcfd` (not committed). The table gives cycles in the
  programs' own code, geometric means, D16-overlap / D32-overlap:

  | Change | Cycles | Where |
  |---|---:|---|
  | No zero register: a 0 needed in a register is a fresh `MOV rX, #0` | +1.3% / +1.1% | sieve +19% / +16%, bst +1% |
  | One register fewer (r14 not allocated), an upper bound on what a 15th is worth | +0.5% / +0.7% | sha256 +6% / +11%, wordfreq +0.8% |

  - The other programs barely change.
  - Sieve's cost is the compiler's: it puts the `MOV` inside the inner
    loop rather than hoisting it, and the loop has registers to spare.
  - The C library is left out because of a layout effect. Its size moves
    sieve's byte array on or off a word boundary, which changes `memset`'s
    time by 3.6×.
  - [Report 0004](0004-report-draft-1-evaluation.md) found no hand-written
    program short of registers either.
- **Replacing it:**
  - Op B (`JMP`/`CALL ea`) has 14 unused values of `k`. One could be
    `CLR ea`, which stores zero at any size, in any mode.
  - `ADC`/`SBC`, `MTSR` and `MTUR` would still need a zero from a register,
    or new forms. For example, the unary group has four free functions,
    room for an add-carry.
- **Against:**
  - It's about 1% either way, so performance doesn't decide it.
  - `r0 = 0` is part of the common draft 1 machine, and 1a needs it.
  - The kernel and the Lisp rely on it.
  - It keeps the compiler simple: a zero never needs a register of its own.

  Only worth it if a 1b-based draft 2 wants the register or the encoding
  space for something else.

### 3.4 Which `MOV`s set the flags

**measured**, open. Stores could be written as `MOV` too: `MOV [r2], r1`
for `ST r1, [r2]`, and `MOV -[sp], r1` for a push. Loads, stores, register
copies and constants would then share one mnemonic, and its flag rule has to
read well for all of them. In draft 1, loads, `MOV`, `MVI` and 1b's `POP`
set N and Z (C and V unchanged); stores don't.

- **Whose N and Z get read.** These are traces of every program in both
  encodings. Each cell says how often a move's N and Z were read before
  something overwrote them:

  | Move | Hand-written, 1a / 1b | Compiled C, 1a / 1b |
  |---|---|---|
  | Constant (`MVI`, `MOV r, #c`) | 0 of 9.4k / 0 of 9.7k | 0 of 22k / 0 of 32k |
  | Register copy | 21 of 103k / 21 of 86k | 0 of 137k / 0 of 123k |
  | 1b `POP` (`MOV r, [sp]+`) | – / 0 of 33k | – |
  | Load | 13.8k of 506k / 13.8k of 263k | 5.7k of 190k / 9.4k of 72k |

  - The 21 are one place in lines: `MOV r8, r3; BEQ`.
  - Every read is `EQ`, `NE`, `MI` or `PL`. Nothing branches on a signed
    condition after a move.
  - The loads whose flags are read are:
    - string loops (`MOV r2, byte [r1]+; BNE`);
    - the console's end-of-input test (`BMI`);
    - lookups that test for an empty table entry or a null link.
- **Four possible rules for a unified `MOV`:**
  - **Never sets the flags** (x86, Z80). Loads need a `TST` wherever their
    flags are read:
    - hand-written code, estimated as one `TST` per read: +2.7% / +3.1%
      (1a / 1b) on D16-overlap and +1.6% / +1.8% on D32-overlap, geometric
      means, up to +13% in strings;
    - compiled C, measured with the compiler keeping its `CMP r, #0` after
      moves and loads: +0.4–0.7% in the programs' own code, up to +7.5% in
      strings. Code grows by 28 bytes across all 15 programs, plus up to 26
      bytes of library.
  - **Sets N and Z when the destination is a register** (draft 1's rule,
    and the 6502's). No measured cost:
    - A constant can't be loaded between a compare and its branch.
    - It can nearly always be loaded before the compare instead. In
      `line`, `MOV r5, #1` can go above the `SUB` that sets the flags. That
      saves the `BRA` that
      [report 0003](0003-report-draft-1-programming-notes.md) put down to
      this rule.
  - **Sets N and Z when the source is memory** (loads only). No measured
    cost. With copies and constants not setting the flags, the compiled C
    doesn't change at all. Hand-written code loses only the 21 reads above.
  - **Always sets N and Z, stores included** (PDP-11, VAX, 68000):
    - **Software:** one idiom has to change. `lib/print.s` pushes a digit
      between the `DIVU` and the branch on its quotient; pushing with
      `SAVE r3-r3` would leave the flags alone. Compiled C never keeps the
      flags live across a store.
    - **1b hardware:** N and Z come from the B bus, and flags can't change
      in a checked memory cycle, or traps would stop being precise. So a
      store can only set them in its last cycle. A plain store's B bus is
      free then, but a push or an `[r]+` store needs it to write back the
      address register.
    - **The cost:** one more cycle for those stores is +0.9% (from report
      0012's cycle counts), up to +2% in vm and sort. A second N/Z source
      instead would be about 5 chips.
- **Or a flag-setting bit** on each move (ARM's S bit), which the program
  writers suggested as the alternative to a fixed rule. Neither encoding
  has a spare bit for it.
- **Whichever rule is chosen:**
  - `RESTORE r-r` already pops without touching the flags, in 1b too.
  - bst's insert walk relies on moves leaving C alone
    (`MOV r3, r4; BCC`). All four rules keep that; a 68000-style move,
    which clears C, would not.
  - Loads could also clear V, as on the PDP-11 and VAX. A signed branch
    after a load would then compare with zero instead of reading a stale
    V. No measured program needs it: it would only save 62 executions of
    a `CMP r, #0` in compiled C. It would remove the same trap as the
    `INC`/`DEC`/`TST` wish in [section 5](#5-more-instruction-ideas), and
    nothing branches on V after a move.
- **The syntax itself:**
  - In 1b it's an assembler and disassembler change only.
  - 1a's loads and stores would take 1b's size keywords, plus one more for
    sign-extending loads (`sbyte`, say).
  - `MOV [x], #c` would be the natural thing to write, and neither
    encoding has it. With `r0 = 0`, `MOV [x], #0` can assemble to
    `ST r0, [x]` ([3.3](#33-r0-as-a-general-register)).
- **The question:** is one rule for loads and stores worth its price?
  - "Never" costs about 2–3% in hand-written string code.
  - "Always" costs about 1% in the 1b hardware.
  - Without one rule, draft 1's rule reads as "a `MOV` into a register sets
    N and Z".

Measured at `b6ffcfd` with scripts that aren't committed.

## 4. What a 1a-based draft 2 would want

For the record, since draft 2 builds on 1b. Some of it is also an
argument for keeping a 1b feature. What 1a would want, from
[report 0004](0004-report-draft-1-evaluation.md#recommendations-for-draft-2)
and the later studies:

- **Post-increment and pre-decrement loads and stores** in op F: byte and
  word `[r]+`, word `-[r]` (pushes), byte `-[r]` (backwards loops), half
  if it fits. Estimated to recover at least 60% of the gap to 1b, and it
  removes the "`ADDI` sets Z" ordering problem from pointer loops. It is
  most of 1b's lead in graphics too
  ([report 0019](0019-report-graphics.md#auto-increment-for-1a)).
- **A jump through a table** (`JMP [table + r*4]`) in a free system
  function. The VM's dispatch is 9 cycles in 1b against 18 in 1a; Egret's
  interpreter dispatches this way on every bytecode
  ([report 0017](0017-report-egret.md#isa-changes-for-the-interpreter)).
- **A memory-indirect call** (`CALL [rs + d]`): the Lisp calls through a
  code word in every object (1.3% over a load and `CALL r`,
  [report 0018](0018-report-lisp.md#for-draft-2)), and an import table
  becomes one instruction ([report 0020](0020-report-operating-system.md#dynamic-linking)).
- **Tagged arithmetic** in op F ([section 6](#6-for-dynamic-languages)).
- **Three-operand add** (`ADD rd, rs, rt`), like 1b's `LEA [rA + rB*s]`,
  if an encoding turns up.
- **From the program writers:**
  - one-parcel `LDH`/`STH`, and one-parcel `AND`/`BIC`/`XOR` immediates;
  - a longer reach for the short byte offsets: 0–15 is too short for a
    34-byte Life row;
  - an `ADDI` that leaves Z alone, or a one-parcel `LEA`, to step a
    pointer between a load and the branch that tests it.
- **The system extensions** of v1bs fit 1a as well: special registers,
  flag bits and two system-group functions
  ([studies/kernel/system.md](../studies/kernel/system.md)).

## 5. More instruction ideas

| Idea | Cost | Notes | Status |
|---|---|---|---|
| Load- and store-multiple through any register, with writeback (68000 `MOVEM`, ARM `LDM`/`STM`) | microcode: `SAVE`/`RESTORE` with the base register from the instruction | Graphics: a copied word 9.2 → 5.1 cycles, a filled one 4.6 → 2.9; emulated through `sp`, clearing an 8-bit screen −29% ([report 0019](0019-report-graphics.md#a-load--and-store-multiple)). Zeroing a page −41%, copying one −37% ([report 0020](0020-report-operating-system.md#zeroing-and-copying)). Also `memcpy` and context switches | **recommended** |
| Interruptible block move/fill/compare (like `REP MOVS`; progress in registers) | microcode | Page copies, screen clears; ~2 bus cycles per halfword against ~14 for a loop. A block fill and copy would reach the bus's limit, about 2× an unrolled loop ([report 0020](0020-report-operating-system.md#zeroing-and-copying)) | **open** |
| Shifts and rotates with a separate destination (`ROR rd, rs, #n`) | microcode | `MOV` was 25–27% of sha256's instructions | **recommended** |
| A funnel shift, `rd = (rd:rs) >> n`, the count in a register or `HI` | microcode, and a barrel shifter ([RFC 0007](0007-rfc-ideas-microarchitecture.md#1-datapath-and-fetch)) | A word of a bit-aligned copy 26.5 → 13.5 cycles ([report 0019](0019-report-graphics.md#a-funnel-shift-or-a-barrel-shifter)). The shift group's free count kind has room for it | **open** |
| Rotate left, or rotates that go the shorter way | microcode | In the timing model `ROR #29` is 7 steps where a rotate left by 3 would be 3, and `ROR #27` 11 cycles on D16-overlap. The draft 1b hardware rotates by any count in 2–5 cycles, so this matters mainly on a narrower datapath | **open** |
| A merge under a mask, `d = (d & ~m) \| (c & m)`, with the mask in `HI` or a fixed register | microcode | Every masked edge and glyph word: 20% off the glyph loop ([report 0019](0019-report-graphics.md#a-merge-under-a-mask)) | **open** |
| Multiply-accumulate into `HI:LO` (`MULA`), fixed-point multiply (multiply, then shift by n) | microcode | Multiply was 50% of mandel; audio, graphics, DSP | **open** |
| Bit-field extract/insert; byte reverse (`REV`) | microcode | Protocols, file formats, graphics; SHA needed big-endian loads | **open** |
| Packed byte arithmetic `ADD.B4` by gating carries at byte boundaries | 1–2 chips | Pixel arithmetic, zero-byte search. Saturation and per-lane flags cost much more | **open** |
| Zero-overhead loops (`LOOP count, end`) | ~10 chips (PC comparator) | DSP style; saves ~5 cycles per iteration in tight loops; modest here | **open** |
| `SKIPcc` (PDP-8 skips, Thumb-2 `IT`) | microcode | Branch-free min/max and conditional moves | **open** |
| Block I/O instruction (Z80 `INIR` style, interruptible) | microcode | ~5–6 cycles per word against ~12–15 for a software loop ([RFC 0009](0009-rfc-ideas-io.md#2-channels-and-dma)) | **open** |
| Atomic exchange / test-and-set | microcode + bus `LOCK` | On one CPU, restartable sequences need no hardware ([report 0020](0020-report-operating-system.md#the-rest)); between CPUs the bus has `LOCK` and semaphore registers ([RFC 0014](0014-rfc-system-bus.md#73-locked-sequences)) | **open** |
| Popcount, find-first-set | microcode | Scheduler and allocator bitmaps; `CLZ` (draft 1) already finds the kernel study's highest ready priority | **open** |
| `DBNZ` (decrement and branch) | a major opcode in 1a; in 1b, op A's free space would hold a one-parcel `DBNZ r, d7` ([3.1](#31-room-left-in-1bs-encoding)) | 2.3% of draft 0's instructions. Rejected on draft 0's evidence; reopened (Emily, 2026-10-15) | **open** |
| Wider branch offsets | encoding | 95% of draft 0's executed branches fit a 6-bit offset and 100% fit 8 bits, and the assembler relaxes the rest. Rejected on draft 0's evidence; reopened (Emily, 2026-10-15) | **open** |
| A link register instead of pushing the return address (`BL`) | a register, or a special register | ~2% of draft 0's cycles. Egret's JIT: 0.7% on average, 2.6% at most (Richards); the calls are long for what they store, not for the call itself ([report 0017](0017-report-egret.md#changes-for-compiled-code)). Rejected; reopened (Emily, 2026-10-15) | **open** |
| 16-bit ALU operations alongside 32-bit (68000 `.W`/`.L`) | doubles the ALU encodings | Rejected for doubling the encodings and baking a 16-bit implementation into the ISA; a narrow implementation is now rejected itself. Reopened (Emily, 2026-10-15) | **open** |
| `V` updated (or defined) by `INC`/`DEC`/`TST` | microcode | Signed branches after them test a stale V ([report 0003](0003-report-draft-1-programming-notes.md)) | **open** |
| System extensions: supervisor mode, register banks, `MFUR`/`MTUR`, XL/XS; a vectored `SWI` | special registers, flag bits, two system functions; the decode ROM | Built and measured as v1bs, except the vectored `SWI`, which is an estimate ([RFC 0010](0010-rfc-ideas-os.md#2-what-the-cpu-gives-the-operating-system)) | **recommended** |

## 6. For dynamic languages

From the Lisp ([report 0018](0018-report-lisp.md)) and Egret
([report 0017](0017-report-egret.md)), both on 1b, interpreted and
compiled on the machine.

| Proposal | Evidence | Status |
|---|---|---|
| Keep misaligned-access traps **precise** (the saved PC is the faulting instruction's, nothing changed) and decodable | Tagged pointers make the Lisp's `car`, `cdr` and calls type-check themselves through the trap; checking in software would cost 16% compiled (up to 35%) and 19% interpreted. Draft 1's restartability rules already give it | **recommended** |
| Tagged arithmetic: `ADD`, `SUB`, `CMP` (and `MOV`) that trap unless both operands are integers, `ADD`/`SUB` trapping on overflow too (SPARC's `TADDccTV`) | The Lisp built it as v1bx, a tagged register operand in 1b's mode E ([isa.md](../studies/lisp/isa.md)): −6.4% of compiled cycles (geometric mean), up to −16% (fib); −5.6% if it costs a cycle more; about one chip. Egret's JIT: −5.5% on average, 16–18% in the numeric programs; its interpreter only 2–3%. The two tag integers differently (the Lisp with bit 0 clear, Egret as 2n + 1); hardware fixes one, and the Lisp's adds directly | **measured**, open |
| Keep a memory-indirect call (`CALL [r + d]`) | The Lisp calls through a code word in every object; a load and `CALL r` would cost 1.3% (up to 2.5%). 1b has it | **measured**, open |
| Guard pages for the stack and heap limits | The Lisp: 5.0% and 1.8% of compiled cycles ([RFC 0010](0010-rfc-ideas-os.md#3-mmu)) | **open** |
| One-parcel `[r - 1]` and `[r + 3]` (the Lisp's pair offsets); the heap limit in a register | 1.1% and 0.9%: not worth the encoding space or a register | **not recommended** |
| Egret's smaller ones: load a value's class, three-operand `XOR`, unaligned 16-bit loads, `CHK` | About 1% or less each, interpreted or compiled. Its link-register call is [in section 5](#5-more-instruction-ideas) | **not recommended** |

What would help these languages more is software: direct threading saves
11% of Egret's interpreter, and its JIT would gain most from keeping the
top of the stack in registers and compiling only what runs often
([report 0017](0017-report-egret.md#what-this-suggests)); the Lisp's
compiler has no register allocation
([report 0018](0018-report-lisp.md#interpreted-and-compiled)).

## 7. Not recommended and rejected

Emily reviewed the rejections on 2026-10-15, and reopened four of them
([section 5](#5-more-instruction-ideas)).

| Proposal | Status | Why not |
|---|---|---|
| Three-operand ALU throughout | **rejected** | `MOV`+op pairs were 1% of draft 0 instructions (12% in queens); doesn't fit 16-bit nibble fields |
| Compare-and-branch | **rejected** | `CMP`;`Bcc` is 5.4% of instructions, but a fused form needs an extension word: 2 parcels either way, ~1 cycle saved |
| A 12-bit `BSR` (±4 KB, SuperH style) in 1a's op B | **rejected** | Saves ~9% of code size and no cycles; op B went to the shift group instead |
| ARM-style conditional execution | **rejected** | No spare bits |
| Decimal (BCD) arithmetic | **rejected** | No use |
| Separate I/O instructions (`IN`/`OUT`) | **not recommended** (Emily, 2026-10-15) | No opcode space; memory-mapped I/O works with every addressing mode |
| Memory-destination ALU operations in general | **not recommended** (Emily, 2026-10-15) | 0.4% of draft 0's instructions, all in fib. A memory increment alone is still recommended ([3.2](#32-1bs-gaps)) |

## 8. Floating point

**open**, and nothing needed yet: the C compiler has no floating point,
and software floating point in its library would come first
([compiler.md](../studies/c_compiler/compiler.md#limitations-and-next-steps)).
These decisions touch the base ISA, so they should be settled before it's
final:

- **Leave a hole:** one escape opcode with a 16-bit *command word* (like the
  68000's "line F" and the 68881, or the 8086's `ESC` and the 8087). It
  traps when no FPU is present.
  - Slow operations don't need compact encodings. The command word gives
    room for FP and later for MMU operations or block moves.
  - Before hardware exists, a trap handler emulates FP in software; same
    binaries throughout.
  - `FFFF` must stay illegal, so erased memory still traps.
  - 1a's op F is free for it. 1b has no whole opcode left, but op B's
    free values ([3.1](#31-room-left-in-1bs-encoding)) could carry a
    command word, with an `ea` for loads and stores.
- **FP registers:** a separate file, e.g. 16 × 64-bit, in the spare
  register-file SRAM. Nearly free in hardware, and doesn't take integer
  registers. The alternative, floats in integer registers (RISC-V's Zfinx),
  is simpler but doubles need register pairs.
- **Compares:** `FCMP` sets N, Z, C, V the ARM way (unordered sets C and V),
  so the existing `Bcc` conditions work and no new branches are needed.
- **Status and vectors to reserve:**
  - an FP-enable bit (for lazy context switching: FP instructions trap
    while it's off);
  - an FP exception vector;
  - a special-register number for FP control/status (rounding, sticky
    flags).
- **Can wait:**
  - instruction list and precision model (registers hold doubles,
    single precision on load/store like the 68881; or per-instruction
    precision);
  - IEEE 754, flushing tiny numbers to zero at first.
- **Implementation:**
  - microcode on the integer datapath (very roughly 30–80 cycles for a
    single-precision add or multiply);
  - or a memory-mapped period FPU: 68882 in peripheral mode, Am9511;
  - or software only.
- **The general "future-proofing kit":**
  - an escape opcode with a command word;
  - every unused function code traps;
  - `0000` = `HALT`, `FFFF` = illegal;
  - reserved bits in the status word (must be written as 0);
  - reserved vectors and special-register numbers.

## 9. The assembler, the library and the compiler

Wishes from the program writers
([report 0003](0003-report-draft-1-programming-notes.md)) and the later
studies that are about the tools, not the ISA. All **open**.

- **Assembler macros and `.rept`** (sha256's rounds). Still missing.
- **`.align` that pads code with `NOP`s,** so hot loops can be aligned:
  wide-fetch cycles depend on loop alignment by up to 15%, and `.align`
  pads with zeros, which are `HALT`
  ([report 0004](0004-report-draft-1-evaluation.md#the-hardware-configurations)).
  **recommended.**
- **Library constants that don't pollute the global namespace**
  (`CONSOLE`, `PR_OUT`): programs couldn't reuse the names.
- **`strcmp` documented as setting the flags from its result:** every call
  was followed by `TST`.
- **Accept `MVI r, 0x80`** when only the low byte matters; today it has to
  be written as −128.
- **The C compiler's next steps** are in
  [compiler.md](../studies/c_compiler/compiler.md#limitations-and-next-steps):
  `long long`, software floating point, linker relaxation,
  shrink-wrapping, and an interrupt-handler attribute. A kernel in C also
  wants intrinsics for `CLZ`, the special registers and `MFUR`/`MTUR`
  ([report 0020](0020-report-operating-system.md#the-rest)).
