# Raster bars

## What it is

Seven coloured bars bobbing behind a block logo, made only by changing
the palette as the beam goes down, done four ways and each measured;
then the same under a CPU load that holds interrupts off, a *tear map*
of what the hardware would show, and palette fades done with the banks.
It starts with a probe: the line interrupt's latency on each path under
five kinds of CPU work, how fast the palette can be written, and how
precisely a write can be put inside a line by polling the beam.

```sh
heron mini_gfx run demos/rasterbars                 # about 800 frames
heron mini_gfx run demos/rasterbars --layout L1     # the same: palette effects don't care
```

`fx.c`/`fx.h` here are shared with the other three demos (a sine table,
taking over the interrupt vector, the CPU left over in a frame, block
letters from the sans font, a random number generator).

## How it uses the video

- **M0** (640 × 480 × 4), the picture in colours 1–15 and the bars in
  colour 0. Layout and bandwidth don't matter (identical in L1; no
  steals or underruns with B0).
- **D0 descriptors**: bit 23 for the line interrupts (A, B, D); the
  bank field for C, D and the fades; both tables with `TSEL` to switch
  a frame's banks atomically (C, fades).
- **Palette banks**: C uses 15 banks as 15 shades; D uses all 16 as a
  ring buffer of line palettes; the fades use them as 16 brightnesses.
- **P1, the beam**: every latency figure; the fast handler finds its
  line from it; the tear map records it at each palette write; a write
  inside a line waits for it.
- **The interrupt vector**: A's handler replaces the runtime's entry by
  patching the `JMP` at address 4 (`fx_vector`); anything not a line's
  interrupt goes on to the runtime's entry.
- No cursor, no block instructions but `FILL` and `COPY` as the
  *load* that holds interrupts off (`load.s`).

The techniques:

| | How | Interrupts |
|---|---|---|
| **A** | each line's descriptor has bit 23; `fast.s`'s handler, on its own vector, writes palette entry 0 from a list indexed by the beam's line | 480 a frame |
| **B** | the same through `rt_line_hook` in C | 480 a frame |
| **C** | three bars of five shades in banks 1–15; each frame the table not on the screen gets the bars' lines' banks (only the lines that change), then `TSEL` flips | none |
| **D** | line *y* is in bank *y* mod 16, for good; an interrupt every 8 lines (C, through the runtime) writes the 8 banks of the lines 8–15 further down, whose previous lines are done: any 2 colours (here the bars and the logo's face) on every line | 59 a frame |

## Implementations and measurements

Ticks are 19.86 ns; a frame is 840,000 ticks (16.68 ms); a character is
16 ticks (8 pixels). Picture line *y*'s descriptor is read, and its
interrupt raised, at character 85 of the line before; the line starts
**15 characters (240 ticks) later**.

**Latency**, in characters after the descriptor's read (60 interrupts a
frame, the last of three frames), by what the main program was doing:

| Main program | C: `rt_line_hook` starts | asm vector: handler starts | asm vector: palette written |
|---|---:|---:|---:|
| `HALT` (waiting) | 32 | 4 | **12** |
| short instructions | 32–33 | 4–5 | 12 |
| `DIVU` in a loop | 32–45 | 4–18 | 12–25 |
| `FILL` of 256 words | 32–144 | 5–115 | 12–125 |
| `COPY` of 256 words | 32–336 | 5–304 | 12–317 |

The C path's 32 characters are `rt/start.s`'s `SAVE r0-r7`, `rt_irq`'s
status read, `video_irq`'s acknowledge and beam read, and the calls.
Its palette write lands at about 45, **30 characters into the line**.

**Writes per interrupt** (the list-walking handler `rb_probe_n`, CPU
halted): the last write is done at 14, 17, 24, 37 and 64 characters for
1, 2, 4, 8 and 16 writes: 3 characters (48 ticks) a write from a list.
Only one write fits the 15-character window.

**The palette's speed** (256 entries, interrupts off):

| How | Ticks an entry | In the blanking (20 chars) | In a line (100 chars) |
|---|---:|---:|---:|
| `MOV [r1 + 4k], r2`, unrolled, from a register | 17 | 18 | 94 |
| `MOV r0, [r2]+; MOV [r1]+, r0; DBNZ` | 49 | 6 | 32 |
| `LDM` 8 then `STM` 8 | 56 | 5 | 28 |
| C loop `PAL[k] = list[k]` | 57 | 5 | 28 |

A write inside a line, polling the beam (`poll_write`) for character 40:
it lands at characters 44–47 (the read after it included), so a split
within a line can be put to about 3 characters (24 pixels) with 24
pixels of jitter, at the cost of the CPU polling. The simulator can't
show it (below).

**What each technique costs**, the CPU used in a frame (from the idle
work left, `fx_idle`, the last 8 frames of each part), split into the
C that computes the next frame's colours (timed alone) and the rest
(the interrupts):

| Technique | Colours a line | Used | Computing (C) | Interrupts | Per interrupt |
|---|---|---:|---:|---:|---:|
| A asm vector, every line | 1, any | 23.2% | 7.9% | 15.3% | ~270 ticks |
| B C hook, every line | 1, any (late) | 59.5% | 7.8% | 51.7% | ~900 ticks |
| C banks, no interrupts | 1 of 16 a frame | 4.9% | 4.8% | 0.1% | – |
| D banks + C every 8 lines | 2, any | 25.8% | 13.6% | 12.2% | ~1,700 ticks (16 writes) |
| Fade, banks (480 descriptors, C) | | 10.0% | 9.9% | | |
| Fade, 15 palette writes (C, `fx_dim`'s divides) | | 3.4% | 3.1% | | |

**The tear map** (one frame's palette writes recorded with the beam; see
*Screenshots*):

| | Where the writes landed, from their line's start | Lines wrong at their start (the simulator) | Lines with pixels of another line's colour (the hardware) | Pixels |
|---|---|---:|---:|---:|
| A, CPU idle | −3 to −1 characters | 0 | 0 | 0% |
| B, C hook | +30 to +32 | 480 | 480 | 37.6% |
| A, CPU COPYing | −82 to +2 | 316 | 316 | 65.8% |
| D, CPU COPYing | −5,552 to −411 | 0 | 0 | 0% |

## What worked well

- **Banks and interrupts together (D)** are the technique: the banks are
  a buffer of line palettes, so the interrupt's deadline goes from 15
  characters to 8 lines and 15 characters (815), the C hook is plenty
  fast, and a CPU stuck in a `COPY` for three lines does no harm (0
  wrong lines against A's 316). It costs less than A (12% against
  15%) for twice the colours a line, and any colour.
- **Banks alone (C)** are nearly free (0.1% beyond writing ~240
  descriptors in C) when 16 colours a frame for colour 0 will do: three
  bars of five shades.
- **Fades with banks**: 16 brightnesses of the 16 colours in the 16
  banks, and the descriptors pick one per line, so a curtain with a soft
  edge, or a fade by halves of the screen, costs no palette writes at
  all.
- **The beam (P1)** made all of this measurable, and it makes a
  handler robust: the fast handler indexes its colour by the beam's line,
  so a late interrupt costs only the lines it misses instead of shifting
  every line after it (counting interrupts did that).
- **A vector of one's own**: 4 characters from the descriptor's read to
  the first instruction, 12 to the palette write.

## What was hard or didn't work

- **The 15-character window.** From the descriptor's read to the line's
  start is 240 ticks. The runtime's C path takes 32 characters to reach
  the hook, so per-line palette changes from C always land in the next
  line's picture; only assembly on its own vector makes it, by 3
  characters, with one write, and only while the CPU runs short
  instructions.
- **The block instructions hold interrupts off**: a 256-word `COPY` for
  up to 317 characters (more than three lines), a `FILL` for up to 125,
  a divide for 13. The study's blk kernels work in chunks of 256 words;
  chunks of 32 would keep the latency under ~40 characters.
- **One flag for the frame and the lines** (RFC 0042, 8): a late line
  handler's acknowledge swallowed the frame's interrupt and the main
  program waited for a frame for ever (see *Issues found*).
- **The simulator can't tear**: it renders a line whole as it starts, so
  the C hook's lateness shows as every line taking the colour a line
  late, which looks right. The tear map works out what the hardware
  would show from the recorded write times.
- **C per line is slow**: 200–300 ticks a line for anything with a
  multiply, a divide or a `%` in it (`fx_dim`'s `/ 15` alone makes the
  15-colour fade cost 3%). Tables fix it.
- **The bank field sits right under bit 23**: a bank of 16 sets the
  line's interrupt (I did it in wobble; the runtime then counts lines as
  frames).

## What would have helped

- **The line's interrupt earlier, or at a programmable character** (the
  descriptor's free bits 30–24: "interrupt at character *n* of the line
  before"). The C hook needs about 47 characters before the line to
  make its write; an interrupt at character ~50 of the line before
  would let C do per-line palette changes and give assembly room for
  ~12 writes. Cost: a latch for the bits and a comparator with the
  character counter, about 2 chips.
- **Separate status bits (and acknowledges) for the frame's interrupt
  and the lines'**: no swallowed frames, no beam read to tell them
  apart (and no `line_irqs` bookkeeping in the runtime). About a GAL
  term and a flip-flop: 0–1 chips.
- **More palette banks.** The palette SRAMs are 32K × 8 and use 8
  address bits; 6 of the descriptor's free bits as more bank bits would
  give M0 1,024 banks of 16: a bank per line, twice over, so D's effect
  (16 colours a line, any of them) with no interrupts at all, written
  whenever in the frame before: ~16K ticks (2%) for 2 colours a line
  from registers, against D's 12%. Cost: a wider bank latch and a
  bigger palette window in the I/O space, 1–2 chips.
- **A microcode copper** (a list of register writes at beam positions):
  a palette write for ~2 cycles (~14 ticks) instead of an interrupt's
  ~270 (asm) or ~900 (C): A's 15% would be under 1%, the writes exact
  to the character, and splits within a line possible. It would have to
  preempt block instructions, or be as late as the interrupts.
- **Palette changes within a line** in hardware (a split column): only
  wanted for effects the bars don't need; polling the beam does it to
  3 characters at the cost of the CPU (on the hardware, not the
  simulator).

## Issues found

1. **One flag and one acknowledge for the frame and the lines swallow
   the frame's interrupt** (RFC 0042, 8; the simulator does as
   specified). A line's interrupt taken late (a `COPY` under way) is
   still pending when the frame ends and sets the flag again; the
   handler's acknowledge clears both, and the frame is never seen. It is
   a race: the window is from the handler's beam check to its
   acknowledge. *Repro:* `heron mini_gfx run demos/rasterbars -D
   SWALLOW=4` runs `rb_noguard` (four writes a line from a list, no
   check after the acknowledge) under a `COPY` loop and prints "120
   frames of the video, 115 seen by the runtime"; with 1 or 16 writes
   this run's phase loses none. During development a longer handler
   phase-locked with the `COPY` loop and lost every frame: the main
   program waited for ever. The fix in `fast.s`: acknowledge, then read
   the beam; past the frame's end, do the frame's work too (`rb_frame`).
   `rt/video.c`'s `video_irq` acknowledges before it reads the beam, so
   the runtime is safe, but drops the line's hook then.
2. **`rt_line_hook(y)` gets the wrong line under block instructions.**
   `video_irq` works *y* out from the beam, assuming the handler starts
   before character 85 of the line after the interrupt's; a `FILL` or
   `COPY` makes it one line too far, and merged interrupts lose lines.
   *Repro:* D using the hook's *y* (instead of counting its interrupts,
   `hook_d`) wrote banks still on the screen: 40 wrong lines in the tear
   map's "D COPYing". Counting works when the interrupts are sparse
   enough not to merge.
3. **The runtime counts any video interrupt as the frame's while
   `line_irqs` is 0**: setting bit 23 directly (rather than with
   `video_line_irq`), or a bank number of 16 in `video_desc` (which
   doesn't mask it), makes `rt_frames` run ahead. *Repro:* in `part_a`,
   set the bits (`lines(0, IRQ)`) before installing the vector: each
   part took about twice its frames; in wobble, banks of 16 gave
   "1,839,712 ticks a frame" for the descriptor stars. Suggested: mask
   the bank in `video_desc`, and have `video_irq` always look at the
   beam (one I/O read).
4. **`video_ticks()` with interrupts off** counts a frame whose
   interrupt is pending only while the beam is before line T; past
   line 44 it's a frame low and a span comes out negative. *Repro:*
   `timed_compute` without its first `fx_idle()` gave the fade "511215%
   of a frame".
5. **`@perf` and `@mark` names can't have spaces**: `run.py` splits the
   line and fails with a `ValueError` (`int('fast')`). Worth a line in
   `perf.h`.
6. **`LDM`/`STM` are no faster than single moves** for consecutive
   stores (56 ticks a word against 49 for a load-store loop; 17 for a
   store from a register), on the palette and in RAM alike.
7. **No runtime hook for one's own interrupt entry.** `fx_vector`
   patches the `JMP rel16` at address 4 (the code is in RAM, so the
   hardware could do it too) and finds the runtime's entry from it. An
   `rt_set_vector` or a pointer the entry jumps through would be
   cleaner.
8. **What the simulator models** (RFC 0042, 12) and what that means
   here: the descriptor read and the line interrupt at character 85
   of the line before, the beam exactly, the frame's interrupt at the
   picture's end, all as specified; but a line is rendered whole at its
   start from the palette and memory as they are then, so writes during
   a line's picture show from the next line: tearing, splits within a
   line and racing the beam can't be seen, only reconstructed (the tear
   map).

## Screenshots

`heron mini_gfx run demos/rasterbars` writes them to
`build/mini_gfx/shots/demos-rasterbars/`:

- `a_fast.png`: A, the asm vector: seven bars with white highlights over
  a blue sky, behind the logo.
- `b_chook.png`: B, the C hook: looks the same in the simulator (each
  line has the colour of the line above); the tear map shows the
  hardware's view.
- `c_banks.png`: C, banks only: three bars of five shades (15 banks),
  black between.
- `d_rotate.png`: D, banks in turn with an interrupt every 8 lines: the
  bars, and a rainbow running down the logo's face (a second colour a
  line).
- `a_copy.png`: A while the CPU `COPY`s: lines whose interrupts were held
  off keep stale colours (on the hardware, torn as well).
- `d_copy.png`: D under the same load: unharmed.
- `tears.png`: the tear map, four panels (a line's 80 characters across,
  480 lines down): green where a line showed its own colour, yellow its
  neighbour's, red one further off. A idle: all green. B: the first 30
  characters of every line yellow. A while `COPY`ing: streaks of
  yellow and red. D while `COPY`ing: all green.
- `fade_curtain.png`: a curtain of darkness coming down with a soft edge,
  each line's bank a brightness.
- `fade_out.png`: the whole picture at a low brightness, by banks.
