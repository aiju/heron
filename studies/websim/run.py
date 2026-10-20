"""A machine of the simulator run here rather than in a browser: the same
engine (heron.native.websim), made from the same description, for the
tests, `heron websim check` and `heron websim run`.
"""

import os
import select
import sys

from heron import native

from . import machines as M


class Timeout(Exception):
    pass


class Running:
    """A machine at power-on. Time is simulated: `run(ms)`."""

    def __init__(self, m, build=None):
        self.m = m
        b = build or m.make()
        self.s = native.websim.Session(b.board, M.params_now(b.params), b.loads)
        self.out = bytearray()
        self.log = bytearray()
        self.mark = 0
        self.status = None

    @property
    def ms(self):
        return self.s.cycles / self.s.clock_hz * 1000

    def run(self, ms):
        """Run for `ms` simulated milliseconds, or until it waits for the
        terminal or halts."""
        self.status = self.s.run(int(self.s.clock_hz * ms / 1000))
        self.out += self.s.output()
        self.log += self.s.log()
        return self.status

    def send(self, text):
        self.s.send(text.encode() if isinstance(text, str) else text)

    def expect(self, text, timeout_ms=30_000):
        """Run until the terminal has printed `text` since the last one
        expected; what it printed up to its end."""
        want = text.encode() if isinstance(text, str) else text
        start = self.ms
        while True:
            i = self.out.find(want, self.mark)
            if i >= 0:
                got = bytes(self.out[self.mark:i + len(want)])
                self.mark = i + len(want)
                return got.decode(errors="replace")
            if self.status in ("waiting", "halted", "idle") and self.ms > start:
                why = f"it's {self.status}"
            elif self.ms - start > timeout_ms:
                why = f"not after {timeout_ms} ms"
            else:
                self.run(20)
                continue
            raise Timeout(f"{self.m.id}: no {text!r} ({why}); the terminal has:\n"
                          + self.out[self.mark:].decode(errors="replace")
                          + ("\nthe log:\n" + self.log.decode(errors="replace") if self.log else ""))

    def screen_varied(self):
        """Whether the screen shows something: more than one colour."""
        px = self.s.screen(True)
        return px is not None and len({px[i:i + 3] for i in range(0, len(px), 4 * 97)}) > 1


def check(m, build=None):
    """Do what the machine's `check` says; what the terminal printed."""
    r = Running(m, build)
    for step in m.check:
        if step[0] == "expect":
            r.expect(step[1])
        elif step[0] == "send":
            r.send(step[1])
            r.status = None
        elif step[0] == "run":
            r.run(step[1])
        elif step[0] == "screen":
            if not r.screen_varied():
                raise AssertionError(f"{m.id}: the screen is blank")
        else:
            raise ValueError(f"{m.id}: no check step {step[0]!r}")
    return r.out.decode(errors="replace")


def console(m):
    """The machine's terminal in this one, until it halts or ^] (raw) or the
    end of the input (line). Line machines read a line at a time here; raw
    ones get every key."""
    r = Running(m)
    raw = (m.terminal or {}).get("mode") == "raw" and sys.stdin.isatty()
    old = None
    if raw:
        import termios
        import tty
        old = termios.tcgetattr(sys.stdin)
        tty.setraw(sys.stdin)
    try:
        while True:
            st = r.run(20)
            if r.out[r.mark:]:
                text = bytes(r.out[r.mark:])
                r.mark = len(r.out)
                sys.stdout.buffer.write(text.replace(b"\n", b"\r\n") if raw else text)
                sys.stdout.flush()
            if st == "halted":
                return 0
            ready, _, _ = select.select([sys.stdin], [], [], 0 if st == "ran" else 0.05)
            if not ready:
                continue
            if raw:
                data = os.read(sys.stdin.fileno(), 64)
                if b"\x1d" in data:
                    return 0
                r.send(data)
            else:
                line = sys.stdin.buffer.readline()
                if not line:
                    r.s.close()
                else:
                    r.send(line)
    finally:
        if old is not None:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)
            print()
