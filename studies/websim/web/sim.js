/* The simulator's page (studies/websim): the engine as WebAssembly
   (websim.wasm, from engine/ and wasm/), the machines it can be
   (machines.json, written from machines.py, with the bytes they load in
   blobs/), and the page around them: the terminal (term.js), the screen,
   the keyboard and the mouse, and a few tools.

   A machine runs in slices, each frame of the browser: as many cycles as
   its clock (times the speed) makes in the time since the last, within a
   few milliseconds of work so the page stays quick. A machine that waits
   for the terminal costs nothing until something is typed. */
(function () {
  "use strict";

  const HERE = new URL(".", document.currentScript.src);
  const GITHUB = "https://github.com/aiju/heron/blob/main/";
  const $ = (id) => document.getElementById(id);
  const enc = new TextEncoder();
  const utf8 = new TextDecoder();
  const STEPS = 20000;          // instructions a call into the engine, at most
  const WORK_MS = 12;           // work a frame, at most
  const RUN = 0, WAITING = 1, IDLE = 2, HALTED = 3, FAILED = -1;

  const ui = {
    machine: $("sim-machine"), run: $("sim-run"), reset: $("sim-reset"), speed: $("sim-speed"),
    clock: $("sim-clock"), more: $("sim-more"), menu: $("sim-menu"), tabs: $("sim-tabs"),
    screen: $("sim-screen"), canvas: $("sim-canvas"), term: $("sim-term"), log: $("sim-log"),
    overlay: $("sim-overlay"), status: $("sim-status"), inspect: $("sim-inspect"),
    stats: $("sim-stats"), regs: $("sim-regs"), addr: $("sim-addr"), dump: $("sim-dump"),
    step: $("sim-step"), group: $("sim-group"), title: $("sim-title"), about: $("sim-about"),
    examples: $("sim-examples"), links: $("sim-links"), keys: $("sim-keys"),
  };
  const lamps = {};
  for (const el of document.querySelectorAll("#sim [data-lamp]")) lamps[el.dataset.lamp] = el;

  // ---------------------------------------------------------------- the engine

  let module = null;            // the compiled engine
  let E = null;                 // its exports, for the machine running

  async function engine() {
    if (!module) {
      const url = new URL("websim.wasm", HERE);
      try {
        module = await WebAssembly.compileStreaming(fetch(url));
      } catch (e) {
        const r = await fetch(url);
        if (!r.ok) throw new Error(`no ${url.pathname} (${r.status})`);
        module = await WebAssembly.compile(await r.arrayBuffer());
      }
    }
    // a fresh instance for each machine: its memory goes with it
    return (await WebAssembly.instantiate(module, {})).exports;
  }

  const mem = () => new Uint8Array(E.memory.buffer);
  function put(bytes) {
    const p = E.inbox(bytes.length);
    mem().set(bytes, p);
  }
  const putText = (s) => put(enc.encode(s));
  function take(n) {
    const p = E.outbox();
    return mem().slice(p, p + n);
  }
  const errorText = () => utf8.decode(take(E.error()));
  function latin1(bytes) {
    let s = "";
    for (let i = 0; i < bytes.length; i += 8192) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
    return s;
  }

  // ---------------------------------------------------------------- machines

  let catalog = null;           // machines.json
  let M = null;                 // the running machine's description
  const blobs = new Map();      // what machines load, by file, as fetched

  async function blob(load) {
    if (load.text !== undefined) return enc.encode(load.text);
    if (!blobs.has(load.blob)) {
      const p = (async () => {
        const r = await fetch(new URL(load.blob, HERE));
        if (!r.ok) throw new Error(`no ${load.blob} (${r.status})`);
        if (!load.blob.endsWith(".gz")) return new Uint8Array(await r.arrayBuffer());
        const s = r.body.pipeThrough(new DecompressionStream("gzip"));
        return new Uint8Array(await new Response(s).arrayBuffer());
      })();
      blobs.set(load.blob, p);
      p.catch(() => blobs.delete(load.blob));
    }
    return blobs.get(load.blob);
  }

  let state = null;             // the running machine: {status, running, ...}
  let term = null;
  let generation = 0;           // which boot is the latest

  async function boot(m) {
    const mine = ++generation;
    state = null;
    M = m;
    show(m);
    setOverlay(`Loading ${m.group}, ${m.variant}…`);
    let e, data;
    try {
      [e, data] = await Promise.all([engine(), Promise.all(m.loads.map(blob))]);
    } catch (err) {
      return setOverlay(`Couldn't load the machine: ${err.message}`, true);
    }
    if (mine !== generation) return;
    E = e;
    putText(m.board);
    E.setup();
    for (const [k, v] of Object.entries(m.params)) {
      putText(`${k}=${v === "now" ? Math.floor(Date.now() / 1000) : v}`);
      if (!E.param()) return setOverlay(errorText(), true);
    }
    for (let i = 0; i < m.loads.length; i++) {
      const t = enc.encode(m.loads[i].target), d = data[i];
      const b = new Uint8Array(t.length + 1 + d.length);
      b.set(t);
      b.set(d, t.length + 1);
      put(b);
      if (!E.load(m.loads[i].at)) return setOverlay(errorText(), true);
    }
    if (!E.start()) return setOverlay(`The machine didn't start: ${errorText()}`, true);
    state = {
      status: RUN, running: true, error: null, clock: E.clock_hz(), started: performance.now(),
      seen: { t: performance.now(), cycles: 0, instructions: 0, idle: 0 }, rate: 0, mips: 0, lagging: false,
    };
    ui.run.disabled = ui.reset.disabled = false;
    ui.log.textContent = "";
    if (m.screen) {
      const w = E.screen_width(), h = E.screen_height();
      ui.canvas.width = w;
      ui.canvas.height = h;
      ctx = ui.canvas.getContext("2d");
      image = ctx.createImageData(w, h);
      fitScreen();
    }
    setOverlay(null);
    if (term && !m.screen) term.focus();
    if (m.screen) ui.canvas.focus({ preventScroll: true });
    update();
  }

  function setOverlay(text, bad) {
    ui.overlay.hidden = !text;
    ui.overlay.textContent = text || "";
    ui.overlay.classList.toggle("bad", !!bad);
  }

  // the page around a machine: views, tabs, help
  function show(m) {
    document.title = `${m.group}, ${m.variant} · Simulator · Heron`;
    ui.group.textContent = m.group;
    ui.title.textContent = m.title;
    ui.about.innerHTML = m.about || "";
    ui.examples.hidden = !(m.examples && m.examples.length && m.terminal);
    for (const b of ui.examples.querySelectorAll("button")) b.remove();
    for (const [title, text] of m.examples || []) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "btn ghost";
      b.textContent = title;
      b.addEventListener("click", () => {
        select("term");
        term.type(text);
        resume();
        term.focus();
      });
      ui.examples.append(b);
    }
    ui.links.textContent = "";
    for (const [title, path] of m.links || []) {
      const a = document.createElement("a");
      a.href = link(path);
      a.textContent = title;
      ui.links.append(a);
    }
    ui.term.textContent = "";
    term = null;
    if (m.terminal) {
      term = new window.HeronTerminal(ui.term, Object.assign({}, m.terminal, {
        onInput: (text) => {
          if (!E || !state) return;
          put(enc.encode(text));
          E.send();
          resume();
        },
        onEnd: () => {
          if (!E || !state) return;
          E.close();
          resume();
        },
      }));
    }
    const views = [];
    if (m.screen) views.push(["screen", "Screen"]);
    if (m.terminal) views.push(["term", m.screen ? "Serial console" : "Console"]);
    if (m.log) views.push(["log", "Log"]);
    ui.tabs.textContent = "";
    ui.tabs.hidden = views.length < 2;
    for (const [v, name] of views) {
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "tab");
      b.dataset.view = v;
      b.textContent = name;
      b.addEventListener("click", () => select(v));
      ui.tabs.append(b);
    }
    select(views.length ? views[0][0] : null);
    for (const b of ui.menu.querySelectorAll("[data-needs]")) {
      const n = b.dataset.needs;
      b.hidden = n === "term" ? !m.terminal : n === "line" ? !(m.terminal && m.terminal.mode === "line") : !m.screen;
    }
    symbols = null;
    for (const o of ui.machine.options) o.selected = o.value === m.id;
  }

  function select(view) {
    ui.screen.hidden = view !== "screen";
    ui.term.hidden = view !== "term";
    ui.log.hidden = view !== "log";
    for (const b of ui.tabs.children) b.setAttribute("aria-selected", b.dataset.view === view ? "true" : "false");
    if (view === "screen") fitScreen();
    if (view === "term" && term) term.focus();
  }

  // a file of the repository: on the site, its page; elsewhere, GitHub
  function link(path) {
    const root = document.body.dataset.root;
    if (root === undefined || !/\.md$/.test(path)) return GITHUB + path;
    return root + path.replace(/(^|\/)README\.md$/, "$1index.html").replace(/\.md$/, ".html");
  }

  // ---------------------------------------------------------------- running

  function resume() {
    if (state && (state.status === WAITING || state.status === IDLE)) state.status = RUN;
  }

  let last = performance.now();
  function frame(now) {
    requestAnimationFrame(frame);
    const dt = Math.min(0.1, Math.max(0, (now - last) / 1000));
    last = now;
    if (!state || !E) return;
    if (state.running && state.status === RUN) slice(dt);
    drain();
    if (now - (frame.ui || 0) > 200) {
      frame.ui = now;
      update();
    }
  }

  function slice(dt) {
    const speed = Number(ui.speed.value);
    const t0 = performance.now();
    let want = speed ? dt * state.clock * speed : Infinity;
    state.lagging = false;
    try {
      while (want > 0) {
        const c0 = E.cycles();
        const st = E.run(Math.min(want, 1e15), STEPS);
        want -= E.cycles() - c0;
        if (st === FAILED) {
          state.error = errorText();
          state.status = FAILED;
          break;
        }
        state.status = st;
        if (st !== RUN) break;
        if (performance.now() - t0 > WORK_MS) {
          state.lagging = speed !== 0 && want > state.clock * 0.002;
          break;
        }
      }
    } catch (err) {
      // a panic in the engine: the instance is done for
      state.error = `the simulator failed (${err.message})`;
      state.status = FAILED;
    }
  }

  let ctx = null, image = null;
  function drain() {
    if (state.status === FAILED && !state.reported) {
      state.reported = true;
      update();
      return;
    }
    if (state.status === FAILED) return;
    const out = take(E.output());
    if (out.length && term) term.write(latin1(out));
    if (M.log) {
      const log = take(E.log());
      if (log.length) {
        ui.log.append(latin1(log));
        ui.log.scrollTop = ui.log.scrollHeight;
      }
    }
    if (term) term.waiting(state.status === WAITING);
    if (ctx && !ui.screen.hidden) {
      const p = E.screen(0);
      if (p) {
        image.data.set(mem().subarray(p, p + image.data.length));
        ctx.putImageData(image, 0, 0);
      }
    }
  }

  function update() {
    const s = state;
    const on = (name, lit) => lamps[name].classList.toggle("on", !!lit);
    if (!s) {
      on("run", false); on("wait", false); on("halt", false);
      ui.clock.textContent = "";
      return;
    }
    const going = s.running && s.status === RUN;
    on("run", going);
    on("wait", s.running && (s.status === WAITING || s.status === IDLE));
    on("halt", s.status === HALTED || s.status === FAILED);
    ui.run.textContent = s.running ? "Pause" : "Run";
    ui.run.disabled = s.status === HALTED || s.status === FAILED;
    ui.step.disabled = s.running || s.status === HALTED || s.status === FAILED;
    const cycles = s.status === FAILED ? s.seen.cycles : E.cycles();
    ui.clock.textContent = `${mhz(s.clock)} · ${seconds(cycles / s.clock)}`;
    // the speed it went at, over the last second or so
    const now = performance.now(), dt = (now - s.seen.t) / 1000;
    if (dt > 0.9 && s.status !== FAILED) {
      const ins = E.instructions(), idle = E.idle_cycles();
      s.rate = (cycles - s.seen.cycles) / dt;
      s.mips = (ins - s.seen.instructions) / dt / 1e6;
      s.busy = cycles > s.seen.cycles ? 1 - (idle - s.seen.idle) / (cycles - s.seen.cycles) : 0;
      s.seen = { t: now, cycles, instructions: ins, idle };
    }
    let text;
    if (s.status === FAILED) text = `Stopped with an error: ${s.error}. Reset starts it again.`;
    else if (s.status === HALTED) text = "Halted. Reset starts it again.";
    else if (!s.running) text = "Paused.";
    else if (s.status === WAITING) text = "Waiting for the terminal.";
    else if (s.status === IDLE) text = "Asleep, until there's input.";
    else if (s.lagging) text = `Running at ${mhz(s.rate)}: the browser can't keep up with ${mhz(s.clock * Number(ui.speed.value))}.`;
    else text = Number(ui.speed.value) === 0 && s.rate ? `Running flat out, ${mhz(s.rate)}.` : "Running.";
    ui.status.textContent = text;
    ui.status.classList.toggle("bad", s.status === FAILED);
    if (!ui.inspect.hidden) inspect();
  }

  const mhz = (hz) => (hz >= 1e8 ? `${(hz / 1e6).toFixed(0)} MHz` : hz >= 1e6 ? `${(hz / 1e6).toFixed(hz >= 1e7 ? 1 : 2)} MHz` : `${(hz / 1e3).toFixed(0)} kHz`);
  function seconds(t) {
    if (t < 60) return `${t.toFixed(t < 10 ? 2 : 1)} s`;
    const m = Math.floor(t / 60);
    return m < 60 ? `${m} min ${Math.floor(t % 60)} s` : `${Math.floor(m / 60)} h ${m % 60} min`;
  }

  // ---------------------------------------------------------------- the screen

  function fitScreen() {
    if (!M || !M.screen) return;
    const w = ui.canvas.width, h = ui.canvas.height;
    const room = ui.screen.clientWidth || ui.screen.parentElement.clientWidth;
    const k = room >= w ? Math.floor(room / w) : room / w;
    ui.canvas.style.width = `${Math.round(w * k)}px`;
    ui.canvas.style.height = `${Math.round(h * k)}px`;
  }
  window.addEventListener("resize", fitScreen);

  function pointer(e) {
    if (!E || !state || !M.screen) return;
    const r = ui.canvas.getBoundingClientRect();
    const x = Math.floor((e.clientX - r.left) * ui.canvas.width / r.width);
    const y = Math.floor((e.clientY - r.top) * ui.canvas.height / r.height);
    E.mouse(x, y, e.buttons & 7);
    resume();
  }
  ui.canvas.addEventListener("pointermove", pointer);
  ui.canvas.addEventListener("pointerdown", (e) => {
    ui.canvas.focus({ preventScroll: true });
    ui.canvas.setPointerCapture(e.pointerId);
    pointer(e);
    e.preventDefault();
  });
  ui.canvas.addEventListener("pointerup", pointer);
  ui.canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  // The machine's keyboard is a US one. A character goes as the key that
  // types it there, with Shift as that needs, whatever the browser's
  // layout; other keys (Return, the arrows, Ctrl) go by where they are.
  const US = (() => {
    const m = {};
    for (let c = 65; c < 91; c++) {
      const l = String.fromCharCode(c);
      m[l.toLowerCase()] = ["Key" + l, false];
      m[l] = ["Key" + l, true];
    }
    for (let d = 0; d < 10; d++) {
      m[String(d)] = ["Digit" + d, false];
      m[")!@#$%^&*("[d]] = ["Digit" + d, true];
    }
    const keys = { " ": "Space", "-": "Minus", "=": "Equal", "[": "BracketLeft", "]": "BracketRight",
      "\\": "Backslash", ";": "Semicolon", "'": "Quote", ",": "Comma", ".": "Period", "/": "Slash", "`": "Backquote" };
    const shifted = { "_": "Minus", "+": "Equal", "{": "BracketLeft", "}": "BracketRight", "|": "Backslash",
      ":": "Semicolon", "\"": "Quote", "<": "Comma", ">": "Period", "?": "Slash", "~": "Backquote" };
    for (const [ch, code] of Object.entries(keys)) m[ch] = [code, false];
    for (const [ch, code] of Object.entries(shifted)) m[ch] = [code, true];
    return m;
  })();
  const SHIFTS = ["ShiftLeft", "ShiftRight"];
  const shifts = new Set();     // the Shift keys held
  const held = new Map();       // a key held: what the machine was sent for it

  function machineKey(code, down) {
    putText(code);
    return E.key(down ? 1 : 0);
  }

  function keyEvent(e, down) {
    if (!E || !state || !M.screen || e.metaKey) return;
    // the machine's, not the page's (the site's "/" goes to its search)
    e.preventDefault();
    e.stopPropagation();
    resume();
    if (!down) {
      if (SHIFTS.includes(e.code)) shifts.delete(e.code);
      const code = held.get(e.code);
      held.delete(e.code);
      if (code) machineKey(code, false);
      return;
    }
    if (e.key === "AltGraph") return;           // it makes characters, below
    if (SHIFTS.includes(e.code)) shifts.add(e.code);
    const altgr = e.getModifierState && e.getModifierState("AltGraph");
    let us = (!e.ctrlKey && !e.altKey) || altgr ? US[e.key] : null;
    if (!us && e.ctrlKey && /^[a-z]$/i.test(e.key)) us = ["Key" + e.key.toUpperCase(), shifts.size > 0];
    if (!us) {
      if (machineKey(e.code, true)) held.set(e.code, e.code);
      return;
    }
    const [code, shift] = us;
    if (shift === shifts.size > 0) {
      machineKey(code, true);
      held.set(e.code, code);
      return;
    }
    // Shift the other way round for this key: a tap of it, Shift put back
    const fix = shift ? ["ShiftLeft"] : [...shifts];
    for (const s of fix) machineKey(s, shift);
    machineKey(code, true);
    machineKey(code, false);
    for (const s of fix) machineKey(s, !shift);
  }
  ui.canvas.addEventListener("keydown", (e) => keyEvent(e, true));
  ui.canvas.addEventListener("keyup", (e) => keyEvent(e, false));
  ui.canvas.addEventListener("blur", () => {
    // let go of what's held, as a keyboard unplugged would
    if (E && state) for (const code of held.values()) machineKey(code, false);
    held.clear();
    shifts.clear();
  });

  // ---------------------------------------------------------------- the inspector

  let symbols = null;           // [[address, name]], sorted, when loaded

  async function loadSymbols() {
    if (symbols || !M.symbols) return;
    symbols = [];
    try {
      const text = utf8.decode(await blob({ blob: M.symbols }));
      symbols = text.split("\n").filter(Boolean).map((l) => {
        const [a, n] = l.split(" ");
        return [parseInt(a, 16), n];
      });
    } catch (e) {
      symbols = [];
    }
  }

  function symbolAt(a) {
    if (!symbols || !symbols.length) return "";
    let lo = 0, hi = symbols.length - 1, best = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (symbols[mid][0] <= a) {
        best = mid;
        lo = mid + 1;
      } else hi = mid - 1;
    }
    if (best < 0 || a - symbols[best][0] > 0x10000) return "";
    const off = a - symbols[best][0];
    return off ? `${symbols[best][1]}+${off.toString(16)}` : symbols[best][1];
  }

  const hex = (v, n = 8) => (v >>> 0).toString(16).toUpperCase().padStart(n, "0");

  function registers() {
    return utf8.decode(take(E.registers())).split("\n").filter(Boolean).map((l) => {
      const [n, v] = l.split(" ");
      return [n, Number(v) >>> 0];
    });
  }

  function inspect() {
    if (!state || state.status === FAILED) return;
    const s = state, cycles = E.cycles(), ins = E.instructions();
    const rows = [
      ["Simulated", seconds(cycles / s.clock)],
      ["Cycles", cycles.toLocaleString("en")],
      ["Instructions", ins.toLocaleString("en")],
      ["Cycles each", ins ? (cycles / ins).toFixed(2) : "–"],
      ["Speed", s.running && s.status === RUN && s.rate ? `${mhz(s.rate)}, ${s.mips.toFixed(1)} MIPS` : "–"],
    ];
    if (M.board === "fen") rows.push(["Asleep", cycles ? `${(100 * E.idle_cycles() / cycles).toFixed(1)} %` : "–"]);
    ui.stats.textContent = "";
    for (const [k, v] of rows) {
      const dt = document.createElement("dt"), dd = document.createElement("dd");
      dt.textContent = k;
      dd.textContent = v;
      ui.stats.append(dt, dd);
    }
    const regs = registers();
    ui.regs.textContent = "";
    for (const [n, v] of regs) {
      const d = document.createElement("div");
      d.className = "reg";
      let shown = hex(v);
      if (n === "nzcv") shown = "NZCV".split("").map((f, i) => (v & (8 >> i) ? f : "-")).join("");
      else if (["i", "s", "ipl", "bank", "ctx"].includes(n)) shown = String(v);
      const b = document.createElement("b");
      b.textContent = n;
      d.append(b, " " + shown);
      if (n === "pc") {
        const sym = symbolAt(v);
        if (sym) {
          const i = document.createElement("i");
          i.textContent = " " + sym;
          d.append(i);
          d.classList.add("wide");
        }
      }
      ui.regs.append(d);
    }
    dump(regs);
  }

  function dump(regs) {
    const want = ui.addr.value.trim();
    let a = null;
    const reg = regs.find(([n]) => n === want.toLowerCase() || (want.toLowerCase() === "sp" && n === "r15"));
    if (reg) a = reg[1];
    else if (/^(0x)?[0-9a-f]+$/i.test(want)) a = parseInt(want.replace(/^0x/i, ""), 16);
    else if (symbols) {
      const s = symbols.find(([, n]) => n === want);
      if (s) a = s[0];
    }
    if (a === null) {
      ui.dump.textContent = "An address in hex, a register, or a symbol.";
      return;
    }
    // Fen's supervisor sees physical memory through its window at 2 GB
    if (M.board === "fen" && a >= 0x80000000) a -= 0x80000000;
    a = Math.max(0, a - (a % 8) - 32);
    const bytes = take(E.peek(a, 128));
    const lines = [];
    for (let i = 0; i < bytes.length; i += 8) {
      const row = bytes.subarray(i, i + 8);
      const h = Array.from(row, (b) => b.toString(16).padStart(2, "0")).join(" ");
      const t = Array.from(row, (b) => (b >= 32 && b < 127 ? String.fromCharCode(b) : "·")).join("");
      lines.push(`${hex(a + i)}  ${h.padEnd(23)}  ${t}`);
    }
    ui.dump.textContent = lines.join("\n") || "Nothing there: past the end of RAM.";
  }

  ui.addr.addEventListener("input", () => state && E && inspect());
  ui.step.addEventListener("click", () => {
    if (!state || state.running) return;
    try {
      const st = E.run(1e15, 1);
      state.status = st === FAILED ? FAILED : st === RUN ? RUN : st;
      if (st === FAILED) state.error = errorText();
    } catch (err) {
      state.error = err.message;
      state.status = FAILED;
    }
    drain();
    update();
  });
  $("sim-inspect-close").addEventListener("click", () => {
    ui.inspect.hidden = true;
    document.getElementById("sim").classList.remove("inspecting");
  });

  // ---------------------------------------------------------------- the controls

  ui.run.addEventListener("click", () => {
    if (!state) return;
    state.running = !state.running;
    update();
  });
  ui.reset.addEventListener("click", () => M && boot(M));
  ui.machine.addEventListener("change", () => {
    location.hash = ui.machine.value;
  });
  ui.speed.addEventListener("change", () => {
    try {
      localStorage.setItem("heron-sim-speed", ui.speed.value);
    } catch (e) { /* private browsing */ }
    update();
  });
  try {
    const s = localStorage.getItem("heron-sim-speed");
    if (s !== null && [...ui.speed.options].some((o) => o.value === s)) ui.speed.value = s;
  } catch (e) { /* no storage */ }

  function closeMenu() {
    ui.menu.hidden = true;
    ui.more.setAttribute("aria-expanded", "false");
  }
  ui.more.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = ui.menu.hidden;
    ui.menu.hidden = !open;
    ui.more.setAttribute("aria-expanded", String(open));
    if (open) ui.menu.querySelector("button:not([hidden])").focus();
  });
  document.addEventListener("click", (e) => {
    if (!ui.menu.hidden && !ui.menu.contains(e.target)) closeMenu();
  });
  ui.menu.addEventListener("keydown", (e) => {
    const items = [...ui.menu.querySelectorAll("button:not([hidden])")];
    const i = items.indexOf(document.activeElement);
    if (e.key === "Escape") {
      closeMenu();
      ui.more.focus();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length].focus();
    }
  });
  ui.menu.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-act]");
    if (!b) return;
    closeMenu();
    act(b.dataset.act, b);
  });

  function save(name, blobData) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blobData);
    a.download = name;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  }

  function act(what) {
    if (!M) return;
    if (what === "inspect") {
      ui.inspect.hidden = false;
      document.getElementById("sim").classList.add("inspecting");
      loadSymbols().then(() => state && inspect());
      inspect();
    } else if (what === "file") {
      const f = document.createElement("input");
      f.type = "file";
      f.addEventListener("change", async () => {
        if (!f.files[0] || !term) return;
        select("term");
        term.type(await f.files[0].text());
        resume();
        term.focus();
      });
      f.click();
    } else if (what === "eof") {
      if (E && state) {
        E.close();
        resume();
      }
    } else if (what === "clear") {
      if (term) term.clear();
    } else if (what === "transcript") {
      if (term) save(`${M.id}.txt`, new Blob([term.text()], { type: "text/plain" }));
    } else if (what === "shot") {
      ui.canvas.toBlob((b) => b && save(`${M.id}.png`, b), "image/png");
    } else if (what === "link") {
      const url = location.href.split("#")[0] + "#" + M.id;
      const done = () => flash(`Copied ${url}`);
      if (navigator.clipboard) navigator.clipboard.writeText(url).then(done, () => flash(url));
      else flash(url);
    } else if (what === "keys") {
      if (ui.keys.showModal) ui.keys.showModal();
    }
  }

  function flash(text) {
    ui.status.textContent = text;
    frame.ui = performance.now() + 2500;
  }

  // ---------------------------------------------------------------- starting

  function fromHash() {
    const id = decodeURIComponent(location.hash.slice(1));
    const m = catalog.machines.find((x) => x.id === id);
    if (id && !m) setTimeout(() => flash(`There's no machine called “${id}” here; this is the first one.`), 0);
    return m || catalog.machines[0];
  }

  async function start() {
    try {
      const r = await fetch(new URL("machines.json", HERE));
      if (!r.ok) throw new Error(`no machines.json (${r.status})`);
      catalog = await r.json();
    } catch (err) {
      const local = location.protocol === "file:";
      return setOverlay(local ? "The simulator needs to be served over HTTP: heron websim serve, or heron site --apps --serve."
        : `Couldn't load the list of machines: ${err.message}`, true);
    }
    if (!window.WebAssembly || !window.DecompressionStream) {
      return setOverlay("This browser can't run the simulator: it needs WebAssembly and DecompressionStream.", true);
    }
    const groups = new Map();
    for (const m of catalog.machines) {
      if (!groups.has(m.group)) {
        const g = document.createElement("optgroup");
        g.label = m.group;
        groups.set(m.group, g);
        ui.machine.append(g);
      }
      const o = document.createElement("option");
      o.value = m.id;
      o.textContent = `${m.group}: ${m.variant}`;
      groups.get(m.group).append(o);
    }
    window.addEventListener("hashchange", () => boot(fromHash()));
    requestAnimationFrame(frame);
    boot(fromHash());
  }

  start();
})();
