---
status: active
depends-on: [v2_isa, v2_hw, v1b_hw, v1b_tradeoffs, v1b_system, c_compiler]
reports: [41]
---

# Heron Mini

Draft 2's user level on one board, beside the full Heron as a 360/20 was
beside the 360/40: a microcoded CPU with its RAM hardwired, no system
bus, an I/O space with a UART pair, an 82C54, a CF card, a boot flash and
two expansion ports, and a 640 x 480 x 4 framebuffer with per-line
descriptors. The design and what it measures are
[RFC 0041](../../reports/0041-rfc-heron-mini.md).

The design is built as a chip-level netlist and run on the chip-level
simulator: the program suite exactly as the register-transfer model runs
it, the devices and the video against what their programs should give.
Static timing analysis of the netlist gives every microinstruction its
length. The netlist is deliberately overbuilt; the RFC estimates what to
leave out by taking chips out of it.

It depends on `v2_isa` for the ISA, its simulator and the program suite;
on `v2_hw` for the parts of draft 2's CPU it adapts (the microcode's
structure, the static timing analysis); on `v1b_hw` for the shift
planner; on `v1b_tradeoffs` for the fast parts; on `v1b_system` for the
CF card's test pattern; on `c_compiler` for the compiled programs.

| File | What's in it |
|---|---|
| `ucode.py` | The control word, the microcode for every instruction, the parcel-indexed entries, the boot from the flash |
| `rtl.py` | The register-transfer model: datapath, prefetch queue, sequencer, the I/O hold |
| `system.py` | The board behind the CPU in the model: RAM, the I/O regions and their wait states, the suite's I/O page, the UARTs, the video's registers |
| `video.py` | The video: the timing ROM, the picture a frame's memory makes, decoding the frames the netlist sends |
| `timing.py` | How long each microinstruction's cycle must be (`ticks.json`, else an estimate), the four length classes |
| `ticks.json` | Every distinct microinstruction's period from static timing analysis (generated: `heron mini hw sta --write`) |
| `parts.py` | The parts: 74F and 74ABT in DIP, flash, 12 ns SRAM |
| `board.py` | The chip-level netlist: CPU, clock generator and hold, RAM and video RAM, I/O space and devices, video |
| `hw.py` | The netlist on the chip-level simulator: the suite against the RTL model, the devices and video programs, the parts list |
| `sta.py` | Static timing analysis of the netlist, per microinstruction |
| `perf.py` | Profiles the suite on the RTL model (cached in `build/mini/`) |
| `check.py` | The RTL model against the instruction-level simulator |
| `sw/hw/` | Programs for the chip-level netlist only: `devices.s` (the I/O devices), `video.s` (the video) |

```sh
heron mini check [--c]               # the RTL model against the ISA simulator: the suite, the C programs
heron mini run PROG.s [--profile]    # one program on the RTL model
heron mini perf                      # the suite's time with the length classes
heron mini hw test [NAMES]           # the suite at chip level against the RTL model (about 5 minutes)
heron mini hw devices                # the devices program at chip level (UARTs, flash, CF, 82C54)
heron mini hw video [--png F]        # the video program at chip level, its frames grabbed (about 90 s)
heron mini hw sta [--write]          # static timing analysis; --write rewrites ticks.json
heron mini hw bom                    # the parts list
heron test mini                      # the unit tests
```
