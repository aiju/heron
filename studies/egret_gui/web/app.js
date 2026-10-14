// The Heron in the browser: heron.wasm is the draft 1 simulator
// (web/src/lib.rs); the snapshots are the machine with the desktop up
// (booted-D.txt) or about to boot (cold-D.txt), D the screen's depth.
// This runs the machine by the clock, shows its screen, and hands it
// the keyboard and mouse as events (studies/v1_isa/isa/src/display.rs).
"use strict";

(() => {
  const CLOCK_HZ = 3_000_000;
  const TICK_HZ = 60;
  const SLICE_MS = 12;          // host time per frame at most
  const STEPS = 40_000;         // instructions per call into the module
  const KEYS = {
    Backspace: 8, Tab: 9, Enter: 13, Escape: 27, Delete: 127,
    ArrowLeft: 0x100, ArrowRight: 0x101, ArrowUp: 0x102, ArrowDown: 0x103,
    Home: 0x104, End: 0x105, PageUp: 0x106, PageDown: 0x107,
  };
  const POINTERS = ["default", "text", "crosshair", "wait", "move", "pointer", "none"];
  const $ = (id) => document.getElementById(id);
  const canvas = $("screen");
  const ctx = canvas.getContext("2d");
  const consoleEl = $("console");

  let wasm = null;
  let speed = 1;                // 0: flat out
  let depth = 3;
  let running = false;
  let budget = 0;
  let last = 0;
  let outPos = 0;
  let busyMs = 0;
  let buttons = 0;
  let stats = { t: 0, cycles: 0, idle: 0 };
  let uptime = 0;               // seconds the machine has been running
  const snapshots = {};

  function status(text, error = false) {
    $("status").textContent = text;
    $("status").classList.toggle("error", error);
  }

  function text(ptr, len) {
    return new TextDecoder("latin1").decode(new Uint8Array(wasm.memory.buffer, ptr, len));
  }

  async function fetchBytes(name) {
    const r = await fetch(name);
    if (!r.ok) throw new Error(`couldn't load ${name} (${r.status})`);
    return new Uint8Array(await r.arrayBuffer());
  }

  // a snapshot is zlib-compressed and then base64 text
  async function snapshot(kind, d) {
    const name = `${kind}-${d}.txt`;
    if (!snapshots[name]) {
      const r = await fetch(name);
      if (!r.ok) throw new Error(`couldn't load ${name} (${r.status})`);
      const bin = atob((await r.text()).trim());
      const z = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) z[i] = bin.charCodeAt(i);
      const s = new Blob([z]).stream().pipeThrough(new DecompressionStream("deflate"));
      snapshots[name] = new Uint8Array(await new Response(s).arrayBuffer());
    }
    return snapshots[name];
  }

  async function start(kind) {
    running = false;
    status(kind === "cold" ? "Cold boot: the machine compiles the prelude and the desktop first…" : "Starting…");
    const snap = await snapshot(kind, depth);
    const p = wasm.input_buffer(snap.length);
    new Uint8Array(wasm.memory.buffer, p, snap.length).set(snap);
    if (!wasm.load()) {
      status(text(wasm.error_ptr(), wasm.error_len()), true);
      return;
    }
    consoleEl.textContent = "";
    outPos = 0;
    budget = 0;
    uptime = 0;
    setTimer();
    stats = { t: performance.now(), cycles: wasm.cycles(), idle: wasm.idle_cycles() };
    setTime();
    running = true;
    status(kind === "cold" ? "Booting…" : "Running.");
    canvas.focus({ preventScroll: true });
  }

  // A faster Heron programs its timer for the same 60 ticks a second, and
  // the desktop works in ticks: so the switch makes the machine quicker,
  // not time faster. (Flat out, it's programmed as for 48 MHz; waiting
  // for the timer costs the host nothing, so time does run faster then.)
  function setTimer() {
    const hz = CLOCK_HZ * (speed === 0 ? 16 : speed);
    wasm.set_timer_period(Math.round(hz / TICK_HZ));
  }

  function setTime() {
    const d = new Date();
    wasm.set_time_of_day(d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds());
  }

  // ---- running

  function frame(now) {
    const dt = Math.min(now - last, 100);
    last = now;
    if (wasm && running) {
      const t0 = performance.now();
      let st = 0;
      if (speed === 0) {
        while (performance.now() - t0 < SLICE_MS && st === 0) st = wasm.run(1e9, STEPS);
      } else {
        budget += dt / 1000 * CLOCK_HZ * speed;
        while (budget > 0 && performance.now() - t0 < SLICE_MS && st === 0) {
          const c = wasm.cycles();
          st = wasm.run(budget, STEPS);
          budget -= wasm.cycles() - c;
        }
        // behind (the host is too slow for this speed): don't catch up later
        budget = Math.min(budget, CLOCK_HZ * speed / 30);
      }
      if (st === 1) {
        running = false;
        status("The machine halted. The console says why.", true);
      } else if (st === 2) {
        running = false;
        status("The simulation stopped: " + text(wasm.error_ptr(), wasm.error_len()), true);
      }
      uptime += dt / 1000;
      busyMs = wasm.idled() ? 0 : busyMs + dt;
      const ptr = busyMs > 400 ? "wait" : POINTERS[wasm.pointer()] || "default";
      if (canvas.style.cursor !== ptr) canvas.style.cursor = ptr;
    }
    if (wasm) {
      draw();
      output();
      readouts(now);
    }
    requestAnimationFrame(frame);
  }

  function draw() {
    const p = wasm.screen();
    if (!p) return;
    const w = wasm.width(), h = wasm.height();
    const px = new Uint8ClampedArray(wasm.memory.buffer, p, w * h * 4);
    shownCtx.putImageData(new ImageData(px, w, h), 0, 0);
    blit();
  }

  function output() {
    const n = wasm.output_len();
    if (n <= outPos) return;
    const s = text(wasm.output_ptr() + outPos, n - outPos);
    outPos = n;
    const atEnd = consoleEl.scrollTop + consoleEl.clientHeight >= consoleEl.scrollHeight - 4;
    consoleEl.textContent += s;
    if (consoleEl.textContent.length > 20000) consoleEl.textContent = consoleEl.textContent.slice(-16000);
    if (atEnd) consoleEl.scrollTop = consoleEl.scrollHeight;
    if (s.includes("ready\n")) status("Running. Click the desktop for the menu.");
  }

  function readouts(now) {
    if (now - stats.t < 500) return;
    const c = wasm.cycles(), idle = wasm.idle_cycles();
    const dc = c - stats.cycles, di = idle - stats.idle, secs = (now - stats.t) / 1000;
    $("mhz").textContent = running ? (dc / secs / 1e6).toFixed(1) + " MHz" : "stopped";
    $("busy").textContent = dc > 0 ? Math.round(100 * (1 - di / dc)) + "%" : "–";
    const t = uptime;
    $("mtime").textContent = `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;
    $("led-run").classList.toggle("on", running && dc > di);
    stats = { t: now, cycles: c, idle };
    setTime();
    setTimer();                 // (booting, the machine sets it for 3 MHz)
  }

  // ---- the screen's size: as big as fits (the width, and the window's
  // height less the panel). Scaled by a fraction with nearest-neighbour,
  // some machine pixels would come out two device pixels wide and some
  // three, and the 12-pixel fonts would look ragged. So the screen is
  // drawn into the canvas at a whole number of pixels to a machine pixel
  // (nearest-neighbour, all the same size), and the browser scales that
  // down smoothly to what fits: only the pixels' edges soften. At a whole
  // number of device pixels it's exact.

  const shown = document.createElement("canvas");   // the machine's screen, 1:1
  shown.width = 640;
  shown.height = 480;
  const shownCtx = shown.getContext("2d");

  function fit() {
    const dpr = window.devicePixelRatio || 1;
    const box = canvas.parentElement;
    const cs = getComputedStyle(box);
    const w = box.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    const h = Math.max(240, window.innerHeight - 230);
    let s = Math.min(w * dpr / 640, h * dpr / 480);   // device pixels to a machine pixel
    if (Math.abs(s - Math.round(s)) < 0.02) s = Math.round(s);
    const k = Math.max(1, Math.min(4, Math.ceil(s)));
    if (canvas.width !== 640 * k) {
      canvas.width = 640 * k;
      canvas.height = 480 * k;
    }
    canvas.style.width = `${640 * s / dpr}px`;
    canvas.style.imageRendering = s === k ? "pixelated" : "auto";
    blit();
  }

  function blit() {
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(shown, 0, 0, canvas.width, canvas.height);
  }

  fit();
  window.addEventListener("resize", fit);

  // ---- input

  function at(e) {
    const r = canvas.getBoundingClientRect();
    const x = Math.max(0, Math.min(639, Math.floor((e.clientX - r.left) * 640 / r.width)));
    const y = Math.max(0, Math.min(479, Math.floor((e.clientY - r.top) * 480 / r.height)));
    return [x, y];
  }

  function mods(e) {
    return (e.shiftKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.altKey ? 4 : 0) | (e.metaKey ? 8 : 0);
  }

  const BUTTON = [0, 2, 1];     // the browser's left, middle, right to the machine's

  function event(kind, value) {
    if (wasm && running) wasm.push_event(((kind << 28) | value) >>> 0);
  }

  canvas.addEventListener("pointermove", (e) => {
    if (!wasm) return;
    const [x, y] = at(e);
    wasm.set_mouse(x, y, buttons | mods(e) << 8);
  });
  canvas.addEventListener("pointerdown", (e) => {
    if (!wasm) return;
    canvas.focus({ preventScroll: true });
    canvas.setPointerCapture(e.pointerId);
    const [x, y] = at(e), b = BUTTON[e.button] ?? 0;
    buttons |= 1 << b;
    wasm.set_mouse(x, y, buttons | mods(e) << 8);
    event(3, (b << 24) | (y << 12) | x);
    e.preventDefault();
  });
  canvas.addEventListener("pointerup", (e) => {
    if (!wasm) return;
    const [x, y] = at(e), b = BUTTON[e.button] ?? 0;
    buttons &= ~(1 << b);
    wasm.set_mouse(x, y, buttons | mods(e) << 8);
    event(4, (b << 24) | (y << 12) | x);
  });
  // (the browser's own focusing on mousedown would scroll the page)
  canvas.addEventListener("mousedown", (e) => e.preventDefault());
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  canvas.addEventListener("wheel", (e) => {
    event(5, (e.deltaY > 0 ? 1 : -1) & 0xFFFF);
    e.preventDefault();
  }, { passive: false });

  function key(kind, e) {
    let code = KEYS[e.key];
    if (code === undefined && e.key.length === 1 && e.key.charCodeAt(0) < 128) code = e.key.charCodeAt(0);
    if (code === undefined) return;
    event(kind, (mods(e) << 16) | code);
    e.preventDefault();
  }
  canvas.addEventListener("keydown", (e) => key(1, e));
  canvas.addEventListener("keyup", (e) => key(2, e));

  // ---- the panel

  function press(group, button) {
    for (const b of group.querySelectorAll("button")) b.setAttribute("aria-pressed", String(b === button));
  }
  $("speeds").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    speed = Number(b.dataset.speed);
    budget = 0;
    if (wasm) setTimer();
    press($("speeds"), b);
    canvas.focus({ preventScroll: true });
  });
  $("depths").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b || Number(b.dataset.depth) === depth) return;
    depth = Number(b.dataset.depth);
    press($("depths"), b);
    start("booted").catch(fail);
  });
  $("restart").addEventListener("click", () => start("booted").catch(fail));
  $("coldboot").addEventListener("click", () => start("cold").catch(fail));

  function fail(err) {
    running = false;
    status(String(err && err.message || err), true);
  }

  // ---- start

  (async () => {
    try {
      const bytes = await fetchBytes("heron.wasm");
      const { instance } = await WebAssembly.instantiate(bytes, {});
      wasm = instance.exports;
      await start("booted");
    } catch (err) {
      fail(err);
    }
  })();
  requestAnimationFrame((t) => { last = t; frame(t); });
})();
