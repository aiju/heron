"""Comparing two runs of a preset, job by job: the native engine against
report 0013's ngspice results.

    python3 -m heron bus_si compare reports/0013-report-bus-si/full.json \\
        reports/0021-report-bus-si-revised/full.json
"""

import json

import numpy as np

# per kind: the measurements compared, in the units they're stored in
FIELDS = {
    "ref": ["rise", "fall"],
    "line": ["rise", "fall", "vmax", "vmin", "voh", "vol", "extra"],
    "clock": ["t50", "tr", "vmax", "vmin", "extra"],
    "xtalk": ["peak"],
    "sso": ["quiet", "die_gnd", "card_gnd"],
}
TIMES = {"rise", "fall", "t50", "tr"}


def _values(kind, res):
    """(name, slot, value) for each measurement of one job's result."""
    if kind == "ref":
        for f in FIELDS[kind]:
            yield f, None, res[f]
    elif kind == "line":
        for k, s in res["slots"].items():
            for f in FIELDS[kind]:
                yield f, k, s[f]
    elif kind == "clock":
        for edge in ("rise", "fall"):
            for k, s in res[edge].items():
                for f in FIELDS[kind]:
                    yield f"{edge} {f}", k, s[f]
    elif kind == "xtalk":
        for k, (base, peak) in res["slots"].items():
            yield "peak", k, peak - base
    elif kind == "sso":
        for f in FIELDS[kind]:
            yield f, None, res[f]


def compare(a_path, b_path):
    """Differences b − a for every measurement both have. Returns
    {(kind, field): array of differences}, the jobs only one has a result
    for, and the measurements where one side is missing (didn't settle)."""
    a = {json.dumps(r["job"]): r for r in json.load(open(a_path))["records"]}
    b = {json.dumps(r["job"]): r for r in json.load(open(b_path))["records"]}
    diffs, only, missing = {}, {"a": [], "b": []}, []
    for k in sorted(set(a) | set(b)):
        ra, rb = a.get(k), b.get(k)
        ok_a = ra is not None and ra["result"] is not None
        ok_b = rb is not None and rb["result"] is not None
        if ok_a != ok_b:
            only["a" if ok_a else "b"].append(json.loads(k))
            continue
        if not ok_a:
            continue
        kind = json.loads(k)[0]
        if kind not in FIELDS:
            continue
        va = {(f, s): v for f, s, v in _values(kind, ra["result"])}
        for f, s, v in _values(kind, rb["result"]):
            w = va.get((f, s))
            if (v is None) != (w is None):
                missing.append((json.loads(k), f, s, w, v))
            elif v is not None:
                diffs.setdefault((kind, f), []).append(v - w)
    return {k: np.array(v) for k, v in diffs.items()}, only, missing


def summary(a_path, b_path):
    diffs, only, missing = compare(a_path, b_path)
    lines = ["| Kind | Measurement | Values | Median |Δ| | 95th percentile | Largest |",
             "|---|---|---:|---:|---:|---:|"]
    for (kind, f), d in sorted(diffs.items()):
        scale, unit = (1e9, "ns") if f.split()[-1] in TIMES else (1, "" if "extra" in f else "V")
        ad = np.abs(d) * scale
        lines.append(f"| {kind} | {f} | {len(d)} | {np.median(ad):.3f} {unit} | "
                     f"{np.percentile(ad, 95):.3f} {unit} | {ad.max():.3f} {unit} |")
    out = "\n".join(lines)
    out += (f"\n\nJobs with a result only in the first: {len(only['a'])}; only in the second: "
            f"{len(only['b'])}. Measurements present in only one: {len(missing)}.")
    return out, diffs, only, missing


def main(argv):
    import sys
    a, b = argv[:2]
    out, _, only, missing = summary(a, b)
    print(out)
    for j in only["b"][:80]:
        print("  only second:", j)
    for j in only["a"][:80]:
        print("  only first:", j)
    for m in missing[:40]:
        print("  missing on one side:", m)
    sys.stdout.flush()
    return 0
