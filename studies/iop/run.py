"""Running the system: the IOP's card with its firmware, and the draft 2
CPU card it boots, on heron.native.iop. The console is the IOP's UART:
what's typed goes to the Forth, and what the Forth (or the CPU, through
the window) prints comes back.
"""

import os
import select
import sys
import termios
import tty

from heron import native

from . import build as bld


class Timeout(Exception):
    pass


class Session:
    """A system powered up. `b` is a build.Build (made if not given)."""

    def __init__(self, b=None, program=bld.DEFAULT_PROGRAM, wcs=False, **kw):
        self.b = b or bld.Build(program, wcs)
        self.s = native.iop.System(self.b.ucode_bytes(), self.b.flash, **kw)
        self.bclk = self.s.bclk_ns
        self.out = b""

    @property
    def ms(self):
        return self.s.clock * self.bclk / 1e6

    def run_ms(self, ms):
        """Run for `ms` of simulated time; what the console printed."""
        st = self.s.run(self.s.clock + int(ms * 1e6 / self.bclk))
        got = self.s.uart_take()
        self.out += got
        if st == "stopped":
            raise Timeout(f"the microcode stopped at {self.where()}")
        return got

    def until(self, text, timeout_ms=1000, step_ms=0.5):
        """Run until the console's output since the last call ends with
        `text` (bytes); the output."""
        got = b""
        start = self.ms
        while not got.endswith(text):
            if self.ms - start > timeout_ms:
                raise Timeout(f"no {text!r} after {timeout_ms} ms; got {got!r}")
            got += self.run_ms(step_ms)
        return got

    def boot(self, timeout_ms=1000):
        """Power up to the Forth's first prompt line; the banner."""
        return self.until(b"cells\r\n", timeout_ms)

    def command(self, line, timeout_ms=1000):
        """Type a line at the Forth; what it printed, the echo included,
        as text: up to its " ok", or to a stop of 20 ms after an error."""
        self.s.uart_send(line.encode() + b"\r")
        got = b""
        quiet = 0
        start = self.ms
        while not got.endswith(b" ok\r\n"):
            if self.ms - start > timeout_ms:
                raise Timeout(f"no prompt after {timeout_ms} ms; got {got!r}")
            more = self.run_ms(0.5)
            got += more
            quiet = 0 if more or self.s.uart_pending else quiet + 0.5
            if quiet >= 20 and got.endswith(b"\r\n"):
                break
        return got.decode("latin-1")

    def where(self):
        """The microcode's place, by label."""
        r = self.s.regs()
        a = r["cur"]
        return "reset" if a is None else self.b.mc.where(a)

    def ip_word(self, bank=0):
        """The Forth word a task is in, by its ip."""
        ip = self.s.sram(0xC000 + 64 * bank, 1)[0]
        best = None
        for a, name in self.b.meta.names.items():
            if a <= ip and (best is None or a > best[0]):
                best = (a, name)
        return f"{best[1]}+{ip - best[0]}" if best else f"{ip:04X}"


def console(args):
    """The console in this terminal: keys to the IOP's UART, its output to
    the screen. Ctrl-] quits."""
    s = Session(program=args.program, wcs=args.wcs)
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd) if os.isatty(fd) else None
    try:
        if old:
            tty.setraw(fd)
        while True:
            if select.select([sys.stdin], [], [], 0)[0]:
                ch = os.read(fd, 64)
                if b"\x1d" in ch:
                    break
                s.s.uart_send(ch.replace(b"\n", b"\r"))
            out = s.run_ms(10)
            if out:
                os.write(sys.stdout.fileno(), out)
    except Timeout as e:
        print(f"\r\n{e}\r")
    finally:
        if old:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    print(f"\n{s.ms / 1000:.2f} s simulated")
    return 0
