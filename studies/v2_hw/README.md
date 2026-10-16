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
against draft 2's instruction-level simulator, with a timing estimate from
datasheet delays; no netlist yet.

It depends on `v2_isa` for the ISA, its simulator and the program suite,
on `v1b_hw` for the shift planner (the shift steps are draft 1b's), and on
`c_compiler` for the compiled programs.

| File | What's in it |
|---|---|
| `ucode.py` | The control word, the microcode for every instruction, the decode table |
| `timing.py` | How long each microinstruction's cycle must be (an estimate from datasheet delays until there's a netlist), the four length classes, and what-ifs for changes not built |
| `rtl.py` | The register-transfer model: datapath, prefetch queue, page map, register banks, sequencer |
| `system.py` | The memory system behind it: translation, the card's RAM, the system bus and its cards with transfer times, the instruction cache for bus space |
| `iop.py` | The boot: the I/O processor writing the control store, the decode table and RAM through the card's slave port |
| `check.py` | The RTL model against the instruction-level simulator: the suite, the compiled C programs, the exercise program, the system tests |
| `exercise.py` | Generates the exercise program: every ALU operation and mode on chosen values, flags, multiply, divide, shifts, the tentative instructions |
| `perf.py` | Profiles the suite (cached in `build/v2_hw/`), picks the length classes, breaks the time down |
| `report.py` | RFC 0031's tables |
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
heron test v2_hw                         # the unit tests
```
