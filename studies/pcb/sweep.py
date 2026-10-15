"""The experiments behind RFC 0023: the CPU card at several sizes, as SMD
and DIP boards on four and six layers, its chips on a grid or anywhere;
the full checks on the boards the RFC recommends; the routed wires back
in the chip-level simulation; Freerouting on a free placement.

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

def _board(label, style, width, height, layers, sides="F", decaps=None, halo=None, full=False,
           arrangement="grid", pitch=None):
    return dict(label=label, style=style, width=width, height=height, layers=layers, sides=sides,
                decaps=decaps or ("under" if style == "smd" and sides == "F" else "beside"),
                halo=halo or (1.0 if style == "dip" else 0.8), full=full,
                arrangement=arrangement, pitch=pitch)


# first the grid (rows and columns of chips, all the same way round), then
# the parts anywhere ("free"), for comparison; full: all the checks, not
# only the netlist's
U6 = 233.35      # a 6U Eurocard's height

BOARDS = [
    _board("smd-6", "smd", 340, U6, 6, full=True),
    _board("smd-6", "smd", 330, U6, 6),
    _board("smd-6", "smd", 320, U6, 6),
    _board("smd-4", "smd", 480, U6, 4),
    _board("dip-6", "dip", 470, 320, 6, full=True),
    _board("dip-6", "dip", 460, 320, 6),
    _board("dip-4", "dip", 490, 345, 4, full=True),
    _board("dip-4", "dip", 500, 345, 4),
    _board("free-smd-6", "smd", 300, U6, 6, full=True, arrangement="free"),
    _board("free-smd-6", "smd", 280, U6, 6, arrangement="free"),
    _board("free-smd-6-top", "smd", 340, U6, 6, decaps="beside", arrangement="free"),
    _board("free-smd-4", "smd", 460, U6, 4, halo=1.2, full=True, arrangement="free"),
    _board("free-dip-6", "dip", 480, 320, 6, arrangement="free"),
    _board("free-dip-4", "dip", 500, 345, 4, full=True, arrangement="free"),
]

KEYS = ["name", "arrangement", "pitch", "style", "width", "height", "layers", "sides", "decaps", "utilisation",
        "unplaced", "legalize", "hpwl_m", "routed", "rounds", "conflicted", "track_m", "vias",
        "seconds_place", "seconds_route", "netlist_errors", "keepout_errors", "decaps_beside",
        "copper_opens", "copper_shorts",
        "drc_errors", "drc_unconnected", "ipc356_errors"]


def run_boards(only=None, reuse=False):
    out = []
    for bd in BOARDS:
        label, w, h = bd["label"], bd["width"], bd["height"]
        if only and only not in label:
            continue
        name = f"cpu-{label}-{int(w)}x{int(h)}"
        done = os.path.join(flow.OUT, name, "result.json")
        if reuse and os.path.exists(done):
            with open(done) as f:
                r = json.load(f)
        else:
            r = flow.build("cpu", bd["style"], w, h, layers=bd["layers"], sides=bd["sides"],
                           decaps=bd["decaps"], halo=bd["halo"],
                           checks=True if bd["full"] else "netlist", name=name,
                           arrangement=bd["arrangement"], pitch=bd["pitch"])
        r = {k: r.get(k) for k in KEYS}
        r["label"] = label
        print(json.dumps(r), flush=True)
        out.append(r)
    return out


CLOCK_TREE_PS = 6000      # CLK through a CDC341 tree: its delay, short branches
TIMING_BOARD = "cpu-smd-6-340x233"     # the board whose wires go into the simulation


def timing(board_name):
    """hello on the whole system at chip level with the routed CPU card's
    wires in, and the length classes worked out again with them (static
    timing analysis with the same per-pin delays): does the loop close?"""
    import copy

    from heron import native
    from heron.infra.pcb import board as B
    from heron.infra.pcb import wires
    from heron.studies.v1b_system import lengths, machine, programs

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
    clk_keys = wires.keys_of(w, "CLK")

    def no_clk(d):          # the timing analysis: CLK is its reference
        return {k: v for k, v in d.items() if k not in clk_keys}
    tree = {**no_clk(full), clk: CLOCK_TREE_PS}
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
             ("flight times", flight, no_clk(flight)),
             ("flight and load, CLK as routed", full, None),
             ("flight and load, CLK through a clock tree", tree, None),
             ("flight and load, CLK through a clock tree", tree, no_clk(full))]
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
             "load_ns": round((full.get(tuple(i["driver"]), 0) - min(i["loads"].values(), default=0))
                              / 1000, 1) if i["driver"] else None}
            for n, i in heavy]
    return rows, nets


def freerouting(timeout=3600, reuse=False):
    name = "cpu-smd-6-340x233-freerouting"
    done = os.path.join(flow.OUT, name, "result.json")
    if reuse and os.path.exists(done):
        with open(done) as f:
            r = json.load(f)
    else:
        r = flow.build("cpu", "smd", 340, U6, layers=6, halo=0.8, router_name="freerouting",
                       checks="netlist", name=name, freeroute_timeout=timeout, arrangement="free")
    return {k: r.get(k) for k in ("freerouting_exit", "freerouting_seconds", "freerouting_tracks",
                                  "track_m", "vias", "netlist_errors")}


def freerouting_text(fr):
    if not fr:
        return "not run."
    if fr["freerouting_exit"] == "timeout":
        return f"stopped at the time limit ({fr['freerouting_seconds']} s) with no result."
    return (f"exit code {fr['freerouting_exit']} after {fr['freerouting_seconds']} s; "
            f"{fr['track_m']} m of track, {fr['vias']} vias, {fr['netlist_errors']} differences "
            "from the netlist.")


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
        r["size"] = f"{r['width']:g} × {r['height']:g}"
        r["slots"] = f"{r['pitch'][0]} × {r['pitch'][1]}" if r.get("pitch") else ""
        r["checks"] = ("" if r.get("drc_errors") is None else
                       f"netlist {r['netlist_errors']}, keep-outs {r['keepout_errors']}, "
                       f"opens {r['copper_opens']}, shorts "
                       f"{r['copper_shorts']}, DRC {r['drc_errors']}, unconnected {r['drc_unconnected']}, "
                       f"fab test netlist {r['ipc356_errors']}")
    text = ["# RFC 0023: results", "",
            "Generated by `heron pcb sweep --write` (studies/pcb/sweep.py). Do not edit.", "",
            "## The CPU card at each size", "",
            "Board: the grid arrangement (rows and columns of chips, all the same way round), "
            "or with free-, the parts anywhere; -top: the capacitors beside the chips. Every board "
            "has the mechanics of RFC 0023 section 8: clear strips along its edges, the front "
            "panel's bracket holes, fiducials, the spacing around through-hole parts. "
            "Slots: the grid's, stretched to fill the board. "
            "Utilisation: the parts' courtyards over the board's area. Track: routed signal "
            "copper. Checks (where run): differences from the netlist, parts or copper in the "
            "keep-outs, copper opens and shorts, KiCad's DRC errors and "
            "unconnected items, differences of the fab's test netlist (IPC-D-356) from the board.", "",
            table(boards, ["label", "size", "layers", "slots", "utilisation", "result", "rounds",
                           "track_m", "vias", "seconds_place", "seconds_route", "checks"],
                  ["Board", "mm", "Layers", "Slots (mm)", "Utilisation", "Result", "Rounds",
                   "Track (m)", "Vias", "Place (s)", "Route (s)", "Checks"]), "",
            "## The routed wires in the chip-level simulation", "",
            "`hello` on the whole system (`studies/v1b_system`), with the CPU card's wires from "
            f"the {TIMING_BOARD.rsplit('-', 1)[1].replace('x', ' × ')} grid board: a delay on each "
            "driving pin, and one in front of each load further along its wire (infra/pcb/wires.py). "
            "\"Stopped after\" 3,000,000 cycles: the limit; the program never finished.", "",
            table(timing_rows, ["wires", "classes", "lengths", "slower", "output", "violations", "worst"],
                  ["Wires", "Length classes", "Ticks", "Program suite", "Output", "Violations",
                   "Worst"]), "",
            "Ticks: the four length classes (20 ns ticks). Program suite: its time against the "
            "design's classes, from the suite's profile. CLK through a clock tree: CLK late by "
            f"{CLOCK_TREE_PS / 1000:g} ns instead of its routed delay, as a CDC341 and short "
            "branches would make it.", "",
            "The most heavily loaded nets:", "",
            table(nets, ["net", "length_mm", "pF", "loads", "flight_ns", "load_ns"],
                  ["Net", "Length (mm)", "Load (pF)", "Loads", "Flight to the last (ns)",
                   "Delay of the load over 50 pF (ns)"]),
            "", "## Splitting the CPU card", "",
            f"Signals between the halves: control against datapath (by the netlist's sections) "
            f"{sp['control_datapath']}; the best balanced split found {sp['best']} "
            f"({sp['best_area']} of the area). `heron pcb split`.", "",
            "## Freerouting", "",
            "The free 340 × 233 (6U) six-layer placement, routed by Freerouting with its fanout off and "
            "only the signal layers, given an hour: " + freerouting_text(fr), ""]
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    with open(RESULTS, "w") as f:
        f.write("\n".join(text))


IMAGES = {"smd.png": (TIMING_BOARD, None), "smd-detail.png": (TIMING_BOARD, (0.36, 0.30, 0.62, 0.62)),
          "dip.png": ("cpu-dip-4-490x345", None)}


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


def describe(r):
    """A board's one-line description from its result.json."""
    style = "SMD" if r["style"] == "smd" else "DIP"
    how = "grid" if r.get("arrangement", "free") == "grid" else ("free, both sides" if r["sides"] == "FB" else "free")
    return f"{style}, {how} · {r['layers']} layers · {r['width']:g} × {r['height']:g} mm"


def viewer(names=None, out=None, standalone=True):
    """The boards (default: those with the full checks) as one web page."""
    from heron.infra.pcb import board as B
    from heron.infra.pcb import view
    if names is None:
        names = [f"cpu-{bd['label']}-{int(bd['width'])}x{int(bd['height'])}" for bd in BOARDS if bd["full"]]
    boards = []
    for name in names:
        folder = os.path.join(flow.OUT, name)
        with open(os.path.join(folder, "result.json")) as f:
            r = json.load(f)
        boards.append((name, describe(r), B.read_kicad(os.path.join(folder, "board.kicad_pcb"))))
    out = out or os.path.join(flow.OUT, "viewer.html")
    return view.write(out, boards, standalone=standalone)


def main(write=False, only=None, reuse=False, freeroute=True):
    """Run the experiments (only: the boards whose label has it; reuse: a
    board already built is read back, not built again) and, with write,
    the results and the pictures."""
    t = time.time()
    boards = run_boards(only, reuse)
    if only and not write:
        return 0
    timing_rows, nets = timing(TIMING_BOARD)
    fr = freerouting(reuse=reuse) if freeroute else {}
    sp = splits()
    if write:
        write_results(boards, timing_rows, nets, fr, sp)
        images()
    print(f"{time.time() - t:.0f} s")
    return 0
