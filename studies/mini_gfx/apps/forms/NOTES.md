# Workshop stores: a forms application

## What it is

A parts inventory on the window manager, with 200 made-up records from
a deterministic generator (`data.c`). It has:

- **A list window**: a table with a header that sorts on a click (click
  again to reverse), zebra stripes, low stock in the accent colour, a
  scroll bar (drag the thumb or click a page), keyboard navigation, and
  a double click to open a record.
- **A search box** that filters the list as you type.
- **A record window** with text, number and money fields (caret, editing,
  validation with an error message), a drop-down with its own popup list
  (mouse and keyboard), radio buttons, check boxes, and the buttons New,
  Save, Delete and Revert. Tab and Shift+Tab move between fields, Enter
  saves and Esc reverts.
- **A modal confirmation dialog** before a delete.
- **A chart window**: stock value by category, as colours at 4 bits and
  patterns at 1 and 2.

At 640 x 480 the list shows 7 columns and 12 rows. At 1024 x 768 it
shows 11 columns and 26 rows, with the record and chart windows beside
it.

The widgets are kept apart from the application, so they can be folded
into `wm/`. `fw.c` and `fw.h` have the text strips, the table, the form,
the popup, the dialog and the bars. `measure.py` runs the measurement
tables.

To run it:

```
heron mini_gfx run apps/forms [--variant c|asm|blk]          # 640 x 480: M0, M3, M4
heron mini_gfx run apps/forms --poke mode=5 --layout L1 --script studies/mini_gfx/apps/forms/xga.script
```

The pokes: `mode`, `options` (the WM's), `row_cache`, `sel_banks`,
`list_font` (0 strips, 1 `font_draw`, 2 cells), `fw_put`, `filter_mode`,
`sort_mode`, `fw_field_full`, `trace`, and `bench` (each piece timed on
its own).

## How it uses the video

- **Modes:** M0, M3 and M4 at 640 x 480; M5 and M6 at 1024 x 768. The
  theme copes with M6: frames instead of bevels, an inverted selection,
  no stripes.
- **Layouts:** L0, L1, and F1 (`WM_F1`). `WM_SNAP` is on by default.
- **Descriptors:** the window manager's table 0. With `sel_banks=1`
  (M0), the selected row is drawn by the palette banks:
  - the rows use colours 12-14, which nothing else uses;
  - bank 1 maps them to the selection's colours;
  - a selection move rewrites 32 descriptors' bank bits.
- **Cursor:** C1 for the pointer. The text caret is a software XOR line.
- **Beam (P1):** used for every timing.
- **Bandwidth:** B0. There were no steals and no underruns in any run,
  M5 included.
- **Block instructions:** through the library's blk variant.

## Implementations and measurements

Each figure is the average total of an operation, from the start of its
handling to the end of the frame's composition, in ms. A frame is
16.7 ms. These are the default settings: row cache on, prefiltered
search, merge sort.

| | | type field | search key | select | scroll row | scroll page | sort | open record | save | full redraw |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M0 L0 | c | 3.9 | 40.5 | 7.6 | 39.0 | 62.0 | 96.2 | 115.3 | 73.9 | 229.7 |
| M0 L0 | asm | 3.0 | 32.4 | 6.7 | 30.1 | 54.8 | 82.3 | 78.8 | 64.4 | 166.7 |
| M0 L0 | blk | 2.9 | 23.9 | 4.3 | 20.3 | 41.0 | 66.7 | 66.5 | 53.3 | 137.5 |
| M0 L1 | blk | 2.9 | 23.9 | 4.3 | 20.3 | 41.0 | 66.7 | 66.5 | 53.3 | 137.5 |
| M3 L0 (= F1) | blk | 3.3 | 25.1 | 4.7 | 15.9 | 42.0 | 73.9 | 78.1 | 57.3 | 157.2 |
| M3 L1 | c | 3.6 | 28.4 | 4.4 | 23.9 | 43.4 | 74.4 | 92.3 | 58.4 | 178.9 |
| M3 L1 | blk | 3.3 | 22.5 | 3.8 | 14.9 | 37.2 | 67.9 | 77.2 | 53.1 | 151.3 |
| M5 L1 (26 rows) | blk | 3.7 | 49.3 | 5.5 | 35.2 | 115.1 | 148.3 | 76.9 | 165.4 | 218.1 |
| M5 F1 | blk | 3.7 | 56.7 | 7.1 | 36.8 | 131.5 | 169.8 | 77.9 | 179.9 | 238.2 |
| M6 L1 | blk | 3.3 | 34.4 | 3.0 | 24.8 | 88.3 | 111.5 | 63.1 | 130.8 | 153.4 |
| M6 L0 | blk | 4.0 | 52.5 | 6.6 | 28.6 | 126.5 | 166.9 | 77.4 | 177.5 | 216.0 |

**Where the time goes.** These are the pieces of one list row (584
pixels, 60 glyphs) in M0, timed on their own with `bench=1`:

| Piece | c | asm | blk |
|---|---:|---:|---:|
| Library `font_draw`, a glyph at a time | 16.2 | 9.9 | 9.7 |
| Strip: cells' text (`sprintf`) | 0.5 | 0.5 | 0.5 |
| Strip: glyphs composed, 1 bit | 1.6 | 1.6 | 1.6 |
| Strip: one expansion, library | 17.1 | 2.2 | 1.4 |
| Strip: one expansion, my aligned C | 2.3 | | |
| Whole row (`table_row`) | 4.4 | 4.4 | 3.5 |
| 11 rows scrolled in the store | 13.1 | 9.1 | 5.7 |
| 12 rows composed to the screen | 14.3 | 9.9 | 6.3 |
| The same, not word-aligned (no `WM_SNAP`) | 216 | 29 | 17 |

At 1 and 2 bits, the library expands a row in C at 90-110 cycles a word
(its asm and blk kernels only do 4 bits). My aligned expansion is much
faster:

| Mode | Library | Mine |
|---|---:|---:|
| M3 | 10.0 ms | 1.3 ms |
| M6 L1 | 6.2 ms | 0.86 ms |
| M5 L1, whole row | 17.5 ms | 5.6 ms |

Other changes, measured one at a time (M0 blk unless noted):

| Change | Before | After |
|---|---:|---:|
| A key in a field, whole field redrawn → only from the edit on (c) | 16 ms | 1.2-1.6 ms |
| Selection move, rows redrawn → row cache | 8.3 ms | 4.3 ms |
| Selection move, row cache → palette bank | 4.3 ms | 0.19 ms |
| Search key, no cache → row cache | 33 ms | 23 ms |
| Filter, full scan of 200 records (c) → character-mask prefilter | 12.5 ms | 1.9 ms |
| Sort, C library `qsort` → keyed merge sort | 43-55 ms | 11-19 ms |

## What worked well

- One expansion a line of text, background and all, from glyphs shifted
  ahead of time. It is 3-4x cheaper than `font_draw` per glyph.
- Drawing only what changed. Typing is under a frame in every variant
  and mode.
- The backing stores made overlapping windows, popups and dialogs easy.
- M6 (1 bit, L1) is the cheapest mode for text: its selection moves are
  the fastest (3.0 ms).
- M5 shows twice the data, but pages cost about 2.5x.
- L1 is free and as good as or better than L0 and F1 everywhere here.
  F1 bought nothing.
- The palette-bank selection is a real use of D0 (D1 can't do it).

## What was hard or didn't work

- Scrolling costs two copies, one in the store and one in the
  composition (6-14 ms each for the list).
- The descriptors can't scroll a window narrower than the screen.
- The palette-bank trick needs spare colour indices, so it only works at
  4 bits.
- The window manager hands a window every queued event before it
  composes. A slow drag handled 12 mouse moves in one 585 ms frame with
  no screen update. My handlers now only record what's wanted, and the
  tick does the work once a frame.
- The window manager has no modality, no keyboard for menus, and no
  focus-change callback; I worked around all three in `fw.c`.

## What would help

**Hardware and microcode:**

- **X1's EXPAND at 1 and 2 bits.** My aligned C loop is about 12 cycles
  a word; a microcoded one would be about 3, making rows another ~2x
  faster in M3, M5 and M6.
- **RFC 0041's copy register (4 chips).** It would cut every
  composition and scroll by a third.
- **A second start address from a split column in the descriptor.** It
  would let a window narrower than the screen scroll by descriptors,
  which would remove both of a scroll's copies.
- **A palette bank per column, or a split column.** It would extend the
  free selection highlight to 2 bits.
- **No extra cursor for the caret.** A caret blink costs 0.3 ms.
- **A text mode.** It would make rows nearly free, but it doesn't mix
  with windows; a per-line text mode in the descriptor bits 31-24 would
  be the way to try it.

**Library and window manager:** fold in from `fw.c`:

- text strips;
- the aligned 1-, 2- and 4-bit expansion;
- the table, form, popup and modal dialog;
- the row cache.

The window manager should also:

- coalesce mouse moves, or call the ticks between events;
- have modal windows and keyboard-driven menus;
- let an unobscured window draw straight to the screen, which saves the
  composition copy, about 30% of a scroll.

## Issues found

- **`build.py`'s object cache doesn't hash the program's own headers.**
  It only hashes `rt/`, `gfx/` and `wm/`, so a change to only `data.h`
  rebuilds nothing, and struct layouts go stale. Repro: add a field to
  `Part` in `data.h` and run; `data.o` and `forms.o` are reused.
- **`wm.frame_work` is declared but never set.**
- **The window manager drains the event queue before composing** (above):
  input never coalesces once the application lags behind.
- **The library's asm and blk expansion kernels only handle 8 pixels a
  word.** At 1 and 2 bits, every text call goes through the C kernel,
  which calls `gfx_xmask` for every word.
- **The compiler multiplies by non-power-of-two constants with `MULS`.**
  `sizeof(Part)` = 192 and a strip pitch of 136 each cost a microcoded
  multiply on every access. Padding `Part` to 256 bytes made the filter
  20% faster.
- **The C library's `qsort` is slow:** 55 ms for 200 ints (byte swaps, a
  comparison through a pointer).
- **The VGA script's scroll-bar drag misses in M4.** `WM_SNAP` moves the
  window to x = 0 at 32 pixels a word.

## Screenshots

These are the script's shots:

- `list`: the start.
- `search`: "disc" filters 12 of 200.
- `sorted`: by quantity, descending.
- `record`: opened by a double click.
- `error`: a bad quantity, with its message.
- `saved`: the edited record is saved and the list is sorted again.
- `popup`: the category drop-down.
- `new`: a new part, saved.
- `dialog`: the delete confirmation.
- `deleted`: after the delete.
- `chart`: the bar chart.
- `scrollbar`: after a thumb drag and page clicks.
- `search2`: "hex bolt".

`xga.script` takes the same shots at 1024 x 768.
