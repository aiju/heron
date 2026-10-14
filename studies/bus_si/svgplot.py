"""Waveforms as standalone SVG line charts, for the report's figures.

No plotting library: a figure is a row of panels sharing a legend, each
with its own axes, threshold lines labelled in the right margin, and up to
three traces. Colours follow the viewer's light or dark scheme.
"""

import math

import numpy as np

# series colours (light, dark), in this order; checked for colour-blind
# separation in both schemes
SERIES = [("#2a78d6", "#3987e5"), ("#eb6834", "#d95926"), ("#1baf7a", "#199e70")]

_STYLE = """
svg {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }}
.bg {{ fill: #fcfcfb; }}
.ink {{ fill: #0b0b0b; }}
.ink2 {{ fill: #52514e; }}
.muted {{ fill: #6f6d68; }}
.grid {{ stroke: #e1e0d9; stroke-width: 1; }}
.axis {{ stroke: #c3c2b7; stroke-width: 1; }}
.mark {{ stroke: #52514e; stroke-width: 1; }}
.tr {{ fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }}
{light}
@media (prefers-color-scheme: dark) {{
  .bg {{ fill: #1a1a19; }}
  .ink {{ fill: #f0efec; }}
  .ink2 {{ fill: #c3c2b7; }}
  .muted {{ fill: #9a988f; }}
  .grid {{ stroke: #2c2c2a; }}
  .axis {{ stroke: #383835; }}
  .mark {{ stroke: #c3c2b7; }}
{dark}
}}
"""

LEGEND_H = 30
TOP = 34            # panel title
BOTTOM = 34         # x ticks and label
LEFT = 50
RIGHT = 80          # threshold labels
GAP = 16


def _ticks(lo, hi, n=6):
    """Round tick values covering [lo, hi]."""
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    first = math.ceil(lo / step - 1e-9) * step
    return [round(first + i * step, 10) for i in range(int((hi - first) / step + 1e-9) + 1)]


def _fmt(x):
    s = f"{x:g}"
    return s.replace("-", "−")


def _decimate(px, py, width):
    """The points of one trace, at most two per pixel (the lowest and
    highest, in time order), so peaks survive."""
    if len(px) <= 2 * width:
        return px, py
    bins = np.floor(px - px[0]).astype(int)
    xs, ys = [], []
    starts = np.flatnonzero(np.diff(bins, prepend=-1))
    for a, b in zip(starts, list(starts[1:]) + [len(px)]):
        seg = py[a:b]
        i, j = a + int(np.argmin(seg)), a + int(np.argmax(seg))
        for k in sorted({i, j}):
            xs.append(px[k])
            ys.append(py[k])
    return np.array(xs), np.array(ys)


def _yrange(p):
    """Round limits around every trace in the x window and every mark."""
    xlo, xhi = p["x"]
    vals = [v[(t >= xlo) & (t <= xhi)] for _, t, v in p["series"]]
    lo = min([float(v.min()) for v in vals] + [m[0] for m in p.get("marks", ())])
    hi = max([float(v.max()) for v in vals] + [m[0] for m in p.get("marks", ())])
    pad = 0.06 * (hi - lo)
    lo, hi = lo - pad, hi + pad
    ticks = _ticks(lo, hi, 5)
    step = ticks[1] - ticks[0]
    lo, hi = math.floor(lo / step) * step, math.ceil(hi / step) * step
    return lo, hi, [round(lo + i * step, 10) for i in range(round((hi - lo) / step) + 1)]


def _panel(p, x0, y0, w, h, uid):
    """One panel: p has title, x (lo, hi), xlabel, series [(slot, t, v)],
    marks [(value, label)] and optionally y (lo, hi)."""
    out = []
    pl, pt = x0 + LEFT, y0 + TOP
    pw, ph = w - LEFT - RIGHT, h - TOP - BOTTOM
    xlo, xhi = p["x"]
    if p.get("y"):
        ylo, yhi = p["y"]
        yt = _ticks(ylo, yhi, 5)
    else:
        ylo, yhi, yt = _yrange(p)

    def sx(x):
        return pl + (x - xlo) / (xhi - xlo) * pw

    def sy(y):
        return pt + ph - (y - ylo) / (yhi - ylo) * ph

    out.append(f'<text class="ink" x="{pl}" y="{y0 + 16}" font-size="13" font-weight="600">{p["title"]}</text>')
    for v in yt:
        y = sy(v)
        unit = " V" if v == yt[-1] else ""
        out.append(f'<line class="grid" x1="{pl}" x2="{pl + pw}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text class="muted" x="{pl - 6}" y="{y + 4:.1f}" font-size="11" '
                   f'text-anchor="end">{_fmt(v)}{unit}</text>')
    for v in _ticks(xlo, xhi, 6):
        x = sx(v)
        out.append(f'<line class="axis" x1="{x:.1f}" x2="{x:.1f}" y1="{pt + ph}" y2="{pt + ph + 4}"/>')
        out.append(f'<text class="muted" x="{x:.1f}" y="{pt + ph + 16}" font-size="11" text-anchor="middle">{_fmt(v)}</text>')
    out.append(f'<line class="axis" x1="{pl}" x2="{pl + pw}" y1="{pt + ph}" y2="{pt + ph}"/>')
    out.append(f'<text class="muted" x="{pl + pw}" y="{pt + ph + 30}" font-size="11" text-anchor="end">{p["xlabel"]}</text>')
    # threshold lines, labelled in the right margin; labels that would
    # overlap move apart
    marks = sorted(p.get("marks", ()), key=lambda m: -m[0])
    last = -1e9
    for v, label in marks:
        y = sy(v)
        out.append(f'<line class="mark" x1="{pl}" x2="{pl + pw + 4}" y1="{y:.1f}" y2="{y:.1f}"/>')
        ty = max(y + 4, last + 13)
        last = ty
        out.append(f'<text class="ink2" x="{pl + pw + 7}" y="{ty:.1f}" font-size="11">{label}</text>')
    cid = f"c{uid}"
    out.append(f'<clipPath id="{cid}"><rect x="{pl}" y="{pt}" width="{pw}" height="{ph}"/></clipPath>')
    for slot, t, v in p["series"]:
        sel = (t >= xlo) & (t <= xhi)
        px, py = _decimate(sx(t[sel]), sy(v[sel]), pw)
        d = "M" + " ".join(f"{a:.1f} {b:.1f}" for a, b in zip(px, py))
        out.append(f'<path class="tr s{slot}" clip-path="url(#{cid})" d="{d}"/>')
    return out


def figure(panels, legend, title, desc, width=720, height=260, cols=None):
    """An SVG document: a legend (names, in series order) above the panels,
    `cols` to a row."""
    cols = cols or len(panels)
    rows = math.ceil(len(panels) / cols)
    pw = (width - GAP * (cols - 1)) / cols
    total = LEGEND_H + rows * height + (rows - 1) * GAP
    light = "\n".join(f".s{i} {{ stroke: {c[0]}; }} .f{i} {{ fill: {c[0]}; }}" for i, c in enumerate(SERIES))
    dark = "\n".join(f"  .s{i} {{ stroke: {c[1]}; }} .f{i} {{ fill: {c[1]}; }}" for i, c in enumerate(SERIES))
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {total:.0f}" width="{width}" '
           f'height="{total:.0f}" role="img" aria-labelledby="title desc">',
           f'<title id="title">{title}</title>', f'<desc id="desc">{desc}</desc>',
           f"<style>{_STYLE.format(light=light, dark=dark)}</style>",
           f'<rect class="bg" x="0" y="0" width="{width}" height="{total:.0f}" rx="6"/>']
    x = LEFT
    for i, name in enumerate(legend):
        out.append(f'<rect class="f{i}" x="{x}" y="10" width="14" height="4" rx="2"/>')
        out.append(f'<text class="ink2" x="{x + 20}" y="16" font-size="12">{name}</text>')
        x += 20 + 6.6 * len(name) + 22
    for k, p in enumerate(panels):
        r, c = divmod(k, cols)
        out += _panel(p, c * (pw + GAP), LEGEND_H + r * (height + GAP), pw, height, k)
    out.append("</svg>")
    return "\n".join(out) + "\n"
