# Editor: notes

## What it is

A text editor on the window manager: two windows (`console.c`, an
original C file in C's colours, and `notes.txt`), each 8 × 16 cells of
`font_cell`. Typing, Backspace, Delete, Enter (indented like the line
above), Tab, arrows, Home/End, Ctrl+Home/End, PgUp/PgDn, Ctrl+Up/Down
(scroll a line), Shift+moves and mouse drags select, Shift+click
extends, Ctrl+X/C/V (one clipboard for both windows), Ctrl+A, Ctrl+F
(find, Enter for the next), Ctrl+L (redraw), Ctrl+Q (quit and print the
measurements); a scroll bar (click or drag), a status line, a blinking
caret.

- `edit.c`, `edit.h`: the editing core, shared with `apps/fsedit`. The
  redisplay remembers what each row shows (a stamp: line, version,
  selection, comment state) and its cells; rows that only moved are moved
  by the front end, rows that changed are drawn from the first changed
  cell to the last; the status line is diffed the same way.
- `text.c`, `textcol.s`: cells with their own colours. 4 bits: a cell is
  a word, a glyph row's word from a 256-entry table per colour pair. 1
  and 2 bits: 4 or 2 cells per word from a *mask font* (the glyphs
  pre-arranged for each place of a cell in a word, 24 KB at 1 bit). The
  columns in C, or unrolled draft 2 assembly (asm, blk).
- `editor.c`: the WM front end. Moves are `gfx_blit` within the window's
  store, then damage. `measure.py`: the bench script and matrix.

## How it uses the video

Through the WM: any mode (`--poke wm_mode=N`), L0/F1/L1, C1 for the
pointer. The caret is an XOR bar in the store. No descriptors or palette
banks (the WM owns the lines). Block instructions only through the
library: COPY for scrolls and composition, FILL for blank row ends.

## Measurements

Milliseconds from the key's arrival (UART interrupt) to the end of the
frame's composition, demo script, M0 (`heron mini_gfx run apps/editor`):

| | type | Enter | scroll a line | page |
|---|---:|---:|---:|---:|
| c | 1.7 | 20.3 | 51.7 | 29.7 |
| blk | 1.6 | 12.3 | 25.7 | 19.4 |

An earlier full matrix (before the last optimisations; relative numbers
hold): scroll a line, blk: M0 26.4, M3 18.6, M4 15.1 ms; asm sits between
c and blk. **L0, F1 and L1 gave identical numbers in every mode**: the
text is table-driven and copies and fills are whole words. A typed
character draws ~25 cells (0.3 ms); the rest is the core's bookkeeping
and the WM's per-rectangle overhead (~0.5 ms).

## What worked well

- The stamp-and-diff redisplay: typing redraws only the rest of the line,
  scrolls copy rows. Typing stays under 2 ms in every mode and variant.
- Cells on 8-pixel boundaries: whole bytes or words, no shifts.

## What was hard

- A scroll in the WM copies the text area twice (store blit, then
  composition): 26 ms in M0 even with COPY, 52 ms in C; 1 bit is 4×
  fewer words, which is why M4/M6 scroll fastest.
- Per-call overheads dominated early versions: `gfx_fill` for a 2×16
  caret cost 7K ticks; `sprintf` divides; the C library's `memmove`
  copies overlapping regions a byte at a time. All worked around here.

## What would have helped

- **WM**: a scroll request (move on screen and in the store, compose only
  the new line) or windows without a store: would halve a scroll.
- **COPY at 2 cycles a word** (RFC 0041's copy register, 4 chips): −33%
  on scrolls and composition.
- **EXPAND with a destination stride** (a glyph column): cells would drop
  from 4 instructions a row to microcode; small gain, typing isn't bound
  by drawing.

## Issues found

- `build.py`'s object cache key ignores headers in the program's own
  folder: change `edit.h` and `fsedit.c` is reused with the old struct
  layout (corrupt screen). Workaround: delete `build/mini_gfx/obj/<file>.c-*`.
- The same cache isn't safe in parallel: two processes building one file
  share the `.tmp` name and one fails (`FileNotFoundError`). `measure.py`
  builds each variant first.
- Scripts cut lines at `#`, so `type` can't type `#`.
- A run that ends with `@done` reports `halted`, not `done`.
- `font_cells` at 1 and 2 bits goes to the C expansion kernel (asm/blk
  only do 8 pixels a word).

## Screenshots

`open` (both windows, C colours), `typing`, `select` (Shift+Up),
`paste`, `drag` (mouse selection), `find`, `find_next`, `scrolled`,
`bar` (scroll bar dragged), `notes_front` (the other window raised),
`notes` (typed in it).
