"""The experiments behind RFC 0023: the CPU card at several sizes, as SMD
and DIP boards on four and six layers, with parts on one side or both;
the full checks on the boards the RFC recommends; the routed wires back
in the chip-level simulation; Freerouting on the same placement.

`heron pcb sweep` runs them (about an hour and a half, most of it the
DIP boards and Freerouting) and prints the tables; with --write it writes
reports/0023-rfc-pcb-flow/results.md.
"""

import json
import os
import time

from heron import ROOT

from . import flow

RESULTS = os.path.join(ROOT, "reports", "0023-rfc-pcb-flow", "results.md")

# (label, style, width, height, layers, sides, decaps, halo, full checks)
BOARDS = [
    ("smd-6", "smd", 380, 220, 6, "F", "under", 1.2, True),
    ("smd-6", "smd", 340, 220, 6, "F", "under", 0.8, False),
    ("smd-6", "smd", 300, 220, 6, "F", "under", 0.8, True),
    ("smd-6", "smd", 280, 220, 6, "F", "under", 0.8, False),
    ("smd-6", "smd", 260, 220, 6, "F", "under", 0.8, False),
    ("smd-6", "smd", 280, 233, 6, "F", "under", 0.8, False),
    ("smd-6-top", "smd", 340, 220, 6, "F", "beside", 0.8, False),
    ("smd-6-top", "smd", 320, 220, 6, "F", "beside", 0.8, False),
    ("smd-6-both", "smd", 280, 220, 6, "FB", "beside", 1.2, False),
    ("smd-6-both", "smd", 260, 220, 6, "FB", "beside", 1.2, False),
    ("smd-4", "smd", 380, 220, 4, "F", "under", 1.2, False),
    ("smd-4", "smd", 440, 260, 4, "F", "under", 1.2, False),
    ("smd-4", "smd", 460, 260, 4, "F", "under", 1.2, True),
    ("dip-6", "dip", 480, 300, 6, "F", "beside", 1.0, True),
    ("dip-6", "dip", 440, 300, 6, "F", "beside", 1.0, False),
    ("dip-6", "dip", 400, 300, 6, "F", "beside", 1.0, False),
    ("dip-4", "dip", 520, 300, 4, "F", "beside", 1.0, False),
    ("dip-4", "dip", 480, 300, 4, "F", "beside", 1.0, True),
]

KEYS = ["name", "style", "width", "height", "layers", "sides", "decaps", "utilisation",
        "unplaced", "legalize", "hpwl_m", "routed", "rounds", "conflicted", "track_m", "vias",
        "seconds_place", "seconds_route", "netlist_errors", "copper_opens", "copper_shorts",
        "drc_errors", "drc_unconnected", "ipc356_errors"]


def run_boards(only=None, reuse=False):
    out = []
    for label, style, w, h, layers, sides, decaps, halo, full in BOARDS:
        if only and only not in label:
            continue
        name = f"cpu-{label}-{w}x{h}"
        done = os.path.join(flow.OUT, name, "result.json")
        if reuse and os.path.exists(done):
            with open(done) as f:
                r = json.load(f)
        else:
            r = flow.build("cpu", style, w, h, layers=layers, sides=sides, decaps=decaps,
                           halo=halo, checks=True if full else "netlist", name=name)
        r = {k: r.get(k) for k in KEYS}
        r["label"] = label
        print(json.dumps(r), flush=True)
        out.append(r)
    return out


CLOCK_TREE_PS = 6000      # CLK through a CDC341 tree: its delay, short branches


def timing(board_name):
    """hello on the whole system at chip level with the routed CPU card's
    wires in, and the length classes worked out again with them (static
    timing analysis with the same per-pin delays): does the loop close?"""
    import copy

    from heron import native
    from heron.infra.pcb import board as B
    from heron.infra.pcb import wires
    from heron.studies.system import lengths, machine, programs

    from . import cards
    nl_cpu = cards.netlists()["cpu"]
    b = B.read_kicad(os.path.join(flow.OUT, board_name, "board.kicad_pcb"))
    b.style = "smd"
    w = wires.nets(b, nl_cpu)
    full = wires.back_annotate(nl_cpu, w)
    w0 = copy.deepcopy(w)
    for v in w0.values():
        v["pF"] = 0.0
    flight = wires.back_annotate(nl_cpu, w0)
    clk = tuple(w["CLK"]["driver"])
    buffered = {k: v for k, v in full.items() if k != clk}      # STA: CLK is the reference
    tree = dict(buffered, **{clk: CLOCK_TREE_PS})
    path = programs.program_paths(["hello"])[0]
    img = programs.assemble(path)
    inp = programs.metadata(path)["input"]
    _, ideal = machine.classes()
    base_ticks = ideal["ticks"]
    derived = {}

    def classes_for(label, sta_wires):
        if label not in derived:
            cls, lens, ticks, _ = lengths.assign(wires=sta_wires)
            derived[label] = (cls, lens, ticks)
        return derived[label]

    rows = []
    cases = [("ideal wires (as simulated)", {}, None),
             ("flight times", flight, None),
             ("flight times", flight, flight),
             ("flight and load, CLK as routed", full, None),
             ("flight and load, CLK through a clock tree", tree, None),
             ("flight and load, CLK through a clock tree", tree, buffered)]
    for label, sim, sta_wires in cases:
        pre = machine.preloads(img, inp)
        if sta_wires is None:
            lens, ticks, which = machine.default_lengths(), base_ticks, "the design's"
        else:
            cls, lens, ticks = classes_for(label, sta_wires)
            pre["CPU.U_UC15"] = bytes(lengths.class_rom(cls))
            which = "worked out for the board"
        nl = machine.build(tuple(lens))
        wires.apply(nl, sim, prefix="CPU.")
        hw = native.hwsim.run_system(nl.export(), machine.config(3_000_000), pre)
        out = bytes(hw["dumps"]["IO.U_UART"])
        worst = hw["violation_summary"][0] if hw["violation_summary"] else None
        rows.append({"wires": label, "classes": which, "lengths": " ".join(map(str, lens)),
                     "slower": f"{ticks / base_ticks - 1:+.1%}",
                     "output": "right" if out == programs.expected("hello") else
                     f"wrong, stopped after {hw['cycles']} cycles",
                     "violations": hw["violation_total"],
                     "worst": "" if not worst else
                     f"{worst['what'].replace('CPU.', '')} {worst['worst_slack_ps'] / 1000:.1f} ns"})
        print(json.dumps(rows[-1]), flush=True)
    heavy = sorted(w.items(), key=lambda kv: -kv[1]["pF"])[:8]
    nets = [{"net": n, "length_mm": round(i["length"]), "pF": round(i["pF"]),
             "loads": len(i["loads"]), "flight_ns": round(max(i["loads"].values(), default=0) / 1000, 1),
             "extra_ns": round(full.get(tuple(i["driver"]), 0) / 1000, 1) if i["driver"] else None}
            for n, i in heavy]
    return rows, nets


def freerouting(timeout=3600, reuse=False):
    name = "cpu-smd-6-340x220-freerouting"
    done = os.path.join(flow.OUT, name, "result.json")
    if reuse and os.path.exists(done):
        with open(done) as f:
            r = json.load(f)
    else:
        r = flow.build("cpu", "smd", 340, 220, layers=6, halo=0.8, router_name="freerouting",
                       checks="netlist", name=name, freeroute_timeout=timeout)
    return {k: r.get(k) for k in ("freerouting_exit", "freerouting_seconds", "freerouting_tracks",
                                  "track_m", "vias", "netlist_errors")}


def table(rows, cols, heads):
    out = ["| " + " | ".join(heads) + " |", "|" + "|".join("---" for _ in heads) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if r.get(c) is None else str(r[c]) for c in cols) + " |")
    return "\n".join(out)


def splits():
    from . import split
    chips, area, nets = split._setup()
    natural = {i.ref: 0 if i.section in split.CONTROL else 1 for i in chips}
    c, side, a = split.best_split(nets, area, natural)
    return {"control_datapath": len(split.cut(nets, natural)), "best": len(c),
            "best_area": f"{a[0] / sum(a):.0%} / {a[1] / sum(a):.0%}"}


def write_results(boards, timing_rows, nets, fr, sp):
    def verdict(r):
        if r["unplaced"]:
            return f"doesn't fit ({r['unplaced']} parts)"
        if not r["routed"]:
            return f"not routed ({r['conflicted']} nets in conflict)"
        return "routed"
    for r in boards:
        r["result"] = verdict(r)
        r["size"] = f"{r['width']} × {r['height']}"
        r["checks"] = ("" if r.get("drc_errors") is None else
                       f"netlist {r['netlist_errors']}, opens {r['copper_opens']}, shorts "
                       f"{r['copper_shorts']}, DRC {r['drc_errors']}, unconnected {r['drc_unconnected']}, "
                       f"fab test netlist {r['ipc356_errors']}")
    text = ["# RFC 0023: results", "",
            "Generated by `heron pcb sweep --write` (studies/pcb/sweep.py). Do not edit.", "",
            "## The CPU card at each size", "",
            "Utilisation: the parts' courtyards over the board's area (both sides' "
            "area for double-sided boards). Track: routed signal copper. Checks (where run): "
            "differences from the netlist, copper opens and shorts, KiCad's DRC errors and "
            "unconnected items, differences of the fab's test netlist (IPC-D-356) from the board.", "",
            table(boards, ["label", "size", "layers", "utilisation", "result", "rounds", "track_m",
                           "vias", "seconds_place", "seconds_route", "checks"],
                  ["Board", "mm", "Layers", "Utilisation", "Result", "Rounds", "Track (m)", "Vias",
                   "Place (s)", "Route (s)", "Checks"]), "",
            "## The routed wires in the chip-level simulation", "",
            "`hello` on the whole system (`studies/system`), with the CPU card's wires from "
            "the 300 × 220 board as per-pin delays (infra/pcb/wires.py).", "",
            table(timing_rows, ["wires", "classes", "lengths", "slower", "output", "violations", "worst"],
                  ["Wires", "Length classes", "Ticks", "Program suite", "Output", "Violations",
                   "Worst"]), "",
            "Ticks: the four length classes (20 ns ticks). Program suite: its time against the "
            "design's classes, from the suite's profile. CLK through a clock tree: CLK late by "
            f"{CLOCK_TREE_PS / 1000:g} ns instead of its routed delay, as a CDC341 and short "
            "branches would make it.", "",
            "The most heavily loaded nets:", "",
            table(nets, ["net", "length_mm", "pF", "loads", "flight_ns", "extra_ns"],
                  ["Net", "Length (mm)", "Load (pF)", "Loads", "Flight (ns)", "Extra delay (ns)"]),
            "", "## Splitting the CPU card", "",
            f"Signals between the halves: control against datapath (by the netlist's sections) "
            f"{sp['control_datapath']}; the best balanced split found {sp['best']} "
            f"({sp['best_area']} of the area). `heron pcb split`.", "",
            "## Freerouting", "",
            "The 340 × 220 six-layer placement, routed by Freerouting with its fanout off and "
            "only the signal layers, given an hour:", "",
            "```", json.dumps(fr, indent=1), "```", ""]
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    with open(RESULTS, "w") as f:
        f.write("\n".join(text))


IMAGES = {"smd.png": ("cpu-smd-6-300x220", None), "smd-detail.png": ("cpu-smd-6-300x220", (0.36, 0.30, 0.62, 0.62)),
          "dip.png": ("cpu-dip-4-480x300", None)}


def images():
    """Pictures of the routed boards for the RFC: the whole SMD and DIP
    boards, and a detail of the SMD one at full scale, as small PNGs."""
    from PIL import Image

    from heron.infra.pcb import board as B
    from heron.infra.pcb import render
    folder = os.path.dirname(RESULTS)
    for out, (name, crop) in IMAGES.items():
        path = os.path.join(flow.OUT, name, "board.kicad_pcb")
        if not os.path.exists(path):
            continue
        b = B.read_kicad(path)
        tmp = os.path.join(flow.OUT, name, "render.png")
        render.render(b, tmp, scale=6 if crop else 3, labels=not crop)
        im = Image.open(tmp)
        if crop:
            w, h = im.size
            im = im.crop((int(w * crop[0]), int(h * crop[1]), int(w * crop[2]), int(h * crop[3])))
        if im.size[0] > 1400:
            im = im.resize((1400, im.size[1] * 1400 // im.size[0]), Image.LANCZOS)
        im.quantize(colors=48).save(os.path.join(folder, out), optimize=True)


def main(write=False, only=None, reuse=False, freeroute=True):
    """Run the experiments (only: the boards whose label has it; reuse: a
    board already built is read back, not built again) and, with write,
    the results and the pictures."""
    t = time.time()
    boards = run_boards(only, reuse)
    if only and not write:
        return 0
    timing_rows, nets = timing("cpu-smd-6-300x220")
    fr = freerouting(reuse=reuse) if freeroute else {}
    sp = splits()
    if write:
        write_results(boards, timing_rows, nets, fr, sp)
        images()
    print(f"{time.time() - t:.0f} s")
    return 0
