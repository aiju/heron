"""Profiles of runs, and the database they go in.

A profile (heron.native.v1b_profile, the Rust in collect/) attaches to a
simulated machine and watches every instruction it executes. `attach()`
puts one on a machine; `rows()` turns its results, with the program's
symbols, into the database's rows; `Database` stores them. The schema is
below, and README.md says what each table is for.
"""

import datetime
import os
import sqlite3
import subprocess
from bisect import bisect_right

from heron import BUILD, ROOT, native
from heron.studies.v1_isa import timing32

DB_PATH = os.path.join(BUILD, "v1b_profile", "profile.db")

# the model's six configurations, as column names
CONFIG_COLUMNS = {
    "D16-separate": "d16_sep", "D16-overlap": "d16_ovl", "D16-wide": "d16_wide",
    "D32-separate": "d32_sep", "D32-overlap": "d32_ovl", "D32-wide": "d32_wide",
}
MODEL = [CONFIG_COLUMNS[c] for c in timing32.CONFIG_NAMES]
_M = ", ".join(f"{c} INTEGER" for c in MODEL)

SCHEMA = f"""
-- One run of a program: a trace.
CREATE TABLE IF NOT EXISTS trace (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,      -- study/program[/variant]
    study TEXT, program TEXT, variant TEXT,
    language TEXT,                  -- asm, C, Lisp, Egret
    isa TEXT,                       -- v1b, v1bx (the Lisp's tags), v1bs (the kernel's system extensions)
    description TEXT,
    input TEXT,                     -- what it was given: console input, a scenario
    instructions INTEGER,           -- executed
    static_insns INTEGER,           -- distinct instructions executed
    hw_cycles INTEGER,              -- on the draft 1b hardware: instructions and interrupt entries
    hw_unknown INTEGER,             -- instructions it doesn't implement (no cost known)
    {_M},                           -- the timing model's estimates, interrupt entries included
    irqs INTEGER, irq_hw_cycles INTEGER,
    traps INTEGER,
    ok INTEGER,                     -- the output was what was expected (NULL: nothing to compare)
    output TEXT,                    -- the console output (the first 4 KB)
    mismatches INTEGER,             -- the hardware shadow disagreed with the simulator (should be 0)
    shadow_errors INTEGER,
    notes TEXT,
    seconds REAL,                   -- the collection's wall time
    source TEXT,                    -- git commit and branch it was collected at
    collected TEXT
);

-- Code: an instruction at an address, as the programs have it, shared by
-- the traces that ran it.
CREATE TABLE IF NOT EXISTS code (
    id INTEGER PRIMARY KEY,
    isa TEXT, pc INTEGER,
    parcels INTEGER, hex TEXT,
    text TEXT,                      -- disassembly
    op TEXT,                        -- mnemonic: MOV, ADD, BNE, ...
    kind TEXT,                      -- operation and operand form: 'MOV [r+d]', 'Bcc', 'LSL reg'
    mode TEXT,                      -- the EA instructions' operand mode: r, #q, #i16, [r+d], b[r]+, ...
    func TEXT, symbol TEXT, offset INTEGER,   -- the enclosing function, nearest label and offset from it
    file TEXT, line INTEGER, source TEXT,     -- where it came from, when the assembler kept it
    reads TEXT, writes TEXT, freads TEXT, fwrites TEXT,   -- registers and flags it uses
    hw_illegal INTEGER              -- the hardware doesn't implement it (v1bx and v1bs extensions)
);

-- An instruction a trace executed: an address and the code there (code
-- that changes, a JIT's say, gets a row per version).
CREATE TABLE IF NOT EXISTS insn (
    trace INTEGER NOT NULL REFERENCES trace(id),
    id INTEGER NOT NULL,            -- within the trace, in order of first execution
    code INTEGER REFERENCES code(id),
    pc INTEGER, phys INTEGER, version INTEGER,
    class TEXT,                     -- timing class: alu, shift, mul, div, ld, op, st, lea, br, jmp, jmpm, call, callm, ret, rti, sys, trap
    count INTEGER,                  -- executions
    hw_cycles INTEGER, hw_unknown INTEGER, hw_min INTEGER, hw_max INTEGER,
    {_M},
    taken INTEGER,                  -- conditional branches: executions that jumped
    irqs INTEGER, traps INTEGER,
    reg_defs INTEGER, reg_defs_used INTEGER,  -- register results written, and read before overwritten
    n_defs INTEGER, n_used INTEGER, z_defs INTEGER, z_used INTEGER,
    c_defs INTEGER, c_used INTEGER, v_defs INTEGER, v_used INTEGER,
    mem INTEGER, mem_io INTEGER, mem_other INTEGER, mem_min INTEGER, mem_max INTEGER,
    first_step INTEGER, mismatches INTEGER,
    PRIMARY KEY (trace, id)
) WITHOUT ROWID;

-- Executions of an instruction per timing key and hardware cost.
CREATE TABLE IF NOT EXISTS exec (
    trace INTEGER NOT NULL, insn INTEGER NOT NULL,
    -- the timing key (studies/v1_isa/timing32.py): its class and parameters
    class TEXT, parcels INTEGER, p2 INTEGER,
    ea TEXT, size INTEGER, x INTEGER, wb INTEGER, taken INTEGER, how TEXT,
    bits INTEGER, signed INTEGER, steps INTEGER, regs INTEGER,
    hw INTEGER,                     -- hardware cycles of one execution (NULL: unknown)
    count INTEGER,
    {_M}                            -- the model's cycles of one execution
);

-- Control flow: how often each instruction was followed by each address.
CREATE TABLE IF NOT EXISTS edge (
    trace INTEGER NOT NULL, src INTEGER NOT NULL,
    dst_pc INTEGER, dst INTEGER,    -- dst: the instruction there, when there is just one
    kind TEXT,                      -- next, irq (an interrupt after src), trap
    fallthrough INTEGER,
    count INTEGER
);

-- Def-use chains of the flags: reads of flags `flags` by `reader` that found
-- them set by `writer`.
CREATE TABLE IF NOT EXISTS flag_use (
    trace INTEGER NOT NULL, writer INTEGER, reader INTEGER, flags TEXT, count INTEGER
);

-- Def-use chains of the registers: reads of `reg` by `reader` that found
-- `writer`'s result, and the instructions between them.
CREATE TABLE IF NOT EXISTS reg_use (
    trace INTEGER NOT NULL, writer INTEGER, reader INTEGER, reg TEXT, count INTEGER,
    dist_sum INTEGER
);

-- Def-use distances in instructions: reads whose definition was lo to hi
-- instructions back.
CREATE TABLE IF NOT EXISTS dist (
    trace INTEGER NOT NULL, lo INTEGER, hi INTEGER, count INTEGER
);

-- Functions, from the call stack: calls and inclusive costs (a recursive
-- function's outermost activations only).
CREATE TABLE IF NOT EXISTS func (
    trace INTEGER NOT NULL, pc INTEGER, name TEXT, calls INTEGER,
    insns INTEGER, hw_cycles INTEGER, {_M}
);

CREATE INDEX IF NOT EXISTS insn_code ON insn(code);
CREATE INDEX IF NOT EXISTS code_kind ON code(kind);
CREATE INDEX IF NOT EXISTS code_func ON code(func);
CREATE INDEX IF NOT EXISTS exec_insn ON exec(trace, insn);
CREATE INDEX IF NOT EXISTS edge_src ON edge(trace, src);
CREATE INDEX IF NOT EXISTS edge_dst ON edge(trace, dst);
CREATE INDEX IF NOT EXISTS flag_writer ON flag_use(trace, writer);
CREATE INDEX IF NOT EXISTS flag_reader ON flag_use(trace, reader);
CREATE INDEX IF NOT EXISTS reg_writer ON reg_use(trace, writer);
CREATE INDEX IF NOT EXISTS reg_reader ON reg_use(trace, reader);
CREATE INDEX IF NOT EXISTS func_trace ON func(trace);

-- Every instruction a trace executed, with its code and its trace's name;
-- costs per execution, and its share of the trace's instructions.
CREATE VIEW IF NOT EXISTS insns AS
SELECT t.name AS trace_name, i.*, c.isa, c.parcels, c.hex, c.text, c.op, c.kind, c.mode,
       c.func, c.symbol, c.offset, c.file, c.line, c.source,
       c.reads, c.writes, c.freads, c.fwrites, c.hw_illegal,
       ROUND(1.0 * i.hw_cycles / NULLIF(i.count - i.hw_unknown, 0), 2) AS hw_cpi,
       ROUND(100.0 * i.count / t.instructions, 3) AS pct
FROM insn i JOIN trace t ON t.id = i.trace JOIN code c ON c.id = i.code;

-- The instruction mix of each trace, by kind.
CREATE VIEW IF NOT EXISTS mix AS
SELECT t.name AS trace, c.kind, SUM(i.count) AS count,
       ROUND(100.0 * SUM(i.count) / t.instructions, 2) AS pct,
       SUM(i.hw_cycles) AS hw_cycles,
       ROUND(100.0 * SUM(i.hw_cycles) / t.hw_cycles, 2) AS hw_pct,
       ROUND(1.0 * SUM(i.hw_cycles) / NULLIF(SUM(i.count) - SUM(i.hw_unknown), 0), 2) AS hw_cpi
FROM insn i JOIN trace t ON t.id = i.trace JOIN code c ON c.id = i.code
GROUP BY t.id, c.kind;

-- Costs by function: own (the function's instructions) and inclusive
-- (from the call stack; NULL for code never called).
CREATE VIEW IF NOT EXISTS profile AS
SELECT t.name AS trace, c.func, SUM(i.count) AS insns, SUM(i.hw_cycles) AS hw_cycles,
       ROUND(100.0 * SUM(i.hw_cycles) / t.hw_cycles, 2) AS hw_pct,
       (SELECT SUM(f.calls) FROM func f WHERE f.trace = t.id AND f.name = c.func) AS calls,
       (SELECT MAX(f.hw_cycles) FROM func f WHERE f.trace = t.id AND f.name = c.func) AS incl_hw_cycles
FROM insn i JOIN trace t ON t.id = i.trace JOIN code c ON c.id = i.code
GROUP BY t.id, c.func;
"""

TABLES = ("insn", "exec", "edge", "flag_use", "reg_use", "dist", "func")
REG_NAMES = [f"r{i}" for i in range(15)] + ["sp", "HI"]
FLAG_NAMES = "NZCV"


def regs(mask):
    return " ".join(REG_NAMES[r] for r in range(17) if mask >> r & 1) or None


def flags(mask):
    return "".join(FLAG_NAMES[f] for f in range(4) if mask >> f & 1) or None


def source_id():
    """The commit (and branch) the code is at, and whether it has changes."""
    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                                  check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return ""
    commit = git("rev-parse", "--short=12", "HEAD")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    dirty = "+changes" if git("status", "--porcelain", "--untracked-files=no") else ""
    return f"{commit}{dirty} ({branch})" if commit else "unknown"


# ---------------------------------------------------------------- attaching

def rom():
    from heron.studies.v1b_hw import rtl_native
    return rtl_native.rom()


def attach(machine, shadow=True, check=True):
    """Put a profile on a machine (a Machine32 or a heron.native.v1 Machine),
    replacing any it had."""
    m = getattr(machine, "_m", machine)
    native.v1b_profile.start(m, rom() if shadow else None, check)
    return m


def results(machine):
    return native.v1b_profile.results(getattr(machine, "_m", machine))


# ---------------------------------------------------------------- symbols

class Symbols:
    """Labels and source lines of a program: what function an address is
    in, and where its instruction came from. Addresses at or past `end`
    hold code the program made itself (a JIT's, a compiler's)."""

    def __init__(self, labels=(), lines=None, end=None, regions=(), prefix=""):
        self.labels = sorted((a, prefix + n) for a, n in labels)
        self.addrs = [a for a, _ in self.labels]
        self.lines = lines or {}
        self.end = end
        # (lo, hi, Symbols, offset): another program's symbols for [lo, hi)
        self.regions = list(regions)
        self.by_addr = {}
        for a, n in self.labels:
            self.by_addr.setdefault(a, n)

    @classmethod
    def of(cls, img, end=None, prefix=""):
        """From an assembled or linked image (`prefix`: put before every
        name)."""
        labels, lines = [], {}
        for st in getattr(img, "stmts", ()):
            if st.kind == "label" and st.label:
                labels.append((st.addr, st.label))
            elif st.kind == "insn" and getattr(st, "where", None):
                lines[st.addr] = (st.where[0], st.where[1], (st.text or "").strip())
        if not labels:
            labels = [(a, n) for n, a in getattr(img, "symbols", {}).items()]
        if end is None and getattr(img, "mem", None):
            end = max(img.mem) + 1
        return cls(labels, lines, end, prefix=prefix)

    def names(self):
        """address -> name, for the disassembler."""
        return self.by_addr

    def at(self, pc, phys=None):
        """(func, symbol, offset, file, line, source) of an address."""
        a = pc if phys is None else phys
        for lo, hi, sub, off in self.regions:
            if lo <= a < hi:
                return sub.at(a - off)
        if self.end is not None and pc >= self.end:
            return ("(generated)", None, None, None, None, None)
        i = bisect_right(self.addrs, pc) - 1
        if i < 0:
            return (None, None, None, None, None, None)
        addr, name = self.labels[i]
        func = name.split(".")[0] or name
        ln = self.lines.get(pc)
        return (func, name, pc - addr) + (ln if ln else (None, None, None))


# ---------------------------------------------------------------- rows

def _key_columns(key):
    """The timing key's parts as the exec table's columns."""
    n, p2, kind, *p = key
    col = dict(ea=None, size=None, x=None, wb=None, taken=None, how=None, bits=None,
               signed=None, steps=None, regs=None)
    if kind == "alu":
        col["wb"], = p
    elif kind == "shift":
        col["steps"], = p
    elif kind == "mul":
        col["bits"], col["signed"] = p
    elif kind == "div":
        col["signed"], = p
    elif kind in ("ld", "st"):
        col["ea"], col["size"], col["x"] = p
    elif kind == "op":
        col["ea"], col["size"], col["x"], col["wb"] = p
    elif kind in ("lea", "jmpm", "callm"):
        col["ea"], col["x"] = p
    elif kind == "br":
        col["taken"], col["x"] = p
    elif kind in ("jmp", "call"):
        col["how"], col["x"] = p
    elif kind in ("save", "restore"):
        col["regs"], = p
    return n, p2, kind, col


def rows(res, syms, isa):
    """The database rows for a profile's results: {table: [row, ...]} for
    the tables after `trace`, without the trace column. An insn row's
    second item is its code row, which Database.store finds or adds."""
    names = syms.names()
    by_insn = {}
    for idx, key, hw, count, model in res["keys"]:
        by_insn.setdefault(idx, []).append((key, hw, count, model))
    out = {t: [] for t in TABLES}
    pcs = {}
    insn_info = {}
    for (static, counts, regdefs, flagdefs, mem, misc, uses) in res["insns"]:
        idx, pc, phys, version, parcels = static
        count, irqs, traps = counts
        text, _ = isa.disassemble(list(parcels) + [0, 0], pc, names)
        kind = isa.kind(list(parcels) + [0, 0])
        op = text.split()[0] if text and not text.startswith(".") else "illegal"
        mode = None
        if " " in kind and kind.split()[0] in ("MOV", "ST", "LEA", "ADD", "SUB", "CMP", "AND", "OR",
                                                "XOR", "JMP", "CALL"):
            mode = kind.split(" ", 1)[1]
        keys = by_insn.get(idx, [])
        hw_known = [(hw, c) for _, hw, c, _ in keys if hw is not None]
        hw_cycles = sum(hw * c for hw, c in hw_known)
        hw_unknown = sum(c for _, hw, c, _ in keys if hw is None)
        model = [sum(m[i] * c for _, _, c, m in keys) for i in range(6)]
        classes = [k[2] for k, _, _, _ in keys if k[2] != "trap"]
        cls = max(set(classes), key=classes.count) if classes else (keys[0][0][2] if keys else None)
        taken = None
        if kind in ("Bcc", "Jcc"):
            taken = sum(c for k, _, c, _ in keys
                        if (k[2] == "br" and k[3] == 1) or k[2] == "jmp")
        func, symbol, offset, file, line, source = syms.at(pc, phys)
        (n_d, z_d, c_d, v_d), (n_u, z_u, c_u, v_u) = flagdefs
        mem_n, mem_io, mem_other, mem_min, mem_max = mem
        first, mismatches, hw_illegal = misc
        reads, writes, freads, fwrites = uses
        code = (isa.NAME, pc, len(parcels), " ".join(f"{w:04X}" for w in parcels),
                text, op, kind, mode, func, symbol, offset, file, line, source,
                regs(reads), regs(writes), flags(freads), flags(fwrites), int(hw_illegal))
        out["insn"].append((
            idx, code, pc, phys, version, cls,
            count, hw_cycles, hw_unknown,
            min((h for h, _ in hw_known), default=None), max((h for h, _ in hw_known), default=None),
            *model, taken, irqs, traps,
            regdefs[0], regdefs[1], n_d, n_u, z_d, z_u, c_d, c_u, v_d, v_u,
            mem_n, mem_io, mem_other, mem_min, mem_max,
            first, mismatches))
        pcs.setdefault(pc, []).append(idx)
        insn_info[idx] = (pc, len(parcels))
        for key, hw, c, m in keys:
            n, p2, kname, col = _key_columns(key)
            out["exec"].append((idx, kname, n, p2, col["ea"], col["size"], col["x"],
                                col["wb"], col["taken"], col["how"], col["bits"], col["signed"],
                                col["steps"], col["regs"], hw, c, *m))
    kinds = {0: "next", 1: "irq", 2: "trap"}
    for src, dst_pc, kind, count in res["edges"]:
        dsts = pcs.get(dst_pc, [])
        pc, n = insn_info[src]
        out["edge"].append((src, dst_pc, dsts[0] if len(dsts) == 1 else None, kinds[kind],
                            int(dst_pc == (pc + 2 * n) & 0xFFFFFFFF), count))
    for w, r, mask, count in res["flag_pairs"]:
        out["flag_use"].append((w, r, flags(mask), count))
    for w, r, reg, count, dsum in res["reg_pairs"]:
        out["reg_use"].append((w, r, REG_NAMES[reg], count, dsum))
    for k, count in enumerate(res["dist"]):
        if count:
            out["dist"].append((1 << k, (1 << (k + 1)) - 1, count))
    for pc, calls, incl in res["funcs"]:
        func, symbol, offset, *_ = syms.at(pc)
        if symbol is None:
            name = f"{func or ''} 0x{pc:X}".strip()
        else:
            name = symbol if offset == 0 else f"{symbol}+{offset}"
        out["func"].append((pc, name, calls, *incl))
    return out


def totals(res):
    """The trace row's columns that come from the profile."""
    tot = res["totals"]
    return {
        "instructions": tot[0], "static_insns": len(res["insns"]), "hw_cycles": tot[1],
        "hw_unknown": res["hw_unknown"], **{MODEL[i]: tot[2 + i] for i in range(6)},
        "irqs": res["irqs"], "irq_hw_cycles": res["irq_hw"],
        "traps": sum(row[1][2] for row in res["insns"]),
        "mismatches": res["mismatches"], "shadow_errors": res["shadow_errors"],
        "notes": "\n".join(res["notes"]) or None,
    }


# ---------------------------------------------------------------- the database

class Database:
    def __init__(self, path=DB_PATH):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self.con = sqlite3.connect(path)
        self.con.executescript(SCHEMA)
        self._code = None

    def close(self):
        self.con.close()

    def names(self):
        return [r[0] for r in self.con.execute("SELECT name FROM trace ORDER BY id")]

    def delete(self, name):
        cur = self.con.execute("SELECT id FROM trace WHERE name = ?", (name,))
        row = cur.fetchone()
        if row:
            for t in TABLES:
                self.con.execute(f"DELETE FROM {t} WHERE trace = ?", row)
            self.con.execute("DELETE FROM trace WHERE id = ?", row)

    CODE_COLUMNS = ("isa, pc, parcels, hex, text, op, kind, mode, func, symbol, offset, file, line, "
                    "source, reads, writes, freads, fwrites, hw_illegal")
    # what makes code the same, as positions in a code row
    _KEY = (0, 1, 3, 4, 8, 9, 10, 11, 12)

    def code_id(self, code):
        """The id of a code row, added if it's new."""
        if self._code is None:
            self._code = {}
            for row in self.con.execute(f"SELECT id, {self.CODE_COLUMNS} FROM code"):
                self._code[tuple(row[1:][k] for k in self._KEY)] = row[0]
        key = tuple(code[k] for k in self._KEY)
        cid = self._code.get(key)
        if cid is None:
            qs = ", ".join("?" for _ in code)
            cid = self.con.execute(f"INSERT INTO code ({self.CODE_COLUMNS}) VALUES ({qs})", code).lastrowid
            self._code[key] = cid
        return cid

    def prune(self):
        """Forget the code no trace has any more."""
        with self.con:
            self.con.execute("DELETE FROM code WHERE id NOT IN (SELECT DISTINCT code FROM insn)")
        self._code = None

    def load(self, name):
        """A trace as store() takes it: (trace row, tables)."""
        con = self.con
        cur = con.execute("SELECT * FROM trace WHERE name = ?", (name,))
        cols = [d[0] for d in cur.description]
        row = dict(zip(cols, cur.fetchone()))
        tid = row.pop("id")
        code = {}
        for r in con.execute(f"SELECT id, {self.CODE_COLUMNS} FROM code WHERE id IN "
                             "(SELECT code FROM insn WHERE trace = ?)", (tid,)):
            code[r[0]] = tuple(r[1:])
        tables = {}
        for t in TABLES:
            rs = [r[1:] for r in con.execute(f"SELECT * FROM {t} WHERE trace = ?", (tid,))]
            if t == "insn":
                rs = [(r[0], code[r[1]], *r[2:]) for r in rs]
            tables[t] = rs
        return row, tables

    def store(self, trace, tables):
        """Replace the trace called trace["name"] with this one: `trace`
        the trace row's columns, `tables` what rows() made."""
        with self.con:
            self.delete(trace["name"])
            trace = dict(trace, collected=trace.get("collected") or
                         datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))
            cols = ", ".join(trace)
            qs = ", ".join("?" for _ in trace)
            cur = self.con.execute(f"INSERT INTO trace ({cols}) VALUES ({qs})", list(trace.values()))
            tid = cur.lastrowid
            tables = dict(tables, insn=[(r[0], self.code_id(r[1]), *r[2:]) for r in tables.get("insn", [])])
            for t in TABLES:
                rs = tables.get(t, [])
                if rs:
                    qs = ", ".join("?" for _ in range(len(rs[0]) + 1))
                    self.con.executemany(f"INSERT INTO {t} VALUES ({qs})", ((tid, *r) for r in rs))
        return tid
