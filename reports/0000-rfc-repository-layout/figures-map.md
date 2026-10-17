# RFC 0000: address maps (map)

The regions of an address space, one above the other. How a figure goes
into a document is in [RFC 0000](../0000-rfc-repository-layout.md#figures).

```map
0x0000_0000  "regions 0–3" "CPU or memory cards"
0x4000_0000  "region 4" "the I/O processor's shared RAM"
0x7000_0000  registers "the card in region N's at 0x7N00_0000"
0x7700_0000  free
0x7F00_0000  "the I/O bus's window"
0x8000_0000  unused
0x1_0000_0000
group 0x0000_0000 0x7000_0000 memory
```

![Part of RFC 0037's map](figures-map/physical.svg)

## The language

A statement a line; `#` starts a comment and `"..."` is a string.

- **A region:** the address it starts at, then its lines of text: a
  title and smaller lines. It ends where the next begins.
- **The end:** the last line is an address alone, where the map ends.
- **`free`, `unused` and `reserved`** as a title hatch the region.
- **`group from to "label"`** draws a bracket beside the regions from
  `from` to `to`, which must be where regions start or end. Brackets
  that overlap stack outwards.
- **Settings:** `.order down` puts low addresses at the top (otherwise
  high addresses are), and `.width` sets the regions' width in pixels.

Regions are as high as their text, not as big as they are.

## Guidelines

- **For the shape of a space:** what's where, and what's left. The
  details of each region, such as a second view's addresses, stay in a
  table.
- **Addresses as the text writes them,** in groups of four digits.
