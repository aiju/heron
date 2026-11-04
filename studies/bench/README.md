---
status: active
depends-on: [v2_isa, c_compiler, v2_hw, lisp, graphics]
reports: []
---

# A performance benchmark for Heron

A suite of workloads to time Heron's implementations on: whole programs
standing for the software Heron runs (an operating system's tools,
interpreters, graphics, games, compilers), not the kernels of draft 1's
program suite. It has two parts, timed and reported apart:

- **hand-written assembly:** the code that is assembly in the real
  software: interpreters' inner loops, graphics kernels, emulators;
- **compiled C:** applications, as the C compiler compiles them.

Each workload is reported on its own, in absolute time on each
implementation; there is no total and no reference machine.

```sh
heron bench list                    # the workloads
heron bench test [NAME...]          # every workload, both sizes, against its expected output
heron bench run NAME --stats        # one on the instruction-level simulator: output, mix (--profile: by routine)
heron bench stats                   # size, instruction mix and cycles of every workload
heron bench time [--size test]      # absolute times on Full Heron's model (v2_hw), cached in build/bench/
heron bench expected [NAME...]      # write the expected outputs from the host references
heron bench report [--write]        # the results page
heron test bench                    # the study's unit tests
```

| File | What's in it |
|---|---|
| `suite.py` | Finding the workloads, building them at a size, the host references, running them on the instruction-level simulator |
| `targets.py` | The implementations they're timed on (`v2_hw` so far) |
| `report.py` | The results page |
| `lib/` | What every workload links with: the start code, and the same small library in assembly (`util.s`) and C (`bench.c`, `bench.h`) |
| `workloads/` | The workloads, a folder each |

## The machine a workload runs on

Every workload is one image that runs on every implementation, so it uses
only what they all have
(Full Heron, [Heron Mini](../../reports/0041-rfc-heron-mini.md),
[Chibi Heron](../../reports/0047-rfc-chibi-heron.md)):

- **Draft 2's user instruction set**, without the tentative instructions
  of RFC 0028's 5.10 (`ADD.B4`, `FFS`, `POPC`, `REV`, `MULA`, `MERGE`,
  `MULFX` and the tagged operations) or `BCOPY`: they are extras an
  implementation may leave out, and `heron bench test` fails a workload
  that runs one. No system instructions, no interrupts.
- **The first megabyte of RAM** from address 0: the image at 0 with draft
  1's vectors, the stack down from `0x100000`. Image, data, heap and
  stack fit in it.
- **The console** at `0xFFFFFF00`, draft 1's I/O page. A workload reads
  input from it if it must, and writes its results to it **at the end**:
  a few lines of checksums and counts, under a kilobyte. Nothing else
  touches I/O, so the time is the processor's and the memory's.
- **From reset to `HALT`** is what is timed: start-up is part of the
  workload.

## What makes a workload

- **It stands for real software.** Its docstring (workload.py) says which,
  and why its time goes where it does. Where Heron's software already
  does the thing (the Lisp, Fen, the graphics library), the workload is
  that code or follows it.
- **It's a program, not a loop:** code of several kilobytes to tens of
  kilobytes, data of tens to hundreds of kilobytes, so that fetch, caches
  and the memory system are exercised as real programs exercise them.
- **Two sizes,** the same program with different parameters:
  - `test`: 20,000 to 100,000 instructions, for the chip-level
    simulators;
  - `ref`: 300,000 to 1,500,000 instructions, the size the results quote.
- **It checks itself:** its output is compared with an expected output
  that comes from an independent reference on the host (the same C built
  with gcc, or a model in C or Python), committed in `expected/`.

### workload.py

```python
"""What it is, what real software it stands for, where its time goes."""

TITLE = "a Forth, compiling and running its programs"   # one line, for tables
PART = "asm"                      # "asm" (hand-written) or "c" (compiled)
CATEGORY = "interpreters"         # interpreters, emulation, graphics, text,
                                  # tools, apps, games
SOURCES = ["forth.s", "words.s"]  # in the folder: .s files, or .c files
SIZES = {"test": {"N": 2}, "ref": {"N": 20}}   # the parameters of each size

def data(p):                      # optional: input data, linked in
    return {"corpus": b"..."}
def input(p):                     # optional: console input
    return b""
def reference(p):                 # optional: the expected output, from Python
    return b"..."
REFERENCE_C = ["ref.c"]           # ... or from C built with gcc on the host
MAX_CYCLES = 100_000_000          # optional
def build(p):                     # optional: make (image, input) some other way
    ...
```

- **Parameters** reach the code as `NAME = value` in front of every
  assembly source, and as `-DNAME=value` for every C file.
- **Data** from `data(p)` is linked in under its name, far (anywhere in
  the image), with its length in a near word: in assembly `corpus` and
  `corpus_len`; in C, declared by the workload,

  ```c
  extern const unsigned char corpus[];
  extern unsigned corpus_len;
  ```
- **Hand-written workloads** define a global `main`, called with the
  stack set up; returning from it halts. They're linked with
  `lib/start.s` and `lib/util.s`, and call `util.s`'s routines (`bench_report`,
  `bench_hash`, ...) in the C calling convention: arguments in `r1`–`r4`,
  the result in `r1`, `r0`–`r7` caller-saved, the return address in `r7`
  ([the C compiler's convention](../c_compiler/compiler.md#calling-convention)).
  Their reference is `reference()` or `REFERENCE_C`.
- **Compiled workloads** are C as the C compiler takes it
  ([compiler.md](../c_compiler/compiler.md)): C89 without `float`,
  `double`, `long long` or bit fields, with its small C library
  (`printf` and `sprintf`, `string.h`, `malloc`, `qsort`, `ctype.h`), and
  `lib/bench.h`. Their reference is the same sources built with gcc
  (`-funsigned-char`, as Heron's `char` is unsigned), so the C must mean
  the same on both: no `long` (64 bits on the host), no pointers kept in
  integers, its own random numbers rather than `rand()`, and `qsort` only
  with comparators that never return 0 for different elements (the two
  libraries' sorts order ties differently).
- **The results** are `bench_report("label", value)` lines: checksums of
  what the workload made (`bench_hash`, the same in C and assembly) and
  counts.

To add one: make the folder, write the workload, `heron bench expected
NAME`, then `heron bench test NAME` and `heron bench time NAME --size
test`.
