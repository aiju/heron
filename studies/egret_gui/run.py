"""Running the GUI without a browser: a session drives the simulated
machine with input events, by the clock (3 MHz of the reference
configuration's cycles), and looks at its screen. The tests use it, and
so does `heron egret_gui shot`.
"""

import struct
import zlib

from heron import native

from . import build

RAM_SIZE = 0x100000
CLOCK_HZ = 3_000_000
TICK = CLOCK_HZ // 60
W, H = 640, 480

# event kinds (studies/v1_isa/isa/src/display.rs)
KEY_DOWN, KEY_UP, BUTTON_DOWN, BUTTON_UP, WHEEL = 1, 2, 3, 4, 5
KEYS = {"backspace": 8, "tab": 9, "return": 13, "enter": 13, "escape": 27, "delete": 127,
        "left": 0x100, "right": 0x101, "up": 0x102, "down": 0x103, "home": 0x104,
        "end": 0x105, "pageup": 0x106, "pagedown": 0x107}
MODS = {"shift": 1, "ctrl": 2, "alt": 4, "meta": 8}


class Halted(Exception):
    pass


def ram_image(img):
    ram = bytearray(RAM_SIZE)
    for addr, b in img.mem.items():
        ram[addr] = b
    return bytes(ram)


class Session:
    """The machine running the desktop (or another program, `source`)."""

    def __init__(self, source=None, depth=3, time_of_day=10 * 3600 + 8 * 60):
        inp = build.console_input(depth, source)
        self.m = native.v1.Machine("v1b", ram_image(build.image()), inp)
        self.m.time_of_day = time_of_day
        self.mouse = (0, 0)
        self.buttons = 0

    # ---- running

    @property
    def cycles(self):
        return self.m.cycles

    @property
    def seconds(self):
        return self.m.cycles / CLOCK_HZ

    def run(self, seconds=None, cycles=None):
        """Run for a while of machine time."""
        if cycles is None:
            cycles = int(seconds * CLOCK_HZ)
        if self.m.run_until(self.m.cycles + cycles):
            raise Halted(f"the machine halted at {self.m.pc:08X}:\n{self.output}")
        return self

    def boot(self, limit=60.0):
        """Run until the desktop is up: the first time it waits for input
        (it has written 'ready' to the console)."""
        end = self.m.cycles + int(limit * CLOCK_HZ)
        while b"ready\n" not in self.m.out:
            if self.m.cycles > end:
                raise Halted(f"not up after {limit} s:\n{self.output}")
            self.run(cycles=TICK)
        return self

    @property
    def output(self):
        return self.m.out.decode("latin-1")

    # ---- input

    def event(self, e):
        self.m.push_event(e)

    def move(self, x, y):
        self.mouse = (x, y)
        self.m.set_mouse(x, y, self.buttons)

    def key(self, key, mods=(), dt=0.05):
        """A key: a character, or a name from KEYS; mods from MODS."""
        code = KEYS[key] if len(key) > 1 else ord(key)
        m = sum(MODS[x] for x in mods)
        self.event(KEY_DOWN << 28 | m << 16 | code)
        self.event(KEY_UP << 28 | m << 16 | code)
        self.run(dt)

    def type(self, text, dt=0.05):
        for ch in text:
            self.key("return" if ch == "\n" else ch, dt=dt)

    def press(self, x, y, button=0):
        self.move(x, y)
        self.buttons |= 1 << button
        self.m.set_mouse(x, y, self.buttons)
        self.event(BUTTON_DOWN << 28 | button << 24 | y << 12 | x)

    def release(self, x, y, button=0):
        self.move(x, y)
        self.buttons &= ~(1 << button)
        self.m.set_mouse(x, y, self.buttons)
        self.event(BUTTON_UP << 28 | button << 24 | y << 12 | x)

    def click(self, x, y, button=0, dt=0.3):
        self.press(x, y, button)
        self.run(1 / 30)
        self.release(x, y, button)
        self.run(dt)

    def drag(self, x0, y0, x1, y1, steps=8, dt=0.3):
        self.press(x0, y0)
        self.run(1 / 30)
        for k in range(1, steps + 1):
            self.move(x0 + (x1 - x0) * k // steps, y0 + (y1 - y0) * k // steps)
            self.run(1 / 30)
        self.release(x1, y1)
        self.run(dt)

    # ---- the screen

    def rgb(self):
        return self.m.screen_rgb()

    def png(self, path):
        write_png(path, self.rgb(), W, H)


def write_png(path, rgb, w, h):
    rows = b"".join(b"\0" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(kind, data):
        c = kind + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
