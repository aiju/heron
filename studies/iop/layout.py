"""What the microcode, the Forth and the tools agree on: the SRAM's map,
the registers of the banks, the control register's bits, the image flash's
header, the rings and their requests. The microassembler sees every name
here as a symbol.

The SRAM, in 16-bit cells (RFC 0027, 3.4):

    0x0000-0x7FFF  the dictionary: code and data. Every colon definition
                   starts here, so that its address has bit 15 clear
    0x8000-0x80FF  system variables (below)
    0x8100-0x81FF  tables: the movers' loop counts, the levels' bits, the
                   ops, the event sources
    0x8200-0x83FF  the rings' settings, 32 cells for each of 16 clients
    0x8400-0x84FF  requests waiting for the Forth's server, 16 cells each
    0x8500-0x853F  each CPU's ring of events, 16 cells a CPU
    0x8600-0x8FFF  buffers: the console's input line
    0x9000-0xAFFF  stacks: 128 cells a task, data then return, for up to
                   64 tasks; task n's data stack grows down from
                   0x9040 + 128n, its return stack from 0x9080 + 128n
    0xB000-0xB0FF  the native jobs' queue: a job's successor, by bank
    0xC000-0xFFFF  the register banks: register r of bank b at
                   0xC000 + 64b + r

**The banks.** Banks 0-63 are Forth tasks, 64-79 the clients' ring jobs,
80-95 the pool of native jobs the Forth starts, 255 the native layer's.
REG names a register and a device on T at once (RFC 0027, 3.5):
registers 0-7 go with device 0, the I/O bus, and 8-15 with device 1, the
shared RAM, any of them; 16-63 one each with the registers of devices
2-7. So a loop that steps a pointer while it reads or writes a device
keeps the pointer in that device's group. Register 7 is m1, -1, in every
bank.

A Forth task's (RFC 0027, 6.1, in its order):

    0 ip      the cell being executed
    1 sp      the data stack: the second item (the top is in AC)
    2 rp      the return stack's top
    3 tos     the top of the stack while the task is switched out
    4 resume  the microaddress the task goes on at: NEXT
    5 link    the next task's bank
    6 wait    0 if it can run; anything else while it waits for an event
    7 m1      -1, for testing AC for zero: m1 + AC carries unless AC is 0
    8-15      t0-t7: scratch for primitives; w, the word `execute` runs,
              is t0. The subroutines a primitive shares with the native
              layer take their arguments here, and t7 is their return
    16 up     the address of its register 0: user variable n is at up + n
    17 me     its own bank's number
    18-63     user variables

A native job's (this study's):

    0 jp, 1 jp2   the movers' bus pointers (with the I/O bus: 0-7)
    2 jx      X for a device's register; 3-5 jt-jt3 scratch
    6 jsoff   CTRL's value for the bus session off
    8 jsx, 9 jsb  the shared RAM's pointer, and the bus pointer or the
              value stepped with it (with the shared RAM: 8-15); a
              request's eight halfwords (jq0-jq7) as the ring job reads
              it; the subroutines' t0-t7
    32 jpg    the page of a ring job's rings
    34 jres   the microaddress its next slice starts at
    35 jkind  what a pool job's end does (JK_*); in a free bank, the
              next free bank's register 0
    36 jarg   the task's wait register, for JK_WAKE
    37 jtag, 38 jstat, 60 jdone   the request's tag, its status and
              result
    39 jme    its own bank's number; 63 jbase its register 0
    40 jleft  bytes left after the current chunk; 45 jchunk in it
    41-42     jalo, jahi: address a, the destination
    43-44     jblo, jbhi: address b, the source; a fill's value; a
              device's register; the image flash as (halfword in its
              page, page)
    46 json   CTRL's value for the session on
    47 jend   where the mover goes when it's done
    48 jmv    the mover's start; 49 jbk what b is (B_*)
    50 jcl    a ring job's client; 51 jset its settings (RINGS + 32c)
    52-55     jreq, jrmask, jrtail: its request ring (byte address in
              page jpg, bytes less one, the next to read); jidx: the
              indices
    56 jwin, 57 jwn   the window being checked, and those left
    58-59     jelo, jehi: the end of a range being checked
    61 jret   a subroutine's return; 62 jirq completions posted since
              the client's last interrupt
"""

# ---- the SRAM: system variables
DICT_END = 0x8000
EVMASK = 0x8000          # INT 0-15 enabled for routing
ATNMASK = 0x8001         # ATN0-3 enabled for routing, bits 0-3
BELLS = 0x8002           # doorbells of clients without rings, for the Forth
FAULT = 0x8003           # why the microcode stopped, when it did
CURTASK = 0x8004         # the running Forth task's bank
JQHEAD = 0x8005          # the native jobs' queue: a ring through JLINK; 0 empty
JQTAIL = 0x8006
JFREE = 0x8007           # the pool's free banks: the first's register 0, 0 none
TICKS = 0x8008           # ticks until held levels go out (counts down)
REQHEAD = 0x8009         # the server's queue of requests: written by the native layer
REQTAIL = 0x800A         # and read by the Forth
SERVER = 0x800B          # the server task's wait register, 0 none
CLIENTS = 0x800C         # the clients whose rings are set up, a bit each
DROPPED = 0x800D         # events and completions dropped: their rings were full
TICKS_IDLE = 0x7FFF      # TICKS with nothing held

# ---- tables
NEGHALF = 0x8100         # n -> -(n / 2) & 15, for n = 0-32: LC for n bytes, a halfword a pass
NEGQUART = 0x8121        # n -> -(n / 4) & 15, for n = 0-64: LC for n bytes, two halfwords a pass
LEVELBIT = 0x8162        # level n -> 1 << (n - 1), for n = 0-8 (0 for 0)
OPTAB = 0x8170           # ops 0-15: where a ring job decodes each to
EVTAB = 0x8180           # sources 0-19 (INT 0-15, ATN 0-3): 4 cells each (EV_*)
RINGS = 0x8200           # 32 cells a client (R_*)
REQQ = 0x8400            # 16 entries of 16 cells: the client, then the request
REQQ_N = 16
EVRING = 0x8500          # 16 cells a CPU (E_*)
TIB = 0x8600             # the console's input line
TIB_SIZE = 128
STACKS = 0x9000
STACK_CELLS = 64         # each of a task's two stacks
JLINK = 0xB000           # a queued job's successor, by bank; 0 when not queued
BANKS = 0xC000

# ---- event sources (RFC 0027, 6.4 and 7.3)
SOURCES = 20             # INT 0-15, ATN 0-3
SRC_ATN = 16
SRC_RING = 32            # a client's completions, as an event: 32 + client
EV_OWNER = 0             # 0 nobody, EV_CPU a CPU, from 0xC000 up a task's wait register
EV_CPU16 = 1             # 16 x the CPU: its EVRING entry
EV_LEVEL = 2
EV_HOLD = 3              # ticks a slow level may be held back for it
EV_CPU = 1

# A CPU's events (EVRING + 16c): a ring of halfwords in the shared RAM,
# each a source's number, and a block beside it: +0 the next entry the IOP
# will write, +2 the next the CPU will read (both byte offsets), +4, +6,
# +8 the mailboxes of levels 6-8, +10 events dropped.
E_RING = 0               # the ring: byte address, page
E_MASK = 2               # its bytes less one
E_HEAD = 3               # the next entry, as a byte offset
E_BLK = 4                # the block: byte address, page
E_SEG = 6                # 0x7000 | CPU << 8: its card's registers (RFC 0037, 5.1)
E_PEND = 7               # slow levels held back: their bits
E_ON = 8                 # the ring is set up
B_HEAD, B_TAIL, B_MAIL, B_DROP = 0, 2, 4, 10
CPUS = 4                 # CPU cards in regions 0-3
IRQ_SET = 0x2000         # in the card's registers (studies/iop/sim/src/system.rs)
IRQ_CLEAR = 0x2004
FAST_LEVEL = 6           # levels 6-8 are fast: never held, one source each

# ---- banks
CONSOLE_BANK = 0
TASKS = 64
CLIENT_BANK = 64         # client c's ring job is bank 64 + c
CLIENTS_N = 16
JOB_FIRST = 80           # the pool, for the Forth's jobs
JOBS = 16
NATIVE_BANK = 255

REGS = {
    "ip": 0, "sp": 1, "rp": 2, "tos": 3, "resume": 4, "link": 5, "wait": 6, "m1": 7,
    **{f"t{n}": 8 + n for n in range(8)}, "w": 8,
    "up": 16, "me": 17,
}
USER_FIRST = 18           # the first user variable

JOB_REGS = {
    "jp": 0, "jp2": 1, "jx": 2, "jt": 3, "jt2": 4, "jt3": 5, "jsoff": 6,
    "jsx": 8, "jsb": 9, **{f"jq{n}": 8 + n for n in range(8)},
    "jpg": 32, "jres": 34, "jkind": 35, "jarg": 36, "jtag": 37, "jstat": 38, "jme": 39,
    "jleft": 40, "jalo": 41, "jahi": 42, "jblo": 43, "jbhi": 44, "jchunk": 45, "json": 46, "jend": 47,
    "jmv": 48, "jbk": 49, "jcl": 50, "jset": 51, "jreq": 52, "jrmask": 53, "jrtail": 54, "jidx": 55,
    "jwin": 56, "jwn": 57, "jelo": 58, "jehi": 59, "jdone": 60, "jret": 61, "jirq": 62, "jbase": 63,
}

# The native layer's (bank 255), beside m1 and t0-t7:
NAT_REGS = {"nret": 16, "nint": 17, "nbit": 18, "nsrc": 19, "nwhich": 20, "nturnc": 21, "nturnf": 22}
TURN_TICKS = 2           # ticks in a job's turn: then the queue moves on, and the Forth runs

# A pool job's end (jkind)
JK_NONE = 0
JK_WAKE = 1

# What a job moves (the Forth's `(job)`): a <- b
K_COPY = 0               # b an address
K_FILL = 1               # b a halfword's value
K_FLASH = 2              # b the image flash: (byte in its page, page)
K_FROMIO = 3             # b a device's register (X)
K_TOIO = 4               # a a device's register, b an address
# What b is, for the chunks
B_ADDR = 0
B_FLASH = 1
B_NONE = 0x8000


def bank_addr(bank, reg=0):
    """The SRAM address of a register."""
    return BANKS + 64 * bank + reg


def stack_tops(task):
    """(data stack's empty sp, return stack's empty rp) of task n."""
    base = STACKS + 2 * STACK_CELLS * task
    return base + STACK_CELLS, base + 2 * STACK_CELLS


S0, R0 = stack_tops(0)    # the console task's


# ---- the control register (an addressable latch: R[2:0] the bit, R[3] its value)
CTRL_SESSION = 0
CTRL_WORK = 1
CTRL_RESET = 2
CTRL_IORESET = 3


def ctrl(bit, on):
    return bit | (8 if on else 0)


# ---- the I/O bus's devices and timing table entries (RFC 0037, 17)
DEV_UART = 12
DEV_FLASH = 13
DEV_TIMER = 14
DEV_PORTS = 15
TT_WAIT = 1 << 12
TT_WINDOW = 1 << 13


def timing(setup, strobe, hold, wait=False, window=False):
    """A timing table entry."""
    assert 0 <= setup <= 3 and 1 <= strobe <= 64 and 0 <= hold <= 15
    return setup | (strobe - 1) << 2 | hold << 8 | (TT_WAIT if wait else 0) | (TT_WINDOW if window else 0)


# At 60 ns: the 16C550 reads in 45 ns after its strobe (0/2/0, RFC 0037's
# example); the SST39SF040-70 in 70 ns (0/2/0, 120 ns); the 82C54 wants a
# 150 ns read strobe and its address 45 ns ahead (1/3/1); the ports are
# HCT latches and buffers (0/2/0).
TT_UART = timing(0, 2, 0, window=True)
TT_FLASH = timing(0, 2, 0)
TT_TIMER = timing(1, 3, 1, window=True)
TT_PORTS = timing(0, 2, 0, window=True)

# The I/O cards in the slots (heron.native.iop.System's disk and serial):
# the CF card in PIO mode 4 (RFC 0037, 17's estimate), the serial card's
# 16C550s as the console's.
DISK_SLOT = 0
SERIAL_SLOT = 1
TT_CF = timing(0, 3, 0)
TT_SERIAL = timing(0, 2, 0, window=True)

# ---- the image flash, in halfwords
FLASH_MAGIC = 0x4F49       # "IO"
FL_MAGIC = 0
FL_VERSION = 1
FL_PAGES = 2               # the dictionary's length, in 256-halfword pages
FL_COLD = 3                # the cold start's body address
FL_HERE = 4                # the dictionary's end
FL_LATEST = 5              # the last word's header
FL_IMAGES = 8              # images 0-3: their first halfword, as (low, high)
FL_DICT = 0x100            # the dictionary starts at the second page

# ---- the rings (RFC 0027, 7.1-7.2)
#
# A client's rings are in the shared RAM: a ring of 16-byte requests the
# client writes, a ring of 8-byte completions the IOP writes, and four
# indices beside them, each with one writer. Indices are byte offsets
# into their rings, and a ring's size is a power of two.
I_REQHEAD = 0              # the client's: where it will write its next request
I_REQTAIL = 2              # the IOP's: the next it will read
I_CMPHEAD = 4              # the IOP's: where it will write its next completion
I_CMPTAIL = 6              # the client's: the next it will read
#
# The IOP's settings for client c, at RINGS + 32c; the request ring's
# are in its job's bank (jreq ...):
R_CMP = 0                  # the completion ring: byte address, page
R_CMASK = 2                # its bytes less one
R_CHEAD = 3                # the next completion, as a byte offset
R_IDX = 4                  # the indices: byte address, page
R_CPU16 = 6                # completions interrupt CPU R_CPU16 / 16
R_LEVEL = 7                # at this level, 0 for none
R_HOLD = 8                 # held back for up to this many ticks (slow levels)
R_NWIN = 9                 # windows, 0-4
R_OUT = 10                 # requests the server has and hasn't completed
R_CL = 11                  # the client's number
R_WIN = 16                 # windows: base (low, high), limit (low, high)
WINDOWS = 4
#
# A request, 8 halfwords; a completion, 4:
Q_OP, Q_FLAGS, Q_ALO, Q_AHI, Q_BLO, Q_BHI, Q_LEN, Q_TAG = range(8)
C_TAG, C_STATUS, C_RLO, C_RHI = range(4)
OP_COPY = 1                # len bytes from b to a
OP_FILL = 2                # len bytes at a, of the halfword blo
OP_ZERO = 3                # len bytes at a
OP_SERVER = 16             # this and up go to the Forth
OP_NOP = 16
OP_RING = 17               # kernel: client blo's rings, from the settings at a (below)
OP_WINDOW = 18             # kernel: client flags & 15's window flags >> 8: [a, b)
OP_ROUTE = 19              # kernel: source blo to CPU bhi >> 8 at level bhi & 0xFF (0: nobody), held len ticks
OP_UNMASK = 20             # source blo, served: routed again
OP_EVRING = 21             # kernel: CPU blo's events, from the settings at a (below)
OP_FORTH = 22              # kernel: len bytes of Forth source at a, interpreted
OP_NOTIFY = 23             # kernel: client blo's completions interrupt CPU bhi >> 8 at level bhi & 0xFF, held len ticks
OP_READ = 32               # disk: len bytes from sector (blo, bhi) to a
OP_WRITE = 33              # disk: len bytes from a to sector (blo, bhi)
OP_SEND = 40               # serial line blo: len bytes from a
OP_RECV = 41               # serial line blo: up to len bytes into a: a line, or what's come if raw
OP_MODE = 42               # serial line blo: flags bit 0 raw, bit 1 no echo
ST_OK = 0
ST_BADOP = 1
ST_WINDOW = 2              # outside the ring's windows
ST_DENIED = 3              # a kernel request on another ring
ST_DEVICE = 4              # the device failed
ST_ALIGN = 5               # an odd address or length
ST_BUSY = 6                # a line already has a receive waiting
#
# OP_RING's settings, 10 halfwords at a: the request ring (byte address
# in the shared RAM: low, high), its bytes, the completion ring likewise,
# the indices (low, high); then the interrupt: level | CPU << 8, and its
# hold. OP_EVRING's, at a: the ring (low, high), its bytes, the block
# (low, high).
#
# The kernel's rings (client 0) and CPU 0's events are where the cold
# start puts them, in the shared RAM by byte: the status block at 0, the
# indices at 0x40, the requests (64) at 0x1000, the completions (64) at
# 0x1400, CPU 0's block at 0x1800 and its ring of events (64) at 0x1820.
STATUS_BYTES = 0x40
K_IDX = 0x40
K_REQ = 0x1000
K_REQS = 64
K_CMP = 0x1400
K_CMPS = 64
K_EVBLK = 0x1800
K_EVRING = 0x1820
K_EVS = 64
