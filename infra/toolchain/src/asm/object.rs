//! An object file from the assembled statements.

use std::borrow::Cow;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::sync::Arc;

use super::{AsmError, Assembler, Base, Kind, Stmt, expr::mangle, is_nobits};
use crate::obj::{self, ObjectFile, Reloc, Section, Symbol};

fn u32_of(v: i64, what: &str) -> Result<u32, AsmError> {
    u32::try_from(v).map_err(|_| AsmError::new(format!("{what} {v} doesn't fit in an object file")))
}

fn stmt_bytes(st: &Stmt) -> Option<Cow<'_, [u8]>> {
    match st.kind {
        Kind::Insn => Some(Cow::Owned(
            st.words.iter().flat_map(|w| w.to_le_bytes()).collect(),
        )),
        Kind::Dir if !st.data.is_empty() => Some(Cow::Borrowed(&st.data)),
        _ => None,
    }
}

impl Assembler {
    /// Assemble into an object file (an assembler made with `relocatable`).
    pub fn assemble_object(&mut self, name: &str) -> Result<ObjectFile, AsmError> {
        if !self.t.relocatable {
            return Err(AsmError::new(
                "this assembler makes images: create it with relocatable=True",
            ));
        }
        self.passes()?;
        let mut o = ObjectFile::new(self.enc.name(), 0, 0, name);
        // relocatable sections in order of appearance, then their indexes (1-based)
        let mut order: Vec<Arc<str>> = Vec::new();
        let mut secs: HashMap<Arc<str>, u32> = HashMap::new();
        let mut content: HashMap<Arc<str>, Vec<u8>> = HashMap::new();
        let mut code: HashMap<Arc<str>, u32> = HashMap::new();
        // absolute sections: address -> (byte, section, is code)
        let mut abs_mem: BTreeMap<i64, (u8, Arc<str>, bool)> = BTreeMap::new();
        let mut note = |s: &Arc<str>, order: &mut Vec<Arc<str>>| {
            if !secs.contains_key(s) {
                secs.insert(s.clone(), 0);
                order.push(s.clone());
            }
        };
        for st in &self.stmts {
            let insn = st.kind == Kind::Insn;
            let Some(data) = stmt_bytes(st) else {
                if let Some(s) = &st.section {
                    note(s, &mut order);
                }
                continue;
            };
            let Some(sec) = &st.section else {
                for (i, &b) in data.iter().enumerate() {
                    abs_mem.insert(st.addr + i as i64, (b, st.seckey.clone(), insn));
                }
                continue;
            };
            note(sec, &mut order);
            let buf = content.entry(sec.clone()).or_default();
            let start = usize::try_from(st.addr)
                .map_err(|_| AsmError::new("negative address").at(&st.at))?;
            let end = start + data.len();
            if buf.len() < end {
                buf.resize(end, 0);
            }
            buf[start..end].copy_from_slice(&data);
            if insn {
                *code.entry(sec.clone()).or_default() += data.len() as u32;
                if is_nobits(sec) {
                    return Err(AsmError::new(format!(
                        "instruction in {sec}, which holds only zeros"
                    ))
                    .at(&st.at));
                }
            } else if is_nobits(sec) && data.iter().any(|&b| b != 0) {
                return Err(AsmError::new(format!("{sec} holds only zeros")).at(&st.at));
            }
        }
        // sizes come from the location counters (a section can end in .space)
        let mut size: HashMap<Arc<str>, i64> = HashMap::new();
        for st in &self.stmts {
            if let Some(sec) = &st.section {
                let end = st.addr
                    + if st.kind == Kind::Insn {
                        st.size
                    } else {
                        st.data.len() as i64
                    };
                let s = size.entry(sec.clone()).or_insert(0);
                *s = (*s).max(end);
            }
        }
        for sec in &order {
            let nb = is_nobits(sec);
            let mut data = content.remove(sec).unwrap_or_default();
            let want = usize::try_from(size.get(sec).copied().unwrap_or(0)).unwrap_or(0);
            if data.len() < want {
                data.resize(want, 0);
            }
            o.sections.push(Section {
                name: sec.to_string(),
                flags: if nb { obj::SEC_NOBITS } else { 0 },
                addr: 0,
                size: u32_of(data.len() as i64, "section size")?,
                align: u32_of(self.sec_align.get(sec).copied().unwrap_or(1), "alignment")?,
                data: if nb { Vec::new() } else { data },
                code: code.get(sec).copied().unwrap_or(0),
            });
            secs.insert(sec.clone(), o.sections.len() as u32);
        }
        // absolute sections: one per contiguous run of bytes
        let mut abs_index: BTreeMap<i64, u32> = BTreeMap::new();
        let mut run: Option<(i64, Vec<u8>, Arc<str>, u32)> = None;
        let mut runs = Vec::new();
        for (&a, (b, key, is_code)) in &abs_mem {
            let fresh = match &run {
                None => true,
                Some((start, bytes, k, _)) => a != start + bytes.len() as i64 || key != k,
            };
            if fresh && let Some(r) = run.take() {
                runs.push(r);
            }
            let r = run.get_or_insert_with(|| (a, Vec::new(), key.clone(), 0));
            r.1.push(*b);
            r.3 += u32::from(*is_code);
        }
        runs.extend(run);
        for (addr, bytes, key, code) in runs {
            o.sections.push(Section {
                name: key.to_string(),
                flags: obj::SEC_ABS,
                addr: u32_of(addr, "address")?,
                size: bytes.len() as u32,
                align: 1,
                data: bytes,
                code,
            });
            abs_index.insert(addr, o.sections.len() as u32);
        }
        // symbols
        let mut syms: HashMap<String, u32> = HashMap::new();
        fn add(
            o: &mut ObjectFile,
            syms: &mut HashMap<String, u32>,
            name: &str,
            section: u32,
            value: i64,
            flags: u32,
        ) {
            syms.insert(name.to_string(), o.symbols.len() as u32);
            o.symbols.push(Symbol {
                name: name.to_string(),
                section,
                value: value as u32,
                flags,
            });
        }
        for sec in &order {
            add(&mut o, &mut syms, sec, secs[sec], 0, obj::SYM_SECTION);
        }
        let mut exported: HashSet<&str> = if self.globals.is_empty() {
            self.stmts
                .iter()
                .filter(|st| st.kind == Kind::Label && st.toplevel)
                .map(|st| st.label.as_str())
                .collect()
        } else {
            self.globals.iter().map(String::as_str).collect()
        };
        exported.retain(|n| !self.locals.contains(*n));
        for name in &self.globals_order {
            if !self.t.defined.contains(name) {
                return Err(AsmError::new(format!(
                    ".global {name}, but {name} isn't defined here (no need to declare external symbols)"
                )));
            }
        }
        let flags = |name: &str| {
            (if exported.contains(name) {
                obj::SYM_GLOBAL
            } else {
                0
            }) | (if self.t.far.contains(name) {
                obj::SYM_FAR
            } else {
                0
            })
        };
        let abs_place = |o: &ObjectFile, a: i64| {
            for (k, sec) in o.sections.iter().enumerate() {
                if sec.absolute() && sec.addr as i64 <= a && a <= sec.addr as i64 + sec.size as i64
                {
                    return (k as u32 + 1, a - sec.addr as i64);
                }
            }
            (obj::ABS, a)
        };
        for st in &self.stmts {
            if st.kind == Kind::Label {
                let v = self.t.symbols.get(&st.label).unwrap_or(0);
                let (section, value) = match &st.section {
                    None => abs_place(&o, v),
                    Some(sec) => (secs[sec], v),
                };
                add(
                    &mut o,
                    &mut syms,
                    &st.label,
                    section,
                    value,
                    flags(&st.label),
                );
            } else if st.kind == Kind::Dir && st.name == ".equ" {
                let Some(id) = st.ops.first().and_then(|o| o.first()).and_then(|t| t.id()) else {
                    continue;
                };
                let name = mangle(id, st.scope.as_deref());
                if let Some(v) = self.t.symbols.get(&name) {
                    let f = if self.globals.contains(&name) {
                        flags(&name)
                    } else {
                        flags(&name) & !obj::SYM_GLOBAL
                    };
                    add(&mut o, &mut syms, &name, obj::ABS, v, f);
                } else if self.globals.contains(&name) {
                    let Some((v, base)) = self.t.equ_rel.get(&name) else {
                        continue;
                    };
                    if let Base::Ext(_) = base {
                        return Err(AsmError::new(format!(
                            "can't export {name}: it's an external symbol plus a constant"
                        ))
                        .at(&st.at));
                    }
                    let sec = self
                        .t
                        .base_section(base)
                        .and_then(|s| secs.get(&s).copied())
                        .ok_or_else(|| AsmError::new(format!("can't export {name}")).at(&st.at))?;
                    let value = self.t.base_offset(base) + v;
                    add(&mut o, &mut syms, &name, sec, value, flags(&name));
                }
            }
        }
        let mut relocs = Vec::new();
        for st in &self.stmts {
            for fx in &st.relocs {
                let (sec, offset) = match &st.section {
                    None => {
                        let Some((&k, &sec)) = abs_index.range(..=fx.offset).next_back() else {
                            return Err(AsmError::new("relocation outside the absolute sections")
                                .at(&st.at));
                        };
                        (sec, fx.offset - k)
                    }
                    Some(s) => (secs[s], fx.offset),
                };
                let symbol = match &fx.base {
                    None => {
                        if !syms.contains_key("*ABS*") {
                            add(&mut o, &mut syms, "*ABS*", obj::ABS, 0, 0);
                        }
                        syms["*ABS*"]
                    }
                    Some(Base::Sec(s)) => syms[&**s],
                    Some(Base::Label(name) | Base::Ext(name)) => {
                        if !syms.contains_key(name) {
                            let far = if self.t.far.contains(name) {
                                obj::SYM_FAR
                            } else {
                                0
                            };
                            add(
                                &mut o,
                                &mut syms,
                                name,
                                obj::UNDEF,
                                0,
                                obj::SYM_GLOBAL | far,
                            );
                        }
                        syms[name]
                    }
                };
                let addend = i32::try_from(fx.addend).map_err(|_| {
                    AsmError::new(format!("relocation addend {} out of range", fx.addend))
                        .at(&st.at)
                })?;
                relocs.push(Reloc {
                    section: sec,
                    offset: u32_of(offset, "offset")?,
                    kind: fx.kind,
                    symbol,
                    addend,
                });
                // the field holds nothing until the linker fills it in
                let target = &mut o.sections[sec as usize - 1];
                if !target.nobits() {
                    let n = obj::reloc_size(fx.kind);
                    let start = (offset as usize).min(target.data.len());
                    let end = (offset as usize + n).min(target.data.len());
                    target.data.splice(start..end, std::iter::repeat_n(0, n));
                }
            }
        }
        o.relocs = relocs;
        Ok(o)
    }
}
