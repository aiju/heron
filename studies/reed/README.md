---
status: active
depends-on: [v2_isa]
reports: [49]
---

# Reed: design A at chip level

Reed (a codename, Emily 2026-11-02) is design A of
[RFC 0049](../../reports/0049-rfc-board-first.md), the Spine: five double
Eurocards on a backplane, CTRL, ALU, MEM, IO and VIDEO, joined by two
32-bit buses (A and B) and 64 control lines with one driver each. This
study is its chip-level netlist, board by board, with the checks the
netlist language has, the backplane's own (each control line driven by
its board alone), and its static timing on infra/sta (RFC 0048).

```sh
heron reed boards      # each board's packages, area and parts
heron reed check       # build the whole machine and check it
heron reed sta         # static timing of each kind of microcycle (seconds)
heron reed estimate    # a rough time an instruction: front ends and cycle lengths on the napkin's mix
heron reed ucode       # the microcode's listing
heron reed hw smoke    # the whole machine at chip level running a small program, against draft 2's simulator
heron reed hw check    # the chip-level gate: small programs at both corners and three seeds
heron reed hw lockstep # the model against the chip level, cycle by cycle
heron reed fuzz        # the microcode against draft 2's simulator, an instruction at a time (faults too)
heron reed systest     # the system half (sw/systest.s) against draft 2's system simulator
heron reed kernel [--chip]   # the nucleus (sw/kernel.s) on the model; --chip at chip level too (minutes)
heron test reed        # the unit tests
```

| File | |
|---|---|
| `bus.py` | the backplane: A, B, the control lines and their drivers, the connectors' pins |
| `fields.py` | the microinstruction: each board's slice of it, the fields' codes |
| `parts.py` | the parts variant (SOIC logic, 45 ns control store), packages and their area, extra chip types |
| `common.py` | helpers: sums of products, a board's control slice, clock buffers, gated clocks |
| `ctrl.py`, `alu.py`, `mem.py`, `io.py`, `video.py` | the boards (each module's docstring describes its board) |
| `clockcard.py` | the clock card: the oscillator, the clock generator, the clock trees |
| `system.py` | the boards joined; the checks; the boards' statistics |
| `sta.py` | the static timing cases: each kind of microcycle at each length, and what fails |
| `ucode.py` | the microassembler and the microcode: words by field, the decode table, the parts' images |
| `ucode_sys.py` | the system's microcode: exceptions, interrupts, the system instructions (RFC 0029) |
| `model.py` | the cycle-level model: the microcode's images run with the netlist's semantics, and the IO board as software sees it |
| `hw.py` | the machine at chip level (infra/hwsim): preloads, the run, the smoke test against `v2_isa`, the lockstep with the model |
| `fuzz.py` | random instructions on the model against draft 2's simulator, faults compared at the vector |
| `systest.py` | `sw/systest.s` on the model and on draft 2's system simulator (`heron.native.v2.SysMachine`) |
| `kernel.py` | the nucleus on the model, and at chip level |
| `sw/` | programs for Reed: `systest.s`, `irqtest.s` and `irquser.s` (interrupts, from supervisor and user mode), `kernel.s` |
| `estimate.py` | a rough time an instruction from microcycle counts and `sta`'s lengths (not a measurement) |

The microcode is draft 2's instruction set but its tentative instructions,
and RFC 0029's system half with Reed's differences. What the timing
analysis and the chip-level runs find, and what's next, is in RFC 0049's
section 14 and its folder:
[clocking-and-front-end.md](../../reports/0049-rfc-board-first/clocking-and-front-end.md),
[microcode-and-model.md](../../reports/0049-rfc-board-first/microcode-and-model.md),
[system.md](../../reports/0049-rfc-board-first/system.md).
