---
status: active
depends-on: [v2_isa, v1b_hw, c_compiler]
reports: [31]
---

# A draft 2 CPU

A CPU for draft 2 ([RFC 0028](../../reports/0028-rfc-draft-2-isa.md)) with
RFC 0029's system architecture, built on RFC 0024's advice: fast parts and
short variable-length cycles, a writable control store that the I/O
processor fills at boot, a 32-bit memory and system bus, and a prefetch
queue that fetches in the cycles that don't use memory. The design is
[RFC 0031](../../reports/0031-rfc-draft-2-cpu.md); its measurements are
in [performance.md](../../reports/0031-rfc-draft-2-cpu/performance.md).

Work in progress: the microcode and a register-transfer model checked
against draft 2's instruction-level simulator, and a chip-level netlist of
the CPU's core (with its RAM, page map and control store, not yet the bus
interface or the slave port) that runs the suite on the chip-level
simulator exactly as the model does. Static timing analysis of the netlist
gives every microinstruction its length.

It depends on `v2_isa` for the ISA, its simulator and the program suite,
on `v1b_hw` for the shift planner (the shift steps are draft 1b's), and on
`c_compiler` for the compiled programs.

| File | What's in it |
|---|---|
| `ucode.py` | The control word, the microcode for every instruction, the decode table |
| `timing.py` | How long each microinstruction's cycle must be (as `ticks.json` says, else an estimate from datasheet delays), the four length classes, and what-ifs for changes not built |
| `ticks.json` | Every distinct microinstruction's period from static timing analysis (generated: `heron v2_hw hw sta --write`) |
| `rtl.py` | The register-transfer model: datapath, prefetch queue, page map, register banks, sequencer |
| `system.py` | The memory system behind it: translation, the card's RAM, the system bus and its cards with transfer times, the instruction cache for bus space |
| `iop.py` | The boot: the I/O processor writing the control store, the decode table and RAM through the card's slave port |
| `check.py` | The RTL model against the instruction-level simulator: the suite, the compiled C programs, the exercise program, the system tests |
| `exercise.py` | Generates the exercise program: every ALU operation and mode on chosen values, flags, multiply, divide, shifts, the tentative instructions |
| `perf.py` | Profiles the suite (cached in `build/v2_hw/`), picks the length classes, breaks the time down |
| `report.py` | RFC 0031's tables |
| `parts.py` | The parts the netlist is built from (the `v2-fast` variant of the chip library) |
| `cpu.py` | The chip-level netlist: with the clock generator and the I/O page as a fixture for the chip-level simulator, or with a clock fixture for static timing analysis |
| `hw.py` | The netlist on the chip-level simulator (`heron v2_hw hw`): its preloads, a run checked against the RTL model cycle for cycle, the parts list |
| `sta.py` | Static timing analysis of the netlist: case analysis per microinstruction in each state of the queue, the fetch's translation and the forced entries; the register file's write phase; `ticks.json` |
| `explore.py`, `explore.html` | The design explorer (`heron v2_hw explore`): the netlist as nested block diagrams down to the chips, grouped by unit, section and the netlist's own comments; a chip-level run of three programs with what each cycle's microinstruction drives and its critical path, from the timing analysis' case analysis; the suite's profile as heat |
| `sw/` | Programs for this CPU: `systest.s` (RFC 0029's supervisor features), `interrupts.s` (the suite's interrupt program with RFC 0029's vectors), `isanotes.s` (where it follows RFC 0028 and the simulator doesn't), and their expected output |

```sh
heron v2_hw check [NAMES] [--lockstep]   # the suite on the RTL model against the ISA simulator
heron v2_hw check --c                    # the compiled C programs
heron v2_hw check exercise systest       # the exercise program, the system tests
heron v2_hw check --bus [--icache N]     # code and data on the memory card, over the bus
heron v2_hw run studies/v2_isa/programs/life.s --profile   # cycles, time, where they go
heron v2_hw boot studies/v2_isa/programs/sieve.s           # booted by the I/O processor
heron v2_hw perf [--bus] [--icache N]    # the suite's time and where it goes
heron v2_hw report --write               # RFC 0031's performance.md (profiles: minutes)
heron v2_hw ucode [--list]               # the microcode's size and length classes
heron v2_hw hw test [NAMES] [--lengths 10,11,12,14]   # the netlist against the RTL model
heron v2_hw hw run studies/v2_isa/programs/hello.s --trace 0:50   # with a per-cycle trace
heron v2_hw hw sta [--write] [--paths N]  # static timing analysis; --write updates ticks.json
heron v2_hw hw bom                       # the netlist's parts
heron v2_hw explore                      # the design explorer, build/v2_hw/explorer.html (half a minute)
heron test v2_hw                         # the unit tests
```
