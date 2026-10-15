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
    ("smd-4", "smd", 340, 220, 4, "F", "under", 0.8, False),
    ("dip-6", "dip", 480, 300, 6, "F", "beside", 1.0, True),
    ("dip-6", "dip", 440, 300, 6, "F", "beside", 1.0, False),
    ("dip-6", "dip", 400, 300, 6, "F", "beside", 1.0, False),
    ("dip-4", "dip", 520, 300, 4, "F", "beside", 1.0, False),
    ("dip-4", "dip", 480, 300, 4, "F", "beside", 1.0, False),
]

KEYS = ["name", "style", "width", "height", "layers", "sides", "decaps", "utilisation",
        "unplaced", "legalize", "hpwl_m", "routed", "rounds", "conflicted", "track_m", "vias",
        "seconds_place", "seconds_route", "netlist_errors", "copper_opens", "copper_shorts",
        "drc_errors", "drc_unconnected", "ipc356_errors"]


def run_boards(only=None):
    out = []
    for label, style, w, h, layers, sides, decaps, halo, full in BOARDS:
        if only and only not in label:
            continue
        name = f"cpu-{label}-{w}x{h}"
        r = flow.build("cpu", style, w, h, layers=layers, sides=sides, decaps=decaps, halo=halo,
                       checks=True if full else "netlist", name=name)
        r = {k: r.get(k) for k in KEYS}
        r["label"] = label
        print(json.dumps(r), flush=True)
        out.append(r)
    return out


def timing(board_name):
    """hello on the system at chip level, with the routed CPU card's wires
    in: none, flight times only, the extra load only, both."""
    import copy

    from heron import native
    from heron.infra.pcb import board as B
    from heron.infra.pcb import wires
    from heron.studies.system import machine, programs

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
    clk_driver = w["CLK"]["driver"]
    load_only = {k: full[k] - flight.get(k, 0) for k in full}
    path = programs.program_paths(["hello"])[0]
    img = programs.assemble(path)
    inp = programs.metadata(path)["input"]
    rows = []
    for label, ann in (("ideal wires (as simulated)", {}),
                       ("flight times", flight),
                       ("extra load, CLK left out", {k: v for k, v in load_only.items() if k != tuple(clk_driver)}),
                       ("extra load on CLK alone", {k: v for k, v in load_only.items() if k == tuple(clk_driver)}),
                       ("both", full)):
        nl = machine.build(machine.default_lengths())
        wires.apply(nl, ann, prefix="CPU.")
        hw = native.hwsim.run_system(nl.export(), machine.config(3_000_000),
                                     machine.preloads(img, inp))
        out = bytes(hw["dumps"]["IO.U_UART"])
        worst = min((v["worst_slack_ps"] for v in hw["violation_summary"]), default=0)
        rows.append({"wires": label, "output": out == programs.expected("hello"),
                     "cycles": hw["cycles"], "violations": hw["violation_total"],
                     "worst_slack_ns": round(worst / 1000, 1)})
        print(json.dumps(rows[-1]), flush=True)
    heavy = sorted(w.items(), key=lambda kv: -kv[1]["pF"])[:8]
    nets = [{"net": n, "length_mm": round(i["length"]), "pF": round(i["pF"]),
             "loads": len(i["loads"]), "flight_ns": round(max(i["loads"].values(), default=0) / 1000, 1),
             "extra_ns": round(full.get(tuple(i["driver"]), 0) / 1000, 1) if i["driver"] else None}
            for n, i in heavy]
    return rows, nets


def freerouting(timeout=3600):
    r = flow.build("cpu", "smd", 340, 220, layers=6, halo=0.8, router_name="freerouting",
                   checks="netlist", name="cpu-smd-6-340x220-freerouting",
                   freeroute_timeout=timeout)
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
            table(timing_rows, ["wires", "output", "cycles", "violations", "worst_slack_ns"],
                  ["Wires", "Output right", "Cycles", "Violations", "Worst slack (ns)"]), "",
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


def main(write=False, only=None):
    t = time.time()
    boards = run_boards(only)
    timing_rows, nets = timing("cpu-smd-6-300x220")
    fr = freerouting() if not only else {}
    sp = splits()
    if write:
        write_results(boards, timing_rows, nets, fr, sp)
    print(f"{time.time() - t:.0f} s")
    return 0
