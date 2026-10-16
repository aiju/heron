"""Where a run's cycles go: compiled code by what the code generator said
each instruction was for (codegen.CATS), the runtime by routine; and
what the evaluation checks found."""

from collections import Counter

from .machine import CONFIG

# runtime routines (by their labels) -> category
RT_GROUPS = {
    "upd": "rt:update", "ind_entry": "rt:update", "pap_entry": "rt:update",
    "ap_slow": "rt:apply", "argslot": "rt:apply",
    "rt_gc": "rt:gc", "evac_range": "rt:gc", "evac": "rt:gc", "objsize": "rt:gc",
    "input_entry": "rt:input",
    "boot": "rt:output", "rt_start": "rt:output", "put_list": "rt:output", "puts": "rt:output",
    "trap_tag": "rt:trap",
}

# categories -> the report's groups
GROUPS = [
    ("evaluation checks", ("evalt", "evalb", "entryt", "entryb", "entert", "enterb")),
    ("evaluating: slow paths", ("evalhit", "evalind", "evalthunk", "evalslow", "entryhit", "entryind",
                                "entrythunk", "entryslow", "enterhit", "enter")),
    ("thunk entry and update", ("update", "fvload", "rt:update")),
    ("allocation", ("alloc",)),
    ("heap checks", ("heapchk", "gcslow")),
    ("stack checks", ("stkchk",)),
    ("known calls and returns", ("call", "save", "return", "jump", "move")),
    ("unknown calls", ("apply", "rt:apply")),
    ("case and fields", ("case", "field")),
    ("arithmetic", ("arith", "ovf")),
    ("the collector", ("rt:gc",)),
    ("input and output", ("rt:input", "rt:output")),
    ("tag traps", ("rt:trap",)),
    ("other", ("error", "rt:other", "?")),
]
GROUP_OF = {c: g for g, cs in GROUPS for c in cs}


class Profile:
    def __init__(self, run, config=CONFIG):
        c = run.compiled
        m = run.machine
        self.run = run
        self.config = config
        img = c.image
        rt_labels = sorted((a, n) for n, a in img.symbols.items()
                           if "." not in n and a < img.symbols["code_start"] and a >= img.symbols["rt_start"])
        self.text = {}
        for st in img.stmts:
            if st.kind == "insn":
                self.text[st.addr] = st.text.strip()
        cats = {}
        for pc in m.pc_counts:
            cat = c.where_cats.get(pc)
            if cat is None:
                if pc >= img.symbols["code_start"]:
                    cat = "?"
                else:
                    cat = self.rt_cat(pc, rt_labels)
            cats[pc] = cat
        self.cats = cats
        self.counts = m.pc_counts
        self.cycles = m.pc_cycles(config)
        self.total = sum(self.cycles.values())
        self.by_cat = Counter()
        self.count_cat = Counter()
        for pc, n in self.cycles.items():
            self.by_cat[cats.get(pc, "rt:other")] += n
        for pc, n in self.counts.items():
            self.count_cat[cats.get(pc, "rt:other")] += n

    @staticmethod
    def rt_cat(pc, labels):
        name = None
        for a, n in labels:
            if a <= pc:
                name = n
            else:
                break
        if name is None:
            return "rt:other"
        if name.startswith("ap_"):
            return "rt:apply"
        if name.startswith(("rt_", "trap_", "msg_")) and name not in RT_GROUPS:
            return "rt:other"
        return RT_GROUPS.get(name, "rt:other")

    def groups(self):
        out = Counter()
        for c, n in self.by_cat.items():
            out[GROUP_OF.get(c, "other")] += n
        return out

    def checks(self):
        """What the evaluation checks found: counts."""
        k = self.count_cat
        checks = k["evalt"] + k["entryt"]
        found = k["evalhit"] + k["entryhit"]
        ind = (k["evalind"] + k["entryind"]) // 2
        return {
            "checks": checks,
            "unevaluated": found,
            "indirections": ind,
            "entered": found - ind,
            "tail enters": k["entert"],
            "tail enters of unevaluated": k["enterhit"],
        }

    def mix(self):
        """Executions by mnemonic."""
        out = Counter()
        for pc, n in self.counts.items():
            t = self.text.get(pc, "?")
            out[t.split()[0] if t else "?"] += n
        return out


def print_profile(run, out, config=CONFIG):
    p = Profile(run, config)
    print(f"--- cycles by group ({config}):", file=out)
    for g, n in p.groups().most_common():
        print(f"  {g:28s} {n:12,} {100 * n / p.total:6.1f}%", file=out)
    print("--- evaluation checks:", file=out)
    for k, v in p.checks().items():
        print(f"  {k:28s} {v:12,}", file=out)
    print("--- the hottest instructions:", file=out)
    for pc, n in p.cycles.most_common(25):
        print(f"  {pc:6X} {n:11,} {100 * n / p.total:5.1f}% {p.cats.get(pc, ''):10s} {p.text.get(pc, '')}",
              file=out)
