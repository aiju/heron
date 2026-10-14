"""Quick reference cards for drafts 1a and 1b, two A4 pages each.

    heron v1_isa refcard    # build/refcard/refcard-v1a.pdf and refcard-v1b.pdf

A card is an HTML page, written next to the PDF, that headless Chromium
prints (set CHROME if it can't find one). The fonts are Inter and JetBrains
Mono where they're installed. The examples on page 2 go through the assembler, so the
encodings printed next to them are the assembler's. Everything else follows
isa-v1.md, isa-v1a.md and isa-v1b.md: change it here when they change.
"""

import glob
import html
import os
import re
import shutil
import subprocess
import sys

from heron import BUILD
from heron.infra import asm, isas
from .v1common import ALU_FN, COND, SHIFT_FN, UN_FN

OUT = os.path.join(BUILD, "refcard")
TITLES = {"v1a": "load/store", "v1b": "register + addressing mode"}


def t(s):
    """Text with `code` spans, escaped for HTML."""
    parts = s.split("`")
    return "".join(f"<code>{html.escape(p)}</code>" if i % 2 else html.escape(p)
                   for i, p in enumerate(parts))


def flags(which, note=""):
    """The four arithmetic flags, the ones an instruction sets in bold."""
    if which == "-":
        out = '<span class="fl none">unchanged</span>'
    elif which == "f":
        out = '<span class="fl none">by function</span>'
    else:
        out = '<span class="fl">' + "".join(
            f'<i class="{"on" if c in which else "off"}">{c}</i>' for c in "NZCV") + "</span>"
    if note:
        out += f' <span class="note">{t(note)}</span>'
    return out


def fmt(fields, group, ext=""):
    """A first parcel as its four hex digits ("1 d s f", or "3 c ii" with a
    two-digit field), and its extension parcels."""
    if fields == "-":
        return '<span class="muted">—</span>'
    cells = []
    for i, f in enumerate(fields.split()):
        cls = "n" + (" opn" if i == 0 else "") + (" w2" if len(f) == 2 else "")
        cells.append(f'<span class="{cls}">{html.escape(f)}</span>')
    if ext:
        cells.append(f'<span class="x">+ {html.escape(ext)}</span>')
    return f'<span class="fmt g-{group}">{"".join(cells)}</span>'


def section(title, body, sub=""):
    sub = f' <span class="sub">{t(sub)}</span>' if sub else ""
    return f'<section><h2>{html.escape(title)}{sub}</h2>{body}</section>'


def table(rows, head=None, cls=""):
    out = [f'<table class="{cls}">']
    if head:
        out.append("<thead><tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr></thead>")
    out.append("<tbody>")
    for r in rows:
        if isinstance(r, str):
            out.append(r)
        else:
            out.append("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def bullets(items):
    return '<ul>' + "".join(f"<li>{t(i)}</li>" for i in items) + "</ul>"


def hexd(n):
    return f'<span class="hex">{n:X}</span>'


def mn(s):
    return f'<code class="mn">{html.escape(s)}</code>'


# ---------------------------------------------------------------------------
# Page 1: the machine and the encodings


def header(isa):
    v = isa[1:]
    return f"""
<header class="top">
  <div class="brand">
    <div class="kicker">Heron · draft 1 instruction set · quick reference</div>
    <h1>Draft <span class="v">{v}</span><span class="what">{TITLES[isa]}</span></h1>
  </div>
  <div class="facts">
    <div><b>32-bit</b> registers, addresses and ALU</div>
    <div><b>16-bit</b> parcels, 0–2 extension parcels</div>
    <div><b>little-endian</b>, byte-addressed</div>
  </div>
</header>"""


def machine():
    regs = []
    for i in range(16):
        cls = "zero" if i == 0 else "tmp" if i <= 7 else "sav" if i <= 14 else "sp"
        sub = {0: "= 0", 15: "sp"}.get(i, "")
        regs.append(f'<div class="r {cls}">r{i}<small>{sub}</small></div>')
    labels = [(1, 1, "always 0"), (2, 7, "scratch: arguments r1–r4, results r1, r2"),
              (9, 7, "callee-saved"), (16, 1, "stack")]
    for col, span, text in labels:
        regs.append(f'<div class="lab" style="grid-column:{col} / span {span}">{text}</div>')
    fw = "".join(f'<div class="b"><small>{4 - i}</small>{c}</div>' for i, c in enumerate("INZCV"))
    return f"""
<section class="machine">
  <div class="regs">{"".join(regs)}</div>
  <div class="special">
    <div class="sr"><b>PC</b><span>32 bits, even</span></div>
    <div class="sr"><b>HI</b><span>multiply high word, divide remainder</span></div>
    <div class="sr fw"><b>flags</b><div class="bits">{fw}</div></div>
  </div>
</section>"""


def opmap(rows):
    out = []
    for op, fields, ext, n, group, insns, operation, fl in rows:
        out.append(f'<tr class="g-{group}"><td><span class="op">{op}</span></td>'
                   f'<td>{fmt(fields, group, ext)}</td><td class="c">{n}</td>'
                   f'<td>{t(insns)}</td><td>{t(operation)}</td><td>{flags(fl)}</td></tr>')
    body = table(out, ["op", "first parcel", "parcels", "instructions", "operation", "flags"], "opmap")
    body += ('<p class="foot">' + t("Extension parcels follow the first, 16 bits each; a 32-bit "
                                    "value takes two, low half first. PC-relative targets and "
                                    "addresses count from the next instruction.") + "</p>")
    return section("Opcodes", body, "the first hex digit of the first parcel")


OPMAP_V1A = [
    ("0", "0 a b f", "", "1", "sys", "system group: `HALT`, `JMP rs`, `SAVE`, `RTI` …", "f picks it", "f"),
    ("1", "1 d s f", "", "1", "alu", "`ADD` … `DIVUL rd, rs`", "`rd ← rd ⊕ rs`: ALU function f", "f"),
    ("2", "2 d s f", "", "1", "bit", "`NOT` … `CLZ rd, rs`", "`rd ← f(rs)`: unary group", "f"),
    ("3", "3 c ii", "", "1", "br", "`Bcc label`; c = E `BRA`, F `BSR`", "`PC ← PC + 2·simm8`", "-"),
    ("4", "4 d s o", "", "1", "mem", "`LD rd, [rs + 4·o]`", "load a word, offset 0–60", "NZ"),
    ("5", "5 d s o", "", "1", "mem", "`ST rd, [rs + 4·o]`", "store a word, offset 0–60", "-"),
    ("6", "6 d s o", "", "1", "mem", "`LDB rd, [rs + o]`", "load a byte, zero-extended, offset 0–15", "NZ"),
    ("7", "7 d s o", "", "1", "mem", "`STB rd, [rs + o]`", "store a byte, offset 0–15", "-"),
    ("8", "8 d k f", "imm", "2–3", "alu", "`ADD` … `DIVUL rd, #imm`", "`rd ← rd ⊕ imm`: k picks the immediate", "f"),
    ("9", "9 c k 0", "target", "2–3", "br", "`Jcc label`; c = E `JMP`, F `CALL`",
     "k = 0 `PC ← PC + 2·simm16`, k = 1 absolute", "-"),
    ("A", "A d s f", "disp", "2–3", "mem", "`LD ST LDB STB LDH STH LDSB LDSH LEA`",
     "`[rs + disp]`; rs = r0: absolute", "f"),
    ("B", "B d s f", "", "1", "bit", "`LSL LSR ASR ROR rd, #n` or `rd, rs`", "shift group", "NZCV"),
    ("C", "C d ii", "", "1", "alu", "`MVI rd, simm8`", "`rd ← simm8`", "NZ"),
    ("D", "D d ii", "", "1", "alu", "`ADDI rd, simm8`", "`rd ← rd + simm8`, leaves C and V alone", "NZ"),
    ("E", "E d ii", "", "1", "alu", "`CMPI rd, simm8`", "flags of `rd − simm8`", "NZCV"),
    ("F", "-", "", "", "res", "reserved: traps as illegal, so `FFFF` traps", "", "-"),
]

OPMAP_V1B = [
    ("0", "0 a b f", "", "1", "sys", "system group: `HALT`, `JMP rs`, `SAVE`, `RTI` …", "f picks it", "f"),
    ("1", "1 d M R", "ea", "1–3", "mem", "`MOV rd, ea`", "`rd ← ea`: move, load or constant", "NZ"),
    ("2", "2 d M R", "ea", "1–3", "mem", "`ST rd, ea`", "`ea ← rd`, memory modes only", "-"),
    ("3", "3 d M R", "ea", "1–3", "mem", "`LEA rd, ea`", "`rd ←` the address of ea", "-"),
    ("4–9", "n d M R", "ea", "1–3", "alu", "4 `ADD` 5 `SUB` 6 `CMP` 7 `AND` 8 `OR` 9 `XOR`",
     "`rd ← rd ⊕ ea`; `CMP` sets flags only", "NZCV"),
    ("A", "A c k 0", "target", "2–3", "br", "`Jcc label`; c = E `JMP`, F `CALL`",
     "k = 0 `PC ← PC + 2·simm16`, k = 1 absolute", "-"),
    ("B", "B k M R", "ea", "1–3", "br", "`JMP ea` (k = 0), `CALL ea` (k = 1)",
     "`PC ←` the value of ea", "-"),
    ("C", "C d s f", "", "1", "bit", "`NOT` … `CLZ rd, rs`", "`rd ← f(rs)`: unary group", "f"),
    ("D", "D d s f", "", "1", "bit", "`LSL LSR ASR ROR rd, #n` or `rd, rs`", "shift group", "NZCV"),
    ("E", "E c ii", "", "1", "br", "`Bcc label`; c = E `BRA`, F `BSR`", "`PC ← PC + 2·simm8`", "-"),
    ("F", "F d s f", "", "1", "alu", "`ADC` … `DIVUL rd, rs`", "`rd ← rd ⊕ rs`: register-only function f", "f"),
]

# The ALU functions: operation (src is rs, the immediate or the operand), flags, note.
ALU_OPS = {
    "ADD": ("`rd ← rd + src`", "NZCV", ""),
    "ADC": ("`rd ← rd + src + C`", "NZCV", "Z sticky"),
    "SUB": ("`rd ← rd − src`", "NZCV", ""),
    "SBC": ("`rd ← rd − src − !C`", "NZCV", "Z sticky"),
    "AND": ("`rd ← rd & src`", "NZ", ""),
    "OR": ("`rd ← rd | src`", "NZ", ""),
    "XOR": ("`rd ← rd ^ src`", "NZ", ""),
    "BIC": ("`rd ← rd & ~src`", "NZ", ""),
    "MOV": ("`rd ← src`", "NZ", ""),
    "CMP": ("flags of `rd − src`", "NZCV", ""),
    "TST": ("flags of `rd & src`", "NZ", ""),
    "MULU": ("`HI:rd ← rd × src`, unsigned", "NZCV", "CV: overflow"),
    "MULS": ("`HI:rd ← rd × src`, signed", "NZCV", "CV: overflow"),
    "DIVU": ("`rd ← rd ÷ src`, `HI ←` remainder", "NZCV", "C = 0, V: overflow"),
    "DIVS": ("signed, toward 0; `HI ←` remainder", "NZCV", "C = 0, V: overflow"),
    "DIVUL": ("`rd ← HI:rd ÷ src`, `HI ←` rem.", "NZCV", "C = 0, V: overflow"),
}


def alu_table(names, codes, title, sub, foot=""):
    rows = []
    for f, name in zip(codes, names):
        op, fl, note = ALU_OPS[name]
        rows.append([hexd(f), mn(name), t(op), flags(fl, note)])
    body = table(rows, ["f", "", "operation", "flags"], "fn")
    if foot:
        body += f'<p class="foot">{foot}</p>'
    return section(title, body, sub)


IMMEDIATES = ("Op 8's k: 0 `simm16`, 1 `uimm16` (zero-extended), 2 `imm16 << 16`, "
              "3 `imm32` (two parcels); 4–F trap.")


def conditions():
    rows = []
    tests = ["Z", "!Z", "C", "!C", "N", "!N", "V", "!V", "C & !Z", "!C | Z", "N = V", "N ≠ V",
             "!Z & N = V", "Z | N ≠ V", "always", ""]
    alias = {2: " HS", 3: " LO", 14: " AL"}
    for i in range(0, 16, 2):
        cells = []
        for cc in (i, i + 1):
            if cc == 15:
                cells += [hexd(cc), '<span class="muted">link</span>', t("`BSR`, `CALL`")]
                continue
            name = mn(COND[cc]) + (f'<span class="muted">{alias[cc]}</span>' if cc in alias else "")
            test = tests[cc] if tests[cc] == "always" else t(f"`{tests[cc]}`")
            cells += [hexd(cc), name, test]
        rows.append(cells)
    body = table(rows, ["cc", "", "test", "cc", "", "test"], "cond")
    body += ('<p class="foot">' + t("C is a carry when adding and *no borrow* when subtracting: "
                                    "after `CMP a, b`, `HS` means a ≥ b unsigned.").replace("*", "")
             + "</p>")
    return section("Conditions", body, "bit 0 inverts the test")


def unary(op):
    ops = ["`~rs`", "`0 − rs`", "`rs + 1`", "`rs − 1`", "`rs << 1 | C`, `C ← bit 31`",
           "`rs >> 1 | C << 31`, `C ← bit 0`", "swap the halves", "sign-extend byte",
           "zero-extend byte", "sign-extend half", "zero-extend half", "leading zeros, 0–32"]
    rows = []
    for i in range(6):
        rows.append([hexd(i), mn(UN_FN[i]), t(ops[i]), hexd(i + 6), mn(UN_FN[i + 6]), t(ops[i + 6])])
    body = table(rows, None, "fn un")
    body += ('<p class="foot">' + t("Flags NZ; `NEG` NZCV; `RLC`, `RRC` NZC with V = 0. "
                                    "f = C–F trap. `NOT r1` is `NOT r1, r1`.") + "</p>")
    return section("Unary group", body, f"`{op} d s f`: `rd ← f(rs)`")


def shifts(op):
    head = ["count", *[mn(s) for s in SHIFT_FN]]
    counts = ["`#s`: 0–15", "`#s + 16`: 16–31", "`rs & 31`"]
    rows = []
    for k in range(3):
        rows.append([t(counts[k]), *[hexd(4 * k + j) for j in range(4)]])
    body = table(rows, head, "fn sh")
    body += ('<p class="foot">' + t("In place on rd. NZ; C = the last bit out, unchanged for a "
                                    "count of 0 (`ROR`: the new bit 31); V = 0. Rotate left by n "
                                    "is `ROR` by 32 − n. f = C–F trap.") + "</p>")
    return section("Shift group", body, f"`{op} d s f`: f by operation and count")


SYS_OPS = [
    ("HALT", "stop; with I = 1, wait for an interrupt"),
    ("NOP", ""),
    ("JMP rs", "`PC ← rs`"),
    ("CALL rs", "push the return address; `PC ← rs`"),
    ("RET", "pop PC"),
    ("SAVE ra-rb", "push `ra` … `rb`, 1 ≤ a ≤ b ≤ 14"),
    ("RESTORE ra-rb", "pop them again"),
    ("RTI", "pop the flags, pop PC"),
    ("EI", "`I ← 1`"),
    ("DI", "`I ← 0`"),
    ("MFSR rd, n", "`rd ← SR n`: 0 flags (`MFF`), 1 HI (`MFHI`)"),
    ("MTSR n, rs", "`SR n ← rs` (`MTF`, `MTHI`)"),
    ("SWI #n", "software interrupt, 8-bit number"),
    ("SETcc rd", "`rd ← 1` if cc holds, else 0"),
]


def system(isa):
    rows = [[hexd(f), mn(name), t(op)] for f, (name, op) in enumerate(SYS_OPS)]
    rows.append(['<span class="hex">E–F</span>', '<span class="muted">trap</span>', ""])
    body = table(rows, None, "fn sys")
    body += ('<p class="foot">' + t(f"Operands go in a and b in order: `SAVE r8-r11` is "
                                    f"`{encode(isa, 'SAVE r8-r11')}`. `JMP` and `CALL rs` use b "
                                    "only, `SWI` puts n in a b, `SETcc` puts cc in b. "
                                    "`0000` is `HALT`.") + "</p>")
    return section("System group", body, "`0 a b f`, the same in 1a and 1b")


def long_mem():
    names = ["LD", "ST", "LDB", "STB", "LDH", "STH", "LDSB", "LDSH", "LEA", "LEA",
             "LD", "ST", "LDB", "STB", "LEA"]
    what = ["word", "word", "byte, zero-extended", "byte", "half, zero-extended", "half",
            "byte, sign-extended", "half, sign-extended", "`rd ← rs + disp`", "`rd ← PC + disp`, s = 0"]
    rows = []
    for i in range(8):
        j = i + 8
        right = [hexd(j), mn(names[j]) if j < 15 else '<span class="muted">trap</span>',
                 t(what[j]) if j < 10 else ("32-bit disp" if j < 15 else "")]
        rows.append([hexd(i), mn(names[i]), t(what[i]), *right])
    body = table(rows, None, "fn mem")
    body += ('<p class="foot">' + t("Address `rs + disp`: disp is signed 16 bits for f = 0–9, "
                                    "32 bits for A–E; rs = r0 makes it absolute. `LEA` leaves "
                                    "the flags alone; loads set NZ.") + "</p>")
    return section("Long memory forms", body, "`A d s f` + disp")


def modes():
    rows = [
        (0, "reg", "register R", "`r2`", "0"),
        (1, "reg", "constant R, 0–15", "`#5`", "0"),
        (2, "mem", "word at R", "`[r2]`", "0"),
        (3, "mem", "word at R + d16", "`[r2 + 8]`, `[label + r2]`", "1"),
        (4, "mem", "word at sp + 4·R, 0–60", "`[sp + 12]`", "0"),
        (5, "mem", "R + Rx·scale + d8, any size", "`[r2 + r3*4 + 8]`", "1"),
        (6, "mem", "word at R, then R += 4", "`[r2]+`", "0"),
        (7, "mem", "R −= 4, then word at R", "`-[r2]`", "0"),
        (8, "mem", "byte at R", "`byte [r2]`", "0"),
        (9, "mem", "byte at R + d16", "`byte [r2 + 1]`", "1"),
        (10, "mem", "byte at R, then R += 1", "`byte [r2]+`", "0"),
        (11, "mem", "half at R", "`half [r2]`", "0"),
        (12, "mem", "half at R + d16", "`half [r2 + 2]`", "1"),
        (13, "reg", "constant −(R + 1), −1 … −16", "`#-1`", "0"),
        (14, "res", "reserved: traps", "", ""),
        (15, "sys", "special, R picks it: below", "", "1–2"),
    ]
    out = [f'<tr class="g-{g}"><td><span class="op sm">{m:X}</span></td><td>{t(w)}</td>'
           f'<td>{t(s)}</td><td class="c">{n}</td></tr>' for m, g, w, s, n in rows]
    body = table(out, ["M", "operand", "syntax", "+"], "modes")
    body += ('<p class="foot">' + t("Memory operands are words unless the mode says otherwise; "
                                    "bytes and halves are zero-extended when read.") + "</p>")
    return section("Addressing modes", body, "`F D M R`: M is the mode, R its register")


def mode_f():
    rows = [
        ("0", "signed 16-bit constant", "`#-300`", "1"),
        ("1", "unsigned 16-bit constant", "`#0xFFFF`", "1"),
        ("2", "16 bits shifted left 16", "`#0x12340000`", "1"),
        ("3", "32-bit constant", "`#0x12345678`", "2"),
        ("4 5 6", "word, byte, half at abs16", "`[count]`, `byte [0xFFFFFF00]`", "1"),
        ("7 8 9", "word, byte, half at abs32", "", "2"),
        ("A B C", "word, byte, half at PC + d16", "`[pc + label]`", "1"),
        ("D–F", "reserved: traps", "", ""),
    ]
    out = [[f'<span class="hex">{r}</span>', t(w), t(s), f'<span class="c">{n}</span>']
           for r, w, s, n in rows]
    body = table(out, ["R", "operand", "syntax", "+"], "fn modef")
    body += ('<p class="foot">' + t("abs16 is sign-extended, so `0xFF00` reaches the I/O page "
                                    "at `0xFFFFFF00`.") + "</p>")
    return section("Mode F", body, "operands that need no register")


def index_parcel():
    fields = [(4, "x", "index register"), (2, "s", "scale ×1 ×2 ×4 ×8"),
              (2, "z", "byte, half, word"), (8, "d8", "signed displacement")]
    cells, bit = [], 16
    for width, name, what in fields:
        cells.append(f'<div class="bf" style="flex:{width}"><span class="bn">{bit - 1}</span>'
                     f'<b>{name}</b><small>{what}</small></div>')
        bit -= width
    return section("Indexed mode", f'<div class="bits16">{"".join(cells)}</div>'
                   '<p class="foot">' + t("`[R + Rx*scale + d8]`; `byte` or `half` before it for "
                                         "the size; z = 3 traps.") + "</p>",
                   "mode 5's extension parcel")


def mode_use():
    rows = [
        [t("`MOV ADD SUB CMP AND OR XOR`"), "every mode"],
        [t("`ST`"), t("memory modes only: not 0, 1, D or a constant")],
        [t("`LEA`"), t("memory modes, but not 6, 7 or A (auto-increment and -decrement)")],
        [t("`JMP ea`, `CALL ea`"), t("every mode; a memory operand must be a word: "
                                     "`JMP [table + r2]` jumps to the address stored there")],
    ]
    body = table(rows, None, "use")
    body += '<p class="foot">A mode an instruction can\'t use traps as an illegal instruction.</p>'
    return section("Which instructions take which modes", body)


def page1(isa):
    if isa == "v1a":
        left = (alu_table(ALU_FN, range(16), "ALU functions", "op 1 `rd, rs` and op 8 `rd, #imm`",
                          t(IMMEDIATES)) + conditions() + shifts("B"))
        right = long_mem() + unary("2") + system(isa)
        rows = OPMAP_V1A
    else:
        rr = ["ADC", "SBC", "BIC", "TST", "MULU", "MULS", "DIVU", "DIVS", "DIVUL"]
        left = modes() + mode_f() + index_parcel() + mode_use()
        right = (alu_table(rr, range(9), "Register-only functions", "`F d s f`; f = 9–F trap")
                 + conditions() + unary("C") + shifts("D"))
        rows = OPMAP_V1B
    return f"""
<div class="page">
  {header(isa)}
  {machine()}
  {opmap(rows)}
  <div class="cols"><div class="col">{left}</div><div class="col">{right}</div></div>
  {footer(isa, 1)}
</div>"""


# ---------------------------------------------------------------------------
# Page 2: semantics, the system, the assembler, examples


def flag_rules(isa):
    loads = "`LD LDB LDH LDSB LDSH`, `MOV`, `MVI`" if isa == "v1a" else "`MOV` (loads too), `POP`"
    rows = [
        [t("`ADD ADC SUB SBC CMP NEG`"), flags("NZCV")],
        [t("`AND OR XOR BIC TST NOT`"), flags("NZ")],
        [t(f"{loads}, `SWAP`, extends, `CLZ`"), flags("NZ")],
        [t("`INC DEC`" + (" `ADDI`" if isa == "v1a" else "")), flags("NZ", "adding a constant leaves C, V")],
        [t("shifts and rotates"), flags("NZCV", "C = last bit out, V = 0")],
        [t("`MULU MULS`"), flags("NZCV", "NZ of the low word; C = V = it didn't fit")],
        [t("`DIVU DIVS DIVUL`"), flags("NZCV", "NZ of the quotient; C = 0; V = overflow")],
        [t("stores, `LEA`, branches, jumps, calls, `SAVE`, `RESTORE`, `SETcc`, `MFSR`")
         + (t(", `POP`") if isa == "v1a" else ""), flags("-")],
    ]
    body = table(rows, None, "rules")
    body += bullets([
        "`ADC` and `SBC` have a sticky Z: they can clear it but never set it, so after "
        "`CMP lo` then `SBC hi` Z is set only if all 64 bits were zero.",
    ])
    return section("Flags", body, "`N` negative, `Z` zero, `C` carry, `V` overflow")


def muldiv():
    return section("Multiply and divide", bullets([
        "`MULU`, `MULS rd, src`: 64-bit product, low word to rd, high word to HI (`MFHI rd`). "
        "Small factors are faster: put the smaller one second.",
        "`DIVU`, `DIVS`: quotient to rd, remainder to HI. `DIVS` rounds toward zero, the "
        "remainder takes the dividend's sign; −2³¹ ÷ −1 gives −2³¹ and sets V.",
        "`DIVUL rd, src`: `HI:rd ÷ src`. With HI ≥ src it would overflow: V is set and nothing "
        "else changes. Chained, one per word, it divides a bignum by a word.",
        "Dividing by zero traps (divide error) and leaves the registers alone.",
    ]))


def stack(isa):
    push = ("`PUSH r` and `POP r` are `SAVE r-r` and `RESTORE r-r`."
            if isa == "v1a" else "`PUSH r` and `POP r` are `ST r, -[sp]` and `MOV r, [sp]+` (sets NZ).")
    return section("Stack and calls", bullets([
        "The stack grows down; sp points at the last word pushed. Every push and pop is a word.",
        "`CALL` and `BSR` push the address of the next instruction; `RET` pops it.",
        "`SAVE ra-rb` makes room for n registers (sp −= 4n), then stores ra at `[sp]`, "
        "ra+1 at `[sp + 4]` …; `RESTORE ra-rb` undoes it.",
        push,
        "Programs start with `.include \"lib/start.s\"`: the vectors, sp = `0x00100000`, "
        "`CALL main`, and `HALT` when main returns.",
    ]))


def interrupts():
    vec = [("00", "reset (also I ← 0)"), ("04", "IRQ: level-triggered, when I = 1"),
           ("08", "illegal instruction"), ("0C", "`SWI`"), ("10", "divide error"),
           ("14", "address error (misaligned)")]
    rows = []
    for i in range(0, 6, 2):
        rows.append([f'<span class="hex">0x{vec[i][0]}</span>', t(vec[i][1]),
                     f'<span class="hex">0x{vec[i + 1][0]}</span>', t(vec[i + 1][1])])
    body = table(rows, None, "vec")
    body += bullets([
        "Each vector has room for one `JMP handler`. Entry pushes PC, then the flags word, "
        "clears I and jumps to the vector; `RTI` pops both.",
        "The saved PC is the next instruction for an IRQ or `SWI`, the faulting one for a "
        "trap. `SWI`'s number is in its own parcel, at saved PC − 2.",
        "Interrupts are taken between instructions: never straight after `EI`, possibly "
        "straight after `DI`, and straight after an `RTI` that enables them.",
        "`HALT` with I = 1 waits for an interrupt, then carries on after the `HALT` "
        "(or stops, if no timer is running).",
    ])
    return section("Interrupts and traps", body, "vectors 4 bytes apart from 0")


def memory_io(isa):
    ext = "; `LDSB`, `LDSH` sign-extend" if isa == "v1a" else ""
    io = [("FF00", "console byte, or −1 if none waiting", "console output (low byte)"),
          ("FF04", "bit 0: a byte waits; bit 1: end of input", "—"),
          ("FF08", "timer period", "period in cycles, 0 = off"),
          ("FF0C", "timer flag (drives IRQ)", "acknowledge the timer"),
          ("FF10", "cycle counter", "—")]
    rows = [[f'<span class="hex">0xFFFF{a}</span>', t(r), t(w)] for a, r, w in io]
    body = bullets([
        "Byte-addressed, little-endian, 32-bit addresses. A half must be 2-aligned and a word "
        "4-aligned, or the access traps (address error). Instructions are 2-aligned.",
        "RAM: 1 MB at `0x00000000`–`0x000FFFFF` in the simulator. Byte and half loads "
        f"zero-extend{ext}.",
        "The I/O page, `0xFFFFFF00`–`FF`, is reached by a sign-extended 16-bit address "
        "(`0xFF00`). Its registers are words, 4 bytes apart; a byte access uses the low byte.",
    ])
    body += table(rows, ["address", "read", "write"], "io")
    body += ('<p class="foot">' + t("Read the console with a word load: a byte load gives "
                                    "`0xFF` at the end of input too.") + "</p>")
    return section("Memory and I/O", body)


def assembler(isa):
    common = [
        "Labels `name:`, and `.name:` local to the last one. Comments start with `;`. Case "
        "doesn't matter; `sp` is r15.",
        "`.byte .half .word .asciz .space .align .org .include`, and `name = expr`.",
        "Expressions: `+ - * / % & | ^ << >> ~`, `'c'`, `$` (here), `lo() hi() lo16() hi16()`.",
        "An out-of-range `Bcc` becomes `Jcc` and `BSR` becomes `CALL`. `LI rd, x` is "
        "`MOV rd, #x`; `HS`, `LO`, `AL` are `CS`, `CC`, `RA`.",
    ]
    if isa == "v1a":
        own = [
            "The shortest form wins: `MOV #n` becomes `MVI`, `CMP #n` becomes `CMPI`, a small "
            "offset takes the short `LD`/`ST`, and op 8 takes the smallest k. `ADD #n` never "
            "becomes `ADDI`: their flags differ.",
            "Memory: `[r2]`, `[r2 + 8]`, `[r2 - 4]`, `[label]`, `[label + r2]`. "
            "`LEA r1, label` is PC-relative.",
        ]
    else:
        own = [
            "The shortest mode wins: a constant 0–15 or −1 … −16 goes in the parcel, "
            "`[sp + n]` is a stack slot, `[r2 + 0]` is `[r2]`, and an address is 16-bit "
            "absolute if it fits, else PC-relative, else 32-bit.",
            "Sizes: `byte`, `half`, `word` (the default) before the operand. "
            "`[pc + label]` forces PC-relative.",
        ]
    return section("Assembler", bullets(common + own))


EXAMPLES = {
    "v1a": """\
; constants
        MVI   r1, -1            ; 8 bits: one parcel
        LI    r2, #0x12345678   ; op 8 with k = 3
        LEA   r3, msg           ; PC-relative
; a byte loop: loads set N and Z
.next:  LDB   r2, [r1]
        BEQ   .done
        STB   r2, [0xFFFFFF00]  ; to the console
        ADDI  r1, 1             ; leaves C and V
        BRA   .next
.done:
; a jump table
        LSL   r2, #2
        LD    r2, [table + r2]
        JMP   r2
; r2:r1 += r4:r3, then r1 × r5
        ADD   r1, r3
        ADC   r2, r4
        MULU  r1, r5            ; HI:r1
        MFHI  r2
; a function keeping r8, r9
f:      SAVE  r8-r9
        RESTORE r8-r9
        RET
""",
    "v1b": """\
; constants
        MOV   r1, #-1           ; −16 … 15: one parcel
        MOV   r2, #0x12345678   ; mode F, R = 3
        LEA   r3, [msg]
; a byte loop with auto-increment
.next:  MOV   r2, byte [r1]+    ; sets N and Z
        BEQ   .done
        ST    r2, byte [0xFFFFFF00]
        BRA   .next
.done:
; memory operands
        ADD   r1, [sp + 12]     ; stack slot
        MOV   r3, [r2 + r4*4]   ; indexed
        CMP   r1, byte [r8 + 1]
; jump tables, calls through memory
        JMP   [table + r2]
        CALL  [r9 + 8]
; r2:r1 += r4:r3, then r1 × r5
        ADD   r1, r3
        ADC   r2, r4
        MULU  r1, r5            ; HI:r1
        MFHI  r2
; push and pop
        PUSH  r8                ; ST r8, -[sp]
        POP   r8                ; MOV r8, [sp]+
""",
}

# Defined for the examples, but not shown.
EXAMPLE_SYMBOLS = "table = 0x1000\nmsg = 0x2000\n"


def assembled(isa):
    """The example as lines of (source, parcels), from the assembler."""
    src = EXAMPLE_SYMBOLS + "ex:\n" + EXAMPLES[isa]
    skip = src.count("\n") - EXAMPLES[isa].count("\n")
    img = asm.assemble_text(isas.get(isa), src, "example.s")
    words = {}
    for st in img.stmts:
        if st.kind == "insn":
            words[st.where[1]] = st.words
    lines = EXAMPLES[isa].rstrip("\n").split("\n")
    return [(line, words.get(i + 1 + skip, [])) for i, line in enumerate(lines)]


def encode(isa, line):
    """One instruction's parcels in hex, from the assembler."""
    img = asm.assemble_text(isas.get(isa), line + "\n", "encode.s")
    return " ".join(f"{w:04X}" for st in img.stmts if st.kind == "insn" for w in st.words)


def examples(isa):
    out = []
    for line, words in assembled(isa):
        code, _, comment = line.partition(";")
        if not code.strip():
            out.append(f'<tr class="hd"><td colspan="2">{html.escape(comment.strip())}</td></tr>')
            continue
        comment = f'<span class="cm">; {html.escape(comment.strip())}</span>' if comment else ""
        hexs = " ".join(f"{w:04X}" for w in words)
        out.append(f'<tr><td class="enc">{hexs}</td><td><pre>{html.escape(code.rstrip())}'
                   f'{" " if comment else ""}{comment}</pre></td></tr>')
    return section("Examples", table(out, None, "ex"), "with the assembler's encodings")


def compared(isa):
    a = [
        "loads and stores in one parcel with a small offset from any register",
        "8-bit constants in one parcel for `MOV`, `ADDI`, `CMP`",
        "an immediate form of every ALU function, `TST`, `BIC`, multiply and divide too",
        "`ADDI`, which leaves C and V alone; sign-extending loads",
    ]
    b = [
        "memory operands for `ADD SUB CMP AND OR XOR`",
        "auto-increment and -decrement, scaled index registers, stack slots",
        "PC-relative loads and stores, jumps and calls through memory",
        "constants −16 … 15 in one parcel for every main instruction",
    ]
    mine, other = (a, b) if isa == "v1a" else (b, a)
    o = "1b" if isa == "v1a" else "1a"
    body = (f'<div class="vs"><div><h3>Only {isa[1:]}</h3>{bullets(mine)}</div>'
            f'<div><h3>Only {o}</h3>{bullets(other)}</div></div>')
    return section(f"1a and 1b", body, "everything else is shared")


def page2(isa):
    if isa == "v1a":
        left = flag_rules(isa) + muldiv() + stack(isa) + interrupts() + compared(isa)
        right = memory_io(isa) + assembler(isa) + examples(isa)
    else:
        # 1b's page 1 has no room for the system group
        left = system(isa) + flag_rules(isa) + muldiv() + stack(isa) + interrupts()
        right = memory_io(isa) + assembler(isa) + examples(isa) + compared(isa)
    return f"""
<div class="page">
  <div class="cols p2"><div class="col">{left}</div><div class="col">{right}</div></div>
  {footer(isa, 2)}
</div>"""


def footer(isa, n):
    return (f'<footer><span>Heron draft {isa[1:]} · from <code>studies/v1_isa/isa-v1.md</code> and '
            f'<code>isa-{isa}.md</code> · <code>heron v1_isa refcard</code></span>'
            f'<span>{n} / 2</span></footer>')


CSS = """
:root {
  --ink: #1b2130; --muted: #5f6878; --faint: #9aa1ad; --rule: #cfd4dc; --hair: #e8ebf0;
  --mono: "JetBrains Mono", "SF Mono", Menlo, "DejaVu Sans Mono", monospace;
  --sans: Inter, "Helvetica Neue", Helvetica, Arial, sans-serif;
}
.v1a { --accent: #0d6e66; --accent-bg: #e0f2ef; }
.v1b { --accent: #b03a2e; --accent-bg: #fbe7e3; }
.g-sys { --g: #e7e9ee; --gf: #4a5262; }
.g-alu { --g: #dce8fb; --gf: #1c58a8; }
.g-reg { --g: #dce8fb; --gf: #1c58a8; }
.g-bit { --g: #ebe2f7; --gf: #673d9e; }
.g-mem { --g: #d9f0e3; --gf: #1b7647; }
.g-br  { --g: #fde8cc; --gf: #9c5200; }
.g-res { --g: #fff; --gf: #9aa1ad; }
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; background: #fff; color: var(--ink); font: 400 7.1pt/1.34 var(--sans);
}
.page { width: 210mm; min-height: 296.5mm; padding: 8.5mm 10mm 6.5mm; display: flex;
  flex-direction: column; gap: 2.8mm; break-after: page; }
.page:last-child { break-after: auto; }
code, pre, .hex { font-family: var(--mono); font-size: .94em; }
code.mn { font-weight: 700; }
pre { margin: 0; white-space: pre; }
.muted { color: var(--faint); }
b { font-weight: 600; }

/* header */
header.top { display: flex; justify-content: space-between; align-items: flex-end;
  border-bottom: 2.2pt solid var(--accent); padding-bottom: 2mm; }
.kicker { font-size: 6.6pt; font-weight: 600; letter-spacing: .12em; text-transform: uppercase;
  color: var(--muted); margin-bottom: .6mm; }
h1 { margin: 0; font: 700 21pt/1 "Inter Display", var(--sans); letter-spacing: -.01em; }
h1 .v { color: var(--accent); }
h1 .what { font-weight: 400; font-size: 12.5pt; color: var(--muted); margin-left: 3mm;
  letter-spacing: 0; }
.facts { text-align: right; font-size: 6.9pt; color: var(--muted); line-height: 1.45; }
.facts b { color: var(--ink); }

/* the machine */
.machine { display: grid; grid-template-columns: auto 1fr; gap: 1.2mm 5mm; align-items: center; }
.regs { display: grid; grid-template-columns: repeat(16, 7.4mm); gap: .6mm .5mm; }
.r { height: 7.2mm; border: .6pt solid var(--rule); border-radius: .8mm; text-align: center;
  font: 600 7pt/1 var(--mono); padding-top: 1.3mm; }
.r small { display: block; font: 500 5.6pt/1 var(--sans); color: var(--muted); margin-top: .7mm; }
.r.zero { background: repeating-linear-gradient(135deg, #f1f2f5 0 1.2mm, #fff 1.2mm 2.4mm); color: var(--muted); }
.r.sav { background: #eef0f4; }
.r.sp { background: var(--ink); color: #fff; border-color: var(--ink); }
.r.sp small { color: #c7ccd6; }
.lab { font-size: 5.8pt; color: var(--muted); text-align: center; border-top: .6pt solid var(--faint);
  padding-top: .4mm; margin: 0 .4mm; white-space: nowrap; }
.special { display: flex; flex-direction: column; gap: .9mm; }
.sr { display: flex; align-items: center; gap: 1.6mm; font-size: 6.6pt; color: var(--muted); }
.sr > b { font: 700 7pt var(--mono); color: var(--ink); min-width: 8.5mm; }
.bits { display: flex; gap: .5mm; }
.bits .b { width: 5mm; height: 4.6mm; border: .6pt solid var(--rule); border-radius: .6mm;
  text-align: center; font: 700 6.8pt/1 var(--mono); color: var(--ink); padding-top: .6mm; }
.bits .b small { display: block; font: 500 4.6pt/1 var(--sans); color: var(--faint); margin-bottom: .2mm; }

/* sections and tables */
section { break-inside: avoid; }
h2 { margin: 0 0 .9mm; font: 700 6.5pt/1.25 var(--sans); letter-spacing: .1em; text-transform: uppercase;
  color: var(--accent); border-bottom: .7pt solid var(--rule); padding-bottom: .6mm; }
h2 .sub { font-weight: 500; letter-spacing: 0; text-transform: none; color: var(--muted); margin-left: 1.2mm; }
h2 .sub code { font-size: 1em; }
h3 { margin: 0 0 .5mm; font: 700 6.6pt var(--sans); color: var(--ink); }
table { border-collapse: collapse; width: 100%; }
th { text-align: left; font: 600 5.6pt/1.2 var(--sans); letter-spacing: .06em; text-transform: uppercase;
  color: var(--faint); padding: 0 .9mm .5mm; }
td { padding: .18mm .9mm; vertical-align: middle; line-height: 1.26; }
.hex, .fn td:first-child { white-space: nowrap; }
tbody tr + tr td { border-top: .4pt solid var(--hair); }
td:first-child, th:first-child { padding-left: 0; }
.hex { color: var(--muted); font-weight: 500; }
.c { text-align: center; }
.note { color: var(--muted); font-size: 6.2pt; }
.foot { margin: .7mm 0 0; color: var(--muted); font-size: 6.4pt; }
ul { margin: 0; padding-left: 3mm; }
li { margin: .25mm 0; }
li::marker { color: var(--accent); }

.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 6mm; flex: 1; }
.col { display: flex; flex-direction: column; gap: 2.6mm; }

/* the opcode map */
.opmap td { padding-top: .22mm; padding-bottom: .22mm; white-space: nowrap; }
.opmap td:nth-child(4) { white-space: normal; }
.op { display: inline-block; min-width: 4.2mm; height: 3.8mm; padding: 0 .7mm; border-radius: .8mm;
  background: var(--g); color: var(--gf); font: 700 7pt/3.8mm var(--mono); text-align: center;
  white-space: nowrap; }
.op.sm { min-width: 3.6mm; height: 3.2mm; font-size: 6.4pt; line-height: 3.2mm; }
.g-res .op { border: .6pt dashed var(--faint); line-height: 3.5mm; }
.fmt { display: inline-flex; align-items: center; white-space: nowrap; }
.fmt .n { display: inline-block; width: 3.8mm; height: 3.6mm; border: .6pt solid var(--rule);
  margin-left: -.6pt; text-align: center; font: 500 6.3pt/3.3mm var(--mono); background: #fff; }
.fmt .n.w2 { width: 7.6mm; }
.fmt .n.opn { background: var(--g); color: var(--gf); font-weight: 700; margin-left: 0;
  border-radius: .7mm 0 0 .7mm; }
.fmt .n:last-of-type { border-radius: 0 .7mm .7mm 0; }
.fmt .x { margin-left: .9mm; padding: 0 .9mm; height: 3.6mm; border: .6pt dashed var(--faint);
  border-radius: .7mm; font: 500 5.8pt/3.2mm var(--sans); color: var(--muted); }
.opmap td:nth-child(3) { color: var(--muted); }
.fl i { font: normal 700 6.2pt var(--mono); display: inline-block; width: 1.7mm; text-align: center; }
.fl i.off { color: #d3d7de; font-weight: 500; }
.fl.none { color: var(--faint); font-size: 6.2pt; }
.modes .g-res td, .g-res td { color: var(--faint); }

.fn td:first-child { width: 4mm; }
.un td:nth-child(4) { padding-left: 2.5mm; border-left: .4pt solid var(--hair); }
.cond td:nth-child(4) { padding-left: 2.5mm; border-left: .4pt solid var(--hair); }
.mem td:nth-child(4) { padding-left: 2.5mm; border-left: .4pt solid var(--hair); }
.sh td:not(:first-child), .sh th:not(:first-child) { text-align: center; }
.vec td:nth-child(3) { padding-left: 2.5mm; border-left: .4pt solid var(--hair); }
.rules td:first-child { width: 40%; }
.rules td:last-child { white-space: nowrap; }
.use td:first-child { width: 24%; }
.io td:first-child { white-space: nowrap; }

.bits16 { display: flex; border: .6pt solid var(--rule); border-radius: .8mm; margin-top: 2.2mm; }
.bf { position: relative; text-align: center; padding: .7mm .5mm .5mm; }
.bf + .bf { border-left: .6pt solid var(--rule); }
.bf b { display: block; font: 700 7pt var(--mono); color: var(--accent); }
.bf small { display: block; font-size: 5.8pt; color: var(--muted); line-height: 1.15; }
.bf .bn { position: absolute; top: -2.3mm; left: .3mm; font: 500 5pt var(--mono); color: var(--faint); }

.ex td { padding: .1mm 0; border: 0 !important; vertical-align: baseline; }
.ex pre { font-size: 6.5pt; line-height: 1.3; }
.ex .cm { color: var(--faint); }
.ex .hd td { font-size: 6.1pt; font-weight: 600; color: var(--accent); padding-top: .9mm; padding-left: 25mm; }
.ex .enc { width: 25mm; font: 500 6.5pt/1.3 var(--mono); color: var(--muted); white-space: nowrap; }
.vs { display: grid; grid-template-columns: 1fr 1fr; gap: 3mm; }

footer { display: flex; justify-content: space-between; font-size: 5.9pt; color: var(--faint);
  border-top: .5pt solid var(--hair); padding-top: 1mm; margin-top: auto; }
footer code { font-size: 1em; }
"""


def build_html(isa):
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<title>Heron draft {isa[1:]}: quick reference</title><style>{CSS}</style></head>'
            f'<body class="{isa}">{page1(isa)}{page2(isa)}</body></html>')


# ---------------------------------------------------------------------------
# Printing


def find_chrome():
    if os.environ.get("CHROME"):
        return os.environ["CHROME"]
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome"):
        if shutil.which(name):
            return shutil.which(name)
    candidates = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    pw = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", os.path.expanduser("~/.cache/ms-playwright"))
    candidates += sorted(glob.glob(os.path.join(pw, "chromium-*/chrome-linux/chrome")), reverse=True)
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def print_pdf(chrome, html_path, pdf_path):
    # Without tagging the PDF is a third of the size: the structure tree is
    # most of it.
    cmd = [chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer", "--disable-pdf-tagging",
           f"--print-to-pdf={pdf_path}", "file://" + os.path.abspath(html_path)]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        cmd.insert(1, "--no-sandbox")
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)


def page_count(pdf_path):
    with open(pdf_path, "rb") as f:
        return len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", f.read()))


def main(args):
    chrome = find_chrome()
    if chrome is None:
        print("error: no Chromium or Chrome found; set CHROME to one", file=sys.stderr)
        return 1
    os.makedirs(OUT, exist_ok=True)
    for isa in ("v1a", "v1b"):
        page = os.path.join(OUT, f"refcard-{isa}.html")
        with open(page, "w") as f:
            f.write(build_html(isa))
        pdf = os.path.join(OUT, f"refcard-{isa}.pdf")
        print_pdf(chrome, page, pdf)
        n = page_count(pdf)
        print(f"{os.path.relpath(pdf)}: {n} pages")
        if n != 2:
            print(f"error: {isa}'s card should be 2 pages", file=sys.stderr)
            return 1
    return 0
