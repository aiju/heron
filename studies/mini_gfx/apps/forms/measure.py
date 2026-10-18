"""The forms application's measurements, NOTES.md's tables: the program
run with its script in each configuration (a variant, a mode and layout,
the run's pokes), its @perf lines collected and printed as markdown.

    python3 studies/mini_gfx/apps/forms/measure.py [--jobs 4] [TABLE ...]

The tables: variants, modes, options, bench (the pieces timed on their
own, forms.c's run_bench). The 1024 x 768 modes run xga.script. A run
takes 10-40 seconds; the whole set a few minutes on four cores.
"""

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
TICK = 19.86e-9
QUIT = "40 keydown ctrl\n40 key q\n40 keyup ctrl\n"
WM_SNAP, WM_SOFTCURSOR, WM_F1 = 4, 1, 8

OPS = ["type_field", "type_search", "select_move", "scroll_row", "scroll_page", "scroll_drag",
       "sort", "open_record", "save", "delete", "popup", "chart", "full_redraw", "caret_blink",
       "startup"]
BENCH = ["glyphs", "cells", "strip_clear", "strip_text", "strip_put", "gfx_expand", "strip_cells",
         "font_draw_row", "table_row", "store_scroll", "screen_rows", "screen_rows_shifted",
         "filter0_scan", "filter1_bolt", "filter2_bolt", "filter3_bolt", "filter3_scan",
         "sort0_desc", "sort1_desc", "sort0_qty", "sort1_qty"]


def cfg(label, variant="blk", mode=0, layout="L0", options=WM_SNAP, **pokes):
    return {"label": label, "variant": variant, "mode": mode, "layout": layout,
            "pokes": dict(pokes, mode=mode, options=options)}


TABLES = {
    "variants": [cfg(v, variant=v) for v in ("c", "asm", "blk")],
    "modes": [
        cfg("M0 L0", "c"), cfg("M0 L0", "blk"), cfg("M0 L1", "blk", layout="L1"),
        cfg("M3 L0", "c", 3), cfg("M3 L0", "blk", 3), cfg("M3 F1", "blk", 3, options=12),
        cfg("M3 L1", "c", 3, "L1"), cfg("M3 L1", "blk", 3, "L1"),
        cfg("M4 L1", "blk", 4, "L1"),
        cfg("M5 L1", "c", 5, "L1"), cfg("M5 L1", "blk", 5, "L1"),
        cfg("M5 F1", "blk", 5, options=12),
        cfg("M6 L1", "c", 6, "L1"), cfg("M6 L1", "blk", 6, "L1"), cfg("M6 L0", "blk", 6),
    ],
    "options": [
        cfg("default: row cache, prefiltered search"),
        cfg("no row cache", row_cache=0),
        cfg("selection by palette bank", sel_banks=1),
        cfg("rows glyph by glyph (font_draw), no cache", list_font=1, row_cache=0),
        cfg("rows in the cell font, no cache", list_font=2, row_cache=0),
        cfg("fields redrawn whole", fw_field_full=1),
        cfg("search: every record scanned", filter_mode=0),
        cfg("sort: the C library's qsort", sort_mode=0),
        cfg("no WM_SNAP", options=0),
        cfg("software cursor", options=WM_SNAP | WM_SOFTCURSOR),
        cfg("c: default", "c"),
        cfg("c: the library's expansion", "c", fw_put=0),
        cfg("M3 L1: default", "blk", 3, "L1"),
        cfg("M3 L1: the library's expansion", "blk", 3, "L1", fw_put=0),
    ],
    "bench": [
        dict(cfg("M0 L0", "c"), bench=1), dict(cfg("M0 L0", "asm"), bench=1),
        dict(cfg("M0 L0", "blk"), bench=1), dict(cfg("M3 L1", "c", 3, "L1"), bench=1),
        dict(cfg("M3 L1", "blk", 3, "L1"), bench=1), dict(cfg("M3 L0", "blk", 3), bench=1),
        dict(cfg("M5 L1", "blk", 5, "L1"), bench=1), dict(cfg("M6 L1", "blk", 6, "L1"), bench=1),
        dict(cfg("M6 L0", "blk", 6), bench=1),
    ],
}


def run(c):
    sys.path.insert(0, ROOT)
    from heron.studies.mini_gfx import programs
    p = programs.get("apps/forms")
    pokes = {"_" + k: v for k, v in c["pokes"].items()}
    if c.get("bench"):
        pokes["_bench"] = 1
        script = QUIT
    elif c["mode"] >= 5:
        with open(os.path.join(HERE, "xga.script")) as f:
            script = f.read()
    else:
        script = None
    r = p.run(c["variant"], c["layout"], None, None, script, None, 0, pokes)
    return c, r.perf, r.trap, r.stats


def ms(ticks):
    return f"{ticks * TICK * 1e3:.1f}"


def table(rows, keys, bench=False):
    head = ["", ""] + [k.replace("_", " ") for k in keys]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * 2 + "---:|" * len(keys)]
    for c, perf, trap, stats in rows:
        cells = [c["label"], c["variant"]]
        for k in keys:
            v = perf.get(("b." if bench else "") + k)
            if not v:
                cells.append("")
            elif bench and k == "glyphs":
                cells.append(str(v[0]))
            else:
                cells.append(ms(v[0]))
        if trap:
            cells[0] += " (trap)"
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tables", nargs="*", default=list(TABLES))
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args(argv)
    for name in args.tables:
        with ProcessPoolExecutor(args.jobs) as ex:
            rows = list(ex.map(run, TABLES[name]))
        print(f"\n### {name} (ms: the average of an operation's frames)\n")
        if name == "bench":
            print(table(rows, BENCH, bench=True))
        else:
            print(table(rows, OPS))
            steals = [(c["label"], c["variant"], s["steal_ticks"], s["underruns"])
                      for c, _, _, s in rows if s["steal_ticks"] or s["underruns"]]
            if steals:
                print("\nsteals and underruns:", steals)
        sys.stdout.flush()


if __name__ == "__main__":
    main()
