---
status: active
depends-on: [reed, pcb, pcb_columns]
---

# Reed's CPU boards as printed circuit boards

A trial layout of [Reed](../reed/README.md)'s boards (design A of
[RFC 0049](../../reports/0049-rfc-board-first.md)), to measure whether
each fits a double Eurocard, routes, and keeps its timing with real
wires: numbers for the decision on splitting the CPU into four boards and
on the 22V10s, not the decision. The ALU board first, then MEM, then CTRL.

So far it **places**: each board's netlist (`studies/reed`'s
`system.board`) becomes its parts in the packages `studies/reed/parts.py`
gives them, on a double Eurocard (233.35 × 160 mm) with
[RFC 0026](../../reports/0026-rfc-pcb-design-rules.md)'s mechanics and
the two DIN 41612 connectors at the back edge, the 233.35 mm one that
meets the backplane in a card cage; [RFC 0046](../../reports/0046-rfc-column-grid.md)'s
column grid places the chips (`studies/pcb_columns`). Nothing is routed
yet.

```sh
heron reed_pcb place                  # the ALU board: build/reed_pcb/<name>/
heron reed_pcb place --gal-sockets    # the ATF22V10C-5s in PLCC-28 sockets
heron reed_pcb place --seed 3 --module 5
heron reed_pcb place --size 220x233.35   # a deeper card
heron reed_pcb place --floorplan      # the ALU by its hand-made floorplan, on 220 mm
heron test reed_pcb                   # the unit tests
```

A placement goes to `build/reed_pcb/<name>/`: `board.kicad_pcb` (the
parts placed, no copper), `board.svg` and `result.json` (the grid's
numbers as `pcb_columns` gives them, the area against RFC 0049's
estimate, the cells each package takes).

| File | What's in it |
|---|---|
| `place.py` | A board's parts from Reed's netlist (packages, pinouts, the register file's 16-bit SRAMs as one package each, the connectors), placing it, its numbers |
| `floorplan.py` | The ALU placed by hand: four byte slices from the backplane inwards, the control below beside P2 |
| `cli.py` | The commands |

**Packages and pinouts:** the footprints are KiCad's, by the package
names in `studies/reed/parts.py` (`FOOTPRINTS` in `place.py`); the
pinouts are infra's (`infra/pcb/packages.py`), which has the 22V10's
PLCC-28 (`22v10_plcc`), the AT27C010 (`27c010`) and the IS61C6416's
SOJ-44 (`sram64k16`) for this study. The SOJ-44's isn't checked against
the datasheet yet (ISSI's site doesn't serve it to a script, and KiCad
has no symbol for it); it agrees with `studies/chibi`'s, written
independently.

**What it needs:** KiCad's footprint library, downloaded on first use
into `build/kicad/footprints/` where KiCad isn't installed
(`studies/pcb_columns`).
