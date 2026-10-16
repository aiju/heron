"""Running compiled Curlew programs on the draft 2 simulator."""

from heron.studies.v2_isa import sim as sim2

from . import build

CONFIG = "D32-separate"         # the 1b hardware's configuration (report 0012)


class Run:
    """A finished run: the machine, its output and how it ended."""

    def __init__(self, compiled, m, error):
        self.compiled = compiled
        self.image = compiled.image
        self.machine = m
        self.output = bytes(m.dev.out)
        self.error = error

    def word(self, name):
        a = self.image.symbols[name]
        return int.from_bytes(self.machine.mem[a:a + 4], "little")

    def stats(self):
        m = self.machine
        hp = m.r[14]
        cur = self.word("cur_start")
        return {
            "gc_count": self.word("gc_count"),
            "allocated": (self.word("gc_alloc") + hp - cur) & 0xFFFFFFFF,
            "copied": self.word("gc_copied"),
            "tag_traps": sum(1 for _, what in m.traps if what == "tag check"),
        }


def run(text, inp=b"", features=(), max_cycles=4_000_000_000, compiled=None, trace=None, heap_size=None):
    """Compile (unless given a Compiled) and run a program: a Run."""
    if compiled is None:
        compiled = build.compile_program(text, features, heap_size)
    m = sim2.Machine(compiled.image, inp=inp)
    if trace is not None:
        m.trace = trace
    err = None
    try:
        m.run(max_cycles=max_cycles)
    except sim2.SimError as e:
        err = str(e)
    if err is None:
        for pc, what in m.traps:
            if what not in ("tag check", "tagged overflow", "divide by zero"):
                err = f"trap at {pc:X}: {what}"
                break
    return Run(compiled, m, err)
