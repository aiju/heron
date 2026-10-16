---
status: active
depends-on: [v1_isa, v2_isa, lisp, egret, fen]
reports: []
---

# The simulator on the website

Heron's machines in a browser: the studies' own instruction-level
simulators, built for WebAssembly, with a terminal, a screen, the
keyboard and the mouse, on the website's Apps page
(`apps/sim/`). The Lisp and Egret at their terminals, on draft 1b and
draft 2, and Fen with its shell on the serial console or its desktop on
the video card, at the machine's own clock or as fast as the browser
goes. A machine is a description, so a new one, or one whose study has
changed its memory map, is a few lines of Python here.

```sh
heron websim list                 # the machines
heron websim serve                # build the simulator and serve it on http://localhost:8000/
heron websim build [-o DIR]       # the same as static files (default build/websim/site/)
heron websim check [MACHINE...]   # boot each machine here and check it answers
heron websim run lisp-v2          # a machine's terminal in this one
heron site --apps --serve         # the whole website, with the simulator in it
heron test websim                 # the unit tests: every machine boots and answers
```

The browser's engine needs Rust's WebAssembly target:
`rustup target add wasm32-unknown-unknown`.

## The machines

| Machine | What it is |
|---|---|
| `lisp-v2`, `lisp-v1b` | The [Lisp](../lisp/README.md)'s runtime, interpreting what's typed |
| `lisp-v2-compiled`, `lisp-v1b-compiled` | The same from its saved image with the compiler, which compiles each form to machine code |
| `egret-v2`, `egret-v1b` | [Egret](../egret/README.md)'s VM at a prompt, its interpreter loop in assembly |
| `egret-v2-jit`, `egret-v1b-jit` | The same with its JIT |
| `fen-serial` | [Fen](../fen/README.md) with its shell on the serial console |
| `fen-desktop` | Fen's desktop, on the video card, the PS/2 keyboard and the mouse |

The page's address names a machine (`apps/sim/#fen-desktop`), so a
report can link to one.

## How it works

| File | What's in it |
|---|---|
| `engine/` | The engine, a plain Rust crate: a machine put together from a description (a board, its parameters, what to load where) and run in slices of time; the boards: `plain`, draft 1 or 2 with the I/O page's console, and `fen`, Fen's board |
| `wasm/` | The engine for the browser, as exported functions without wasm-bindgen; Python has it as `heron.native.websim` (heron/bindings) |
| `machines.py` | The machines: how each is made from its study's build, how the page shows it, and its check |
| `web/` | The page: `body.html`, `sim.js` (loading, running, the screen, the inspector, the menus), `term.js` (the terminal), `sim.css` |
| `web.py` | The static files: the engine, the page, `machines.json` and the blobs the machines load |
| `run.py`, `cli.py` | A machine run here, for the checks and `heron websim run`; the command line |

**A machine** is a description the page reads from `machines.json`: the
board, its parameters, what to load where (RAM images, a CompactFlash
card, text waiting on the console), and how to show it: a terminal (and
how it takes what's typed), a screen, help, examples, links. The bytes
it loads are in `blobs/`, gzipped and named by their contents, so
machines share what's the same. The page passes the parameters and the
loads to the engine as they are, so a board's new parameter needs no
change to the page.

**Adding a machine**: a function in `machines.py` that builds what it
loads with its study's own code (the Lisp's `machine.image`, Egret's
`build.heron`, Fen's `build.boot_image`) and an entry in `MACHINES`,
with a `check`. A study that changes its memory map or its build changes
its machine at the next build, and `heron test websim` boots every
machine and runs its check, so one that stops working is found. A new
kind of hardware is a board: a module of `engine/` that implements
`Board`, and a name for it in `Setup::start`.

**Time.** A board counts cycles at its clock (Fen's board 6 MHz; the
plain board 3 MHz for 1b, the 1b hardware's, and 6 MHz for draft 2, as
on Fen's board). Each frame, the page asks for the cycles its clock
makes in the time since the last, times the speed, and gives the engine
at most 12 ms of work, so a machine the browser can't keep up with runs
slower rather than freezing the page. A machine in HALT skips to its
next event, and one waiting for the terminal isn't run at all, so an
idle machine costs nothing. The speeds above real time make all of the
machine's time go faster, its timers and clock included.

**The terminal.** Fen's console server echoes and edits the line, so
its terminal sends each key as it's typed ("raw"). The Lisp and Egret
don't echo: their terminal edits the line itself, with a history, and
sends it at Return ("line").

**The keyboard and the mouse** (Fen's desktop). The machine's keyboard
is a US one: a character goes as the key that types it there, with Shift
as that needs, whatever the browser's layout, and other keys by where
they are. The page gives the mouse's position; the engine moves the
machine's PS/2 mouse there at most 200 counts a sample, 40 samples a
second as Fen asks for, since a mouse drops more than 255, and gives a
change of buttons a sample of its own, so a click isn't lost between
two.

**The inspector** (the More menu): the cycles, the instructions and the
speed, the registers with the symbol at the PC, and memory at an
address, a register or a symbol; Step runs one instruction while the
machine is paused.

## What the studies gained for it

- **A console that waits** (studies/v1_isa/isa and studies/v2_isa/isa):
  a plain machine's console input was all there from the start. With its
  line open (`Devices::open`), a read with nothing typed stops the
  instruction before it happens (`Stop::Wait`), and the machine runs it
  again once there's input; `close` is the end of the input. Every load
  reads before it changes a register, so nothing is undone. Off, as
  before, unless a frontend turns it on.
- **A device of the frontend's** (the same machines, and
  `infra/devices::Device`): a machine can be given one for the addresses
  it has nothing for, which were an error before and still are without
  one. Nothing here uses it yet; it's for the Egret desktop
  ([below](#the-egret-desktop)).
- **Egret at a terminal** (studies/egret/vm/main.c): the VM read its
  whole input before running any of it. Built with `EGRET_INTERACTIVE`
  it reads a statement at a time: it ends where its brackets, strings
  and blocks close and the line doesn't go on, or at an empty line. The
  normal builds don't define it and compile to the same image as
  before, so the study's measurements don't move.
- **The Lisp** needed nothing: its top level evaluates each form typed,
  and the machine's console text defines `%toplevel`, the hook the
  compiler uses, to print the value too. The terminal shows the prompt,
  since the runtime prints none, after an error included.

## The Egret desktop

The Egret desktop (studies/egret_gui, on its own branch) runs in a
browser already, with a page of its own. To be a machine here:

- **Its display as a device** the machine is given, rather than wired
  into every draft 1 and draft 2 machine (the first item of its "Before
  a PR"). The machines have that now: `device`, an
  `infra/devices::Device`, gets the I/O page's registers from +20 on and
  the addresses outside RAM (its VRAM at 0x0100_0000), and
  `device_as::<Display>()` gives the frontend its own type back. The
  display implements `Device`, and its wiring in each `machine.rs` goes.
- **A board** in `engine/`: the plain machine with the display as its
  device, its screen from VRAM and the palette, its keys and buttons as
  the display's events (it reads the mouse's position as it is, so the
  board takes the position straight, not the PS/2 mouse's steps), the
  time of day from the page, and its timer set from the clock it runs at,
  as its page does.
- **A machine** in `machines.py` from its `build.image`. A cold boot
  compiles the desktop, 25 s at 3 MHz: a second or two flat out, which
  the machine could ask the page for, or the description could load a
  snapshot of the booted machine, as its page does now.
