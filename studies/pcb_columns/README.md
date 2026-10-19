---
status: active
depends-on: [pcb, v1b_system]
reports: [46]
---

# Placement on a grid of columns and half-columns

A prototype of [RFC 0046](../../reports/0046-rfc-column-grid.md)'s
placement: every chip of a board on a grid whose rows are 0.1 inch and
whose columns hold a 0.6 inch DIP, or two half-columns of 0.3 inch DIPs
side by side. Each chip gets a box on the grid and sits in the middle of
it, its pins on the 0.1 inch lattice. Connectors, holes and fiducials
stay off the grid, as exceptions. It places only: no routing.

The demonstration is a slice of the draft 1b CPU card (studies/v1b_system):
its ALU, R and T registers, register file, decode ROMs and clock
generator, 48 chips with the card's own nets, on a double Eurocard (6U ×
160 mm) with RFC 0026's mechanics and the card's DIN 41612 connectors.

| File | What's in it |
|---|---|
| `grid.py` | The grid: its parameters, a part's box and where the part sits in it, the lattice on a board |
| `placer.py` | The placer: quadratic targets (infra's), a legal start, annealing on the columns' stacks (each column's boxes in order from its top) for wire length; annealing of the boxes' positions for wire alone, as the comparison; the capacitors under the chips |
| `demo.py` | The demonstration slice: its parts and packages, the card, the checks of a placement |
| `draw.py` | A placed board as an SVG: the grid, the boxes, the parts |
| `report.py` | RFC 0046's results and figures |
| `footprints.py` | The footprints the study uses, downloaded from KiCad's library where it isn't installed |
| `cli.py` | The commands |

```sh
heron pcb_columns place                        # the slice with the defaults: build/pcb_columns/<name>/
heron pcb_columns place --half 4 --size 110x233.35   # tighter, on a smaller card
heron pcb_columns place --module 5 --gap 3 --pads socket-long
heron pcb_columns report --write               # RFC 0046's results.md and figures (a few minutes)
heron pcb_columns fetch                        # the footprints, into build/kicad/footprints/
heron test pcb_columns                         # the unit tests
```

A placement goes to `build/pcb_columns/<name>/`: `board.kicad_pcb` (the
parts placed, no copper), `board.svg` and `result.json` (the grid, the
boxes, the share of the grid used, the wire's half-perimeter length, and
the checks: every chip in its box with its pins on its lattice, no
courtyards overlapping, the least gap between two chips' pads).

**What it needs:** KiCad's footprint library. Where KiCad isn't
installed, the commands download the 53 footprints the study uses
from KiCad's repository (tag 9.0.0) into `build/kicad/footprints/` the
first time; the tests that need them are skipped until then.
