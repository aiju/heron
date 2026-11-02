---
status: active
depends-on: []
reports: [49]
---

# Cards: napkin designs on double Eurocards

The napkin behind [RFC 0049](../../reports/0049-rfc-board-first.md): the
next Heron sketched as boards on a backplane first, in three designs.
Not a netlist and not a model. Each board is a list of blocks and each
block the parts it needs, so that a chip count is a parts list rather
than a guess; each key instruction is a list of microcycles, each with
the longest path it carries, summed from worst-case datasheet delays and
generous figures for wires and the backplane.

```sh
heron cards napkin            # the tables
heron cards napkin --write    # into reports/0049-rfc-board-first/napkin.md
heron test cards              # the unit tests (napkin.md must be up to date)
```

- **`napkin.py`:** the parts and their area on a board, the three
  designs' boards, the delays, each design's instructions as microcycles,
  and the weighting by the compiled C programs' dynamic mix (data taken
  from `heron c_compiler cc --isa v2 --run --stats` and the
  instruction-level simulator's traces, recorded in the file).
- Change a delay, a part or a recipe there, then `--write`: the RFC's
  tables follow.
