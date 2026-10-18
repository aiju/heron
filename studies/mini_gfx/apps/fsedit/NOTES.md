# Full-screen editor: notes

## What it is

The editor's core (`../editor/edit.c`, `text.c`, `textcol.s`) on the
whole screen without the WM: M6 by default (1024 × 768 × 1, 128 × 47
cells and a status line), or M5, M4, M3, M0 (`--poke mode=N`, `f1=0` for
L0's chunky pixels, `scroll_copy=1` to move rows by copying pixels).

## How it uses the video

- **Descriptors (D0):** each text row's 16 lines are a buffer of their
  own in bank 1 (47 rows + 4 spares); the table says which buffer each
  row shows. Rows that move (a scroll, Enter or a deleted line above
  them) are moved by rewriting descriptors, not pixels. The new table
  goes into the table not shown and **TSEL switches in the frame
  interrupt**, so a move is atomic (the simulator reads TSEL at every
  line's descriptor fetch). A buffer drawn while the old table still
  shows it at another row is copied first (copy-on-write). Only the
  table's rows that differ from what that table holds are rewritten.
- **Palette banks:** bank 1 tints the caret's line (pale yellow), bank 2
  makes the status line white on blue: colour in a 1-bit mode for free.
- **C1:** an I-beam pointer. The caret is an XOR bar.
- The editor's own memory of the rows also moves by pointers.

## Measurements

Milliseconds from the key's arrival to the screen's memory updated, demo
script, M6 F1:

| | type | Enter | scroll a line | page |
|---|---:|---:|---:|---:|
| c | 1.9 | 5.6 | 5.9 | 38.9 |
| blk | 1.8 | 5.3 | 5.3 | 35.5 |

A descriptor move is shown at the next frame's start (16.7 ms after the
key with scripted input). Its work is ~1 ms of table (752 descriptors),
the new row, and the core's bookkeeping. Copying instead moves ~23.5K
words: about 9 ms with COPY and 17–24 ms in C at RFC 0041's per-word
costs (estimate; `measure.py` has the `copy` configurations). A full
redraw is ~36 ms: a third glyphs, the rest fills and bookkeeping.

Writing cells: bytes at 1 bit cost ~4 instructions a cell row; the mask
font writes 4 cells per word (9 instructions per word row), and makes
L0's chunky 1 bit (bit c of each nibble) exactly as fast as F1 or L1.

## What worked well

- Descriptors as a row map: scroll and line insertion cost a table
  rewrite, not a screen copy; a fixed status line comes free.
- TSEL double-buffering plus copy-on-write: no tearing.
- Palette banks per row: highlight and status colours at 1 bit.

## What was hard

- 16 descriptors per text row, and keeping two tables in step.
- At 128 columns the core's per-row work (stamps, diffs, status) costs
  more than drawing a typed character.

## What would have helped

- **A repeat count in descriptor bits 31–24** (one descriptor for a text
  row's 16 lines): 47 writes instead of 752 per scroll (~1 ms → 0.07 ms).
  An answer to RFC 0042's open question 7.
- **A character generator** (font SRAM, a mux to the shifters; ~4–6
  chips, a descriptor bit per line for text): a page would be 6K byte
  stores (~1–2 ms) instead of ~36 ms. Typing and scrolling don't need it
  once descriptors exist.
- **X1's 1-bit EXPAND** would make the library's `font_cells` usable at 1
  bit (today: the C kernel); the mask font does it in software.
- **D1 instead of D0** would lose moving rows in the middle, the fixed
  status line and the per-row banks.

## Issues found

See `../editor/NOTES.md` (the build cache, scripts). RFC 0042 doesn't say
whether TSEL is latched per frame; switch it in the frame interrupt.

## Screenshots

`open`, `typing` (the caret's line tinted), `select`, `paste`, `drag`,
`find`, `scrolled`, `page`.
