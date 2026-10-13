---
number: 15
type: rfc
title: Languages for the tools, Rust engines with Python bindings
status: accepted
date: 2026-10-13
context:
  studies: [v1_isa, v1b_hw, v0_hw, c_compiler]
  commit: c6dbe1b
---

# RFC 0015: Languages for the tools, Rust engines with Python bindings

## Summary

| What | Language |
|---|---|
| **Engines:** the instruction-level simulator, the assembler and linker, the chip-level simulator, later perhaps static timing analysis | Rust |
| **Descriptions:** the netlist language, chip library, microcode generators; reports, analysis and glue; the `heron` command | Python |
| **Studies** | Python, using the engines through Python bindings |
| **Software for the machine** | C and assembly |

The Go chip-level simulator (`infra/hwsim/`) is rewritten in Rust, so the
repository has two languages, not three. Nothing is rewritten just to
change language: frozen studies stay as they are, and active ones move to
the Rust engines when it helps them.

## Motivation

Today the tools are about 24,000 lines of Python and 2,400 of Go.

- **Instruction-level simulation is slow.**
  - The Python simulator runs about 600,000 instructions a second: draft
    1b's `vm` program runs 597,389 instructions in 1.1 s, assembly
    included.
  - That's fine for the 20 test programs. But booting a small operating
    system in simulation takes hundreds of millions of instructions, which
    is minutes per run in Python.
  - Going from a monitor to an OS is where the project is heading
    ([RFC 0005](0005-rfc-ideas-direction.md#1-direction-and-ambition)).
    A compiled simulator should run 100 times faster or more.
- **Chip-level simulation is slow too.** The Go event-driven simulator runs
  draft 0's `fib` at 23,700 cycles a second (4.8 million events a second)
  and draft 1b's at 14,200 (3.7 million). One second of draft 1b at 3 MHz
  takes about 3½ minutes. The simulator's algorithm matters more than its
  language here, but a rewrite is the moment to work on both.
- **The engines are long-lived and regular.** An assembler, a decoder or a
  simulator is mostly "match on one of N instruction shapes". Rust's enums
  and exhaustive `match` turn a forgotten case into a compile error.
- **Most of the code is written by agents.** Rust's type checker catches a
  class of mistakes before anything runs. The untyped Python has nothing
  like it: during the restructure, only the tests kept the moves safe.
- **Two languages, not three.** Adding Rust next to Go would leave three;
  replacing Go keeps two.

Python stays where it is better.

- **Describing hardware.** The netlist language and the microcode
  generators are tables and ad-hoc structure, which Python says compactly.
  In Rust they would be builder boilerplate or macros.
- **Experiments.** Studies change shape constantly, and Python iterates
  much faster: no compile step, no borrow checker fighting a half-formed
  idea.
- **Reports and glue.**

## Python bindings

The Rust engines are usable from Python, so a study can drive them like
any Python module: load a program, run it, read registers and memory and
the cycle count, and step or trace.

- **How:** [PyO3](https://pyo3.rs/), compiled into one extension module
  that the `heron` package imports. Each engine stays a plain Rust crate
  with its own Rust API and tests; the bindings are a thin layer over it.
- **No install step:** the extension is built on demand into `build/`,
  the way `infra/hw/runner.py` builds the Go simulator today.
  - The first import that needs an engine runs `cargo build` if the Rust
    sources are newer than the built module.
  - `heron build` does it explicitly.
  - `python3 -m heron ...` from a plain checkout keeps working; it needs
    `cargo` on the PATH, as it needs `go` today.
- **The chip-level simulator in-process:** studies call it directly instead
  of writing a JSON configuration and running a separate binary.
  - The netlist stays a Python description, exported as data.
  - Python stays where netlists are written, Rust where they are run.

## Replacing the Go simulator

`infra/hwsim/` (`sim.go`, `models.go`, `main.go`) becomes a Rust crate.

1. **Port it with the same netlist and configuration format,** so the
   machine modules in `v0_hw` and `v1b_hw` don't change.
2. **Cross-check it against the Go simulator on both machines:** every
   program's cycles, registers, RAM, fetches, timing violations and
   contention must match, the same way the chip-level runs are checked
   today.
3. **Delete the Go code,** and drop Go from the requirements.
4. **Move to the bindings:** `infra/hw/runner.py` calls the simulator
   through them instead of a subprocess, and the Go tests become Rust
   tests.

The draft 0 study is frozen and may keep the subprocess path at its
`frozen-at` commit; it isn't ported on purpose.

## ISA definitions

An ISA's definition lives in Rust: its encoder, decoder and semantics are
one implementation. Python reads it through the bindings: the microcode
and decode-ROM generators, and the studies. A separate data file
describing the ISA isn't needed; draft 1b's addressing modes and
extension parcels are too irregular to describe as tables.

## The assembler and linker

The assembler core, the object format and the linker move to Rust too,
together with the draft 1a and 1b encoders. The studies use them through
the bindings:
- `v1_isa`'s command line;
- the C compiler, which assembles its output and links it with the C
  library.

The object format stays the same, so object files, executables and
libraries written before the move still load. The Python versions in
`infra/` go once the studies' tests pass on the Rust ones. The frozen
draft 0 study keeps the Python assembler at its `frozen-at` commit.

## Where the Rust code lives

- **One Cargo workspace,** with `Cargo.toml` at the repository root.
- **Reusable engines are crates in `infra/`,** next to the Python they
  replace or serve. Examples: the chip-level simulator, the object format
  and linker.
- **The current design's engines go in `isa/` and `tools/`.** Draft 2's
  ISA, its simulator and its assembler live there.
- **The bindings crate** builds the one extension module.

## What doesn't change

- The studies' Python code, except where it calls the engines.
- `infra/`'s netlist language and static timing analysis, which stay
  Python.
- The C compiler. It's a study, and compile speed isn't its problem.
- The machine's own software: C and assembly.
- **Tools that run on the machine itself** are out of scope. Rust can't
  target a 32-bit TTL machine with 1 MB of RAM, so a native toolchain
  would be C, or a small existing C compiler ported to it.
- **What the hardware is described in for boards** is a separate
  question: the Python netlist language with a KiCad export, an HDL, or
  KiCad schematics.

## Order of work

1. **The toolchain:** the Cargo workspace, the bindings crate, the build
   on demand, `heron build`, Rust in CI and in the cloud environment.
2. **The chip-level simulator in Rust,** checked against Go, then Go
   removed.
3. **Draft 1's instruction-level simulator and timing model in Rust.**
   They are checked against the Python ones on every program: output,
   registers, memory, and the cycle counts for all six configurations. The
   `v1_isa` and `c_compiler` studies, and the `v1b_hw` study's reference
   runs, then switch to them. Software work (a monitor, an OS, the
   compiler's output) gets fast simulation before draft 2 exists, and
   draft 2's simulator starts from it.
4. **The assembler and linker in Rust,** with the 1a and 1b encoders,
   checked against the Python assembler: identical images and object
   files for every program and library.
5. **Draft 2's engines** as draft 2 is built.

## Decisions

Emily has decided, in the discussion of this RFC:

- Rust for the engines, Python for descriptions, generators, reports and
  studies;
- the Go simulator is replaced by Rust;
- the Rust engines get Python bindings, so studies can use them from
  Python;
- an ISA's definition lives in Rust, and Python reads it through the
  bindings;
- the first instruction-level engine is a port of draft 1's simulator;
- the studies' assembler and linker move to Rust too.
