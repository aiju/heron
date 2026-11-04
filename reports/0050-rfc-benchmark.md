---
number: 50
type: rfc
title: A performance benchmark for Heron
status: open
date: 2026-11-04
context:
  studies: [bench]
  commit: d29c077
depends-on: [28, 31]
---

# RFC 0050: A performance benchmark for Heron

A suite of workloads to time Heron's implementations on, in place of
draft 1's program suite: twelve programs standing for the software Heron
is meant to run, five in hand-written assembly and seven in compiled C,
each reported on its own in absolute time. Part I specifies the suite;
Part II is why it is as it is, what it shows so far, and what is left
for Emily to decide. The study is [studies/bench](../studies/bench/README.md),
and the results are in [results.md](0050-rfc-benchmark/results.md).

Decided (Emily, 2026-11-04): subscores only, no single number; absolute
times, tied to no reference machine; no system-mode workloads; new
programs welcome; a study of its own.

## Contents

- [Part I: Specification](#part-i-specification)
  - [1. The suite](#1-the-suite)
  - [2. The machine a workload runs on](#2-the-machine-a-workload-runs-on)
  - [3. Sizes](#3-sizes)
  - [4. The workloads](#4-the-workloads)
  - [5. What an implementation reports](#5-what-an-implementation-reports)
- [Part II: Discussion](#part-ii-discussion)
  - [6. Why not draft 1's suite](#6-why-not-draft-1s-suite)
  - [7. Where the workloads come from](#7-where-the-workloads-come-from)
  - [8. The choices](#8-the-choices)
  - [9. What it shows so far](#9-what-it-shows-so-far)
  - [10. Open questions](#10-open-questions)
  - [11. Next steps](#11-next-steps)

## Part I: Specification

### 1. The suite

The benchmark is a set of **workloads**. A workload is one program, one
image, that runs from reset to `HALT` and checks its own result. It
belongs to one of two **parts**:

- **hand-written assembly:** code that is assembly in the software it
  stands for: interpreters, an emulator, graphics kernels;
- **compiled C:** applications, as Heron's C compiler compiles them.

Each workload also has a **category**: interpreters, emulation,
graphics, text, tools, apps or games.

The result of running the benchmark on an implementation is each
workload's time, in absolute units (milliseconds), and nothing else:
there is no total, no mean and no score, and no reference machine that
times are divided by.

### 2. The machine a workload runs on

Every workload runs, unchanged, on every implementation of draft 2, so
it uses only what they all have:

- **Draft 2's user instruction set** ([RFC 0028](0028-rfc-draft-2-isa.md)),
  without its tentative instructions (5.10: `ADD.B4`, `FFS`, `POPC`,
  `REV`, `MULA`, `MERGE`, `MULFX`, the tagged operations) and without
  `BCOPY`. No system instructions; no interrupts.
- **RAM from address 0 to `0x100000`**, the first megabyte, holding the
  image (loaded at 0, with draft 1's vectors at 0–`0x1B`), its data, heap
  and stack. The stack pointer starts at `0x100000`.
- **The console** at `0xFFFFFF00` ([RFC 0004's I/O page](0004-rfc-draft-1-isa.md)):
  a workload may read input from it, and writes its results to it at the
  end, under a kilobyte of text.
- **No other I/O.** Results are checksums and counts, so the time is the
  processor's and the memory's.

What is timed is the whole run, from the first instruction after reset
to `HALT`, start-up included.

### 3. Sizes

Each workload has three sizes, the same program with different
parameters:

| Size | Instructions | For |
|---|---|---|
| `test` | up to about 100,000 | chip-level simulation |
| `small` | up to about 1,500,000 | quick runs on the slower models |
| `ref` | 5 to 15 million | the results: data of realistic size |

The `ref` size is the one an implementation's results quote. The
others exist so that slow simulators can check a workload's output at
all.

### 4. The workloads

| Workload | Part | Category | What it stands for |
|---|---|---|---|
| [`m6502`](../studies/bench/workloads/m6502/workload.py) | asm | emulation | Running 8-bit software: a 6502 emulator (every documented opcode, decimal mode, cycle counts) running sorting, CRCs, BCD and string programs |
| [`gfx_desktop`](../studies/bench/workloads/gfx_desktop/workload.py) | asm | graphics | Fen's window system and Mini's window manager: overlapping windows clipped to rectangle lists, text, window moves by unaligned copies, terminal scrolls, a cursor with save-under, on a 640 × 480 × 4 screen |
| [`gfx_sprites`](../studies/bench/workloads/gfx_sprites/workload.py) | asm | graphics | Mini's games: a scrolling tiled playfield, 48 masked sprites at any pixel with save-under, a status line |
| [`forth`](../studies/bench/workloads/forth/workload.py) | asm | interpreters | The Forth RFC 0005 calls likely: direct-threaded, compiling its program from source at start-up, then sieves, recursion, queens, sorting, life and word counting |
| [`lisp`](../studies/bench/workloads/lisp/workload.py) | asm | interpreters | The Lisp of [report 0018](0018-report-lisp.md), its runtime unchanged: the interpreter and collector running symbolic, list, closure and vector code, from a saved image |
| [`db`](../studies/bench/workloads/db/workload.py) | C | apps | Mini's forms application: CSV tables parsed, indexed by hash, joined, sorted on several columns, searched and reported with `sprintf` |
| [`editor`](../studies/bench/workloads/editor/workload.py) | C | apps | Mini's text editor: a gap buffer holding a 40 KB C file, a scripted session with undo, syntax colouring and a redraw after every key |
| [`rts`](../studies/bench/workloads/rts/workload.py) | C | games | Mini's strategy game, headless: 200 units on a 96 × 64 map, flow fields by breadth-first search, steering, combat, the frame's bookkeeping |
| [`ttf`](../studies/bench/workloads/ttf/workload.py) | C | graphics | The graphics library's TrueType text: glyphs rasterised plain and anti-aliased, a glyph cache, kerned paragraphs in a window |
| [`textutils`](../studies/bench/workloads/textutils/workload.py) | C | text | Fen's shell tools in pipelines over in-memory files: grep and sed with regular expressions, sort, uniq, cut, tr, wc |
| [`cc`](../studies/bench/workloads/cc/workload.py) | C | tools | A toolchain on the machine: a compiler for a C subset compiling 2,000 lines to draft 2 assembly, with a peephole optimiser |
| [`inflate`](../studies/bench/workloads/inflate/workload.py) | C | tools | Compressed files: inflate for zlib, gzip and PNG files, and a compressor whose output goes back through it |

Each workload's `workload.py` says what it does and where its time goes.
Every workload's expected output comes from a reference that doesn't
share its code: the same C built with gcc on the host for the compiled
ones, and for the hand-written ones a model in C or Python (the Lisp's
reference interpreter, a 6502 emulator in Python, the graphics drawn a
pixel at a time).

### 5. What an implementation reports

An implementation's results are, for each workload at `ref`:

- its time, in milliseconds, with the clock and cycle lengths it assumes
  stated once for the whole table;
- its instructions and cycles;
- that its output was the expected; a time with the wrong output isn't
  quoted.

The two parts are reported in separate tables. Where an implementation
has instructions beyond the core (Mini's block instructions, `MULFX`),
the times quoted are without them; variants that use them are **open**
([10](#10-open-questions)).

## Part II: Discussion

### 6. Why not draft 1's suite

Every implementation so far has been timed on draft 1's twenty programs,
ported to draft 2, and Full Heron and Mini also on fifteen of them in C
([RFC 0031's performance.md](0031-rfc-draft-2-cpu/performance.md),
RFC 0041, RFC 0047). They were written to compare 1a with 1b, and as a
benchmark they mislead:

- **They are kernels, not programs.** Their hot code fits in a kilobyte:
  RFC 0031's instruction cache gives the same times with 256 words as
  with 4,096. Nothing about fetch, caches or the bus can be learnt from
  them.
- **Their weights are accidents.** The suite's total is a sum of
  milliseconds, so the longest programs decide it: `vm` is 210 of the
  465 ms of hand-written code on Full Heron, and `mandel` another 92.
  Multiply and divide steps are 22% of Full Heron's time, and `MULFX`
  alone, through `mandel`, is 30% of Chibi Heron's. RFC 0049 makes
  `MULFX` an optional extra; the old suite would charge an implementation
  heavily for leaving it out.
- **The assembly and the C are the same programs.** That measures the
  compiler against hand-written code, which reports 0030 and 0034 already
  do, not the machine on what it will run.
- **They don't do what Heron's software does:** few calls and returns, no
  dispatch through tables, no allocation or collection, no text drawing,
  no block moves with masks. Chibi's RFC notes that code with more calls,
  returns and indirect jumps pays more than the suite shows.
- **Several print as they go**, so on a machine with a real UART they time
  the console, and are left out of comparisons.

The old programs stay what they are good at: tests of the ISA's
implementations, and the comparison of compiled with hand-written code.

### 7. Where the workloads come from

From the software the studies have written for Heron, on `main` and on
other branches, and what it spends its time on:

- **Fen** ([report 0036](0036-report-fen.md)): a shell and its utilities,
  a window system, a terminal. `textutils` is its tools; `gfx_desktop`
  its window system's drawing. Its kernel paths are system mode, which is
  left out ([8](#8-the-choices)).
- **The Lisp and Egret** ([reports 0018](0018-report-lisp.md),
  [0017](0017-report-egret.md), [0032](0032-report-lisp-egret-draft-2.md)):
  interpreters whose time goes to dispatch, environment lookups, calls
  through closures and collection. Egret's desktop (report 0021) spends
  30–70% of an interaction in its interpreter loop and up to 41% drawing
  text. `lisp` is the Lisp itself; `forth` is a second interpreter, of a
  different kind (threaded code), which RFC 0005 expects the machine to
  have; `ttf` and `gfx_desktop` are the text.
- **Heron Mini's software** ([report 0043](0043-report-mini-graphics.md),
  on its branch): a window manager, an editor, a forms application, a
  schematic editor, eight games and demos. Their time goes to sprites
  (erase, draw, copy-under), unshifted copies and text. `gfx_sprites`,
  `editor`, `db` and `rts` follow its programs.
- **Guest instruction sets** ([report 0039](0039-report-guest-isas.md)):
  the 6502 in microcode ran 39 times slower than native code. `m6502` is
  the same thing as software.
- **A toolchain and files on the machine** (RFC 0005, RFC 0015): `cc` and
  `inflate`, new programs for what a whole computer does that no study has
  written yet.

Left out, for now: Egret as a workload (its start-up alone, compiling
its prelude in C, is 1.2 million instructions, more than `small`
allows), Curlew (on its branch), and the guest ISAs in microcode (they
are an implementation's feature, not a program).

### 8. The choices

- **No total** (Emily, 2026-11-04). A total, or a mean, weights the
  workloads, and the weights would be as arbitrary as the old suite's.
  Each workload answers its own question: how fast is the window system,
  the compiler, the Lisp.
- **Absolute times** (Emily, 2026-11-04), not speed-ups over a reference
  machine, so that the numbers don't move when the reference does.
- **Different programs in the two parts.** Each part is what that code
  is in practice: an interpreter's loop is assembly, an editor is C.
  Hand-written and compiled versions of the same program measure the
  compiler instead.
- **The core ISA only.** Every implementation can run every workload,
  and an optional instruction's worth is a separate measurement, not
  something the suite assumes. The harness fails a workload that
  executes a tentative instruction.
- **No system mode** (Emily, 2026-11-04). Mini and Chibi have no modes
  or page map, so it couldn't be common to all implementations anyway.
- **The first megabyte:** it is all the RAM draft 2's instruction-level
  simulator has, it is the window Full Heron's suite maps, and it is
  under Chibi's 2 MB.
- **Results only at the end.** Console output while working would time
  the console (the old suite's *prints* problem).
- **Three sizes.** `ref` is sized for realistic data: a compiler
  compiling 2,000 lines, a 40 KB file in the editor, 60 ticks of a game
  with 200 units, a corpus of tens of kilobytes. At about 5,000
  instructions a source line (`cc`) or 150,000 a game tick (`rts`), that
  needs millions of instructions. Full Heron's register-transfer model
  runs some 75,000 cycles a second, so the suite at `ref` takes about 15
  minutes on four cores; the chip-level simulators need `test`. `small`
  is what the workloads were first sized for, and keeps a middle ground.
- **The Lisp starts from a saved image**, as Lisp systems do: reading its
  prelude costs 470,000 instructions before any work, too much for
  `test`. Its unit of work is still big (an interpreted Lisp spends
  thousands of instructions on a few forms), so its `test` is 400,000.
- **Checksums.** Results are `bench_hash` of what a workload made
  (`h = h × 33 ^ byte`, shifts and adds only, so that a machine without a
  fast multiply doesn't pay for checking itself), except where hashing a
  byte at a time would be a large part of the run: the graphics
  workloads sum the screen's words instead. Even so, hashing their output
  is 6–9% of `db`, `editor` and `cc`, and checksumming the screen 7–8%
  of the graphics workloads.

### 9. What it shows so far

On Full Heron, the only implementation whose model is on `main`. The
tables are in [results.md](0050-rfc-benchmark/results.md).

- **Every workload at `ref` takes 1.8 to 2.9 seconds** on Full Heron
  with code and data in the CPU card's RAM, at 183–273 ns an
  instruction. The hand-written ones run 1.7 to 2.8 cycles an
  instruction, the compiled ones 1.8 to 2.5. `gfx_desktop` is the
  slowest per instruction: its unaligned copies shift by a register,
  which takes a cycle a bit.
- **Their code is real-sized.** The code that runs is 1.8–17.5 KB (the
  compiler's 17.5 KB, the compiled programs' 6–9 KB, the interpreters' and
  kernels' 2–4 KB), against 0.4 KB (hand-written) and 0.8 KB (C) for draft
  1's median program.
- **Multiply and divide are rare, but compiled code pays for them.** They
  are at most 2% of any workload's instructions. In the hand-written
  workloads they are 0–2.5% of Full Heron's time, against 22.5% of the
  old suite's; in the compiled ones 10–18% (`db`, `rts`, `ttf`,
  `textutils`, `cc`), each one taking dozens of cycles. Most of those
  are the C library's `qsort`, which multiplies an index by the
  element's size at every step (the biggest in `db` and `textutils`), and
  multiplies by constants that the compiler leaves as `MULS #n` (array
  indexing in `rts`, `cc` and `ttf`); then hashing and decimal
  conversion. A `qsort` that steps pointers and a compiler that turns
  constant multiplies into shifts and adds would take most of it away,
  which matters most on a machine with a slow multiply (Chibi's goes a
  bit a step).
- **Calls, returns and dispatch:** calls and returns are up to 9.5% of a
  workload's instructions (`cc`; `db`, `textutils` and `lisp` 5–7%), and
  jumps through a register 10% of the emulator's and 31% of the Forth's
  (dispatch, and `NEXT`).
- **Code over the bus costs more than the old suite showed, and the
  instruction cache's size now matters.** With every access a bus
  transfer, the workloads take 2.15–2.65 times as long (the old suite
  1.81–2.77, 2.08 in total). With RFC 0031's instruction cache for bus
  space they still take 1.29–1.76 times as long with 4,096 words, and
  with 256 words up to 0.21 more (`cc` 1.61 against 1.40, `lisp` 1.57
  against 1.45); on the old suite the two sizes gave the same time
  for every hand-written program. What the cache can't take away is the
  data: the workloads that move the most data (`gfx_sprites` 1.71,
  `forth` 1.76, its stacks in memory) lose most, which says data should
  stay on the CPU card or have a cache of its own.

### 10. Open questions

1. **Egret and Curlew as workloads.** With `ref` at millions of
   instructions, Egret's start-up fits; its desktop's interactions (a
   keystroke, "print it") would be the most direct measure of what report
   0021 found slow. Curlew is a third kind of interpreter (lazy, compiled
   to a graph-reduction machine).
2. **Variants with optional instructions.** An implementation could also
   report the workloads with what it has beyond the core: Mini's block
   instructions in the graphics workloads, `MULFX` and `MULA`, the tagged
   operations in the Lisp. That needs a second build of the workloads that
   use them, and says what each extra is worth on real programs.
3. **`small`:** worth keeping, or `test` and `ref` only?
4. **A cheaper checksum** in the library (a word at a time) would take
   the results' cost below 2% everywhere.
5. **The other implementations' targets.** Heron Mini's and Chibi Heron's
   models are on their branches; each adds a target to
   [targets.py](../studies/bench/targets.py) when it reaches `main`.

### 11. Next steps

- Times on Heron Mini and Chibi Heron, once their models are on `main`.
- The C library's `qsort` stepping pointers, and the C compiler's
  constant multiplies as shifts and adds ([9](#9-what-it-shows-so-far)):
  changes to the C compiler's study, measured with this suite.
- The open questions above, as Emily decides them.
