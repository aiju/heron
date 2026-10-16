//! The linker: object files and libraries in, an executable out.
//!
//! Symbols: every global symbol must be defined once. A library (archive)
//! is searched for symbols that are still undefined, and a member is loaded
//! when it defines one; a library's definition gives way to one in the
//! program's own objects, so a program can replace a library function.
//!
//! Sections that nothing refers to are left out (unless `gc` is off): the
//! roots are the absolute sections (the vectors), the entry symbol if one
//! is given, and, when there are neither, every section of the program's
//! own objects.
//!
//! Layout: absolute sections where they say; then, from the end of the
//! last absolute section (or `base`), the others in this order:
//!
//! ```text
//! .data .rodata .bss      near data: 16-bit addresses reach it below 0x8000
//! .text                   code
//! (anything else)
//! .fardata .farbss        far data, reached with 32-bit addresses
//! ```
//!
//! `__end` is defined as the first free address after everything (where
//! the C library's heap starts). Zero-filled sections are written out as
//! zeros, so a loader doesn't need to clear them.

use std::collections::{HashMap, HashSet};

use crate::obj::{
    self, ABS, EXEC, ObjectFile, SEC_ABS, SEC_NOBITS, SYM_GLOBAL, SYM_SECTION, Symbol, UNDEF,
};

const ORDER: [Option<&[&str]>; 6] = [
    Some(&[".data", ".rodata"]),
    Some(&[".bss"]),
    Some(&[".text"]),
    None,
    Some(&[".fardata"]),
    Some(&[".farbss"]),
];

/// Symbols the linker defines.
const LINKER_SYMBOLS: [&str; 1] = ["__end"];

/// Everything wrong with a link.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LinkError(pub Vec<String>);

impl LinkError {
    fn one(msg: String) -> LinkError {
        LinkError(vec![msg])
    }
}

fn section_class(name: &str) -> usize {
    let mut other = 0;
    for (k, prefixes) in ORDER.iter().enumerate() {
        match prefixes {
            None => other = k,
            Some(ps) => {
                if ps
                    .iter()
                    .any(|p| name == *p || name.starts_with(&format!("{p}.")))
                {
                    return k;
                }
            }
        }
    }
    other
}

fn align_up(a: u64, n: u64) -> u64 {
    a.div_ceil(n) * n
}

struct Input {
    obj: ObjectFile,
    library: bool,
    addr: Vec<u64>,
    live: Vec<bool>,
}

/// (input, symbol index)
type Def = (usize, usize);

/// What a link makes.
pub struct Linked {
    pub exe: ObjectFile,
    /// Symbol addresses, in the order they were first defined.
    pub symbols: Vec<(String, u64)>,
    /// The symbols in sections, by address: (name, address).
    pub labels: Vec<(String, u64)>,
    /// Each section's final contents, by address: what goes into memory
    /// (zero-filled sections too, which the executable leaves out).
    pub contents: Vec<(u64, Vec<u8>)>,
    /// Bytes of instructions.
    pub code: u64,
    /// The first free address.
    pub end: u64,
    /// The layout, as text.
    pub map: String,
}

pub struct Linker {
    pub isa: Option<String>,
    pub base: Option<u64>,
    pub gc: bool,
    pub entry: Option<String>,
    /// The top of memory: a program can't end past it.
    pub mem_top: u64,
    inputs: Vec<Input>,
    archives: Vec<Vec<(String, ObjectFile)>>,
    defs: HashMap<String, Def>,
    end: u64,
}

impl Linker {
    pub fn new(
        isa: Option<&str>,
        base: Option<u64>,
        gc: bool,
        entry: Option<&str>,
        mem_top: u64,
    ) -> Linker {
        Linker {
            isa: isa.map(String::from),
            base,
            gc,
            entry: entry.map(String::from),
            mem_top,
            inputs: Vec::new(),
            archives: Vec::new(),
            defs: HashMap::new(),
            end: 0,
        }
    }

    fn check_isa(&mut self, o: &ObjectFile) -> Result<(), LinkError> {
        match &self.isa {
            None => self.isa = Some(o.isa.clone()),
            Some(isa) if *isa != o.isa => {
                return Err(LinkError::one(format!(
                    "{} is for {}, not {}",
                    o.name, o.isa, isa
                )));
            }
            _ => {}
        }
        Ok(())
    }

    pub fn add(&mut self, o: ObjectFile) -> Result<(), LinkError> {
        self.check_isa(&o)?;
        if o.executable() {
            return Err(LinkError::one(format!(
                "{} is an executable, not an object file",
                o.name
            )));
        }
        self.push(o, false);
        Ok(())
    }

    pub fn add_library(&mut self, members: Vec<(String, ObjectFile)>) -> Result<(), LinkError> {
        for (_, o) in &members {
            self.check_isa(o)?;
        }
        self.archives.push(members);
        Ok(())
    }

    fn push(&mut self, obj: ObjectFile, library: bool) {
        let n = obj.sections.len();
        self.inputs.push(Input {
            obj,
            library,
            addr: vec![0; n],
            live: vec![false; n],
        });
    }

    // ---- symbols

    fn define_globals(&mut self, i: usize, errors: &mut Vec<String>) {
        let inp = &self.inputs[i];
        for (k, s) in inp.obj.symbols.iter().enumerate() {
            if !s.is_global() || !s.defined() {
                continue;
            }
            match self.defs.get(&s.name) {
                None => {
                    self.defs.insert(s.name.clone(), (i, k));
                }
                Some(&(p, _)) => {
                    let prev = &self.inputs[p];
                    if prev.library && !inp.library {
                        // the program's own replaces the library's
                        self.defs.insert(s.name.clone(), (i, k));
                    } else if inp.library && !prev.library {
                    } else {
                        errors.push(format!(
                            "{} is defined in both {} and {}",
                            s.name, prev.obj.name, inp.obj.name
                        ));
                    }
                }
            }
        }
    }

    fn resolve(&mut self) -> Result<(), LinkError> {
        let mut errors = Vec::new();
        self.defs.clear();
        for i in 0..self.inputs.len() {
            self.define_globals(i, &mut errors);
        }
        let mut loaded = HashSet::new();
        loop {
            let wanted: HashSet<&str> = self
                .inputs
                .iter()
                .flat_map(|inp| &inp.obj.symbols)
                .filter(|s| !s.defined() && !self.defs.contains_key(&s.name))
                .map(|s| s.name.as_str())
                .collect();
            let mut member = None;
            'search: for (ai, members) in self.archives.iter().enumerate() {
                for (mi, (_, o)) in members.iter().enumerate() {
                    if loaded.contains(&(ai, mi)) {
                        continue;
                    }
                    if o.symbols
                        .iter()
                        .any(|s| s.is_global() && s.defined() && wanted.contains(s.name.as_str()))
                    {
                        member = Some((ai, mi));
                        break 'search;
                    }
                }
            }
            let Some((ai, mi)) = member else { break };
            loaded.insert((ai, mi));
            let o = self.archives[ai][mi].1.clone();
            self.push(o, true);
            self.define_globals(self.inputs.len() - 1, &mut errors);
        }
        if errors.is_empty() {
            Ok(())
        } else {
            Err(LinkError(errors))
        }
    }

    /// The definition a reference resolves to, if any.
    fn target_of(&self, i: usize, k: usize) -> Option<Def> {
        let s = &self.inputs[i].obj.symbols[k];
        if s.is_global() || !s.defined() {
            self.defs.get(&s.name).copied()
        } else {
            Some((i, k))
        }
    }

    // ---- garbage collection

    fn mark(&mut self) -> Result<(), LinkError> {
        let mut work = Vec::new();
        let mut roots = false;
        let keep = |inputs: &mut Vec<Input>, work: &mut Vec<(usize, usize)>, i: usize, k: usize| {
            if !inputs[i].live[k] {
                inputs[i].live[k] = true;
                work.push((i, k));
            }
        };
        for i in 0..self.inputs.len() {
            for k in 0..self.inputs[i].obj.sections.len() {
                if self.inputs[i].obj.sections[k].absolute() {
                    keep(&mut self.inputs, &mut work, i, k);
                    roots = true;
                }
            }
        }
        if let Some(entry) = &self.entry {
            let Some(&(i, k)) = self.defs.get(entry) else {
                return Err(LinkError::one(format!(
                    "entry symbol {entry} isn't defined"
                )));
            };
            let sec = self.inputs[i].obj.symbols[k].section;
            if sec != UNDEF && sec != ABS {
                keep(&mut self.inputs, &mut work, i, sec as usize - 1);
            }
            roots = true;
        }
        if !roots || !self.gc {
            for i in 0..self.inputs.len() {
                if !self.inputs[i].library || !self.gc {
                    for k in 0..self.inputs[i].obj.sections.len() {
                        keep(&mut self.inputs, &mut work, i, k);
                    }
                }
            }
        }
        let mut by_section: HashMap<(usize, usize), Vec<usize>> = HashMap::new();
        for (i, inp) in self.inputs.iter().enumerate() {
            for (j, r) in inp.obj.relocs.iter().enumerate() {
                by_section
                    .entry((i, r.section as usize - 1))
                    .or_default()
                    .push(j);
            }
        }
        while let Some((i, k)) = work.pop() {
            for &j in by_section.get(&(i, k)).map(|v| v.as_slice()).unwrap_or(&[]) {
                let r = &self.inputs[i].obj.relocs[j];
                let Some((ti, tk)) = self.target_of(i, r.symbol as usize) else {
                    continue;
                };
                let sec = self.inputs[ti].obj.symbols[tk].section;
                if sec != UNDEF && sec != ABS {
                    keep(&mut self.inputs, &mut work, ti, sec as usize - 1);
                }
            }
        }
        Ok(())
    }

    // ---- layout

    fn layout(&mut self) -> Result<(), LinkError> {
        // (start, end, input, section)
        let mut placed = Vec::new();
        for (i, inp) in self.inputs.iter_mut().enumerate() {
            for (k, sec) in inp.obj.sections.iter().enumerate() {
                if inp.live[k] && sec.absolute() {
                    inp.addr[k] = sec.addr as u64;
                    placed.push((sec.addr as u64, sec.addr as u64 + sec.size as u64, i, k));
                }
            }
        }
        placed.sort_by_key(|p| (p.0, p.1));
        let mut errors = Vec::new();
        for w in placed.windows(2) {
            let (a, b) = (w[0], w[1]);
            if b.0 < a.1 {
                let (oa, ob) = (&self.inputs[a.2].obj, &self.inputs[b.2].obj);
                errors.push(format!(
                    "{}({}) at {:#x}-{:#x} overlaps {}({}) at {:#x}",
                    oa.name,
                    oa.sections[a.3].name,
                    a.0,
                    a.1 - 1,
                    ob.name,
                    ob.sections[b.3].name,
                    b.0
                ));
            }
        }
        if !errors.is_empty() {
            return Err(LinkError(errors));
        }
        let mut addr = match self.base {
            Some(b) => b,
            None => align_up(placed.iter().map(|p| p.1).max().unwrap_or(0), 4),
        };
        let mut order = Vec::new();
        for (i, inp) in self.inputs.iter().enumerate() {
            for (k, sec) in inp.obj.sections.iter().enumerate() {
                if inp.live[k] && !sec.absolute() {
                    order.push((section_class(&sec.name), i, k));
                }
            }
        }
        order.sort_by_key(|t| t.0); // stable: input order within a class
        for (_, i, k) in order {
            let sec = &self.inputs[i].obj.sections[k];
            addr = align_up(addr, sec.align.max(1) as u64);
            let size = sec.size as u64;
            self.inputs[i].addr[k] = addr;
            addr += size;
        }
        self.end = align_up(placed.iter().map(|p| p.1).fold(addr, u64::max), 4);
        if self.end > self.mem_top {
            return Err(LinkError::one(format!(
                "the program needs {:#x} bytes, more than the {:#x} of memory",
                self.end, self.mem_top
            )));
        }
        Ok(())
    }

    fn address(&self, (i, k): Def) -> u64 {
        let s = &self.inputs[i].obj.symbols[k];
        if s.section == ABS {
            s.value as u64
        } else {
            self.inputs[i].addr[s.section as usize - 1] + s.value as u64
        }
    }

    // ---- the whole thing

    pub fn link(&mut self) -> Result<Linked, LinkError> {
        if self.inputs.is_empty() {
            return Err(LinkError::one("nothing to link".into()));
        }
        self.resolve()?;
        self.mark()?;
        self.layout()?;
        let mut errors = Vec::new();
        let mut contents: HashMap<(usize, usize), Vec<u8>> = HashMap::new();
        for (i, inp) in self.inputs.iter().enumerate() {
            for (k, sec) in inp.obj.sections.iter().enumerate() {
                if inp.live[k] {
                    let data = if sec.nobits() {
                        vec![0; sec.size as usize]
                    } else {
                        sec.data.clone()
                    };
                    contents.insert((i, k), data);
                }
            }
        }
        for (i, inp) in self.inputs.iter().enumerate() {
            for r in &inp.obj.relocs {
                let k = r.section as usize - 1;
                if !inp.live[k] {
                    continue;
                }
                let sym = &inp.obj.symbols[r.symbol as usize];
                let sec = &inp.obj.sections[k];
                let wh = format!("{}({}+{:#x})", inp.obj.name, sec.name, r.offset);
                let s = match self.target_of(i, r.symbol as usize) {
                    Some(t) => self.address(t),
                    None if LINKER_SYMBOLS.contains(&sym.name.as_str()) => self.end,
                    None => {
                        errors.push(format!("{wh}: undefined symbol {}", sym.name));
                        continue;
                    }
                };
                let p = inp.addr[k] + r.offset as u64;
                match obj::reloc_value(r.kind, s as i64, r.addend as i64, p as i64) {
                    Ok(data) => {
                        // reading the object file checked that the field
                        // is inside the section
                        let o = r.offset as usize;
                        contents.get_mut(&(i, k)).unwrap()[o..o + data.len()]
                            .copy_from_slice(&data);
                    }
                    Err(e) => {
                        let pc_rel = obj::pc_relative(r.kind);
                        let what = if r.addend != 0 && !pc_rel {
                            format!("{}{:+}", sym.name, r.addend)
                        } else {
                            sym.name.clone()
                        };
                        let hint = if r.kind == obj::ABS16S {
                            "; declare it .far to use 32-bit addresses"
                        } else {
                            ""
                        };
                        let kind = obj::reloc_name(r.kind).unwrap_or("?");
                        errors.push(format!("{wh}: {kind} reference to {what}: {e}{hint}"));
                    }
                }
            }
        }
        if !errors.is_empty() {
            return Err(LinkError(errors));
        }
        Ok(self.output(contents))
    }

    fn output(&self, mut contents: HashMap<(usize, usize), Vec<u8>>) -> Linked {
        let isa = self.isa.clone().unwrap_or_default();
        let mut exe = ObjectFile::new(&isa, EXEC, 0, "a.out");
        let mut code = 0;
        let mut secs = Vec::new();
        for (i, inp) in self.inputs.iter().enumerate() {
            for k in 0..inp.obj.sections.len() {
                if inp.live[k] {
                    secs.push((inp.addr[k], i, k));
                }
            }
        }
        secs.sort_by_key(|t| t.0);
        let mut mem = Vec::new();
        for &(addr, i, k) in &secs {
            let sec = &self.inputs[i].obj.sections[k];
            let data = contents.remove(&(i, k)).unwrap();
            mem.push((addr, data.clone()));
            code += sec.code as u64;
            exe.sections.push(obj::Section {
                name: sec.name.clone(),
                flags: SEC_ABS | (sec.flags & SEC_NOBITS),
                addr: addr as u32,
                size: sec.size,
                align: sec.align,
                data: if sec.nobits() { Vec::new() } else { data },
                code: sec.code,
            });
        }
        let mut symbols: Vec<(String, u64)> = Vec::new();
        let mut index: HashMap<String, usize> = HashMap::new();
        let mut labels = Vec::new();
        for (i, inp) in self.inputs.iter().enumerate() {
            for (k, s) in inp.obj.symbols.iter().enumerate() {
                if !s.defined() || s.flags & SYM_SECTION != 0 || s.name == "*ABS*" {
                    continue;
                }
                if s.section != ABS && !inp.live[s.section as usize - 1] {
                    continue;
                }
                if s.is_global() && self.defs.get(&s.name) != Some(&(i, k)) {
                    continue;
                }
                let a = self.address((i, k));
                if s.section != ABS {
                    labels.push((s.name.clone(), a));
                }
                match index.get(&s.name) {
                    Some(&j) if s.is_global() => symbols[j].1 = a,
                    Some(_) => {}
                    None => {
                        index.insert(s.name.clone(), symbols.len());
                        symbols.push((s.name.clone(), a));
                    }
                }
                exe.symbols.push(Symbol {
                    name: s.name.clone(),
                    section: ABS,
                    value: a as u32,
                    flags: s.flags & !SYM_SECTION,
                });
            }
        }
        if !index.contains_key("__end") {
            symbols.push(("__end".into(), self.end));
            exe.symbols.push(Symbol {
                name: "__end".into(),
                section: ABS,
                value: self.end as u32,
                flags: SYM_GLOBAL,
            });
        }
        labels.sort_by_key(|l| l.1);
        Linked {
            exe,
            symbols,
            labels,
            contents: mem,
            code,
            end: self.end,
            map: self.map(),
        }
    }

    /// The layout, as text (after linking).
    fn map(&self) -> String {
        let mut rows = Vec::new();
        for inp in &self.inputs {
            for (k, sec) in inp.obj.sections.iter().enumerate() {
                if inp.live[k] {
                    rows.push((inp.addr[k], sec, &inp.obj.name));
                }
            }
        }
        rows.sort_by_key(|r| r.0);
        let mut out = String::new();
        for (addr, sec, name) in rows {
            out += &format!(
                "{:06X}-{:06X}  {:6}  {:<24} {}\n",
                addr,
                addr + (sec.size as u64).max(1) - 1,
                sec.size,
                sec.name,
                name
            );
        }
        let dropped = self
            .inputs
            .iter()
            .map(|inp| inp.live.iter().filter(|&&l| !l).count())
            .sum::<usize>();
        if dropped > 0 {
            out += &format!("({dropped} unused sections left out)\n");
        }
        out += &format!("end {:06X}\n", self.end);
        out
    }
}
