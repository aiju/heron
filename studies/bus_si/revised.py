"""Report 0022's sweeps: the signal-integrity questions of RFC 0014's
2026-10-14 draft (its section 17), on the native engine.

Each preset is a list of jobs (JSON-able tuples, the first element the
kind) and `run_job` runs one. sweep.py runs them in parallel, resumably.
"""

from dataclasses import replace

from . import bus, bused, floating, gb, radial, xt

PATTERNS = {
    "all16": range(16),
    "half8": range(0, 16, 2),
    "four": (0, 5, 10, 15),
    "two": (0, 15),
    "pair": (0, 1),                 # the nearest receiver and nothing else: hold time
}
DRIVERS = {"all16": (0, 3, 7), "half8": (0, 6, 14), "four": (0, 5), "two": (0,), "pair": (0,)}
BUS_FAMILIES = ("abt", "fct", "hct")
CORNERS = ("min", "max")


def _loading_jobs():
    out = []
    for pat in PATTERNS:
        for stub in (25, 50, 75):
            for c in (9, 12, 15, 20, 25):
                for fam in BUS_FAMILIES:
                    card = bused.Card(family=fam, stub=stub * 1e-3)
                    if bused.card_c(card) > (c + 0.5) * 1e-12:
                        continue            # this stub alone is more than c
                    for corner in CORNERS:
                        for d in DRIVERS[pat]:
                            out.append(("load", pat, stub, c, fam, corner, d))
    return out


def _conn_jobs():
    out = []
    for l_nh in (6, 9, 12, 15, 20):
        for c_pf in (1, 2, 3):
            for fam in ("abt", "fct"):
                for corner in CORNERS:
                    for d in (0, 7):
                        out.append(("conn", l_nh, c_pf, fam, corner, d))
    return out


def _geom_jobs():
    out = []
    for slots in (8, 12, 16, 20):
        for pitch in (15.24, 20.32, 25.4):
            for stub in (25, 50):
                for fam in ("abt", "fct"):
                    for corner in CORNERS:
                        for d in (0, (slots - 1) // 2):
                            out.append(("geom", slots, pitch, stub, fam, corner, d))
    return out


# where the backplane's logic might sit (mm from slot 0): beyond slot 0's
# end, in the middle, a quarter of the way along
DEVICE_X = {"end": -40.0, "middle": 7.5 * 20.32, "quarter": 3.5 * 20.32}


def _bpl_jobs():
    out = []
    for where in DEVICE_X:
        for fam in ("abt", "fct"):
            for series in (0, 22, 33):
                for corner in CORNERS:
                    out.append(("bpl-drive", where, fam, series, corner))
            for d in (0, 7, 15):
                for corner in CORNERS:
                    out.append(("bpl-receive", where, fam, d, corner))
    return out


def _sel_jobs():
    # SEL and GNT: a register on the backplane to one slot; lengths from a
    # slot next to the logic to the far end of a 16-slot backplane
    out = []
    for length in (50, 100, 200, 350):
        for series in (0, 22, 33, 47, 56, 68, 82):
            for rx in ("hct", "abt"):
                for count in (1, 2, 3):
                    for corner in ("min", "typ", "max"):
                        out.append(("sel", length, series, rx, count, corner))
    return out


# the clock driver in the middle of the backplane, this far below the
# connector row; slot k's trace runs along to it
CLOCK_OFFSET = 30.0


def clock_lengths(slots=16, pitch=20.32, matched=False):
    mid = (slots - 1) / 2 * pitch
    raw = [abs(k * pitch - mid) + CLOCK_OFFSET for k in range(slots)]
    return [max(raw)] * slots if matched else raw


def _clock_jobs():
    # one clock-driver package's six outputs to six slots: the nearest six
    # (slots 5-10) or the farthest (0-2 and 13-15)
    out = []
    for drv in ("cdc329a", "abt244"):
        for group in ("near", "far", "far3"):
            for matched in (False, True):
                for series in (33, 47, 56, 68):
                    for rx in ("abt244", "cdc329a"):
                        for corner in ("min", "typ", "max"):
                            for rails in CLOCK_RAILS:
                                out.append(("clock", drv, group, matched, series, rx, corner, rails))
    return out


# how the clock driver's own rails are modelled: ideal; through its
# package pins with the IBIS fit's crowbar current and 50 pF across the
# die; the same without crowbar current; with 200 pF across the die
CLOCK_RAILS = {"ideal": None, "pkg": dict(die_c=50e-12), "pkg-bbm": dict(die_c=50e-12, overlap=False),
               "pkg-200p": dict(die_c=200e-12),
               "pkg-cal": dict(die_c=50e-12, overlap=False, alpha=gb.CALIBRATED_ALPHA)}


GB_PARTS = [("abt", "dip"), ("abt", "soic"), ("abt16245", "tssop"), ("abt2245", "soic"),
            ("fct", "dip"), ("fct", "soic"), ("act", "soic")]


def _gb_jobs():
    out = []
    for fam, pkg in GB_PARTS:
        for model in ("raw", "calibrated"):
            for edge in ("falling", "rising"):
                for corner in ("typ", "max"):
                    for lines in (16, 32):
                        for decaps in (1, 0):
                            out.append(("gb", fam, pkg, lines, model, edge, corner, decaps, None))
                    # one line switching alone: the baseline for push-out
                    out.append(("gb", fam, pkg, 16, model, edge, corner, 1, 1))
    for fam, pkg in GB_PARTS:
        for model in ("raw", "calibrated"):
            out.append(("volp", fam, pkg, model))
    return out


def _xt_jobs():
    out = []
    for fam in ("hct", "abt"):
        for pkg in ("soic", "dip"):
            for model in ("raw", "calibrated"):
                for guard in (True, False):
                    for edge in ("rising", "falling"):
                        for corner in ("typ", "max"):
                            for sel_r in (33, 56, 68):
                                out.append(("xt", fam, pkg, model, guard, edge, corner, sel_r))
    return out


def _floating_jobs():
    out = []
    for victim in ("wait", "class"):
        for k in (0.07, 0.35):
            for fam in ("abt", "fct"):
                for corner in CORNERS + ("typ",):
                    for agg in (0, 7):
                        out.append(("floating", victim, fam, corner, agg, k))
    return out


PRESETS = {
    "floating": _floating_jobs,
    "crosstalk": _xt_jobs,
    "groundbounce": _gb_jobs,
    "sel": _sel_jobs,
    "clock": _clock_jobs,
    "loading": _loading_jobs,
    "connector": _conn_jobs,
    "geometry": _geom_jobs,
    "backplane": _bpl_jobs,
}


def jobs(preset):
    return PRESETS[preset]()


def _card12(fam, stub=25e-3, c=12e-12):
    card = bused.Card(family=fam, stub=stub)
    return replace(card, extra_c=bused.extra_for(c, card))


def _summary(res, b):
    w = bused.worst(res)
    w["ref"] = res["ref"]
    w["card_c"] = [bused.card_c(c) if c else None for c in b.cards]
    return w


def run_job(job):
    kind = job[0]
    if kind == "load":
        _, pat, stub, c, fam, corner, d = job
        card = bused.Card(family=fam, stub=stub * 1e-3)
        card = replace(card, extra_c=bused.extra_for(c * 1e-12, card))
        b = bused.Bus.full().with_cards(set(PATTERNS[pat]), card)
        res = bused.run(b, ("slot", d), corner)
        return {"worst": _summary(res, b), "rx": res["rx"]}
    if kind == "conn":
        _, l_nh, c_pf, fam, corner, d = job
        bp = bus.Backplane(package="soic", conn_l=l_nh * 1e-9, conn_c=c_pf * 1e-12)
        b = bused.Bus.full(bp=bp, card=_card12(fam))
        return {"worst": _summary(bused.run(b, ("slot", d), corner), b)}
    if kind == "geom":
        _, slots, pitch, stub, fam, corner, d = job
        bp = bus.Backplane(slots=slots, pitch=pitch * 1e-3, package="soic")
        b = bused.Bus.full(bp=bp, card=_card12(fam, stub * 1e-3, max(12e-12, bused.card_c(
            bused.Card(family=fam, stub=stub * 1e-3)))))
        return {"worst": _summary(bused.run(b, ("slot", d), corner), b)}
    if kind == "bpl-drive":
        _, where, fam, series, corner = job
        dev = bused.Device(x=DEVICE_X[where] * 1e-3, family=fam, series=series)
        b = replace(bused.Bus.full(card=_card12("abt")), devices=(dev,))
        res = bused.run(b, ("dev", 0), corner)
        return {"worst": _summary(res, b), "rx": res["rx"]}
    if kind == "bpl-receive":
        _, where, fam, d, corner = job
        dev = bused.Device(x=DEVICE_X[where] * 1e-3, family="abt")
        b = replace(bused.Bus.full(card=_card12(fam)), devices=(dev,))
        res = bused.run(b, ("slot", d), corner)
        return {"worst": _summary(res, b), "device": res["rx"]["d0"]}
    if kind == "sel":
        _, length, series, rx, count, corner = job
        path = radial.Radial(length=length * 1e-3, series=series, rx_family=rx, rx_count=count)
        res = radial.run(radial.Driver(), [path], corner)
        return res
    if kind == "clock":
        _, drv, group, matched, series, rx, corner, rails = job
        lengths = clock_lengths(matched=matched)
        # six outputs of one package, or three (the other three unused)
        slots = {"near": range(5, 11), "far": (0, 1, 2, 13, 14, 15), "far3": (0, 1, 2)}[group]
        rx_pkg = "ssop" if rx.startswith("cdc") else "soic"
        paths = [radial.Radial(length=lengths[k] * 1e-3, series=series, rx_family=rx, rx_package=rx_pkg)
                 for k in slots]
        n_gnd, n_vcc = {"cdc329a": (3, 2), "abt244": (1, 1)}[drv]
        pkg = "ssop" if drv == "cdc329a" else "soic"
        if CLOCK_RAILS[rails] is None:
            driver = radial.Driver(family=drv, package=pkg)
        else:
            driver = radial.Driver(family=drv, package=pkg, n_gnd=n_gnd, n_vcc=n_vcc, **CLOCK_RAILS[rails])
        res = radial.run(driver, paths, corner)
        res["slots"] = list(slots)
        return res
    if kind == "gb":
        _, fam, pkg, lines, model, edge, corner, decaps, switching = job
        c = gb.Card.model(model, family=fam, package=pkg, lines=lines, decaps=decaps, switching=switching,
                          series=0.0 if fam == "abt2245" else 22.0)
        return gb.run(c, corner, edge == "falling")
    if kind == "floating":
        _, victim, fam, corner, agg, k = job
        return floating.run(victim, fam, corner, aggressor_slot=agg, k_conn=k)
    if kind == "xt":
        _, fam, pkg, model, guard, edge, corner, sel_r = job
        return xt.run(xt.card(fam, pkg, model), corner, edge == "falling", guard, sel_r)
    if kind == "volp":
        _, fam, pkg, model = job
        kw = {} if model == "raw" else dict(overlap=False, alpha=gb.CALIBRATED_ALPHA)
        return {"volp": gb.volp(fam, pkg, "typ", **kw), "vohv": gb.volp(fam, pkg, "typ", falling=False, **kw)}
    raise ValueError(kind)


def cost(job):
    return {"gb": 3.0, "xt": 2.0, "clock": 0.5, "sel": 0.2}.get(job[0], 1.0) * (2 if job[0] == "gb" and job[3] == 32 else 1)
