"""Where a program's cycles go on draft 1b.

The simulator records the cycles spent at every instruction address, for
every hardware configuration. A program's own cycles are its run's minus
those of an empty program's (start-up compiles the prelude, which is the
same every time), and each address is put down to a part of the VM:

- a C function, grouped (allocation, collection, primitives, big
  integers, maps, the compiler, the C library);
- inside the interpreter's loop, a bytecode: the switch's jump table gives
  each opcode's first block, and every block reachable from it without
  going back through the dispatch belongs to it. Blocks that several
  opcodes reach (the send path, mostly) are "send/call" if OP_SEND reaches
  them, "shared" otherwise.
"""

import bisect
import re
from collections import Counter, defaultdict

from . import build

CONFIGS = ["D16-overlap", "D32-separate", "D32-wide"]

GROUPS = [
    ("C slow path", r"_(step|egret_step|egret_raise|egret_prim_failed)$"),
    ("collector", r"_(gc|forward|obj_bytes)$"),
    ("allocation", r"_(alloc_obj|alloc_bytes|next_hash|perm_obj|perm_bytes|make_list|list_push|"
                   r"make_string|make_string_c|make_range|make_error|make_error_v|push_root|pop_roots)$"),
    ("big integers", r"_(int_\w+|mag_\w+|unpack|pack|trim|add_signed|bitwise|too_big|big_hash|is_bigint)$"),
    ("maps", r"_(map_\w+|find|rebuild|new_index|value_eq|value_hash|str_hash|str_eq)$"),
    ("method lookup", r"_(lookup|class_lookup|class_lookup_here|interp_flush_cache)$"),
    ("compiler", r"_(lex_\w+|token|skip_string|peek_chain|continues|ends_operand|is_\w+|intern|intern_c|"
                 r"compile_\w+|gen\w*|emit\w*|lit|set_line|load|store|send|binop|patch\w*|jump_\w+|"
                 r"node|next|accept|expect|skip_nl|new_func|new_var|find_var|resolve|name_ref|define_target|"
                 r"note_assign|ivar_index|append|call_args|send_node|string_node|list_literal|param_list|"
                 r"block_literal|parse_\w+|loop_\w+|primary|method_name_after_dot|postfix|power|unary|"
                 r"at_level|binary|not_expr|and_expr|or_expr|setter_name|expr|statement|statements|"
                 r"def_name|finish_method|decide_boxes|perm_literal|perm_string|global_index|"
                 r"global_exists|scratch_\w+|class_add_method|table_put|new_table|errorf|error|"
                 r"sym_text|cur_tok_text|temp_slot|push_self|push_loop|pop_loop|assign_op|"
                 r"make_class|new_class_obj)$"),
    ("primitives", r"_(p_\w+|type_error|index_error|arith_check|list_slice|str_cmp|find_sub|map_list|"
                   r"is_space|prim_fail\w*|msg3)$"),
    ("C library", r"_(memcpy|memset|memcmp|memmove|strlen|strcmp|strcpy|strcat|__\w+)$"),
    ("output", r"_(out_\w+)$"),
]


def group_of(func):
    for name, pat in GROUPS:
        if re.match(pat, func):
            return name
    return "other C"


class Layout:
    """What every code address of the VM is: function, and in the
    interpreter, bytecode."""

    def __init__(self, img):
        self.img = img
        syms = img.symbols
        funcs = sorted((a, n) for n, a in syms.items() if n.startswith("_") and "." not in n
                       and a < syms["__end"])
        self.starts = [a for a, _ in funcs]
        self.names = [n for _, n in funcs]
        self.asm = "_asm_run" in syms
        if self.asm:
            self._asm_layout()
            self.interp_lo = self.interp_hi = 0
            return
        from .vm_ops import OPCODES
        self.interp_lo = syms["_interpret"]
        self.interp_hi = self.starts[self.starts.index(self.interp_lo) + 1]
        # the blocks of the interpreter, from its local labels
        blocks = sorted((a, n) for n, a in syms.items() if n.startswith("_interpret.b"))
        blocks = [(a, n) for a, n in blocks if self.interp_lo <= a < self.interp_hi]
        self.block_starts = [self.interp_lo] + [a for a, _ in blocks]
        self.block_names = ["entry"] + [n.split(".")[1] for _, n in blocks]
        self.succ = self._successors()
        self.block_op = self._attribute(OPCODES)

    # the hand-written loop: its labels say what each instruction is for
    ASM_PARTS = [
        (r"^send(\.int|\.probe)?$", "send: lookup"),
        (r"^send\.(call|clear|go|overflow2?)$", "send: frame"),
        (r"^send\.(notplain|failed)$", "send: primitive"),
        (r"^send\.special$", "send: block"),
        (r"^send\.miss$", "send: miss"),
        (r"^op_send$", "SEND"),
        (r"^binop_slow$", "send: operator"),
        (r"^op_at_put\.slow$", "send: operator"),
        (r"^push_(true|false)$", "booleans"),
        (r"^(save|slow|reload|op_slow|exit|_asm_run)$", "to C and back"),
    ]

    def _asm_layout(self):
        from heron.infra import isas
        syms = self.img.symbols
        lo = syms["_asm_run"]
        hi = syms["optable"]
        labels = sorted((a, n) for n, a in syms.items()
                        if lo <= a < hi and not re.match(r"^[A-Z_0-9]+$", n) and not n.startswith("_mcache"))
        labels = [(a, n) for a, n in labels if n == "_asm_run" or not n.startswith("_")]
        self.asm_lo, self.asm_hi = lo, hi
        self.asm_starts = [a for a, _ in labels]
        self.asm_names = [n for _, n in labels]
        # the dispatches: MOV r1, byte [r8]+ then JMP [r13 + r1*4]
        isa = isas.get("v1b")
        mem = self.img.mem
        def parcel(a):
            return mem.get(a, 0) | mem.get(a + 1, 0) << 8
        self.dispatch_pcs = set()
        pc, prev = lo, None
        while pc < hi:
            text, n = isa.disassemble([parcel(pc), parcel(pc + 2), parcel(pc + 4)], pc, {})
            norm = " ".join(text.split())
            if norm == "JMP [r13 + r1*4]" and prev is not None:
                self.dispatch_pcs.update((prev[0], pc))
            prev = (pc, norm) if norm == "MOV r1, byte [r8]+" else None
            pc += 2 * n

    def asm_part(self, pc):
        if pc in self.dispatch_pcs:
            return "dispatch"
        k = bisect.bisect_right(self.asm_starts, pc) - 1
        name = self.asm_names[k] if k >= 0 else "?"
        for pat, part in self.ASM_PARTS:
            if re.match(pat, name):
                return part
        if name.startswith("op_"):
            return name[3:].split(".")[0].upper()
        return name

    def _successors(self):
        """Each block's successors, from the disassembly: branch targets and
        the fall-through."""
        from heron.infra import isas
        isa = isas.get("v1b")
        mem = self.img.mem
        def parcel(a):
            return mem.get(a, 0) | mem.get(a + 1, 0) << 8
        index = {a: i for i, a in enumerate(self.block_starts)}
        succ = defaultdict(set)
        tables = []
        for i, start in enumerate(self.block_starts):
            end = self.block_starts[i + 1] if i + 1 < len(self.block_starts) else self.interp_hi
            pc = start
            falls = True
            while pc < end:
                text, n = isa.disassemble([parcel(pc), parcel(pc + 2), parcel(pc + 4)], pc, {})
                op = text.split()[0] if text else ""
                m = re.search(r"\b(?:0x)?([0-9A-Fa-f]{4,8})\b\s*$", text)
                if op in ("BRA", "JMP") or (op.startswith("B") and op not in ("BSR", "BIC")) \
                        or (op.startswith("J") and op != "JMP"):
                    if m:
                        t = int(m.group(1), 16)
                        if t in index:
                            succ[i].add(index[t])
                    if op in ("BRA", "JMP", "JRA"):
                        falls = False
                if op == "JMP" and "[" in text:
                    tables.append(i)
                    falls = False
                if op in ("RET", "HALT"):
                    falls = False
                pc += 2 * n
            if falls and i + 1 < len(self.block_starts):
                succ[i].add(i + 1)
        self.dispatch_blocks = set(tables)
        return succ

    def _jump_table(self):
        syms = self.img.symbols
        mem = self.img.mem
        tabs = sorted(a for n, a in syms.items() if n.startswith("_interpret_jt"))
        # the biggest table is the bytecode switch; a table ends where the
        # next one starts, or at the first word that isn't an address in
        # the interpreter
        best = None
        for t, a in enumerate(tabs):
            limit = tabs[t + 1] if t + 1 < len(tabs) else a + 4096
            k = 0
            while a + 4 * k < limit:
                w = sum(mem.get(a + 4 * k + j, 0) << (8 * j) for j in range(4))
                if not (self.interp_lo <= w < self.interp_hi):
                    break
                k += 1
            if best is None or k > best[1]:
                best = (a, k)
        a, k = best
        return [sum(mem.get(a + 4 * i + j, 0) << (8 * j) for j in range(4)) for i in range(k)]

    def _attribute(self, opcodes):
        table = self._jump_table()
        index = {a: i for i, a in enumerate(self.block_starts)}
        # the dispatch: the block holding the switch's indexed jump
        dispatch = {i for i in self.dispatch_blocks if any(index.get(t) is not None for t in table)}
        reach = defaultdict(set)
        for op, target in enumerate(table):
            name = opcodes[op] if op < len(opcodes) else f"op{op}"
            start = index.get(target)
            if start is None:
                continue
            seen = set()
            todo = [start]
            while todo:
                b = todo.pop()
                if b in seen or b in dispatch:
                    continue
                seen.add(b)
                todo.extend(self.succ.get(b, ()))
            for b in seen:
                reach[b].add(name)
        out = {}
        for b in range(len(self.block_starts)):
            ops = reach.get(b)
            if b in dispatch:
                out[b] = "dispatch"
            elif not ops:
                out[b] = "entry/exit"
            elif len(ops) == 1:
                out[b] = next(iter(ops))
            elif "SEND" in ops:
                out[b] = "send/call"
            else:
                out[b] = "shared"
        self.dispatch = dispatch
        return out

    def func(self, pc):
        k = bisect.bisect_right(self.starts, pc) - 1
        return self.names[k] if k >= 0 else "?"

    def where(self, pc):
        """(group, detail) for an address"""
        if self.asm and self.asm_lo <= pc < self.asm_hi:
            return "interpreter", self.asm_part(pc)
        if self.interp_lo <= pc < self.interp_hi:
            b = bisect.bisect_right(self.block_starts, pc) - 1
            return "interpreter", self.block_op[b]
        f = self.func(pc)
        return group_of(f), f


_empty = {}


def empty_cycles(config, variant="asm"):
    """Per-address cycles of the empty program: start-up."""
    if (variant, config) not in _empty:
        m = build.machine(b"", variant=variant)
        _empty.update({(variant, c): m.pc_cycles(c) for c in CONFIGS})
    return _empty[(variant, config)]


def variant_of(m):
    return "asm" if "_asm_run" in m.image.symbols else "c"


def own_cycles(m, config):
    """A run's cycles per address, start-up taken out."""
    base = empty_cycles(config, variant_of(m))
    out = Counter(m.pc_cycles(config))
    out.subtract(base)
    return {pc: c for pc, c in out.items() if c and pc is not None}


def breakdown(m, config, layout=None):
    """{group: cycles}, {(group, detail): cycles}"""
    layout = layout or Layout(m.image)
    groups, details = Counter(), Counter()
    for pc, c in own_cycles(m, config).items():
        g, d = layout.where(pc)
        groups[g] += c
        details[(g, d)] += c
    return groups, details


def print_stats(m, f):
    layout = Layout(m.image)
    for config in ["D32-separate"]:
        groups, details = breakdown(m, config, layout)
        total = sum(groups.values())
        print(f"\n{config}: {total:,} cycles after start-up", file=f)
        for g, c in groups.most_common():
            print(f"  {g:<16} {c:>12,} {100 * c / total:5.1f}%", file=f)
        print("  the interpreter's part, by bytecode:", file=f)
        for (g, d), c in details.most_common():
            if g == "interpreter" and c * 200 > total:
                print(f"    {d:<18} {c:>12,} {100 * c / total:5.1f}%", file=f)
        print("  the biggest C functions:", file=f)
        for (g, d), c in details.most_common(40):
            if g != "interpreter" and c * 100 > total:
                print(f"    {d:<18} {c:>12,} {100 * c / total:5.1f}%  ({g})", file=f)
