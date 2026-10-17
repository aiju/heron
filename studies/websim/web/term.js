/* The simulator's terminal (studies/websim): a screen of text with
   scrollback, the control characters and the few ANSI sequences a small
   machine prints, and the keyboard.

   What's typed goes to the machine one of two ways. Raw: every key as the
   bytes a terminal sends for it, and the machine echoes (Fen's console
   does). Line: the machine doesn't echo, so the line is edited here and
   sent at Return, with a history (the Lisp's and Egret's consoles); the
   terminal shows a prompt of its own when the machine has none: `prompt`
   when it answered the last line, `prompt2` when it waits for more of it.

   new Terminal(element, {mode, prompt, prompt2, onInput(text), onEnd()})
   write(text)       what the machine printed (a byte a character)
   waiting(bool)     whether the machine waits for input
   type(text)        as if typed (or pasted): lines go as they end
*/
(function () {
  "use strict";

  const COLS = 80, ROWS = 24, KEEP = 5000;

  // what a key sends in raw mode, by KeyboardEvent.key
  const RAW_KEYS = {
    Enter: "\r", Backspace: "\x7f", Tab: "\t", Escape: "\x1b",
    ArrowUp: "\x1b[A", ArrowDown: "\x1b[B", ArrowRight: "\x1b[C", ArrowLeft: "\x1b[D",
    Home: "\x1b[H", End: "\x1b[F", PageUp: "\x1b[5~", PageDown: "\x1b[6~",
    Insert: "\x1b[2~", Delete: "\x1b[3~",
  };

  class Terminal {
    constructor(el, opts) {
      this.el = el;
      this.opts = Object.assign({ mode: "raw", prompt: "", prompt2: "" }, opts);
      el.classList.add("term");
      el.tabIndex = -1;
      this.view = document.createElement("div");
      this.view.className = "term-view";
      this.view.setAttribute("role", "log");
      this.view.setAttribute("aria-live", "polite");
      this.input = document.createElement("textarea");
      this.input.className = "term-input";
      this.input.setAttribute("aria-label", "Type to the machine");
      this.input.autocapitalize = "off";
      this.input.autocomplete = "off";
      this.input.spellcheck = false;
      this.input.setAttribute("autocorrect", "off");
      el.append(this.view, this.input);
      el.addEventListener("mouseup", () => {
        // focus the input unless text is being selected (to copy it)
        if (!String(window.getSelection())) this.focus();
      });
      this.input.addEventListener("keydown", (e) => this.key(e));
      this.input.addEventListener("input", () => this.typed());
      this.input.addEventListener("paste", (e) => {
        e.preventDefault();
        this.type((e.clipboardData || window.clipboardData).getData("text"));
      });
      this.input.addEventListener("focus", () => el.classList.add("focused"));
      this.input.addEventListener("blur", () => el.classList.remove("focused"));
      this.reset();
    }

    reset() {
      this.lines = [[]];
      this.row = 0;
      this.col = 0;
      this.esc = null;            // an escape sequence coming in
      this.edit = "";             // line mode: the line being edited,
      this.at = 0;                // the cursor in it,
      this.history = [];
      this.hpos = 0;
      this.answered = true;       // the machine printed since the last line went
      this.isWaiting = false;
      this.view.textContent = "";
      this.shown = [];            // the line elements
      this.dirty = new Set([0]);
      this.render();
    }

    focus() {
      this.input.focus({ preventScroll: true });
    }

    get top() {
      return Math.max(0, this.lines.length - ROWS);
    }

    // ---- what the machine prints

    write(text) {
      if (!text) return;
      this.answered = true;
      for (const ch of text) this.put(ch);
      this.render();
    }

    put(ch) {
      const c = ch.charCodeAt(0);
      if (this.esc !== null) return this.escape(ch);
      if (c === 0x1b) {
        this.esc = "";
      } else if (c === 10) {
        this.newline();
      } else if (c === 13) {
        this.col = 0;
      } else if (c === 8) {
        this.col = Math.max(0, this.col - 1);
      } else if (c === 9) {
        this.col = Math.min(COLS - 1, (this.col + 8) & ~7);
      } else if (c === 7) {
        this.el.classList.remove("bell");
        void this.el.offsetWidth;
        this.el.classList.add("bell");
      } else if (c >= 32) {
        if (this.col >= COLS) this.newline();
        const line = this.lines[this.row];
        while (line.length < this.col) line.push(" ");
        line[this.col++] = c === 127 ? " " : ch;
        this.dirty.add(this.row);
      }
    }

    newline() {
      this.dirty.add(this.row);
      this.row++;
      this.col = 0;
      if (this.row >= this.lines.length) this.lines.push([]);
      if (this.lines.length > KEEP) {
        const n = this.lines.length - KEEP;
        this.lines.splice(0, n);
        this.row -= n;
        for (const el of this.shown.splice(0, n)) el.remove();
        this.dirty = new Set([...this.dirty].map((r) => r - n).filter((r) => r >= 0));
      }
      this.dirty.add(this.row);
    }

    // ESC [ params final; anything else after ESC is ignored
    escape(ch) {
      if (this.esc === "" && ch !== "[") {
        this.esc = null;
        return;
      }
      this.esc += ch;
      if (this.esc.length === 1) return;
      const c = ch.charCodeAt(0);
      if (c < 0x40 || c > 0x7e) {
        if (this.esc.length > 32) this.esc = null;
        return;
      }
      const args = this.esc.slice(1, -1).split(";").map((a) => parseInt(a, 10));
      const n = (i, d) => (Number.isNaN(args[i]) || args[i] === undefined ? d : args[i]);
      this.esc = null;
      const line = () => this.lines[this.row];
      this.dirty.add(this.row);
      switch (ch) {
        case "A": this.row = Math.max(this.top, this.row - n(0, 1)); break;
        case "B": this.row = Math.min(this.lines.length - 1, this.row + n(0, 1)); break;
        case "C": this.col = Math.min(COLS - 1, this.col + n(0, 1)); break;
        case "D": this.col = Math.max(0, this.col - n(0, 1)); break;
        case "G": this.col = Math.min(COLS - 1, n(0, 1) - 1); break;
        case "H": case "f": {
          const r = this.top + Math.max(0, n(0, 1) - 1);
          while (this.lines.length <= r) this.lines.push([]);
          this.row = r;
          this.col = Math.min(COLS - 1, Math.max(0, n(1, 1) - 1));
          break;
        }
        case "J":
          if (n(0, 0) === 2) {
            for (let r = this.top; r < this.lines.length; r++) {
              this.lines[r] = [];
              this.dirty.add(r);
            }
          } else {
            line().length = Math.min(line().length, this.col);
            for (let r = this.row + 1; r < this.lines.length; r++) {
              this.lines[r] = [];
              this.dirty.add(r);
            }
          }
          break;
        case "K": {
          const k = n(0, 0), l = line();
          if (k === 0) l.length = Math.min(l.length, this.col);
          else if (k === 1) for (let i = 0; i <= this.col && i < l.length; i++) l[i] = " ";
          else l.length = 0;
          break;
        }
        default: break;           // colours and the rest: ignored
      }
      this.dirty.add(this.row);
    }

    // ---- showing it

    render() {
      const stick = this.view.scrollHeight - this.view.scrollTop - this.view.clientHeight < 24;
      while (this.shown.length < this.lines.length) {
        const d = document.createElement("div");
        d.className = "ln";
        this.view.append(d);
        this.shown.push(d);
        this.dirty.add(this.shown.length - 1);
      }
      if (this.cursorRow !== undefined && this.cursorRow !== this.row) this.dirty.add(this.cursorRow);
      this.dirty.add(this.row);
      for (const r of this.dirty) {
        const el = this.shown[r];
        if (!el) continue;
        const text = this.lines[r].join("");
        if (r !== this.row) {
          el.textContent = text;
          continue;
        }
        // the cursor's line: the machine's text, the line being edited, the cursor
        let before = text.slice(0, this.col).padEnd(this.col, " ");
        let after = text.slice(this.col);
        if (this.opts.mode === "line") {
          const prompt = this.col === 0 && this.isWaiting
            ? (this.answered ? this.opts.prompt : this.opts.prompt2) : "";
          before += prompt + this.edit.slice(0, this.at);
          after = this.edit.slice(this.at) + after.slice(prompt.length + this.edit.length);
        }
        el.textContent = "";
        const cur = document.createElement("span");
        cur.className = "cursor";
        cur.textContent = after[0] || " ";
        el.append(before, cur, after.slice(1));
      }
      this.cursorRow = this.row;
      this.dirty.clear();
      if (stick) this.view.scrollTop = this.view.scrollHeight;
    }

    waiting(on) {
      if (on === this.isWaiting) return;
      this.isWaiting = on;
      this.el.classList.toggle("waiting", on);
      this.dirty.add(this.row);
      this.render();
    }

    clear() {
      const keep = this.lines[this.row];
      this.lines = [keep];
      this.row = 0;
      this.view.textContent = "";
      this.shown = [];
      this.dirty = new Set([0]);
      this.render();
    }

    /* everything on it, as text */
    text() {
      return this.lines.map((l) => l.join("").replace(/\s+$/, "")).join("\n").replace(/\n+$/, "\n");
    }

    // ---- the keyboard

    send(text) {
      if (this.opts.onInput) this.opts.onInput(text);
    }

    key(e) {
      if (e.isComposing || e.keyCode === 229) return;
      if (e.metaKey) return;                      // the browser's: copy, paste
      if (e.ctrlKey && (e.key === "v" || e.key === "V")) return;
      if (e.ctrlKey && e.key === "c" && String(window.getSelection())) return;
      const handled = this.opts.mode === "line" ? this.lineKey(e) : this.rawKey(e);
      if (handled) e.preventDefault();
    }

    rawKey(e) {
      if (e.ctrlKey && !e.altKey && e.key.length === 1) {
        const c = e.key.toUpperCase().charCodeAt(0);
        if (c >= 64 && c < 96) {
          this.send(String.fromCharCode(c & 31));
          return true;
        }
        if (e.key === " ") {
          this.send("\0");
          return true;
        }
        return false;
      }
      if (RAW_KEYS[e.key]) {
        this.send(RAW_KEYS[e.key]);
        return true;
      }
      if (e.key.length === 1) {
        this.send(e.altKey ? "\x1b" + e.key : e.key);
        return true;
      }
      return false;
    }

    // line mode: an editor of one line
    lineKey(e) {
      const k = e.key, ctrl = e.ctrlKey && !e.altKey;
      const set = (text, at) => {
        this.edit = text;
        this.at = Math.max(0, Math.min(text.length, at));
        this.dirty.add(this.row);
        this.render();
      };
      const word = (i) => {
        while (i > 0 && this.edit[i - 1] === " ") i--;
        while (i > 0 && this.edit[i - 1] !== " ") i--;
        return i;
      };
      if (k === "Enter") {
        this.commit();
      } else if (k === "Backspace" || (ctrl && k === "h")) {
        if (this.at > 0) set(this.edit.slice(0, this.at - 1) + this.edit.slice(this.at), this.at - 1);
      } else if (k === "Delete") {
        set(this.edit.slice(0, this.at) + this.edit.slice(this.at + 1), this.at);
      } else if (k === "ArrowLeft" || (ctrl && k === "b")) {
        set(this.edit, this.at - 1);
      } else if (k === "ArrowRight" || (ctrl && k === "f")) {
        set(this.edit, this.at + 1);
      } else if (k === "Home" || (ctrl && k === "a")) {
        set(this.edit, 0);
      } else if (k === "End" || (ctrl && k === "e")) {
        set(this.edit, this.edit.length);
      } else if (ctrl && k === "u") {
        set(this.edit.slice(this.at), 0);
      } else if (ctrl && k === "k") {
        set(this.edit.slice(0, this.at), this.at);
      } else if (ctrl && k === "w") {
        const w = word(this.at);
        set(this.edit.slice(0, w) + this.edit.slice(this.at), w);
      } else if (k === "ArrowUp" || k === "ArrowDown") {
        const h = this.history, i = this.hpos + (k === "ArrowUp" ? -1 : 1);
        if (i < 0 || i > h.length) return true;
        if (this.hpos === h.length) this.draft = this.edit;
        this.hpos = i;
        const t = i === h.length ? this.draft || "" : h[i];
        set(t, t.length);
      } else if (ctrl && k === "d") {
        if (this.edit.length) set(this.edit.slice(0, this.at) + this.edit.slice(this.at + 1), this.at);
        else if (this.opts.onEnd) this.opts.onEnd();
      } else if (ctrl && k === "c") {
        this.write("^C\n");
        set("", 0);
      } else if (ctrl && k === "l") {
        this.clear();
      } else if (k === "Tab") {
        set(this.edit.slice(0, this.at) + "  " + this.edit.slice(this.at), this.at + 2);
      } else if (k.length === 1 && !ctrl) {
        set(this.edit.slice(0, this.at) + k + this.edit.slice(this.at), this.at + 1);
      } else {
        return false;
      }
      return true;
    }

    /* the line at Return: shown as typed, and sent */
    commit() {
      const text = this.edit;
      const prompt = this.col === 0 && this.isWaiting ? (this.answered ? this.opts.prompt : this.opts.prompt2) : "";
      this.edit = "";
      this.at = 0;
      if (text.trim() && this.history[this.history.length - 1] !== text) this.history.push(text);
      if (this.history.length > 500) this.history.shift();
      this.hpos = this.history.length;
      this.draft = "";
      for (const ch of prompt + text) this.put(ch);
      this.newline();
      this.answered = false;
      this.isWaiting = false;
      this.render();
      this.send(text + "\n");
    }

    /* text from the input element the keys didn't account for (a phone's
       keyboard, an input method) */
    typed() {
      const v = this.input.value;
      this.input.value = "";
      if (v) this.type(v);
    }

    /* text as if typed: in line mode each line goes as it ends, and the
       rest is left to edit */
    type(text) {
      text = text.replace(/\r\n?/g, "\n");
      if (this.opts.mode !== "line") {
        this.send(text.replace(/\n/g, "\r"));
        return;
      }
      const parts = text.split("\n");
      for (let i = 0; i < parts.length; i++) {
        const p = parts[i].replace(/\t/g, "  ");
        this.edit = this.edit.slice(0, this.at) + p + this.edit.slice(this.at);
        this.at += p.length;
        if (i < parts.length - 1) this.commit();
      }
      this.dirty.add(this.row);
      this.render();
    }
  }

  window.HeronTerminal = Terminal;
})();
