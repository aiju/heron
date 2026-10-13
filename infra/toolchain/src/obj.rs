//! Object files, executables and libraries (archives of object files).
//! All three formats are little-endian.
//!
//! Object file / executable:
//!
//! ```text
//! "TMO1"
//! u32 flags          1 = executable (every section placed, no relocations)
//! u32 isa            string: "v1a", "v1b"
//! u32 entry          start address (executables; 0 = the reset vector)
//! u32 nsections, nsymbols, nrelocs, strtab size
//! sections   nsections x {u32 name, u32 flags, u32 addr, u32 size, u32 align, u32 code}
//! symbols    nsymbols  x {u32 name, u32 section, u32 value, u32 flags}
//! relocs     nrelocs   x {u32 section, u32 offset, u32 kind, u32 symbol, s32 addend}
//! strtab     NUL-terminated names; offset 0 is the empty string
//! data       the contents of every section without NOBITS, in section order
//! ```
//!
//! A section is either absolute (placed at `addr`) or relocatable (the
//! linker picks the address; `addr` is 0). `code` counts the bytes of
//! instructions in it, for statistics. A symbol's `section` is 1-based, 0
//! for undefined (an external reference) and ABS for an absolute value;
//! `value` is the offset in the section. A relocation's `symbol` is an
//! index into the symbol table.
//!
//! Archive:
//!
//! ```text
//! "TMA1", u32 count, count x {u32 name length, name, u32 size, object file}
//! ```

use std::collections::HashMap;
use std::fmt;

pub const MAGIC: &[u8; 4] = b"TMO1";
pub const AR_MAGIC: &[u8; 4] = b"TMA1";

/// File flags: an executable.
pub const EXEC: u32 = 1;

/// Section flags: at a fixed address.
pub const SEC_ABS: u32 = 1;
/// Section flags: zero-filled, no contents in the file (.bss).
pub const SEC_NOBITS: u32 = 2;

/// A symbol's section: undefined (an external reference).
pub const UNDEF: u32 = 0;
/// A symbol's section: an absolute value.
pub const ABS: u32 = 0xFFFF_FFFF;

pub const SYM_GLOBAL: u32 = 1;
/// May lie anywhere: references use 32-bit forms.
pub const SYM_FAR: u32 = 2;
/// Stands for the start of its section.
pub const SYM_SECTION: u32 = 4;

// Relocation kinds. S = the symbol's address, A = the addend, P = the
// address of the field being patched.
/// 32 bits (two parcels, or a data word): S + A
pub const ABS32: u32 = 1;
/// 16 bits of data: S + A in -32768..65535
pub const ABS16: u32 = 2;
/// 16 bits the CPU sign-extends: S + A in -32768..32767
pub const ABS16S: u32 = 3;
/// 16 bits, PC-relative: S + A - P in -32768..32767
pub const PC16: u32 = 4;
/// 16 bits, PC-relative in parcels: (S + A - P) / 2, even, ±64 KB
pub const PC16H: u32 = 5;

pub fn reloc_name(kind: u32) -> Option<&'static str> {
    Some(match kind {
        ABS32 => "abs32",
        ABS16 => "abs16",
        ABS16S => "abs16s",
        PC16 => "pc16",
        PC16H => "pc16h",
        _ => return None,
    })
}

pub fn reloc_size(kind: u32) -> usize {
    if kind == ABS32 { 4 } else { 2 }
}

/// A file that isn't a valid object file or library.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ObjError(pub String);

impl fmt::Display for ObjError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for ObjError {}

fn s32(v: i64) -> i64 {
    v as u32 as i32 as i64
}

/// The bytes to store for a relocation, or why the value doesn't fit.
pub fn reloc_value(kind: u32, s: i64, a: i64, p: i64) -> Result<Vec<u8>, String> {
    let v = s + a;
    let u = v as u32;
    match kind {
        ABS32 => Ok(u.to_le_bytes().to_vec()),
        ABS16 => {
            if !((-32768..=32767).contains(&s32(v)) || u <= 0xFFFF) {
                return Err(format!("{u:#x} doesn't fit in 16 bits"));
            }
            Ok((u as u16).to_le_bytes().to_vec())
        }
        ABS16S => {
            if !(-32768..=32767).contains(&s32(v)) {
                return Err(format!(
                    "{u:#x} is out of reach of 16-bit addresses (0-0x7FFF)"
                ));
            }
            Ok((u as u16).to_le_bytes().to_vec())
        }
        PC16 | PC16H => {
            let off = s32(v - p);
            if kind == PC16 {
                if !(-32768..=32767).contains(&off) {
                    return Err(format!("{u:#x} is {off:+} bytes away, more than ±32 KB"));
                }
                return Ok((off as u16).to_le_bytes().to_vec());
            }
            if off & 1 != 0 {
                return Err(format!("{u:#x} is at an odd address"));
            }
            if !(-65536..=65534).contains(&off) {
                return Err(format!("{u:#x} is {off:+} bytes away, more than ±64 KB"));
            }
            Ok(((off >> 1) as u16).to_le_bytes().to_vec())
        }
        _ => Err(format!("unknown relocation kind {kind}")),
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Section {
    pub name: String,
    pub flags: u32,
    pub addr: u32,
    pub size: u32,
    pub align: u32,
    /// The contents (empty for NOBITS).
    pub data: Vec<u8>,
    /// Bytes of instructions.
    pub code: u32,
}

impl Section {
    pub fn absolute(&self) -> bool {
        self.flags & SEC_ABS != 0
    }

    pub fn nobits(&self) -> bool {
        self.flags & SEC_NOBITS != 0
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Symbol {
    pub name: String,
    /// 1-based section index, UNDEF or ABS.
    pub section: u32,
    pub value: u32,
    pub flags: u32,
}

impl Symbol {
    pub fn is_global(&self) -> bool {
        self.flags & SYM_GLOBAL != 0
    }

    pub fn defined(&self) -> bool {
        self.section != UNDEF
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Reloc {
    /// 1-based section index.
    pub section: u32,
    pub offset: u32,
    pub kind: u32,
    /// Index into the symbol table.
    pub symbol: u32,
    pub addend: i32,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ObjectFile {
    pub isa: String,
    pub flags: u32,
    pub entry: u32,
    pub sections: Vec<Section>,
    pub symbols: Vec<Symbol>,
    pub relocs: Vec<Reloc>,
    /// The file it came from, for messages.
    pub name: String,
}

/// Reads little-endian words; running out is a truncated file.
struct Reader<'a> {
    buf: &'a [u8],
    pos: usize,
}

impl Reader<'_> {
    fn bytes(&mut self, n: usize) -> Option<&[u8]> {
        let b = self.buf.get(self.pos..self.pos.checked_add(n)?)?;
        self.pos += n;
        Some(b)
    }

    fn u32(&mut self) -> Option<u32> {
        Some(u32::from_le_bytes(self.bytes(4)?.try_into().ok()?))
    }
}

impl ObjectFile {
    pub fn new(isa: &str, flags: u32, entry: u32, name: &str) -> ObjectFile {
        ObjectFile {
            isa: isa.into(),
            flags,
            entry,
            sections: Vec::new(),
            symbols: Vec::new(),
            relocs: Vec::new(),
            name: name.into(),
        }
    }

    pub fn executable(&self) -> bool {
        self.flags & EXEC != 0
    }

    pub fn to_bytes(&self) -> Vec<u8> {
        let mut strtab = vec![0u8];
        let mut offsets: HashMap<String, u32> = HashMap::from([(String::new(), 0)]);
        let mut s = |name: &str, strtab: &mut Vec<u8>| -> u32 {
            if let Some(&off) = offsets.get(name) {
                return off;
            }
            let off = strtab.len() as u32;
            strtab.extend_from_slice(name.as_bytes());
            strtab.push(0);
            offsets.insert(name.to_string(), off);
            off
        };
        // the names go in in this order: the ISA, sections, symbols
        let isa = s(self.isa.as_str(), &mut strtab);
        let mut secs = Vec::new();
        for x in &self.sections {
            for v in [
                s(x.name.as_str(), &mut strtab),
                x.flags,
                x.addr,
                x.size,
                x.align,
                x.code,
            ] {
                secs.extend_from_slice(&v.to_le_bytes());
            }
        }
        let mut syms = Vec::new();
        for x in &self.symbols {
            for v in [s(x.name.as_str(), &mut strtab), x.section, x.value, x.flags] {
                syms.extend_from_slice(&v.to_le_bytes());
            }
        }
        let mut out = MAGIC.to_vec();
        let head = [
            self.flags,
            isa,
            self.entry,
            self.sections.len() as u32,
            self.symbols.len() as u32,
            self.relocs.len() as u32,
            strtab.len() as u32,
        ];
        for v in head {
            out.extend_from_slice(&v.to_le_bytes());
        }
        out.extend(secs);
        out.extend(syms);
        for r in &self.relocs {
            for v in [r.section, r.offset, r.kind, r.symbol] {
                out.extend_from_slice(&v.to_le_bytes());
            }
            out.extend_from_slice(&r.addend.to_le_bytes());
        }
        out.extend(strtab);
        for x in &self.sections {
            if !x.nobits() {
                out.extend_from_slice(&x.data);
            }
        }
        out
    }

    pub fn from_bytes(buf: &[u8], name: &str) -> Result<ObjectFile, ObjError> {
        if buf.get(..4) != Some(MAGIC) {
            return Err(ObjError(format!("{name}: not an object file")));
        }
        let truncated = || ObjError(format!("{name}: truncated object file"));
        let mut r = Reader { buf, pos: 4 };
        let mut head = [0u32; 7];
        for h in &mut head {
            *h = r.u32().ok_or_else(truncated)?;
        }
        let [flags, isa, entry, ns, nsym, nrel, nstr] = head;
        let mut raw_secs = Vec::new();
        for _ in 0..ns {
            let mut v = [0u32; 6];
            for x in &mut v {
                *x = r.u32().ok_or_else(truncated)?;
            }
            raw_secs.push(v);
        }
        let mut raw_syms = Vec::new();
        for _ in 0..nsym {
            let mut v = [0u32; 4];
            for x in &mut v {
                *x = r.u32().ok_or_else(truncated)?;
            }
            raw_syms.push(v);
        }
        let mut relocs = Vec::new();
        for _ in 0..nrel {
            let mut v = [0u32; 5];
            for x in &mut v {
                *x = r.u32().ok_or_else(truncated)?;
            }
            relocs.push(Reloc {
                section: v[0],
                offset: v[1],
                kind: v[2],
                symbol: v[3],
                addend: v[4] as i32,
            });
        }
        let strtab = r.bytes(nstr as usize).ok_or_else(truncated)?.to_vec();
        let string = |off: u32| -> Result<String, ObjError> {
            let rest = strtab.get(off as usize..).unwrap_or(&[]);
            let end = rest.iter().position(|&b| b == 0);
            let bad = || ObjError(format!("{name}: bad string table"));
            String::from_utf8(rest[..end.ok_or_else(bad)?].to_vec()).map_err(|_| bad())
        };
        let mut o = ObjectFile::new(&string(isa)?, flags, entry, name);
        for [nm, fl, addr, size, align, code] in raw_secs {
            let mut sec = Section {
                name: string(nm)?,
                flags: fl,
                addr,
                size,
                align,
                data: Vec::new(),
                code,
            };
            if !sec.nobits() {
                sec.data = r.bytes(size as usize).ok_or_else(truncated)?.to_vec();
            }
            o.sections.push(sec);
        }
        for [nm, section, value, flags] in raw_syms {
            o.symbols.push(Symbol {
                name: string(nm)?,
                section,
                value,
                flags,
            });
        }
        for rl in &relocs {
            let in_section = |rl: &Reloc| {
                let size = o.sections[rl.section as usize - 1].size as u64;
                rl.offset as u64 + reloc_size(rl.kind) as u64 <= size
            };
            if !(1 <= rl.section && rl.section <= ns)
                || rl.symbol >= nsym
                || reloc_name(rl.kind).is_none()
                || !in_section(rl)
            {
                return Err(ObjError(format!("{name}: bad relocation")));
            }
        }
        o.relocs = relocs;
        Ok(o)
    }
}

/// An archive of object files: [(member name, object file)].
pub fn archive_bytes(members: &[(String, ObjectFile)]) -> Vec<u8> {
    let members: Vec<(String, Vec<u8>)> = members
        .iter()
        .map(|(n, o)| (n.clone(), o.to_bytes()))
        .collect();
    archive_of(&members)
}

/// An archive of object files already in bytes: [(member name, bytes)].
pub fn archive_of(members: &[(String, Vec<u8>)]) -> Vec<u8> {
    let mut out = AR_MAGIC.to_vec();
    out.extend_from_slice(&(members.len() as u32).to_le_bytes());
    for (name, data) in members {
        out.extend_from_slice(&(name.len() as u32).to_le_bytes());
        out.extend_from_slice(name.as_bytes());
        out.extend_from_slice(&(data.len() as u32).to_le_bytes());
        out.extend_from_slice(data);
    }
    out
}

/// The members of an archive; `path` names it in messages.
pub fn read_archive(buf: &[u8], path: &str) -> Result<Vec<(String, ObjectFile)>, ObjError> {
    if buf.get(..4) != Some(AR_MAGIC) {
        return Err(ObjError(format!("{path}: not a library")));
    }
    let truncated = || ObjError(format!("{path}: truncated library"));
    let mut r = Reader { buf, pos: 4 };
    let n = r.u32().ok_or_else(truncated)?;
    let mut out = Vec::new();
    for _ in 0..n {
        let ln = r.u32().ok_or_else(truncated)?;
        let name = String::from_utf8(r.bytes(ln as usize).ok_or_else(truncated)?.to_vec())
            .map_err(|_| truncated())?;
        let size = r.u32().ok_or_else(truncated)?;
        let data = r.bytes(size as usize).ok_or_else(truncated)?;
        out.push((
            name.clone(),
            ObjectFile::from_bytes(data, &format!("{path}({name})"))?,
        ));
    }
    Ok(out)
}
