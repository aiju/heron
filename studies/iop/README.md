---
status: active
depends-on: [v2_isa, v2_hw, fen]
reports: [27]
---

# The I/O processor

The I/O processor of [RFC 0027](../../reports/0027-rfc-io-coprocessor.md),
with the interrupts and rings of
[RFC 0040](../../reports/0040-rfc-interrupts.md), RFC 0027's "simulate
first" (16), steps 1-3: a model of the IOP at
microinstruction level, its microcode, and the Forth the microcode
interprets, on a system with a draft 2 CPU card that the IOP boots; then
the native jobs, the rings with their requests, windows and completions,
events and interrupts to the CPUs, I/O cards behind them, and the
measurements. An experiment: RFC 0027 isn't settled, and where this study
needed something it leaves open, it chose (below).

- **The simulator** (`sim/`, Rust, `heron.native.iop`): RFC 0027's core
  clocked by the bus clock, a microinstruction at a time, with its
  pipeline and delay slot, HOLD, the SRAM as registers and memory, the
  devices on T, the system bus master side with overlapped transfers, the
  slave side (the shared RAM, the doorbells, the I/O bus's window), the
  I/O bus with its timing table, and the card's devices: the console UART
  and the 82C54 from `infra/devices`, the image flash (two SST39SF040
  with their command sequences) and the ports. I/O cards for the slots: a
  CompactFlash card, two serial lines, and a GPIO card whose INT a test
  can raise.
- **The system:** the IOP's card and a CPU card on RFC 0037's map, the
  CPU being draft 2 at instruction level (`studies/v2_isa`) behind a card
  with RFC 0040's registers (control, board information, the request
  register, the message register, the timer) and RFC 0027's slave port
  and control store window. The CPU starts with RUN off; the IOP loads it
  and starts it.
- **The microcode** (`ucode/`, about 2,100 microinstructions): reset (the
  timing table, the SRAM's self test, the dictionary out of the image
  flash), the inner interpreter, 76 primitives and the task switch
  (`core.uc`, `prims.uc`); the native layer, which runs the tick, the
  doorbells and the native jobs; and the jobs themselves (`jobs.uc`): the
  movers (copies, fills and blocks between the bus, the shared RAM, the
  image flash and a device's register, in slices of 16 transfers), each
  client's ring job (requests fetched, checked against the client's
  windows, done or passed to the Forth, completed; the CF card's sectors
  among them), and posting events to their owners by the routing table.
- **The Forth** (`forth/`, about 8,700 cells): the console *is* its
  interpreter. A kernel with the compiler, catch and throw; the monitor
  (examine, deposit, dump anywhere on the system bus), blocks as native
  jobs, the image flash and `save`, tasks, booting the CPU; the system:
  the server for the requests the ring jobs pass on (setting up rings,
  windows, routes, the CPUs' rings of events, Forth from the kernel), the
  CF card's words for the console, and the serial lines with a line
  discipline.

```sh
heron iop console                # the Forth in this terminal (Ctrl-] quits)
heron iop run '2 3 + .' ': sq dup * ; 7 sq .'
heron iop boot                   # power up, boot-cpu: the CPU's hello through the window
heron iop boot --wcs             # with draft 2's control store, checked (v2_hw's microcode: a minute to build, then cached)
heron iop build                  # build/iop: ucode.bin, ucode.lst, flash.bin
heron iop ucode [--list]         # the microcode's size by primitive, and its listing
heron iop words                  # the dictionary
heron iop bench [--wcs]          # what RFC 0027 estimates, measured (below)
heron test iop                   # the unit tests
```

At the console, for example:

```forth
boot-cpu cpu-wait          \ load and start the CPU, wait for it to halt
$1000. e                   \ examine the CPU's RAM at 0x1000, through its slave port
$BEEF $1000. d             \ deposit
$0. 16 dump                \ the CPU's RAM from 0
0 $10000. 4096 bus-fill    \ halfwords on the bus, a native job; bus-move, sr>bus, bus>sr likewise
variable n : counter begin 1 n +! pause again ;
' counter 3 spawn          \ a second task, in bank 3
: hi ." hello" ; save      \ into the image flash, for the next cold start
```

The kernel on a CPU uses the IOP through its rings (layout.py has the
formats, `sw/ring.s` is an example): requests of 16 bytes into its
request ring in the shared RAM, the doorbell, and completions of 8 bytes
back into its completion ring in the CPU's own RAM, with an event if it
routed its completions' source to its CPU. Client 0's request ring, the
kernel's, is set up at the cold start; its completion ring, the CPUs'
rings of events and other clients' rings through the kernel's ring.

| File | What's in it |
|---|---|
| `sim/` | The simulator crate: `micro.rs` (the microinstruction, the 74181), `iop.rs` (the core, the T bus, the system bus master and slave sides), `iobus.rs` (the I/O bus and the card's devices), `flash.rs` (the image flash), `cards.rs` (I/O cards for the slots), `system.rs` (the CPU card and the two in turn) |
| `layout.py` | What the microcode, the Forth and the tools share: the SRAM's map, the banks' registers, the system's variables and tables, the control register, the timing table, the image flash's header, the rings and their requests |
| `uasm.py` | The microassembler: RFC 0027's notation, one line a microinstruction, with macros |
| `ucode/core.uc`, `ucode/jobs.uc`, `ucode/prims.uc` | The microcode |
| `ucode/hwtest.uc` | A microcode program of its own, for checking the netlist's system bus side, shared RAM and I/O bus against the model |
| `card.py` | The card's netlist, for the chip-level simulator (`infra/hwsim`), with a test bench around it on the system bus |
| `hw.py` | Running the netlist, and checking it against the model clock for clock (`heron iop hw`) |
| `meta.py` | The metacompiler: the Forth source into the dictionary image |
| `forth/kernel.fs`, `monitor.fs`, `system.fs`, `devices.fs`, `cold.fs` | The Forth |
| `build.py` | The image flash: the dictionary, and the CPU's images as records |
| `sw/hello.s`, `sw/irq.s`, `sw/ring.s` | CPU programs: the default boot program, one that waits for an interrupt from the IOP, and the kernel's side of the rings |
| `run.py`, `cli.py` | Running it; the command line |
| `bench.py` | The measurements |
| `tests/` | The unit tests: the microassembler, the Forth, the system, the rings, the devices behind them, the events, the netlist |

## The machine, as this study has it

RFC 0027 gives the fields and widths of the microinstruction; the rest of
this section is what the study chose to make it run. These are for the
RFC, not decisions.

- **The microinstruction's layout** (`sim/src/micro.rs`): K 0-15, REG
  16-21, RS 22-23, ALU 24-29, WB 30, LD 31-33, BUS 34-35, SEG 36, SZ
  37-38, T 39-41, SEQ 42-43, COND 44-46, TASK 47. M is stored inverted, so
  that the all-zero ALU field is HOLD (M = 1, S = 0000, carry in 0, one of
  the codes that repeat a logic function) and the all-zero
  microinstruction does nothing at all.
- **WB writes the SRAM at its address:** X when RS is memory, the register
  {BANK, REG} otherwise, so `t0 <- #5` writes a register, and copying one
  register to another takes two microinstructions (`F <- a`, `b <- F`).
- **CTRL is an addressable latch** (a 74x259 for the 74ABT273): LD CTRL
  sets bit R[2:0] to R[3], so firmware can change one bit without knowing
  the others. Its bits: SESSION, WORK, RESET (the system bus's), IORESET.
- **LC** is one 74F161: COND "LC not done" is LC != 15, and counts. Loading
  it with -n gives n passes, 1 to 16.
- **BA interlocks:** a microinstruction that reads BA before the last
  read's data is there waits (RFC 0027 says only that the next transfer
  waits at E1).
- **AB interlocks too:** a microinstruction that loads AB while the last
  write's data phase hasn't ended waits at E1, as a transfer does, so the
  write's data holds; without it, writes of registers one after another
  (a completion's four halfwords) would have to count the slave's
  clocks.
- **An I/O bus access** starts when the last one's hold has ended, and
  stretches its microinstruction to its strobe's end, (1 + SETUP) +
  STROBE clocks from the timing table, when that is more than 2 ("stalls
  the core until its strobe ends", RFC 0027, 3.5). The hold overlaps what
  follows, so the I/O side is taken to keep A0-A7, WRITE and the data
  through it.
- **REQ and GNT:** GNT comes 4 clocks after SESSION rises (an idle bus;
  the CPU's own use of the bus isn't modelled). A transfer without
  SESSION is a microcode error here.
- **The event ports** (device 3): register 0 the INT lines; 1 ATN0-3 and
  the tick in bit 15, written to clear the tick; 2 the doorbells, written
  to clear doorbell X[3:0].
- **The shared RAM takes X as a byte address,** its bit 0 ignored, and
  its page register (device 4 register 0, 7 bits for up to 8 MB) as
  address bits 16-22: a CPU's physical address in region 4 splits into
  the two without a shift, which the datapath doesn't have. RFC 0027 has
  X count halfwords, with a 4-bit page register for 2 MB; with that, every
  request into the shared RAM would cost a 15-step shift.
- **The registers** are in RFC 0027's order and groups (6.1, 3.5): a
  task's `ip sp rp tos resume link wait m1` with the I/O bus, `t0`-`t7`
  with the shared RAM, `up` and `me` at 16-17, user variables from 18. So
  no primitive can step a scratch register while it reads the I/O bus:
  `io@` and `flash!` move their data through AC and X instead. `m1` is -1
  in every bank, and since BANK takes F's low 8 bits, `BANK <- m1` goes to
  bank 255, the native layer's, while K holds a branch target.
- **`execute`** goes through nest-w, with w = t0 (RFC 0027, 6.2).
- **The native layer** runs in bank 255, entered at a primitive's end
  (`branch`, `0branch`, `exit`, the loops), from `pause` while it skips
  waiting tasks, or between a job's slices. It runs the tick, the
  doorbells (each queues its client's ring job), and the jobs.
- **Native jobs** each have a bank: 64-79 the clients' ring jobs, 80-95 a
  pool the Forth's `(job)` takes from, which the task that started one
  waits on. Queued jobs are a ring through a table of links; the head
  runs, a slice at a time, and WORK is on while any wait, so that the
  Forth looks at attention. Between slices a job counts and clears the
  tick itself when nothing else is up (10 microcycles), and goes to the
  native layer otherwise. A job's turn is 4 ticks, then the queue moves
  on and the Forth gets a turn, only if a task is running or has been
  woken.
- **The movers** cut a block into chunks that keep each address within
  its 64 KB (the bus's AH, the shared RAM's page; b within its page of the
  image flash), and each chunk into slices of 16 transfers, with LC
  loaded from a table by the slice's bytes. Halfwords only; to and from a
  device's register, multiples of 4.
- **The rings** (layout.py, RFC 0040, 5): +0 head and +4 tail, each
  counting entries in its word's low half, then the entries; each lives
  with its reader. A client's request ring is in the shared RAM, its
  completion ring in its CPU's RAM, within a 64 KB page; the IOP never
  reads a completion ring's or a ring of events' tail, as RFC 0040's rule
  (a slot for everything outstanding) keeps them from filling. The ring
  job reads a request into its registers, and does copies, fills, zeroing
  and the disk's reads and writes itself, checked against up to 4 windows
  of the client's (the kernel's ring, client 0, has none to check); the
  rest go through a queue to a Forth task, the server. A client's
  completions are an event, source SRC_RING + c, posted when its ring is
  next empty, so a run of requests costs one event.
- **Masking a client's completions** (RFC 0040, 4.4 has each source
  masked until it's served): the head words' high halves count those
  events, the completion ring's (the IOP's) those posted and the request
  ring's (the client's) those handled. Having handled one, the client
  copies the first to the second, then looks at its completions again;
  the IOP posts the next only when they're equal. That serves the source
  without a request, and a spurious interrupt can't put them out of step.
- **The routing table** (RFC 0040, 4.3): 8 cells for each of 48 sources
  (INT 0-15, ATN0-3, the clients' completions): owner (a task's wait
  register or a CPU), CPU, class, level, hold or deadline, and a fast
  event's message source. `post` delivers: to a task by clearing its
  wait; lazy into the CPU's ring of events, with its level only if the
  ring's wake-me word (in the shared RAM) is set or when its deadline
  passes; slow into the ring and its level at once or held back; fast by
  claiming the CPU card's message register and writing {source, the
  event's source number}, or as slow when the claim fails. A level held
  back sets TICKS, a countdown the tick takes, to the shortest hold
  waiting; when it runs out every held level goes in one write to each
  CPU's set address. A lazy deadline is the same mechanism, so a CPU that
  drained the ring at its tick may still get the level, with nothing new
  in it.
- **I/O cards** (`sim/src/cards.rs`): the CF card with A3 as its second
  chip select, PIO mode 4 timing (0/3/0); the serial card's two 16C550s
  on A3, from CLKA; a GPIO card with an INT mask register.
- **The image flash's layout:** a header page, the dictionary from page 1,
  the CPU's images from halfword 0x10000 (`build.py`), as records of
  {bus address, n, n halfwords}.
- **The CPU card's registers** at `0x7000_0000` (`sim/src/system.rs`),
  RFC 0040, 3's: control at +0 (RUN, RESET, STEP, NMI), board information
  at +0x1000, the request register at +0x2000 (set, clear, read), the
  message register at +0x3000 (claim, message, release, contents), the
  timer at +0x4000, and the control store's ten lanes at +0x40_0000. The
  timer's tick jumper is off unless `System(tick=16)`, as the study's CPU
  programs don't take level 6.

## The netlist

`card.py` is the card at chip level (RFC 0027, 16, step 4), a first cut:
the core, the devices on T, the I/O bus side with the card's own devices,
and the system bus side as a master. `hw.py` runs it on the chip-level
simulator and checks it against the model: every E2, the microaddress
uIR takes and AC, must be the model's, on the same bus clock.

```sh
heron iop hw run --ms 32                 # power up: the Forth's banner, about 8 s
heron iop hw run --ms 45 --type '1 2 + .\r'
heron iop hw test --ms 21                # the firmware against the model, to the first tick
heron iop hw test --ucode hwtest.uc      # the bus side, shared RAM and I/O bus against the model
heron iop hw bom                         # the parts
```

- **What it does:** from power-up it runs the firmware's cold start (the
  SRAM's test, the dictionary out of the image flash, the Forth's cold
  start) to the banner, and the Forth's interpreter on the console, with
  no timing violations at the slow corner. It is the model's, clock for
  clock and AC for AC, for the 161,554 microinstructions up to the
  timer's first tick, which the two see a few clocks apart (the model
  looks at the timer lazily); after that it runs on by itself. The bus
  side runs `ucode/hwtest.uc` the model's way, and leaves the same
  registers and the same RAM on the bench's CPU card.
- **The microcycle:** PH, a flip-flop, is the half. At each edge it turns
  to the second half (E1) unless something holds the first, and back (E2)
  unless something holds the second; every register is clocked by BCLK
  with an enable, E1EN or E2EN. The SRAM is written from E1 until BCLK
  falls.
- **Predecoding** (RFC 0027, 3.6's suggestion): the first half's paths
  don't fit 60 ns with decoders in them, so 13 bits are decoded from the
  next microinstruction as the flash gives it and registered with it in
  uIR's spare bits and a seventh half: the SRAM's address source (both
  polarities), R's and T's sources, a device onto R, the I/O bus access.
  With them a register through the ALU into F is about 54 ns.
- **The I/O bus side** (RFC 0037, 16): an access is S0 (idle, or its
  setup), STB and HLD, with an 8-bit counter each state starts from 0 and
  two comparators against the timing table's fields. The table is
  addressed by X: SETUP and STROBE are read while the access's
  microinstruction runs, HOLD is latched at the strobe's end. An
  access's first clock compares SETUP with two XORs, since X may have
  changed at its start. The strobe's end is registered (IODONE), and
  that is what the core waits on.
- **The system bus side:** AL and AHOUT take the address at E1; START,
  WRITE and BE are registered for the address clock, which is the second
  half's last; BA takes read data at the data phase's end, AB drives
  write data through it. A transfer waits at E1 for GNT and the last data
  phase's end, with WAIT's own term last in E1EN, as it comes late in the
  clock (RFC 0037's 29 ns); E2 can't wait for WAIT, as E2EN goes to the
  74F161s' 11.5 ns setups.
- **What the model changed to match:** an I/O bus read is latched at the
  strobe's end, so one onto R takes two clocks more than the model had;
  an access that stretches the second half ends a clock after its strobe
  (the registered stall); an AB load waits for the clock after the last
  write's data phase; a transfer's address clock is the second half's
  last. RFC 0027's own figures (3.6) leave out the decoders, the
  comparator in the I/O side and the WAIT path, which is where these
  came from.
- **Substitutes** for parts the library lacks: four 74ABT16823 halves for
  the 74ABT16652; a 74F175, a 74F138 and gates for CTRL (the study's
  74x259); 74F138s for the 74F139s and the 74HCT154; SST39SF010A (128K x
  8) for the image flash's SST39SF040s, so 128K halfwords of it;
  AS7C4096A-12 for the shared RAM, as the AS6C4008-55 can't be read onto
  R in a first half; CY7C199D-10 for the timing table.
- **Parts:** 140 packages so far (`heron iop hw bom`), against RFC 0027's
  ~95 for the whole card: about 40 are gates (74F00-74F32), the glue that
  decoding, the stalls and the I/O side's state need, and 14 are 74F138s.
- **Contention:** R changes hands at E1 with up to 7 ns of overlap (F's
  enable against the SRAM's disable), and while reset holds uIR cleared
  both of the SRAM's address drivers are on.
- **Not yet:** the slave side (the shared RAM from the bus, sharing T
  with the core, the doorbells, the window), the 32-bit path, LOCK, the
  stuck-transfer counter, the watchdog, the time of day, the ports' read
  side, I/O cards in the slots, static timing analysis (the simulator's
  checks catch a late signal only within a setup window, not one later
  than the edge, so the paths above were checked by hand), and a
  timer model in the microinstruction-level model exact enough to keep
  the two together past the first tick.

## Measurements

`heron iop bench --wcs`, against RFC 0027's estimates:

| | Measured | RFC 0027 |
|---|---:|---|
| SRAM self test (64K cells, two patterns) | 125.8 ms | - |
| dictionary out of the flash (8705 cells, 35 pages) | 7.1 ms | 32K cells in ~30 ms |
| power-up to the banner | 151.0 ms | - |
| Forth words a second, in a loop of `i inc dup + over swap - drop` | 1,257,041 | about 1,000,000 |
| microcycles a Forth word, there | 6.63 | NEXT 3 (2 with its delay slot used), most primitives 5-7 |
| the tick's share of the IOP while Forth computes | 9.5% | 5-10% (0.5-1 us a tick) |
| Forth words a second, `words` (the console, `emit` waiting on the UART) | 1,238,920 | - |
| fill, the CPU's RAM, 8192 halfwords | 6.1 MB/s | 9.9 MB/s |
| copy, the CPU's RAM to its RAM, 8192 halfwords | 3.0 MB/s | 4.9 MB/s |
| copy, the shared RAM to the CPU's RAM, 8192 halfwords | 4.6 MB/s | 7.6 MB/s |
| copy, the CPU's RAM to the shared RAM, 8192 halfwords | 3.8 MB/s | 7.6 MB/s |
| booting the CPU: draft 2's control store, its decode table and the program | 92.5 ms (2.6 MB/s) | about 35 ms for the 1b's (130K halfwords at 7.6 MB/s) |
| a request, the IOP's side: fill 64 bytes, from the doorbell to its completion, and to the interrupt | 45.0 us, 63.6 us | ~5 us on top of the transfer |
| a request, the IOP's side: copy a 4 KB page, from the doorbell to its completion, and to the interrupt | 1377.6 us, 1396.2 us | ~5 us on top of the transfer |
| a request, the IOP's side: OP_NOP, through the Forth's server, from the doorbell to its completion, and to the interrupt | 154.7 us, 238.9 us | ~5 us on top of the transfer |
| a request from the CPU at 6 MHz: fill 64 bytes, its cycles (the handler included), and the time from one to the next | 281 cycles, 103 us | 200-700 cycles |
| a request from the CPU at 6 MHz: copy a 4 KB page, its cycles (the handler included), and the time from one to the next | 281 cycles, 1435 us | 200-700 cycles |
| a request from the CPU at 6 MHz: a request to the Forth's server (OP_NOP), its cycles (the handler included), and the time from one to the next | 281 cycles, 278 us | 200-700 cycles |
| Fen: `cat /tmp/big > /dev/null`, 256 KB: its own PIO driver; through the IOP | 527 ms, 100% busy, 12,317 cycles a KB; 380 ms, 82% busy, 7,291 cycles a KB | the CPU's time back |
| Fen: `cp /tmp/big /tmp/copy`, 256 KB: its own PIO driver; through the IOP | 2343 ms, 100% busy, 54,893 cycles a KB; 1664 ms, 68% busy, 26,569 cycles a KB | the CPU's time back |
| microcode | 2231 microinstructions, 76 primitives | 1-2K; the interpreter and primitives 500-1,000 |
| the Forth's dictionary | 8705 cells | up to 32K |

The copies are a job's time from its first slice to its end, with the
ticks and the Forth's turns. A request's CPU cycles are `sw/ring.s`'s,
whose handler takes one completion and drains the events: a kernel's
would do more. Fen's rows are [studies/fen](../fen/README.md) on its own
board with the IOP's card added, the CPU at 6 MHz, a file bigger than its
file server's cache of 96 KB: the time from typing the command to the
prompt, how much of it the CPU wasn't waiting in HALT, and its busy
cycles a KB.

What the differences come from, so far:

- **The copies** run at the loop's rate in each slice (fill 3 clocks a
  halfword, two writes a microinstruction pair; copies 4-6), but a slice
  costs 7 microinstructions more than RFC 0027's 6 clocks of
  re-arbitration (its count and test, LC, the step, the session off and
  on, the look at attention), the tick about 10 a job's slice when it
  comes, and a job's turn ending 30-40. The RFC's figures leave all three
  out. A copy within the CPU's RAM moves 8 halfwords a slice, so it pays
  that twice as often.
- **Into the shared RAM** a halfword waits a clock for BA: the CPU card's
  slave port takes 2 data clocks, so the read's data comes a clock after
  the next microinstruction's E1.
- **Out of the image flash** a halfword is 6 clocks, not 4: the
  SST39SF040-70 needs a 2-clock strobe (0/2/0), so the read stretches its
  microinstruction to 3, and the netlist's I/O side (below) takes a clock
  more to end it. A 45 ns part (0/1/0) would make it 5. The boot
  is also a job for each run of the control store's used words, a few
  hundred, each started from the Forth.
- **A request** costs the IOP about 280 microcycles (34 us) from the
  doorbell to its completion for the smallest one, against RFC 0027's 5
  us: the doorbell and queueing its ring job (about 40), reading 8
  halfwords at 2 microinstructions each and the ring's bookkeeping (43),
  decoding, the checks and starting the mover (about 40), the move, the
  completion (56: its settings are read through X, 3 microinstructions a
  value), and ticks and turns meanwhile. The interrupt is another 55 or
  so: the routing table read, the event into the CPU's ring, then the
  level. So a request pays
  from about 200 bytes up, which is what RFC 0027 (11.4) expects of the
  CPU's side; with the IOP's side as measured, from about 500.
- **The server** is the Forth's: about 150 us for a request that does
  nothing, from the queue through `serve` to `(complete)`, and its event
  another 85 us, as the ring job posts it once it runs again.
- **The disk** was the server's at first, as RFC 0027 (7.2) has it: a
  1 KB read took the IOP 811 us, 3,700 of its 6,000 microcycles the
  Forth's (reading the request's fields, dispatching, the CF card's task
  file, a job a sector, the completion). With Fen that was as slow as
  Fen's own PIO driver, if half the CPU's time. As native ops in the ring
  job (`jr_read`, `jr_write`: the task file written, the status polled
  between visits to the native layer, a mover a sector) it is 315 us,
  most of it the transfer, and Fen reads a file 28% faster than with its
  own driver, with 41% fewer of the CPU's cycles; copying one, 31% faster
  with 52% fewer. RFC 0027's line between microcode and Forth wants
  moving for the disk, at least: what's per request is too slow in Forth.
- **The Forth** is faster than the RFC's estimate in ordinary code; the
  slow words are the ones with microcode loops (`um*`, `um/mod`, `rshift`
  and so `2/`: 80-160 microcycles).
- **The tick** costs Forth 7 microcycles when nothing is up (the INT
  lines, ATN0-3, and TICKS counted), and a job between slices 10.

## Not yet

- **More of Fen behind the IOP:** its console on the IOP's serial card,
  pages zeroed and copied by the IOP, user-level drivers with rings of
  their own; Fen's board is still its own (RFC 0014's slots, its own
  timer and interrupt mask), with the IOP's card added on RFC 0037's map.
- **Devices:** the serial loader, PS/2, the time of day and the front
  panel; the stuck-transfer counter; the 32-bit paths; change detection
  on the INT lines; a timer request (a completion after a delay).
- **The rings:** a completion ring or a ring of events is never checked
  for room (RFC 0040, 5.1's rule keeps them from filling, if the client
  keeps it); requests from the CPU's RAM rather than the shared RAM; the
  server's own windows for Forth from the kernel. The disk's errors only
  as ST_DEVICE, and a card that stays busy holds its ring job for ever.
- **The netlist's rest:** see [The netlist](#the-netlist).

Where the CPU's side doesn't match this system yet, for the RFCs rather
than this study: draft 2's CPU card in `studies/v2_hw` (`iop.py`, after
RFC 0031, 6) has its slave port in slot 0 by RFC 0014's slots, with the
control register at `0x600_0000` and the control store at `0x400_0000`
in the slot. Here the card is RFC 0037's region 0, its registers at
`0x7000_0000` with the control store's window among them, ten lanes:
draft 2's 144-bit microinstruction in nine, the decode table in one.
