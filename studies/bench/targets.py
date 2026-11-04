"""The implementations the workloads are timed on, in absolute time.

Each target runs a workload's image from reset to HALT and gives its
instructions, cycles, time and console output; the output is checked
against the expected, so a time is only quoted for a correct run. Runs
are slow (the register-transfer models run thousands of cycles a
second), so they are cached in build/bench/, by the image, its input
and the target's own sources.

    v2_hw   Full Heron (RFC 0031): the register-transfer model, which the
            chip-level netlist matches cycle for cycle, code and data in the
            CPU card's RAM, costed with the length classes the CPU's own
            report picked (LENGTHS, ticks of 20 ns).

Other implementations (Heron Mini, Chibi Heron, Reed) add a target here
when their models are on main: a function from (image, input,
max_cycles) to the row below.
"""

import json
import os

from . import suite

# Full Heron's four length classes, as RFC 0031's performance.md has them
# (heron v2_hw report picks them from its own suite's profile).
V2_HW_LENGTHS = (4, 5, 6, 9)
V2_HW_TICK_NS = 20


def _v2_hw_tag():
    from heron.studies.v2_hw import perf
    return "v2_hw-" + perf._sources_tag() + "-" + "-".join(map(str, V2_HW_LENGTHS))


def run_v2_hw(mem, inp, max_cycles):
    from types import SimpleNamespace
    from heron.studies.v2_hw import check, perf
    m = check.run_rtl(SimpleNamespace(mem=mem), inp, profile=True, max_cycles=max_cycles)
    row = {"instructions": m.instructions, "cycles": m.cycles,
           "hold": m.hold_ticks, "ucount": dict(m.ucount)}
    ticks = perf.time_with([dict(row, name="x")], V2_HW_LENGTHS)["x"]
    return {"instructions": m.instructions, "cycles": m.cycles, "ticks": ticks,
            "ms": ticks * V2_HW_TICK_NS / 1e6, "output": bytes(m.out).decode("latin-1")}


TARGETS = {"v2_hw": (run_v2_hw, _v2_hw_tag)}


def _one(target, name, size, mem, inp, max_cycles, path):
    fn, _ = TARGETS[target]
    row = fn(mem, inp, max_cycles)
    row.update(name=name, size=size)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(row, f)
    os.replace(path + ".tmp", path)
    return row


def times(target, names, size="ref", jobs=4, force=False):
    """[row] for the workloads on a target: name, instructions, cycles, ms,
    ok (the output was the expected)."""
    if target not in TARGETS:
        raise suite.BenchError(f"no target {target!r} (there are: {', '.join(TARGETS)})")
    tag = TARGETS[target][1]()
    todo, rows = [], {}
    for n in names:
        w = suite.get(n)
        img, inp = w.image(size)
        path = os.path.join(suite.OUT, target, f"{n}-{size}-{suite.image_key(img, inp)}-{tag}.json")
        if not force and os.path.exists(path):
            with open(path) as f:
                rows[n] = json.load(f)
        else:
            todo.append((n, dict(img.mem), inp, w.max_cycles, path))
    if todo:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(min(jobs, len(todo))) as ex:
            futs = {ex.submit(_one, target, n, size, mem, inp, mc, path): n
                    for n, mem, inp, mc, path in todo}
            for f, n in futs.items():
                rows[n] = f.result()
    out = []
    for n in names:
        row = dict(rows[n])
        row["ok"] = row["output"].encode("latin-1") == suite.get(n).expected(size)
        out.append(row)
    return out
