---
status: active
depends-on: [egret, graphics, c_compiler, v1_isa]
reports: [21]
---

# A graphical desktop for Egret

A demo more than a design study: a small Smalltalk-style desktop for
[Egret](../egret/README.md), running on the simulated draft 1b machine.
There are overlapping windows, a mouse and a keyboard, a Workspace where
you type Egret and run it, a Transcript, a class browser, and a few demos
(a clock, Life, the Mandelbrot set, Paint). The desktop is Egret source
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
heron egret_gui bench [--write]       # report 0021's tables (--write: the file, and its screenshots)
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
  code, selected. Errors go there too, and to the Transcript. Ctrl-A,
  Ctrl-C, Ctrl-X and Ctrl-V work, with a clipboard of the machine's own.
  Meta (Cmd) works as Ctrl.
- **In the Browser**, pick a class, then a method, to see its source;
  double-click the method to open it in a Workspace, change it, and run
  it again (Ctrl-A, Ctrl-D) to redefine it in the running system.
- **On the page**, the clock switch runs the machine at 3, 12 or 48 MHz,
  or as fast as the browser can (about 50–80 MHz). Restart starts from a
  snapshot of the desktop just booted; Cold boot starts from nothing and
  shows the machine compiling the desktop (10 s at 3 MHz). An infinite
  loop in a Workspace hangs the desktop: Restart is the way out.

## How it works

| File | What's in it |
|---|---|
| `lib/gui.eg` | Colours, windows, menus, the desktop and its event loop |
| `lib/widgets.eg` | A window of editable text |
| `lib/apps.eg` | Workspace, Transcript, Clock, Life, Mandelbrot, Paint, Browser, About |
| `lib/desktop.eg` | The menu, the first windows, and `DESK.run` |
| `src/gwm.c` | The window manager: the graphics study's `wm.c`, with updates for Egret to paint instead of paint functions |
| `src/gui_prims.c` | Egret's primitives for the screen, events, windows, drawing, fonts, the Workspace's compiler and the Browser |
| `src/gui.h`, `src/gui_map.h` | The devices, and Egret's memory map for this build |
| `src/rt_v1b.s` | Egret's start code, with a timer interrupt and `gui_wait` |
| `build.py` | The image: Egret's VM, the graphics library and kernels, the fonts, `src/` |
| `run.py` | A session without a browser: input events by the clock, the screen as PNG |
| `snapshot.py` | The machine's state as bytes, for the browser to start from |
| `web/` | The browser version: `index.html`, `app.js`, and the simulator crate for WebAssembly |
| `bench.py` | What things cost on the machine: report 0021's tables and screenshots |
| `web.py`, `cli.py` | Putting the site together; the command line |

**The devices** (`studies/v1_isa/isa/src/display.rs`). The frame buffer
is 512 KB of VRAM at `0x01000000`, outside the 1 MB of RAM, laid out as
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

**Running code from the Workspace.** `gui_compile` compiles each
top-level statement into a method of Object with a name of its own
(`__doit1`, ...), and the desktop sends them, inside a `try`. So the code
runs in the ordinary interpreter, never nested in C, and an error in it
is an Egret error the desktop catches. Classes and methods take effect as
they're compiled. Each statement's method stays in the permanent space.

**Memory.** The VM, the graphics library and the fonts come to 310 KB,
past where Egret's code space ended (0x30000), so `src/gui_map.h` moves
Egret's map up: console input at 0x50000, 192 KB of permanent space, two
152 KB semispaces, 72 KB of C stack. The font cache lives in VRAM past
the screen (`gui_alloc`), and so does what's under a menu. The build also
shrinks the scan converter's edge tables from 52 KB to 13 and 26 KB (a
text substitution on the graphics study's sources at build time), and
links the C library in the middle of the code, which is past the 64 KB
a 16-bit relative call reaches.

**The browser** (`web/`). The simulator crate compiles for
`wasm32-unknown-unknown` with no changes. `web/src/lib.rs` wraps it in
plain exported functions, without wasm-bindgen. `app.js` loads a
snapshot, runs the machine in slices of at most 12 ms a frame, copies
the screen to a canvas when VRAM has changed, and turns the browser's
keys, buttons and wheel into events. The snapshots are written by
`snapshot.py`: `cold` is the machine before its first instruction, with
the desktop's source as console input, and `booted` is the same machine
once the desktop is up.

## Before a PR

This was built to be shown, not merged. Before it goes to `main`, these
changes outside the study need doing properly or taking out:

- `studies/v1_isa/isa/src/display.rs` and `machine.rs`: the display,
  keyboard and mouse are wired into every draft 1 machine, and VRAM is
  allocated for each. They should be optional (a feature, or a device
  the machine is given), or be replaced by whatever RFC 0016 becomes.
- `heron/bindings/src/py_v1.rs`: the display's getters and setters,
  `run_until`, and setters for the timer and the cycle count (for
  snapshots).
- `studies/egret/vm`: `EGRET_GUI` hooks in `egret.h` (the memory map from
  `gui_map.h`, 256 primitives), `prims.c` (a second table of primitives;
  `PrimDef` moved to `egret.h`) and `main.c` (output copied to the
  Transcript). Egret's own builds don't define it, and its tests pass.
- `Cargo.toml`: the new crate, `studies/egret_gui/web`, is a workspace
  member, so `cargo test` and clippy build it (as a native library).
- The graphics study's sources are patched at build time
  (`build.py`'s `SHRINK`): its `MAXE` and glyph edge table could take a
  define instead.
