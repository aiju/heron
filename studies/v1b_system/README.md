---
status: active
depends-on: [v1b_hw, v1_isa]
reports: []
---

# The system: draft 1b on the bus

The draft 1b CPU as a card on the RFC 0014 system bus, with the backplane,
a memory card and an I/O card (UART, timer, CompactFlash card), all as
chip-level netlists that run together on the chip-level simulator. The CPU
card has its own clock generator, which gives each microinstruction a
cycle as long as it needs: one of four lengths, from 260 to 340 ns.

| Slot | Card | Chips | What's on it |
|---|---|---:|---|
| – | Backplane | 51 | Clock driver, power-on reset, slot and class decode, transfer timing, SEL, the bus monitor, the arbiter |
| 0 | CPU | 269 | The draft 1b CPU (`v1b_hw`, 213 chips with its RAM), its 50 MHz clock generator with variable-length cycles, and the bus interface |
| 1 | Memory | 31 | 2 MB of 12 ns SRAM, a fast 32-bit card |
| 15 | I/O | 16 | A 16C550 UART, an 82C54 timer and a CF card, a simple card |

It depends on `v1b_hw` for the CPU (its card mode in `cpu.py`) and its
microcode, and on `v1_isa` for the programs and the instruction-level
simulator, which runs the same system as a model to check the hardware
against.

| File | What's in it |
|---|---|
| [design.md](design.md) | The design: memory map, the bus as built, each card, the variable-length cycles, timing, findings |
| `bus.py` | The bus's signals, where a card's pins go in each slot, and the composer that puts cards into slots |
| `backplane.py`, `cpucard.py`, `memcard.py`, `iocard.py` | The netlists |
| `lengths.py` | The length classes: what each microinstruction needs (static timing analysis), and the classes and jumpers |
| `machine.py` | The composed system on the chip-level simulator: ROM and RAM images, what a run watches |
| `programs.py`, `sw/` | The program suite on the system: the `v1_isa` programs with the system's runtime library, and the system's own programs |
| `model/` | The instruction-level model of the system (a Rust crate): the cards behind the CPU, for the `v1_isa` simulator |
| `bfm.py` | Scripted bus masters and slaves, for testing the backplane and the cards without a CPU |
| `cli.py` | The commands |

```sh
heron v1b_system run studies/v1_isa/programs/v1b/fib.s   # a program on the whole system, against the model
heron v1b_system test [NAMES] [--jobs 4]   # the suite at chip level (about 8 minutes); --isa: on the model only
heron v1b_system bom [--card CPU]          # the parts list
heron v1b_system lengths                   # the length classes and their jumpers
heron v1b_system schematic                 # the netlists as a schematic to browse, in build/v1b_system/schematic.html
heron test v1b_system                      # the unit tests: the bus against RFC 0014 with scripted masters, hello at chip level
```
