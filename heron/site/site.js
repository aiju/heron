// The Heron Reference Library's behaviour (heron site). Every page reads
// without it; this adds the index's filters, sorting and summaries, the
// full-text search, and on documents the section links, the contents that
// follow the reading and the highlighting of what a search found.
(() => {
  "use strict";
  const GH = "https://github.com/aiju/heron";
  const root = document.body.dataset.root || "";
  const qin = document.getElementById("q");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const reEsc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const terms = (q) => q.toLowerCase().split(/\s+/).filter(Boolean);
  const store = {
    get(k, v) { try { const x = localStorage.getItem(k); return x === null ? v : JSON.parse(x); } catch { return v; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private window */ } },
  };

  let toastTimer;
  function toast(msg) {
    let t = document.querySelector(".toast");
    if (!t) { t = document.createElement("div"); t.className = "toast"; t.setAttribute("role", "status"); document.body.appendChild(t); }
    t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 2600);
  }

  // "/" anywhere goes to the search box.
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !e.ctrlKey && !e.metaKey && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
      e.preventDefault(); qin.focus(); qin.select();
    }
  });

  // ------------------------------------------------------------ search
  let index = null;
  function loadIndex() {
    if (!index) index = fetch(root + "search.json").then((r) => r.json()).then((a) => a.map((x) => ({ ...x, lt: x.t.toLowerCase() })));
    return index;
  }
  function count(hay, t) { let n = 0, i = hay.indexOf(t); while (i >= 0 && n < 999) { n++; i = hay.indexOf(t, i + t.length); } return n; }
  function snippet(text, lt, ts) {
    const found = ts.map((t) => lt.indexOf(t)).filter((i) => i >= 0);
    if (!found.length) return "";
    const pos = Math.min(...found);
    const start = pos > 80 ? text.lastIndexOf(" ", pos - 80) + 1 : 0;
    const end = Math.min(text.length, pos + 180);
    const re = new RegExp(ts.map(reEsc).join("|"), "gi");
    return (start > 0 ? "… " : "") + esc(text.slice(start, end)).replace(re, (m) => `<mark>${m}</mark>`) + (end < text.length ? " …" : "");
  }
  function search(pages, q) {
    const ts = terms(q), out = [];
    for (const p of pages) {
      if (!ts.every((t) => p.meta.includes(t) || p.lt.includes(t))) continue;
      let score = 0;
      const sub = p.id.endsWith("›");
      if (p.no && !sub && (q.trim() === p.no || q.trim() === String(+p.no))) score += 10000;
      if (ts.every((t) => p.title.toLowerCase().includes(t))) score += 1000;
      const hits = ts.reduce((n, t) => n + count(p.lt, t), 0);
      out.push({ p, hits, score: score + Math.min(hits, 900) + (sub ? 0 : 5), snip: snippet(p.t, p.lt, ts) });
    }
    return out.sort((a, b) => b.score - a.score || a.p.u.localeCompare(b.p.u));
  }

  // ------------------------------------------------------------ the index
  const table = document.getElementById("dir");
  if (table && document.body.classList.contains("index")) {
    const tbody = table.tBodies[0];
    const rows = [...tbody.rows];
    const bar = document.getElementById("bar");
    const libbody = document.getElementById("libbody");
    const results = document.getElementById("results");
    const TYPES = [["all", "All"], ["rfc", "RFC"], ["ideas", "Ideas"], ["report", "Report"]];
    const STATUSES = [["all", "All"], ["open", "Open"], ["draft", "Draft"], ["accepted", "Accepted"], ["current", "Current"], ["rejected", "Rejected"], ["obsolete", "Obsolete"]];
    const ORDER = ["open", "draft", "accepted", "current", "rejected", "obsolete"];
    const st = Object.assign({ type: "all", status: "all", sort: "n", desc: true, sum: false }, store.get("heron-index", {}));
    const empty = document.createElement("tr");
    empty.className = "empty";
    empty.innerHTML = `<td colspan="6">Nothing has this type and status.</td>`;

    const pass = (r, t, s) => (t === "all" || r.dataset.type === t) && (s === "all" || r.dataset.status === s);
    const n = (t, s) => rows.filter((r) => pass(r, t, s)).length;
    function seg(label, opts, key) {
      const buttons = opts.map(([v, l]) => {
        const c = key === "type" ? n(v, st.status) : n(st.type, v);
        if (key === "status" && v !== "all" && c === 0 && st.status !== v) return "";
        return `<button type="button" data-key="${key}" data-v="${v}" aria-pressed="${st[key] === v}">${l}<span class="n">${c}</span></button>`;
      }).join("");
      return `<div class="seg" role="group" aria-label="${label}"><span class="label">${label}</span>${buttons}</div>`;
    }
    function apply() {
      store.set("heron-index", st);
      bar.innerHTML = seg("Type", TYPES, "type") + seg("Status", STATUSES, "status") +
        `<label class="opt label" for="sum"><input type="checkbox" id="sum"${st.sum ? " checked" : ""}>Summaries</label>`;
      const key = { n: (r) => r.dataset.n, title: (r) => r.dataset.title, date: (r) => r.dataset.date + r.dataset.n,
                    status: (r) => String(ORDER.indexOf(r.dataset.status)).padStart(2, "0") + r.dataset.n }[st.sort];
      const sorted = [...rows].sort((a, b) => key(a).localeCompare(key(b)) * (st.desc ? -1 : 1));
      let shown = 0;
      for (const r of sorted) { r.hidden = !pass(r, st.type, st.status); shown += !r.hidden; tbody.appendChild(r); }
      if (!shown) tbody.appendChild(empty); else empty.remove();
      table.classList.toggle("sum", st.sum);
      table.tHead.querySelectorAll("th").forEach((th) => {
        const b = th.querySelector("[data-sort]");
        if (b && b.dataset.sort === st.sort) th.setAttribute("aria-sort", st.desc ? "descending" : "ascending");
        else th.removeAttribute("aria-sort");
      });
    }
    bar.hidden = false;
    bar.addEventListener("click", (e) => { const b = e.target.closest("button[data-key]"); if (b) { st[b.dataset.key] = b.dataset.v; apply(); } });
    bar.addEventListener("change", (e) => { if (e.target.id === "sum") { st.sum = e.target.checked; apply(); } });
    table.tHead.addEventListener("click", (e) => {
      const b = e.target.closest("[data-sort]"); if (!b) return;
      if (st.sort === b.dataset.sort) st.desc = !st.desc;
      else { st.sort = b.dataset.sort; st.desc = st.sort === "n" || st.sort === "date"; }
      apply();
    });
    tbody.addEventListener("click", (e) => {
      if (e.target.closest("a")) return;
      const a = e.target.closest("tr")?.querySelector(".c-title a");
      if (a) location.href = a.href;
    });
    apply();

    // The search runs here, in place of the table, as you type.
    let seq = 0;
    async function run() {
      const q = qin.value.trim();
      history.replaceState(null, "", q ? "?q=" + encodeURIComponent(q) : location.pathname);
      if (!q) { results.hidden = true; libbody.hidden = false; return; }
      libbody.hidden = true; results.hidden = false;
      const my = ++seq;
      if (!results.innerHTML) results.innerHTML = `<div class="rs-head"><span>Searching…</span></div>`;
      let pages;
      try { pages = await loadIndex(); } catch { results.innerHTML = `<div class="rs-head"><span>The search index didn't load.</span></div>`; return; }
      if (my !== seq) return;
      const res = search(pages, q);
      results.innerHTML = `
        <div class="rs-head"><span><b>${res.length}</b> ${res.length === 1 ? "page matches" : "pages match"} “${esc(q)}” <span class="status">· titles and full text</span></span><button type="button" id="clearq">Clear</button></div>
        <ol class="results">${res.map((x) => `<li><a href="${esc(root + x.p.u)}?hl=${encodeURIComponent(q)}"><span class="r-id">${esc(x.p.id)}</span><span class="r-t">${esc(x.p.title)}</span><span class="r-n">${x.hits ? `${x.hits} ${x.hits === 1 ? "match" : "matches"}` : ""}</span>${x.snip ? `<span class="r-s">${x.snip}</span>` : ""}</a></li>`).join("")}</ol>`;
    }
    results.addEventListener("click", (e) => { if (e.target.id === "clearq") { qin.value = ""; run(); qin.focus(); } });
    qin.form.addEventListener("submit", (e) => { e.preventDefault(); run(); });
    qin.addEventListener("input", run);
    qin.addEventListener("keydown", (e) => { if (e.key === "Escape") { qin.value = ""; run(); } });
    const q0 = new URLSearchParams(location.search).get("q");
    if (q0) { qin.value = q0; run(); }
  }

  // ------------------------------------------------------------ documents
  const prose = document.getElementById("prose");
  if (prose) {
    // Section links: copy the section's address on GitHub (on its branch,
    // for a draft), which is how documents are cited in chats and pull
    // requests (AGENTS.md).
    const src = document.body.dataset.src;
    if (src) {
      prose.querySelectorAll("h2[id], h3[id], h4[id], h5[id]").forEach((h) => {
        const a = document.createElement("a");
        a.className = "sec"; a.href = `#${h.id}`; a.textContent = "§";
        a.title = "Copy a link to this section on GitHub"; a.setAttribute("aria-label", a.title);
        a.dataset.copy = `${GH}/blob/${document.body.dataset.ref || "main"}/${src}#${h.id}`;
        h.appendChild(a);
      });
      prose.addEventListener("click", (e) => {
        const a = e.target.closest("a.sec"); if (!a) return;
        const url = a.dataset.copy;
        const done = navigator.clipboard?.writeText(url);
        if (done) done.then(() => toast("Copied the section's GitHub link"), () => toast(url)); else toast(url);
      });
    }

    // The contents in the margin follow the reading.
    const links = new Map([...document.querySelectorAll(".side .toc a")].map((a) => [decodeURIComponent(a.hash.slice(1)), a]));
    const heads = [...prose.querySelectorAll("h2[id], h3[id]")].filter((h) => links.has(h.id));
    if (heads.length && "IntersectionObserver" in window) {
      const side = document.querySelector(".side");
      const io = new IntersectionObserver(() => {
        const top = heads.filter((h) => h.getBoundingClientRect().top < innerHeight * 0.25).pop();
        links.forEach((a) => a.classList.remove("active"));
        const a = top && links.get(top.id);
        if (!a) return;
        a.classList.add("active");
        const r = a.getBoundingClientRect(), s = side.getBoundingClientRect();
        if (r.top < s.top || r.bottom > s.bottom) a.scrollIntoView({ block: "nearest" });
      }, { rootMargin: "0px 0px -70% 0px", threshold: [0, 1] });
      heads.forEach((h) => io.observe(h));
    }
    document.querySelectorAll(".side-m a").forEach((a) => a.addEventListener("click", () => a.closest("details").open = false));

    // ?hl=: mark what a search found, and step through it.
    const hl = new URLSearchParams(location.search).get("hl");
    if (hl && terms(hl).length) {
      const ts = terms(hl);
      const re = new RegExp(ts.map(reEsc).join("|"), "gi");
      const walker = document.createTreeWalker(prose, NodeFilter.SHOW_TEXT, {
        acceptNode: (t) => t.parentElement.closest("mjx-container, .sec, script") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
      });
      const nodes = [];
      while (walker.nextNode()) nodes.push(walker.currentNode);
      let made = 0;
      for (const node of nodes) {
        const t = node.nodeValue;
        re.lastIndex = 0;
        if (made > 500 || !re.test(t)) continue;
        const frag = document.createDocumentFragment();
        let last = 0, m;
        re.lastIndex = 0;
        while ((m = re.exec(t))) {
          frag.append(t.slice(last, m.index));
          const mk = document.createElement("mark"); mk.className = "hit"; mk.textContent = m[0];
          frag.append(mk); last = m.index + m[0].length; made++;
        }
        frag.append(t.slice(last));
        node.replaceWith(frag);
      }
      const marks = [...prose.querySelectorAll("mark.hit")];
      if (marks.length) {
        const bar = document.createElement("div");
        bar.className = "findbar"; bar.setAttribute("role", "status");
        bar.innerHTML = `<span><span class="fi">1</span> of ${marks.length} for <mark>${esc(ts.join(" "))}</mark></span><span class="sp"></span>` +
          `<button type="button" data-d="-1" aria-label="Previous match">↑</button><button type="button" data-d="1" aria-label="Next match">↓</button><button type="button" data-d="0">Clear</button>`;
        prose.before(bar);
        let cur = 0;
        const go = (i) => {
          marks[cur].classList.remove("cur");
          cur = (i + marks.length) % marks.length;
          marks[cur].classList.add("cur");
          marks[cur].scrollIntoView({ block: "center" });
          bar.querySelector(".fi").textContent = cur + 1;
        };
        bar.addEventListener("click", (e) => {
          const b = e.target.closest("button"); if (!b) return;
          if (b.dataset.d === "0") {
            marks.forEach((m) => m.replaceWith(m.textContent)); prose.normalize(); bar.remove();
            history.replaceState(null, "", location.pathname + location.hash);
            return;
          }
          go(cur + +b.dataset.d);
        });
        go(0);
      }
    }
  }
})();
