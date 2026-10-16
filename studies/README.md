# Studies

Experiments: a design, a measurement, a tool. Each study is a folder, and
mostly self-contained ([RFC 0000](../reports/0000-rfc-repository-layout.md#studies)).

Each study's README starts with front matter: its status, the studies it
depends on, and the reports about it.

- **Active:** its tests run in the slow CI, and breakage while someone is
  working on it is accepted.
- **Frozen:** nothing runs it any more. Check out its `frozen-at` commit to
  reproduce its results.

`heron list` shows them all. `heron <study> --help` shows a study's
commands, and `heron test <study>` runs its unit tests.

| Study | What it is |
|---|---|
| [v0_hw](v0_hw/README.md) | Draft 0: a 16-bit ISA and its 98-chip implementation (frozen) |
| [v1_isa](v1_isa/README.md) | Draft 1: a 32-bit ISA in two encodings, 1a and 1b, and the program suite |
| [v2_isa](v2_isa/README.md) | Draft 2, RFC 0028's instruction set: assembler, simulator and the program suite ported to it |
| [v1b_hw](v1b_hw/README.md) | A 213-chip implementation of draft 1b |
| [v1b_system](v1b_system/README.md) | Draft 1b on the RFC 0014 bus: the backplane, the CPU card with variable-length cycles, a memory card and an I/O card, at chip level |
| [v1b_tradeoffs](v1b_tradeoffs/README.md) | Faster and smaller: where the 1b system's time and chips go, faster parts and a clock generator for them at chip level, cycle floors and other microarchitectures |
| [pcb](pcb/README.md) | The cards as printed circuit boards: placed and routed by code, written as KiCad boards, checked against the simulated netlist |
| [c_compiler](c_compiler/README.md) | A C compiler for drafts 1a, 1b and 2 |
| [lisp](lisp/README.md) | A Lisp for drafts 1b and 2: interpreter, compiler and collector on the machine, and what it wants from the ISA |
| [bus_si](bus_si/README.md) | Signal integrity of the system bus backplane: loading, ground bounce, crosstalk, the clock tree, the strobes |
| [egret](egret/README.md) | Egret, a small object language, interpreted and compiled on drafts 1b and 2 |
| [graphics](graphics/README.md) | Graphics on draft 1: a library, bitmap and TrueType fonts, and a window manager, in C and assembly for 1a and 1b |
| [kernel](kernel/README.md) | An operating system for Heron: system extensions to 1b, a benchmark nucleus that measures an OS's hot paths, and page statistics for the MMU |
