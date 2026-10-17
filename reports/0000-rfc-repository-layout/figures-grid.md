# RFC 0000: tables as charts (grid)

A table drawn as a chart, whose cells can span: an opcode map. How a
figure goes into a document is in
[RFC 0000](../0000-rfc-repository-layout.md#figures).

```grid
| | _0 | _1 | _2 | _3 | _4 | _5 | _6 | _7 |
|---|---|---|---|---|---|---|---|---|
| 7_ | MVI #u7 ×8 | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ |
| C_ | LSL #n ×2 | ↳ | LSL rs |  | LSR #n ×2 | ↳ | LSR rs |  |
| D_ | NOT | NEG | INC | DEC | RLC | RRC | SWAP | SXB |
```

![Part of RFC 0028's opcode map](figures-grid/opcode-map.svg)

## The language

The rows are written as Markdown's, so a table becomes a chart by
copying it into the figure.

- **The first row** is the columns' heads; its first cell is the corner.
  The line under it (`|---|`) is skipped.
- **Every other row** is its head, then its cells.
- **`↳`** continues the cell to its left: `MVI #u7 ×8` and seven `↳`
  span eight columns.
- **An empty cell** is free, and hatched.
- **A cell's text:** its first word is its title; words that start with
  `+` or `×` go small, under the rest. Backticks are dropped.
- **`#`** at the start of a line is a comment. **`.cell W`** sets the
  cells' width in pixels (58).

## Guidelines

- **A chart where the arrangement means something:** an opcode map,
  whose rows and columns are bits of the opcode.
- **The chart can replace its table** when the facts are also in the
  text, as RFC 0028's instruction tables give each instruction's cells.
  Where they aren't, keep the table: a reader can search and copy it.
