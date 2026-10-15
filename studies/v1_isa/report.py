"""Draft 1 report: cycles, code size and ISA statistics for 1a vs 1b.

Runs every program in programs/v1a and programs/v1b and writes the
generated part of RFC 0004 (draft 0's numbers, for reference, come from
the v0_hw study's baseline.json).

    heron v1_isa report
"""

import math
import os
import re
from collections import Counter

from heron import ROOT
from heron.infra import isas
from heron.studies.v0_hw import baseline
from . import timing32
from .testing import program_paths, run_program

DOC = os.path.join(ROOT, "reports", "0004-rfc-draft-1-isa", "performance.md")

ISAS = ["v1a", "v1b"]
CONFIGS = timing32.CONFIG_NAMES
MAIN = "D16-overlap"        # the configuration used in the headline tables
CLOCK = 3e6                 # assumed clock for run times
REG_RE = re.compile(r"\b(r1[0-5]|r[0-9]|sp)\b")


def parcels(m, pc):
    return [m.parcel(pc + 2 * i) for i in range(3)]


def own_code(r):
    """Code bytes from the program's own file (no library code)."""
    return sum(st.size for st in r["image"].stmts
               if st.kind == "insn" and os.path.abspath(st.where[0]) == os.path.abspath(r["path"]))


def geomean(xs):
    xs = [x for x in xs if x > 0]
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else float("nan")


def collect():
    """Run everything. Returns {isa: {program: result}} plus v0 results."""
    out = {}
    for name in ISAS:
        out[name] = {}
        for p in program_paths(isa_name=name):
            r = run_program(p, name)
            out[name][r["name"]] = r
    out["v0"] = baseline.load()["programs"]
    return out


def analyse(name, results):
    """Per-ISA statistics over all programs."""
    isa = isas.get(name)
    st = {
        "kinds": Counter(), "kind_cycles": Counter(), "static_kinds": Counter(),
        "parcels_static": Counter(), "parcels_dyn": Counter(), "two_parcel": Counter(),
        "three_parcel": Counter(), "modes_dyn": Counter(), "modes_static": Counter(),
        "data_bytes": 0, "instructions": 0, "fetch_bytes": 0, "regs": {},
        "kind_share": Counter(), "kind_cyc_share": Counter(), "mode_share": Counter(), "nprogs": 0,
    }
    seen = set()
    for prog, r in results.items():
        m = r.get("machine")
        if m is None:
            continue
        st["instructions"] += m.instructions
        st["data_bytes"] += m.data_bytes
        pcc = m.pc_cycles(MAIN)
        tot_c = sum(pcc.values()) or 1
        modes_here = Counter()
        st["nprogs"] += 1
        for pc, cnt in m.pc_counts.items():
            ws = parcels(m, pc)
            k = isa.kind(ws)
            n = isa.size_of(ws[0])
            st["kinds"][k] += cnt
            st["kind_cycles"][k] += pcc[pc]
            st["kind_share"][k] += cnt / m.instructions
            st["kind_cyc_share"][k] += pcc[pc] / tot_c
            st["parcels_dyn"][n] += cnt
            st["fetch_bytes"] += 2 * n * cnt
            if name == "v1b" and (1 <= (ws[0] >> 12) <= 9 or (ws[0] >> 12) == 0xB):
                modes_here[isa.mode_class(ws)] += cnt
                st["modes_dyn"][isa.mode_class(ws)] += cnt
        tm = sum(modes_here.values())
        for k, v in modes_here.items():
            st["mode_share"][k] += v / tm
        regs = set()
        for s in r["image"].stmts:
            if s.kind != "insn":
                continue
            text, _ = isa.disassemble(s.words + [0, 0], s.addr)
            regs.update(REG_RE.findall(text.split(";")[0]))
            if s.where in seen:
                continue
            seen.add(s.where)
            ws = s.words + [0, 0]
            k = isa.kind(ws)
            st["static_kinds"][k] += 1
            st["parcels_static"][len(s.words)] += 1
            if len(s.words) == 2:
                st["two_parcel"][k] += 1
            elif len(s.words) == 3:
                st["three_parcel"][k] += 1
            if name == "v1b" and (1 <= (ws[0] >> 12) <= 9 or (ws[0] >> 12) == 0xB):
                st["modes_static"][isa.mode_class(ws)] += 1
        regs.discard("r0")
        st["regs"][prog] = len(regs)
    return st


def profile(r, n=3, config=MAIN):
    """Top routines of one program by cycles: [(name, share)]."""
    m = r["machine"]
    syms = sorted((st.addr, st.label) for st in r["image"].stmts
                  if st.kind == "label" and "." not in st.label)
    import bisect
    starts = [a for a, _ in syms]
    per = Counter()
    total = 0
    for pc, cyc in m.pc_cycles(config).items():
        total += cyc
        if pc is None:
            per["<interrupt entry>"] += cyc
            continue
        i = bisect.bisect_right(starts, pc) - 1
        per[syms[i][1] if i >= 0 else "?"] += cyc
    return [(k, v / total) for k, v in per.most_common(n)]


def autoinc_candidates(r):
    """Draft 1a: pointer steps that post-increment / pre-decrement loads and
    stores would absorb. Returns {pc of the ADDI: kind} for an ADDI of
    +size within 3 instructions after a [rB] access, or of ±size within 3
    before one (a step written first becomes a post-increment once the
    pointer starts one element earlier), with nothing in between reading or
    writing rB."""
    isa = isas.get("v1a")
    insns = [st for st in r["image"].stmts if st.kind == "insn"]
    insns.sort(key=lambda st: st.addr)
    decoded = []
    for st in insns:
        w = st.words[0]
        op, d, b, c = w >> 12, (w >> 8) & 15, (w >> 4) & 15, w & 15
        text = isa.disassemble(st.words + [0, 0], st.addr)[0]
        regs = set(REG_RE.findall(text))
        mem = None              # (base, size) for a [base + 0] access
        if op in (4, 5) and c == 0:
            mem = (b, 4)
        elif op in (6, 7) and c == 0:
            mem = (b, 1)
        elif op == 0xA and c <= 7 and st.words[1] == 0 and b:
            mem = (b, (4, 4, 1, 1, 2, 2, 1, 2)[c])
        addi = (d, (w & 0xFF) - 256 if w & 0x80 else w & 0xFF) if op == 0xD else None
        decoded.append((st.addr, mem, addi, regs))
    rn = lambda n: "sp" if n == 15 else f"r{n}"
    out = {}
    for i, (addr, mem, addi, regs) in enumerate(decoded):
        if not mem or not mem[0]:
            continue
        base, size = mem
        name = rn(base)
        for j in range(i + 1, min(i + 4, len(decoded))):            # post-increment
            a2, m2, ad2, r2 = decoded[j]
            if ad2 and ad2[0] == base and ad2[1] == size:
                out[a2] = "post"
                break
            if name in r2:
                break
        for j in range(i - 1, max(i - 4, -1), -1):                   # pre-decrement, or a step
            a2, m2, ad2, r2 = decoded[j]                            # written before the access
            if ad2 and ad2[0] == base and ad2[1] in (size, -size):
                out.setdefault(a2, "pre")
                break
            if name in r2:
                break
    return out


def whatif_autoinc(r, config):
    """(cycles, instructions, code parcels) for draft 1a with the pointer steps
    absorbed into auto-increment loads and stores (an estimate)."""
    m = r["machine"]
    cand = autoinc_candidates(r)
    saved_c = saved_i = 0
    for (pc, k), n in m.pc_keys.items():
        if pc in cand:
            saved_i += n
            saved_c += n * timing32.cycles(k, config)
    base = m.cycles_avg(config)
    own = {st.addr for st in r["image"].stmts if st.kind == "insn"
           and os.path.abspath(st.where[0]) == os.path.abspath(r["path"])}
    return base - saved_c, m.instructions - saved_i, sum(1 for a in cand if a in own)


def fmt(n):
    return f"{round(n):,}"


def pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "–"


def fmt_time(cycles):
    s = cycles / CLOCK
    if s < 1:
        return f"{s * 1e3:.1f} ms"
    return f"{s:.2f} s"


def timing_examples():
    rows = [
        ("`ADD r1, r2`", (1, 0, "alu", 1)),
        ("`CMP r1, r2`", (1, 0, "alu", 0)),
        ("`ADD r1, #1000` (2 parcels)", (2, 0, "alu", 1)),
        ("word load `[r2 + 4]`", (1, 0, "ld", "rd", 4, 0)),
        ("byte load `[r2 + 1]`", (1, 0, "ld", "rd", 1, 0)),
        ("word store `[r2 + 4]`", (1, 0, "st", "rd", 4, 0)),
        ("1b `ADD r1, [r2]` (word)", (1, 0, "op", "r", 4, 0, 1)),
        ("1b `ADD r1, byte [r2 + 8]`", (2, 0, "op", "rd", 1, 0, 1)),
        ("1b `MOV r1, [r2]+`", (1, 0, "ld", "pi", 4, 0)),
        ("branch taken", (1, 0, "br", 1, 0)),
        ("branch not taken", (1, 0, "br", 0, 0)),
        ("`CALL` (2 parcels)", (2, 0, "call", "rel", 0)),
        ("`RET`", (1, 0, "ret")),
        ("`SAVE` of 4 registers", (1, 0, "save", 4)),
        ("`MULU`, 16-bit multiplier", (1, 0, "mul", 16, 0)),
        ("`DIVU`", (1, 0, "div", 0)),
    ]
    L = ["| Instruction | " + " | ".join(CONFIGS) + " |",
         "|---|" + "---:|" * len(CONFIGS)]
    for label, k in rows:
        L.append(f"| {label} | " + " | ".join(str(timing32.cycles(k, c)) for c in CONFIGS) + " |")
    return L


def report(data):
    L = []
    a, b, v0 = data["v1a"], data["v1b"], data["v0"]
    progs = sorted(set(a) | set(b))
    L.append("# Draft 1 performance: 1a (load/store) vs 1b (register + addressing mode)")
    L.append("")
    L.append("Generated by `heron v1_isa report`; don't edit by hand. Cycle counts come from "
             "the timing model in [timing-model-v1.md](../../studies/v1_isa/timing-model-v1.md), applied to every "
             f"executed instruction of every program. Run times assume a {CLOCK / 1e6:g} MHz clock "
             "for every configuration.")
    L.append("")
    status = []
    for name, res in (("1a", a), ("1b", b)):
        bad = [p for p, r in res.items() if not r["ok"]]
        status.append(f"{name}: {len(res) - len(bad)}/{len(res)} programs pass" +
                      (f" (failing: {', '.join(bad)})" if bad else ""))
    L.append("Test status: " + "; ".join(status) + ".")
    L.append("")

    # ---- headline ----
    L.append("## Whole suite")
    L.append("")
    common = [p for p in progs if p in a and p in b and a[p]["ok"] and b[p]["ok"]]
    big = max(common, key=lambda p: a[p]["machine"].cycles_avg(MAIN))
    share = a[big]["machine"].cycles_avg(MAIN) / sum(a[p]["machine"].cycles_avg(MAIN) for p in common)
    L.append(f"Over the {len(common)} programs that pass on both. The headline figure is the geometric "
             f"mean of the per-program ratios, so every program counts equally: `{big}` alone is "
             f"{100 * share:.0f}% of 1a's cycles and would dominate a plain total.")
    L.append("")
    L.append(f"| Configuration | geometric mean 1b / 1a | total 1a cycles | total 1b cycles | 1b / 1a | "
             f"1b / 1a without {big} | 1a CPI | 1b CPI |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    ia = sum(a[p]["instructions"] for p in common)
    ib = sum(b[p]["instructions"] for p in common)
    cyc = {}
    for c in CONFIGS:
        ca = sum(a[p]["machine"].cycles_avg(c) for p in common)
        cb = sum(b[p]["machine"].cycles_avg(c) for p in common)
        xa = ca - a[big]["machine"].cycles_avg(c)
        xb = cb - b[big]["machine"].cycles_avg(c)
        cyc[c] = (ca, cb)
        g = geomean([b[p]["machine"].cycles_avg(c) / a[p]["machine"].cycles_avg(c) for p in common])
        L.append(f"| {c} | **{g:.3f}** | {fmt(ca)} | {fmt(cb)} | {cb / ca:.3f} | {xb / xa:.3f} | "
                 f"{ca / ia:.2f} | {cb / ib:.2f} |")
    L.append("")
    gi = geomean([b[p]["instructions"] / a[p]["instructions"] for p in common])
    go = geomean([own_code(b[p]) / own_code(a[p]) for p in common if own_code(a[p])])
    L.append(f"Geometric means of 1b / 1a: instructions executed {gi:.3f}, program code size "
             f"(own code, without libraries) {go:.3f}.")
    L.append("")
    ba = sum(a[p]["code_bytes"] for p in common)
    bb = sum(b[p]["code_bytes"] for p in common)
    L.append(f"Instructions executed: 1a {fmt(ia)}, 1b {fmt(ib)} (1b / 1a = {ib / ia:.3f}). "
             f"Code size, summed over programs (library code counted in each program that includes it): "
             f"1a {fmt(ba)} bytes, 1b {fmt(bb)} bytes (1b / 1a = {bb / ba:.3f}).")
    L.append("")
    # speed-up from datapath and fetch
    L.append("The wide fetch reads aligned 32-bit words, so its cycle counts depend on where loops "
             "fall: shifting a program's code by one parcel changes them. All wide-fetch numbers in "
             "this report are the average of the two alignments. The spread between them:")
    L.append("")
    L.append("| Program | 1a D16-wide | 1b D16-wide | 1a D32-wide | 1b D32-wide |")
    L.append("|---|---:|---:|---:|---:|")
    spread = []
    for p in common:
        cells = []
        big_cell = 0
        for c in ("D16-wide", "D32-wide"):
            for res in (a, b):
                m = res[p]["machine"]
                x, y = m.cycles_for(c), m.cycles_for(c, True)
                d = abs(x - y) / min(x, y)
                big_cell = max(big_cell, d)
                cells.append((c, res is b, d))
        spread.append((big_cell, p, cells))
    spread.sort(reverse=True)
    for big_cell, p, cells in spread[:6]:
        order = {("D16-wide", False): 0, ("D16-wide", True): 1, ("D32-wide", False): 2, ("D32-wide", True): 3}
        vals = [""] * 4
        for c, isb, d in cells:
            vals[order[(c, isb)]] = f"{100 * d:.1f}%"
        L.append(f"| {p} | " + " | ".join(vals) + " |")
    L.append("")
    L.append("(The six programs with the largest spread; the rest are smaller.)")
    L.append("")
    L.append("Effect of the hardware choices: cycles relative to D16-separate of the same ISA "
             "(geometric mean over programs).")
    L.append("")
    L.append("| ISA | " + " | ".join(CONFIGS) + " |")
    L.append("|---|" + "---:|" * len(CONFIGS))
    for name, res in (("1a", a), ("1b", b)):
        L.append(f"| {name} | " + " | ".join(
            f"{geomean([res[p]['machine'].cycles_avg(c) / res[p]['machine'].cycles_avg('D16-separate') for p in common]):.2f}"
            for c in CONFIGS) + " |")
    L.append("")

    # ---- per program ----
    L.append("## Per program")
    L.append("")
    L.append("Cycles count executed instructions only: time `interrupts` spends asleep in `HALT` "
             "waiting for timer ticks isn't included.")
    L.append("")
    L.append(f"Instructions, code size, and cycles in the {MAIN} and D32-wide configurations "
             f"(the cheapest and the most capable that overlap fetches), with run time at {CLOCK / 1e6:g} MHz.")
    L.append("")
    L.append("Code bytes are the program's own code; the libraries it includes are extra.")
    L.append("")
    L.append("| Program | 1a instr | 1b instr | 1a code B | 1b code B | 1a cycles " + MAIN +
             " | 1b cycles " + MAIN + " | 1b/1a | 1a D32-wide | 1b D32-wide | 1b/1a | 1a time | 1b time |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for p in progs:
        ra, rb = a.get(p), b.get(p)
        if not ra or not rb or not ra["ok"] or not rb["ok"]:
            L.append(f"| {p} | " + ("ok" if ra and ra["ok"] else "fail") + " | " +
                     ("ok" if rb and rb["ok"] else "fail") + " |" + " |" * 11)
            continue
        ma, mb = ra["machine"], rb["machine"]
        c1a, c1b = ma.cycles_avg(MAIN), mb.cycles_avg(MAIN)
        w1a, w1b = ma.cycles_avg("D32-wide"), mb.cycles_avg("D32-wide")
        L.append(f"| {p} | {fmt(ra['instructions'])} | {fmt(rb['instructions'])} | {own_code(ra)} | "
                 f"{own_code(rb)} | {fmt(c1a)} | {fmt(c1b)} | {c1b / c1a:.2f} | {fmt(w1a)} | "
                 f"{fmt(w1b)} | {w1b / w1a:.2f} | {fmt_time(c1a)} | {fmt_time(c1b)} |")
    L.append("")
    for name, res in (("1a", a), ("1b", b)):
        L.append(f"<details><summary>All six configurations, draft {name}</summary>")
        L.append("")
        L.append("| Program | " + " | ".join(CONFIGS) + " |")
        L.append("|---|" + "---:|" * len(CONFIGS))
        for p in progs:
            r = res.get(p)
            if not r or not r["ok"]:
                continue
            m = r["machine"]
            L.append(f"| {p} | " + " | ".join(fmt(m.cycles_avg(c)) for c in CONFIGS) + " |")
        L.append("")
        L.append("</details>")
        L.append("")

    # ---- what-if: 1a with auto-increment ----
    L.append("## What if 1a had auto-increment?")
    L.append("")
    L.append("1a's op F is unused, enough for post-increment and pre-decrement loads and stores "
             "(`LDB r1, [r2]+`, `ST r1, -[sp]`). This estimate removes every `ADDI rB, ±size` that "
             "steps the base register of an adjacent `[rB]` load or store (within three instructions, "
             "nothing else touching rB in between) and charges the access the same cycles, as the model "
             "does for 1b. It's rough, and probably low: 1a code is often shaped around the short "
             "offsets instead (the VM reads operands at `[r8 + 1]`, `[r8 + 2]` and steps r8 once per "
             "instruction), and only a rewrite would show what auto-increment does there.")
    L.append("")
    L.append("| Program | ADDIs absorbed (executed) | 1a+inc / 1a, D16-overlap | 1b / 1a, D16-overlap | "
             "1a+inc / 1a, D32-wide | 1b / 1a, D32-wide |")
    L.append("|---|---:|---:|---:|---:|---:|")
    gi = {"a16": [], "b16": [], "a32": [], "b32": []}
    for p in progs:
        if p not in common:
            continue
        ma, mb = a[p]["machine"], b[p]["machine"]
        c16, i16, _ = whatif_autoinc(a[p], MAIN)
        c32, _, _ = whatif_autoinc(a[p], "D32-wide")
        base16, base32 = ma.cycles_avg(MAIN), ma.cycles_avg("D32-wide")
        x = {"a16": c16 / base16, "b16": mb.cycles_avg(MAIN) / base16,
             "a32": c32 / base32, "b32": mb.cycles_avg("D32-wide") / base32}
        for k in gi:
            gi[k].append(x[k])
        L.append(f"| {p} | {fmt(ma.instructions - i16)} | {x['a16']:.2f} | {x['b16']:.2f} | "
                 f"{x['a32']:.2f} | {x['b32']:.2f} |")
    L.append(f"| **geometric mean** | | **{geomean(gi['a16']):.3f}** | **{geomean(gi['b16']):.3f}** | "
             f"**{geomean(gi['a32']):.3f}** | **{geomean(gi['b32']):.3f}** |")
    L.append("")

    # ---- against draft 0 ----
    L.append("## Against draft 0")
    L.append("")
    L.append("Draft 0's cycles are exact (from its microcode); draft 1's are from the model. "
             "D16-overlap is draft 0's own organisation with a 32-bit register file; "
             "programs where the work differs (16-bit vs 32-bit arithmetic) still produce identical output.")
    L.append("")
    L.append("Speed-up over draft 0 (draft 0 cycles divided by draft 1 cycles; above 1 is faster). "
             "Code size is the program's own code plus the library routines it includes, for all three.")
    L.append("")
    L.append("| Program | v0 instr | v0 cycles | v0 code B | 1a code B | 1b code B | 1a D16-overlap | 1b D16-overlap | 1a D32-overlap | 1b D32-overlap |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    sp = {k: [] for k in ("a16", "b16", "a32", "b32")}
    for p in progs:
        r0 = v0.get(p)
        if not r0 or not r0["ok"] or p not in common:
            continue
        ma, mb = a[p]["machine"], b[p]["machine"]
        x = {"a16": r0["cycles"] / ma.cycles_avg(MAIN), "b16": r0["cycles"] / mb.cycles_avg(MAIN),
             "a32": r0["cycles"] / ma.cycles_avg("D32-overlap"), "b32": r0["cycles"] / mb.cycles_avg("D32-overlap")}
        for k in sp:
            sp[k].append(x[k])
        L.append(f"| {p} | {fmt(r0['instructions'])} | {fmt(r0['cycles'])} | {r0['code_bytes']} | "
                 f"{a[p]['code_bytes']} | {b[p]['code_bytes']} | " +
                 " | ".join(f"{x[k]:.2f}×" for k in ("a16", "b16", "a32", "b32")) + " |")
    if sp["a16"]:
        L.append("| **geometric mean** | | | | | | " +
                 " | ".join(f"**{geomean(sp[k]):.2f}×**" for k in ("a16", "b16", "a32", "b32")) + " |")
    L.append("")

    # ---- static code ----
    sa, sb = analyse("v1a", a), analyse("v1b", b)
    L.append("## Code size and instruction length")
    L.append("")
    L.append("Static counts take each source line once (library code counts once, not once per program).")
    L.append("")
    L.append("| | 1a | 1b |")
    L.append("|---|---:|---:|")
    na, nb = sum(sa["parcels_static"].values()), sum(sb["parcels_static"].values())
    L.append(f"| instructions in the source | {fmt(na)} | {fmt(nb)} |")
    pa = sum(k * v for k, v in sa["parcels_static"].items())
    pb = sum(k * v for k, v in sb["parcels_static"].items())
    L.append(f"| code bytes | {fmt(2 * pa)} | {fmt(2 * pb)} |")
    L.append(f"| bytes per instruction | {2 * pa / na:.2f} | {2 * pb / nb:.2f} |")
    for n in (1, 2, 3):
        L.append(f"| {n}-parcel instructions | {pct(sa['parcels_static'][n], na)} | {pct(sb['parcels_static'][n], nb)} |")
    da, db = sum(sa["parcels_dyn"].values()), sum(sb["parcels_dyn"].values())
    L.append(f"| executed: parcels per instruction | {sum(k * v for k, v in sa['parcels_dyn'].items()) / da:.2f} | "
             f"{sum(k * v for k, v in sb['parcels_dyn'].items()) / db:.2f} |")
    L.append(f"| executed: instruction bytes fetched | {fmt(sa['fetch_bytes'])} | {fmt(sb['fetch_bytes'])} |")
    L.append(f"| executed: data bytes loaded or stored | {fmt(sa['data_bytes'])} | {fmt(sb['data_bytes'])} |")
    L.append("")
    for name, s in (("1a", sa), ("1b", sb)):
        L.append(f"Most common multi-parcel forms in draft {name}: " +
                 ", ".join(f"`{k}` {v}" for k, v in (s["two_parcel"] + s["three_parcel"]).most_common(8)) + ".")
        L.append("")

    # ---- instruction mix ----
    L.append("## Instruction mix")
    L.append("")
    L.append(f"Share of executed instructions and of {MAIN} cycles, averaged over the programs so each "
             "counts equally (pooling would let `vm`, half of all instructions, decide the table). "
             "Top 25 per ISA.")
    L.append("")
    ka = sa["kind_share"].most_common(25)
    kb = sb["kind_share"].most_common(25)
    na, nb = sa["nprogs"], sb["nprogs"]
    L.append("| 1a instruction | instr | cycles | 1b instruction | instr | cycles |")
    L.append("|---|---:|---:|---|---:|---:|")
    for i in range(max(len(ka), len(kb))):
        x = ka[i] if i < len(ka) else ("", 0)
        y = kb[i] if i < len(kb) else ("", 0)
        L.append(f"| `{x[0]}` | {pct(x[1], na)} | {pct(sa['kind_cyc_share'][x[0]], na)} | "
                 f"`{y[0]}` | {pct(y[1], nb)} | {pct(sb['kind_cyc_share'][y[0]], nb)} |")
    L.append("")
    L.append("Where the time goes: the top routines of each program by cycles.")
    L.append("")
    L.append("| Program | 1a | 1b |")
    L.append("|---|---|---|")
    for p in progs:
        if p in common:
            pa = ", ".join(f"`{k}` {100 * v:.0f}%" for k, v in profile(a[p]))
            pb = ", ".join(f"`{k}` {100 * v:.0f}%" for k, v in profile(b[p]))
            L.append(f"| {p} | {pa} | {pb} |")
    L.append("")

    # ---- 1b modes ----
    L.append("## Draft 1b: addressing modes")
    L.append("")
    L.append("Operand modes of the instructions that take one (`MOV ST LEA ADD SUB CMP AND OR XOR JMP CALL`). "
             "`b`/`h` mark byte and half operands; `#q` is a constant in the instruction (−16…15).")
    L.append("")
    md, ms = sb["mode_share"], sb["modes_static"]
    tsm = sum(ms.values())
    L.append("| Mode | executed (average over programs) | in the source |")
    L.append("|---|---:|---:|")
    for k, v in md.most_common():
        L.append(f"| `{k}` | {pct(v, sb['nprogs'])} | {pct(ms[k], tsm)} |")
    L.append("")
    alu = ("ADD", "SUB", "CMP", "AND", "OR", "XOR")
    alu_mem = sum(v for k, v in sb["kind_share"].items() if k.split()[0] in alu and "[" in k)
    alu_all = sum(v for k, v in sb["kind_share"].items() if k.split()[0] in alu)
    L.append(f"ALU instructions with a memory operand (average over programs): {pct(alu_mem, alu_all)} of "
             f"executed `ADD SUB CMP AND OR XOR`, {pct(alu_mem, sb['nprogs'])} of all executed instructions.")
    L.append("")

    # ---- registers ----
    L.append("## Registers used")
    L.append("")
    L.append("Distinct registers named in each program, including library code (out of 15 usable).")
    L.append("")
    L.append("| Program | 1a | 1b |")
    L.append("|---|---:|---:|")
    for p in progs:
        if p in sa["regs"] and p in sb["regs"]:
            L.append(f"| {p} | {sa['regs'][p]} | {sb['regs'][p]} |")
    L.append("")

    L.append("## Timing model examples")
    L.append("")
    L += timing_examples()
    L.append("")
    return "\n".join(L) + "\n"


def main(argv=None):
    data = collect()
    text = report(data)
    path = DOC
    with open(path, "w") as f:
        f.write(text)
    print(f"wrote {path}")
    for name in ISAS:
        for p, r in sorted(data[name].items()):
            if not r["ok"]:
                print(f"  {name} {p}: {r['error']}")
    return 0
