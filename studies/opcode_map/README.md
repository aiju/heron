---
status: active
depends-on: []
reports: [28]
---

# The opcode map

The browser tool draft 2's opcode map was laid out in, with
[RFC 0028](../../reports/0028-rfc-draft-2-isa.md)'s map built in. The
first byte's 256 cells are a 16 × 16 grid. Each cell holds an
instruction, with an addressing mode or a whole row of them, or leads to
an extension grid whose second byte picks the opcode. Click a cell for
its encoding, bit by bit, and its length in parcels. The checks list
what doesn't fit, what's encoded twice and what traps. The catalog holds
the instructions of drafts 1a and 1b, the RFCs' proposals and your own,
and the addressing modes, to place on the grid.

```sh
heron opcode_map build            # build/opcode_map/opcode-map.html, with RFC 0028's map
heron opcode_map serve            # the same on http://localhost:8000/opcode-map.html
heron opcode_map build --map F    # with another exported map
heron site --apps                 # the website, with the map on its Apps page
heron test opcode_map             # the unit tests
```

## The map and your maps

- **RFC 0028's map** is [`map.json`](../../reports/0028-rfc-draft-2-isa/map.json)
  in the RFC's folder, as the tool exports it. The page is built with
  it, named after the commit that last changed it, for example
  "RFC 0028 (b3cfc83)".
- **Your maps** live in your browser (IndexedDB), each with its history
  for undo and redo. Nothing you do on the page changes the RFC's map.
- **A first visit** opens the RFC's map. A later visit after the RFC's
  map has changed opens the new one as a map of its own and leaves yours
  as they were. **RFC map** opens a fresh copy at any time.
- **To change the RFC's map,** export it from the tool (Export, JSON) and
  commit it over `map.json` with the RFC's change, so the two agree.

## Files

| File | What it is |
|---|---|
| `opcode-map.html` | The tool: one page, with Preact and htm from a CDN |
| `page.py` | Builds the page with a map in it |
| `cli.py` | `heron opcode_map` |
| `tests/` | The page has the RFC's map, and every cell of the map names an instruction, mode and grid the tool knows |

The tool's catalog describes draft 2's multiplies with `r0` and `r1`,
where draft 1 had `HI` and `LO`
([RFC 0028, 9.9](../../reports/0028-rfc-draft-2-isa.md#99-hi-and-lo-are-r0-and-r1)).
