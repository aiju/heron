---
status: active
depends-on: []
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
| `estimate.py` | a rough time an instruction from microcycle counts and `sta`'s lengths (not a measurement) |

There is no microcode yet and no chip-level simulation: what the timing
analysis finds, and what's next, is in RFC 0049's section 14 and
[clocking-and-front-end.md](../../reports/0049-rfc-board-first/clocking-and-front-end.md).
