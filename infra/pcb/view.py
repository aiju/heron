"""A board as a web page to look at: every copper layer, the pads, vias,
parts and keep-outs, drawn on a canvas you can pan and zoom, with each
layer switched on and off and a net or part highlighted by clicking it or
finding it by name.

page(boards) returns the page's HTML, the boards embedded as compact JSON
(coordinates in units of 10 um), gzipped and in base64, so the file
stands alone: open it in a browser (one that has DecompressionStream:
any from 2023 on). With standalone=False it leaves out the doctype, for
hosts that wrap a page in their own.
"""

import base64
import gzip
import json

UNIT = 0.01               # mm per unit in the page's data

SHAPES = {"rect": 0, "roundrect": 0, "trapezoid": 0, "custom": 0, "circle": 1, "oval": 2}


def _u(v):
    return int(round(v / UNIT))


def data(board, name, title=""):
    """One board as the page's JSON object."""
    nets = sorted({n for n in board.nets()} | {t[6] for t in board.tracks} | {v[4] for v in board.vias})
    net_ix = {n: i for i, n in enumerate(nets)}
    layers = list(board.copper)
    lay_ix = {l: i for i, l in enumerate(layers)}
    tracks = []
    for (layer, x1, y1, x2, y2, w, net) in board.tracks:
        if layer in lay_ix:
            tracks += [lay_ix[layer], _u(x1), _u(y1), _u(x2), _u(y2), max(1, _u(w)), net_ix.get(net, -1)]
    vias = []
    for (x, y, dia, drill, net) in board.vias:
        vias += [_u(x), _u(y), _u(dia), _u(drill), net_ix.get(net, -1)]
    parts, pads = [], []
    for i, p in enumerate(sorted(board.parts.values(), key=lambda p: p.ref)):
        x0, y0, x1, y1 = p.courtyard()
        parts.append([p.ref, p.value or "", p.fp.name.split(":")[-1], p.kind,
                      0 if p.side == "F" else 1, _u(x0), _u(y0), _u(x1), _u(y1)])
        for d in p.pads():
            if d.layers == "*":
                side = 3 if d.kind == "np_thru_hole" else 2
            elif not d.layers:
                continue
            else:
                side = 0 if d.layers[0] == "F.Cu" else 1
            drill = d.drill if isinstance(d.drill, (int, float)) else (max(d.drill) if d.drill else 0)
            pads += [i, SHAPES.get(d.shape, 0), _u(d.x), _u(d.y), _u(d.w), _u(d.h),
                     int(round(d.angle)) % 360, side, net_ix.get(d.net, -1) if d.net else -1,
                     _u(drill or 0), d.number or ""]
    keepouts = [[_u(k["x0"]), _u(k["y0"]), _u(k["x1"]), _u(k["y1"]), k["name"]] for k in board.keepouts]
    return {"name": name, "title": title, "w": _u(board.width), "h": _u(board.height),
            "layers": layers, "planes": dict(board.planes), "nets": nets, "t": tracks, "v": vias,
            "parts": parts, "p": pads, "k": keepouts}


def page(boards, title="Heron Board Viewer", standalone=True):
    """The page for [(name, title, board)], the first shown first."""
    blobs = []
    for i, (name, btitle, board) in enumerate(boards):
        raw = json.dumps(data(board, name, btitle), separators=(",", ":")).encode()
        text = base64.b64encode(gzip.compress(raw, 9)).decode()
        blobs.append(f'<script type="application/octet-stream" class="board-data" '
                     f'data-name="{name}">{text}</script>')
    html = TEMPLATE.replace("__TITLE__", title).replace("__BOARDS__", "\n".join(blobs))
    if standalone:
        html = "<!doctype html>\n<meta charset=\"utf-8\">\n" \
               "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n" \
               + html
    return html


def write(path, boards, **kw):
    with open(path, "w") as f:
        f.write(page(boards, **kw))
    return path


TEMPLATE = r"""<title>__TITLE__</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@400;500;600&display=swap">
<style>
/* Layout: a one-screen instrument. A toolbar of controls over the board,
   which fills the rest; readouts float in the board's corners. */
:root {
  --bg: #f3f5f2; --panel: #ffffffe6; --ink: #18211c; --muted: #5d6b63; --line: #c9d2cb;
  --accent: #0b7a5c; --focus: #0b7a5c;
  --board: #e4ebe4; --edge: #8a9a90; --court: #9aa89f; --ref: #4d5c53; --keep: #c46a2a;
  --f-cu: #c2412f; --b-cu: #2f62b8; --in1: #2f8a4a; --in2: #8a46b8; --in3: #0f8a8a; --in4: #b07d16;
  --pad-tht: #a8841c; --via: #6b736e; --drill: #f3f5f2; --hi: #e6a100;
  --sans: "IBM Plex Sans Condensed", "Arial Narrow", "Helvetica Neue", Arial, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #0c110e; --panel: #141c17e6; --ink: #e3ebe5; --muted: #93a39a; --line: #2a362f;
  --accent: #3fd1a0; --focus: #3fd1a0;
  --board: #101814; --edge: #50615a; --court: #46564d; --ref: #8fa197; --keep: #e08a4a;
  --f-cu: #ef5d4a; --b-cu: #5b8ef0; --in1: #4cc274; --in2: #b57ae6; --in3: #3cc8c8; --in4: #e0b040;
  --pad-tht: #d6b04a; --via: #a9b3ad; --drill: #0c110e; --hi: #ffd34d; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #0c110e; --panel: #141c17e6; --ink: #e3ebe5; --muted: #93a39a; --line: #2a362f;
  --accent: #3fd1a0; --focus: #3fd1a0;
  --board: #101814; --edge: #50615a; --court: #46564d; --ref: #8fa197; --keep: #e08a4a;
  --f-cu: #ef5d4a; --b-cu: #5b8ef0; --in1: #4cc274; --in2: #b57ae6; --in3: #3cc8c8; --in4: #e0b040;
  --pad-tht: #d6b04a; --via: #a9b3ad; --drill: #0c110e; --hi: #ffd34d; color-scheme: dark }
html, body { height: 100%; }
body { background: var(--bg); color: var(--ink); font: 14px/1.35 var(--sans); display: flex; flex-direction: column; overflow: hidden; }
.bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; padding-block: 10px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  border-bottom: 1px solid var(--line); }
.name { font-weight: 600; font-size: 15px; letter-spacing: 0.02em; white-space: nowrap; }
.name small { font-weight: 400; color: var(--muted); font-size: 13px; margin-left: 6px; }
select, input, button { font: inherit; color: var(--ink); background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 4px 8px; min-height: 30px; }
select:focus-visible, input:focus-visible, button:focus-visible { outline: 2px solid var(--focus); outline-offset: 1px; }
button { cursor: pointer; }
button:hover { border-color: var(--muted); }
.layers { display: flex; gap: 6px; overflow-x: auto; max-width: 100%; padding-bottom: 2px; }
.chip { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; font-size: 13px; }
.chip i { width: 10px; height: 10px; border-radius: 2px; background: var(--sw); display: inline-block; }
.chip[aria-pressed="false"] { color: var(--muted); }
.chip[aria-pressed="false"] i { background: transparent; box-shadow: inset 0 0 0 1.5px var(--sw); }
.find { display: flex; gap: 6px; align-items: center; min-width: 0; }
.find input { width: 15em; max-width: 52vw; }
.stage { position: relative; flex: 1; min-height: 0; }
canvas { position: absolute; inset: 0; width: 100%; height: 100%; touch-action: none; cursor: grab; display: block; }
canvas.dragging { cursor: grabbing; }
.readout, .info, .scale { position: absolute; background: var(--panel); border: 1px solid var(--line); border-radius: 4px;
  font: 12px/1.4 var(--mono); padding: 5px 8px; pointer-events: none; font-variant-numeric: tabular-nums; }
.readout { top: 10px; left: max(10px, env(safe-area-inset-left, 0px)); }
.scale { bottom: max(10px, env(safe-area-inset-bottom, 0px)); left: max(10px, env(safe-area-inset-left, 0px)); }
.scale b { display: block; height: 3px; background: var(--ink); margin-top: 3px; }
.info { right: max(10px, env(safe-area-inset-right, 0px)); bottom: max(10px, env(safe-area-inset-bottom, 0px)); max-width: min(360px, 70vw); pointer-events: auto; }
.info h2 { font: 600 13px/1.3 var(--sans); margin: 0 0 2px; letter-spacing: 0.02em; }
.info p { margin: 0; color: var(--muted); }
.info button { margin-top: 6px; min-height: 26px; padding: 2px 8px; font-size: 12px; }
.hint { color: var(--muted); }
@media (max-width: 600px) { .name small { display: none; } .find input { width: 11em; } }
</style>

<header class="bar">
  <div class="name">Heron boards<small id="summary"></small></div>
  <select id="board" aria-label="Board"></select>
  <div class="layers" id="layers" role="group" aria-label="Layers"></div>
  <div class="find">
    <input id="find" list="names" placeholder="Find a net or part" aria-label="Find a net or part" autocomplete="off">
    <datalist id="names"></datalist>
    <button id="fit" type="button">Fit</button>
  </div>
</header>
<main class="stage" id="stage">
  <canvas id="cv"></canvas>
  <div class="readout" id="readout">x — y — mm</div>
  <div class="scale" id="scale"><span id="scale-label">10 mm</span><b id="scale-bar"></b></div>
  <div class="info" id="info"><h2>Click a pad or a track</h2><p>Drag to pan, scroll or pinch to zoom. Click a net or a part to highlight it.</p></div>
</main>

__BOARDS__

<script>
(() => {
  const UNIT = 0.01;  // mm per data unit
  const blobs = [...document.querySelectorAll("script.board-data")];
  const boards = blobs.map(s => ({ name: s.dataset.name }));
  async function load(i) {
    if (boards[i].t) return boards[i];
    const bytes = Uint8Array.from(atob(blobs[i].textContent.trim()), c => c.charCodeAt(0));
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    return (boards[i] = await new Response(stream).json());
  }
  const cv = document.getElementById("cv"), ctx = cv.getContext("2d");
  const stage = document.getElementById("stage");
  const sel = document.getElementById("board"), layersEl = document.getElementById("layers");
  const info = document.getElementById("info"), readout = document.getElementById("readout");
  const find = document.getElementById("find"), names = document.getElementById("names");
  let B = null, view = { s: 1, x: 0, y: 0 }, vis = {}, picked = null, dirty = true, colors = {};

  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  function readColors() {
    for (const k of ["board", "edge", "court", "ref", "keep", "f-cu", "b-cu", "in1", "in2", "in3", "in4",
                     "pad-tht", "via", "drill", "hi", "ink", "mono"]) colors[k] = css("--" + k);
    colors.mono = css("--mono");
  }
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { readColors(); dirty = true; });
  new MutationObserver(() => { readColors(); dirty = true; }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  // ---- one board's drawing data --------------------------------------------------
  function prepare(b) {
    if (b.ready) return b;
    const L = b.layers.length;
    b.layerColor = b.layers.map((l, i) => l === "F.Cu" ? "f-cu" : l === "B.Cu" ? "b-cu" : ["in1", "in2", "in3", "in4"][(i - 1) % 4]);
    // tracks: one path per layer and width
    b.tr = b.layers.map(() => new Map());
    const t = b.t, n = t.length / 7;
    b.netItems = new Map();
    const add = (net, kind, i) => { if (net < 0) return; let m = b.netItems.get(net); if (!m) b.netItems.set(net, m = { t: [], v: [], p: [] }); m[kind].push(i); };
    for (let i = 0; i < n; i++) {
      const o = i * 7, l = t[o], w = t[o + 5];
      let p = b.tr[l].get(w); if (!p) b.tr[l].set(w, p = new Path2D());
      p.moveTo(t[o + 1], t[o + 2]); p.lineTo(t[o + 3], t[o + 4]);
      add(t[o + 6], "t", i);
    }
    // pads: copper by side (0 top, 1 bottom, 2 through), holes
    b.padPath = [new Path2D(), new Path2D(), new Path2D()];
    b.holes = new Path2D();
    const P = b.p, np = P.length / 11;
    b.padBox = new Int32Array(np * 4);
    for (let i = 0; i < np; i++) {
      const o = i * 11, shape = P[o + 1], x = P[o + 2], y = P[o + 3], w = P[o + 4], h = P[o + 5], a = P[o + 6] * Math.PI / 180, side = P[o + 7], drill = P[o + 9];
      const c = Math.abs(Math.cos(a)), s = Math.abs(Math.sin(a));
      const hx = (w * c + h * s) / 2, hy = (w * s + h * c) / 2;
      b.padBox.set([x - hx, y - hy, x + hx, y + hy], i * 4);
      if (side < 3) padShape(b.padPath[side], shape, x, y, w, h, a);
      if (drill > 0) { b.holes.moveTo(x + drill / 2, y); b.holes.arc(x, y, drill / 2, 0, 2 * Math.PI); }
      add(P[o + 8], "p", i);
    }
    b.vias = new Path2D(); b.viaHoles = new Path2D();
    const V = b.v, nv = V.length / 5;
    for (let i = 0; i < nv; i++) {
      const o = i * 5, x = V[o], y = V[o + 1];
      b.vias.moveTo(x + V[o + 2] / 2, y); b.vias.arc(x, y, V[o + 2] / 2, 0, 2 * Math.PI);
      b.viaHoles.moveTo(x + V[o + 3] / 2, y); b.viaHoles.arc(x, y, V[o + 3] / 2, 0, 2 * Math.PI);
      add(V[o + 4], "v", i);
    }
    // a grid of cells for picking
    b.cell = 500; b.gw = Math.ceil(b.w / b.cell) + 1; b.gh = Math.ceil(b.h / b.cell) + 1;
    b.grid = new Map();
    const put = (x0, y0, x1, y1, item) => {
      for (let cx = Math.max(0, Math.floor(x0 / b.cell)); cx <= Math.min(b.gw - 1, Math.floor(x1 / b.cell)); cx++)
        for (let cy = Math.max(0, Math.floor(y0 / b.cell)); cy <= Math.min(b.gh - 1, Math.floor(y1 / b.cell)); cy++) {
          const k = cx * 100000 + cy; let a = b.grid.get(k); if (!a) b.grid.set(k, a = []); a.push(item);
        }
    };
    for (let i = 0; i < n; i++) { const o = i * 7, r = t[o + 5] / 2; put(Math.min(t[o + 1], t[o + 3]) - r, Math.min(t[o + 2], t[o + 4]) - r, Math.max(t[o + 1], t[o + 3]) + r, Math.max(t[o + 2], t[o + 4]) + r, ["t", i]); }
    for (let i = 0; i < np; i++) put(b.padBox[i * 4], b.padBox[i * 4 + 1], b.padBox[i * 4 + 2], b.padBox[i * 4 + 3], ["p", i]);
    for (let i = 0; i < nv; i++) { const o = i * 5, r = V[o + 2] / 2; put(V[o] - r, V[o + 1] - r, V[o] + r, V[o + 1] + r, ["v", i]); }
    b.partIx = new Map(b.parts.map((p, i) => [p[0], i]));
    b.netIx = new Map(b.nets.map((n, i) => [n, i]));
    b.ready = true;
    return b;
  }

  function padShape(path, shape, x, y, w, h, a) {
    const c = Math.cos(a), s = Math.sin(a);
    // KiCad turns counter-clockwise with y down: a point (u, v) goes to (u c + v s, -u s + v c)
    const pt = (u, v) => [x + u * c + v * s, y - u * s + v * c];
    if (shape === 1) { path.moveTo(x + w / 2, y); path.arc(x, y, w / 2, 0, 2 * Math.PI); return; }
    if (shape === 2) {
      const r = Math.min(w, h) / 2, L = Math.max(w, h) / 2 - r, horiz = w >= h;
      const [ax, ay] = horiz ? pt(-L, 0) : pt(0, -L), [bx, by] = horiz ? pt(L, 0) : pt(0, L);
      const ang = Math.atan2(by - ay, bx - ax);
      path.moveTo(ax + r * Math.cos(ang + Math.PI / 2), ay + r * Math.sin(ang + Math.PI / 2));
      path.arc(ax, ay, r, ang + Math.PI / 2, ang + 3 * Math.PI / 2);
      path.arc(bx, by, r, ang - Math.PI / 2, ang + Math.PI / 2);
      path.closePath(); return;
    }
    const q = [pt(-w / 2, -h / 2), pt(w / 2, -h / 2), pt(w / 2, h / 2), pt(-w / 2, h / 2)];
    path.moveTo(...q[0]); path.lineTo(...q[1]); path.lineTo(...q[2]); path.lineTo(...q[3]); path.closePath();
  }

  // ---- layers ------------------------------------------------------------------------
  function layerList(b) {
    const out = [];
    b.layers.forEach((l, i) => out.push({ id: "cu" + i, label: b.planes[l] ? `${l.replace(".Cu", "")} · ${b.planes[l]}` : l.replace(".Cu", ""), color: b.layerColor[i], on: !b.planes[l] }));
    out.push({ id: "parts", label: "Parts", color: "court", on: true });
    out.push({ id: "refs", label: "Names", color: "ref", on: true });
    if (b.k.length) out.push({ id: "keep", label: "Keep-outs", color: "keep", on: true });
    return out;
  }
  function buildLayerChips(b) {
    layersEl.textContent = "";
    for (const L of layerList(b)) {
      if (!(L.id in vis)) vis[L.id] = L.on;
      const btn = document.createElement("button");
      btn.type = "button"; btn.className = "chip"; btn.id = "layer-" + L.id;
      btn.style.setProperty("--sw", `var(--${L.color})`);
      btn.setAttribute("aria-pressed", String(vis[L.id]));
      btn.innerHTML = `<i></i>${L.label}`;
      btn.addEventListener("click", ev => {
        if (ev.altKey || ev.metaKey) { for (const k of Object.keys(vis)) if (k.startsWith("cu")) vis[k] = false; vis[L.id] = true; }
        else vis[L.id] = !vis[L.id];
        for (const c of layersEl.children) c.setAttribute("aria-pressed", String(vis[c.id.slice(6)]));
        dirty = true;
      });
      layersEl.appendChild(btn);
    }
  }

  // ---- view --------------------------------------------------------------------------
  function size() {
    const r = stage.getBoundingClientRect(), d = devicePixelRatio || 1;
    cv.width = Math.max(1, Math.round(r.width * d)); cv.height = Math.max(1, Math.round(r.height * d));
    dirty = true;
  }
  function fitTo(x0, y0, x1, y1, pad = 0.04) {
    const r = stage.getBoundingClientRect(), w = Math.max(1, x1 - x0), h = Math.max(1, y1 - y0);
    view.s = Math.min(r.width / (w * (1 + 2 * pad)), r.height / (h * (1 + 2 * pad)));
    view.x = r.width / 2 - (x0 + w / 2) * view.s; view.y = r.height / 2 - (y0 + h / 2) * view.s;
    dirty = true;
  }
  const fit = () => { if (B) fitTo(0, 0, B.w, B.h); };
  const toWorld = (px, py) => [(px - view.x) / view.s, (py - view.y) / view.s];

  function draw() {
    dirty = false;
    const d = devicePixelRatio || 1, b = B;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = css("--bg"); ctx.fillRect(0, 0, cv.width, cv.height);
    ctx.setTransform(view.s * d, 0, 0, view.s * d, view.x * d, view.y * d);
    const px = 1 / view.s;   // one screen pixel in data units
    ctx.fillStyle = colors.board; ctx.fillRect(0, 0, b.w, b.h);
    const dim = picked ? 0.28 : 1;
    // planes: a tint over the board
    b.layers.forEach((l, i) => {
      if (b.planes[l] && vis["cu" + i]) { ctx.globalAlpha = 0.16 * dim; ctx.fillStyle = colors[b.layerColor[i]]; ctx.fillRect(0, 0, b.w, b.h); }
    });
    // copper, bottom up: the bottom, the inner layers, the top
    const order = [b.layers.length - 1, ...b.layers.map((_, i) => i).slice(1, -1).reverse(), 0];
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    for (const i of order) {
      if (!vis["cu" + i] || b.planes[b.layers[i]]) continue;
      const col = colors[b.layerColor[i]];
      ctx.globalAlpha = 0.85 * dim; ctx.strokeStyle = col;
      for (const [w, p] of b.tr[i]) { ctx.lineWidth = Math.max(w, px); ctx.stroke(p); }
      if (i === 0 || i === b.layers.length - 1) { ctx.fillStyle = col; ctx.globalAlpha = 0.95 * dim; ctx.fill(b.padPath[i === 0 ? 0 : 1]); }
    }
    const anyCu = b.layers.some((_, i) => vis["cu" + i]);
    if (anyCu) {
      ctx.globalAlpha = dim; ctx.fillStyle = colors["pad-tht"]; ctx.fill(b.padPath[2]);
      ctx.fillStyle = colors.via; ctx.fill(b.vias);
      ctx.fillStyle = colors.drill; ctx.globalAlpha = 1; ctx.fill(b.viaHoles); ctx.fill(b.holes);
    }
    ctx.globalAlpha = 1;
    if (vis.keep && b.k.length) {
      ctx.fillStyle = colors.keep; ctx.strokeStyle = colors.keep;
      for (const k of b.k) { ctx.globalAlpha = 0.12; ctx.fillRect(k[0], k[1], k[2] - k[0], k[3] - k[1]); ctx.globalAlpha = 0.7; ctx.lineWidth = px; ctx.strokeRect(k[0], k[1], k[2] - k[0], k[3] - k[1]); }
      ctx.globalAlpha = 1;
    }
    if (vis.parts) {
      ctx.strokeStyle = colors.court; ctx.lineWidth = px; ctx.globalAlpha = 0.9;
      for (const p of b.parts) if (p[3] !== "decap" || view.s > 0.05) ctx.strokeRect(p[5], p[6], p[7] - p[5], p[8] - p[6]);
      ctx.globalAlpha = 1;
    }
    if (vis.refs && 120 * view.s >= 7) {
      // names 1.2 mm high, but never more than 13 px on screen; the bottom
      // side's (the capacitors under the chips) smaller, below the chip's
      ctx.fillStyle = colors.ref; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      for (const bottom of [false, true]) {
        const fs = Math.min(120, 13 / view.s) * (bottom ? 0.7 : 1);
        if (bottom && fs * view.s < 8) continue;
        ctx.font = `${fs}px ${colors.mono}`;
        for (const p of b.parts) {
          if (!!p[4] !== bottom) continue;
          const w = p[7] - p[5], h = p[8] - p[6];
          if (ctx.measureText(p[0]).width > w * 1.6) continue;
          ctx.fillText(p[0], (p[5] + p[7]) / 2, (p[6] + p[8]) / 2 + (bottom ? fs * 0.9 : -fs * 0.1) * (h > 3 * fs ? 1 : 0));
        }
      }
    }
    // the outline
    ctx.strokeStyle = colors.edge; ctx.lineWidth = 2 * px; ctx.strokeRect(0, 0, b.w, b.h);
    if (picked) drawPicked(px);
    scaleBar();
  }

  function drawPicked(px) {
    const b = B; ctx.globalAlpha = 1; ctx.strokeStyle = colors.hi; ctx.fillStyle = colors.hi;
    if (picked.kind === "net") {
      const m = b.netItems.get(picked.i); if (!m) return;
      ctx.lineCap = "round";
      for (const i of m.t) { const o = i * 7; if (!vis["cu" + b.t[o]]) continue; ctx.lineWidth = Math.max(b.t[o + 5], 2 * px); ctx.beginPath(); ctx.moveTo(b.t[o + 1], b.t[o + 2]); ctx.lineTo(b.t[o + 3], b.t[o + 4]); ctx.stroke(); }
      for (const i of m.p) { const o = i * 11, p = new Path2D(); padShape(p, b.p[o + 1], b.p[o + 2], b.p[o + 3], b.p[o + 4], b.p[o + 5], b.p[o + 6] * Math.PI / 180); ctx.fill(p); }
      for (const i of m.v) { const o = i * 5; ctx.beginPath(); ctx.arc(b.v[o], b.v[o + 1], b.v[o + 2] / 2, 0, 2 * Math.PI); ctx.fill(); }
    } else {
      const p = b.parts[picked.i]; ctx.lineWidth = 2 * px; ctx.strokeRect(p[5], p[6], p[7] - p[5], p[8] - p[6]);
      for (let i = 0; i < b.p.length / 11; i++) if (b.p[i * 11] === picked.i) { const o = i * 11, q = new Path2D(); padShape(q, b.p[o + 1], b.p[o + 2], b.p[o + 3], b.p[o + 4], b.p[o + 5], b.p[o + 6] * Math.PI / 180); ctx.fill(q); }
    }
  }

  function scaleBar() {
    const target = 120 / view.s * UNIT;   // mm in about 120 px
    const steps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200];
    const mm = steps.find(s => s >= target / 2.2) || 200;
    document.getElementById("scale-label").textContent = `${mm} mm`;
    document.getElementById("scale-bar").style.width = `${mm / UNIT * view.s}px`;
  }

  // ---- picking -----------------------------------------------------------------------
  function pick(px, py) {
    const b = B, [x, y] = toWorld(px, py), tol = 4 / view.s;
    const seen = new Set(); let best = null;
    const cx = Math.floor(x / b.cell), cy = Math.floor(y / b.cell);
    const score = (d, rank, item) => { if (d <= tol && (!best || rank < best.rank || (rank === best.rank && d < best.d))) best = { d, rank, item }; };
    for (let i = cx - 1; i <= cx + 1; i++) for (let j = cy - 1; j <= cy + 1; j++) {
      for (const it of b.grid.get(i * 100000 + j) || []) {
        const key = it[0] + it[1]; if (seen.has(key)) continue; seen.add(key);
        if (it[0] === "t") {
          const o = it[1] * 7, l = b.t[o]; if (!vis["cu" + l]) continue;
          score(segDist(x, y, b.t[o + 1], b.t[o + 2], b.t[o + 3], b.t[o + 4]) - b.t[o + 5] / 2, l === 0 ? 1 : 3, it);
        } else if (it[0] === "p") {
          const o = it[1] * 11; const bx = b.padBox;
          const dx = Math.max(bx[it[1] * 4] - x, 0, x - bx[it[1] * 4 + 2]), dy = Math.max(bx[it[1] * 4 + 1] - y, 0, y - bx[it[1] * 4 + 3]);
          score(Math.hypot(dx, dy), 0, it);
        } else {
          const o = it[1] * 5; score(Math.hypot(x - b.v[o], y - b.v[o + 1]) - b.v[o + 2] / 2, 2, it);
        }
      }
    }
    if (best) {
      const it = best.item, net = it[0] === "t" ? b.t[it[1] * 7 + 6] : it[0] === "p" ? b.p[it[1] * 11 + 8] : b.v[it[1] * 5 + 4];
      if (net >= 0) return { kind: "net", i: net, pad: it[0] === "p" ? it[1] : null };
      if (it[0] === "p") return { kind: "part", i: b.p[it[1] * 11] };
    }
    for (let i = b.parts.length - 1; i >= 0; i--) { const p = b.parts[i]; if (x >= p[5] && x <= p[7] && y >= p[6] && y <= p[8] && p[3] !== "decap") return { kind: "part", i }; }
    return null;
  }
  function segDist(x, y, x1, y1, x2, y2) {
    const dx = x2 - x1, dy = y2 - y1, L = dx * dx + dy * dy;
    let t = L ? ((x - x1) * dx + (y - y1) * dy) / L : 0; t = Math.max(0, Math.min(1, t));
    return Math.hypot(x - x1 - t * dx, y - y1 - t * dy);
  }

  function describe() {
    const b = B;
    if (!picked) { info.innerHTML = `<h2>Click a pad or a track</h2><p>Drag to pan, scroll or pinch to zoom. Click a net or a part to highlight it; alt-click a layer to see it alone.</p>`; return; }
    if (picked.kind === "net") {
      const m = b.netItems.get(picked.i) || { t: [], v: [], p: [] };
      let len = 0; for (const i of m.t) { const o = i * 7; len += Math.hypot(b.t[o + 3] - b.t[o + 1], b.t[o + 4] - b.t[o + 2]); }
      const pins = m.p.map(i => `${b.parts[b.p[i * 11]][0]}.${b.p[i * 11 + 10]}`);
      const plane = Object.entries(b.planes).find(([, n]) => n === b.nets[picked.i]);
      info.innerHTML = `<h2>${esc(b.nets[picked.i])}</h2><p>${pins.length} pads · ${(len * UNIT / 1000).toFixed(3)} m of track · ${m.v.length} vias${plane ? ` · plane on ${plane[0]}` : ""}</p>` +
        (pins.length <= 24 ? `<p>${pins.map(esc).join(" ")}</p>` : "") + `<button type="button" id="clear">Clear</button>`;
    } else {
      const p = b.parts[picked.i];
      info.innerHTML = `<h2>${esc(p[0])}</h2><p>${esc(p[1] || p[3])} · ${esc(p[2])} · ${p[4] ? "bottom" : "top"}</p><p>at ${((p[5] + p[7]) / 2 * UNIT).toFixed(2)}, ${((p[6] + p[8]) / 2 * UNIT).toFixed(2)} mm</p><button type="button" id="clear">Clear</button>`;
    }
    document.getElementById("clear").addEventListener("click", () => { picked = null; describe(); dirty = true; });
  }
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ---- input -------------------------------------------------------------------------
  const pts = new Map(); let moved = false, pinch = null;
  cv.addEventListener("pointerdown", e => { cv.setPointerCapture(e.pointerId); pts.set(e.pointerId, [e.offsetX, e.offsetY]); moved = false; if (pts.size === 2) { const [a, c] = [...pts.values()]; pinch = { d: Math.hypot(a[0] - c[0], a[1] - c[1]), s: view.s }; } });
  cv.addEventListener("pointermove", e => {
    const [wx, wy] = toWorld(e.offsetX, e.offsetY);
    readout.textContent = `x ${(wx * UNIT).toFixed(2)}  y ${(wy * UNIT).toFixed(2)} mm`;
    if (!pts.has(e.pointerId)) return;
    const prev = pts.get(e.pointerId); pts.set(e.pointerId, [e.offsetX, e.offsetY]);
    if (pts.size === 2 && pinch) {
      const [a, c] = [...pts.values()], d = Math.hypot(a[0] - c[0], a[1] - c[1]), mx = (a[0] + c[0]) / 2, my = (a[1] + c[1]) / 2;
      zoomAt(mx, my, pinch.s * d / pinch.d / view.s); moved = true; return;
    }
    const dx = e.offsetX - prev[0], dy = e.offsetY - prev[1];
    if (Math.abs(dx) + Math.abs(dy) > 0) { if (Math.hypot(dx, dy) > 1) moved = true; view.x += dx; view.y += dy; cv.classList.add("dragging"); dirty = true; }
  });
  const up = e => {
    if (pts.has(e.pointerId) && !moved && pts.size === 1) { picked = pick(e.offsetX, e.offsetY); describe(); dirty = true; }
    pts.delete(e.pointerId); if (pts.size < 2) pinch = null; cv.classList.remove("dragging");
  };
  cv.addEventListener("pointerup", up); cv.addEventListener("pointercancel", up);
  cv.addEventListener("wheel", e => { e.preventDefault(); zoomAt(e.offsetX, e.offsetY, Math.exp(-e.deltaY * (e.deltaMode ? 0.05 : 0.0015))); }, { passive: false });
  cv.addEventListener("dblclick", e => zoomAt(e.offsetX, e.offsetY, 2));
  function zoomAt(px, py, f) {
    const s = Math.min(Math.max(view.s * f, 0.0005), 2);
    view.x = px - (px - view.x) * s / view.s; view.y = py - (py - view.y) * s / view.s; view.s = s; dirty = true;
  }
  document.getElementById("fit").addEventListener("click", fit);
  find.addEventListener("change", () => {
    const b = B, q = find.value.trim();
    if (b.netIx.has(q)) {
      picked = { kind: "net", i: b.netIx.get(q) }; const m = b.netItems.get(picked.i);
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      if (m) for (const i of m.p) { x0 = Math.min(x0, b.padBox[i * 4]); y0 = Math.min(y0, b.padBox[i * 4 + 1]); x1 = Math.max(x1, b.padBox[i * 4 + 2]); y1 = Math.max(y1, b.padBox[i * 4 + 3]); }
      if (x0 < x1) fitTo(x0, y0, x1, y1, 0.15);
    } else if (b.partIx.has(q)) {
      picked = { kind: "part", i: b.partIx.get(q) }; const p = b.parts[picked.i]; fitTo(p[5], p[6], p[7], p[8], 2);
    } else return;
    describe(); dirty = true;
  });
  addEventListener("keydown", e => { if (e.target === find) return; if (e.key === "Escape") { picked = null; describe(); dirty = true; } if (e.key === "f") fit(); });

  async function show(i) {
    info.innerHTML = "<h2>Loading the board</h2>";
    try { B = prepare(await load(i)); }
    catch (e) { info.innerHTML = "<h2>This browser can't open the board</h2><p>It needs DecompressionStream (any current browser has it).</p>"; return; }
    picked = null; vis = {};
    buildLayerChips(B);
    document.getElementById("summary").textContent = B.title;
    names.innerHTML = B.nets.map(n => `<option value="${esc(n)}"></option>`).join("") + B.parts.filter(p => p[3] !== "decap").map(p => `<option value="${esc(p[0])}"></option>`).join("");
    find.value = ""; describe(); size(); fit();
    try { history.replaceState(null, "", "#" + B.name); } catch (e) {}
  }
  boards.forEach((b, i) => { const o = document.createElement("option"); o.value = i; o.textContent = b.name; sel.appendChild(o); });
  sel.addEventListener("change", () => show(+sel.value));
  new ResizeObserver(() => { size(); }).observe(stage);
  readColors();
  const start = boards.findIndex(b => "#" + b.name === location.hash);
  sel.value = String(Math.max(0, start));
  show(Math.max(0, start));
  if (document.fonts) document.fonts.ready.then(() => { readColors(); dirty = true; });
  (function loop() { if (dirty && B) draw(); requestAnimationFrame(loop); })();
})();
</script>
"""
