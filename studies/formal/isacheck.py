"""The specification against the instruction-level simulator, on known
values: random machine states and random instructions, one step each,
everything compared. A case where the specification says the behaviour is
outside it (an `assume` that fails) must be one where the simulator stops
with an error, or one that touches the I/O page, which the specification
leaves out.

    heron formal isacheck [-n 20000] [--seed 1]
"""

import random

from heron import native
from heron.studies.v1_isa import timing32

from . import spec as S

WINDOW = 0x10000          # code and most data in the first 64 KB


class Window:
    """RAM for the specification: the image, and its writes beside it."""

    def __init__(self, image):
        self.image = image
        self.writes = {}

    def read(self, a):
        if not a.known:
            raise S.SpecError("symbolic address")
        x = a.x
        v = self.writes.get(x)
        if v is None:
            v = self.image[x] if x < len(self.image) else 0
        return S.mk(8, v)

    def write(self, a, v, g):
        if g is False:
            return
        if g is not True or not a.known or not v.known:
            raise S.SpecError("symbolic write")
        self.writes[a.x] = v.x


def random_state(rng):
    """Registers: some addresses in the window (aligned or not), some
    small, some anything."""
    def value():
        k = rng.random()
        if k < 0.35:
            return rng.randrange(0x100, WINDOW - 0x100) & ~rng.choice((0, 1, 3, 3, 3))
        if k < 0.55:
            return rng.randrange(-40, 40) & 0xFFFFFFFF
        if k < 0.7:
            return rng.choice((0, 0, 1, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 31, 32, 33))
        return rng.getrandbits(32)
    r = [0] + [value() for _ in range(15)]
    if rng.random() < 0.9:
        r[15] = rng.randrange(0x1000, WINDOW, 4)            # a usable stack, mostly
    return r, value(), rng.getrandbits(5), rng.randrange(0x100, WINDOW - 0x100, 2)


def random_parcels(rng):
    """A first parcel and two more; encodings whose legal forms random bits
    seldom hit (Jcc, SAVE, RESTORE, MFSR, MTSR) are steered to them."""
    w = rng.getrandbits(16)
    op, f = w >> 12, w & 15
    if op == 0xA and rng.random() < 0.8:
        w = (w & 0xFF00) | rng.randrange(2) << 4
    elif op == 0 and f in (5, 6) and rng.random() < 0.8:
        a = rng.randrange(1, 15)
        w = a << 8 | rng.randrange(a, 15) << 4 | f
    elif op == 0 and f == 10 and rng.random() < 0.8:
        w = (w & 0x0F0F) | rng.randrange(2) << 4
    elif op == 0 and f == 11 and rng.random() < 0.8:
        w = (w & 0x00FF) | rng.randrange(2) << 8
    if rng.random() < 0.3:          # small displacements and indexed parcels
        e = rng.getrandbits(16) & rng.choice((0x00FF, 0xF3FF, 0xFFFF))
    else:
        e = rng.getrandbits(16)
    return [w, e, rng.getrandbits(16)]


def run_one(spec, rng, cover=None, record=None):
    """One random case: None if it agrees, else a description. `cover`
    counts (instruction, outcome); `record`, if a set, collects the
    decisions the specification took (Run.note)."""
    image = bytearray(rng.getrandbits(8) for _ in range(256)) * (WINDOW // 256)
    r, hi, fl, pc = random_state(rng)
    for i, p in enumerate(random_parcels(rng)):
        image[pc + 2 * i] = p & 0xFF
        image[pc + 2 * i + 1] = p >> 8
    return compare(spec, r, hi, fl, pc, bytes(image), cover, record)


def compare(spec, r, hi, fl, pc, image, cover=None, record=None):
    """One step from a given state on the simulator and the specification:
    None if they agree, else (what differs, the parcels at pc, the state).
    `image` is RAM from address 0 (the rest of the 1 MB is zero)."""
    m = native.v1.Machine("v1b", image, b"", timing32.REFERENCE)
    m.r = r
    m.hi = hi
    m.flags = fl
    m.pc = pc
    sim_err = None
    try:
        m.step()
    except native.v1.SimError as e:
        sim_err = str(e)

    win = Window(image)
    regs = {"r": [S.mk(32, x) for x in r], "hi": S.mk(32, hi), "pc": S.mk(32, pc)}
    regs.update({f: bool(fl >> i & 1) for i, f in enumerate("VCZNI")})
    st = S.State(spec, regs, {"mem": win})
    words = [win.read(S.mk(32, pc + 2 * i)).x | win.read(S.mk(32, pc + 2 * i + 1)).x << 8
             for i in range(3)]
    run = None
    try:
        run = spec.step(st, record=record is not None)
    except S.Unspecified as e:
        if cover is not None:
            cover[("?", "outside: " + str(e).split(" (")[0])] += 1
        if sim_err is None and "I/O page" not in str(e):
            return f"spec: outside ({e}), simulator went on", words, (r, hi, fl, pc)
        return None
    finally:
        if record is not None and run is not None:
            record.update(taken(run, owner(spec, words[0])))
    if sim_err is not None:
        return f"simulator stopped ({sim_err}), spec went on", words, (r, hi, fl, pc)
    if cover is not None:
        name = run.matched.syntax if run.matched else "(illegal)"
        vec = run.fault[0] if run.fault_g is True else None
        how = "ok" if vec is None else f"fault {vec if isinstance(vec, int) else vec.x:#x}"
        cover[(name, how)] += 1

    diffs = []
    got_r = [x.x for x in st.regs["r"]]
    if list(m.r) != got_r:
        diffs += [f"r{i}: sim {m.r[i]:08X} spec {got_r[i]:08X}" for i in range(16) if m.r[i] != got_r[i]]
    for name, sim_v in (("hi", m.hi), ("pc", m.pc)):
        if sim_v != st.regs[name].x:
            diffs.append(f"{name}: sim {sim_v:08X} spec {st.regs[name].x:08X}")
    sfl = sum(int(st.regs[f]) << i for i, f in enumerate("VCZNI"))
    if m.flags != sfl:
        diffs.append(f"flags: sim {m.flags:05b} spec {sfl:05b}")
    if bool(m.halted) != (run.halt_g is True):
        diffs.append(f"halted: sim {m.halted} spec {run.halt_g}")
    mem = m.mem
    expect = bytearray(image) + bytes(len(mem) - len(image))
    for a, v in win.writes.items():
        expect[a] = v
    if mem != bytes(expect):
        bad = [a for a in range(len(mem)) if mem[a] != expect[a]][:4]
        diffs.append("memory differs at " + ", ".join(f"{a:05X} (sim {mem[a]:02X} spec "
                                                      f"{expect[a]:02X})" for a in bad))
    if diffs:
        return "; ".join(diffs), words, (r, hi, fl, pc)
    return None


def owner(spec, w):
    """The line of the first instruction whose encoding a first parcel
    matches, `when` or not (0 for none): whose encoding space it is in."""
    return next((i.line for i in spec.instructions if i.matches(w)), 0)


def taken(run, ins):
    """The decision outcomes a run on known values took: {(instruction,
    site, outcome)}, the instruction by its line in the specification."""
    out = set()
    for site, yes, no in run.record or ():
        if yes is True:
            out.add((ins, site, True))
        elif no is True:
            out.add((ins, site, False))
    return out


def main(argv=None):
    import argparse
    from heron.infra import isas
    p = argparse.ArgumentParser(prog="heron formal isacheck")
    p.add_argument("-n", type=int, default=20000)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--show", type=int, default=10, help="how many disagreements to show")
    p.add_argument("--coverage", action="store_true", help="count instructions and outcomes")
    args = p.parse_args(argv)
    spec = S.load("v1b.isa")
    rng = random.Random(args.seed)
    isa = isas.get("v1b")
    bad = 0
    from collections import Counter
    cover = Counter()
    for _ in range(args.n):
        res = run_one(spec, rng, cover)
        if res is not None:
            bad += 1
            if bad <= args.show:
                why, words, (r, hi, fl, pc) = res
                text, _ = isa.disassemble(words, pc, {})
                print(f"{pc:08X}: {' '.join(f'{w:04X}' for w in words)}  {text}")
                print(f"    {why}")
    if args.coverage:
        names = sorted({n for n, _ in cover})
        for n in names:
            row = {h: k for (m, h), k in cover.items() if m == n}
            print(f"  {n:<40} " + ", ".join(f"{h} {k}" for h, k in sorted(row.items())))
    print(f"{args.n} cases, {bad} disagree")
    return 1 if bad else 0
