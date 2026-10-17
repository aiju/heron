# RFC 0000: timing diagrams (timing)

Signals over time: a bus cycle, a handshake, a clock and what it
clocks. After Emily's timepic(1): a signal is its values at times, and a
time can be named and measured from. How a figure goes into a document
is in [RFC 0000](../0000-rfc-repository-layout.md#figures).

```timing
.grid 1 'BCLK edge'
.range 0 8
BCLK            8{:1 +.5:0 +.5}
'A0–A7, WRITE'  :x .1[a]:'address, WRITE, write data' 7.1[b]:x
  <-> a on   '1 + SETUP'
  <-> off b  '1 + HOLD'
SEL             :0 2.1[on]:1 5.1[off]:0
  <-> on off 'STROBE'
'D, a read'     :z 3.6:'read data' off+.15:z
  ^ off 'taken at the end of the strobe'
```

![RFC 0037's access, with SETUP = 1, STROBE = 3 and HOLD = 1](figures-timing/access.svg)

## The language

A statement a line (or up to a `;`); `#` starts a comment.

- **A signal:** its name (in quotes if it has spaces or commas), then its
  events. `:v` is a value from the time so far: `0`, `1`, `x` (unknown,
  hatched), `z` (floating), or anything else, which is a bus's value and
  its label (`:'read data'`, `:DQ`).
- **Times:** an expression is an absolute time, and `+` before one is
  relative to the last (`:1 +.5:0`). A number with a name right after it
  is multiplied by it: with `ns = 1/60`, `25ns`.
- **`[name]`** after a time names it, for other signals (`on+25ns`),
  intervals and arrows.
- **`N{ ... }`** repeats its events N times; times inside are relative.
- **`|`** before a value draws a dashed line across the diagram at its
  time.
- **`name = expr`** defines a constant.
- **Under a signal,** indented by convention:
  - `<-> t1 t2 'label'` is an interval, with dotted lines to the edges
    it measures;
  - `^ t 'label'` is a pointer to a time.
- **`a -> b 'label'`** is an arrow from one named edge to another, for
  cause and effect.
- **Settings:** `.grid step 'label'` (a line and a number at every
  step), `.range from to` (the times shown; otherwise from 0 to the last
  event), `.width` and `.row` in pixels (640 and 36).

Intervals and arrows can name a time that a later line gives; signals
can't.

## Guidelines

- **One operation, drawn with stated values:** a figure shows one case
  (SETUP = 1, STROBE = 3), and its caption says which. The rules belong
  in the text.
- **Derive times from the edges they follow** (`on+25ns`, `off+.15`),
  so that changing one moves the rest.
- **A grid of clocks** for anything synchronous, with units for times
  inside a clock.
- **Few marks:** a handful of intervals and arrows. A label that doesn't
  fit inside its interval goes beside it, and nothing moves labels out
  of each other's way, so check the drawing.
