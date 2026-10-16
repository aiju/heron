---
status: active
depends-on: []
reports: []
---

# Figures in documents

Small languages for the pictures in reports and RFCs, in place of ASCII
art: timing diagrams, bit fields, block diagrams, address maps, and
tables drawn as charts, such as an opcode map. A figure's source sits in
a comment in the document, and the SVG it draws in the document's
folder, where GitHub and the site show it. Everything is plain Python
with no dependencies.

The [gallery](gallery.md) draws every picture on `main` (at `198d40a`)
in these languages, with the ASCII next to it, and a few new ones.

## Running it

```sh
heron figures write                 # draw every figure in the repository's Markdown into its SVG
heron figures write reports/0037-rfc-system-and-io-bus.md   # or one document's
heron figures check                 # only check that every SVG is what its source draws
heron figures list                  # the figures: document, line, language, SVG
heron figures draw access.timing    # one source file, to access.timing.svg (-o elsewhere)
heron test figures                  # the study's unit tests, the gallery's SVGs among them
```

All of the gallery's figures draw in about 0.1 s together.

## In a document

The source goes in a comment whose first word names the language, and
the image that is its SVG right after it:

```markdown
<!-- timing
.grid 1 'BCLK edge'
BCLK  8{:1 +.5:0 +.5}
SEL   :0 2.1[on]:1 5.1[off]:0
  <-> on off 'STROBE'
-->
![An access](gallery/access.svg)
```

- **The SVG's path** is the image's, relative to the document. A
  report's or RFC's figures go in its folder, `reports/NNNN-slug/`.
- **After changing a source,** run `heron figures write`: the SVG is
  generated, like the other generated files, and `heron figures check`
  finds one that wasn't redrawn.
- **The source can't contain `-->`,** which ends the comment. None of
  the languages needs it.
- **A fenced block** whose info string is the language (```` ```timing ````)
  works the same and shows its source, as the gallery does.

## The languages

They share their lexing where they can: a statement a line, `#` to the
end of a line a comment, `"..."` or `'...'` a string (doubled to include
the quote), and settings for the whole figure on lines that start with a
dot. bits, blocks and map are keyword-first and take `key=value`
attributes; grid is Markdown's table; timing keeps timepic's denser
notation.

### timing

After Emily's timepic(1): a signal is its values at times, times are
expressions with units, and a time can be named and measured from.

```timing
ns = 1/60                         # a constant; 25ns is 25 × ns
.grid 1 'BCLK edge'               # a line and a number at every clock
.range 0 11                       # the times shown
BCLK  11{:1 +.5:0 +.5}            # 11 times: high, then low half a clock on, ...
SEL   :0 1.1[on]:1 9.1[off]|:0    # 0; 1 at 1.1, called on; 0 at 9.1, called off
WAIT  :1 on+25ns[w]:0 5.4[r]:1
  <-> on w '≤ 30 ns'              # an interval under the row above
D     :z 5.2[d]:'read data' off+.15:z
  ^ off 'taken'                   # a pointer under the row above
d -> r 'then released'            # an arrow from one named edge to another
```

- **Values:** `0`, `1`, `x` (unknown, hatched), `z` (floating), or
  anything else, which is a bus's value and its label.
- **Times:** an expression is an absolute time, `+` before one is
  relative to the last. `[name]` names the time before it, for other
  signals, intervals and arrows; a name can be used before the line
  that gives it in intervals and arrows only.
- **`N{...}`** repeats its events N times; times inside are relative.
  **`|`** before a value draws a dashed line across the diagram at it.
- **Settings:** `.grid step 'label'`, `.range from to`, `.width` and
  `.row` in pixels.
- **From timepic:** the values, `+`, `[name]`, `{}`, `|` and units.
  **Changed:** a newline ends a statement, `#` comments, a time is a
  whole expression (`1c+t`), units work in assignments too, numbers are
  decimal, a signal can't go back in time, and an empty signal's time
  starts at 0. **New:** intervals, pointers, arrows, the grid.

### bits

Bit fields: instruction encodings, registers, table entries.

```bits
word 16 "MOV rd, #u7"           # a word: its width in bits, a label
  15-12 rd                      # a field: its bits and its name
  11-8  "u7 6–3"
  7-3   = 01110                 # constant bits
  2-0   "u7 2–0"
  over 15-8 "register byte"     # a bracket over some bits (or under)
word 8 beside                   # the next word goes to the right of this one
  7-0 opcode
```

- **Fields** are a bit (`13 WAIT`) or a range (`15-12`, `15–12`,
  `15..12`). Every bit of a word must be in exactly one field.
- **A name too long for its field** goes under it on a leader. A field
  called `reserved` is hatched.
- **Settings:** `.bit N`, a bit's width in pixels (from 16 to 40 by
  default, to fit the widest row), and `.numbers all|edges|none`, which
  bit numbers to show (also a word's `numbers=`).

### blocks

Block diagrams, laid out by hand on a grid of 10-pixel units.

```blocks
box alu "ALU" "8 × 74LS181" at 20,4      # a box: name, lines of text, where
box mux "result mux" right of alu gap 4  # right of, left of, below, above
text "posted writes" right of bif        # text without a box
bus a "A bus" from 0,2 to 40,2           # a bus: straight, thick
alu -> mux "F"                           # a wire between the sides that face
alu.right -> mux.left                    # or between sides of your choosing
mux.right -> 60,8 via 56,8               # through points of its own
r - sram.top-3                           # 3 units left of the side's middle
frame "the CPU card" around alu mux      # a dashed frame
dot 30,2
```

- **A box** is as big as its text (`width=` and `height=` in units say
  otherwise). Its first line is its title; `plain` sets every line alike
  and `dashed` dashes it. `align=top` (or `bottom`, `left`, `right`) lines
  it up with the box it's placed against; `dx=` and `dy=` nudge it.
- **A point** is `x,y`, a box's side with an optional offset in units
  along it, a box (the side that faces the other end), or a bus (straight
  across to it, with a dot where it meets it).
- **Wires** are `->`, `<-`, `<->` or `-`, and can chain (`a -> b -> c`).
  Two sides that overlap meet straight; otherwise a wire goes across and
  down as its ends' sides say, and two sides that face the same way meet
  as a U. A label goes on the longest stretch (`place=start` or `end`
  puts it at an end).

### map

Address maps, a region a line.

```map
0x0000_0000  "regions 0–3" "CPU or memory cards"   # where a region starts, its text
0x7000_0000  registers
0x7700_0000  free                                  # free, unused, reserved: hatched
0x8000_0000                                        # an address alone: the end
group 0x0000_0000 0x7000_0000 memory               # a bracket beside
```

Regions are as high as their text, not as big as they are; high
addresses are at the top (`.order down` turns it over).

### grid

A table drawn as a chart, whose cells can span: an opcode map.

```grid
| | _0 | _1 | _2 |
| 0_ | ILLEGAL | LDM rb,ra-rc +1 | STM rb,ra-rc +1 |
| 7_ | MVI #u7 ×8 | ↳ | ↳ |
| C_ | LSL #n ×2 | ↳ | |
```

The first row is the columns' heads, then a row a line: its head and its
cells. `↳` continues the cell to its left, and an empty cell is free,
and hatched. The rows are written as Markdown's, so a table converts by
copying it (the `|---|` line is skipped, and backticks dropped); `#`
comments are whole lines. A cell's first word
is its title; words that start with `+` or `×` go small under the rest.
`.cell W` sets the cells' width in pixels.

## The drawing

- **The site's look:** its colours and its fonts, Libre Franklin and IBM
  Plex Mono, with Helvetica, Arial and the system's monospace after them.
  Text is measured with Libre Franklin's widths (`svg.py`), which are a
  little wider than Helvetica's and Arial's.
- **Light and dark:** a figure carries both, and follows the reader's
  setting by itself, in an `<img>` too. Every style is under the class
  `diagram`, so a page can also include an SVG inline.
- **Deterministic:** the same source draws the same bytes, so `check`
  can compare them.

## Open

- **Fonts on GitHub:** an `<img>` can't load web fonts, so GitHub shows
  the figures in Helvetica or Arial. The site could put them into its
  pages instead, where its own fonts apply; embedding the fonts would
  make every SVG some 20 KB bigger.
- **The site's figures** have a border and a white background, which
  suits screenshots but not these: a dark figure on white. The site
  would show `.svg` images (or inline ones) without them.
- **Committing SVGs:** they can be regenerated in a moment, which
  AGENTS.md says not to commit, but GitHub can only show a committed
  file. They would be the exception, and `heron figures check` could go
  into `heron test`; drawing all of them takes well under a second.
- **timing's notation** is denser than the others'. A spelled-out form,
  an event a line, is possible (a sketch, not built):

  ```
  SEL   :0 2.1[on]:1 5.1[off]:0        # as it is

  signal SEL                           # spelled out
    0
    at 2.1, on: 1
    at 5.1, off: 0
  ```

  It reads without knowing the notation and diffs an event at a time,
  but a diagram gets three or four times as long, and timepic's lines
  line up as the waveforms do.
- **Labels can collide:** nothing moves a wire's or an arrow's label
  out of the way of another; the source does, by moving things.
- **Not converted in place:** report 0012 is `current` and can't be
  rewritten, RFC 0001 is `obsolete`. The open RFCs' pictures (0016, 0027,
  0028, 0037) could be.
- **A chart beside its table, or instead of it:** the opcode map's chart
  is easier to take in, but the table can be searched and copied. A
  document could keep the table and draw the chart from it, which would
  need the figure's source to name the table rather than repeat it.
- **Not done:** plots, which `studies/bus_si/svgplot.py` already draws
  from data.
