"""Heron Mini's simulator for software: the register-transfer model in
Rust (studies/mini/engine), cycle for cycle and tick for tick as rtl.py,
with the video options of RFC 0042 (modes, layouts, descriptors or a
frame base, the cursor, the beam's position, the bandwidth), rendering
each frame as it's shown.

    heron mini sim FILE.s [--frames N] [--png F] [--png-dir D] [--layout L0|L1]
                          [--bandwidth B0|B1|B2] [--input TEXT] [--profile]

From Python:

    from heron.studies.mini import sim
    m = sim.machine(bandwidth="B1")      # heron.native.mini.Machine
    sim.load(m, "prog.s")
    m.run(100_000_000, frames=10)        # "halted", "frames" or "limit"
    sim.write_png("out.png", *m.frame())

The program runs from reset with its image in the RAM at 0, as the suite's
programs do (check.py); the suite's I/O page (the console at 0xFFFF_FF00,
its timer and cycle counter) is there, and the UARTs, the boot flash and
the video's registers (RFC 0042, 8). The CF card, the 82C54 and the
expansion ports read 0.
"""

import os
import sys

from heron import native

from . import ucode as uc
from .timing import TICK

_rom = {}


def rom(mc=None):
    """The control store as the engine takes it: (words, index, entry,
    refill, irq, fault, lengths)."""
    key = id(mc)
    if key not in _rom:
        mc = mc or uc.built()
        fields = native.mini.FIELDS
        words, index, seen = [], [-1] * (1 << 17), {}
        for a, w in mc.rom().items():
            if w not in seen:
                f = uc.unpack(w)
                seen[w] = len(seen)
                words += [f[n] for n in fields]
            index[a] = seen[w]
        lengths = list(mc.lengths) + [mc.lengths[-1]] * (4 - len(mc.lengths))
        _rom[key] = (words, index, uc.ENTRY, uc.REFILL_ADDR, uc.IRQ_ADDR, list(uc.FAULT_ADDRS),
                     lengths, mc)
    return _rom[key]


def machine(layout="L0", bandwidth="B0", queue=2, profile=False, mc=None, **kw):
    """A machine with the microcode as built; the board's options as
    RFC 0042 names them."""
    words, index, entry, refill, irq, fault, lengths, _ = rom(mc)
    return native.mini.Machine(words, index, entry, refill, irq, fault, lengths, layout=layout,
                               bandwidth=bandwidth, queue=queue, profile=profile, **kw)


def assemble(path):
    import heron.studies.v2_isa  # noqa: F401
    from heron.infra import asm as asmcore
    from heron.infra import isas
    return asmcore.assemble_file(isas.get("v2"), path)


def load(m, program, base=0):
    """A program into the RAM: an assembler's image, or a .s file's path."""
    img = assemble(program) if isinstance(program, str) else program
    for a, data in _runs(img.mem):
        m.load(base + a, data)
    return img


def _runs(mem):
    """{address: byte} as (address, bytes) runs."""
    run, start, prev = bytearray(), None, None
    for a in sorted(mem):
        if prev is not None and a != prev + 1:
            yield start, bytes(run)
            run, start = bytearray(), None
        if start is None:
            start = a
        run.append(mem[a])
        prev = a
    if start is not None:
        yield start, bytes(run)


def rgb(data):
    """RGB 5:6:5 little-endian as 8-bit RGB bytes."""
    import array
    px = array.array("H", data)
    if sys.byteorder != "little":
        px.byteswap()
    out = bytearray(3 * len(px))
    out[0::3] = bytes(((c >> 11) & 31) * 255 // 31 for c in px)
    out[1::3] = bytes(((c >> 5) & 63) * 255 // 63 for c in px)
    out[2::3] = bytes((c & 31) * 255 // 31 for c in px)
    return bytes(out)


def write_png(path, w, h, data):
    """A frame (RGB 5:6:5, as Machine.frame gives it) as a PNG file."""
    import struct
    import zlib
    px = rgb(data)
    raw = b"".join(b"\0" + px[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def stats(m):
    """What the run did, as lines of text."""
    ms = m.ticks * TICK / 1e6
    lines = [f"{m.instructions} instructions, {m.cycles} cycles, {ms:.3f} ms "
             f"({m.ticks} ticks, {m.ticks / max(m.cycles, 1) * TICK:.1f} ns a cycle)",
             f"I/O holds {m.hold_ticks * TICK / 1e6:.3f} ms; video steals {m.steal_ticks} ticks "
             f"({100 * m.steal_ticks / max(m.ticks, 1):.2f}% of the time, {m.steals} loads), "
             f"{m.underruns} shifter loads without a word",
             f"{m.frames} frames shown, {m.line_irqs} line interrupts"]
    return lines


def main(args):
    from heron.infra.programs import metadata
    m = machine(layout=args.layout, bandwidth=args.bandwidth, queue=args.queue,
                profile=args.profile)
    meta = metadata(args.file)
    inp = args.input.encode() if args.input is not None else meta["input"]
    m.console_input(inp)
    if args.uart is not None:
        m.uart_input(args.uart.encode())
    _, _, _, _, _, _, _, mc = rom()
    load(m, args.file)
    if args.png_dir:
        os.makedirs(args.png_dir, exist_ok=True)
    status = None
    while True:
        status = m.run(args.max_cycles, frames=1 if args.png_dir else args.frames)
        if status != "frames":
            break
        if args.png_dir and (m.frames - 1) % args.every == 0:
            write_png(os.path.join(args.png_dir, f"{m.frames - 1:05d}.png"), *m.frame())
        if not args.png_dir or (args.frames and m.frames >= args.frames):
            break
    out = m.output()
    sys.stdout.write(out.decode("latin-1"))
    if out and not out.endswith(b"\n"):
        print()
    if m.uart_output():
        print(f"UART 0: {m.uart_output().decode('latin-1')!r}")
    print(f"{status}: " + "\n".join(stats(m)))
    if args.png:
        # halted: the picture the memory makes; else the last frame shown
        frame = m.snapshot() if status == "halted" or not m.frames else m.frame()
        write_png(args.png, *frame)
        print(f"{args.png}: {frame[0]} x {frame[1]}")
    if args.profile:
        from collections import Counter
        names = Counter()
        for a, n in m.ucount():
            node = mc.by_addr.get(a)
            names[node.name if node else f"{a:05X}"] += n
        for name, n in names.most_common(25):
            print(f"  {n:9d} {100 * n / m.cycles:5.1f}%  {name}")
    return 0
