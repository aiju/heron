# RFC 0000: bit fields (bits)

Where the bits are: instruction encodings, registers, table entries. How
a figure goes into a document is in
[RFC 0000](../0000-rfc-repository-layout.md#figures).

```bits
word 16 "MOV rd, #u7"
  15-12 rd
  11-8  "u7 6–3"
  7-3   = 01110
  2-0   "u7 2–0"
  over 15-8 "register byte"
  over 7-0  "opcode byte"
```

![RFC 0028's MOV rd, #u7](figures-bits/mov-u7.svg)

## The language

A statement a line; `#` starts a comment, `"..."` is a string and
`key=value` an attribute.

- **`word N ["label"] [beside]`** starts a word of N bits, with its
  label on the left. `beside` puts it to the right of the word before,
  for bytes in memory order; otherwise words stack.
- **A field:** its bits and its name, under its word: `15-12 x`,
  `13 WAIT`. Ranges are `15-12`, `15–12` or `15..12`, high or low first.
  Every bit of a word is in exactly one field.
- **`= 0111`** after the bits (or after a name) gives constant bits, one
  digit a bit; `x` is a bit that doesn't matter.
- **`reserved`** as a name hatches the field.
- **`over 15-8 "label"`** and **`under ...`** draw a bracket over or
  under some bits: a byte, or a field split in two.
- **Settings:** `.bit N`, a bit's width in pixels (otherwise 16 to 40,
  so the widest row fits 576), and `.numbers all|edges|none`, which bit
  numbers are shown (`edges`: each field's first and last). A word's
  `numbers=` overrides it.

A name too long for its field goes under the word, on a leader.

## Guidelines

- **The figure shows positions; the text says what the fields mean.**
  A table of fields with their meanings stays a table.
- **Field names as the text writes them** (`rd`, `d8`, `a23–16`), so a
  reader can match them.
- **Bit 0 on the right,** and the word's width as the hardware sees it:
  a parcel as 16 bits, bytes in memory as two words `beside` each other.
- **Brackets for structure** the fields don't show: which byte is
  which, or the parts of a split field.
