"""The flow from a card's netlist to a checked board, in one call:

    netlist -> parts (packages, pinouts, decoupling, connectors)
            -> placement (global, legal, detail; capacitors)
            -> power fanout and planes
            -> routing (the grid router, or Freerouting)
            -> the board file, a picture
            -> checks: pads against the netlist, the copper's connectivity
               (after KiCad fills the planes), KiCad's DRC

Each step's results go into a dict, which `heron pcb build` prints and the
sweep collects.
"""

import json
import os
import shutil
import subprocess
import time

from heron import BUILD
from heron.infra.pcb import board as B
from heron.infra.pcb import check, copper, dsn, fanout, place, render, router

from . import cards

OUT = os.path.join(BUILD, "pcb")


def kicad_cli():
    return shutil.which("kicad-cli")


def pcbnew_available():
    try:
        import pcbnew  # noqa: F401
        return True
    except ImportError:
        return False


def drc(path):
    """KiCad's DRC of a board file: (errors by type, unconnected items), or
    None without kicad-cli."""
    cli = kicad_cli()
    if not cli:
        return None
    out = path[:-len(".kicad_pcb")] + "-drc.json"
    subprocess.run([cli, "pcb", "drc", "--severity-error", "--format", "json", "-o", out, path],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    with open(out) as f:
        d = json.load(f)
    types = {}
    for v in d["violations"]:
        types[v["type"]] = types.get(v["type"], 0) + 1
    return types, len(d["unconnected_items"])


def build(card="cpu", style="smd", width=380.0, height=220.0, layers=6, sides="F", halo=None,
          seed=1, moves=30000, router_name="grid", route_params=None, out=None, checks=True,
          name=None, freeroute_timeout=3600, decaps=None, timing_driven=True):
    """Build one board and check it. Returns a dict of what happened."""
    res = {"card": card, "style": style, "width": width, "height": height, "layers": layers,
           "sides": sides, "router": router_name}
    name = name or f"{card}-{style}-{int(width)}x{int(height)}-{layers}L-{sides}"
    out = out or os.path.join(OUT, name)
    os.makedirs(out, exist_ok=True)
    res["name"] = name
    t0 = time.time()
    b = cards.board(card, style, width, height, layers=layers)
    nl = b.netlist
    chips = [p for p in b.parts.values() if p.kind == "chip"]
    res["chips"] = len(chips)
    res["parts"] = len(b.parts)
    court = sum((p.fp.courtyard[2] - p.fp.courtyard[0]) * (p.fp.courtyard[3] - p.fp.courtyard[1])
                for p in b.parts.values() if p.kind != "conn")
    res["courtyard_mm2"] = round(court)
    res["utilisation"] = round(court / (width * height * (2 if sides == "FB" else 1)), 3)
    if halo is None:
        halo = 1.2 if style == "smd" else 1.0
    decaps = decaps or ("under" if style == "smd" and sides == "F" else "beside")
    res["decaps"] = decaps
    pl = place.Placer(b, region=(3.0, 3.0, width - 3.0, height - 3.0), halo=halo,
                      grid=0.635 if style == "smd" else 1.27, sides=sides, decaps=decaps, seed=seed,
                      weights=cards.weights(nl) if timing_driven else None)
    pl.global_place()
    targets = {p.ref: (p.x, p.y, p.side) for p in pl.movable}
    # largest first packs the surface-mount boards best, left to right the
    # DIP ones: try one, then the other
    for order in (("size", "x") if style == "smd" else ("x", "size")):
        for p in pl.movable:
            p.place(*targets[p.ref][:2], p.rot, targets[p.ref][2])
        unplaced = pl.legalize(order=order)
        if not unplaced:
            break
    res["legalize"] = order
    res["unplaced"] = len(unplaced)
    if unplaced:
        res["result"] = "does not fit"
        res["seconds_place"] = round(time.time() - t0, 1)
        with open(os.path.join(out, "result.json"), "w") as f:
            json.dump(res, f, indent=1)
        return res
    w0, w1 = pl.refine(moves=moves)
    res["hpwl_m"] = round(w1 / 1000, 1)
    place.place_decaps(b, side="B" if decaps == "under" else "F")
    res["fanout"] = fanout.fanout(b)
    b.add_planes()
    res["seconds_place"] = round(time.time() - t0, 1)
    path = os.path.join(out, "board.kicad_pcb")
    t1 = time.time()
    if router_name == "grid":
        sol = router.route(b, **(route_params or {}))
        res["rounds"] = len(sol["rounds"])
        res["conflicted"] = len(sol["conflicted"])
        res["failed"] = len(sol["failed"]) + len(sol["unreachable"])
        res["routed"] = not (sol["conflicted"] or sol["failed"] or sol["unreachable"])
    else:
        res.update(freeroute(b, out, timeout=freeroute_timeout))
    res["seconds_route"] = round(time.time() - t1, 1)
    routed = {n for n in b.nets() if n not in b.planes.values()}
    res["track_m"] = round(sum(abs(t[3] - t[1]) + abs(t[4] - t[2]) for t in b.tracks
                               if t[6] in routed) / 1000, 1)
    res["vias"] = sum(1 for v in b.vias if v[4] in routed)
    b.write(path)
    render.render(b, os.path.join(out, "board.png"), scale=3, labels=False)
    if checks:
        res.update(check_board(path, nl, b.style, b.pin_maps, full=checks != "netlist"))
    res["seconds"] = round(time.time() - t0, 1)
    with open(os.path.join(out, "result.json"), "w") as f:
        json.dump(res, f, indent=1)
    return res


def check_board(path, nl, style, pin_maps, full=True):
    """The checks of a board file: the pads against the netlist; with
    `full` and KiCad, the planes filled, the copper's connectivity, and
    the DRC."""
    res = {}
    t = time.time()
    rb = B.read_kicad(path)
    errs = check.compare(nl, rb, style, pin_maps)
    res["netlist_errors"] = len(errs)
    res["netlist_sample"] = errs[:5]
    if not full:
        res["seconds_check"] = round(time.time() - t, 1)
        return res
    if pcbnew_available():
        copper.fill_zones(path)
        rb = B.read_kicad(path)
        cerrs = copper.check(rb)
        res["copper_opens"] = sum(1 for e in cerrs if e.startswith("open"))
        res["copper_shorts"] = sum(1 for e in cerrs if e.startswith("short"))
        res["copper_sample"] = cerrs[:5]
    d = drc(path)
    if d is not None:
        res["drc_errors"] = sum(d[0].values())
        res["drc_types"] = d[0]
        res["drc_unconnected"] = d[1]
        # the fab's files, and its test netlist against the board
        fab(path, len([l for l in rb.copper]))
        ipc = os.path.join(os.path.dirname(path), "fab", "netlist.ipc")
        ierrs = check.compare_ipc356(ipc, rb)
        res["ipc356_errors"] = len(ierrs)
        res["ipc356_sample"] = ierrs[:5]
    res["seconds_check"] = round(time.time() - t, 1)
    return res


def fab(path, layers):
    """The fabrication and assembly files for a board, with kicad-cli,
    into fab/ beside it: Gerbers of the copper, mask, paste, silkscreen
    and outline layers, the drill files, the placement file for assembly,
    and the IPC-D-356 netlist the fab tests the bare board against.
    Returns the files' names."""
    cli = kicad_cli()
    if not cli:
        return None
    out = os.path.join(os.path.dirname(path), "fab")
    os.makedirs(out, exist_ok=True)
    cu = ["F.Cu"] + [f"In{i}.Cu" for i in range(1, layers - 1)] + ["B.Cu"]
    lay = cu + ["F.Mask", "B.Mask", "F.Paste", "B.Paste", "F.SilkS", "B.SilkS", "Edge.Cuts"]
    run = lambda *a: subprocess.run([cli, "pcb", "export", *a], check=True,       # noqa: E731
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    run("gerbers", "-o", out + "/", "-l", ",".join(lay), path)
    run("drill", "-o", out + "/", path)
    run("pos", "--format", "csv", "--units", "mm", "-o", os.path.join(out, "positions.csv"), path)
    run("ipcd356", "-o", os.path.join(out, "netlist.ipc"), path)
    return sorted(os.listdir(out))


def freeroute(b, out, timeout=3600, threads=3):
    """Route with Freerouting through DSN and SES: only the signal layers
    are given to it (the planes are KiCad's)."""
    sig = b.signal_layers
    full = b.stackup
    b.stackup = [(l, None) for l in sig]
    dpath = os.path.join(out, "board.dsn")
    spath = os.path.join(out, "board.ses")
    dsn.write(b, dpath, protect=set(full_net for _, full_net in full if full_net))
    b.stackup = full
    t = time.time()
    try:
        code = dsn.freeroute(dpath, spath, passes=100, threads=threads, timeout=timeout,
                             log=os.path.join(out, "freerouting.log"),
                             extra=["--router.fanout.enabled=false"])
    except subprocess.TimeoutExpired:
        code = "timeout"
    res = {"freerouting_exit": code, "freerouting_seconds": round(time.time() - t)}
    if os.path.exists(spath):
        n, v = dsn.read_ses(b, spath)
        res["freerouting_tracks"] = n
    return res
