---
number: 6
type: rfc
title: Instruction set ideas
status: open
date: 2026-10-15
context:
  studies: [v1_isa, v1b_hw, c_compiler, lisp, egret, graphics, kernel]
  commit: 0987e76
---

# RFC 0006: Instruction set ideas

An ideas RFC: a scratchpad of instruction-set ideas, each with its own
status ([RFC 0000](0000-rfc-repository-layout.md#ideas-rfcs)). The
evidence is in the reports each item links to. Draft 2's encoding is
drafted in [RFC 0028](0028-rfc-draft-2-isa.md); this RFC keeps the ideas
and the evidence it draws on.

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
([RFC 0001](0001-rfc-draft-0.md)); draft 1 has them
([RFC 0004](0004-rfc-draft-1-isa.md)):

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
programs ([RFC 0004](0004-rfc-draft-1-isa.md)).

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
| The 20 hand-written programs | 0.90–0.93 | Auto-increment above all; the VM's table dispatch (−24%) and Life's memory operands (−16%). Register-bound programs are within 3% | [0004](0004-rfc-draft-1-isa.md) |
| The 15 programs in compiled C | 0.94–0.95 | Auto-increment in pointer loops. Memory operands save a cycle each; 4-bit constants cost the compiler more than a person | [0011](0011-report-c-compiler.md) |
| Graphics: assembly kernels / compiled C | 0.95 / 0.97 | Copies (−30% along rows) and anti-aliased text, by auto-increment; the rest is the same | [0019](0019-report-graphics.md) |
| Egret's interpreter | 1b only | Auto-increment is 21–37% of the loop's instructions, `JMP [r + r*4]` 7–14% | [0017](0017-report-egret.md) |
| The Lisp | 1b only | `CALL [r1 + 1]` through a code word, auto-increment for pushes, pops and `cons`; its stack slots are one parcel in both |  [0018](0018-report-lisp.md) |
| Kernel routines | 0.93 unrolled | 1b is 1–3 cycles faster calling through tables, and PC-relative data is free. 1a's one-parcel `[r + 4o]` would suit control-block fields | [0020](0020-report-operating-system.md#the-rest) |

- **Draft 2 builds on 1b.** **decided** (Emily, 2026-10-15). It's where
  most of the work since draft 1 has gone: the 213-chip hardware
  ([report 0012](0012-report-draft-1b-hardware.md)), the Lisp, Egret and
  the kernel study's v1bs. Section 3 collects what a 1b-based draft 2
  would change, and [RFC 0028](0028-rfc-draft-2-isa.md) lays out its
  encoding.
- **Draft 2 on 1a.** RFC 0004 recommended it. That recommendation is
  withdrawn: it rested on faulty numbers (Emily, 2026-10-14). The C
  compiler's first figure, 1b at 0.978 of 1a's cycles, came from a
  register-allocation bug (0.943 once fixed), and 1b's encoding isn't as
  full as the report said ([3.1](#31-room-left-in-1bs-encoding)). Section
  4 keeps what 1a would have wanted, for the record.

## 3. For a draft 2 built on 1b

### 3.1 Room left in 1b's encoding

Every opcode of the `F D M R` format is taken
([RFC 0004, Part II](0004-rfc-draft-1-isa.md#part-ii-draft-1b)). What's left:

- **Op A, `A c k R`:** the long jumps and calls use only k = 0 and 1 with
  R = 0, and everything else traps, so about 4,064 encodings are free:
  nearly a whole opcode. With `c` as a register, k = 8–F and R give each
  register a 7-bit field, enough for one one-parcel instruction with a
  constant up to 127 (`MOV rd, #'a'`, say), with k = 2–7 left over.
  RFC 0004 counted only the modes and special forms when it called
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

Draft 2 doesn't fill these holes: it re-cuts the parcel into an opcode
byte, given out value by value, and a register byte
([RFC 0028](0028-rfc-draft-2-isa.md#2-instruction-format)). This list matters
only for extending 1b itself.

### 3.2 1b's gaps

From [RFC 0004](0004-rfc-draft-1-isa.md), the program
writers' notes ([report 0003](0003-report-draft-1-programming-notes.md))
and the later studies. Where RFC 0028's map closes a gap, the status says
how:

| Gap | What it costs | Status |
|---|---|---|
| Constants are 4 bits in one parcel: characters, masks, 16–255 take an extension parcel | 13% of 1b's operands in the hand-written source are 16-bit constants that 1a mostly fits in one parcel. Executed, 5.6% of compiled 1b operands are 16- or 32-bit constants, against 1.0% in the hand-written code ([report 0011](0011-report-c-compiler.md)). One-parcel 8-bit constants for every instruction have no room in `F D M R`; op A has room for one form with a 7-bit constant ([3.1](#31-room-left-in-1bs-encoding)). Measured at `0987e76` ([3.5](#35-what-1b-code-uses)): beyond the quick constants, `MOV` with 16…127 is 0.31% of executed instructions hand-written and 1.00% compiled, `CMP` 0.68% and 1.74%; 128…255 is at most 0.07%, and nothing loads or compares with −128…−17 | **recommended:** `MVI` and `CMPI rd, #u7`, zero-extended, half a row each in RFC 0028's map, written `MOV` and `CMP` (Emily, 2026-10-15) ([9.2](0028-rfc-draft-2-isa.md#92-alu-operations-and-constants)) |
| No one-parcel `[r + small offset]` | Struct fields: bst's `inorder` and `height` are 3–5% slower than on 1a; a cycle per control-block field in kernel code ([report 0020](0020-report-operating-system.md#the-rest)). Loads and stores at 0–15 elements forward are 0.78% of hand-written and 0.34% of compiled executed instructions ([RFC 0028, 10.1](0028-rfc-draft-2-isa.md#101-short-offsets)). Measured on 1b with a fixed-base mode ([RFC 0028's fixed-base measurements](0028-rfc-draft-2-isa/fixed-base-mode.md)): 3–5% of the nucleus's message and switch paths, about 1% of Egret's cycles, nothing for the Lisp | **decided** (Emily, 2026-10-15): RFC 0028's mode E, `[r14 + 4R]`, for every operation; short offsets through any register aren't proposed |
| No immediate `TST`/`BIC`/`MUL`/`DIV` (op F is register-only) | Constants need registers, and so callee-saved registers across calls | **open.** RFC 0028's map gives `TST`, `BIC`, `MULU` and `MULS` the special mode's 16- and 32-bit constants; a divide by a constant takes a `MOV rX, #c` first |
| No byte or half auto-decrement, no half auto-increment | Backwards loops (`memmove`, `reverse`). Pointer steps that these modes would fold are at most 0.04% of executed instructions, hand-written or compiled ([RFC 0028, 10.2](0028-rfc-draft-2-isa.md#102-more-auto-increment-and-auto-decrement-modes)) | **open;** none proposed for now |
| No sign-extending loads (1a has them) | A signed byte or half takes `SXB` or `SXH` after the load. `SXB` right after a byte load is 0.19% of hand-written executed instructions (vm's bytecode), and compiled C, whose `char` is unsigned, needs none ([RFC 0028, 10.3](0028-rfc-draft-2-isa.md#103-sign-extending-loads)) | **open;** none proposed |
| The indexed mode's displacement is 8 bits | A table's address needs a register of its own ([report 0019](0019-report-graphics.md#smaller-things)). Indexed accesses whose base was loaded with `MOV r, #label` are 1.47% of hand-written executed instructions (vm 16%, mandel 10%) and 0.19% of compiled ones, at `0987e76` | **decided** (Emily, 2026-10-15): RFC 0028's special mode gains `[abs24 + Rx·s]` and `[pc + d24 + Rx·s]` ([3.1](0028-rfc-draft-2-isa.md#31-the-special-mode)) |
| `[label + reg]` reaches only ±32 KB | 1b has no 32-bit displacement form | **decided** (Emily, 2026-10-15): `[abs24 + Rx]` reaches 8 MB, as above |
| `POP` is `MOV r, [sp]+`, which sets N and Z | It can't sit between a test and its branch; `RESTORE r-r` can ([3.4](#34-which-movs-set-the-flags)) | **open.** Gone in RFC 0028's map, where `MOV` never sets the flags |
| No store-immediate | Zero is stored as `ST r0, ea` ([3.3](#33-r0-as-a-general-register)); `CLR ea` in op B would replace it. With `r0` a general register in draft 2, something has to | **recommended:** `CLR ea`, one cell with every mode in RFC 0028's map. It leaves the flags alone, like a store: **decided** (Emily, 2026-10-15) |
| No memory increment (`INC [mem]`, `ADD [mem], r`) | fib's call counter is 30% of its time; a timer interrupt handler is a load, an add and a store. Memory-destination ALU operations in general were 0.4% of draft 0's instructions ([section 7](#7-not-recommended-and-rejected)) | **recommended** ([RFC 0004](0004-rfc-draft-1-isa.md#35-recommendations-for-draft-2)): `INC ea` and `DEC ea`, one cell each in RFC 0028's map. They set N and Z like the register forms: **decided** (Emily, 2026-10-15) |
| `CALL [r]+` and `CALL -[r]` move the register before pushing the return address, so a fault on the push can't be restarted | Found by the kernel study ([report 0020](0020-report-operating-system.md#what-was-hard)). The microcode should push first, or draft 2 drops the form (crc uses it). RFC 0028's `CALL ea` has every mode, these two included | **recommended**; gone in draft 2, whose calls push nothing ([RFC 0028, 5.7](0028-rfc-draft-2-isa.md#57-jumps-and-calls)) |

### 3.3 `r0` as a general register

**decided** (Emily, 2026-10-15): in draft 2, `r0` is a general register
([RFC 0028](0028-rfc-draft-2-isa.md#97-r0-is-a-general-register)). What
follows is the evidence, and what the change still needs.

In draft 1, `r0` reads as zero in both encodings. In 1a it carries its
weight: `[r0 + disp]` is 1a's only absolute address. 1b's encoding already
covers the usual reasons for a zero register: `#0` is a one-parcel constant
(mode 1), absolute addresses have their own modes (F4–F9) and `NEG` is a
unary op. So a 1b-based draft 2 can make `r0` a 15th general register.

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
  - [RFC 0004](0004-rfc-draft-1-isa.md) found no hand-written
    program short of registers either.
- **Replacing it:**
  - `CLR ea` stores zero at any size, in any mode, a register included
    (`CLR rX`). In 1b it would take one of op B's 14 unused values of `k`;
    RFC 0028's map gives it a cell. `MOV [x], #0` can assemble to it.
  - `ADC`/`SBC`, `MTSR` and `MTUR` still need a zero from a register, or
    new forms: `ADC`, `SBC` and the tagged `CMP` with a quick constant,
    say. Which is **open**
    ([RFC 0028, 12](0028-rfc-draft-2-isa.md#12-open-questions)).
  - The hardware's zero becomes a hidden register-file entry.
- **Against, as weighed before the decision:**
  - It's about 1% either way, so performance doesn't decide it.
  - `r0 = 0` is part of the common draft 1 machine, and 1a needs it.
  - The kernel and the Lisp rely on it, so porting them to draft 2 means
    finding each use.
  - It keeps the compiler simple: a zero never needs a register of its own.

### 3.4 Which `MOV`s set the flags

**measured**, open. RFC 0028's map takes "never", with a `MOVS` that sets
N and Z, and writes stores as `MOV`
([RFC 0028](0028-rfc-draft-2-isa.md#91-moves-and-flags)); the last bullet
below has why.

Stores could be written as `MOV` too: `MOV [r2], r1`
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
  - By mode, at `0987e76` with the C library: a load directly followed by
    a branch on N or Z is 5.0% of hand-written executed instructions and
    1.9% of compiled ones. `byte [R]+` is 3.91% and 0.98% of that, `[R]`
    0.75% and 0.31%; five modes cover about 95%
    ([RFC 0028](0028-rfc-draft-2-isa.md#91-moves-and-flags)).
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
    `ST r0, [x]` ([3.3](#33-r0-as-a-general-register)); in draft 2, to
    `CLR [x]`.
- **The question:** is one rule for loads and stores worth its price?
  - "Never" costs about 2–3% in hand-written string code.
  - "Always" costs about 1% in the 1b hardware.
  - Without one rule, draft 1's rule reads as "a `MOV` into a register sets
    N and Z".
- **RFC 0028's answer: "never", plus `MOVS`.** A re-cut encoding has room
  for what neither 1a nor 1b had, a second move that sets N and Z: row 3
  of its map, with every mode but the quick constants. That pays for
  "never" in cells instead of cycles:
  - the string loops and null-link tests keep their one-instruction test;
  - a constant, a register copy or a pop can sit between a compare and its
    branch, which retires 1b's `POP` gap
    ([3.2](#32-1bs-gaps));
  - the rule reads "ALU operations and `MOVS` set the flags; moves
    don't".
  - `MOVS rs`, a register copy that sets N and Z, is in the map too, and
    open ([RFC 0028, 12](0028-rfc-draft-2-isa.md#12-open-questions)). By
    the traces above its flags would hardly ever be read, and
    `CMP r, #0` already tests a register.

Measured at `b6ffcfd` (the loads by mode at `0987e76`) with scripts that
aren't committed.

### 3.5 What 1b code uses

**measured.** What the 1b code executes, counted to lay out draft 2's map
([RFC 0028](0028-rfc-draft-2-isa.md)). On the instruction-level simulator
at `0987e76`: the 20 hand-written 1b programs and the 15 C programs
compiled for 1b, with their C library. Shares are of executed
instructions, as the mean over programs, so each program counts once. The
scripts aren't committed.

- **Operation × mode pairs.** About 90 of 1b's roughly 165 pairs ever
  execute. The 32 most frequent cover 88% of the executed instructions
  that take a mode, 48 cover 96% and 64 cover 99%; those instructions are
  56% of all executed ones. The top of the list: `MOV rs`, `CMP rs`,
  `MOV byte [R]+`, `ST byte [R]`, `ADD rs`, `CMP #q`,
  `ADD byte [R + d16]`, `MOV [R]`.
- **A parcel that carries only opcode bits costs about what a second
  instruction does.** On the 1b hardware `ADD r1, [r2]` is one parcel and
  5 cycles; `MOV r9, [r2]` and `ADD r1, r9` are two parcels and 4 + 2. A
  two-parcel long form of the `ADD` would be two parcels and about 6
  cycles (an estimate). So a pair without a one-parcel form can trap, and
  code uses two instructions ([section 7](#7-not-recommended-and-rejected)).
- **Memory operands on ALU operations** (not moves, `LEA`, jumps or calls)
  are 5.1% of hand-written and 5.6% of compiled executed instructions:
  `ADD` 3.51% and 3.14%, `CMP` 0.71% and 1.92%, `OR`, `SUB` and `XOR`
  0.9% and 0.6% together, `AND` never.
- **The stack-slot mode `[sp + 4R]`** is unused in the hand-written
  programs, as [RFC 0004](0004-rfc-draft-1-isa.md) found. With
  the C library it is up to 17% of a compiled program's executed
  instructions, mostly `printf`'s frame: hello 16.6%, arith 9.6%, strings
  6.3%, bignum 6.0%, and over 2% in 7 of the 15 programs.
- **`LEA`** is 1.85% of hand-written and 3.10% of compiled executed
  instructions; the most is 16% of mandel's, and 8% each of matmul's and
  wordfreq's in C:

  | Mode | Hand-written | Compiled C | What it does |
  |---|---:|---:|---|
  | indexed | 0.95% | 0.81% | A three-operand add: the displacement is almost always 0 and the scale ×1 or ×2 |
  | `[R + d16]` | 0.43% | 1.89% | A pointer plus an offset, into another register and leaving the flags. In C, half have `rd` as the base |
  | `[abs16]` | 0.47% | – | A label's address (140 places): the length of `MOV rd, #label`, which leaves the flags alone too in draft 2 |
  | `[sp + 4R]` | – | 0.24% | A local variable's address |
  | `[R]` | – | 0.16% | The compiler's register copy that leaves the flags alone |

  - `LEA rd, [rA + rB]` takes 6 cycles on the 1b hardware, `MOV` and
    `ADD` 2 + 2: it saves an instruction, not time.
  - `LEA rd, [pc + d16]` never ran, since nothing is position-independent
    yet. It's the only way to get a position-independent address.
- **Unary operations with `rd` ≠ `rs`:**

  | | Hand-written | Compiled C |
  |---|---:|---:|
  | Unary instructions | 6.9% | 8.0% |
  | …with `rd` ≠ `rs` | 0.46% (20 of 162 places) | 3.0% (115 of 256 places) |
  | Mostly | `ZXB` 0.23%, `NEG` 0.20% | `INC` 1.33%, `DEC` 0.66%, `NOT` 0.64% |

  - In compiled C it's mostly `x + 1` into another register. Without the
    separate source each would take a `MOV` more: 3% more instructions in
    compiled C, 0.5% in hand-written code.
  - Working in place, the whole group would take one cell, with the
    function in the register byte. The separate source costs about 11
    cells.
  - `RLC`, `RRC` and `SWAP` never ran.
- **A register copy feeding a shift** (`MOV rd, rs` then `LSL rd, #n`) is
  1.2% of hand-written executed instructions (41 places) and 1.5% of
  compiled ones (39): sha256 10.5%, matmul 3–4%, crc 3%, sort and bst
  about 2%.
- **Decrement-and-branch-back loops** (`DEC r` or `SUB r, #1`, then a
  backward `BNE`) are 3.6% of hand-written executed instructions, about
  1.9% without the interrupts program's delay loop: crc 15%, lines 9%,
  arith 4%. Compiled C has none, because the compiler counts up. Over 99%
  of executions branch at most 16 parcels back, all at most 32; the most
  common distances are 4 parcels and 1.
- **`SAVE` and `RESTORE`.** All 29 compiled functions that save registers
  save `r8`–`rN`, and none saves a register it doesn't use: 7 of the 105
  ranges ever appear. The 1b hardware unrolls a microcode routine per
  range, which takes 1,476 of its 3,507 microinstructions (`SAVE` 406,
  `RESTORE` 1,070), 42% of them
  ([RFC 0007](0007-rfc-ideas-microarchitecture.md#1-datapath-and-fetch)).
- **Short loops.** Executed instructions inside a loop of at most 16
  parcels are 51% of hand-written and 32% of compiled ones (RFC 0007's
  loop buffer).

## 4. What a 1a-based draft 2 would want

For the record, since draft 2 builds on 1b. Some of it is also an
argument for keeping a 1b feature. What 1a would want, from
[RFC 0004](0004-rfc-draft-1-isa.md#35-recommendations-for-draft-2)
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
  ([report 0020's appendix](0020-report-operating-system.md#appendix-v1bs-draft-1b-with-system-extensions)).

## 5. More instruction ideas

| Idea | Cost | Notes | Status |
|---|---|---|---|
| Load- and store-multiple through any register, with writeback (68000 `MOVEM`, ARM `LDM`/`STM`) | microcode: `SAVE`/`RESTORE` with the base register from the instruction, best as one loop for all four ([RFC 0007](0007-rfc-ideas-microarchitecture.md#1-datapath-and-fetch)) | Graphics: a copied word 9.2 → 5.1 cycles, a filled one 4.6 → 2.9; emulated through `sp`, clearing an 8-bit screen −29% ([report 0019](0019-report-graphics.md#a-load--and-store-multiple)). Zeroing a page −41%, copying one −37% ([report 0020](0020-report-operating-system.md#zeroing-and-copying)). Also `memcpy` and context switches. A register range does as well as a mask: compiled code only ever saves `r8`–`rN` ([3.5](#35-what-1b-code-uses)); with a link register, a range plus a bit for it. RFC 0028's map has `LDM rb, ra-rc` and `STM` in a cell each, `rc` in an extension parcel | **recommended** |
| Interruptible block move/fill/compare (like `REP MOVS`; progress in registers) | microcode | Page copies, screen clears; ~2 bus cycles per halfword against ~14 for a loop. A block fill and copy would reach the bus's limit, about 2× an unrolled loop ([report 0020](0020-report-operating-system.md#zeroing-and-copying)) | **open** |
| Shifts and rotates with a separate destination (`ROR rd, rs, #n`) | microcode; one-parcel forms would take 32 cells of draft 2's map per kind | `MOV` was 25–27% of sha256's instructions, but that's mostly sha256 alone: a register copy feeding a shift is 1.2% of hand-written and 1.5% of compiled executed instructions ([3.5](#35-what-1b-code-uses)). A two-parcel form saves only about a cycle over `MOV` and a shift. A rotate for hashing, or `REV` for big-endian loads, would buy sha256 back more cheaply | **not recommended** |
| A funnel shift, `rd = (rd:rs) >> n`, the count in a register or `HI` | microcode, and a barrel shifter ([RFC 0007](0007-rfc-ideas-microarchitecture.md#1-datapath-and-fetch)) | A word of a bit-aligned copy 26.5 → 13.5 cycles ([report 0019](0019-report-graphics.md#a-funnel-shift-or-a-barrel-shifter)). The shift group's free count kind has room for it | **open** |
| Rotate left, or rotates that go the shorter way | microcode | In the timing model `ROR #29` is 7 steps where a rotate left by 3 would be 3, and `ROR #27` 11 cycles on D16-overlap. The draft 1b hardware rotates by any count in 2–5 cycles, so this matters mainly on a narrower datapath | **open** |
| A merge under a mask, `d = (d & ~m) \| (c & m)`, with the mask in `HI` or a fixed register | microcode | Every masked edge and glyph word: 20% off the glyph loop ([report 0019](0019-report-graphics.md#a-merge-under-a-mask)). RFC 0028 defines `MERGE` tentatively | **open** |
| Multiply-accumulate into `HI:LO` (`MULA`), fixed-point multiply (multiply, then shift by n) | microcode | Multiply was 50% of mandel; audio, graphics, DSP. RFC 0028 defines `MULA` and `MULFX` tentatively, to be simulated and measured | **open** |
| Bit-field extract/insert; byte reverse (`REV`) | microcode | Protocols, file formats, graphics; SHA needed big-endian loads. RFC 0028 defines `REV` tentatively | **open** |
| Packed byte arithmetic `ADD.B4` by gating carries at byte boundaries | 1–2 chips | Pixel arithmetic, zero-byte search. Saturation and per-lane flags cost much more. RFC 0028 defines `ADD.B4` tentatively | **open** |
| Zero-overhead loops (`LOOP count, end`) | ~10 chips (PC comparator) | DSP style; saves ~5 cycles per iteration in tight loops; modest here. A loop buffer with `DBNZ` gets most of it without a new instruction ([RFC 0007](0007-rfc-ideas-microarchitecture.md#1-datapath-and-fetch)) | **open** |
| `SKIPcc` (PDP-8 skips, Thumb-2 `IT`) | microcode | Branch-free min/max and conditional moves | **open** |
| Block I/O instruction (Z80 `INIR` style, interruptible) | microcode | ~5–6 cycles per word against ~12–15 for a software loop ([RFC 0009](0009-rfc-ideas-io.md#2-channels-and-dma)) | **open** |
| Atomic exchange / test-and-set | microcode + bus `LOCK` | On one CPU, restartable sequences need no hardware ([report 0020](0020-report-operating-system.md#the-rest)); between CPUs the bus has `LOCK` and semaphore registers ([RFC 0014](0014-rfc-system-bus.md#73-locked-sequences)). So an instruction is for data shared between bus masters in memory, and C11 atomics, which want compare-and-swap: it builds any lock-free structure, and a word on a 16-bit card is two reads and two writes, inside `LOCK`'s 4 transfers. `CAS rs, [R]` with the expected value in `r1` (x86's `CMPXCHG`) fits one cell. `XCHG` is optional; `TAS` isn't needed beside the semaphores. RFC 0028 marks out a cell ([12](0028-rfc-draft-2-isa.md#12-open-questions)) | **open** |
| Popcount, find-first-set | microcode | Scheduler and allocator bitmaps; `CLZ` (draft 1) already finds the kernel study's highest ready priority. RFC 0028 defines `POPC` and `FFS` tentatively | **open** |
| `DBNZ` (decrement and branch) | a major opcode in 1a; in 1b, op A's free space would hold a one-parcel `DBNZ r, d7` ([3.1](#31-room-left-in-1bs-encoding)); in draft 2's map, one cell: the register and a 4-bit backward offset, 1–16 parcels | 2.3% of draft 0's instructions. Rejected on draft 0's evidence; reopened (Emily, 2026-10-15). In 1b code it would replace 3.6% of hand-written executed instructions and none of compiled C's, which counts up; over 99% branch at most 16 parcels back ([3.5](#35-what-1b-code-uses)). It saves a parcel per iteration and probably a cycle. It should leave the flags alone, so an `ADC` chain's carry survives the counter. A loop buffer would make it worth more ([RFC 0007](0007-rfc-ideas-microarchitecture.md#1-datapath-and-fetch)) | **recommended:** `DBNZ r, back4` |
| Wider branch offsets | encoding | 95% of draft 0's executed branches fit a 6-bit offset and 100% fit 8 bits, and the assembler relaxes the rest. Rejected on draft 0's evidence; reopened (Emily, 2026-10-15) | **open** |
| A link register instead of pushing the return address (`BL`) | a register, or a special register | ~2% of draft 0's cycles. Egret's JIT: 0.7% on average, 2.6% at most (Richards); the calls are long for what they store, not for the call itself ([report 0017](0017-report-egret.md#changes-for-compiled-code)). Rejected; reopened (Emily, 2026-10-15). Measured on 1b with `r7` as the link register (the link-register report, in review): −2.3% of the hand-written suite's cycles, −0.2% of compiled C's, −0.9% of Egret's JIT, at worst +0.24%; 74 fewer microinstructions | **decided** (Emily, 2026-10-15): `r7`, in RFC 0028 ([5.7](0028-rfc-draft-2-isa.md#57-jumps-and-calls)) |
| 16-bit ALU operations alongside 32-bit (68000 `.W`/`.L`) | doubles the ALU encodings | Rejected for doubling the encodings and baking a 16-bit implementation into the ISA; a narrow implementation is now rejected itself. Reopened (Emily, 2026-10-15) | **open** |
| `V` updated (or defined) by `INC`/`DEC`/`TST` | microcode | Signed branches after them test a stale V ([report 0003](0003-report-draft-1-programming-notes.md)) | **open** |
| System extensions: supervisor mode, register banks, `MFUR`/`MTUR`, XL/XS; a vectored `SWI` | special registers, flag bits, two system functions; the decode ROM | Built and measured as v1bs, except the vectored `SWI`, which is an estimate ([RFC 0010](0010-rfc-ideas-os.md#2-what-the-cpu-gives-the-operating-system)). In RFC 0028's map `SWI #n` is one cell and the decode ROM sees `n`, so each can have its own microcode entry. [RFC 0029](0029-rfc-draft-2-system.md) specifies them for draft 2, without XL/XS | **recommended** |
| One-operand instructions with every mode in one cell (the 68000's single-operand group, 1b's op B) | the decode ROM | The mode and its register are 8 bits, the register byte of draft 2's parcel. RFC 0028's map uses it for `CLR`, `INC` and `DEC`, `JMP` and `CALL`. A mode an instruction can't use traps (`CLR #q`) | **recommended** |

## 6. For dynamic languages

From the Lisp ([report 0018](0018-report-lisp.md)) and Egret
([report 0017](0017-report-egret.md)), both on 1b, interpreted and
compiled on the machine.

| Proposal | Evidence | Status |
|---|---|---|
| Keep misaligned-access traps **precise** (the saved PC is the faulting instruction's, nothing changed) and decodable | Tagged pointers make the Lisp's `car`, `cdr` and calls type-check themselves through the trap; checking in software would cost 16% compiled (up to 35%) and 19% interpreted. Draft 1's restartability rules already give it | **recommended** |
| Tagged arithmetic: `ADD`, `SUB`, `CMP` (and `MOV`) that trap unless both operands are integers, `ADD`/`SUB` trapping on overflow too (SPARC's `TADDccTV`) | The Lisp built it as v1bx, a tagged register operand in 1b's mode E ([report 0018's appendix](0018-report-lisp.md#appendix-v1bx-draft-1b-with-a-tagged-register-mode)): −6.4% of compiled cycles (geometric mean), up to −16% (fib); −5.6% if it costs a cycle more; about one chip. Egret's JIT: −5.5% on average, 16–18% in the numeric programs; its interpreter only 2–3%. The two tag integers differently (the Lisp with bit 0 clear, Egret as 2n + 1); hardware fixes one, and the Lisp's adds directly. A register holding the expected tag bit would let the check serve both for a couple of gates, though Egret's adds would still need a correction. Not only for the Lisp: Smalltalk, Scheme, ML and Erlang keep small integers the same way; C, the kernel and assembly gain nothing. RFC 0028's map has `TMOV`, `TTST`, `TADD`, `TSUB` and `TCMP` on registers, in its column E ([9.2](0028-rfc-draft-2-isa.md#92-alu-operations-and-constants)) | **measured**, open |
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
| Every operation with every mode as a two-parcel long form, beside one-parcel short forms | **not recommended** | A parcel carrying only opcode bits costs what a second instruction does: a long `ADD r1, [r2]` would be 2 parcels and about 6 cycles, like `MOV` and `ADD` ([3.5](#35-what-1b-code-uses)). It saves only a scratch register, and no program was short of registers. Pairs without a short form can trap. Two-parcel instructions are for what can't be split: atomics, register lists, command words |

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
  - RFC 0028's map marks out a cell for it. With a command word and the
    32-bit forms of an `ea` it would be four parcels, one over draft 1's
    limit ([RFC 0028, 12](0028-rfc-draft-2-isa.md#12-open-questions)).
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
  - `0000` = `HALT`, `FFFF` = illegal (RFC 0028's map makes both
    illegal, so a jump into zeroed memory traps too);
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
  ([RFC 0004](0004-rfc-draft-1-isa.md#33-the-hardware-configurations)).
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
- **The C compiler for draft 2,** as RFC 0028's map stands: `MOV` for the
  register copy it now writes as `LEA rd, [R]`; `MOVS` where it relies on
  a load's flags; `CLR` for zero stores and a fresh zero where it reads
  `r0`; loops whose index is only a counter counted down, for `DBNZ`.
