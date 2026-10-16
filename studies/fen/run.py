"""Running Fen on the simulated machine: a session that boots it and talks
to its serial console (for the tests and the interactive console), and
the screen as a PNG.

Simulated time is the machine's cycle count at its clock (6 MHz by
default). A session runs the machine in slices of simulated time; waiting
in HALT skips to the next interrupt, so an idle machine costs the host
little.
"""

import os
import sys
import time

from heron import native
from heron.studies.fen import build

MS = 1_000_000          # ns


class Timeout(Exception):
    pass


class Session:
    """A booted machine. `serial`: a shell on the serial console instead of
    the window system. `disk`: the CF card's image (build.disk() by
    default)."""

    def __init__(self, serial=True, disk=None, ram=4 << 20, clock_hz=6e6, boot=None):
        img, self.kernel = boot if boot is not None else build.boot_image()
        self.disk = disk if disk is not None else build.disk()
        self.c = native.fen.Computer(cf_image=self.disk, ram_size=ram, clock_hz=clock_hz,
                                     boot_flags=1 if serial else 0)
        self.c.load(0, img)
        self.out = bytearray()      # what the console printed
        self.log = bytearray()      # the kernel's log (the debug port)
        self.status = None
        self.mark = 0

    @property
    def ms(self):
        """Simulated milliseconds since power-on."""
        return self.c.now_ns / MS

    def _collect(self):
        self.out += self.c.uart_take()
        self.log += self.c.debug_take()

    def run(self, ms):
        """Run for `ms` simulated milliseconds."""
        until = self.c.cycles_at(int((self.ms + ms) * MS))
        self.status = self.c.run(until)
        self._collect()
        if self.status == "halted":
            raise RuntimeError("the machine halted:\n" + self.log.decode(errors="replace"))
        return self.status

    def type(self, text):
        """Type at the serial terminal."""
        self.c.uart_send(text.encode() if isinstance(text, str) else text)

    def wait_for(self, text, timeout_ms=60_000, step_ms=20):
        """Run until the console has printed `text` since the mark: what it
        printed up to the end of it. The mark moves past it."""
        want = text.encode() if isinstance(text, str) else text
        start = self.ms
        while True:
            i = self.out.find(want, self.mark)
            if i >= 0:
                got = bytes(self.out[self.mark:i + len(want)])
                self.mark = i + len(want)
                return got.decode(errors="replace")
            if self.ms - start > timeout_ms:
                raise Timeout(f"no {text!r} after {timeout_ms} ms; the console has:\n"
                              + self.out[self.mark:].decode(errors="replace")
                              + "\nthe log:\n" + self.log.decode(errors="replace"))
            self.run(step_ms)

    def boot(self, prompt="% ", timeout_ms=60_000):
        """Run until the shell's first prompt."""
        return self.wait_for(prompt, timeout_ms)

    def command(self, line, prompt="% ", timeout_ms=60_000):
        """Type a command line, and return what it printed before the next
        prompt (without the echoed line and the prompt)."""
        self.type(line + "\n")
        got = self.wait_for(prompt, timeout_ms)
        got = got.replace("\r\n", "\n")
        echoed = line + "\n"
        if got.startswith(echoed):
            got = got[len(echoed):]
        # the prompt is the last line
        cut = got.rfind("\n")
        return got[:cut + 1] if cut >= 0 else ""

    def screen(self):
        """The screen, 640 x 480 RGB bytes."""
        return self.c.screen(True)

    def save_png(self, path):
        from heron.studies.graphics.png import write_png
        rgb = self.screen()
        rows = [rgb[y * 640 * 3:(y + 1) * 640 * 3] for y in range(480)]
        write_png(path, 640, 480, rows)

    def cf_image(self):
        return bytes(self.c.cf_image())


def console(args):
    """The serial console in this terminal, in real time (or as fast as
    the host can go, with --fast). Ctrl-] ends it; the card's contents
    are kept in build/fen/disk.img."""
    import select
    import termios
    import tty
    disk_path = os.path.join(build.OUT, "disk.img")
    disk = None
    if os.path.exists(disk_path) and not args.fresh:
        with open(disk_path, "rb") as f:
            disk = f.read()
    print("building...", file=sys.stderr)
    s = Session(serial=True, disk=disk, clock_hz=args.mhz * 1e6)
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd) if os.isatty(fd) else None
    if old:
        tty.setraw(fd)
    print("Fen on the simulated Heron: Ctrl-] to quit\r", file=sys.stderr)
    t0 = time.monotonic()
    sim0 = s.ms
    shown = 0
    try:
        while True:
            r, _, _ = select.select([fd], [], [], 0)
            if r:
                data = os.read(fd, 64)
                if b"\x1d" in data:
                    break
                s.type(data.replace(b"\n", b"\r"))
            if args.fast:
                s.run(20)
            else:
                # keep simulated time with real time
                ahead = (s.ms - sim0) / 1000 - (time.monotonic() - t0)
                if ahead > 0:
                    time.sleep(min(ahead, 0.02))
                s.run(10)
            if len(s.out) > shown:
                os.write(sys.stdout.fileno(), bytes(s.out[shown:]))
                shown = len(s.out)
    finally:
        if old:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        with open(disk_path, "wb") as f:
            f.write(s.cf_image())
        print("\nthe card is saved in", os.path.relpath(disk_path), file=sys.stderr)
    return 0
