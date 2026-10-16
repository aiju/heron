---
status: active
depends-on: [egret, graphics, c_compiler, v1_isa, v2_isa]
reports: [21]
---

# A graphical desktop for Egret

A demo more than a design study: a small Smalltalk-style desktop for
[Egret](../egret/README.md), running on the simulated draft 1b machine,
and on draft 2's ([below](#on-draft-2)), built from the same sources.
There are overlapping windows, a mouse and a keyboard, a Workspace where
you type Egret and run it, a Transcript, a class browser, a few demos
(a clock, Life, the Mandelbrot set, Paint), and Gadgets, a playground of
parts with cartoon physics where a new class is a new part. The desktop is Egret source
that the machine compiles when it boots, like any other Egret program.
The pixels are the [graphics study](../graphics/README.md)'s library and
assembly kernels. It runs in a browser, as WebAssembly, at the machine's
own 3 MHz or faster. What it costs, and what it says about the machine:
[report 0021](../../reports/0021-report-egret-gui.md).

To make it work, the simulator got a display, a keyboard and a mouse,
and Egret's VM a few hooks. Both are hacks, outside this folder: see
[Before a PR](#before-a-pr). The display isn't the video card of
[RFC 0016](../../reports/0016-rfc-video.md), and isn't meant to be.

```sh
heron egret_gui serve                 # build the browser version and serve it on http://127.0.0.1:8000/
heron egret_gui web [-o DIR]          # the same as static files (default build/egret_gui/web/)
heron egret_gui shot --do "click 550 300; wait 1" -o desk.png   # without a browser: do things, save the screen
heron egret_gui shot --depth 0        # at 1 bit per pixel
heron egret_gui shot --isa v2         # on draft 2
heron egret_gui bench [--write]       # report 0021's tables, on 1b and draft 2 (--write: the file, and its screenshots)
heron test egret_gui                  # the unit tests
```

The browser version needs Rust's WebAssembly target:
`rustup target add wasm32-unknown-unknown`.

## Using it

- **Click the desktop** for the menu (Workspace, Transcript, Browser, the
  demos, About). Right-click a window for its own menu, if it has one.
- **Drag a title bar** to move a window, its bottom right corner to resize
  it. The box closes it, as does Ctrl-W.
- **In a Workspace**, put the cursor on a line (or select some lines) and
  press Ctrl-D to do it or Ctrl-P to print it: the value goes after the
  code, selected. With the cursor anywhere in a `class` or a block `def`,
  it does the whole of it. Errors go there too, and to the Transcript. Ctrl-A,
  Ctrl-C, Ctrl-X and Ctrl-V work, with a clipboard of the machine's own.
  Meta (Cmd) works as Ctrl.
- **In the Browser**, pick a class, then a method, to see its source.
  Double-click a class to open all of it in a Workspace, or a method for
  just that (or right-click for the same): change it, and with the cursor
  in it press Ctrl-D to redefine it in the running system. Objects that
  exist already use the new methods from their next send, and the open
  windows of a class a Workspace has run a `class` statement for are
  repainted at once (Clock keeps its colours in `face_color` and the
  like, to try it on). The Browser
  remembers what the Workspaces changed, so a class opened again shows
  your version. A class can't take new instance variables once it exists
  (that's Egret), and running a class with a different superclass leaves
  the old one.
- **Gadgets** (on the desktop's menu) is a table of parts, after The
  Incredible Machine: balls, bowling balls, bricks, ramps, a trampoline,
  a bucket, and a dropper that drops balls. Run and Reset (or the space
  bar) start it and put it back. Take a part from the bin and click the
  table to put one there; drag parts about, a ramp by its ends; throw a
  ball while it runs. Right-click a part for its menu: Edit opens its
  class in a Workspace. Every part is an object of a subclass of `Part`,
  and the bin shows every such class, so a new part is a new class:
  "New part..." on the menu starts one (`class Balloon < Ball` with a
  colour and gravity of -30). Change a method, Ctrl-D, and the parts on
  the table use it from the next frame; an error in one stops the table
  and says so in its status line.
- **On the page**, the clock switch runs the machine at 3, 12 or 48 MHz,
  or as fast as the browser can (about 50–80 MHz). The page programs the
  machine's timer for 60 ticks a second at each speed, as a faster Heron
  would be, and the desktop works in ticks: a faster machine does more in
  a tick, so Gadgets gets smoother rather than faster (flat out, the
  timer is set as for 48 MHz). Restart starts from a
  snapshot of the desktop just booted; Cold boot starts from nothing and
  shows the machine compiling the desktop (25 s at 3 MHz), under a splash. An infinite
  loop in a Workspace hangs the desktop: Restart is the way out.

## How it works

| File | What's in it |
|---|---|
| `lib/gui.eg` | Colours, windows, menus, the desktop and its event loop |
| `lib/widgets.eg` | A window of editable text, wrapped at spaces, with a scroll bar |
| `lib/apps.eg` | Workspace, Transcript, Clock, Life, Mandelbrot, Paint, Browser, About |
| `lib/gadgets.eg` | Gadgets: the parts, their physics, and the table |
| `lib/desktop.eg` | The menu, the first windows, and `DESK.run` |
| `src/gwm.c` | The window manager: the graphics study's `wm.c`, with updates for Egret to paint instead of paint functions |
| `src/gui_prims.c` | Egret's primitives for the screen, events, windows, drawing, fonts, the Workspace's compiler and the Browser |
| `src/splash.c` | The splash at a cold boot: a heron and an egret, 450 bytes of vector paths, and a progress bar |
| `src/gui.h`, `src/gui_map.h` | The devices, and Egret's memory map for this build |
| `src/rt_v1b.s`, `src/rt_v2.s` | Egret's start code for each draft, with a timer interrupt and `gui_wait` |
| `build.py` | The image: Egret's VM, the graphics library and kernels, the fonts, `src/` |
| `run.py` | A session without a browser: input events by the clock, the screen as PNG |
| `snapshot.py` | The machine's state as bytes, for the browser to start from |
| `display/` | The display, keyboard and mouse, for draft 1's and draft 2's simulators |
| `web/` | The browser version: `index.html`, `app.js`, and the simulators' crate for WebAssembly |
| `bench.py` | What things cost on the machine: report 0021's tables and screenshots |
| `web.py`, `cli.py` | Putting the site together; the command line |

**The devices** (`display/`, a crate both drafts' simulators put in
their machines). The frame buffer
is 1 MB of VRAM at `0x01000000`, outside the 1 MB of RAM, laid out as
the graphics study draws: 640 × 480 at 1, 2, 4 or 8 bits per pixel. The
I/O page gains a queue of input events (keys, buttons, the wheel), the
mouse's position and buttons, the mode, a 256-entry palette, the time of
day, and the shape of the pointer, which the browser draws, like a
hardware cursor. The timer, at 60 Hz, wakes the machine: when there's
nothing to do, the desktop runs `EI; HALT; DI`, and the simulator skips
the cycles to the next tick. So an idle machine costs the host nothing,
and the browser runs it by counting cycles against the clock.

**C and Egret.** C does the pixels and the window stacking: frames, title
bars, the desktop, moving windows by copying, and clipping to what's
visible. Egret does everything with behaviour. C never calls Egret.
Whatever of a window comes into view is erased and becomes the window's
pending update, as on the classic Mac OS. Egret gets it as an event and
paints it with the window's clip cut down to it. Egret can also draw in
a window at any time, in the window's coordinates, clipped to what shows.

**The splash.** Egret compiles a program whole before it runs any of
it, so the desktop can't draw anything while it compiles. So C does: the
VM reads the input's first line (`SCREEN_DEPTH = d`) before the prelude,
`gui_boot` draws a heron and an egret, and the lexer calls
`gui_compiling` to move a progress bar as it reads the lines. The birds are paths
of lines and cubic Béziers (`splash.c`), flattened and filled
anti-aliased with the graphics study's scan converter, the edges
blended with what's under them; at 1 bit a pixel the edges are black,
which draws them in outline. The desktop's own `gui_init` paints over
it.

**Running code from the Workspace.** `gui_compile` compiles each
top-level statement into a method of Object with a name of its own
(`__doit1`, ...), and the desktop sends them, inside a `try`. So the code
runs in the ordinary interpreter, never nested in C, and an error in it
is an Egret error the desktop catches. Classes and methods take effect as
they're compiled. Each statement's method stays in the permanent space.

**Gadgets' drawing.** A frame is every other tick. The table is drawn
offscreen in two layers in VRAM (`gui_layers`): one has the parts that
stay still, the other the picture, with the balls. A ball that moves is
rubbed out in the picture by copying from the still layer, drawn where
it is, and the rectangle copied to the screen, so the screen never shows
a ball half drawn and what was under it isn't drawn again. The window is
kept on a word boundary of the screen, as the Macintosh kept its
windows, so those copies don't shift. The still parts are found from a
ball through a grid of 64-pixel cells. A frame that's late is done with
the next and drawn once for both; later than that is slow motion.

**Memory.** The VM, the graphics library and the fonts come to 310 KB,
past where Egret's code space ended (0x30000), so `src/gui_map.h` moves
Egret's map up: 96 KB of console input at 0x50000 (the desktop's source
is 85 KB), 224 KB of permanent space (the desktop takes 173 KB, and
every class and line a Workspace runs adds to it), two 120 KB
semispaces, 72 KB of C stack. VRAM past the screen holds the font cache (`gui_alloc`), what's
under a menu, where the source's lines start, and Gadgets' layers. The
build also shrinks the scan converter's edge tables from 52 KB to 13 and
26 KB (a text substitution on the graphics study's sources at build
time). The code is past the 64 KB a 16-bit relative call reaches, so
`build.py` links it in an order where every call reaches: the graphics,
the GUI, the C library, the VM, the interpreter.

**The browser** (`web/`). The simulator crate compiles for
`wasm32-unknown-unknown` with no changes. `web/src/lib.rs` wraps it in
plain exported functions, without wasm-bindgen. `app.js` loads a
snapshot, runs the machine in slices of at most 12 ms a frame, copies
the screen to a canvas when VRAM has changed, and turns the browser's
keys, buttons and wheel into events. The snapshots are written by
`snapshot.py`: `cold` is the machine before its first instruction, with
the desktop's source as console input, and `booted` is the same machine
once the desktop is up.

## On draft 2

The same sources build for draft 2 ([RFC 0028](../../reports/0028-rfc-draft-2-isa.md)),
`build.image("v2")`, and run on draft 2's simulator (`v2_isa`), whose
plain machine has draft 1's memory map and I/O page: Egret's VM through
the C compiler's draft 2 backend, its interpreter loop in `interp_v2.s`,
this study's C, `src/rt_v2.s`, and the graphics study's kernels for draft
2 (`asm/v2/`, translated from 1b's for this; with only the C kernels,
filling and copying took two to five times as long). The page's
instruction-set switch loads either. Draft 2 takes 1 to 5% fewer cycles
for everything the bench measures (report 0021's
[performance.md](../../reports/0021-report-egret-gui/performance.md#on-draft-2)),
about what Egret's own programs show ([report 0032](../../reports/0032-report-lisp-egret-draft-2.md)):
the desktop's time is mostly Egret's interpreter.

## Before a PR

This was built to be shown, not merged. Before it goes to `main`, these
changes outside the study need doing properly or taking out:

- `studies/v1_isa/isa` and `studies/v2_isa/isa`: `machine.rs` and
  `lib.rs` wire the display, keyboard and mouse (this study's `display`
  crate) into every draft 1 and draft 2 machine (draft 2's plain one),
  and VRAM is allocated for each (1 MB, to give Gadgets its layers);
  draft 2's gains `run_until`. They should be optional (a feature, or a
  device the machine is given), or be replaced by whatever RFC 0016
  becomes.
- `heron/bindings/src/py_v1.rs` and `py_v2.rs`: the display's getters
  and setters, `run_until`, and setters for the timer and the cycle
  count (for snapshots).
- `studies/graphics`: the kernels for draft 2 (`asm/v2/`), and draft 2
  in its build, scene runner, command line and tests. That could go to
  `main` on its own, as the graphics study's.
- `studies/egret/vm`: `EGRET_GUI` hooks in `egret.h` (the memory map from
  `gui_map.h`, 256 primitives), `prims.c` (a second table of primitives;
  `PrimDef` moved to `egret.h`) and `main.c` (output copied to the
  Transcript; the input read before the prelude, its first line first,
  for the splash) and `lex.c` (the splash's progress bar told of the
  lines read). Egret's own builds don't define it, and its tests pass.
- `studies/egret/vm/parse.c`: a fix, not a hook, which could go to `main`
  on its own. A class statement that failed to compile left its class
  defined but empty, and since a class can't be given instance variables
  after its first statement, the corrected class then failed too. Now
  the failed statement's new class is forgotten.
- `Cargo.toml`: the new crates, `studies/egret_gui/display` and
  `studies/egret_gui/web`, are workspace members, so `cargo test` and
  clippy build them (the web one as a native library).
- The graphics study's sources are patched at build time
  (`build.py`'s `SHRINK`): its `MAXE` and glyph edge table could take a
  define instead.
