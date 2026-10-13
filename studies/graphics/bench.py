"""The graphics benchmarks: every scene at every depth, for drafts 1a and
1b, as compiled C and with the assembly kernels; checked against the host
reference, costed in every configuration, and written up as the tables of
report 0019.

    heron graphics bench            print the tables
    heron graphics bench --write    also write reports/0019-report-graphics/performance.md

The runs are kept in build/graphics/bench.json, keyed by a hash of the
sources, so changing only this file doesn't run them again.
"""

import glob
import hashlib
import json
import math
import os

from heron import ROOT
from heron.studies.v1_isa import timing32
from . import build, run as runmod

DOC = os.path.join(ROOT, "reports", "0019-report-graphics", "performance.md")
CACHE = os.path.join(build.OUT, "bench.json")
REF = "D16-overlap"
HW = "D32-separate"             # the draft 1b hardware's configuration
WIDE = "D32-wide"
MHZ = 3.0
# (ISA, assembly kernels, the store-multiple experiment)
VARIANTS = (("v1a", False, False), ("v1a", True, False), ("v1b", False, False),
            ("v1b", True, False), ("v1b", True, True))


def label(isa, kernels, stm=False):
    return f"{isa[1:]} {'stm' if stm else 'asm' if kernels else 'C'}"


def sources_hash():
    h = hashlib.sha256()
    for path in sorted(glob.glob(os.path.join(build.HERE, "src", "*")) +
                       glob.glob(os.path.join(build.HERE, "asm", "*", "*.s")) +
                       glob.glob(os.path.join(build.HERE, "fonts", "*")) +
                       [os.path.join(build.HERE, f) for f in ("run.py", "build.py", "fonts.py")]):
        with open(path, "rb") as f:
            h.update(path.encode() + f.read())
    for path in sorted(glob.glob(os.path.join(ROOT, "studies", "v1_isa", "isa", "src", "*.rs"))):
        with open(path, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def barrel(keys, config):
    """A phase's cycles with a barrel shifter: every shift one step."""
    total = 0
    for (pc, key), n in keys.items():
        if key[2] == "shift":
            key = key[:3] + (1,)
        total += n * timing32.cycles(key, config)
    return total


def shift_cycles(keys, config):
    return sum(n * timing32.cycles(k, config) for (pc, k), n in keys.items() if k[2] == "shift")


def collect(verbose=True):
    """{scene: {depth: {variant label: [phase dicts]}}}, run or from the cache."""
    h = sources_hash()
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            data = json.load(f)
        if data.get("hash") == h:
            return data["runs"]
    runs = {}
    for scene in runmod.SCENES:
        runs[scene] = {}
        for d in range(4):
            runs[scene][str(d)] = {}
            for isa, kernels, stm in VARIANTS:
                img = build.image(isa, kernels, stm)
                phases = runmod.run(img, isa, scene, d, profile=True)
                msgs = runmod.check(phases, scene, d)
                if msgs:
                    raise RuntimeError(f"{scene} depth {d} {label(isa, kernels, stm)}: {msgs[0]}")
                out = []
                for p in phases:
                    if p.name.startswith("_"):
                        continue
                    out.append({
                        "name": p.name, "count": p.count, "cycles": p.cycles,
                        "instructions": p.instructions,
                        "barrel": {c: barrel(p.keys, c) for c in (REF, HW)},
                        "shifts": {c: shift_cycles(p.keys, c) for c in (REF, HW)},
                    })
                runs[scene][str(d)][label(isa, kernels, stm)] = out
                if verbose:
                    print(f"  {scene} depth {d} {label(isa, kernels, stm)}: {len(out)} phases")
    os.makedirs(build.OUT, exist_ok=True)
    with open(CACHE, "w") as f:
        json.dump({"hash": h, "runs": runs}, f)
    return runs


def geomean(xs):
    xs = [x for x in xs if x and x > 0]
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else float("nan")


def phase(runs, scene, d, var, name):
    for p in runs[scene][str(d)][var]:
        if p["name"] == name:
            return p
    return None


def ms(cycles):
    return cycles / (MHZ * 1000)


def fmt_ms(c):
    t = ms(c)
    return f"{t:,.0f}" if t >= 100 else f"{t:,.1f}" if t >= 1 else f"{t:,.2f}"


def fmt_n(x):
    return f"{x:,.0f}"


# what a phase's count counts, and how to show a rate
UNITS = {
    "clear": ("Mpixel/s", 1e6), "rect": ("Mpixel/s", 1e6), "rect.xor": ("Mpixel/s", 1e6),
    "rect.8x8": ("Mpixel/s", 1e6), "rect.tiny": ("kpixel/s", 1e3), "pattern": ("Mpixel/s", 1e6),
    "line": ("kpixel/s", 1e3), "line.xor": ("kpixel/s", 1e3), "line.short": ("kpixel/s", 1e3),
    "line.clipped": ("lines/s", 1), "line.horizontal": ("kpixel/s", 1e3),
    "line.vertical": ("kpixel/s", 1e3), "ellipse": ("ellipses/s", 1),
    "ellipse.fill": ("ellipses/s", 1), "polygon": ("polygons/s", 1),
    "blit.aligned": ("Mpixel/s", 1e6), "blit.unaligned": ("Mpixel/s", 1e6),
    "scroll.up": ("Mpixel/s", 1e6), "scroll.right": ("Mpixel/s", 1e6),
    "icon": ("icons/s", 1), "icon.opaque": ("icons/s", 1),
}

PRIMS = ["clear", "rect", "rect.xor", "rect.8x8", "rect.tiny", "pattern", "line", "line.xor",
         "line.short", "line.clipped", "line.horizontal", "line.vertical", "ellipse",
         "ellipse.fill", "polygon", "blit.aligned", "blit.unaligned", "scroll.up",
         "scroll.right", "icon", "icon.opaque"]
TEXT = ["text.sans12", "text.mono12", "ttf.cached.12", "ttf.cached.24", "ttf.cached.48"]
RASTER = ["raster.mono.12", "raster.mono.24", "raster.mono.48", "raster.aa.12",
          "raster.aa.24", "raster.aa.48"]
WM = ["wm.paint", "wm.raise", "wm.move", "wm.outline", "wm.scroll.covered", "wm.raise.term",
      "wm.scroll", "wm.cursor", "wm.close", "wm.repaint"]
ALL = [("prims", n) for n in PRIMS] + [("text", n) for n in TEXT + RASTER] + \
      [("text", "ttf.first.12"), ("wm", "wm.glyphs")] + [("wm", n) for n in WM]

DESCR = {
    "clear": "the whole 640 x 480 screen", "rect": "100 rectangles, 8-200 pixels a side",
    "rect.xor": "the same, XOR", "rect.8x8": "400 rectangles of 8 x 8",
    "rect.tiny": "400 rectangles of 1-3 x 1-3", "pattern": "560 x 400, an 8 x 8 pattern",
    "line": "400 lines, up to 150 pixels across", "line.xor": "the same, XOR",
    "line.short": "400 lines, up to 20 across", "line.clipped": "100 long lines, mostly off the screen",
    "line.horizontal": "100 horizontal lines of 600", "line.vertical": "100 vertical lines of 440",
    "ellipse": "40 outlines, radii up to 205", "ellipse.fill": "40 filled, radii up to 50",
    "polygon": "20 stars, 5-10 points, 60-130 across", "blit.aligned": "256 x 256, same alignment",
    "blit.unaligned": "256 x 256, 3 pixels off", "scroll.up": "the screen up 16 rows",
    "scroll.right": "the screen right 1 pixel", "icon": "100 icons of 16 x 16, 1-bit, transparent",
    "icon.opaque": "the same, opaque",
    "text.sans12": "a paragraph, proportional bitmap font", "text.mono12": "a terminal, 12 lines",
    "ttf.cached.12": "TrueType at 12 px, from the glyph cache", "ttf.cached.24": "the same, 24 px",
    "ttf.cached.48": "the same, 48 px", "ttf.first.12": "TrueType at 12 px, rasterising every glyph",
    "wm.glyphs": "rasterise the 95 glyphs of the document font (13 px)",
    "wm.paint": "draw the desktop and four windows", "wm.raise": "raise the bottom window",
    "wm.move": "move the top window 12 right, 9 down", "wm.outline": "drag an XOR outline one step",
    "wm.scroll.covered": "scroll the terminal one line, half covered",
    "wm.raise.term": "raise the terminal", "wm.scroll": "scroll the terminal one line, on top",
    "wm.cursor": "move the cursor", "wm.close": "close the terminal",
    "wm.repaint": "repaint the whole screen",
}


def per_unit(p, config=REF):
    return p["cycles"][config] / (p["count"] or 1)


def report(runs):
    out = []
    w = out.append
    best = "1b asm"

    # ---- the operations, at each depth ----
    w("## The operations\n")
    w(f"Time for one unit of each phase (the count: a pixel, a glyph, an operation), "
      f"on draft 1b with the assembly kernels, at {MHZ:g} MHz on {REF} (the reference "
      f"configuration of the draft 1 reports). Rates are for the phase as a whole.\n")
    w("| Phase | What | 1 bit | 2 bits | 4 bits | 8 bits | Rate at 1 bit | Rate at 8 bits |")
    w("|---|---|---:|---:|---:|---:|---:|---:|")
    for scene, name in [("prims", n) for n in PRIMS]:
        cells = [f"`{name}`", DESCR.get(name, "")]
        for d in range(4):
            p = phase(runs, scene, d, best, name)
            cells.append(f"{per_unit(p):,.1f}" if per_unit(p) < 100 else fmt_n(per_unit(p)))
        unit, div = UNITS.get(name, ("/s", 1))
        for d in (0, 3):
            p = phase(runs, scene, d, best, name)
            rate = p["count"] / (p["cycles"][REF] / (MHZ * 1e6)) / div
            cells.append(f"{rate:,.2f} {unit}" if rate < 10 else f"{rate:,.0f} {unit}")
        w("| " + " | ".join(cells) + " |")
    w("")
    w("Cycles per unit as above; for the phases counted in pixels, that is cycles per pixel.\n")

    w("### Text\n")
    w(f"Cycles per character (1b, assembly kernels, {REF}), and characters per second at "
      f"{MHZ:g} MHz. The TrueType text is anti-aliased at 2, 4 and 8 bits per pixel and "
      f"plain at 1.\n")
    w("| Phase | What | 1 bit | 2 bits | 4 bits | 8 bits | chars/s at 1 bit | chars/s at 8 bits |")
    w("|---|---|---:|---:|---:|---:|---:|---:|")
    for name in TEXT + ["ttf.first.12"]:
        cells = [f"`{name}`", DESCR.get(name, "")]
        for d in range(4):
            cells.append(fmt_n(per_unit(phase(runs, "text", d, best, name))))
        for d in (0, 3):
            cells.append(fmt_n(MHZ * 1e6 / per_unit(phase(runs, "text", d, best, name))))
        w("| " + " | ".join(cells) + " |")
    w("")
    w("Rasterising TrueType glyphs (the 62 letters and digits, into a buffer; the same "
      "work at every depth), in cycles and milliseconds per glyph:\n")
    w("| Size | Plain | ms | Anti-aliased | ms |")
    w("|---:|---:|---:|---:|---:|")
    for size in (12, 24, 48):
        a = per_unit(phase(runs, "text", 3, best, f"raster.mono.{size}"))
        b = per_unit(phase(runs, "text", 3, best, f"raster.aa.{size}"))
        w(f"| {size} px | {fmt_n(a)} | {fmt_ms(a)} | {fmt_n(b)} | {fmt_ms(b)} |")
    w("")

    w("### The window manager\n")
    w(f"Milliseconds per operation at {MHZ:g} MHz (1b, assembly kernels, {REF}):\n")
    w("| Phase | What | 1 bit | 2 bits | 4 bits | 8 bits |")
    w("|---|---|---:|---:|---:|---:|")
    for name in ["wm.glyphs"] + WM:
        cells = [f"`{name}`", DESCR.get(name, "")]
        for d in range(4):
            cells.append(fmt_ms(per_unit(phase(runs, "wm", d, best, name))))
        w("| " + " | ".join(cells) + " |")
    w("")

    # ---- 1a against 1b ----
    w("## 1a against 1b\n")
    w(f"Cycles, 1b / 1a ({REF}), for compiled C and with the assembly kernels; geometric "
      f"means over the phases of each scene and depth, then over everything.\n")
    w("| Scene | Depth | C | asm |")
    w("|---|---:|---:|---:|")
    allr = {"C": [], "asm": []}
    for scene in runmod.SCENES:
        for d in range(4):
            rr = {}
            for v in ("C", "asm"):
                xs = []
                for p in runs[scene][str(d)][f"1a {v}"]:
                    q = phase(runs, scene, d, f"1b {v}", p["name"])
                    if p["cycles"][REF] > 0:
                        xs.append(q["cycles"][REF] / p["cycles"][REF])
                rr[v] = geomean(xs)
                allr[v] += xs
            w(f"| {scene} | {1 << d} | {rr['C']:.3f} | {rr['asm']:.3f} |")
    w(f"| **all** | | **{geomean(allr['C']):.3f}** | **{geomean(allr['asm']):.3f}** |")
    w("")
    w("By phase at 8 bits per pixel (and 1 bit), with the assembly kernels:\n")
    w("| Phase | 1a | 1b | 1b / 1a | 1a, 1 bit | 1b, 1 bit | 1b / 1a |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    for scene, name in ALL:
        cells = [f"`{name}`"]
        for d in (3, 0):
            a = phase(runs, scene, d, "1a asm", name)["cycles"][REF]
            b = phase(runs, scene, d, "1b asm", name)["cycles"][REF]
            cells += [fmt_n(a), fmt_n(b), f"{b / a:.3f}"]
        w("| " + " | ".join(cells) + " |")
    w("")

    # ---- C against assembly ----
    w("## Compiled C against the assembly kernels\n")
    w(f"Cycles of the compiled C library over the same library with the assembly "
      f"kernels ({REF}): how much the hand-written inner loops buy. The rest of the "
      f"library (set-up, clipping, the scan converter, the TrueType decoder, the window "
      f"manager) is compiled C in both.\n")
    w("| Phase | 1a, 1 bit | 1a, 8 bits | 1b, 1 bit | 1b, 8 bits |")
    w("|---|---:|---:|---:|---:|")
    sp = {"1a": [], "1b": []}
    for scene, name in ALL:
        cells = [f"`{name}`"]
        for isa in ("1a", "1b"):
            for d in (0, 3):
                c = phase(runs, scene, d, f"{isa} C", name)["cycles"][REF]
                a = phase(runs, scene, d, f"{isa} asm", name)["cycles"][REF]
                cells.append(f"{c / a:.2f}")
                sp[isa].append(c / a)
        w("| " + " | ".join(cells) + " |")
    w(f"| **geometric mean** | **{geomean(sp['1a'][0::2]):.2f}** | **{geomean(sp['1a'][1::2]):.2f}** "
      f"| **{geomean(sp['1b'][0::2]):.2f}** | **{geomean(sp['1b'][1::2]):.2f}** |")
    w("")

    # ---- hardware configurations ----
    w("## Hardware configurations\n")
    w(f"Cycles relative to {REF}, geometric means over every phase at every depth (1b, "
      f"assembly kernels; 1a in brackets). {HW} is the configuration of the draft 1b "
      f"hardware; {WIDE} has a 32-bit bus.\n")
    w("| | separate | overlap | wide |")
    w("|---|---:|---:|---:|")
    for dp in (16, 32):
        cells = [f"{dp}-bit datapath"]
        for fetch in ("separate", "overlap", "wide"):
            cfg = f"D{dp}-{fetch}"
            r = {}
            for isa in ("1a", "1b"):
                xs = [p["cycles"][cfg] / p["cycles"][REF]
                      for s in runmod.SCENES for d in range(4)
                      for p in runs[s][str(d)][f"{isa} asm"] if p["cycles"][REF] > 0]
                r[isa] = geomean(xs)
            cells.append(f"{r['1b']:.2f} ({r['1a']:.2f})")
        w("| " + " | ".join(cells) + " |")
    w("")

    # ---- a barrel shifter ----
    w("## What a barrel shifter would save\n")
    w(f"The model charges a shift by n a step per 16, per 8 and per remaining bit "
      f"(timing-model-v1.md); a barrel shifter does any shift in one. The same runs, "
      f"re-costed with every shift at one step: cycles with the barrel shifter over "
      f"cycles without, and the share of cycles spent in shifts ({REF}, assembly "
      f"kernels).\n")
    w("| Phase | 1a, 1 bit | 1b, 1 bit | 1b, 2 bits | 1b, 4 bits | 1b, 8 bits | shifts' share, 1b, 1 bit |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    allb = []
    for scene, name in ALL:
        cells = [f"`{name}`"]
        for isa, d in (("1a", 0), ("1b", 0), ("1b", 1), ("1b", 2), ("1b", 3)):
            p = phase(runs, scene, d, f"{isa} asm", name)
            r = p["barrel"][REF] / p["cycles"][REF]
            cells.append(f"{r:.2f}")
            if isa == "1b":
                allb.append(r)
        p = phase(runs, scene, 0, "1b asm", name)
        cells.append(f"{100 * p['shifts'][REF] / p['cycles'][REF]:.0f}%")
        w("| " + " | ".join(cells) + " |")
    w(f"| **geometric mean (1b)** | | | | | **{geomean(allb):.3f}** | |")
    w("")

    # ---- a load/store-multiple ----
    w("## What a load- and store-multiple would save\n")
    w("The store-multiple experiment (asm/v1b/stm): 1b's fill and copy kernels with "
      "the whole words of long rows moved 8 at a time by SAVE and RESTORE, with sp "
      "pointed into the rows, as a stand-in for a load- and store-multiple through any "
      "register. Cycles with it over cycles without (1b, assembly kernels), at 1, 2, 4 "
      "and 8 bits per pixel. Only rows of 24 words or more (fills) and 17 or more "
      "(forward, unshifted copies) use it.\n")
    w(f"| Phase | {REF}: 1 bit | 2 | 4 | 8 | {WIDE}: 1 bit | 2 | 4 | 8 |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for scene, name in [("prims", "clear"), ("prims", "rect"), ("prims", "pattern"),
                        ("prims", "scroll.up"), ("wm", "wm.paint"), ("wm", "wm.move"),
                        ("wm", "wm.scroll"), ("wm", "wm.repaint")]:
        cells = [f"`{name}`"]
        for cfg in (REF, WIDE):
            for d in range(4):
                a = phase(runs, scene, d, "1b asm", name)["cycles"][cfg]
                s = phase(runs, scene, d, "1b stm", name)["cycles"][cfg]
                cells.append(f"{s / a:.2f}")
        w("| " + " | ".join(cells) + " |")
    w("")

    # ---- inner loops ----
    w("## The inner loops, word by word\n")
    w("Cycles per destination word of the kernels' inner loops, from the timing model, "
      "and of the same loops with instructions neither draft has (estimates: the "
      "hypothetical instructions are costed like the nearest ones the model has).\n")
    w(f"| Loop | {REF} | {HW} | Instructions |")
    w("|---|---:|---:|---|")
    for title, seq, per, instr in inner_loops():
        cyc = [sum(timing32.cycles(k, c) * n for k, n in seq) / per for c in (REF, HW)]
        w(f"| {title} | {cyc[0]:.1f} | {cyc[1]:.1f} | {instr} |")
    w("")
    return "\n".join(out)


def inner_loops():
    """(title, [(timing key, count)], words, instructions) for the inner
    loops and their what-ifs."""
    alu = (1, 0, "alu", 1)
    br = (1, 0, "br", 1, 0)                 # taken
    nbr = (1, 0, "br", 0, 0)                # not taken
    st_s, ld_s = (1, 0, "st", "rd", 4, 0), (1, 0, "ld", "rd", 4, 0)
    st_pi, ld_pi = (1, 0, "st", "pi", 4, 0), (1, 0, "ld", "pi", 4, 0)
    save8, rest8 = (1, 0, "save", 8), (1, 0, "restore", 8)
    lea = (2, 0, "lea", "rd", 0)

    def ror(n):
        return (1, 0, "shift", n)
    return [
        ("fill, 1a: 8 x ST [r + 4k], ADDI", [(st_s, 8), (alu, 2), (br, 1)], 8,
         "ST x 8, ADDI, DEC, BNE"),
        ("fill, 1b: 8 x ST [r]+", [(st_pi, 8), (alu, 1), (br, 1)], 8, "ST [r]+ x 8, DEC, BNE"),
        ("fill, SAVE r1-r8 (the experiment; a store-multiple)", [(save8, 1), (alu, 1), (br, 1)], 8,
         "SAVE, DEC, BNE"),
        ("copy, 1a: 4 x LD, ST [r + 4k], ADDI x 2", [(ld_s, 4), (st_s, 4), (alu, 3), (br, 1)], 4,
         "(LD, ST) x 4, ADDI x 2, DEC, BNE"),
        ("copy, 1b: 4 x MOV [r]+, ST [r]+", [(ld_pi, 4), (st_pi, 4), (alu, 1), (br, 1)], 4,
         "(MOV [r]+, ST [r]+) x 4, DEC, BNE"),
        ("copy, RESTORE and SAVE through sp (the experiment)",
         [(rest8, 1), (save8, 1), (alu, 3), (lea, 2), (br, 1)], 8,
         "MOV sp, RESTORE, MOV, LEA sp, SAVE, LEA, DEC, BNE"),
        ("copy, a load- and store-multiple with writeback (LDM, STM)",
         [(rest8, 1), (save8, 1), (alu, 1), (br, 1)], 8, "LDM, STM, DEC, BNE"),
        ("shifted copy, 1b, shift 3 (1 bit per pixel)", [(ld_pi, 2), (ror(3), 2), (alu, 7), (st_pi, 2), (br, 1)], 2,
         "(MOV [r]+, ROR, XOR, AND, XOR, ST [r]+) x 2, DEC, BNE"),
        ("shifted copy, 1b, shift 29", [(ld_pi, 2), (ror(7), 2), (alu, 7), (st_pi, 2), (br, 1)], 2,
         "the same; ROR by 29 is 7 steps"),
        ("shifted copy, 1b, with a barrel shifter", [(ld_pi, 2), (ror(1), 2), (alu, 7), (st_pi, 2), (br, 1)], 2,
         "the same, any ROR one step"),
        ("shifted copy, with a funnel shift (rd = rd:rs >> n, one step)",
         [(ld_pi, 2), (ror(1), 2), (alu, 1), (st_pi, 2), (br, 1)], 2,
         "(MOV [r]+, FSR, ST [r]+) x 2, DEC, BNE"),
        ("glyph pixels at 8 bits, two words (1b)",
         [(alu, 1), (lea, 1), (ld_pi, 1), (nbr, 2), (ld_s, 3), (alu, 6), (st_s, 2), (alu, 2),
          ((1, 0, "shift", 1), 1), (br, 1)], 2,
         "ZXB, LEA, LSR, BNE; a word: MOV, BEQ, MOV, BIC, AND, OR, ST, ADD"),
        ("the same with a merge under mask (d = d & ~m | c & m)",
         [(alu, 1), (lea, 1), (ld_pi, 1), (nbr, 2), (ld_s, 3), (alu, 2), (st_s, 2), (alu, 2),
          ((1, 0, "shift", 1), 1), (br, 1)], 2,
         "ZXB, LEA, LSR, BNE; a word: MOV, BEQ, MOV, MRG, ST, ADD"),
    ]


HEADER = """# Report 0019: generated tables

Generated by `heron graphics bench --write` from the graphics study
([studies/graphics](../../studies/graphics/README.md)); don't edit by hand.
The text is in [report 0019](../0019-report-graphics.md).

Every phase's screen matches the same C built with gcc, for both ISAs
and both builds, at every depth.

"""


def main(write=False):
    runs = collect()
    text = HEADER + report(runs)
    print(text)
    if write:
        os.makedirs(os.path.dirname(DOC), exist_ok=True)
        with open(DOC, "w") as f:
            f.write(text)
        print(f"wrote {os.path.relpath(DOC)}")
    return 0
