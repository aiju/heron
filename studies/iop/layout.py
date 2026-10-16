"""What the microcode, the Forth and the tools agree on: the SRAM's map,
the registers of a bank, the control register's bits, the image flash's
header. The microassembler sees every name here as a symbol.

The SRAM, in 16-bit cells (RFC 0027, 3.4):

    0x0000-0x7FFF  the dictionary: code and data. Every colon definition
                   starts here, so that its address has bit 15 clear
    0x8000-0x80FF  system variables and tables (below)
    0x8100-0x8FFF  buffers: the console's input line
    0x9000-0xAFFF  stacks: 128 cells a task, data then return, for up to
                   64 tasks; task n's data stack grows down from
                   0x9040 + 128n, its return stack from 0x9080 + 128n
    0xB000-0xBFFF  free
    0xC000-0xFFFF  the register banks: register r of bank b at
                   0xC000 + 64b + r

A bank's registers, for a Forth task. RFC 0027 (6.1) lists them; their
numbers are this study's. REG names a register and a device on T at once
(RFC 0027, 3.5), so a microinstruction that writes back a value read from
a device, or steps a register while it moves data to or from one, must
use a register in that device's group of eight. So each group whose low
bits are free has scratch registers, and the task's own state is out of
the way, in the page registers' group:

    0 ip      the cell being executed
    1 sp      the data stack: the second item (the top is in AC)
    2 rp      the return stack's top
    3-7       i0-i4: scratch for primitives, in the I/O bus's group
    8-15      t0-t7: scratch, in the shared RAM's group
    16-23     s0-s7: scratch, in the swap register's group
    24-31     scratch for the native layer, which runs in whatever bank
              is current, in the event ports' group (24 takes the INT
              lines, 26 the doorbells)
    32 tos    the top of the stack while the task is switched out
    33 resume the microaddress the task goes on at: NEXT for a Forth task
    34 link   the next task's bank
    35 wait   0 if it can run; anything else while it waits for an event
    36 me     its own bank's number
    37 up     the address of its own register 0: user variable n is at
              up + n
    38-39     xa, xb: `execute`'s thread of two cells
    40-63     user variables
"""

# ---- the SRAM
DICT_END = 0x8000
SYSVARS = 0x8000
EVMASK = 0x8000          # INT lines enabled for routing to tasks
BELLS = 0x8001           # doorbells rung, OR'd in by the native layer
FAULT = 0x8002           # why the microcode stopped, when it did
EVTAB = 0x8010           # INT line n's owner: the address of its wait register
TIB = 0x8100             # the console's input line
TIB_SIZE = 128
STACKS = 0x9000
STACK_CELLS = 64         # each of a task's two stacks
BANKS = 0xC000

# ---- registers
REGS = {
    "ip": 0, "sp": 1, "rp": 2,
    **{f"i{n}": 3 + n for n in range(5)},
    **{f"t{n}": 8 + n for n in range(8)},
    **{f"s{n}": 16 + n for n in range(8)},
    "ints": 24, "bit": 25, "bells": 26, "ex": 27, "nret": 28, "n5": 29, "n6": 30, "n7": 31,
    "tos": 32, "resume": 33, "link": 34, "wait": 35, "me": 36, "up": 37, "xa": 38, "xb": 39,
}
USER_FIRST = 40           # the first user variable

CONSOLE_BANK = 0


def bank_addr(bank, reg=0):
    """The SRAM address of a register."""
    return BANKS + 64 * bank + reg


def stack_tops(task):
    """(data stack's empty sp, return stack's empty rp) of task n."""
    base = STACKS + 2 * STACK_CELLS * task
    return base + STACK_CELLS, base + 2 * STACK_CELLS


S0, R0 = stack_tops(0)    # the console task's
NATIVE_BANK = 255         # the reset microcode's


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
