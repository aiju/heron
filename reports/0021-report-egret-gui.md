---
number: 21
type: report
title: A graphical desktop for Egret on draft 1b
status: draft
date: 2026-10-14
context:
  studies: [egret_gui, egret, graphics, c_compiler, v1_isa]
  commit: c953ae7
---

# Report 0021: A graphical desktop for Egret on draft 1b

A demo more than a measurement: a small Smalltalk-style desktop for
[Egret](0017-report-egret.md) on the simulated draft 1b machine, with
overlapping windows, a mouse, a keyboard, a Workspace to run Egret in, a
Transcript, a class browser, and a few demos. The desktop is 1,800 lines
of Egret that the machine compiles as it boots. The pixels are the
[graphics study](0019-report-graphics.md)'s library and kernels. It runs
in a browser as WebAssembly, at the machine's 3 MHz or faster
([studies/egret_gui](../studies/egret_gui/README.md)). The study's
generated tables are in
[performance.md](0021-report-egret-gui/performance.md), written by
`heron egret_gui bench --write`.

![The desktop at 8 bits per pixel](0021-report-egret-gui/desktop-8.png)

The desktop at 8 bits per pixel: the Workspace after three print-its and
a do-it, the Transcript with what was printed, the Mandelbrot set, drawn
by Egret a slice at a time while the desktop went on, and the clock.

## Short version

- **It works, and at 3 MHz it's usable.** A keystroke in the Workspace
  takes 17 ms of the machine's time, printing `3 + 4 * 5` 57 ms (compiling
  it on the machine included), opening the menu 250 ms, dragging a window
  300 ms, and opening the Browser 0.6 s. Booting takes 13 s: 1.6 s for
  the prelude, 10.6 s to compile the desktop, 1.2 s to paint it. Life runs
  at 3 generations a second; the Mandelbrot set takes 107 s. At 4× (12
  MHz) it all feels quick.
- **Most of the time is Egret's, not the drawing's.** For small things,
  the interpreter takes half the cycles and drawing a tenth. Only the big
  repaints (opening the Browser: 41%) are mostly drawing, and that's text.
  An idle desktop costs 6% of the machine: its event loop's own work each
  tick, after cutting it from 11%.
- **The machine needed four things it didn't have.** A frame buffer, input
  as a queue of events, somewhere to sleep until the next tick (`HALT`
  and the timer, which it had), and memory: the VM, the graphics library
  and the fonts take 310 KB of the 1 MB before Egret has an object, and
  Egret's heap shrank from two 256 KB semispaces to two 152 KB ones.
- **The code passed 64 KB,** as far as a 16-bit relative call reaches, and
  the C library at the end of it went out of reach. Linking the library
  in the middle fixed it here; a bigger program needs long calls or a
  smarter linker.
- **The simulator runs in a browser unchanged.** The Rust crate compiles to
  WebAssembly as it is, and runs at 55–65 MHz in Chromium (about 20 times
  the real machine), against 120–150 MHz natively.

## What was built

| Part | What it is | Size |
|---|---|---:|
| The devices | A frame buffer in 512 KB of VRAM outside RAM (640 × 480 at 1–8 bits per pixel, a 256-colour palette), a queue of input events, the mouse's position and buttons, the time of day, and the pointer's shape | 190 lines of Rust |
| The window manager | The graphics study's `wm.c`, reworked so that whatever of a window comes into view is erased and handed to Egret as an update, as on the classic Mac OS | 590 lines of C |
| Egret's primitives | Events, windows, drawing, fonts, the Workspace's compiler, the Browser's view of classes and source | 860 lines of C |
| The desktop | Windows, menus, the event loop, a text editor, and the applications: Workspace, Transcript, Browser, Clock, Life, Mandelbrot, Paint, About | 1,800 lines of Egret |
| The browser version | The simulator as WebAssembly, a page that runs it by the clock, snapshots of the machine | 320 lines of Rust, 260 of JavaScript |

- **C does the pixels and the stacking.** It draws frames, title bars and
  the desktop, moves windows by copying them, and clips everything Egret
  draws to what's visible of its window. C never calls Egret; Egret pulls
  events, updates among them.
- **Egret does everything with behaviour:** which window gets a click, the
  dragging, the menus, and the applications. A Workspace's line is
  compiled by the compiler on the machine into a method, which the
  desktop then sends, so the code runs in the ordinary interpreter and its
  errors are Egret errors the desktop catches.
- **The Browser makes it a live system.** It lists classes and methods
  and shows a method's source, found from the line the compiler recorded.
  A double click opens the method in a Workspace, where it can be changed
  and compiled again into the running desktop.
- **Idle costs the host nothing.** The desktop waits for the timer with
  `EI; HALT; DI`, and the simulator skips the cycles to the next tick.
  The browser counts cycles against the clock to run the machine at the
  speed chosen, and shows how busy it is.

![The Browser, with a method's source; Life behind](0021-report-egret-gui/browser.png)
![The desktop at 1 bit per pixel](0021-report-egret-gui/desktop-1.png)

## How fast it is

At 3 MHz in the reference configuration (D16-overlap), less what the idle
loop would have spent in the same time (all of them in
[performance.md](0021-report-egret-gui/performance.md#the-desktops-costs)):

| | at 3 MHz |
|---|---:|
| Type a character in the Workspace | 17 ms |
| Return, with the lines below it redrawn | 151 ms |
| Print it: `3 + 4 * 5` | 57 ms |
| Print it: `2 ** 100` | 69 ms |
| Open the desktop menu and close it | 246 ms |
| Drag a window by 100 pixels and move it | 297 ms |
| Close a window, and paint the desktop under it | 91 ms |
| Open the Browser | 587 ms |
| Pick a method in the Browser and show its source | 640 ms |
| Open About (TrueType at 30 pixels, rasterised the first time) | 2,746 ms |
| Boot: the prelude, the desktop's 1,800 lines, the first paint | 13.4 s |

- **The first second is the budget.** Typing keeps up with a fast typist;
  everything that redraws a window's worth of text takes a few hundred
  milliseconds, the speed of the graphics study's text (2,600 characters
  a second). A desktop of this kind on a 3 MHz Heron would feel like an
  early Macintosh, slower where it draws text in colour.
- **Long computations need to share.** Without processes, Life and the
  Mandelbrot set work a slice at a time from the timer's tick (the
  Mandelbrot set 13 ms of cycles a tick), so the desktop stays usable
  while they run. A loop that never returns in a Workspace hangs it.

## Where the cycles go

By the kind of function, everything from the event to the end of a short
wait after it, idle loop included:

| | an idle second | a keystroke | print it | open the Browser |
|---|---:|---:|---:|---:|
| Egret's interpreter (the assembly loop) | 69% | 54% | 35% | 40% |
| its slow path, in C | 0% | 10% | 6% | 4% |
| allocation and collection | 13% | 8% | 6% | 5% |
| drawing (the graphics library) | 0% | 12% | 28% | 41% |
| the window manager | 6% | 4% | 1% | 2% |
| Egret's primitives | 10% | 7% | 6% | 4% |
| the rest of the VM and the C library | 1% | 5% | 17% | 5% |

- **GUI code is made of small objects.** Points, rectangles and events are
  lists, and a list literal, string interpolation, `try` and `for` all go
  to the interpreter's slow path in C ([report 0017](0017-report-egret.md)
  measured the interpreter on programs that hardly use them). Faster paths
  for those in the VM would help GUI code more than any instruction.
- **The idle loop is software.** A tick with nothing to do took 5,600
  cycles at first: building the mouse's position and a hit test as lists,
  and working out the pointer's shape, every tick. Doing that only when
  the mouse has moved brought it to 3,100 cycles, 6% of the machine.
- **Print it is the compiler as much as the code.** A Workspace line goes
  through the same compiler as a program (17% of the cycles are the rest
  of the VM, mostly the compiler and, for `2 ** 100`, big integers), then
  the result is drawn into the line.

## What it says about the machine

- **Memory is the first limit.** The VM, the graphics library and kernels
  and the fonts are 310 KB, against 140 KB for Egret alone. Egret's map had
  to move up (console input at 0x50000 instead of 0x30000) and its
  semispaces to shrink to 152 KB. After booting, the desktop uses 118 KB
  of its 192 KB of permanent space and 37 KB of heap; every Workspace line
  done adds a method that's never collected. A desktop on the real
  machine wants 2 MB or more.
- **A separate frame buffer suits it,** as [RFC 0016](0016-rfc-video.md)
  recommends: the screen takes none of the RAM. Here the VRAM past the
  screen also holds the font cache and what's under a menu, which is a
  hack: real VRAM reads are slow ([RFC 0016, section 4.5](0016-rfc-video.md#45-how-the-cpu-reaches-it)).
- **The pointer is drawn by the browser,** like a hardware cursor, which
  RFC 0016 doesn't recommend. It saved the window manager from hiding a
  software cursor around everything it draws. That bookkeeping, not the
  drawing, is the case for a hardware cursor.
- **Input as a queue of events,** with the buttons' state readable too,
  was all the desktop needed. Since the machine can be busy for a while,
  a click is acted on where it happened, not where the mouse is when the
  machine gets to it; events carry their position, but not their time,
  so a double click is timed from when the first click was dealt with.
- **16-bit relative calls reach 64 KB.** The linker puts the C library
  after everything else, and once the code passed 64 KB, early callers of
  `memset` couldn't reach it. The workaround was to link the library in
  the middle; a real system would want the compiler to use 32-bit calls
  where needed, as it already does for far data.

## Caveats

- **It's a demo.** The display, keyboard and mouse, and Egret's hooks for
  this build, are hacks outside the study, listed in its
  [README](../studies/egret_gui/README.md#before-a-pr), to be done properly
  or taken out before anything is merged.
- **The times are the reference configuration's,** like the other draft 1
  reports; the draft 1b hardware's configuration (D32-separate) takes 5%
  more cycles to boot the desktop, and D32-wide 31% fewer.
- **Cycles spent waiting on VRAM aren't counted.** The simulator gives VRAM
  the same timing as RAM; on a real video card, reads would be slower.
