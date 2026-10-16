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
        write_png(path, self.screen(), 640, 480)

    # ---- the keyboard and the mouse ----

    mx, my = 320, 240       # where wsys starts the cursor

    def press(self, name, mods=(), ms=8):
        """Press and let go of a key, by its browser name ("KeyA",
        "Enter"), with modifiers ("ShiftLeft", "ControlLeft") held."""
        codes = [native.fen.scancode(m) for m in mods]
        code = native.fen.scancode(name)
        if code is None or None in codes:
            raise ValueError(f"no key {name!r}")
        for m in codes:
            self.c.key(m, True)
        self.c.key(code, True)
        self.run(ms)
        self.c.key(code, False)
        for m in reversed(codes):
            self.c.key(m, False)
        self.run(ms)

    def keys(self, text, ms=8):
        """Type text on the keyboard (a US layout)."""
        for ch in text:
            name, shift = key_name(ch)
            self.press(name, ("ShiftLeft",) if shift else (), ms)

    def mouse_to(self, x, y, buttons=0):
        """Move the mouse to (x, y) on the screen with buttons held (bit 0
        the left one), and run until it has got there. A sample is at most
        255 counts each way and a mouse drops what it can't send (as a PS/2
        one does), so a long way goes in steps, a sample (25 ms) each."""
        x, y = max(0, min(639, x)), max(0, min(479, y))
        while (self.mx, self.my) != (x, y):
            dx = max(-200, min(200, x - self.mx))
            dy = max(-200, min(200, y - self.my))
            self.c.mouse(dx, -dy, buttons)
            self.mx, self.my = self.mx + dx, self.my + dy
            self.run(30)
        self.c.mouse(0, 0, buttons)
        self.run(30)

    def click(self, x, y, button=1, ms=60):
        self.mouse_to(x, y)
        self.c.mouse(0, 0, button)
        self.run(ms)
        self.c.mouse(0, 0, 0)
        self.run(ms)

    def drag(self, x0, y0, x1, y1, button=1):
        self.mouse_to(x0, y0)
        self.c.mouse(0, 0, button)
        self.run(60)
        self.mouse_to(x1, y1, button)
        self.c.mouse(0, 0, 0)
        self.run(60)

    def cf_image(self):
        return bytes(self.c.cf_image())


_SHIFTED = dict(zip('!@#$%^&*()', '1234567890'))
_PUNCT = {" ": "Space", "\n": "Enter", "\t": "Tab", "\b": "Backspace", "-": "Minus",
          "=": "Equal", "[": "BracketLeft", "]": "BracketRight", "\\": "Backslash",
          ";": "Semicolon", "'": "Quote", ",": "Comma", ".": "Period", "/": "Slash",
          "`": "Backquote"}
_PUNCT_SHIFTED = {"_": "-", "+": "=", "{": "[", "}": "]", "|": "\\", ":": ";", '"': "'",
                  "<": ",", ">": ".", "?": "/", "~": "`"}


def key_name(ch):
    """The key for a character on a US keyboard, and whether it's shifted."""
    if ch.isascii() and ch.isalpha():
        return "Key" + ch.upper(), ch.isupper()
    if ch.isdigit():
        return "Digit" + ch, False
    if ch in _SHIFTED:
        return "Digit" + _SHIFTED[ch], True
    if ch in _PUNCT:
        return _PUNCT[ch], False
    if ch in _PUNCT_SHIFTED:
        return _PUNCT[_PUNCT_SHIFTED[ch]], True
    raise ValueError(f"no key for {ch!r}")


def write_png(path, rgb, w, h):
    """RGB bytes as a PNG file."""
    import struct
    import zlib
    raw = b"".join(b"\0" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


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
