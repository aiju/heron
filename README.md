# Heron

Design exploration for a minicomputer to be built from 7400-series logic
chips: instruction sets, CPU implementations with their microcode and
chip-level netlists, simulators and timing analysis, a C compiler, and the
system bus. It started out as `ttl-minicomputer` in a playground
repository, and the history came along.

So far there has been:

- **Draft 0** (superseded): a 16-bit instruction set and a 98-chip
  implementation, evaluated end to end.
- **Draft 1:** a 32-bit machine with 16-bit instruction parcels, in two
  candidate encodings, 1a (load/store) and 1b (register + addressing mode),
  with 20 programs written for both.
- **The draft 1b hardware:** a 213-chip implementation of 1b with a 32-bit
  datapath and pipelined microcode, running every program at 3 MHz in the
  chip-level simulator.
- **A C compiler** for drafts 1a and 1b, with object files and a linker.
- **Graphics on draft 1:** a graphics library for screens of 1 to 8 bits
  per pixel, bitmap and TrueType fonts and the graphics side of a window
  manager, in C and assembly for 1a and 1b.
- **The system bus:** a draft specification, with signal-integrity
  simulations of the backplane on a simulator of our own.
- **An operating system study:** what the hardware should give an
  operating system, measured with a small message-passing kernel on 1b
  with proposed system extensions, and what the operating system could
  be.

Draft 2 is next, built on 1b
([RFC 0006](reports/0006-rfc-ideas-isa.md#2-1a-against-1b-and-the-base-for-draft-2)).
Its encoding is drafted in
[RFC 0028](reports/0028-rfc-draft-2-isa.md), and a study has it in an
assembler and the instruction-level simulator, with the 20 programs
ported ([studies/v2_isa](studies/v2_isa/README.md)). The C compiler
compiles for it too, and Fen, an operating system with a kernel, servers,
a shell and a desktop, runs on its system half
([studies/fen](studies/fen/README.md), [report 0036](reports/0036-report-fen.md)).

## Layout

How the repository is organised, and why: [RFC 0000](reports/0000-rfc-repository-layout.md).

| Folder | What's in it |
|---|---|
| [docs/](docs/README.md) | The current design: what has been decided, as reference |
| [reports/](reports/README.md) | Numbered reports (what was done and found) and RFCs (proposals that need decisions) |
| [studies/](studies/README.md) | Experiments, one folder each: draft 0, draft 1, the 1b hardware, draft 2, the 1b system on the bus, the C compiler, a Lisp, the bus signal integrity, graphics, operating systems, formal verification |
| [infra/](infra/README.md) | Reusable code: assembler and linker core, netlist language, static timing analysis, the chip-level simulator |
| `heron/` | The `heron` command, the glue that makes the folders importable as `heron.*`, and `bindings/`, the crate that makes the Rust engines a Python module (`heron.native`) |
| `tests/` | Tests of the repository itself |

The current design's own `isa/`, `hw/`, `sw/` and `tools/` folders come
with draft 2.

The tools are Python, except the engines (the simulators, the assembler
and the linker), which are Rust: crates in one Cargo workspace, with
`Cargo.toml` at the root ([RFC 0015](reports/0015-rfc-languages.md)).

**Start here:** [RFC 0004](reports/0004-rfc-draft-1-isa.md)
(draft 1a against 1b, and the hardware options), then
[RFC 0005](reports/0005-rfc-ideas-direction.md) (where the ideas stand,
and what the measurements point to), the other
[ideas RFCs](reports/README.md) and [RFC 0014](reports/0014-rfc-system-bus.md)
(the system bus).

## Running things

Needs Python 3.10+ and Rust (stable, from [rustup](https://rustup.rs)). No
other dependencies; the signal-integrity tools also need numpy, and
[ngspice](https://ngspice.sourceforge.io/) only to cross-check their own
engine ([studies/bus_si](studies/bus_si/README.md)).

The Rust engines' Python module is built into `build/` the first time it's
used, and again whenever the Rust sources change; `heron build` builds it
explicitly.

Run `python3 -m heron` from the repository root, or `pip install -e .`
once (in a virtual environment) to get a `heron` command that works from
anywhere. The examples use `heron`.

```sh
heron list                                # the studies, with their status
heron test                                # the repository's own tests
heron test v1_isa c_compiler              # a study's unit tests (--active: every active study's)
heron reports                             # rewrite reports/README.md from the front matter
heron reports reserve rfc slug "Title"    # reserve the next number: push a stub to main
heron build                               # build the Rust engines' Python module
cargo test                                # the Rust crates' tests

heron v1_isa run studies/v1_isa/programs/v1b/life.s --stats   # draft 1b: cycles for six configurations, mix, profile
heron v1_isa --isa v1a test               # every 1a program against its expected output
heron v2_isa test                         # every draft 2 program
heron c_compiler cc studies/c_compiler/programs/life.c --run  # compile C for 1b (--isa v1a, v2) and run it
heron lisp run -c studies/lisp/programs/tak.lisp --stats      # compile Lisp on the 1b simulator and run it
heron v1b_hw hw run studies/v1_isa/programs/v1b/fib.s --period 340   # the 1b hardware at chip level
heron v1b_hw hw sta                       # static timing analysis of the 1b netlist
```

Each study's README lists its commands, and `heron <study> --help` shows
them.
