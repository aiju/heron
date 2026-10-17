"""timing: timing diagrams, event by event.

After Emily's timepic(1): a signal is its values at times, times are
expressions with units, and a time can be named and measured from.

    ns = 1/60                      # a unit: the grid is in clocks of 60 ns
    .grid 1 'BCLK edge'            # a line and a number at every clock
    .range 0 11
    BCLK  11{:1 +.5:0 +.5}         # 11 times: high, then low half a clock on
    SEL   :0 1.1[on]:1 9.1[off]|:0 # low; at 1.1 (call it on) high; ...
    WAIT  :1 on+25ns[w]:0 5.4[r]:1
      <-> on w '≤ 30 ns'           # an interval under the row above
    D     :z 5.2[d]:'read data' off+.15:z
      ^ off 'taken'                # a pointer under the row above
    d -> r 'then released'         # an arrow from one named edge to another

A value is 0, 1, x (unknown, hatched), z (floating) or anything else,
which is a bus's value and its label. | before a value draws a dashed line
across the diagram at it. Statements end at a newline or ;, # starts a
comment. .width and .row set the size in pixels.
"""

import re

from .svg import Drawing, Error, textwidth

LOW, HIGH, UNKNOWN, FLOAT, BUS = "0", "1", "x", "z", "bus"

# ---------------------------------------------------------------- lexer

TOKEN = re.compile(r"""
    (?P<ws>[ \t\r]+)
  | (?P<comment>\#[^\n]*)
  | (?P<nl>\n)
  | (?P<str>'(?:[^'\n]|'')*'|"[^"\n]*")
  | (?P<num>\d+(?:\.\d*)?|\.\d+)
  | (?P<name>[^\W\d]\w*|[\u0080-\U0010FFFF][\w\u0080-\U0010FFFF]*)
  | (?P<op><->|->|[-+*/():;\[\]{}|^=.])
""", re.X)


def lex(text):
    """Tokens (kind, value, line, glued): glued is true when nothing
    separates a token from the one before, so 3c is 3 times c. A newline
    ends a statement except inside brackets."""
    pos, line, depth, end = 0, 1, 0, -1
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            raise Error(f"line {line}: unexpected {text[pos]!r}")
        kind, s = m.lastgroup, m.group()
        glued = m.start() == end
        pos = end = m.end()
        if kind in ("ws", "comment"):
            continue
        if kind == "nl":
            line += 1
            if depth == 0:
                yield "nl", s, line - 1, False
            continue
        if kind == "str":
            s = s[1:-1].replace("''", "'") if s[0] == "'" else s[1:-1]
        elif kind == "num":
            s = float(s)
        elif kind == "op":
            kind = s
            depth += s in "({[" and 1 or s in ")}]" and -1 or 0
        yield kind, s, line, glued
    yield "nl", "\n", line, False
    yield "eof", None, line, False


# ---------------------------------------------------------------- parser

class Signal:
    def __init__(self, name):
        self.name = name
        self.events = []        # [time, value, label, marked]
        self.notes = []         # ("<->", a, b, label) or ("^", a, None, label)


class Parser:
    def __init__(self, text):
        self.toks = list(lex(text))
        self.i = 0
        self.syms = {}          # constants and named times
        self.edges = {}         # named time -> (time, row)
        self.signals = []
        self.arrows = []        # (from, to, label, line)
        self.width, self.row = 640, 36
        self.grid = None        # (step, caption)
        self.range = None

    # tokens
    def peek(self, k=0):
        return self.toks[self.i + k]

    def next(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def err(self, msg, tok=None):
        raise Error(f"line {(tok or self.peek())[2]}: {msg}")

    def expect(self, kind):
        t = self.next()
        if t[0] != kind:
            self.err(f"expected {kind}, found {t[1]!r}", t)
        return t

    # expressions are trees, evaluated when the names in them are known
    def factor(self):
        t = self.next()
        if t[0] == "num":
            u = self.peek()
            if u[0] == "name" and u[3]:  # 3c: c is a unit
                self.next()
                return ("*", ("n", t[1]), ("s", u[1], u[2]))
            return ("n", t[1])
        if t[0] == "name":
            return ("s", t[1], t[2])
        if t[0] == "(":
            e = self.expr()
            self.expect(")")
            return e
        if t[0] == "-":
            return ("-", ("n", 0.0), self.factor())
        self.err(f"expected a number, found {t[1]!r}", t)

    def term(self):
        e = self.factor()
        while self.peek()[0] in ("*", "/"):
            e = (self.next()[0], e, self.factor())
        return e

    def expr(self):
        e = self.term()
        while self.peek()[0] in ("+", "-"):
            e = (self.next()[0], e, self.term())
        return e

    def eval(self, e):
        if e[0] == "n":
            return e[1]
        if e[0] == "s":
            if e[1] not in self.syms:
                raise Error(f"line {e[2]}: {e[1]} isn't defined")
            return self.syms[e[1]]
        a, b = self.eval(e[1]), self.eval(e[2])
        return {"+": a + b, "-": a - b, "*": a * b, "/": a / b if b else float("nan")}[e[0]]

    def label(self):
        """An optional label: a string, or a word or number."""
        t = self.peek()
        if t[0] in ("str", "name"):
            return self.next()[1]
        if t[0] == "num":
            return f"{self.next()[1]:g}"
        return None

    def end(self):
        t = self.next()
        if t[0] not in ("nl", ";"):
            self.err(f"unexpected {t[1]!r}", t)

    # statements
    def parse(self):
        later = []              # notes and arrows: their names may come later
        while self.peek()[0] != "eof":
            t, u = self.peek(), self.peek(1)
            if t[0] in ("nl", ";"):
                self.next()
            elif t[0] == "." and u[0] == "name" and u[3]:
                self.next(), self.next()
                self.directive(u)
            elif t[0] in ("<->", "^"):
                if not self.signals:
                    self.err(f"{t[0]} belongs under a signal")
                self.next()
                a = self.expr()
                b = self.expr() if t[0] == "<->" else None
                later.append((self.signals[-1].notes, (t[0], a, b, self.label())))
                self.end()
            elif t[0] == "name" and u[0] == "=":
                self.next(), self.next()
                if t[1] in self.syms:
                    self.err(f"{t[1]} is already defined", t)
                self.syms[t[1]] = self.eval(self.expr())
                self.end()
            elif t[0] == "name" and u[0] == "->":
                self.next(), self.next()
                b = self.expect("name")
                later.append((None, (t[1], b[1], self.label(), t[2])))
                self.end()
            elif t[0] in ("name", "str"):
                self.next()
                self.signal(t[1])
            else:
                self.err(f"unexpected {t[1]!r}")
        for notes, item in later:
            if notes is None:
                for name in item[:2]:
                    if name not in self.edges:
                        raise Error(f"line {item[3]}: no edge is named {name}")
                self.arrows.append(item)
            else:
                kind, a, b, label = item
                notes.append((kind, self.eval(a), b and self.eval(b), label))
        return self

    def directive(self, t):
        if t[1] == "width":
            self.width = self.eval(self.expr())
        elif t[1] == "row":
            self.row = self.eval(self.expr())
        elif t[1] == "grid":
            self.grid = (self.eval(self.expr()), self.label())
        elif t[1] == "range":
            self.range = (self.eval(self.expr()), self.eval(self.expr()))
        else:
            self.err(f"no such directive: .{t[1]}", t)
        self.end()

    def signal(self, name):
        s = Signal(name)
        self.signals.append(s)
        self.events(s, 0.0, False)
        self.end()

    def events(self, s, off, inner):
        """Read events into s.events until the statement or a } ends;
        return the time after the last."""
        marked = False
        while True:
            t = self.peek()
            if t[0] in ("nl", ";", "}", "eof"):
                return off
            if t[0] == ":":
                self.next()
                v = self.value()
                if s.events and off < s.events[-1][0]:
                    self.err(f"{s.name} goes back in time, to {off:g}", t)
                s.events.append([off, v[0], v[1], marked])
                marked = False
            elif t[0] == "|":
                self.next()
                marked = True
            elif t[0] == "+":
                self.next()
                off += self.eval(self.term())
                self.bind(s, off, inner)
            else:
                e = self.expr()
                if self.peek()[0] == "{":
                    self.next()
                    n = self.eval(e)
                    if n != int(n) or n < 0:
                        self.err(f"can't repeat {n:g} times")
                    body = Signal(s.name)
                    length = self.events(body, 0.0, True)
                    self.expect("}")
                    for _ in range(int(n)):
                        for ev in body.events:
                            if s.events and off + ev[0] < s.events[-1][0]:
                                self.err(f"{s.name} goes back in time")
                            s.events.append([off + ev[0]] + ev[1:])
                        off += length
                    continue
                if inner:
                    self.err("times inside { } are relative: write +")
                off = self.eval(e)
                self.bind(s, off, inner)

    def bind(self, s, off, inner):
        if self.peek()[0] != "[":
            return
        t = self.next()
        if inner:
            self.err("can't name a time inside { }", t)
        n = self.expect("name")
        self.expect("]")
        if n[1] in self.syms:
            self.err(f"{n[1]} is already defined", n)
        self.syms[n[1]] = off
        self.edges[n[1]] = (off, len(self.signals) - 1)

    def value(self):
        t = self.next()
        if t[0] == "num" and t[1] in (0, 1):
            return (LOW if t[1] == 0 else HIGH), None
        if t[0] == "name" and t[1] in (UNKNOWN, FLOAT):
            return t[1], None
        if t[0] in ("name", "str"):
            return BUS, t[1]
        if t[0] == "num":
            return BUS, f"{t[1]:g}"
        self.err(f"expected a value, found {t[1]!r}", t)


# ---------------------------------------------------------------- drawing

TW = 2.5     # half an edge's width
LANE = 20    # a lane of notes under a row


def render(text):
    p = Parser(text).parse()
    if not p.signals:
        raise Error("no signals")
    W, R = p.width, p.row
    HEAD, PAD = (18 if p.grid else 6), 10
    times = [e[0] for s in p.signals for e in s.events] + [0.0]
    times += [t for s in p.signals for n in s.notes for t in (n[1], n[2]) if t is not None]
    left, right = p.range or (min(times), max(times))
    if right <= left:
        raise Error("the diagram has no length: give .range")
    gutter = max([textwidth(s.name, 12, 600) for s in p.signals] +
                 [textwidth(p.grid[1], 10) if p.grid and p.grid[1] else 0]) + 18
    x0, x1 = gutter, W - PAD
    scale = (x1 - x0) / (right - left)

    def X(t):
        return x0 + (t - left) * scale

    d, over = Drawing(), Drawing()

    # rows, and the lanes of notes under them
    lanes, y = [], HEAD
    for s in p.signals:
        packed = []
        for n in s.notes:
            kind, a, b, label = n
            w = textwidth(label, 11) if label else 0
            if kind == "<->":
                xa, xb = sorted((X(a), X(b)))
                inside = w + 10 <= xb - xa
                lo, hi = (xa, xb) if inside else (xa, xb + 5 + w)
                if not inside and hi > W:
                    lo, hi = xa - 5 - w, xb
            else:
                xa = X(a)
                lo, hi = xa - 4, xa + 6 + w
                if hi > W:
                    lo, hi = xa - 6 - w, xa + 4
            for lane in packed:
                if all(hi + 8 <= l or lo >= h + 8 for l, h, _ in lane):
                    lane.append((lo, hi, n))
                    break
            else:
                packed.append([(lo, hi, n)])
        lanes.append((y, packed))
        y += R + LANE * len(packed)
    H = y + 4
    rows = {i: (top, top + R * 0.25, top + R * 0.75) for i, (top, _) in enumerate(lanes)}

    if p.grid:
        step, cap = p.grid
        k = int(-(-left // step))
        while k * step <= right + 1e-9:
            gx = X(k * step)
            d.line(gx, HEAD - 2, gx, H - 4, "grid")
            d.text(f"{k}", gx, HEAD / 2 - 1, "xs", 10, "middle")
            k += 1
        if cap:
            d.text(cap, 0, HEAD / 2 - 1, "xs", 10)

    for i, s in enumerate(p.signals):
        top, t, b = rows[i]
        m = (t + b) / 2
        d.text(s.name, 0, m, "b", 12, weight=600)
        ev = list(s.events)
        if not ev:
            continue
        # clip to the range: the value at left, then what follows
        while len(ev) > 1 and ev[1][0] <= left:
            ev.pop(0)
        ev[0] = [left] + ev[0][1:] if ev[0][0] < left else ev[0]
        ev = [e for e in ev if e[0] < right] + [[right, None, None, False]]
        for j in range(len(ev) - 1):
            (ta, v, label, _), (tb, nv, _, mk) = ev[j], ev[j + 1]
            xa, xb = X(ta), X(tb)
            tw = min(TW, (xb - xa) / 2)
            first, last = j == 0 and ta <= left, nv is None
            if mk:
                over.line(xb, HEAD, xb, H - 4, "spot dashed")

            def rail(y):
                pts = [(xa, y)] if first else [(xa, m), (xa + tw, y)]
                return pts + ([(xb, y)] if last else [(xb - tw, y), (xb, m)])

            if v in (LOW, HIGH):
                d.path(rail(b if v == LOW else t))
            elif v == FLOAT:
                d.path([(xa, m), (xb, m)])
            else:
                upper, lower = rail(t), rail(b)
                d.path(upper + lower[::-1], "hatch" if v == UNKNOWN else "paper", close=True)
                d.path(upper)
                d.path(lower)
                if v == BUS and label:
                    if textwidth(label, 11.5, mono=True) <= xb - xa - 2 * tw - 6:
                        d.text(label, (xa + xb) / 2, m, "m", 11.5, "middle", mono=True)

    # notes: intervals and pointers
    for i, (top, packed) in enumerate(lanes):
        _, _, b = rows[i]
        for k, lane in enumerate(packed):
            ly = top + R + LANE * k + LANE / 2 - 2
            for lo, hi, (kind, a, bb, label) in lane:
                if kind == "<->":
                    xa, xb = X(a), X(bb)
                    for tt, xx in ((a, xa), (bb, xb)):
                        ty = b + 2   # from the edge it measures, if it's named
                        for et, row in p.edges.values():
                            if abs(et - tt) < 1e-9:
                                ty = sum(rows[row][1:]) / 2 if row != i else b + 2
                                break
                        d.line(xx, min(ty, ly + 4), xx, max(ty, ly + 4), "dotted")
                    xa, xb = sorted((xa, xb))
                    d.line(xa, ly, xb, ly, "thin")
                    d.arrowhead(xa, ly, -1, 0, "solid-2")
                    d.arrowhead(xb, ly, 1, 0, "solid-2")
                    if label:
                        if textwidth(label, 11) + 10 <= xb - xa:
                            d.text(label, (xa + xb) / 2, ly - 7, "s", 11, "middle")
                        elif lo < xa:
                            d.text(label, xa - 5, ly, "s", 11, "end")
                        else:
                            d.text(label, xb + 5, ly, "s", 11)
                else:
                    xa = X(a)
                    d.line(xa, ly + 6, xa, b + 3, "thin")
                    d.arrowhead(xa, b + 3, 0, -1, "solid-2")
                    if label:
                        if lo < xa - 5:
                            d.text(label, xa - 5, ly + 1, "s", 11, "end")
                        else:
                            d.text(label, xa + 5, ly + 1, "s", 11)

    # arrows from edge to edge
    for a, bname, label, _ in p.arrows:
        (ta, ra), (tb, rb) = p.edges[a], p.edges[bname]
        xa, xb = X(ta), X(tb)
        ya, yb = sum(rows[ra][1:]) / 2, sum(rows[rb][1:]) / 2
        over.circle(xa, ya, 2, "solid-spot")
        if abs(xb - xa) < 2 * abs(yb - ya):
            # steep: straight, stopping at the edge
            n = ((xb - xa) ** 2 + (yb - ya) ** 2) ** 0.5
            ex, ey = xb - 2 * (xb - xa) / n, yb - 2 * (yb - ya) / n
            over.path([(xa, ya), (ex, ey)], "spot")
            over.arrowhead(ex, ey, xb - xa, yb - ya, "solid-spot")
            mx = (xa + xb) / 2
        else:
            # shallow: leave and arrive level, like the signals
            h = abs(xb - xa) / 2
            c1, c2 = (xa + h, ya), (xb - h, yb)
            over.curve(f"M{xa:.1f} {ya:.1f} C{c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} {xb - 2:.1f} {yb:.1f}",
                       [(xa, ya), (xb, yb)], "spot")
            over.arrowhead(xb - 2, yb, 1, 0, "solid-spot")
            mx = (xa + 3 * c1[0] + 3 * c2[0] + xb) / 8
        if label:
            over.text(label, mx + 6, (ya + yb) / 2, "s sp halo", 11)

    d.extend(over)
    return d.svg()
