"""Running a program on the mini's simulator (studies/mini/sim.py) frame
by frame: input from a script, the console's marks, screenshots, and a
profile by sampling the PC.

A script is a list of steps, each (frame, verb, args...), or the same as
lines of text ("30 click 120 200"); the frame counts from the run's start:

    mouse X Y               the mouse moves there
    down B / up B           mouse button B (1 left, 2 right, 4 middle)
    click X Y [B]           moves, presses, releases a frame later
    drag X0 Y0 X1 Y1 N      pressed at the first, moved over N frames, released
    key NAME                a key pressed and released (a character, or enter,
                            esc, up, ...: KEYS)
    keydown NAME / keyup NAME
    type TEXT               the text, a character a frame
    shot NAME               a screenshot of this frame
    stop                    the end of the run

The program's console lines that start with '@' are for the harness:

    @mark NAME CYCLES       a mark (rt_mark), kept with the frame it came in
    @perf NAME VALUES...    a measurement (rt/perf.h): ticks of 19.86 ns
    @shot NAME              a screenshot of the frame two after (rt_shot)
    @done                   the end of the run
    @trap ...               a trap (rt/start.s): the run stops
"""

import bisect
import os
import shlex

from heron.studies.mini import sim
from heron.studies.mini.timing import TICK

KEYS = {"backspace": 8, "tab": 9, "enter": 13, "up": 0x11, "down": 0x12, "left": 0x13,
        "right": 0x14, "shift": 0x15, "ctrl": 0x16, "alt": 0x17, "esc": 27, "pgup": 0x1C,
        "pgdn": 0x1D, "home": 0x1E, "end": 0x1F, "del": 0x7F, "space": 32,
        **{f"f{n}": n for n in range(1, 8)}}
SHIFTED = dict(zip('~!@#$%^&*()_+{}|:"<>?', "`1234567890-=[]\\;',./"))


def key_code(name):
    if name in KEYS:
        return KEYS[name], False
    if len(name) == 1:
        c = name
        if "A" <= c <= "Z":
            return ord(c.lower()), True
        if c in SHIFTED:
            return ord(SHIFTED[c]), True
        return ord(c), False
    raise ValueError(f"no key {name!r}")


def parse_script(text):
    steps = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        frame, verb, *rest = line.split(None, 2)
        if verb == "type":
            args = [rest[0]] if rest else [""]
        else:
            args = shlex.split(rest[0]) if rest else []
            args = [int(a) if a.lstrip("-").isdigit() else a for a in args]
        steps.append((int(frame), verb, *args))
    return steps


class Mark:
    def __init__(self, name, cycles, frame, ticks):
        self.name, self.cycles, self.frame, self.ticks = name, cycles, frame, ticks


class Result:
    """What a run did."""

    def __init__(self):
        self.status = None
        self.frames = 0
        self.marks = []             # [Mark]
        self.perf = {}              # name -> [numbers] (@perf lines)
        self.shots = {}             # name -> (w, h, rgb565 bytes)
        self.output = ""            # the console, but the harness's lines
        self.lines = []             # every console line
        self.trap = None
        self.profile = None         # {function: samples}
        self.stats = {}
        self.frame_ticks = []       # the CPU's ticks at each frame's end

    def mark(self, name):
        for m in self.marks:
            if m.name == name:
                return m
        raise KeyError(name)


class Session:
    def __init__(self, build, layout="L0", bandwidth="B0", pokes=None):
        self.build = build
        self.layout, self.bandwidth = layout, bandwidth
        mc = None
        if build.variant == "wif":
            from . import whatif
            mc = whatif.extended()
        self.m = sim.machine(layout=layout, bandwidth=bandwidth, mc=mc)
        sim.load(self.m, build.img)
        # the board's layout for the library (gfx/format.c), and the run's variables
        pokes = dict(pokes or {})
        pokes.setdefault("_board_layout", 1 if layout == "L1" else 0)
        for name, value in pokes.items():
            if name in build.symbols:
                self.m.load(build.symbols[name], (value & 0xFFFFFFFF).to_bytes(4, "little"))
            elif name != "_board_layout":
                raise KeyError(f"{name}: not in the program")
        self.buttons = 0
        self.mx = self.my = 0
        self.out_pos = 0
        self.partial = ""
        # functions only: the labels without a local part
        funcs = [(a, n) for a, n in build.labels if "." not in n]
        self.addrs = [a for a, _ in funcs]
        self.funcs = funcs

    # ---- input ----
    def send(self, data):
        self.m.uart_input(bytes(data), 1)

    def mouse(self, x, y, buttons=None):
        if buttons is not None:
            self.buttons = buttons
        self.mx, self.my = max(0, x), max(0, y)
        self.send([0x82, self.buttons & 7, self.mx & 127, self.mx >> 7 & 127, self.my & 127,
                   self.my >> 7 & 127])

    def key(self, name, down=None):
        k, shift = key_code(name)
        seq = []
        if down is None:
            if shift:
                seq += [0x80, KEYS["shift"]]
            seq += [0x80, k, 0x81, k]
            if shift:
                seq += [0x81, KEYS["shift"]]
        else:
            seq += [0x80 if down else 0x81, k]
        self.send(seq)

    # ---- running ----
    def _console(self, res, frame):
        out = self.m.output()
        new = out[self.out_pos:].decode("latin-1")
        self.out_pos = len(out)
        text = self.partial + new
        lines = text.split("\n")
        self.partial = lines.pop()
        events = []
        for ln in lines:
            res.lines.append(ln)
            if ln.startswith("@"):
                events.append(ln[1:].split())
            else:
                res.output += ln + "\n"
        return events

    def where(self, pc):
        i = bisect.bisect_right(self.addrs, pc) - 1
        return self.funcs[i][1] if i >= 0 else "?"

    def run(self, frames=600, script=(), shots_dir=None, profile=0, max_cycles=2_000_000_000,
            on_frame=None):
        """Run for `frames` frames at most; returns a Result. profile: sample
        the PC every that many cycles."""
        m, res = self.m, Result()
        if isinstance(script, str):
            script = parse_script(script)
        steps = sorted(script, key=lambda s: s[0])
        pending = []                # (frame, action) for later frames: releases, drags
        shot_at = {}                # frame -> name
        si = 0
        prof = {}
        start_frame = m.frames
        for f in range(frames):
            # the steps for this frame
            while si < len(steps) and steps[si][0] <= f:
                self._step(steps[si], f, pending, shot_at, res)
                si += 1
            for p in [p for p in pending if p[0] <= f]:
                pending.remove(p)
                p[1]()
            target = m.frames + 1
            while m.frames < target:
                if profile:
                    st = m.run(min(m.cycles + profile, max_cycles), frames=1)
                    fn = self.where(m.pc)
                    prof[fn] = prof.get(fn, 0) + 1
                else:
                    st = m.run(max_cycles, frames=1)
                if st != "frames" and st != "limit":
                    break
                if st == "limit" and m.cycles >= max_cycles:
                    break
            res.frame_ticks.append(m.ticks)
            events = self._console(res, f)
            done = False
            for ev in events:
                if ev[0] == "mark":
                    res.marks.append(Mark(ev[1], int(ev[2]) if len(ev) > 2 else 0, f, m.ticks))
                elif ev[0] == "perf":
                    res.perf[ev[1]] = [int(v) for v in ev[2:]]
                elif ev[0] == "shot":
                    shot_at[f + 2] = ev[1]
                elif ev[0] == "done":
                    done = True
                elif ev[0] == "trap":
                    res.trap = " ".join(ev[1:])
                    done = True
            if f in shot_at and m.frames > start_frame:
                res.shots[shot_at.pop(f)] = m.frame()
            if on_frame:
                on_frame(self, f)
            if m.halted:
                res.status = "halted"
                break
            if done or (si >= len(steps) and steps and steps[-1][1] == "stop" and f >= steps[-1][0]):
                res.status = "done"
                break
        else:
            res.status = "frames"
        res.frames = m.frames - start_frame
        self._console(res, frames)
        if self.partial:
            res.output += self.partial
        if shots_dir:
            os.makedirs(shots_dir, exist_ok=True)
            for name, fr in res.shots.items():
                if fr:
                    sim.write_png(os.path.join(shots_dir, f"{name}.png"), *fr)
        if profile:
            res.profile = prof
        res.stats = {"cycles": m.cycles, "ticks": m.ticks, "ms": m.ticks * TICK / 1e6,
                     "instructions": m.instructions, "steal_ticks": m.steal_ticks,
                     "underruns": m.underruns, "line_irqs": m.line_irqs, "frames": m.frames}
        return res

    def _step(self, step, f, pending, shot_at, res):
        verb, args = step[1], step[2:]
        if verb == "mouse":
            self.mouse(args[0], args[1])
        elif verb == "down":
            self.mouse(self.mx, self.my, self.buttons | args[0])
        elif verb == "up":
            self.mouse(self.mx, self.my, self.buttons & ~args[0])
        elif verb == "click":
            b = args[2] if len(args) > 2 else 1
            self.mouse(args[0], args[1], self.buttons | b)
            pending.append((f + 1, lambda: self.mouse(self.mx, self.my, self.buttons & ~b)))
        elif verb == "drag":
            x0, y0, x1, y1, n = args[:5]
            self.mouse(x0, y0, self.buttons | 1)
            for k in range(1, n + 1):
                x, y = x0 + (x1 - x0) * k // n, y0 + (y1 - y0) * k // n
                pending.append((f + k, lambda x=x, y=y: self.mouse(x, y)))
            pending.append((f + n + 1, lambda: self.mouse(self.mx, self.my, self.buttons & ~1)))
        elif verb == "key":
            self.key(str(args[0]))
        elif verb == "keydown":
            self.key(str(args[0]), True)
        elif verb == "keyup":
            self.key(str(args[0]), False)
        elif verb == "type":
            for k, ch in enumerate(args[0]):
                pending.append((f + k, lambda ch=ch: self.key(" " if ch == " " else ch)))
        elif verb == "shot":
            shot_at[f] = args[0]
        elif verb == "stop":
            pass
        else:
            raise ValueError(f"script: no verb {verb!r}")


def frame_png(path, frame):
    sim.write_png(path, *frame)
