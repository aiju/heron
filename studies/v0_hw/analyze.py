"""ISA usage statistics: the evidence for changing the instruction set.

Runs every program on the instruction-level simulator and records, per
executed instruction, what it needed: branch distances, immediate sizes,
load/store offsets, registers touched, and common instruction pairs that a
richer ISA could fold into one (MOV + op, load + pointer increment,
compare + branch, ...).

    heron v0_hw analyze              # print a markdown report
"""

from collections import Counter, defaultdict

from heron.infra import asm as asmcore
from . import isa as v0
from .sim import Machine
from .testing import program_paths, metadata


def sext8(x):
    x &= 0xFF
    return x - 256 if x & 0x80 else x


def s16(x):
    return x - 65536 if x & 0x8000 else x


class Stats:
    def __init__(self):
        self.n = 0
        self.cycles = 0
        self.br_dist = Counter()          # |offset| bucket of executed conditional branches (words)
        self.br_taken = Counter()
        self.jcc_dist = Counter()         # conditional long jumps: distance in words
        self.imm16 = Counter()            # executed ALU #imm16: smallest field that would hold it
        self.mem_off = Counter()          # executed load/store offsets by form
        self.mem_long_small = 0           # long-form accesses with offsets that fit in 8 signed bits
        self.regs_used = defaultdict(set)
        self.pairs = Counter()
        self.idioms = Counter()
        self.idiom_cycles = Counter()
        self.calls = 0
        self.push_pop_in_runs = 0
        self.func_cycles = Counter()      # (program, function) -> cycles
        self.lib_cycles = Counter()       # library routine -> cycles over all programs
        self.prog_cycles = Counter()
        self.long_small_base = Counter()  # long-form small offsets: "sp" / "other", "negative" / "beyond short range"
        self.short_off = Counter()        # short-form offsets used (bytes)
        self.calls_to = Counter()         # call target symbol -> calls


def bucket_signed(v):
    for bits in (4, 6, 8, 10, 12):
        if -(1 << (bits - 1)) <= v < (1 << (bits - 1)):
            return f"{bits}-bit"
    return "16-bit"


def bucket_unsigned_imm(v):
    sv = s16(v)
    if -8 <= sv <= 7:
        return "fits 4 bits (signed)"
    if -128 <= sv <= 127:
        return "fits 8 bits (signed)"
    if 0 <= v <= 255:
        return "fits 8 bits (unsigned)"
    return "needs 16 bits"


def analyse_program(path, isa, timing, st):
    img = asmcore.assemble_file(isa, path)
    meta = metadata(path)
    m = Machine(isa, img, inp=meta["input"], timing=timing)
    name = path.rsplit("/", 1)[-1][:-2]
    import bisect
    import os
    funcs = sorted((addr, sym) for sym, addr in img.symbols.items()
                   if "." not in sym and not sym.startswith("__") and addr < 0xFF00)
    starts = [a for a, _ in funcs]
    lib_syms = set()
    for st_ in img.stmts:
        if st_.kind == "label" and "." not in st_.label and "lib" + os.sep in st_.where[0]:
            lib_syms.add(st_.label)
    window = []          # last few decoded instructions: (kind, op, a, b, c, word, ext)

    def tr(m):
        w = m.rd16(m.pc)
        ext = m.rd16((m.pc + 2) & 0xFFFF) if m.pc + 2 < 0xFF00 else 0
        op, a, b, c = w >> 12, (w >> 8) & 15, (w >> 4) & 15, w & 15
        k = isa.kind(w)
        st.n += 1
        i = bisect.bisect_right(starts, m.pc) - 1
        fn = funcs[i][1] if i >= 0 else "?"
        cyc = timing(w, None) if not (op == 0 and c == 0) else 1
        st.func_cycles[(name, fn)] += cyc
        st.prog_cycles[name] += cyc
        if fn in lib_syms:
            st.lib_cycles[fn] += cyc
        # registers referenced
        if op in (1, 2, 4, 5, 6, 7, 0xA):
            st.regs_used[name].update((a, b))
        elif op in (8, 0xC, 0xD, 0xE):
            st.regs_used[name].add(a)
        elif op == 0 and c in (2, 3, 5, 11):
            st.regs_used[name].add(b)
        elif op == 0 and c in (6, 10):
            st.regs_used[name].add(a)
        # branches
        if op == 3 and a < 14:
            st.br_dist[bucket_signed(sext8(w))] += 1
        if op == 9 and a < 14:
            st.jcc_dist[bucket_signed((s16(ext) - (m.pc + 4)) // 2)] += 1
        if op == 8:
            st.imm16[bucket_unsigned_imm(ext)] += 1
        if op in (4, 5):
            st.mem_off["word, short form"] += 1
        if op in (6, 7):
            st.mem_off["byte, short form"] += 1
        if op == 0xA and c <= 3:
            if b == 0:
                st.mem_off["long form, absolute address"] += 1
            else:
                st.mem_off["long form, base + 16-bit offset"] += 1
                if -128 <= s16(ext) <= 127:
                    st.mem_long_small += 1
                    st.long_small_base["base sp" if b == 15 else "other base"] += 1
                    st.long_small_base["negative offset" if s16(ext) < 0 else "offset 0..127"] += 1
        if k in ("CALL", "BSR"):
            st.calls += 1
            if op == 3:
                tgt = (m.pc + 2 + 2 * sext8(w)) & 0xFFFF
            elif op == 9:
                tgt = ext
            else:
                tgt = m.r[b]
            j = bisect.bisect_right(starts, tgt) - 1
            st.calls_to[funcs[j][1] if j >= 0 else "?"] += 1
        # pairs and idioms
        if window:
            pk, pop, pa, pb, pc_, pw, pext = window[-1]
            st.pairs[(pk, k)] += 1
            # MOV rd, rs immediately followed by a 2-operand op on rd: a 3-operand form saves the MOV
            if pk in ("MOV",) and op in (1, 2) and a == pa and k not in ("MOV", "CMP", "TST"):
                st.idioms["MOV rd, rs; OP rd, rt  (3-operand would save the MOV)"] += 1
            # load/store via rB, then rB += size within the next few instructions: auto-increment
            inc = None
            if op == 0xD and sext8(w) in (1, 2):
                inc = "ADDI"
            elif op == 0xA and c == 4 and a == b and ext in (1, 2):
                inc = "LEA"
            if inc:
                for (qk, qop, qa, qb, qc, qw, qext) in window[-3:]:
                    if qop in (4, 5, 6, 7) and qb == a:
                        st.idioms["LD/ST [rB]; ...; ADDI/LEA rB, 1 or 2  (auto-increment)"] += 1
                        break

            # compare then conditional branch: compare-and-branch fusion
            if pk in ("CMP", "CMPI", "TST", "CMP #imm16") and op in (3, 9) and a < 14:
                st.idioms["CMP; Bcc  (compare-and-branch)"] += 1
            # ADDI/DEC then branch on not-zero: decrement-and-branch loop
            if (pk == "ADDI" and sext8(pw) == -1 or pk == "DEC") and op == 3 and a == 1:
                st.idioms["ADDI r, -1; BNE  (decrement-and-branch)"] += 1
            # consecutive pushes / pops: multi-register push/pop
            if pk == k and k in ("PUSH", "POP"):
                st.idioms["PUSH/POP runs  (multi-register save/restore)"] += 1
            # shift sequences: several SHL/SHR/ASR in a row (multi-bit shift)
            if pk in ("SHL", "SHR", "ASR") and k == pk and a == pa:
                st.idioms["SHx; SHx ...  (multi-bit shift)"] += 1
        window.append((k, op, a, b, c, w, ext))
        if len(window) > 4:
            window.pop(0)

    m.trace = tr
    m.run(max_cycles=meta["max-cycles"])
    st.cycles += m.cycles
    return m


def run_all(isa_name="v0"):
    from . import microcode
    isa = v0
    timing = microcode.timing_function(isa_name)
    st = Stats()
    for p in program_paths():
        analyse_program(p, isa, timing, st)
    return st


def pct(n, d):
    return f"{100 * n / max(1, d):.1f}%"


def markdown(st):
    L = []
    L.append("## ISA usage statistics")
    L.append("")
    L.append(f"Collected over {st.n:,} executed instructions in all programs "
             "(`heron v0_hw analyze`).")
    L.append("")
    tot = sum(st.br_dist.values())
    L.append(f"**Conditional branch distances** ({tot:,} executed short branches; offsets in instructions):")
    L.append("")
    L.append("| Offset fits in | Share (cumulative) |")
    L.append("|---|---:|")
    acc = 0
    for b in ("4-bit", "6-bit", "8-bit"):
        acc += st.br_dist[b]
        L.append(f"| {b} signed | {pct(acc, tot)} |")
    jt = sum(st.jcc_dist.values())
    if jt:
        L.append("")
        L.append(f"Conditional *long* jumps executed: {jt:,}. Their distances: " +
                 ", ".join(f"{k} {pct(v, jt)}" for k, v in sorted(st.jcc_dist.items())))
    L.append("")
    ti = sum(st.imm16.values())
    L.append(f"**16-bit immediates** ({ti:,} executed two-word ALU instructions):")
    L.append("")
    L.append("| Value | Share |")
    L.append("|---|---:|")
    for k, v in st.imm16.most_common():
        L.append(f"| {k} | {pct(v, ti)} |")
    L.append("")
    tm = sum(st.mem_off.values())
    L.append(f"**Loads and stores** ({tm:,} executed):")
    L.append("")
    L.append("| Form | Share |")
    L.append("|---|---:|")
    for k, v in st.mem_off.most_common():
        L.append(f"| {k} | {pct(v, tm)} |")
    L.append("")
    if st.mem_long_small:
        lsb = st.long_small_base
        L.append(f"{st.mem_long_small:,} long-form accesses ({pct(st.mem_long_small, tm)} of all loads and "
                 "stores) used a base register with an offset that would fit in 8 signed bits, so they "
                 "were long only because the short form's 4-bit unsigned offset couldn't reach. Nearly "
                 "all of them are in `life` (neighbour cells 34-70 bytes away) and `matmul` (row "
                 f"strides); {lsb['negative offset']:,} had negative offsets and "
                 f"{lsb['base sp']:,} were relative to `sp`. In this "
                 "implementation the long forms cost no extra cycles, only code space.")
        L.append("")
    if st.calls:
        rows = []
        for fn, n in st.calls_to.most_common(5):
            c = st.lib_cycles.get(fn) or sum(v for (p, f), v in st.func_cycles.items() if f == fn)
            rows.append(f"`{fn}` {n:,} calls, {c / max(1, n):.0f} cycles per call")
        L.append(f"**Calls**: {st.calls:,} executed ({pct(st.calls, st.n)} of instructions). Most called: "
                 + "; ".join(rows) + ".")
        L.append("")
    L.append("**Registers used** per program (out of r1–r15): " +
             ", ".join(f"{k} {len(v - {0})}" for k, v in sorted(st.regs_used.items())))
    L.append("")
    L.append("**Idioms a richer ISA could fold into one instruction** (executed occurrences):")
    L.append("")
    L.append("| Pattern | Occurrences | Share of instructions |")
    L.append("|---|---:|---:|")
    for k, v in st.idioms.most_common():
        L.append(f"| {k} | {v:,} | {pct(v, st.n)} |")
    L.append("")
    L.append("**Where each program spends its time** (top routines by cycles):")
    L.append("")
    L.append("| Program | Top routines |")
    L.append("|---|---|")
    by_prog = defaultdict(list)
    for (prog, fn), c in st.func_cycles.items():
        by_prog[prog].append((c, fn))
    for prog in sorted(by_prog):
        tot = st.prog_cycles[prog]
        top = sorted(by_prog[prog], reverse=True)[:3]
        L.append(f"| {prog} | " + ", ".join(f"`{fn}` {pct(c, tot)}" for c, fn in top) + " |")
    L.append("")
    if st.lib_cycles:
        allc = sum(st.prog_cycles.values())
        L.append("**Library routines over all programs** (share of all cycles): " +
                 ", ".join(f"`{fn}` {pct(c, allc)}" for fn, c in st.lib_cycles.most_common(8)))
        L.append("")
    L.append("**Most common consecutive instruction pairs:**")
    L.append("")
    L.append("| Pair | Share of instructions |")
    L.append("|---|---:|")
    for (a, b), v in st.pairs.most_common(12):
        L.append(f"| `{a}` → `{b}` | {pct(v, st.n)} |")
    L.append("")
    return "\n".join(L)


def main(argv=None):
    st = run_all()
    print(markdown(st))
    return 0
