"""The schematic editor's measurements (bench.c) over the kernel variants,
the modes and the layouts, as markdown tables in results.md:

    python3 studies/mini_gfx/apps/schematic/measure.py            # print
    python3 studies/mini_gfx/apps/schematic/measure.py --write    # results.md

from the repository's root; about 15 minutes on four cores. Each run is the program with bench = 1 and no script; its
"@perf" lines are ticks of 19.86 ns (frames of 840,000), shown here in ms.
"""

import argparse
import concurrent.futures
import glob
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from heron import BUILD
from heron.studies.mini_gfx import programs
from heron.studies.mini.timing import TICK

HERE = os.path.dirname(os.path.abspath(__file__))
WM_SNAP, WM_F1 = 4, 8

# (name, mode, layout, F1)
CONFIGS = [
    ("M5 L0", 5, "L0", 0), ("M5 F1", 5, "L0", 1), ("M5 L1", 5, "L1", 0),
    ("M6 L0", 6, "L0", 0), ("M6 F1", 6, "L0", 1),
    ("M0 L0", 0, "L0", 0), ("M0 L1", 0, "L1", 0),
]
VARIANTS = ["c", "asm", "blk"]
# extra runs: (name, config, variant, pokes)
EXTRAS = [
    ("library kernels", "M5 L0", "asm", {"lib_kernels": 1}),
    ("ghost as one XOR copy", "M5 L0", "asm", {"ghost_blit": 1}),
    ("ghost as one XOR copy", "M5 F1", "asm", {"ghost_blit": 1}),
    ("ghost as one XOR copy", "M5 L1", "asm", {"ghost_blit": 1}),
    ("ghost as one XOR copy", "M6 F1", "asm", {"ghost_blit": 1}),
]


def clear_cache():
    # build.py's object cache keys on rt/, gfx/ and wm/'s headers, not on
    # sch.h: objects of these files may be stale
    for f in ("schematic", "view", "bench", "sheet", "symbols", "xpand", "sheetview", "sch_wm"):
        for p in glob.glob(os.path.join(BUILD, "mini_gfx", "obj", f"{f}.c-*")):
            os.remove(p)


def run(config, variant, pokes=None):
    name, mode, layout, f1 = next(c for c in CONFIGS if c[0] == config)
    p = programs.get("apps/schematic")
    pk = {"_bench": 1, "_sch_mode": mode, "_sch_opts": WM_SNAP | (WM_F1 if f1 else 0)}
    for k, v in (pokes or {}).items():
        pk["_" + k] = v
    r = p.run(variant=variant, layout=layout, frames=4000, script="", pokes=pk)
    if r.trap:
        raise RuntimeError(f"{config} {variant}: trap {r.trap}")
    out = {k: v for k, v in r.perf.items()}
    out["_output"] = r.output
    return out


def ms(t):
    return f"{t * TICK / 1e6:.1f}"


def us(t):
    return f"{t * TICK / 1e3:.0f}"


# the rows of the main table: (label, key, index, unit)
ROWS = [
    ("sprites, all 40 at the zoom", "sprites_all", 0, ms),
    ("full redraw (17 parts, 25 wires)", "redraw", 0, ms),
    ("  the same, parts as lines", "redraw_vector", 0, ms),
    ("  clearing", "layer_clear", 0, ms),
    ("  grid", "layer_grid", 0, ms),
    ("  wires", "layer_wires", 0, ms),
    ("  parts", "layer_parts", 0, ms),
    ("  labels", "layer_labels", 0, ms),
    ("  junction dots", "layer_dots", 0, ms),
    ("whole canvas to the screen (WM)", "compose_full", 0, ms),
    ("wire band: editor, a frame", "band_store_app", 0, ms),
    ("wire band: WM, a frame", "band_store_frame", 0, ms),
    ("wire band on the screen: editor", "band_screen_app", 0, ms),
    ("wire band on the screen: WM", "band_screen_frame", 0, ms),
    ("wire band redrawn: editor", "band_redraw_app", 0, ms),
    ("wire band redrawn: WM", "band_redraw_frame", 0, ms),
    ("crosshair in software, a frame", "crosshair_app", 0, ms),
    ("placing: the ghost in XOR, a frame", "place_xor_frame", 0, ms),
    ("placing: the ghost as the cursor", "place_cursor_frame", 0, ms),
    ("the mouse moving, no ghost", "hover_frame", 0, ms),
    ("move 3 parts: editor, a frame", "move_store_app", 0, ms),
    ("move 3 parts: WM, a frame", "move_store_frame", 0, ms),
    ("move: the drop", "move_store_drop", 0, ms),
    ("pan 4 steps across: editor", "pan_across_app", 0, ms),
    ("pan 4 steps down: editor", "pan_down_app", 0, ms),
    ("pan: WM, a frame", "pan_across_frame", 0, ms),
    ("pan by a step, not a word: editor", "pan_shift_app", 0, ms),
    ("pan by the mouse: editor, a frame", "pan_drag_app", 0, ms),
    ("sheet view: drawing the sheet", "sheet_render", 0, ms),
    ("sheet view: a pan (descriptors)", "sheet_pan", 0, ms),
    ("sheet view: wire band, a frame", "sheet_band_app", 0, ms),
    ("zoom to 1 (sprites, redraw)", "zoom_1", 0, ms),
    ("zoom to 4 (sprites, redraw)", "zoom_4", 0, ms),
    ("100 lines across, 200 px", "lines_across", 0, ms),
    ("100 lines down, 200 px (library fill)", "lines_down", 0, ms),
    ("100 lines down, 200 px (sch_vline)", "lines_vline", 0, ms),
    ("100 lines diagonal, 200 px", "lines_diagonal", 0, ms),
    ("100 lines across in XOR", "lines_across_xor", 0, ms),
    ("100 lines down in XOR (sch_vline)", "lines_vline_xor", 0, ms),
    ("junctions (example)", "junctions", 0, ms),
    ("net highlight: the search", "net", 0, ms),
    ("stress (68 parts, 100 wires): redraw at zoom 1", "stress_redraw_z1", 0, ms),
    ("stress: redraw at zoom 2", "stress_redraw_z2", 0, ms),
    ("stress: junctions", "stress_junctions", 0, ms),
    ("stress: net search", "stress_net", 0, ms),
]

PARTS = ["res", "cap", "nand", "nor", "inv", "dip14", "conn", "led", "gnd", "vcc"]


def table(results, configs, variants, rows):
    cols = [(c, v) for c in configs for v in variants if (c, v) in results]
    head = "| | " + " | ".join(f"{c} {v}" for c, v in cols) + " |"
    sep = "|---|" + "---:|" * len(cols)
    lines = [head, sep]
    for label, key, i, fmt in rows:
        cells = []
        for c in cols:
            v = results[c].get(key)
            cells.append(fmt(v[i]) if v and len(v) > i else "")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--only", help="a config, e.g. 'M5 L0'")
    args = ap.parse_args(argv)
    clear_cache()
    # one build of each variant first, so the jobs don't all compile
    for v in VARIANTS:
        programs.get("apps/schematic").build(v)
    jobs = [(c[0], v, None, None) for c in CONFIGS for v in VARIANTS
            if not args.only or c[0] == args.only]
    jobs += [(c, v, p, n) for n, c, v, p in EXTRAS if not args.only or c == args.only]
    results, extras = {}, {}
    with concurrent.futures.ProcessPoolExecutor(args.jobs) as ex:
        futs = {ex.submit(run, c, v, p): (c, v, p, n) for c, v, p, n in jobs}
        for f in concurrent.futures.as_completed(futs):
            c, v, p, n = futs[f]
            r = f.result()
            if n:
                extras[(n, c, v)] = r
            else:
                results[(c, v)] = r
            print(f"done {c} {v} {n or ''}", flush=True)
    names = [c[0] for c in CONFIGS]
    out = ["# The schematic editor's measurements", "",
           "Generated by `measure.py` (bench.c with `bench = 1`, no script): milliseconds,",
           "from ticks of 19.86 ns; a frame is 16.7 ms. The editor's own work and the",
           "window manager's (\"WM\": the frame's events and the copies of the damage to",
           "the screen) are apart.", ""]
    for group in (names[:3], names[3:5], names[5:]):
        out += [f"## {', '.join(group)}", "", table(results, group, VARIANTS, ROWS), ""]
    out += ["## A part drawn (µs): from its sprite / from its lines", ""]
    rows = []
    for pt in PARTS:
        rows.append((pt + " sprite", f"part_{pt}_spr", 0, us))
        rows.append((pt + " lines", f"part_{pt}_vec", 0, us))
    out += [table(results, names, ["asm"], rows), ""]
    out += ["## Text: \"74HC132\" (µs)", ""]
    rows = [("sans12, a glyph at a time (font_draw)", "text_font_draw", 0, us),
            ("sans12, put together, then one expansion", "text_once", 0, us),
            ("sans12, the bitmap cached", "text_cached", 0, us),
            ("the 3 x 5 font, put together", "text_tiny", 0, us)]
    out += [table(results, names, ["c", "asm"], rows), ""]
    out += ["## Filling and copying (ticks a word)", ""]
    tw = lambda t: f"{t / 10:.1f}"
    rows = [("fill: the library", "word_fill_lib", 0, tw), ("fill: SAVE, sp borrowed", "word_fill_save", 0, tw),
            ("fill: FILL", "word_fill_blk", 0, tw), ("copy: the library", "word_copy_lib", 0, tw),
            ("copy: RESTORE and SAVE", "word_copy_rs", 0, tw), ("copy: COPY", "word_copy_blk", 0, tw)]
    out += [table(results, ["M5 L0"], VARIANTS, rows), ""]
    out += ["## Variations (asm)", "", "| | config | redraw | move: editor, a frame | parts |",
            "|---|---|---:|---:|---:|"]
    for (n, c, v), r in sorted(extras.items()):
        base = results.get((c, v), {})
        out.append(f"| {n} | {c} | {ms(r['redraw'][0])} ({ms(base.get('redraw', [0])[0])}) | "
                   f"{ms(r['move_store_app'][0])} ({ms(base.get('move_store_app', [0])[0])}) | "
                   f"{ms(r['layer_parts'][0])} ({ms(base.get('layer_parts', [0])[0])}) |")
    out += ["", "(In brackets: the same run without the variation.)", ""]
    text = "\n".join(out)
    if args.write:
        with open(os.path.join(HERE, "results.md"), "w") as f:
            f.write(text)
    else:
        print(text)
    for (c, v), r in sorted(results.items()):
        for line in r["_output"].splitlines():
            if "xcheck" in line or "blocks" in line:
                print(f"{c} {v}: {line}")


if __name__ == "__main__":
    main()
