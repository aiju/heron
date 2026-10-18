"""The input scripts for mines.c, worked out from its boards: this
replicates the C's geometry, its random mines and its flood fill, so the
clicks can open a large area, flag mines, lose on purpose and win.

    python3 studies/mini_gfx/games/mines/make_scripts.py

writes m0.script (M0 and M3: 640 x 480) and m5.script (M5: 1024 x 768)
next to it. Each: the mouse in, the first board (expert, or the 60 x 40 one
in M5) opened where it opens most, a few flags, safe cells and a chord,
then a mine (lost); the beginner's board then won; Esc (the
measurements)."""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
T = 16
LEVELS = [(9, 9, 10), (16, 16, 40), (30, 16, 99), (60, 40, 400)]


class Board:
    """mines.c's new_board, place and reveal, for one level and screen."""

    def __init__(self, level, w, h):
        self.level = level
        self.cols, self.rows, self.nmines = LEVELS[level]
        self.n = self.cols * self.rows
        bar_h = 64 if h > 600 else 48
        bw = self.cols * T
        barw = max(bw, 208)
        self.bx = ((w - bw) // 2) & ~15
        barx = self.bx + bw // 2 - barw // 2
        bary = max(4, (h - (bar_h + 12 + self.rows * T)) // 2)
        self.by = bary + bar_h + 12
        s = bar_h - 12
        self.button = (barx + (barw - s) // 2 + s // 2, bary + 6 + s // 2)
        self.mine = [0] * self.n
        self.adj = [0] * self.n
        self.open = [False] * self.n
        self.flag = [False] * self.n

    def xy(self, c):
        """the middle of cell c on the screen"""
        return self.bx + (c % self.cols) * T + T // 2, self.by + (c // self.cols) * T + T // 2

    def near(self, a, b):
        ax, ay, bx, by = a % self.cols, a // self.cols, b % self.cols, b // self.cols
        return abs(ax - bx) <= 1 and abs(ay - by) <= 1

    def neighbours(self, c):
        x, y = c % self.cols, c // self.cols
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if (dx or dy) and 0 <= x + dx < self.cols and 0 <= y + dy < self.rows:
                    yield c + dy * self.cols + dx

    def place(self, first):
        seed = (2026 + 977 * self.level) & 0xFFFFFFFF
        k = 0
        while k < self.nmines:
            seed = (seed * 1103515245 + 12345) & 0xFFFFFFFF
            c = (seed >> 16) % self.n
            if self.mine[c] or self.near(c, first):
                continue
            self.mine[c] = 1
            k += 1
        for c in range(self.n):
            self.adj[c] = sum(self.mine[k] for k in self.neighbours(c))

    def reveal(self, c):
        """the cells a left click on c opens"""
        if self.open[c] or self.flag[c] or self.mine[c]:
            return 0
        q = [c]
        self.open[c] = True
        i = 0
        while i < len(q):
            c = q[i]
            i += 1
            if self.adj[c]:
                continue
            for k in self.neighbours(c):
                if not self.open[k] and not self.flag[k]:
                    self.open[k] = True
                    q.append(k)
        return len(q)

    def best_first(self):
        """the first click that opens the most"""
        best = None
        for c in range(self.n):
            b = Board(self.level, 0, 0)
            b.__dict__.update({k: v for k, v in self.__dict__.items()
                               if k in ("bx", "by", "button")})
            b.place(c)
            n = b.reveal(c)
            if best is None or n > best[0]:
                best = (n, c)
        return best[1]

    def frontier(self):
        """hidden cells next to open ones"""
        return [c for c in range(self.n) if not self.open[c]
                and any(self.open[k] for k in self.neighbours(c))]


class Script:
    def __init__(self):
        self.lines = []
        self.f = 5
        self.x, self.y = 40, 40
        self.lines.append(f"{self.f} mouse {self.x} {self.y}")

    def move(self, x, y, frames=6):
        for k in range(1, frames + 1):
            self.f += 1
            self.lines.append(f"{self.f} mouse {self.x + (x - self.x) * k // frames} "
                              f"{self.y + (y - self.y) * k // frames}")
        self.x, self.y = x, y

    def click(self, x, y, button=1, wait=2):
        self.move(x, y)
        self.f += 1
        self.lines.append(f"{self.f} click {x} {y}" + (f" {button}" if button != 1 else ""))
        self.f += wait

    def key(self, name, wait=2):
        self.f += 1
        self.lines.append(f"{self.f} key {name}")
        self.f += wait

    def shot(self, name, wait=20):
        self.f += wait
        self.lines.append(f"{self.f} shot {name}")

    def text(self, comment):
        return f"# {comment}\n" + "\n".join(self.lines) + "\n"


def play(w, h):
    s = Script()
    # the first board: opened where it opens most, flags, safe cells, a chord, a mine
    b = Board(3 if h > 600 else 2, w, h)
    first = b.best_first()
    b.place(first)
    n = b.reveal(first)
    s.click(*b.xy(first), wait=10)
    s.shot("opened", 10)
    edge = b.frontier()
    mines = [c for c in edge if b.mine[c]][:6]
    for c in mines:
        b.flag[c] = True
        s.click(*b.xy(c), button=2)
    safe = [c for c in edge if not b.mine[c]][:8]
    for c in safe:
        b.reveal(c)
        s.click(*b.xy(c), wait=4)
    chords = [c for c in range(b.n) if b.open[c] and b.adj[c]
              and all(b.flag[k] == bool(b.mine[k]) for k in b.neighbours(c))
              and any(not b.open[k] and not b.mine[k] for k in b.neighbours(c))]
    if chords:
        c = chords[0]
        for k in b.neighbours(c):
            if not b.mine[k]:
                b.reveal(k)
        s.click(*b.xy(c), wait=4)
    s.move(*b.xy(b.frontier()[len(b.frontier()) // 2]))
    s.shot("playing", 30)
    boom = [c for c in b.frontier() if b.mine[c] and not b.flag[c]][0]
    s.click(*b.xy(boom), wait=4)
    s.move(*b.button)
    s.shot("lost", 20)
    # the beginner's board, won
    s.key("1", wait=20)
    b = Board(0, w, h)
    first = b.best_first()
    b.place(first)
    b.reveal(first)
    s.click(*b.xy(first), wait=6)
    flagged = 0
    for c in range(b.n):
        if b.mine[c] and flagged < 3 and any(b.open[k] for k in b.neighbours(c)):
            b.flag[c] = True
            flagged += 1
            s.click(*b.xy(c), button=2)
    for c in range(b.n):
        if not b.mine[c] and not b.open[c]:
            b.reveal(c)
            s.click(*b.xy(c), wait=3)
    s.shot("won", 30)
    s.key("esc", wait=0)
    return s, n


def main():
    for name, w, h in (("m0", 640, 480), ("m5", 1024, 768)):
        s, n = play(w, h)
        with open(os.path.join(HERE, f"{name}.script"), "w") as f:
            f.write(s.text(f"made by make_scripts.py for {w} x {h}; the first click opens {n} "
                           f"cells; {s.f} frames"))
        print(f"{name}.script: {s.f} frames, the first click opens {n} cells")


if __name__ == "__main__":
    main()
