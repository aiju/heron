# ttl-minicomputer

Design exploration for a minicomputer to be built from 7400-series logic
chips. There have been two rounds so far:

- **Draft 0:** a 16-bit instruction set, evaluated end to end. That covers an
  assembler and simulator, a suite of real programs, notes on writing them,
  a 98-chip implementation with an event-driven timing simulator, and
  performance numbers.
- **Draft 1:** a 32-bit machine with 16-bit instruction words, in two
  candidate encodings. 1a is load/store; 1b is register + addressing mode.
  Each has an assembler and simulator, 20 programs written for both, and
  cycle estimates for six hardware configurations (16- or 32-bit datapath,
  three fetch styles).
- **Draft 1b hardware:** a 213-chip implementation of 1b with a 32-bit
  datapath, pipelined microcode and a separate fetch cycle. It runs all 20
  programs cycle-exactly in the chip-level simulator at 3 MHz (worst-case
  delays) and checks the timing model's estimates.

| Document | What's in it |
|---|---|
| [docs/evaluation-v1.md](docs/evaluation-v1.md) | **Start here**: draft 1a vs 1b, the hardware options, and recommendations for draft 2 |
| [docs/proposals.md](docs/proposals.md) | Every design idea from the discussions so far (ISA, clocking, system bus, MMU, I/O, video, DMA, networking, OS, big ideas) with its status |
| [docs/isa-v1.md](docs/isa-v1.md) | Draft 1, the common machine: registers, flags, memory, I/O, interrupts, shared instruction groups |
| [docs/isa-v1a.md](docs/isa-v1a.md), [docs/isa-v1b.md](docs/isa-v1b.md) | The two draft 1 encodings |
| [docs/timing-model-v1.md](docs/timing-model-v1.md) | How draft 1 cycle counts are estimated |
| [docs/performance-v1.md](docs/performance-v1.md) | Generated: cycles per program and configuration, code size, instruction mix, addressing modes |
| [docs/notes-v1/](docs/notes-v1/) | What writing the draft 1 programs was like, from the five writers |
| [docs/hardware-v1b.md](docs/hardware-v1b.md) | The 213-chip draft 1b implementation: datapath, pipelined microcode, timing, known issues |
| [docs/microcode-v1b.md](docs/microcode-v1b.md) | Generated: the draft 1b microcode for a selection of instructions, cycle by cycle |
| [docs/performance-v1b.md](docs/performance-v1b.md) | Generated: draft 1b hardware clock speed and cycles, against the timing model and draft 0 |
| [docs/evaluation.md](docs/evaluation.md) | The draft 0 evaluation |
| [docs/isa-v0.md](docs/isa-v0.md) | ISA draft 0: encoding, instructions, conventions, assembler syntax |
| [docs/programming-notes.md](docs/programming-notes.md) | What writing the draft 0 programs was like |
| [docs/hardware.md](docs/hardware.md) | The 98-chip draft 0 implementation: datapath, microcode, timing, known issues |
| [docs/performance.md](docs/performance.md) | Generated: draft 0 clock speed, cycles and run time per program, instruction mix |

## Running things

Needs Python 3.10+ and Go 1.21+ (for the chip-level simulator). No other
dependencies.

```sh
python3 -m tmc --isa v1b run programs/v1b/life.s --stats   # draft 1b: cycles for all six configurations, mix, profile
python3 -m tmc --isa v1a test                    # all draft 1a programs against expected output
python3 -m tmc report1                           # regenerate docs/performance-v1.md (under a minute)

python3 -m tmc --isa v1b hw run programs/v1b/fib.s --period 340   # draft 1b on the chip-level simulator
python3 -m tmc --isa v1b hw test --period 340 --max-cycles 10000000  # all draft 1b programs at chip level
python3 -m tmc --isa v1b hw sta                  # static timing analysis of the 1b netlist
python3 -m tmc --isa v1b hw bom                  # its parts list
python3 -m tmc --isa v1b ucode [--doc]           # 1b ROM images and full listing in build/ucode-v1b (--doc: docs/microcode-v1b.md)
python3 -m tmc.hw.check_v1b [--lockstep] [NAME]  # 1b RTL model against the ISA simulator ("exercise" too)
python3 -m tmc report1b [--hw]                   # regenerate docs/performance-v1b.md (--hw: about 30 minutes)

python3 -m tmc run programs/mandel.s --stats    # draft 0: assemble and run, with an instruction mix
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
tmc/isa/v1a.py      draft 1a; v1b.py draft 1b; v1common.py what they share (semantics, common groups)
tmc/sim32.py        instruction-level simulator for the 32-bit draft 1 machines
tmc/timing32.py     draft 1 timing model: micro-op scheduler, six hardware configurations
tmc/report1.py      generates docs/performance-v1.md
tmc/sim.py          draft 0 instruction-level simulator: memory, I/O page, statistics, interrupts
tmc/testing.py      program test suite
tmc/report.py       generates docs/performance.md
tmc/hw/microcode.py control word layout and microcode for v0; also the cycle counts for the simulator
tmc/hw/cpu_v0.py    chip-level netlist of the v0 CPU
tmc/hw/ucode_v1b.py draft 1b control word, microcode generator, decode ROM
tmc/hw/rtl_v1b.py   draft 1b register-transfer model (runs the ROM images; checks microcode rules)
tmc/hw/cpu_v1b.py   chip-level netlist of the draft 1b CPU
tmc/hw/check_v1b.py RTL model against the ISA simulator, whole programs or in lockstep
tmc/report1b.py     generates docs/performance-v1b.md
tmc/hw/chips.py     chip library: pins, timing arcs, parts variants
tmc/hw/netlist.py   netlist description language (automatic gate packing, driver checks)
tmc/hw/sta.py       static timing analysis with per-microinstruction case analysis
tmc/hw/timing.json  delays per part, built from tmc/hw/datasheets by build_timing.py
hwsim/              Go event-driven simulator: chip models, setup/hold, write timing, bus contention
programs/           draft 0 programs and library, reference.py (independent expected outputs)
programs/v1a, v1b/  draft 1 programs and libraries; programs/common/ holds data both use
tests/              assembler/ISA unit tests, hardware exercise programs (tests/hw/exercise_v1b.py
                    generates the 1b one)
```

## Changing the ISA

The tooling is split so most of it carries over to the next draft:

- **ISA-independent**: the assembler core, the simulator harness, the test
  suite and report, the chip library and timing data, the netlist language,
  the static timing analyser and the Go simulator.
- **Per ISA**: `tmc/isa/vN.py` (encodings, assembler hook, semantics), the
  microcode, and the CPU netlist. A netlist module's `CONFIG` tells the Go
  simulator which chips hold the register file and RAM, how wide the address
  and PC are, which nets mark a fetch and a halt, and which I/O fixture to
  use (see `tmc/hw/cpu_v1b.py`); it also expects `CLK`, `RESET_n`, `IFLAG`,
  `ADDRn`, `DBUSn` and `PCn`. `tmc/hw/cli.py` picks the machine from `--isa`.

Select an ISA revision with `python3 -m tmc --isa vN ...`.
