"""Chibi Heron's whole-machine simulator (sim/, a Rust crate; Python has it
as heron.native.chibi): the two-halves machine's microcode as rtl2.py runs
it, on a board with every device of the netlist.

    m = Chibi()                         # at power-on: the reset routine first
    m.load_image(check.assemble("prog.s"))
    m.run_until_halt()
    m.console_out()                     # the suite's console (the fixture)

The control store is routines2's, as this checkout has it: store_image()
writes it for the engine, naming what each field does rather than how
ucode2 encodes it, so the engine needs no change when an encoding does.
The engine's vocabulary is in sim/src/store.rs; the lists here are in its
order.
"""

import struct

from heron import native

from . import routines2, ucode2 as uc
from .rtl2 import Word

# the engine's vocabulary (sim/src/store.rs), in its order
DS = [uc.DS_NONE, uc.DS_RF, uc.DS_MEM, uc.DS_IMM, uc.DS_ADR, uc.DS_PCH, uc.DS_FLW]
MOP = [uc.MOP_NONE, uc.MOP_RDM, uc.MOP_WRM, uc.MOP_RDP, uc.MOP_FETCH, uc.MOP_PCS, uc.MOP_LDIRM]
AXP = [uc.AXP_NONE, uc.AXP_LO, uc.AXP_HI]
AXM = [uc.AXM_NONE, uc.AXM_LO, uc.AXM_HI, uc.AXM_INC]
IRN = [uc.HIRN_NONE, uc.HIRN_INCD, uc.HIRN_DECS, uc.HIRN_IDX]
SEQ = [uc.HSEQ_JUMP, uc.HSEQ_MW, uc.HSEQ_END, uc.HSEQ_JUMPT]
HX = [uc.HX_NAT, uc.HX_ZERO, uc.HX_FILL, uc.HX_IMMH]
RM = [uc.RM_PASS, uc.RM_SHR, uc.RM_ZXB, uc.RM_SXB]
SI = [uc.SI_0, uc.SI_C, uc.SI_D15, uc.SI_CO]
SEL = [uc.SEL_K, uc.SEL_D, uc.SEL_S]
CARRY = ["0", "1", "C", "IC"]
FLOPS = ["NONE", "ADDLO", "SUBLO", "ADCLO", "SBCLO", "ICLO", "ICLOZ", "LOGLO", "NZ16", "SHR",
         "SHL", "STN", "STZ", "ICSTZ", "STF0", "STA4", "CNZ", "VNZ", "ZNZ", "NNZ", "INZ", "BNZ",
         "BINZ", "SETI", "CLRI", "ENTRY", "SETINIT", "STC", "ADDHI", "SUBHI", "LOGHI", "STZ32"]
CONDS = ["TRUE", "Z", "C", "N", "V", "HI", "LT", "LE", "IC", "ST", "INIT", "IRQP", "NE", "A0",
         "ODT", "I"]

TICK_NS = 19.86
BOOT_MAGIC = routines2.BOOT_MAGIC


def _word_bytes(raw, halt):
    w = Word(raw)
    b = [DS.index(w.DS), w.SZ, w.IMMF, SEL.index(w.RS), w.KR, w.HR, w.WEN, SEL.index(w.WS),
         w.KW, w.HW, w.AOP, SI.index(w.SISEL), RM.index(w.RM), FLOPS.index(w.flop),
         FLOPS.index(w.flop_h), w.LDL, MOP.index(w.MOP), AXP.index(w.AXP), AXM.index(w.AXM),
         IRN.index(w.IRN), SEQ.index(w.SEQ), CONDS.index(w.cnd), w.CND & 3, w.JT & 0xFF,
         w.JT >> 8, w.LEN + 1, w.HLEN, HX.index(w.HX), int(halt)]
    return bytes(b + [0] * (32 - len(b)))


def store_image(cs=None):
    """The control store as the engine takes it (sim/src/store.rs has the
    format): routines2's by default."""
    cs = cs or routines2.control_store()
    out = bytearray(b"CHST")
    out += struct.pack("<8H", 1, uc.CS_WORDS, uc.ENTRY_BASE, uc.TASK_BASE, uc.DEVICE_BASE,
                       uc.COPPER_BASE, uc.NOCHK, 0)
    for code in range(32):
        name = uc.AOP_NAME.get(code, "A")
        for st in (0, 1):
            s, m, carry = uc.aop_resolve(name, st)
            out += bytes([s, m, CARRY.index(carry)])
    names = list(uc.IMMS)
    assert len(names) == 32
    for name in names:
        for d in range(16):
            for s in range(16):
                out += struct.pack("<3H", uc.imm_value(name, d, s, 0),
                                   uc.imm_value(name, d, s, 1, 0), uc.imm_value(name, d, s, 1, 1))
    for a in range(uc.CS_WORDS):
        out += _word_bytes(cs.words[a], a in cs.halt)
    return bytes(out)


_IMAGE = None


def default_image():
    global _IMAGE
    if _IMAGE is None:
        _IMAGE = store_image()
    return _IMAGE


def flash_image(ram):
    """A boot flash that the reset routine copies into RAM at 0: the magic,
    the count of 256-byte pages, the pages (RFC 0047, 10). `ram`: bytes from
    address 0."""
    pages = (len(ram) + 255) // 256
    if pages > 255:
        raise ValueError(f"{len(ram)} bytes: the boot copies at most 255 pages")
    return bytes([BOOT_MAGIC, pages]) + bytes(ram) + b"\xff" * (pages * 256 - len(ram))


def image_bytes(img):
    """An assembled image's bytes from address 0 to its end."""
    if not img.mem:
        return b""
    buf = bytearray(max(img.mem) + 1)
    for a, b in img.mem.items():
        buf[a] = b
    return bytes(buf)


class Chibi:
    """The machine at power-on, with its board. `fixture`: the suite's
    console in slot 7; `stretch`: phase F's length as the board has it
    (off: as rtl2.py counts it)."""

    def __init__(self, fixture=True, stretch=True, mouse_reporting=False, console=b"", store=None):
        self.m = native.chibi.Machine(store or default_image(), fixture=fixture, stretch=stretch,
                                      mouse_reporting=mouse_reporting, console_input=console)

    def __getattr__(self, name):
        return getattr(self.m, name)

    def __setattr__(self, name, value):
        if name == "m":
            object.__setattr__(self, name, value)
        else:
            setattr(self.m, name, value)

    def load_image(self, img, addr=0):
        """An assembled image into RAM, as the suite's runs have it."""
        self.m.load(addr, image_bytes(img))

    def boot_from_flash(self, img):
        """An assembled image into the boot flash, for the reset routine to
        copy into RAM."""
        self.m.set_flash(flash_image(image_bytes(img)))

    def run_until_halt(self, max_cycles=200_000_000):
        st = self.m.run(max_cycles=max_cycles)
        if st != "halted":
            raise RuntimeError(f"{st} after {self.m.cycles} cycles, at {self.m.insn_pc:06X}")
        return self

    def regs(self, bank=False):
        return [self.m.reg(i, bank) for i in range(16)]

    @property
    def ms(self):
        return self.m.ticks * TICK_NS / 1e6

    def save_png(self, path):
        stats = self.m.stats()
        write_png(path, self.m.screen(), stats["width"], stats["height"])

    def save_wav(self, path, samples, rate=44100):
        write_wav(path, samples, rate)


def write_png(path, rgb, w, h):
    """RGB bytes as a PNG file."""
    import zlib
    raw = b"".join(b"\0" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def write_wav(path, samples, rate=44100):
    """16-bit mono little-endian samples as a WAV file."""
    hdr = b"RIFF" + struct.pack("<I", 36 + len(samples)) + b"WAVEfmt "
    hdr += struct.pack("<IHHIIHH", 16, 1, 1, rate, 2 * rate, 2, 16)
    with open(path, "wb") as f:
        f.write(hdr + b"data" + struct.pack("<I", len(samples)) + samples)


# ---- typing on the PS/2 keyboard

# set 2 make codes of the keys that type ASCII, and what shift makes of them
_CODES = dict(zip("`1234567890-=qwertyuiop[]\\asdfghjkl;'zxcvbnm,./",
                  [0x0E, 0x16, 0x1E, 0x26, 0x25, 0x2E, 0x36, 0x3D, 0x3E, 0x46, 0x45, 0x4E, 0x55,
                   0x15, 0x1D, 0x24, 0x2D, 0x2C, 0x35, 0x3C, 0x43, 0x44, 0x4D, 0x54, 0x5B, 0x5D,
                   0x1C, 0x1B, 0x23, 0x2B, 0x34, 0x33, 0x3B, 0x42, 0x4B, 0x4C, 0x52,
                   0x1A, 0x22, 0x21, 0x2A, 0x32, 0x31, 0x3A, 0x41, 0x49, 0x4A]))
_SHIFTED = dict(zip('~!@#$%^&*()_+QWERTYUIOP{}|ASDFGHJKL:"ZXCVBNM<>?',
                    "`1234567890-=qwertyuiop[]\\asdfghjkl;'zxcvbnm,./"))
_CODES.update({" ": 0x29, "\n": 0x5A, "\t": 0x0D, "\b": 0x66, "\x1b": 0x76})
SHIFT = 0x12


def keystrokes(text):
    """[(set 2 code, down)] that type `text` on a US keyboard."""
    out = []
    for ch in text:
        shifted = ch in _SHIFTED
        code = _CODES.get(_SHIFTED.get(ch, ch))
        if code is None:
            raise ValueError(f"no key types {ch!r}")
        if shifted:
            out.append((SHIFT, True))
        out += [(code, True), (code, False)]
        if shifted:
            out.append((SHIFT, False))
    return out


# ---- the command line

USAGE = """heron chibi sim: Chibi Heron's whole-machine simulator (sim/, Rust)

  run FILE.s [options]          a program from power-on: the reset routine,
                                then the program at 0, its image in RAM
      --flash                   the image in the boot flash instead, for the
                                reset routine to copy (RFC 0047, 10)
      --seconds S               run S seconds of the machine's time (else
                                until it stops)
      --input TEXT              the suite's console input (the fixture)
      --uart TEXT               typed at UART 0's terminal
      --type TEXT               typed on the PS/2 keyboard, a key each 20 ms
      --type-at S               from S seconds on (0.5)
      --screenshot FILE.png     the last frame drawn
      --wav FILE.wav            the sound (44.1 kHz)
      --profile                 where the time went, by instruction
      --no-fixture              no test fixture in slot 7 (the board alone)
  check [NAMES] [--model]       the suite against draft 2's simulator, and
                                the board's device tests; --model: also
                                against rtl2.py, decode by decode (slow)
  term [FILE.s] [--flash] [--fast]
                                UART 0 in this terminal, in the machine's
                                time (--fast: as fast as it goes); Ctrl-]
                                quits, Ctrl-B is the halt button (ODT)
  bench                         the suite's speed
"""


def _ascii(b):
    return bytes(b).decode("latin-1")


def _assemble(path):
    from . import check
    return check.assemble(path)


def cmd_run(args):
    import time
    from heron.infra.programs import metadata
    meta = metadata(args.file)
    img = _assemble(args.file)
    m = Chibi(fixture=not args.no_fixture,
              console=(args.input.encode("latin-1") if args.input is not None else meta["input"]))
    if args.flash:
        m.boot_from_flash(img)
    else:
        m.load_image(img)
    if args.uart:
        m.uart_send(0, args.uart.encode("latin-1").decode("unicode_escape").encode("latin-1"))
    if args.profile:
        m.keep_profile()
    if args.screenshot:
        m.render(True)
    if args.wav:
        m.record_audio(True)
    keys = keystrokes(args.type.encode("latin-1").decode("unicode_escape")) if args.type else []
    key_every = native.chibi.ticks_of(0.020)
    next_key = native.chibi.ticks_of(args.type_at)
    t0 = time.time()
    # until it stops, or for the time asked (at most a minute of its own)
    end = native.chibi.ticks_of(args.seconds if args.seconds else 60.0)
    while True:
        until = min(next_key, end) if keys else end
        status = m.run(until=until)
        if keys and m.ticks >= next_key:
            m.key(*keys.pop(0))
            next_key += key_every
        if status != "limit" or m.ticks >= end:
            break
    wall = time.time() - t0
    out = m.console_out()
    if out:
        print(_ascii(out), end="" if out.endswith(b"\n") else "\n")
    sent = m.uart_take(0)
    if sent:
        print("UART 0:", _ascii(sent).replace("\r", ""), sep="\n")
    s = m.seconds
    print(f"-- {status}: {m.instructions} instructions, {m.cycles} microinstructions, "
          f"{m.ticks} ticks, {s * 1e3:.2f} ms ({wall:.2f} s here, {s / max(wall, 1e-9):.1f}x the board)")
    st = m.stats()
    if st["underflows"]:
        print(f"-- the video's buffer ran out {st['underflows']} times")
    if args.screenshot:
        if m.frames == 0:
            m.stop_on_halt = False
            m.run_for(0.035)
        m.save_png(args.screenshot)
        print(f"-- {args.screenshot}: frame {m.frames}")
    if args.wav:
        data = m.audio_take(44100.0)
        write_wav(args.wav, data, 44100)
        print(f"-- {args.wav}: {len(data) // 2 / 44100:.2f} s")
    if args.profile:
        print_profile(m)
    return 0 if status in ("halted", "limit") else 1


def print_profile(m, n=25):
    p = m.profile()
    total = sum(t for _, t in p["insns"].values()) + p["device_task"][1] + p["copper"][1]
    rows = sorted(p["insns"].items(), key=lambda kv: -kv[1][1])[:n]
    print(f"{'address':>8} {'runs':>9} {'ticks':>11} {'share':>6}")
    for a, (runs, ticks) in rows:
        print(f"{a:08X} {runs:9d} {ticks:11d} {100 * ticks / max(total, 1):5.1f}%")
    for name in ("device_task", "copper"):
        c, t = p[name]
        if t:
            print(f"{name:>8} {'':9} {t:11d} {100 * t / max(total, 1):5.1f}%")


DEVICE_TESTS = {
    # (program, what to do first, what it prints or sends)
    "odt": ("odt.s", "odt", None),
    "copper": ("copper.s", None, b"ABABZ"),
    "pcm": ("pcm.s", None, b"P"),
    "ps2": ("ps2.s", "kbd", b"\x1c\xf0"),
}
ODT_SENT = (b"\n\r00000000\r\n@X?\r\n@2000/CAFEF00D \r\n@%1/00000000 \r\n@S\n\r00000004\r\n"
            b"@%1/00001234 5678\r\n@2000/CAFEF00D 11223344\n\r00002004/00000000 \r\n"
            b"@%2/00000000 \n\n@S\n\r00000006\r\n@S\n\r00000008\r\n@S\n\r0000000A\r\n@S\n\r"
            b"00000006\r\n@S\n\r00000008\r\n@S\n\r0000000A\r\n@%2/00000002 \r\n@4G")
PCM_SAMPLES = bytes([0x80, 0xC0, 0xFF, 0xC0, 0x80, 0x40, 0x00, 0x40])


def run_device_test(name, stretch=True):
    """One of the board's device tests (programs/): the machine after it,
    and what went wrong, if anything. The outcomes are the model's
    (rtl2.py's, as hw.py runs it)."""
    import os
    from . import hw
    prog, setup, printed = DEVICE_TESTS[name]
    img = _assemble(os.path.join(os.path.dirname(os.path.abspath(__file__)), "programs", prog))
    m = Chibi(stretch=stretch)
    m.load_image(img)
    if setup == "odt":
        m.uart_send(0, hw.ODT_KEYS)
        m.press_halt()
    elif setup == "kbd":
        m.ps2_send(0, b"\x1c\xf0")
    st = m.run(max_cycles=3_000_000)
    diffs = []
    if st != "halted":
        diffs.append(f"{st} after {m.cycles} cycles")
    if printed is not None and m.console_out() != printed:
        diffs.append(f"printed {m.console_out()!r}, not {printed!r}")
    if name == "odt" and m.uart_take(0) != ODT_SENT:
        diffs.append("ODT's session differs")
    if name == "pcm" and m.pcm_log()[:8] != PCM_SAMPLES:
        diffs.append(f"the samples {m.pcm_log()[:8].hex(' ')}")
    return m, diffs


def check_program(path, model=False):
    """A suite program on the engine against draft 2's simulator (and
    rtl2.py): what differs."""
    import os
    from heron.infra.programs import metadata
    from . import check
    name = os.path.basename(path)[:-2]
    meta = metadata(path)
    img = check.assemble(path)
    m = Chibi(stretch=False, console=meta["input"])
    m.load_image(img)
    if model:
        m.keep_decodes()
    m.run_until_halt()
    ref = check.run_isa(img, meta["input"])
    diffs = []
    if name not in check.TIMED:
        if m.console_out() != bytes(ref.dev.out):
            diffs.append(f"output {m.console_out()[:60]!r}")
        diffs += [f"r{i} = {m.reg(i):08X}, expected {ref.r[i]:08X}" for i in range(16)
                  if m.reg(i) != ref.r[i]]
        f = m.flags()
        diffs += [f"{k} = {f[k]}" for k in "NZCV" if f[k] != getattr(ref, k.lower())]
        ram = m.ram(0, len(ref.mem))
        bad = [a for a in range(len(ram)) if ram[a] != ref.mem[a]]
        if bad:
            diffs.append(f"{len(bad)} bytes of RAM differ, the first at {bad[0]:06X}")
    if model:
        r = check.run_rtl(img, meta["input"], log=True)
        mine = [(c, pc, p) for c, _, pc, p in m.decodes()]
        theirs = [tuple(x) for x in r.decodes]
        if mine != theirs:
            i = next((i for i, (a, b) in enumerate(zip(mine, theirs)) if a != b),
                     min(len(mine), len(theirs)))
            diffs.append(f"the decodes differ from rtl2.py's at the {i}th")
        if (m.cycles, m.ticks) != (r.cycles, r.ticks):
            diffs.append(f"{m.cycles} cycles {m.ticks} ticks, rtl2.py {r.cycles} {r.ticks}")
        rf = m.register_file()
        if any(rf[h << 7 | t << 6 | b << 5 | n] != r.rf.get((h, t, b, n), 0)
               for h in (0, 1) for t in (0, 1) for b in (0, 1) for n in range(32)):
            diffs.append("the register file differs from rtl2.py's")
    return name, m, diffs


def cmd_check(args):
    from heron.studies.v2_isa import testing
    bad = 0
    for p in testing.program_paths(args.names or None):
        name, m, diffs = check_program(p, model=args.model)
        bad += bool(diffs)
        print(f"{name:12} {'FAIL' if diffs else 'ok':5} {m.instructions:9d} instructions "
              f"{m.cycles:10d} cycles {m.ticks:11d} ticks  {'; '.join(diffs[:3])}")
    if not args.names:
        for name in DEVICE_TESTS:
            m, diffs = run_device_test(name)
            bad += bool(diffs)
            print(f"{name:12} {'FAIL' if diffs else 'ok':5} {m.instructions:9d} instructions "
                  f"{m.cycles:10d} cycles {m.ticks:11d} ticks  {'; '.join(diffs[:3])}")
    return 1 if bad else 0


def cmd_bench(args):
    import time
    from heron.infra.programs import metadata
    from heron.studies.v2_isa import testing
    total_c = total_t = total_wall = 0
    for p in testing.program_paths(None):
        meta = metadata(p)
        m = Chibi(console=meta["input"])
        m.load_image(_assemble(p))
        t = time.time()
        m.run_until_halt()
        wall = time.time() - t
        total_c += m.cycles
        total_t += m.seconds
        total_wall += wall
    print(f"the suite: {total_c} microinstructions, {total_t * 1e3:.0f} ms of the board's time, "
          f"in {total_wall:.2f} s: {total_c / total_wall / 1e6:.1f} M microinstructions a second, "
          f"{total_t / total_wall:.1f}x the board")
    return 0


def cmd_term(args):
    """UART 0 in this terminal."""
    import os
    import select
    import sys
    import termios
    import time
    import tty
    m = Chibi()
    if args.file:
        img = _assemble(args.file)
        if args.flash:
            m.boot_from_flash(img)
        else:
            m.load_image(img)
    else:
        m.press_halt()          # nothing to run: ODT
    m.stop_on_halt = False
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd) if os.isatty(fd) else None
    if old:
        tty.setraw(fd)
    try:
        start = time.time()
        while True:
            if select.select([fd], [], [], 0)[0]:
                data = os.read(fd, 256)
                if b"\x1d" in data:
                    break
                if b"\x02" in data:
                    m.press_halt()
                    data = data.replace(b"\x02", b"")
                if data:
                    m.uart_send(0, data)
            if args.fast:
                m.run_for(0.01)
            else:
                ahead = m.seconds - (time.time() - start)
                if ahead > 0:
                    time.sleep(min(ahead, 0.01))
                m.run(until=native.chibi.ticks_of(time.time() - start + 0.01))
            out = m.uart_take(0)
            if out:
                os.write(sys.stdout.fileno(), bytes(out))
    finally:
        if old:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    print()
    return 0


def main(argv):
    import argparse
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE, end="")
        return 0
    p = argparse.ArgumentParser(prog="heron chibi sim", usage=USAGE)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("file")
    r.add_argument("--flash", action="store_true")
    r.add_argument("--seconds", type=float)
    r.add_argument("--input")
    r.add_argument("--uart")
    r.add_argument("--type")
    r.add_argument("--type-at", type=float, default=0.5)
    r.add_argument("--screenshot")
    r.add_argument("--wav")
    r.add_argument("--profile", action="store_true")
    r.add_argument("--no-fixture", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("names", nargs="*")
    c.add_argument("--model", action="store_true")
    t = sub.add_parser("term")
    t.add_argument("file", nargs="?")
    t.add_argument("--flash", action="store_true")
    t.add_argument("--fast", action="store_true")
    sub.add_parser("bench")
    args = p.parse_args(argv)
    return {"run": cmd_run, "check": cmd_check, "term": cmd_term, "bench": cmd_bench}[args.cmd](args)
