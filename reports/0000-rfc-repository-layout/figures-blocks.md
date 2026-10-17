# RFC 0000: block diagrams (blocks)

Parts and how they connect: a datapath, a card, where a request goes.
Laid out by hand, on a grid. How a figure goes into a document is in
[RFC 0000](../0000-rfc-repository-layout.md#figures).

```blocks
text sys "system bus (P1 + P2)" at 30,0
box bif "bus interface" below sys gap 2
text "posted writes; WAIT on reads" right of bif gap 1.5
box tim "timing ROMs" at 0,11
box vram "VRAM" "4 × 512K × 8, 32 bits" "79 ns slots" right of tim gap 4 width=27
box pix "pixel path" right of vram gap 4
box cop "copper" below vram gap 4
box blit "blitter" left of cop gap 1.5
box spr "sprites, tiles" right of cop gap 1.5
sys -> bif
bif -> vram "CPU slots"
tim -> vram -> pix
blit -> vram
cop -> vram
spr -> vram
```

![Part of RFC 0016's video card](figures-blocks/video.svg)

## The language

A statement a line; `#` starts a comment, `"..."` is a string and
`key=value` an attribute. Coordinates are in grid units, 10 pixels
(`.unit`), with y going down.

- **`box name "title" "line"... where`** is a box, as big as its text:
  its first line is its title, the others smaller. `width=` and
  `height=` in units make it bigger; `dashed` dashes it (something
  optional), and `plain` sets every line alike.
- **`text [name] "line"... where`** is text without a box: a note, or
  something outside the diagram that a wire can start or end at.
- **Where:** `at x,y` (a box's top left; text is centred on y), or
  `right of a`, `left of a`, `below a`, `above a`, with `gap n` units
  (3 if not given). `align=top` (`bottom`, `left`, `right`) lines it up
  with an edge of `a` instead of its middle; `dx=` and `dy=` nudge it.
- **`bus name "label" from x,y to x,y`** is a thick straight line, its
  label above its start (`label=end` puts it after the end of a bus
  across).
- **Wires:** `a -> b ["label"]`, with `->`, `<-`, `<->` or `-` (none),
  chained if wanted (`a -> b -> c`). An end is:
  - a box, `a`: the side that faces the other end;
  - a side, `a.left`, `a.top+2` (2 units along the side from its middle);
  - a bus: straight across to it, with a dot where it meets it;
  - a point, `x,y`.

  Two sides that overlap meet straight, in the middle of the overlap.
  Otherwise a wire goes across and down as its ends' sides say, and two
  sides that face the same way meet as a U. `via x,y ...` routes it
  through points of its own. The label goes on its longest stretch;
  `place=start` or `end` puts it at an end.
- **`frame "label" around a b ...`** draws a dashed frame around boxes;
  **`dot x,y`** a junction.

## Guidelines

- **Place boxes relative to each other,** with `at` for the first of a
  group, so moving one moves its neighbours.
- **A box's title is the part, its other lines the chips** ("RF copy
  A", "4 × SRAM").
- **Buses as buses:** a bus that many parts share is a `bus`, tapped by
  short wires, not a web of wires.
- **Notes under the figure:** a sentence of explanation goes in the
  text after it, not in the diagram.
- **Width:** a figure wider than the column it's in is scaled down,
  text and all: about 60 units (600 pixels) on the site, 88 on GitHub.
  Keep a diagram narrow, or split it.
- **Check the drawing:** nothing stops a wire from crossing a box or two
  labels from meeting. Move boxes, or route with `via`.
