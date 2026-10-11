# ttl-minicomputer

Design exploration for a 16-bit minicomputer to be built from 7400-series
logic chips. This stage evaluates a draft instruction set: an assembler and
simulator for it, a suite of real programs, notes on what writing them was
like, a chip-level implementation with an event-driven timing simulator, and
performance numbers.

| Document | What's in it |
|---|---|
| [docs/evaluation.md](docs/evaluation.md) | **Start here**: the ISA evaluation and recommendations for the next draft |
| [docs/isa-v0.md](docs/isa-v0.md) | ISA draft 0: encoding, instructions, conventions, assembler syntax |
| [docs/programming-notes.md](docs/programming-notes.md) | What writing the programs was like, program by program |
| [docs/hardware.md](docs/hardware.md) | The 98-chip implementation: datapath, microcode, timing, known issues |
| [docs/performance.md](docs/performance.md) | Generated: clock speed, cycles and run time per program, instruction mix |

## Running things

Needs Python 3.10+ and Go 1.21+ (for the chip-level simulator). No other
dependencies.

```sh
python3 -m tmc run programs/mandel.s --stats    # assemble and run, with an instruction mix
python3 -m tmc run programs/rpn.s --input '3 4 + 2 *\n'
python3 -m tmc asm programs/sieve.s -l sieve.lst # assemble with a listing
python3 -m tmc test                              # run all programs against expected output
python3 -m unittest discover tests               # assembler/ISA unit tests

python3 -m tmc ucode                             # write the microcode ROM images to build/ucode
python3 -m tmc hw bom                            # parts list
python3 -m tmc hw sta                            # static timing analysis
python3 -m tmc hw run programs/fib.s --period 500   # run on the chip-level simulator at 2 MHz
python3 -m tmc hw sweep tests/hw/exercise.s      # find the fastest clock that still works
python3 -m tmc report --hw                       # regenerate docs/performance.md (a few minutes)
(cd hwsim && go test ./...)                      # 74181/74182 model tests
```

`--variant` picks the parts (`hct-ls181`, `hct-f181`, `act-f181`) and
`--corner` the delays (`max` worst case, `typ` typical) for the `hw` commands.

## Layout

```
tmc/asm.py          assembler core: expressions, labels, directives, size relaxation (ISA-independent)
tmc/isa/v0.py       ISA draft 0: encoder, disassembler, semantics (one module per ISA revision)
tmc/sim.py          instruction-level simulator: memory, I/O page, statistics, interrupts
tmc/testing.py      program test suite
tmc/report.py       generates docs/performance.md
tmc/hw/microcode.py control word layout and microcode for v0; also the cycle counts for the simulator
tmc/hw/cpu_v0.py    chip-level netlist of the v0 CPU
tmc/hw/chips.py     chip library: pins, timing arcs, parts variants
tmc/hw/netlist.py   netlist description language (automatic gate packing, driver checks)
tmc/hw/sta.py       static timing analysis with per-microinstruction case analysis
tmc/hw/timing.json  delays per part, built from tmc/hw/datasheets by build_timing.py
hwsim/              Go event-driven simulator: chip models, setup/hold, write timing, bus contention
programs/           benchmark programs, library routines, reference.py (independent expected outputs)
tests/              assembler/ISA unit tests, hardware exercise programs
```

## Changing the ISA

The tooling is split so most of it carries over to the next draft:

- **ISA-independent**: the assembler core, the simulator harness, the test
  suite and report, the chip library and timing data, the netlist language,
  the static timing analyser and the Go simulator.
- **Per ISA**: `tmc/isa/vN.py` (encodings, assembler hook, semantics), the
  microcode, and the CPU netlist. The Go simulator's main loop expects a few
  conventional net names (`uHALT_n`, `uEND_n`, `uLDIR_n`, `MODERST`,
  `MODEIRQ`, `IFLAG`, `ADDRn`, `DBUSn`, `PCn`) and register-file chips
  `U_RF{A,B}{L,H}`; a new CPU netlist keeps those names or adjusts `hwsim/main.go`.

Select an ISA revision with `python3 -m tmc --isa vN ...`.
