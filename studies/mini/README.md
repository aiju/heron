---
status: active
depends-on: [v2_isa, v2_hw, v1b_hw, v1b_tradeoffs, v1b_system, c_compiler, lisp]
reports: [41]
---

# Heron Mini

Draft 2's user level without a system bus, beside the full Heron as a 360/20 was
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
CF card's test pattern; on `c_compiler` for the compiled programs; on
`lisp` for the Lisp, whose type checks are address errors.

| File | What's in it |
|---|---|
| `ucode.py` | The control word, the microcode for every instruction, the parcel-indexed entries, the block instructions, the boot from the flash |
| `rtl.py` | The register-transfer model: datapath, prefetch queue, sequencer, the I/O hold |
| `engine/` | The same model in Rust (the crate `mini-engine`), cycle for cycle, with the board and the video options of [RFC 0042](../../reports/0042-rfc-mini-video.md): about 200 times faster |
| `sim.py` | The fast simulator for software: the engine from Python (`heron.native.mini`), frames as PNG files |
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
| `bench.py` | Graphics kernels: draft 2 code against the block instructions, on the RTL model |
| `reduce.py` | What could be left out: the chips each reduction removes, its time from the profile |
| `report.py` | RFC 0041's tables (`reports/0041-rfc-heron-mini/performance.md`) |
| `sw/video/` | `demo.s`: RFC 0042's options from a program (1024 x 768 x 2 from a frame base, the cursor, the beam) |
| `sw/hw/` | Programs outside the suite: `devices.s` (the I/O devices) and `video.s` (the video), for the chip-level netlist; `addrerr.s` (the address error), also on the model |

```sh
heron mini check [--c]               # the RTL model against the ISA simulator: the suite, the C programs
heron mini check addrerr             # the address error (sw/hw/addrerr.s)
heron mini check --lisp [--compiled] # the Lisp's short tests (studies/lisp), whose type checks are address errors
heron mini run PROG.s [--profile]    # one program on the RTL model
heron mini sim PROG.s [--png F]      # one program on the fast simulator, with RFC 0042's video
heron mini perf                      # the suite's time with the length classes
heron mini bench                     # graphics kernels: code against the block instructions
heron mini report [--write]          # RFC 0041's tables (performance.md; a few minutes)
heron mini schematic                 # the netlist in the schematic viewer (build/mini/schematic.html)
heron mini hw test [--c] [NAMES]     # the suite (--c the C programs) at chip level against the RTL model (about 6 minutes)
heron mini hw devices                # the devices program at chip level (UARTs, flash, CF, 82C54)
heron mini hw video [--png F]        # the video program at chip level, its frames grabbed (about 90 s)
heron mini hw blocks                 # the block instructions at chip level against the RTL model
heron mini hw sta [--write]          # static timing analysis; --write rewrites ticks.json
heron mini hw bom                    # the parts list
heron test mini                      # the unit tests
```

## Software on the simulator

`heron mini sim` runs a program on the Rust engine with every video
option of [RFC 0042](../../reports/0042-rfc-mini-video.md) (its Part I
is the programmer's reference; 12 says how the simulator models it):

```sh
heron mini sim studies/mini/sw/video/demo.s --png demo.png   # the picture as it halts
heron mini sim prog.s --frames 60 --png-dir frames/  # the first 60 frames shown
heron mini sim prog.s --bandwidth B1 --layout L1     # the board's options
heron mini sim prog.s --profile                      # where the microcycles go
```

It prints the program's console output and where the time went: cycles,
ticks, the I/O holds, the ticks the video stole (B1) and the shifter
loads that found no word (B0, B2: a glitch on the real machine). A
program runs from reset with its image at 0, like the suite's (draft 2
code, `heron.infra.asm`; the suite's `lib/` has a console and number
printing); the console at 0xFFFF_FF00 and its timer and cycle counter
are there, and the UARTs, the boot flash and the video's registers. A
program that waits in `HALT` for interrupts runs until `--frames` or
`--max-cycles`.

From Python, `sim.machine(layout=, bandwidth=)` gives a
`heron.native.mini.Machine` to load (`sim.load`), run
(`run(max_cycles, frames=N)`), look at (`frame()`, `snapshot()`, `r`,
`read(addr, n)`, the counters) and feed (`console_input`, `uart_input`);
`sim.write_png` writes a frame.
